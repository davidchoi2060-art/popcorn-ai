"""Caller-connection simulation and SQL contract checks; NOT PostgreSQL proof."""
from copy import deepcopy
import ast
import json
from pathlib import Path
import re
import unittest

from api import commerce_contract as c
from api import commerce_writer as w
from tests.test_commerce_contract import owner, policy, sale, draft
from tests.test_commerce_payment_core import spec, evidence, verifier, OP, OTHER

CONTEXT = '577fbb7b-524c-487a-9192-e266272532cb'


class Result:
    def __init__(self, rows=(), scalar=None, rowcount=1):
        self.rows, self.scalar, self.rowcount = deepcopy(list(rows)), scalar, rowcount
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def one(self):
        if len(self.rows) != 1: raise RuntimeError('fixture wrong cardinality')
        return self.rows[0]
    def scalar_one(self): return self.scalar


class Connection:
    """A deliberately limited state simulator, never a SQL/database emulator."""
    def __init__(self):
        self.txid, self.aborted, self.trace, self.fail_tag = 1, False, [], None
        self.data = dict(products={101:dict(product_code=101,stock_qty=3,status='판매중',
          pricing_basis_revision=1,commerce_stock_revision=1)}, orders={}, details={}, operations={},
          reservations=[], payments=[], movements=[], events={})
        self.saved = deepcopy(self.data)
        self.context = dict(context_id=CONTEXT,owner_scope=c.fingerprint(owner()),owner_identity=owner(),
                            expires_at=1000,revoked_at=None)
    def in_transaction(self): return True
    def in_nested_transaction(self): return False
    def get_execution_options(self): return {}
    def commit_simulation(self):
        if self.aborted: raise RuntimeError('aborted simulation cannot commit')
        self.saved = deepcopy(self.data); self.txid += 1
    def rollback_simulation(self):
        self.data = deepcopy(self.saved); self.aborted=False; self.txid+=1
    def order(self, no):
        o=self.data['orders'].get(no)
        if not o: return None
        return o | self.data['details'][o['order_id']]
    def execute(self, statement, params):
        sql=str(statement)
        match=re.search(r'/\*commerce:(\w+)\*/',sql)
        tag=match[1] if match else 'product_lock'
        self.trace.append((tag,sql,deepcopy(params)))
        if tag=='abort': self.aborted=True; raise RuntimeError('fixture abort')
        if self.aborted: raise RuntimeError('fixture aborted')
        if tag==self.fail_tag: raise RuntimeError('fixture injected private SQL failure')
        d=self.data; p=params
        if tag=='txid': return Result(scalar=self.txid)
        if tag=='policy_lock': return Result()
        if tag=='policy_revision': return Result(scalar=1)
        if tag=='product_lock': return Result(sorted(pc for pc in p['codes'] if pc in d['products']))
        if tag=='products': return Result([d['products'][pc] for pc in p['codes'] if pc in d['products']])
        if tag=='claims': return Result([r for r in d['reservations'] if r['product_code'] in p['codes'] and
          (r['status']=='protected' or (r['status']=='held' and r['expires_epoch']>p['now']))])
        if tag=='context': return Result([self.context] if p['id']==CONTEXT else [])
        if tag in ('order','order_lock'):
            row=self.order(p['no']); return Result([row] if row else [])
        if tag=='order_bundle':
            # Capture the statement's data before any boundary interleave hook.
            observed=deepcopy(d); order=observed['orders'].get(p['no'])
            if order is None: return Result()
            row=order|observed['details'][order['order_id']]
            payments=[x for x in observed['payments'] if x['order_id']==order['order_id']]
            money=dict(approved=sum(x['amount'] for x in payments if x['amount']>0),
                       refunded=-sum(x['amount'] for x in payments if x['amount']<0))
            proofs=[]
            for payment in payments:
                record=observed['operations'].get(payment['operation_id'])
                if (payment['amount']>=0 and record is not None and record['order_id']==order['order_id']
                      and record['operation']['spec']['kind']=='approve' and record['operation']['state']=='confirmed'):
                    proofs.append(dict(approval_payment_id=payment['payment_id'],approval_amount=payment['amount'],
                      approval_operation=record['operation'],approval_verification=record['verification'],
                      approval_write_txid=record['write_txid']))
            empty=dict.fromkeys(('approval_payment_id','approval_amount','approval_operation',
                                 'approval_verification','approval_write_txid'))
            return Result([row|money|proof for proof in (proofs or [empty])])
        if tag=='draft_replay': return Result([dict(order_no=o['order_no'],snapshot=d['details'][o['order_id']]['snapshot'])
          for o in d['orders'].values() if d['details'][o['order_id']]['owner_scope']==p['scope'] and
          d['details'][o['order_id']]['request_id']==p['rid']])
        if tag=='insert_order':
            if p['no'] in d['orders']: raise RuntimeError('fixture duplicate order')
            oid=len(d['orders'])+1
            d['orders'][p['no']]=dict(order_id=oid,order_no=p['no'],order_state='접수',total_amount=p['total'])
            return Result(scalar=oid)
        if tag=='insert_detail':
            d['details'][p['oid']]=dict(context_id=p['context'],owner_scope=p['scope'],owner_identity=json.loads(p['owner']),
              request_id=p['rid'],request_basis=p['basis'],snapshot=json.loads(p['snapshot']),policy_snapshot=json.loads(p['policy']),
              provider_binding=json.loads(p['binding']) if p['binding'] else None,states=json.loads(p['states']),
              revision=1,expires_at=p['expires'],write_txid=self.txid)
            return Result()
        if tag=='insert_item' or tag in ('order_event','paid_event'): return Result()
        if tag=='insert_reservation':
            d['reservations'].append(dict(reservation_id=len(d['reservations'])+1,order_id=p['oid'],product_code=p['code'],
                                         qty=p['qty'],status='held',expires_epoch=p['expires']))
            d['products'][p['code']]['commerce_stock_revision']+=1; return Result()
        if tag=='balance':
            rows=[x for x in d['payments'] if x['order_id']==p['oid']]
            return Result([dict(approved=sum(x['amount'] for x in rows if x['amount']>0),
                                refunded=-sum(x['amount'] for x in rows if x['amount']<0))])
        if tag in ('operation','operation_lock'):
            r=d['operations'].get(p['id']); return Result([r] if r else [])
        if tag in ('request_operation','active_operation'):
            rows=[r for r in d['operations'].values() if r['order_id']==p['oid'] and
              (r['operation']['state'] in ('prepared','processing','unknown') if tag=='active_operation' else
               r['operation']['spec']['kind']==p['kind'] and r['operation']['spec']['request_id']==p['rid'])]
            return Result(rows)
        if tag=='insert_operation':
            if p['id'] in d['operations'] or any(x['order_id']==p['oid'] and x['operation']['state'] in
              ('prepared','processing','unknown') for x in d['operations'].values()): raise RuntimeError('fixture unique')
            d['operations'][p['id']]=dict(operation=json.loads(p['operation']),verification=None,write_txid=self.txid,order_id=p['oid'])
            return Result()
        if tag=='update_operation':
            row=d['operations'][p['id']]
            if row['operation']['revision']!=p['revision']: return Result(rowcount=0)
            row.update(operation=json.loads(p['operation']),write_txid=self.txid)
            if p.get('verification') is not None: row['verification']=json.loads(p['verification'])
            return Result()
        if tag=='update_order':
            row=d['details'][p['oid']]
            if row['revision']!=p['revision']: return Result(rowcount=0)
            row.update(states=json.loads(p['states']),revision=row['revision']+1,write_txid=self.txid); return Result()
        if tag=='reservations':
            for r in d['reservations']:
                if r['order_id']==p['oid'] and r['status'] in ('held','protected'):
                    r['status']=p['target']; d['products'][r['product_code']]['commerce_stock_revision']+=1
            return Result()
        if tag=='insert_payment':
            if any(x['operation_id']==p['id'] for x in d['payments']): raise RuntimeError('fixture payment unique')
            pid=len(d['payments'])+1
            d['payments'].append(dict(payment_id=pid,order_id=p['oid'],operation_id=p['id'],amount=p['amount'],key=p['key']))
            return Result(scalar=pid)
        if tag=='insert_movement':
            if any(x['key']==p['key'] for x in d['movements']): raise RuntimeError('fixture effect unique')
            d['movements'].append(deepcopy(p)); return Result()
        if tag=='decrement_stock':
            product=d['products'][p['code']]
            if product['stock_qty']<p['qty']: return Result(rowcount=0)
            product['stock_qty']+=p['delta']; product['commerce_stock_revision']+=1; return Result()
        if tag=='paid_order':
            for o in d['orders'].values():
                if o['order_id']==p['oid']: o['order_state']='결제완료'
            return Result()
        if tag=='committed_approval':
            return Result([dict(payment_id=x['payment_id'],amount=x['amount'],operation=d['operations'][x['operation_id']]['operation'],
              verification=d['operations'][x['operation_id']]['verification'],
              write_txid=d['operations'][x['operation_id']]['write_txid']) for x in d['payments'] if
              x['order_id']==p['oid'] and x['amount']>0])
        if tag=='event_lookup':
            x=d['events'].get((p['provider'],p['environment'],p['merchant'],p['key'])); return Result([x] if x else [])
        if tag=='insert_event':
            d['events'][(p['provider'],p['environment'],p['merchant'],p['key'])]=dict(operation_id=p['id'],evidence_basis=p['basis'])
            return Result()
        raise AssertionError('unhandled fixture SQL '+tag)


def reader(conn, source, now):
    value=sale()
    products=[dict(conn.data['products'][101])]
    claims=[dict(x) for x in conn.data['reservations'] if x['status']=='protected' or (x['status']=='held' and x['expires_epoch']>now)]
    value['stock_basis']=c.fingerprint(dict(products=products,claims=claims))
    return dict(sale_basis=value,policy=policy(),provider_binding={k:spec()[k] for k in
                ('adapter_id','provider','environment','merchant_id','provider_order_id')})


class WriterTests(unittest.TestCase):
    def setUp(self): self.conn=Connection()
    def draft(self):
        return w.create_draft(self.conn,draft(),context_id=CONTEXT,owner=owner(),order_no='fixture-order',
                             sale_basis=sale(),policy=policy(),now=100,revalidate=reader)
    def basis(self):
        return w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=150)['basis_id']
    def prepared(self):
        self.draft(); self.conn.commit_simulation()
        basis=self.basis(); value=spec(order_basis=basis)
        w.prepare(self.conn,value,context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=policy(),now=105,revalidate=reader)
        self.conn.commit_simulation(); return value
    def processing(self):
        self.prepared(); w.dispatch(self.conn,OP,expected_revision=1,now=110,lease_expires_at=130)
        self.conn.commit_simulation(); return w.read_committed_operation(self.conn,OP,now=120)
    def paid(self):
        operation=self.processing(); event=evidence(operation)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120)
        self.conn.commit_simulation(); return w.read_committed_operation(self.conn,OP,now=120)

    def test_full_flow_returns_pending_until_new_transaction_and_allocates_once(self):
        self.paid()
        result=w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=130)
        self.assertEqual(c.order_detail(result['row'])['total'],'2100')
        self.assertEqual(result['row']['allocation_state'],'allocated')
        self.assertEqual(len(self.conn.data['payments']),1)
        self.assertEqual(self.conn.data['products'][101]['stock_qty'],1)
        self.assertEqual(len(self.conn.data['movements']),1)
        tags=[x[0] for x in self.conn.trace]
        self.assertLess(tags.index('policy_lock'),tags.index('product_lock'))
        paid_index=tags.index('insert_payment')
        self.assertLess(tags.index('reservations',paid_index),tags.index('decrement_stock'))
        self.assertTrue(all(':no' in sql for tag,sql,_ in self.conn.trace if tag=='order_lock'))

    def test_uncommitted_draft_and_prepared_dispatch_abort_entire_caller_tx(self):
        self.draft()
        with self.assertRaisesRegex(c.CommerceError,'commit_not_visible'): self.basis()
        with self.assertRaises(RuntimeError): self.conn.commit_simulation()
        self.conn.rollback_simulation(); self.assertEqual(self.conn.data['orders'],{})
        self.prepared(); self.conn.data['operations'][OP]['write_txid']=self.conn.txid
        with self.assertRaisesRegex(c.CommerceError,'commit_not_visible'):
            w.dispatch(self.conn,OP,expected_revision=1,now=110,lease_expires_at=130)

    def test_mid_finalization_failure_aborts_even_if_caller_catches_and_preserves_prior_commits(self):
        operation=self.processing(); event=evidence(operation); self.conn.fail_tag='decrement_stock'
        with self.assertRaisesRegex(c.CommerceError,'commerce_writer_failed'):
            w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120)
        self.assertEqual(len(self.conn.data['payments']),1)  # pending partial writes, never committable
        with self.assertRaises(RuntimeError): self.conn.commit_simulation()
        self.conn.rollback_simulation()
        self.assertEqual(self.conn.data['payments'],[])
        self.assertEqual(self.conn.data['products'][101]['stock_qty'],3)
        self.assertEqual(self.conn.data['operations'][OP]['operation']['state'],'processing')

    def test_response_loss_replay_and_terminal_duplicate_do_not_duplicate_money_or_stock(self):
        operation=self.paid(); before=deepcopy(self.conn.data)
        result=w.finalize(self.conn,OP,evidence(operation),verifier(operation,evidence(operation)),expected_revision=3,now=130)
        self.assertEqual(result['action'],'read_result'); self.assertEqual(before,self.conn.data)
        replay=self.draft(); self.assertEqual(replay['order_no'],'fixture-order'); self.assertEqual(before,self.conn.data)

    def test_changed_payload_owner_context_or_revision_fails_closed(self):
        self.draft(); self.conn.commit_simulation()
        bad=draft(); bad['shipping']['name']='different'
        with self.assertRaisesRegex(c.CommerceError,'request_conflict'):
            w.create_draft(self.conn,bad,context_id=CONTEXT,owner=owner(),order_no='another',sale_basis=sale(),policy=policy(),now=100,revalidate=reader)
        self.conn.rollback_simulation()
        with self.assertRaises(c.CommerceError):
            w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner()|{'owner_hash':'f'*64},now=110)
        self.conn.rollback_simulation()
        self.conn.context['revoked_at']=110
        with self.assertRaisesRegex(c.CommerceError,'owner_unconfirmed'): self.basis()

    def test_stale_cas_and_second_active_operation_abort(self):
        self.prepared()
        with self.assertRaisesRegex(c.CommerceError,'operation_revision_conflict'):
            w.dispatch(self.conn,OP,expected_revision=99,now=110,lease_expires_at=130)
        self.conn.rollback_simulation(); basis=self.basis()
        second=spec(operation_id=OTHER,request_id=OTHER,order_basis=basis)
        with self.assertRaisesRegex(c.CommerceError,'active_operation_conflict'):
            w.prepare(self.conn,second,context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=policy(),now=110,revalidate=reader)

    def test_unknown_expiry_protects_and_late_success_uses_same_operation(self):
        self.processing(); w.mark_unresolved(self.conn,OP,expected_revision=2,reason='transport_lost',now=140)
        self.conn.commit_simulation()
        result=w.expire(self.conn,'fixture-order',expected_basis=self.basis(),now=300)
        self.assertEqual(result['action'],'query_required'); self.assertEqual(self.conn.data['reservations'][0]['status'],'protected')
        operation=w.read_committed_operation(self.conn,OP,now=300); event=evidence(operation,observed_at=300)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=3,now=300)
        self.conn.commit_simulation(); self.assertEqual(self.conn.data['products'][101]['stock_qty'],1)

    def test_unprocessed_expiry_releases_and_never_creates_money(self):
        self.prepared(); basis=self.basis()
        w.expire(self.conn,'fixture-order',expected_basis=basis,now=200); self.conn.commit_simulation()
        self.assertEqual(self.conn.data['reservations'][0]['status'],'released')
        self.assertEqual(self.conn.data['operations'][OP]['operation']['state'],'expired')
        self.assertEqual(self.conn.data['payments'],[])

    def test_money_success_is_preserved_when_product_stops_and_allocation_blocks(self):
        operation=self.processing(); self.conn.data['products'][101]['status']='단종'
        event=evidence(operation)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120); self.conn.commit_simulation()
        result=w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=130)
        self.assertEqual(result['row']['payment_state'],'confirmed'); self.assertEqual(result['row']['allocation_state'],'blocked')
        self.assertEqual(self.conn.data['products'][101]['stock_qty'],3); self.assertEqual(self.conn.data['movements'],[])
        self.assertEqual(result['row']['order_state'],'접수')

    def test_cancel_remaining_balance_guest_policy_change_and_no_automatic_stock_return(self):
        original=self.paid(); basis=self.basis()
        changed_policy=policy(); changed_policy['capabilities']['guest_checkout']=False; changed_policy['policy_basis']='9'*64
        value=spec('cancel',operation_id=OTHER,request_id=OTHER,order_basis=basis,refunded_amount=0,amount=2100,
                   original_operation_id=OP,original_provider_ref=original['provider_result']['provider_ref'],
                   capabilities=changed_policy['capabilities'])
        w.prepare(self.conn,value,context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=changed_policy,now=130)
        self.conn.commit_simulation(); w.dispatch(self.conn,OTHER,expected_revision=1,now=131,lease_expires_at=150)
        self.conn.commit_simulation(); operation=w.read_committed_operation(self.conn,OTHER,now=140)
        event=evidence(operation,observed_at=140,provider_ref='fixture-cancel-ref')
        w.finalize(self.conn,OTHER,event,verifier(operation,event),expected_revision=2,now=140); self.conn.commit_simulation()
        self.assertEqual([x['amount'] for x in self.conn.data['payments']],[2100,-2100])
        self.assertEqual(self.conn.data['products'][101]['stock_qty'],1); self.assertEqual(len(self.conn.data['movements']),1)
        self.assertEqual(self.conn.data['details'][1]['states']['refund_state'],'refunded')

    def test_absent_source_provider_and_wrong_stock_token_never_get_approval(self):
        for override, code in ((None,'sale_reader_required'),(lambda conn,source,now: reader(conn,source,now)|
             {'sale_basis':sale()},'stock_basis_changed')):
            with self.subTest(code=code),self.assertRaisesRegex(c.CommerceError,code):
                w.create_draft(self.conn,draft(),context_id=CONTEXT,owner=owner(),order_no='fixture-order',sale_basis=sale(),
                               policy=policy(),now=100,revalidate=override)
            self.conn.rollback_simulation()
        self.draft(); self.conn.commit_simulation(); self.conn.data['details'][1]['provider_binding']=None
        basis=self.basis()
        with self.assertRaisesRegex(c.CommerceError,'provider_unconfirmed'):
            w.prepare(self.conn,spec(order_basis=basis),context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=policy(),now=110,revalidate=reader)

    def test_other_active_hold_is_subtracted_before_second_draft_mutates(self):
        self.draft(); self.conn.commit_simulation(); before=deepcopy(self.conn.data)
        second=draft()|{'request_id':OTHER}
        with self.assertRaisesRegex(c.CommerceError,'stock_insufficient'):
            w.create_draft(self.conn,second,context_id=CONTEXT,owner=owner(),order_no='second-order',
                           sale_basis=sale(),policy=policy(),now=110,revalidate=reader)
        self.conn.rollback_simulation(); self.assertEqual(before,self.conn.data)

    def test_concurrent_cancel_intents_are_serialized_and_balance_is_rechecked(self):
        original=self.paid(); basis=self.basis()
        value=spec('cancel',operation_id=OTHER,request_id=OTHER,order_basis=basis,refunded_amount=0,amount=2100,
                   original_operation_id=OP,original_provider_ref=original['provider_result']['provider_ref'])
        w.prepare(self.conn,value,context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=policy(),now=130)
        self.conn.commit_simulation(); basis=self.basis()
        second=value|dict(operation_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',request_id=OP,order_basis=basis)
        with self.assertRaisesRegex(c.CommerceError,'active_operation_conflict'):
            w.prepare(self.conn,second,context_id=CONTEXT,owner=owner(),expected_basis=basis,policy=policy(),now=135)
        self.conn.rollback_simulation()
        self.assertEqual(len(self.conn.data['payments']),1)
        self.assertEqual(self.conn.data['operations'][OTHER]['operation']['state'],'prepared')

    def test_nontransactional_connection_refused_and_source_owns_no_engine_or_commit(self):
        self.conn.in_transaction=lambda:False
        with self.assertRaisesRegex(c.CommerceError,'caller_transaction_required'): self.draft()
        tree=ast.parse((Path(__file__).resolve().parents[1]/'api/commerce_writer.py').read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if isinstance(n,ast.Name): self.assertNotIn(n.id,('engine','router','requests','httpx','create_engine'))
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute): self.assertNotIn(n.func.attr,('begin','commit','rollback','begin_nested'))

    def test_decline_after_product_stop_releases_only_own_claim_and_replay_is_no_effect(self):
        operation=self.processing()
        self.conn.data['reservations'].append(dict(reservation_id=2,order_id=99,product_code=101,qty=1,status='protected',expires_epoch=1))
        self.conn.data['products'][101]['status']='단종'; self.conn.commit_simulation()
        event=evidence(operation,status='declined',provider_ref=None)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120,event_key='fixture-decline')
        self.conn.commit_simulation()
        read=w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=130)
        self.assertEqual((read['row']['payment_state'],read['row']['allocation_state']),('declined','released'))
        self.assertEqual([x['status'] for x in self.conn.data['reservations']],['released','protected'])
        self.assertEqual(self.conn.data['payments'],[]); self.assertEqual(self.conn.data['movements'],[])
        before=deepcopy(self.conn.data)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=3,now=130,event_key='fixture-decline')
        self.assertEqual(before,self.conn.data)
        result=w.expire(self.conn,'fixture-order',expected_basis=self.basis(),now=300)
        self.assertEqual(result['action'],'none')

    def test_pending_not_found_bad_verify_and_decline_rollback_preserve_protected_claims(self):
        for status in ('pending','not_found'):
            self.setUp(); operation=self.processing(); self.conn.data['products'][101]['status']='단종'; self.conn.commit_simulation()
            event=evidence(operation,status=status,provider_ref=None)
            w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120)
            self.conn.commit_simulation(); self.assertEqual(self.conn.data['reservations'][0]['status'],'protected')
        self.setUp(); operation=self.processing(); self.conn.data['products'][101]['status']='단종'; self.conn.commit_simulation()
        event=evidence(operation,status='declined',provider_ref=None); before=deepcopy(self.conn.data)
        with self.assertRaises(c.CommerceError):
            w.finalize(self.conn,OP,event,verifier(operation,event)|{'evidence_basis':'0'*64},expected_revision=2,now=120)
        self.conn.rollback_simulation(); self.assertEqual(before,self.conn.data)
        self.conn.fail_tag='update_order'
        with self.assertRaises(c.CommerceError):
            w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120)
        self.conn.rollback_simulation(); self.assertEqual(before,self.conn.data)

    def test_new_tx_probe_rejects_physical_autocommit_savepoint_and_visible_proof_tamper(self):
        self.conn.in_nested_transaction=lambda:True
        with self.assertRaisesRegex(c.CommerceError,'caller_transaction_required'): self.draft()
        self.setUp(); execute=self.conn.execute
        def autocommit(statement,params):
            result=execute(statement,params)
            if 'commerce:txid' in str(statement): self.conn.txid+=1
            return result
        self.conn.execute=autocommit
        with self.assertRaisesRegex(c.CommerceError,'caller_transaction_required'): self.draft()
        self.assertEqual(self.conn.data['orders'],{})
        self.setUp(); self.paid(); self.conn.data['operations'][OP]['verification']['evidence_basis']='0'*64
        with self.assertRaisesRegex(c.CommerceError,'provider_verification_mismatch'):
            w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=130)

    def test_dispatch_identity_requires_fresh_committed_plan_and_unexpired_lease(self):
        self.prepared(); pending=w.dispatch(self.conn,OP,expected_revision=1,now=110,lease_expires_at=130)
        with self.assertRaisesRegex(c.CommerceError,'commit_not_visible'):
            w.read_dispatch(self.conn,OP,dispatch_basis=pending['dispatch_basis'],now=110)
        self.conn.rollback_simulation(); pending=w.dispatch(self.conn,OP,expected_revision=1,now=110,lease_expires_at=130)
        self.conn.commit_simulation()
        identity=w.read_dispatch(self.conn,OP,dispatch_basis=pending['dispatch_basis'],now=110)
        self.assertEqual(identity['idempotency_key'],OP)
        with self.assertRaisesRegex(c.CommerceError,'dispatch_not_available'):
            w.read_dispatch(self.conn,OP,dispatch_basis=pending['dispatch_basis'],now=130)

    def test_detail_bundle_uses_one_snapshot_before_and_after_other_backend_commit(self):
        self.paid(); before=deepcopy(self.conn.data); caller_txid=self.conn.txid
        after=deepcopy(before)
        after['details'][1]['states']['refund_state']='partial'
        after['details'][1]['revision']+=1; after['details'][1]['write_txid']=caller_txid+100
        after['payments'].append(dict(payment_id=2,order_id=1,operation_id=OTHER,amount=-400,key=OTHER+':payment'))
        execute=self.conn.execute; crossed=[]; self.conn.trace=[]
        def interleave(statement,params):
            result=execute(statement,params)
            if '/*commerce:order_bundle*/' in str(statement) and not crossed:
                # Model a foreign COMMIT after this statement's observation.
                # The caller TX remains unchanged; later statements see after.
                crossed.append(True); self.conn.data=deepcopy(after)
            return result
        self.conn.execute=interleave
        def project():
            read=w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=150)
            item=c.customer_order_detail(read['row'],context=dict(state='confirmed',binding_id=CONTEXT),
              checked_at=150,basis=dict(state='confirmed',basis_id=read['basis_id']),permissions=None,
              balances=dict(approved=read['approved'],refunded=read['refunded']))
            return read,item
        old_read,old=project(); new_read,new=project()
        self.assertEqual((old['refund_state'],old['refunded_amount']),('none','0'))
        self.assertEqual((new['refund_state'],new['refunded_amount']),('partial','400'))
        self.assertEqual(old_read['basis_id'],w._basis(before['orders']['fixture-order']|before['details'][1],2100,0))
        self.assertEqual(new_read['basis_id'],w._basis(after['orders']['fixture-order']|after['details'][1],2100,400))
        self.assertNotEqual(old_read['basis_id'],new_read['basis_id'])
        self.assertEqual(old_read['row']['committed_payment'],new_read['row']['committed_payment'])
        self.assertEqual(self.conn.txid,caller_txid); self.assertTrue(crossed)
        bundles=[sql for tag,sql,_ in self.conn.trace if tag=='order_bundle']
        self.assertEqual(len(bundles),2)
        for sql in bundles:
            self.assertIn('CROSS JOIN LATERAL',sql); self.assertIn('LEFT JOIN LATERAL',sql)
            self.assertIn('::bigint AS approved',sql); self.assertIn('::bigint AS refunded',sql)
            self.assertNotIn('FOR UPDATE',sql); self.assertNotIn('LIMIT',sql)
        self.assertTrue({'order','balance','committed_approval','policy_lock','product_lock','order_lock'}.isdisjoint(
          tag for tag,_,_ in self.conn.trace))

    def test_detail_bundle_null_duplicate_proof_owner_same_tx_and_exception_abort_fail_closed(self):
        cases=('missing','duplicate','null_proof','null_aggregate','non_native_json','same_tx_row','same_tx_proof',
               'owner','verification_drift','receipt_payment_drift','sql_exception')
        for case in cases:
            with self.subTest(case=case):
                self.setUp(); self.paid(); committed=deepcopy(self.conn.saved)
                if case=='missing': self.conn.data['orders'].clear()
                elif case=='duplicate': self.conn.data['payments'].append(deepcopy(self.conn.data['payments'][0]))
                elif case=='null_proof': self.conn.data['operations'].clear()
                elif case=='same_tx_row': self.conn.data['details'][1]['write_txid']=self.conn.txid
                elif case=='same_tx_proof': self.conn.data['operations'][OP]['write_txid']=self.conn.txid
                elif case=='owner': self.conn.context['owner_identity']=owner()|{'owner_hash':'f'*64}
                elif case=='verification_drift': self.conn.data['operations'][OP]['verification']['evidence_basis']='0'*64
                elif case=='receipt_payment_drift': self.conn.data['operations'][OP]['operation']['final_commit']['payment_id']=999
                elif case=='sql_exception': self.conn.fail_tag='order_bundle'
                if case in ('null_aggregate','non_native_json'):
                    execute=self.conn.execute
                    def corrupt_driver(statement,params):
                        result=execute(statement,params)
                        if '/*commerce:order_bundle*/' in str(statement):
                            result.rows[0]['approved' if case=='null_aggregate' else 'approval_operation']=None if case=='null_aggregate' else '{}'
                        return result
                    self.conn.execute=corrupt_driver
                self.conn.data['movements'].append(dict(pending_caller_marker=True))
                with self.assertRaises(c.CommerceError) as failure:
                    w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=150)
                if case=='missing': self.assertEqual(failure.exception.code,'order_not_found')
                elif case=='duplicate': self.assertEqual(failure.exception.code,'committed_approval_cardinality')
                elif case in ('same_tx_row','same_tx_proof'): self.assertEqual(failure.exception.code,'commit_not_visible')
                elif case=='sql_exception': self.assertEqual(failure.exception.code,'commerce_writer_failed')
                with self.assertRaises(RuntimeError): self.conn.commit_simulation()
                self.conn.rollback_simulation(); self.assertEqual(self.conn.data,committed)


    def admin_authorizer(self, *, order_no, now):
        """Simulated internal auth adapter; not a session/authentication proof."""
        return dict(auth_source='api.auth.current_operator', authenticated=True,
                    actor=dict(operator_id=9,role='viewer',status='활성'),
                    permission='commerce.order.read',allowed=True,order_no=order_no,checked_at=now)

    def test_admin_read_shares_proof_without_customer_context_expiry_or_cookie(self):
        self.paid()
        customer=w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=150)
        self.conn.context['expires_at']=149
        self.conn.context['revoked_at']=140
        self.conn.context['owner_identity']=owner()|{'owner_hash':'f'*64}
        self.conn.trace.clear(); before=deepcopy(self.conn.data); observed=[]
        def authorize(**scope):
            self.assertFalse(any(tag=='order_bundle' for tag,_,_ in self.conn.trace))
            observed.append(scope)
            return self.admin_authorizer(**scope)
        admin=w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=authorize)
        self.assertEqual(admin,customer)
        self.assertEqual(observed,[dict(order_no='fixture-order',now=150)])
        self.assertEqual(self.conn.data,before)
        self.assertEqual([tag for tag,_,_ in self.conn.trace if tag!='txid'],['order_bundle'])
        self.assertEqual(admin['row']['committed_payment']['payment_id'],1)
        with self.assertRaisesRegex(c.CommerceError,'owner_unconfirmed'):
            w.read_committed_order(self.conn,'fixture-order',context_id=CONTEXT,owner=owner(),now=150)

    def test_admin_missing_forged_unready_or_denied_authorization_precedes_financial_sql(self):
        cases=('missing','direct_dto','truthy_object','actor_id','empty','client_role',
               'wrong_source','unauthenticated','truthy_authenticated','denied','truthy_allowed',
               'wrong_permission','wrong_order','old_check','boolean_check','boolean_actor',
               'unknown_role','suspended','callback_exception')
        for case in cases:
            with self.subTest(case=case):
                self.setUp(); self.paid(); committed=deepcopy(self.conn.saved)
                grant=self.admin_authorizer(order_no='fixture-order',now=150)
                callback=lambda **scope:grant
                if case=='missing': callback=None
                elif case=='direct_dto': callback=grant
                elif case=='truthy_object': callback=object()
                elif case=='actor_id': callback=9
                elif case=='empty': grant={}
                elif case=='client_role': grant=dict(actor=dict(operator_id=9,role='owner'))
                elif case=='wrong_source': grant['auth_source']='client'
                elif case=='unauthenticated': grant['authenticated']=False
                elif case=='truthy_authenticated': grant['authenticated']=1
                elif case=='denied': grant['allowed']=False
                elif case=='truthy_allowed': grant['allowed']='true'
                elif case=='wrong_permission': grant['permission']='commerce.order.write'
                elif case=='wrong_order': grant['order_no']='some-other-order'
                elif case=='old_check': grant['checked_at']=149
                elif case=='boolean_check': grant['checked_at']=True
                elif case=='boolean_actor': grant['actor']['operator_id']=True
                elif case=='unknown_role': grant['actor']['role']='customer'
                elif case=='suspended': grant['actor']['status']='정지'
                elif case=='callback_exception':
                    def callback(**scope): raise RuntimeError('private authentication detail')
                self.conn.trace.clear()
                self.conn.data['movements'].append(dict(pending_caller_marker=True))
                with self.assertRaises(c.CommerceError) as failure:
                    w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=callback)
                self.assertTrue(all(tag in ('txid','abort') for tag,_,_ in self.conn.trace))
                if case in ('missing','direct_dto','truthy_object','actor_id'):
                    self.assertEqual(failure.exception.code,'admin_authorization_unready')
                if case=='callback_exception':
                    self.assertEqual(failure.exception.code,'commerce_writer_failed')
                    self.assertNotIn('private',str(failure.exception))
                with self.assertRaises(RuntimeError): self.conn.commit_simulation()
                self.conn.rollback_simulation(); self.assertEqual(self.conn.data,committed)

    def test_admin_reader_preserves_bundle_and_stored_proof_failure_guards(self):
        cases=('missing','duplicate','null_proof','null_aggregate','float_aggregate','non_native_json','same_tx_row',
               'same_tx_proof','stored_scope','stored_owner','verification_drift','receipt_payment_drift',
               'proof_amount','order_total','operation_order','operation_kind','operation_state','sql_exception')
        for case in cases:
            with self.subTest(case=case):
                self.setUp(); self.paid(); committed=deepcopy(self.conn.saved)
                if case=='missing': self.conn.data['orders'].clear()
                elif case=='duplicate': self.conn.data['payments'].append(deepcopy(self.conn.data['payments'][0]))
                elif case=='null_proof': self.conn.data['operations'].clear()
                elif case=='same_tx_row': self.conn.data['details'][1]['write_txid']=self.conn.txid
                elif case=='same_tx_proof': self.conn.data['operations'][OP]['write_txid']=self.conn.txid
                elif case=='stored_scope': self.conn.data['details'][1]['owner_scope']='f'*64
                elif case=='stored_owner':
                    changed=owner()|{'owner_hash':'f'*64}
                    self.conn.data['details'][1].update(owner_identity=changed,owner_scope=c.fingerprint(changed))
                elif case=='verification_drift': self.conn.data['operations'][OP]['verification']['evidence_basis']='0'*64
                elif case=='receipt_payment_drift': self.conn.data['operations'][OP]['operation']['final_commit']['payment_id']=999
                elif case=='proof_amount': self.conn.data['payments'][0]['amount']-=1
                elif case=='order_total': self.conn.data['orders']['fixture-order']['total_amount']-=1
                elif case=='operation_order': self.conn.data['operations'][OP]['operation']['spec']['order_no']='other'
                elif case=='operation_kind': self.conn.data['operations'][OP]['operation']['spec']['kind']='cancel'
                elif case=='operation_state': self.conn.data['operations'][OP]['operation']['state']='unknown'
                elif case=='sql_exception': self.conn.fail_tag='order_bundle'
                if case in ('null_aggregate','float_aggregate','non_native_json'):
                    execute=self.conn.execute
                    def corrupt_driver(statement,params):
                        result=execute(statement,params)
                        if '/*commerce:order_bundle*/' in str(statement):
                            result.rows[0]['approved' if case!='non_native_json' else 'approval_operation']=None if case=='null_aggregate' else 2100.0 if case=='float_aggregate' else '{}'
                        return result
                    self.conn.execute=corrupt_driver
                self.conn.data['movements'].append(dict(pending_caller_marker=True))
                with self.assertRaises(c.CommerceError) as failure:
                    w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=self.admin_authorizer)
                if case=='duplicate': self.assertEqual(failure.exception.code,'committed_approval_cardinality')
                elif case in ('same_tx_row','same_tx_proof'): self.assertEqual(failure.exception.code,'commit_not_visible')
                elif case=='stored_scope': self.assertEqual(failure.exception.code,'owner_scope_mismatch')
                elif case=='stored_owner': self.assertEqual(failure.exception.code,'owner_mismatch')
                with self.assertRaises(RuntimeError): self.conn.commit_simulation()
                self.conn.rollback_simulation(); self.assertEqual(self.conn.data,committed)

    def test_admin_bundle_observes_coherent_state_balance_before_and_after_commit_boundary(self):
        self.paid(); before=deepcopy(self.conn.data); crossed=[]; execute=self.conn.execute
        def cross_boundary(statement,params):
            result=execute(statement,params)
            if '/*commerce:order_bundle*/' in str(statement) and not crossed:
                crossed.append(True)
                self.conn.data['details'][1]['states']['refund_state']='partial'
                self.conn.data['details'][1]['revision']+=1
                self.conn.data['payments'].append(dict(order_id=1,amount=-400,payment_id=2,operation_id=OTHER))
            return result
        self.conn.execute=cross_boundary; txid=self.conn.txid; self.conn.trace.clear()
        first=w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=self.admin_authorizer)
        second=w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=self.admin_authorizer)
        self.assertEqual((first['row']['refund_state'],first['refunded']),('none',0))
        self.assertEqual((second['row']['refund_state'],second['refunded']),('partial',400))
        self.assertNotEqual(first['basis_id'],second['basis_id']); self.assertEqual(self.conn.txid,txid)
        self.assertEqual([tag for tag,_,_ in self.conn.trace if tag!='txid'],['order_bundle','order_bundle'])
        self.assertEqual(first['row']['committed_payment'],second['row']['committed_payment'])
        self.conn.data=before

    def test_admin_native_bigint_money_stays_exact_through_shared_proof_and_projection(self):
        unit=9007199254740993; total=unit*2+100
        def big_reader(conn,source,now):
            value=reader(conn,source,now)
            value['sale_basis']['lines'][0]['unit_amount']=unit
            value['sale_basis']['total']=total
            return value
        w.create_draft(self.conn,draft(),context_id=CONTEXT,owner=owner(),order_no='fixture-order',
                       sale_basis=sale(),policy=policy(),now=100,revalidate=big_reader)
        self.conn.commit_simulation()
        intent=spec(order_basis=self.basis(),amount=total,order_total=total)
        w.prepare(self.conn,intent,context_id=CONTEXT,owner=owner(),expected_basis=intent['order_basis'],
                  policy=policy(),now=105,revalidate=big_reader)
        self.conn.commit_simulation()
        w.dispatch(self.conn,OP,expected_revision=1,now=110,lease_expires_at=130)
        self.conn.commit_simulation()
        operation=w.read_committed_operation(self.conn,OP,now=120); event=evidence(operation)
        w.finalize(self.conn,OP,event,verifier(operation,event),expected_revision=2,now=120)
        self.conn.commit_simulation()
        read=w.read_committed_admin_order(self.conn,'fixture-order',now=150,authorize=self.admin_authorizer)
        self.assertIs(type(read['approved']),int); self.assertEqual(read['approved'],total)
        self.assertEqual(read['row']['committed_payment']['amount'],total)
        public=c.admin_order_detail(read['row'],context=dict(state='confirmed',binding_id=OTHER),
          checked_at=150,basis=dict(state='confirmed',basis_id=read['basis_id']),permissions=None,
          balances=dict(approved=read['approved'],refunded=read['refunded']),
          provider=dict(provider_environment='test',verification_state='confirmed',provider_checked_at=120))
        self.assertEqual(public['total'],str(total)); self.assertEqual(public['approved_amount'],str(total))
        self.assertTrue(all(not action['allowed'] for action in public['actions'].values()))
        self.assertNotIn('committed_payment',public); self.assertNotIn('provider_binding',public)


if __name__=='__main__': unittest.main()
