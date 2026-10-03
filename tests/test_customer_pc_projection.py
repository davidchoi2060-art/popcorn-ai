"""Isolated proposed public contract; no routes, DB, network or actual permissions."""
import copy
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from api.customer_pc_projection import project_configuration


def isolated_sales_functions():
    """Execute existing pure sales code with its digest dependency injected.

    DB/router/auth imports are deliberately not executed. The only edited AST
    node is scope_basis's import of the DB-backed copy module, replaced by the
    exact existing digest function below. No sales validation logic is replaced.
    """
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'api/pc_sales_conditions.py').read_text(encoding='utf-8'))
    names = {'Condition', 'SalesEdit', 'scope_basis', 'customer_statement',
             'effective_conditions', 'customer_conditions'}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in ('datetime', 'typing', 'pydantic'):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'LABELS' for t in node.targets):
            nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            if node.name == 'scope_basis':
                node.body = [n for n in node.body if not isinstance(n, ast.ImportFrom)]
            nodes.append(node)
    copy_tree = ast.parse((root / 'api/pc_configuration_copy.py').read_text(encoding='utf-8'))
    digest = next(n for n in copy_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'digest')
    namespace = {'__name__': 'isolated_sales', '__package__': 'api', 'hashlib': hashlib, 'json': json}
    module = ast.fix_missing_locations(ast.Module(body=[digest] + nodes, type_ignores=[]))
    exec(compile(module, 'existing_sales_pure_functions', 'exec'), namespace)
    return namespace


class CustomerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.basis = 'a' * 64
        self.binding = dict(configuration_id='N-DEMO', revision=3, basis=self.basis)
        self.config = dict(configuration_id='N-DEMO', revision=3, status='approved',
                           content={'_review': {'state': 'approved', 'basis': self.basis},
                                    'internal': 'PRIVATE_SENTINEL'})
        self.review = dict(self.binding, state='approved', eligible=True, customer_publishable=True)
        self.publication = dict(self.binding, allowed=True)
        self.parts = [dict(configuration_id='N-DEMO', ordinal=i, slot=slot, quantity=qty,
                           pseudo=pseudo, source_code='PRIVATE_SENTINEL', explanation_hash=self.basis)
                      for i, slot, qty, pseudo in [(1, 'GPU', 1, False), (2, 'SSD', 2, False),
                                                  (3, 'SSD', 1, False), (4, 'GPU', 1, True)]]
        self.details = dict(self.binding, offer_id='ADMIN-DEMO',
                            description={'title': '구성 예시', 'intro': '소개', 'scene': '사용 예시',
                                         'benefits': [('용량', '게임 저장 공간')], 'checks': ['실조립 확인 전'],
                                         'faq': [{'question': '보증?', 'answer': '조건 확인 필요'}]},
                            parts=[{'ordinal': p['ordinal'], 'name': '부품 예시', 'description': '역할',
                                    'specs': [{'label': '용량', 'value': '1TB'}]} for p in self.parts],
                            price={'state': 'confirmed', 'amount': 1490000,
                                   'checked_at': '2026-10-03T06:00:00Z', 'model': 'bundle'},
                            stock={'state': 'available', 'checked_at': '2026-10-03T06:00:00Z'},
                            compatibility={'document_state': 'pass', 'public_summary': '문서 조건 확인',
                                           'assembly_state': 'verified'})
        self.terms = dict(self.binding, values={
            'os': dict(state='included', detail='Windows 예시', months=None,
                       needs_reconfirmation=False, customer_statement='운영체제는 포함됩니다.'),
            'warranty': dict(state='verified', detail='판매자 조립작업 12개월; 부품별 범위 별도 확인',
                             months=12, needs_reconfirmation=False,
                             customer_statement='보증·AS 기간은 12개월입니다.')})

    def project(self):
        return project_configuration(self.config, self.parts, self.review,
                                     publication=self.publication, details=self.details, terms=self.terms)

    def test_default_is_closed_including_existing_source_false(self):
        self.assertEqual(project_configuration(self.config, self.parts, self.review),
                         {'status': 404, 'error': 'not_public'})
        self.review['customer_publishable'] = False
        self.assertEqual(self.project(), {'status': 404, 'error': 'not_public'})

    def test_every_missing_or_false_gate_returns_same_private_result(self):
        cases = [(self.config, 'status', value) for value in (None, 'retired', 'draft', 'review_required')]
        cases += [(self.review, 'state', value) for value in (None, 'pending', 'stale', 'revoked')]
        for target, key in [(self.review, 'eligible'), (self.review, 'customer_publishable'),
                            (self.publication, 'allowed')]:
            cases += [(target, key, value) for value in (None, False, 1, 'true')]
        for target, key, value in cases:
            before = copy.deepcopy(target)
            with self.subTest(key=key, value=value):
                target[key] = value
                self.assertEqual(self.project(), {'status': 404, 'error': 'not_public'})
            target.clear(); target.update(before)
        for target, key in [(self.review, 'eligible'), (self.review, 'state'),
                            (self.review, 'customer_publishable'), (self.publication, 'allowed')]:
            before = target.pop(key)
            self.assertEqual(self.project()['status'], 404)
            target[key] = before

    def test_legacy_review_fallback_does_not_open(self):
        self.config['content'] = {'_admin_bom_edit': {'review_required': False}}
        self.assertEqual(self.project()['status'], 404)

    def test_saved_basis_or_explicit_saved_approval_required(self):
        for saved in ({}, {'basis': self.basis}, {'state': 'approved'},
                      {'state': 'approved', 'basis': 'b' * 64},
                      {'state': 'revoked', 'basis': self.basis}):
            self.config['content']['_review'] = saved
            self.assertEqual(self.project()['status'], 404)

    def test_all_envelopes_bound_to_exact_identity_revision_and_basis(self):
        for target in (self.review, self.publication, self.details, self.terms):
            for key, value in [('configuration_id', 'OTHER'), ('revision', 4), ('revision', True),
                               ('revision', '3'), ('basis', 'b' * 64), ('basis', ''), ('basis', None)]:
                with self.subTest(key=key, value=value):
                    before = target[key]; target[key] = value
                    self.assertEqual(self.project()['status'], 404)
                    target[key] = before

    def test_quantity_multiple_ssds_and_pseudo_gpu_preserved_by_ordinal(self):
        self.parts.reverse(); self.details['parts'].reverse()
        data = self.project()['data']
        self.assertEqual([(p['ordinal'], p['slot'], p['quantity'], p['pseudo']) for p in data['parts']],
                         [(1, 'GPU', 1, False), (2, 'SSD', 2, False), (3, 'SSD', 1, False),
                          (4, 'GPU', 1, True)])
        self.assertNotIn('total_storage_gb', data)
        self.assertNotIn('line_id', data['parts'][0])

    def test_invalid_or_ambiguous_part_structure_denies_instead_of_silently_dropping(self):
        original = copy.deepcopy(self.parts)
        for key, value in [('quantity', 0), ('quantity', True), ('quantity', '2'),
                           ('ordinal', None), ('configuration_id', 'OTHER'), ('pseudo', 'false')]:
            self.parts = copy.deepcopy(original); self.parts[0][key] = value
            self.assertEqual(self.project()['status'], 404)
        self.parts = copy.deepcopy(original); self.parts.append(copy.deepcopy(self.parts[0]))
        self.assertEqual(self.project()['status'], 404)
        self.parts = original; self.details['parts'].pop()
        self.assertEqual(self.project()['status'], 404)

    def test_private_fields_stripped_recursively_at_every_allowed_container(self):
        private = {'source': 'PRIVATE_SENTINEL', 'evidence': 'PRIVATE_SENTINEL',
                   'previous': {'operator': 'PRIVATE_SENTINEL'}, 'content': {'access_key': 'PRIVATE_SENTINEL'}}
        self.config.update({k: v for k, v in private.items() if k != 'content'})
        self.config['content'].update(private)
        for target in (self.review, self.publication, self.details, self.terms,
                       self.details['description'], self.details['description']['faq'][0],
                       self.details['price'], self.details['stock'], self.details['compatibility'],
                       self.terms['values']['os'], self.terms['values']['warranty']):
            target.update(copy.deepcopy(private))
        for target in self.parts + self.details['parts'] + self.details['parts'][0]['specs']:
            target.update(copy.deepcopy(private))
        self.details['description']['benefits'].append(['PRIVATE_SENTINEL', {'source': 'PRIVATE_SENTINEL'}])
        self.details['description']['checks'].append({'source': 'PRIVATE_SENTINEL'})
        self.details['parts'][0]['specs'].append({'label': 'bad', 'value': {'source': 'PRIVATE_SENTINEL'}})
        result = self.project()
        self.assertEqual(result['status'], 200)
        encoded = json.dumps(result)
        for value in ('PRIVATE_SENTINEL', self.basis, 'access_key', 'source_code', 'explanation_hash',
                      'recommendation_policy', 'approved_by', 'previous', 'content', 'evidence'):
            self.assertNotIn(value, encoded)

    def test_unknown_and_stale_terms_hide_prior_claims_and_keep_all_five_keys(self):
        for state, stale in [('unknown', False), ('included', True)]:
            self.terms['values']['os'].update(state=state, needs_reconfirmation=stale,
                                            detail='PRIVATE_SENTINEL', customer_statement='PRIVATE_SENTINEL')
            result = self.project()['data']['customer_conditions']
            self.assertEqual(set(result), {'os', 'keyboard', 'mouse', 'monitor', 'warranty'})
            self.assertEqual(result['os']['state'], 'unknown')
            self.assertEqual(result['os']['detail'], '')
            self.assertIsNone(result['os']['months'])
            self.assertEqual(result['os']['needs_reconfirmation'], stale)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.terms['values']['warranty'].update(needs_reconfirmation=True)
        result = self.project()['data']['customer_conditions']['warranty']
        self.assertEqual(result['state'], 'unknown'); self.assertIsNone(result['months'])
        self.assertEqual(result['detail'], ''); self.assertTrue(result['needs_reconfirmation'])

    def test_verified_warranty_preserves_scope_period_and_statement(self):
        value = self.project()['data']['customer_conditions']['warranty']
        self.assertEqual(value, self.terms['values']['warranty'])

    def test_existing_sales_converter_boundary_and_changed_scope(self):
        sales = isolated_sales_functions()
        offers = [{'offer_id': 'ADMIN-DEMO', 'price_snapshot': 1490000, 'payload': {}}]
        self.config['bom_fingerprint'] = 'c' * 64
        scope = sales['scope_basis'](self.config, self.parts, offers)
        self.config['content']['_sales_conditions'] = {
            'warranty': dict(state='verified', detail='작업 범위 한정 보증', months=12,
                             evidence='PRIVATE_SENTINEL', source='PRIVATE_SENTINEL',
                             checked_date='2026-10-01', scope_basis=scope,
                             operator_id=7, confirmed_at='2026-10-01T00:00:00Z')}
        self.terms['values'] = sales['customer_conditions'](self.config, self.parts, offers)
        value = self.project()['data']['customer_conditions']['warranty']
        self.assertEqual(value['state'], 'verified')
        self.assertEqual(value['months'], 12)
        self.assertEqual(value['detail'], '작업 범위 한정 보증')
        for change in ('quantity', 'offer_price', 'offer_identity'):
            parts, changed_offers = copy.deepcopy(self.parts), copy.deepcopy(offers)
            if change == 'quantity': parts[1]['quantity'] += 1
            elif change == 'offer_price': changed_offers[0]['price_snapshot'] += 100
            else: changed_offers[0]['offer_id'] = 'OTHER'
            self.terms['values'] = sales['customer_conditions'](self.config, parts, changed_offers)
            value = self.project()['data']['customer_conditions']['warranty']
            self.assertEqual(value['state'], 'unknown')
            self.assertTrue(value['needs_reconfirmation'])
            self.assertEqual(value['detail'], ''); self.assertIsNone(value['months'])
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(self.project()))

    def test_invalid_terms_never_promote_unknown_to_a_claim(self):
        for patch in ({'months': True}, {'months': 121}, {'detail': {'private': 1}},
                      {'needs_reconfirmation': 'false'}, {'state': 'included'}):
            original = copy.deepcopy(self.terms['values']['warranty'])
            self.terms['values']['warranty'].update(patch)
            value = self.project()['data']['customer_conditions']['warranty']
            self.assertEqual(value['state'], 'unknown'); self.assertIsNone(value['months'])
            self.terms['values']['warranty'] = original

    def test_unknown_price_is_none_not_zero_or_previous_amount(self):
        for price in (None, {}, {'state': 'unknown', 'amount': 1490000},
                      {'state': 'confirmed', 'amount': 0, 'checked_at': 'now'},
                      {'state': 'confirmed', 'amount': True, 'checked_at': 'now'},
                      {'state': 'confirmed', 'amount': 1490000},
                      {'state': 'needs_reconfirmation', 'amount': 1490000, 'checked_at': 'old'}):
            self.details['price'] = price
            self.assertIsNone(self.project()['data']['price']['amount'])

    def test_price_models_reference_states_and_offer_selection_not_inferred(self):
        for model in ('bundle', 'new_parts_sum', 'derived_delta'):
            for state in ('snapshot', 'estimated', 'confirmed'):
                self.details['price'].update(model=model, state=state, observed_date='2026-10-03')
                result = self.project()['data']
                self.assertEqual(result['price']['model'], model)
                self.assertEqual(result['price']['state'], state)
                self.assertEqual(result['price']['amount'], 1490000)
                self.assertEqual(result['offer_id'], 'ADMIN-DEMO')
        self.details.pop('offer_id')
        self.assertIsNone(self.project()['data']['offer_id'])

    def test_stock_and_assembly_not_inferred_from_approval_or_price(self):
        self.details.pop('stock')
        self.details['compatibility'] = {'document_state': 'unknown', 'public_summary': 'OLD CLAIM'}
        result = self.project()['data']
        self.assertEqual(result['stock'], {'state': 'unknown', 'checked_at': None})
        self.assertEqual(result['compatibility'], {'document_state': 'unknown', 'public_summary': None,
                                                  'assembly_state': 'unknown'})

    def test_strings_are_data_not_rendered_html_and_input_not_mutated(self):
        self.details['description']['title'] = '<script>ignored as text</script>'
        before = copy.deepcopy((self.config, self.parts, self.review, self.publication, self.details, self.terms))
        result = self.project()
        self.assertEqual(result['data']['description']['title'], self.details['description']['title'])
        self.assertEqual(before, (self.config, self.parts, self.review, self.publication, self.details, self.terms))
        result['data']['parts'][0]['specs'][0]['value'] = 'CHANGED'
        self.assertEqual(self.details['parts'][0]['specs'][0]['value'], '1TB')

    def test_malformed_outer_inputs_are_private_without_internal_error_detail(self):
        for value in (None, [], 'bad', False):
            self.assertEqual(project_configuration(value, value, value, publication=value,
                                                  details=value, terms=value),
                             {'status': 404, 'error': 'not_public'})

    def test_import_and_execution_work_without_site_packages_or_db_modules(self):
        root = Path(__file__).resolve().parents[1]
        program = ('import sys; from api.customer_pc_projection import project_configuration; '
                   'assert project_configuration(None, None, None)["status"] == 404; '
                   'assert not any(k in sys.modules for k in '
                   '("api.db", "api.auth", "fastapi", "sqlalchemy", "requests", "socket"))')
        completed = subprocess.run([sys.executable, '-S', '-c', program], cwd=root,
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
