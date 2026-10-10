"""New standalone V3 phase fixtures; no actual I1, SQL, HTTP or runtime wiring."""
import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import unittest

from fastapi import HTTPException


def _deny_live(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system', 'sqlite3.connect'):
        raise AssertionError('V3 live IO forbidden')
    if event == 'import' and args:
        name = args[0]
        if any(name == n or name.startswith(n + '.') for n in
               ('api.db', 'api.main', 'api.my_account', 'sqlalchemy', 'psycopg',
                'psycopg2', 'httpx', 'requests')):
            raise AssertionError('V3 production/HTTP import forbidden')
        if name.startswith('test_') and name != 'test_customer_auth_phase_binding':
            raise AssertionError('V3 accepted suite import forbidden')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace('\\', '/').lower().rstrip("'").rsplit('/', 1)[-1] == '.env':
            raise AssertionError('V3 secret read forbidden')


sys.addaudithook(_deny_live)
from api import customer_auth as auth
from api import customer_auth_store as store
from api import customer_auth_sql_read as q1
from api import customer_auth_provenance as p1
from api import customer_identity as identity


SID = 'a' * 64
SID2 = 'b' * 64
DIGEST = hashlib.sha256(SID.encode('ascii')).hexdigest()
DIGEST2 = hashlib.sha256(SID2.encode('ascii')).hexdigest()
PROOF = '11111111-1111-4111-8111-111111111111'
CONTEXT = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
SUBJECT = '44444444-4444-4444-8444-444444444444'
AUTHORITY = 'offline-phase-authority-v1'


def envelope():
    member = q1.StoredMember(101, SUBJECT, 1, 'active', 'fixture member', None)
    mapping = q1.StoredIdentity(17, 101, 'fixture-app', 'https://issuer.example.invalid',
        '  opaque-A  ', 90, 'fixture-proof', 'fixture-registration', None)
    session = q1.StoredSession(101, 17, 1, CONTEXT, 100, 200, None)
    provenance = q1.StoredProvenance(mapping.issuer_key, mapping.issuer, mapping.subject,
        100, mapping.verification_method, mapping.registration_ref)
    binding = q1.IssuanceBinding(PROOF, DIGEST, 101, 17, CONTEXT, 1, 100, 200)
    return q1.SessionEnvelopeV2(DIGEST, member, (mapping,), session, provenance,
        binding, 120, Decimal('120.875'))


def receipt(row):
    b, p = row.issuance_binding, row.provenance
    return p1.AuthorityReceipt(
        p1.IssuanceBinding(b.proof_ref, b.credential_hash, b.member_id, b.verified_identity_id,
            b.auth_context_id, b.issued_auth_revision, b.issued_at, b.expires_at),
        p1.IssuanceProvenance(p.issuer_key, p.issuer, p.subject, p.verified_at,
            p.verification_method, p.registration_ref), AUTHORITY)


class FixtureSource:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.calls = []
        self.member_calls = []
        self.failure = None

    def schema_ready(self):
        return True

    def member_schema_ready(self):
        return True

    def read_current_session(self, digest):
        index = min(len(self.calls), len(self.rows) - 1)
        self.calls.append(digest)
        if self.failure is not None:
            raise self.failure
        return self.rows[index]

    def read_current_member(self, member_id):
        self.member_calls.append(member_id)
        return self.rows[0].member


class FixtureAuthority:
    """Independent prearranged receipt observations; not SQL-selected authority."""
    def __init__(self, observations):
        self.observations = tuple(observations)
        self.calls = []

    def ready(self):
        return True

    def read_verified_issuance(self, proof_ref):
        index = min(len(self.calls), len(self.observations) - 1)
        self.calls.append(proof_ref)
        return (self.observations[index],)


class FixtureI1:
    """Offline trusted registration fixture; actual I1 remains unconnected."""
    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def restore_verified_principal(self, evidence):
        self.calls.append(evidence)
        p = evidence.provenance
        registration = identity.IssuerRegistration(p.issuer_key, p.issuer,
            p.registration_ref, p.verification_method, 'email')
        return identity.VerifiedPrincipal._from_server_verifier(registration,
            subject=p.subject, verified_at=p.verified_at)


class Harness:
    def __init__(self, rows=None, observations=None, actual_default=False, factory=None):
        rows = (envelope(),) if rows is None else rows
        self.source = FixtureSource(rows)
        self.read = store.Q1ReadBridgeV2(self.source)
        observations = tuple(receipt(r) for r in rows if r is not None) if observations is None else observations
        self.authority = FixtureAuthority(observations)
        verifier = p1.IssuanceEvidenceVerifier(self.authority, authority_ref=AUTHORITY)
        self.i1 = FixtureI1()
        restorer = None if actual_default else self.i1
        self.principal = store.P1PrincipalBridgeV2(verifier, restorer, authority_ref=AUTHORITY)
        self.resolver = auth.create_stored_read_resolver_v3(self.read, self.principal)
        self.adapter = self.resolver.repository
        if factory is not None:
            self.adapter.snapshot_factory = factory


class StaticRepository:
    """Explicit injected native fixture, never an authentic-proof claim."""
    def __init__(self, value):
        self.value = value

    def schema_ready(self):
        return True

    def read_verified_session(self, digest):
        return self.value


def change_field(row, field):
    b, p, s, m = row.issuance_binding, row.provenance, row.session, row.identities[0]
    if field == 'proof_ref':
        return replace(row, issuance_binding=replace(b, proof_ref=OTHER))
    if field == 'credential_hash':
        return replace(row, credential_hash=DIGEST2, issuance_binding=replace(b, credential_hash=DIGEST2))
    if field == 'member_id':
        return replace(row, member=replace(row.member, member_id=102), identities=(replace(m, member_id=102),),
            session=replace(s, member_id=102), issuance_binding=replace(b, member_id=102))
    if field == 'verified_identity_id':
        return replace(row, identities=(replace(m, identity_id=18),),
            session=replace(s, verified_identity_id=18), issuance_binding=replace(b, verified_identity_id=18))
    if field == 'auth_context_id':
        return replace(row, session=replace(s, auth_context_id=OTHER), issuance_binding=replace(b, auth_context_id=OTHER))
    if field == 'issued_auth_revision':
        return replace(row, member=replace(row.member, auth_revision=2),
            session=replace(s, issued_auth_revision=2), issuance_binding=replace(b, issued_auth_revision=2))
    if field in ('issued_at', 'expires_at'):
        value = getattr(b, field) + 1
        return replace(row, session=replace(s, **{field: value}), issuance_binding=replace(b, **{field: value}))
    if field == 'verified_at':
        return replace(row, provenance=replace(p, verified_at=99))
    return replace(row, identities=(replace(m, **{field: 'fixture-other'}),),
        provenance=replace(p, **{field: 'fixture-other'}))


class PhaseBindingTests(unittest.TestCase):
    def assert_error(self, call, status, code):
        with self.assertRaises(HTTPException) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.status_code, status)
        self.assertEqual(error.detail, {'code': code})
        self.assertEqual(error.headers['Cache-Control'], 'no-store')
        return error

    def closed(self, call):
        return self.assert_error(call, 503, 'auth_unavailable')

    def native_key(self, value):
        return auth.VerifiedSessionResolution(value.member, value.session, value.credential_hash,
            value.now, auth._RESOLUTION_SEAL).key()

    def static_resolver(self, value, h):
        return auth.VerifiedSessionResolverV3(StaticRepository(value), h.principal)

    def assert_valid_change_rejected(self, field, old_key_equal=False):
        rows = (envelope(), change_field(envelope(), field))
        h = Harness(rows)
        before = h.resolver.resolve(SID)
        sid = SID2 if field == 'credential_hash' else SID
        # Prove both observations pass per-read checks before asserting phase rejection.
        after = h.resolver.resolve(sid)
        if old_key_equal:
            self.assertEqual(self.native_key(before), self.native_key(after))
        before_values = dict(zip(auth.PHASE_ISSUANCE_FIELDS_V3,
            auth._phase_issuance_values_v3(before.issuance_identity)))
        after_values = dict(zip(auth.PHASE_ISSUANCE_FIELDS_V3,
            auth._phase_issuance_values_v3(after.issuance_identity)))
        self.assertEqual([name for name in before_values if before_values[name] != after_values[name]], [field])
        self.assertNotEqual(before.key(), after.key())
        self.assert_error(lambda: h.resolver.confirm(sid, before), 409, 'auth_context_changed')
        self.assertEqual(len(h.source.calls), 3)
        self.assertEqual(len(h.authority.calls), 3)
        self.assertEqual(len(h.i1.calls), 3)

    def test_same14_transferred_and_each_query_emit_confirmation_is_fresh(self):
        h = Harness()
        before = h.resolver.resolve(SID)
        query = h.resolver.confirm(SID, before)
        h.read.read_current_member(101)
        emitted = h.resolver.confirm(SID, query)
        self.assertIs(type(emitted), auth.VerifiedSessionResolutionV3)
        self.assertIs(type(emitted.issuance_identity), auth.IssuanceIdentityV3)
        self.assertEqual(auth.PHASE_ISSUANCE_FIELDS_V3, p1.BINDING_FIELDS + p1.PROVENANCE_FIELDS)
        r = envelope()
        for field in p1.BINDING_FIELDS:
            self.assertEqual(getattr(emitted.issuance_identity, field), getattr(r.issuance_binding, field))
        for field in p1.PROVENANCE_FIELDS:
            self.assertEqual(getattr(emitted.issuance_identity, field), getattr(r.provenance, field))
        self.assertEqual(before.key(), emitted.key())
        self.assertEqual(h.source.calls, [DIGEST] * 3)
        self.assertEqual(h.authority.calls, [PROOF] * 3)
        self.assertEqual(len(h.i1.calls), 3)
        self.assertEqual(h.source.member_calls, [101])
        self.assertIsNot(before.issuance_identity, emitted.issuance_identity)

    def test_same_clock_bucket_is_fresh_without_clock_in_equality(self):
        a = envelope()
        h = Harness((a, replace(a, observed_epoch_exact=Decimal('120.999'))))
        before = h.resolver.resolve(SID)
        current = h.resolver.confirm(SID, before)
        self.assertEqual(before.key(), current.key())
        self.assertEqual((before.now, current.now), (120, 120))
        self.assertEqual(len(h.authority.calls), 2)

    def test_advancing_observation_clock_does_not_change_issuance_identity(self):
        a = envelope()
        h = Harness((a, replace(a, now=121, observed_epoch_exact=Decimal('121.25'))))
        before = h.resolver.resolve(SID)
        current = h.resolver.confirm(SID, before)
        self.assertEqual((before.now, current.now), (120, 121))
        self.assertEqual(before.key(), current.key())
        self.assertEqual(len(h.i1.calls), 2)

    def test_changed_proof_ref_is_valid_per_read_but_rejected_between_phases(self):
        self.assert_valid_change_rejected('proof_ref', old_key_equal=True)

    def test_changed_original_verified_at_is_valid_per_read_but_rejected_between_phases(self):
        self.assert_valid_change_rejected('verified_at', old_key_equal=True)

    def test_changed_issued_at_is_valid_per_read_but_rejected_between_phases(self):
        self.assert_valid_change_rejected('issued_at', old_key_equal=True)

    def test_changed_expires_at_is_valid_per_read_but_rejected_between_phases(self):
        self.assert_valid_change_rejected('expires_at', old_key_equal=True)

    def test_each_of_all14_fields_is_covered_by_successful_read_phase_comparison(self):
        for field in auth.PHASE_ISSUANCE_FIELDS_V3:
            with self.subTest(field=field):
                self.assert_valid_change_rejected(field)

    def test_current_canonical_auth_subject_comparison_is_kept(self):
        a = envelope()
        h = Harness((a, replace(a, member=replace(a.member, auth_subject=OTHER))))
        before = h.resolver.resolve(SID)
        after = h.resolver.resolve(SID)
        self.assertEqual(before.issuance_identity, after.issuance_identity)
        self.assertNotEqual(before.key(), after.key())
        self.assert_error(lambda: h.resolver.confirm(SID, before), 409, 'auth_context_changed')

    def test_mapping_time_is_distinct_from_original_issuance_verified_at(self):
        a = envelope()
        h = Harness((a, replace(a, identities=(replace(a.identities[0], verified_at=91),))))
        before = h.resolver.resolve(SID)
        after = h.resolver.confirm(SID, before)
        self.assertEqual(after.issuance_identity.verified_at, 100)
        self.assertEqual(after.member.principal.verified_at, 100)
        self.assertEqual(before.key(), after.key())
        self.assertEqual(len(h.authority.calls), 2)

    def test_missing_wrong_or_subclass_carrier_rejected503(self):
        h = Harness()
        snapshot = h.adapter.read_verified_session(DIGEST)
        c = snapshot.issuance_identity
        class Derived(auth.IssuanceIdentityV3):
            pass
        wrong = Derived(*auth._phase_issuance_values_v3(c))
        for value in (None, {}, envelope().issuance_binding, wrong, object.__new__(auth.IssuanceIdentityV3)):
            with self.subTest(kind=type(value).__name__):
                self.closed(lambda: self.static_resolver(replace(snapshot, issuance_identity=value), h).resolve(SID))

    def test_snapshot_requires_new_exact_class_not_legacy_dict_or_subclass(self):
        h = Harness()
        r = h.adapter.read_verified_session(DIGEST)
        legacy = auth.PersistedSessionSnapshot(r.credential_hash, r.principal, r.mappings, r.session, r.now)
        class Derived(auth.PersistedSessionSnapshotV3):
            pass
        derived = Derived(r.credential_hash, r.principal, r.mappings, r.session, r.now, r.issuance_identity)
        for value in (legacy, {}, derived):
            self.closed(lambda: self.static_resolver(value, h).resolve(SID))

    def test_carrier_integer_fields_reject_bool_string_float_decimal_and_range(self):
        h = Harness()
        snapshot = h.adapter.read_verified_session(DIGEST)
        for field in ('member_id', 'verified_identity_id', 'issued_auth_revision', 'verified_at', 'issued_at', 'expires_at'):
            for value in (True, str(getattr(snapshot.issuance_identity, field)),
                          float(getattr(snapshot.issuance_identity, field)), Decimal('100'),
                          -1, identity.MAX_BIGINT + 1):
                with self.subTest(field=field, kind=type(value).__name__):
                    wrong = replace(snapshot.issuance_identity, **{field: value})
                    self.closed(lambda: self.static_resolver(replace(snapshot, issuance_identity=wrong), h).resolve(SID))

    def test_invalid_carrier_identifiers_text_digest_and_event_order_are503(self):
        h = Harness()
        snapshot = h.adapter.read_verified_session(DIGEST)
        changes = {'proof_ref': 'bad', 'auth_context_id': 'bad', 'credential_hash': 'A' * 64,
            'issuer_key': '', 'issuer': '\x00', 'subject': '\ud800',
            'verification_method': None, 'registration_ref': '', 'expires_at': 100, 'verified_at': 101}
        for field, value in changes.items():
            with self.subTest(field=field):
                wrong = replace(snapshot.issuance_identity, **{field: value})
                self.closed(lambda: self.static_resolver(replace(snapshot, issuance_identity=wrong), h).resolve(SID))

    def test_every_locally_checkable_carrier_field_must_match_same_read_native_inputs(self):
        h = Harness()
        snapshot = h.adapter.read_verified_session(DIGEST)
        for field in auth.PHASE_ISSUANCE_FIELDS_V3:
            if field == 'proof_ref':
                continue  # Proof reference is bound upstream, not inferable from the native5 fields.
            altered = change_field(envelope(), field)
            source = altered.issuance_binding if field in p1.BINDING_FIELDS else altered.provenance
            carrier = replace(snapshot.issuance_identity, **{field: getattr(source, field)})
            self.closed(lambda: self.static_resolver(replace(snapshot, issuance_identity=carrier), h).resolve(SID))

    def test_factory_cannot_substitute_same_shape_carrier_or_change_proof_ref(self):
        for alter in (lambda c: replace(c), lambda c: replace(c, proof_ref=OTHER)):
            def factory(**kw):
                return replace(auth.PersistedSessionSnapshotV3(**kw), issuance_identity=alter(kw['issuance_identity']))
            h = Harness(factory=factory)
            self.closed(lambda: h.resolver.resolve(SID))

    def test_factory_in_place_carrier_mutation_cannot_change_verified_proof_ref(self):
        def factory(**kw):
            object.__setattr__(kw['issuance_identity'], 'proof_ref', OTHER)
            return auth.PersistedSessionSnapshotV3(**kw)
        h = Harness(factory=factory)
        self.closed(lambda: h.resolver.resolve(SID))
        self.assertEqual(h.authority.calls, [PROOF])
        self.assertEqual(len(h.i1.calls), 1)

    def test_factory_cannot_drop_carrier_or_replace_native_inputs_or_clock(self):
        factories = [lambda **kw: kw,
            lambda **kw: replace(auth.PersistedSessionSnapshotV3(**kw), now=True),
            lambda **kw: replace(auth.PersistedSessionSnapshotV3(**kw), session=replace(kw['session'])),
            lambda **kw: replace(auth.PersistedSessionSnapshotV3(**kw), mappings=list(kw['mappings'])),
            lambda **kw: replace(auth.PersistedSessionSnapshotV3(**kw), principal=None)]
        for factory in factories:
            h = Harness(factory=factory)
            self.closed(lambda: h.resolver.resolve(SID))

    def test_native_snapshot_clock_must_be_strict_integer(self):
        h = Harness()
        snapshot = h.adapter.read_verified_session(DIGEST)
        for now in (True, '120', Decimal('120'), -1):
            self.closed(lambda: self.static_resolver(replace(snapshot, now=now), h).resolve(SID))

    def test_current_expired_revoked_mapping_inactive_and_revision_fail_native401(self):
        a = envelope()
        changes = [
            (replace(a, now=200, observed_epoch_exact=Decimal('200.25')), 'unauthenticated'),
            (replace(a, session=replace(a.session, revoked_at=119)), 'unauthenticated'),
            (replace(a, identities=(replace(a.identities[0], revoked_at=119),)), 'identity_revoked'),
            (replace(a, member=replace(a.member, status='inactive')), 'member_inactive'),
            (replace(a, member=replace(a.member, auth_revision=2)), 'principal_revision_changed')]
        for after, code in changes:
            with self.subTest(code=code):
                h = Harness((a, after))
                before = h.resolver.resolve(SID)
                self.assert_error(lambda: h.resolver.confirm(SID, before), 401, code)
                self.assertEqual(len(h.authority.calls), 2)

    def test_invalid_current_state_takes_precedence_over_changed_issuance_identity(self):
        a = envelope()
        changed = change_field(a, 'proof_ref')
        changed = replace(changed, session=replace(changed.session, revoked_at=119))
        h = Harness((a, changed))
        before = h.resolver.resolve(SID)
        self.assert_error(lambda: h.resolver.confirm(SID, before), 401, 'unauthenticated')

    def test_existing_expected_context_mismatch_and_malformed_context_stay409(self):
        for context in (OTHER, 'bad', True):
            h = Harness()
            before = h.resolver.resolve(SID)
            self.assert_error(lambda: h.resolver.confirm(SID, before, expected_context=context),
                409, 'auth_context_changed')

    def test_changed_valid_context_with_expected_old_context_stays_native409(self):
        a = envelope()
        h = Harness((a, change_field(a, 'auth_context_id')))
        before = h.resolver.resolve(SID, expected_context=CONTEXT)
        self.assert_error(lambda: h.resolver.confirm(SID, before, expected_context=CONTEXT),
            409, 'auth_context_changed')

    def test_query_to_emit_confirm_discards_valid_rebound_receipt(self):
        a = envelope()
        h = Harness((a, a, change_field(a, 'proof_ref')))
        initial = h.resolver.resolve(SID)
        before_query = h.resolver.confirm(SID, initial)
        h.read.read_current_member(101)
        self.assert_error(lambda: h.resolver.confirm(SID, before_query), 409, 'auth_context_changed')
        self.assertEqual(h.source.member_calls, [101])
        self.assertEqual(h.authority.calls, [PROOF, PROOF, OTHER])
        self.assertEqual(len(h.i1.calls), 3)

    def test_unknown_fresh_row_remains401_without_receipt_fallback(self):
        h = Harness((envelope(), None))
        before = h.resolver.resolve(SID)
        self.assert_error(lambda: h.resolver.confirm(SID, before), 401, 'unauthenticated')
        self.assertEqual(len(h.source.calls), 2)
        self.assertEqual(len(h.authority.calls), 1)

    def test_source_fault_is_private503_before_receipt_or_i1(self):
        h = Harness()
        h.source.failure = RuntimeError('private source input')
        error = self.closed(lambda: h.resolver.resolve(SID))
        self.assertNotIn('private', str(error.detail))
        self.assertTrue(error.__suppress_context__)
        self.assertEqual(h.authority.calls, [])
        self.assertEqual(h.i1.calls, [])

    def test_actual_default_i1_stays_unready503_in_new_composition(self):
        h = Harness(actual_default=True)
        self.assertFalse(h.principal.ready())
        self.closed(lambda: h.resolver.resolve(SID))
        self.assertEqual(h.source.calls, [])
        self.assertEqual(h.authority.calls, [])
        self.assertEqual(h.i1.calls, [])

    def test_typed_metadata_cannot_replace_independent_same_read_receipt(self):
        a = envelope()
        independent = receipt(change_field(a, 'proof_ref'))
        h = Harness((a,), observations=(independent,))
        self.closed(lambda: h.resolver.resolve(SID))
        self.assertEqual(h.authority.calls, [PROOF])
        self.assertEqual(h.i1.calls, [])

    def test_before_resolution_requires_new_exact_type_and_seal(self):
        h = Harness()
        before = h.resolver.resolve(SID)
        old = auth.VerifiedSessionResolution(before.member, before.session, before.credential_hash,
            before.now, auth._RESOLUTION_SEAL)
        for value in (old, {}, replace(before, _seal=object())):
            self.assert_error(lambda: h.resolver.confirm(SID, value), 401, 'unauthenticated')
        self.assertEqual(len(h.source.calls), 1)

    def test_malformed_before_carrier_is503_without_using_cached_snapshot(self):
        h = Harness()
        before = h.resolver.resolve(SID)
        self.closed(lambda: h.resolver.confirm(SID, replace(before, issuance_identity=None)))
        self.assertEqual(len(h.source.calls), 1)

    def test_phase_metadata_is_frozen_internal_and_not_added_to_public_payload(self):
        h = Harness()
        current = h.resolver.resolve(SID)
        with self.assertRaises(FrozenInstanceError):
            current.issuance_identity.proof_ref = OTHER
        body = identity.authenticated_payload(current.member, current.session, now=current.now)
        wire = json.dumps(body)
        for private in (PROOF, DIGEST, AUTHORITY, 'issuance_identity', 'proof_ref',
                        'credential_hash', 'verified_at', 'issued_at', 'expires_at', 'observed_epoch_exact'):
            self.assertNotIn(private, wire)
        self.assertEqual(set(vars(h.adapter)), {'source', 'principal', 'snapshot_factory'})

    def test_unversioned_auth_and_accepted_v2_prefix_AST_and_runtime_are_preserved(self):
        for module, length, pin in (
                (auth, 14287, 'd5be0157d009e3a6fd46a82508a6d91dcd4f445e5df452b672105f653fe378d1'),
                (store, 23478, '371120b99c533cda04edf6a6c15a88726e1151c2b8f0f81ac14fed7bed9d04ea')):
            raw = Path(module.__file__).read_bytes()
            self.assertEqual(hashlib.sha256(raw[:length]).hexdigest(), pin)
            old = ast.parse(raw[:length].decode('utf-8'))
            new = ast.parse(raw.decode('utf-8'))
            self.assertEqual([ast.dump(n) for n in old.body], [ast.dump(n) for n in new.body[:len(old.body)]])
        self.assertFalse(auth.RUNTIME_RESOLVER.repository.schema_ready())
        self.assertFalse(store.RUNTIME_READ_PORT.schema_ready())
        self.assertFalse(store.RUNTIME_PRINCIPAL_PORT.ready())
        self.assertFalse(store.RUNTIME_REVOCATION_PORT.ready())
        self.closed(lambda: auth.RUNTIME_RESOLVER.resolve(SID))
        for forbidden in ('api.db', 'api.main', 'api.my_account', 'test_customer_auth_store_issuance_contract',
                          'test_customer_auth_store_connection', 'test_customer_auth_sql_read', 'test_customer_auth_provenance'):
            self.assertNotIn(forbidden, sys.modules)


if __name__ == '__main__':
    unittest.main()
