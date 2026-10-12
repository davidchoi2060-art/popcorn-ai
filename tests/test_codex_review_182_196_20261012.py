"""코덱스 검수 #182~#196(2026-10-12 인계) 중 재현된 지적.

#188 현재 PC 에 «달고 싶은» 부품 요청까지 지워 조건 안내가 빠졌다.
#194 P2-1 장르 통칭 이름만 있으면 상담은 FHD 카드라 답하는데 추천은 카드를 비웠다.
#194 P2-2 한 마디의 견주는 질문(SSD 1TB 아니면 2TB) 때문에 정한 램 64GB 까지 빠졌다.
#194 P2-3 앞서 말한 큰 작업으로 카드는 고르는데 뒤 턴 기준 줄은 기본 작업이었다.
#195 P2-1·2 취소 기한의 「언제」로 배송 안내가 붙었고, 따로 물은 방문 설치 안내는 빠졌다.
#196 P2·P3 물음표 없는 부탁(「말씀해 주실래요.」)을 놓쳤고, 괄호 안 물음표를 질문으로 보았다.
"""
import ast
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api import talk, talk_rules as TR, reco_explore as X
from api import talk_pc_advice as PA
from tests.test_talk_reask_defaults_20261012 import ADVICE, parse
from tests import test_talk_schema_game_scope as GS


class CurrentPcWantedPart(unittest.TestCase):
    def test_part_to_add_to_current_pc_is_kept(self):
        t = "지금 쓰는 컴퓨터에 RTX 4070을 달고 싶어요."
        self.assertEqual(TR.unsupported_conditions(t, None, _all=True), ["그래픽카드 RTX 4070"])
        self.assertEqual(X.extract(t).get("gpu_model"), "RTX 4070")

    def test_owned_parts_are_still_dropped(self):
        t = "지금 쓰는 컴퓨터가 i5-8400에 GTX 1060인데 업그레이드할까요?"
        self.assertEqual(TR.unsupported_conditions(t, None, _all=True), [])
        self.assertNotIn("gpu_model", X.extract(t))          # 전에는 GTX 1060 · RTX 8400 으로 읽었다
        self.assertEqual(X.extract("지금 쓰는 컴퓨터가 GTX 1060인데 RTX 4070 들어간 걸로").get("gpu_model"), "RTX 4070")


class GenericGameName(unittest.TestCase):
    def test_generic_name_counts_as_unnamed(self):
        st = lambda names: SimpleNamespace(game=SimpleNamespace(names=names))
        self.assertTrue(TR.unnamed_game(st(["스팀 인디(통칭)"])))
        self.assertFalse(TR.unnamed_game(st(["메이플스토리"])))
        self.assertFalse(TR.unnamed_game(st(["스팀 인디(통칭)", "메이플스토리"])))

    def _sold_branch(self, names):
        v = GS.vocab(listed=list(names))
        grid_state, _ = GS.TS.validate_state({"usages": ["고사양 게임"], "budget_won": 1500000,
                                              "game": {"names": names}}, v)
        tree = ast.parse((GS.ROOT / "api/grid_public.py").read_text(encoding="utf-8-sig"))
        recommend = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "recommend")
        branch = next(n for n in ast.walk(recommend)
                      if isinstance(n, ast.If) and ast.unparse(n.test) == "RECO_SOURCE == 'sold'")
        cards = Mock(return_value=[])
        env = {"RECO_SOURCE": "sold", "state": grid_state, "game_usages": ["고사양 게임"],
               "game_grade": grid_state.game.grade, "card_sets": [], "notes": [],
               "is_game_usage": GS.TS.is_game_usage, "SOLD": SimpleNamespace(card_sets=cards),
               "_game_context": Mock(return_value={}), "assumed": [], "ai_estimated": [],
               "DEFAULT_RESOLUTION": GS.TS.DEFAULT_RESOLUTION, "ASSUMED_RESOLUTION": "game.resolution=1080p",
               "conn": None, "vocab": v, "body": None, "talk_notes": [],
               "_explore_input": lambda b, st, tn: (st, None), "TR": GS.TR}
        exec(compile(ast.Module(body=branch.body, type_ignores=[]), "grid sold branch", "exec"), env)
        return cards.call_args[0][1]

    def test_recommend_sends_game_target_for_generic_name(self):
        self.assertEqual(self._sold_branch(["스팀 인디(통칭)"]), ["고사양 게임"])
        self.assertEqual(self._sold_branch(["메이플스토리"]), [])     # 실제 게임은 기존 보류 그대로


class MixedWeighClause(unittest.TestCase):
    T = "램 64GB는 꼭 넣고 SSD는 1TB 아니면 2TB 중 뭐가 좋나요?"

    def test_fixed_part_survives_the_compared_part(self):
        self.assertEqual(TR.unsupported_conditions(self.T, None, _all=True), ["메모리 64GB"])
        w = X.extract(self.T)
        self.assertEqual(w.get("min_ram_gb"), 64)
        self.assertNotIn("min_ssd_gb", w)


class HeavyWorkFollowUp(unittest.TestCase):
    def test_follow_up_keeps_the_heavy_work_basis(self):
        seen = {}

        def fake_first(state, pref, *, is_game_usage, heavy=None, **k):
            seen["heavy"] = heavy
            return "기준 줄"
        with patch.object(talk.TD, "answer_first", fake_first):
            with patch.object(talk, "_trim_history", lambda h: [("user", "대용량 엑셀 돌리는 사무용 PC"),
                                                                ("assistant", "사무용 쾌적 기준으로 봤어요.")]):
                parse("조금 더 싸게", {"usages": ["사무·인강"]}, answer=ADVICE, topic=PA.TOPIC_BUILD,
                      reply="더 싼 쪽으로 볼게요.")
        self.assertEqual(seen.get("heavy"), X.heavy_levels("대용량 엑셀 돌리는 사무용 PC"))
        self.assertTrue(seen["heavy"])


class RefundAndDelivery(unittest.TestCase):
    def test_cancel_deadline_is_not_a_delivery_question(self):
        for t in ("배송 중에 취소는 언제까지 할 수 있어요?", "배송 중에 취소하면 환불은 얼마나 걸려요?"):
            self.assertEqual(TR.purchase_topics(t), ["refund"], t)

    def test_installation_asked_with_return_keeps_its_notice(self):
        self.assertEqual(set(TR.purchase_topics("반품 조건 알려주시고 방문 설치도 해 주나요?")), {"refund", "delivery"})
        self.assertEqual(set(TR.purchase_topics("배그PC 추천하고 배송일과 환불도 알려줘")), {"refund", "delivery"})


class AskDetection(unittest.TestCase):
    def test_polite_requests_without_question_mark(self):
        for r in ("어떤 용도로 쓰실지 말씀해 주실래요.", "용도를 알려 주시겠어요.", "어떤 용도인가요?"):
            self.assertTrue(talk._asks_already(r), r)

    def test_quoted_question_mark_is_not_a_question(self):
        for r in ("물음표(?)는 모르는 부분을 표시할 때 쓰기도 해요.", "SSD는 저장 장치예요."):
            self.assertFalse(talk._asks_already(r), r)


if __name__ == "__main__":
    unittest.main()
