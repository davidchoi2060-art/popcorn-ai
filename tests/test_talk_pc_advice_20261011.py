"""PC 구성 질문에 일반 AI 처럼 먼저 설명한다(api/talk_pc_advice) -- 2026-10-11 사장님 원칙."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA, talk_schema as TS
from tests.test_talk_rules_20261010 import vocab as base_vocab


def vocab():
    v = base_vocab()
    v.usages = list(v.usages) + [("개발", ["개발", "코딩"])]
    return v


class Routing(unittest.TestCase):
    def test_pc_questions_get_advice(self):
        for s, want in (("개발자용 PC를 가장 저렴하게 추천해줘", ["개발"]),
                        ("웹 개발, 예산은 최대한 싸게", ["개발"]),
                        ("컴퓨터 하나 추천해 주세요", [])):
            with self.subTest(s=s):
                self.assertEqual(PA.wants_advice(s, vocab()), want)

    def test_not_advice(self):
        for s in ("개발이요", "오늘 날씨 어때", "배송은 언제 와요"):
            with self.subTest(s=s):
                self.assertIsNone(PA.wants_advice(s, vocab()))

    def test_game_talk_stays_on_game_path(self):
        seen = []
        with patch.object(PA, "advise", lambda *a, **k: seen.append(1)), \
             patch.object(TA, "is_game_related", lambda *a: True):
            TA.answer_path(lambda: None, "요즘 게임 추천해줘", vocab())
        self.assertEqual(seen, [])

    def test_answer_path_routes_pc_question(self):
        out = SimpleNamespace(text="개발에는 램과 SSD가 중요해요. 그래픽카드는 아껴도 돼요.", provider="t",
                              model="t", cost_usd=0, tokens_in=1, tokens_out=1, log_id=None)
        with patch.object(PA.llm, "call", lambda *a, **k: out), \
             patch.object(PA, "basis_lines", lambda conn, labels: []):
            class C:
                def __enter__(self): return self
                def __exit__(self, *a): return False
            r = TA.answer_path(C, "개발자용 PC를 가장 저렴하게 추천해줘", vocab())
        self.assertEqual(r.kind, "pc_advice")
        self.assertIn("램과 SSD", r.answer)
        self.assertIsNone(r.error)


class Cleaning(unittest.TestCase):
    def test_drops_prices_models_questions(self):
        raw = ("개발용은 CPU와 램이 중요해요. 예산은 60만원대면 충분해요. RTX 4060이면 넉넉해요."
               " 재고는 바로 확인돼요. 어떤 개발을 하시나요? 도커를 많이 쓰면 램 32GB가 편해요.")
        body, dropped = PA.clean(raw)
        self.assertEqual(body, "개발용은 CPU와 램이 중요해요. 도커를 많이 쓰면 램 32GB가 편해요.")
        self.assertEqual([d["reason"] for d in dropped], ["price", "part model", "stock", "question"])

    def test_prompt_carries_our_basis_without_internal_indices(self):
        class Conn:
            def execute(self, *a, **k):
                return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [
                    {"usage": "개발", "level": "기본", "level_rank": 1,
                     "work": "웹·스크립트 개발 (VS Code·브라우저·로컬 서버)",
                     "conditions": "CPU 멀티 지수 12,000 이상 · 램 16GB 이상 · SSD 480GB 이상"}]))
        lines = PA.basis_lines(Conn(), ["개발"])
        self.assertEqual(lines, ["- 개발 기본: 웹·스크립트 개발 (VS Code·브라우저·로컬 서버)"
                                 " (램 16GB 이상 · SSD 480GB 이상) <- 추천 카드의 최소 기준"])
        prompt = PA.build_prompt("개발자용 PC 싸게", lines)
        self.assertIn("램 16GB 이상", prompt)
        self.assertNotIn("멀티 지수", prompt)


if __name__ == "__main__":
    unittest.main()


class Topics(unittest.TestCase):
    """코덱스 담당의견-최소차이-v1 §3: 부품 질문·쓰던 PC 고민도 설명을 먼저 하고, 구매 절차를 강제로 열지 않는다."""

    def test_topics(self):
        for s, want in (("SSD랑 메모리 차이가 뭐예요", PA.TOPIC_PART),
                        ("그래픽카드는 왜 필요해요?", PA.TOPIC_PART),
                        ("지금 쓰는 PC가 느려요", PA.TOPIC_UPGRADE),
                        ("램 업그레이드 하고 싶어요", PA.TOPIC_UPGRADE),
                        ("개발자용 PC를 가장 저렴하게 추천해줘", PA.TOPIC_BUILD),
                        ("모니터 추천해줘", None), ("오늘 날씨 어때", None), ("개발이요", None)):
            with self.subTest(s=s):
                self.assertEqual(PA.topic_of(s, vocab()), want)

    def test_prompt_follows_topic(self):
        self.assertIn("역할과 차이", PA.build_prompt("SSD랑 메모리 차이가 뭐예요", [], topic=PA.TOPIC_PART))
        self.assertIn("먼저 살펴볼 부품", PA.build_prompt("PC가 느려요", [], topic=PA.TOPIC_UPGRADE))
