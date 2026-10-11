"""상담 해석 바로잡기 — 관리자가 등록하는 표현 규칙 (2026-10-11 품질관리 · 개편 14번 · R8 나머지).

AI 가 잘못 읽은 표현을 고치려면 매번 개발이 필요했다. 관리자가 «표현 → 바로잡을 값»을 등록하면
상담이 AI 값 대신 그 값을 쓴다.

DB 없이 확인하는 것: 규칙 적용(공백·대소문자 · 긴 표현 우선 · 종류별 하나) · 상담 응답에 반영과
사유 기록 · 관리자 입력 검사 · 대표 권한 · 시험 · 표 없을 때 건너뛰기 · 마이그레이션 사슬.
DB 를 거치는 저장은 로컬 Postgres 로 따로 확인했다(PR 본문).
"""
import contextlib
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import admin_talk_text_fixes as AF, talk, talk_text_fixes as TF
from tests.test_talk_rules_20261010 import run_parse as _run_parse

ROOT = pathlib.Path(__file__).resolve().parents[1]


def rule(phrase, kind='예산', won=None, bound=None, res=None):
    return {'phrase': phrase, 'phrase_norm': TF.norm(phrase), 'kind': kind,
            'budget_won': won, 'budget_bound': bound, 'resolution': res}


UNDER = rule('백만원 언더', won=1_000_000, bound='이하')
QHD = rule('큐에이치디', kind='해상도', res='1440p')


def run_parse(text, ai_state, *, fixes=(), **kw):
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(talk.shop_notices, 'load_written', lambda conn: {}))
        if hasattr(talk.shop_notices, 'load_custom'):
            st.enter_context(patch.object(talk.shop_notices, 'load_custom', lambda conn: []))
        st.enter_context(patch.object(talk.text_fixes, 'load', lambda conn: list(fixes)))
        return _run_parse(text, ai_state, **kw)


class Apply(unittest.TestCase):
    def test_space_and_case_ignored(self):
        raw = {'budget_won': 10_000_000}
        out = TF.apply('사무용 백만원언더로요', raw, [UNDER])
        self.assertEqual((raw['budget_won'], raw['budget_bound']), (1_000_000, '이하'))
        self.assertEqual(out[0]['reason'], '관리자 해석 규칙 「백만원 언더」 -> 100만원 이하')

    def test_resolution_creates_game_and_keeps_names(self):
        raw = {'game': {'names': ['배틀그라운드'], 'resolution': '1080p'}}
        TF.apply('배그 큐에이치디', raw, [QHD])
        self.assertEqual(raw['game'], {'names': ['배틀그라운드'], 'resolution': '1440p'})
        raw2 = {}
        TF.apply('큐에이치디 모니터', raw2, [QHD])
        self.assertEqual(raw2['game'], {'resolution': '1440p'})

    def test_longest_first_one_per_kind(self):
        short = rule('백만', won=900_000)
        raw = {}
        TF.apply('백만원 언더', raw, [UNDER, short])     # load() 가 긴 표현부터 준다
        self.assertEqual(raw['budget_won'], 1_000_000)

    def test_no_match_no_change_and_same_value_no_reason(self):
        raw = {'budget_won': 5}
        self.assertEqual(TF.apply('게임용', raw, [UNDER]), [])
        self.assertEqual(raw, {'budget_won': 5})
        raw = {'budget_won': 1_000_000, 'budget_bound': '이하'}
        self.assertEqual(TF.apply('백만원 언더', raw, [UNDER]), [])


class Parse(unittest.TestCase):
    def test_admin_rule_wins_over_ai_and_reason_kept(self):
        d = run_parse('사무용 백만원 언더', {'usages': ['사무·인강'], 'budget_won': 10_000_000},
                      fixes=[UNDER])
        self.assertEqual(d['state']['budget_won'], 1_000_000)
        self.assertEqual(d['state']['budget_bound'], '이하')
        self.assertTrue(any('관리자 해석 규칙' in x['reason'] for x in d['dropped']))

    def test_without_rule_unchanged(self):
        d = run_parse('사무용 백만원 언더', {'usages': ['사무·인강'], 'budget_won': 1_000_000})
        self.assertFalse(any('관리자 해석 규칙' in str(x.get('reason')) for x in d['dropped']))


class Loader(unittest.TestCase):
    def test_missing_table_is_skipped(self):
        class Broken:
            def execute(self, *a, **k):
                raise RuntimeError('relation "talk_text_fixes" does not exist')
        self.assertEqual(TF.load(Broken()), [])


class AdminInput(unittest.TestCase):
    def clean(self, **kw):
        base = dict(phrase=' 백만원 언더 ', kind='예산', budget_man=100, budget_bound='이하', status='사용')
        base.update(kw)
        return AF._clean(AF.FixBody(**base))

    def test_budget_cleaned(self):
        v = self.clean(resolution='4K')
        self.assertEqual((v['phrase'], v['phrase_norm'], v['budget_won'], v['budget_bound'], v['resolution']),
                         ('백만원 언더', '백만원언더', 1_000_000, '이하', None))

    def test_resolution_cleaned(self):
        v = self.clean(kind='해상도', resolution='4K', budget_man=100)
        self.assertEqual((v['resolution'], v['budget_won'], v['budget_bound']), ('4K', None, None))

    def test_rejects(self):
        for kw in ({'phrase': '가'}, {'phrase': '가' * 31}, {'kind': 'GPU'}, {'status': '보류'},
                   {'budget_man': None}, {'budget_man': 5}, {'budget_man': 5001}, {'budget_bound': '대'},
                   {'kind': '해상도', 'resolution': '8K'}, {'memo': '가' * 201}):
            with self.subTest(kw=kw), self.assertRaises(HTTPException) as c:
                self.clean(**kw)
            self.assertEqual(c.exception.status_code, 400)

    def test_owner_only(self):
        with patch.object(AF, 'current_operator', lambda: {'role': 'operator'}):
            for call in (lambda: AF.add_fix(AF.FixBody(phrase='백만원 언더', kind='예산', budget_man=100)),
                         lambda: AF.save_fix(1, AF.FixBody(phrase='백만원 언더', kind='예산', budget_man=100))):
                with self.assertRaises(HTTPException) as c:
                    call()
                self.assertEqual(c.exception.status_code, 403)


class TrySentence(unittest.TestCase):
    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_draft_applied_without_saving(self):
        with patch.object(AF.engine, 'connect', lambda: self._C()), \
                patch.object(AF.TF, 'load', lambda conn: []):
            r = AF.try_sentence(AF.TryBody(sentence='사무용 백만원언더',
                                           draft=AF.FixBody(phrase='백만원 언더', kind='예산',
                                                            budget_man=100, budget_bound='이하')))
        self.assertEqual((r['budget_won'], r['budget_bound']), (1_000_000, '이하'))
        self.assertEqual(len(r['applied']), 1)

    def test_empty_sentence_rejected(self):
        with self.assertRaises(HTTPException) as c:
            AF.try_sentence(AF.TryBody(sentence=' '))
        self.assertEqual(c.exception.status_code, 400)


class Migration(unittest.TestCase):
    def test_revision(self):
        p = ROOT / 'db/migrations/versions/0151_talk_text_fixes.py'
        spec = importlib.util.spec_from_file_location('m0151', p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.revision, '0151')
        self.assertTrue(list((ROOT / 'db/migrations/versions').glob(m.down_revision + '_*.py')))


if __name__ == '__main__':
    unittest.main()
