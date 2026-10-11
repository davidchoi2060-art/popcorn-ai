"""상담 해석 바로잡기 — 시험한 값만 «사용»으로 올린다 (2026-10-11 코덱스 검수 #111 · 0154).

화면은 «미사용으로 저장 → 시험 → 사용»을 안내했지만 API 는 처음부터 «사용»으로 만들 수 있었다.
서버가 그 순서를 지키는지 로컬 Postgres 의 임시 스키마에서 확인한다(0151 · 0154 를 그대로 올린다).
"""
import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@127.0.0.1:1/x")

from fastapi import HTTPException  # noqa: E402

from api import admin_talk_text_fixes as AF  # noqa: E402

OWNER = {'role': 'owner', 'operator_id': 7}


def _migration(name):
    p = ROOT / 'db/migrations/versions' / name
    spec = importlib.util.spec_from_file_location(p.stem, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _local_url():
    from tests.test_mall_price import _local_url as f
    return f()


class _Op:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        from sqlalchemy import text
        self.conn.execute(text(sql))


class Contract(unittest.TestCase):
    def test_revision_follows_main_head(self):
        m = _migration('0154_talk_text_fix_tested.py')
        self.assertEqual((m.revision, m.down_revision), ('0154', '0153'))

    def test_new_rule_cannot_start_in_use(self):
        with patch.object(AF, 'current_operator', lambda: OWNER), self.assertRaises(HTTPException) as c:
            AF.add_fix(AF.FixBody(phrase='백만원 언더', kind='예산', budget_man=100, status='사용'))
        self.assertEqual(c.exception.status_code, 409)

    def test_testing_a_saved_rule_is_owner_only(self):
        with patch.object(AF, 'current_operator', lambda: {'role': 'operator'}), \
                self.assertRaises(HTTPException) as c:
            AF.try_sentence(AF.TryBody(sentence='백만원 언더', fix_id=1))
        self.assertEqual(c.exception.status_code, 403)

    def test_sig_ignores_memo(self):
        a = dict(phrase_norm='x', kind='예산', budget_won=1, budget_bound=None, resolution=None, memo='a')
        self.assertEqual(AF.sig(a), AF.sig(dict(a, memo='b')))
        self.assertNotEqual(AF.sig(a), AF.sig(dict(a, budget_won=2)))


@unittest.skipUnless(_local_url(), '루프백 Postgres 가 없어 DB 검사를 건너뜁니다')
class TestedBeforeUse(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine, text
        self.text = text
        self.schema = 'tfix_t_' + uuid.uuid4().hex[:12]
        with create_engine(_local_url()).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % self.schema))
        self.engine = create_engine(_local_url(), connect_args={'options': '-csearch_path=%s' % self.schema})
        with self.engine.begin() as c:
            for name in ('0151_talk_text_fixes.py', '0154_talk_text_fix_tested.py'):
                m = _migration(name)
                with patch.object(m, 'op', _Op(c)):
                    m.upgrade()
        self.patches = [patch.object(AF, 'engine', self.engine),
                        patch.object(AF, 'current_operator', lambda: OWNER)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(_local_url()).begin() as c:
            c.execute(self.text('DROP SCHEMA "%s" CASCADE' % self.schema))

    def body(self, **kw):
        base = dict(phrase='백만원 언더', kind='예산', budget_man=100, budget_bound='이하', status='미사용')
        base.update(kw)
        return AF.FixBody(**base)

    def status(self, fid):
        with self.engine.connect() as c:
            return c.execute(self.text('SELECT status FROM talk_text_fixes WHERE fix_id=:i'), {'i': fid}).scalar()

    def expect(self, code, call):
        with self.assertRaises(HTTPException) as c:
            call()
        self.assertEqual(c.exception.status_code, code)

    def test_use_needs_a_matching_test(self):
        fid = AF.add_fix(self.body())['fix_id']
        self.expect(409, lambda: AF.save_fix(fid, self.body(status='사용')))
        # 표현이 없는 문장으로 시험하면 시험한 것으로 치지 않는다
        r = AF.try_sentence(AF.TryBody(sentence='사무용 PC', fix_id=fid))
        self.assertFalse(r['tested'])
        self.expect(409, lambda: AF.save_fix(fid, self.body(status='사용')))
        self.assertFalse(AF.list_fixes()['items'][0]['tested'])
        # 미사용 규칙도 fix_id 로 시험하면 문장에 쓰인다
        r = AF.try_sentence(AF.TryBody(sentence='사무용 백만원언더', fix_id=fid))
        self.assertTrue(r['tested'])
        self.assertEqual((r['budget_won'], r['budget_bound']), (1_000_000, '이하'))
        self.assertTrue(AF.list_fixes()['items'][0]['tested'])
        self.assertEqual(AF.save_fix(fid, self.body(status='사용', memo='확인'))['status'], '사용')
        self.assertEqual(self.status(fid), '사용')

    def test_changed_value_needs_a_new_test(self):
        fid = AF.add_fix(self.body())['fix_id']
        AF.try_sentence(AF.TryBody(sentence='백만원 언더로', fix_id=fid))
        AF.save_fix(fid, self.body(status='사용'))
        # 값이 그대로면 «사용» 그대로 저장된다(메모만 바꿈)
        AF.save_fix(fid, self.body(status='사용', memo='메모'))
        # 값을 바꾸면 다시 시험해야 한다
        self.expect(409, lambda: AF.save_fix(fid, self.body(status='사용', budget_man=120)))
        self.assertEqual(self.status(fid), '사용')
        AF.save_fix(fid, self.body(budget_man=120))
        self.assertFalse(AF.list_fixes()['items'][0]['tested'])
        AF.try_sentence(AF.TryBody(sentence='백만원 언더로', fix_id=fid))
        self.assertEqual(AF.save_fix(fid, self.body(status='사용', budget_man=120))['status'], '사용')

    def test_longer_rule_wins_so_test_does_not_count(self):
        long_id = AF.add_fix(self.body(phrase='백만원 언더 사무용', budget_man=90))['fix_id']
        AF.try_sentence(AF.TryBody(sentence='백만원 언더 사무용', fix_id=long_id))
        AF.save_fix(long_id, self.body(phrase='백만원 언더 사무용', budget_man=90, status='사용'))
        short_id = AF.add_fix(self.body())['fix_id']
        r = AF.try_sentence(AF.TryBody(sentence='백만원 언더 사무용', fix_id=short_id))
        self.assertFalse(r['tested'])
        self.assertEqual(r['budget_won'], 900_000)
        self.expect(409, lambda: AF.save_fix(short_id, self.body(status='사용')))

    def test_unknown_rule(self):
        self.expect(404, lambda: AF.try_sentence(AF.TryBody(sentence='백만원 언더', fix_id=999)))
        self.expect(404, lambda: AF.save_fix(999, self.body()))

    def test_downgrade_keeps_0151(self):
        m = _migration('0154_talk_text_fix_tested.py')
        with self.engine.begin() as c, patch.object(m, 'op', _Op(c)):
            m.downgrade()
        with self.engine.connect() as c:
            cols = {r[0] for r in c.execute(self.text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=:s"
                " AND table_name='talk_text_fixes'"), {'s': self.schema})}
        self.assertNotIn('tested_sig', cols)
        self.assertIn('status', cols)


if __name__ == '__main__':
    unittest.main()
