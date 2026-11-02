"""PR431 — 관리자 상품 노출(is_visible) 수정 경로 (2026-11-02 사용자 확정: 숨김을 고객 화면에도 적용).

무엇을 증명하나 (DB 없이 — 가짜 연결로 SQL 과 인자만 본다):
  ① PATCH 는 JSON true/false 만 받는다. "false"·"true"·0·1·null·"" 는 400 이고 아무것도 쓰지 않는다.
  ② false 도 정상 저장된다(「거짓 값이라 변경 없음」으로 버리지 않는다) — 변경 기록·잠금이 함께 남는다.
  ③ 같은 값이면 쓰지 않는다(원장을 더럽히지 않는다).
  ④ 되돌리기는 노출 값과 잠금을 함께 되돌리고, 기록이 boolean 이 아니면 409 로 멈춘다.
  ⑤ 단건 조회가 is_visible 을 낸다 · 쓰기는 운영자 이상(조회 등급 차단)이다.
  ⑥ 적재(catalog_ingest)는 이 컬럼을 쓰지 않는다 — 쓰게 되면 잠금 가드를 함께 넣어야 한다.
  ⑦ 확인 창은 문자열이 아니라 boolean 을 보내고, 모르는 값은 고치게 하지 않는다.

증명하지 않는 것: 실제 PostgreSQL 동작·고객 화면 재조회(→ tests/scenarios/test_mvp4_admin_link_e2e.py, CI 일회용 DB),
브라우저 클릭(→ 합성 UI 확인).
"""
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from fastapi import HTTPException  # noqa: E402

from api import admin_orders, admin_products as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Conn:
    """patch_product · undo_product_edit 가 보내는 SQL 만 흉내 낸다."""

    def __init__(self, product, log=None):
        self.product = dict(product)
        self.log = log
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append((q, dict(params or {})))
        if "FROM admin_operator_activity_logs WHERE log_id" in q:
            return Rows([self.log] if self.log else [])
        if "action='product_edit_undo'" in q:
            return Rows([])
        if q.startswith("SELECT") and "FROM products WHERE product_code=:pc" in q:
            return Rows([dict(self.product)])
        if q.startswith("UPDATE products SET"):
            for k, v in params.items():
                if k == "lf":
                    self.product["locked_fields"] = json.loads(v)
                elif k in P.EDITABLE:
                    self.product[P.EDITABLE[k][0]] = v
            return Rows([])
        if "v_recommendation_candidates" in q:
            return Rows([])
        raise AssertionError("예상하지 못한 SQL: " + q)

    def updates(self):
        return [(q, p) for q, p in self.sql if q.startswith("UPDATE")]


PRODUCT = dict(product_code=130001, sku="S-130001", product_name="합성 PC", maker=None, supplier=None,
               purchase_price=None, sale_price=900000, stock_qty=1, status="판매중", model_name=None,
               danawa_code=None, market_price=None, is_visible=True, locked_fields=[])


def run_patch(changes, product=PRODUCT):
    conn = Conn(product)
    logged = []
    with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)), \
         mock.patch.object(admin_orders, "_log", side_effect=lambda c, a, t, d, kind=None: logged.append((a, d)) or 77), \
         mock.patch.object(P, "current_operator_id", return_value=1):
        out = P.patch_product(130001, P.PatchBody(changes=changes))
    return out, conn, logged


class StrictBooleanPatchTests(unittest.TestCase):
    def test_non_boolean_values_are_rejected_before_any_write(self):
        for bad in ("false", "true", "False", 0, 1, None, "", "0", [], {}):
            with self.subTest(value=bad):
                conn = Conn(PRODUCT)
                with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)):
                    with self.assertRaises(HTTPException) as e:
                        P.patch_product(130001, P.PatchBody(changes={"is_visible": bad}))
                self.assertEqual(e.exception.status_code, 400)
                self.assertIn("is_visible", str(e.exception.detail))
                self.assertEqual(conn.sql, [])       # 조회조차 하지 않고 멈춘다

    def test_false_hides_and_is_logged_and_locked(self):
        out, conn, logged = run_patch({"is_visible": False})
        self.assertEqual((out["changed"], out["fields"]), (1, ["is_visible"]))
        self.assertIs(conn.product["is_visible"], False)
        upd = conn.updates()
        self.assertEqual(len(upd), 1)
        self.assertIn("is_visible = :is_visible", upd[0][0])
        self.assertIs(upd[0][1]["is_visible"], False)
        self.assertEqual(conn.product["locked_fields"], ["is_visible"])
        self.assertEqual(logged, [("product_edit", {
            "product_code": 130001, "sku": "S-130001",
            "changes": {"is_visible": {"from": True, "to": False}},
            "before": {"locked_fields": []}, "locked": True})])
        self.assertEqual(out["undo_id"], 77)

    def test_true_restores_visibility(self):
        out, conn, _ = run_patch({"is_visible": True}, dict(PRODUCT, is_visible=False))
        self.assertEqual(out["changed"], 1)
        self.assertIs(conn.product["is_visible"], True)

    def test_same_value_writes_nothing(self):
        out, conn, logged = run_patch({"is_visible": True})
        self.assertEqual(out["changed"], 0)
        self.assertEqual((conn.updates(), logged), ([], []))

    def test_editable_and_meta_list_include_is_visible(self):
        self.assertEqual(P.EDITABLE["is_visible"][0], "is_visible")
        self.assertIs(P.EDITABLE["is_visible"][1](False), False)


def undo_detail(frm=True, to=False, before_locks=None, locked=True):
    return {"action": "product_edit", "detail": {
        "product_code": 130001, "sku": "S-130001",
        "changes": {"is_visible": {"from": frm, "to": to}},
        "before": {"locked_fields": list(before_locks or [])}, "locked": locked}}


def run_undo(log, product):
    conn = Conn(product, log)
    logged = []
    with mock.patch.object(P, "engine", mock.Mock(begin=lambda: conn)), \
         mock.patch.object(P, "_lock_restore_products", return_value=None), \
         mock.patch.object(admin_orders, "_log", side_effect=lambda c, a, t, d, kind=None: logged.append((a, d)) or 78), \
         mock.patch.object(P, "current_operator_id", return_value=1):
        out = P.undo_product_edit(77)
    return out, conn, logged


class UndoTests(unittest.TestCase):
    def test_undo_restores_value_and_lock(self):
        out, conn, logged = run_undo(undo_detail(), dict(PRODUCT, is_visible=False, locked_fields=["is_visible"]))
        self.assertEqual(out, {"ok": True, "restored": 1})
        self.assertIs(conn.product["is_visible"], True)
        self.assertEqual(conn.product["locked_fields"], [])
        self.assertEqual(logged[0][0], "product_edit_undo")
        self.assertEqual(logged[0][1]["ref_log_id"], 77)

    def test_undo_refuses_non_boolean_record(self):
        for frm, to in (("true", False), (True, None), (1, 0)):
            with self.subTest(frm=frm, to=to):
                with self.assertRaises(HTTPException) as e:
                    run_undo(undo_detail(frm, to), dict(PRODUCT, is_visible=False, locked_fields=["is_visible"]))
                self.assertEqual(e.exception.status_code, 409)

    def test_undo_refuses_when_changed_since(self):
        # 숨긴 뒤 누가 다시 노출했으면 되돌리기가 그 변경을 덮지 않는다
        with self.assertRaises(HTTPException) as e:
            run_undo(undo_detail(), dict(PRODUCT, is_visible=True, locked_fields=["is_visible"]))
        self.assertEqual(e.exception.status_code, 409)


class ContractTests(unittest.TestCase):
    SRC = (ROOT / "api" / "admin_products.py").read_text(encoding="utf-8")

    def test_detail_reads_and_returns_is_visible(self):
        body = self.SRC.split("def get_product", 1)[1].split("class PatchBody", 1)[0]
        self.assertIn("p.is_visible", body)
        self.assertIn('"is_visible": r["is_visible"]', body)

    def test_write_needs_operator(self):
        from api.auth import required_role
        self.assertEqual(required_role("PATCH", "/api/admin/products/130001"), "operator")
        self.assertEqual(required_role("POST", "/api/admin/products/undo/77"), "operator")
        self.assertEqual(required_role("GET", "/api/admin/products/130001"), "viewer")

    def test_catalog_ingest_never_writes_visibility(self):
        ingest = (ROOT / "api" / "catalog_ingest.py").read_text(encoding="utf-8")
        # 적재가 이 컬럼을 쓰기 시작하면 locked_fields ? 'is_visible' 가드가 필요하다 — 이 검사가 그 날을 알린다
        self.assertNotIn("is_visible", ingest)


class DrawerUiTests(unittest.TestCase):
    TPL = (ROOT / "templates" / "admin" / "products.html.j2").read_text(encoding="utf-8")

    def test_field_offers_show_hide_and_sends_boolean(self):
        self.assertIn('["is_visible","고객 노출","visible","is_visible"]', self.TPL)
        self.assertIn('<option value="true"', self.TPL)
        self.assertIn('<option value="false"', self.TPL)
        collect = self.TPL.split("function collectBasicChanges", 1)[1].split("function onDrSaveClick", 1)[0]
        self.assertRegex(collect, r'k==="is_visible"\)\{ var b = visibleOf\(v\); if\(b !== null\) out\[k\] = b; \}')

    def test_unknown_value_is_not_editable(self):
        self.assertIn("if(editing && vis !== null)", self.TPL)
        self.assertIn('"확인 불가"', self.TPL)

    def test_visible_parser_never_treats_strings_loosely(self):
        fn = re.search(r"function visibleOf\(v\)\{[^\n]+\}", self.TPL).group(0)
        self.assertIn('v === true || v === "true"', fn)
        self.assertIn('v === false || v === "false"', fn)
        self.assertIn(": null", fn)

    def test_no_new_write_endpoint_in_screen(self):
        # 노출 변경은 기존 상품 수정 PATCH 를 그대로 쓴다 — 별도 우회 쓰기 경로를 만들지 않는다
        self.assertEqual(len(re.findall(r'method *: *"(?:POST|PATCH|PUT|DELETE)"', self.TPL)), 8)


class DrawerRoleBoundaryTests(unittest.TestCase):
    """viewer 보완(PC2 Codex 검수 2026-11-02) — 확인 창의 쓰기 진입은 실제 세션 등급(Admin2Shell.canWrite)만 본다.

    ① 판정 함수를 실제 JS 로 실행해 owner/operator 만 참, viewer·모르는 등급·등급 없음·셸 없음은 거짓(fail-closed).
    ② 버튼을 그리는 곳: 쓰기 불가면 수정·저장·미리보기·확정 버튼 마크업에 닿기 전에 돌아간다.
    ③ 핸들러: 서랍 안 쓰기 요청을 보내는 함수마다 첫머리에서 같은 판정을 한다(버튼이 남아도 편집·요청이 나가지 않는다).
    """
    TPL = (ROOT / "templates" / "admin" / "products.html.j2").read_text(encoding="utf-8")
    SHELL = (ROOT / "mockups" / "shared" / "admin2" / "admin2-shell.js").read_text(encoding="utf-8")

    def fn(self, name):
        m = re.search(r"\n  function " + name + r"\([^)]*\)\{.*?\n  \}\n", self.TPL, re.S)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_writable_judgement_runs_on_real_role_and_fails_closed(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음 — CI(Node 22)에서 실행")
        writable = re.search(r"function drawerWritable\(\)\{[^\n]+\}", self.TPL).group(0)
        rank = re.search(r"var ROLE_RANK = \{[^}]+\};", self.SHELL).group(0)
        can = re.search(r"function canWrite\(minRole\) \{.*?\n  \}", self.SHELL, re.S).group(0)
        # 셸의 ROLE_RANK·canWrite 원문과 화면의 drawerWritable 원문을 그대로 실행한다(me 는 셸이 /auth/me 로 채우는 값)
        js = "var me = null;\n" + rank + "\n" + can + "\n" + writable + """
var out = {};
var cases = {owner:{role:'owner'}, operator:{role:'operator'}, viewer:{role:'viewer'}, unknown:{role:'admin'}, empty:{}, none:null};
Object.keys(cases).forEach(function(k){ me = cases[k]; global.window = {Admin2Shell: {canWrite: canWrite}}; out[k] = drawerWritable(); });
me = {role:'owner'}; global.window = {}; out.noShell = drawerWritable();
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"owner": True, "operator": True, "viewer": False,
                                                "unknown": False, "empty": False, "none": False, "noShell": False})

    def test_writable_uses_shell_session_role_not_dom(self):
        w = re.search(r"function drawerWritable\(\)\{[^\n]+\}", self.TPL).group(0)
        self.assertEqual(w, 'function drawerWritable(){ return !!(window.Admin2Shell && window.Admin2Shell.canWrite("operator")); }')
        self.assertNotIn("roleBox", self.fn("renderDrawerFooter"))

    def test_footer_returns_before_any_write_button(self):
        foot = self.fn("renderDrawerFooter")
        guard = foot.index("if(!drawerWritable()){")
        for marker in ('id="drEdit"', 'id="drSave"', 'id="drPreview"', 'id="drConfirm"', 'id="drReselect"'):
            self.assertGreater(foot.index(marker), guard, marker)
        ro = foot[guard:foot.index("if(tab===", guard)]
        self.assertIn("dropDrawerEditing();", ro)
        self.assertIn("return;", ro)
        self.assertNotIn("drEdit", ro)

    def test_body_drops_editing_when_not_writable(self):
        body = self.fn("renderDrawerBody")
        self.assertLess(body.index("if(!drawerWritable()) dropDrawerEditing();"), body.index("basicTabHtml"))

    def test_every_drawer_write_handler_is_guarded(self):
        guarded = ("onDrEditClick", "onDrSaveClick", "onDrPreviewClick", "onDrConfirmClick", "supplierAdd", "supplierDelete")
        for name in guarded:
            src = self.fn(name)
            first_fetch = src.find("fetch(")
            g = src.find("if(!drawerWritable())")
            self.assertGreater(g, -1, name)
            if first_fetch > -1:
                self.assertLess(g, first_fetch, name)
        self.assertIn('e.onclick=function(){ if(!drawerWritable()) return; DRAWER.partPreview=null;', self.TPL)
        # 서랍 영역(openDrawer 이후)의 쓰기 fetch 는 모두 위 함수 안에 있다 — 새 쓰기 경로가 생기면 여기서 걸린다
        start = self.TPL.index("\n  function openDrawer(")
        for m in re.finditer(r'method *: *"(?:POST|PATCH|PUT|DELETE)"', self.TPL[start:]):
            pos = start + m.start()
            owner = re.findall(r"\n  function (\w+)\(", self.TPL[:pos])[-1]
            self.assertIn(owner, guarded, owner)

    def test_role_rerender_after_session_known(self):
        self.assertIn("window.Admin2Shell.meReady.then(function(){ if(DRAWER.code && DRAWER.data){ renderDrawerBody(); renderDrawerFooter(); } });", self.TPL)


if __name__ == "__main__":
    unittest.main()
