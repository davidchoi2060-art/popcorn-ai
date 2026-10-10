"""P1 standalone issuance-evidence comparison, D-C2-SESSION-PROOF-V1.

Only a SERVER-INJECTED, independently approved authority may supply receipts.
That port must check its actual receipt authenticity, validity and registration
source on each lookup; SQL cache rows, DTO types and ready flags are not proofs.
Selecting/verifying that authority, keys or providers belongs to future I1.

This module returns evidence comparison results, never C1 principals, member
authorization, cookies or sessions. It does not implement frozen R1's six-field
restore port. Binding consumption and principal restoration need separate V2
acceptance. There is no database, network, clock, configuration or runtime wiring.
"""
from dataclasses import dataclass
import re
from typing import Protocol
from uuid import UUID


CONTRACT_ID = 'D-C2-SESSION-PROOF-V1-20261007'
MAX_BIGINT = 9223372036854775807
BINDING_FIELDS = ('proof_ref', 'credential_hash', 'member_id', 'verified_identity_id',
                  'auth_context_id', 'issued_auth_revision', 'issued_at', 'expires_at')
PROVENANCE_FIELDS = ('issuer_key', 'issuer', 'subject', 'verified_at',
                     'verification_method', 'registration_ref')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class IssuanceUnavailable(ValueError):
    """Closed technical boundary; includes no input or authority exception data."""
    def __init__(self):
        self.status = 503
        self.code = 'auth_unavailable'
        super().__init__(self.code)


@dataclass(frozen=True, slots=True, repr=False)
class IssuanceBinding:
    """Eight untrusted server-read fields, not a bearer or an authorization."""
    proof_ref: str
    credential_hash: str
    member_id: int
    verified_identity_id: int
    auth_context_id: str
    issued_auth_revision: int
    issued_at: int
    expires_at: int


@dataclass(frozen=True, slots=True, repr=False)
class IssuanceProvenance:
    """Original issuance provenance; verified_at is not a GET observation time."""
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorityReceipt:
    """Port output shape; authenticity is the independent authority's duty."""
    binding: IssuanceBinding
    provenance: IssuanceProvenance
    authority_ref: str


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedIssuanceEvidence:
    """Immutable comparison result only; never accepted R1/C1 authorization."""
    binding: IssuanceBinding
    provenance: IssuanceProvenance
    authority_ref: str


class IndependentIssuanceAuthority(Protocol):
    """Approved server port, disjoint from untrusted SQL receipt metadata.

    ready is readiness, not verification. Each lookup must return ALL matching
    current independently verified receipts (zero/duplicates close P1), using
    the injected approved authority/registration source. The argument identifies
    an issuance only; it must never select a publisher, key or provider.
    """
    def ready(self) -> bool: ...
    def read_verified_issuance(self, proof_ref: str) -> tuple[AuthorityReceipt, ...]: ...


class UnavailableIssuanceAuthority:
    """Actual I1 authority is not configured or selected by P1."""
    def ready(self):
        return False

    def read_verified_issuance(self, proof_ref):
        raise IssuanceUnavailable()


def _opaque(value):
    if type(value) is not str or not value or '\x00' in value:
        raise IssuanceUnavailable()
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        raise IssuanceUnavailable() from None
    return value


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise IssuanceUnavailable()
    except (ValueError, TypeError, AttributeError):
        raise IssuanceUnavailable() from None
    return value


def _integer(value, minimum):
    if type(value) is not int or not minimum <= value <= MAX_BIGINT:
        raise IssuanceUnavailable()
    return value


def _binding(value):
    if type(value) is not IssuanceBinding:
        raise IssuanceUnavailable()
    _uuid(value.proof_ref)
    _uuid(value.auth_context_id)
    if type(value.credential_hash) is not str or not _DIGEST.fullmatch(value.credential_hash):
        raise IssuanceUnavailable()
    for name in ('member_id', 'verified_identity_id', 'issued_auth_revision'):
        _integer(getattr(value, name), 1)
    _integer(value.issued_at, 0)
    _integer(value.expires_at, 0)
    if value.expires_at <= value.issued_at:
        raise IssuanceUnavailable()
    # Copy immutable primitives before the independent lookup; keep no input row.
    return IssuanceBinding(**{name:getattr(value, name) for name in BINDING_FIELDS})


def _provenance(value):
    if type(value) is not IssuanceProvenance:
        raise IssuanceUnavailable()
    for name in PROVENANCE_FIELDS:
        if name != 'verified_at':
            _opaque(getattr(value, name))
    _integer(value.verified_at, 0)
    return IssuanceProvenance(**{name:getattr(value, name) for name in PROVENANCE_FIELDS})


def _issuance(binding, provenance):
    copied_binding, copied_provenance = _binding(binding), _provenance(provenance)
    if copied_provenance.verified_at > copied_binding.issued_at:
        raise IssuanceUnavailable()
    return copied_binding, copied_provenance


def _exact(left, right, names):
    return all(type(getattr(left, name)) is type(getattr(right, name))
               and getattr(left, name) == getattr(right, name) for name in names)


class IssuanceEvidenceVerifier:
    """Server construction only; source/ref cannot be selected by request data.

    authority_ref is an expected approved authority version from server-owned
    registration configuration. It is not supplied by SQL receipt metadata.
    Constructing a positive fixture port does not approve an actual I1 source.
    """
    def __init__(self, authority: IndependentIssuanceAuthority | None = None,
                 *, authority_ref: str | None = None):
        self._authority = UnavailableIssuanceAuthority() if authority is None else authority
        self._authority_ref = authority_ref

    def ready(self):
        try:
            _opaque(self._authority_ref)
            return self._authority.ready() is True
        except Exception:
            return False

    def verify_issuance(self, provenance: IssuanceProvenance, *, binding: IssuanceBinding):
        """Fresh exact-one lookup, then binding8/provenance6/ref comparison.

        Expiry, current member revisions and session revocation belong to the
        separately accepted current-state resolver. No clock or TTL is invented.
        This checks original issuance chronology and the authority receipt only.
        """
        try:
            expected_binding, expected_provenance = _issuance(binding, provenance)
        except Exception:
            raise IssuanceUnavailable() from None
        if not self.ready():
            raise IssuanceUnavailable()
        try:
            receipts = self._authority.read_verified_issuance(expected_binding.proof_ref)
        except Exception:
            raise IssuanceUnavailable() from None
        if not self.ready():
            raise IssuanceUnavailable()
        if type(receipts) is not tuple or len(receipts) != 1:
            raise IssuanceUnavailable()
        receipt = receipts[0]
        if type(receipt) is not AuthorityReceipt:
            raise IssuanceUnavailable()
        try:
            actual_binding, actual_provenance = _issuance(receipt.binding, receipt.provenance)
            _opaque(receipt.authority_ref)
            if (receipt.authority_ref != self._authority_ref
                    or not _exact(actual_binding, expected_binding, BINDING_FIELDS)
                    or not _exact(actual_provenance, expected_provenance, PROVENANCE_FIELDS)):
                raise IssuanceUnavailable()
            return VerifiedIssuanceEvidence(actual_binding, actual_provenance, receipt.authority_ref)
        except Exception:
            raise IssuanceUnavailable() from None


RUNTIME_VERIFIER = IssuanceEvidenceVerifier()
