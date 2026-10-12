"""취소·환불·반품 안내 주제 -- 2026-10-12 개발 서버 재점검(모델 OpenAI luna).

「배송 중에 취소할 수 있어?」에 취소가 아니라 「배송과 설치 안내는 쇼핑몰에서 해요」가 나갔다.
취소·환불·반품은 가게 정책이 정해지지 않았으니 일반 안내(설명)는 그대로 두고 「쇼핑몰에서 확인」 안내를 낸다.
"""
import unittest

from api import talk_rules as TR


class RefundTopic(unittest.TestCase):
    def test_cancel_during_delivery_is_a_refund_question(self):
        self.assertEqual(TR.purchase_topics("배송 중에 취소할 수 있어?"), ["refund"])
        notes = TR.topic_notices("배송 중에 취소할 수 있어?")
        self.assertEqual(len(notes), 1)
        self.assertIn("취소·환불·반품", notes[0])
        self.assertNotIn("배송과 설치", notes[0])

    def test_refund_and_return(self):
        self.assertEqual(TR.purchase_topics("환불 언제 들어와?"), ["refund"])
        self.assertEqual(TR.purchase_topics("반품하면 택배비 내요?"), ["refund"])

    def test_delivery_time_still_answered_with_refund(self):
        self.assertEqual(set(TR.purchase_topics("배그PC 추천하고 배송일과 환불도 알려줘")), {"refund", "delivery"})
        self.assertEqual(TR.purchase_topics("배송은 얼마나 걸려요?"), ["delivery"])

    def test_admin_can_write_the_refund_notice(self):
        self.assertEqual(TR.topic_label("refund"), "취소·환불·반품")


if __name__ == "__main__":
    unittest.main()
