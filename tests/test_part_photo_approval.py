"""Exact photo approval + original 0130 readers/digest on SQL MOCK ports.

No PG, storage, credentials, application/auth import or migration execution.
All image/provenance/rights fixtures are MOCK, never operating approvals.
"""
import ast
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_photo_original_fixture',ROOT/'tests/test_part_explanation_approval.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
PNG = b'\x89PNG\r\n\x1a\nMOCK-current-detail-bytes'
RIGHTS = 'workroom:MOCK-company-sales-attestation@v1:'+'b'*64


class Connection(fixture.Connection):
    def __init__(self, part):
        super().__init__(part)
        self.photo_events=[]; self.photo_fail=None; self.after_append=None
        for code,e in self.explanations.items():
            prefix=f'products/{code}/'+('a'*16)+'/'
            e['content'].update(image_url=f'https://merchant.example/{code}.png', image_asset=dict(
                bucket='popcorn-ai-product-media-045e861b',sha256='a'*64,detail_sha256=hashlib.sha256(PNG).hexdigest(),
                original_key=prefix+'original.png',detail_key=prefix+'detail.png',thumbnail_key=prefix+'thumb.webp',
                original_size=[20,20],detail_size=[16,16],crop_box=[2,2,18,18],crop_mode='uniform_margin',
                prepared_at=fixture.PAST.isoformat()))
        self.before_photo=deepcopy((self.explanations,self.products,self.events,self.photo_events))

    def execute(self, statement, params=None):
        q=str(statement); p=params or {}
        if not q.startswith('/*part_photo:'): return super().execute(statement,params)
        self.calls.append((q,deepcopy(p)))
        tag=q.split('*/',1)[0].split(':',1)[1]
        if tag==self.photo_fail: raise self.error
        if tag=='latest':
            return fixture.Result(deepcopy(sorted((e for e in self.photo_events if e['source_product_code']==p['code']),
                                                  key=lambda e:e['event_seq'],reverse=True)[:1]))
        if tag=='request': return fixture.Result([deepcopy(e) for e in self.photo_events if e['request_id']==p['uid']])
        if tag=='append':
            if any(e['request_id']==p['uid'] for e in self.photo_events): raise self.error
            event=dict(source_product_code=p['code'],event_seq=p['seq'],request_id=p['uid'],request_digest=p['digest'],
                       action=p['action'],operator_id=p['actor'],recorded_at=self.now,note=p['note'],
                       source_basis=p['source_basis'],approval_basis=p['basis'],snapshot=json.loads(p['snapshot']),write_txid=99)
            self.photo_events.append(event)
            if self.after_append: self.after_append()
            return fixture.Result([deepcopy(event)])
        raise AssertionError('unexpected photo SQL '+tag)

    def caller_discards_failed_tx(self):
        self.explanations,self.products,self.events,self.photo_events=deepcopy(self.before_photo)


class PhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous={k:v for k,v in sys.modules.items() if k==fixture.PACKAGE or k.startswith(fixture.PACKAGE+'.')}
        cls.original,cls.part,cls.copy=fixture.load_sources()
        fixture.selected('product_images','api/product_images.py',(),('MEDIA_BUCKET',))
        spec=importlib.util.spec_from_file_location(fixture.PACKAGE+'.part_photo_approval',ROOT/'api/part_photo_approval.py')
        cls.core=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cls.core;spec.loader.exec_module(cls.core)

    @classmethod
    def tearDownClass(cls):
        for k in list(sys.modules):
            if k==fixture.PACKAGE or k.startswith(fixture.PACKAGE+'.'): del sys.modules[k]
        sys.modules.update(cls.previous)

    def setUp(self):
        self.conn=Connection(self.part);self.bytes=PNG;self.image_calls=[]

    def provenance(self,conn,*,row,expected_basis):
        self.assertIs(conn,self.conn)
        return self.core.PhotoProvenance(row['source_product_code'],row['product_code'],expected_basis,
            'registered_product_photo','product-image-manifest:MOCK-current-version',RIGHTS)

    def image(self,asset,code,variant):
        self.image_calls.append((deepcopy(asset),code,variant));return self.bytes

    def ports(self):
        return dict(provenance_reader=self.provenance,image_reader=self.image,business_rights_reference=RIGHTS)

    def read(self,code=11,**ports):
        return self.core.read_current(self.conn,code,**(self.ports()|ports))

    def request(self,code=11,**updates):
        current=self.read(code)
        body=dict(expected_seq=current['event_seq'],expected_basis=current['basis'],request_id=str(uuid4()),
                  note='MOCK same product and current registered bytes',actor=deepcopy(self.conn.actor),**self.ports())
        body.update(updates);return body

    def approve(self,code=11,**updates): return self.core.approve(self.conn,code,**self.request(code,**updates))
    def revoke(self,seq=1,**updates):
        body=dict(expected_seq=seq,request_id=str(uuid4()),note='MOCK photo withdraw',actor=deepcopy(self.conn.actor))
        body.update(updates);return self.core.revoke(self.conn,11,**body)

    def error(self,status,fn,*args,**kwargs):
        with self.assertRaises(HTTPException) as caught:fn(*args,**kwargs)
        self.assertEqual(caught.exception.status_code,status);return caught.exception.detail

    def test_exact_actor_dbtime_bytes_and_no_native_description_changes(self):
        before=deepcopy((self.conn.explanations,self.conn.products))
        result=self.approve()
        self.assertFalse(result['committed']);self.assertFalse(result['replayed']);self.assertTrue(result['current']['allowed'])
        self.assertEqual(result['event']['operator_id'],2**40)
        self.assertEqual(result['event']['recorded_at'],fixture.NOW.isoformat())
        self.assertEqual(before,(self.conn.explanations,self.conn.products))
        self.assertFalse(self.part.can_publish(self.conn.row(11)))
        self.assertEqual({(code,variant) for asset,code,variant in self.image_calls},{(11,'detail')})

    def test_original_digest_algorithm_and_lock_order(self):
        self.approve()
        tags=[q.split('*/',1)[0].split(':',1)[1] for q,p in self.conn.calls]
        start=tags.index('catalog_lock')
        self.assertEqual(tags[start:start+5],['catalog_lock','row','product_lock','row','actor'])
        model=self.core._model(self.conn.row(11))
        self.assertEqual(self.core.basis(self.conn.row(11)),self.copy.digest(dict(version=self.core.VERSION,scope=self.core.SCOPE,model=model)))

    def test_unapproved_and_unconnected_do_not_grant_authority(self):
        self.assertFalse(self.read()['allowed'])
        self.error(503,self.approve,image_reader=None)
        self.assertEqual(self.conn.photo_events,[])
        self.approve()
        self.assertFalse(self.core.read_current(self.conn,11)['allowed'])

    def test_rights_is_existing_server_reference_not_boolean_or_merchant_url(self):
        for reference in (None,True,'https://merchant.example/rights','workroom:missing-version'):
            with self.subTest(reference=reference): self.error(503,self.approve,business_rights_reference=reference)

    def test_provenance_reader_client_dict_bool_and_merchant_only_rejected(self):
        for value in (True,dict(verified=True),None):
            with self.subTest(value=value):self.error(422,self.approve,provenance_reader=lambda *a,**k:value)
        def merchant(conn,**kwargs):return replace(self.provenance(conn,**kwargs),source_reference='https://merchant.example/photo.png')
        self.error(422,self.approve,provenance_reader=merchant)

    def test_provenance_identity_basis_kind_and_rights_must_match(self):
        for change in (dict(source_product_code=12),dict(product_code=102),dict(product_code=True),
                       dict(basis='c'*64),dict(kind='ai_render'),dict(rights_reference=RIGHTS+'x')):
            with self.subTest(change=change):
                def wrong(conn,**kwargs):return replace(self.provenance(conn,**kwargs),**change)
                self.error(422,self.approve,provenance_reader=wrong)

    def test_fake_inactive_viewer_actor_denied_by_real_db_recheck(self):
        for actor in (dict(operator_id=True,role='operator',status='활성'),dict(operator_id=1,role='operator',status='활성'),
                      dict(operator_id=2**40,role='viewer',status='활성'),dict(operator_id=2**40,role='operator',status='중지')):
            with self.subTest(actor=actor):self.error(403,self.approve,actor=actor)
        self.conn.actor['status']='중지';self.error(403,self.approve)

    def test_missing_asset_or_each_required_key_rejected(self):
        asset=deepcopy(self.conn.explanations[11]['content']['image_asset'])
        for key in ('bucket','sha256','detail_sha256','original_key','detail_key','thumbnail_key','prepared_at'):
            with self.subTest(key=key):
                self.conn.explanations[11]['content']['image_asset']=deepcopy(asset)
                del self.conn.explanations[11]['content']['image_asset'][key]
                self.error(422,self.approve)
        self.conn.explanations[11]['content']['image_asset']=None;self.error(422,self.approve)

    def test_wrong_bucket_version_code_and_hash_format(self):
        asset=deepcopy(self.conn.explanations[11]['content']['image_asset'])
        for change in (dict(bucket='public-other'),dict(sha256='A'*64),dict(detail_sha256='bad'),
                       dict(detail_key=asset['detail_key'].replace('/11/','/12/')),
                       dict(original_key=asset['original_key'].replace('a'*16,'c'*16)),
                       dict(thumbnail_key='https://merchant.example/photo')):
            with self.subTest(change=change):
                self.conn.explanations[11]['content']['image_asset']=asset|change;self.error(422,self.approve)

    def test_crop_and_size_metadata_require_native_values(self):
        asset=deepcopy(self.conn.explanations[11]['content']['image_asset'])
        for change in (dict(crop_box=[0,0,30,20]),dict(detail_size=[20,20]),dict(original_size=[True,20]),
                       dict(crop_mode='ai_regeneration'),dict(prepared_at='missing timezone')):
            with self.subTest(change=change):
                self.conn.explanations[11]['content']['image_asset']=asset|change;self.error(422,self.approve)

    def test_current_detail_bytes_type_signature_size_and_digest(self):
        for data in (True,bytearray(PNG),b'\x89PNG\r\n\x1a\n',b'not PNG',PNG+b'changed',b'x'*(10*1024*1024+1)):
            with self.subTest(length=len(data) if hasattr(data,'__len__') else None):
                self.bytes=data;self.error(422,self.approve)
        self.assertEqual(self.conn.photo_events,[])

    def test_same_uuid_replay_does_not_append_and_reports_fresh_current(self):
        request=self.request();first=self.core.approve(self.conn,11,**request)
        second=self.core.approve(self.conn,11,**request)
        self.assertTrue(second['replayed']);self.assertEqual(first['event'],second['event'])
        self.assertTrue(second['current']['allowed']);self.assertEqual(len(self.conn.photo_events),1)

    def test_changed_uuid_payload_note_basis_rights_seq_or_target_conflicts(self):
        request=self.request();self.core.approve(self.conn,11,**request)
        for change in (dict(note=request['note']+' '),dict(expected_seq=1),dict(expected_basis='c'*64),
                       dict(business_rights_reference=RIGHTS.replace('b'*64,'c'*64))):
            with self.subTest(change=change): self.error(409,self.core.approve,self.conn,11,**(request|change))
        self.error(409,self.core.approve,self.conn,12,**request)

    def test_raw_note_uuid_digest_preserves_whitespace_before_stored_trim(self):
        request=self.request(note=' MOCK approve ');self.core.approve(self.conn,11,**request)
        self.error(409,self.core.approve,self.conn,11,**(request|dict(note='MOCK approve')))

    def test_expected_seq_and_basis_prevent_old_screen_approval(self):
        request=self.request();self.approve()
        self.error(409,self.core.approve,self.conn,11,**request)
        self.error(409,self.approve,expected_basis='c'*64)

    def test_revoke_does_not_require_current_bytes_or_rights_and_changes_no_source(self):
        self.approve();before=deepcopy(self.conn.explanations)
        self.conn.explanations[11]['content']['image_asset']=None
        self.bytes=None;result=self.revoke()
        self.assertEqual(result['current']['state'],'revoked');self.assertFalse(result['current']['allowed'])
        self.assertIsNone(self.conn.explanations[11]['content']['image_asset'])
        self.assertEqual(result['event']['snapshot'],self.conn.photo_events[0]['snapshot'])
        self.assertEqual(before[11]['status'],self.conn.explanations[11]['status'])

    def test_old_approve_replay_after_revoke_cannot_restore_current(self):
        request=self.request();self.core.approve(self.conn,11,**request);self.revoke()
        result=self.core.approve(self.conn,11,**request)
        self.assertTrue(result['replayed']);self.assertEqual(result['current']['state'],'revoked')
        self.assertFalse(result['current']['allowed']);self.assertEqual(len(self.conn.photo_events),2)

    def test_old_revoke_replay_after_new_approval_keeps_new_current(self):
        self.approve();request=dict(expected_seq=1,request_id=str(uuid4()),note='MOCK revoke',actor=self.conn.actor)
        self.core.revoke(self.conn,11,**request);self.approve()
        result=self.core.revoke(self.conn,11,**request)
        self.assertTrue(result['replayed']);self.assertEqual(result['current']['state'],'unknown')
        self.assertTrue(self.read()['allowed']);self.assertEqual(len(self.conn.photo_events),3)

    def test_revoke_changed_request_or_stale_sequence_conflict(self):
        self.approve();request=dict(expected_seq=1,request_id=str(uuid4()),note='MOCK revoke',actor=self.conn.actor)
        self.core.revoke(self.conn,11,**request)
        self.error(409,self.core.revoke,self.conn,11,**(request|dict(note='changed')))
        self.error(409,self.revoke,seq=1)

    def test_missing_null_retired_non_selling_and_stale_models_failclosed(self):
        self.conn.explanations[11]['product_code']=None;self.error(422,self.approve)
        self.conn.explanations[11]['product_code']=101;self.conn.explanations[11]['status']='retired';self.error(422,self.approve)
        self.conn.explanations[11]['status']='draft';self.conn.products[101]['status']='품절';self.error(422,self.approve)
        self.conn.products[101]['status']='판매중';self.conn.products[101]['spec_source_text']='NEW';self.error(422,self.approve)

    def test_assembly_only_photo_keeps_rights_and_bytes_checks(self):
        e=self.conn.explanations[11]; e['product_code']=None; e['content']['availability_scope']='assembly_only'
        self.assertIsNone(self.core._model_reason(self.conn.row(11)))
        for reference in (None,'https://merchant.example/rights'):
            with self.subTest(reference=reference): self.error(503,self.approve,business_rights_reference=reference)
        self.bytes=PNG+b'changed'; self.error(422,self.approve); self.bytes=PNG
        self.assertEqual(self.conn.photo_events,[])
        result=self.approve()
        self.assertTrue(result['current']['allowed'])
        snapshot=result['event']['snapshot']
        self.assertIsNone(snapshot['model']['product_code']); self.assertIsNone(snapshot['provenance']['product_code'])
        self.assertEqual(snapshot['provenance']['rights_reference'],RIGHTS)
        self.assertTrue(self.read()['allowed'])
        e['content']['availability_scope']='retail'
        self.assertEqual(self.read()['state'],'stale')

    def test_missing_explanation_is_404(self):
        self.error(404,self.read,99)

    def test_asset_version_or_bytes_change_makes_approval_stale(self):
        self.approve();self.bytes=PNG+b'new';self.assertFalse(self.read()['allowed'])
        self.bytes=PNG;self.conn.explanations[11]['content']['image_asset']['prepared_at']=fixture.NOW.isoformat()
        self.assertEqual(self.read()['state'],'stale')

    def test_new_model_with_same_bytes_is_not_old_photo_approval(self):
        self.approve();e=self.conn.explanations[11];self.conn.products[101]['spec_source_text']='NEW'
        e['source_snapshot']['spec']='NEW';e['source_fingerprint']=self.part.fingerprint('CPU','NEW')
        self.assertEqual(self.read()['state'],'stale');self.assertFalse(self.read()['allowed'])

    def test_description_edit_and_native_approval_do_not_create_or_erase_photo_authority(self):
        self.approve();e=self.conn.explanations[11];e['content']['role']='new actual description'
        self.assertTrue(self.read()['allowed'])
        request=dict(expected_seq=0,expected_basis=self.original.basis(self.conn.row(11)),request_id=str(uuid4()),
                     note='MOCK description approval',actor=self.conn.actor)
        self.original.approve(self.conn,11,**request)
        self.assertTrue(self.read()['allowed']);self.revoke()
        self.assertEqual(e['status'],'approved');self.assertTrue(self.part.can_publish(self.conn.row(11)))

    def test_current_provenance_reference_change_is_stale(self):
        self.approve()
        def changed(conn,**kwargs):return replace(self.provenance(conn,**kwargs),source_reference='manifest:MOCK-next-version')
        self.assertEqual(self.read(provenance_reader=changed)['state'],'stale')

    def test_withdrawal_observed_during_bytes_read_denies_old_approval(self):
        self.approve();self.revoke();withdrawal=self.conn.photo_events.pop()
        def changed(asset,code,variant):
            self.conn.photo_events.append(deepcopy(withdrawal));return PNG
        current=self.read(image_reader=changed)
        self.assertEqual(current['state'],'revoked');self.assertEqual(current['event_seq'],2)
        self.assertFalse(current['allowed']);self.assertIsNone(current['reference'])

    def test_new_approval_observed_during_bytes_read_requires_retry(self):
        self.approve();self.approve();new_approval=self.conn.photo_events.pop()
        def changed(asset,code,variant):
            self.conn.photo_events.append(deepcopy(new_approval));return PNG
        current=self.read(image_reader=changed)
        self.assertEqual(current['state'],'stale');self.assertEqual(current['event_seq'],2)
        self.assertFalse(current['allowed']);self.assertTrue(self.read()['allowed'])

    def test_bytes_or_provenance_reader_failure_is_unknown_without_error_data(self):
        self.approve()
        def failed(*args,**kwargs):raise RuntimeError('private URL/credential must never exit')
        current=self.read(image_reader=failed)
        self.assertEqual(current['state'],'unknown');self.assertFalse(current['allowed'])
        self.assertNotIn('credential',json.dumps(current));self.assertNotIn('private URL',json.dumps(current))
        self.error(503,self.approve,image_reader=failed)

    def test_callback_source_change_before_append_is_conflict_no_event(self):
        def changed(asset,code,variant):
            self.conn.explanations[11]['content']['image_asset']['prepared_at']=fixture.NOW.isoformat();return PNG
        self.error(409,self.approve,image_reader=changed);self.assertEqual(self.conn.photo_events,[])

    def test_callback_copy_mutation_does_not_change_source_basis(self):
        def provider(conn,**kwargs):
            proof=self.provenance(conn,**kwargs);kwargs['row']['content'].clear();return proof
        self.assertTrue(self.approve(provenance_reader=provider)['current']['allowed'])

    def test_transaction_replacement_callback_is_rejected(self):
        def changed(conn,**kwargs):
            proof=self.provenance(conn,**kwargs);conn.transaction=object();return proof
        self.error(503,self.approve,provenance_reader=changed);self.assertEqual(self.conn.photo_events,[])

    def test_actor_and_join_rechecked_after_native_product_lock(self):
        self.conn.after_product_lock=lambda:self.conn.products[101].update(spec_source_text='NEW')
        self.error(409,self.approve)

    def test_missing_nested_and_autocommit_caller_transaction(self):
        for kind in ('none','nested','autocommit'):
            with self.subTest(kind=kind):
                self.conn.active=kind!='none';self.conn.nested=kind=='nested'
                self.conn.isolation='AUTOCOMMIT' if kind=='autocommit' else 'REPEATABLE READ'
                self.error(503,self.read)

    def test_sql_unique_conflict_propagates_not_false_success(self):
        self.conn.photo_fail='append'
        with self.assertRaisesRegex(RuntimeError,'fake SQL'):self.approve()
        self.assertEqual(self.conn.photo_events,[])

    def test_failure_after_pending_append_requires_whole_caller_rollback(self):
        original=deepcopy((self.conn.explanations,self.conn.products,self.conn.events,self.conn.photo_events))
        self.conn.explanations[12]['content']['role']='MOCK earlier caller write'
        self.conn.after_append=lambda:setattr(self.conn,'photo_fail','latest')
        with self.assertRaises(RuntimeError):self.approve()
        self.assertEqual(len(self.conn.photo_events),1)
        self.conn.caller_discards_failed_tx()
        self.assertEqual(original,(self.conn.explanations,self.conn.products,self.conn.events,self.conn.photo_events))

    def test_corrupt_event_digest_is_not_current_authority(self):
        self.approve();self.conn.photo_events[0]['snapshot']['provenance']['source_reference']='manifest:tampered'
        self.error(503,self.read)

    def test_current_proof_has_no_bytes_keys_model_or_public_permission(self):
        self.approve();current=self.read();encoded=json.dumps(current)
        for key in ('image_url','image_asset','detail_key','thumbnail_key','snapshot','detail_bytes','content','customer_publishable'):
            self.assertNotIn(key,encoded)
        self.assertEqual(current['scope'],'registered_product_photo');self.assertTrue(current['allowed'])

    def test_source_has_no_route_tx_factory_network_or_native_edits(self):
        source=(ROOT/'api/part_photo_approval.py').read_text(encoding='utf-8');tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                self.assertNotIn(node.func.attr,('connect','begin','commit','rollback','close'))
        self.assertNotRegex(source,r'UPDATE\s+product_explanations|DELETE\s+FROM|APIRouter|AuthorizedSession|google.auth')

    def test_migration_revision_fk_shape_bigint_and_source_only(self):
        source=(ROOT/'db/migrations/versions/0131_part_photo_approval.py').read_text(encoding='utf-8')
        ast.parse(source)
        for value in ("revision = '0131'","down_revision = '0130'",'pg_catalog.pg_attribute','pg_catalog.pg_constraint',
                      "'pg_catalog.int8'::regtype",'REFERENCES __S__.product_explanations(source_product_code)',
                      'operator_id BIGINT','REFERENCES __S__.admin_operators(operator_id)','request_id UUID NOT NULL UNIQUE',
                      'PRIMARY KEY(source_product_code,event_seq)','NEW.recorded_at IS DISTINCT FROM now()',
                      'NEW.write_txid IS DISTINCT FROM txid_current()',"previous.action IS DISTINCT FROM 'approve'",
                      'BEFORE INSERT OR UPDATE OR DELETE','BEFORE TRUNCATE',"SET search_path=pg_catalog"):
            self.assertIn(value,source)
        self.assertNotRegex(source,r'ALTER TABLE|UPDATE\s+__S__\.product_explanations|DROP TABLE|GRANT ')

    def test_migration_schema_rejects_injection_and_downgrade_preserves_history(self):
        source=ast.parse((ROOT/'db/migrations/versions/0131_part_photo_approval.py').read_text(encoding='utf-8'))
        namespace={'re':re,'text':text}
        nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in ('_schema','downgrade')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual_photo_schema','exec'),namespace)
        class Bind:
            def __init__(self,value):self.value=value
            def execute(self,q):
                class Result:
                    def scalar_one(inner):return self.value
                return Result()
        self.assertEqual(namespace['_schema'](Bind('isolated_test')),'"isolated_test"')
        for value in ('a.b','public;DROP',None,True,''):
            with self.subTest(value=value),self.assertRaises(RuntimeError):namespace['_schema'](Bind(value))
        with self.assertRaises(RuntimeError):namespace['downgrade']()


if __name__=='__main__':unittest.main()
