"""고객 판매 PC 목록의 용도 수준표 공개 투영 (2026-10-21 찜목록 성능 차이 준비).

판정 조건(내부 지수 문턱값)은 고객 응답에 나가지 않고, 수준 이름·서열·작업 설명과 「실측 아님」 근거만 나간다.
"""
import unittest
from unittest.mock import patch

from fastapi import Response

from api import customer_pc_catalog as C

LEVELS = [
    {"usage": "게임", "level": "FHD", "level_rank": 2, "work": "FHD 중간 옵션", "conditions": "GPU 지수 60 이상"},
    {"usage": "게임", "level": "QHD", "level_rank": 3, "work": "QHD 높음 옵션", "conditions": "GPU 지수 100 이상"},
    {"usage": "사무용", "level": "", "level_rank": 1, "work": "x", "conditions": "c"},
    {"usage": "사무용", "level": "기본", "level_rank": 0, "work": "x", "conditions": "c"},
]


class PublicLevelsTest(unittest.TestCase):
    def test_projection_drops_conditions_and_bad_rows(self):
        out = C.public_levels(LEVELS)
        self.assertEqual(out, [{"usage": "게임", "level": "FHD", "rank": 2, "work": "FHD 중간 옵션"},
                               {"usage": "게임", "level": "QHD", "rank": 3, "work": "QHD 높음 옵션"}])
        self.assertTrue(all("conditions" not in x for x in out))

    def test_catalog_response_carries_levels_and_basis(self):
        with patch.object(C, "load", return_value=(LEVELS, {})), \
             patch.object(C, "public_codes", return_value=frozenset()), \
             patch.object(C, "_media_hints", return_value=frozenset()):
            body = C.read_catalog(Response())
        self.assertEqual([x["level"] for x in body["levels"]], ["FHD", "QHD"])
        self.assertIn("실측 아님", body["levels_basis"])
        self.assertNotIn("지수", repr(body["levels"]))
        self.assertEqual(body["items"], [])


if __name__ == "__main__":
    unittest.main()
