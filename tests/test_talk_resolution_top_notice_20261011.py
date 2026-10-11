"""4K · 최고사양을 반영하는 척하지 않는다 — 2026-10-11 품질관리 M6 회귀 고정.

고객 문장은 품질관리-20261011 고객1 15번 · 고객3 4·5·11번 실제 문의다.
4K 는 게임 칸(state.game.resolution)에서만 추천이 쓰고, 비게임 해상도·「최고사양」은
어느 축도 거르지 않는다(api/grid_public). 모니터 포함 예산은 #83 의 주변기기 주제가 맡는다.
"""
import unittest

from api import talk_rules as TR, talk_schema as TS
from tests.test_talk_honest_notices_20261011 import run_parse


def _game(res):
    return TS.TalkState.model_validate({
        'usages': ['게임'], 'game': {'names': ['배틀그라운드'], 'grade': 'C',
                                    'grade_src': 'catalog', 'resolution': res}})


class ResolutionAndTopSpec(unittest.TestCase):
    def test_4k_edit_said_not_applied(self):
        st = {'usages': ['영상편집'], 'budget_won': 4000000}
        r = run_parse('다빈치 리졸브로 4K 편집할 거예요. 400만원', st,
                      ai_reply='4K 영상편집용 400만원대 구성을 맞춰보겠습니다.')
        self.assertNotIn('맞춰보겠습니다', r['reply'])
        self.assertIn('4K 해상도 조건은 아직 추천에 반영하지 못해요', r['reply'])

    def test_4k_question_variants(self):
        for t in ('4K 영상 편집 되나요?', 'UHD로 편집해요', '2160p 작업', '4케이 편집'):
            self.assertIn('4K 해상도', TR.unsupported_conditions(t, TS.TalkState()), t)

    def test_game_4k_is_applied(self):
        self.assertNotIn('4K 해상도', TR.unsupported_conditions('배그 4K로', _game('4K')))
        self.assertIn('4K 해상도', TR.unsupported_conditions('배그 4K로', _game(None)))

    def test_monitor_4k_and_other_numbers_not_counted(self):
        for t in ('4K 모니터 추천해줘', 'RTX 4070 사양', '144hz 모니터', '24k 금도금'):
            self.assertNotIn('4K 해상도', TR.unsupported_conditions(t, TS.TalkState()), t)

    def test_top_spec_said_not_applied(self):
        st = {'usages': ['게임'], 'budget_won': 2500000}
        r = run_parse('250 이하로 게임 최고사양', st, ai_reply='최고사양으로 맞춰드릴게요.')
        self.assertNotIn('맞춰드릴게요', r['reply'])
        self.assertIn('최고 사양 조건은 아직 추천에 반영하지 못해요', r['reply'])
        for t in ('영상편집 최고 사양으로 해주세요', '풀옵으로', '최상급으로', '하이엔드 구성'):
            self.assertIn('최고 사양', TR.unsupported_conditions(t, TS.TalkState()), t)

    def test_top_spec_is_admin_tag(self):
        _applied, conds = TR.requested_conditions('예산 150만원인데 영상편집 최고 사양으로 해주세요', TS.TalkState())
        self.assertEqual(conds, ['최고 사양'])

    def test_monitor_included_budget_stays_peripheral_topic(self):
        self.assertIn('peripheral', TR.purchase_topics('모니터 포함해서 100만원이면요?'))
        self.assertIn('peripheral', TR.purchase_topics('모니터도 같이 사야 하는데 영상편집용 300만원 안에 다 되나요?'))


if __name__ == '__main__':
    unittest.main()
