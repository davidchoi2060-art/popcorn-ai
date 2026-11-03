"""용도별 최소 사양 영향 미리보기 — 활성·연산 반영 (2026-11-03 ADMIN-REMAINING-BATCH1-1B).

미리보기·목록의 통과 수는 «이 하한 한 줄» 기준이고, 견적 엔진(api/usage_floors.py)과 같은
규칙으로 센다: 비활성 줄은 엔진이 읽지 않으므로 거르지 않는다(통과 = 슬롯 후보 전체),
활성이면 op(gte/lte)를 그대로, 값 NULL 은 불통과.

DB 검사는 루프백 Postgres 안의 격리 스키마에서만 돈다(실제 하한·상품에 닿지 않는다).
CI(POPCORN_CI=1)에서는 연결이 안 되면 건너뛰지 않고 실패한다.
"""
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from fastapi import HTTPException                                 # noqa: E402

from api import admin_usage_floors as AUF                         # noqa: E402

TEMPLATE = (ROOT / "templates/admin/usage_floors.html.j2").read_text(encoding="utf-8")


def _db_url():
    url = os.environ.get("DATABASE_URL") or ""
    from sqlalchemy.engine import make_url
    try:
        u = make_url(url)
    except Exception:                                               # noqa: BLE001
        return None
    if u.host not in ("127.0.0.1", "localhost", "::1"):
        return None
    from sqlalchemy import create_engine, text
    try:
        with create_engine(u).connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:                                               # noqa: BLE001
        if os.environ.get("POPCORN_CI") == "1":
            raise
        return None
    return u


# GPU 후보 5개(전원 300·550·750·NULL + 품절 1개) · RAM 후보 3개(8·16·32) · SSD 후보 0개.
CANDIDATES = [
    ("GPU", 3, 300, None), ("GPU", 2, 550, None), ("GPU", 1, 750, None), ("GPU", 4, None, None),
    ("GPU", 0, 900, None),
    ("RAM", 5, None, 8), ("RAM", 5, None, 16), ("RAM", 5, None, 32),
]
FLOORS = [  # floor_id, usage_key, slot, field, op, value, active, sort
    (1, "game", "GPU", "required_power_watt", "gte", 550, True, 1),
    (2, "game", "RAM", "capacity_gb", "gte", 16, True, 2),
    (3, "office", "RAM", "capacity_gb", "gte", 16, False, 3),
    (4, "office", "RAM", "capacity_gb", "lte", 16, True, 4),
    (5, "game", "SSD", "capacity_gb", "gte", 500, True, 5),
]


@unittest.skipUnless(_db_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다(CI 에서는 실패)")
class FloorPreviewOnPostgres(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine, text
        self.text = text
        self.url = _db_url()
        self.schema = "floor_prev_t_" + uuid.uuid4().hex[:12]
        with create_engine(self.url).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % self.schema))
        self.engine = create_engine(self.url, connect_args={"options": "-csearch_path=%s" % self.schema})
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE v_recommendation_candidates (part_type TEXT, stock_qty INTEGER,"
                           " required_power_watt INTEGER, capacity_gb INTEGER)"))
            c.execute(text("CREATE TABLE usage_floors (floor_id BIGINT PRIMARY KEY, usage_key TEXT,"
                           " usage_label TEXT, match_terms TEXT[], slot TEXT, field TEXT, op TEXT, value INTEGER,"
                           " label TEXT, detail_fmt TEXT, active BOOLEAN NOT NULL, sort_order INTEGER,"
                           " created_at TIMESTAMP DEFAULT now())"))
            for pt, st, w, gb in CANDIDATES:
                c.execute(text("INSERT INTO v_recommendation_candidates VALUES (:p, :s, :w, :g)"),
                          {"p": pt, "s": st, "w": w, "g": gb})
            for fid, key, slot, field, op, v, act, so in FLOORS:
                c.execute(text("INSERT INTO usage_floors (floor_id, usage_key, usage_label, match_terms, slot,"
                               " field, op, value, label, active, sort_order) VALUES"
                               " (:i, :k, :k, ARRAY[:k], :s, :f, :o, :v, :k, :a, :so)"),
                          {"i": fid, "k": key, "s": slot, "f": field, "o": op, "v": v, "a": act, "so": so})
        self.log = mock.Mock(return_value=1)
        self.reload = mock.Mock(return_value=0)
        self.patches = [mock.patch.object(AUF, "engine", self.engine),
                        mock.patch.object(AUF, "current_operator", lambda: {"role": "owner"}),
                        mock.patch("api.admin_orders._log", self.log),
                        mock.patch.object(AUF.UF, "reload", self.reload)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(self.url).begin() as c:
            c.execute(self.text('DROP SCHEMA "%s" CASCADE' % self.schema))

    def preview(self, fid, value, active=True):
        return AUF.update_floor(fid, AUF.FloorBody(value=value, active=active, preview=True))["impact"]

    def floor_row(self, fid):
        with self.engine.connect() as c:
            return tuple(c.execute(self.text("SELECT value, active FROM usage_floors WHERE floor_id=:i"),
                                   {"i": fid}).one())

    def test_value_change_counts_like_before(self):
        imp = self.preview(1, 750)
        # 재고 있는 GPU 4개(품절 제외) 중 550↑ 2개 → 750↑ 1개. NULL 전원은 불통과.
        self.assertEqual((imp["pass_before"], imp["pass_after"], imp["slot_total"]), (2, 1, 4))
        self.assertTrue(imp["buildable_after"])

    def test_deactivating_passes_whole_slot(self):
        imp = self.preview(1, 550, active=False)
        self.assertEqual((imp["pass_before"], imp["pass_after"]), (2, 4))
        self.assertEqual(imp["pass_after"], imp["slot_total"])
        self.assertEqual((imp["active_before"], imp["active_after"]), (True, False))
        self.assertIn("이 줄로는 거르지 않습니다", imp["note"])

    def test_activating_starts_from_whole_slot(self):
        imp = self.preview(3, 16, active=True)
        self.assertEqual((imp["pass_before"], imp["pass_after"], imp["slot_total"]), (3, 2, 3))
        self.assertNotIn("이 줄로는 거르지 않습니다", imp["note"])

    def test_lte_floor_counts_with_lte(self):
        imp = self.preview(4, 8)
        self.assertEqual((imp["pass_before"], imp["pass_after"]), (2, 1), "lte 는 <= 로 센다(8·16 → 8)")

    def test_empty_slot_is_not_buildable_even_when_turned_off(self):
        imp = self.preview(5, 500, active=False)
        self.assertEqual((imp["pass_after"], imp["slot_total"]), (0, 0))
        self.assertFalse(imp["buildable_after"], "슬롯 후보가 0 이면 꺼도 견적 불가 — True 로 고정하지 않는다")

    def test_preview_writes_nothing(self):
        before = [self.floor_row(f[0]) for f in FLOORS]
        self.preview(1, 900, active=False)
        self.assertEqual([self.floor_row(f[0]) for f in FLOORS], before)
        self.log.assert_not_called()
        self.reload.assert_not_called()

    def test_list_and_preview_before_agree(self):
        items = [it for g in AUF.list_floors()["groups"] for it in g["items"]]
        self.assertEqual(len(items), len(FLOORS))
        for it in items:
            with self.subTest(floor=it["floor_id"]):
                imp = self.preview(it["floor_id"], it["value"], active=it["active"])
                self.assertEqual(it["pass_count"], imp["pass_before"])
                self.assertEqual(it["pass_count"], imp["pass_after"], "같은 값·활성이면 전후가 같다")
                self.assertEqual(it["slot_total"], imp["slot_total"])
        inactive = next(it for it in items if it["floor_id"] == 3)
        self.assertEqual(inactive["pass_count"], inactive["slot_total"])

    def test_save_still_writes_value_and_active(self):
        out = AUF.update_floor(1, AUF.FloorBody(value=600, active=False, preview=False))
        self.assertTrue(out["ok"])
        self.assertEqual(self.floor_row(1), (600, False))
        self.assertEqual(out["impact"]["pass_after"], 4)
        self.log.assert_called_once()
        self.reload.assert_called_once()


class PermissionTests(unittest.TestCase):
    def test_non_owner_is_refused_before_counting(self):
        for role in ("operator", "viewer", None):
            with self.subTest(role=role), \
                    mock.patch.object(AUF, "current_operator", lambda r=role: {"role": r} if r else None), \
                    mock.patch.object(AUF, "engine") as eng:
                with self.assertRaises(HTTPException) as cm:
                    AUF.update_floor(1, AUF.FloorBody(value=1, preview=True))
                self.assertEqual(cm.exception.status_code, 403)
                eng.begin.assert_not_called()


class ScreenTests(unittest.TestCase):
    def test_deactivation_sentence_and_owner_note(self):
        self.assertIn("if (impact.active_after === false)", TEMPLATE)
        self.assertIn("이 하한을 끄면 이 줄로는 거르지 않습니다 — 같은 용도의 다른 하한은 그대로 적용됩니다.", TEMPLATE)
        self.assertIn("관리자(owner) 등급만 「영향 미리보기」에서", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
