"""Exercise the projection with canonical-reader doubles; no DB-backed imports."""
import ast
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / 'api' / 'sale_readiness_configurations.py'


def load_projection(read_rows=None, read_detail=None):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'), filename=str(SOURCE))
    # Keep the whole module except these exact, DB-backed reader imports.
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.level == 1
        and node.module in ('pc_configuration_copy', 'pc_configuration_edit'))]
    namespace = {'catalog_rows': read_rows or Mock(), 'read_configuration': read_detail or Mock(),
                 'description_complete': Mock(return_value=True)}
    exec(compile(tree, str(SOURCE), 'exec'), namespace)
    return namespace


def row(**changes):
    value = dict(configuration_id='N07', title='문서용 PC', status='approved',
                 management_state='ready', part_count=2, affected_parts=[],
                 description_ready=True, market_alerts=[], review_state='approved',
                 review_reasons=[], needs_review=False, customer_publishable=False,
                 price_is_snapshot=True, price=500000)
    value.update(changes)
    return value


def detail(**changes):
    value = row()
    value.update(content={'title': '문서용 PC', 'intro': 'private untouched content'},
                 parts=[dict(pseudo=False, explanation={'role': '프로그램 실행'})],
                 current_review=dict(state='approved', eligible=True, blockers=[], checks=[],
                                     approved_by={'operator_id': 123, 'name': 'private operator'},
                                     findings={'copy': {'evidence': 'private evidence'}}, note='private note'),
                 sales_conditions={key: dict(state='verified' if key == 'warranty' else 'excluded',
                    stale=False, customer_statement='보증·AS 기간은 12개월입니다.' if key == 'warranty'
                    else label + '는 미포함입니다.', source='private source', evidence='private evidence',
                    previous={'operator_id': 123}, operator_id=123, confirmed_at='private time')
                    for key, label in {'os':'운영체제','keyboard':'키보드','mouse':'마우스',
                                       'monitor':'모니터','warranty':'보증·AS'}.items()})
    value.update(changes)
    return value


class ReadinessTests(unittest.TestCase):
    def checks(self, item):
        return {check['key']: check for check in item['checks']}

    def test_bulk_once_no_per_item_detail_and_no_mutation(self):
        rows = [row(configuration_id='N' + str(i)) for i in range(104)]
        before = copy.deepcopy(rows)
        reader, selected = Mock(return_value=rows), Mock(side_effect=AssertionError('N+1'))
        module = load_projection(reader, selected)
        conn = object()
        items = module['list_configurations'](conn)
        reader.assert_called_once_with(conn)
        selected.assert_not_called()
        self.assertEqual(len(items), 104)
        self.assertEqual(rows, before)

    def test_detail_once_reuses_description_rule_and_does_not_mutate_source(self):
        data = detail()
        before = copy.deepcopy(data)
        reader, bulk = Mock(return_value=data), Mock(side_effect=AssertionError('bulk fallback'))
        module = load_projection(bulk, reader)
        conn = object()
        item = module['detail_configuration'](conn, 'N07')
        reader.assert_called_once_with(conn, 'N07')
        bulk.assert_not_called()
        module['description_complete'].assert_called_once_with(data['content'])
        self.assertEqual(data, before)
        self.assertEqual(self.checks(item)['description']['state'], 'met')

    def test_no_alerts_or_approved_review_never_confirm_price_stock_publication(self):
        item = load_projection()['_project'](row())
        self.assertEqual(item['state'], 'needs_check')
        for key in ('price', 'stock', 'publication', 'assembly', 'sales_conditions'):
            self.assertEqual(self.checks(item)[key]['state'], 'unknown')
        self.assertEqual(self.checks(item)['review']['state'], 'met')
        self.assertNotIn('판매 가능', item['state_label'])

    def test_all_confirmed_terms_still_leave_actual_sale_unknown(self):
        module = load_projection(read_detail=Mock(return_value=detail()))
        item = module['detail_configuration'](object(), 'N07')
        self.assertEqual(item['state'], 'needs_check')
        for key in module['SALES_LABELS']:
            self.assertEqual(self.checks(item)['sales:' + key]['state'], 'met')
        self.assertEqual(self.checks(item)['stock']['state'], 'unknown')

    def test_missing_list_terms_not_inferred_from_facts_or_copy(self):
        item = load_projection()['_project'](row(content={'intro': '운영체제 포함'},
                                               facts={'os_included': True},
                                               sales_conditions={'os': {'state': 'included'}}))
        self.assertEqual(self.checks(item)['sales_conditions']['state'], 'unknown')
        self.assertFalse(any(c['key'].startswith('sales:') for c in item['checks']))

    def test_each_unknown_and_stale_condition_is_preserved_without_prior_assertion(self):
        data = detail()
        data['sales_conditions']['os'] = dict(state='unknown', stale=True,
                                              previous={'detail': 'Windows private previous'})
        data['sales_conditions'].pop('mouse')
        item = load_projection(read_detail=Mock(return_value=data))['detail_configuration'](object(), 'N07')
        self.assertEqual(self.checks(item)['sales:os']['state'], 'unknown')
        self.assertEqual(self.checks(item)['sales:mouse']['state'], 'unknown')
        self.assertIn('재확인', next(r['label'] for r in item['reasons'] if r['key'] == 'sales:os'))
        self.assertNotIn('Windows', json.dumps(item, ensure_ascii=False))

    def test_retired_and_actual_excluded_dominate_other_work(self):
        for changes in ({'status': 'retired'}, {'management_state': 'excluded'}):
            with self.subTest(changes=changes):
                item = load_projection()['_project'](row(description_ready=False, **changes))
                self.assertEqual(item['state'], 'excluded')

    def test_hold_pending_stale_and_revoked_keep_source_review_state(self):
        for state in ('pending', 'stale', 'revoked'):
            data = detail(current_review=dict(state=state, eligible=False, blockers=[], checks=[]))
            item = load_projection(read_detail=Mock(return_value=data))['detail_configuration'](object(), 'N07')
            self.assertEqual(item['state'], 'excluded' if state == 'revoked' else 'needs_work')
        item = load_projection()['_project'](row(management_state='hold', review_state=None))
        self.assertEqual(item['state'], 'needs_work')

    def test_recommendation_candidate_is_not_approval(self):
        item = load_projection()['_project'](row(management_state='ready', review_state=None))
        self.assertEqual(self.checks(item)['review']['state'], 'unknown')
        self.assertEqual(item['state'], 'needs_check')

    def test_description_and_all_market_warnings_survive_priority(self):
        item = load_projection()['_project'](row(description_ready=False,
            market_alerts=[dict(kind='price', label='현재 합계와 기준가 차이'),
                           dict(kind='sale', label='연결 부품 판매중 아님')],
            review_reasons=['CPU 사양 확인 필요']))
        self.assertEqual(item['state'], 'needs_work')
        keys = {r['key'] for r in item['reasons']}
        self.assertTrue({'description', 'market:0', 'market:1', 'review:source:0'} <= keys)

    def test_detail_distinguishes_blockers_recommendation_unknown_and_assembly(self):
        data = detail(current_review=dict(state='pending', eligible=False,
            blockers=['CPU 소켓 · 현재 DB 사양 불일치'], checks=[
                dict(state='unknown', stage='recommendation', label='필수 사양', detail='RAM 규격 없음'),
                dict(state='unknown', stage='assembly', label='실장착', detail='고객별 조립 확인')]))
        item = load_projection(read_detail=Mock(return_value=data))['detail_configuration'](object(), 'N07')
        reasons = {r['key']: r for r in item['reasons']}
        self.assertEqual(reasons['review:blocker:0']['severity'], 'blocker')
        self.assertEqual(reasons['review:unknown:0']['severity'], 'unknown')
        self.assertNotIn('review:unknown:1', reasons)
        self.assertEqual(self.checks(item)['assembly']['state'], 'unknown')

    def test_detail_preserves_each_rule_and_distinct_assembly_check_without_pii(self):
        rule = dict(key='socket', state='pass', stage='recommendation', label='CPU 소켓', detail='AM5 / AM5')
        assembly = dict(key='slot_count', state='unknown', stage='assembly',
                        label='RAM 장착 수량', detail='판매 패키지와 실제 슬롯 확인')
        data = detail(current_review=dict(state='approved', eligible=True, blockers=[],
            checks=[rule, assembly], assembly_checks=[assembly, dict(key='boot', state='unknown',
                label='실제 부팅', detail='인식 확인 예정', evidence='private operator evidence')]))
        item = load_projection(read_detail=Mock(return_value=data))['detail_configuration'](object(), 'N07')
        checks = self.checks(item)
        self.assertEqual(checks['review:check:0'], dict(key='review:check:0', label='CPU 소켓',
                                                     state='met', detail='AM5 / AM5'))
        self.assertEqual(sum(c['label'] == 'RAM 장착 수량' for c in item['checks']), 1)
        self.assertEqual(checks['assembly:check:1']['state'], 'unknown')
        self.assertNotIn('private', json.dumps(item))

    def test_rule_failure_keeps_original_blocker_and_does_not_become_unknown(self):
        data = detail(current_review=dict(state='pending', eligible=False,
            blockers=['CPU 소켓 불일치'], checks=[dict(key='socket', state='fail',
                stage='recommendation', label='CPU 소켓', detail='AM5 / LGA1700')]))
        item = load_projection(read_detail=Mock(return_value=data))['detail_configuration'](object(), 'N07')
        self.assertEqual(self.checks(item)['review:check:0']['state'], 'blocked')
        self.assertEqual(item['state'], 'needs_work')

    def test_part_source_changes_are_not_invented_retail_stock_or_assembly_blockers(self):
        item = load_projection()['_project'](row(affected_parts=['ASSEMBLY-ONLY']))
        self.assertEqual(self.checks(item)['parts']['state'], 'unknown')
        self.assertEqual(next(r['severity'] for r in item['reasons'] if r['key'] == 'parts'), 'unknown')
        self.assertEqual(item['state'], 'needs_check')

    def test_pseudo_only_or_missing_role_cannot_complete_description(self):
        for parts in ([dict(pseudo=True)], [dict(pseudo=False, explanation={})]):
            with self.subTest(parts=parts):
                module = load_projection(read_detail=Mock(return_value=detail(parts=parts)))
                item = module['detail_configuration'](object(), 'N07')
                self.assertEqual(item['state'], 'needs_work')
        module = load_projection(read_detail=Mock(return_value=detail()))
        module['description_complete'].return_value = False
        item = module['detail_configuration'](object(), 'N07')
        self.assertEqual(self.checks(item)['description']['state'], 'blocked')

    def test_reader_404_propagates_without_fallback_or_other_reads(self):
        error = LookupError('existing reader 404 stand-in')
        module = load_projection(read_detail=Mock(side_effect=error))
        with self.assertRaises(LookupError) as caught:
            module['detail_configuration'](object(), 'absent')
        self.assertIs(caught.exception, error)
        module['catalog_rows'].assert_not_called()

    def test_exact_item_allowlist_and_no_operator_evidence_or_prior_content(self):
        item = load_projection(read_detail=Mock(return_value=detail()))['detail_configuration'](object(), 'N07')
        self.assertEqual(set(item), {'id', 'name', 'code', 'state', 'state_label', 'reasons', 'checks', 'href'})
        for reason in item['reasons']:
            self.assertEqual(set(reason), {'key', 'label', 'detail', 'href', 'severity'})
            self.assertIn(reason['severity'], ('blocker', 'unknown', 'info'))
        for check in item['checks']:
            self.assertEqual(set(check), {'key', 'label', 'state', 'detail'})
            self.assertIn(check['state'], ('met', 'blocked', 'unknown', 'na'))
        rendered = json.dumps(item, ensure_ascii=False)
        for private in ('private', 'operator_id', 'approved_by', 'findings', 'previous', 'confirmed_at'):
            self.assertNotIn(private, rendered)

    def test_identity_encoded_as_single_query_value_and_no_unimplemented_tab(self):
        identity = '한글/&?id=else#tag'
        item = load_projection()['_project'](row(configuration_id=identity))
        self.assertEqual(item['id'], identity)
        self.assertEqual(item['href'], '/admin2/pc-workspace?id=%ED%95%9C%EA%B8%80%2F%26%3Fid%3Delse%23tag')
        self.assertTrue(all(r['href'] == item['href'] for r in item['reasons']))
        self.assertNotIn('tab=', item['href'])


if __name__ == '__main__':
    unittest.main()
