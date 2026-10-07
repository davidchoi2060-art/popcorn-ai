"""Owned-detail ASGI using existing writer fixtures and actual proof/projection code.

No new sale/payment success DTOs or verification bypass. SQL calls are simulated,
so this does not prove native parser, MVCC, authentication or operating COMMIT.
"""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

# Installs DB/import/network protection before loading this router and writer.
from tests import test_commerce_owner_contexts as isolated
from tests import test_commerce_writer as stored_fixtures
from tests.test_commerce_owner import TOKEN, OTHER, policy
from api import commerce_contract as c
from api import commerce_owner as owner

routes = importlib.import_module('api.commerce_orders')
ORDER = 'fixture-order'  # Existing WriterTests.draft/prepared/paid identity.
PATH = '/api/commerce/orders/' + ORDER


class ReadBridge:
    """Add auth/scope reads to the existing caller-connection call simulator."""
    def __init__(self, stored):
        self.stored, self.trace = stored, []
        self.fail_tag = None
        self.now = 150

    def in_transaction(self): return self.stored.in_transaction()
    def in_nested_transaction(self): return self.stored.in_nested_transaction()
    def get_execution_options(self): return self.stored.get_execution_options()
    def rollback(self):
        self.trace.append('rollback')
        self.stored.rollback_simulation()
    def commit(self): raise AssertionError('GET attempted COMMIT')

    def execute(self, statement, params):
        sql = str(statement)
        auth_tag = re.search(r'/\*commerce_owner:(\w+)\*/', sql)
        if auth_tag:
            tag = auth_tag[1]
            self.trace.append('owner_' + tag)
            if tag == self.fail_tag: raise RuntimeError('fixture-private-auth-sql')
            if tag == 'ready': return stored_fixtures.Result()
            if tag == 'clock': return stored_fixtures.Result(scalar=self.now)
            if tag == 'lookup':
                if params['credential_hash'] != owner.credential_digest(TOKEN):
                    return stored_fixtures.Result()
                context = deepcopy(self.stored.context)
                context.update(credential_hash=owner.credential_digest(TOKEN), created_at=0)
                return stored_fixtures.Result([context])
            raise AssertionError('GET attempted owner issuance')
        if '/*commerce_http:scope_probe*/' in sql:
            self.trace.append('scope_probe')
            if self.fail_tag == 'scope_probe': raise RuntimeError('fixture-private-scope-sql')
            value = self.stored.order(params['order_no'])
            match = value is not None and (
                value['context_id'] == params['context_id']
                and value['owner_scope'] == params['owner_scope']
                and value['owner_identity'] == json.loads(params['identity']))
            return stored_fixtures.Result([{'allowed':1}] if match else [])
        return self.stored.execute(statement, params)


class ReadEngine:
    def __init__(self, bridge): self.bridge, self.trace = bridge, []
    def connect(self): return self
    def __enter__(self):
        self.trace.append('connect'); return self.bridge
    def __exit__(self, *args): self.trace.append('close')
    def begin(self): raise AssertionError('GET attempted write transaction')


class DetailHttpTests(unittest.TestCase):
    def setUp(self):
        # Reuse accepted source fixtures, including real writer/core transitions.
        self.fixture = stored_fixtures.WriterTests()
        self.fixture.setUp(); self.fixture.paid()
        self.stored = self.fixture.conn
        self.stored.trace.clear()
        self.bridge = ReadBridge(self.stored)
        self.engine = ReadEngine(self.bridge)
        self.before = deepcopy(self.stored.data)
        self.app = isolated.FastAPI()
        self.app.include_router(routes.router)
        self.app.middleware('http')(isolated.auth.member_middleware)
        self.client = isolated.TestClient(self.app, base_url=isolated.ORIGIN, follow_redirects=False)
        self.addCleanup(self.client.close)
        for name, value in [('get_policy', policy()), ('get_engine', self.engine)]:
            p = patch.object(routes.owner_http, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(isolated.auth, 'resolve_session', return_value={'member_id':11})
        self.resolver = p.start(); self.addCleanup(p.stop)

    def get(self, path=PATH, token=TOKEN, binding=stored_fixtures.CONTEXT, query=None):
        headers = {'Cookie':'popcorn_member_session=dev-only-cookie'}
        if token is not None: headers['Cookie'] += '; '+owner.COOKIE+'='+token
        query = {'expected_binding_id':binding} if query is None else query
        return self.client.get(path, params=query, headers=headers)

    def response(self, response, status=200):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')
        self.assertNotIn('set-cookie', response.headers)
        for value in [TOKEN, owner.credential_digest(TOKEN), 'fixture-private', 'dev-only-cookie']:
            self.assertNotIn(value, response.text)
        self.resolver.assert_not_called()
        if self.engine.trace:
            self.assertEqual(self.engine.trace[-1], 'close')
            self.assertEqual(self.bridge.trace[-1], 'rollback')
        return response.json()

    def no_finance(self):
        self.assertFalse(any(tag in ('order_bundle','balance','committed_approval','txid')
                             for tag, _, _ in self.stored.trace))

    def test_stored_paid_detail_uses_actual_reader_and_projection_without_enabling_actions(self):
        with patch.object(routes.writer, 'read_committed_order', wraps=routes.writer.read_committed_order) as read:
            with patch.object(routes.c, 'order_envelope', wraps=routes.c.order_envelope) as project:
                data = self.response(self.get())
        read.assert_called_once(); project.assert_called_once()
        self.assertEqual(set(data), {'commerce_version','checked_at','context','item'})
        self.assertEqual(data['context'], {'state':'confirmed','binding_id':stored_fixtures.CONTEXT})
        item = data['item']
        self.assertEqual(item['payment_state'], 'confirmed')
        self.assertEqual(item['order_no'], ORDER)
        self.assertEqual(item['approved_amount'], str(self.before['payments'][0]['amount']))
        self.assertEqual(item['basis_state'], 'unconfirmed')
        self.assertIsNone(item['basis_id'])
        self.assertEqual(set(item['actions']), set(c.CUSTOMER_ACTIONS))
        self.assertTrue(all(x=={'allowed':False,'reason':'route_unavailable','expected_basis':None}
                            for x in item['actions'].values()))
        self.assertEqual(self.stored.data, self.before)
        tags = [x[0] for x in self.stored.trace]
        self.assertEqual(tags.count('order_bundle'), 1)
        self.assertNotIn('balance', tags)
        self.assertNotIn('committed_approval', tags)

    def test_scope_probe_sql_binds_full_server_identity_before_financial_reader(self):
        with patch.object(self.bridge, 'execute', wraps=self.bridge.execute) as execute:
            self.response(self.get())
        calls = execute.call_args_list
        probe_index = next(i for i,x in enumerate(calls) if 'commerce_http:scope_probe' in str(x.args[0]))
        finance_index = next(i for i,x in enumerate(calls) if 'commerce:order_bundle' in str(x.args[0]))
        self.assertLess(probe_index, finance_index)
        sql, params = calls[probe_index].args
        for predicate in ['o.order_no=:order_no','d.context_id=CAST(:context_id AS uuid)',
                          'd.owner_scope=:owner_scope','d.owner_identity=CAST(:identity AS jsonb)']:
            self.assertIn(predicate, str(sql))
        self.assertEqual(params['owner_scope'], self.stored.context['owner_scope'])
        self.assertEqual(json.loads(params['identity']), self.stored.context['owner_identity'])
        self.assertNotIn(TOKEN, json.dumps(params))

    def test_foreign_and_absent_orders_have_identical_404_and_no_financial_probe(self):
        missing = self.response(self.get(path='/api/commerce/orders/missing-order'), 404)
        details = self.stored.data['details'][1]
        foreign = details['owner_identity'] | {'user_id':12}
        details.update(owner_identity=foreign, owner_scope=c.fingerprint(foreign))
        response = self.response(self.get(), 404)
        self.assertEqual(response, missing)
        self.no_finance()

    def test_each_context_scope_identity_filter_prevents_financial_probe(self):
        for field, value in [('context_id', OTHER), ('owner_scope','0'*64),
                             ('owner_identity', self.stored.context['owner_identity'] | {'user_id':12})]:
            self.stored.data = deepcopy(self.before)
            self.stored.data['details'][1][field] = value
            self.stored.trace.clear()
            self.response(self.get(), 404); self.no_finance()

    def test_invalid_duplicate_extra_or_missing_query_rejected_before_engine(self):
        for query in [{}, {'expected_binding_id':'raw-private-value'},
                      [('expected_binding_id',stored_fixtures.CONTEXT),('expected_binding_id',stored_fixtures.CONTEXT)],
                      {'expected_binding_id':stored_fixtures.CONTEXT,'k':TOKEN},
                      {'expected_binding_id':stored_fixtures.CONTEXT,'user_id':'11'},
                      {'expected_binding_id':stored_fixtures.CONTEXT,'expected_context':OTHER}]:
            data = self.response(self.get(query=query), 422)
            self.assertNotIn('raw-private-value', json.dumps(data))
        self.assertEqual(self.engine.trace, [])
        self.no_finance()

    def test_order_no_is_single_bounded_ascii_identifier_and_errors_are_redacted(self):
        for number in ['a'*21, 'private!', 'bad value', '한글', '_bad', '-bad']:
            response = self.get(path='/api/commerce/orders/'+number)
            self.response(response, 422)
            self.assertNotIn(number, response.text)
        self.assertEqual(self.engine.trace, [])

    def test_cookie_loss_wrong_key_revocation_and_expiry_close_before_scope(self):
        for token in [None, '', 'B'*43]:
            self.response(self.get(token=token), 401)
        self.stored.context['revoked_at'] = 140
        self.response(self.get(), 401)
        self.stored.context['revoked_at'] = None
        self.stored.context['expires_at'] = self.bridge.now
        self.response(self.get(), 401)
        self.assertNotIn('scope_probe', self.bridge.trace)
        self.no_finance()

    def test_binding_drift_is_409_without_order_data_or_financial_probe(self):
        data = self.response(self.get(binding=OTHER), 409)
        self.assertEqual(data, {'detail':{'code':'owner_context_changed'}})
        self.assertNotIn('scope_probe', self.bridge.trace)
        self.no_finance()

    def test_dev_member_or_visitor_keys_cannot_promote_identity(self):
        response = self.client.get(PATH, params={'expected_binding_id':stored_fixtures.CONTEXT},
            headers={'Cookie':'popcorn_member_session='+TOKEN+'; pc_vid='+TOKEN,'X-Access-Key':TOKEN})
        self.response(response, 401)
        self.no_finance()

    def test_configuration_or_http_transport_blocks_before_lazy_engine(self):
        with patch.object(routes.owner_http, 'get_policy', side_effect=owner.OwnerError(503,'owner_configuration_unready')):
            self.response(self.get(),503)
        self.response(self.client.get('http://shop.example'+PATH,
                      params={'expected_binding_id':stored_fixtures.CONTEXT}),503)
        self.assertEqual(self.engine.trace, [])
        self.no_finance()

    def test_owner_schema_lookup_and_order_schema_failure_are_503_no_empty_success(self):
        for tag in ['ready','lookup','scope_probe']:
            self.bridge.fail_tag = tag
            data = self.response(self.get(), 503)
            self.assertNotIn('item', data)
        self.no_finance()

    def test_real_reader_sql_failure_rolls_back_and_does_not_expose_sql_parameters(self):
        self.stored.fail_tag = 'order_bundle'
        self.response(self.get(),503)
        self.assertFalse(self.stored.aborted)
        self.assertEqual(self.stored.data,self.before)

    def test_real_provider_verification_failure_cannot_return_paid_projection(self):
        operation = next(iter(self.stored.data['operations'].values()))
        operation['verification']['evidence_basis'] = '0'*64
        data = self.response(self.get(),503)
        self.assertNotIn('item', data)
        self.assertIn('order_bundle', [x[0] for x in self.stored.trace])

    def test_real_duplicate_approval_proof_is_not_silently_chosen(self):
        payment = deepcopy(self.stored.data['payments'][0])
        payment['payment_id'] += 1
        self.stored.data['payments'].append(payment)
        self.response(self.get(),503)
        self.assertFalse(self.stored.aborted)

    def test_same_transaction_stored_order_is_rejected_by_original_reader(self):
        self.stored.data['details'][1]['write_txid'] = self.stored.txid
        self.response(self.get(),503)
        self.assertFalse(self.stored.aborted)

    def test_owner_recheck_after_preflight_is_not_bypassed(self):
        original = self.bridge.execute
        def revoke(statement, params):
            result = original(statement, params)
            if 'commerce_http:scope_probe' in str(statement): self.stored.context['revoked_at'] = 140
            return result
        with patch.object(self.bridge, 'execute', side_effect=revoke): self.response(self.get(),401)

    def test_public_projection_omits_internal_proof_provider_identity_and_shipping(self):
        data = self.response(self.get())
        serialized = json.dumps(data)
        for key in ['committed_payment','payment_id','operation_id','request_basis','provider_binding',
                    'owner_scope','owner_identity','credential_hash','write_txid','shipping']:
            self.assertNotIn(key, serialized)
        for secret in ['fixture recipient','fixture phone','fixture address']:
            self.assertNotIn(secret, serialized)

    def test_success_has_no_domain_write_commit_cookie_or_write_lock(self):
        self.response(self.get())
        allowed = {'txid','order_bundle','context'}
        self.assertTrue({x[0] for x in self.stored.trace}.issubset(allowed))
        self.assertEqual(self.stored.data,self.before)
        self.assertEqual(self.engine.trace,['connect','close'])
        self.assertEqual(self.bridge.trace.count('rollback'),1)

    def test_new_module_registers_only_detail_get_and_does_not_modify_frozen_helpers(self):
        self.assertEqual([(x.path,x.methods) for x in routes.router.routes],
                         [('/api/commerce/orders/{order_no}',{'GET'})])
        source = Path(routes.__file__).read_text(encoding='utf-8')
        self.assertNotIn('create_draft(',source)
        self.assertNotIn('set_cookie(',source)
        self.assertNotIn('.commit(',source)


if __name__ == '__main__': unittest.main()
