"""고객 문의 · 보관 견적 상세(api/admin_mvp3_consults.visitor_detail) — 2026-10-11 코덱스 검수 #81 지적 반영.

① 방문자 미확인 문의(`h<번호>`)를 직접 열어도 시험 문의는 기본으로 빠진다(목록과 같은 기준).
② 상한(문의 500 · 보관 200 · 구매 상담 100)을 넘는 방문자는 «최근» 것을 싣고 잘렸다고 알린다.
DB 없이 SQL 을 받아 두는 가짜 연결로 돈다.
"""
import datetime as dt
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException

from api import admin_mvp3_consults as MC


class R:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return self
    def all(self): return self.rows


def hit(i):
    return {"hit_id": i, "created_at": dt.datetime(2026, 10, 1) + dt.timedelta(minutes=i),
            "matched_terms": [], "unmatched_n": 0, "answer_kind": None, "llm_called": False,
            "intent_key": None, "is_test": False, "raw_text": None, "raw_purge_at": None,
            "shown_reply": None, "flags": None, "review_status": None}


class DB:
    def __init__(self, hits=(), quotes=(), inquiries=()):
        self.sql, self.params = [], []
        self.hits, self.quotes, self.inquiries = list(hits), list(quotes), list(inquiries)

    @contextmanager
    def connect(self): yield self

    def execute(self, sql, p=None):
        s = str(sql)
        self.sql.append(s)
        self.params.append(p or {})
        if "FROM talk_intent_hits h" in s:
            rows = self.hits
        elif "FROM mvp3_saved_recommendations" in s:
            rows = self.quotes
        elif "FROM purchase_inquiries" in s:
            rows = self.inquiries
        else:
            raise AssertionError(s)
        n = (p or {}).get("n")
        return R(rows[:n] if n else rows)


class Detail(unittest.TestCase):
    def test_unknown_visitor_hit_excludes_test_unless_asked(self):
        db = DB()
        with patch.object(MC, "engine", db):
            with self.assertRaises(HTTPException) as e:
                MC.visitor_detail("h7")
        self.assertEqual(e.exception.status_code, 404)
        self.assertIn("NOT " + MC.HIT_IS_TEST, db.sql[0])
        db = DB(hits=[hit(7)])
        with patch.object(MC, "engine", db):
            out = MC.visitor_detail("h7", include_test=True)
        self.assertNotIn("NOT " + MC.HIT_IS_TEST, db.sql[0])
        self.assertEqual(out["hits"], 1)

    def test_over_the_limit_keeps_the_newest_and_says_so(self):
        newest_first = [hit(i) for i in range(600, 0, -1)]
        db = DB(hits=newest_first)
        with patch.object(MC, "engine", db):
            out = MC.visitor_detail("u5")
        self.assertIn("ORDER BY h.created_at DESC", db.sql[0])
        self.assertEqual(out["hits"], MC.DETAIL_LIMITS["hits"])
        self.assertEqual(out["truncated"], {"hits": True, "saved": False, "inquiries": False})
        ats = [e["at"] for e in out["timeline"]]
        self.assertEqual(ats, sorted(ats))                     # 화면은 여전히 시간 순서
        iso = MC.iso
        self.assertEqual((ats[0], ats[-1]), (iso(hit(101)["created_at"]), iso(hit(600)["created_at"])))

    def test_under_the_limit_is_not_marked(self):
        with patch.object(MC, "engine", DB(hits=[hit(1), hit(2)])):
            out = MC.visitor_detail("u5")
        self.assertEqual(out["truncated"], {"hits": False, "saved": False, "inquiries": False})



class RetentionAndMasking(unittest.TestCase):
    """코덱스 검수 #84 · #85: AI 답 · 구매 상담 연락처도 보관 기한이 지나면 내보내지 않고,
    조회 권한에는 문의 내용 안의 연락처도 가린다."""

    def setUp(self):
        self.past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        self.future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)

    def test_expired_reads_naive_and_aware(self):
        from api.admin_raw_text import expired
        self.assertTrue(expired(self.past))
        self.assertTrue(expired(self.past.replace(tzinfo=None)))
        self.assertFalse(expired(self.future))
        self.assertFalse(expired(None))

    def inquiry(self, purge_at):
        return {"inquiry_id": 1, "inquiry_no": "PI-1", "created_at": None, "topic": "견적",
                "status": "대기", "contact_name": "홍길동", "contact_phone": "010-1234-5678",
                "contact_email": "abc@example.com", "message": "010-9876-5432 로 전화 주세요",
                "memo": "abc@example.com 메일 보냄", "user_id": 3, "quote_id": None,
                "product_code": None, "product_name": None, "assignee_name": None,
                "assignee_id": None, "updated_at": None, "purge_at": purge_at, "is_test": False}

    def test_viewer_role_sees_no_contact_inside_free_text(self):
        from api import admin_purchase_inquiries as PI
        row = PI._row(self.inquiry(self.future), full=False)
        self.assertNotIn("9876", row["message"])
        self.assertNotIn("abc@example.com", row["memo"])
        self.assertEqual(row["phone"], "010-****-5678")
        full = PI._row(self.inquiry(self.future), full=True)
        self.assertIn("010-9876-5432", full["message"])

    def test_expired_inquiry_hides_contact_and_message(self):
        from api import admin_purchase_inquiries as PI
        row = PI._row(self.inquiry(self.past), full=True)
        self.assertEqual((row["name"], row["phone"], row["email"], row["message"]), (None, None, None, None))
        self.assertTrue(row["contact_purged"])

    def test_expired_ai_reply_is_not_sent(self):
        from api import admin_talk_review as TRV
        r = {"hit_id": 1, "created_at": None, "raw_text": None, "raw_purge_at": None,
             "visitor_key": None, "matched_terms": [], "flags": [], "ai_reply": "AI 말",
             "shown_reply": "고객이 본 말", "answer": "자유 답", "answer_error": False,
             "question_key": None, "status": "미확인", "memo": None, "reviewed_at": None,
             "is_test": False, "reply_purge_at": self.past}
        row = TRV._row(r)
        self.assertEqual((row["ai_reply"], row["shown_reply"], row["answer"]), (None, None, None))
        self.assertTrue(row["reply_purged"])
        r["reply_purge_at"] = self.future
        self.assertEqual(TRV._row(r)["ai_reply"], "AI 말")


if __name__ == "__main__":
    unittest.main()
