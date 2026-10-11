"""잡담 답에서 앞 문장을 걷은 뒤 「혹은」 같은 이어 주는 말로 시작하지 않는다 -- 2026-10-12 개발 서버 확인 결과를 고정한다.

「심심해」의 답이 「혹은 책이나 음악, 산책 같은 것들도 좋고요.」로 시작했다(앞의 게임 권유 문장이 걸러진 흔적).
"""
import unittest

from api import talk


class DanglingConnective(unittest.TestCase):
    def test_after_game_sentence_dropped(self):
        out = talk.drop_game_nudge("게임 한 판 해 보시는 건 어떠세요? 혹은 책이나 음악, 산책 같은 것들도 좋고요. 무엇을 생각하고 계세요?")
        self.assertEqual(out, "책이나 음악, 산책 같은 것들도 좋고요. 무엇을 생각하고 계세요?")

    def test_after_pc_push_dropped(self):
        out = talk.drop_pc_push("혹시 컴퓨터 맞추실 생각 있으세요? 그리고 따뜻한 차 한잔도 좋아요.")
        self.assertEqual(out, "따뜻한 차 한잔도 좋아요.")

    def test_kept_when_nothing_dropped(self):
        r = "산책도 좋아요. 아니면 음악을 들어 보세요."
        self.assertEqual(talk.drop_game_nudge(r), r)
        self.assertEqual(talk.drop_pc_push(r), r)


if __name__ == "__main__":
    unittest.main()
