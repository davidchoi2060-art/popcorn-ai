"""대화 화면 시작 단추(2026-10-11 코덱스 1816 보강6 의견 v1 -- 입구는 하나, 안에 시작 단추 셋).

화면 `mockups/mvp3/talk.js` 의 STARTERS 키와 서버 `api.talk.ENTRY_KEYS` 가 같아야 어느 단추로
시작했는지 로그로 센다. 하나만 늘리면 그 단추는 조용히 「-」로 찍힌다.
"""
import pathlib
import re
import unittest

from api import talk

ROOT = pathlib.Path(__file__).resolve().parents[1]


class StarterKeys(unittest.TestCase):
    def test_screen_and_server_keys_match(self):
        js = (ROOT / "mockups/mvp3/talk.js").read_text(encoding="utf-8")
        block = js[js.index("const STARTERS=["):js.index("];", js.index("const STARTERS=["))]
        keys = set(re.findall(r"key:'([a-z_]+)'", block))
        self.assertEqual(keys, set(talk.ENTRY_KEYS))

    def test_entry_is_optional_and_ascii(self):
        self.assertIsNone(talk.ParseBody(text="x").entry)
        self.assertEqual(talk.ParseBody(text="x", entry="new_pc").entry, "new_pc")
        for k in talk.ENTRY_KEYS:
            self.assertTrue(k.isascii())

    def test_landing_has_no_start_gateway(self):
        # 2026-10-16 중헌 님 「첫화면 게이트웨이를 세군대로 나누는게 의미가 없어 … 예전처럼 단일 화면으로」.
        # 처음 화면(index.html)은 갈래 없이 상담 화면을 연다. 시작 단추 셋은 대화 화면(talk.js STARTERS)에만 남는다.
        app = (ROOT / "mockups/mvp3/app.js").read_text(encoding="utf-8")
        self.assertNotIn("GATEWAY_PATHS", app)
        self.assertNotIn("talk.html?start=", app)
        self.assertNotRegex(app, r"data-action=\"gateway|'gateway-")

    def test_starters_do_not_lead_with_games(self):
        # 사장님 2026-10-11 「게임.. 뭐 이런건 빼고」 -- 시작 단추가 게임 탐색을 권하지 않는다.
        js = (ROOT / "mockups/mvp3/talk.js").read_text(encoding="utf-8")
        block = js[js.index("const STARTERS=["):js.index("];", js.index("const STARTERS=["))]
        self.assertNotRegex(block, "게임|겜")


if __name__ == "__main__":
    unittest.main()
