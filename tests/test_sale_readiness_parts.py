"""Disconnected evidence and endpoint contracts; never import the application DB."""
import copy
import importlib.abc
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch


class NoApplicationDB(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('api.db', 'api.main'):
            raise AssertionError('application DB/main import forbidden')


guard = NoApplicationDB()
sys.meta_path.insert(0, guard)
try:
    from api import admin_sale_readiness as endpoint
    from api import sale_readiness_parts as parts
finally:
    sys.meta_path.remove(guard)


def audit(event, args):
    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen'):
        raise AssertionError('disconnected test')
sys.addaudithook(audit)


def row(**changes):
    base = dict(product_code=101, sku='CPU-101', product_name='시험 CPU', part_type='CPU',
                category_group='core_part', data_origin='real', status='판매중', stock_qty=7,
                sale_price=13000, review_required_yn=False, ai_candidate_yn=True,
                locked_fields=[], has_specs=True, in_pool=True)
    base.update(changes)
    return base


class PartsTests(unittest.TestCase):
    def test_actual_membership_and_current_stock_produce_recommendation_label(self):
        item = parts.project_part(row())
        self.assertEqual(item['state'], 'basis_met')
        self.assertEqual(item['state_label'], '추천 근거 충족')
        self.assertEqual(item['reasons'], [])
        self.assertTrue(all(c['state'] == 'met' for c in item['checks']))

    def test_all_blockers_are_reported_without_first_failure_masking(self):
        item = parts.project_part(row(has_specs=False, review_required_yn=True,
                                      ai_candidate_yn=False, sale_price=None, stock_qty=0, in_pool=False))
        self.assertEqual(item['state'], 'needs_work')
        self.assertTrue({'spec_row', 'review', 'candidate', 'price', 'stock'} <= {r['key'] for r in item['reasons']})

    def test_empty_explanation_does_not_override_actual_candidate_absence(self):
        item = parts.project_part(row(in_pool=False))
        self.assertEqual(item['state'], 'needs_check')
        self.assertEqual(next(r for r in item['reasons'] if r['key'] == 'pool_mismatch')['severity'], 'unknown')

    def test_actual_membership_conflicting_with_gate_is_not_basis_met(self):
        item = parts.project_part(row(stock_qty=0))
        self.assertEqual(item['state'], 'needs_check')
        self.assertIn('pool_mismatch', [r['key'] for r in item['reasons']])

    def test_demo_and_noncore_are_excluded_with_explicit_source_reason(self):
        for changes, key in ((dict(data_origin='demo'), 'origin'),
                             (dict(category_group='peripheral', part_type='MONITOR'), 'category')):
            with self.subTest(key=key):
                item = parts.project_part(row(in_pool=False, **changes))
                self.assertEqual(item['state'], 'excluded')
                self.assertEqual(next(r for r in item['reasons'] if r['key'] == key)['severity'], 'info')

    def test_nullable_origin_follows_distinct_from_demo_and_zero_price_adds_no_policy(self):
        self.assertEqual(parts.project_part(row(data_origin=None, sale_price=0))['state'], 'basis_met')

    def test_missing_stock_or_review_is_unknown_instead_of_ready(self):
        for key in ('stock_qty', 'review_required_yn'):
            with self.subTest(key=key):
                item = parts.project_part(row(in_pool=False, **{key: None}))
                self.assertEqual(item['state'], 'needs_check')
                self.assertIn('unknown', [c['state'] for c in item['checks']])

    def test_out_of_stock_state_does_not_predict_future_candidate_entry(self):
        item = parts.project_part(row(status='품절', stock_qty=0, in_pool=False))
        self.assertEqual(item['state'], 'needs_work')
        self.assertTrue({'status', 'stock'} <= {r['key'] for r in item['reasons']})
        self.assertNotIn('입고 시 후보 진입', str(item))

    def test_price_link_respects_actual_price_review_population(self):
        item = parts.project_part(row(sale_price=None, in_pool=False))
        self.assertEqual(next(r for r in item['reasons'] if r['key'] == 'price')['href'], parts.PRICE)
        for changes in (dict(locked_fields=['sale_price']), dict(review_required_yn=True)):
            item = parts.project_part(row(sale_price=None, in_pool=False, **changes))
            self.assertEqual(next(r for r in item['reasons'] if r['key'] == 'price')['href'], parts.PRODUCTS)

    def test_projection_has_no_contact_passthrough_and_does_not_mutate_input(self):
        raw = row(contact_phone='private', supplier_contact='private')
        original = copy.deepcopy(raw)
        item = parts.project_part(raw)
        self.assertEqual(raw, original)
        self.assertNotIn('private', str(item))
        self.assertEqual(set(item), {'id', 'name', 'code', 'state', 'state_label', 'reasons', 'checks', 'href'})

    def test_list_uses_one_bulk_query_and_canonical_view_stock_filter(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.all.return_value = [row(), row(product_code=102)]
        self.assertEqual(len(parts.list_parts(conn)), 2)
        conn.execute.assert_called_once()
        sql = str(conn.execute.call_args.args[0])
        self.assertIn('v_recommendation_candidates WHERE stock_qty > 0', sql)
        self.assertTrue(sql.lstrip().startswith('SELECT'))
        for word in ('INSERT', 'UPDATE', 'DELETE', 'COMMIT', 'contact'):
            self.assertNotIn(word, sql)
        conn.commit.assert_not_called()

    def test_detail_is_bound_single_query_and_same_projection_as_list(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.first.return_value = row()
        self.assertEqual(parts.detail_part(conn, '101'), parts.project_part(row()))
        conn.execute.assert_called_once()
        self.assertEqual(conn.execute.call_args.args[1], {'code': 101})
        self.assertIn('WHERE p.product_code = :code', str(conn.execute.call_args.args[0]))

    def test_invalid_identity_is_rejected_without_query(self):
        conn = Mock()
        for identity in ('0', '-1', '101 OR 1=1', '９', '9223372036854775808'):
            self.assertIsNone(parts.detail_part(conn, identity))
        conn.execute.assert_not_called()

    def test_missing_detail_returns_none(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.first.return_value = None
        self.assertIsNone(parts.detail_part(conn, '101'))


class APITests(unittest.TestCase):
    def test_configuration_reader_error_preserves_status_detail_and_closes_connection(self):
        cm = MagicMock()
        failure = endpoint.HTTPException(404, '구성 없음', headers={'X-Test': 'original'})
        load = Mock(side_effect=failure)
        with patch.object(endpoint, 'connection', return_value=cm), patch.object(
                endpoint, 'readers', return_value=(Mock(), load)):
            with self.assertRaises(endpoint.HTTPException) as raised:
                endpoint.sale_readiness_detail('configurations', 'missing', endpoint.Response())
        self.assertIs(raised.exception, failure)
        self.assertEqual(failure.status_code, 404)
        self.assertEqual(failure.detail, '구성 없음')
        self.assertEqual(failure.headers, {'X-Test': 'original', 'Cache-Control': 'no-store'})
        cm.__exit__.assert_called_once()

    def test_counts_cover_search_population_before_pagination(self):
        items = [parts.project_part(row(product_code=n, stock_qty=0, in_pool=False)) for n in (101, 102, 103)]
        items += [parts.project_part(row(product_code=104, product_name='다른 상품'))]
        result = endpoint.page_result('parts', items, '시험 CPU', 1, 1)
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['counts']['needs_work'], 3)
        self.assertEqual([item['id'] for item in result['items']], ['102'])

    def test_reason_search_and_empty_page_keep_full_counts(self):
        item = parts.project_part(row(has_specs=False, in_pool=False))
        result = endpoint.page_result('parts', [item], '사양 행 없음', 40, 40)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['total'], 1)
        self.assertEqual(sum(result['counts'].values()), 1)

    def test_bulk_handler_passes_single_caller_connection(self):
        conn = Mock()
        cm = MagicMock()
        cm.__enter__.return_value = conn
        load = Mock(return_value=[parts.project_part(row())])
        response = endpoint.Response()
        with patch.object(endpoint, 'connection', return_value=cm) as connect, patch.object(endpoint, 'readers', return_value=(load, Mock())):
            result = endpoint.sale_readiness(response, 'parts', '', 0, 40)
        connect.assert_called_once_with()
        load.assert_called_once_with(conn)
        self.assertEqual(result['scope'], 'parts')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        cm.__exit__.assert_called_once()
        conn.commit.assert_not_called()

    def test_detail_passes_configuration_identity_without_changing_contract(self):
        conn = Mock()
        cm = MagicMock()
        cm.__enter__.return_value = conn
        item = parts.project_part(row())
        load = Mock(return_value=item)
        response = endpoint.Response()
        with patch.object(endpoint, 'connection', return_value=cm), patch.object(endpoint, 'readers', return_value=(Mock(), load)):
            self.assertEqual(endpoint.sale_readiness_detail('configurations', 'N01', response), item)
        load.assert_called_once_with(conn, 'N01')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_missing_item_is_404(self):
        with patch.object(endpoint, 'connection', return_value=MagicMock()), patch.object(endpoint, 'readers', return_value=(Mock(), Mock(return_value=None))):
            with self.assertRaises(endpoint.HTTPException) as caught:
                endpoint.sale_readiness_detail('parts', '101', endpoint.Response())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.headers['Cache-Control'], 'no-store')

    def test_schema_has_only_GET_and_bounded_shared_query_contract(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(endpoint.router)
        paths = app.openapi()['paths']
        self.assertEqual(set(paths), {'/api/admin/sale-readiness', '/api/admin/sale-readiness/{scope}/{identity}'})
        self.assertTrue(all(set(methods) == {'get'} for methods in paths.values()))
        parameters = {p['name']: p['schema'] for p in paths['/api/admin/sale-readiness']['get']['parameters']}
        self.assertEqual(parameters['scope']['enum'], ['parts', 'configurations'])
        self.assertEqual((parameters['limit']['minimum'], parameters['limit']['maximum'], parameters['limit']['default']), (1, 100, 40))
        self.assertEqual(parameters['offset']['minimum'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
