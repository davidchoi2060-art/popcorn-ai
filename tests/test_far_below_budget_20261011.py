"""예산이 가장 싼 판매 구성의 절반도 안 되면 카드를 내밀지 않는다 -- 2026-10-11 배포 뒤 일반 AI 비교.

「10만원」 질문에 480만원대 카드가 나왔다. 그 정도로 먼 카드는 「○○원부터 가능합니다」와 함께 보여도 설명과
어긋나 보인다. 절반 이하면 안내 한 줄만, 그보다 가까우면 지금처럼 가장 가까운 카드 한 장과 안내.
"""
import unittest

from api import sold_reco as S


def p(code, price, rank):
    return {'code': code, 'name': f'PC{code}', 'price': price, 'price_src': '현재 판매가', 'url': None, 'spec': {},
            'includes': None, 'fit': {'게임': {'level': f'L{rank}', 'rank': rank, 'blocked': []}}}


def pick(items, budget):
    return S.pick('게임', 1, budget, '이하', [], {i['code']: i for i in items})


class FarBelowBudget(unittest.TestCase):
    def test_far_below_gives_no_card_only_the_line(self):
        res = pick([p(1, 4800000, 1), p(2, 5200000, 2)], 100000)
        self.assertEqual(res['items'], [])
        self.assertEqual(res['empty_reason'], '예산이 너무 낮음')
        self.assertEqual(res['empty_note'], '이 작업은 4,800,000원부터 가능합니다. 예산을 조금 올리시면 보여 드릴게요.')

    def test_just_below_still_shows_the_nearest_card(self):
        res = pick([p(1, 1624400, 1)], 1200000)
        self.assertEqual([i['product_code'] for i in res['items']], [1])
        self.assertEqual(res['empty_note'], '이 작업은 1,624,400원부터 가능합니다.')

    def test_half_is_the_boundary(self):
        self.assertEqual(len(pick([p(1, 1000000, 1)], 500000)['items']), 1)    # 절반이면 카드 한 장
        self.assertEqual(pick([p(1, 1000000, 1)], 499999)['items'], [])        # 절반 미만이면 안내만

    def test_no_premium_card_when_nothing_is_shown(self):
        res = pick([p(1, 4800000, 1), p(2, 5200000, 2)], 100000)
        self.assertIsNone(S.premium_item(res, '게임', 1, 100000, '이하', [], {1: p(1, 4800000, 1), 2: p(2, 5200000, 2)}))


if __name__ == '__main__':
    unittest.main()
