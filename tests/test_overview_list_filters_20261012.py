"""「운영 현황」 카드가 붙이는 조건(status= · state=)을 목록 화면이 읽는다(2026-10-12).

카드의 숫자와 도착한 목록의 조건이 같아야 한다(코덱스 대시보드 기획안 v1 §3).
브라우저 확인은 PR 설명에 적었다 — 여기서는 각 화면이 그 키를 읽고, 목록에 있는 값만 받는지 본다.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "templates/admin"


class OverviewListFilters(unittest.TestCase):
    def check(self, name, key, guard):
        t = (ROOT / name).read_text(encoding="utf-8")
        self.assertIn(f"URLSearchParams(location.search).get('{key}')", t)
        self.assertIn(guard, t)

    def test_purchase_inquiries_reads_status_only_from_options(self):
        self.check("purchase_inquiries.html.j2", "status", "sel.options")

    def test_member_reviews_reads_state_only_from_chips(self):
        self.check("member_reviews.html.j2", "state", ".mr-chip[data-filter=")

    def test_talk_patterns_reads_status_only_from_chips(self):
        self.check("talk_patterns.html.j2", "status", "#tp-filters [data-f=")


if __name__ == "__main__":
    unittest.main()
