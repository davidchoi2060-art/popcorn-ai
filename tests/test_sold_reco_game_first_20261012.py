"""게임과 다른 용도를 함께 말하면 게임 묶음이 먼저 온다 -- 2026-10-12 사장님 시험.

「배그·롤 · 사무용 · 150만원」에서 사무용 묶음이 먼저 와 그래픽카드 없는 오피스 PC가 첫 카드가 됐고,
첫 묶음 기준으로 붙는 「150만원 안에는 맞는 PC가 없어요」 안내도 빠졌다.
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from api import sold_reco as S


class GameFirst(unittest.TestCase):
    def test_game_target_comes_before_other_usages(self):
        with mock.patch.object(S, 'game_min_rank', return_value=2):
            targets = S._targets(SimpleNamespace(game=None), ['고사양 게임', '캐주얼 게임'], ['사무용'], [], None, [])
        self.assertEqual([t[1] for t in targets][0], '게임')
        self.assertEqual(targets[0], ('고사양 게임', '게임', 2))
        self.assertEqual(len([t for t in targets if t[1] == '게임']), 1)

    def test_without_game_order_is_unchanged(self):
        targets = S._targets(SimpleNamespace(game=None), [], ['사무용'], [], None, [])
        self.assertEqual([t[0] for t in targets], ['사무용'])


if __name__ == '__main__':
    unittest.main()
