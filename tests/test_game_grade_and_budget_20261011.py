"""6번 — 게임 사양 등급 고치기(R9·F13) + 예산·용도 해석(R8). 2026-10-11 품질관리.

해석 문장은 품질관리-20261011 고객 결과.md 에 적힌 실제 문의다.
  고객1 6번 「대학생인데 게임용 컴퓨터 100만원대」 -> 100만원 상한으로 읽음
  고객1 21번 「롤 120」 -> 「120」을 예산으로 못 읽음
  고객3 3번 「프리미어 프로랑 포토샵 쓸 PC 200만원」 -> 게임 「프로젝트 좀보이드」를 지어냄
"""
import pathlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import talk, talk_rules as TR, talk_schema as TS
from api import admin_game_grades as GG, admin_nav, admin_page_intro
from tests.test_talk_rules_20261010 import vocab, run_parse as _run_parse

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_parse(*a, **k):
    with patch.object(talk, '_record_reply', lambda *x, **y: None):
        return _run_parse(*a, **k)


class BudgetBand(unittest.TestCase):
    def test_band_reads_whole_place(self):
        cases = {'대학생인데 게임용 컴퓨터 100만원대': (1_000_000, 1_990_000),
                 '150만원대로': (1_500_000, 1_590_000), '50만원대 사무용': (500_000, 590_000),
                 '100만 원대요': (1_000_000, 1_990_000), '200만원대가 적당': (2_000_000, 2_990_000)}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(TR.budget_band_from_text(text), want)

    def test_not_a_band(self):
        for text in ('200만원', '100만원 대학생', '100만원대 200만원대', '롤 120'):
            with self.subTest(text=text):
                self.assertIsNone(TR.budget_band_from_text(text))

    def test_parse_sets_cap_and_says_so(self):
        d = run_parse('대학생인데 게임용 컴퓨터 100만원대',
                      {'usages': ['게임'], 'budget_won': 1_000_000, 'game': {'names': [], 'grade': None}},
                      ai_reply='게임용 PC를 찾고 계시는군요.')
        self.assertEqual((d['state']['budget_won'], d['state']['budget_bound']), (1_990_000, '이하'))
        self.assertIn('100만원부터 199만원까지로 보고 찾았어요', d['reply'])


class BareNumber(unittest.TestCase):
    def test_reads_bare_number_at_end(self):
        for text, won in (('롤 120', 1_200_000), ('오버워치 할 컴 120', 1_200_000),
                          ('롤 120 정도', 1_200_000), ('300 정도요', 3_000_000), ('롤 120이요.', 1_200_000)):
            with self.subTest(text=text):
                self.assertEqual(TR.bare_budget_from_text(text), won)

    def test_leaves_part_numbers_and_units(self):
        for text in ('RTX 4060', '27인치', '5대', '배그 2', 'i5 14400', '144hz 모니터', '1080p',
                     '롤 1200', '롤 120만원', '롤 120 배그 150'):
            with self.subTest(text=text):
                self.assertIsNone(TR.bare_budget_from_text(text))

    def test_parse_fills_missing_budget(self):
        d = run_parse('롤 120', {'usages': ['게임'], 'budget_won': None,
                                'game': {'names': ['리그 오브 레전드'], 'grade': None}})
        self.assertEqual(d['state']['budget_won'], 1_200_000)

    def test_parse_replaces_carried_budget_only(self):
        prev = {'usages': ['게임'], 'budget_won': 2_500_000}
        d = run_parse('롤 120', {'usages': ['게임'], 'budget_won': 2_500_000,
                                'game': {'names': ['리그 오브 레전드'], 'grade': None}}, prev=prev)
        self.assertEqual(d['state']['budget_won'], 1_200_000)
        d = run_parse('롤 120', {'usages': ['게임'], 'budget_won': 900_000,
                                'game': {'names': ['리그 오브 레전드'], 'grade': None}}, prev=prev)
        self.assertEqual(d['state']['budget_won'], 900_000, 'AI read a new amount on purpose')


class SoftwareIsNotAGame(unittest.TestCase):
    def setUp(self):
        self.v = vocab()
        self.v.all_game_names.append('프로젝트 좀보이드')

    def test_premiere_pro_does_not_match_zomboid(self):
        self.assertEqual(TR.games_from_text('프리미어 프로랑 포토샵 쓸 PC 200만원', self.v, TS.match_game), [])
        self.assertIn('리그 오브 레전드', TR.games_from_text('포토샵도 하고 롤도 해요', self.v, TS.match_game))

    def test_parse_drops_invented_game(self):
        v = self.v
        with patch.object(talk.TS, 'load_vocab', lambda conn: v):
            d = run_parse('프리미어 프로랑 포토샵 쓸 PC 200만원',
                          {'usages': ['사무·인강', '게임'], 'budget_won': 2_000_000,
                           'game': {'names': ['프로젝트 좀보이드'], 'grade': None}})
        self.assertIsNone(d['state']['game'])
        self.assertNotIn('게임', d['state']['usages'])
        self.assertIn('game.names', {x['field'] for x in d['dropped']})


class GameGradeAdmin(unittest.TestCase):
    def test_owner_only_writes(self):
        with patch.object(GG, 'current_operator', lambda: {'role': 'operator', 'operator_id': 2}):
            with self.assertRaises(HTTPException) as c:
                GG.set_grade(1, GG.GradeBody(grade='E', reason='x'))
            self.assertEqual(c.exception.status_code, 403)
            with self.assertRaises(HTTPException):
                GG.undo(1)
        with patch.object(GG, 'current_operator', lambda: None):
            with self.assertRaises(HTTPException) as c:
                GG.list_games()
            self.assertEqual(c.exception.status_code, 401)

    def test_reason_required_before_db(self):
        with patch.object(GG, 'current_operator', lambda: {'role': 'owner', 'operator_id': 1}):
            with self.assertRaises(HTTPException) as c:
                GG.set_grade(1, GG.GradeBody(grade='E', reason='   '))
            self.assertEqual(c.exception.status_code, 400)

    def test_ledger_and_undo_contract(self):
        src = (ROOT / 'api/admin_game_grades.py').read_text(encoding='utf-8')
        self.assertIn("'ref_log_id'", src)
        self.assertIn('admin_operator_activity_logs', src)
        self.assertNotIn('DELETE FROM game_grade_assignments', src)
        self.assertNotIn('game_grade_suggestions SET', src)

    def test_registered_in_menu_and_intro(self):
        hrefs = [i[1] for g in admin_nav.NAV for i in g[2]]
        self.assertIn('/admin2/game-grades', hrefs)
        self.assertIn('/admin2/game-grades', admin_page_intro.INTRO)
        groups = admin_nav.new_admin_nav('/admin2/game-grades')
        self.assertEqual([g['label'] for g in groups if g['active']], ['사용·성능 자료'])


def _local_url():
    from tests.test_mall_price import _local_url as f
    return f()


@unittest.skipUnless(_local_url(), '루프백 Postgres 가 없어 DB 검사를 건너뜁니다')
class GameGradeUndoLatestOnly(unittest.TestCase):
    """코덱스 검수 #88: A->B, B->C, C->B 뒤 첫 기록(A->B)을 되돌리면 안 된다(값만 같을 뿐 최신 기록이 아니다)."""

    @classmethod
    def setUpClass(cls):
        import uuid
        from sqlalchemy import create_engine, text
        cls.text = staticmethod(text)
        cls.schema = 'game_grade_t_' + uuid.uuid4().hex[:12]
        with create_engine(_local_url()).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % cls.schema))
        cls.engine = create_engine(_local_url(), connect_args={'options': '-csearch_path=%s' % cls.schema})
        with cls.engine.begin() as c:
            for stmt in (
                'CREATE TABLE games (game_id INT PRIMARY KEY, name TEXT)',
                'CREATE TABLE game_grade_assignments (game_id INT PRIMARY KEY, grade TEXT,'
                ' is_confirmed BOOLEAN, note TEXT, assigned_at TIMESTAMP)',
                'CREATE TABLE admin_operator_activity_logs (log_id BIGSERIAL PRIMARY KEY, operator_id INT,'
                ' action TEXT, target_kind TEXT, target_id TEXT, detail JSONB)',
                "INSERT INTO games VALUES (1, '게임1')",
                "INSERT INTO game_grade_assignments VALUES (1, 'A', TRUE, NULL, now())"):
                c.execute(text(stmt))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(_local_url()).begin() as c:
            c.execute(cls.text('DROP SCHEMA "%s" CASCADE' % cls.schema))

    def test_old_record_is_refused_and_latest_is_undone(self):
        grades = [{'grade': g} for g in 'ABC']
        with patch.object(GG, 'engine', self.engine), \
                patch.object(GG, 'current_operator', lambda: {'role': 'owner', 'operator_id': 1}), \
                patch.object(GG, '_grades', lambda conn: grades):
            first = GG.set_grade(1, GG.GradeBody(grade='B', reason='r1'))['log_id']
            GG.set_grade(1, GG.GradeBody(grade='C', reason='r2'))
            last = GG.set_grade(1, GG.GradeBody(grade='B', reason='r3'))['log_id']
            with self.assertRaises(HTTPException) as c:
                GG.undo(first)
            self.assertEqual(c.exception.status_code, 409)
            GG.undo(last)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(self.text('SELECT grade FROM game_grade_assignments')).scalar(), 'C')


if __name__ == '__main__':
    unittest.main()
