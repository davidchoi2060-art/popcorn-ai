"""Native 0130/0131 history -> actual publication core on SQL MOCK ports.

No DB/main/auth module, engines, PG, credentials or storage initialization.
Native event writers run only against MOCK SQL; this is not operating approval.
"""
from copy import deepcopy
from datetime import timezone
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_native_publication_reader_test'


def fixture(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


pub_fixture=fixture('_reader_publication_fixture','tests/test_pc_customer_publication.py')
part_fixture=fixture('_reader_part_fixture','tests/test_part_explanation_approval.py')
photo_fixture=fixture('_reader_photo_fixture','tests/test_part_photo_approval.py')
pub_fixture.PACKAGE=part_fixture.PACKAGE=PACKAGE


class Scalar:
    def __init__(self,value):self.value=value
    def scalar_one(self):return self.value


class Connection(pub_fixture.Connection):
    def __init__(self,copy,part):
        super().__init__(copy,part)
        self.native=photo_fixture.Connection(part)
        self.settings_isolation='repeatable read'
        for p in self.parts:p['explanation_hash']=copy.explanation_digest(self.native.row(p['explanation_code']))

    def execute(self,statement,params=None):
        q=str(statement);p=params or {}
        if q=='SHOW transaction_isolation':
            self.calls.append((q,deepcopy(p)));return Scalar(self.settings_isolation)
        if q.startswith(('/*part_approval:','/*part_photo:')):
            self.calls.append((q,deepcopy(p)));return self.native.execute(statement,params)
        if '/*pc_publication:sources*/' in q or 'SELECT e.*,p.product_name,p.spec_source_text' in q:
            self.calls.append((q,deepcopy(p)))
            return pub_fixture.Result([self.native.row(c) for c in sorted(set(p['codes'])) if self.native.row(c) is not None])
        return super().execute(statement,params)


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous={k:v for k,v in sys.modules.items() if k==PACKAGE or k.startswith(PACKAGE+'.')}
        cls.publication,oldcopy,oldpart,cls.sales,cls.review=pub_fixture.sources()
        cls.part,cls.source_part,cls.copy=part_fixture.load_sources()
        cls.photo=pub_fixture.full('part_photo_approval','api/part_photo_approval.py')
        cls.producer=pub_fixture.full('pc_publication_source_reader','api/pc_publication_source_reader.py')

    @classmethod
    def tearDownClass(cls):
        for k in list(sys.modules):
            if k==PACKAGE or k.startswith(PACKAGE+'.'):del sys.modules[k]
        sys.modules.update(cls.previous)

    def setUp(self):
        self.conn=Connection(self.copy,self.source_part);self.image_calls=[]
        for code in (11,12):
            row=self.conn.native.row(code)
            self.photo.approve(self.conn,code,expected_seq=0,expected_basis=self.photo.basis(row),
                request_id=str(uuid4()),note='MOCK native registered photo',actor=self.conn.actor,
                provenance_reader=self.provenance,image_reader=lambda *a:photo_fixture.PNG,
                business_rights_reference=photo_fixture.RIGHTS)
            self.part.approve(self.conn,code,expected_seq=0,expected_basis=self.part.basis(self.conn.native.row(code)),
                request_id=str(uuid4()),note='MOCK native description',actor=self.conn.actor)
        self.conn.config['content'].pop('_review',None)
        state=self.review.load_review(self.conn,'P10')[3]
        self.conn.config['content']['_review']=dict(state='approved',basis=state['basis'],
            actor=self.conn.actor,at=pub_fixture.NOW.isoformat())
        self.assertTrue(self.review.load_review(self.conn,'P10')[3]['eligible'])
        self.reader=self.producer.make_source_reader(image_reader=self.image,business_rights_reference=photo_fixture.RIGHTS)
        self.conn.calls.clear();self.image_calls.clear()

    def provenance(self,conn,*,row,expected_basis):
        return self.photo.PhotoProvenance(row['source_product_code'],row['product_code'],expected_basis,
            'registered_product_photo','manifest:MOCK-native-current',photo_fixture.RIGHTS)

    def image(self,asset,code,variant):
        self.image_calls.append((deepcopy(asset),code,variant));return photo_fixture.PNG

    def inputs(self):
        cfg,parts,offers,review=self.publication._load(self.conn,'P10')
        return dict(configuration=cfg,parts=parts,offers=offers,review=review,
                    rows={p['explanation_code']:self.conn.native.row(p['explanation_code']) for p in parts if not p['pseudo']})

    def read(self,**updates):return self.reader(self.conn,**(self.inputs()|updates))

    def denied(self,fn=None,*args,**kwargs):
        with self.assertRaises(self.publication._Unavailable):
            (fn or self.read)(*args,**kwargs)

    def publication_approve(self):
        current=self.publication.read_current(self.conn,'P10',source_reader=self.reader)
        return self.publication.approve(self.conn,'P10',expected_seq=current['event_seq'],revision=1,
            review_basis=current['basis'],publication_basis=current['publication_basis'],request_id=str(uuid4()),
            note='MOCK actual producer',actor=self.conn.actor,source_reader=self.reader)

    def test_actual_native_current_latest_typed_refs_scoped_basis_and_utc(self):
        with patch.object(self.part,'read_current',wraps=self.part.read_current) as part_read, \
             patch.object(self.photo,'read_current',wraps=self.photo.read_current) as photo_read:
            proofs=self.read()
        self.assertIs(type(proofs),self.publication.PublicationSources)
        self.assertEqual((part_read.call_count,photo_read.call_count),(2,2))
        inputs=self.inputs()
        for p,desc,image in zip(inputs['parts'],proofs.parts,proofs.photos):
            row=inputs['rows'][p['explanation_code']]
            self.assertEqual(desc.basis,self.publication.component_basis(inputs['configuration'],p,row))
            self.assertEqual(image.basis,self.publication.photo_basis(inputs['configuration'],p,row))
            self.assertNotEqual(desc.basis,self.part.basis(row));self.assertNotEqual(image.basis,self.photo.basis(row))
            self.assertEqual(desc.operator_id,2**40);self.assertIs(desc.approved_at.tzinfo,timezone.utc)
            self.assertTrue(desc.reference.startswith('part-explanation-approval:'))
            self.assertTrue(image.reference.startswith('part-photo-approval:'));self.assertEqual(image.detail_bytes,photo_fixture.PNG)

    def test_actual_publication_core_accepts_producer_without_changing_private_false(self):
        before=deepcopy((self.conn.config,self.conn.parts,self.conn.native.explanations,self.conn.native.products))
        self.assertTrue(self.publication_approve()['current']['allowed'])
        self.assertEqual(before,(self.conn.config,self.conn.parts,self.conn.native.explanations,self.conn.native.products))
        self.assertFalse(self.review.load_review(self.conn,'P10')[3]['customer_publishable'])

    def test_one_invocation_bytes_cache_is_not_reused_on_next_call(self):
        self.read();self.assertEqual(len(self.image_calls),2)
        self.read();self.assertEqual(len(self.image_calls),4)

    def test_same_native_code_multiple_ordinals_has_per_ordinal_proofs_one_fetch(self):
        inputs=self.inputs();duplicate=deepcopy(inputs['parts'][0]);duplicate['ordinal']=8
        proofs=self.read(parts=inputs['parts']+[duplicate])
        self.assertEqual([p.ordinal for p in proofs.parts],[0,1,8]);self.assertEqual(len(self.image_calls),2)
        self.assertNotEqual(proofs.parts[0].basis,proofs.parts[2].basis)

    def test_pseudo_has_no_sku_or_generated_approval(self):
        inputs=self.inputs();pseudo=dict(configuration_id='P10',ordinal=9,slot='SERVICE',quantity=1,pseudo=True)
        proofs=self.read(parts=inputs['parts']+[pseudo]);self.assertEqual(len(proofs.parts),2);self.assertEqual(len(proofs.photos),2)

    def test_missing_native_part_event_is_not_native_metadata_approval(self):
        self.conn.native.events.clear();self.denied()

    def test_part_withdrawal_fails_closed(self):
        inputs=self.inputs()
        self.part.revoke(self.conn,11,expected_seq=1,request_id=str(uuid4()),note='MOCK withdrawn',actor=self.conn.actor)
        self.denied(lambda:self.reader(self.conn,**inputs))

    def test_photo_withdrawal_fails_actual_publication_current(self):
        self.publication_approve()
        self.photo.revoke(self.conn,11,expected_seq=1,request_id=str(uuid4()),note='MOCK withdrawn',actor=self.conn.actor)
        current=self.publication.read_current(self.conn,'P10',source_reader=self.reader)
        self.assertFalse(current['allowed']);self.assertEqual(current['source_state'],'unknown')

    def test_stale_native_row_or_null_link_cannot_match_supplied_rows(self):
        inputs=self.inputs();self.conn.native.explanations[11]['product_code']=None
        self.denied(lambda:self.reader(self.conn,**inputs))

    def test_forged_rows_or_bom_hash_are_not_valid_proof_basis(self):
        inputs=self.inputs();rows=deepcopy(inputs['rows']);rows[11]['approved_by']=1
        self.denied(rows=rows)
        parts=deepcopy(inputs['parts']);parts[0]['explanation_hash']='a'*64;self.denied(parts=parts)

    def test_config_revision_identity_private_state_binding(self):
        inputs=self.inputs()
        for change in (dict(revision=2),dict(configuration_id='Pother'),dict(status='draft')):
            with self.subTest(change=change):self.denied(configuration=inputs['configuration']|change)
        self.denied(review=inputs['review']|dict(customer_publishable=True))

    def test_missing_rows_extra_rows_and_duplicate_ordinal_denied(self):
        inputs=self.inputs();self.denied(rows={11:inputs['rows'][11]})
        self.denied(rows=inputs['rows']|{99:inputs['rows'][11]})
        self.denied(parts=inputs['parts']+[deepcopy(inputs['parts'][0])])

    def test_missing_server_image_or_rights_ports_never_return_empty_success(self):
        for ports in (dict(),dict(image_reader=self.image),dict(image_reader=self.image,business_rights_reference=True)):
            with self.subTest(ports=ports):
                reader=self.producer.make_source_reader(**ports);self.denied(lambda:reader(self.conn,**self.inputs()))

    def test_storage_permission_error_maps_to_unknown_not_approved(self):
        def denied_image(*args):raise HTTPException(403,'PRIVATE storage credentials')
        reader=self.producer.make_source_reader(image_reader=denied_image,business_rights_reference=photo_fixture.RIGHTS)
        current=self.publication.read_current(self.conn,'P10',source_reader=reader)
        self.assertFalse(current['allowed']);self.assertEqual(current['source_state'],'unknown')
        self.assertNotIn('PRIVATE',str(current))

    def test_changed_detail_bytes_or_hash_denied(self):
        reader=self.producer.make_source_reader(image_reader=lambda *a:photo_fixture.PNG+b'new',
                                               business_rights_reference=photo_fixture.RIGHTS)
        self.denied(lambda:reader(self.conn,**self.inputs()))

    def test_changed_asset_model_does_not_reuse_old_photo_event(self):
        inputs=self.inputs();self.conn.native.explanations[11]['content']['image_asset']['detail_sha256']='d'*64
        self.denied(lambda:self.reader(self.conn,**inputs))

    def test_actor_native_binding_and_corrupt_reference_are_not_trusted(self):
        self.conn.native.events[0]['operator_id']=1;self.denied()

    def test_corrupt_photo_event_digest_not_success(self):
        self.conn.native.photo_events[0]['snapshot']['provenance']['source_reference']='manifest:changed'
        self.denied()

    def test_sql_failure_propagates_instead_of_empty_coverage(self):
        self.conn.native.photo_fail='latest'
        with self.assertRaisesRegex(RuntimeError,'fake SQL'):self.read()

    def test_malformed_row_is_failclosed(self):
        inputs=self.inputs();self.denied(rows=inputs['rows']|{11:None})

    def test_callback_cannot_change_captured_config_revision(self):
        inputs=self.inputs();original=deepcopy(inputs['configuration'])
        def changing(*args):inputs['configuration']['revision']=99;return photo_fixture.PNG
        reader=self.producer.make_source_reader(image_reader=changing,business_rights_reference=photo_fixture.RIGHTS)
        proofs=reader(self.conn,**inputs)
        p=inputs['parts'][0]
        self.assertEqual(proofs.parts[0].basis,self.publication.component_basis(original,p,inputs['rows'][11]))

    def test_sql_snapshot_failure_after_image_is_not_storage_unknown(self):
        original_execute=self.conn.execute; failed=False
        def image(*args):
            nonlocal failed
            failed=True;return photo_fixture.PNG
        def execute(statement,params=None):
            if failed and str(statement)=='SHOW transaction_isolation':raise RuntimeError('MOCK snapshot SQL failed')
            return original_execute(statement,params)
        self.conn.execute=execute
        reader=self.producer.make_source_reader(image_reader=image,business_rights_reference=photo_fixture.RIGHTS)
        with self.assertRaisesRegex(RuntimeError,'snapshot SQL failed'):reader(self.conn,**self.inputs())

    def test_read_committed_not_disguised_by_execution_options(self):
        self.conn.settings_isolation='read committed'
        with self.assertRaises(HTTPException):self.read()

    def test_callback_transaction_replacement_denied(self):
        def changed(*args):self.conn.transaction=object();return photo_fixture.PNG
        reader=self.producer.make_source_reader(image_reader=changed,business_rights_reference=photo_fixture.RIGHTS)
        with self.assertRaises(HTTPException):reader(self.conn,**self.inputs())

    def test_native_description_withdrawn_during_bytes_read_not_old_true(self):
        def changed(asset,code,variant):
            if code==11:self.part.revoke(self.conn,11,expected_seq=1,request_id=str(uuid4()),
                                         note='MOCK during bytes',actor=self.conn.actor)
            return photo_fixture.PNG
        reader=self.producer.make_source_reader(image_reader=changed,business_rights_reference=photo_fixture.RIGHTS)
        self.denied(lambda:reader(self.conn,**self.inputs()))

    def test_source_input_and_native_history_are_unmodified_and_readonly(self):
        inputs=self.inputs();before=deepcopy((inputs,self.conn.native.explanations,self.conn.native.events,self.conn.native.photo_events))
        self.reader(self.conn,**inputs)
        self.assertEqual(before,(inputs,self.conn.native.explanations,self.conn.native.events,self.conn.native.photo_events))
        for q,p in self.conn.calls:self.assertNotRegex(q,r'\b(INSERT|UPDATE|DELETE|COMMIT|ROLLBACK|FOR UPDATE)\b')


if __name__=='__main__':unittest.main()
