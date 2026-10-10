"""New R1 adapter/native-handler tests only; no completed suite imports."""
from dataclasses import replace
import hashlib
import importlib
import socket
import sys
import types
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_GUARD = False
_FAKE_DB = None


def _deny_live_io(event, args):
    if not _GUARD:
        return
    fallback = getattr(socket, '_fallback_socketpair', None)
    if (event == 'socket.connect' and fallback is not None
            and sys._getframe(1).f_code is fallback.__code__
            and args[1][0] in ('127.0.0.1', '::1')):
        return
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise AssertionError('R1 live IO forbidden')
    if event == 'import' and args:
        name = args[0]
        if name == 'api.db' and sys.modules.get(name) is not _FAKE_DB:
            raise AssertionError('R1 real DB import forbidden')
        if name in ('api.main', 'api.auth') or name.split('.')[0] in ('psycopg', 'psycopg2', 'pg8000'):
            raise AssertionError('R1 live main/auth/driver import forbidden')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace('\\', '/').lower().rstrip("'").endswith('/.env'):
            raise AssertionError('R1 secret access forbidden')


class NoDatabase:
    def __init__(self):
        self.calls = []

    def connect(self):
        self.calls.append('connect')
        raise AssertionError('R1 legacy DB connect forbidden')

    def begin(self):
        self.calls.append('begin')
        raise AssertionError('R1 legacy DB write forbidden')


sys.addaudithook(_deny_live_io)
sys.dont_write_bytecode = True
database = NoDatabase()
_GUARD = True
try:
    identity = importlib.import_module('api.customer_identity')
    store = importlib.import_module('api.customer_auth_store')
    auth = importlib.import_module('api.customer_auth')
    _FAKE_DB = types.ModuleType('api.db')
    _FAKE_DB.engine = database
    previous_db = sys.modules.get('api.db')
    sys.modules['api.db'] = _FAKE_DB
    try:
        profile = importlib.import_module('api.my_account')
    finally:
        if previous_db is None:
            sys.modules.pop('api.db', None)
        else:
            sys.modules['api.db'] = previous_db
finally:
    _GUARD = False

TOKEN = 'a' * 64
DIGEST = hashlib.sha256(TOKEN.encode('ascii')).hexdigest()
CONTEXT = '11111111-1111-4111-8111-111111111111'
OTHER_CONTEXT = '33333333-3333-4333-8333-333333333333'
SUBJECT = '22222222-2222-4222-8222-222222222222'


def member(**changes):
    return store.StoredMember(**dict(dict(member_id=101, auth_subject=SUBJECT,
        auth_revision=1, status='active', nickname='회원', email=None), **changes))


def record(**changes):
    provenance = store.StoredProvenance('fixture-app', 'https://issuer.example.invalid',
        'server-subject', 100, 'fixture-verified', 'fixture-registration')
    mapping = store.StoredIdentity(17, 101, provenance.issuer_key, provenance.issuer,
        provenance.subject, 90, provenance.verification_method, provenance.registration_ref)
    session = store.StoredSession(101, 17, 1, CONTEXT, 100, 200)
    return store.StoredSessionRead(**dict(dict(credential_hash=DIGEST, member=member(),
        identities=(mapping,), session=session, provenance=provenance, now=120), **changes))


class FixtureReads:
    """Explicit test port; no SQL/credential issuance/revoke capabilities."""
    def __init__(self):
        self.schema = True
        self.members_ready = True
        self.session_row = record()
        self.member_row = member()
        self.lookups = []
        self.member_reads = []
        self.on_session = None
        self.on_member = None
        self.session_error = None
        self.member_error = None

    def schema_ready(self):
        return self.schema

    def member_schema_ready(self):
        return self.members_ready

    def read_current_session(self, digest):
        self.lookups.append(digest)
        if self.on_session:
            self.on_session(len(self.lookups))
        if self.session_error:
            raise self.session_error
        return self.session_row

    def read_current_member(self, member_id):
        self.member_reads.append(member_id)
        if self.on_member:
            self.on_member()
        if self.member_error:
            raise self.member_error
        return self.member_row


class FixtureTrustedPrincipal:
    """Pre-established server fixture authority, independent of supplied rows.

    This is not a real verifier/persisted proof. Restoration recognizes only
    the pre-established fixture, never arbitrary row shape/provider/email.
    """
    def __init__(self):
        self.enabled = True
        self.calls = []
        self.evidence = record().provenance
        registration = identity.IssuerRegistration(self.evidence.issuer_key, self.evidence.issuer,
            self.evidence.registration_ref, self.evidence.verification_method, 'kakao')
        self.principal = identity.VerifiedPrincipal._from_server_verifier(registration,
            subject=self.evidence.subject, verified_at=self.evidence.verified_at)
        self.on_restore = None
        self.error = None

    def ready(self):
        return self.enabled

    def restore_verified_principal(self, evidence):
        self.calls.append(evidence)
        if self.on_restore:
            self.on_restore()
        if self.error:
            raise self.error
        if type(evidence) is not store.StoredProvenance or evidence != self.evidence:
            raise ValueError('fixture authority does not recognize evidence')
        return self.principal


class StoreConnectionTests(unittest.TestCase):
    def setUp(self):
        global _GUARD
        _GUARD = True
        database.calls.clear()
        self.reads = FixtureReads()
        self.trusted = FixtureTrustedPrincipal()
        self.resolver = auth.create_stored_read_resolver(self.reads, self.trusted)
        self.reader = profile.create_stored_profile_reader(self.reads)
        self.app = FastAPI()
        self.app.middleware('http')(auth.create_member_middleware(self.resolver))
        self.app.include_router(auth.create_auth_router(self.resolver))
        self.app.include_router(profile.router)
        self.app.dependency_overrides[profile.get_profile_repository] = lambda: self.reader
        self.client = TestClient(self.app)

    def tearDown(self):
        global _GUARD
        try:
            self.client.close()
            self.assertEqual(database.calls, [])
            self.assertIsNone(auth.current_member())
        finally:
            _GUARD = False

    def get(self, path='/api/my/profile'):
        return self.client.get(path, headers={'Cookie': auth.COOKIE + '=' + TOKEN,
            'X-Popcorn-Auth-Context': CONTEXT})

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json(), {'detail': {'code': code}})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('set-cookie', response.headers)

    def test_explicit_storage_mapping_and_hash_only_native_query(self):
        result = self.get('/api/my/profile?member_id=202&auth_revision=9&schema_ready=true&provider=dev')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'auth_version': 2,
            'auth_context': {'member_id': '101', 'session_context_id': CONTEXT, 'principal_revision': '1'},
            'profile': {'member_id': '101', 'nickname': '회원', 'email': None}})
        self.assertEqual(self.reads.member_reads, [101])
        self.assertEqual(self.reads.lookups, [DIGEST] * 4)
        self.assertNotIn(TOKEN, self.reads.lookups)
        self.assertEqual(len(self.trusted.calls), 4)
        self.assertEqual(result.headers['cache-control'], 'no-store')

    def test_adapter_maps_storage_names_without_coercing_bigint(self):
        maximum = identity.MAX_BIGINT
        row = record(member=member(member_id=maximum, auth_revision=maximum),
            identities=(replace(record().identities[0], member_id=maximum),),
            session=replace(record().session, member_id=maximum, issued_auth_revision=maximum))
        self.reads.session_row = row
        self.reads.member_row = row.member
        result = self.get()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['auth_context']['principal_revision'], str(maximum))
        self.assertEqual(result.json()['profile']['member_id'], str(maximum))
        self.assertEqual(self.reads.member_reads, [maximum])

    def test_runtime_defaults_stay_unavailable_even_with_client_readiness_fields(self):
        self.assertFalse(auth.RUNTIME_RESOLVER.repository.schema_ready())
        self.assertFalse(auth.RUNTIME_RESOLVER.issuer.ready())
        self.assertFalse(profile.get_profile_repository().ready())
        app = FastAPI()
        app.middleware('http')(auth.member_middleware)
        app.include_router(auth.router)
        app.include_router(profile.router)
        with TestClient(app) as client:
            for path in ('/api/auth/me?ready=true', '/api/my/profile?schema_ready=true'):
                self.error(client.get(path, headers={'Cookie': auth.COOKIE+'='+TOKEN}), 503, 'auth_unavailable')

    def test_schema_alone_does_not_authorize_without_trusted_port(self):
        self.trusted.enabled = False
        self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.reads.lookups, [])
        self.assertEqual(self.trusted.calls, [])

    def test_bool_or_dict_cannot_supply_server_ports(self):
        for input_value in (True, {'ready': True, 'schema_ready': True}):
            resolver = auth.create_stored_read_resolver(self.reads, input_value)
            with self.assertRaises(HTTPException) as caught:
                resolver.resolve(TOKEN)
            self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(store.SessionReadAdapter(True, True, auth.PersistedSessionSnapshot).schema_ready())
        self.assertFalse(profile.create_stored_profile_reader({'member_schema_ready': True}).ready())

    def test_non_boolean_readiness_does_not_open_adapter(self):
        for value in (1, 'true', None):
            self.reads.schema = value
            self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.reads.lookups, [])

    def test_dict_or_legacy_rawsid_envelope_is_not_promoted(self):
        for value in ({'session_id': TOKEN, 'member_id': 101, 'ready': True},
                      {'credential_hash': DIGEST, 'member': member(), 'verified': True}):
            self.reads.session_row = value
            self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.trusted.calls, [])
        self.assertEqual(self.reads.member_reads, [])

    def test_well_shaped_rows_cannot_mint_unsealed_or_dict_principal(self):
        for value in (True, {'issuer_key': 'fixture-app', 'subject': 'server-subject'},
                      object.__new__(identity.VerifiedPrincipal)):
            self.trusted.principal = value
            self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.reads.member_reads, [])

    def test_wrong_restored_provenance_or_bool_timestamp_is_rejected(self):
        registration = identity.IssuerRegistration('other-app', 'https://issuer.example.invalid',
            'other-registration', 'fixture-verified', 'kakao')
        self.trusted.principal = identity.VerifiedPrincipal._from_server_verifier(registration,
            subject='server-subject', verified_at=100)
        self.error(self.get(), 503, 'auth_unavailable')
        self.trusted = FixtureTrustedPrincipal()
        adapter = store.SessionReadAdapter(self.reads, self.trusted, auth.PersistedSessionSnapshot)
        self.reads.session_row = replace(record(), provenance=replace(record().provenance, verified_at=True))
        with self.assertRaises(HTTPException):
            adapter.read_verified_session(DIGEST)

    def test_source_or_trusted_restore_errors_are_sanitized(self):
        self.reads.session_error = HTTPException(200, {'secret': 'fixture-private-detail'})
        self.error(self.get(), 503, 'auth_unavailable')
        self.reads.session_error = None
        self.trusted.error = RuntimeError('fixture-private-detail')
        self.error(self.get(), 503, 'auth_unavailable')

    def test_structurally_invalid_revision_context_time_fk_and_tuple_are503(self):
        for row in (record(member=member(auth_revision=True)),
                    record(member=member(auth_revision=None)),
                    record(session=replace(record().session, auth_context_id=TOKEN)),
                    record(now=True), record(identities=list(record().identities)),
                    record(identities=(replace(record().identities[0], member_id=202),))):
            self.reads.session_row = row
            self.error(self.get(), 503, 'auth_unavailable')

    def test_missing_stored_session_stays401(self):
        self.reads.session_row = None
        self.error(self.get(), 401, 'unauthenticated')

    def test_hash_mismatch_is_c4_authentication_error_not_row_upgrade(self):
        self.reads.session_row = record(credential_hash='b'*64)
        self.error(self.get(), 401, 'unauthenticated')

    def test_current_expiry_session_revoke_and_revision_keep_c4_401_codes(self):
        for row, code in ((record(now=200), 'unauthenticated'),
                          (record(session=replace(record().session, revoked_at=120)), 'unauthenticated'),
                          (record(member=member(auth_revision=2)), 'principal_revision_changed')):
            self.reads.session_row = row
            self.error(self.get(), 401, code)
        self.assertEqual(self.reads.member_reads, [])

    def test_current_identity_revoke_inactive_and_unlinked_keep_c1_semantics(self):
        for row, status, code in ((record(identities=(replace(record().identities[0], revoked_at=110),)), 401, 'identity_revoked'),
                                 (record(member=member(status='blocked')), 401, 'member_inactive'),
                                 (record(identities=()), 409, 'identity_unlinked')):
            self.reads.session_row = row
            self.error(self.get(), status, code)

    def test_fresh_adapter_session_revoke_during_member_read_discards_data(self):
        self.reads.on_member = lambda: setattr(self.reads, 'session_row',
            record(session=replace(record().session, revoked_at=120)))
        self.error(self.get(), 401, 'unauthenticated')
        self.assertEqual(self.reads.lookups, [DIGEST]*4)
        self.assertEqual(self.reads.member_reads, [101])

    def test_fresh_adapter_revision_during_member_read_discards_data(self):
        self.reads.on_member = lambda: setattr(self.reads, 'session_row', record(member=member(auth_revision=2)))
        self.error(self.get(), 401, 'principal_revision_changed')
        self.assertEqual(self.reads.member_reads, [101])

    def test_fresh_adapter_context_during_member_read_discards_data(self):
        self.reads.on_member = lambda: setattr(self.reads, 'session_row',
            record(session=replace(record().session, auth_context_id=OTHER_CONTEXT)))
        self.error(self.get(), 409, 'auth_context_changed')

    def test_readiness_lost_during_source_read_or_restoration_is503(self):
        self.reads.on_session = lambda count: setattr(self.reads, 'schema', False)
        self.error(self.get(), 503, 'auth_unavailable')
        self.reads.schema = True
        self.reads.on_session = None
        self.trusted.on_restore = lambda: setattr(self.trusted, 'enabled', False)
        self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.reads.member_reads, [])

    def test_member_readiness_lost_during_final_session_restore_is503(self):
        self.trusted.on_restore = lambda: setattr(self.reads, 'members_ready', False) if len(self.trusted.calls)==4 else None
        self.error(self.get(), 503, 'auth_unavailable')
        self.assertEqual(self.reads.member_reads, [101])

    def test_member_port_missing_foreign_row_and_read_exception_do_not_emit(self):
        self.reads.member_row = None
        self.error(self.get(), 401, 'unauthenticated')
        self.reads.member_row = member(member_id=202)
        self.error(self.get(), 409, 'auth_context_changed')
        self.reads.member_error = RuntimeError('fixture-private-detail')
        self.error(self.get(), 503, 'auth_unavailable')

    def test_latest_c4_contact_fields_win_over_stale_member_port_row(self):
        self.reads.on_member = lambda: setattr(self.reads, 'session_row',
            record(member=member(nickname='현재 회원', email='current@example.invalid')))
        response = self.get()
        self.assertEqual(response.json()['profile'], {'member_id': '101', 'nickname': '현재 회원', 'email': 'current@example.invalid'})

    def test_native_me_and_profile_share_explicit_adapters_without_cookie_issuance(self):
        response = self.get('/api/auth/me')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['auth_context']['session_context_id'], CONTEXT)
        self.assertEqual(response.json()['member']['member_id'], '101')
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.reads.member_reads, [])

    def test_revoke_policy_unapproved_even_in_positive_read_fixture(self):
        self.assertFalse(store.RUNTIME_REVOCATION_PORT.ready())
        with self.assertRaises(HTTPException) as caught:
            store.RUNTIME_REVOCATION_PORT.revoke_verified_session(DIGEST)
        self.assertEqual(caught.exception.status_code, 503)
        response = self.client.post('/api/auth/logout', headers={'Cookie': auth.COOKIE+'='+TOKEN})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': {'code': 'auth_unavailable'}})
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
        self.assertEqual(self.reads.lookups, [])
        self.assertEqual(self.get().status_code, 200)  # No persisted revoke claimed.

    def test_issuer_login_and_non_profile_private_operations_stay_closed(self):
        response = self.client.post('/api/auth/login', json={'email': 'fixture@example.invalid', 'provider': 'dev'})
        self.error(response, 503, 'auth_unavailable')
        self.error(self.get('/api/my/account'), 503, 'auth_unavailable')
        self.assertEqual(self.reads.member_reads, [])


if __name__ == '__main__':
    unittest.main()
