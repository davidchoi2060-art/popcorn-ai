"""Commerce guest ownership on a caller connection; no transaction or engine ownership.

The opaque cookie, stable guest identity and public context UUID have different
roles. Existing development member sessions and visitor keys are not credentials.
"""
from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text

from . import commerce_contract as c

COOKIE = '__Host-popcorn_commerce_owner'
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


class OwnerError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


@dataclass(frozen=True)
class OwnerPolicy:
    origin: str
    ttl_seconds: int
    enabled: bool
    secure: bool

    def __post_init__(self):
        try:
            origin = urlsplit(self.origin)
            port = origin.port
            valid = (type(self.origin) is str and self.origin.isascii()
                     and origin.scheme == 'https' and origin.hostname
                     and origin.username is None and origin.password is None
                     and not origin.path and not origin.query and not origin.fragment
                     and self.origin == 'https://' + origin.netloc.lower()
                     and not any(ch.isspace() for ch in self.origin)
                     and (port is None or 0 < port < 65536))
            if (not valid or self.enabled is not True or self.secure is not True
                    or type(self.ttl_seconds) is not int
                    or not 0 < self.ttl_seconds <= c.MAX_INTEGER):
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise OwnerError(503, 'owner_configuration_unready') from None

    @classmethod
    def from_mapping(cls, values):
        try:
            ttl = values['COMMERCE_OWNER_TTL_SECONDS']
            if type(ttl) is not str or not re.fullmatch(r'[1-9][0-9]{0,18}', ttl):
                raise ValueError()
            return cls(origin=values['COMMERCE_OWNER_ORIGIN'], ttl_seconds=int(ttl),
                       enabled=values['COMMERCE_OWNER_ENABLED'] in ('1', 'true'),
                       secure=values['COMMERCE_OWNER_SECURE'] in ('1', 'true'))
        except (KeyError, TypeError, ValueError):
            raise OwnerError(503, 'owner_configuration_unready') from None


@dataclass(frozen=True)
class OwnerContext:
    context_id: str
    owner_scope: str
    owner_identity: dict
    expires_at: int

    def public(self):
        return dict(state='confirmed', binding_id=self.context_id)


def expected_binding(value):
    if value is None:
        return None
    try:
        return c.uuid_text(value)
    except c.CommerceError:
        raise OwnerError(422, 'invalid_expected_binding') from None


def credential_digest(credential):
    if type(credential) is not str or not _TOKEN.fullmatch(credential):
        raise OwnerError(401, 'owner_context_lost')
    return hashlib.sha256(('commerce_owner_v1:' + credential).encode('ascii')).hexdigest()


def _sql(conn, tag, statement, params=None):
    return conn.execute(text('/*commerce_owner:' + tag + '*/ ' + statement), params or {})


def ensure_ready(conn):
    # Query all required columns even for an anonymous GET: missing schema is
    # unavailable, never a successful empty/unconfirmed response.
    _sql(conn, 'ready', '''SELECT context_id,owner_scope,owner_identity,credential_hash,
        expires_at,revoked_at,created_at FROM commerce_owner_contexts WHERE false''')


def database_now(conn):
    value = _sql(conn, 'clock',
                 'SELECT floor(extract(epoch FROM clock_timestamp()))::bigint').scalar_one()
    try:
        return c.integer(value)
    except c.CommerceError:
        raise OwnerError(503, 'owner_context_unavailable') from None


def lookup_context(conn, credential, *, expected_binding_id, now):
    expected = expected_binding(expected_binding_id)
    if credential is None:
        if expected is not None:
            raise OwnerError(401, 'owner_context_lost')
        return None
    digest = credential_digest(credential)
    row = _sql(conn, 'lookup', '''SELECT context_id,owner_scope,owner_identity,credential_hash,
        expires_at,revoked_at,created_at FROM commerce_owner_contexts
        WHERE credential_hash=:credential_hash''', {'credential_hash': digest}).mappings().first()
    if row is None or row['revoked_at'] is not None:
        raise OwnerError(401, 'owner_context_lost')
    try:
        expiry, created = c.integer(row['expires_at']), c.integer(row['created_at'])
        now = c.integer(now)
        binding = c.uuid_text(str(row['context_id']))
        owner = c.owner_identity(row['owner_identity'])
        if (created > now or row['owner_scope'] != c.fingerprint(owner)
                or not secrets.compare_digest(row['credential_hash'], digest)):
            raise OwnerError(503, 'owner_context_unavailable')
    except (c.CommerceError, KeyError, TypeError):
        raise OwnerError(503, 'owner_context_unavailable') from None
    if expiry <= now:
        raise OwnerError(401, 'owner_context_lost')
    # No verified issuer/session adapter exists here. A stored member label
    # or a development member cookie cannot supply that missing verification.
    if owner['kind'] != 'guest':
        raise OwnerError(401, 'verified_member_adapter_unready')
    if expected is not None and expected != binding:
        raise OwnerError(409, 'owner_context_changed')
    return OwnerContext(binding, row['owner_scope'], owner, expiry)


def create_guest(conn, policy, *, now):
    """Prepare inserts only; caller must commit and verify a subsequent read."""
    if not conn.in_transaction():
        raise OwnerError(503, 'owner_transaction_required')
    try:
        now = c.integer(now)
        expires = c.integer(now + policy.ttl_seconds)
    except c.CommerceError:
        raise OwnerError(503, 'owner_configuration_unready') from None
    credential = secrets.token_urlsafe(32)
    digest = credential_digest(credential)
    stable_hash = secrets.token_hex(32)
    user_id = _sql(conn, 'insert_user',
                   'INSERT INTO users DEFAULT VALUES RETURNING user_id').scalar_one()
    owner = c.owner_identity(dict(kind='guest', user_id=user_id, owner_hash=stable_hash))
    context = OwnerContext(str(uuid4()), c.fingerprint(owner), owner, expires)
    _sql(conn, 'insert_context', '''INSERT INTO commerce_owner_contexts
        (context_id,owner_scope,owner_identity,credential_hash,expires_at,created_at)
        VALUES (CAST(:context_id AS uuid),:owner_scope,CAST(:owner_identity AS jsonb),
                :credential_hash,:expires_at,:created_at)''',
         dict(context_id=context.context_id, owner_scope=context.owner_scope,
              owner_identity=json.dumps(owner, sort_keys=True, separators=(',', ':')),
              credential_hash=digest, expires_at=expires, created_at=now))
    return context, credential
