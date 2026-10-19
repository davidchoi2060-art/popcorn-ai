import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request
from api import mvp3_saved_quotes as m


def request(headers=()):
    return Request({'type': 'http', 'scheme': 'https', 'server': ('example.invalid', 443),
                    'path': '/api/mvp3/saved-quotes', 'query_string': b'',
                    'headers': [(b'host', b'example.invalid'), (b'x-access-key', b'a'*64), *headers]})


PRODUCT = {'product_code': 17, 'name': 'real stored product', 'price': 1500000,
           'price_src': 'current database price', 'spec': {'cpu': 'actual stored model', 'ram_gb': 32,
             'cpu_mt': 12345, 'operator_note': 'private', 'vram_gb': True},
           'reasons': ['stored reason'], 'operator_id': 9, 'purchase_price': 42}
RECO = {'card_sets': [{'kind': 'sold', 'items': [dict(PRODUCT, photo={'state': 'available', 'url': 'stale'},
                                                      public_configuration={'stale': True})]}]}
LIVE = {'photo': {'state': 'available', 'kind': 'ai_assembly_example',
                  'url': '/api/customer/products/17/representative-image', 'notice': 'n'},
        'public_configuration': {'product_code': 17}}


SAME = {'status': 'same', 'quoted': None, 'mall': None, 'diff': 0, 'saved': False, 'message': None,
        'soldout': False, 'checked_at': '2026-10-11T01:00:00Z'}


def body(**kwargs):
    return m.SaveBody(**{'request_id': UUID(int=1), 'product_code': 17, 'expected_price': 1500000,
                         'state': {'usages': ['게임']}, **kwargs})


class Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def one(self): assert len(self.rows) == 1; return self.rows[0]
    def all(self): return self.rows


class Store:
    def __init__(self):
        self.rows = []; self.executed = []
        # 방문자 연락처(mvp3_visitor_contacts) -- 기본은 이미 등록된 방문자(기존 검사들이 연락처 없이도 보관되던 때와 같다)
        self.contact = {'contact_phone': '010-1234-5678', 'contact_name': None, 'contact_email': None,
                        'consent_at': datetime.now(timezone.utc), 'purge_at': datetime.now(timezone.utc)}
    @contextmanager
    def begin(self): yield self
    def execute(self, sql, p):
        sql = str(sql); self.executed.append((sql, p))
        if 'rate_limit_policies' in sql:
            return Result([])
        if 'mvp3_visitor_contacts' in sql:
            if sql.lstrip().upper().startswith('INSERT'):
                self.contact = {'contact_phone': p['p'], 'contact_name': p['n'], 'contact_email': p['e'],
                                'consent_at': p['now'], 'purge_at': p['purge'], 'consent_text': p['t']}
                return Result([])
            return Result([self.contact] if self.contact else [])
        if 'INSERT INTO' in sql:
            import json
            if not any(r['user_id'] == p['u'] and r['owner_key_hash'] == p['owner'] and r['request_id'] == p['r'] for r in self.rows):
                self.rows.append({'user_id': p['u'], 'owner_key_hash': p['owner'], 'request_id': p['r'], 'quote_id': p['id'],
                                  'request_basis': p['basis'], 'product_snapshot': json.loads(p['product']),
                                  'talk_state': json.loads(p['state']), 'saved_at': datetime.now(timezone.utc)})
            return Result([])
        rows = [r for r in self.rows if r['user_id'] == p['u'] and r['owner_key_hash'] == p['owner']]
        if 'r' in p: rows = [r for r in rows if r['request_id'] == p['r']]
        return Result(rows[:p.get('n', len(rows))])


class SavedQuotesTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        m.access_gate._reset_for_test()
        self.addCleanup(m.access_gate._reset_for_test)
        self.patches = [patch.object(m, 'engine', self.store),
                        patch.object(m.visitor, 'resolve', return_value=11),
                        patch.object(m, 'load_vocab', return_value=None),
                        patch.object(m, 'validate_state', return_value=(SimpleNamespace(model_dump=lambda: {'usages': ['게임']}), [])),
                        patch.object(m.customer_pc_offer, 'public_item', side_effect=lambda code: dict(LIVE)),
                        patch.object(m.grid_public, 'recommend', return_value=RECO),
                        patch.object(m.grid_public, 'eligible_sold_item', return_value=None)]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        # 쇼핑몰 현재가 확인(api/mall_price_live)은 따로 둔다 — 위 목록의 위치 번호를 바꾸지 않게.
        confirm = patch.object(m.mall_price_live, 'confirm',
                               side_effect=lambda moment, code, quoted, **k: dict(SAME, quoted=quoted, mall=quoted))
        self.confirm = confirm.start()
        self.addCleanup(confirm.stop)

    def test_save_uses_server_product_and_filters_private_fields(self):
        q = m.save_quote(body(), request(), Response())['quote']
        self.assertEqual(q['product']['price'], PRODUCT['price'])
        self.assertNotIn('operator_id', q['product'])
        self.assertNotIn('purchase_price', q['product'])
        self.assertFalse(q['product']['price_confirmed'])
        self.assertEqual(q['product']['spec'], {'cpu': 'actual stored model', 'ram_gb': 32})

    def test_photo_and_configuration_are_live_not_snapshotted(self):
        q = m.save_quote(body(), request(), Response())['quote']
        self.assertEqual((q['product']['photo'], q['product']['public_configuration']),
                         (LIVE['photo'], LIVE['public_configuration']))
        stored = self.store.rows[0]['product_snapshot']
        self.assertNotIn('photo', stored)
        self.assertNotIn('public_configuration', stored)
        # 승인·선택이 바뀌면 다음 조회가 바로 따른다
        LIVE_NOW = {'photo': {'state': 'unavailable', 'url': None}, 'public_configuration': None}
        self.mocks[4].side_effect = lambda code: dict(LIVE_NOW)
        listed = m.list_quotes(request(), Response(), limit=20)['quotes'][0]['product']
        self.assertEqual((listed['photo'], listed['public_configuration']), (LIVE_NOW['photo'], None))
        self.assertNotIn('photo', self.store.rows[0]['product_snapshot'])

    def client(self):
        app = FastAPI()
        app.include_router(m.router)
        return TestClient(app, base_url='https://example.invalid')

    def test_surface_is_stored_from_screen_header(self):
        m.save_quote(body(), request([(b'x-popcorn-surface', b'mvp4')]), Response())
        m.save_quote(body(request_id=UUID(int=2)), request(), Response())
        inserts = [p for sql, p in self.store.executed if 'INSERT INTO mvp3_saved_recommendations' in sql]
        self.assertEqual([p['surface'] for p in inserts], ['mvp4', None])

    def test_http_roundtrip_and_no_store(self):
        with self.client() as client:
            headers = {'X-Access-Key': 'a' * 64, 'Origin': 'https://example.invalid'}
            saved = client.post('/api/mvp3/saved-quotes', json=body().model_dump(mode='json'), headers=headers)
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.headers['cache-control'], 'no-store')
            listed = client.get('/api/mvp3/saved-quotes', headers=headers)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()['quotes'], [saved.json()['quote']])
            self.assertEqual(listed.headers['cache-control'], 'no-store')

    def test_http_strict_input_rejects_before_database(self):
        with self.client() as client:
            original = body().model_dump(mode='json')
            for changes in ({'product_code': True}, {'expected_price': '1500000'},
                            {'request_id': 'not-uuid'}, {'product_snapshot': {'name': 'injected'}}):
                with self.subTest(changes=changes):
                    response = client.post('/api/mvp3/saved-quotes', json={**original, **changes},
                                           headers={'X-Access-Key': 'a' * 64})
                    self.assertEqual(response.status_code, 422)
            self.assertEqual(self.store.executed, [])

    def test_http_query_key_is_not_an_access_header(self):
        with self.client() as client:
            response = client.get('/api/mvp3/saved-quotes', params={'k': 'a' * 64})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.store.executed, [])

    def test_http_invalid_limit_rejected_before_database(self):
        with self.client() as client:
            response = client.get('/api/mvp3/saved-quotes?limit=1000', headers={'X-Access-Key': 'a' * 64})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.store.executed, [])

    def test_same_request_recovers_without_recommend_again(self):
        first = m.save_quote(body(), request(), Response())
        self.mocks[-1].side_effect = RuntimeError('must not call again')
        self.assertEqual(first, m.save_quote(body(), request(), Response()))
        self.assertEqual(len(self.store.rows), 1)

    def test_new_saves_are_rate_limited_per_visitor(self):
        for i in range(m.SAVE_PER_MINUTE):
            m.save_quote(body(request_id=UUID(int=100 + i)), request(), Response())
        with self.assertRaises(HTTPException) as ex:
            m.save_quote(body(request_id=UUID(int=999)), request(), Response())
        self.assertEqual(ex.exception.status_code, 429)
        d = ex.exception.detail
        self.assertEqual((d['error'], d['window']), ('rate_limited', 'minute'))
        self.assertIsInstance(d['retry_after_sec'], int)
        self.assertEqual(ex.exception.headers['Retry-After'], str(d['retry_after_sec']))
        self.assertEqual(d['detail'], f"잠시 동안 견적 저장 요청이 많았습니다. {d['retry_after_sec']}초 후 다시 저장해 주세요.")
        self.assertEqual(len(self.store.rows), m.SAVE_PER_MINUTE)

    def test_daily_limit_uses_day_message(self):
        with patch.object(m, 'SAVE_PER_MINUTE', 100), patch.object(m, 'SAVE_PER_DAY', 3):
            for i in range(3):
                m.save_quote(body(request_id=UUID(int=100 + i)), request(), Response())
            with self.assertRaises(HTTPException) as ex:
                m.save_quote(body(request_id=UUID(int=999)), request(), Response())
        d = ex.exception.detail
        self.assertEqual((ex.exception.status_code, d['window']), (429, 'day'))
        self.assertEqual(d['detail'], '오늘 저장할 수 있는 견적 수에 도달했습니다. 내일 다시 저장해 주세요.')
        # "내일" is only true because the day window ends at the next KST midnight.
        self.assertLessEqual(d['retry_after_sec'], 24 * 3600)
        self.assertEqual(len(self.store.rows), 3)

    def test_replay_still_wins_while_limited(self):
        first = m.save_quote(body(), request(), Response())
        for i in range(m.SAVE_PER_MINUTE - 1):
            m.save_quote(body(request_id=UUID(int=100 + i)), request(), Response())
        with self.assertRaises(HTTPException):
            m.save_quote(body(request_id=UUID(int=999)), request(), Response())
        self.assertEqual(m.save_quote(body(), request(), Response()), first)

    def test_replay_does_not_count_toward_limit(self):
        for _ in range(m.SAVE_PER_MINUTE + 5):
            m.save_quote(body(), request(), Response())
        m.save_quote(body(request_id=UUID(int=2)), request(), Response())
        self.assertEqual(len(self.store.rows), 2)

    def test_save_limit_does_not_spend_ai_call_budget(self):
        for i in range(m.SAVE_PER_MINUTE):
            m.save_quote(body(request_id=UUID(int=100 + i)), request(), Response())
        # AI parse/explain still has its own full per-minute allowance.
        for _ in range(m.access_gate.DEFAULT_PER_MINUTE):
            m.access_gate.check_rate(self.store, request(), what='talk.parse')
        # ...and keeps its own, unchanged wording when exhausted.
        with self.assertRaises(HTTPException) as ex:
            m.access_gate.check_rate(self.store, request(), what='talk.parse')
        self.assertTrue(ex.exception.detail['detail'].startswith('방문자별 AI 호출 한도 초과 - 분당'))

    def test_changed_request_id_content_is_rejected(self):
        m.save_quote(body(), request(), Response())
        changed = body(); changed.expected_price = 1
        with self.assertRaises(HTTPException) as ex: m.save_quote(changed, request(), Response())
        self.assertEqual(ex.exception.status_code, 409)

    def test_stale_price_cannot_insert(self):
        changed = body(); changed.expected_price = 1
        with self.assertRaises(HTTPException): m.save_quote(changed, request(), Response())
        self.assertEqual(self.store.rows, [])

    def test_unrecommended_product_cannot_insert(self):
        changed = body(); changed.product_code = 999
        with self.assertRaises(HTTPException): m.save_quote(changed, request(), Response())
        self.assertEqual(self.store.rows, [])

    def test_no_owner_cannot_save(self):
        self.mocks[1].return_value = None
        with self.assertRaises(HTTPException) as ex: m.save_quote(body(), request(), Response())
        self.assertEqual(ex.exception.status_code, 409)
        self.assertEqual(self.store.rows, [])

    def test_other_owner_cannot_read(self):
        m.save_quote(body(), request(), Response())
        self.mocks[1].return_value = 22
        self.assertEqual(m.list_quotes(request(), Response(), 20)['quotes'], [])

    def test_same_visitor_wrong_key_cannot_read(self):
        m.save_quote(body(), request(), Response())
        req = request()
        req.scope['headers'] = [(k, b'b'*64 if k == b'x-access-key' else v) for k, v in req.scope['headers']]
        self.assertEqual(m.list_quotes(req, Response(), 20)['quotes'], [])

    def test_no_access_key_rejected_before_database(self):
        req = request()
        req.scope['headers'] = [(k,v) for k,v in req.scope['headers'] if k != b'x-access-key']
        with self.assertRaises(HTTPException) as ex: m.list_quotes(req, Response(), 20)
        self.assertEqual(ex.exception.status_code, 403)
        self.assertEqual(self.store.executed, [])

    def test_owner_change_before_insert_is_rejected(self):
        # owner lookup, rate-limit subject lookup, then the changed owner at insert time
        self.mocks[1].side_effect = [11, 11, 22]
        with self.assertRaises(HTTPException) as ex: m.save_quote(body(), request(), Response())
        self.assertEqual(ex.exception.status_code, 403)
        self.assertEqual(self.store.rows, [])

    def test_cross_origin_rejected_before_db(self):
        with self.assertRaises(HTTPException) as ex:
            m.save_quote(body(), request([(b'origin', b'https://other.invalid')]), Response())
        self.assertEqual(ex.exception.status_code, 403)
        self.assertEqual(self.store.executed, [])

    def test_private_grid_quote_is_not_sold_product(self):
        self.mocks[-2].return_value = {'card_sets': [{'kind': 'game', 'cards': [{'product_code': 17}]}]}
        with self.assertRaises(HTTPException): m.save_quote(body(), request(), Response())
        self.assertEqual(self.store.rows, [])

    def test_explored_card_outside_default_list_saves_when_eligible(self):
        # 「더 싸게」로 본 카드는 조건만으로 다시 조회한 목록에 없다 — 같은 판매 원천의 용도 판정을 통과하면 보관한다.
        eligible = dict(PRODUCT, product_code=31, price=990000, tag='고른 구성', role='chosen')
        self.mocks[-1].return_value = eligible
        saved = m.save_quote(body(product_code=31, expected_price=990000), request(), Response())
        self.assertEqual(saved['quote']['product']['product_code'], 31)
        self.assertEqual(saved['quote']['product']['role'], 'chosen')
        self.mocks[-1].assert_called_once_with({'usages': ['게임']}, 31)

    def test_recommended_product_does_not_ask_eligibility(self):
        m.save_quote(body(), request(), Response())
        self.mocks[-1].assert_not_called()

    def test_ineligible_explored_card_cannot_insert(self):
        with self.assertRaises(HTTPException) as ex:
            m.save_quote(body(product_code=31, expected_price=990000), request(), Response())
        self.assertEqual(ex.exception.status_code, 409)
        self.assertEqual(self.store.rows, [])


    def test_changed_parts_saved_at_server_total(self):
        built = {'base_price': 1500000, 'total': 1550000, 'compat': {'ok': True},
                 'changes': [{'ordinal': 1, 'slot': 'CPU', 'delta': 50000}]}
        with patch.object(m.mvp3_build, 'build_quote', return_value=(dict(PRODUCT), built)) as bq:
            q = m.save_quote(body(expected_price=1550000, changes=[{'ordinal': 1, 'product_code': 102}]),
                             request(), Response())['quote']
            self.assertEqual(bq.call_args.args[1], 17)
        self.assertEqual(q['product']['price'], 1550000)
        self.assertEqual(q['product']['build']['base_price'], 1500000)
        self.mocks[5].assert_not_called()   # 부품을 바꾼 저장은 추천을 다시 돌리지 않는다
        with patch.object(m.mvp3_build, 'build_quote', return_value=(dict(PRODUCT), built)):
            with self.assertRaises(HTTPException) as e:
                m.save_quote(body(request_id=UUID(int=2), expected_price=1500000,
                                  changes=[{'ordinal': 1, 'product_code': 102}]), request(), Response())
        self.assertEqual(e.exception.status_code, 409)

    def test_changed_parts_compare_base_pc_and_shift_total(self):
        # 쇼핑몰에 있는 것은 기준 PC 다. 기준 가격만 비교하고, 바뀐 만큼 총액도 옮긴다.
        built = {'base_price': 1500000, 'total': 1550000, 'compat': {'ok': True},
                 'changes': [{'ordinal': 1, 'slot': 'CPU', 'delta': 50000}]}
        self.confirm.side_effect = lambda *a, **k: dict(SAME, status='changed', quoted=1500000, mall=1540000,
                                                         diff=40000, saved=True, message='바뀜')
        with patch.object(m.mvp3_build, 'build_quote', return_value=(dict(PRODUCT), built)):
            q = m.save_quote(body(expected_price=1550000, changes=[{'ordinal': 1, 'product_code': 102}]),
                             request(), Response())['quote']
        self.assertEqual(self.confirm.call_args.args, ('cart', 17, 1500000))
        self.assertEqual((q['product']['price'], q['product']['build']['base_price']), (1590000, 1540000))

    def test_fingerprint_without_changes_is_unchanged(self):
        plain = body()
        self.assertEqual(m.fingerprint(plain), m.fingerprint(body(changes=[])))
        self.assertNotEqual(m.fingerprint(plain), m.fingerprint(body(changes=[{'ordinal': 1, 'product_code': 2}])))

    # 2겹 실시간 안전장치(cart) — api/mall_price_live.confirm 이 판정하고 여기서는 그 결과로 보관한다.
    def test_cart_check_runs_once_with_the_stored_quote_id(self):
        q = m.save_quote(body(), request(), Response())['quote']
        confirm = self.confirm
        confirm.assert_called_once()
        args, kw = confirm.call_args
        self.assertEqual(args, ('cart', 17, 1500000))
        self.assertEqual((kw['quote_id'], kw['visitor_ref']), (q['id'], 11))
        self.assertEqual(q['product']['price'], 1500000)
        self.assertEqual(q['product']['price_check']['status'], 'same')

    def test_changed_mall_price_is_saved_and_told(self):
        changed = dict(SAME, status='changed', quoted=1500000, mall=1540000, diff=40000, saved=True,
                       message='쇼핑몰 현재 가격이 1,500,000원에서 1,540,000원으로 바뀌었습니다. 바뀐 가격으로 보관했습니다.')
        self.confirm.side_effect = lambda *a, **k: dict(changed)
        q = m.save_quote(body(), request(), Response())['quote']
        self.assertEqual(q['product']['price'], 1540000)
        self.assertEqual(q['product']['price_check']['message'], changed['message'])
        stored = self.store.rows[0]['product_snapshot']
        self.assertEqual((stored['price'], stored['price_check']['quoted']), (1540000, 1500000))
        self.assertFalse(stored['price_confirmed'])

    def test_unchecked_mall_price_keeps_card_price_and_does_not_block(self):
        self.confirm.side_effect = lambda *a, **k: dict(SAME, status='unchecked', quoted=1500000, diff=None,
                                                         message='현재 가격 확인이 안 되어 쇼핑몰에서 최종 확인됩니다')
        q = m.save_quote(body(), request(), Response())['quote']
        self.assertEqual(q['product']['price'], 1500000)
        self.assertEqual(q['product']['price_check']['status'], 'unchecked')

    def test_replay_does_not_check_the_mall_again(self):
        m.save_quote(body(), request(), Response())
        m.save_quote(body(), request(), Response())
        self.assertEqual(self.confirm.call_count, 1)


if __name__ == '__main__': unittest.main()
