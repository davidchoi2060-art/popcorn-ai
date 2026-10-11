"""작업 프로그램 이름으로 용도를 고정한다 — 2026-10-11 품질관리 고객3 F8 회귀 고정.

「라이트룸이랑 포토샵으로 사진 보정할 컴퓨터 150만원」이 1차는 디자인·조판, 2차는 영상편집으로
읽혀 카드가 달라졌다. 문장에 프로그램 이름이 있으면 용도 표의 그 낱말로 용도를 정한다.
"""
import unittest

from api import talk, talk_rules as TR, talk_schema as TS

USAGES = [
    ('고사양 게임', []), ('게임', ['게임']),
    ('영상편집', ['영상', '편집', '프리미어', '다빈치', '인코딩']),
    ('디자인·조판', ['디자인', '포토샵', '포샵', '일러스트', '인디자인', '라이트룸', '피그마']),
    ('사무용', ['사무', '엑셀', '줌']),
]


def vocab():
    return TS.Vocab(usages=USAGES, all_game_names=['배틀그라운드'],
                    confirmed_games={'배틀그라운드': 'C'})


def fix(text, ai_usages, prev=None, game=None):
    raw = {'usages': ai_usages, 'budget_won': 1500000}
    if game:
        raw['game'] = game
    return talk._apply_text_rules(text, raw, vocab(), prev_usages=prev)


class UsagesFromPrograms(unittest.TestCase):
    def test_only_program_names_count(self):
        self.assertEqual(TR.usages_from_programs('라이트룸이랑 포토샵으로 사진 보정', USAGES), ['디자인·조판'])
        # 「영상」「편집」 같은 넓은 낱말은 프로그램 이름이 아니다
        self.assertEqual(TR.usages_from_programs('영상 편집할 컴퓨터', USAGES), [])
        self.assertEqual(TR.usages_from_programs('프리미어랑 포토샵', USAGES), ['영상편집', '디자인·조판'])

    def test_second_run_wrong_usage_is_fixed(self):
        raw, fixes = fix('라이트룸이랑 포토샵으로 사진 보정할 컴퓨터 150만원', ['영상편집'])
        self.assertEqual(raw['usages'], ['디자인·조판'])
        self.assertEqual(fixes[-1]['field'], 'usages')
        self.assertEqual(fixes[-1]['value'], ['영상편집'])

    def test_first_run_right_usage_is_untouched(self):
        raw, fixes = fix('라이트룸이랑 포토샵으로 사진 보정할 컴퓨터 150만원', ['디자인·조판'])
        self.assertEqual(raw['usages'], ['디자인·조판'])
        self.assertFalse([f for f in fixes if f['field'] == 'usages'])

    def test_usage_backed_by_text_or_previous_turn_is_kept(self):
        raw, _ = fix('포토샵도 쓰고 영상 편집도 해요', ['영상편집'])
        self.assertEqual(raw['usages'], ['영상편집', '디자인·조판'])
        raw, _ = fix('포토샵도 쓸 거예요', ['사무용', '디자인·조판'], prev=['사무용'])
        self.assertEqual(raw['usages'], ['사무용', '디자인·조판'])

    def test_game_usage_is_kept(self):
        raw, _ = fix('배틀그라운드 하고 프리미어로 편집도 해요', ['게임'],
                     game={'names': ['배틀그라운드']})
        self.assertEqual(raw['usages'], ['게임', '영상편집'])

    def test_no_program_no_change(self):
        raw, fixes = fix('사진 보정할 컴퓨터 150만원', ['영상편집'])
        self.assertEqual(raw['usages'], ['영상편집'])
        self.assertFalse([f for f in fixes if f['field'] == 'usages'])


if __name__ == '__main__':
    unittest.main()
