"""Actual source functions with caller-connection mocks; no native DB/PG proof."""
import ast
import builtins
import hashlib
import secrets
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'api/orders.py'
BASELINE_AST_SHA = '684986df8e636b552b2095b6c023b837bf7c14bc5e82f005fd4cf1c80179fead'


class Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, mode='own', session=True, stored='owner-key', ready=True):
        self.mode, self.session, self.stored, self.ready = mode, session, stored, ready
        self.trace, self.fail, self.rollbacks, self.begins = [], None, 0, 0
    def execute(self, sql, params=None):
        self.trace.append((sql, params))
        if self.fail and self.fail in sql: raise RuntimeError('read failure')
        if sql == 'SELECT key, mode FROM ops_settings': return Result([('pay', self.mode)])
        if 'FROM consult_sessions' in sql:
            return Result([{'access_key': self.stored}] if self.session else [])
        raise AssertionError('business read/write reached: ' + sql)
    def __enter__(self): self.begins += 1; return self
    def __exit__(self, kind, value, tb):
        if kind: self.rollbacks += 1


def functions(conn):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    tree.body = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))]
    for n in tree.body: n.decorator_list = []
    gate_source = ROOT / 'api/access_gate.py'
    gate_tree = ast.parse(gate_source.read_text(encoding='utf-8-sig'))
    gate_tree.body = [n for n in gate_tree.body if isinstance(n, ast.FunctionDef) and n.name in
                      ('key_from_request', 'matches', 'gate_unavailable', 'forbidden', 'require_session_owner')]
    gate = dict(HTTPException=HTTPException, Request=Request, secrets=secrets,
                HEADER='X-Access-Key', text=lambda sql: sql,
                column_ready=lambda c, table: c.ready,
                log=SimpleNamespace(info=lambda *args: None))
    env = dict(BaseModel=BaseModel, HTTPException=HTTPException, Request=Request, Response=Response,
               engine=SimpleNamespace(begin=lambda: conn), text=lambda sql: sql)
    real_import = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name == 'main' or name == 'api' or name.startswith('api.'):
            raise AssertionError('production import blocked: ' + name)
        return real_import(name, *args, **kwargs)
    with patch('builtins.__import__', side_effect=blocked):
        exec(compile(gate_tree, str(gate_source), 'exec'), gate)
        env['access_gate'] = SimpleNamespace(**gate)
        exec(compile(tree, str(SOURCE), 'exec'), env)
    return SimpleNamespace(**env)


class MockPaymentBlockTests(unittest.TestCase):
    def call(self, conn, tier='value', key='owner-key', query=None, header=None):
        f = functions(conn)
        body = f.OrderBody(session_id=71, tier=tier, access_key=key,
                           member={'nick': 'fixture', 'email': 'fixture@example.invalid'},
                           shipping={'name': 'fixture', 'phone': 'fixture', 'addr': 'fixture'})
        request = Request({'type': 'http', 'headers': [(b'x-access-key', header.encode())] if header else []})
        return f.create_order(body, request, Response(), query)
    def error(self, conn, status, **kwargs):
        with self.assertRaises(HTTPException) as caught: self.call(conn, **kwargs)
        self.assertEqual(caught.exception.status_code, status)
        return caught.exception.detail
    def test_all_tiers_stop_after_owner_before_quote_or_any_business_query(self):
        for tier in ('value', 'recommend', 'highend'):
            with self.subTest(tier=tier):
                c = Connection()
                self.assertEqual(self.error(c, 409, tier=tier)['error'], 'legacy_mock_payment_disabled')
                self.assertEqual(len(c.trace), 2)
                self.assertEqual(c.trace[1][1], {'s': 71})
                self.assertEqual((c.begins, c.rollbacks), (1, 1))
    def test_invalid_tier_precedes_mode_and_owner(self):
        c = Connection(mode='mall', ready=False)
        self.assertEqual(self.error(c, 400, tier='unknown'), '알 수 없는 티어: unknown')
        self.assertEqual((c.trace, c.begins), ([], 0))
    def test_non_own_modes_preserve_original_409_before_owner(self):
        for mode in ('mall', None, 'unexpected'):
            with self.subTest(mode=mode):
                c = Connection(mode=mode, ready=False)
                self.assertEqual(self.error(c, 409)['error'], 'pay_mode_mall')
                self.assertEqual(len(c.trace), 1)
    def test_actual_owner_schema_503_and_absent_session_404_precede_new_block(self):
        c = Connection(ready=False)
        self.assertEqual(self.error(c, 503)['error'], 'gate_unavailable')
        self.assertEqual(len(c.trace), 1)
        c = Connection(session=False)
        self.assertEqual(self.error(c, 404), '그 상담을 찾을 수 없습니다')
        self.assertEqual(len(c.trace), 2)
    def test_actual_owner_all_403_reasons_precede_new_block(self):
        for stored, key, reason in ((None, 'owner-key', 'no_access_key'),
                                    ('owner-key', None, 'access_key_missing'),
                                    ('owner-key', 'wrong', 'access_key_mismatch')):
            with self.subTest(reason=reason):
                c = Connection(stored=stored)
                detail = self.error(c, 403, key=key)
                self.assertEqual((detail['error'], detail['reason']), ('forbidden', reason))
                self.assertEqual(len(c.trace), 2)
    def test_access_key_body_query_header_priority_is_preserved(self):
        for key, query, header in (('owner-key', 'wrong', 'wrong'),
                                   (None, ' owner-key ', 'wrong'),
                                   (None, ' ', ' owner-key ')):
            with self.subTest(key=key, query=query):
                self.assertEqual(self.error(Connection(), 409, key=key, query=query, header=header)['error'],
                                 'legacy_mock_payment_disabled')
        self.assertEqual(self.error(Connection(), 403, key=None, query='wrong', header='owner-key')['reason'],
                         'access_key_mismatch')
    def test_read_failures_propagate_without_business_access(self):
        for fragment, count in (('ops_settings', 1), ('consult_sessions', 2)):
            with self.subTest(fragment=fragment):
                c = Connection(); c.fail = fragment
                with self.assertRaisesRegex(RuntimeError, 'read failure'): self.call(c)
                self.assertEqual((len(c.trace), c.rollbacks), (count, 1))
    def test_only_new_raise_added_entire_original_mock_body_preserved(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_order')
        tx = next(n for n in function.body if isinstance(n, ast.With))
        blocks = [n for n in tx.body if isinstance(n, ast.Raise) and
                  'legacy_mock_payment_disabled' in ast.dump(n)]
        self.assertEqual(len(blocks), 1)
        index = tx.body.index(blocks[0])
        self.assertIn('require_session_owner', ast.dump(tx.body[index-1]))
        self.assertIn('quote_snapshots', ast.dump(tx.body[index+1]))
        tx.body.remove(blocks[0])
        digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        self.assertEqual(digest, BASELINE_AST_SHA)


if __name__ == '__main__': unittest.main()
