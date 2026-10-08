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
