"""예산이 아무리 낮아도 가장 가까운 PC 한 장과 «예산과 맞지 않음» 안내 -- 2026-10-12 사장님 결정.

「예산과 안맞으면 예산과 맞지 않음을 그냥 공지하고 추천PC를 제시해」. 예전(#167)에는 예산이 가장 싼 판매 구성의
절반도 안 되면(「10만원」에 480만원) 카드 없이 안내 한 줄만 냈다.
"""
import unittest

from api import sold_reco as S


def p(code, price, rank):
    return {'code': code, 'name': f'PC{code}', 'price': price, 'price_src': '현재 판매가', 'url': None, 'spec': {},
            'includes': None, 'fit': {'게임': {'level': f'L{rank}', 'rank': rank, 'blocked': []}}}


def pick(items, budget):
    return S.pick('게임', 1, budget, '이하', [], {i['code']: i for i in items})


class FarBelowBudget(unittest.TestCase):
    def test_far_below_still_shows_the_nearest_card(self):
        res = pick([p(1, 4800000, 1), p(2, 5200000, 2)], 100000)
        self.assertEqual([i['product_code'] for i in res['items']], [1])
        self.assertEqual(res['empty_reason'], '예산 안 상품 없음')
        self.assertEqual(res['empty_note'], '이 작업은 4,800,000원부터 가능합니다.')

    def test_just_below_still_shows_the_nearest_card(self):
        res = pick([p(1, 1624400, 1)], 1200000)
        self.assertEqual([i['product_code'] for i in res['items']], [1])
        self.assertEqual(res['empty_note'], '이 작업은 1,624,400원부터 가능합니다.')

    def test_no_half_boundary(self):
        self.assertEqual(len(pick([p(1, 1000000, 1)], 500000)['items']), 1)
        self.assertEqual(len(pick([p(1, 1000000, 1)], 499999)['items']), 1)


if __name__ == '__main__':
    unittest.main()
