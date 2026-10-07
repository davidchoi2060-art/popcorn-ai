"""Real adapter calls over a limited SQL-result simulator; NOT PostgreSQL proof."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID
import ast
import json
import re
import unittest

from api import commerce_contract as c
from api import commerce_fulfillment_writer as w
from api import commerce_writer as money
from tests.test_commerce_writer import Connection as FinancialConnection, Result
from tests import test_commerce_fulfillment_core as fixture

PRIVATE = fixture.PRIVATE


class Connection(FinancialConnection):
    def __init__(self):
        super().__init__(); original=fixture.inputs(); order=original['order']; self.txid=2
        self.data=dict(products={code:dict(product_code=code,stock_qty=5,status='판매중',pricing_basis_revision=1,
            commerce_stock_revision=1) for code in (101,202)},
            orders={'fixture-order':dict(order_id=1,order_no='fixture-order',order_state='결제완료',total_amount=2100)},
            details={1:dict(context_id='577fbb7b-524c-487a-9192-e266272532cb',owner_scope=c.fingerprint(order['owner']),
                owner_identity=order['owner'],request_id=fixture.REQUEST,request_basis='f'*64,
                snapshot=dict(lines=fixture.sale_lines(),charges=[],basis_id='b'*64),
                policy_snapshot=dict(policy_basis='c'*64),provider_binding=None,
                states={key:order[key] for key in ('checkout_state','payment_state','allocation_state','refund_state')},
                revision=3,expires_at=500,write_txid=1)},
            operations={fixture.APPROVAL:dict(operation=original['approval']['operation'],verification=original['approval']['verification'],
                write_txid=1,order_id=1)},reservations=[],payments=[dict(payment_id=9,order_id=1,operation_id=fixture.APPROVAL,amount=2100)],
            movements=original['movements'],events={},physical_ops={},ships={},cargo=[],physical_events=[],refunds=[])
        self.saved=deepcopy(self.data); self.clock=100; self.serial=100; self.child_hook=None
        self.active=True; self.nested=False; self.options={}; self.cas_tag=None
    def in_transaction(self): return self.active
    def in_nested_transaction(self): return self.nested
    def get_execution_options(self): return self.options
    def execute(self,statement,params):
        sql=str(statement); match=re.search(r'/\*commerce:physical_(\w+)\*/',sql)
        if not match:
            if self.cas_tag=='update_order' and '/*commerce:update_order*/' in sql:
                self.trace.append(('update_order',sql,deepcopy(params))); return Result(rowcount=0)
            return super().execute(statement,params)
        tag=match[1]; self.trace.append(('physical_'+tag,sql,deepcopy(params)))
        if self.aborted: raise RuntimeError('fixture aborted')
        if self.fail_tag=='physical_'+tag: raise RuntimeError(PRIVATE)
        if self.cas_tag=='physical_'+tag: return Result(rowcount=0)
        d=self.data; p=params
        if self.child_hook is not None and tag=='shipments': self.child_hook(self)
        if tag=='operation': return Result([d['physical_ops'][p['id']]] if p['id'] in d['physical_ops'] else [])
        if tag=='financial_uuid': return Result([dict(operation_id=p['id'])] if p['id'] in d['operations'] else [])
        if tag=='financial_history': return Result([dict(operation_id=opid,order_no='fixture-order',kind=record['operation']['spec']['kind'],
            state=record['operation']['state']) for opid,record in sorted(d['operations'].items()) if record['order_id']==p['oid']])
        if tag=='sale_movements': return Result([{key:row[key] for key in ('movement_id','product_code','movement_type','qty_delta','operation_id','effect_key')}
            for row in d['movements']])
        if tag=='legacy_refunds': return Result(d['refunds'])
        if tag=='shipments': return Result([row for _,row in sorted(d['ships'].items()) if row['order_id']==p['oid']])
        if tag=='shipment_lines': return Result(sorted([row for row in d['cargo'] if row['order_id']==p['oid']],key=lambda row:(row['shipment_id'],row['line_id'])))
        if tag=='operations': return Result([row for _,row in sorted(d['physical_ops'].items()) if row['order_id']==p['oid']])
        if tag=='insert_shipment':
            sid=max(d['ships'],default=0)+10
            d['ships'][sid]=dict(shipment_id=sid,order_id=p['oid'],revision=1,state='준비',line_basis=p['basis'],
                carrier=None,tracking_no=None,tracking_evidence=None,handoff_evidence=None,delivery_evidence=None,
                readiness=None,readiness_operation_id=None,write_txid=self.txid)
            return Result(scalar=sid)
        if tag=='insert_line':
            d['cargo'].append(dict(order_id=p['oid'],shipment_id=p['sid'],line_id=p['line'],product_code=p['code'],qty=p['qty'],sale_movement_id=p['movement']))
            return Result()
        if tag=='insert_operation':
            if p['id'] in d['physical_ops']: raise RuntimeError('fixture unique physical ID')
            d['physical_ops'][p['id']]=dict(operation_id=p['id'],order_id=p['oid'],shipment_id=p['sid'],contract=p['contract'],
                action=p['action'],actor_id=p['actor'],owner_scope=p['scope'],request_basis=p['basis'],request=json.loads(p['request']),
                identity=json.loads(p['identity']),state='applied',revision=1,result=json.loads(p['result']),
                receipt=json.loads(p['receipt']),write_txid=self.txid)
            return Result()
        if tag=='update_shipment':
            ship=d['ships'][p['sid']]
            if ship['order_id']!=p['oid'] or ship['revision']!=p['revision']: return Result(rowcount=0)
            ship.update(revision=ship['revision']+1,state=p['state'],carrier=p['carrier'],tracking_no=p['tracking'],write_txid=self.txid,
                **{key:json.loads(p[key]) if p[key] is not None else None for key in ('tracking_evidence','handoff_evidence','delivery_evidence','readiness')},
                readiness_operation_id=p['ready_id'])
            return Result()
        if tag=='order_status':
            order=d['orders']['fixture-order']
            if order['order_id']!=p['oid'] or order['order_state']!=p['previous']: return Result(rowcount=0)
            order['order_state']=p['next']; return Result()
        if tag=='order_event': d['physical_events'].append(deepcopy(p)); return Result()
        raise AssertionError('unhandled physical SQL '+tag)


def policy(**changes):
    return dict(contract=w.POLICY_VERSION,policy_id='fixture preparation policy',policy_basis='d'*64,state='confirmed',
        order_no='fixture-order',allowed_commands=list(w.PREPARATION),assembly_required=True,
        required_events=['assembly_completed','inspection_recorded'],rule_basis='e'*64,allowed_refund_states=['none']) | changes


def rebind(req):
    normalized=deepcopy(req); normalized['operation_id']=c.uuid_text(req['operation_id'])
    normalized['lines']=w.core._lines(req['lines'])
    if req.get('contract')==w.VERSION:
        normalized['prerequisites']=w._refs(req['prerequisites'])
        if req['quantities'] is not None: normalized['quantities']=sorted(req['quantities'],key=lambda row:row['line_id'])
    req['request_basis']=c.fingerprint({key:value for key,value in normalized.items() if key!='request_basis'})
    return req


def prep_request(conn, action='prepare_shipment', *, sid=None, lines=None, event=None, quantities=None, outcome=None, refs=None, **changes):
    conn.serial+=1; conn.clock+=10; row=conn.order('fixture-order')
    lines=fixture.cargo_lines() if lines is None else lines
    req=dict(contract=w.VERSION,operation_id=str(UUID(int=conn.serial)),actor_id=7,order_no='fixture-order',action=action,
        expected_order_basis=money._basis(row,2100,0),expected_order_revision=row['revision'],expected_order_state=row['order_state'],
        expected_policy_basis='d'*64,shipment_id=sid,expected_shipment_revision=conn.data['ships'][sid]['revision'] if sid else None,
        lines=lines,event_kind=event,quantities=quantities,outcome=outcome,prerequisites=[] if refs is None else refs,evidence=None)
    req.update(changes)
    if action!='prepare_shipment':
        content=dict(lines=req['lines'],event_kind=req['event_kind'],quantities=req['quantities'],outcome=req['outcome'],
            prerequisites=sorted(req['prerequisites'],key=lambda ref:ref['operation_id']),policy_basis=req['expected_policy_basis'],rule_basis='e'*64)
        proof=dict(contract=w.EVIDENCE_VERSION,source='operator_record',state='confirmed',
            kind=event if action=='record_preparation_event' else 'dispatch_ready',order_no=req['order_no'],shipment_id=sid,actor_id=req['actor_id'],
            occurred_at=conn.clock,reference=PRIVATE,rules_basis='e'*64,content_basis=c.fingerprint(content))
        proof['basis']=c.fingerprint(proof); req['evidence']=proof
    return rebind(req)


def authorize(req, **changes):
    permission=w.PERMISSIONS[req['action']] if req['action'] in w.PREPARATION else 'commerce.fulfillment.write'
    def callback(*,order_no,action,now):
        return dict(auth_source='api.auth.current_operator',authenticated=True,allowed=True,
            actor=dict(operator_id=req['actor_id'],role='operator',status='활성'),permission=permission,
            order_no=order_no,action=action,checked_at=now) | deepcopy(changes)
    return callback


def shipping_request(conn, sid, action='record_tracking', **changes):
    conn.serial+=1; conn.clock+=10; row=conn.order('fixture-order')
    lines=[{key:item[key] for key in ('line_id','product_code','qty','sale_movement_id')} for item in conn.data['cargo'] if item['shipment_id']==sid]
    return fixture.request(action,operation_id=str(UUID(int=conn.serial)),expected_order_basis=money._basis(row,2100,0),
        expected_order_revision=row['revision'],shipment_id=sid,expected_shipment_revision=conn.data['ships'][sid]['revision'],
        lines=lines,evidence=fixture.manual(action,shipment_id=sid,lines=lines,occurred_at=conn.clock),**changes)


class FulfillmentWriterTests(unittest.TestCase):
    def setUp(self): self.conn=Connection()
    def execute(self,req, *, conn=None, prep_policy=None, callback=None):
        conn=self.conn if conn is None else conn
        kwargs=dict(authorize=authorize(req) if callback is None else callback,now=conn.clock)
        if 'contract' in req:
            return w.execute_preparation(conn,req,policy=policy() if prep_policy is None else prep_policy,**kwargs)
        return w.execute_fulfillment(conn,req,preparation_policy=policy() if prep_policy is None else prep_policy,
                                    fulfillment_policy=fixture.inputs()['policy'],**kwargs)
    def committed(self,req):
        pending=self.execute(req); self.assertTrue(pending['pending_commit']); self.conn.commit_simulation()
        factual=w.read_result(self.conn,req,authorize=authorize(req),now=self.conn.clock,preparation=req.get('contract')==w.VERSION)
        self.assertFalse(factual['pending_commit']); return factual
    def prepare(self,lines=None):
        req=prep_request(self.conn,lines=lines); result=self.committed(req)
        return result['result']['shipment_id'],req
    def event(self,sid,kind, *, quantities=None,outcome=None):
        lines=[{key:item[key] for key in ('line_id','product_code','qty','sale_movement_id')} for item in self.conn.data['cargo'] if item['shipment_id']==sid]
        quantities=[dict(line_id=line['line_id'],observed_qty=line['qty']) for line in lines] if quantities is None else quantities
        req=prep_request(self.conn,'record_preparation_event',sid=sid,lines=lines,event=kind,quantities=quantities,
            outcome=outcome or ('accepted' if kind=='inspection_recorded' else 'recorded'))
        self.committed(req); return req
    def refs(self):
        ops=self.conn.data['physical_ops'].values()
        latest={}
        for op in ops:
            req=op['request']
            if op['action']!='record_preparation_event' or req['event_kind'] not in ('assembly_completed','inspection_recorded'): continue
            for metric in req['quantities']:
                key=(req['event_kind'],metric['line_id'])
                if key not in latest or latest[key]['request']['evidence']['occurred_at']<req['evidence']['occurred_at']: latest[key]=op
        unique={op['operation_id']:dict(operation_id=op['operation_id'],evidence_basis=op['request']['evidence']['basis']) for op in latest.values()}
        return sorted(unique.values(),key=lambda ref:ref['operation_id'])
    def ready(self,sid):
        self.event(sid,'assembly_started'); self.event(sid,'assembly_completed'); self.event(sid,'inspection_recorded')
        lines=[{key:item[key] for key in ('line_id','product_code','qty','sale_movement_id')} for item in self.conn.data['cargo'] if item['shipment_id']==sid]
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid,lines=lines,refs=self.refs()); self.committed(req); return req
    def rejects(self,req, *, code=None, **kwargs):
        with self.assertRaises(c.CommerceError) as failure: self.execute(req,**kwargs)
        if code is not None: self.assertEqual(failure.exception.code,code)
        self.assertNotIn(PRIVATE,str(failure.exception)); self.assertTrue(self.conn.aborted)

    def test_bootstrap_persists_linked_prepared_lines_no_invoice_state_or_stock_money_changes(self):
        protected=deepcopy({key:self.conn.data[key] for key in ('products','movements','payments','reservations')})
        sid,req=self.prepare(); ship=self.conn.data['ships'][sid]
        self.assertEqual((ship['state'],ship['revision'],ship['readiness']),('준비',1,None))
        self.assertEqual(self.conn.data['orders']['fixture-order']['order_state'],'결제완료')
        self.assertEqual({key:self.conn.data[key] for key in protected},protected)
        self.assertEqual([row['sale_movement_id'] for row in self.conn.data['cargo']],[31,32])
        self.assertEqual(len(self.conn.data['physical_ops']),1); self.assertEqual(len(self.conn.data['physical_events']),1)
        self.assertFalse(self.execute(req)['result']['ready'])

    def test_write_and_same_transaction_read_are_not_a_commit_and_abort_preserves_previous_records(self):
        req=prep_request(self.conn); self.execute(req)
        with self.assertRaisesRegex(c.CommerceError,'commit_not_visible'):
            w.read_result(self.conn,req,authorize=authorize(req),now=self.conn.clock)
        with self.assertRaises(RuntimeError): self.conn.commit_simulation()
        self.conn.rollback_simulation(); self.assertEqual(self.conn.data['ships'],{})

    def test_start_completion_inspection_and_dispatch_confirmation_have_distinct_states(self):
        sid,_=self.prepare(); self.event(sid,'assembly_started')
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'조립중')
        self.event(sid,'assembly_completed'); self.event(sid,'inspection_recorded')
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'조립중')
        self.assertIsNone(self.conn.data['ships'][sid]['readiness'])
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid,refs=self.refs()); result=self.committed(req)
        self.assertEqual(result['result']['order_state'],'출고'); self.assertEqual(result['result']['shipment_state'],'준비')
        self.assertTrue(result['public']['ready'])

    def test_real_module_tracking_handoff_delivery_full_path_does_not_deduct_stock_again(self):
        sid,_=self.prepare(); self.ready(sid); before=deepcopy(self.conn.data['products'])
        for action,state in (('record_tracking','준비'),('handoff','배송중'),('deliver','완료')):
            result=self.committed(shipping_request(self.conn,sid,action))
            self.assertEqual(result['result']['shipment_state'],state)
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'완료')
        self.assertEqual(self.conn.data['products'],before); self.assertEqual(len(self.conn.data['movements']),2)

    def test_invoice_does_not_confirm_preparation_and_handoff_checks_target_even_if_order_is_outbound(self):
        sid,_=self.prepare(); self.committed(shipping_request(self.conn,sid))
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'결제완료')
        self.conn.data['orders']['fixture-order']['order_state']='출고'
        req=shipping_request(self.conn,sid,'handoff'); self.rejects(req,code='dispatch_readiness_unready')

    def test_explicit_assembly_exemption_can_confirm_without_inventing_an_assembly_event(self):
        sid,_=self.prepare(); req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid)
        self.rejects(req,code='assembly_policy_unready'); self.conn.rollback_simulation()
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid)
        result=self.execute(req,prep_policy=policy(assembly_required=False,required_events=[]))
        self.assertEqual(result['result']['order_state'],'출고'); self.assertTrue(result['result']['ready'])
        self.assertFalse(any(op['action']=='record_preparation_event' for op in self.conn.data['physical_ops'].values()))

    def test_missing_or_unconfirmed_policy_and_missing_physical_proofs_never_make_ready(self):
        for mutation in (lambda p:p.update(state='unknown'),lambda p:p.update(assembly_required=None),
                         lambda p:p.pop('rule_basis'),lambda p:p.update(required_events=[])):
            self.setUp(); sid,_=self.prepare(); req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid); value=policy(); mutation(value)
            self.rejects(req,prep_policy=value)
        self.setUp(); sid,_=self.prepare(); self.event(sid,'assembly_started')
        self.rejects(prep_request(self.conn,'confirm_dispatch_ready',sid=sid),code='dispatch_evidence_unready')

    def test_prepared_shipments_consume_original_line_quantity_with_no_state_filter_or_pagination(self):
        self.prepare(fixture.cargo_lines(2,1)); self.prepare(fixture.cargo_lines(1,1))
        self.rejects(prep_request(self.conn,lines=fixture.cargo_lines(1,0)),code='shipment_quantity_exceeded')
        sql='\n'.join(sql for tag,sql,_ in self.conn.trace if tag in ('physical_shipments','physical_shipment_lines','physical_operations'))
        self.assertNotIn('LIMIT',sql); self.assertNotIn("state='applied'",sql)
        self.assertIn('WHERE order_id=:oid',sql); self.assertIn('FOR UPDATE',sql)

    def test_same_product_distinct_sale_lines_do_not_merge(self):
        self.conn.data['details'][1]['snapshot']['lines'][1]['product_code']=202
        approved=fixture.approval(self.conn.data['details'][1]['snapshot']['lines'])
        self.conn.data['operations'][fixture.APPROVAL].update(operation=approved['operation'],verification=approved['verification'])
        self.conn.data['movements'][1]['product_code']=202
        lines=fixture.cargo_lines(); lines[1]['product_code']=202
        sid,_=self.prepare(lines); self.assertEqual(len(self.conn.data['cargo']),2)
        self.assertEqual({row['sale_movement_id'] for row in self.conn.data['cargo']},{31,32})

    def test_shared_cumulative_observation_cannot_be_double_used_across_partial_shipments(self):
        one,_=self.prepare(fixture.cargo_lines(1,0)); two,_=self.prepare(fixture.cargo_lines(2,0))
        self.event(one,'assembly_started'); self.event(one,'assembly_completed'); self.event(one,'inspection_recorded')
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=one,lines=fixture.cargo_lines(1,0),refs=self.refs()); self.committed(req)
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=two,lines=fixture.cargo_lines(2,0),refs=self.refs())
        self.rejects(req,code='dispatch_evidence_unready')

    def test_partial_shipping_preserves_order_shipping_state_for_new_preparation(self):
        sid,_=self.prepare(fixture.cargo_lines(1,0)); self.ready(sid)
        self.committed(shipping_request(self.conn,sid)); self.committed(shipping_request(self.conn,sid,'handoff'))
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'배송중')
        other,_=self.prepare(fixture.cargo_lines(2,2))
        self.assertEqual(self.conn.order('fixture-order')['order_state'],'배송중')
        self.assertEqual(self.conn.data['ships'][other]['state'],'준비')

    def test_pending_processing_unknown_physical_history_is_never_ignored(self):
        for state in ('prepared','processing','unknown'):
            self.setUp(); self.prepare(fixture.cargo_lines(1,0)); previous=next(iter(self.conn.data['physical_ops'].values()))
            previous.update(state=state,result=None,receipt=None)
            self.rejects(prep_request(self.conn,lines=fixture.cargo_lines(1,0)),code='physical_operation_unresolved')

    def test_financial_unknown_legacy_refunds_and_financial_uuid_reuse_are_blocked(self):
        self.conn.data['refunds']=[dict(refund_id=1,status='접수')]
        self.rejects(prep_request(self.conn),code='legacy_refund_boundary')
        self.setUp(); self.conn.data['operations'][fixture.APPROVAL]['operation']['state']='unknown'
        self.rejects(prep_request(self.conn))
        self.setUp(); req=prep_request(self.conn,operation_id=fixture.APPROVAL)
        self.rejects(req,code='physical_operation_must_be_independent')

    def test_missing_tables_or_rows_are_errors_not_empty_history_and_original_sale_references_are_exact(self):
        self.conn.fail_tag='physical_shipments'; self.rejects(prep_request(self.conn),code='commerce_writer_failed')
        self.setUp(); self.prepare(); self.conn.data['cargo'].pop()
        self.rejects(prep_request(self.conn),code='shipment_content_changed')
        for key,value in (('sale_movement_id',99),('product_code',101),('line_id','other')):
            self.setUp(); req=prep_request(self.conn); req['lines'][0][key]=value; rebind(req)
            self.rejects(req)

    def test_all_products_asc_before_order_child_locks_and_order_and_shipment_cas_are_effective(self):
        sid,_=self.prepare(); tags=[tag for tag,_,_ in self.conn.trace]
        self.assertLess(tags.index('product_lock'),tags.index('order_lock'))
        self.assertLess(tags.index('order_lock'),tags.index('physical_shipments'))
        self.assertEqual(next(params['codes'] for tag,_,params in self.conn.trace if tag=='product_lock'),[101,202])
        req=prep_request(self.conn,'record_preparation_event',sid=sid,event='assembly_started',
                         quantities=[dict(line_id='a',observed_qty=3),dict(line_id='b',observed_qty=2)],outcome='recorded')
        self.conn.child_hook=lambda conn:conn.data['ships'][sid].update(revision=99)
        self.rejects(req,code='physical_shipment_changed')
        self.conn.rollback_simulation(); self.conn.child_hook=None
        req=prep_request(self.conn,expected_order_revision=99); self.rejects(req,code='physical_order_changed')

    def test_late_failure_aborts_whole_transaction_and_does_not_make_partial_writes_committable(self):
        self.conn.fail_tag='physical_order_event'; req=prep_request(self.conn)
        self.rejects(req,code='commerce_writer_failed'); self.assertEqual(len(self.conn.data['physical_ops']),1)
        with self.assertRaises(RuntimeError): self.conn.commit_simulation()
        self.conn.rollback_simulation(); self.assertEqual(self.conn.data['physical_ops'],{}); self.assertEqual(self.conn.data['ships'],{})

    def test_write_time_order_shipment_and_state_cas_losses_abort_inserted_operation(self):
        for tag in ('update_order','physical_update_shipment','physical_order_status'):
            self.setUp(); sid,_=self.prepare(); before=deepcopy(self.conn.data)
            req=prep_request(self.conn,'record_preparation_event',sid=sid,event='assembly_started',
                quantities=[dict(line_id='a',observed_qty=3),dict(line_id='b',observed_qty=2)],outcome='recorded')
            self.conn.cas_tag=tag; self.rejects(req)
            with self.assertRaises(RuntimeError): self.conn.commit_simulation()
            self.conn.rollback_simulation(); self.assertEqual(self.conn.data,before)

    def test_two_partial_deliveries_complete_order_only_after_all_source_quantities_arrive(self):
        one,_=self.prepare(fixture.cargo_lines(1,0)); self.ready(one)
        self.committed(shipping_request(self.conn,one)); self.committed(shipping_request(self.conn,one,'handoff'))
        self.committed(shipping_request(self.conn,one,'deliver')); self.assertEqual(self.conn.order('fixture-order')['order_state'],'배송중')
        two,_=self.prepare(fixture.cargo_lines(2,2))
        metrics=[dict(line_id='a',observed_qty=3),dict(line_id='b',observed_qty=2)]
        for kind in w.EVENTS: self.event(two,kind,quantities=metrics)
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=two,lines=fixture.cargo_lines(2,2),refs=self.refs())
        self.committed(req); self.assertEqual(self.conn.order('fixture-order')['order_state'],'배송중')
        self.committed(shipping_request(self.conn,two)); self.committed(shipping_request(self.conn,two,'handoff'))
        result=self.committed(shipping_request(self.conn,two,'deliver'))
        self.assertEqual(result['result']['order_state'],'완료'); self.assertEqual(len(self.conn.data['movements']),2)

    def test_caller_transaction_autocommit_nested_and_changed_tx_are_rejected(self):
        for key,value in (('active',False),('nested',True),('options',{'isolation_level':'AUTOCOMMIT'})):
            self.setUp(); setattr(self.conn,key,value); req=prep_request(self.conn)
            with self.assertRaisesRegex(c.CommerceError,'caller_transaction_required'): self.execute(req)
            self.assertEqual(self.conn.trace,[])
        self.setUp(); req=prep_request(self.conn); good=authorize(req)
        def changed(**kwargs): self.conn.txid+=1; return good(**kwargs)
        self.rejects(req,callback=changed,code='caller_transaction_changed')

    def test_exact_uuid_replay_rechecks_auth_but_never_current_business_policies_or_creates_another_id(self):
        sid,req=self.prepare(); before=deepcopy(self.conn.data)
        with patch.object(w,'_origin',side_effect=AssertionError('must not recalculate')):
            result=self.execute(req,prep_policy={'private':PRIVATE})
        self.assertEqual(result['result']['shipment_id'],sid); self.assertEqual(self.conn.data,before)
        self.assertEqual(result['action'],'read_existing_result')
        req['operation_id']=req['operation_id'].upper(); self.assertEqual(self.execute(req)['result']['shipment_id'],sid)
        self.rejects(req,callback=authorize(req,allowed=False),code='physical_authorization_required')

    def test_replay_actor_owner_scope_payload_version_qty_evidence_changes_are_conflicts(self):
        for mutation in (lambda r:r.update(actor_id=8),lambda r:r.update(expected_order_revision=99),
                         lambda r:r.update(expected_policy_basis='f'*64),lambda r:r.update(expected_order_state='출고'),
                         lambda r:r['lines'][0].update(qty=2)):
            self.setUp(); _,req=self.prepare(); mutation(req); rebind(req); self.rejects(req,code='physical_operation_conflict')
        self.setUp(); _,req=self.prepare(); owner=self.conn.data['details'][1]['owner_identity']; owner['user_id']=99
        self.conn.data['details'][1]['owner_scope']=c.fingerprint(owner); self.rejects(req,code='physical_operation_conflict')
        self.setUp(); _,req=self.prepare(); req['contract']='older'; self.rejects(req,code='preparation_contract_mismatch')

    def test_authorization_precedes_all_business_reads_and_role_changes_before_write_abort(self):
        for changes in (dict(auth_source='client'),dict(actor=dict(operator_id=7,role='viewer',status='활성')),
                        dict(permission='commerce.order.read'),dict(allowed=False),dict(checked_at=0)):
            self.setUp(); req=prep_request(self.conn); self.rejects(req,callback=authorize(req,**changes))
            self.assertFalse(any(tag in ('order','physical_operation') for tag,_,_ in self.conn.trace))
        self.setUp(); req=prep_request(self.conn); base=authorize(req); calls=[]
        def changes_role(**kwargs):
            grant=base(**kwargs); calls.append(1)
            if len(calls)>1: grant['actor']['role']='viewer'
            return grant
        self.rejects(req,callback=changes_role,code='physical_authorization_required')

    def test_event_proof_native_metrics_chronology_prerequisites_and_actor_are_required(self):
        for change in ('actor','future','qty','source'):
            self.setUp(); sid,_=self.prepare()
            req=prep_request(self.conn,'record_preparation_event',sid=sid,event='assembly_started',
                quantities=[dict(line_id='a',observed_qty=3),dict(line_id='b',observed_qty=2)],outcome='recorded')
            if change=='actor': req['evidence']['actor_id']=8
            elif change=='future': req['evidence']['occurred_at']=self.conn.clock+1
            elif change=='qty': req['quantities'][0]['observed_qty']=4
            else: req['evidence']['source']='client'
            req['evidence']['basis']=c.fingerprint({key:value for key,value in req['evidence'].items() if key!='basis'})
            rebind(req); self.rejects(req)
        self.setUp(); sid,_=self.prepare()
        req=prep_request(self.conn,'record_preparation_event',sid=sid,event='assembly_completed',
            quantities=[dict(line_id='a',observed_qty=3),dict(line_id='b',observed_qty=2)],outcome='recorded')
        self.rejects(req,code='preparation_prerequisite_unready')

    def test_new_rejected_or_stale_observation_cannot_fall_back_to_older_accepted_readiness(self):
        sid,_=self.prepare(); self.ready(sid); self.committed(shipping_request(self.conn,sid))
        self.event(sid,'inspection_recorded',outcome='rejected')
        self.rejects(shipping_request(self.conn,sid,'handoff'),code='dispatch_readiness_unready')

    def test_new_assembly_start_invalidates_previous_completion_until_new_physical_observations(self):
        sid,_=self.prepare(); self.ready(sid); self.event(sid,'assembly_started')
        req=prep_request(self.conn,'confirm_dispatch_ready',sid=sid,refs=self.refs())
        self.rejects(req,code='dispatch_evidence_unready')

    def test_each_command_exact_replay_skips_all_current_business_and_preserves_original_result(self):
        sid,prepare=self.prepare(); requests=[prepare]
        requests.extend([self.event(sid,'assembly_started'),self.event(sid,'assembly_completed'),self.event(sid,'inspection_recorded')])
        confirm=prep_request(self.conn,'confirm_dispatch_ready',sid=sid,refs=self.refs()); self.committed(confirm); requests.append(confirm)
        for action in w.core.ACTIONS:
            req=shipping_request(self.conn,sid,action); self.committed(req); requests.append(req)
        before=deepcopy(self.conn.data)
        for req in requests:
            with patch.object(w,'_origin',side_effect=AssertionError('business replay forbidden')), \
                 patch.object(w,'_observations',side_effect=AssertionError('quantity replay forbidden')), \
                 patch.object(w,'_policy',side_effect=AssertionError('policy replay forbidden')):
                result=self.execute(req,prep_policy={'private':PRIVATE})
            self.assertEqual(result['action'],'read_existing_result')
            self.assertEqual(result['result'],self.conn.data['physical_ops'][req['operation_id']]['result'])
        self.assertEqual(self.conn.data,before)

    def test_native_server_rows_readiness_scope_and_original_approval_owner_fail_closed(self):
        for location in ('parent_revision','cargo_qty','operation_actor','ready_reference','approval_owner'):
            self.setUp(); sid,_=self.prepare(); self.ready(sid)
            if location=='parent_revision': self.conn.data['ships'][sid]['revision']=True
            elif location=='cargo_qty': self.conn.data['cargo'][0]['qty']=1.0
            elif location=='operation_actor': next(iter(self.conn.data['physical_ops'].values()))['actor_id']=True
            elif location=='ready_reference': self.conn.data['ships'][sid]['readiness_operation_id']=fixture.APPROVAL
            else: self.conn.data['operations'][fixture.APPROVAL]['operation']['spec']['owner']['user_id']=99
            req=prep_request(self.conn,lines=fixture.cargo_lines(1,0)); self.rejects(req)

    def test_event_evidence_payload_change_on_same_uuid_and_read_receipt_tampering_are_rejected(self):
        sid,_=self.prepare(); req=self.event(sid,'assembly_started')
        changed=deepcopy(req); changed['evidence']['reference']='changed fixture evidence'
        changed['evidence']['basis']=c.fingerprint({key:value for key,value in changed['evidence'].items() if key!='basis'})
        rebind(changed); self.rejects(changed,code='physical_operation_conflict')
        self.conn.rollback_simulation(); record=self.conn.data['physical_ops'][req['operation_id']]
        record['receipt']['write_txid']=self.conn.txid
        with self.assertRaisesRegex(c.CommerceError,'physical_result_mismatch'):
            w.read_result(self.conn,req,authorize=authorize(req),now=self.conn.clock)

    def test_readiness_refs_and_manual_handoff_time_are_rechecked_before_core(self):
        sid,_=self.prepare(); ready_req=self.ready(sid); self.committed(shipping_request(self.conn,sid))
        req=shipping_request(self.conn,sid,'handoff'); req['evidence']['occurred_at']=ready_req['evidence']['occurred_at']-1
        req['evidence']['basis']=c.fingerprint({key:value for key,value in req['evidence'].items() if key!='basis'})
        rebind(req); self.rejects(req,code='dispatch_readiness_changed')

    def test_native_quantities_ids_revisions_unknown_fields_and_json_coercion_fail_closed(self):
        for value in (None,True,1.0,Decimal('1'),'1',0,-1,c.MAX_QUANTITY+1):
            self.setUp(); req=prep_request(self.conn); req['lines'][0]['qty']=value; self.rejects(req)
        for value in (None,True,1.0,Decimal('1'),'1',0,-1,c.MAX_INTEGER+1):
            self.setUp(); req=prep_request(self.conn); req['actor_id']=value; self.rejects(req)
        self.setUp(); req=prep_request(self.conn); req['private']=PRIVATE; self.rejects(req,code='invalid_fields')

    def test_resealed_stored_result_cannot_change_original_command_state_or_referenced_receipt(self):
        for key,value in (('order_state','出go'),('shipment_revision',9),('ready',True),('evidence_basis','f'*64)):
            self.setUp(); _,req=self.prepare(); record=self.conn.data['physical_ops'][req['operation_id']]
            record['result'][key]='출고' if key=='order_state' else value
            record['receipt']['result_basis']=c.fingerprint(dict(identity=record['identity'],result=record['result']))
            self.rejects(req,code='physical_result_mismatch')

    def test_public_allowlist_detached_outputs_and_adapter_owns_no_io_or_transaction(self):
        req=prep_request(self.conn); before=deepcopy(req); result=self.committed(req)
        self.assertNotIn(PRIVATE,repr(result)); self.assertNotIn('a'*64,repr(result)); self.assertEqual(req,before)
        self.assertEqual(set(result['public']),{'operation_id','order_no','action','shipment_id','order_state','shipment_state','ready','pending'})
        result['result']['shipment_id']=99; self.assertEqual(self.execute(req)['result']['shipment_id'],10)
        source=(Path(__file__).resolve().parents[1]/'api/commerce_fulfillment_writer.py').read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                self.assertNotIn(node.func.attr,('connect','begin','commit','rollback','begin_nested','create_engine'))
        self.assertNotIn('INSERT INTO stock_movements',source); self.assertNotIn('UPDATE products',source)
        self.assertNotIn('INSERT INTO payments',source); self.assertNotIn('UPDATE stock_reservations',source)


if __name__=='__main__': unittest.main()
