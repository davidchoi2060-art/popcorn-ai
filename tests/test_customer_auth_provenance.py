"""New P1 standalone CODE/MOCK fixtures only; no old suites or live IO."""
import ast
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest


def _deny_live_io(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system', 'sqlite3.connect'):
        raise AssertionError('P1 fixture live IO forbidden')
    if event == 'import' and args:
        name = args[0]
        forbidden = ('api.db', 'api.main', 'api.customer_identity', 'api.customer_auth',
                     'api.customer_auth_store', 'api.my_account', 'api.customer_auth_sql_read',
                     'sqlalchemy', 'psycopg', 'psycopg2', 'fastapi', 'httpx', 'requests')
        if any(name == item or name.startswith(item+'.') for item in forbidden):
            raise AssertionError('P1 unrelated/runtime import forbidden')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        name = str(args[0]).replace('\\', '/').lower().rstrip("'")
        if name.rsplit('/', 1)[-1] == '.env':
            raise AssertionError('P1 secret file read forbidden')


sys.addaudithook(_deny_live_io)
from api import customer_auth_provenance as p1


AUTHORITY = 'fixture-authority-version-1'
PROOF = '11111111-1111-4111-8111-111111111111'
CONTEXT = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'


def binding():
    return p1.IssuanceBinding(PROOF, 'a'*64, 101, 17, CONTEXT, 1, 100, 200)


def provenance():
    return p1.IssuanceProvenance('fixture-app', 'https://issuer.example.invalid',
                               '  opaque-신원-A  ', 100, 'fixture-verified', 'fixture-registration-1')


def receipt():
    return p1.AuthorityReceipt(binding(), provenance(), AUTHORITY)


class FixtureIndependentAuthority:
    """Explicit trusted test source, not SQL data or an actual approved issuer."""
    def __init__(self):
        self.receipts = (receipt(),)
        self.lookups = []
        self.ready_value = True
        self.ready_error = None
        self.lookup_error = None
        self.close_after_lookup = False

    def ready(self):
        if self.ready_error is not None:
            raise self.ready_error
        return self.ready_value

    def read_verified_issuance(self, proof_ref):
        self.lookups.append(proof_ref)
        if self.close_after_lookup:
            self.ready_value = False
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.receipts


class P1StandaloneEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.authority = FixtureIndependentAuthority()
        self.verifier = p1.IssuanceEvidenceVerifier(self.authority, authority_ref=AUTHORITY)

    def verify(self, *, input_binding=None, input_provenance=None):
        return self.verifier.verify_issuance(
            provenance() if input_provenance is None else input_provenance,
            binding=binding() if input_binding is None else input_binding)

    def closed(self, call=None):
        with self.assertRaises(p1.IssuanceUnavailable) as caught:
            (self.verify if call is None else call)()
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'auth_unavailable'))
        self.assertEqual(str(caught.exception), 'auth_unavailable')
        return caught.exception

    def test_exact_receipt_uses_only_proof_ref_once_and_returns_evidence(self):
        result = self.verify()
        self.assertEqual(self.authority.lookups, [PROOF])
        self.assertIs(type(result), p1.VerifiedIssuanceEvidence)
        self.assertEqual(result.binding, binding())
        self.assertEqual(result.provenance, provenance())
        self.assertEqual(result.authority_ref, AUTHORITY)
        self.assertIsNot(result.binding, self.authority.receipts[0].binding)
        self.assertIsNot(result.provenance, self.authority.receipts[0].provenance)
        self.assertFalse(hasattr(result, '_seal'))
        self.assertFalse(hasattr(result, 'authenticated'))

    def test_runtime_without_authority_is_closed(self):
        self.assertFalse(p1.RUNTIME_VERIFIER.ready())
        self.closed(lambda:p1.RUNTIME_VERIFIER.verify_issuance(provenance(), binding=binding()))

    def test_authority_without_server_registration_ref_is_closed(self):
        self.closed(lambda:p1.IssuanceEvidenceVerifier(self.authority).verify_issuance(provenance(), binding=binding()))
        self.assertEqual(self.authority.lookups, [])

    def test_bool_dict_and_seal_are_not_injected_authorities(self):
        for source in (True, {'ready':True, 'receipt':receipt()}, object()):
            with self.subTest(source_type=type(source).__name__):
                self.closed(lambda:p1.IssuanceEvidenceVerifier(source, authority_ref=AUTHORITY)
                            .verify_issuance(provenance(), binding=binding()))

    def test_ready_flag_alone_does_not_approve_unknown_receipt(self):
        self.authority.receipts = ()
        self.assertTrue(self.verifier.ready())
        self.closed()
        self.assertEqual(self.authority.lookups, [PROOF])

    def test_duplicate_authority_receipts_are_closed_even_if_identical(self):
        self.authority.receipts = (receipt(), receipt())
        self.closed()
        self.assertEqual(self.authority.lookups, [PROOF])

    def test_missing_malformed_or_lazy_authority_results_are_closed(self):
        for value in (None, True, {'receipt':receipt()}, [receipt()], iter((receipt(),)), (None,)):
            with self.subTest(result_type=type(value).__name__):
                self.authority.receipts = value
                self.closed()

    def test_sql_metadata_dict_is_not_an_authority_receipt(self):
        self.authority.receipts = (asdict(receipt()),)
        self.closed()

    def test_shape_and_seal_only_object_is_not_an_authority_receipt(self):
        class RowWithSeal:
            pass
        row = RowWithSeal()
        row.binding, row.provenance, row.authority_ref, row._seal = binding(), provenance(), AUTHORITY, object()
        self.authority.receipts = (row,)
        self.closed()

    def test_result_cannot_be_replayed_as_an_authority_receipt(self):
        self.authority.receipts = (self.verify(),)
        self.closed()

    def test_every_binding_field_mismatch_is_closed(self):
        changes = {'proof_ref':OTHER, 'credential_hash':'b'*64, 'member_id':102,
                   'verified_identity_id':18, 'auth_context_id':OTHER,
                   'issued_auth_revision':2, 'issued_at':101, 'expires_at':201}
        for name, value in changes.items():
            with self.subTest(field=name):
                self.authority.receipts = (replace(receipt(), binding=replace(binding(), **{name:value})),)
                self.closed()

    def test_every_provenance_field_mismatch_is_closed(self):
        changes = {'issuer_key':'other-app', 'issuer':'https://other.example.invalid',
                   'subject':'different-subject', 'verified_at':99,
                   'verification_method':'different-verification', 'registration_ref':'different-registration'}
        for name, value in changes.items():
            with self.subTest(field=name):
                self.authority.receipts = (replace(receipt(), provenance=replace(provenance(), **{name:value})),)
                self.closed()

    def test_same_provenance_receipt_cannot_authorize_another_session(self):
        target = replace(binding(), proof_ref=OTHER, credential_hash='b'*64, auth_context_id=OTHER)
        self.closed(lambda:self.verify(input_binding=target))
        self.assertEqual(self.authority.lookups, [OTHER])

    def test_unrelated_authority_registration_cannot_be_selected_by_receipt(self):
        self.authority.receipts = (replace(receipt(), authority_ref='different-authority'),)
        self.closed()

    def test_authority_registration_ref_is_strict_opaque_text(self):
        for value in (None, True, '', '\x00', '\ud800'):
            with self.subTest(value_type=type(value).__name__):
                self.authority.receipts = (replace(receipt(), authority_ref=value),)
                self.closed()

    def test_same_invalid_binding_on_both_sides_is_still_closed(self):
        changes = {'member_id':True, 'verified_identity_id':0, 'issued_auth_revision':-1,
                   'credential_hash':'A'*64, 'proof_ref':'not-uuid',
                   'auth_context_id':CONTEXT.upper(), 'issued_at':Decimal('100'), 'expires_at':200.0}
        # The numeric-only context UUID uppercases unchanged; use an alphabetic invalid canonical form.
        changes['auth_context_id'] = 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'
        for name, value in changes.items():
            with self.subTest(field=name):
                bad = replace(binding(), **{name:value})
                self.authority.receipts = (replace(receipt(), binding=bad),)
                self.closed(lambda:self.verify(input_binding=bad))
        self.assertEqual(self.authority.lookups, [])

    def test_same_invalid_provenance_on_both_sides_is_still_closed(self):
        for name, value in (('issuer_key',''), ('issuer',True), ('subject','\x00'),
                            ('verification_method','\ud800'), ('registration_ref',None), ('verified_at',False)):
            with self.subTest(field=name):
                bad = replace(provenance(), **{name:value})
                self.authority.receipts = (replace(receipt(), provenance=bad),)
                self.closed(lambda:self.verify(input_provenance=bad))
        self.assertEqual(self.authority.lookups, [])

    def test_id_epoch_overflow_and_negative_times_are_closed(self):
        for name, value in (('member_id',p1.MAX_BIGINT+1), ('issued_auth_revision',p1.MAX_BIGINT+1),
                            ('issued_at',-1), ('expires_at',p1.MAX_BIGINT+1)):
            with self.subTest(field=name):
                self.closed(lambda:self.verify(input_binding=replace(binding(), **{name:value})))
        self.closed(lambda:self.verify(input_provenance=replace(provenance(), verified_at=p1.MAX_BIGINT+1)))
        self.assertEqual(self.authority.lookups, [])

    def test_fractional_and_string_events_are_not_coerced(self):
        for value in (100.1, Decimal('100.9'), '100', Decimal('NaN'), Decimal('Infinity')):
            with self.subTest(value_type=type(value).__name__):
                self.closed(lambda:self.verify(input_provenance=replace(provenance(), verified_at=value)))
        self.assertEqual(self.authority.lookups, [])

    def test_verified_after_issuance_is_closed(self):
        bad = replace(provenance(), verified_at=101)
        self.closed(lambda:self.verify(input_provenance=bad))
        self.assertEqual(self.authority.lookups, [])

    def test_expiry_not_after_issuance_is_closed(self):
        for value in (100, 99):
            with self.subTest(expiry=value):
                self.closed(lambda:self.verify(input_binding=replace(binding(), expires_at=value)))
        self.assertEqual(self.authority.lookups, [])

    def test_original_verification_time_preserved_without_refresh_or_ttl(self):
        old = replace(provenance(), verified_at=90)
        self.authority.receipts = (replace(receipt(), provenance=old),)
        result = self.verify(input_provenance=old)
        self.assertEqual((result.provenance.verified_at, result.binding.issued_at, result.binding.expires_at), (90,100,200))
        self.assertEqual(self.authority.lookups, [PROOF])

    def test_zero_event_and_bigint_identity_boundaries_are_valid(self):
        bound = replace(binding(), member_id=p1.MAX_BIGINT, issued_at=0, expires_at=1)
        prov = replace(provenance(), verified_at=0)
        self.authority.receipts = (p1.AuthorityReceipt(bound, prov, AUTHORITY),)
        self.assertEqual(self.verify(input_binding=bound, input_provenance=prov).binding, bound)

    def test_opaque_subject_is_not_stripped_lowered_or_email_linked(self):
        result = self.verify()
        self.assertEqual(result.provenance.subject, '  opaque-신원-A  ')
        self.authority.receipts = (replace(receipt(), provenance=replace(provenance(), subject=provenance().subject.strip())),)
        self.closed()

    def test_plain_client_input_dicts_and_bool_are_closed_without_lookup(self):
        for value in (asdict(binding()), True):
            self.closed(lambda:self.verify(input_binding=value))
        for value in (asdict(provenance()), True):
            self.closed(lambda:self.verify(input_provenance=value))
        self.assertEqual(self.authority.lookups, [])

    def test_incomplete_typed_input_and_authority_objects_are_closed(self):
        self.closed(lambda:self.verify(input_binding=object.__new__(p1.IssuanceBinding)))
        self.closed(lambda:self.verify(input_provenance=object.__new__(p1.IssuanceProvenance)))
        self.authority.receipts = (object.__new__(p1.AuthorityReceipt),)
        self.closed()

    def test_authority_unready_nonbool_or_throwing_never_performs_lookup(self):
        for value in (False, 1, 'true'):
            self.authority.ready_value = value
            self.closed()
        self.authority.ready_value = True
        self.authority.ready_error = RuntimeError('private registration source failure')
        self.closed()
        self.assertEqual(self.authority.lookups, [])

    def test_authority_lookup_error_does_not_leak_private_payload(self):
        self.authority.lookup_error = RuntimeError('private subject digest proof payload')
        error = self.closed()
        self.assertTrue(error.__suppress_context__)
        self.assertEqual(vars(error), {'status':503, 'code':'auth_unavailable'})

    def test_authority_becomes_unready_after_lookup_is_closed(self):
        self.authority.close_after_lookup = True
        self.closed()
        self.assertEqual(self.authority.lookups, [PROOF])

    def test_each_verification_performs_fresh_independent_lookup(self):
        self.verify()
        self.authority.receipts = ()
        self.closed()
        self.assertEqual(self.authority.lookups, [PROOF, PROOF])

    def test_input_and_result_are_immutable_and_repr_hides_private_fields(self):
        result = self.verify()
        for value, name in ((result,'authority_ref'), (result.binding,'member_id'), (result.provenance,'subject')):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, name, 'changed')
                self.assertNotIn(PROOF, repr(value))
                self.assertNotIn(provenance().subject, repr(value))

    def test_external_c2_field_contract_matches_standalone_input(self):
        # The accepted C2 contract is not in the repo yet. Read it from the repo fixture, or from
        # POPCORN_C2_CONTRACT_SOURCE; the sha256 pin below still decides whether it is the accepted file.
        path = Path(os.environ.get('POPCORN_C2_CONTRACT_SOURCE') or
                    Path(__file__).resolve().parent / 'fixtures' / 'c2-session-proof-contract-v1.json')
        if not path.is_file():
            self.skipTest('개발 PC 전용 자료 없음: accepted C2 contract fixture missing at ' + str(path))
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), 'f28ccf34a308fd147dabc98345c602696bc984f7bb23cfd339e3b30fc46a160a')
        contract = json.loads(raw)
        self.assertEqual(tuple(contract['v2_binding_fields']), p1.BINDING_FIELDS)
        self.assertEqual(tuple(contract['v2_provenance_fields']), p1.PROVENANCE_FIELDS)
        self.assertFalse(contract['r1_signature_compatible'])

    def test_module_has_no_c1_r1_sql_http_provider_or_runtime_composition_import(self):
        tree = ast.parse(Path(p1.__file__).read_text(encoding='utf-8'))
        imports = {node.module if isinstance(node,ast.ImportFrom) else alias.name
                   for node in ast.walk(tree) if isinstance(node,(ast.ImportFrom,ast.Import))
                   for alias in (node.names if isinstance(node,ast.Import) else [None])}
        self.assertEqual(imports, {'dataclasses','re','typing','uuid'})
        self.assertFalse(hasattr(p1, 'restore_verified_principal'))
        self.assertFalse(hasattr(p1.IssuanceEvidenceVerifier, 'restore_verified_principal'))
        self.assertNotIn('api.customer_identity', sys.modules)
        self.assertNotIn('api.customer_auth_store', sys.modules)
        self.assertNotIn('api.db', sys.modules)


if __name__ == '__main__':
    unittest.main()
