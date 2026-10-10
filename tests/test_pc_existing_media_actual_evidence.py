"""Exact two observed CASE rows and pinned existing QA, no images/cloud/DB."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from api.pc_existing_media_authority import ManifestCasePins, ManifestCaseReader
from api.pc_existing_media_import import Denied, provenance, Capture
from tools.register_existing_pc_media import (
    CaseEvidence, ImportBinding, OriginalProvenance, ImportPlan, MANIFEST_SHA,
)

ROOT=Path('D:/WORK/PopcornAI')
PM=ROOT/'outputs/existing-media-actual-wiring-package-20261008/PM-current-case-read-only.json'
MANIFEST=ROOT/'outputs/assembled-pc-images-20260929/manifest.json'

def sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


class ActualEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw=PM.read_bytes()
        assert hashlib.sha256(raw).hexdigest()=='35413de9e21fcdd497f28e5c60acb7ca483f8773953a3d3c63a299bc74e5d7dc'
        cls.observed=json.loads(raw)['rows']
        cls.manifest_bytes=MANIFEST.read_bytes()
        assert hashlib.sha256(cls.manifest_bytes).hexdigest()==MANIFEST_SHA
        cls.items={i['configuration_id']:i for i in json.loads(cls.manifest_bytes)['items']
            if i['configuration_id'] in ('P113835','P113836')}
    def setUp(self):
        self.raw=self.manifest_bytes;self.rows={};self.pins=[];self.conn=object()
        for observed in self.observed:
            code=observed['case_code'];item=self.items[observed['sku']]
            ref=next(r for r in item['references'] if r['slot']=='CASE')
            self.rows[code]=dict(source_product_code=code,source_fingerprint=observed['source_fingerprint'],
                content=copy.deepcopy(observed['content']))
            self.pins.append(ManifestCasePins(observed['sku'],code,observed['source_fingerprint'],
                observed['content_sha256'],observed['content']['name'],item['qa_notes'][0],sha(ref)))
        self.reader=ManifestCaseReader(self.pins,lambda:self.raw)
    def test_exact_both_cases_normalize_from_observed_name_and_external_qa(self):
        for code,color in ((129552,'black'),(129551,'white')):
            with self.subTest(code=code):
                value=self.reader(self.conn,self.rows[code])
                self.assertEqual(value.product_code,code);self.assertEqual(value.model,'DAVEN N1 MESH')
                self.assertEqual(value.color,color);self.assertEqual(value.side_panel,'closed_mesh_opaque')
                self.assertEqual(value.front,'N1_MESH')
    def test_observed_content_hashes_and_fingerprints_are_actual_inputs(self):
        for p in self.pins:
            self.assertEqual(sha(self.rows[p.product_code]['content']),p.content_sha256)
        self.assertEqual(self.rows[129551]['source_fingerprint'],'8e5b3964b68a97c5d67926e19d8c0f7ce622a5256ab27d3adceaa46fcca6fbb7')
        self.assertEqual(self.rows[129552]['source_fingerprint'],'a8a227169962fad6be537cc8fdccfa5985cf56ac5f8d3e692cd4ec86a8945012')
    def test_source_reference_preserves_external_qa_and_exact_paths_hashes(self):
        ref=json.loads(self.reader(self.conn,self.rows[129551]).source_reference)
        self.assertEqual(ref['source'],'explicit-name-and-external-manifest-QA')
        self.assertEqual(ref['model_color']['raw'],'DAVEN N1 MESH (화이트)')
        self.assertEqual(ref['exterior']['source'],'external_QA')
        self.assertEqual(ref['exterior']['raw'],self.items['P113836']['qa_notes'][0])
        self.assertEqual(ref['exterior']['manifest_sha256'],MANIFEST_SHA)
        self.assertIn('P113836',ref['exterior']['path'])
        self.assertEqual(ref['case_reference']['code'],'129551')
        self.assertEqual(ref['case_reference']['source_url'],'https://www.popcornpc.co.kr/data/pimg/129/129551_600.jpg')
    def test_no_facts_backfill_or_mutation(self):
        before=copy.deepcopy(self.rows)
        for row in self.rows.values():self.reader(self.conn,row)
        self.assertEqual(self.rows,before)
        self.assertFalse(any('side_panel' in row['content'] for row in self.rows.values()))
    def test_future_fingerprint_change_or_unknown_is_denied(self):
        for value in (None,'b'*64):
            row={**self.rows[129552],'source_fingerprint':value}
            with self.assertRaises(Denied):self.reader(self.conn,row)
    def test_future_content_change_is_denied_even_same_fingerprint(self):
        self.rows[129552]['content']['facts'][0]['value']='changed'
        with self.assertRaises(Denied):self.reader(self.conn,self.rows[129552])
    def test_similar_name_substring_never_matches(self):
        for name in ('DAVEN N1 MESH (블랙) NEW','DAVEN N1 MESH','unknown'):
            row=copy.deepcopy(self.rows[129552]);row['content']['name']=name
            p=replace(self.pins[1] if self.pins[1].product_code==129552 else self.pins[0],
                name=name,content_sha256=sha(row['content']))
            with self.assertRaises(Denied):ManifestCaseReader([p],lambda:self.raw)(self.conn,row)
    def test_qa_pin_changed_or_missing(self):
        for qa in ('',self.pins[0].qa_note+' maybe'):
            p=replace(self.pins[0],qa_note=qa)
            with self.assertRaises(Denied):ManifestCaseReader([p],lambda:self.raw)(self.conn,self.rows[p.product_code])
    def test_manifest_qa_modification_refused(self):
        value=json.loads(self.raw)
        for i in value['items']:
            if i['configuration_id']=='P113835':i['qa_notes'][0]='glass panel'
        self.raw=json.dumps(value,ensure_ascii=False).encode()
        with self.assertRaises(Denied):self.reader(self.conn,self.rows[129552])
    def test_case_reference_hash_change_refused(self):
        p=replace(self.pins[0],case_reference_sha256='0'*64)
        with self.assertRaises(Denied):ManifestCaseReader([p],lambda:self.raw)(self.conn,self.rows[p.product_code])
    def test_case_reference_or_manifest_bytes_unknown(self):
        self.raw=b'{}'
        with self.assertRaises(Denied):self.reader(self.conn,self.rows[129552])
    def test_sku_case_substitution_refused(self):
        p=replace(self.pins[0],sku='P113835' if self.pins[0].sku=='P113836' else 'P113836')
        with self.assertRaises(Denied):ManifestCaseReader([p],lambda:self.raw)(self.conn,self.rows[p.product_code])
    def test_unbound_case_boolean_code_and_no_connection_refused(self):
        for code in (True,129553,None):
            with self.assertRaises(Denied):self.reader(self.conn,{**self.rows[129552],'source_product_code':code})
        with self.assertRaises(Denied):self.reader(None,self.rows[129552])
    def test_missing_pin_and_duplicate_pin_refused(self):
        for pins in ([],[self.pins[0],self.pins[0]]):
            with self.assertRaises(Denied):ManifestCaseReader(pins,lambda:self.raw)(self.conn,self.rows[self.pins[0].product_code])
    def test_reader_unwired_refused(self):
        with self.assertRaises(Denied):ManifestCaseReader(self.pins,None)(self.conn,self.rows[129552])
    def test_case_provenance_survives_existing_runtime_provenance(self):
        # No file/image byte import or old runtime test rerun: exercise new source ref consumer.
        case=self.reader(self.conn,self.rows[129552])
        binding=ImportBinding(113835,'P113835','actual-config',2,'a'*64,case)
        original=OriginalProvenance('P113835','originals/P113835.png','b'*64,MANIFEST_SHA,1,('qa',),None,None,None)
        value=provenance(Capture(ImportPlan(original,binding),'c'*64,'{}'))
        stored=value['current_binding']['case_evidence']['source_reference']
        self.assertEqual(stored,case.source_reference)
        self.assertEqual(json.loads(stored)['exterior']['source'],'external_QA')
        self.assertIsNone(value['original']['generation_model'])


if __name__=='__main__':unittest.main()
