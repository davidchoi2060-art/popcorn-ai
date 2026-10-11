"""홈 「고객 화면 문의」 수가 모든 고객 화면 합계라는 사실을 숫자 옆에 밝힌다(2026-10-11 개편 17번).

문의 기록에는 어느 고객 화면에서 왔는지가 없어 mvp2 문의가 함께 세어진다(관리자 결과 §2).
"""
import pathlib
import unittest

from api import admin_ui_home as H

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = {"flow": {"sessions_today": 3, "sessions_done": 1, "sessions_drop": 2,
                 "mvp3_inquiries_today": 12, "mvp3_saved_today": 2}}


class HomeInquiryScope(unittest.TestCase):
    def test_count_carries_scope_and_reason(self):
        f = H._flow(DASH, None, None, "x")
        self.assertEqual(f["mvp3"]["value_fmt"], "12")
        self.assertEqual(f["mvp3_scope"], "모든 고객 화면 합계")
        self.assertIn("mvp2", f["mvp3"]["reason"])
        self.assertIn("나눠 셀 수 없습니다", f["mvp3"]["reason"])

    def test_template_shows_scope_next_to_number(self):
        t = (ROOT / "templates/admin/home.html.j2").read_text(encoding="utf-8")
        self.assertIn("{{ flow.mvp3_scope }}", t)


if __name__ == "__main__":
    unittest.main()
