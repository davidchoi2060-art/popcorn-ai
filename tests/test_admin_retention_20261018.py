"""보관 기한 · 파기 이력(api/admin_retention) — 2026-10-18 관리자 정리 기획 A05(2묶음). DB 없이 확인하는 것.

기한 지남과 실제 파기를 같은 말로 부르지 않는지, 「값 남음」 셈이 파기 작업의 대상 조건과 같은
정의를 쓰는지, 화면에 실행 버튼이나 고정 보유 일수가 없는지를 본다. 실제 집계는 로컬 Postgres
(alembic head + 시험 행)에서 파기 작업 미리보기 건수와 맞춰 봤다(PR 본문).
"""
import datetime as dt
import pathlib
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from api import admin_nav, admin_page_intro
from api import admin_retention as AR
from api import retention_purge as RP

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)


def run(**kw):
    base = {"run_id": 1, "moment": "auto", "dry_run": True, "counts": {}, "error": None,
            "started_at": NOW, "finished_at": NOW}
    return {**base, **kw}


class Runs(unittest.TestCase):
    def test_preview_and_real_runs_are_named_apart(self):
        self.assertIn("미리보기", AR._run(run(dry_run=True))["kind_label"])
        self.assertIn("실제 비움", AR._run(run(dry_run=False))["kind_label"])

    def test_unfinished_run_is_not_called_done(self):
        r = AR._run(run(finished_at=None))
        self.assertEqual(r["state"], "unknown")
        self.assertIn("미확인", r["state_label"])
        self.assertEqual(AR._run(run(error="X: y"))["state"], "failed")

    def test_counts_keep_only_numbers_and_name_every_target(self):
        r = AR._run(run(counts={"talk_raw": 3, "inquiry_memo": 0, "odd": "x"}))
        self.assertEqual([(c["key"], c["n"]) for c in r["counts"]], [("talk_raw", 3), ("inquiry_memo", 0)])
        self.assertEqual(r["counts"][0]["label"], "고객 문의 원문")


class Summary(unittest.TestCase):
    def test_every_purge_target_has_screen_info(self):
        self.assertEqual({t[0] for t in RP.TARGETS}, set(AR.TARGET_INFO))

    def test_holding_count_uses_the_purge_job_condition(self):
        seen = []

        class R:
            def __init__(self, v): self.v = v
            def mappings(self): return self
            def one(self): return self.v
            def scalar(self): return self.v

        class C:
            def execute(self, sql, p=None):
                seen.append(str(sql))
                if str(sql).startswith("SELECT count(*) FROM"):
                    return R(2)
                return R({"total": 9, "valid": 4, "soon": 1, "expired": 4, "no_deadline": 0,
                          "purged": 2, "last_purged_at": NOW})

        out = AR._summary(C(), NOW)
        for name, target, _ in RP.TARGETS:
            table, where = RP._split(target)
            self.assertIn("SELECT count(*) FROM %s WHERE %s" % (table, where), seen)
        row = out[0]
        self.assertEqual((row["expired_holding"], row["expired_cleared"]), (2, 2))
        talk = [x for x in out if x["key"] == "talk_raw"][0]
        self.assertFalse(talk["purge_recorded"])
        self.assertIsNone(talk["purged"])          # 지운 시각 칸이 없는 대상은 파기 건수를 지어내지 않는다


class Endpoint(unittest.TestCase):
    def test_reads_only(self):
        src = (ROOT / "api/admin_retention.py").read_text(encoding="utf-8")
        self.assertNotIn("@router.post", src)
        self.assertNotIn("@router.put", src)
        self.assertNotIn("UPDATE ", src)
        self.assertNotIn("RP.purge(", src)


class Screen(unittest.TestCase):
    def tpl(self):
        return (ROOT / "templates/admin/retention.html.j2").read_text(encoding="utf-8")

    def test_no_action_buttons_or_fixed_days(self):
        src = self.tpl().split("#}", 1)[1]          # 머리 주석(하지 않는 일을 적은 곳)은 빼고 본다
        for word in ("180일", "실행하기", "다시 실행", "기한 연장", "method:'POST'", 'method:"POST"', "innerHTML"):
            self.assertNotIn(word, src)

    def test_columns_match_empty_rows(self):
        src = self.tpl()
        heads = src.split("<thead>")
        self.assertEqual(heads[1].split("</thead>")[0].count("<th "), 7)
        self.assertEqual(heads[2].split("</thead>")[0].count("<th "), 6)
        self.assertIn('colspan="7"', src)
        self.assertIn('colspan="6"', src)
        self.assertIn("msgRow('rtSummary',7", src)
        self.assertIn("msgRow('rtRuns',6", src)

    def test_menu_and_intro(self):
        hrefs = [i[1] for g in admin_nav.NAV for i in g[2]]
        self.assertIn("/admin2/retention", hrefs)
        self.assertIn("/admin2/retention", admin_page_intro.INTRO)
        groups = admin_nav.new_admin_nav("/admin2/retention")
        self.assertEqual([g["label"] for g in groups if g["active"]], ["주문 운영"])
        self.assertNotIn("180일", admin_page_intro.INTRO["/admin2/purchase-inquiries"]["desc"])

    def test_expired_is_not_called_purged_on_other_screens(self):
        pi = (ROOT / "templates/admin/purchase_inquiries.html.j2").read_text(encoding="utf-8")
        self.assertIn("실제 파기 여부 미확인", pi)
        self.assertIn("it.purged_at", pi)
        mc = (ROOT / "templates/admin/mvp3_consults.html.j2").read_text(encoding="utf-8")
        self.assertIn("c.purged_at", mc)


if __name__ == "__main__":
    unittest.main()
