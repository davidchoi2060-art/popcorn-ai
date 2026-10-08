"""Mixed game scope regression, without importing the app or a DB engine.

The original schema module is loaded with only its DB-backed vocabulary loader
stubbed. Grid coverage uses the original sold branch AST, not a live API call.
"""
import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_schema():
    package = ModuleType('_talk_schema_scope_test')
    package.__path__ = [str(ROOT / 'api')]
    loader = ModuleType('_talk_schema_scope_test.usage_floors')
    spec = importlib.util.spec_from_file_location(
        '_talk_schema_scope_test.talk_schema', ROOT / 'api/talk_schema.py')
    module = importlib.util.module_from_spec(spec)
    original_db = sys.modules.get('api.db')
    with patch.dict(sys.modules, {
        package.__name__: package, loader.__name__: loader, spec.name: module,
    }):
        spec.loader.exec_module(module)
    if sys.modules.get('api.db') is not original_db:
        raise AssertionError('Schema import loaded the DB module')
    return module


TS = load_schema()


def vocab(*, confirmed=None, listed=None):
    return TS.Vocab(
        grades=[{'grade': 'E'}, {'grade': 'C'}],
        confirmed_games={'리그 오브 레전드': 'E'} if confirmed is None else confirmed,
        all_game_names=['리그 오브 레전드'] if listed is None else listed,
        game_aliases={'롤': '리그 오브 레전드', '배그': '배틀그라운드'},
        grade_weight={'E': 1, 'C': 3},
        usages=[('고사양 게임', []), ('캐주얼 게임', [])],
    )


def validate(names, vocabulary, grade='C', grade_src='ai_estimate'):
    return TS.validate_state({
        'usages': ['고사양 게임', '캐주얼 게임'],
        'budget_won': 1500000,
        'game': {'names': names, 'grade': grade, 'grade_src': grade_src,
                 'resolution': '1080p'},
    }, vocabulary)


class GameScopeTests(unittest.TestCase):
    def assert_blocked(self, state, vocabulary, dropped, unresolved):
        self.assertIsNone(state.game.grade)
        self.assertIsNone(state.game.grade_src)
        self.assertEqual(TS.missing_for(state, vocabulary), ['game.grade'])
        for field in ['game.grade', 'game.grade_src']:
            entry = next(d for d in dropped if d['field'] == field)
            self.assertIn('전체 게임 적합성 확인 전 추천 보류', entry['reason'])
            for name in unresolved:
                self.assertIn(name, entry['reason'])

    def test_confirmed_plus_unlisted_is_blocked(self):
        v = vocab()
        state, dropped = validate(['롤', '목록 밖 게임'], v)
        self.assert_blocked(state, v, dropped, ['목록 밖 게임'])
        self.assertEqual(state.game.names, ['롤', '목록 밖 게임'])

    def test_confirmed_plus_listed_without_grade_is_blocked(self):
        v = vocab(listed=['리그 오브 레전드', '배틀그라운드'])
        state, dropped = validate(['배그', '롤'], v)
        self.assert_blocked(state, v, dropped, ['배틀그라운드'])

    def test_confirmed_plus_both_unresolved_kinds_is_blocked(self):
        v = vocab(listed=['리그 오브 레전드', '배틀그라운드'])
        state, dropped = validate(['롤', '배그', '목록 밖 게임'], v)
        self.assert_blocked(state, v, dropped, ['배틀그라운드', '목록 밖 게임'])

    def test_mixed_without_incoming_grade_remains_blocked(self):
        v = vocab()
        state, dropped = validate(['롤', '목록 밖 게임'], v, None, None)
        self.assert_blocked(state, v, dropped, ['목록 밖 게임'])

    def test_all_confirmed_keep_heaviest(self):
        v = vocab(confirmed={'리그 오브 레전드': 'E', '배틀그라운드': 'C'},
                  listed=['리그 오브 레전드', '배틀그라운드'])
        state, _ = validate(['롤', '배그'], v, 'E', 'catalog')
        self.assertEqual((state.game.grade, state.game.grade_src), ('C', 'catalog'))
        self.assertEqual(TS.missing_for(state, v), [])

    def test_single_confirmed_still_overrides_ai(self):
        state, _ = validate(['롤'], vocab())
        self.assertEqual((state.game.grade, state.game.grade_src), ('E', 'catalog'))

    def test_alias_and_duplicate_names_do_not_create_unresolved_game(self):
        state, _ = validate(['롤', '리그 오브 레전드', '롤'], vocab())
        self.assertEqual(state.game.names, ['롤', '리그 오브 레전드'])
        self.assertEqual((state.game.grade, state.game.grade_src), ('E', 'catalog'))

    def test_no_names_keeps_existing_ai_estimate_policy(self):
        state, _ = validate([], vocab())
        self.assertEqual((state.game.grade, state.game.grade_src), ('C', 'ai_estimate'))

    def test_all_unlisted_keeps_explicit_ai_estimate(self):
        state, _ = validate(['새 게임 하나', '새 게임 둘'], vocab())
        self.assertEqual((state.game.grade, state.game.grade_src), ('C', 'ai_estimate'))

    def test_all_unlisted_without_source_is_not_promoted(self):
        state, _ = validate(['새 게임'], vocab(), grade_src=None)
        self.assertEqual((state.game.grade, state.game.grade_src), ('C', None))

    def test_all_unlisted_catalog_claim_is_not_accepted(self):
        state, _ = validate(['새 게임'], vocab(), grade_src='catalog')
        self.assertEqual((state.game.grade, state.game.grade_src), ('C', None))

    def test_all_listed_unconfirmed_stays_blocked(self):
        v = vocab(confirmed={}, listed=['배틀그라운드'])
        state, _ = validate(['배그'], v)
        self.assertIsNone(state.game.grade)
        self.assertEqual(TS.missing_for(state, v), ['game.grade'])

    def test_talk_state_grid_revalidation_and_original_sold_branch(self):
        v = vocab(listed=['리그 오브 레전드', '배틀그라운드'])
        talk_state, _ = validate(['롤', '배그'], v)
        grid_state, dropped = TS.validate_state(talk_state.model_dump(), v)
        self.assert_blocked(grid_state, v, dropped, ['배틀그라운드'])
        tree = ast.parse((ROOT / 'api/grid_public.py').read_text(encoding='utf-8-sig'))
        recommend = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'recommend')
        branch = next(n for n in ast.walk(recommend)
                      if isinstance(n, ast.If) and ast.unparse(n.test) == "RECO_SOURCE == 'sold'")
        # Fail immediately if a DB-backed game-context read becomes reachable.
        cards = Mock(return_value=[])
        context = Mock(side_effect=AssertionError('Unexpected game context DB path'))
        env = {'RECO_SOURCE': 'sold', 'state': grid_state,
               'game_usages': ['고사양 게임', '캐주얼 게임'],
               'game_grade': grid_state.game.grade, 'card_sets': [], 'notes': [],
               'is_game_usage': TS.is_game_usage, 'SOLD': SimpleNamespace(card_sets=cards),
               '_game_context': context, 'assumed': [], 'ai_estimated': [],
               'DEFAULT_RESOLUTION': TS.DEFAULT_RESOLUTION,
               'ASSUMED_RESOLUTION': 'game.resolution=1080p', 'conn': None, 'vocab': v}
        exec(compile(ast.Module(body=branch.body, type_ignores=[]), 'grid sold branch', 'exec'), env)
        cards.assert_called_once_with(grid_state, [], [], env['notes'])
        context.assert_not_called()
        self.assertEqual(env['card_sets'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
