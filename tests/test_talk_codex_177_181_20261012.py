"""코덱스 #177~#181 소스 검수(2026-10-12) 후보 셋을 고정한다.

P2-4 「100만원 PC 환불 언제 들어와?」의 금액을 새 PC 예산으로 읽어 일반 환불 설명이 비었다.
P2-5 「노트북은 판매점마다 A/S 정책이 달라요.」를 노트북 취급 중복 문장으로 보고 지웠다.
P3-1 「그럼에도 …」의 「그럼」만 지워 「에도 …」가 됐다.
"""
import unittest

from api import talk, talk_pc_advice as PA, talk_rules as TR
from tests.test_talk_pc_routing_20261012 import vocab


class OrderAmountIsNotBudget(unittest.TestCase):
    def test_refund_with_amount_is_general(self):
        for s in ("100만원 PC 환불 언제 들어와?", "150만원 컴퓨터 배송 언제 와요?"):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), PA.TOPIC_GENERAL)

    def test_budget_pc_still_build(self):
        self.assertEqual(PA.topic_of("화이트 감성으로 100만원 PC", vocab()), PA.TOPIC_BUILD)


class LaptopPolicyKept(unittest.TestCase):
    def test_store_policy_sentence_stays(self):
        out = TR.with_laptop_notice("노트북은 판매점마다 A/S 정책이 달라요. 들고 다니실 일이 많으신가요?")
        self.assertEqual(out, TR.LAPTOP_NOTICE + " 노트북은 판매점마다 A/S 정책이 달라요. 들고 다니실 일이 많으신가요?")

    def test_repeat_still_dropped(self):
        for r in ("노트북은 판매하지 않아요.", "노트북은 취급하지 않습니다.", "노트북은 안 팔아요."):
            with self.subTest(r=r):
                self.assertEqual(TR.with_laptop_notice(r + " 용도를 알려 주세요."), TR.LAPTOP_NOTICE + " 용도를 알려 주세요.")


class ConnectiveWholeWord(unittest.TestCase):
    def test_geureomedo_kept_whole(self):
        out = talk.drop_pc_push("혹시 컴퓨터 맞추실 생각 있으세요? 그럼에도 음악은 즐거움을 줄 수 있어요.")
        self.assertEqual(out, "그럼에도 음악은 즐거움을 줄 수 있어요.")

    def test_connective_with_comma_or_space_dropped(self):
        self.assertEqual(talk.drop_pc_push("혹시 컴퓨터 맞추실 생각 있으세요? 그럼, 차 한잔 어떠세요."), "차 한잔 어떠세요.")
        self.assertEqual(talk.drop_pc_push("혹시 컴퓨터 맞추실 생각 있으세요? 그리고 산책도 좋아요."), "산책도 좋아요.")


if __name__ == "__main__":
    unittest.main()
