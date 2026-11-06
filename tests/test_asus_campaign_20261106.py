"""ASUS 기획전 DB 원천 (2026-11-06, 0178) — 입력 규칙 · 공개 필드 · 격리 스키마 저장/재조회.

DB 검사는 루프백 Postgres 안의 새 스키마에서만 돈다(products 표조차 없는 스키마라 다른 표에 닿으면 실패한다).
개발 PC 에 Postgres 가 없으면 건너뛰고, CI(POPCORN_CI=1)에서는 연결이 안 되면 실패한다.
"""
import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import unittest
import uuid
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402
from pydantic import ValidationError                     # noqa: E402

from api import admin_asus_campaign as ADM               # noqa: E402
from api import admin_nav, admin_page_intro, auth        # noqa: E402
from api import admin_ui_asus_campaign as UI             # noqa: E402
from api import asus_campaign as AC                      # noqa: E402

SEED_PATH = ROOT / "db/migrations/data/asus_campaign_models_20261106.json"
MIGRATION = ROOT / "db/migrations/versions/0178_asus_campaign_models.py"
SEED = AC.seed_models()
DATA_JS = (ROOT / "mockups/mvp4/assets/js/asus-data.js").read_text(encoding="utf-8")
PAGE = (ROOT / "templates/admin/asus_campaign.html.j2").read_text(encoding="utf-8")


def content(model="video"):
    return copy.deepcopy(SEED[model]["content"])


def part(c, label):
    return next(p for p in c["parts"] if p["label"] == label)


class Seed(unittest.TestCase):
    def test_seed_file_is_pinned_to_pr447_values(self):
        # LF 기준 고정. PR447 asus-data.js(48522978)에서 기계로 뽑았다 — 값을 고치면 여기서 멈춘다.
        data = SEED_PATH.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(data).hexdigest(), PINNED_SEED_SHA)

    def test_every_seed_row_passes_the_save_rules(self):
        self.assertEqual(sorted(SEED), sorted(AC.MODEL_IDS))
        for model_id, row in SEED.items():
            AC.public_model(model_id, row["plan_review_price"], row["content"])

    def test_images_and_icons_exist_on_disk(self):
        for name in AC.HERO_IMAGES + AC.USE_IMAGES:
            self.assertTrue((ROOT / "mockups/mvp4/assets/images/asus" / name).is_file(), name)
        for name in AC.ICONS:
            self.assertTrue((ROOT / "mockups/mvp4/assets/icons" / (name + ".svg")).is_file(), name)

    def test_states_match_screen_names(self):
        for key, label in AC.STATES.items():
            self.assertIn(f"{key}: '{label}'", DATA_JS)
        self.assertIn(f"PLAN_LABEL: '{AC.PLAN_LABEL}'", DATA_JS)


class SaveRules(unittest.TestCase):
    def assertRejected(self, c):
        with self.assertRaises(ValidationError):
            AC.Content.model_validate(c)

    def test_html_and_script_are_rejected_everywhere(self):
        for bad in ("<script>alert(1)</script>", "a>b", "javascript:alert(1)", "x onclick=alert(1)", "줄\n바꿈"):
            c = content(); c["tagline"] = bad; self.assertRejected(c)
            c = content(); c["uses"][0]["steps"][0] = bad; self.assertRejected(c)
            c = content(); part(c, "메인보드")["options"][0]["note"] = bad; self.assertRejected(c)

    def test_length_limits(self):
        c = content(); c["name"] = "가" * 31; self.assertRejected(c)
        c = content(); c["uses"][0]["steps"][0] = "가" * 31; self.assertRejected(c)
        c = content(); c["uses"] = []; self.assertRejected(c)
        c = content(); c["uses"] = c["uses"] * 2; self.assertRejected(c)

    def test_unknown_fields_are_rejected(self):
        c = content(); c["sale_price"] = 1; self.assertRejected(c)
        c = content(); part(c, "메인보드")["options"][0]["cost_price"] = 1; self.assertRejected(c)

    def test_image_allowlist(self):
        for bad in ("../../evil.webp", "https://x.test/a.webp", "/assets/images/asus/use-ai-1.webp", "use-ai-9.webp"):
            c = content(); c["uses"][0]["image"] = bad; self.assertRejected(c)
            c = content(); c["hero_image"] = bad; self.assertRejected(c)

    def test_prices_are_strict_positive_integers_or_null(self):
        for bad in (0, -1, 1.5, "1000", True, AC.PRICE_MAX + 1):
            c = content(); part(c, "메인보드")["options"][0]["price"] = bad; self.assertRejected(c)
            with self.assertRaises(ValidationError):
                ADM.SaveBody(expected_version=1, plan_review_price=bad, content=content())
        ADM.SaveBody(expected_version=1, plan_review_price=None, content=content())

    def test_unconfirmed_states_cannot_carry_price(self):
        c = content(); part(c, "CPU 쿨러")["options"][0]["price"] = 100000; self.assertRejected(c)
        c = content(); part(c, "운영체제")["options"][0]["price"] = 100000; self.assertRejected(c)
        c = content(); part(c, "메인보드")["options"][0]["price"] = None; self.assertRejected(c)   # 프리미엄만 남는 경우

    def test_fixed_rows_and_os_stay(self):
        c = content(); c["parts"] = c["parts"][:-1]; self.assertRejected(c)
        c = content(); c["parts"][0], c["parts"][1] = c["parts"][1], c["parts"][0]; self.assertRejected(c)
        c = content(); part(c, "운영체제")["status"] = "sale"; self.assertRejected(c)
        c = content(); part(c, "케이스")["options"] = []; self.assertRejected(c)

    def test_local_ai_keeps_limit_notice(self):
        c = content("local-ai"); c["limit"] = None
        with self.assertRaises(ValueError):
            AC.public_model("local-ai", 12990000, c)


class PublicModel(unittest.TestCase):
    def test_customer_payload_has_no_internal_fields(self):
        out = AC.public_model("video", 5990000, content())
        text = json.dumps(out, ensure_ascii=False)
        for gone in ("mall_no", "cost", "supplier", "공급처", "version", "updated_by"):
            self.assertNotIn(gone, text, gone)
        self.assertEqual(out["plan_label"], "기획 검토가 · ASUS 협의 전")
        self.assertEqual((out["gpu"], out["gpu_status"], out["vram"]), ("ASUS PRIME RTX 5080 16GB", "supply", "16GB"))

    def test_null_plan_stays_null(self):
        self.assertIsNone(AC.public_model("video", None, content())["plan_review_price"])
        with self.assertRaises(ValueError):
            AC.public_model("video", 0, content())

    def test_modules_never_touch_catalog_tables(self):
        for f in ("api/asus_campaign.py", "api/admin_asus_campaign.py", "db/migrations/versions/0178_asus_campaign_models.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            for sql in ("FROM products", "UPDATE products", "INSERT INTO products", "stock_movements", "product_specs"):
                self.assertNotIn(sql, src, f)


class Wiring(unittest.TestCase):
    PATH = "/admin2/asus-campaign"

    def test_menu_intro_routes(self):
        self.assertIn(self.PATH, [i[1] for g in admin_nav.NAV for i in g[2]])
        self.assertIn(self.PATH, admin_page_intro.INTRO)
        self.assertEqual([r.path for r in UI.router.routes], [self.PATH])
        self.assertIn("/api/customer/asus-campaign", [r.path for r in AC.router.routes])

    def test_write_role_gate(self):
        self.assertEqual(auth.required_role("PUT", "/api/admin/asus-campaign/video"), "operator")
        self.assertEqual(auth.required_role("GET", "/api/admin/asus-campaign/video"), "viewer")

    def test_screen_uses_korean_fields_not_raw_json(self):
        for label in ("모델 이름", "한 줄 소개", "기획 검토가(원)", "추천 대상 문구", "진행 순서", "후보 상태", "일반회원가(원)"):
            self.assertIn(label, PAGE, label)
        self.assertNotIn("JSON.parse(", PAGE)
        self.assertNotIn("innerHTML", PAGE.split("#}", 1)[1])
        self.assertIn("beforeunload", PAGE)
        self.assertIn("seq!==st.seq", PAGE)
        self.assertIn("$('acForm').disabled=st.saving", PAGE)   # 저장 중 입력이 재조회로 사라지지 않게 잠근다

    def test_static_file_has_no_model_values(self):
        for gone in ("3990000", "5990000", "12990000", "RTX 5080 16GB", "use-business-1", "126548"):
            self.assertNotIn(gone, DATA_JS, gone)


class CustomerReadFailure(unittest.TestCase):
    """DB 없이 확인한다: 연결 실패 응답도 정직한 503 이고 캐시되지 않는다(2026-11-06 CI 실패 회귀)."""

    def test_503_is_not_cacheable_and_carries_no_model_values(self):
        from sqlalchemy.exc import OperationalError

        class Down:
            def connect(self):
                raise OperationalError("SELECT 1", {}, Exception("down"))

        app = FastAPI()
        app.include_router(AC.router)
        with mock.patch.object(AC, "engine", Down()):
            r = TestClient(app, raise_server_exceptions=False).get("/api/customer/asus-campaign")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.json(), {"detail": "기획전 정보를 불러오지 못했습니다."})


def _db_url():
    from sqlalchemy.engine import make_url
    from sqlalchemy import create_engine, text
    try:
        u = make_url(os.environ.get("DATABASE_URL") or "")
    except Exception:                                   # noqa: BLE001
        return None
    if u.host not in ("127.0.0.1", "localhost", "::1"):
        return None
    try:
        with create_engine(u).connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:                                   # noqa: BLE001
        if os.environ.get("POPCORN_CI") == "1":
            raise
        return None
    return u


def _migration():
    spec = importlib.util.spec_from_file_location("m0178", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(_db_url(), "루프백 Postgres 가 없어 DB 검사를 건너뜁니다(CI 에서는 실패)")
class OnIsolatedSchema(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine, text
        self.text = text
        self.url = _db_url()
        self.schema = "asus_campaign_t_" + uuid.uuid4().hex[:12]
        with create_engine(self.url).begin() as c:
            c.execute(text('CREATE SCHEMA "%s"' % self.schema))
        self.engine = create_engine(self.url, connect_args={"options": "-csearch_path=%s" % self.schema})
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE admin_operators (operator_id BIGSERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL)"))
            c.execute(text("CREATE TABLE admin_operator_activity_logs (log_id BIGSERIAL PRIMARY KEY, operator_id BIGINT,"
                           " action VARCHAR(100) NOT NULL, target_kind VARCHAR(50), target_id VARCHAR(100), detail JSONB,"
                           " created_at TIMESTAMP NOT NULL DEFAULT now())"))
            c.execute(text("INSERT INTO admin_operators (operator_id, name) VALUES (7, '시험 운영자')"))
        self.upgrade()
        self.me = {"role": "operator", "operator_id": 7, "name": "시험 운영자"}
        self.patches = [mock.patch.object(AC, "engine", self.engine), mock.patch.object(ADM, "engine", self.engine),
                        mock.patch.object(ADM, "current_operator", lambda: self.me),
                        mock.patch("api.admin_orders.current_operator_id", lambda: 7)]
        for p in self.patches:
            p.start()
        app = FastAPI()
        app.include_router(ADM.router)
        app.include_router(AC.router)
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.engine.dispose()
        from sqlalchemy import create_engine
        with create_engine(self.url).begin() as c:
            c.execute(self.text('DROP SCHEMA "%s" CASCADE' % self.schema))

    def upgrade(self, fn="upgrade"):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        mod = _migration()
        with self.engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(mod, fn)()

    def row(self, model_id):
        with self.engine.connect() as c:
            return c.execute(self.text("SELECT plan_review_price, content, version, origin, updated_by"
                                       " FROM asus_campaign_models WHERE model_id=:i"), {"i": model_id}).mappings().first()

    def save(self, model_id="video", **kw):
        body = {"expected_version": self.row(model_id)["version"], "plan_review_price": self.row(model_id)["plan_review_price"],
                "content": copy.deepcopy(self.row(model_id)["content"])}
        body.update(kw)
        return self.client.put(f"/api/admin/asus-campaign/{model_id}", json=body)

    def logs(self):
        with self.engine.connect() as c:
            return list(c.execute(self.text("SELECT action, target_kind, target_id, detail FROM admin_operator_activity_logs"
                                            " ORDER BY log_id")).mappings())

    # ── 마이그레이션 ──
    def test_fresh_upgrade_inserts_pr447_values(self):
        for model_id, seed in SEED.items():
            r = self.row(model_id)
            self.assertEqual((r["plan_review_price"], r["content"], r["version"], r["origin"]),
                             (seed["plan_review_price"], seed["content"], 1, "seed"))

    def test_reapply_keeps_edits_and_only_refills_missing(self):
        c = content(); c["tagline"] = "관리자가 고친 값"
        self.assertEqual(self.save(content=c, plan_review_price=5000000).status_code, 200)
        with self.engine.begin() as conn:
            conn.execute(self.text("DELETE FROM asus_campaign_models WHERE model_id='business'"))
        self.upgrade()
        r = self.row("video")
        self.assertEqual((r["content"]["tagline"], r["plan_review_price"], r["version"], r["origin"]),
                         ("관리자가 고친 값", 5000000, 2, "admin"))
        self.assertEqual(self.row("business")["plan_review_price"], 3990000)

    def test_downgrade_refuses_when_edited(self):
        c = content(); c["tagline"] = "수정"
        self.save(content=c)
        with self.assertRaises(RuntimeError):
            self.upgrade("downgrade")
        self.assertEqual(self.row("video")["content"]["tagline"], "수정")

    def test_db_checks_reject_zero_price_and_unknown_id(self):
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(self.text("UPDATE asus_campaign_models SET plan_review_price = 0 WHERE model_id='video'"))
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            c.execute(self.text("INSERT INTO asus_campaign_models (model_id, content) VALUES ('other', '{}')"))

    # ── 저장 · 재조회 ──
    def test_save_rereads_from_db_and_reaches_customer(self):
        c = content(); c["tagline"] = "저장 확인 문구"; part(c, "메인보드")["options"][0]["price"] = 300000
        r = self.save(content=c, plan_review_price=6100000)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["version"], 2)
        got = self.client.get("/api/admin/asus-campaign/video").json()
        self.assertEqual((got["content"]["tagline"], got["plan_review_price"], got["version"], got["updated_by"]),
                         ("저장 확인 문구", 6100000, 2, "시험 운영자"))
        pub = {m["id"]: m for m in self.client.get("/api/customer/asus-campaign").json()["models"]}
        self.assertEqual((pub["video"]["tagline"], pub["video"]["plan_review_price"]), ("저장 확인 문구", 6100000))
        self.assertEqual(pub["business"]["plan_review_price"], 3990000)
        self.assertNotIn("mall_no", json.dumps(pub, ensure_ascii=False))

    def test_stale_version_is_rejected_and_keeps_winner(self):
        c = content(); c["tagline"] = "먼저 저장"
        self.assertEqual(self.save(content=c).status_code, 200)
        c2 = content(); c2["tagline"] = "늦은 저장"
        r = self.save(content=c2, expected_version=1)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.row("video")["content"]["tagline"], "먼저 저장")
        self.assertEqual(len(self.logs()), 1)

    def test_same_values_do_not_bump_or_log(self):
        r = self.save()
        self.assertEqual((r.status_code, r.json()["changed"]), (200, False))
        self.assertEqual((self.row("video")["version"], self.logs()), (1, []))

    def test_audit_records_changed_fields_only(self):
        c = content(); c["tagline"] = "감사 확인"
        self.save(content=c, plan_review_price=None)
        log = self.logs()[0]
        self.assertEqual((log["action"], log["target_kind"], log["target_id"]), ("ASUS 기획전 구성 저장", "asus_campaign", "video"))
        self.assertEqual(sorted(log["detail"]["changes"]), ["content.tagline", "plan_review_price"])
        self.assertEqual(log["detail"]["changes"]["plan_review_price"], {"before": 5990000, "after": None})
        self.assertEqual((log["detail"]["version_from"], log["detail"]["version_to"]), (1, 2))

    def test_failed_validation_writes_nothing(self):
        c = content(); c["tagline"] = "<b>x</b>"
        self.assertEqual(self.save(content=c).status_code, 422)
        self.assertEqual(self.save(plan_review_price=0).status_code, 422)
        self.assertEqual((self.row("video")["version"], self.logs()), (1, []))

    def test_unknown_id_and_viewer(self):
        self.assertEqual(self.client.get("/api/admin/asus-campaign/other").status_code, 404)
        self.assertEqual(self.client.put("/api/admin/asus-campaign/other", json={
            "expected_version": 1, "plan_review_price": None, "content": content()}).status_code, 404)
        self.me = {"role": "viewer", "operator_id": 7}
        self.assertEqual(self.client.get("/api/admin/asus-campaign/video").json()["can_write"], False)
        self.assertEqual(self.save().status_code, 403)
        self.me = {}
        self.assertEqual(self.client.get("/api/admin/asus-campaign").status_code, 401)

    # ── 고객 API 실패 · 빈 결과 ──
    def test_customer_empty_broken_and_missing_table(self):
        with self.engine.begin() as c:
            c.execute(self.text("UPDATE asus_campaign_models SET content = '{\"name\": \"<x>\"}' WHERE model_id='video'"))
            c.execute(self.text("DELETE FROM asus_campaign_models WHERE model_id='business'"))
        d = self.client.get("/api/customer/asus-campaign").json()
        self.assertEqual(([m["id"] for m in d["models"]], d["unavailable"]), (["local-ai"], ["video"]))
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM asus_campaign_models"))
        d = self.client.get("/api/customer/asus-campaign").json()
        self.assertEqual((d["ok"], d["models"], d["unavailable"]), (True, [], []))
        self.assertEqual(self.client.get("/api/admin/asus-campaign").json()["missing"], list(AC.MODEL_IDS))
        with self.engine.begin() as c:
            c.execute(self.text("DROP TABLE asus_campaign_models"))
        r = self.client.get("/api/customer/asus-campaign")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/api/admin/asus-campaign").status_code, 503)


PINNED_SEED_SHA = "a8f3ccb2fa26d548d5c4e6e6d85c713df23c0ab6e4dc4a646de1a4f2dfe3d808"

if __name__ == "__main__":
    unittest.main()
