"""대화 화면 시작 단추(2026-10-11 「입구는 하나, 그 안에 세 갈래」).

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
        self.assertEqual(talk.ParseBody(text="x", entry="game_pick").entry, "game_pick")
        for k in talk.ENTRY_KEYS:
            self.assertTrue(k.isascii())


if __name__ == "__main__":
    unittest.main()
