"""Q1 standalone decoder. Injected fixtures only; no runtime or authority wiring.

Executor attestations are a server contract, not proof of live DB configuration.
SQL is a plan supplied to an injected executor; this module opens no connection.
Returned receipt/provenance data is untrusted until independent P1 verification.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from types import MappingProxyType
from typing import Protocol
import re
from uuid import UUID

MAX_BIGINT = 9223372036854775807
SCHEMA_CONTRACT = "D-C2-SESSION-PROOF-V1-20261007"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class SQLReadUnavailable(Exception):
    status_code = 503
    detail = MappingProxyType({"code": "auth_unavailable"})
    headers = MappingProxyType({"Cache-Control": "no-store", "Pragma": "no-cache", "Expires": "0"})

    def __init__(self):
        super().__init__("auth_unavailable")


@dataclass(frozen=True, slots=True)
class ReadRequirements:
    schema_contract: str = SCHEMA_CONTRACT
    isolation: str = "read committed"
    read_only: bool = True
    primary: bool = True
    fresh_statement: bool = True


@dataclass(frozen=True, slots=True, repr=False)
class StatementObservation:
    """Executor returns only after its short read transaction has closed.

    sequence is executor-local, strictly increasing across every observation.
    A fixture claiming primary/RC does not verify an actual driver or server.
    """
    sequence: int
    schema_contract: str
    isolation: str
    read_only: bool
    primary: bool
    transaction_closed: bool
    rows: tuple[Mapping, ...]


class ReadExecutor(Protocol):
    def ready(self, requirements: ReadRequirements) -> bool: ...
    def observe(self, query: str, parameters: Mapping, *,
                requirements: ReadRequirements) -> StatementObservation: ...


@dataclass(frozen=True, slots=True, repr=False)
class StoredMember:
    member_id: int
    auth_subject: str
    auth_revision: int
    status: str
    nickname: str
    email: str | None


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
    revoked_at: int | None


@dataclass(frozen=True, slots=True, repr=False)
class StoredSession:
    member_id: int
    verified_identity_id: int
    issued_auth_revision: int
    auth_context_id: str
    issued_at: int
    expires_at: int
    revoked_at: int | None


@dataclass(frozen=True, slots=True, repr=False)
class StoredProvenance:
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str


@dataclass(frozen=True, slots=True, repr=False)
class IssuanceBinding:
    proof_ref: str
    credential_hash: str
    member_id: int
    verified_identity_id: int
    auth_context_id: str
    issued_auth_revision: int
    issued_at: int
    expires_at: int


@dataclass(frozen=True, slots=True, repr=False)
class SessionEnvelopeV2:
    """Untrusted detached data; never a VerifiedPrincipal or auth resolution."""
    credential_hash: str
    member: StoredMember
    identities: tuple[StoredIdentity, ...]
    session: StoredSession
    provenance: StoredProvenance
    issuance_binding: IssuanceBinding
    now: int
    observed_epoch_exact: Decimal


SESSION_QUERY = """WITH observation_clock AS MATERIALIZED (
 SELECT statement_timestamp() AS observed_at,
 current_setting('transaction_isolation') AS isolation_level,
 current_setting('transaction_read_only') AS read_only
)
SELECT s.credential_hash,s.member_id,s.verified_identity_id,s.auth_context_id,
 s.issued_auth_revision,s.issued_at_epoch,s.expires_at_epoch,s.revoked_at_epoch,s.proof_ref,
 m.member_id AS canonical_member_id,m.auth_subject,m.auth_revision,m.status,m.nickname,m.email,
 i.identity_id,i.member_id AS identity_member_id,i.issuer_key,i.issuer,i.subject,
 i.verified_at_epoch AS mapping_verified_at_epoch,i.verification_method,i.registration_ref,
 i.revoked_at_epoch AS identity_revoked_at_epoch,
 r.proof_ref AS receipt_ref,r.credential_hash AS receipt_digest,
 r.member_id AS receipt_member_id,r.verified_identity_id AS receipt_identity_id,
 r.auth_context_id AS receipt_context_id,r.issued_auth_revision AS receipt_revision,
 r.issued_at_epoch AS receipt_issued_at,r.expires_at_epoch AS receipt_expires_at,
 r.issuer_key AS receipt_issuer_key,r.issuer AS receipt_issuer,r.subject AS receipt_subject,
 r.principal_verified_at_epoch,r.verification_method AS receipt_verification_method,
 r.registration_ref AS receipt_registration_ref,r.authority_ref,
 identity_count.exact_subject_count,EXTRACT(EPOCH FROM c.observed_at) AS observed_epoch_exact,
 c.isolation_level,c.read_only
FROM public.member_verified_sessions s CROSS JOIN observation_clock c
LEFT JOIN public.members m ON m.member_id=s.member_id
LEFT JOIN public.member_verified_identities i ON i.identity_id=s.verified_identity_id
LEFT JOIN public.member_session_issuance_receipts r ON r.proof_ref=s.proof_ref
LEFT JOIN LATERAL (
 SELECT count(*) AS exact_subject_count FROM public.member_verified_identities same_subject
 WHERE same_subject.issuer_key=i.issuer_key AND same_subject.subject=i.subject
) identity_count ON TRUE
WHERE s.credential_hash=:credential_hash"""

MEMBER_QUERY = """WITH observation_clock AS MATERIALIZED (
 SELECT statement_timestamp() AS observed_at,
 current_setting('transaction_isolation') AS isolation_level,
 current_setting('transaction_read_only') AS read_only
)
SELECT m.member_id,m.auth_subject,m.auth_revision,m.status,m.nickname,m.email,
 EXTRACT(EPOCH FROM c.observed_at) AS observed_epoch_exact,c.isolation_level,c.read_only
FROM public.members m CROSS JOIN observation_clock c WHERE m.member_id=:member_id"""


def _integer(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_BIGINT:
        raise SQLReadUnavailable()
    return value


def _optional_epoch(value):
    return None if value is None else _integer(value)


def _text(value):
    if type(value) is not str or not value or "\x00" in value:
        raise SQLReadUnavailable()
    value.encode("utf-8")
    return value


def _uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise SQLReadUnavailable()
    return value


def _digest(value):
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise SQLReadUnavailable()
    return value


def _clock(row):
    exact = row["observed_epoch_exact"]
    if type(exact) is not Decimal or not exact.is_finite() or not 0 <= exact <= MAX_BIGINT:
        raise SQLReadUnavailable()
    if row["isolation_level"] != "read committed" or row["read_only"] != "on":
        raise SQLReadUnavailable()
    # Current observation only: integer-event expiry/chronology comparisons
    # are equivalent at this bucket. No persisted event is rounded/coerced.
    return int(exact), exact


def _member(row, id_key):
    return StoredMember(_integer(row[id_key], positive=True), _uuid(row["auth_subject"]),
        _integer(row["auth_revision"], positive=True), _text(row["status"]),
        _text(row["nickname"]), None if row["email"] is None else _text(row["email"]))


def _session(row, requested):
    digest = _digest(row["credential_hash"])
    if digest != requested or _integer(row["exact_subject_count"], positive=True) != 1:
        raise SQLReadUnavailable()
    member = _member(row, "canonical_member_id")
    session = StoredSession(_integer(row["member_id"], positive=True),
        _integer(row["verified_identity_id"], positive=True),
        _integer(row["issued_auth_revision"], positive=True), _uuid(row["auth_context_id"]),
        _integer(row["issued_at_epoch"]), _integer(row["expires_at_epoch"]),
        _optional_epoch(row["revoked_at_epoch"]))
    mapping = StoredIdentity(_integer(row["identity_id"], positive=True),
        _integer(row["identity_member_id"], positive=True), _text(row["issuer_key"]),
        _text(row["issuer"]), _text(row["subject"]), _integer(row["mapping_verified_at_epoch"]),
        _text(row["verification_method"]), _text(row["registration_ref"]),
        _optional_epoch(row["identity_revoked_at_epoch"]))
    provenance = StoredProvenance(_text(row["receipt_issuer_key"]), _text(row["receipt_issuer"]),
        _text(row["receipt_subject"]), _integer(row["principal_verified_at_epoch"]),
        _text(row["receipt_verification_method"]), _text(row["receipt_registration_ref"]))
    binding = IssuanceBinding(_uuid(row["proof_ref"]), digest, session.member_id,
        session.verified_identity_id, session.auth_context_id, session.issued_auth_revision,
        session.issued_at, session.expires_at)
    receipt_binding = IssuanceBinding(_uuid(row["receipt_ref"]), _digest(row["receipt_digest"]),
        _integer(row["receipt_member_id"], positive=True), _integer(row["receipt_identity_id"], positive=True),
        _uuid(row["receipt_context_id"]), _integer(row["receipt_revision"], positive=True),
        _integer(row["receipt_issued_at"]), _integer(row["receipt_expires_at"]))
    _text(row["authority_ref"])  # Metadata cannot select a trusted issuer/key.
    if (binding != receipt_binding or member.member_id != session.member_id
            or mapping.member_id != session.member_id or mapping.identity_id != session.verified_identity_id
            or (mapping.issuer_key, mapping.issuer, mapping.subject, mapping.verification_method, mapping.registration_ref)
            != (provenance.issuer_key, provenance.issuer, provenance.subject, provenance.verification_method, provenance.registration_ref)
            or not provenance.verified_at <= session.issued_at < session.expires_at):
        raise SQLReadUnavailable()
    now, exact = _clock(row)
    # Current expiry/revoke/status/revision/context semantics belong to C1/C4.
    return SessionEnvelopeV2(digest, member, (mapping,), session, provenance, binding, now, exact)


class SQLReadPort:
    """Standalone Q1; not installed in R1 or any consumer/runtime factory."""
    def __init__(self, executor: ReadExecutor):
        self._executor = executor
        self._requirements = ReadRequirements()
        self._last_sequence = 0
        self._lock = Lock()

    def schema_ready(self):
        try:
            return self._executor.ready(self._requirements) is True
        except Exception:
            return False

    def member_schema_ready(self):
        return self.schema_ready()

    def _observe(self, query, parameters):
        if not self.schema_ready():
            raise SQLReadUnavailable()
        result = self._executor.observe(query, MappingProxyType(parameters), requirements=self._requirements)
        if (type(result) is not StatementObservation
                or _integer(result.sequence, positive=True) <= self._last_sequence):
            raise SQLReadUnavailable()
        # Consume sequence even if later decoding fails; replay stays rejected.
        self._last_sequence = result.sequence
        if (result.schema_contract != SCHEMA_CONTRACT or result.isolation != "read committed"
                or result.read_only is not True or result.primary is not True
                or result.transaction_closed is not True or type(result.rows) is not tuple
                or not self.schema_ready()):
            raise SQLReadUnavailable()
        if len(result.rows) > 1:
            raise SQLReadUnavailable()
        if not result.rows:
            return None
        if not isinstance(result.rows[0], Mapping):
            raise SQLReadUnavailable()
        return dict(result.rows[0])

    def read_current_session(self, credential_hash):
        with self._lock:
            try:
                digest = _digest(credential_hash)
                row = self._observe(SESSION_QUERY, {"credential_hash": digest})
                return None if row is None else _session(row, digest)
            except Exception:
                raise SQLReadUnavailable() from None

    def read_current_member(self, member_id):
        with self._lock:
            try:
                member_id = _integer(member_id, positive=True)
                row = self._observe(MEMBER_QUERY, {"member_id": member_id})
                if row is None:
                    return None
                _clock(row)
                member = _member(row, "member_id")
                if member.member_id != member_id:
                    raise SQLReadUnavailable()
                return member
            except Exception:
                raise SQLReadUnavailable() from None
