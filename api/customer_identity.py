"""C1 pure server identity contract; no issuer, database, token or session issuance.

Only a future trusted server verifier may call the private principal constructor
AFTER actual verification. Its in-process seal is a type boundary, not signature
verification or a sandbox against arbitrary Python code. Explicit mapping/session
inputs must come from trusted persisted readers, never request dictionaries.
RuntimeIssuerVerifier remains unavailable; positive fixtures live only in tests.
"""
from dataclasses import dataclass, field
import re
from typing import Protocol
from uuid import UUID

AUTH_VERSION = 2
MAX_BIGINT = 9223372036854775807
_DECIMAL = re.compile(r'[1-9][0-9]{0,18}\Z')
_SEAL = object()


class IdentityError(ValueError):
    """Typed error without subject, email, registration or credential values."""
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


def _fail(status, code):
    raise IdentityError(status, code)


def positive_bigint(value):
    if type(value) is not int or not 0 < value <= MAX_BIGINT:
        _fail(422, 'invalid_identity_integer')
    return value


def decimal_id(value):
    """Strict public decimal string to native int; no Number/float coercion."""
    if type(value) is not str or not _DECIMAL.fullmatch(value):
        _fail(422, 'invalid_identity_decimal')
    return positive_bigint(int(value))


def wire_id(value):
    return str(positive_bigint(value))


def _epoch(value):
    if type(value) is not int or not 0 <= value <= MAX_BIGINT:
        _fail(422, 'invalid_identity_time')
    return value


def _opaque(value):
    # Preserve the exact opaque subject: no strip, lower, email or numeric cast.
    if type(value) is not str or not value or '\x00' in value:
        _fail(422, 'invalid_identity_text')
    try:
        value.encode('utf-8')
    except UnicodeError:
        _fail(422, 'invalid_identity_text')
    return value


def _optional(value):
    return None if value is None else _opaque(value)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail(422, 'invalid_identity_context')
    return value


@dataclass(frozen=True, slots=True, repr=False)
class IssuerRegistration:
    """Immutable trusted registration input; not client provider selection."""
    issuer_key: str
    issuer: str
    registration_ref: str
    verification_method: str
    via: str

    def __post_init__(self):
        for value in (self.issuer_key, self.issuer, self.registration_ref, self.verification_method):
            _opaque(value)
        if type(self.via) is not str or self.via not in ('kakao', 'naver', 'google', 'email'):
            _fail(422, 'invalid_identity_provider')


@dataclass(frozen=True, slots=True, repr=False)
class OptionalProfile:
    nickname: str | None = None
    email: str | None = None

    def __post_init__(self):
        _optional(self.nickname)
        _optional(self.email)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class VerifiedPrincipal:
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str
    via: str
    optional_profile: OptionalProfile
    _seal: object = field(compare=False)

    def __init__(self, *args, **kwargs):
        _fail(401, 'server_verified_principal_required')

    @classmethod
    def _from_server_verifier(cls, registration, *, subject, verified_at, optional_profile=None):
        if type(registration) is not IssuerRegistration:
            _fail(401, 'server_registration_required')
        profile = OptionalProfile() if optional_profile is None else optional_profile
        if type(profile) is not OptionalProfile:
            _fail(401, 'server_verified_principal_required')
        value = object.__new__(cls)
        fields = dict(issuer_key=registration.issuer_key, issuer=registration.issuer,
                      subject=_opaque(subject), verified_at=_epoch(verified_at),
                      verification_method=registration.verification_method,
                      registration_ref=registration.registration_ref, via=registration.via,
                      optional_profile=profile, _seal=_SEAL)
        for name, item in fields.items(): object.__setattr__(value, name, item)
        return value


class PrincipalVerifier(Protocol):
    def verify(self, server_proof: object) -> VerifiedPrincipal: ...


class RuntimeIssuerVerifier:
    """No configured verifier exists in C1. No fixture or flag fallback."""
    def verify(self, server_proof: object) -> VerifiedPrincipal:
        _fail(503, 'auth_unavailable')


@dataclass(frozen=True, slots=True, repr=False)
class CanonicalMember:
    member_id: int
    auth_subject: str
    principal_revision: int
    status: str
    nickname: str
    email: str | None = None

    def __post_init__(self):
        positive_bigint(self.member_id)
        positive_bigint(self.principal_revision)
        _uuid(self.auth_subject)
        _opaque(self.status)
        _opaque(self.nickname)
        _optional(self.email)


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedIdentityMapping:
    """Explicit trusted persisted mapping + provenance. No automatic linking."""
    identity_id: int
    member: CanonicalMember
    issuer_key: str
    issuer: str
    subject: str
    verified_at: int
    verification_method: str
    registration_ref: str
    revoked_at: int | None = None

    def __post_init__(self):
        positive_bigint(self.identity_id)
        if type(self.member) is not CanonicalMember:
            _fail(422, 'invalid_identity_mapping')
        for value in (self.issuer_key, self.issuer, self.subject,
                      self.verification_method, self.registration_ref): _opaque(value)
        _epoch(self.verified_at)
        if self.revoked_at is not None: _epoch(self.revoked_at)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class VerifiedMember:
    member: CanonicalMember
    identity_id: int
    principal: VerifiedPrincipal
    _seal: object = field(compare=False)

    def __init__(self, *args, **kwargs):
        _fail(401, 'verified_mapping_required')

    def stable_owner(self):
        _require_member(self)
        return dict(kind='member', member_id=self.member.member_id,
                    auth_subject=self.member.auth_subject)


def _require_principal(principal):
    if type(principal) is not VerifiedPrincipal or getattr(principal, '_seal', None) is not _SEAL:
        _fail(401, 'server_verified_principal_required')


def _require_member(member):
    if type(member) is not VerifiedMember or getattr(member, '_seal', None) is not _SEAL:
        _fail(401, 'verified_mapping_required')
    _require_principal(member.principal)


def resolve_identity(principal, mappings, *, now):
    """Resolve exact registration-scoped subject; email is never a lookup key."""
    _require_principal(principal)
    _epoch(now)
    if principal.verified_at > now:
        _fail(401, 'verification_provenance_mismatch')
    if type(mappings) not in (list, tuple) or any(type(m) is not VerifiedIdentityMapping for m in mappings):
        _fail(503, 'identity_mapping_unavailable')
    matches = [m for m in mappings if (m.issuer_key, m.subject)==(principal.issuer_key, principal.subject)]
    if not matches:
        _fail(409, 'identity_unlinked')
    if len(matches) != 1:
        _fail(503, 'identity_mapping_conflict')
    mapping = matches[0]
    if ((mapping.issuer, mapping.verification_method, mapping.registration_ref)
            != (principal.issuer, principal.verification_method, principal.registration_ref)
            or mapping.verified_at > now):
        _fail(401, 'verification_provenance_mismatch')
    if mapping.revoked_at is not None:
        _fail(401, 'identity_revoked')
    if mapping.member.status != 'active':
        _fail(401, 'member_inactive')
    value = object.__new__(VerifiedMember)
    for name, item in dict(member=mapping.member, identity_id=mapping.identity_id,
                           principal=principal, _seal=_SEAL).items():
        object.__setattr__(value, name, item)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class SessionContext:
    """Verified persisted session metadata only. Contains no cookie/token."""
    member_id: int
    verified_identity_id: int
    issued_auth_revision: int
    session_context_id: str
    issued_at: int
    expires_at: int
    revoked_at: int | None = None

    def __post_init__(self):
        for value in (self.member_id, self.verified_identity_id, self.issued_auth_revision):
            positive_bigint(value)
        _uuid(self.session_context_id)
        _epoch(self.issued_at)
        _epoch(self.expires_at)
        if self.expires_at <= self.issued_at: _fail(422, 'invalid_identity_time')
        if self.revoked_at is not None: _epoch(self.revoked_at)


def auth_context(member, session, *, now, expected_context=None):
    """Pure validation of CURRENT trusted inputs, to call before query and emit.

    C4 must reload cookie/session/mapping/member state at those boundaries. This
    function cannot establish persistence, cookie ownership or live revocation.
    """
    _require_member(member)
    _epoch(now)
    if type(session) is not SessionContext:
        _fail(401, 'verified_session_required')
    canonical = member.member
    if (session.revoked_at is not None or session.expires_at <= now
            or session.issued_at > now or session.issued_at < member.principal.verified_at):
        _fail(401, 'unauthenticated')
    if (session.member_id, session.verified_identity_id) != (canonical.member_id, member.identity_id):
        _fail(401, 'session_identity_mismatch')
    if session.issued_auth_revision != canonical.principal_revision:
        _fail(401, 'principal_revision_changed')
    if session.session_context_id == canonical.auth_subject:
        _fail(401, 'session_identity_mismatch')
    if expected_context is not None:
        try: _uuid(expected_context)
        except IdentityError: _fail(409, 'auth_context_changed')
        if expected_context != session.session_context_id:
            _fail(409, 'auth_context_changed')
    return dict(member_id=wire_id(canonical.member_id), session_context_id=session.session_context_id,
                principal_revision=wire_id(canonical.principal_revision))


def authenticated_payload(member, session, *, now, expected_context=None):
    context = auth_context(member, session, now=now, expected_context=expected_context)
    canonical = member.member
    return dict(auth_version=AUTH_VERSION, phase='authenticated', authenticated=True,
                member=dict(member_id=wire_id(canonical.member_id), nickname=canonical.nickname,
                            email=canonical.email, via=member.principal.via), auth_context=context)


def profile_payload(member, session, *, now, expected_context):
    # Private reads require an actual expected context; None cannot omit it.
    if expected_context is None: _fail(409, 'auth_context_changed')
    context = auth_context(member, session, now=now, expected_context=expected_context)
    canonical = member.member
    return dict(auth_version=AUTH_VERSION, auth_context=context,
                profile=dict(member_id=wire_id(canonical.member_id), nickname=canonical.nickname,
                             email=canonical.email))


def unavailable_payload():
    return dict(auth_version=AUTH_VERSION, phase='unavailable', authenticated=False,
                member=None, auth_context=None, reason='auth_unavailable')


def signed_out_payload():
    return dict(auth_version=AUTH_VERSION, phase='signed-out', authenticated=False,
                member=None, auth_context=None)
