"""Pure fake server-evidence regressions; never PG calls or database proof."""
from copy import deepcopy
import unittest

from api import commerce_contract as c
from api import commerce_payment_core as p

OP = '8b540b8a-ec5c-4517-a3fd-9541997aee83'
REQUEST = 'b798e9c3-52bc-4c53-8ce2-c7d98e57c9ab'
OTHER = '4f106413-8c13-41a7-83c3-f2bc8b717177'


def spec(kind='approve', **changes):
    return dict(operation_id=OP, request_id=REQUEST, order_no='fixture-order',
                owner=dict(kind='guest', user_id=11, owner_hash='a' * 64), kind=kind,
                adapter_id='fixture-adapter', provider='fixture-provider', environment='test',
                merchant_id='fixture-merchant', provider_order_id='fixture-provider-order', currency='KRW',
                amount=2100 if kind == 'approve' else 1600, order_total=2100,
                approved_amount=0 if kind == 'approve' else 2100,
                refunded_amount=0 if kind == 'approve' else 500, order_basis='c' * 64,
                allocation_lines=[dict(line_id='item-1', product_code=101, qty=2)], reservation_expires_at=200,
                original_operation_id=None if kind == 'approve' else OTHER,
                original_provider_ref=None if kind == 'approve' else 'fixture-original-ref',
                capabilities=dict(approve=True, cancel=True, partial_cancel=False, guest_checkout=True)) | changes


def prepared(kind='approve'):
    return p.prepare_operation(spec(kind), now=100)['operation']


def durable(kind='approve'):
    op = prepared(kind)
    receipt = dict(commerce_version=c.VERSION, operation_id=OP, request_basis=op['request_basis'],
                   prepared_revision=1, commit_id='fixture-prepared-commit')
    return p.attach_prepared_commit(op, receipt)


def processing(kind='approve'):
    return p.plan_dispatch(durable(kind), now=110, lease_expires_at=130)['next_operation']


def evidence(op, *, status=None, **changes):
    return {k: op['spec'][k] for k in ('provider', 'environment', 'merchant_id', 'provider_order_id', 'currency', 'amount')} | dict(
        operation_id=op['spec']['operation_id'], status=status or ('approved' if op['spec']['kind'] == 'approve' else 'cancelled'),
        provider_ref='fixture-result-ref', original_provider_ref=op['spec']['original_provider_ref'], observed_at=120) | changes


def verifier(op, event):
    # Test-only fake adapter attestation. This is not a signature, provider
    # request, real credential, or evidence that a transaction was committed.
    return dict(contract='commerce_provider_verification_v1', adapter_id=op['spec']['adapter_id'],
                verification_id='fixture-verification', operation_id=op['spec']['operation_id'],
                request_basis=op['request_basis'], evidence_basis=c.fingerprint(event), source='server_query')


def result(op, *, event=None, allocation='held', now=140):
    event = event or evidence(op)
    return p.plan_provider_result(op, event, verifier(op, event), now=now, allocation_state=allocation)


def commit_receipt(op, plan):
    return dict(commerce_version=c.VERSION, operation_id=op['spec']['operation_id'], request_basis=op['request_basis'],
                plan_basis=plan['plan_basis'], commit_id='fixture-final-commit',
                payment_id=9 if any(e['kind'].startswith('payment_') for e in plan['effects']) else None,
                effect_keys=[e['dedup_key'] for e in plan['effects']])


def finalized(kind='approve'):
    op = processing(kind)
    plan = result(op)
    return p.apply_finalization_receipt(op, plan, commit_receipt(op, plan))


class CommercePaymentCoreTests(unittest.TestCase):
    def test_authoritative_decline_releases_blocked_own_reservation_not_pending_or_unknown(self):
        operation=processing()
        event=evidence(operation,status='declined',provider_ref=None)
        plan=result(operation,event=event,allocation='blocked')
        self.assertEqual(plan['proposed_states']['allocation_state'],'released')
        self.assertEqual(plan['effects'],[dict(kind='release_reservation',dedup_key=OP+':release')])
        done=p.apply_finalization_receipt(operation,plan,commit_receipt(operation,plan))
        self.assertEqual(done['state'],'declined')
        self.assertEqual(result(done,event=event,allocation='released')['effects'],[])
        for status in ('pending','not_found'):
            event=evidence(operation,status=status,provider_ref=None)
            plan=result(operation,event=event,allocation='blocked')
            self.assertEqual(plan['action'],'query_required'); self.assertEqual(plan['effects'],[])

    def test_approval_and_cancel_have_separate_intents_and_balances(self):
        self.assertEqual(prepared()['spec']['amount'], 2100)
        self.assertEqual(prepared('cancel')['spec']['amount'], 1600)
        for change in ({'amount': True}, {'amount': 2100.0}, {'amount': 1}, {'currency': 'USD'},
                       {'approved_amount': 1}, {'refunded_amount': 1}, {'merchant_id': None}, {'environment': None}):
            with self.subTest(change=change), self.assertRaises(c.CommerceError):
                p.prepare_operation(spec(**change), now=100)

    def test_prepared_requires_durable_identity_not_boolean_before_dispatch(self):
        op = prepared()
        with self.assertRaisesRegex(c.CommerceError, 'prepared_commit_required'):
            p.plan_dispatch(op, now=110, lease_expires_at=130)
        for receipt in (True, {'durable': True}, {'verified': True}):
            with self.subTest(receipt=receipt), self.assertRaises(c.CommerceError):
                p.attach_prepared_commit(op, receipt)
        receipt = durable()['prepared_commit'] | {'request_basis': 'a' * 64}
        with self.assertRaisesRegex(c.CommerceError, 'prepared_commit_mismatch'):
            p.attach_prepared_commit(op, receipt)
        plan = p.plan_dispatch(durable(), now=110, lease_expires_at=130)
        self.assertTrue(plan['requires_commit_before_external'])
        self.assertEqual(plan['effects'], [])
        self.assertEqual(plan['action'], 'dispatch_after_commit')

    def test_request_replay_conflict_and_active_operation_exclusion(self):
        active = processing()
        self.assertEqual(p.prepare_operation(spec(), now=300, active=active)['action'], 'replay')
        with self.assertRaisesRegex(c.CommerceError, 'request_conflict'):
            p.prepare_operation(spec(provider_order_id='other'), now=110, active=active)
        with self.assertRaisesRegex(c.CommerceError, 'active_operation_conflict'):
            p.prepare_operation(spec(request_id=OTHER, operation_id=OTHER), now=110, active=active)
        with self.assertRaisesRegex(c.CommerceError, 'operation_scope_mismatch'):
            p.prepare_operation(spec(order_no='other'), now=110, active=active)
        with self.assertRaises(c.CommerceError):
            p.prepare_operation(spec(owner={'email': 'fixture@example.invalid'}), now=110)

    def test_every_provider_identity_is_matched_even_with_fresh_fake_attestation(self):
        op = processing()
        for field, bad in (('amount', 2099), ('amount', True), ('currency', 'USD'), ('merchant_id', 'other'),
                           ('provider', 'other'), ('environment', 'live'), ('provider_order_id', 'other'),
                           ('operation_id', OTHER), ('original_provider_ref', 'other')):
            event = evidence(op, **{field: bad})
            with self.subTest(field=field, bad=bad), self.assertRaises(c.CommerceError):
                result(op, event=event)

    def test_callback_status_and_verification_boolean_are_insufficient(self):
        op, event = processing(), evidence(processing())
        for proof in (None, True, {'verified': True}, {'status': 'approved'}):
            with self.subTest(proof=proof), self.assertRaises(c.CommerceError):
                p.plan_provider_result(op, event, proof, now=140, allocation_state='held')
        proof = verifier(op, event)
        for field, bad in (('source', 'browser_callback'), ('adapter_id', 'other'), ('operation_id', OTHER),
                           ('request_basis', 'a' * 64), ('evidence_basis', 'a' * 64), ('verification_id', None)):
            with self.subTest(field=field), self.assertRaises(c.CommerceError):
                p.plan_provider_result(op, event, proof | {field: bad}, now=140, allocation_state='held')

    def test_missing_evidence_and_null_fields_fail_closed(self):
        op = processing()
        for key in evidence(op):
            event = evidence(op)
            del event[key]
            with self.subTest(key=key), self.assertRaises(c.CommerceError):
                result(op, event=event)
        for change in ({'status': 'success'}, {'status': 'cancelled'}, {'provider_ref': None},
                       {'observed_at': 99}, {'observed_at': 141}, {'observed_at': True}):
            with self.subTest(change=change), self.assertRaises(c.CommerceError):
                result(op, event=evidence(op, **change))

    def test_pending_not_found_and_transport_loss_protect_unknown(self):
        op = processing()
        for status in ('pending', 'not_found'):
            plan = result(op, event=evidence(op, status=status, provider_ref=None))
            self.assertEqual(plan['action'], 'query_required')
            self.assertEqual(plan['next_operation']['state'], 'unknown')
            self.assertEqual(plan['effects'], [])
        lost = p.plan_unresolved(op, reason='transport_lost', now=500)
        unknown = lost['next_operation']
        retry = p.plan_dispatch(unknown, now=500, lease_expires_at=600)
        self.assertEqual(retry['action'], 'query_required')
        self.assertNotIn('external_identity', retry)
        expiry = p.plan_expiry(order_no='fixture-order', checkout_state='draft', allocation_state='held',
                               expires_at=200, now=500, active=unknown)
        self.assertEqual(expiry, dict(action='query_required', effects=[], reservation_action='protect'))

    def test_lease_expiry_is_not_reservation_expiry_and_late_success_is_recoverable(self):
        op = processing()
        expiry = p.plan_expiry(order_no='fixture-order', checkout_state='processing', allocation_state='protected',
                               expires_at=200, now=501, active=op)
        self.assertEqual(expiry['reservation_action'], 'protect')
        unknown = p.plan_unresolved(op, reason='process_lost', now=501)['next_operation']
        plan = result(unknown, event=evidence(unknown, observed_at=502), now=503, allocation='protected')
        self.assertEqual(plan['action'], 'finalize_after_commit')
        self.assertEqual(plan['proposed_states']['allocation_state'], 'allocated')

    def test_valid_success_plans_ledger_and_allocation_once_after_atomic_commit(self):
        op = processing()
        plan = result(op)
        self.assertEqual(op['state'], 'processing')
        self.assertIsNone(plan['next_operation']['final_commit'])
        self.assertEqual([(e['kind'], e.get('amount'), e.get('qty_delta')) for e in plan['effects']],
                         [('payment_approval', 2100, None), ('allocate', None, -2)])
        receipt = commit_receipt(op, plan)
        confirmed = p.apply_finalization_receipt(op, plan, receipt)
        self.assertEqual(confirmed['state'], 'confirmed')
        self.assertEqual(p.apply_finalization_receipt(confirmed, plan, receipt), confirmed)
        again = result(confirmed, event=evidence(confirmed, observed_at=130))
        self.assertEqual(again['effects'], [])
        self.assertEqual(again['action'], 'read_result')
        self.assertEqual(p.plan_dispatch(confirmed, now=140, lease_expires_at=200)['action'], 'read_result')

    def test_replanning_before_commit_has_stable_effect_keys_and_cas(self):
        op = processing()
        first, second = result(op), result(op)
        self.assertEqual(first, second)
        self.assertEqual(first['expected_revision'], op['revision'])
        self.assertIn('payment_operation_unique', first['requires'])
        stale = deepcopy(op)
        stale['revision'] += 1
        with self.assertRaises(c.CommerceError):
            p.apply_finalization_receipt(stale, first, commit_receipt(stale, first))

    def test_commit_receipt_cannot_skip_ledger_or_stock_effects(self):
        op, plan = processing(), result(processing())
        receipt = commit_receipt(op, plan)
        for bad in (True, receipt | {'effect_keys': []}, receipt | {'payment_id': None},
                    receipt | {'request_basis': 'a' * 64}, receipt | {'operation_id': OTHER}):
            with self.subTest(bad=bad), self.assertRaises(c.CommerceError):
                p.apply_finalization_receipt(op, plan, bad)
        terminal = deepcopy(op)
        terminal.update(state='confirmed', final_commit=True, provider_result=True)
        with self.assertRaises(c.CommerceError):
            p.plan_dispatch(terminal, now=140, lease_expires_at=200)

    def test_recomputed_hash_does_not_authorize_changed_finalize_semantics(self):
        op, plan = processing(), result(processing())
        for change in ('remove_effect', 'stock_qty', 'next_status', 'capability'):
            forged = deepcopy(plan)
            if change == 'remove_effect':
                forged['effects'].pop()
            elif change == 'stock_qty':
                forged['effects'][1]['qty_delta'] = -3
            elif change == 'next_status':
                forged['next_operation']['state'] = 'declined'
            else:
                forged['next_operation']['spec']['capabilities']['partial_cancel'] = True
            forged['plan_basis'] = c.fingerprint({k: v for k, v in forged.items() if k != 'plan_basis'})
            with self.subTest(change=change), self.assertRaises(c.CommerceError):
                p.apply_finalization_receipt(op, forged, commit_receipt(op, forged))

    def test_money_success_preserved_when_allocation_is_blocked(self):
        op = processing()
        for allocation in ('blocked', 'released'):
            plan = result(op, allocation=allocation)
            self.assertEqual(plan['proposed_states']['payment_state'], 'confirmed')
            self.assertEqual(plan['proposed_states']['allocation_state'], 'blocked')
            self.assertEqual(len(plan['effects']), 1)
            self.assertEqual(plan['effects'][0]['kind'], 'payment_approval')

    def test_authoritative_decline_releases_approval_hold_but_not_cancelled_goods(self):
        for kind in ('approve', 'cancel'):
            op = processing(kind)
            plan = result(op, event=evidence(op, status='declined', provider_ref=None), allocation='allocated' if kind == 'cancel' else 'held')
            self.assertEqual(plan['next_operation']['state'], 'declined')
            self.assertEqual(plan['effects'], [] if kind == 'cancel' else [dict(kind='release_reservation', dedup_key=OP + ':release')])
            final = p.apply_finalization_receipt(op, plan, commit_receipt(op, plan))
            self.assertEqual(final['state'], 'declined')

    def test_cancel_remaining_amount_partial_capability_and_no_automatic_stock_return(self):
        for amount in (0, -1, 1601, True, 1600.0):
            with self.subTest(amount=amount), self.assertRaises(c.CommerceError):
                p.prepare_operation(spec('cancel', amount=amount), now=100)
        with self.assertRaisesRegex(c.CommerceError, 'partial_cancel_unavailable'):
            p.prepare_operation(spec('cancel', amount=500), now=100)
        partial = spec('cancel', amount=500)
        partial['capabilities']['partial_cancel'] = True
        self.assertEqual(p.prepare_operation(partial, now=100)['action'], 'prepare')
        op = processing('cancel')
        plan = result(op, allocation='allocated')
        self.assertEqual(plan['effects'], [dict(kind='payment_cancel', dedup_key=OP + ':payment', amount=-1600)])
        self.assertEqual(plan['proposed_states']['refund_state'], 'refunded')
        self.assertEqual(plan['proposed_states']['allocation_state'], 'allocated')
        self.assertEqual(finalized('cancel')['state'], 'confirmed')
        with self.assertRaises(c.CommerceError):
            result(op, event=evidence(op, original_provider_ref='other'))

    def test_cancel_cannot_reference_itself_as_original_approval(self):
        with self.assertRaisesRegex(c.CommerceError, 'original_operation_mismatch'):
            p.prepare_operation(spec('cancel', original_operation_id=OP), now=100)

    def test_disabling_new_guest_checkout_does_not_block_existing_guest_cancel(self):
        cancel = spec('cancel')
        cancel['capabilities']['guest_checkout'] = False
        self.assertEqual(p.prepare_operation(cancel, now=100)['action'], 'prepare')
        approval = spec()
        approval['capabilities']['guest_checkout'] = False
        with self.assertRaisesRegex(c.CommerceError, 'guest_checkout_unavailable'):
            p.prepare_operation(approval, now=100)

    def test_terminal_result_conflict_and_later_timeout_cannot_erase_success(self):
        op = finalized()
        with self.assertRaisesRegex(c.CommerceError, 'terminal_result_conflict'):
            result(op, event=evidence(op, status='declined', provider_ref=None))
        self.assertEqual(p.plan_unresolved(op, reason='transport_lost', now=900)['action'], 'read_result')

    def test_draft_expiry_is_a_cas_plan_with_no_payment_or_stock_movement(self):
        op = durable()
        plan = p.plan_expiry(order_no='fixture-order', checkout_state='draft', allocation_state='held',
                             expires_at=200, now=200, active=op)
        self.assertEqual(plan['action'], 'expire_draft_after_commit')
        self.assertEqual(plan['next_operation']['state'], 'expired')
        self.assertEqual(plan['effects'], [dict(kind='release_reservation', dedup_key='fixture-order:draft-expiry')])
        with self.assertRaises(c.CommerceError):
            p.plan_dispatch(op, now=200, lease_expires_at=220)
        self.assertEqual(p.plan_expiry(order_no='fixture-order', checkout_state='draft', allocation_state='held',
                                       expires_at=200, now=199)['action'], 'none')

    def test_mutation_and_error_diagnostics_do_not_expose_inputs(self):
        op = processing()
        before = deepcopy(op)
        plan = result(op)
        plan['next_operation']['spec']['allocation_lines'][0]['qty'] = 99
        self.assertEqual(op, before)
        with self.assertRaises(c.CommerceError) as caught:
            result(op, event=evidence(op, merchant_id='DO_NOT_EXPOSE'))
        self.assertNotIn('DO_NOT_EXPOSE', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
