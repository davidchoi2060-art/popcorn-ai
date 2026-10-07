"""Real return adapters/core over limited SQL results; no PG/HTTP/provider proof."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID
import ast
import json
import re
import unittest

from api import commerce_contract as c
from api import commerce_physical_return_writer as w
from api import commerce_physical_return_read as r
from tests.test_commerce_fulfillment_read import Connection as ShippingConnection, prepare, ready, committed, NO
from tests.test_commerce_fulfillment_writer import Result, shipping_request
from tests import test_commerce_physical_return_core as fixture


class Connection(ShippingConnection):
    def __init__(self):
        super().__init__()
        self.data.update(returns={}, return_lines={}, return_ops={}, return_effects={})
        self.saved = deepcopy(self.data); self.return_snapshot_hook = None

    def execute(self, statement, params=None):
        sql = str(statement); p = params or {}; found = re.search(r'/\*physical_return:(\w+)\*/', sql)
        if not found: return super().execute(statement, p)
        tag = found[1]; self.trace.append(('return_' + tag, sql, deepcopy(p)))
        if self.aborted: raise RuntimeError('aborted fixture')
        if self.fail_tag == 'return_' + tag: raise RuntimeError(fixture.PRIVATE)
        if self.cas_tag == 'return_' + tag: return Result(rowcount=0)
        d = self.data
        if tag.startswith('lock_') or tag == 'uuid_lock': return Result()
        if tag == 'operation': return Result([d['return_ops'][p['id']]] if p['id'] in d['return_ops'] else [])
        if tag == 'foreign_uuid': return Result([dict(operation_id=p['id'])] if p['id'] in d['operations'] or p['id'] in d['physical_ops'] else [])
        if tag == 'snapshot':
            row = deepcopy(self.order(p['no']))
            if row is None: return Result()
            payments = d['payments']; row.update(approved=sum(x['amount'] for x in payments if x['amount']>0),
                refunded=-sum(x['amount'] for x in payments if x['amount']<0), read_txid=self.txid)
            proofs = [(pay, d['operations'][pay['operation_id']]) for pay in payments if pay['amount']>0
                      and d['operations'][pay['operation_id']]['operation']['spec']['kind']=='approve']
            if len(proofs)!=1: return Result([row]*len(proofs))
            pay, proof = proofs[0]
            row.update(approval_payment_id=pay['payment_id'], approval_operation=deepcopy(proof['operation']),
                approval_verification=deepcopy(proof['verification']), approval_write_txid=proof['write_txid'],
                parents=[deepcopy(v) for _,v in sorted(d['ships'].items())],
                cargo=sorted(deepcopy(d['cargo']), key=lambda v:(v['shipment_id'],v['line_id'])),
                operations=[deepcopy(v) for _,v in sorted(d['physical_ops'].items())],
                cases=[deepcopy(v) for _,v in sorted(d['returns'].items())],
                return_lines=[deepcopy(v) for _,v in sorted(d['return_lines'].items())],
                return_operations=[deepcopy(v) for _,v in sorted(d['return_ops'].items())],
                effects=[deepcopy(v) for _,v in sorted(d['return_effects'].items())],
                financial_operations=[dict(operation_id=key,order_no=NO,kind=v['operation']['spec']['kind'],
                    state=v['operation']['state']) for key,v in sorted(d['operations'].items())], movements=[])
            for move in d['movements']:
                row['movements'].append(dict(movement_id=move['movement_id'], product_code=move['product_code'],
                    movement_type=move['movement_type'], qty_delta=move['qty_delta'], ref_kind='order',ref_id=1,
                    commerce_operation_id=move.get('operation_id'),commerce_effect_key=move.get('effect_key'),
                    physical_return_operation_id=move.get('physical_return_operation_id'),
                    physical_return_effect_key=move.get('physical_return_effect_key')))
            if self.return_snapshot_hook: self.return_snapshot_hook(row)
            return Result([row])
        if tag == 'insert_case':
            rid = max(d['returns'], default=0)+20
            d['returns'][rid]=dict(return_id=rid,order_id=p['oid'],revision=1,write_txid=self.txid)
            return Result(scalar=rid)
        if tag == 'insert_line':
            lid=max(d['return_lines'],default=50)+1
            d['return_lines'][lid]=dict(return_line_id=lid,order_id=p['oid'],return_id=p['rid'],shipment_id=p['sid'],
                line_id=p['line'],sale_movement_id=p['movement'],product_code=p['code'],claimed_qty=p['qty'],
                collected_qty=0,received_qty=0,inspected_qty=0,resellable_qty=0,
                collection_evidence=None,receipt_evidence=None,inspection_evidence=None)
            return Result(scalar=lid)
        if tag in ('update_observation','update_inspection'):
            line=d['return_lines'][p['lid']]
            field=('collected_qty' if 'SET collected_qty=' in sql else 'received_qty') if tag=='update_observation' else 'inspected_qty'
            if line[field]!=p['previous'] or line['return_id']!=p['rid'] or line['order_id']!=p['oid']: return Result(rowcount=0)
            proof={'collected_qty':'collection_evidence','received_qty':'receipt_evidence','inspected_qty':'inspection_evidence'}[field]
            line.update({field:p['qty'],proof:json.loads(p['proof'])})
            if tag=='update_inspection': line['resellable_qty']=p['resale']
            return Result()
        if tag=='update_case':
            case=d['returns'][p['rid']]
            if case['revision']!=p['revision']: return Result(rowcount=0)
            case.update(revision=case['revision']+1,write_txid=self.txid); return Result()
        if tag=='insert_operation':
            if p['id'] in d['return_ops']: raise RuntimeError('duplicate UUID')
            d['return_ops'][p['id']]=dict(operation_id=p['id'],order_id=p['oid'],return_id=p['rid'],contract=p['contract'],
                action=p['action'],actor_id=p['actor'],owner_scope=p['scope'],wire_intent=json.loads(p['wire']),
                request_basis=p['basis'],request=json.loads(p['request']),identity=json.loads(p['identity']),
                state='applied',revision=1,result=json.loads(p['result']),receipt=json.loads(p['receipt']),write_txid=self.txid)
            return Result()
        if tag=='insert_movement':
            mid=max(v['movement_id'] for v in d['movements'])+1
            d['movements'].append(dict(movement_id=mid,product_code=p['code'],qty_delta=p['qty'],movement_type='return',
                physical_return_operation_id=p['id'],physical_return_effect_key=p['key']))
            return Result(scalar=mid)
        if tag=='insert_effect':
            d['return_effects'][p['key']]=dict(effect_key=p['key'],physical_operation_id=p['id'],order_id=p['oid'],
                return_id=p['rid'],return_line_id=p['lid'],sale_movement_id=p['sale'],product_code=p['code'],qty=p['qty'],
                inspection_basis=p['inspection'],policy_basis=p['policy'],state='applied',movement_id=p['movement'],
                receipt=json.loads(p['receipt']),write_txid=self.txid)
            return Result()
        if tag=='restore_stock':
            product=d['products'][p['code']]
            if product['stock_qty'] is None or product['stock_qty']>c.MAX_QUANTITY-p['qty']: return Result(rowcount=0)
            product['stock_qty']+=p['qty']; product['commerce_stock_revision']+=1; return Result()
        raise AssertionError('Unhandled return SQL '+tag)



class NativeUUIDConnection(Connection):
    """DBAPI returns native UUID columns as UUID, while JSON stays text."""
    def execute(self, statement, params=None):
        result = super().execute(statement, params)
        if '/*physical_return:operation*/' in str(statement):
            for row in result.rows:
                row['operation_id'] = UUID(row['operation_id'])
        return result


def authorize(**kwargs):
    return dict(auth_source='api.auth.current_operator',authenticated=True,allowed=True,
        actor=dict(operator_id=7,role='operator',status='활성'),permission='commerce.return.'+kwargs['action'],
        order_no=kwargs['order_no'],return_id=kwargs['return_id'],action=kwargs['action'],checked_at=kwargs['now'])


def observe(conn, **kwargs):
    value=dict(source='operator_record',state='confirmed',action=kwargs['action'],order_no=kwargs['order_no'],
        actor_id=kwargs['actor_id'],occurred_at=kwargs['now'],reference=fixture.PRIVATE,
        targets_basis=c.fingerprint(kwargs['targets']))
    value['basis']=c.fingerprint(value); return value


def policy(conn, **kwargs):
    return deepcopy(fixture.inputs()['policy'])


def inspection(conn, **kwargs):
    result=[]
    for line in kwargs['lines']:
        qty=line['qty']; resale=qty
        proof=fixture.evidence('inspect',line,return_id=kwargs['return_id'],actor_id=kwargs['actor_id'],
            occurred_at=kwargs['now'],quantities=dict(inspected_qty=qty,resellable_qty=resale))
        result.append(dict(return_line_id=line['return_line_id'],inspected_qty=qty,resellable_qty=resale,evidence=proof))
    return result


class PersistenceTests(unittest.TestCase):
    def setUp(self): self.conn=Connection()
    def current(self): return r.read_current(self.conn,NO,authorize=authorize,now=self.conn.clock)
    def ship(self, quantities=None):
        sid,_=prepare(self.conn,quantities); ready(self.conn,sid)
        for action in ('record_tracking','handoff','deliver'): committed(self.conn,shipping_request(self.conn,sid,action))
        return sid
    def command(self,action='create_case',rid=None,lines=None):
        current=self.current(); self.conn.clock+=10; self.conn.serial+=1
        case=next((v for v in current['cases'] if v['return_id']==rid),None)
        if lines is None:
            if rid is None: lines=[dict(shipment_id=v['shipment_id'],line_id=v['line_id'],qty=v['qty']) for v in self.conn.data['cargo']]
            else: lines=[dict(return_line_id=v['return_line_id'],qty=v['claimed_qty']) for v in case['lines']]
        return dict(operation_id=str(UUID(int=self.conn.serial)),order_no=NO,action=action,return_id=rid,
            expected_order_basis=current['expected_order_basis'],expected_order_revision=current['order_revision'],
            expected_return_revision=case['revision'] if case else None,expected_history_token=current['expected_history_token'],
            expected_policy_basis='d'*64 if action in w.core.ACTIONS else None,lines=lines)
    def execute(self,cmd,**kwargs):
        args=dict(authorize=authorize,now=self.conn.clock)
        if cmd['action'] in w.INTAKE:
            return getattr(w,cmd['action'])(self.conn,cmd,**(args|dict(observe=observe)|kwargs))
        return w.execute_return(self.conn,cmd,**(args|dict(policy=policy,inspect=inspection)|kwargs))
    def commit(self,cmd,**kwargs):
        pending=self.execute(cmd,**kwargs); self.assertTrue(pending['pending_commit']); self.assertTrue(pending['pending'])
        self.conn.commit_simulation()
        result=r.read_result(self.conn,NO,cmd['operation_id'],authorize=authorize,now=self.conn.clock)
        self.assertFalse(result['pending_commit']); return result
    def intake(self):
        self.ship(); rid=self.commit(self.command())['return_id']
        for action in ('record_collection','record_receipt'): self.commit(self.command(action,rid))
        return rid
    def inspected(self):
        rid=self.intake(); self.commit(self.command('inspect',rid)); return rid
    def rejects(self,cmd,code=None,**kwargs):
        before=deepcopy(self.conn.data)
        with self.assertRaises(c.CommerceError) as error: self.execute(cmd,**kwargs)
        if code: self.assertEqual(error.exception.code,code)
        self.assertNotIn(fixture.PRIVATE,str(error.exception)); self.assertTrue(self.conn.aborted)
        self.conn.rollback_simulation(); self.assertEqual(self.conn.data,self.conn.saved)
        return before

    def test_empty_snapshot_single_select_stable_token_across_transactions(self):
        first=self.current(); self.assertEqual(first['cases'],[]); self.conn.commit_simulation()
        self.assertEqual(first['expected_history_token'],self.current()['expected_history_token'])
        self.assertEqual(sum(tag=='return_snapshot' for tag,_,_ in self.conn.trace),2)
    def test_intake_preserves_financial_stock_and_has_full_history(self):
        self.ship(); protected=deepcopy({k:self.conn.data[k] for k in ('products','movements','payments','reservations','operations')})
        rid=self.commit(self.command())['return_id']
        for action in ('record_collection','record_receipt'): self.commit(self.command(action,rid))
        self.assertEqual(protected,{k:self.conn.data[k] for k in protected})
        case=self.current()['cases'][0]; self.assertEqual(case['revision'],3)
        self.assertEqual([v['action'] for v in case['history']],list(w.INTAKE))
        self.assertTrue(all(v['reference']==fixture.PRIVATE for v in case['history']))
    def test_read_result_unconfirmed_before_commit(self):
        self.ship(); cmd=self.command(); self.execute(cmd)
        with self.assertRaises(c.CommerceError): r.read_result(self.conn,NO,cmd['operation_id'],authorize=authorize,now=self.conn.clock)
        self.assertTrue(self.conn.aborted); self.conn.rollback_simulation(); self.assertEqual(self.current()['cases'],[])
    def test_replay_reads_stored_uuid_without_snapshot_policy_or_locks(self):
        rid=self.inspected(); cmd=self.command('restore',rid); expected=self.commit(cmd); before=deepcopy(self.conn.data)
        self.conn.trace.clear(); self.conn.fail_tag='return_snapshot'
        result=self.execute(cmd,policy=None,inspect=None)
        self.assertFalse(result['pending_commit']); self.assertEqual(result['result']['return_revision'],expected['return_revision'])
        self.assertEqual(self.conn.data,before)
        self.assertFalse(any('lock' in tag or tag=='return_snapshot' for tag,_,_ in self.conn.trace))
    def test_replay_conflicting_wire_and_actor_rejected(self):
        self.ship(); cmd=self.command(); self.commit(cmd)
        changed=deepcopy(cmd); changed['lines'][0]['qty']=1
        self.rejects(changed,'return_operation_conflict')
        def other(**kwargs): value=authorize(**kwargs); value['actor']['operator_id']=8; return value
        self.rejects(cmd,'return_operation_conflict',authorize=other)
    def test_five_stages_use_real_plan_only_restore_changes_stock(self):
        rid=self.intake(); before=deepcopy(self.conn.data['products'])
        self.commit(self.command('inspect',rid)); self.assertEqual(before,self.conn.data['products'])
        self.commit(self.command('restore',rid))
        self.assertEqual(self.conn.data['products'][202]['stock_qty'],8)
        self.assertEqual(self.conn.data['products'][101]['stock_qty'],7)
        self.assertEqual(len(self.conn.data['return_effects']),2)
        lines=self.current()['cases'][0]['lines']; self.assertTrue(all(v['restoration_remaining_qty']==0 for v in lines))
        history=self.current()['cases'][0]['history']; self.assertEqual(history[3]['evidence'][0]['kind'],'inspect')
        self.assertIsNone(history[4]['occurred_at'])  # A reused inspection proof is not a restoration clock.
        self.assertEqual(history[3]['evidence'],history[4]['evidence'])
        self.assertEqual(self.conn.data['payments'],self.conn.saved['payments'])
    def test_partial_restore_then_remainder_and_overrun(self):
        rid=self.inspected(); ids=sorted(self.conn.data['return_lines'])
        self.commit(self.command('restore',rid,[dict(return_line_id=ids[0],qty=1)]))
        self.assertEqual(self.current()['cases'][0]['lines'][0]['restoration_remaining_qty'],2)
        self.commit(self.command('restore',rid,[dict(return_line_id=ids[0],qty=2)]))
        self.rejects(self.command('restore',rid,[dict(return_line_id=ids[0],qty=1)]))
    def test_create_claim_capacity_all_cases(self):
        self.ship(); lines=[dict(shipment_id=10,line_id='a',qty=2)]
        self.commit(self.command(lines=lines)); self.commit(self.command(lines=[dict(shipment_id=10,line_id='a',qty=1)]))
        self.rejects(self.command(lines=[dict(shipment_id=10,line_id='a',qty=1)]),'return_quantity_exceeded')
    def test_forged_wire_actor_product_proof_and_boolean_quantities(self):
        self.ship(); cmd=self.command()
        for key in ('actor_id','product_code','inspection','policy'):
            bad=deepcopy(cmd); bad[key]=7; self.rejects(bad)
        for qty in (True,0,-1,'1',1.0):
            bad=deepcopy(cmd); bad['lines'][0]['qty']=qty; self.rejects(bad)
    def test_wrong_shipment_line_and_positive_qty_cap(self):
        self.ship(); self.rejects(self.command(lines=[dict(shipment_id=999,line_id='a',qty=1)]),'return_shipment_scope_mismatch')
        self.rejects(self.command(lines=[dict(shipment_id=10,line_id='a',qty=4)]),'return_quantity_exceeded')
    def test_policy_and_inspection_absent_fail_before_writes(self):
        rid=self.intake(); cmd=self.command('inspect',rid)
        for kwargs in (dict(policy=None),dict(policy=lambda *a,**k:None),dict(inspect=None)):
            self.conn.trace.clear(); before=self.rejects(cmd,**kwargs)
            self.assertFalse(any(tag.startswith('return_insert') or tag.startswith('return_update') for tag,_,_ in self.conn.trace))
            self.assertEqual(before,self.conn.data)
    def test_unconfirmed_policy_and_wrong_rules_rejected(self):
        rid=self.intake(); cmd=self.command('inspect',rid)
        def unconfirmed(conn,**kwargs): value=policy(conn,**kwargs); value['state']='unknown'; return value
        self.rejects(cmd,'return_policy_unconfirmed',policy=unconfirmed)
        def wrong(conn,**kwargs):
            value=inspection(conn,**kwargs); value[0]['evidence']['rules_basis']='f'*64; fixture.seal(value[0]['evidence']); return value
        self.rejects(cmd,inspect=wrong)
    def test_observation_must_bind_server_targets_actor_clock(self):
        self.ship(); cmd=self.command()
        for field,value in (('targets_basis','a'*64),('actor_id',8),('occurred_at',self.conn.clock+1),('state','unknown')):
            def wrong(conn,**kwargs):
                proof=observe(conn,**kwargs); proof[field]=value; fixture.seal(proof); return proof
            self.rejects(cmd,'return_observation_unconfirmed',observe=wrong)
    def test_collection_receipt_monotonic_and_downstream_freeze(self):
        rid=self.intake(); cmd=self.command('record_collection',rid)
        self.rejects(cmd,'return_quantity_inconsistent')
        self.rejects(self.command('record_receipt',rid),'return_quantity_inconsistent')
    def test_stale_public_token_and_order_revision(self):
        self.ship(); cmd=self.command(); self.conn.commit_simulation()
        current=self.current(); self.assertEqual(current['expected_history_token'],cmd['expected_history_token'])
        self.commit(cmd)
        self.rejects(dict(self.command(),expected_history_token=cmd['expected_history_token']),'return_history_changed')
    def test_original_financial_and_shipping_uuid_collision(self):
        self.ship(); cmd=self.command()
        for opid in (next(iter(self.conn.data['operations'])),next(iter(self.conn.data['physical_ops']))):
            self.rejects(dict(cmd,operation_id=opid),'physical_operation_must_be_independent')
    def test_whole_lock_order_precedes_children_and_mutations(self):
        self.ship(); cmd=self.command(); self.conn.trace.clear(); self.commit(cmd)
        tags=[tag for tag,_,_ in self.conn.trace]
        self.assertLess(tags.index('product_lock'),tags.index('order_lock'))
        expected=['order_lock','return_lock_returns','return_lock_lines','return_lock_operations','return_lock_effects','return_insert_case']
        self.assertEqual([tags.index(tag) for tag in expected],sorted(tags.index(tag) for tag in expected))
        locked=next(p['codes'] for tag,_,p in self.conn.trace if tag=='product_lock'); self.assertEqual(locked,[101,202])
    def test_after_write_auth_revoked_aborts_caller(self):
        self.ship(); cmd=self.command(); calls=0
        def revoke(**kwargs):
            nonlocal calls
            calls+=1; grant=authorize(**kwargs)
            if calls>=3: grant['allowed']=False
            return grant
        self.rejects(cmd,'return_authorization_required',authorize=revoke)
    def test_callback_transaction_change_aborts_without_write(self):
        self.ship(); cmd=self.command()
        def changed(conn,**kwargs): proof=observe(conn,**kwargs); conn.txid+=1; return proof
        self.rejects(cmd,'caller_transaction_changed',observe=changed)
    def test_sql_failure_and_cas_failure_preserve_no_partial_success(self):
        self.ship(); cmd=self.command()
        for tag in ('return_insert_line','return_insert_operation','update_order'):
            self.conn.fail_tag=tag; self.rejects(cmd); self.conn.fail_tag=None
        self.conn.cas_tag='update_order'; self.rejects(cmd); self.conn.cas_tag=None
    def test_restore_stock_failure_rolls_back_ledgers(self):
        rid=self.inspected(); cmd=self.command('restore',rid); self.conn.cas_tag='return_restore_stock'
        self.rejects(cmd,'return_stock_changed'); self.assertEqual(self.conn.data['return_effects'],{})
    def test_unknown_operation_never_promotes_success(self):
        self.ship(); cmd=self.command(); self.commit(cmd); op=self.conn.data['return_ops'][cmd['operation_id']]
        op.update(state='unknown',result=None,receipt=None); self.conn.saved=deepcopy(self.conn.data)
        self.rejects(cmd,'return_result_unconfirmed')
    def test_unknown_restore_counts_capacity_and_blocks_other_case_same_sale(self):
        self.ship()
        cases=[]
        for qty in (1,2):
            rid=self.commit(self.command(lines=[dict(shipment_id=10,line_id='a',qty=qty)]))['return_id']
            for action in ('record_collection','record_receipt','inspect'): self.commit(self.command(action,rid))
            cases.append(rid)
        before=deepcopy(self.conn.data); cmd=self.command('restore',cases[0]); self.commit(cmd)
        op=deepcopy(self.conn.data['return_ops'][cmd['operation_id']]); op.update(state='unknown',result=None,receipt=None)
        effect=deepcopy(next(v for v in self.conn.data['return_effects'].values() if v['physical_operation_id']==cmd['operation_id']))
        effect.update(state='unknown',movement_id=None,receipt=None)
        self.conn.data=before; self.conn.data['return_ops'][cmd['operation_id']]=op
        self.conn.data['return_effects'][effect['effect_key']]=effect; self.conn.saved=deepcopy(self.conn.data)
        current=self.current(); line=current['cases'][0]['lines'][0]
        self.assertTrue(line['restoration_unresolved']); self.assertEqual(line['restoration_consumed_qty'],1)
        self.rejects(cmd,'return_result_unconfirmed')
        self.rejects(self.command('restore',cases[0]),'return_operation_unresolved')
        self.rejects(self.command('restore',cases[1]),'physical_restoration_unresolved')
    def test_committed_replay_all_five_actions_survives_current_policy_absence(self):
        self.ship(); commands=[]
        cmd=self.command(); rid=self.commit(cmd)['return_id']; commands.append(cmd)
        for action in ('record_collection','record_receipt','inspect','restore'):
            cmd=self.command(action,rid); self.commit(cmd); commands.append(cmd)
        before=deepcopy(self.conn.data)
        with patch.object(w.core,'plan_physical_return',side_effect=AssertionError('must never replan')):
            for cmd in commands:
                result=self.execute(cmd,**(dict(observe=None) if cmd['action'] in w.INTAKE else dict(policy=None,inspect=None)))
                self.assertFalse(result['pending_commit'])
        self.assertEqual(before,self.conn.data)
    def test_history_missing_original_case_line_and_foreign_financial_scope(self):
        self.intake()
        for corrupt in (lambda row:row['financial_operations'][0].update(order_no='foreign'),
                        lambda row:row['return_lines'][0].update(claimed_qty=1),
                        lambda row:row['return_operations'][0].update(owner_scope='f'*64)):
            self.conn.return_snapshot_hook=corrupt
            with self.assertRaises(c.CommerceError): self.current()
            self.conn.rollback_simulation()
    def test_corrupt_stored_result_and_receipt_fail_closed(self):
        self.ship(); cmd=self.command(); self.commit(cmd); saved=deepcopy(self.conn.data)
        for field in ('result_basis','storage_basis','request_basis','write_txid'):
            self.conn.data=deepcopy(saved); self.conn.data['return_ops'][cmd['operation_id']]['receipt'][field]='f'*64
            with self.assertRaises(c.CommerceError): r.read_result(self.conn,NO,cmd['operation_id'],authorize=authorize,now=self.conn.clock)
            self.conn.rollback_simulation()
    def test_snapshot_missing_history_or_movement_mismatch_fails(self):
        rid=self.inspected(); self.commit(self.command('restore',rid))
        for field in ('return_operations','effects','return_lines'):
            self.conn.return_snapshot_hook=lambda row:row.update({field:[]})
            with self.assertRaises(c.CommerceError): self.current()
            self.conn.rollback_simulation()
        def corrupt(row): row['movements'][-1]['qty_delta']+=1
        self.conn.return_snapshot_hook=corrupt
        with self.assertRaises(c.CommerceError): self.current()
    def test_inspection_frozen_after_restore(self):
        rid=self.inspected(); self.commit(self.command('restore',rid,[dict(return_line_id=51,qty=1)]))
        self.rejects(self.command('inspect',rid))
    def test_load_request_scope_and_mutation_does_not_change_storage(self):
        self.ship(); cmd=self.command(); self.commit(cmd)
        loaded=r.load_request(self.conn,NO,cmd['operation_id'],authorize=authorize,now=self.conn.clock)
        loaded['lines'][0]['qty']=999; self.assertEqual(self.conn.data['return_ops'][cmd['operation_id']]['wire_intent'],cmd)
        self.assertIsNone(r.load_request(self.conn,NO,str(UUID(int=9000)),authorize=authorize,now=self.conn.clock,missing_ok=True))
    def test_native_uuid_result_all_five_actions_load_and_replay(self):
        self.conn = NativeUUIDConnection(); self.ship(); commands = []
        cmd = self.command(); factual = self.commit(cmd); rid = factual['return_id']; commands.append(cmd)
        for action in ('record_collection', 'record_receipt', 'inspect', 'restore'):
            cmd = self.command(action, rid); factual = self.commit(cmd); commands.append(cmd)
            self.assertEqual((factual['state'], factual['pending'], factual['pending_commit']), ('confirmed', False, False))
            self.assertIs(type(factual['operation_id']), str); self.assertEqual(factual['operation_id'], cmd['operation_id'])
        snapshot = deepcopy(self.conn.data)
        for cmd in commands:
            loaded = r.load_request(self.conn, NO, cmd['operation_id'], authorize=authorize, now=self.conn.clock)
            self.assertEqual(loaded, cmd)
            self.conn.trace.clear(); self.conn.fail_tag = 'return_snapshot'
            replay = self.execute(cmd, **(dict(observe=None) if cmd['action'] in w.INTAKE else dict(policy=None, inspect=None)))
            self.assertFalse(replay['pending_commit']); self.assertEqual(replay['operation_id'], cmd['operation_id'])
            self.assertFalse(any('lock' in tag or tag == 'return_snapshot' for tag, _, _ in self.conn.trace))
            self.conn.fail_tag = None
        self.assertEqual(self.conn.data, snapshot)
        case = self.current()['cases'][0]; self.assertEqual(case['revision'], 5)
        self.assertTrue(all(line['restoration_remaining_qty'] == 0 for line in case['lines']))
        self.assertEqual(len(self.conn.data['return_effects']), 2)

    def test_native_uuid_scope_and_receipt_tampering_still_rejected(self):
        self.conn = NativeUUIDConnection(); self.ship(); cmd = self.command(); self.commit(cmd)
        stored = deepcopy(self.conn.data)
        changes = (
            ('native_operation', lambda record: record.update(operation_id=str(UUID(int=9999))), 'return_operation_scope_mismatch'),
            ('order', lambda record: record.update(order_id=99), 'return_operation_scope_mismatch'),
            ('actor', lambda record: record.update(actor_id=8), 'return_authorization_required'),
            ('owner', lambda record: record.update(owner_scope='f'*64), 'return_operation_scope_mismatch'),
            ('receipt', lambda record: record['receipt'].update(operation_id=str(UUID(int=9999))), 'return_result_reference_mismatch'),
        )
        for name, change, code in changes:
            with self.subTest(name=name):
                self.conn.data = deepcopy(stored); self.conn.saved = deepcopy(stored)
                change(self.conn.data['return_ops'][cmd['operation_id']])
                with self.assertRaises(c.CommerceError) as error:
                    r.read_result(self.conn, NO, cmd['operation_id'], authorize=authorize, now=self.conn.clock)
                self.assertEqual(error.exception.code, code); self.assertTrue(self.conn.aborted)
                self.conn.rollback_simulation()

    def test_native_uuid_before_commit_and_nonstring_wire_still_rejected(self):
        self.conn = NativeUUIDConnection(); self.ship(); cmd = self.command(); self.execute(cmd)
        with self.assertRaises(c.CommerceError) as error:
            r.read_result(self.conn, NO, cmd['operation_id'], authorize=authorize, now=self.conn.clock)
        self.assertEqual(error.exception.code, 'commit_not_visible'); self.conn.rollback_simulation()
        cmd = self.command(); cmd['operation_id'] = UUID(cmd['operation_id'])
        self.rejects(cmd, 'invalid_uuid')

    def test_sources_do_not_import_main_db_or_manage_transactions(self):
        for module in (w,r):
            source=Path(module.__file__).read_text(encoding='utf-8'); tree=ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                    self.assertNotIn(node.func.attr,('commit','rollback','begin','begin_nested','create_engine'))
            self.assertNotRegex(source,r'from .*main import|from .*db import|import requests|import httpx')


if __name__=='__main__': unittest.main()
