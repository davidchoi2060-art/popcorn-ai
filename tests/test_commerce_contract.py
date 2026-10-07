"""Supplied-data regression tests, not authorization/DB/real commerce proof."""
from copy import deepcopy
import ast
from pathlib import Path
import unittest

from api import commerce_contract as c


def owner():
    return dict(kind='guest', user_id=11, owner_hash='a' * 64)


def policy():
    return dict(policy_id='fixture-policy', policy_basis='b' * 64, state='confirmed', currency='KRW',
                capabilities=dict(approve=True, cancel=True, partial_cancel=False, guest_checkout=True))


def sale():
    return dict(basis_id='c' * 64, source=dict(kind='fixture-sale-source', id='101', version='v1'),
                state='confirmed', currency='KRW',
                lines=[dict(line_id='item-1', product_code=101, name='fixture product', qty=2,
                            unit_amount=1000, stock_available=3)], charges=[dict(code='fixture-fee', amount=100)],
                total=2100, expires_at=200, price_basis='d' * 64, stock_basis='e' * 64,
                terms_basis='f' * 64, policy_id='fixture-policy', policy_basis='b' * 64)


def draft():
    return dict(request_id='b798e9c3-52bc-4c53-8ce2-c7d98e57c9ab', source=sale()['source'],
                expected_basis='c' * 64,
                shipping=dict(name='fixture recipient', phone='fixture phone', address='fixture address',
                              contact_email='fixture@example.invalid'))


def detail():
    return dict(order_no='fixture-order', order_state='접수', checkout_state='draft',
                payment_state='unpaid', allocation_state='held', refund_state='none', total=2100,
                currency='KRW', expires_at=200, lines=sale()['lines'], reason_codes=['price_recheck', 'stock_recheck'],
                capabilities=policy()['capabilities'])


class CommerceContractTests(unittest.TestCase):
    def validate(self, value, **kwargs):
        return c.validate_sale_basis(value, expected_basis='c' * 64, policy=kwargs.get('policy', policy()), now=100)

    def test_confirmed_basis_preserves_lines_charges_and_source_without_mutation(self):
        value = sale()
        original = deepcopy(value)
        result = self.validate(value)
        self.assertEqual(result['total'], 2100)
        self.assertEqual(result['source'], value['source'])
        result['lines'][0]['name'] = 'changed'
        self.assertEqual(value, original)

    def test_missing_null_unknown_fields_and_unconfirmed_basis_fail_closed(self):
        for field in sale():
            for bad in ('missing', 'null'):
                value = sale()
                if bad == 'missing':
                    del value[field]
                else:
                    value[field] = None
                with self.subTest(field=field, bad=bad), self.assertRaises(c.CommerceError):
                    self.validate(value)
        for state in ('estimated', 'basis_met', 'approved', 'unknown', True):
            with self.subTest(state=state), self.assertRaises(c.CommerceError):
                self.validate(sale() | {'state': state})

    def test_current_basis_policy_and_expiry_are_bound(self):
        for change in ({'basis_id': 'a' * 64}, {'policy_id': 'other'}, {'policy_basis': 'a' * 64},
                       {'currency': 'USD'}, {'expires_at': 100}, {'expires_at': 99}):
            with self.subTest(change=change), self.assertRaises(c.CommerceError):
                self.validate(sale() | change)
        with self.assertRaises(c.CommerceError):
            self.validate(sale(), policy=policy() | {'state': 'unknown'})

    def test_money_is_integer_and_sum_has_no_float_bool_or_overflow(self):
        for field in ('unit_amount', 'stock_available', 'qty', 'product_code'):
            for bad in (None, True, False, 1.0, '1', -1, c.MAX_INTEGER + 1):
                value = sale()
                value['lines'][0][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(c.CommerceError):
                    self.validate(value)
        for amount in (True, 2100.0, -1, 2101, c.MAX_INTEGER + 1):
            with self.subTest(total=amount), self.assertRaises(c.CommerceError):
                self.validate(sale() | {'total': amount})
        value = sale()
        value['lines'][0]['unit_amount'] = c.MAX_INTEGER
        with self.assertRaises(c.CommerceError):
            self.validate(value)

    def test_quantity_technical_range_and_explicit_policy_are_distinct(self):
        value = sale()
        value['lines'][0].update(qty=10000, unit_amount=1, stock_available=10000)
        value['total'] = 10100
        self.assertEqual(self.validate(value)['lines'][0]['qty'], 10000)
        with self.assertRaisesRegex(c.CommerceError, 'quantity_policy_exceeded'):
            self.validate(value, policy=policy() | {'max_quantity': 9999})
        for qty in (0, -1, c.MAX_QUANTITY + 1):
            value['lines'][0]['qty'] = qty
            with self.subTest(qty=qty), self.assertRaises(c.CommerceError):
                self.validate(value)

    def test_duplicate_product_quantities_are_aggregated_against_one_stock_basis(self):
        value = sale()
        value['lines'].append(dict(value['lines'][0], line_id='item-2'))
        value['total'] = 4100
        with self.assertRaisesRegex(c.CommerceError, 'stock_insufficient'):
            self.validate(value)
        value['lines'][1]['stock_available'] = 4
        with self.assertRaisesRegex(c.CommerceError, 'stock_basis_inconsistent'):
            self.validate(value)
        for line in value['lines']:
            line['stock_available'] = 4
        self.assertEqual(self.validate(value)['total'], 4100)
        value['lines'][1]['line_id'] = 'item-1'
        with self.assertRaisesRegex(c.CommerceError, 'duplicate_line'):
            self.validate(value)

    def test_charges_are_server_policy_lines_without_invented_assembly_fee(self):
        value = sale()
        value['charges'] = []
        value['total'] = 2000
        self.assertEqual(self.validate(value)['total'], 2000)
        for charge in ({'code': 'fee', 'amount': True}, {'code': 'fee', 'amount': -1},
                       {'code': 'fee', 'amount': 1.0}, {'code': 'fee', 'amount': 0, 'verified': True}):
            with self.subTest(charge=charge), self.assertRaises(c.CommerceError):
                self.validate(value | {'charges': [charge]})
        value['charges'] = [dict(code='fee', amount=50), dict(code='fee', amount=50)]
        value['total'] = 2100
        with self.assertRaises(c.CommerceError):
            self.validate(value)

    def test_email_dev_and_verified_boolean_cannot_supply_order_ownership(self):
        for value in ({'email': 'fixture@example.invalid'},
                      {'kind': 'member', 'member_id': 11, 'verified': True},
                      owner() | {'email': 'fixture@example.invalid'},
                      {'kind': 'member', 'member_id': 11, 'auth_subject': None}):
            with self.subTest(owner=value), self.assertRaises(c.CommerceError):
                c.owner_identity(value)
        with self.assertRaisesRegex(c.CommerceError, 'owner_mismatch'):
            c.require_owner(owner(), owner() | {'user_id': 12})
        with self.assertRaisesRegex(c.CommerceError, 'owner_mismatch'):
            c.require_owner(owner(), dict(kind='member', member_id=11, auth_subject='fixture-verified-subject'))

    def test_canonical_request_replays_result_and_rejects_changed_payload(self):
        identity = c.request_identity(draft()['request_id'].upper(), {'b': [1, 2], 'a': 'value'}, owner())
        reordered = c.request_identity(draft()['request_id'], {'a': 'value', 'b': [1, 2]}, owner())
        self.assertEqual(identity, reordered)
        self.assertEqual(c.replay_request(identity, None), {'state': 'new'})
        existing = dict(identity=identity, result={'order_no': 'fixture-order', 'state': 'draft'})
        replay = c.replay_request(reordered, existing)
        replay['result']['state'] = 'modified'
        self.assertEqual(existing['result']['state'], 'draft')
        other = c.request_identity(draft()['request_id'], {'a': 'value', 'b': [2, 1]}, owner())
        with self.assertRaisesRegex(c.CommerceError, 'request_conflict'):
            c.replay_request(other, existing)
        with self.assertRaises(c.CommerceError):
            c.replay_request(identity | {'owner': owner() | {'owner_hash': 'b' * 64}}, existing)

    def test_json_rejects_float_nonfinite_nonstring_key_and_non_json(self):
        for value in ({'price': 1.0}, {'price': float('nan')}, {1: 'v'}, {'object': object()}, {'set': {1}},
                      {'big': c.MAX_INTEGER + 1}):
            with self.subTest(value=value), self.assertRaises(c.CommerceError):
                c.fingerprint(value)

    def test_unencodable_input_is_a_value_free_validation_error(self):
        with self.assertRaises(c.CommerceError) as caught:
            c.fingerprint({'invalid': '\ud800'})
        self.assertEqual(str(caught.exception), 'invalid_json')

    def test_draft_checks_source_shipping_and_does_not_promote_email(self):
        body = draft()
        output = c.draft_contract(body, owner=owner(), sale_basis=sale(), policy=policy(), now=100)
        self.assertEqual(output['identity']['owner'], owner())
        self.assertNotIn('member_id', output['identity']['owner'])
        for bad in (body | {'amount': 1}, body | {'verified': True},
                    body | {'source': dict(body['source'], id='other')},
                    body | {'shipping': body['shipping'] | {'address': ''}}):
            with self.subTest(bad=bad), self.assertRaises(c.CommerceError):
                c.draft_contract(bad, owner=owner(), sale_basis=sale(), policy=policy(), now=100)
        blocked = policy()
        blocked['capabilities']['guest_checkout'] = False
        with self.assertRaises(c.CommerceError):
            c.draft_contract(body, owner=owner(), sale_basis=sale(), policy=blocked, now=100)

    def test_detail_has_multiple_reasons_and_no_secret_or_pii_projection(self):
        row = detail() | dict(owner_hash='DO_NOT_EXPOSE', shipping={'phone': 'DO_NOT_EXPOSE'},
                              pg_ref='DO_NOT_EXPOSE', environment='DO_NOT_EXPOSE', receipt='DO_NOT_EXPOSE')
        output = c.order_detail(row)
        self.assertEqual(output['reason_codes'], ['price_recheck', 'stock_recheck'])
        self.assertNotIn('DO_NOT_EXPOSE', str(output))
        output['reason_codes'].clear()
        self.assertEqual(len(row['reason_codes']), 2)

    def test_detail_unknown_removes_approval_and_cancel_actions(self):
        row = detail() | dict(checkout_state='unknown', payment_state='unknown', allocation_state='protected')
        output = c.order_detail(row)
        self.assertFalse(output['capabilities']['approve'])
        self.assertFalse(output['capabilities']['cancel'])
        for proof in (None, True, {'verified': True}):
            with self.subTest(proof=proof), self.assertRaises(c.CommerceError):
                c.order_detail(detail() | dict(checkout_state='paid', payment_state='confirmed', committed_payment=proof))

    def test_detail_confirmed_requires_bound_structured_commit(self):
        proof = dict(operation_id=draft()['request_id'], request_basis='a' * 64, commit_id='fixture-commit',
                     payment_id=9, order_no='fixture-order', amount=2100, currency='KRW', status='approved')
        row = detail() | dict(checkout_state='paid', payment_state='confirmed', allocation_state='allocated',
                              committed_payment=proof)
        self.assertEqual(c.order_detail(row)['payment_state'], 'confirmed')
        for field, value in (('order_no', 'other'), ('amount', True), ('amount', 1), ('currency', 'USD'), ('status', 'pending')):
            with self.subTest(field=field), self.assertRaises(c.CommerceError):
                c.order_detail(row | {'committed_payment': proof | {field: value}})
        with self.assertRaises(c.CommerceError):
            c.order_detail(detail() | {'allocation_state': 'allocated'})

    def test_fulfillment_state_cannot_claim_paid_without_payment_and_allocation(self):
        for state in ('결제완료', '조립중', '출고', '배송중', '완료'):
            with self.subTest(state=state), self.assertRaises(c.CommerceError):
                c.order_detail(detail() | {'order_state': state})

    def test_wire_money_uses_lossless_decimal_text_above_js_safe_integer(self):
        value = 2**53 + 1
        row = detail() | {'total': value, 'lines': [dict(line_id='large', name='fixture', qty=1, unit_amount=value)]}
        output = c.order_detail(row)
        self.assertEqual(output['total'], '9007199254740993')
        self.assertEqual(output['lines'][0]['unit_amount'], output['total'])
        self.assertIs(type(output['total']), str)

    def test_modules_have_only_pure_imports_and_no_router_or_io(self):
        root = Path(__file__).resolve().parents[1]
        allowed = {'copy', 'hashlib', 'json', 're', 'commerce_contract'}
        for name in ('commerce_contract.py', 'commerce_payment_core.py'):
            tree = ast.parse((root / 'api' / name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name in allowed for alias in node.names))
                elif isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module or node.names[0].name, allowed)
                elif isinstance(node, ast.Name):
                    self.assertNotIn(node.id, {'router', 'engine', 'open', 'eval', 'exec', '__import__'})


class CommerceEnvelopeTests(unittest.TestCase):
    context = dict(state='confirmed', binding_id='577fbb7b-524c-487a-9192-e266272532cb')
    basis = dict(state='confirmed', basis_id='8'*64)

    def record(self):
        return dict(row=detail()|{'owner_binding_id':self.context['binding_id']},basis=dict(self.basis),
                    permissions=None,balances=dict(approved=0,refunded=0))

    def permissions(self,keys,**allowed):
        return {key:dict(allowed=allowed.get(key,False),reason=None if allowed.get(key,False) else 'route_unavailable',
                        expected_basis=self.basis['basis_id']) for key in keys}

    def customer(self,record=None,**changes):
        return c.order_envelope([record or self.record()],audience='customer',context=self.context,
                                checked_at=100,**changes)

    def test_customer_list_detail_public_binding_lossless_money_and_one_order_per_row(self):
        record=self.record(); record['permissions']=self.permissions(c.CUSTOMER_ACTIONS,confirm=True)
        result=self.customer(record)
        item=result['items'][0]
        self.assertEqual(item['total'],'2100'); self.assertEqual(item['refundable_amount'],'0')
        self.assertTrue(item['actions']['confirm']['allowed']); self.assertEqual(result['context'],self.context)
        self.assertEqual(self.customer(record,detail=True)['item'],item)
        with self.assertRaisesRegex(c.CommerceError,'duplicate_order'):
            c.order_envelope([record,record],audience='customer',context=self.context,checked_at=100)

    def test_unknown_context_never_exposes_old_personal_rows(self):
        unknown=dict(state='unconfirmed',binding_id=None)
        self.assertEqual(c.order_envelope([],audience='customer',context=unknown,checked_at=100)['items'],[])
        with self.assertRaises(c.CommerceError):
            c.order_envelope([self.record()],audience='customer',context=unknown,checked_at=100)
        for bad in (None,'',self.context['binding_id'].replace('577f','677f')):
            record=self.record(); record['row']['owner_binding_id']=bad
            with self.subTest(binding=bad),self.assertRaises(c.CommerceError): self.customer(record)

    def test_policy_capability_is_never_actor_permission_and_reconcile_missing_is_false(self):
        item=self.customer()['items'][0]
        self.assertTrue(item['capabilities']['approve'])
        self.assertFalse(any(x['allowed'] for x in item['actions'].values()))
        self.assertEqual(item['actions']['reconcile']['reason'],'permission_unconfirmed')

    def test_stale_basis_and_mismatched_permission_fail_closed(self):
        for state,identity in (('stale','7'*64),('unconfirmed',None),('confirmed','7'*64)):
            record=self.record(); record['basis']=dict(state=state,basis_id=identity)
            record['permissions']=self.permissions(c.CUSTOMER_ACTIONS,confirm=True)
            item=self.customer(record)['items'][0]
            self.assertFalse(item['actions']['confirm']['allowed'])
        for bad in (True,{'allowed':True,'reason':None,'expected_basis':''},
                    {'allowed':True,'reason':None,'expected_basis':None}):
            record=self.record(); record['permissions']=self.permissions(c.CUSTOMER_ACTIONS)
            record['permissions']['confirm']=bad
            with self.assertRaises(c.CommerceError): self.customer(record)

    def test_public_envelope_allowlist_excludes_secrets_and_other_receipts(self):
        record=self.record(); record['row'].update(owner_hash='secret',shipping={'phone':'private'},
          merchant_id='private',pg_token='private',admin_receipt='private')
        serialized=c.fingerprint(self.customer(record))
        self.assertEqual(len(serialized),64)
        item=self.customer(record)['items'][0]
        self.assertTrue({'owner_hash','shipping','merchant_id','pg_token','admin_receipt'}.isdisjoint(item))

    def test_admin_projection_explicit_environment_verification_and_no_default_permission(self):
        record=self.record(); record['provider']=dict(provider_environment='unknown',verification_state='unknown',provider_checked_at=None)
        result=c.order_envelope([record],audience='admin',context=self.context,checked_at=100)['items'][0]
        self.assertEqual(result['provider_environment'],'unknown'); self.assertFalse(result['actions']['reconcile']['allowed'])
        self.assertNotIn('owner_binding_id',result)
        record['provider']['verification_state']='confirmed'
        with self.assertRaisesRegex(c.CommerceError,'provider_unconfirmed'):
            c.order_envelope([record],audience='admin',context=self.context,checked_at=100)

    def test_checked_at_is_not_provider_verified_time_and_explicit_future_time_fails(self):
        record=self.record(); record['provider']=dict(provider_environment='test',verification_state='pending',provider_checked_at=99)
        result=c.order_envelope([record],audience='admin',context=self.context,checked_at=100)['items'][0]
        self.assertEqual((result['checked_at'],result['provider_checked_at']),(100,99))
        record['provider']['provider_checked_at']=101
        with self.assertRaises(c.CommerceError): c.order_envelope([record],audience='admin',context=self.context,checked_at=100)

    def test_return_stock_has_no_automatic_permission_in_this_exact_phase(self):
        record=self.record(); record['provider']=dict(provider_environment='test',verification_state='pending',provider_checked_at=99)
        record['permissions']=self.permissions(c.ADMIN_ACTIONS,return_stock=True)
        item=c.order_envelope([record],audience='admin',context=self.context,checked_at=100)['items'][0]
        self.assertFalse(item['actions']['return_stock']['allowed'])


if __name__ == '__main__':
    unittest.main()
