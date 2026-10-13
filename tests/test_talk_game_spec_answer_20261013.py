"""「게임별로 필요한 성능을 좀 알려줘」에 「확인된 정보가 없어 안내하기 어렵습니다」가 나갔다 -- 2026-10-13 사장님 캡처.

성능·사양을 묻는 말은 PC 질문이다. 게임 소개 경로([B] 게임 답)는 사양 수치를 말하지 못하게 막혀 있어서, 거기로 가면 답을
못 한다. 이런 문장은 일반 AI 처럼 먼저 설명하는 PC 설명 경로(talk_pc_advice)로 보낸다(2026-10-11 사장님 「LLM 이 먼저 답하고
아래에 우리 제품」). 게임 잡담(「롤 재밌어?」)은 그대로 게임 답이다.
"""
import unittest
from unittest.mock import patch

from api import talk_answer as TA, talk_pc_advice as PA, talk_schema as TS
from tests.test_talk_rules_20261010 import vocab


def _route(sentence, prev=None):
    seen = {}

    def fake_advise(conn_factory, s, labels, res, **kw):
        seen.update(path="advice", topic=kw.get("topic"), games=kw.get("games"), labels=labels)
        res.kind, res.answer = "pc_advice", "설명"
        return res
    with patch.object(PA, "advise", fake_advise), \
            patch.object(TA, "collect_evidence", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("game path"))):
        res = TA.answer_path(lambda: None, sentence, vocab(), prev_state=prev, history=[("assistant", "안녕하세요")])
    if not seen:
        seen["path"] = "game" if res.error and "answer path error" in res.error else "none"
    return seen


class GameSpecGoesToAdvice(unittest.TestCase):
    def test_owner_capture_sentence(self):
        r = _route("게임별로 필요한 성능을 좀 알려줘")
        self.assertEqual(r["path"], "advice")
        self.assertEqual(r["topic"], PA.TOPIC_BUILD)

    def test_named_game_spec(self):
        r = _route("배그 권장 사양 알려줘")
        self.assertEqual(r["path"], "advice")
        self.assertEqual(r["games"], ["배틀그라운드"])

    def test_previous_games_carried(self):
        prev = TS.TalkState(usages=["게임"], game=TS.GameState(names=["리그 오브 레전드", "발로란트"]))
        r = _route("게임별로 필요한 성능을 좀 알려줘", prev)
        self.assertEqual(r["games"], ["리그 오브 레전드", "발로란트"])

    def test_game_smalltalk_stays_game_answer(self):
        self.assertEqual(_route("롤 재밌어?")["path"], "game")

    def test_part_compare_stays_part(self):
        self.assertEqual(PA.topic_of("RTX 5060이랑 5060 Ti 성능 차이가 뭐예요?", vocab()), PA.TOPIC_PART)


if __name__ == "__main__":
    unittest.main()
