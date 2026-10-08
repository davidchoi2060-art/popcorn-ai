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
RECO = {'card_sets': [{'kind': 'sold', 'items': [PRODUCT]}]}


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
    def __init__(self): self.rows = []; self.executed = []
    @contextmanager
    def begin(self): yield self
    def execute(self, sql, p):
        sql = str(sql); self.executed.append((sql, p))
        if 'rate_limit_policies' in sql:
            return Result([])
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
                        patch.object(m.grid_public, 'recommend', return_value=RECO)]
        self.mocks = [p.start() for p in self.patches]
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_save_uses_server_product_and_filters_private_fields(self):
        q = m.save_quote(body(), request(), Response())['quote']
        self.assertEqual(q['product']['price'], PRODUCT['price'])
        self.assertNotIn('operator_id', q['product'])
        self.assertNotIn('purchase_price', q['product'])
        self.assertFalse(q['product']['price_confirmed'])
        self.assertEqual(q['product']['spec'], {'cpu': 'actual stored model', 'ram_gb': 32})

    def client(self):
        app = FastAPI()
        app.include_router(m.router)
        return TestClient(app, base_url='https://example.invalid')

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
        self.mocks[-1].return_value = {'card_sets': [{'kind': 'game', 'cards': [{'product_code': 17}]}]}
        with self.assertRaises(HTTPException): m.save_quote(body(), request(), Response())
        self.assertEqual(self.store.rows, [])


if __name__ == '__main__': unittest.main()
