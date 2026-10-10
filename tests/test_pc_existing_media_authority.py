"""New adapter tests only: no real auth import, SQLAlchemy engine, DB or cloud."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from api.pc_existing_media_authority import (
    ServerContext, SessionAuthority, FieldPin, CasePins, ExplicitCaseReader,
)
from api.pc_existing_media_import import Denied, Principal, ServerAuthority
from tools.register_existing_pc_media import Decision, ReuseSubject


class Connection:
    def __init__(self, row):
        self.row, self.calls = row, []
    def execute(self, sql, params):
        assert sql.startswith('SELECT ')
        assert not any(x in sql.upper() for x in ('UPDATE ', 'INSERT ', 'DELETE ', 'FOR UPDATE'))
        self.calls.append((sql, params))
        return self
    def mappings(self): return self
    def first(self): return copy.deepcopy(self.row)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.shim = patch.dict(sys.modules, {'sqlalchemy':SimpleNamespace(text=lambda x:x),
            'api.db':None, 'api.auth':None})
        self.shim.start(); self.addCleanup(self.shim.stop)
        self.context = ServerContext('server-secret-session', 42, 'operator', 'same-origin')
        self.adapter = SessionAuthority(lambda:self.context, idle_minutes_reader=lambda:480)
        self.principal = Principal(42,'operator')
        self.subject = ReuseSubject(None,None)
        self.conn = Connection(dict(operator_id=42,role='operator',status='활성',
            revoked=False,expired=False,idle=False))
    def verify(self):
        return self.adapter.verify_registration(self.subject,self.principal,self.conn)
    def test_same_connection_select_only_existing_schema(self):
        self.assertIs(self.verify(),Decision.ALLOW)
        self.assertEqual(len(self.conn.calls),1)
        sql,params=self.conn.calls[0]
        for value in ('admin_sessions s JOIN admin_operators o USING (operator_id)',
            's.revoked_at IS NOT NULL','s.expires_at <= now()',
            "s.last_seen_at <= now() - :idle * interval '1 minute'",'s.session_id=:s'):
            self.assertIn(value,sql)
        self.assertEqual(params,dict(s='server-secret-session',idle=480))
    def test_each_transaction_revalidates_revoke(self):
        self.assertIs(self.verify(),Decision.ALLOW)
        final=Connection({**self.conn.row,'revoked':True})
        with self.assertRaises(Denied):
            self.adapter.verify_registration(self.subject,self.principal,final)
        self.assertEqual(len(final.calls),1)
    def test_missing_session(self):
        self.conn.row=None
        with self.assertRaises(Denied):self.verify()
    def test_expired_idle_and_revoked(self):
        for key in ('expired','idle','revoked'):
            with self.subTest(key=key):
                self.conn.row[key]=True
                with self.assertRaises(Denied):self.verify()
                self.conn.row[key]=False
    def test_unknown_flags_fail_closed(self):
        for value in (None,0,'false'):
            self.conn.row['expired']=value
            with self.assertRaises(Denied):self.verify()
    def test_inactive_pending(self):
        for status in ('정지','대기',None):
            self.conn.row['status']=status
            with self.assertRaises(Denied):self.verify()
    def test_role_changed_even_promotion(self):
        for role in ('viewer','owner',None):
            self.conn.row['role']=role
            with self.assertRaises(Denied):self.verify()
    def test_different_operator(self):
        self.conn.row['operator_id']=43
        with self.assertRaises(Denied):self.verify()
    def test_owner_retains_existing_write_role(self):
        self.context=replace(self.context,role='owner'); self.conn.row['role']='owner'
        self.principal=Principal(42,'owner')
        self.assertIs(self.verify(),Decision.ALLOW)
    def test_cross_site_denied_before_sql(self):
        self.context=replace(self.context,sec_fetch_site='cross-site')
        with self.assertRaises(Denied):self.verify()
        self.assertFalse(self.conn.calls)
    def test_context_absence_dict_bool_and_seed_fallback_rejected(self):
        for value in (None,True,dict(operator_id=1,role='owner',session_id='body'),
                      ServerContext('',1,'owner',None),ServerContext('s',True,'owner',None)):
            self.context=value
            with self.assertRaises(Denied):self.adapter.operator_reader()
    def test_context_session_cannot_change_between_stages(self):
        self.adapter.operator_reader()
        self.context=replace(self.context,session_id='replacement')
        with self.assertRaises(Denied):self.verify()
    def test_principal_mismatch_and_no_connection(self):
        with self.assertRaises(Denied):
            self.adapter.verify_registration(self.subject,Principal(43,'operator'),self.conn)
        with self.assertRaises(Denied):
            self.adapter.verify_registration(self.subject,self.principal,None)
    def test_no_cli_or_request_body_injection_surface(self):
        with self.assertRaises(TypeError):SessionAuthority(actor=1,role='owner')
        with self.assertRaises(TypeError):self.adapter.verify_registration(
            self.subject,self.principal,self.conn,session_id='body')
        self.assertNotIn('server-secret-session',repr(self.context))
    def test_reuse_unwired_even_for_authorized_registration(self):
        self.assertIs(self.verify(),Decision.ALLOW)
        self.assertIs(self.adapter.verify_reuse(self.subject,self.principal,self.conn),Decision.UNKNOWN)
        runtime=ServerAuthority(self.adapter.verify_reuse,self.adapter.operator_reader,
            self.adapter.verify_registration)
        with self.assertRaises(Denied):runtime.verify_reuse(self.subject,self.principal,self.conn)
    def test_default_idle_reads_existing_auth_constant(self):
        with patch.dict(sys.modules, {'api.auth':SimpleNamespace(IDLE_MINUTES=480)}):
            adapter=SessionAuthority(lambda:self.context)
            self.assertIs(adapter.verify_registration(self.subject,self.principal,self.conn),Decision.ALLOW)
        self.assertEqual(self.conn.calls[0][1]['idle'],480)
    def test_missing_fetch_site_keeps_existing_policy(self):
        self.context=replace(self.context,sec_fetch_site=None)
        self.assertIs(self.verify(),Decision.ALLOW)
    def test_invalid_idle_configuration(self):
        self.adapter._idle_minutes_reader=lambda:True
        with self.assertRaises(Denied):self.verify()


class CaseTests(unittest.TestCase):
    def setUp(self):
        # Synthetic explicit evidence tests, never selected production CASE facts.
        self.content=dict(facts=[dict(value=x) for x in
            ('DAVEN N1 MESH','black','closed_mesh_opaque','N1_MESH')])
        h=hashlib.sha256(json.dumps(self.content,ensure_ascii=False,sort_keys=True,
            separators=(',',':')).encode()).hexdigest()
        fields=[FieldPin(('facts',i,'value'),v,'test-evidence:field/'+str(i))
            for i,v in enumerate(('DAVEN N1 MESH','black','closed_mesh_opaque','N1_MESH'))]
        self.pins=CasePins(129552,'a'*64,h,*fields)
        self.row=dict(source_product_code=129552,source_fingerprint='a'*64,content=self.content)
        self.conn=Connection(None)
    def read(self,pins=None):return ExplicitCaseReader([pins or self.pins])(self.conn,self.row)
    def test_actual_explicit_fields_with_all_pinned_references(self):
        value=self.read(); self.assertEqual(value.model,'DAVEN N1 MESH')
        self.assertEqual(value.color,'black'); self.assertFalse(self.conn.calls)
        ref=json.loads(value.source_reference)
        self.assertEqual(ref['source_fingerprint'],'a'*64)
        self.assertEqual(ref['content_sha256'],self.pins.content_sha256)
        self.assertEqual(ref['fields']['side_panel']['path'],['facts',2,'value'])
        self.assertEqual(ref['fields']['front']['reference'],'test-evidence:field/3')
    def test_source_fingerprint_unknown_or_changed(self):
        for value in (None,'','b'*64):
            self.row['source_fingerprint']=value
            with self.assertRaises(Denied):self.read()
    def test_content_change_even_unchanged_fingerprint(self):
        self.row['content']['facts'][1]['value']='white'
        with self.assertRaises(Denied):self.read()
    def test_field_absence_no_inference_from_name(self):
        p=replace(self.pins,model=replace(self.pins.model,path=('name',)))
        with self.assertRaises(Denied):self.read(p)
    def test_pinned_expected_value_is_not_returned_without_actual_match(self):
        p=replace(self.pins,color=replace(self.pins.color,value='white'))
        with self.assertRaises(Denied):self.read(p)
    def test_missing_reference_unknown_value_and_boolean_path(self):
        for field in (replace(self.pins.front,reference=''),replace(self.pins.front,value='unknown'),
                      replace(self.pins.front,path=('facts',True,'value'))):
            with self.assertRaises(Denied):self.read(replace(self.pins,front=field))
    def test_case_id_and_unbound_case_denied(self):
        for value in (129551,True,None):
            self.row['source_product_code']=value
            with self.assertRaises(Denied):self.read()
    def test_duplicate_pins_and_missing_connection(self):
        with self.assertRaises(Denied):ExplicitCaseReader([self.pins,self.pins])(self.conn,self.row)
        with self.assertRaises(Denied):ExplicitCaseReader([self.pins])(None,self.row)
    def test_same_field_cannot_fill_all_exterior_fields(self):
        with self.assertRaises(Denied):self.read(replace(self.pins,color=self.pins.model))
    def test_prose_is_not_parsed_or_guessed(self):
        p=replace(self.pins,color=replace(self.pins.color,value='black case, probably white'))
        with self.assertRaises(Denied):self.read(p)
    def test_actual_prose_cannot_be_normalized_by_pin(self):
        self.content['facts'][1]['value']='probably black or white'
        h=hashlib.sha256(json.dumps(self.content,ensure_ascii=False,sort_keys=True,
            separators=(',',':')).encode()).hexdigest()
        p=replace(self.pins,content_sha256=h,
            color=replace(self.pins.color,value='probably black or white'))
        with self.assertRaises(Denied):self.read(p)
    def test_default_no_case_pins_denied(self):
        with self.assertRaises(Denied):ExplicitCaseReader([])(self.conn,self.row)


if __name__=='__main__':unittest.main()
