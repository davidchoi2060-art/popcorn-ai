"""New V2 consumer fixtures only; actual I1/SQL/HTTP/runtime remain closed."""
import ast
from dataclasses import replace
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
import unittest

from fastapi import HTTPException


def _deny_live(event, args):
    if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system', 'sqlite3.connect'):
        raise AssertionError('V2 live IO forbidden')
    if event == 'import' and args:
        name = args[0]
        if any(name == n or name.startswith(n+'.') for n in
               ('api.db', 'api.main', 'api.my_account', 'sqlalchemy', 'psycopg', 'psycopg2', 'httpx', 'requests')):
            raise AssertionError('V2 production/HTTP import forbidden')
        if name.startswith('test_') and name != 'test_customer_auth_store_issuance_contract':
            raise AssertionError('V2 completed test import forbidden')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        if str(args[0]).replace('\\','/').lower().rstrip("'").rsplit('/',1)[-1] == '.env':
            raise AssertionError('V2 secret read forbidden')


sys.addaudithook(_deny_live)
from api import customer_auth_store as store
from api import customer_auth as auth
from api import customer_identity as identity
from api import customer_auth_sql_read as q1
from api import customer_auth_provenance as p1


SID = 'a'*64
DIGEST = hashlib.sha256(SID.encode('ascii')).hexdigest()
PROOF = '11111111-1111-4111-8111-111111111111'
CONTEXT = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
SUBJECT = '44444444-4444-4444-8444-444444444444'
AUTHORITY = 'fixture-authority-version-1'


def envelope():
    member = q1.StoredMember(101,SUBJECT,1,'active','fixture member',None)
    mapping = q1.StoredIdentity(17,101,'fixture-app','https://issuer.example.invalid',
        '  opaque-A  ',90,'fixture-proof','fixture-registration',None)
    session = q1.StoredSession(101,17,1,CONTEXT,100,200,None)
    prov = q1.StoredProvenance(mapping.issuer_key,mapping.issuer,mapping.subject,100,
                               mapping.verification_method,mapping.registration_ref)
    bound = q1.IssuanceBinding(PROOF,DIGEST,101,17,CONTEXT,1,100,200)
    return q1.SessionEnvelopeV2(DIGEST,member,(mapping,),session,prov,bound,120,Decimal('120.875'))


def independent_receipt(row):
    b,p=row.issuance_binding,row.provenance
    return p1.AuthorityReceipt(p1.IssuanceBinding(b.proof_ref,b.credential_hash,b.member_id,
        b.verified_identity_id,b.auth_context_id,b.issued_auth_revision,b.issued_at,b.expires_at),
        p1.IssuanceProvenance(p.issuer_key,p.issuer,p.subject,p.verified_at,p.verification_method,p.registration_ref),AUTHORITY)


class FixtureReadSource:
    """Typed server fixture only; no Q1 SQL executor or real query is invoked."""
    def __init__(self):
        self.row=envelope();self.session_calls=[];self.member_calls=[]
        self.ready_value=True;self.close_on_read=False;self.failure=None
        self.member_row=self.row.member
    def schema_ready(self):return self.ready_value
    def member_schema_ready(self):return self.ready_value
    def read_current_session(self,digest):
        self.session_calls.append(digest)
        if self.failure is not None:raise self.failure
        if self.close_on_read:self.ready_value=False
        return self.row
    def read_current_member(self,member_id):
        self.member_calls.append(member_id)
        return self.member_row


class FixtureAuthority:
    def __init__(self):self.receipt=independent_receipt(envelope());self.calls=[]
    def ready(self):return True
    def read_verified_issuance(self,proof_ref):
        self.calls.append(proof_ref)
        return (self.receipt,)


class FixtureI1Restorer:
    """Explicit offline fixture, not approved actual I1 or provider selection."""
    def __init__(self):
        self.calls=[];self.ready_value=True;self.transform=None;self.close_on_restore=False
    def ready(self):return self.ready_value
    def restore_verified_principal(self,evidence):
        self.calls.append(evidence)
        p=evidence.provenance
        registration=identity.IssuerRegistration(p.issuer_key,p.issuer,p.registration_ref,p.verification_method,'email')
        principal=identity.VerifiedPrincipal._from_server_verifier(registration,
            subject=p.subject,verified_at=p.verified_at)
        if self.close_on_restore:self.ready_value=False
        return principal if self.transform is None else self.transform(principal)


class FixtureResultVerifier:
    def __init__(self,result):self.result=result;self.calls=[];self.ready_value=True;self.failure=None
    def ready(self):return self.ready_value
    def verify_issuance(self,provenance,*,binding):
        self.calls.append((provenance,binding))
        if self.failure is not None:raise self.failure
        return self.result


class V2ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.source=FixtureReadSource();self.read=store.Q1ReadBridgeV2(self.source)
        self.authority=FixtureAuthority();self.verifier=p1.IssuanceEvidenceVerifier(self.authority,authority_ref=AUTHORITY)
        self.restorer=FixtureI1Restorer()
        self.principal=store.P1PrincipalBridgeV2(self.verifier,self.restorer,authority_ref=AUTHORITY)
        self.adapter=store.SessionReadAdapterV2(self.read,self.principal,auth.PersistedSessionSnapshot)
        self.resolver=auth.VerifiedSessionResolver(self.adapter,self.principal)

    def closed(self,call):
        with self.assertRaises(HTTPException) as caught:call()
        self.assertEqual(caught.exception.status_code,503)
        self.assertEqual(caught.exception.detail,{'code':'auth_unavailable'})
        self.assertEqual(caught.exception.headers['Cache-Control'],'no-store')
        return caught.exception

    def stored(self):return self.read.read_current_session(DIGEST)

    def evidence(self):
        value=independent_receipt(envelope())
        return p1.VerifiedIssuanceEvidence(value.binding,value.provenance,AUTHORITY)

    def bridge_for_result(self,result):
        return store.P1PrincipalBridgeV2(FixtureResultVerifier(result),self.restorer,authority_ref=AUTHORITY)

    def test_q1_to_store_copies_exact_classes_all_fields_and_original_times(self):
        value=self.stored()
        self.assertIs(type(value),store.StoredSessionReadV2)
        self.assertIs(type(value.member),store.StoredMember)
        self.assertIs(type(value.identities[0]),store.StoredIdentity)
        self.assertIs(type(value.session),store.StoredSession)
        self.assertIs(type(value.provenance),store.StoredProvenance)
        self.assertIs(type(value.issuance_binding),store.StoredIssuanceBindingV2)
        for name in p1.BINDING_FIELDS:self.assertEqual(getattr(value.issuance_binding,name),getattr(self.source.row.issuance_binding,name))
        for name in p1.PROVENANCE_FIELDS:self.assertEqual(getattr(value.provenance,name),getattr(self.source.row.provenance,name))
        self.assertEqual((value.identities[0].verified_at,value.provenance.verified_at,value.now),(90,100,120))
        self.assertEqual(value.observed_epoch_exact,Decimal('120.875'))

    def test_store_to_p1_exact_inputs_and_fresh_receipt_to_fixture_i1(self):
        snapshot=self.adapter.read_verified_session(DIGEST)
        self.assertIs(type(snapshot),auth.PersistedSessionSnapshot)
        e=self.restorer.calls[0]
        self.assertIs(type(e.binding),p1.IssuanceBinding)
        self.assertIs(type(e.provenance),p1.IssuanceProvenance)
        self.assertEqual(self.authority.calls,[PROOF])
        self.assertEqual(snapshot.principal.verified_at,100)
        self.assertEqual(snapshot.now,120)
        self.assertIs(type(snapshot.mappings[0].member),identity.CanonicalMember)
        self.assertIs(type(snapshot.session),identity.SessionContext)

    def test_default_actual_i1_port_stays_unready_and_no_authority_lookup(self):
        bridge=store.P1PrincipalBridgeV2(self.verifier,authority_ref=AUTHORITY)
        value=self.stored()
        self.assertFalse(bridge.ready())
        self.closed(lambda:bridge.restore_verified_principal(value.provenance,binding=value.issuance_binding))
        self.assertEqual(self.authority.calls,[])

    def test_q1_objects_cannot_be_passed_directly_to_p1_bridge(self):
        r=self.source.row
        self.closed(lambda:self.principal.restore_verified_principal(r.provenance,binding=r.issuance_binding))
        self.assertEqual(self.authority.calls,[])

    def test_q1_root_and_nested_wrong_exact_classes_are_closed(self):
        r=self.source.row;stored=self.stored()
        values=[stored,{},replace(r,member=stored.member),replace(r,session=stored.session),
                replace(r,provenance=stored.provenance),replace(r,issuance_binding=stored.issuance_binding),
                replace(r,identities=stored.identities),replace(r,identities=list(r.identities))]
        for value in values:
            with self.subTest(type=type(value).__name__):
                self.source.row=value;self.closed(self.stored)

    def test_same_field_subclass_is_not_an_exact_q1_envelope(self):
        class Derived(q1.SessionEnvelopeV2):pass
        r=envelope()
        self.source.row=Derived(r.credential_hash,r.member,r.identities,r.session,r.provenance,r.issuance_binding,r.now,r.observed_epoch_exact)
        self.closed(self.stored)

    def test_invalid_strict_binding_or_provenance_not_coerced(self):
        for value in (True,'100',Decimal('100.1')):
            with self.subTest(value_type=type(value).__name__):
                self.source.row=replace(envelope(),provenance=replace(envelope().provenance,verified_at=value))
                self.closed(self.stored)
        self.source.row=replace(envelope(),issuance_binding=replace(envelope().issuance_binding,member_id=True))
        self.closed(self.stored)

    def test_session_binding_and_member_identity_joins_are_rechecked(self):
        r=envelope()
        for value in (replace(r,credential_hash='b'*64),
                      replace(r,issuance_binding=replace(r.issuance_binding,auth_context_id=OTHER)),
                      replace(r,member=replace(r.member,member_id=102)),
                      replace(r,identities=(replace(r.identities[0],identity_id=18),)),
                      replace(r,identities=(replace(r.identities[0],registration_ref='other'),)),
                      replace(r,identities=())):
            self.source.row=value;self.closed(self.stored)

    def test_clock_bucket_and_exact_metadata_are_rechecked(self):
        for clock,now in ((Decimal('120.875'),121),(120.875,120),(Decimal('NaN'),120),
                          (Decimal('-1'),-1),(Decimal('120'),True)):
            with self.subTest(clock_type=type(clock).__name__):
                self.source.row=replace(envelope(),observed_epoch_exact=clock,now=now)
                self.closed(self.stored)

    def test_member_only_bridge_returns_old_type_without_receipt_freshness(self):
        member=self.read.read_current_member(101)
        self.assertIs(type(member),store.StoredMember)
        canonical=store.MemberReadAdapter(self.read).read_member(101)
        self.assertIs(type(canonical),identity.CanonicalMember)
        self.assertEqual(self.source.session_calls,[])
        self.assertEqual(self.authority.calls,[])
        self.assertFalse(hasattr(member,'observed_epoch_exact'))

    def test_member_wrong_class_foreign_id_and_readiness_close(self):
        self.source.member_row=replace(self.source.member_row,member_id=102)
        self.closed(lambda:self.read.read_current_member(101))
        self.source.member_row=store.StoredMember(101,SUBJECT,1,'active','fixture')
        self.closed(lambda:self.read.read_current_member(101))
        self.source.ready_value=False
        self.closed(lambda:self.read.read_current_member(101))

    def test_source_becomes_unready_after_read_without_proof_or_i1_use(self):
        self.source.close_on_read=True
        self.closed(lambda:self.adapter.read_verified_session(DIGEST))
        self.assertEqual(self.authority.calls,[])
        self.assertEqual(self.restorer.calls,[])

    def test_source_failure_is_private503_with_no_live_fallback(self):
        self.source.failure=RuntimeError('private DB credential input')
        error=self.closed(lambda:self.adapter.read_verified_session(DIGEST))
        self.assertTrue(error.__suppress_context__)
        self.assertNotIn('private',str(error.detail))

    def test_unknown_digest_stays_none_then_native_c4_401(self):
        self.source.row=None
        self.assertIsNone(self.adapter.read_verified_session(DIGEST))
        with self.assertRaises(HTTPException) as caught:self.resolver.resolve(SID)
        self.assertEqual(caught.exception.status_code,401)
        self.assertEqual(self.authority.calls,[])

    def test_p1_failure_is503_and_never_calls_i1(self):
        verifier=FixtureResultVerifier(None);verifier.failure=p1.IssuanceUnavailable()
        bridge=store.P1PrincipalBridgeV2(verifier,self.restorer,authority_ref=AUTHORITY)
        row=self.stored()
        self.closed(lambda:bridge.restore_verified_principal(row.provenance,binding=row.issuance_binding))
        self.assertEqual(self.restorer.calls,[])

    def test_malformed_evidence_and_nested_classes_are_closed(self):
        e=self.evidence();row=self.stored()
        for value in (True,{},replace(e,binding=row.issuance_binding),replace(e,provenance=row.provenance)):
            bridge=self.bridge_for_result(value)
            self.closed(lambda:bridge.restore_verified_principal(row.provenance,binding=row.issuance_binding))
        self.assertEqual(self.restorer.calls,[])

    def test_result_every_binding_field_is_compared_to_this_read(self):
        e=self.evidence();row=self.stored()
        changes={'proof_ref':OTHER,'credential_hash':'b'*64,'member_id':102,'verified_identity_id':18,
                 'auth_context_id':OTHER,'issued_auth_revision':2,'issued_at':101,'expires_at':201}
        for name,value in changes.items():
            with self.subTest(field=name):
                bridge=self.bridge_for_result(replace(e,binding=replace(e.binding,**{name:value})))
                self.closed(lambda:bridge.restore_verified_principal(row.provenance,binding=row.issuance_binding))
        self.assertEqual(self.restorer.calls,[])

    def test_result_every_provenance_field_is_compared_to_original_issuance(self):
        e=self.evidence();row=self.stored()
        changes={'issuer_key':'other','issuer':'other','subject':'other','verified_at':99,
                 'verification_method':'other','registration_ref':'other'}
        for name,value in changes.items():
            with self.subTest(field=name):
                bridge=self.bridge_for_result(replace(e,provenance=replace(e.provenance,**{name:value})))
                self.closed(lambda:bridge.restore_verified_principal(row.provenance,binding=row.issuance_binding))
        self.assertEqual(self.restorer.calls,[])

    def test_server_expected_authority_ref_cannot_be_selected_from_metadata(self):
        row=self.stored()
        self.assertFalse(hasattr(self.source.row,'authority_ref'))
        bridge=self.bridge_for_result(replace(self.evidence(),authority_ref='other-authority'))
        self.closed(lambda:bridge.restore_verified_principal(row.provenance,binding=row.issuance_binding))
        self.assertEqual(self.restorer.calls,[])

    def test_wrong_principal_type_and_missing_c1_seal_are_closed(self):
        row=self.stored()
        for transform in (lambda p:True,lambda p:{'subject':p.subject},lambda p:object.__new__(identity.VerifiedPrincipal)):
            self.restorer.transform=transform
            self.closed(lambda:self.principal.restore_verified_principal(row.provenance,binding=row.issuance_binding))

    def test_returned_principal_original_six_fields_are_rechecked(self):
        row=self.stored()
        def changed(principal):
            registration=identity.IssuerRegistration(principal.issuer_key,principal.issuer,principal.registration_ref,principal.verification_method,'email')
            return identity.VerifiedPrincipal._from_server_verifier(registration,subject=principal.subject,verified_at=99)
        self.restorer.transform=changed
        self.closed(lambda:self.principal.restore_verified_principal(row.provenance,binding=row.issuance_binding))

    def test_i1_becomes_unready_after_fixture_restore_is_closed(self):
        self.restorer.close_on_restore=True
        self.closed(lambda:self.adapter.read_verified_session(DIGEST))
        self.assertEqual(len(self.restorer.calls),1)

    def test_snapshot_factory_cannot_return_dict_or_change_observation_clock(self):
        for factory in (lambda **kw:kw,
                        lambda **kw:replace(auth.PersistedSessionSnapshot(**kw),now=True),
                        lambda **kw:replace(auth.PersistedSessionSnapshot(**kw),credential_hash='b'*64)):
            adapter=store.SessionReadAdapterV2(self.read,self.principal,factory)
            self.closed(lambda:adapter.read_verified_session(DIGEST))

    def test_current_expired_revoked_inactive_and_revision_remain_native401(self):
        r=envelope()
        for value in (replace(r,now=200,observed_epoch_exact=Decimal('200.2')),
                      replace(r,session=replace(r.session,revoked_at=119)),
                      replace(r,identities=(replace(r.identities[0],revoked_at=119),)),
                      replace(r,member=replace(r.member,status='inactive')),
                      replace(r,member=replace(r.member,auth_revision=2))):
            self.source.row=value
            with self.assertRaises(HTTPException) as caught:self.resolver.resolve(SID)
            self.assertEqual(caught.exception.status_code,401)

    def test_expected_context_change_remains_native409(self):
        with self.assertRaises(HTTPException) as caught:self.resolver.resolve(SID,expected_context=OTHER)
        self.assertEqual(caught.exception.status_code,409)

    def test_query_emit_confirm_repeats_full_chain_and_discards_revoked_state(self):
        initial=self.resolver.resolve(SID)
        before_query=self.resolver.confirm(SID,initial)
        self.read.read_current_member(101)
        self.source.row=replace(self.source.row,session=replace(self.source.row.session,revoked_at=120))
        with self.assertRaises(HTTPException) as caught:self.resolver.confirm(SID,before_query)
        self.assertEqual(caught.exception.status_code,401)
        self.assertEqual(len(self.source.session_calls),3)
        self.assertEqual(len(self.authority.calls),3)
        self.assertEqual(len(self.restorer.calls),3)

    def test_same_bucket_fresh_chain_is_allowed_without_clock_or_evidence_cache(self):
        initial=self.resolver.resolve(SID)
        after=self.resolver.confirm(SID,initial)
        self.assertEqual(initial.now,after.now)
        self.assertEqual(self.source.session_calls,[DIGEST,DIGEST])
        self.assertEqual(self.authority.calls,[PROOF,PROOF])
        self.assertEqual(len(self.restorer.calls),2)

    def test_c4_key_does_not_claim_full_binding_or_event_phase_comparison(self):
        current=self.resolver.resolve(SID)
        self.assertNotIn(PROOF,current.key())
        self.assertNotIn(100,current.key())
        self.assertNotIn(200,current.key())
        self.assertEqual(set(vars(self.adapter)),{'source','principal','snapshot_factory'})

    def test_private_evidence_and_exact_decimal_not_added_to_public_payload(self):
        current=self.resolver.resolve(SID)
        body=identity.authenticated_payload(current.member,current.session,now=current.now)
        rendered=str(body)
        for private in (DIGEST,PROOF,AUTHORITY,'observed_epoch_exact','issuance_binding'):
            self.assertNotIn(private,rendered)

    def test_r1_store_prefix_protocols_and_runtime_ports_still_preserved(self):
        raw=Path(store.__file__).read_bytes()
        self.assertEqual(hashlib.sha256(raw[:8794]).hexdigest(),'e83edba41d066ae7444707d7a55ae5463b7d72db7f5d5d1b1196543a997281d7')
        old=ast.parse(raw[:8794].decode('utf-8'));new=ast.parse(raw.decode('utf-8'))
        self.assertEqual([ast.dump(n) for n in old.body],[ast.dump(n) for n in new.body[:len(old.body)]])
        self.assertFalse(store.RUNTIME_READ_PORT.schema_ready())
        self.assertFalse(store.RUNTIME_PRINCIPAL_PORT.ready())
        self.assertFalse(store.RUNTIME_REVOCATION_PORT.ready())
        self.assertFalse(auth.RUNTIME_RESOLVER.repository.schema_ready())
        self.assertNotIn('api.db',sys.modules)
        self.assertNotIn('api.main',sys.modules)


if __name__ == '__main__':unittest.main()
