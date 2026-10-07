"""Exact publication core + actual source review/terms on fake SQL ports.

No api.db/main/auth import, engine, PG, storage access or migration execution.
Proofs are deliberately MOCK server-producer inputs, never production evidence.
"""
import ast
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_publication_source_test'
NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)
PNG = b'\x89PNG\r\n\x1a\nmock-photo-bytes'


def selected(name, filename, functions, *, assignments=(), namespace=None, imports=False, classes=()):
    """Compile named ACTUAL source nodes, excluding route/engine/auth imports."""
    source = ast.parse((ROOT / filename).read_text(encoding='utf-8-sig'))
    nodes = [n for n in source.body if
             (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in (*functions,*classes))
             or (isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id in assignments for t in n.targets))
             or (imports and isinstance(n,(ast.Import,ast.ImportFrom)) and not getattr(n,'level',0))]
    module = ModuleType(PACKAGE+'.'+name)
    module.__file__ = str(ROOT / filename)
    module.__package__ = PACKAGE
    module.__dict__.update(namespace or {})
    sys.modules[module.__name__] = module
    exec(compile(ast.Module(body=nodes,type_ignores=[]),module.__file__,'exec'),module.__dict__)
    return module


def full(name, filename):
    spec = importlib.util.spec_from_file_location(PACKAGE+'.'+name,ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sources():
    pkg = ModuleType(PACKAGE)
    pkg.__path__ = [str(ROOT/'api')]
    sys.modules[PACKAGE] = pkg
    part = selected('part_explanations','api/part_explanations.py',('fingerprint','is_current'),
                    namespace=dict(json=json,hashlib=hashlib))
    copy = selected('pc_configuration_copy','api/pc_configuration_copy.py',
                    ('digest','explanation_digest','part_needs_review'),
                    namespace=dict(json=json,hashlib=hashlib,is_current=part.is_current))
    cooling = full('pc_cooling_plan','api/pc_cooling_plan.py')
    policy = full('pc_review_policy','api/pc_review_policy.py')
    specs = full('pc_review_specs','api/pc_review_specs.py')
    claims = full('pc_copy_claims','api/pc_copy_claims.py')
    sales = selected('pc_sales_conditions','api/pc_sales_conditions.py',
                     ('scope_basis','customer_statement','effective_conditions','customer_conditions'),
                     assignments=('LABELS',), imports=True, classes=('Condition','SalesEdit'))
    description = selected('pc_configuration_edit','api/pc_configuration_edit.py',('description_complete',))
    recommend = selected('recommend','api/recommend.py',('_cmp','rule_ref_value','rule_verdict','_rule_applies'),
                         namespace=dict(re=re))
    review = selected('pc_configuration_review','api/pc_configuration_review.py',
                      ('basis_hash','assess','load_review'), assignments=('MANUAL',), namespace=dict(
                          text=text,HTTPException=HTTPException,digest=copy.digest,
                          part_needs_review=copy.part_needs_review,description_complete=description.description_complete,
                          cooling_plan=cooling.cooling_plan,POLICY_VERSION=policy.POLICY_VERSION,
                          issue_stages=policy.issue_stages,route_checks=policy.route_checks,
                          specs_for_review=specs.specs_for_review,rule_verdict=recommend.rule_verdict,
                          rule_ref_value=recommend.rule_ref_value,_rule_applies=recommend._rule_applies))
    # Extract only the actual bucket constant, never initialize GCS or its module.
    selected('product_images','api/product_images.py',(),assignments=('MEDIA_BUCKET',))
    core = full('pc_customer_publication','api/pc_customer_publication.py')
    return core, copy, part, sales, review


class Result:
    def __init__(self, rows=()): self.rows=list(rows)
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def one(self):
        if len(self.rows)!=1: raise AssertionError('one row required')
        return self.rows[0]
    def all(self): return self.rows
    def __iter__(self): return iter(self.rows)


class Connection:
    def __init__(self, copy, part, actor_id=2**40):
        self.calls=[]; self.events=[]; self.active=True; self.nested=False; self.isolation='REPEATABLE READ'; self.transaction=object()
        self.error_tag=None; self.error=RuntimeError('fake SQL failure'); self.after_product_lock=None
        self.actor=dict(operator_id=actor_id,role='operator',status='활성')
        self.config=dict(configuration_id='P10',revision=1,bom_fingerprint='a'*64,
                         content_hash='b'*64,copy_hash='c'*64,status='approved',observed_date=date(2020,1,1),
                         content=dict(title='검증 PC',intro='근거 설명',facts=dict(cpu='CPU',ram_gb=16,storage_gb=512)))
        self.parts=[]; self.rows={}; self.specs={}
        for ordinal,slot,code,product in ((0,'CPU',11,101),(1,'MB',12,102)):
            content=dict(name=slot,slot=slot,facts=[],review_issues=[],image_url='https://merchant.example/'+str(code),
                image_asset=dict(bucket='popcorn-ai-product-media-045e861b',
                                 detail_key=f'products/{code}/0123456789abcdef/detail.png',
                                 thumbnail_key=f'products/{code}/0123456789abcdef/thumb.webp',
                                 detail_sha256=hashlib.sha256(PNG).hexdigest()))
            row=dict(source_product_code=code,product_code=product,content=content,
                source_snapshot=dict(name=slot,spec='AM4'),source_fingerprint=part.fingerprint(slot,'AM4'),
                status='approved',approved_by=actor_id,approved_at=NOW,
                product_name=slot,spec_source_text='AM4',sale_status='판매중',sale_price=100)
            self.rows[code]=row
            self.parts.append(dict(configuration_id='P10',ordinal=ordinal,slot=slot,source_code=str(code),
                                   explanation_code=code,quantity=1,pseudo=False,selection_note='',
                                   explanation_hash=copy.explanation_digest(row)))
            self.specs[product]=dict(product_code=product,part_type=slot,socket='AM4')
        self.offers=[dict(configuration_id='P10',offer_id='P10',price_snapshot=1000,payload=dict(offer_id='P10'))]
        self.rules=[dict(rule_id=1,rule_key='socket',label='소켓',slot='CPU',ref_slot='MB',
                         field='socket',ref_field='socket',op='eq',active=True)]

    def in_transaction(self): return self.active
    def in_nested_transaction(self): return self.nested
    def get_execution_options(self): return dict(isolation_level=self.isolation)
    def get_transaction(self): return self.transaction
    def execute(self, statement, params=None):
        q=str(statement); p=params or {}; self.calls.append((q,deepcopy(p)))
        tag=re.search(r'/\*pc_publication:([^*]+)\*/',q)
        if tag:
            tag=tag[1]
            if tag==self.error_tag: raise self.error
            if tag=='actor': return Result([deepcopy(self.actor)] if p['operator_id']==self.actor['operator_id'] else [])
            if tag=='latest': return Result(deepcopy(sorted((e for e in self.events if e['configuration_id']==p['identity']),key=lambda e:e['event_seq'],reverse=True)[:1]))
            if tag=='request': return Result([deepcopy(e) for e in self.events if e['request_id']==p['request_id']])
            if tag=='sources': return Result([deepcopy(self.rows[c]) for c in sorted(set(p['codes'])) if c in self.rows])
            if tag=='append':
                if any(e['request_id']==p['uid'] for e in self.events): raise self.error
                e=dict(configuration_id=p['identity'],event_seq=p['seq'],request_id=p['uid'],
                    request_digest=p['request_digest'],action=p['action'],operator_id=p['operator_id'],
                    recorded_at=NOW,note=p['note'],configuration_revision=p['revision'],
                    review_basis=p['review_basis'],publication_basis=p['publication_basis'],evidence=json.loads(p['evidence']))
                self.events.append(e); return Result([deepcopy(e)])
            raise AssertionError('Unexpected publication SQL '+tag)
        if q.startswith('SELECT pg_advisory_xact_lock'): return Result()
        if q.startswith('SELECT * FROM pc_configurations'): return Result([deepcopy(self.config)] if p['id']==self.config['configuration_id'] else [])
        if q.startswith('SELECT * FROM pc_configuration_parts'): return Result(deepcopy(self.parts))
        if q.startswith('SELECT * FROM pc_configuration_offers'): return Result(deepcopy(self.offers))
        if 'SELECT e.*,p.product_name,p.spec_source_text' in q: return Result([deepcopy(self.rows[c]) for c in sorted(set(p['codes'])) if c in self.rows])
        if q.startswith('SELECT product_code FROM products'):
            if self.after_product_lock:
                callback=self.after_product_lock; self.after_product_lock=None; callback()
            return Result([dict(product_code=c) for c in sorted(set(p['codes']))])
        if q.startswith('SELECT * FROM product_specs'): return Result([deepcopy(self.specs[c]) for c in sorted(set(p['codes'])) if c in self.specs])
        if q.startswith('SELECT * FROM compat_rules'): return Result(deepcopy(self.rules))
        raise AssertionError('Unexpected original SQL '+q)

    def begin(self): raise AssertionError('Caller owns begin')
    def connect(self): raise AssertionError('No connection factory')
    def commit(self): raise AssertionError('Caller owns commit')
    def rollback(self): raise AssertionError('Caller owns rollback')
    def close(self): raise AssertionError('Caller owns close')


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous={k:v for k,v in sys.modules.items() if k==PACKAGE or k.startswith(PACKAGE+'.')}
        cls.core,cls.copy,cls.part,cls.sales,cls.review=sources()

    @classmethod
    def tearDownClass(cls):
        for key in list(sys.modules):
            if key==PACKAGE or key.startswith(PACKAGE+'.'): del sys.modules[key]
        sys.modules.update(cls.previous)

    def setUp(self):
        self.conn=Connection(self.copy,self.part)
        self.restamp_review()

    def restamp_review(self):
        self.conn.config['content'].pop('_review',None)
        state=self.review.load_review(self.conn,'P10')[3]
        self.conn.config['content']['_review']=dict(state='approved',basis=state['basis'],
                                                  actor=dict(operator_id=self.conn.actor['operator_id']),at=NOW.isoformat())
        self.assertTrue(self.review.load_review(self.conn,'P10')[3]['eligible'])

    def reader(self, conn, *, configuration, parts, offers, review, rows):
        part_proofs=[]; photo_proofs=[]
        for p in parts:
            if p['pseudo']: continue
            row=rows[p['explanation_code']]
            part_proofs.append(self.core.PartApproval(p['ordinal'],p['explanation_code'],
                self.core.component_basis(configuration,p,row),'MOCK-part-'+str(p['ordinal']),row['approved_by'],row['approved_at']))
            photo_proofs.append(self.core.PhotoApproval(p['ordinal'],p['explanation_code'],
                self.core.photo_basis(configuration,p,row),'MOCK-photo-'+str(p['ordinal']),row['approved_by'],row['approved_at'],
                'registered_product_photo','MOCK-same-product-source','MOCK-display-rights',PNG))
        return self.core.PublicationSources(self.core.SOURCE_POLICY,tuple(part_proofs),tuple(photo_proofs))

    def request(self, **updates):
        current=self.core.read_current(self.conn,'P10',source_reader=self.reader)
        body=dict(expected_seq=current['event_seq'],revision=self.conn.config['revision'],
                  review_basis=current['basis'],publication_basis=current['publication_basis'],
                  request_id=str(uuid4()),note='검토 근거',actor=deepcopy(self.conn.actor),source_reader=self.reader)
        body.update(updates); return body

    def approve(self, **updates):
        return self.core.approve(self.conn,'P10',**self.request(**updates))

    def error(self, status, function, *args, **kwargs):
        with self.assertRaises(HTTPException) as caught: function(*args,**kwargs)
        self.assertEqual(caught.exception.status_code,status)
        return caught.exception.detail

    def test_approve_read_pending_without_mutating_original_review(self):
        original=deepcopy((self.conn.config,self.conn.parts,self.conn.offers,self.conn.rows))
        basis=self.review.load_review(self.conn,'P10')[3]['basis']
        result=self.approve()
        self.assertTrue(result['current']['allowed']); self.assertFalse(result['committed'])
        self.assertFalse(result['replayed']); self.assertEqual(result['event']['event_seq'],1)
        self.assertEqual((self.conn.config,self.conn.parts,self.conn.offers,self.conn.rows),original)
        review=self.review.load_review(self.conn,'P10')[3]
        self.assertEqual(review['basis'],basis); self.assertFalse(review['customer_publishable'])
        self.assertNotIn('_publication',self.conn.config['content'])
        writes=[q for q,p in self.conn.calls if re.match(r'\s*(?:/\*.*?\*/\s*)?(INSERT|UPDATE|DELETE)\b',q)]
        self.assertEqual(len(writes),1); self.assertIn('INSERT INTO pc_customer_publication_events',writes[0])

    def test_unapproved_exposes_server_basis_but_never_allows(self):
        r=self.core.read_current(self.conn,'P10',source_reader=self.reader)
        self.assertEqual(r['state'],'unapproved'); self.assertFalse(r['allowed'])
        self.assertEqual(r['source_state'],'current'); self.assertRegex(r['publication_basis'],r'^[a-f0-9]{64}$')

    def test_default_unconnected_reader_cannot_approve_or_publish(self):
        body=self.request(source_reader=None)
        self.error(503,self.core.approve,self.conn,'P10',**body)
        self.assertEqual(self.conn.events,[])
        r=self.core.read_current(self.conn,'P10'); self.assertFalse(r['allowed']); self.assertEqual(r['source_state'],'unknown')
        self.approve(); self.assertFalse(self.core.read_current(self.conn,'P10')['allowed'])

    def test_revoke_then_old_approval_replay_preserves_revoked_latest(self):
        body=self.request(); a=self.core.approve(self.conn,'P10',**body)
        r=self.core.revoke(self.conn,'P10',expected_seq=1,request_id=str(uuid4()),reason='공개 회수',actor=self.conn.actor)
        self.assertEqual(r['event']['event_seq'],2); self.assertEqual(r['current']['state'],'revoked')
        replay=self.core.approve(self.conn,'P10',**body)
        self.assertTrue(replay['replayed']); self.assertEqual(replay['event']['event_seq'],a['event']['event_seq'])
        self.assertEqual(replay['current']['event_seq'],2); self.assertFalse(replay['current']['allowed'])
        self.assertEqual(len(self.conn.events),2)

    def test_revoke_stale_source_and_replay(self):
        a=self.approve(); self.conn.rows.clear(); self.conn.config['content']['intro']='changed'
        body=dict(expected_seq=1,request_id=str(uuid4()),reason='근거 변경',actor=self.conn.actor)
        r=self.core.revoke(self.conn,'P10',**body)
        self.assertEqual(r['event']['evidence'],a['event']['evidence']); self.assertFalse(r['current']['allowed'])
        replay=self.core.revoke(self.conn,'P10',**body)
        self.assertTrue(replay['replayed']); self.assertEqual(len(self.conn.events),2)

    def test_old_screen_cannot_revoke_new_approval(self):
        self.approve()
        self.core.revoke(self.conn,'P10',expected_seq=1,request_id=str(uuid4()),reason='회수',actor=self.conn.actor)
        self.approve(); self.assertEqual(self.conn.events[-1]['event_seq'],3)
        self.error(409,self.core.revoke,self.conn,'P10',expected_seq=1,request_id=str(uuid4()),reason='과거 화면',actor=self.conn.actor)
        self.assertTrue(self.core.read_current(self.conn,'P10',source_reader=self.reader)['allowed'])

    def test_approval_replay_has_no_extra_insert(self):
        body=self.request(); self.core.approve(self.conn,'P10',**body)
        r=self.core.approve(self.conn,'P10',**body)
        self.assertTrue(r['replayed']); self.assertTrue(r['current']['allowed']); self.assertEqual(len(self.conn.events),1)

    def test_request_input_mismatch_is_conflict_even_before_seq_check(self):
        body=self.request(); self.core.approve(self.conn,'P10',**body)
        for field,value in [('note','different'),('expected_seq',1),('revision',2),('review_basis','e'*64),('publication_basis','f'*64)]:
            with self.subTest(field=field): self.error(409,self.core.approve,self.conn,'P10',**dict(body,**{field:value}))
        self.error(409,self.core.revoke,self.conn,'P10',expected_seq=1,request_id=body['request_id'],reason='회수',actor=self.conn.actor)
        self.assertEqual(len(self.conn.events),1)

    def test_request_actor_and_identity_mismatch_is_conflict(self):
        body=self.request(); self.core.approve(self.conn,'P10',**body)
        old=deepcopy(self.conn.actor); self.conn.actor['operator_id']+=1
        self.error(409,self.core.approve,self.conn,'P10',**dict(body,actor=self.conn.actor))
        self.conn.actor=old
        self.conn.config['configuration_id']='P20'
        for p in self.conn.parts: p['configuration_id']='P20'
        for o in self.conn.offers: o['configuration_id']='P20'
        self.error(409,self.core.approve,self.conn,'P20',**body)

    def test_same_uuid_cross_config_unique_failure_propagates(self):
        body=self.request(); self.core.approve(self.conn,'P10',**body)
        self.conn.error_tag='request'
        with self.assertRaises(RuntimeError) as caught: self.core.approve(self.conn,'P10',**body)
        self.assertIs(caught.exception,self.conn.error)

    def test_sequence_and_basis_compare_only(self):
        for changes in (dict(expected_seq=1),dict(revision=2),dict(review_basis='d'*64),dict(publication_basis='d'*64)):
            with self.subTest(changes=changes): self.error(409,self.core.approve,self.conn,'P10',**self.request(**changes))
        self.assertEqual(self.conn.events,[])

    def test_invalid_native_inputs(self):
        class SubInt(int): pass
        for field in ('expected_seq','revision'):
            for value in (True,None,1.0,'1',-1,SubInt(1),2**63):
                with self.subTest(field=field,value=value): self.error(422,self.core.approve,self.conn,'P10',**self.request(**{field:value}))
        for field in ('review_basis','publication_basis'):
            for value in ('A'*64,'a'*63,None):
                self.error(422,self.core.approve,self.conn,'P10',**self.request(**{field:value}))
        for value in ('invalid','',None,True): self.error(422,self.core.approve,self.conn,'P10',**self.request(request_id=value))

    def test_actor_bigint_and_invalid_null_ids(self):
        r=self.approve(); self.assertGreater(r['event']['operator_id'],2**31)
        for value in (None,True,0,-1,1.0,'7',2**63):
            self.error(403,self.core.approve,self.conn,'P10',**self.request(actor=dict(self.conn.actor,operator_id=value)))
        for actor in (None,dict(self.conn.actor,role='viewer'),dict(self.conn.actor,status='중지')):
            self.error(403,self.core.approve,self.conn,'P10',**self.request(actor=actor))
        self.conn.actor['status']='중지'
        self.error(403,self.core.approve,self.conn,'P10',**self.request(actor=dict(self.conn.actor,status='활성')))

    def test_caller_tx_required_without_implicit_begin(self):
        body=self.request()
        for field,value in (('active',False),('nested',True),('isolation','AUTOCOMMIT')):
            original=getattr(self.conn,field); setattr(self.conn,field,value); calls=len(self.conn.calls)
            for fn,args,kwargs in ((self.core.read_current,(self.conn,'P10'),{}),
                                   (self.core.approve,(self.conn,'P10'),body),
                                   (self.core.revoke,(self.conn,'P10'),dict(expected_seq=0,request_id=str(uuid4()),reason='회수',actor=self.conn.actor))):
                self.error(503,fn,*args,**kwargs)
            self.assertEqual(len(self.conn.calls),calls); setattr(self.conn,field,original)

    def test_original_lock_order_and_post_product_lock_reread(self):
        body=self.request(); self.conn.calls=[]
        self.core.approve(self.conn,'P10',**body)
        queries=[q for q,p in self.conn.calls]
        advisory=next(i for i,q in enumerate(queries) if 'pg_advisory_xact_lock' in q)
        config=next(i for i,q in enumerate(queries) if 'pc_configurations' in q and 'FOR UPDATE' in q)
        explanation=next(i for i,q in enumerate(queries) if 'FOR SHARE OF e' in q)
        product=next(i for i,q in enumerate(queries) if q.startswith('SELECT product_code FROM products'))
        reread=next(i for i,q in enumerate(queries) if i>product and 'SELECT e.*,p.product_name' in q)
        specs=next(i for i,q in enumerate(queries) if q.startswith('SELECT * FROM product_specs') and 'FOR SHARE' in q)
        rules=next(i for i,q in enumerate(queries) if q.startswith('SELECT * FROM compat_rules') and 'FOR SHARE' in q)
        self.assertEqual([advisory,config,explanation,product,reread,specs,rules],sorted([advisory,config,explanation,product,reread,specs,rules]))
        self.conn.after_product_lock=lambda: self.conn.rows[11].update(sale_price=200)
        self.error(409,self.core.approve,self.conn,'P10',**self.request(publication_basis=body['publication_basis'],review_basis=body['review_basis']))

    def test_current_config_copy_bom_part_terms_and_photo_drift_denies(self):
        mutations=(lambda:self.conn.config.update(revision=2),lambda:self.conn.config.update(bom_fingerprint='d'*64),
            lambda:self.conn.config.update(content_hash='d'*64),lambda:self.conn.config.update(copy_hash='d'*64),
            lambda:self.conn.config['content'].update(intro='새 설명'),lambda:self.conn.parts[0].update(quantity=2),
            lambda:self.conn.rows[11]['content'].update(name='changed'),lambda:self.conn.rows[11].update(spec_source_text='new'),
            lambda:self.conn.config['content'].update(_sales_conditions={'os':{'state':'included'}}),
            lambda:self.conn.rows[11]['content']['image_asset'].update(detail_sha256='d'*64))
        for change in mutations:
            self.setUp(); self.approve(); change()
            with self.subTest(change=change): self.assertFalse(self.core.read_current(self.conn,'P10',source_reader=self.reader)['allowed'])

    def test_stored_hashes_are_not_enough_for_same_revision_copy_change(self):
        self.approve(); old=(self.conn.config['content_hash'],self.conn.config['copy_hash'])
        self.conn.config['content']['intro']='current text drift'
        self.restamp_review()  # Even a newly current recommendation is not public approval.
        r=self.core.read_current(self.conn,'P10',source_reader=self.reader)
        self.assertEqual(old,(self.conn.config['content_hash'],self.conn.config['copy_hash']))
        self.assertFalse(r['allowed']); self.assertEqual(r['state'],'stale')

    def test_invalid_review_actor_or_time_cannot_supply_publication_evidence(self):
        for value in ('invalid','2020-01-01T00:00:00','2099-01-01T00:00:00+00:00'):
            self.setUp(); self.conn.config['content']['_review']['at']=value
            self.error(422,self.core.approve,self.conn,'P10',**self.request(publication_basis='d'*64))
        self.setUp(); self.conn.config['content']['_review']['actor']['operator_id']=True
        self.error(422,self.core.approve,self.conn,'P10',**self.request(publication_basis='d'*64))

    def test_missing_draft_stale_and_null_part_fail_closed(self):
        for mutate in (lambda:self.conn.rows.pop(11),lambda:self.conn.rows[11].update(status='draft'),
                       lambda:self.conn.rows[11].update(approved_by=None),lambda:self.conn.rows[11].update(product_code=None)):
            self.setUp(); self.approve(); mutate()
            self.assertFalse(self.core.read_current(self.conn,'P10',source_reader=self.reader)['allowed'])
        self.setUp(); self.conn.rows[11]['status']='draft'; self.restamp_review()
        self.error(422,self.core.approve,self.conn,'P10',**self.request(publication_basis='d'*64))

    def test_photo_byte_or_kind_or_proof_binding_failure(self):
        for changes in (dict(detail_bytes=b''),dict(detail_bytes=PNG+b'changed'),dict(kind='ai_example'),
                        dict(source_reference=''),dict(rights_reference=''),dict(basis='d'*64),dict(explanation_code=999),
                        dict(operator_id=None),dict(approved_at=datetime(2020,1,1))):
            def bad(conn, **kw):
                proofs=self.reader(conn,**kw)
                return replace(proofs,photos=(replace(proofs.photos[0],**changes),proofs.photos[1]))
            with self.subTest(changes=changes): self.error(422,self.core.approve,self.conn,'P10',**self.request(source_reader=bad))
        self.assertEqual(self.conn.events,[])

    def test_external_verified_mapping_is_not_server_proof(self):
        self.error(422,self.core.approve,self.conn,'P10',**self.request(source_reader=lambda conn,**kw:dict(verified=True)))
        body=self.request(); body['verified']=True
        with self.assertRaises(TypeError): self.core.approve(self.conn,'P10',**body)
        self.assertEqual(self.conn.events,[])

    def test_exact_component_coverage_and_part_approval_binding(self):
        for transform in (lambda p:replace(p,parts=p.parts[:1]),lambda p:replace(p,photos=p.photos[:1]),
                          lambda p:replace(p,parts=p.parts+(p.parts[0],)),
                          lambda p:replace(p,parts=(replace(p.parts[0],operator_id=7),p.parts[1])),
                          lambda p:replace(p,policy_version='unknown')):
            def bad(conn,**kw): return transform(self.reader(conn,**kw))
            self.error(422,self.core.approve,self.conn,'P10',**self.request(source_reader=bad))

    def test_terms_safe_display_and_scope_are_bound(self):
        r=self.approve(); evidence=r['event']['evidence']
        self.assertEqual(evidence['terms_scope_basis'],self.sales.scope_basis(self.conn.config,self.conn.parts,self.conn.offers))
        terms=self.sales.customer_conditions(self.conn.config,self.conn.parts,self.conn.offers)
        self.assertEqual(terms['os']['state'],'unknown'); self.assertEqual(evidence['terms_digest'],self.copy.digest(terms))
        self.assertNotIn('price_confirmed',evidence); self.assertNotIn('sale_approved',r['current'])

    def test_legacy_review_cannot_publish_unproven_sales_copy(self):
        self.conn.config['content']['intro']='운영체제는 포함됩니다.'
        self.restamp_review()  # Existing assess skips its claim check without _sales_conditions.
        self.error(422,self.core.approve,self.conn,'P10',**self.request(publication_basis='d'*64))
        self.assertEqual(self.conn.events,[])
        self.conn.config['content']['intro']='운영체제 포함 여부를 구매 전에 확인해 주세요.'
        self.restamp_review(); self.assertTrue(self.approve()['current']['allowed'])

    def test_revoke_reason_required_no_event_and_repeated_revoke_conflict(self):
        self.error(409,self.core.revoke,self.conn,'P10',expected_seq=0,request_id=str(uuid4()),reason='회수',actor=self.conn.actor)
        self.approve()
        for reason in ('',' ',None): self.error(422,self.core.revoke,self.conn,'P10',expected_seq=1,request_id=str(uuid4()),reason=reason,actor=self.conn.actor)
        self.core.revoke(self.conn,'P10',expected_seq=1,request_id=str(uuid4()),reason='회수',actor=self.conn.actor)
        self.error(409,self.core.revoke,self.conn,'P10',expected_seq=2,request_id=str(uuid4()),reason='다시 회수',actor=self.conn.actor)

    def test_sql_and_reader_errors_propagate_for_caller_rollback(self):
        for tag in ('actor','request','latest','sources','append'):
            self.setUp(); body=self.request(); self.conn.error_tag=tag
            with self.subTest(tag=tag),self.assertRaises(RuntimeError) as caught: self.core.approve(self.conn,'P10',**body)
            self.assertIs(caught.exception,self.conn.error)
        self.setUp(); body=self.request()
        def broken(conn,**kw): raise self.conn.error
        with self.assertRaises(RuntimeError) as caught: self.core.approve(self.conn,'P10',**dict(body,source_reader=broken))
        self.assertIs(caught.exception,self.conn.error); self.assertEqual(self.conn.events,[])

    def test_tampered_event_denies_even_with_old_valid_approval(self):
        self.approve(); self.conn.events[0]['publication_basis']='d'*64
        self.error(503,self.core.read_current,self.conn,'P10',source_reader=self.reader)

    def test_request_note_whitespace_and_revoke_reason_reuse_are_exact(self):
        body=self.request(note=' 근거 '); self.core.approve(self.conn,'P10',**body)
        self.error(409,self.core.approve,self.conn,'P10',**dict(body,note='근거'))
        request=str(uuid4())
        self.core.revoke(self.conn,'P10',expected_seq=1,request_id=request,reason='회수 근거',actor=self.conn.actor)
        self.error(409,self.core.revoke,self.conn,'P10',expected_seq=1,request_id=request,reason='다른 근거',actor=self.conn.actor)

    def test_server_reader_cannot_end_or_replace_caller_transaction(self):
        body=self.request()
        def ended(conn,**kw):
            proofs=self.reader(conn,**kw); conn.active=False; return proofs
        self.error(503,self.core.approve,self.conn,'P10',**dict(body,source_reader=ended))
        self.assertEqual(self.conn.events,[])
        self.setUp(); body=self.request()
        def switched(conn,**kw):
            proofs=self.reader(conn,**kw); conn.transaction=object(); return proofs
        self.error(503,self.core.approve,self.conn,'P10',**dict(body,source_reader=switched))
        self.assertEqual(self.conn.events,[])

    def test_append_result_mismatch_propagates_after_pending_write(self):
        body=self.request(); execute=self.conn.execute
        def mismatched(statement,params=None):
            result=execute(statement,params)
            if '/*pc_publication:append*/' in str(statement): result.rows[0]['request_digest']='d'*64
            return result
        with patch.object(self.conn,'execute',mismatched): self.error(503,self.core.approve,self.conn,'P10',**body)
        # The fake event is still pending: the core must not secretly roll back.
        self.assertEqual(len(self.conn.events),1)

    def test_same_request_uuid_insert_unique_conflict_is_not_swallowed(self):
        body=self.request(); execute=self.conn.execute
        def raced(statement,params=None):
            if '/*pc_publication:append*/' in str(statement):
                raise self.conn.error  # Fake concurrent other-config UNIQUE(request_id) winner.
            return execute(statement,params)
        with patch.object(self.conn,'execute',raced),self.assertRaises(RuntimeError) as caught:
            self.core.approve(self.conn,'P10',**body)
        self.assertIs(caught.exception,self.conn.error); self.assertEqual(self.conn.events,[])

    def test_confirmed_conditions_becoming_stale_cannot_keep_publication(self):
        cfg=self.conn.config
        cfg['content']['_sales_conditions']={'os':dict(state='included',detail='등록 OS',
            evidence='판매 구성표 확인',source='MOCK-S1',checked_date='2020-01-01',months=None,
            scope_basis=self.sales.scope_basis(cfg,self.conn.parts,self.conn.offers),
            operator_id=self.conn.actor['operator_id'],confirmed_at=NOW.isoformat())}
        self.restamp_review(); self.approve()
        self.assertEqual(self.sales.customer_conditions(cfg,self.conn.parts,self.conn.offers)['os']['state'],'included')
        cfg['content']['_sales_conditions']['os']['scope_basis']='d'*64
        self.restamp_review()
        terms=self.sales.customer_conditions(cfg,self.conn.parts,self.conn.offers)
        self.assertEqual(terms['os']['state'],'unknown'); self.assertTrue(terms['os']['needs_reconfirmation'])
        self.assertFalse(self.core.read_current(self.conn,'P10',source_reader=self.reader)['allowed'])

    def test_consistent_snapshot_and_authentication_remain_caller_contracts(self):
        self.conn.isolation='READ COMMITTED'
        # No false claim that the fake port proves MVCC; the caller must supply one snapshot.
        r=self.approve(); self.assertFalse(r['committed'])
        self.assertFalse(self.core.read_current(self.conn,'P10')['allowed'])

    def test_not_found_identity_and_pseudo_part(self):
        self.error(404,self.core.read_current,self.conn,'missing')
        self.error(422,self.core.read_current,self.conn,' P10')
        self.conn.parts.append(dict(configuration_id='P10',ordinal=2,slot='GPU',source_code='integrated',
            explanation_code=None,quantity=1,pseudo=True,selection_note='',explanation_hash=None))
        self.restamp_review(); r=self.approve(); self.assertTrue(r['current']['allowed'])
        self.assertEqual(len(r['event']['evidence']['components']),2)

    def test_core_source_has_no_tx_ownership_routes_or_mutating_config_sql(self):
        tree=ast.parse((ROOT/'api/pc_customer_publication.py').read_text(encoding='utf-8-sig'))
        forbidden={'engine','connect','begin','commit','rollback','close','current_operator_id','save_review','write_content','APIRouter'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Name): self.assertNotIn(node.id,forbidden)
            if isinstance(node,ast.Attribute): self.assertNotIn(node.attr,forbidden)
        sql='\n'.join(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str))
        self.assertNotRegex(sql,r'(?i)\b(UPDATE|DELETE FROM)\s+pc_configurations\b')

    def test_migration_source_bigint_append_guard_schema_and_no_erase(self):
        filename=ROOT/'db/migrations/versions/0129_pc_customer_publication.py'
        tree=ast.parse(filename.read_text(encoding='utf-8-sig'))
        namespace=dict(re=re,text=text)
        nodes=[n for n in tree.body if isinstance(n,ast.Assign) or isinstance(n,ast.FunctionDef)]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(filename),'exec'),namespace)
        self.assertEqual(namespace['revision'],'0129'); self.assertEqual(namespace['down_revision'],'0128')
        sql=namespace['UPGRADE_SQL']; self.assertIn('operator_id BIGINT NOT NULL REFERENCES __S__.admin_operators',sql)
        self.assertIn('BEFORE INSERT OR UPDATE OR DELETE',sql); self.assertIn('BEFORE TRUNCATE',sql)
        self.assertIn("TG_OP<>'INSERT'",sql); self.assertIn('FOR UPDATE',sql)
        self.assertIn("previous.action IS DISTINCT FROM 'approve'",sql)
        self.assertNotRegex(sql,r'(?i)\b(GRANT|DROP|DELETE FROM|UPDATE pc_configurations)\b')
        with self.assertRaises(RuntimeError): namespace['downgrade']()
        class Bind:
            def __init__(self,value): self.value=value
            def execute(self,*args): return self
            def scalar_one(self): return self.value
        self.assertEqual(namespace['_schema'](Bind('isolated_test')),'"isolated_test"')
        for value in ('public;DROP TABLE x','a.b','',None,True):
            with self.assertRaises(RuntimeError): namespace['_schema'](Bind(value))


if __name__ == '__main__':
    unittest.main()
