"""Mocked internal binding reads; never import api.db/main or open a connection."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'api' / 'pc_configuration_copy.py'
HELPER = 'read_sold_offer_configuration'
BEFORE_AST = '03d9fa0973ef64dfad83f1abfbdbab02cca2bbb15e08c26494246f52847fba6d'


def functions(path, names):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])


def isolated_reader():
    # Compile the unchanged real detail/hash/freshness functions and the new helper;
    # module-level imports, routes, engine and application initialization never run.
    namespace = dict(__name__='isolated_offer_reader', __package__='api', hashlib=hashlib,
                     json=json, re=re, HTTPException=HTTPException, text=lambda sql: sql,
                     SLOT_LABELS={'CPU': 'CPU', 'COOLER': '쿨러', 'GPU': 'GPU'},
                     review_snapshot=lambda identity, parts: {'configuration_id': identity},
                     load_market=lambda conn: ({}, {}, {}), changes_for=lambda *args: [])
    exec(compile(functions(ROOT / 'api' / 'part_explanations.py', {'fingerprint', 'is_current'}), 'actual_part_freshness', 'exec'), namespace)
    exec(compile(functions(SOURCE, {'digest', 'explanation_digest', 'part_needs_review',
                                  'queue_status', 'read_configuration', HELPER}), 'actual_offer_detail', 'exec'), namespace)
    return namespace


class Rows:
    def __init__(self, values):
        self.values = copy.deepcopy(values)

    def mappings(self):
        return self

    def first(self):
        return copy.deepcopy(self.values[0]) if self.values else None

    def __iter__(self):
        return iter(copy.deepcopy(self.values))


class Connection:
    def __init__(self, namespace, product_code=99413, identity='P90678'):
        records = json.loads((ROOT / 'db/migrations/data/pc_configuration_catalog_20260928.json').read_text(encoding='utf-8'))['records']
        historical = next(r for r in records if r['id'] == 'P90678')
        self.config = dict(configuration_id=identity, revision=2, bom_fingerprint='a' * 64,
                           content_hash='b' * 64, copy_hash='c' * 64, status='approved',
                           observed_date='2026-09-28', content=dict(source=historical['source'],
                           source_ids=list(historical['source_ids']) if product_code == 99413 else [f'P{product_code}'],
                           title='Mock admin description', _review={'state': 'approved', 'basis': 'd' * 64}))
        offer_id = f'P{product_code}'
        payload = copy.deepcopy(next(o for o in historical['offers'] if o['id'] == 'P99413'))
        payload['id'] = offer_id
        self.offers = [dict(offer_id=offer_id, configuration_id=identity, price_snapshot=payload['price'], payload=payload)]
        self.bound = dict(copy.deepcopy(self.offers[0]), **{k: self.config[k] for k in ('revision', 'bom_fingerprint', 'content_hash', 'copy_hash')})
        self.rows = {}
        self.parts = []
        for ordinal, slot, source, explanation, linked in [(3, 'CPU', 'merchant-source-A', 1001, 201), (9, 'COOLER', 'assembly-source-B', 1002, None)]:
            content = dict(name='Mock ' + slot, role='Documented role', review_issues=[])
            if linked is None:
                content['availability_scope'] = 'assembly_only'
            row = dict(source_product_code=explanation, product_code=linked, content=content,
                       source_snapshot={'name': 'Mock part', 'spec': 'Documented specification'},
                       product_name='Mock part', spec_source_text='Documented specification',
                       source_fingerprint=namespace['fingerprint']('Mock part', 'Documented specification'),
                       sale_status='판매중' if linked else None, sale_price=123 if linked else None)
            self.rows[explanation] = row
            self.parts.append(dict(configuration_id=identity, ordinal=ordinal, slot=slot, source_code=source,
                                   explanation_code=explanation, quantity=2 if linked else 1, pseudo=False,
                                   selection_note='Source selection note', explanation_hash=namespace['explanation_digest'](row)))
        self.parts.append(dict(configuration_id=identity, ordinal=12, slot='GPU', source_code='integrated',
                               explanation_code=None, quantity=1, pseudo=True, selection_note='Recorded integrated component', explanation_hash=None))
        self.review = dict(configuration_id=identity, revision=2, basis='d' * 64, state='approved',
                           eligible=True, customer_publishable=False, checks=[], blockers=[],
                           recommendation_state='ready', cooling_plan={}, assembly_checks=[],
                           findings={'copy': {'evidence': 'Private review evidence'}}, approved_by={'operator_id': 1})
        self.sales_conditions = {'os': {'state': 'unknown', 'customer_statement': '포함 여부 확인 필요'}}
        self.registered = True
        self.calls = []
        self.tx_calls = []
        self.error = None
        self.error_at = None

    def execute(self, statement, params=None):
        sql = ' '.join(str(statement).split())
        self.calls.append((sql, copy.deepcopy(params)))
        if not sql.startswith('SELECT '):
            raise AssertionError('Write SQL prohibited')
        if 'FROM pc_configuration_offers o JOIN pc_configurations c' in sql:
            kind, rows = 'binding', [self.bound] if self.registered else []
        elif 'FROM pc_configurations WHERE configuration_id=' in sql:
            kind, rows = 'configuration', [self.config]
            assert params == {'id': self.bound['configuration_id']}
        elif 'FROM pc_configuration_parts WHERE configuration_id=' in sql:
            kind, rows = 'parts', self.parts
        elif 'FROM product_explanations e LEFT JOIN products p' in sql:
            kind, rows = 'explanation', [self.rows[params['code']]] if params['code'] in self.rows else []
        elif 'FROM pc_configuration_offers WHERE configuration_id=' in sql:
            kind, rows = 'offers', self.offers
        elif 'FROM pc_media_jobs WHERE configuration_id=' in sql:
            kind, rows = 'media', []
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        if self.error_at == kind:
            raise self.error
        return Rows(rows)

    def forbidden(self, name):
        self.tx_calls.append(name)
        raise AssertionError('Connection/TX control prohibited: ' + name)

    def begin(self):
        return self.forbidden('begin')

    def commit(self):
        return self.forbidden('commit')

    def rollback(self):
        return self.forbidden('rollback')

    def connect(self):
        return self.forbidden('connect')

    def __enter__(self):
        return self.forbidden('enter')


class OfferBindingTests(unittest.TestCase):
    def setUp(self):
        self.module = isolated_reader()
        self.conn = Connection(self.module)
        self.reader = Mock(wraps=self.module['read_configuration'])
        self.module['read_configuration'] = self.reader
        package = types.ModuleType('api')
        package.__path__ = []
        review = types.ModuleType('api.pc_configuration_review')
        review.load_review = Mock(side_effect=lambda c, identity: (None, None, None, copy.deepcopy(c.review)))
        media = types.ModuleType('api.pc_media')
        media.snapshot = Mock(side_effect=AssertionError('No media fixture; no image existence claim'))
        terms = types.ModuleType('api.pc_sales_conditions')
        terms.effective_conditions = lambda config, parts, offers: copy.deepcopy(self.conn.sales_conditions)
        policy = types.ModuleType('api.pc_review_policy')
        policy.issue_stages = lambda row: [{'stage': 'recommendation'} for issue in row['content']['review_issues']]
        self.dependencies = {'api': package, 'api.pc_configuration_review': review, 'api.pc_media': media,
                             'api.pc_sales_conditions': terms, 'api.pc_review_policy': policy}
        self.patch = patch.dict(sys.modules, self.dependencies)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def resolve(self, code=99413):
        return self.module[HELPER](self.conn, code)

    def rejects(self, status=409, code=99413):
        with self.assertRaises(HTTPException) as caught:
            self.resolve(code)
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(self.conn.tx_calls, [])

    def test_historical_99413_uses_90678_fk_and_real_detail_reader(self):
        value = self.resolve()
        self.reader.assert_called_once_with(self.conn, 'P90678')
        self.assertEqual((value['product_code'], value['offer_id'], value['configuration_id']), (99413, 'P99413', 'P90678'))
        self.assertEqual(value['revision'], 2)
        self.assertEqual(value['copy_hash'], self.conn.config['copy_hash'])
        sql, params = self.conn.calls[0]
        self.assertEqual(params, {'offer': 'P99413'})
        self.assertIn('c.configuration_id=o.configuration_id', sql)
        self.assertIn('WHERE o.offer_id=:offer', sql)
        self.assertNotIn('product_name', sql)
        self.assertNotIn('sale_price', sql)

    def test_normal_registered_p_offer_uses_returned_fk(self):
        self.conn = Connection(self.module, 113835, 'P113835')
        self.assertEqual(self.resolve(113835)['configuration_id'], 'P113835')
        self.reader.assert_called_once_with(self.conn, 'P113835')

    def test_native_positive_int_only_before_any_query(self):
        class IntSubclass(int):
            pass
        for code in [True, False, 0, -1, '99413', 99413.0, None, [], IntSubclass(99413)]:
            with self.subTest(code=code):
                self.rejects(422, code)
        self.assertEqual(self.conn.calls, [])
        self.reader.assert_not_called()

    def test_unregistered_or_unlinked_offer_is_404_without_fallback(self):
        self.conn.registered = False
        self.rejects(404)
        self.assertEqual(len(self.conn.calls), 1)
        self.reader.assert_not_called()

    def test_admin_or_mismatched_offer_pk_does_not_resolve(self):
        for offer in ['ADMIN-P90678', 'P90678', 'N01', None]:
            with self.subTest(offer=offer):
                self.conn.bound['offer_id'] = offer
                self.rejects()
        self.reader.assert_not_called()

    def test_quote_only_missing_or_explicit_false_is_accepted(self):
        self.resolve()
        self.conn.bound['payload']['quote_only'] = False
        self.conn.offers[0]['payload']['quote_only'] = False
        self.resolve()

    def test_quote_only_true_or_wrong_native_type_is_rejected(self):
        for value in [True, 'false', 0, 1, None, []]:
            with self.subTest(value=value):
                self.conn.bound['payload']['quote_only'] = value
                self.rejects()
        self.reader.assert_not_called()

    def test_payload_id_and_payload_object_are_required(self):
        for payload in [None, [], 'text', {}, {'id': 'ADMIN-P90678'}, {'id': 99413}]:
            with self.subTest(payload=payload):
                self.conn.bound['payload'] = payload
                self.rejects()
        self.reader.assert_not_called()

    def test_initial_fk_revision_snapshot_native_types(self):
        original = copy.deepcopy(self.conn.bound)
        for key, values in [('configuration_id', [None, '', ' ', 90678, []]), ('revision', [None, 0, True, 2.0, '2']), ('price_snapshot', [None, 0, True, 10.0, '10'])]:
            for value in values:
                with self.subTest(key=key, value=value):
                    self.conn.bound = dict(copy.deepcopy(original), **{key: value})
                    self.rejects()
        self.reader.assert_not_called()

    def test_initial_hashes_are_native_sha256_strings(self):
        original = copy.deepcopy(self.conn.bound)
        for key in ['bom_fingerprint', 'content_hash', 'copy_hash']:
            for value in [None, 123, '', 'x' * 64, 'A' * 64, 'a' * 63]:
                with self.subTest(key=key, value=value):
                    self.conn.bound = dict(copy.deepcopy(original), **{key: value})
                    self.rejects()
        self.reader.assert_not_called()

    def test_source_and_registered_source_ids_match_without_coercion(self):
        original = copy.deepcopy(self.conn.config['content'])
        for changes in [{'source': '신규'}, {'source': None}, {'source_ids': None}, {'source_ids': 'P99413'}, {'source_ids': []}, {'source_ids': ['P90678']}, {'source_ids': ['P99413', 99413]}, {'source_ids': ['P99413', '']}]:
            with self.subTest(changes=changes):
                self.conn.config['content'] = dict(copy.deepcopy(original), **changes)
                self.rejects()

    def test_observed_revision_and_hash_changes_are_409(self):
        original = copy.deepcopy(self.conn.config)
        for key, value in [('revision', 3), ('revision', 2.0), ('revision', '2'), ('bom_fingerprint', 'e' * 64), ('content_hash', 'f' * 64), ('copy_hash', '1' * 64)]:
            with self.subTest(key=key, value=value):
                self.conn.config = dict(copy.deepcopy(original), **{key: value})
                self.rejects()

    def test_observed_configuration_identity_change_is_409(self):
        self.conn.config['configuration_id'] = 'OTHER'
        self.rejects()

    def test_missing_duplicate_or_replaced_detail_offer_is_409(self):
        original = copy.deepcopy(self.conn.offers)
        for offers in [[], original + original, [dict(original[0], offer_id='ADMIN-P90678')]]:
            with self.subTest(offers=offers):
                self.conn.offers = copy.deepcopy(offers)
                self.rejects()

    def test_observed_offer_fk_price_or_payload_change_is_409(self):
        original = copy.deepcopy(self.conn.offers[0])
        for changes in [{'configuration_id': 'OTHER'}, {'price_snapshot': original['price_snapshot'] + 1}, {'price_snapshot': float(original['price_snapshot'])}, {'payload': dict(original['payload'], quote_only=True)}, {'payload': dict(original['payload'], id='P90678')}, {'payload': None}]:
            with self.subTest(changes=changes):
                self.conn.offers = [dict(copy.deepcopy(original), **changes)]
                self.rejects()

    def test_payload_false_zero_difference_cannot_hide_a_change(self):
        self.conn.bound['payload']['quote_only'] = False
        self.conn.offers[0]['payload']['quote_only'] = 0
        self.rejects()

    def test_review_identity_revision_or_basis_mismatch_is_409(self):
        original = copy.deepcopy(self.conn.review)
        for changes in [{'configuration_id': 'OTHER'}, {'revision': 3}, {'revision': 2.0}, {'basis': None}, {'basis': 'bad'}]:
            with self.subTest(changes=changes):
                self.conn.review = dict(copy.deepcopy(original), **changes)
                self.rejects()

    def test_stale_description_hash_and_partial_part_freshness_remain_private(self):
        self.conn.rows[1001]['content']['role'] = 'Changed description'
        self.conn.review.update(state='stale', eligible=False)
        value = self.resolve()
        self.assertTrue(value['detail']['needs_review'])
        self.assertEqual(value['detail']['affected_parts'], ['merchant-source-A'])
        self.assertEqual([p['needs_review'] for p in value['detail']['parts']], [True, False, False])
        self.assertEqual(value['detail']['current_review']['state'], 'stale')
        self.assertFalse(value['customer_publishable'])
        self.assertFalse(value['detail']['customer_publishable'])
        self.assertTrue(value['price_is_snapshot'])

    def test_changed_product_raw_source_and_missing_explanation_preserve_findings(self):
        self.conn.rows[1001]['spec_source_text'] = 'Changed raw specification'
        self.assertTrue(self.resolve()['detail']['parts'][0]['needs_review'])
        del self.conn.rows[1001]
        detail = self.resolve()['detail']
        self.assertTrue(detail['needs_review'])
        self.assertEqual(detail['parts'][0]['explanation'], {})
        self.assertIsNone(detail['parts'][0]['current_unit_price'])

    def test_quantity_ordinal_assembly_only_and_pseudo_are_not_fabricated_skus(self):
        value = self.resolve()
        parts = value['detail']['parts']
        self.assertEqual([(p['ordinal'], p['quantity']) for p in parts], [(3, 2), (9, 1), (12, 1)])
        self.assertEqual((parts[0]['source_code'], parts[0]['explanation_code'], self.conn.rows[1001]['product_code']), ('merchant-source-A', 1001, 201))
        self.assertIsNone(self.conn.rows[1002]['product_code'])
        self.assertIsNone(parts[1]['current_unit_price'])
        self.assertTrue(parts[2]['pseudo'])
        self.assertIsNone(parts[2]['explanation_code'])
        self.assertNotIn('current_unit_price', parts[2])
        self.assertNotIn('image_url', parts[2])
        self.assertEqual(len(parts), 3)
        self.assertEqual(value['detail']['current_review']['findings'], self.conn.review['findings'])
        self.assertNotIn('price_confirmed', value)
        self.assertNotIn('stock_available', value)
        self.assertEqual(value['detail']['sales_conditions'], self.conn.sales_conditions)

    def test_private_reader_flags_cannot_be_promoted_or_lost(self):
        for changes in [{'customer_publishable': True}, {'customer_publishable': 0}, {'price_is_snapshot': False}, {'price_is_snapshot': 1}, {'needs_review': 'false'}]:
            with self.subTest(changes=changes):
                actual = self.reader._mock_wraps
                self.module['read_configuration'] = lambda c, i: dict(actual(c, i), **changes)
                self.rejects()

    def test_db_and_detail_exceptions_propagate_without_tx_cleanup_or_fallback(self):
        for stage in ['binding', 'configuration', 'parts', 'explanation', 'offers', 'media']:
            with self.subTest(stage=stage):
                failure = RuntimeError('Mock reader failure')
                self.conn.error_at, self.conn.error = stage, failure
                with self.assertRaises(RuntimeError) as caught:
                    self.resolve()
                self.assertIs(caught.exception, failure)
                self.assertEqual(self.conn.tx_calls, [])

    def test_readonly_connection_and_original_rows_are_unchanged(self):
        before = copy.deepcopy((self.conn.bound, self.conn.config, self.conn.offers, self.conn.parts, self.conn.rows))
        self.resolve()
        self.assertEqual((self.conn.bound, self.conn.config, self.conn.offers, self.conn.parts, self.conn.rows), before)
        self.assertEqual(self.conn.tx_calls, [])
        self.assertTrue(all(sql.startswith('SELECT ') for sql, params in self.conn.calls))
        self.dependencies['api.pc_media'].snapshot.assert_not_called()

    def test_original_whole_ast_imports_routes_and_functions_are_unchanged(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == HELPER)]
        actual = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        self.assertEqual(actual, BEFORE_AST)

    def test_helper_has_no_route_import_connection_creation_or_tx_control(self):
        tree = functions(SOURCE, {HELPER})
        helper = tree.body[0]
        self.assertEqual(helper.decorator_list, [])
        for node in ast.walk(helper):
            self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom))
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {'connect', 'begin', 'commit', 'rollback', 'close'})
            if isinstance(node, ast.Name):
                self.assertNotEqual(node.id, 'engine')


if __name__ == '__main__':
    unittest.main()
