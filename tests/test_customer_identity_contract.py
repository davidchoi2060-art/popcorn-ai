"""C1 supplied-data contract boundaries only; no real verifier/DB/session proof."""
import ast
from dataclasses import FrozenInstanceError, replace
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_IO_GUARD_ENABLED = False

def _deny_io(event, args):
    if not _IO_GUARD_ENABLED:
        return
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
        raise AssertionError('C1 external IO forbidden')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace('\\','/').lower().endswith('/.env'):
            raise AssertionError('C1 secret file read forbidden')


# Guard is installed BEFORE application import. There is no live-engine stub:
# importing api.db itself is outside this pure contract and forbidden below.
sys.addaudithook(_deny_io)
_IO_GUARD_ENABLED = True
try:
    identity = importlib.import_module('api.customer_identity')
finally:
    _IO_GUARD_ENABLED = False

STABLE = '22222222-2222-4222-8222-222222222222'
CONTEXT = '11111111-1111-4111-8111-111111111111'
ROTATED = '33333333-3333-4333-8333-333333333333'


def registration(**changes):
    fields = dict(issuer_key='fixture-registration-kakao', issuer='https://issuer.example.invalid',
                  registration_ref='fixture-app-v1', verification_method='fixture-server-oidc', via='kakao')
    fields.update(changes)
    return identity.IssuerRegistration(**fields)


class FixtureVerifier:
    """Tests-only verified-output port; it performs NO cryptographic verification."""
    def __init__(self, registered=None, subject='fixture-Opaque-subject', profile=None):
        self.registered = registration() if registered is None else registered
        self.subject, self.profile = subject, profile
    def verify(self, proof):
        if proof != 'explicit-fixture-proof':
            raise identity.IdentityError(401, 'fixture_verification_rejected')
        return identity.VerifiedPrincipal._from_server_verifier(self.registered,
            subject=self.subject, verified_at=100, optional_profile=self.profile)


def principal(**changes): return FixtureVerifier(**changes).verify('explicit-fixture-proof')


def member(**changes):
    fields = dict(member_id=101, auth_subject=STABLE, principal_revision=1,
                  status='active', nickname='회원', email=None)
    fields.update(changes)
    return identity.CanonicalMember(**fields)


def mapping(**changes):
    fields = dict(identity_id=17, member=member(), issuer_key=registration().issuer_key,
                  issuer=registration().issuer, subject='fixture-Opaque-subject', verified_at=90,
                  verification_method=registration().verification_method,
                  registration_ref=registration().registration_ref)
    fields.update(changes)
    return identity.VerifiedIdentityMapping(**fields)


def resolved(**changes):
    return identity.resolve_identity(principal(), [mapping(**changes)], now=120)


def session(**changes):
    fields = dict(member_id=101, verified_identity_id=17, issued_auth_revision=1,
                  session_context_id=CONTEXT, issued_at=100, expires_at=200)
    fields.update(changes)
    return identity.SessionContext(**fields)


class IdentityContractTests(unittest.TestCase):
    def setUp(self):
        global _IO_GUARD_ENABLED
        _IO_GUARD_ENABLED = True

    def tearDown(self):
        global _IO_GUARD_ENABLED
        _IO_GUARD_ENABLED = False

    def rejected(self, status, code, call, *args, **kwargs):
        with self.assertRaises(identity.IdentityError) as caught: call(*args, **kwargs)
        self.assertEqual((caught.exception.status,caught.exception.code),(status,code))
        for secret in ['fixture-Opaque-subject', 'private@example.invalid', 'fixture-app-v1', 'private-token']:
            self.assertNotIn(secret, str(caught.exception))

    def test_bigint_wire_accepts_full_range_and_is_lossless_above_js_safe_integer(self):
        for number in [1,101,9007199254740993,identity.MAX_BIGINT]:
            self.assertEqual(identity.decimal_id(identity.wire_id(number)),number)
            self.assertEqual(identity.wire_id(number),str(number))

    def test_decimal_ids_reject_noncanonical_or_nonstring_forms(self):
        for value in [None,0,1,True,1.0,'','0','-1','+1','01',' 1','1 ','1.0','1e2',
                      '１','١','9223372036854775808','12345678901234567890','1\n']:
            with self.subTest(value=value):
                self.rejected(422,'invalid_identity_decimal' if type(value) is not str
                    or not identity._DECIMAL.fullmatch(value) else 'invalid_identity_integer',
                    identity.decimal_id,value)

    def test_native_ids_reject_bool_float_and_overflow_in_all_identity_fields(self):
        for value in [None,False,True,0,-1,1.0,'101',identity.MAX_BIGINT+1]:
            with self.subTest(value=value):
                self.rejected(422,'invalid_identity_integer',identity.wire_id,value)
                self.rejected(422,'invalid_identity_integer',member,member_id=value)
                self.rejected(422,'invalid_identity_integer',member,principal_revision=value)
                self.rejected(422,'invalid_identity_integer',mapping,identity_id=value)
                self.rejected(422,'invalid_identity_integer',session,issued_auth_revision=value)

    def test_direct_principal_constructor_and_request_verified_flags_are_denied(self):
        self.rejected(401,'server_verified_principal_required',identity.VerifiedPrincipal,
                      issuer_key='kakao',subject='private@example.invalid',verified=True)
        for value in [dict(verified=True,issuer='kakao',member_id=101),
                      dict(provider='kakao',email='private@example.invalid'), None]:
            self.rejected(401,'server_verified_principal_required',identity.resolve_identity,
                          value,[mapping()],now=120)

    def test_unsealed_object_and_direct_verified_member_constructor_are_denied(self):
        forged = object.__new__(identity.VerifiedPrincipal)
        self.rejected(401,'server_verified_principal_required',identity.resolve_identity,forged,[mapping()],now=120)
        self.rejected(401,'verified_mapping_required',identity.VerifiedMember,member=member(),identity_id=17)

    def test_server_port_requires_registered_typed_input_and_optional_profile(self):
        self.rejected(401,'server_registration_required',identity.VerifiedPrincipal._from_server_verifier,
                      {'issuer_key':'kakao'},subject='fixture-sub',verified_at=100)
        self.rejected(401,'server_verified_principal_required',identity.VerifiedPrincipal._from_server_verifier,
                      registration(),subject='fixture-sub',verified_at=100,optional_profile={'email':'private@example.invalid'})

    def test_nonstring_provider_is_rejected_before_custom_equality_or_public_payload(self):
        class EqualityOnlyVia:
            equality_calls = 0
            def __eq__(self, other):
                self.equality_calls += 1
                return other == 'kakao'
        value = EqualityOnlyVia()
        self.rejected(422,'invalid_identity_provider',registration,via=value)
        self.assertEqual(value.equality_calls,0)

    def test_provider_string_subclass_is_rejected_before_principal_creation(self):
        class TextSubclass(str):
            pass
        self.rejected(422,'invalid_identity_provider',registration,via=TextSubclass('kakao'))

    def test_subject_is_opaque_exact_case_and_has_no_numeric_or_email_coercion(self):
        for subject in ['Case-sensitive',' case-sensitive ','001','123@example.invalid']:
            p = principal(subject=subject)
            result = identity.resolve_identity(p,[mapping(subject=subject)],now=120)
            self.assertEqual(result.principal.subject,subject)
            self.assertEqual(result.member.member_id,101)
        self.rejected(409,'identity_unlinked',identity.resolve_identity,
                      principal(subject='CASE-sensitive'),[mapping(subject='Case-sensitive')],now=120)

    def test_empty_numeric_or_unpersistable_subjects_fail_closed(self):
        for subject in [None,123,False,'','nul\x00byte','surrogate\ud800']:
            self.rejected(422,'invalid_identity_text',principal,subject=subject)

    def test_same_email_different_subject_does_not_link_even_with_profile_email(self):
        display = identity.OptionalProfile(email='private@example.invalid')
        canonical = member(email='private@example.invalid')
        self.rejected(409,'identity_unlinked',identity.resolve_identity,
                      principal(subject='new-subject',profile=display),[mapping(member=canonical)],now=120)

    def test_same_subject_different_registration_does_not_auto_merge(self):
        p = principal(registered=registration(issuer_key='fixture-other-app'))
        self.rejected(409,'identity_unlinked',identity.resolve_identity,p,[mapping()],now=120)

    def test_unmatched_identity_always409_without_mapping_mutation_or_session(self):
        mappings = []
        self.rejected(409,'identity_unlinked',identity.resolve_identity,principal(),mappings,now=120)
        self.assertEqual(mappings,[])

    def test_mapping_dict_legacy_provider_or_duplicate_rows_never_supply_verified_identity(self):
        for mappings in [[{'joined_via':'kakao','provider_uid':'fixture-Opaque-subject'}],
                         {'member_id':101}, None]:
            self.rejected(503,'identity_mapping_unavailable',identity.resolve_identity,principal(),mappings,now=120)
        self.rejected(503,'identity_mapping_conflict',identity.resolve_identity,principal(),[mapping(),mapping()],now=120)

    def test_issuer_registration_method_provenance_and_verification_time_must_match(self):
        for changes in [dict(issuer='https://other.example.invalid'),dict(registration_ref='other-app'),
                        dict(verification_method='client-verified'),dict(verified_at=121)]:
            self.rejected(401,'verification_provenance_mismatch',identity.resolve_identity,
                          principal(),[mapping(**changes)],now=120)
        self.rejected(401,'verification_provenance_mismatch',identity.resolve_identity,principal(),[mapping()],now=99)

    def test_revoked_mapping_and_inactive_member_are_not_authenticated(self):
        self.rejected(401,'identity_revoked',identity.resolve_identity,principal(),[mapping(revoked_at=0)],now=120)
        for status in ['inactive','withdrawn','blocked']:
            self.rejected(401,'member_inactive',resolved,member=member(status=status))

    def test_provider_without_email_works_only_with_explicit_verified_mapping(self):
        result = resolved()
        data = identity.authenticated_payload(result,session(),now=120)
        self.assertIsNone(data['member']['email'])
        self.assertEqual(data['member']['member_id'],'101')
        self.assertEqual(data['member']['via'],'kakao')

    def test_provider_display_claim_does_not_overwrite_canonical_member_contact(self):
        p = principal(profile=identity.OptionalProfile(nickname='provider name',email='private@example.invalid'))
        result = identity.resolve_identity(p,[mapping()],now=120)
        data = identity.authenticated_payload(result,session(),now=120)
        self.assertEqual(data['member']['nickname'],'회원')
        self.assertIsNone(data['member']['email'])

    def test_mapping_principal_member_and_session_are_immutable_and_reprs_do_not_print_pii(self):
        objects = [(principal(),'subject','changed'),(mapping(),'subject','changed'),
                   (member(),'nickname','changed'),(session(),'session_context_id',ROTATED),
                   (resolved(),'identity_id',18)]
        for value,name,replacement in objects:
            with self.assertRaises((FrozenInstanceError,AttributeError)): setattr(value,name,replacement)
            self.assertNotIn('fixture-Opaque-subject',repr(value))
            self.assertNotIn('fixture-app-v1',repr(value))

    def test_stable_owner_survives_session_context_rotation(self):
        result = resolved()
        first = identity.authenticated_payload(result,session(),now=120)
        next_session = session(session_context_id=ROTATED,issued_at=110)
        second = identity.authenticated_payload(result,next_session,now=120)
        self.assertEqual(result.stable_owner(),dict(kind='member',member_id=101,auth_subject=STABLE))
        self.assertEqual(first['auth_context']['member_id'],second['auth_context']['member_id'])
        self.assertNotEqual(first['auth_context']['session_context_id'],second['auth_context']['session_context_id'])
        self.assertNotEqual(STABLE,first['auth_context']['session_context_id'])

    def test_stable_subject_is_not_a_public_session_context(self):
        self.rejected(401,'session_identity_mismatch',identity.authenticated_payload,resolved(),
                      session(session_context_id=STABLE),now=120)

    def test_context_header_alone_or_client_member_dictionary_does_not_authorize(self):
        for unverified in [{'member_id':101,'auth_subject':STABLE,'verified':True}, member(), None]:
            self.rejected(401,'verified_mapping_required',identity.auth_context,unverified,session(),
                          now=120,expected_context=CONTEXT)
        self.rejected(401,'verified_session_required',identity.auth_context,resolved(),
                      {'session_context_id':CONTEXT},now=120)

    def test_session_member_or_identity_fk_mismatch_fails_closed(self):
        for changes in [dict(member_id=102),dict(verified_identity_id=18)]:
            self.rejected(401,'session_identity_mismatch',identity.authenticated_payload,resolved(),session(**changes),now=120)

    def test_issued_and_current_principal_revisions_must_match(self):
        self.rejected(401,'principal_revision_changed',identity.authenticated_payload,resolved(),
                      session(issued_auth_revision=2),now=120)
        self.rejected(401,'principal_revision_changed',identity.authenticated_payload,
                      resolved(member=member(principal_revision=2)),session(),now=120)

    def test_expired_revoked_future_or_pre_verification_session_is_denied(self):
        for changes in [dict(expires_at=120),dict(revoked_at=0),dict(issued_at=121),dict(issued_at=99)]:
            self.rejected(401,'unauthenticated',identity.authenticated_payload,resolved(),session(**changes),now=120)

    def test_expected_public_context_mismatch_and_malformed_value_are409(self):
        for value in [ROTATED,'private-token','',True,STABLE]:
            self.rejected(409,'auth_context_changed',identity.auth_context,resolved(),session(),
                          now=120,expected_context=value)

    def test_profile_requires_context_and_rechecks_expiry_before_emission(self):
        result, metadata = resolved(),session()
        before = identity.auth_context(result,metadata,now=120,expected_context=CONTEXT)
        self.assertEqual(before['session_context_id'],CONTEXT)
        self.rejected(409,'auth_context_changed',identity.profile_payload,result,metadata,now=120,expected_context=None)
        self.rejected(401,'unauthenticated',identity.profile_payload,result,metadata,now=200,expected_context=CONTEXT)

    def test_me_and_profile_share_exact_canonical_context_and_safe_fields(self):
        result, metadata = resolved(),session()
        me = identity.authenticated_payload(result,metadata,now=120)
        profile = identity.profile_payload(result,metadata,now=120,expected_context=CONTEXT)
        self.assertEqual(me,dict(auth_version=2,phase='authenticated',authenticated=True,
            member=dict(member_id='101',nickname='회원',email=None,via='kakao'),
            auth_context=dict(member_id='101',session_context_id=CONTEXT,principal_revision='1')))
        self.assertEqual(profile,dict(auth_version=2,auth_context=me['auth_context'],
                                      profile=dict(member_id='101',nickname='회원',email=None)))
        for text in [STABLE,'fixture-Opaque-subject','fixture-app-v1','identity_id','verified_at','session_id']:
            self.assertNotIn(text,json.dumps(me)+json.dumps(profile))

    def test_full_bigint_member_and_revision_remain_strings_in_every_public_field(self):
        number = identity.MAX_BIGINT
        result = resolved(member=member(member_id=number,principal_revision=number))
        metadata = session(member_id=number,issued_auth_revision=number)
        payload = identity.profile_payload(result,metadata,now=120,expected_context=CONTEXT)
        self.assertEqual(payload['profile']['member_id'],str(number))
        self.assertEqual(payload['auth_context']['member_id'],str(number))
        self.assertEqual(payload['auth_context']['principal_revision'],str(number))

    def test_context_uuid_is_canonical_and_does_not_accept_secrets_or_coerce_objects(self):
        for value in [None,CONTEXT.upper(),'{'+CONTEXT+'}',CONTEXT.replace('-',''),'private-token',17]:
            # This sample UUID is digit-only, so uppercase would be identical.
            if value==CONTEXT: continue
            self.rejected(422,'invalid_identity_context',session,session_context_id=value)
        self.rejected(422,'invalid_identity_context',member,auth_subject='ABCDEFAB-1234-4234-8234-ABCDEFABCDEF')

    def test_invalid_verification_and_session_epoch_forms_are_not_coerced(self):
        for value in [None,-1,False,100.0,'100',identity.MAX_BIGINT+1]:
            self.rejected(422,'invalid_identity_time',identity.VerifiedPrincipal._from_server_verifier,
                          registration(),subject='fixture-sub',verified_at=value)
            self.rejected(422,'invalid_identity_time',session,issued_at=value)
        self.rejected(422,'invalid_identity_time',session,expires_at=100)

    def test_client_mutation_of_returned_payload_cannot_change_trusted_inputs_or_next_response(self):
        result, metadata = resolved(),session()
        payload = identity.authenticated_payload(result,metadata,now=120)
        payload['member']['member_id']='999'; payload['auth_context']['session_context_id']=ROTATED
        fresh = identity.authenticated_payload(result,metadata,now=120)
        self.assertEqual(fresh['member']['member_id'],'101')
        self.assertEqual(fresh['auth_context']['session_context_id'],CONTEXT)

    def test_signed_out_and_unavailable_payloads_never_have_member_or_context(self):
        self.assertEqual(identity.unavailable_payload(),dict(auth_version=2,phase='unavailable',authenticated=False,
                                                           member=None,auth_context=None,reason='auth_unavailable'))
        self.assertEqual(identity.signed_out_payload(),dict(auth_version=2,phase='signed-out',authenticated=False,
                                                          member=None,auth_context=None))

    def test_runtime_verifier_stays503_with_flags_or_positive_fixture_inputs(self):
        runtime = identity.RuntimeIssuerVerifier()
        with patch.dict('os.environ',{'CUSTOMER_AUTH_V2_ENABLED':'1','CUSTOMER_PROFILE_READ_ENABLED':'1'}):
            for proof in [principal(),{'verified':True,'member_id':'101'},'explicit-fixture-proof',None]:
                self.rejected(503,'auth_unavailable',runtime.verify,proof)

    def test_import_uses_only_stdlib_and_no_db_network_env_secret_or_router_initialization(self):
        source = Path(identity.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        modules = {n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
        self.assertEqual(modules,{'dataclasses','re','typing','uuid'})
        self.assertNotIn('router',vars(identity))
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertTrue(calls.isdisjoint({'connect','begin','commit','rollback','getenv','load_dotenv','urlopen'}))
        # Execute a fresh module without reloading the shared public module:
        # combined suites may already hold references to its immutable types.
        sentinel = object()
        before_db = sys.modules.get('api.db',sentinel)
        name = '_c1_pure_import_probe'
        self.assertNotIn(name,sys.modules)
        spec = importlib.util.spec_from_file_location(name,identity.__file__)
        candidate = importlib.util.module_from_spec(spec)
        sys.modules[name] = candidate
        try:
            spec.loader.exec_module(candidate)
            self.assertIs(sys.modules.get('api.db',sentinel),before_db)
            with self.assertRaises(candidate.IdentityError) as caught:
                candidate.RuntimeIssuerVerifier().verify('private-token')
            self.assertEqual((caught.exception.status,caught.exception.code),(503,'auth_unavailable'))
        finally:
            sys.modules.pop(name,None)


if __name__ == '__main__': unittest.main()
