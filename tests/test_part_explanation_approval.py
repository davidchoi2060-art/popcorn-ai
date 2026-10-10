"""Actual approval core/canonical source functions on fake SQL ports only.

No api.db/auth/main module, PG, migration execution, storage or credentials.
Native metadata/event mutations here are MOCKs, not accepted public wiring.
"""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_part_approval_source_test'
PAST = datetime(2020,1,1,tzinfo=timezone.utc)
NOW = datetime(2020,1,2,tzinfo=timezone.utc)


def selected(name, filename, functions, assignments=(), namespace=None):
    source = ast.parse((ROOT/filename).read_text(encoding='utf-8-sig'))
    nodes = [n for n in source.body if isinstance(n,ast.FunctionDef) and n.name in functions
             or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in assignments for t in n.targets)]
    module = ModuleType(PACKAGE+'.'+name)
    module.__file__=str(ROOT/filename); module.__package__=PACKAGE
    module.__dict__.update(namespace or {})
    sys.modules[module.__name__]=module
    exec(compile(ast.Module(body=nodes,type_ignores=[]),module.__file__,'exec'),module.__dict__)
    return module


def load_sources():
    package=ModuleType(PACKAGE); package.__path__=[str(ROOT/'api')]; sys.modules[PACKAGE]=package
    part=selected('part_explanations','api/part_explanations.py',('fingerprint','is_current','can_publish'),
                  ('SELECT',),dict(json=json,hashlib=hashlib))
    copy=selected('pc_configuration_copy','api/pc_configuration_copy.py',('digest','explanation_digest'),
                  namespace=dict(json=json,hashlib=hashlib))
    spec=importlib.util.spec_from_file_location(PACKAGE+'.part_explanation_approval',ROOT/'api/part_explanation_approval.py')
    core=importlib.util.module_from_spec(spec); sys.modules[spec.name]=core; spec.loader.exec_module(core)
    return core,part,copy


class Result:
    def __init__(self,rows=()): self.rows=list(rows)
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def one(self):
        if len(self.rows)!=1: raise AssertionError('one row required')
        return self.rows[0]
    def all(self): return self.rows


class Connection:
    def __init__(self,part):
        self.active=True; self.nested=False; self.transaction=object(); self.isolation='REPEATABLE READ'
        self.calls=[]; self.events=[]; self.fail_tag=None; self.error=RuntimeError('fake SQL/unique failure')
        self.after_product_lock=None; self.after_update=None; self.now=NOW
        self.actor=dict(operator_id=2**40,role='operator',status='활성')
        self.explanations={}
        self.products={}
        for source_code,product_code,name in ((11,101,'CPU'),(12,102,'MB')):
            self.products[product_code]=dict(product_code=product_code,product_name=name,
                spec_source_text='AM4',status='판매중',sale_price=Decimal('100.00'))
            self.explanations[source_code]=dict(source_product_code=source_code,product_code=product_code,
                content=dict(name=name,slot=name,facts=[],role='실원문 설명',review_issues=[]),
                source_snapshot=dict(name=name,spec='AM4'),source_fingerprint=part.fingerprint(name,'AM4'),
                status='draft',approved_by=None,approved_at=None,updated_at=PAST)
        self.before=deepcopy((self.explanations,self.products,self.events))

    def row(self,code):
        e=self.explanations.get(code)
        if e is None: return None
        p=self.products.get(e['product_code'],{})
        return deepcopy(dict(e,product_name=p.get('product_name'),spec_source_text=p.get('spec_source_text'),
                             sale_status=p.get('status'),sale_price=p.get('sale_price')))

    def in_transaction(self): return self.active
    def in_nested_transaction(self): return self.nested
    def get_execution_options(self): return dict(isolation_level=self.isolation)
    def get_transaction(self): return self.transaction
    def execute(self,statement,params=None):
        q=str(statement); p=params or {}; self.calls.append((q,deepcopy(p)))
        if not q.startswith('/*part_approval:'): raise AssertionError('unexpected SQL '+q)
        tag=q.split('*/',1)[0].split(':',1)[1]
        if tag==self.fail_tag: raise self.error
        if tag=='catalog_lock': return Result()
        if tag=='row':
            row=self.row(p['code']); return Result([row] if row is not None else [])
        if tag=='product_lock':
            if self.after_product_lock:
                callback=self.after_product_lock; self.after_product_lock=None; callback()
            return Result([dict(product_code=p['code'])] if p['code'] in self.products else [])
        if tag=='actor': return Result([deepcopy(self.actor)] if p['operator_id']==self.actor['operator_id'] else [])
        if tag=='latest': return Result(deepcopy(sorted((e for e in self.events if e['source_product_code']==p['code']),key=lambda e:e['event_seq'],reverse=True)[:1]))
        if tag=='request': return Result([deepcopy(e) for e in self.events if e['request_id']==p['uid']])
        if tag=='approve_metadata':
            e=self.explanations[p['code']]
            e.update(status='approved',approved_by=p['operator_id'],approved_at=self.now,updated_at=self.now)
            if self.after_update: self.after_update()
            return Result([dict(source_product_code=p['code'])])
        if tag=='revoke_metadata':
            e=self.explanations[p['code']]
            if (e['status']!='approved' or e['approved_by']!=p['old_actor'] or e['approved_at']!=p['old_at']): return Result()
            e.update(status='draft',approved_by=None,approved_at=None,updated_at=self.now)
            if self.after_update: self.after_update()
            return Result([dict(source_product_code=p['code'])])
        if tag=='append':
            if any(e['request_id']==p['uid'] for e in self.events): raise self.error
            event=dict(source_product_code=p['code'],event_seq=p['seq'],request_id=p['uid'],request_digest=p['request_digest'],
                       action=p['action'],operator_id=p['operator_id'],recorded_at=self.now,note=p['note'],
                       approval_basis=p['basis'],snapshot=json.loads(p['snapshot']),metadata_reset=p['reset'],write_txid=99)
            self.events.append(event); return Result([deepcopy(event)])
        raise AssertionError('unexpected tag '+tag)

    def begin(self): raise AssertionError('caller owns begin')
    def connect(self): raise AssertionError('no connection factory')
    def commit(self): raise AssertionError('caller owns commit')
    def rollback(self): raise AssertionError('caller owns rollback')
    def close(self): raise AssertionError('caller owns close')
    def caller_discards_failed_tx(self):
        # Only the TEST caller invokes this; the real core never owns rollback.
        self.explanations,self.products,self.events=deepcopy(self.before)


class PartApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous={k:v for k,v in sys.modules.items() if k==PACKAGE or k.startswith(PACKAGE+'.')}
        cls.core,cls.part,cls.copy=load_sources()

    @classmethod
    def tearDownClass(cls):
        for k in list(sys.modules):
            if k==PACKAGE or k.startswith(PACKAGE+'.'): del sys.modules[k]
        sys.modules.update(cls.previous)

    def setUp(self): self.conn=Connection(self.part)

    def request(self,code=11,**updates):
        current=self.core.read_current(self.conn,code)
        body=dict(expected_seq=current['event_seq'],expected_basis=current['basis'],
                  request_id=str(uuid4()),note='실제 원문과 현재 설명 대조',actor=deepcopy(self.conn.actor))
        body.update(updates); return body

    def approve(self,code=11,**updates): return self.core.approve(self.conn,code,**self.request(code,**updates))

    def revoke(self,code=11,**updates):
        body=dict(expected_seq=self.conn.events[-1]['event_seq'],request_id=str(uuid4()),note='설명 승인 회수',actor=self.conn.actor)
        body.update(updates); return self.core.revoke(self.conn,code,**body)

    def error(self,status,function,*args,**kwargs):
        with self.assertRaises(HTTPException) as caught: function(*args,**kwargs)
        self.assertEqual(caught.exception.status_code,status)
        return caught.exception.detail

    def writes(self): return [(q,p) for q,p in self.conn.calls if '*/ UPDATE ' in q or '*/ INSERT ' in q]

    def test_approve_read_current_exact_native_binding_and_internal_scope(self):
        original=deepcopy(self.conn.explanations[11])
        expected=self.request(); result=self.core.approve(self.conn,11,**expected)
        self.assertTrue(result['current']['allowed']); self.assertFalse(result['committed'])
        self.assertFalse(result['replayed']); self.assertEqual(result['current']['scope'],'internal_part_description')
        row=self.conn.row(11); event=result['event']
        self.assertEqual(row['approved_by'],2**40); self.assertEqual(event['snapshot']['approved_by'],2**40)
        self.assertEqual(event['approval_basis'],self.core.basis(row))
        self.assertEqual(event['recorded_at'],NOW.isoformat()); self.assertEqual(event['snapshot']['approved_at'],NOW.isoformat())
        self.assertNotEqual(expected['expected_basis'],result['current']['basis'])
        for key in ('content','source_snapshot','source_fingerprint','product_code'):
            self.assertEqual(self.conn.explanations[11][key],original[key])
        self.assertEqual(result['current']['explanation_hash'],self.copy.explanation_digest(row))
        self.assertNotIn('customer_publishable',result['current'])

    def assembly(self,code=11):
        e=self.conn.explanations[code]; e['product_code']=None; e['content']['availability_scope']='assembly_only'

    def test_assembly_only_part_without_retail_product_is_approved_with_history(self):
        # 2026-10-10 owner decision: spec values are not a gate; BOM-only parts are approvable.
        self.assembly()
        self.assertTrue(self.part.is_current(self.conn.row(11)))
        result=self.approve()
        self.assertTrue(result['current']['allowed']); self.assertEqual(result['current']['state'],'approved')
        self.assertIsNone(result['event']['snapshot']['product_code'])
        self.assertEqual(result['event']['operator_id'],self.conn.actor['operator_id'])
        self.assertEqual(len(self.conn.events),1)
        self.assertNotIn('product_lock',[q.split('*/',1)[0].split(':',1)[1] for q,p in self.conn.calls])
        # Not an individual retail page: the legacy public part GET stays closed.
        self.assertFalse(self.part.can_publish(self.conn.row(11)))
        self.conn.now=NOW+timedelta(seconds=1); r=self.revoke()
        self.assertEqual(r['current']['state'],'revoked'); self.assertTrue(r['event']['metadata_reset'])

    def test_assembly_only_still_requires_source_evidence_review_and_marker(self):
        self.assembly(); self.conn.explanations[11]['source_fingerprint']='0'*64
        self.assertFalse(self.part.is_current(self.conn.row(11)))
        self.assertEqual(self.error(422,self.approve),'part_approval_source_stale')
        self.setUp(); self.assembly(); self.conn.explanations[11]['content']['review_issues']=['확인 필요']
        self.assertEqual(self.error(422,self.approve),'part_approval_review_issues')
        self.setUp(); self.conn.explanations[11]['product_code']=None
        self.assertFalse(self.part.is_current(self.conn.row(11)))
        self.assertEqual(self.error(422,self.approve),'part_approval_unlinked')
        self.assertEqual(self.conn.events,[])

    def test_assembly_only_content_change_after_approval_is_stale(self):
        self.assembly(); self.approve()
        self.conn.explanations[11]['content']['role']='changed'
        self.assertEqual(self.core.read_current(self.conn,11)['state'],'stale')

    def test_native_public_get_effect_requires_separate_activation_review(self):
        self.assertFalse(self.part.can_publish(self.conn.row(11)))
        self.approve(); self.assertTrue(self.part.can_publish(self.conn.row(11)))
        # Deliberate evidence of the legacy consumer effect, NOT publication acceptance.
        self.assertEqual(self.core.read_current(self.conn,11)['scope'],'internal_part_description')

    def test_missing_event_is_not_backfilled_from_legacy_metadata(self):
        self.conn.explanations[11].update(status='approved',approved_by=7,approved_at=PAST)
        r=self.core.read_current(self.conn,11)
        self.assertEqual(r['state'],'unapproved'); self.assertFalse(r['allowed']); self.assertEqual(self.conn.events,[])
        result=self.approve(); self.assertEqual(result['event']['operator_id'],self.conn.actor['operator_id'])
        self.assertEqual(result['event']['recorded_at'],NOW.isoformat()); self.assertNotEqual(result['event']['recorded_at'],PAST.isoformat())

    def test_normal_revoke_resets_only_its_native_metadata(self):
        a=self.approve(); original=deepcopy(self.conn.explanations[11])
        self.conn.now=NOW+timedelta(seconds=1); r=self.revoke()
        self.assertTrue(r['event']['metadata_reset']); self.assertEqual(r['current']['state'],'revoked')
        self.assertFalse(r['current']['allowed']); self.assertEqual(r['event']['snapshot'],a['event']['snapshot'])
        for key in ('content','source_snapshot','source_fingerprint','product_code'):
            self.assertEqual(self.conn.explanations[11][key],original[key])
        self.assertEqual(self.conn.explanations[11]['status'],'draft')
        self.assertIsNone(self.conn.explanations[11]['approved_by']); self.assertIsNone(self.conn.explanations[11]['approved_at'])

    def test_approval_replay_never_writes_again(self):
        body=self.request(); self.core.approve(self.conn,11,**body); count=len(self.writes())
        r=self.core.approve(self.conn,11,**body)
        self.assertTrue(r['replayed']); self.assertTrue(r['current']['allowed'])
        self.assertEqual(len(self.writes()),count); self.assertEqual(len(self.conn.events),1)

    def test_old_approval_replay_after_revoke_does_not_restore_authority(self):
        body=self.request(); self.core.approve(self.conn,11,**body); self.revoke(); count=len(self.writes())
        r=self.core.approve(self.conn,11,**body)
        self.assertTrue(r['replayed']); self.assertEqual(r['event']['event_seq'],1)
        self.assertEqual(r['current']['event_seq'],2); self.assertFalse(r['current']['allowed'])
        self.assertEqual(len(self.writes()),count); self.assertEqual(self.conn.explanations[11]['status'],'draft')

    def test_old_revoke_replay_after_new_approve_does_not_clear_new_metadata(self):
        self.approve(); body=dict(expected_seq=1,request_id=str(uuid4()),note='회수',actor=self.conn.actor)
        self.core.revoke(self.conn,11,**body); self.conn.now=NOW+timedelta(seconds=2); self.approve()
        before=deepcopy(self.conn.explanations[11]); count=len(self.writes())
        r=self.core.revoke(self.conn,11,**body)
        self.assertTrue(r['replayed']); self.assertEqual(r['event']['event_seq'],2)
        self.assertEqual(r['current']['event_seq'],3); self.assertTrue(r['current']['allowed'])
        self.assertEqual(self.conn.explanations[11],before); self.assertEqual(len(self.writes()),count)

    def test_old_screen_revoke_conflicts_with_new_approval(self):
        self.approve(); self.revoke(); self.approve(); before=deepcopy(self.conn.explanations)
        self.error(409,self.core.revoke,self.conn,11,expected_seq=1,request_id=str(uuid4()),note='과거 화면',actor=self.conn.actor)
        self.assertEqual(self.conn.explanations,before); self.assertEqual(len(self.conn.events),3)

    def test_uuid_binding_input_action_actor_code_and_note_conflicts(self):
        body=self.request(); self.core.approve(self.conn,11,**body)
        for changes in (dict(expected_seq=1),dict(expected_basis='e'*64),dict(note='다른 입력')):
            self.error(409,self.core.approve,self.conn,11,**dict(body,**changes))
        self.error(409,self.core.revoke,self.conn,11,expected_seq=1,request_id=body['request_id'],note=body['note'],actor=self.conn.actor)
        self.error(409,self.core.approve,self.conn,12,**body)
        self.conn.actor['operator_id']+=1
        self.error(409,self.core.approve,self.conn,11,**dict(body,actor=self.conn.actor))
        self.assertEqual(len(self.conn.events),1)

    def test_raw_note_whitespace_is_bound_not_normalized_for_replay(self):
        body=self.request(note=' 근거 '); r=self.core.approve(self.conn,11,**body)
        self.assertEqual(r['event']['note'],'근거')
        self.error(409,self.core.approve,self.conn,11,**dict(body,note='근거'))

    def test_sequence_and_expected_basis_compare_before_any_write(self):
        for changes in (dict(expected_seq=1),dict(expected_basis='d'*64)):
            self.error(409,self.core.approve,self.conn,11,**self.request(**changes))
        self.assertEqual(self.writes(),[]); self.assertEqual(self.conn.events,[])

    def test_invalid_native_code_seq_hash_uuid_note(self):
        class SubInt(int): pass
        body=self.request()
        for code in (None,True,0,-1,'11',11.0,SubInt(11),2**63): self.error(422,self.core.approve,self.conn,code,**body)
        for seq in (None,True,-1,'0',0.0,SubInt(0),2**63-1):
            self.error(422,self.core.approve,self.conn,11,**dict(body,expected_seq=seq))
        for hashvalue in (None,'A'*64,'a'*63,True):
            self.error(422,self.core.approve,self.conn,11,**dict(body,expected_basis=hashvalue))
        for uid in (None,True,'bad',''):
            self.error(422,self.core.approve,self.conn,11,**dict(body,request_id=uid))
        for note in ('',' ',None,'x'*3001):
            self.error(422,self.core.approve,self.conn,11,**dict(body,note=note))
        self.assertEqual(self.writes(),[])

    def test_bigint_actor_and_missing_bool_role_status_rejections(self):
        body=self.request(); self.assertTrue(self.approve()['current']['allowed'])
        for value in (None,True,0,-1,'7',7.0,2**63):
            self.error(403,self.core.approve,self.conn,11,**dict(body,actor=dict(self.conn.actor,operator_id=value)))
        for actor in (None,dict(self.conn.actor,role='viewer'),dict(self.conn.actor,status='정지')):
            self.error(403,self.core.approve,self.conn,11,**dict(body,actor=actor))
        self.conn.actor['status']='정지'
        self.error(403,self.core.approve,self.conn,11,**dict(body,actor=dict(self.conn.actor,status='활성')))

    def test_actual_actor_missing_or_role_changed_in_db(self):
        body=self.request(); self.conn.actor['operator_id']+=1
        self.error(403,self.core.approve,self.conn,11,**body)
        self.conn.actor['operator_id']-=1; self.conn.actor['role']='owner'
        self.error(403,self.core.approve,self.conn,11,**body)
        self.assertEqual(self.writes(),[])

    def test_source_content_and_native_metadata_edits_make_latest_stale(self):
        mutations=(lambda:self.conn.explanations[11]['content'].update(role='새 설명'),
            lambda:self.conn.explanations[11]['source_snapshot'].update(spec='new'),
            lambda:self.conn.explanations[11].update(source_fingerprint='d'*64),
            lambda:self.conn.explanations[11].update(approved_by=7),
            lambda:self.conn.explanations[11].update(approved_at=PAST),
            lambda:self.conn.explanations[11].update(updated_at=NOW+timedelta(seconds=1)),
            lambda:self.conn.products[101].update(spec_source_text='new'),
            lambda:self.conn.products[101].update(sale_price=Decimal('200.00')))
        for mutate in mutations:
            self.setUp(); self.approve(); mutate()
            self.assertFalse(self.core.read_current(self.conn,11)['allowed'])

    def test_retired_null_or_review_issues_cannot_be_approved(self):
        mutations=(lambda:self.conn.explanations[11].update(status='retired'),
            lambda:self.conn.explanations[11].update(product_code=None),
            lambda:self.conn.explanations[11]['content'].update(review_issues=['근거 보완']),
            lambda:self.conn.products[101].update(status='판매중지'),
            lambda:self.conn.products.pop(101),lambda:self.conn.products[101].update(spec_source_text='changed'))
        for mutate in mutations:
            self.setUp(); mutate(); self.error(422,self.core.approve,self.conn,11,**self.request())
            self.assertEqual(self.writes(),[])

    def test_source_snapshot_and_current_fingerprint_are_both_required(self):
        self.conn.explanations[11]['source_snapshot']['name']='other'
        self.error(422,self.core.approve,self.conn,11,**self.request())
        self.assertEqual(self.writes(),[])

    def test_original_trim_fallback_is_reused_without_refreshing_fingerprint(self):
        e=self.conn.explanations[11]; e['source_snapshot'].update(name='CPU ',spec='AM4 ')
        e['source_fingerprint']=self.part.fingerprint('CPU ','AM4 ')
        before=e['source_fingerprint']; self.assertTrue(self.part.is_current(self.conn.row(11)))
        self.assertTrue(self.approve()['current']['allowed']); self.assertEqual(e['source_fingerprint'],before)

    def test_late_product_drift_is_reread_after_lock(self):
        body=self.request(); self.conn.after_product_lock=lambda:self.conn.products[101].update(spec_source_text='new')
        self.error(409,self.core.approve,self.conn,11,**body)
        self.assertEqual(self.writes(),[])

    def test_lock_order_is_advisory_explanation_product_reread_actor(self):
        body=self.request(); self.conn.calls=[]; self.core.approve(self.conn,11,**body)
        queries=[q for q,p in self.conn.calls]
        self.assertIn('catalog_lock',queries[0]); self.assertIn('pg_advisory_xact_lock',queries[0])
        self.assertIn('FOR UPDATE OF e',queries[1]); self.assertIn('product_lock',queries[2])
        self.assertIn('row*/',queries[3]); self.assertNotIn('FOR UPDATE',queries[3]); self.assertIn('actor*/',queries[4])
        self.assertFalse(any('pc_configurations' in q for q in queries))

    def test_revoke_after_content_edit_clears_only_owned_metadata(self):
        self.approve(); e=self.conn.explanations[11]
        e['content']['role']='保留新内容'; e['source_snapshot']['spec']='new'
        e['source_fingerprint']='d'*64; e['updated_at']=NOW+timedelta(seconds=1)
        before=deepcopy(e); self.assertFalse(self.core.read_current(self.conn,11)['allowed'])
        r=self.revoke(); self.assertTrue(r['event']['metadata_reset'])
        for key in ('content','source_snapshot','source_fingerprint','product_code'): self.assertEqual(e[key],before[key])
        self.assertFalse(r['current']['allowed']); self.assertEqual(e['status'],'draft')

    def test_revoke_after_admin_draft_edit_performs_no_native_write(self):
        self.approve(); e=self.conn.explanations[11]
        e.update(status='draft',approved_by=None,approved_at=None,updated_at=NOW+timedelta(seconds=1)); e['content']['role']='edited'
        before=deepcopy(e); self.conn.calls=[]; r=self.revoke()
        self.assertFalse(r['event']['metadata_reset']); self.assertEqual(e,before)
        self.assertFalse(any('revoke_metadata*/' in q for q,p in self.conn.calls))

    def test_revoke_preserves_other_approval_metadata_and_retirement(self):
        for changes in (dict(approved_by=7),dict(approved_at=NOW+timedelta(seconds=1)),dict(status='retired')):
            self.setUp(); self.approve(); self.conn.explanations[11].update(**changes)
            before=deepcopy(self.conn.explanations[11]); r=self.revoke()
            self.assertFalse(r['event']['metadata_reset']); self.assertEqual(self.conn.explanations[11],before)
            self.assertEqual(r['current']['state'],'revoked')

    def test_revoke_unlinked_after_approval_keeps_null_and_new_body(self):
        self.approve(); e=self.conn.explanations[11]; e['product_code']=None; e['content']['role']='changed'
        r=self.revoke(); self.assertTrue(r['event']['metadata_reset'])
        self.assertIsNone(e['product_code']); self.assertEqual(e['content']['role'],'changed'); self.assertFalse(r['current']['allowed'])

    def test_missing_or_repeated_revoke_is_conflict(self):
        self.error(409,self.core.revoke,self.conn,11,expected_seq=0,request_id=str(uuid4()),note='회수',actor=self.conn.actor)
        self.approve(); self.revoke()
        self.error(409,self.core.revoke,self.conn,11,expected_seq=2,request_id=str(uuid4()),note='회수',actor=self.conn.actor)

    def test_revoke_request_replay_has_no_native_or_event_write(self):
        self.approve(); body=dict(expected_seq=1,request_id=str(uuid4()),note='회수',actor=self.conn.actor)
        self.core.revoke(self.conn,11,**body); count=len(self.writes())
        r=self.core.revoke(self.conn,11,**body); self.assertTrue(r['replayed'])
        self.assertEqual(len(self.writes()),count); self.assertEqual(len(self.conn.events),2)
        self.error(409,self.core.revoke,self.conn,11,**dict(body,note='다른 사유'))

    def test_missing_row_and_consistent_snapshot_contract(self):
        self.error(404,self.core.read_current,self.conn,99)
        self.conn.isolation='READ COMMITTED'
        self.assertTrue(self.approve()['current']['allowed'])
        # This port cannot prove MVCC; the caller must guarantee one snapshot.

    def test_caller_transaction_required_before_any_sql(self):
        body=self.request()
        for field,value in (('active',False),('nested',True),('transaction',None),('isolation','AUTOCOMMIT')):
            old=getattr(self.conn,field); setattr(self.conn,field,value); count=len(self.conn.calls)
            self.error(503,self.core.read_current,self.conn,11)
            self.error(503,self.core.approve,self.conn,11,**body)
            self.error(503,self.core.revoke,self.conn,11,expected_seq=0,request_id=str(uuid4()),note='회수',actor=self.conn.actor)
            self.assertEqual(len(self.conn.calls),count); setattr(self.conn,field,old)

    def test_sql_failure_before_update_leaves_no_pending_mutation(self):
        for tag in ('catalog_lock','row','product_lock','actor','request','latest','approve_metadata'):
            self.setUp(); body=self.request(); before=deepcopy(self.conn.explanations); self.conn.fail_tag=tag
            with self.assertRaises(RuntimeError) as caught: self.core.approve(self.conn,11,**body)
            self.assertIs(caught.exception,self.conn.error); self.assertEqual(self.conn.explanations,before); self.assertEqual(self.conn.events,[])

    def test_insert_failure_after_pending_metadata_requires_caller_whole_rollback(self):
        body=self.request(); self.conn.fail_tag='append'
        with self.assertRaises(RuntimeError) as caught: self.core.approve(self.conn,11,**body)
        self.assertIs(caught.exception,self.conn.error); self.assertEqual(self.conn.events,[])
        self.assertEqual(self.conn.explanations[11]['status'],'approved')  # Pending fake mutation, not a commit.
        self.conn.caller_discards_failed_tx(); self.assertEqual(self.conn.explanations[11]['status'],'draft')
        self.assertEqual(self.conn.events,[])

    def test_unique_insert_conflict_is_not_retry_or_success(self):
        body=self.request(); execute=self.conn.execute
        def raced(statement,params=None):
            if '/*part_approval:append*/' in str(statement): raise self.conn.error
            return execute(statement,params)
        with patch.object(self.conn,'execute',raced),self.assertRaises(RuntimeError) as caught:
            self.core.approve(self.conn,11,**body)
        self.assertIs(caught.exception,self.conn.error); self.assertEqual(self.conn.events,[])
        self.conn.caller_discards_failed_tx(); self.assertEqual(self.conn.explanations[11]['status'],'draft')

    def test_revoke_insert_failure_keeps_only_pending_reset_until_caller_discards(self):
        self.approve(); self.conn.before=deepcopy((self.conn.explanations,self.conn.products,self.conn.events))
        self.conn.fail_tag='append'
        with self.assertRaises(RuntimeError): self.revoke()
        self.assertEqual(self.conn.explanations[11]['status'],'draft'); self.assertEqual(len(self.conn.events),1)
        self.conn.caller_discards_failed_tx(); self.assertEqual(self.conn.explanations[11]['status'],'approved')
        self.assertEqual(len(self.conn.events),1)

    def test_metadata_or_append_result_validation_failure_propagates(self):
        body=self.request(); self.conn.after_update=lambda:self.conn.explanations[11]['content'].update(role='unexpected mutation')
        self.error(503,self.core.approve,self.conn,11,**body); self.assertEqual(self.conn.events,[])
        self.conn.caller_discards_failed_tx(); self.assertEqual(self.conn.explanations[11]['status'],'draft')
        self.setUp(); body=self.request(); execute=self.conn.execute
        def mismatch(statement,params=None):
            result=execute(statement,params)
            if '/*part_approval:append*/' in str(statement): result.rows[0]['request_digest']='d'*64
            return result
        with patch.object(self.conn,'execute',mismatch): self.error(503,self.core.approve,self.conn,11,**body)
        self.assertEqual(len(self.conn.events),1); self.conn.caller_discards_failed_tx(); self.assertEqual(self.conn.events,[])

    def test_tampered_latest_event_fails_closed_without_fallback(self):
        self.approve(); self.conn.events[0]['approval_basis']='d'*64
        self.error(503,self.core.read_current,self.conn,11)

    def test_timestamp_timezone_normalization_prevents_false_mismatch(self):
        self.approve(); before=self.core.read_current(self.conn,11)['basis']
        e=self.conn.explanations[11]; tz=timezone(timedelta(hours=9))
        e['approved_at']=e['approved_at'].astimezone(tz); e['updated_at']=e['updated_at'].astimezone(tz)
        r=self.core.read_current(self.conn,11); self.assertEqual(r['basis'],before); self.assertTrue(r['allowed'])

    def test_source_ast_has_no_tx_owner_router_config_write_or_seed(self):
        tree=ast.parse((ROOT/'api/part_explanation_approval.py').read_text(encoding='utf-8-sig'))
        forbidden={'engine','connect','begin','commit','rollback','close','current_operator_id','APIRouter','save_review'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Name): self.assertNotIn(node.id,forbidden)
            if isinstance(node,ast.Attribute): self.assertNotIn(node.attr,forbidden)
        sql='\n'.join(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str))
        self.assertNotIn('pc_configurations',sql); self.assertNotIn('source_fingerprint=',sql)
        self.assertNotIn('content=',sql); self.assertNotIn('source_snapshot=',sql)

    def test_migration_preflight_and_metadata_guards_are_source_only(self):
        filename=ROOT/'db/migrations/versions/0130_part_explanation_approval.py'
        tree=ast.parse(filename.read_text(encoding='utf-8-sig')); ns=dict(text=text)
        import re
        ns['re']=re
        nodes=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(filename),'exec'),ns)
        self.assertEqual(ns['revision'],'0130'); self.assertEqual(ns['down_revision'],'0129')
        sql=ns['UPGRADE_SQL']; self.assertEqual(sql.count('CREATE TABLE '),1)
        self.assertLess(sql.index('pg_catalog.pg_attribute'),sql.index('ALTER TABLE'))
        for fragment in ("'pg_catalog.int4'::regtype","'pg_catalog.int8'::regtype",'confrelid=a_oid',
            'confkey=ARRAY[a_col]::smallint[]','conkey=ARRAY[e_col]::smallint[]',"contype='p'",'NOT condeferrable',
            'ALTER COLUMN approved_by TYPE BIGINT','operator_id BIGINT NOT NULL REFERENCES',
            'BEFORE INSERT OR UPDATE OR DELETE','BEFORE TRUNCATE','DEFERRABLE INITIALLY DEFERRED',
            'x.write_txid=txid_current()','Part native approval requires same-transaction immutable event',
            'NEW.snapshot IS DISTINCT FROM previous.snapshot'):
            self.assertIn(fragment,sql)
        self.assertNotRegex(sql,r'(?i)\b(GRANT|DROP|DELETE FROM)\b')
        with self.assertRaises(RuntimeError): ns['downgrade']()
        class Bind:
            def __init__(self,value): self.value=value
            def execute(self,*args): return self
            def scalar_one(self): return self.value
        self.assertEqual(ns['_schema'](Bind('source_test')),'"source_test"')
        for value in ('','public;DROP x','a.b',None,True):
            with self.assertRaises(RuntimeError): ns['_schema'](Bind(value))
        captured=[]
        class Op:
            def get_bind(self): return Bind('source_test')
            def execute(self,value): captured.append(value)  # String capture, NO SQL interpreter/DB.
        ns['op']=Op(); ns['upgrade']()
        self.assertEqual(len(captured),1); self.assertNotIn('__S__',captured[0])
        self.assertIn('"source_test".product_explanations',captured[0])


if __name__=='__main__':
    unittest.main()
