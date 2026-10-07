"""Pure observations only: these fixtures prove no SQL/auth/provider/COMMIT."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import ast
import unittest

from api import commerce_contract as c
from api import commerce_physical_return_core as physical
from tests import test_commerce_fulfillment_core as shipping_fixture

OP = 'df7165ef-46c8-4d60-bbf7-766061a75a9b'
PRIOR = '7e404f6d-e90b-4f1b-93e0-41b78eac5db8'
CANCEL = 'b6a8d53d-5b58-49d0-9e13-d9e8fae499ae'
PRIVATE = shipping_fixture.PRIVATE
RULE = 'e' * 64


def seal(value):
    value['basis'] = c.fingerprint({key: item for key, item in value.items() if key != 'basis'})
    return value


def evidence(kind, line, *, return_id=20, actor_id=7, occurred_at=None, quantities=None):
    if quantities is None:
        quantities = (dict(inspected_qty=line['inspected_qty'], resellable_qty=line['resellable_qty'])
                      if kind == 'inspect' else dict(qty=line['collected_qty' if kind == 'collect' else 'received_qty']))
    return seal(dict(source='server_inspection' if kind == 'inspect' else 'operator_record',
        state='confirmed', kind=kind, order_no='fixture-order', return_id=return_id,
        return_line_id=line['return_line_id'], shipment_id=line['shipment_id'],
        sale_movement_id=line['sale_movement_id'], actor_id=actor_id,
        occurred_at={'collect': 75, 'receive': 80, 'inspect': 90}[kind] if occurred_at is None else occurred_at,
        reference=PRIVATE, content_basis=c.fingerprint(quantities), rules_basis=RULE if kind == 'inspect' else None))


def return_line(*, line_id='a', return_line_id=51, shipment_id=10, return_id=20,
                qty=3, inspected=0, resale=0, product_code=None):
    line = dict(return_line_id=return_line_id, shipment_id=shipment_id, line_id=line_id,
        sale_movement_id=31 if line_id == 'a' else 32,
        product_code=(202 if line_id == 'a' else 101) if product_code is None else product_code,
        claimed_qty=qty, collected_qty=qty, received_qty=qty, inspected_qty=inspected, resellable_qty=resale,
        collection_evidence=None, receipt_evidence=None, inspection_evidence=None)
    for kind, key, count in (('collect', 'collection_evidence', qty), ('receive', 'receipt_evidence', qty),
                             ('inspect', 'inspection_evidence', inspected)):
        if count:
            line[key] = evidence(kind, line, return_id=return_id)
    return line


def observe(args):
    args['history'] = dict(state='complete', order_no=args['order']['order_no'], read_txid=2,
        financial_operation_ids=[row['operation_id'] for row in args['financial_operations']],
        shipment_ids=[row['shipment_id'] for row in args['shipments']],
        return_ids=[row['return_id'] for row in args['returns']],
        restoration_effect_keys=[row['effect_key'] for row in args['restorations']],
        basis_id=c.fingerprint(dict(order_no=args['order']['order_no'], read_txid=2,
            **{key: args[key] for key in ('financial_operations', 'shipments', 'returns', 'restorations')})))
    return args


def inputs(*, inspected=0, resale=0):
    base = shipping_fixture.inputs()
    base.pop('active_operations')
    base['order']['order_state'] = '완료'
    base.update(financial_operations=[dict(operation_id=shipping_fixture.APPROVAL,
        order_no='fixture-order', kind='approve', state='confirmed')],
        shipments=[shipping_fixture.shipment('완료')],
        returns=[dict(return_id=20, order_no='fixture-order', revision=1,
                      lines=[return_line(inspected=inspected, resale=resale)])],
        restorations=[], inspection=None,
        policy=dict(policy_id='fixture explicit physical policy', policy_basis='d' * 64, state='confirmed',
            order_no='fixture-order', inspection_rule_basis=RULE, allowed_actions=['inspect', 'restore'],
            allowed_refund_states=['none'], allowed_active_cancel_states=[]))
    return observe(base)


def inspection_result(line, *, return_id=20, qty=None, resale=2, actor_id=7):
    qty = line['received_qty'] if qty is None else qty
    return dict(return_line_id=line['return_line_id'], inspected_qty=qty, resellable_qty=resale,
        evidence=evidence('inspect', line, return_id=return_id, actor_id=actor_id,
                          quantities=dict(inspected_qty=qty, resellable_qty=resale)))


def request(args, action='inspect', *, quantities=None, **changes):
    target = next(case for case in args['returns'] if case['return_id'] == changes.get('return_id', 20))
    if quantities is None:
        quantities = [dict(return_line_id=line['return_line_id'],
                           qty=line['received_qty'] if action == 'inspect' else 1) for line in target['lines']]
    if action == 'inspect' and args['inspection'] is None:
        args['inspection'] = [inspection_result(line, return_id=target['return_id'],
                                               resale=min(2, line['received_qty'])) for line in target['lines']]
    proofs = ({row['return_line_id']: row['evidence'] for row in args['inspection']} if action == 'inspect'
              else {line['return_line_id']: line['inspection_evidence'] for line in target['lines']})
    refs = [dict(return_line_id=row['return_line_id'], inspection_basis=proofs[row['return_line_id']]['basis'])
            for row in sorted(quantities, key=lambda row: row['return_line_id'])]
    value = dict(operation_id=OP, actor_id=7, order_no='fixture-order', return_id=target['return_id'], action=action,
        expected_order_basis=args['order']['basis_id'], expected_order_revision=args['order']['revision'],
        expected_return_revision=target['revision'], expected_policy_basis=args['policy']['policy_basis'],
        expected_history_basis=args['history']['basis_id'], evidence_basis=c.fingerprint(refs), lines=quantities) | changes
    return rebind(value)


def rebind(req):
    normalized = dict(req, operation_id=c.uuid_text(req['operation_id']),
                      lines=sorted(req['lines'], key=lambda row: row['return_line_id']))
    req['request_basis'] = c.fingerprint({key: value for key, value in normalized.items() if key != 'request_basis'})
    return req


def grant(req):
    return dict(auth_source='api.auth.current_operator', authenticated=True, allowed=True,
        actor=dict(operator_id=req['actor_id'], role='operator', status='활성'),
        permission='commerce.return.' + req['action'], order_no=req['order_no'], return_id=req['return_id'],
        action=req['action'], checked_at=100)


def restoration(args, *, line_id=51, qty=1, state='applied', operation_id=PRIOR, actor_id=7, movement_id=81):
    case = next(case for case in args['returns'] if any(line['return_line_id'] == line_id for line in case['lines']))
    line = next(line for line in case['lines'] if line['return_line_id'] == line_id)
    value = dict(physical_operation_id=operation_id, actor_id=actor_id, order_no='fixture-order',
        return_id=case['return_id'], return_line_id=line_id, sale_movement_id=line['sale_movement_id'],
        product_code=line['product_code'], qty=qty, inspection_basis=line['inspection_evidence']['basis'],
        policy_basis=args['policy']['policy_basis'], state=state, effect_key=operation_id + ':return:' + str(line_id),
        movement_id=None, receipt=None)
    if state == 'applied':
        value.update(movement_id=movement_id, receipt=dict(operation_id=operation_id,
            effect_key=value['effect_key'], movement_id=movement_id,
            content_basis=c.fingerprint({key: value[key] for key in ('physical_operation_id', 'actor_id',
                'order_no', 'return_id', 'return_line_id', 'sale_movement_id', 'product_code', 'qty',
                'inspection_basis', 'policy_basis', 'effect_key')}),
            commit_id=shipping_fixture.COMMIT, write_txid=1, read_txid=2))
    return value


class PhysicalReturnCoreTests(unittest.TestCase):
    def run_plan(self, req, args, *, authorization=None, existing=None):
        return physical.plan_physical_return(req, **args,
            authorization=grant(req) if authorization is None else authorization, existing=existing)

    def rejects(self, req, args, *, code=None, **kwargs):
        before = deepcopy((req, args, kwargs))
        with self.assertRaises(c.CommerceError) as caught:
            self.run_plan(req, args, **kwargs)
        self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertEqual((req, args, kwargs), before)
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def test_inspection_records_confirmed_server_result_with_zero_stock_or_money_effects(self):
        args = inputs(); req = request(args); before = deepcopy((args, req))
        plan = self.run_plan(req, args)
        self.assertEqual(plan['effects'][0]['resellable_qty'], 2)
        self.assertEqual(plan['effects'][0]['inspected_qty'], 3)
        self.assertEqual(plan['stock_effects'], [])
        self.assertEqual(plan['financial_effects'], []); self.assertEqual(plan['reservation_effects'], [])
        self.assertEqual(plan['result']['order_revision'], 4); self.assertEqual(plan['result']['return_revision'], 2)
        self.assertTrue(plan['pending']); self.assertTrue(plan['pending_commit'])
        self.assertEqual((args, req), before)

    def test_restoration_uses_inspection_and_separate_physical_effect_identity(self):
        args = inputs(inspected=3, resale=2); req = request(args, 'restore')
        plan = self.run_plan(req, args)
        self.assertEqual(plan['effects'], [])
        self.assertEqual(plan['stock_effects'], [dict(kind='restore_return_stock', physical_operation_id=OP,
            return_id=20, return_line_id=51, sale_movement_id=31, product_code=202, qty_delta=1,
            inspection_basis=args['returns'][0]['lines'][0]['inspection_evidence']['basis'], effect_key=OP + ':return:51')])
        self.assertEqual(plan['financial_effects'], []); self.assertEqual(plan['reservation_effects'], [])

    def test_cash_full_refund_is_neither_required_nor_sufficient_for_stock_restoration(self):
        for state, amount in (('none', 0), ('partial', 500), ('refunded', 2100)):
            args = inputs(inspected=3, resale=2)
            args['order'].update(refund_state=state, refunded_amount=amount)
            args['policy']['allowed_refund_states'] = [state]
            plan = self.run_plan(request(args, 'restore'), args)
            self.assertEqual(plan['stock_effects'][0]['qty_delta'], 1)
        args = inputs(); req = request(args)
        args['order'].update(refund_state='refunded', refunded_amount=2100)
        args['policy']['allowed_refund_states'] = ['refunded']
        req.update(action='restore'); rebind(req); args['inspection'] = None
        self.rejects(req, args, code='inspection_result_required')

    def test_unclear_cash_and_active_cancel_require_explicit_confirmed_policy(self):
        for state in ('prepared', 'processing', 'unknown'):
            args = inputs(inspected=3, resale=2)
            args['order']['refund_state'] = 'unknown'
            args['financial_operations'].append(dict(operation_id=CANCEL, order_no='fixture-order', kind='cancel', state=state))
            observe(args); req = request(args, 'restore')
            self.rejects(req, args, code='return_policy_blocked')
            args['policy']['allowed_refund_states'] = ['unknown']
            self.rejects(req, args, code='financial_state_policy_unconfirmed')
            args['policy']['allowed_active_cancel_states'] = [state]
            self.assertEqual(len(self.run_plan(req, args)['stock_effects']), 1)
            args['policy']['state'] = 'unknown'
            self.rejects(req, args, code='return_policy_unconfirmed')

    def test_unresolved_approval_cannot_be_authorized_as_cash_cancel(self):
        args = inputs(); args['financial_operations'].append(dict(operation_id=CANCEL,
            order_no='fixture-order', kind='approve', state='unknown'))
        args['policy']['allowed_active_cancel_states'] = ['unknown']; observe(args)
        self.rejects(request(args), args, code='financial_state_policy_unconfirmed')

    def test_no_policy_defaults_and_stale_order_return_history_policy_are_rejected(self):
        for key, value in (('expected_order_basis', 'f' * 64), ('expected_order_revision', 4),
                           ('expected_return_revision', 2), ('expected_policy_basis', 'f' * 64),
                           ('expected_history_basis', 'f' * 64)):
            args = inputs(); req = request(args, **{key: value}); self.rejects(req, args)
        for key in ('inspection_rule_basis', 'allowed_actions', 'allowed_refund_states', 'allowed_active_cancel_states'):
            args = inputs(); req = request(args); del args['policy'][key]; self.rejects(req, args)

    def test_authorization_is_current_exact_and_never_supplied_by_a_client_boolean(self):
        mutations = [lambda a: a.update(auth_source='client'), lambda a: a.update(authenticated=False),
            lambda a: a.update(allowed=False), lambda a: a.update(permission='commerce.order.read'),
            lambda a: a['actor'].update(operator_id=8), lambda a: a['actor'].update(role='viewer'),
            lambda a: a['actor'].update(status='비활성'), lambda a: a.update(order_no='other-order'),
            lambda a: a.update(return_id=21), lambda a: a.update(action='restore'), lambda a: a.update(checked_at=99)]
        for mutate in mutations:
            args = inputs(); req = request(args); auth = grant(req); mutate(auth)
            self.rejects(req, args, authorization=auth)

    def test_original_sale_requires_owner_payment_receipt_and_exact_own_sale_lines(self):
        mutations = [lambda a: a['order']['owner'].update(user_id=12),
            lambda a: a['order'].update(payment_state='unknown'), lambda a: a['order'].update(allocation_state='held'),
            lambda a: a['approval'].update(payment_id=10), lambda a: a['approval'].update(read_txid=1),
            lambda a: a['movements'][0].update(qty_delta=-2), lambda a: a['movements'][0].update(movement_type='adjust'),
            lambda a: a['movements'][0].update(operation_id=OP), lambda a: a['movements'][0].update(effect_key='wrong')]
        for mutate in mutations:
            args = inputs(); req = request(args); mutate(args); self.rejects(req, args)

    def test_collection_receipt_inspection_bind_order_case_shipment_and_original_sale(self):
        for kind in ('collection_evidence', 'receipt_evidence', 'inspection_evidence'):
            for key, value in (('order_no', 'other-order'), ('return_id', 21), ('return_line_id', 52),
                               ('shipment_id', 11), ('sale_movement_id', 32), ('state', 'unknown')):
                args = inputs(inspected=3, resale=2); req = request(args, 'restore')
                args['returns'][0]['lines'][0][kind][key] = value
                seal(args['returns'][0]['lines'][0][kind]); observe(args)
                req['expected_history_basis'] = args['history']['basis_id']; rebind(req)
                self.rejects(req, args)

    def test_invoice_only_cannot_prove_actual_handoff_or_collection(self):
        args = inputs(); args['shipments'] = [shipping_fixture.shipment(tracked=True)]; observe(args)
        self.rejects(request(args), args, code='actual_handoff_required')

    def test_evidence_is_confirmed_chronological_quantity_bound_and_not_future(self):
        for key, value in (('source', 'operator_record'), ('actor_id', 8), ('occurred_at', 79),
                           ('occurred_at', 101), ('content_basis', 'f' * 64), ('rules_basis', 'f' * 64), ('reference', '')):
            args = inputs(); req = request(args); proof = args['inspection'][0]['evidence']
            proof[key] = value; seal(proof); self.rejects(req, args)
        args = inputs(); req = request(args); args['inspection'][0]['evidence']['basis'] = 'f' * 64
        self.rejects(req, args, code='physical_evidence_basis_mismatch')
        args = inputs(); req = request(args); req['evidence_basis'] = 'f' * 64; rebind(req)
        self.rejects(req, args, code='inspection_evidence_changed')

    def test_physical_counts_never_exceed_collected_received_inspected_or_claimed(self):
        for key, value in (('collected_qty', 4), ('received_qty', 4), ('inspected_qty', 4), ('resellable_qty', 4)):
            args = inputs(inspected=3, resale=2); req = request(args, 'restore')
            args['returns'][0]['lines'][0][key] = value; observe(args)
            req['expected_history_basis'] = args['history']['basis_id']; rebind(req); self.rejects(req, args)
        args = inputs(); req = request(args); args['inspection'][0]['resellable_qty'] = 4
        self.rejects(req, args, code='inspection_quantity_exceeded')

    def test_nonresellable_items_restore_zero_and_missing_inspection_fails_closed(self):
        args = inputs(); args['inspection'] = [inspection_result(args['returns'][0]['lines'][0], resale=0)]
        plan = self.run_plan(request(args), args)
        self.assertEqual(plan['effects'][0]['resellable_qty'], 0); self.assertEqual(plan['stock_effects'], [])
        args = inputs(inspected=3, resale=0)
        self.rejects(request(args, 'restore'), args, code='restoration_quantity_exceeded')
        args = inputs(inspected=3, resale=2); req = request(args, 'restore')
        args['returns'][0]['lines'][0]['inspection_evidence'] = None; observe(args)
        req['expected_history_basis'] = args['history']['basis_id']; rebind(req); self.rejects(req, args)

    def test_partial_restoration_consumes_case_resellable_balance(self):
        args = inputs(inspected=3, resale=2); args['restorations'] = [restoration(args)]; observe(args)
        plan = self.run_plan(request(args, 'restore'), args)
        self.assertEqual(plan['stock_effects'][0]['qty_delta'], 1)
        self.rejects(request(args, 'restore', quantities=[dict(return_line_id=51, qty=2)]), args,
                     code='restoration_quantity_exceeded')

    def test_all_returns_share_original_sale_and_claim_caps(self):
        args = inputs(); args['returns'][0]['lines'] = [return_line(qty=2, inspected=2, resale=2)]
        args['returns'].append(dict(return_id=21, order_no='fixture-order', revision=1,
            lines=[return_line(return_id=21, return_line_id=52, qty=1, inspected=1, resale=1)]))
        args['restorations'] = [restoration(args, line_id=51),
            restoration(args, line_id=52, operation_id=CANCEL, movement_id=82)]; observe(args)
        plan = self.run_plan(request(args, 'restore'), args)
        self.assertEqual(sum(row['qty'] for row in args['restorations']) + plan['stock_effects'][0]['qty_delta'], 3)
        self.rejects(request(args, 'restore', quantities=[dict(return_line_id=51, qty=2)]), args,
                     code='restoration_quantity_exceeded')
        args['returns'].append(dict(return_id=22, order_no='fixture-order', revision=1,
            lines=[return_line(return_id=22, return_line_id=53, qty=1)])); observe(args)
        self.rejects(request(args, 'restore'), args, code='return_quantity_exceeded')

    def test_uncollected_prepared_return_claims_still_reserve_shipment_quantity(self):
        args = inputs(); args['returns'][0]['lines'] = [return_line(qty=2, inspected=2, resale=2)]
        held = return_line(return_id=21, return_line_id=52, qty=1)
        held.update(collected_qty=0, received_qty=0, collection_evidence=None, receipt_evidence=None)
        args['returns'].append(dict(return_id=21, order_no='fixture-order', revision=1, lines=[held])); observe(args)
        self.assertEqual(self.run_plan(request(args, 'restore'), args)['stock_effects'][0]['qty_delta'], 1)
        duplicate = deepcopy(held); duplicate['return_line_id'] = 53
        args['returns'].append(dict(return_id=22, order_no='fixture-order', revision=1, lines=[duplicate])); observe(args)
        self.rejects(request(args, 'restore'), args, code='return_quantity_exceeded')

    def test_same_product_distinct_original_lines_keep_separate_effects(self):
        args = inputs(); lines = shipping_fixture.sale_lines(); lines[1]['product_code'] = 202
        args['order']['lines'] = lines; args['approval'] = shipping_fixture.approval(lines)
        args['movements'][1]['product_code'] = 202
        cargo = shipping_fixture.cargo_lines(); cargo[1]['product_code'] = 202
        args['shipments'] = [shipping_fixture.shipment('완료', lines=cargo)]
        args['returns'][0]['lines'] = [return_line(inspected=3, resale=2),
            return_line(line_id='b', return_line_id=52, qty=2, inspected=2, resale=2, product_code=202)]
        observe(args); plan = self.run_plan(request(args, 'restore'), args)
        self.assertEqual(plan['required_product_codes'], [202])
        self.assertEqual([effect['sale_movement_id'] for effect in plan['stock_effects']], [31, 32])
        self.assertEqual(len({effect['effect_key'] for effect in plan['stock_effects']}), 2)

    def test_one_original_line_split_across_shipments_is_combined_without_double_allocation(self):
        args = inputs(); args['shipments'] = [shipping_fixture.shipment('완료', lines=shipping_fixture.cargo_lines(2, 2)),
            shipping_fixture.shipment('완료', shipment_id=11, lines=shipping_fixture.cargo_lines(1, 0))]
        args['returns'][0]['lines'] = [return_line(qty=2, inspected=2, resale=2),
            return_line(return_line_id=52, shipment_id=11, qty=1, inspected=1, resale=1)]
        observe(args); quantities = [dict(return_line_id=51, qty=2), dict(return_line_id=52, qty=1)]
        plan = self.run_plan(request(args, 'restore', quantities=quantities), args)
        self.assertEqual(sum(effect['qty_delta'] for effect in plan['stock_effects']), 3)
        self.assertEqual({effect['sale_movement_id'] for effect in plan['stock_effects']}, {31})
        self.rejects(request(args, 'restore', quantities=[dict(return_line_id=51, qty=3), dict(return_line_id=52, qty=1)]),
                     args, code='restoration_quantity_exceeded')

    def test_prepared_processing_unknown_restorations_occupy_quantity_and_block_same_source(self):
        for state in ('prepared', 'processing', 'unknown'):
            args = inputs(inspected=3, resale=2); args['restorations'] = [restoration(args, state=state)]; observe(args)
            self.rejects(request(args, 'restore'), args, code='physical_restoration_unresolved')
            args['restorations'][0]['qty'] = 3; observe(args)
            self.rejects(request(args, 'restore'), args, code='restoration_quantity_exceeded')

    def test_unresolved_other_original_line_does_not_block_confirmed_target_source(self):
        args = inputs(inspected=3, resale=2)
        args['returns'].append(dict(return_id=21, order_no='fixture-order', revision=1,
            lines=[return_line(line_id='b', return_id=21, return_line_id=52, qty=2, inspected=2, resale=2)]))
        args['restorations'] = [restoration(args, line_id=52, state='unknown')]; observe(args)
        self.assertEqual(self.run_plan(request(args, 'restore'), args)['stock_effects'][0]['sale_movement_id'], 31)

    def test_manifest_detects_missing_financial_shipment_return_or_restoration_rows(self):
        for key in ('financial_operations', 'shipments', 'returns', 'restorations'):
            args = inputs(inspected=3, resale=2); args['restorations'] = [restoration(args)]; observe(args)
            req = request(args, 'restore'); args[key] = []
            self.rejects(req, args)
        args = inputs(); req = request(args); args['history']['state'] = 'partial'
        self.rejects(req, args, code='whole_return_history_required')
        args = inputs(); req = request(args); args['returns'][0]['revision'] = 2
        self.rejects(req, args, code='return_history_changed')

    def test_nonobject_history_rows_duplicate_manifest_ids_and_missing_actual_rows_are_stable_errors(self):
        for key in ('financial_operations', 'shipments', 'returns', 'restorations'):
            args = inputs(); req = request(args); args[key].append(None); self.rejects(req, args)
        for key in ('financial_operation_ids', 'shipment_ids', 'return_ids'):
            args = inputs(); req = request(args); args['history'][key] *= 2; self.rejects(req, args)
        args = inputs(); req = request(args); args['history']['restoration_effect_keys'] = [PRIVATE]
        self.rejects(req, args, code='whole_return_history_required')

    def test_receipts_bind_scope_qty_commit_read_and_unique_stock_movement(self):
        mutations = [lambda r: r.update(sale_movement_id=32), lambda r: r.update(product_code=101),
            lambda r: r.update(inspection_basis='f' * 64), lambda r: r.update(effect_key='wrong'),
            lambda r: r['receipt'].update(operation_id=OP), lambda r: r['receipt'].update(movement_id=82),
            lambda r: r['receipt'].update(content_basis='f' * 64), lambda r: r['receipt'].update(read_txid=1),
            lambda r: r['receipt'].update(read_txid=3), lambda r: r['receipt'].update(commit_id='unknown')]
        for mutate in mutations:
            args = inputs(inspected=3, resale=2); prior = restoration(args); mutate(prior)
            args['restorations'] = [prior]; observe(args); self.rejects(request(args, 'restore'), args)
        args = inputs(inspected=3, resale=2)
        args['restorations'] = [restoration(args), restoration(args, operation_id=CANCEL)]; observe(args)
        self.rejects(request(args, 'restore'), args, code='duplicate_restoration_movement')

    def test_original_sale_movement_cannot_be_reused_as_applied_restoration_receipt(self):
        for movement_id in (31, 32):
            args = inputs(inspected=3, resale=2)
            args['restorations'] = [restoration(args, movement_id=movement_id)]; observe(args)
            self.rejects(request(args, 'restore'), args, code='duplicate_restoration_movement')

    def test_pending_receipt_and_duplicate_effect_key_cannot_masquerade_as_new_allocation(self):
        args = inputs(inspected=3, resale=2); row = restoration(args, state='prepared'); row['movement_id'] = 81
        args['restorations'] = [row]; observe(args)
        self.rejects(request(args, 'restore'), args, code='restoration_receipt_mismatch')
        args = inputs(inspected=3, resale=2); row = restoration(args)
        args['restorations'] = [row, deepcopy(row)]; observe(args)
        self.rejects(request(args, 'restore'), args, code='whole_return_history_required')

    def test_physical_uuid_cannot_reuse_financial_identity_or_previous_restoration(self):
        args = inputs(inspected=3, resale=2)
        self.rejects(request(args, 'restore', operation_id=shipping_fixture.APPROVAL), args,
                     code='physical_operation_must_be_independent')
        args['restorations'] = [restoration(args, operation_id=OP)]; observe(args)
        self.rejects(request(args, 'restore'), args, code='physical_existing_result_required')
        args = inputs(inspected=3, resale=2); args['restorations'] = [restoration(args, operation_id=shipping_fixture.APPROVAL)]
        observe(args); self.rejects(request(args, 'restore'), args, code='restoration_scope_mismatch')

    def test_one_physical_operation_cannot_span_different_actors_or_return_cases(self):
        args = inputs(); args['returns'][0]['lines'] = [return_line(qty=2, inspected=2, resale=2)]
        args['returns'].append(dict(return_id=21, order_no='fixture-order', revision=1,
            lines=[return_line(return_id=21, return_line_id=52, qty=1, inspected=1, resale=1)]))
        args['restorations'] = [restoration(args), restoration(args, line_id=52, movement_id=82)]
        observe(args); self.rejects(request(args, 'restore'), args, code='restoration_operation_scope_mismatch')

    def test_reinspection_cannot_rewrite_evidence_after_partial_stock_restoration(self):
        args = inputs(inspected=3, resale=2); args['restorations'] = [restoration(args)]; observe(args)
        self.rejects(request(args), args, code='inspection_has_restoration_history')
        args = inputs(inspected=3, resale=2); args['policy']['inspection_rule_basis'] = 'f' * 64
        self.rejects(request(args, 'restore'), args, code='inspection_result_required')

    def test_native_request_quantities_and_ids_reject_null_bool_float_decimal_string_overflow(self):
        for value in (None, True, 1.0, Decimal('1'), '1', 0, -1, c.MAX_QUANTITY + 1):
            for key in ('qty', 'return_line_id'):
                args = inputs(); req = request(args); req['lines'][0][key] = value; self.rejects(req, args)
        for value in (None, True, 1.0, Decimal('1'), '1', 0, -1, c.MAX_INTEGER + 1):
            for key in ('actor_id', 'return_id', 'expected_order_revision', 'expected_return_revision'):
                args = inputs(); req = request(args); req[key] = value; self.rejects(req, args)

    def test_native_server_inspection_auth_receipt_and_counts_reject_null_or_coercion(self):
        for value in (None, True, 1.0, Decimal('1'), '1'):
            for location in ('inspection', 'authorization', 'movement', 'history', 'order', 'receipt', 'count'):
                args = inputs(inspected=3, resale=2); req = request(args)
                auth = grant(req)
                if location == 'inspection': args['inspection'][0]['resellable_qty'] = value
                elif location == 'authorization': auth['checked_at'] = value
                elif location == 'movement': args['movements'][0]['qty_delta'] = value
                elif location == 'history': args['history']['read_txid'] = value
                elif location == 'order': args['order']['revision'] = value
                elif location == 'count': args['returns'][0]['lines'][0]['resellable_qty'] = value
                else:
                    row = restoration(args); row['receipt']['movement_id'] = value
                    args['restorations'] = [row]
                # Reseal representable bool/null/string observations so failure
                # cannot be caused merely by a stale manifest hash. Float and
                # Decimal are deliberately rejected at the JSON boundary too.
                if location in ('count', 'receipt') and type(value) not in (float, Decimal):
                    observe(args); req['expected_history_basis'] = args['history']['basis_id']; rebind(req)
                self.rejects(req, args, authorization=auth)

    def test_exact_replay_returns_old_result_without_current_business_recalculation(self):
        for action in ('inspect', 'restore'):
            args = inputs(inspected=3, resale=2); req = request(args, action)
            previous = shipping_fixture.stored(self.run_plan(req, args))
            args['order'].update(payment_state='unknown', revision=99, basis_id='f' * 64)
            for key in ('approval', 'financial_operations', 'movements', 'shipments', 'returns',
                        'restorations', 'history', 'inspection', 'policy'): args[key] = None
            with patch.object(physical, '_new_plan', side_effect=AssertionError('must not recalculate')):
                plan = self.run_plan(req, args, existing=previous)
            self.assertEqual(plan['result'], previous['result']); self.assertEqual(plan['action'], 'read_existing_result')
            for key in ('effects', 'stock_effects', 'financial_effects', 'reservation_effects'): self.assertEqual(plan[key], [])
            self.assertTrue(plan['pending']); self.assertFalse(plan['pending_commit'])

    def test_replay_conflicting_actor_owner_order_case_qty_evidence_version_are_rejected(self):
        args = inputs(inspected=3, resale=2); base = request(args, 'restore')
        previous = shipping_fixture.stored(self.run_plan(base, args))
        for key, value in (('actor_id', 8), ('return_id', 21), ('action', 'inspect'), ('expected_order_revision', 4),
                           ('expected_return_revision', 2), ('evidence_basis', 'f' * 64), ('expected_policy_basis', 'f' * 64),
                           ('lines', [dict(return_line_id=51, qty=2)])):
            req = deepcopy(base); req[key] = value; rebind(req)
            self.rejects(req, args, existing=previous, code='return_operation_conflict')
        other = deepcopy(args); other['order']['owner']['user_id'] = 99
        self.rejects(base, other, existing=previous, code='return_operation_conflict')
        for key, value in (('order_no', 'other-order'), ('contract', 'older_contract')):
            bad = deepcopy(previous); bad['identity'][key] = value
            self.rejects(base, args, existing=bad, code='return_operation_conflict')

    def test_replay_rechecks_auth_and_resealed_results_still_bind_original_request(self):
        args = inputs(); req = request(args); previous = shipping_fixture.stored(self.run_plan(req, args))
        auth = grant(req); auth['allowed'] = False; self.rejects(req, args, existing=previous, authorization=auth)
        for key, value in (('action', 'restore'), ('order_revision', 9), ('return_revision', 9),
                           ('evidence_basis', 'f' * 64), ('lines', [dict(return_line_id=51, qty=2)])):
            bad = deepcopy(previous); bad['result'][key] = value
            bad['receipt']['result_basis'] = c.fingerprint(dict(identity=bad['identity'], result=bad['result']))
            self.rejects(req, args, existing=bad, code='return_result_reference_mismatch')
        for mutate in (lambda p: p['receipt'].update(read_txid=1), lambda p: p['receipt'].update(operation_id=PRIOR),
                       lambda p: p['result'].update(private=PRIVATE), lambda p: p['identity'].update(actor_id=True)):
            bad = deepcopy(previous); mutate(bad); self.rejects(req, args, existing=bad)

    def test_uuid_normalization_unknown_fields_duplicate_and_foreign_target_lines_fail_closed(self):
        args = inputs(); req = request(args); req['operation_id'] = OP.upper()
        self.assertEqual(self.run_plan(req, args)['identity']['operation_id'], OP)
        for target in ('request', 'order', 'policy', 'history', 'inspection', 'case', 'line', 'evidence'):
            args = inputs(); req = request(args)
            container = {'request': req, 'order': args['order'], 'policy': args['policy'], 'history': args['history'],
                'inspection': args['inspection'][0], 'case': args['returns'][0], 'line': args['returns'][0]['lines'][0],
                'evidence': args['inspection'][0]['evidence']}[target]
            container['private'] = PRIVATE; self.rejects(req, args)
        args = inputs(); req = request(args); req['lines'] *= 2; self.rejects(req, args, code='duplicate_return_line')
        req = request(args); req['lines'][0]['return_line_id'] = 52; rebind(req)
        self.rejects(req, args, code='return_line_scope_mismatch')

    def test_public_allowlist_deepcopy_full_product_locks_cas_atomic_and_pure_limits(self):
        args = inputs(); req = request(args); before = deepcopy((req, args)); plan = self.run_plan(req, args)
        self.assertEqual(set(plan['public']), {'operation_id', 'return_id', 'action', 'pending'})
        for secret in (PRIVATE, 'a' * 64, 'fixture real tracking', 'fixture carrier', 'fixture-provider-ref'):
            self.assertNotIn(secret, repr(plan))
        self.assertEqual(plan['required_product_codes'], [101, 202])
        self.assertTrue({'whole_history_snapshot_recheck', 'whole_products_asc_before_order',
            'order_then_return_then_child_locks', 'order_revision_cas', 'return_revision_cas',
            'physical_operation_unique', 'restoration_effect_unique', 'all_return_quantity_caps_recheck',
            'atomic_caller_transaction', 'read_after_commit'}.issubset(plan['requirements']))
        plan['result']['lines'][0]['qty'] = 999; plan['effects'][0]['resellable_qty'] = 999
        self.assertEqual((req, args), before)
        source = (Path(__file__).resolve().parents[1] / 'api/commerce_physical_return_core.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): self.fail('pure core imports only selected pure helpers')
            if isinstance(node, ast.ImportFrom): self.assertIn(node.module, ('copy', None))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, ('execute', 'connect', 'begin', 'commit', 'rollback', 'begin_nested'))
        self.assertIn('cannot authenticate evidence', source)
        self.assertIn('only the adapter can prove', source)
        self.assertIn('return_stock=False', (Path(__file__).resolve().parents[1] / 'api/commerce_contract.py')
                      .read_text(encoding='utf-8').replace(' ', ''))


if __name__ == '__main__':
    unittest.main()
