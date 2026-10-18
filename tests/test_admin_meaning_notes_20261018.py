"""숫자의 뜻을 화면이 말한다 — 2026-10-18 관리자 정리 기획 3묶음(A06 · A07 · A08 · A09). DB 없이 확인하는 것.

유입 성과의 mvp3 숫자마다 세는 기준을 응답이 함께 싣는지, 같은 기간 구매 상담 신청 수가 시험 자료를
빼고 세지는지, 조립 호환 규칙 화면의 파워 기준 상자가 읽기 전용이며 조립 판정과 고객 안내를 나눠
적는지, AI 답 점검과 판매 준비 현황의 안내가 코드가 하는 일과 맞는지를 본다.
실제 집계는 로컬 Postgres(alembic head + 시험 행)에서 맞춰 봤다(PR 본문).
"""
import pathlib
import unittest

from api import admin_funnel as F
from api import admin_page_intro
from api import power_rule
from api.admin_purchase_inquiries import IS_TEST, LINKS

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class FunnelMvp3(unittest.TestCase):
    def test_inquiries_exclude_test_rows_with_the_inquiry_screen_rule(self):
        seen = []

        class R:
            def mappings(self): return self
            def one(self): return {"n": 7, "quote_linked": 3, "test_excluded": 2}

        class C:
            def execute(self, sql, p=None):
                seen.append(str(sql))
                return R()

        out = F._mvp3_inquiries(C(), "LO", None, {"_dt_lo": "LO"})
        self.assertEqual(out, {"n": 5, "quote_linked": 3, "test_excluded": 2})
        sql = seen[0]
        self.assertIn(IS_TEST, sql)                 # 구매 상담 신청 화면과 같은 시험 자료 정의
        self.assertIn(f"{LINKS['quote']} AND NOT {IS_TEST}", sql)
        self.assertIn("i.created_at >= :_dt_lo", sql)

    def test_basis_says_what_the_numbers_are_not(self):
        text = " ".join(F.MVP3_BASIS)
        for word in ("보관한 시각", "인계한 시각", "서로 나누지 않습니다", "시험 자료 제외가 적용되지 않습니다",
                     "보관 목적은 기록하지 않습니다", "매출이 아닙니다", "구매 전환이 아닙니다"):
            self.assertIn(word, text)

    def test_screen_shows_basis_as_text(self):
        src = read("templates/admin/funnel.html.j2")
        self.assertIn('id="fnMvp3Basis"', src)
        self.assertIn("m.inquiries", src)
        self.assertIn("li.textContent = t", src)
        self.assertIn("구매 전환이 아닙니다", src)


class PowerBox(unittest.TestCase):
    def test_api_reads_the_power_rule_and_writes_nothing(self):
        from api import admin_power_basis as P

        class R:
            def __init__(self, v): self.v = v
            def mappings(self): return self
            def first(self): return self.v

        class C:
            def __init__(self, row): self.row, self.sql = row, []
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, p=None):
                self.sql.append(str(sql)); return R(self.row)

        class E:
            def __init__(self, row): self.c = C(row)
            def connect(self): return self.c

        from unittest.mock import patch
        e = E({"ref_offset": 200, "active": True, "blocking": True, "null_ref_mode": "skip"})
        with patch.object(P, "engine", e):
            out = P.power_basis()
        self.assertIn("rule_key = 'power'", e.c.sql[0])
        self.assertEqual(out["rule"]["ref_offset"], 200)
        self.assertEqual((out["fallback_offset_w"], out["advice_margin_w"]),
                         (power_rule.SYSTEM_POWER_OVERHEAD_W, power_rule.PSU_ADVICE_MARGIN_W))
        with patch.object(P, "engine", E(None)):
            self.assertIsNone(P.power_basis()["rule"])     # 규칙이 없으면 기본값으로 메우지 않는다
        src = read("api/admin_power_basis.py")
        for word in ("@router.post", "@router.put", "UPDATE ", "INSERT", "DELETE"):
            self.assertNotIn(word, src)

    def test_box_is_read_only_and_separates_the_two_bases(self):
        src = read("templates/admin/compat_rules.html.j2")
        box = src.split('id="cr-power"', 1)[1].split("</div>\n\n", 1)[0]
        self.assertNotIn("<button", box)
        self.assertNotIn("<input", box)
        fn = src.split("function renderPower", 1)[1].split("function applyData", 1)[0]
        self.assertNotIn("innerHTML", fn)
        self.assertIn("/api/admin/power-basis", fn)
        self.assertNotIn("method:", fn)
        self.assertIn("운영값 미확인", fn)
        self.assertIn("서로 다른 기준", fn)
        self.assertIn("loadPower();", src)


class Notes(unittest.TestCase):
    def test_talk_review_does_not_call_an_amount_a_violation(self):
        desc = admin_page_intro.INTRO["/admin2/talk-review"]["desc"]
        self.assertIn("점검 후보", desc)
        self.assertIn("위반으로 확정하지 않습니다", desc)

    def test_ai_really_gets_no_part_prices(self):
        src = read("api/talk_tools.py")
        part = src.split('item["parts"].append({', 1)[1].split("})", 1)[0]
        self.assertNotIn("price", part)

    def test_sale_readiness_says_past_holds_are_not_recorded(self):
        src = read("templates/admin/sale_readiness.html.j2")
        self.assertIn('id="srHoldNote"', src)
        self.assertIn("선택 보류", src)
        self.assertIn("기록하지 않습니다", src)
        self.assertNotIn("srHoldNote", read("mockups/shared/admin-sale-readiness.js"))   # 스크립트가 덮어쓰지 않는다


if __name__ == "__main__":
    unittest.main()
