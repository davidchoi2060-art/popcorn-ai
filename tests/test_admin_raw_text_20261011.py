"""관리자 화면에서 고객 질문 원문 보기 — 2026-10-11 품질관리 11번 (중헌 님 10/11 11:18 결정)."""
import pathlib
import unittest
from datetime import datetime, timedelta

from api import admin_raw_text as RT

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 3, 0, 0)


class RawView(unittest.TestCase):
    def test_kept_text_is_shown_as_is(self):
        v = RT.raw_view("램 32GB 이상, 연락처 [전화번호]", NOW + timedelta(days=1), now=NOW)
        self.assertEqual(v, {"text": "램 32GB 이상, 연락처 [전화번호]", "state": "kept", "label": None})

    def test_past_purge_date_is_not_sent(self):
        v = RT.raw_view("오래된 질문", NOW - timedelta(seconds=1), now=NOW)
        self.assertIsNone(v["text"])
        self.assertEqual((v["state"], v["label"]), ("purged", "원문 보관 기간 지남"))

    def test_missing_text(self):
        for raw in (None, "", "   "):
            v = RT.raw_view(raw, None, now=NOW)
            self.assertEqual((v["text"], v["state"]), (None, "none"))

    def test_notice_wording(self):
        self.assertEqual(RT.NOTICE, "고객 원문 · 개선 목적으로만 열람")


class Wiring(unittest.TestCase):
    def src(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_apis_send_question_and_notice(self):
        mc = self.src("api/admin_mvp3_consults.py")
        self.assertIn('"question": raw_view(h["raw_text"], h["raw_purge_at"])', mc)
        self.assertIn('"last_question": raw_view(', mc)
        self.assertEqual(mc.count('"raw_notice": RAW_NOTICE'), 2)
        tr = self.src("api/admin_talk_review.py")
        self.assertIn('"question": raw_view(r["raw_text"], r["raw_purge_at"])', tr)
        self.assertIn('"raw_notice": RAW_NOTICE', tr)
        tp = self.src("api/admin_talk_patterns.py")
        self.assertIn('"samples": samples.get(r["grp"], [])', tp)
        self.assertIn('"raw_notice": RAW_NOTICE', tp)
        self.assertIn('"raw_notice": RAW_NOTICE', self.src("api/admin_purchase_inquiries.py"))

    def test_screens_load_shared_renderer_and_drop_old_wording(self):
        for t in ("mvp3_consults", "talk_review", "talk_patterns", "purchase_inquiries"):
            s = self.src(f"templates/admin/{t}.html.j2")
            self.assertIn('/shared/admin2/raw-text.js', s, t)
            self.assertIn('RawText.notice(d.raw_notice)', s, t)
            self.assertNotIn("원문은 보여 주지 않습니다", s, t)
        js = self.src("mockups/shared/admin2/raw-text.js")
        self.assertIn("<details>", js)
        self.assertIn("esc(t)", js)

    def test_talk_review_column_counts_match(self):
        s = self.src("templates/admin/talk_review.html.j2")
        self.assertEqual(s.count('<th scope="col">'), 7)
        self.assertNotIn("colSpan=6", s)
        self.assertNotIn('colspan="6"', s)

    def test_spec_decision_recorded(self):
        s = self.src("docs/design/req/req-talk-patterns.md")
        self.assertIn("원문 열람 허용(중헌 님 10/11 11:18 결정)", s)


if __name__ == "__main__":
    unittest.main()
