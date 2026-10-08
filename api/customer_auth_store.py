"""R1 stored-read contracts and explicit server adapters; CODE/MOCK only.

No SQL, schema, timestamp conversion, issuer verification or revoke-success
policy is implemented. Record shapes never establish verified provenance.
The principal port must independently restore C1 server-verified provenance.
Runtime ports stay unavailable, and only explicit server fixtures can read.
"""
from dataclasses import dataclass
import re
from typing import Callable, NoReturn, Protocol

from fastapi import HTTPException

from . import customer_identity as identity

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Expires": "0"}


def _unavailable():
    return HTTPException(503, detail={"code": "auth_unavailable"}, headers=dict(_NO_STORE))


def _ready(port, name):
    try:
        return getattr(port, name)() is True
    except Exception:
        return False


def _read(call, *args):
    try:
        return call(*args)
    except Exception:
        raise _unavailable() from None


@dataclass(frozen=True, slots=True, repr=False)
class StoredMember:
    member_id: int
    auth_subject: str
    auth_revision: int
    status: str
    nickname: str
    email: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class StoredIdentity:
    identity_id: int
    member_id: int
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str
    revoked_at: int | None = None


@dataclass(frozen=True, slots=True, repr=False)
class StoredSession:
    member_id: int
    verified_identity_id: int
    issued_auth_revision: int
    auth_context_id: str
    issued_at: int
    expires_at: int
    revoked_at: int | None = None


@dataclass(frozen=True, slots=True, repr=False)
class StoredProvenance:
    """Untrusted metadata for a trusted restoration port, not a proof/seal."""
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str


@dataclass(frozen=True, slots=True, repr=False)
class StoredSessionRead:
    """Fresh server read envelope; field names do not choose SQL/storage."""
    credential_hash: str
    member: StoredMember
    identities: tuple[StoredIdentity, ...]
    session: StoredSession
    provenance: StoredProvenance
    now: int


class StoredReadPort(Protocol):
    def schema_ready(self) -> bool: ...
    def member_schema_ready(self) -> bool: ...
    def read_current_session(self, credential_hash: str) -> StoredSessionRead | None: ...
    def read_current_member(self, member_id: int) -> StoredMember | None: ...


class TrustedPrincipalPort(Protocol):
    """Server-owned restoration after independent trusted issuance evidence.

    Neither a client dict/bool nor StoredProvenance alone may mint a principal.
    Actual persistence/restoration trust depends on an accepted C2/I1 contract.
    """
    def ready(self) -> bool: ...
    def restore_verified_principal(self, provenance: StoredProvenance) -> identity.VerifiedPrincipal: ...


class UnavailableStoredReadPort:
    def schema_ready(self):
        return False

    def member_schema_ready(self):
        return False

    def read_current_session(self, credential_hash):
        raise _unavailable()

    def read_current_member(self, member_id):
        raise _unavailable()


class UnavailableTrustedPrincipalPort:
    def ready(self):
        return False

    def restore_verified_principal(self, provenance):
        raise _unavailable()


class UnapprovedRevocationPort:
    """No approved writer/result/idempotency contract. Never claims success.

    R1 does not call any persisted writer from logout. A future writer must
    replace this boundary only under its separately accepted policy/contract.
    """
    def ready(self):
        return False

    def revoke_verified_session(self, credential_hash: str) -> NoReturn:
        raise _unavailable()


RUNTIME_READ_PORT = UnavailableStoredReadPort()
RUNTIME_PRINCIPAL_PORT = UnavailableTrustedPrincipalPort()
RUNTIME_REVOCATION_PORT = UnapprovedRevocationPort()


def canonical_member(row):
    if type(row) is not StoredMember:
        raise _unavailable()
    # Explicit C2 proposed storage name -> accepted C1 DTO. No defaults/coercion.
    return identity.CanonicalMember(member_id=row.member_id, auth_subject=row.auth_subject,
        principal_revision=row.auth_revision, status=row.status, nickname=row.nickname, email=row.email)


class SessionReadAdapter:
    def __init__(self, source: StoredReadPort, principal: TrustedPrincipalPort,
                 snapshot_factory: Callable):
        self.source, self.principal, self.snapshot_factory = source, principal, snapshot_factory

    def schema_ready(self):
        return _ready(self.source, "schema_ready") and _ready(self.principal, "ready")

    def read_verified_session(self, credential_hash):
        if not self.schema_ready():
            raise _unavailable()
        if type(credential_hash) is not str or not _DIGEST.fullmatch(credential_hash):
            raise _unavailable()
        row = _read(self.source.read_current_session, credential_hash)
        if not self.schema_ready():
            raise _unavailable()
        if row is None:
            return None
        if (type(row) is not StoredSessionRead or type(row.member) is not StoredMember
                or type(row.session) is not StoredSession or type(row.provenance) is not StoredProvenance
                or type(row.identities) is not tuple
                or any(type(item) is not StoredIdentity for item in row.identities)
                or type(row.credential_hash) is not str or not _DIGEST.fullmatch(row.credential_hash)):
            raise _unavailable()
        try:
            member = canonical_member(row.member)
            mappings = []
            for item in row.identities:
                # No FK mismatch is normalized into the current member.
                if type(item.member_id) is not int or item.member_id != member.member_id:
                    raise _unavailable()
                mappings.append(identity.VerifiedIdentityMapping(identity_id=item.identity_id,
                    member=member, issuer_key=item.issuer_key, issuer=item.issuer, subject=item.subject,
                    verified_at=item.verified_at, verification_method=item.verification_method,
                    registration_ref=item.registration_ref, revoked_at=item.revoked_at))
            stored = row.session
            session = identity.SessionContext(member_id=stored.member_id,
                verified_identity_id=stored.verified_identity_id, issued_auth_revision=stored.issued_auth_revision,
                session_context_id=stored.auth_context_id, issued_at=stored.issued_at,
                expires_at=stored.expires_at, revoked_at=stored.revoked_at)
            if type(row.now) is not int or row.now < 0:
                raise _unavailable()
            # The source cannot mint a principal. Only an explicitly injected
            # server restoration port can return one; C1 seal is checked too.
            principal = _read(self.principal.restore_verified_principal, row.provenance)
            identity._require_principal(principal)
            fields = ("issuer_key", "issuer", "subject", "verified_at", "verification_method", "registration_ref")
            if any(type(getattr(principal, name)) is not type(getattr(row.provenance, name))
                   or getattr(principal, name) != getattr(row.provenance, name) for name in fields):
                raise _unavailable()
            if not self.schema_ready():
                raise _unavailable()
            # C4 owns current expiry/revocation/revision/credential/context
            # semantics, preserving its typed401/409 instead of remapping here.
            return self.snapshot_factory(credential_hash=row.credential_hash, principal=principal,
                mappings=tuple(mappings), session=session, now=row.now)
        except Exception:
            raise _unavailable() from None


class MemberReadAdapter:
    def __init__(self, source: StoredReadPort):
        self.source = source

    def ready(self):
        return _ready(self.source, "member_schema_ready")

    def read_member(self, member_id):
        if not self.ready():
            raise _unavailable()
        try:
            identity.positive_bigint(member_id)
        except identity.IdentityError:
            raise _unavailable() from None
        row = _read(self.source.read_current_member, member_id)
        if not self.ready():
            raise _unavailable()
        if row is None:
            return None
        try:
            return canonical_member(row)
        except Exception:
            raise _unavailable() from None


# V2 standalone consumers. Existing R1 definitions and runtime ports above are
# retained. These classes are never installed into the runtime HTTP factories.
from decimal import Decimal
from . import customer_auth_sql_read as q1
from . import customer_auth_provenance as p1


@dataclass(frozen=True, slots=True, repr=False)
class StoredIssuanceBindingV2:
    proof_ref: str
    credential_hash: str
    member_id: int
    verified_identity_id: int
    auth_context_id: str
    issued_auth_revision: int
    issued_at: int
    expires_at: int


@dataclass(frozen=True, slots=True, repr=False)
class StoredSessionReadV2:
    credential_hash: str
    member: StoredMember
    identities: tuple[StoredIdentity, ...]
    session: StoredSession
    provenance: StoredProvenance
    issuance_binding: StoredIssuanceBindingV2
    now: int
    observed_epoch_exact: Decimal


class StoredReadPortV2(Protocol):
    def schema_ready(self) -> bool: ...
    def member_schema_ready(self) -> bool: ...
    def read_current_session(self, credential_hash: str) -> StoredSessionReadV2 | None: ...
    def read_current_member(self, member_id: int) -> StoredMember | None: ...


class TrustedPrincipalPortV2(Protocol):
    def ready(self) -> bool: ...
    def restore_verified_principal(self, provenance: StoredProvenance, *,
                                   binding: StoredIssuanceBindingV2) -> identity.VerifiedPrincipal: ...


class I1PrincipalRestorationPortV2(Protocol):
    """Server internal, not an actual approved I1 implementation.

    I1 must approve the independent authority verification channel and trusted
    registration source. P1 result types, SQL metadata or a ready flag alone do
    not prove external verification. The original verification time must remain
    unchanged; via/optional profile must come from the approved I1 source.
    """
    def ready(self) -> bool: ...
    def restore_verified_principal(self, evidence: p1.VerifiedIssuanceEvidence) -> identity.VerifiedPrincipal: ...


class UnavailableI1PrincipalRestorationPortV2:
    def ready(self):
        return False

    def restore_verified_principal(self, evidence):
        raise _unavailable()


def _v2_read(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except Exception:
        raise _unavailable() from None


def _v2_text(value):
    if type(value) is not str or not value or '\x00' in value:
        raise _unavailable()
    value.encode('utf-8', 'strict')
    return value


def _v2_digest(value):
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise _unavailable()
    return value


def _v2_equal(left, right, names):
    return all(type(getattr(left, name)) is type(getattr(right, name))
               and getattr(left, name) == getattr(right, name) for name in names)


def _v2_inputs(provenance, binding):
    if type(provenance) is not StoredProvenance or type(binding) is not StoredIssuanceBindingV2:
        raise _unavailable()
    identity._uuid(binding.proof_ref)
    identity._uuid(binding.auth_context_id)
    _v2_digest(binding.credential_hash)
    for value in (binding.member_id, binding.verified_identity_id, binding.issued_auth_revision):
        identity.positive_bigint(value)
    for value in (binding.issued_at, binding.expires_at, provenance.verified_at):
        identity._epoch(value)
    for name in p1.PROVENANCE_FIELDS:
        if name != 'verified_at':
            _v2_text(getattr(provenance, name))
    if not provenance.verified_at <= binding.issued_at < binding.expires_at:
        raise _unavailable()
    # Explicit copies across distinct class identities, never cast/alias/asdict.
    pb = p1.IssuanceBinding(proof_ref=binding.proof_ref, credential_hash=binding.credential_hash,
        member_id=binding.member_id, verified_identity_id=binding.verified_identity_id,
        auth_context_id=binding.auth_context_id, issued_auth_revision=binding.issued_auth_revision,
        issued_at=binding.issued_at, expires_at=binding.expires_at)
    pp = p1.IssuanceProvenance(issuer_key=provenance.issuer_key, issuer=provenance.issuer,
        subject=provenance.subject, verified_at=provenance.verified_at,
        verification_method=provenance.verification_method, registration_ref=provenance.registration_ref)
    return pp, pb


def _v2_components(row, requested):
    if (type(row) is not StoredSessionReadV2 or type(row.member) is not StoredMember
            or type(row.session) is not StoredSession or type(row.provenance) is not StoredProvenance
            or type(row.identities) is not tuple or len(row.identities) != 1
            or any(type(item) is not StoredIdentity for item in row.identities)):
        raise _unavailable()
    _v2_digest(requested)
    if _v2_digest(row.credential_hash) != requested:
        raise _unavailable()
    pp, pb = _v2_inputs(row.provenance, row.issuance_binding)
    if (row.credential_hash != pb.credential_hash
            or not _v2_equal(row.session, pb, ('member_id', 'verified_identity_id', 'auth_context_id',
                                              'issued_auth_revision', 'issued_at', 'expires_at'))):
        raise _unavailable()
    exact = row.observed_epoch_exact
    if (type(exact) is not Decimal or not exact.is_finite() or not 0 <= exact <= identity.MAX_BIGINT
            or type(row.now) is not int or row.now != int(exact)):
        raise _unavailable()
    member = canonical_member(row.member)
    item = row.identities[0]
    if (type(item.member_id) is not int or item.member_id != member.member_id
            or row.session.member_id != member.member_id or item.identity_id != pb.verified_identity_id
            or not _v2_equal(item, pp, ('issuer_key', 'issuer', 'subject', 'verification_method', 'registration_ref'))):
        raise _unavailable()
    mapping = identity.VerifiedIdentityMapping(identity_id=item.identity_id, member=member,
        issuer_key=item.issuer_key, issuer=item.issuer, subject=item.subject, verified_at=item.verified_at,
        verification_method=item.verification_method, registration_ref=item.registration_ref, revoked_at=item.revoked_at)
    session = identity.SessionContext(member_id=row.session.member_id,
        verified_identity_id=row.session.verified_identity_id, issued_auth_revision=row.session.issued_auth_revision,
        session_context_id=row.session.auth_context_id, issued_at=row.session.issued_at,
        expires_at=row.session.expires_at, revoked_at=row.session.revoked_at)
    # No current expiry/revocation/status/revision/context judgment here.
    return (mapping,), session


class Q1ReadBridgeV2:
    def __init__(self, source: q1.SQLReadPort):
        self.source = source

    def schema_ready(self):
        return _ready(self.source, 'schema_ready')

    def member_schema_ready(self):
        return _ready(self.source, 'member_schema_ready')

    def _member(self, value):
        if type(value) is not q1.StoredMember:
            raise _unavailable()
        copied = StoredMember(member_id=value.member_id, auth_subject=value.auth_subject,
            auth_revision=value.auth_revision, status=value.status, nickname=value.nickname, email=value.email)
        canonical_member(copied)
        return copied

    def read_current_session(self, credential_hash):
        try:
            if not self.schema_ready():
                raise _unavailable()
            _v2_digest(credential_hash)
            value = _v2_read(self.source.read_current_session, credential_hash)
            if not self.schema_ready():
                raise _unavailable()
            if value is None:
                return None
            if (type(value) is not q1.SessionEnvelopeV2 or type(value.session) is not q1.StoredSession
                    or type(value.provenance) is not q1.StoredProvenance
                    or type(value.issuance_binding) is not q1.IssuanceBinding
                    or type(value.identities) is not tuple
                    or any(type(item) is not q1.StoredIdentity for item in value.identities)):
                raise _unavailable()
            m = self._member(value.member)
            identities = tuple(StoredIdentity(identity_id=i.identity_id, member_id=i.member_id,
                issuer_key=i.issuer_key, issuer=i.issuer, subject=i.subject, verified_at=i.verified_at,
                verification_method=i.verification_method, registration_ref=i.registration_ref,
                revoked_at=i.revoked_at) for i in value.identities)
            s, p, b = value.session, value.provenance, value.issuance_binding
            copied = StoredSessionReadV2(credential_hash=value.credential_hash, member=m, identities=identities,
                session=StoredSession(member_id=s.member_id, verified_identity_id=s.verified_identity_id,
                    issued_auth_revision=s.issued_auth_revision, auth_context_id=s.auth_context_id,
                    issued_at=s.issued_at, expires_at=s.expires_at, revoked_at=s.revoked_at),
                provenance=StoredProvenance(issuer_key=p.issuer_key, issuer=p.issuer, subject=p.subject,
                    verified_at=p.verified_at, verification_method=p.verification_method, registration_ref=p.registration_ref),
                issuance_binding=StoredIssuanceBindingV2(proof_ref=b.proof_ref, credential_hash=b.credential_hash,
                    member_id=b.member_id, verified_identity_id=b.verified_identity_id, auth_context_id=b.auth_context_id,
                    issued_auth_revision=b.issued_auth_revision, issued_at=b.issued_at, expires_at=b.expires_at),
                now=value.now, observed_epoch_exact=value.observed_epoch_exact)
            _v2_components(copied, credential_hash)
            return copied
        except Exception:
            raise _unavailable() from None

    def read_current_member(self, member_id):
        try:
            if not self.member_schema_ready():
                raise _unavailable()
            identity.positive_bigint(member_id)
            value = _v2_read(self.source.read_current_member, member_id)
            if not self.member_schema_ready():
                raise _unavailable()
            if value is None:
                return None
            copied = self._member(value)
            if copied.member_id != member_id:
                raise _unavailable()
            # Member-only data does not establish session/receipt freshness.
            return copied
        except Exception:
            raise _unavailable() from None


class P1PrincipalBridgeV2:
    def __init__(self, verifier: p1.IssuanceEvidenceVerifier,
                 restorer: I1PrincipalRestorationPortV2 | None = None, *, authority_ref: str):
        self.verifier = verifier
        self.restorer = UnavailableI1PrincipalRestorationPortV2() if restorer is None else restorer
        self.authority_ref = authority_ref

    def ready(self):
        try:
            _v2_text(self.authority_ref)
            return _ready(self.verifier, 'ready') and _ready(self.restorer, 'ready')
        except Exception:
            return False

    def restore_verified_principal(self, provenance, *, binding):
        try:
            if not self.ready():
                raise _unavailable()
            pp, pb = _v2_inputs(provenance, binding)
            evidence = _v2_read(self.verifier.verify_issuance, pp, binding=pb)
            if (not self.ready() or type(evidence) is not p1.VerifiedIssuanceEvidence
                    or type(evidence.binding) is not p1.IssuanceBinding
                    or type(evidence.provenance) is not p1.IssuanceProvenance
                    or type(evidence.authority_ref) is not str or evidence.authority_ref != self.authority_ref
                    or not _v2_equal(evidence.binding, pb, p1.BINDING_FIELDS)
                    or not _v2_equal(evidence.provenance, pp, p1.PROVENANCE_FIELDS)):
                raise _unavailable()
            principal = _v2_read(self.restorer.restore_verified_principal, evidence)
            identity._require_principal(principal)
            if not self.ready() or not _v2_equal(principal, pp, p1.PROVENANCE_FIELDS):
                raise _unavailable()
            return principal
        except Exception:
            raise _unavailable() from None


class SessionReadAdapterV2:
    """Fresh full chain per read; no full-binding comparison across C4 phases.

    Existing C4 resolution key excludes proof_ref and original event fields.
    C2/I1 immutable issuance bindings remain required. No request/global cache
    fills that gap, and no runtime factory installs this standalone adapter.
    """
    def __init__(self, source: StoredReadPortV2, principal: TrustedPrincipalPortV2,
                 snapshot_factory: Callable):
        self.source, self.principal, self.snapshot_factory = source, principal, snapshot_factory

    def schema_ready(self):
        return _ready(self.source, 'schema_ready') and _ready(self.principal, 'ready')

    def read_verified_session(self, credential_hash):
        try:
            if not self.schema_ready():
                raise _unavailable()
            _v2_digest(credential_hash)
            row = _v2_read(self.source.read_current_session, credential_hash)
            if not self.schema_ready():
                raise _unavailable()
            if row is None:
                return None
            mappings, session = _v2_components(row, credential_hash)
            principal = _v2_read(self.principal.restore_verified_principal, row.provenance,
                                 binding=row.issuance_binding)
            identity._require_principal(principal)
            if not self.schema_ready() or not _v2_equal(principal, row.provenance, p1.PROVENANCE_FIELDS):
                raise _unavailable()
            # Lazy type lookup avoids the store/C4 module import cycle. No app,
            # DB or HTTP route is created; only the accepted snapshot type.
            from .customer_auth import PersistedSessionSnapshot
            snapshot = self.snapshot_factory(credential_hash=row.credential_hash, principal=principal,
                mappings=mappings, session=session, now=row.now)
            if (type(snapshot) is not PersistedSessionSnapshot
                    or type(snapshot.credential_hash) is not str or snapshot.credential_hash != row.credential_hash
                    or type(snapshot.now) is not int or snapshot.now != row.now
                    or snapshot.principal is not principal or snapshot.mappings is not mappings
                    or snapshot.session is not session):
                raise _unavailable()
            return snapshot
        except Exception:
            raise _unavailable() from None

# V3 is paired with the separately versioned C4 phase consumer. V2's native
# five-field snapshot gate above and all runtime defaults remain unchanged.
class SessionReadAdapterV3(SessionReadAdapterV2):
    """Transfers the same-read validated binding8 and original provenance6.

    This adapter still requires the independent P1/I1 server ports. A typed
    carrier alone is not proof, and no runtime factory installs this adapter.
    """
    def read_verified_session(self, credential_hash):
        try:
            if not self.schema_ready():
                raise _unavailable()
            _v2_digest(credential_hash)
            row = _v2_read(self.source.read_current_session, credential_hash)
            if not self.schema_ready():
                raise _unavailable()
            if row is None:
                return None
            mappings, session = _v2_components(row, credential_hash)
            principal = _v2_read(self.principal.restore_verified_principal, row.provenance,
                                 binding=row.issuance_binding)
            identity._require_principal(principal)
            if not self.schema_ready() or not _v2_equal(principal, row.provenance, p1.PROVENANCE_FIELDS):
                raise _unavailable()
            from .customer_auth import (IssuanceIdentityV3, PersistedSessionSnapshotV3,
                                        _phase_match_issuance_v3)
            b, p = row.issuance_binding, row.provenance
            issuance = IssuanceIdentityV3(proof_ref=b.proof_ref, credential_hash=b.credential_hash,
                member_id=b.member_id, verified_identity_id=b.verified_identity_id,
                auth_context_id=b.auth_context_id, issued_auth_revision=b.issued_auth_revision,
                issued_at=b.issued_at, expires_at=b.expires_at, issuer_key=p.issuer_key,
                issuer=p.issuer, subject=p.subject, verified_at=p.verified_at,
                verification_method=p.verification_method, registration_ref=p.registration_ref)
            original_values = _phase_match_issuance_v3(issuance, principal, session, row.credential_hash)
            snapshot = self.snapshot_factory(credential_hash=row.credential_hash, principal=principal,
                mappings=mappings, session=session, now=row.now, issuance_identity=issuance)
            if (type(snapshot) is not PersistedSessionSnapshotV3
                    or type(snapshot.credential_hash) is not str or snapshot.credential_hash != row.credential_hash
                    or type(snapshot.now) is not int or snapshot.now != row.now
                    or snapshot.principal is not principal or snapshot.mappings is not mappings
                    or snapshot.session is not session or snapshot.issuance_identity is not issuance):
                raise _unavailable()
            if _phase_match_issuance_v3(snapshot.issuance_identity, snapshot.principal,
                    snapshot.session, snapshot.credential_hash) != original_values:
                raise _unavailable()
            # Current state401/context409 remain in C1/C4 after this source call.
            return snapshot
        except Exception:
            raise _unavailable() from None
