"""Actual frozen resolver + publication + projection on SQL MOCK only.

Reuses the existing publication fixture's real review/terms/source functions.
No DB/main/auth/storage imports, engines, PG or network. Approval/bytes are MOCK.
"""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_sold_read_publication_fixture', ROOT / 'tests/test_pc_customer_publication.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Scalar:
    def __init__(self, value): self.value = value
    def scalar_one(self): return self.value


class Connection(fixture.Connection):
    def __init__(self, copy, part):
        super().__init__(copy, part)
        self.readonly = 'off'
        self.settings_isolation = 'repeatable read'
        self.registered = True
        self.binding_override = {}
        self.before_latest = None
        self.failure = None
        self.sold = dict(product_code=99413, status='판매중')
        self.config['content'].update(source='기존', source_ids=['P99413', 'P10'])
        self.offers = [dict(configuration_id='P10', offer_id='P99413', price_snapshot=1000,
                            payload=dict(id='P99413', quote_only=False))]
        self.media_selected = False
        for code, row in self.rows.items():
            row['content'].update(role='실제 등록 역할 '+str(code), facts=[
                dict(label='등록 사실', value='AM4', source_id='PRIVATE', verification='PRIVATE')])
            self.parts[code - 11]['explanation_hash'] = copy.explanation_digest(row)

    def execute(self, statement, params=None):
        q = str(statement); p = params or {}
        if self.failure and self.failure in q:
            raise RuntimeError('MOCK SQL unavailable')
        if self.readonly == 'on' and re.match(r'\s*(?:/\*.*?\*/\s*)?(INSERT|UPDATE|DELETE)', q):
            raise RuntimeError('MOCK read-only violation')
        if q in ('SHOW transaction_isolation', 'SHOW transaction_read_only'):
            self.calls.append((q, deepcopy(p)))
            return Scalar(self.settings_isolation if q.endswith('isolation') else self.readonly)
        if '/*pc_publication:latest*/' in q and self.before_latest:
            callback = self.before_latest; self.before_latest = None; callback()
        if q == 'SELECT product_code,status FROM products WHERE product_code=:code':
            self.calls.append((q, deepcopy(p)))
            return fixture.Result([deepcopy(self.sold)]) if self.sold else fixture.Result()
        if 'WHERE o.offer_id=:offer' in q:
            self.calls.append((q, deepcopy(p)))
            offer = next((o for o in self.offers if o['offer_id'] == p['offer']), None)
            if not self.registered or not offer: return fixture.Result()
            value = {k: deepcopy(offer[k]) for k in ('offer_id', 'configuration_id', 'price_snapshot', 'payload')}
            value.update({k: self.config[k] for k in ('revision', 'bom_fingerprint', 'content_hash', 'copy_hash')})
            value.update(self.binding_override)
            return fixture.Result([value])
        if 'WHERE e.source_product_code=:code' in q:
            self.calls.append((q, deepcopy(p)))
            return fixture.Result([deepcopy(self.rows[p['code']])]) if p['code'] in self.rows else fixture.Result()
        if 'FROM pc_media_jobs' in q:
            self.calls.append((q, deepcopy(p)))
            return fixture.Result()
        if q.startswith('SELECT * FROM pc_configuration_offers'):
            self.calls.append((q, deepcopy(p)))
            ordering = (lambda o: (o['price_snapshot'], o['offer_id'])) if 'ORDER BY price_snapshot' in q else (lambda o: o['offer_id'])
            return fixture.Result(deepcopy(sorted(self.offers, key=ordering)))
        return super().execute(statement, params)


class SoldReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {k: v for k, v in sys.modules.items()
                        if k == fixture.PACKAGE or k.startswith(fixture.PACKAGE + '.')}
        cls.core, old_copy, cls.part, cls.sales, cls.review = fixture.sources()
        cls.copy = fixture.selected('pc_configuration_copy', 'api/pc_configuration_copy.py',
            ('digest', 'explanation_digest', 'part_needs_review', 'queue_status',
             'read_configuration', 'read_sold_offer_configuration'), namespace=dict(
                json=fixture.json, hashlib=fixture.hashlib, re=re, text=text, HTTPException=HTTPException,
                is_current=cls.part.is_current, SLOT_LABELS={'CPU':'CPU', 'MB':'메인보드'},
                review_snapshot=lambda identity, parts: {'configuration_id':identity},
                load_market=lambda conn: ({}, {}, {}), changes_for=lambda *args: []))
        media = ModuleType(fixture.PACKAGE + '.pc_media')
        media.snapshot = Mock(side_effect=AssertionError('No generated-media authority'))
        sys.modules[media.__name__] = media
        cls.projection = fixture.full('customer_pc_projection', 'api/customer_pc_projection.py')
        cls.adapter = fixture.full('customer_sold_offer_read', 'api/customer_sold_offer_read.py')

    @classmethod
    def tearDownClass(cls):
        for key in list(sys.modules):
            if key == fixture.PACKAGE or key.startswith(fixture.PACKAGE + '.'):
                del sys.modules[key]
        sys.modules.update(cls.previous)

    def setUp(self):
        self.conn = Connection(self.copy, self.part)
        self.restamp()
        self.approve()
        self.conn.readonly = 'on'
        self.conn.calls.clear()

    def restamp(self):
        self.conn.config['content'].pop('_review', None)
        review = self.review.load_review(self.conn, 'P10')[3]
        self.conn.config['content']['_review'] = dict(state='approved', basis=review['basis'],
            actor=dict(operator_id=self.conn.actor['operator_id']), at=fixture.NOW.isoformat())
        self.assertTrue(self.review.load_review(self.conn, 'P10')[3]['eligible'])

    def reader(self, conn, **inputs):
        return fixture.PublicationTests.reader(self, conn, **inputs)

    def approve(self):
        current = self.core.read_current(self.conn, 'P10', source_reader=self.reader)
        self.core.approve(self.conn, 'P10', expected_seq=current['event_seq'],
            revision=self.conn.config['revision'], review_basis=current['basis'],
            publication_basis=current['publication_basis'], request_id=str(uuid4()),
            actor=self.conn.actor, source_reader=self.reader)

    def read(self, **kwargs):
        return self.adapter.read_customer_sold_offer(self.conn, 99413, source_reader=kwargs.get('reader', self.reader))

    def denied(self, **kwargs):
        self.assertEqual(self.read(**kwargs), {'status':404, 'error':'not_public'})

    def test_actual_frozen_functions_and_different_product_configuration(self):
        with patch.object(self.copy, 'read_sold_offer_configuration', wraps=self.copy.read_sold_offer_configuration) as resolve, \
             patch.object(self.core, 'read_current', wraps=self.core.read_current) as publish:
            result = self.read()
        self.assertEqual(result['status'], 200)
        self.assertEqual((result['data']['product_code'], result['data']['offer_id'], result['data']['configuration_id']),
                         (99413, 'P99413', 'P10'))
        resolve.assert_called_once_with(self.conn, 99413)
        self.assertEqual(publish.call_count, 1)
        self.assertIs(publish.call_args.args[0], self.conn)

    def test_public_bom_role_and_facts_without_per_part_price_or_photo(self):
        result = self.read()['data']
        self.assertEqual(result['parts'][0], dict(ordinal=0, slot='CPU', quantity=1, pseudo=False,
            name='CPU', description='실제 등록 역할 11', specs=[dict(label='등록 사실', value='AM4')]))
        self.assertEqual(result['photo'], dict(state='unresolved', url=None))
        self.assertEqual(result['price']['state'], 'unknown')
        self.assertIsNone(result['price']['amount'])
        self.assertEqual(result['stock'], dict(state='unknown', checked_at=None))

    def test_missing_fact_value_is_shown_as_unknown_not_dropped(self):
        parts = [dict(ordinal=0, slot='CPU', quantity=1, pseudo=False, explanation_code=11)]
        rows = {11: dict(content=dict(name='CPU', role='역할', facts=[
            dict(label='소켓', value='LGA1851'), dict(label='기본 전력', value=None),
            dict(label='최대 클럭', value='  '), dict(label=3, value='x'), 'broken']))}
        self.assertEqual(self.adapter._public_parts(parts, rows)[0]['specs'],
                         [dict(label='소켓', value='LGA1851'), dict(label='기본 전력', value='정보 없음'),
                          dict(label='최대 클럭', value='정보 없음')])

    def test_private_false_and_all_source_inputs_remain_unchanged(self):
        original = deepcopy((self.conn.config, self.conn.parts, self.conn.offers, self.conn.rows, self.conn.events))
        self.assertEqual(self.read()['status'], 200)
        self.assertEqual(original, (self.conn.config, self.conn.parts, self.conn.offers, self.conn.rows, self.conn.events))
        self.assertFalse(self.review.load_review(self.conn, 'P10')[3]['customer_publishable'])
        private = self.copy.read_sold_offer_configuration(self.conn, 99413)
        self.assertFalse(private['customer_publishable']); self.assertFalse(private['detail']['customer_publishable'])

    def test_missing_or_noncallable_server_reader(self):
        for reader in (None, {}, True, 'approved'):
            with self.subTest(reader=reader): self.denied(reader=reader)

    def test_native_recommendation_without_publication_event_denies(self):
        self.conn.events.clear(); self.denied()

    def test_current_withdrawal_denies(self):
        self.conn.readonly = 'off'
        self.core.revoke(self.conn, 'P10', expected_seq=1, request_id=str(uuid4()), reason='MOCK withdraw', actor=self.conn.actor)
        self.conn.readonly = 'on'; self.denied()

    def test_withdrawal_between_resolver_and_publication_denies(self):
        self.conn.readonly = 'off'
        self.core.revoke(self.conn, 'P10', expected_seq=1, request_id=str(uuid4()),
                         reason='MOCK concurrent withdrawal', actor=self.conn.actor)
        event = self.conn.events.pop()
        self.conn.readonly = 'on'
        def withdraw():
            self.conn.events.append(deepcopy(event))
        self.conn.before_latest = withdraw; self.denied()

    def test_missing_sold_product_is_not_replaced_by_a_component(self):
        self.conn.sold = None; self.denied()

    def test_whole_pc_sale_status_is_checked_independently_of_parts(self):
        for status in ('품절', '단종', '삭제대기', None):
            with self.subTest(status=status):
                self.conn.sold['status'] = status; self.denied()

    def test_wrong_sold_product_identity_is_rejected(self):
        self.conn.sold['product_code'] = 101; self.denied()

    def test_revision_or_source_change_denies(self):
        self.conn.config['revision'] += 1; self.denied()

    def test_description_change_is_stale(self):
        self.conn.rows[11]['content']['role'] = 'changed'; self.denied()

    def test_missing_registered_offer(self):
        self.conn.registered = False; self.denied()

    def test_wrong_configuration_binding(self):
        self.conn.binding_override['configuration_id'] = 'P999'; self.denied()

    def test_wrong_offer_reference(self):
        self.conn.binding_override['payload'] = dict(id='Pwrong'); self.denied()

    def test_quote_only_offer_cannot_be_public_sold_offer(self):
        self.conn.offers[0]['payload']['quote_only'] = True; self.denied()

    def test_missing_source_reference(self):
        self.conn.config['content']['source_ids'] = ['P10']; self.denied()

    def test_missing_part_and_null_link_denies(self):
        for mutate in ('missing', 'null'):
            with self.subTest(mutate=mutate):
                saved = deepcopy(self.conn.rows)
                if mutate == 'missing': del self.conn.rows[11]
                else: self.conn.rows[11]['product_code'] = None
                self.denied(); self.conn.rows = saved

    def test_photo_bytes_proof_mismatch_denies(self):
        from dataclasses import replace
        def wrong(conn, **inputs):
            proofs = self.reader(conn, **inputs)
            return replace(proofs, photos=(replace(proofs.photos[0], detail_bytes=b'wrong'), *proofs.photos[1:]))
        self.denied(reader=wrong)

    def test_configuration_changes_between_resolver_and_permission_denies(self):
        self.conn.before_latest = lambda: self.conn.config.update(revision=2)
        self.denied()

    def test_callback_copies_cannot_corrupt_projection_inputs(self):
        def mutating(conn, **inputs):
            proofs = self.reader(conn, **inputs)
            inputs['rows'][11]['content']['name'] = 'PRIVATE injected'
            inputs['configuration']['content']['intro'] = 'PRIVATE injected'
            inputs['parts'].clear()
            return proofs
        result = self.read(reader=mutating)
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['data']['parts'][0]['name'], 'CPU')
        self.assertNotIn('PRIVATE injected', json.dumps(result, ensure_ascii=False))

    def test_whitelist_excludes_operating_data_and_raw_evidence(self):
        result = self.read()['data']
        self.assertEqual(set(result), {'configuration_id','revision','offer_id','description','parts','price','stock',
                                       'compatibility','customer_conditions','product_code','photo'})
        encoded = json.dumps(result, ensure_ascii=False)
        for key in ('source_ids','approved_by','image_asset','detail_key','merchant_image_url',
                    'price_snapshot','explanation_code','explanation_hash','current_unit_price',
                    'publication_basis','operator_id','review_workflow','PRIVATE','MOCK-photo'):
            self.assertNotIn(key, encoded)

    def test_multiple_offers_different_sql_order_are_same_binding(self):
        self.conn.readonly = 'off'
        self.conn.offers.append(dict(configuration_id='P10',offer_id='P1',price_snapshot=2000,payload=dict(id='P1')))
        self.restamp(); self.approve(); self.conn.readonly = 'on'
        self.assertEqual(self.read()['status'], 200)

    def test_pseudo_row_has_no_invented_name_description_specs(self):
        self.conn.readonly = 'off'
        self.conn.parts.append(dict(configuration_id='P10', ordinal=8,slot='SERVICE',source_code='assembly',
            explanation_code=None, explanation_hash=None,quantity=1,pseudo=True,selection_note='PRIVATE operation'))
        self.restamp(); self.approve(); self.conn.readonly = 'on'
        value = self.read()['data']['parts'][-1]
        self.assertEqual(value, dict(ordinal=8,slot='SERVICE',quantity=1,pseudo=True,name=None,description=None,specs=[]))

    def test_database_snapshot_settings_not_execution_option_claim(self):
        self.conn.settings_isolation = 'read committed'
        with self.assertRaises(HTTPException) as caught: self.read()
        self.assertEqual(caught.exception.detail, 'customer_readonly_snapshot_required')

    def test_readwrite_transaction_is_rejected_without_draft_or_source_reads(self):
        self.conn.readonly = 'off'
        with self.assertRaises(HTTPException): self.read()
        self.assertEqual([q for q,p in self.conn.calls], ['SHOW transaction_isolation','SHOW transaction_read_only'])

    def test_missing_nested_autocommit_transaction_denied(self):
        for kind in ('missing','nested','autocommit'):
            with self.subTest(kind=kind):
                self.conn.active = kind != 'missing'; self.conn.nested = kind == 'nested'
                self.conn.isolation = 'AUTOCOMMIT' if kind == 'autocommit' else 'REPEATABLE READ'
                with self.assertRaises(HTTPException): self.read()

    def test_transaction_changed_by_callback_rejected(self):
        def changing(conn, **inputs):
            proofs = self.reader(conn, **inputs); conn.transaction = object(); return proofs
        with self.assertRaises(HTTPException) as caught: self.read(reader=changing)
        self.assertEqual(caught.exception.detail, 'customer_snapshot_changed')

    def test_actual_read_path_has_no_writes_or_tx_ownership(self):
        self.assertEqual(self.read()['status'], 200)
        for q,p in self.conn.calls:
            self.assertFalse(re.search(r'\b(INSERT|UPDATE|DELETE|COMMIT|ROLLBACK|FOR UPDATE)\b',q))
        self.assertTrue(all(q.startswith('SHOW') or q.lstrip().startswith('SELECT') or q.startswith('/*pc_publication:')
                            for q,p in self.conn.calls))

    def test_invalid_product_identity_is_not_coerced(self):
        for code in (None,True,0,-1,'99413',1.5,2**63):
            with self.subTest(code=code):
                with self.assertRaises(HTTPException) as caught:
                    self.adapter.read_customer_sold_offer(self.conn,code,source_reader=self.reader)
                self.assertEqual(caught.exception.status_code,422)

    def test_sql_failure_propagates_and_never_grants_public_permission(self):
        self.conn.failure = 'WHERE o.offer_id=:offer'
        with self.assertRaisesRegex(RuntimeError,'MOCK SQL unavailable'): self.read()

    def test_source_has_no_engine_routes_factory_or_application_import(self):
        source = (ROOT/'api/customer_sold_offer_read.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                self.assertNotIn(node.func.attr, ('begin','connect','commit','rollback','close'))
            if isinstance(node,ast.ImportFrom):
                self.assertNotIn(node.module, ('db','main','auth','product_images'))
        self.assertNotIn('APIRouter',source)


if __name__ == '__main__':
    unittest.main()
