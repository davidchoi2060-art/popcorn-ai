"""Pure server-observation fixtures; no native auth, SQL, provider or commit proof."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
import ast
from pathlib import Path
import unittest

from api import commerce_contract as c
from api import commerce_payment_core as payment
from api import commerce_fulfillment_core as f

OP = 'df7165ef-46c8-4d60-bbf7-766061a75a9b'
APPROVAL = 'd50939bf-99ec-442b-9443-bd3bda922a36'
REQUEST = '172436a9-70f0-4a92-8e6c-8b70d3a9a370'
COMMIT = 'd86b1132-bbd1-4fce-803c-fbf53e2c2e88'
PRIVATE = 'https://fixture.invalid/receipt?private=do-not-expose'


def sale_lines():
    return [dict(line_id='a', product_code=202, qty=3), dict(line_id='b', product_code=101, qty=2)]


def cargo_lines(a=3, b=2):
    return [dict(line_id=line, product_code=code, sale_movement_id=movement, qty=qty)
            for line, code, movement, qty in (('a', 202, 31, a), ('b', 101, 32, b)) if qty]


def manual(kind, *, shipment_id=10, lines=None, occurred_at=50, actor_id=7,
           carrier='fixture carrier', tracking_no='fixture real tracking'):
    lines = cargo_lines() if lines is None else lines
    content = dict(order_no='fixture-order', shipment_id=shipment_id, lines=lines,
                   carrier=carrier, tracking_no=tracking_no)
    value = dict(source='operator_record', kind=kind, order_no='fixture-order',
                 shipment_id=shipment_id, actor_id=actor_id, occurred_at=occurred_at,
                 reference=PRIVATE, content_basis=c.fingerprint(content))
    return value | dict(basis=c.fingerprint(value))


def shipment(state='준비', *, shipment_id=10, lines=None, tracked=False):
    lines = ([] if state == '준비' and not tracked else cargo_lines()) if lines is None else lines
    result = dict(shipment_id=shipment_id, order_no='fixture-order', revision=1, state=state,
                  lines=lines, carrier=None, tracking_no=None, tracking_evidence=None,
                  handoff_evidence=None, delivery_evidence=None)
    if state != '준비' or tracked:
        result.update(carrier='fixture carrier', tracking_no='fixture real tracking',
                      tracking_evidence=manual('record_tracking', shipment_id=shipment_id, lines=lines))
    if state in ('배송중', '완료'):
        result['handoff_evidence'] = manual('handoff', shipment_id=shipment_id, lines=lines, occurred_at=60)
    if state == '완료':
        result['delivery_evidence'] = manual('deliver', shipment_id=shipment_id, lines=lines, occurred_at=70)
    return result


def approval(lines=None):
    spec = dict(operation_id=APPROVAL, request_id=REQUEST, order_no='fixture-order',
                owner=dict(kind='guest', user_id=11, owner_hash='a' * 64), kind='approve',
                adapter_id='fixture-adapter', provider='fixture-provider', environment='test',
                merchant_id='fixture-merchant', provider_order_id='fixture-provider-order', currency='KRW',
                amount=2100, order_total=2100, approved_amount=0, refunded_amount=0,
                order_basis='b' * 64, allocation_lines=sale_lines() if lines is None else lines, reservation_expires_at=500,
                original_operation_id=None, original_provider_ref=None,
                capabilities=dict(approve=True, cancel=True, partial_cancel=True, guest_checkout=True))
    operation = payment.prepare_operation(spec, now=10)['operation']
    prepared = dict(commerce_version=c.VERSION, operation_id=APPROVAL, request_basis=operation['request_basis'],
                    prepared_revision=1, commit_id=COMMIT)
    operation = payment.attach_prepared_commit(operation, prepared)
    operation = payment.plan_dispatch(operation, now=20, lease_expires_at=40)['next_operation']
    event = {key: spec[key] for key in payment._EXPECTED_FIELDS} | dict(
        operation_id=APPROVAL, status='approved', provider_ref='fixture-provider-ref',
        original_provider_ref=None, observed_at=30)
    verification = dict(contract='commerce_provider_verification_v1', adapter_id='fixture-adapter',
                        verification_id='fixture-verification', operation_id=APPROVAL,
                        request_basis=operation['request_basis'], evidence_basis=c.fingerprint(event), source='server_query')
    plan = payment.plan_provider_result(operation, event, verification, now=40, allocation_state='protected')
    receipt = dict(commerce_version=c.VERSION, operation_id=APPROVAL, request_basis=operation['request_basis'],
                   plan_basis=plan['plan_basis'], commit_id=COMMIT, payment_id=9,
                   effect_keys=[effect['dedup_key'] for effect in plan['effects']])
    operation = payment.apply_finalization_receipt(operation, plan, receipt)
    return dict(operation=operation, verification=verification, payment_id=9, write_txid=1, read_txid=2)


def inputs():
    order = dict(order_no='fixture-order', owner=dict(kind='guest', user_id=11, owner_hash='a' * 64),
                 basis_id='b' * 64, revision=3, order_state='출고', checkout_state='paid',
                 payment_state='confirmed', allocation_state='allocated', refund_state='none',
                 total=2100, approved_amount=2100, refunded_amount=0, lines=sale_lines())
    movements = [dict(movement_id=mid, order_no='fixture-order', operation_id=APPROVAL,
                      line_id=line['line_id'], product_code=line['product_code'], movement_type='own_sale',
                      qty_delta=-line['qty'], effect_key=APPROVAL + ':allocate:' + line['line_id'])
                 for mid, line in zip((31, 32), sale_lines())]
    return dict(order=order, approval=approval(), active_operations=[], movements=movements,
                shipments=[shipment()], policy=dict(policy_id='fixture shipping policy', policy_basis='c' * 64,
                    state='confirmed', order_no='fixture-order', responsibility='own', allowed_actions=list(f.ACTIONS),
                    allowed_refund_states=['none'], carriers=['fixture carrier']), now=100)


def request(action='record_tracking', **changes):
    value = dict(operation_id=OP, order_no='fixture-order', actor_id=7, action=action,
                 expected_order_basis='b' * 64, expected_order_revision=3, expected_policy_basis='c' * 64,
                 shipment_id=10, expected_shipment_revision=1, lines=cargo_lines(),
                 carrier='fixture carrier', tracking_no='fixture real tracking',
                 evidence=manual(action, occurred_at=80)) | changes
    value['operation_id'] = c.uuid_text(value['operation_id'])
    return value | dict(request_basis=c.fingerprint(value))


def grant(req):
    return dict(auth_source='api.auth.current_operator', authenticated=True, allowed=True,
                actor=dict(operator_id=req['actor_id'], role='operator', status='활성'),
                permission='commerce.fulfillment.write', order_no=req['order_no'], action=req['action'], checked_at=100)


def stored(plan):
    result = deepcopy(plan['result']); identity = deepcopy(plan['identity'])
    receipt = dict(operation_id=identity['operation_id'], request_basis=identity['request_basis'],
                   result_basis=c.fingerprint(dict(identity=identity, result=result)), commit_id=COMMIT,
                   write_txid=1, read_txid=2)
    return dict(identity=identity, result=result, receipt=receipt)


class CommerceFulfillmentCoreTests(unittest.TestCase):
    def run_plan(self, req=None, args=None, authorization=None, existing=None):
        req = request() if req is None else req
        args = inputs() if args is None else args
        return f.plan_fulfillment(req, **args, authorization=grant(req) if authorization is None else authorization,
                                  existing=existing)

    def rejects_without_mutation(self, req, args, *, authorization=None, existing=None, code=None):
        before = deepcopy((req, args, authorization, existing))
        with self.assertRaises(c.CommerceError) as failure:
            self.run_plan(req, args, authorization=authorization, existing=existing)
        self.assertNotIn(PRIVATE, str(failure.exception))
        self.assertEqual((req, args, authorization, existing), before)
        if code is not None:
            self.assertEqual(failure.exception.code, code)

    def test_tracking_is_pending_metadata_without_handoff_delivery_stock_or_owner_leak(self):
        req, args = request(), inputs(); before = deepcopy((req, args))
        plan = self.run_plan(req, args)
        self.assertEqual(plan['result']['shipment_state'], '준비')
        self.assertEqual(plan['result']['order_state'], '출고')
        self.assertEqual(plan['required_product_codes'], [101, 202])
        self.assertTrue(plan['pending']); self.assertTrue(plan['pending_commit'])
        self.assertEqual(plan['stock_effects'], []); self.assertEqual(plan['reservation_effects'], [])
        self.assertEqual([effect['kind'] for effect in plan['effects']], ['record_tracking'])
        self.assertEqual(plan['effects'][0]['evidence_source'], 'operator_record')
        for private in (PRIVATE, 'fixture real tracking', 'fixture carrier', 'a' * 64, 'fixture-provider-ref'):
            self.assertNotIn(private, repr(plan))
        self.assertEqual(set(plan['public']), {'operation_id', 'shipment_id', 'action', 'pending'})
        self.assertEqual((req, args), before)

    def test_handoff_uses_stored_tracking_and_does_not_imply_delivery(self):
        args = inputs(); args['shipments'] = [shipment(tracked=True)]
        plan = self.run_plan(request('handoff'), args)
        self.assertEqual(plan['result']['shipment_state'], '배송중')
        self.assertEqual(plan['result']['order_state'], '배송중')
        self.assertEqual(plan['stock_effects'], [])

    def test_delivery_completes_order_only_when_all_sold_quantities_are_delivered(self):
        args = inputs(); args['order']['order_state'] = '배송중'; args['shipments'] = [shipment('배송중')]
        plan = self.run_plan(request('deliver'), args)
        self.assertEqual(plan['result']['order_state'], '완료')
        self.assertEqual(plan['result']['shipment_state'], '완료')
        self.assertEqual(plan['stock_effects'], [])

    def test_split_delivery_preserves_order_until_other_shipment_and_remaining_qty_complete(self):
        for other_state, other_lines in (('배송중', cargo_lines(2, 1)), ('완료', cargo_lines(1, 1))):
            with self.subTest(other_state=other_state):
                args = inputs(); args['order']['order_state'] = '배송중'
                selected = cargo_lines(1, 1)
                args['shipments'] = [shipment('배송중', lines=selected), shipment(other_state, shipment_id=11, lines=other_lines)]
                req = request('deliver', lines=selected, evidence=manual('deliver', lines=selected, occurred_at=80))
                self.assertEqual(self.run_plan(req, args)['result']['order_state'], '배송중')

    def test_all_existing_prepared_shipments_consume_remaining_source_quantity(self):
        args = inputs(); args['shipments'] += [shipment(shipment_id=11, lines=cargo_lines(2, 1))]
        remaining = cargo_lines(1, 1)
        req = request(lines=remaining, evidence=manual('record_tracking', lines=remaining, occurred_at=80))
        self.assertTrue(self.run_plan(req, args)['pending'])
        self.rejects_without_mutation(request(), args, code='shipment_quantity_exceeded')

    def test_target_preallocated_quantity_is_counted_once_not_added_twice(self):
        args = inputs(); args['shipments'] = [shipment(lines=cargo_lines())]
        self.assertTrue(self.run_plan(request(), args)['pending'])
        args['shipments'][0]['lines'] = cargo_lines(1, 1)
        self.rejects_without_mutation(request(), args, code='shipment_content_changed')

    def test_same_product_distinct_lines_do_not_merge_sale_movement_identity(self):
        args = inputs(); args['order']['lines'][1]['product_code'] = 202
        self.rejects_without_mutation(request(), args, code='fulfillment_allocation_scope_mismatch')
        args['approval'] = approval(args['order']['lines'])
        args['movements'][1]['product_code'] = 202
        lines = cargo_lines(); lines[1]['product_code'] = 202
        req = request(lines=lines, evidence=manual('record_tracking', lines=lines, occurred_at=80))
        self.assertEqual(self.run_plan(req, args)['required_product_codes'], [202])

    def test_whole_scope_and_sale_movement_drift_reject_without_partial_effects(self):
        mutations = [lambda a: a['movements'].pop(),
                     lambda a: a['movements'][0].update(order_no='other-order'),
                     lambda a: a['movements'][0].update(operation_id=OP),
                     lambda a: a['movements'][0].update(qty_delta=-2),
                     lambda a: a['movements'][0].update(product_code=101),
                     lambda a: a['movements'][0].update(effect_key='unbound-effect'),
                     lambda a: a['movements'][1].update(movement_id=31),
                     lambda a: a['order']['lines'][0].update(qty=4),
                     lambda a: a['order']['owner'].update(user_id=99),
                     lambda a: a['shipments'].append(deepcopy(a['shipments'][0])),
                     lambda a: a['shipments'][0].update(order_no='other-order')]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                args = inputs(); mutation(args); self.rejects_without_mutation(request(), args)

    def test_stale_order_shipment_policy_or_request_basis_is_rejected(self):
        for field, value in (('expected_order_basis', 'd' * 64), ('expected_order_revision', 2),
                             ('expected_shipment_revision', 2), ('expected_policy_basis', 'd' * 64)):
            with self.subTest(field=field):
                self.rejects_without_mutation(request(**{field: value}), inputs())
        req = request(); req['tracking_no'] = 'changed after fingerprint'
        self.rejects_without_mutation(req, inputs())

    def test_financial_unresolved_and_unallocated_states_never_plan_shipment(self):
        for field, values in (('payment_state', ('prepared', 'processing', 'unknown', 'unpaid')),
                              ('checkout_state', ('draft', 'processing', 'unknown')),
                              ('allocation_state', ('held', 'protected', 'blocked', 'released'))):
            for value in values:
                with self.subTest(field=field, value=value):
                    args = inputs(); args['order'][field] = value
                    self.rejects_without_mutation(request(), args, code='fulfillment_payment_unconfirmed')
        for state in ('prepared', 'processing', 'unknown'):
            args = inputs(); args['active_operations'] = [dict(operation_id=OP, order_no='fixture-order', kind='cancel', state=state)]
            self.rejects_without_mutation(request(), args, code='financial_operation_unresolved')

    def test_missing_commit_and_provider_binding_receipts_cannot_be_booleans(self):
        mutations = [lambda a: a.update(approval=True),
                     lambda a: a['approval'].update(payment_id=99),
                     lambda a: a['approval'].update(read_txid=1),
                     lambda a: a['approval']['operation'].update(final_commit=None),
                     lambda a: a['approval']['verification'].update(evidence_basis='d' * 64),
                     lambda a: a['order'].update(approved_amount=2000),
                     lambda a: a['order'].update(refunded_amount=2200)]
        for mutation in mutations:
            args = inputs(); mutation(args); self.rejects_without_mutation(request(), args)

    def test_requested_and_partial_refunds_require_explicit_policy_without_new_universal_ban(self):
        for state, refunded in (('requested', 0), ('partial', 500)):
            args = inputs(); args['order'].update(refund_state=state, refunded_amount=refunded)
            self.rejects_without_mutation(request(), args, code='fulfillment_policy_blocked')
            args['policy']['allowed_refund_states'].append(state)
            self.assertTrue(self.run_plan(request(), args)['pending'])
        for state in ('processing', 'unknown', 'refunded'):
            args = inputs(); args['order']['refund_state'] = state
            if state == 'refunded': args['order']['refunded_amount'] = 2100
            self.rejects_without_mutation(request(), args)

    def test_missing_responsibility_policy_and_carrier_have_no_default(self):
        for field, value in (('responsibility', None), ('state', 'unconfirmed'), ('carriers', []),
                             ('allowed_actions', []), ('allowed_refund_states', [])):
            args = inputs(); args['policy'][field] = value
            self.rejects_without_mutation(request(), args)
        args = inputs(); del args['policy']['responsibility']
        self.rejects_without_mutation(request(), args)
        args = inputs(); args['policy']['carriers'] = ['other carrier']
        self.rejects_without_mutation(request(), args)

    def test_authorization_is_exact_server_actor_scope_and_action_not_positive_id(self):
        req = request(); good = grant(req)
        mutations = [lambda g: g.update(authenticated=1), lambda g: g.update(allowed=False),
                     lambda g: g.update(auth_source='browser'), lambda g: g.update(permission='commerce.order.read'),
                     lambda g: g['actor'].update(operator_id=8), lambda g: g['actor'].update(role='viewer'),
                     lambda g: g['actor'].update(status='비활성'), lambda g: g.update(order_no='other-order'),
                     lambda g: g.update(action='deliver'), lambda g: g.update(checked_at=99)]
        for mutation in mutations:
            auth = deepcopy(good); mutation(auth)
            self.rejects_without_mutation(req, inputs(), authorization=auth)

    def test_manual_evidence_cannot_claim_provider_verification_or_another_scope(self):
        mutations = [lambda e: e.update(source='provider_verified'), lambda e: e.update(order_no='other-order'),
                     lambda e: e.update(shipment_id=11), lambda e: e.update(actor_id=8),
                     lambda e: e.update(content_basis='d' * 64), lambda e: e.update(reference=''),
                     lambda e: e.update(occurred_at=101), lambda e: e.update(basis='d' * 64)]
        for mutation in mutations:
            event = manual('record_tracking', occurred_at=80); mutation(event)
            self.rejects_without_mutation(request(evidence=event), inputs())

    def test_tracking_handoff_delivery_states_and_evidence_chronology_remain_distinct(self):
        for action, state in (('deliver', '준비'), ('record_tracking', '배송중')):
            args = inputs(); args['shipments'] = [shipment(state)]
            self.rejects_without_mutation(request(action), args, code='fulfillment_transition_blocked')
        self.rejects_without_mutation(request('handoff'), inputs(), code='shipment_tracking_required')
        args = inputs(); args['shipments'] = [shipment(tracked=True)]
        req = request('handoff', evidence=manual('handoff', occurred_at=49))
        self.rejects_without_mutation(req, args, code='shipment_evidence_time_mismatch')
        args = inputs(); args['order']['order_state'] = '배송중'; args['shipments'] = [shipment('배송중')]
        req = request('deliver', evidence=manual('deliver', occurred_at=59))
        self.rejects_without_mutation(req, args, code='shipment_evidence_time_mismatch')
        args['shipments'][0]['handoff_evidence'] = None
        self.rejects_without_mutation(request('deliver'), args)

    def test_target_content_and_inspection_order_state_cannot_drift(self):
        args = inputs(); args['shipments'] = [shipment(tracked=True)]
        lines = cargo_lines(2, 2)
        req = request('handoff', lines=lines, evidence=manual('handoff', lines=lines, occurred_at=80))
        self.rejects_without_mutation(req, args, code='shipment_content_changed')
        args['order']['order_state'] = '조립중'
        self.rejects_without_mutation(request('handoff'), args, code='fulfillment_transition_blocked')

    def test_native_integers_reject_bool_float_decimal_string_and_overflow(self):
        for value in (True, 1.0, Decimal('1'), '1', 0, -1, c.MAX_INTEGER + 1):
            for location in ('actor', 'shipment_revision', 'movement', 'order_revision', 'approval_id'):
                with self.subTest(value=repr(value), location=location):
                    args = inputs(); req = request()
                    if location == 'actor':
                        req['actor_id'] = value
                    elif location == 'shipment_revision': args['shipments'][0]['revision'] = value
                    elif location == 'movement': args['movements'][0]['movement_id'] = value
                    elif location == 'order_revision': args['order']['revision'] = value
                    else: args['approval']['payment_id'] = value
                    self.rejects_without_mutation(req, args)

    def test_quantity_limits_and_duplicate_lines_are_native_and_exact(self):
        for qty in (True, 1.0, Decimal('1'), '1', 0, -1, c.MAX_QUANTITY + 1):
            req = request(); req['lines'][0]['qty'] = qty
            self.rejects_without_mutation(req, inputs())
        req = request(); req['lines'].append(deepcopy(req['lines'][0]))
        self.rejects_without_mutation(req, inputs())

    def test_exact_replay_skips_current_business_calculation_and_has_no_new_effects(self):
        req = request(); previous = stored(self.run_plan(req))
        args = inputs(); args['order'].update(payment_state='unknown', revision=99, basis_id='d' * 64)
        args.update(approval=None, movements=None, shipments=None, policy=None, active_operations=None)
        with patch.object(f, '_new_plan', side_effect=AssertionError('must not recalculate')):
            plan = self.run_plan(req, args, existing=previous)
        self.assertEqual(plan['action'], 'read_existing_result')
        self.assertEqual(plan['effects'], []); self.assertFalse(plan['pending_commit']); self.assertTrue(plan['pending'])
        self.assertEqual(plan['result'], previous['result'])

    def test_replay_other_actor_order_owner_action_and_payload_are_conflicts(self):
        base = request(); previous = stored(self.run_plan(base))
        cases = [request(actor_id=8, evidence=manual('record_tracking', actor_id=8, occurred_at=80)),
                 request('handoff'), request(expected_order_revision=4),
                 request(tracking_no='changed', evidence=manual('record_tracking', tracking_no='changed', occurred_at=80))]
        for req in cases:
            self.rejects_without_mutation(req, inputs(), existing=previous, code='fulfillment_operation_conflict')
        args = inputs(); args['order']['owner']['user_id'] = 99
        self.rejects_without_mutation(base, args, existing=previous, code='fulfillment_operation_conflict')
        other = deepcopy(previous); other['identity']['order_no'] = 'other-order'
        self.rejects_without_mutation(base, inputs(), existing=other, code='fulfillment_operation_conflict')

    def test_replay_requires_authorization_and_bound_redacted_stored_reference(self):
        req = request(); previous = stored(self.run_plan(req))
        auth = grant(req); auth['allowed'] = False
        self.rejects_without_mutation(req, inputs(), authorization=auth, existing=previous)
        for mutation in (lambda p: p['receipt'].update(read_txid=1),
                         lambda p: p['receipt'].update(operation_id=APPROVAL),
                         lambda p: p['result'].update(shipment_revision=9),
                         lambda p: p['result'].update(private=PRIVATE),
                         lambda p: p['identity'].update(actor_id=True)):
            bad = deepcopy(previous); mutation(bad)
            self.rejects_without_mutation(req, inputs(), existing=bad)

    def test_resealed_recovery_result_still_binds_original_evidence_action_and_versions(self):
        req = request(); previous = stored(self.run_plan(req))
        for field, value in (('evidence_basis', 'd' * 64), ('order_revision', 9),
                             ('shipment_revision', 9), ('shipment_state', '완료'), ('order_state', '취소')):
            with self.subTest(field=field):
                bad = deepcopy(previous); bad['result'][field] = value
                bad['receipt']['result_basis'] = c.fingerprint(dict(identity=bad['identity'], result=bad['result']))
                self.rejects_without_mutation(req, inputs(), existing=bad, code='fulfillment_result_reference_mismatch')

    def test_uuid_normalization_and_unknown_schema_fields_are_explicit(self):
        req = request(); req['operation_id'] = OP.upper()
        # The basis is over the canonical UUID, so uppercase representation replays.
        self.assertEqual(self.run_plan(req)['identity']['operation_id'], OP)
        for target in ('request', 'order', 'policy', 'shipment', 'evidence', 'approval'):
            args = inputs(); req = request()
            container = {'request': req, 'order': args['order'], 'policy': args['policy'],
                         'shipment': args['shipments'][0], 'evidence': req['evidence'], 'approval': args['approval']}[target]
            container['unexpected'] = PRIVATE
            self.rejects_without_mutation(req, args)

    def test_return_value_is_detached_and_source_has_no_io_or_transaction_owner(self):
        req, args = request(), inputs(); before = deepcopy((req, args))
        plan = self.run_plan(req, args); plan['result']['order_revision'] = 999
        self.assertEqual((req, args), before)
        source = (Path(__file__).resolve().parents[1]/'api/commerce_fulfillment_core.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name == 'copy' for alias in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, ('copy', None))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, ('execute', 'connect', 'begin', 'commit', 'rollback', 'begin_nested'))


if __name__ == '__main__':
    unittest.main()
