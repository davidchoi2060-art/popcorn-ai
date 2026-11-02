"""MVP4 고객 화면 ↔ 관리자 연결 — 합성 끝단 검증 (2026-11-02 · Codex 독립 검수 요청).

무엇을 증명하나 (단위·계약 테스트가 못 하는 것):
  ① 문의 저장 → 관리자 처리함 조회: /mvp4 화면 표시(X-Popcorn-Surface)로 접수한 AI 슈퍼컴퓨터 문의가
     관리자 목록에서 상품 번호 · 모델(이름·용량·수량) · 문의 종류(fixed) · 화면(mvp4)을 그대로 갖는다.
     연락처는 목록에서 가려진다.
  ② 관리자 수정 → 고객 재조회: 판매가·판매 상태를 고친 «직후» 고객 API 와 관리자 고객 링크 판정이
     새 값을 낸다(캐시가 옛 값을 쥐고 있지 않다).
  ③ 상품 확인 창 판정: 완제품 PC · AI 장비는 부품 추천 기준을 적용하지 않고(gate_applies=false),
     부품은 적용한다. 고객 링크는 PC/장비/부품을 가른다.

어디서만 도나:
  「끝까지 시나리오」 CI 작업의 일회용 PostgreSQL(마이그레이션만 적용 · 측정기 뒤)에서만 돈다.
  SCENARIO_E2E_DB=1 이고 DATABASE_URL 이 그 CI 주소일 때만 실행하고, 그 밖에는 건너뛴다 —
  개발·운영 DB 에는 절대 쓰지 않는다. 실제 고객·실제 문의·LLM·외부 전송 없음.

증명하지 않는 것:
  브라우저 화면(사람의 클릭), 사진 캐시, 몰 등록 구성 캐시(customer_pc_registered 10분 TTL —
  이 테스트는 그 경로를 타지 않는다), 운영 서버.
"""
import os
import uuid

import pytest

CI_URL = "postgresql+psycopg2://ci:ci@127.0.0.1:5432/ci"
RUN = os.environ.get("SCENARIO_E2E_DB") == "1" and os.environ.get("DATABASE_URL") == CI_URL
pytestmark = pytest.mark.skipif(not RUN, reason="CI 일회용 DB(SCENARIO_E2E_DB=1 + CI DATABASE_URL)에서만 실행")

ADMIN_EMAIL = "e2e-link-owner@ci.popcorn.invalid"
ORIGIN = {"Origin": "http://testserver"}
MVP4 = {**ORIGIN, "X-Popcorn-Surface": "mvp4"}


@pytest.fixture(scope="module")
def env():
    assert os.environ.get("DATABASE_URL") == CI_URL      # 이중 확인 — 다른 DB 면 여기서 멈춘다
    assert ADMIN_EMAIL in os.environ.get("ADMIN_BOOTSTRAP_EMAILS", "")
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from api.db import engine
    from api.main import app

    admin = TestClient(app)
    r = admin.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    guest = TestClient(app)
    with engine.connect() as conn:
        ai_cat = conn.execute(text("SELECT category_id FROM categories WHERE public_key = 'ai-supercomputer'")).scalar()
    assert ai_cat is not None, "마이그레이션 0166 이 AI 슈퍼컴퓨터 분류를 만들어야 한다"
    tag = uuid.uuid4().hex[:8]

    def register(name, part_type, category_id=None):
        body = {"name": f"E2E 합성 {name} {tag}", "part_type": part_type, "confirm_similar": True}
        if category_id is not None:
            body["category_id"] = category_id
        rr = admin.post("/api/admin/products", json=body, headers=ORIGIN)
        assert rr.status_code == 200, rr.text
        return rr.json()["product_code"]

    def patch(code, **changes):
        rr = admin.patch(f"/api/admin/products/{code}", json={"changes": changes}, headers=ORIGIN)
        assert rr.status_code == 200, rr.text

    return dict(admin=admin, guest=guest, engine=engine, text=text, ai_cat=ai_cat,
                register=register, patch=patch, tag=tag)


@pytest.fixture(scope="module")
def device(env):
    code = env["register"]("AI 장비 4TB", "ETC", env["ai_cat"])
    r = env["admin"].put(f"/api/admin/ai-device-profiles/{code}", headers=ORIGIN, json={
        "display_name": "E2E 합성 AI 장비", "storage": "4TB", "model_label": "4TB"})
    assert r.status_code == 200, r.text
    env["patch"](code, sale_price=1000000, stock_qty=1, status="판매중")
    return code


def test_inquiry_saved_and_read_back_with_context(env, device):
    g = env["guest"]
    assert g.get("/api/mvp3/purchase-inquiries/form").status_code == 200       # 방문자 연결
    r = g.post("/api/mvp3/purchase-inquiries", headers=MVP4, json={
        "topic": "AI 슈퍼컴퓨터 견적", "product_code": device, "consent": True,
        "email": f"e2e-{env['tag']}@example.invalid", "message": "합성 E2E 문의",
        "fixed": {"intent": "quote", "quantity": 2, "seen_unit_price": 1000000}})
    assert r.status_code == 200, r.text
    no = r.json()["inquiry_no"]

    lst = env["admin"].get("/api/admin/purchase-inquiries?surface=mvp4&include_test=true")
    assert lst.status_code == 200, lst.text
    row = next(i for i in lst.json()["items"] if i["inquiry_no"] == no)
    assert row["product_code"] == device                       # 상품
    fp = row["fixed_product"]
    assert fp["product_code"] == device and fp["storage"] == "4TB" and fp["quantity"] == 2   # 모델·수량
    assert fp["unit_price"] == 1000000 and fp["price_differs"] is False
    assert row["inquiry_kind"] == "fixed"                      # 종류
    assert row["surface"] == "mvp4"                            # 화면
    assert row["email"] != f"e2e-{env['tag']}@example.invalid"  # 목록에서는 연락처를 가린다


def test_admin_edit_is_visible_to_customer_on_next_read(env, device):
    a, p = env["admin"], env["patch"]
    c1 = a.get(f"/api/customer/supercomputers/{device}").json()["item"]
    assert (c1["price"], c1["sale_state"]) == (1000000, "on_sale")
    p(device, sale_price=1200000)
    c2 = a.get(f"/api/customer/supercomputers/{device}").json()["item"]
    assert c2["price"] == 1200000                              # 수정 직후 재조회에 새 값
    p(device, status="단종")
    c3 = a.get(f"/api/customer/supercomputers/{device}").json()["item"]
    assert c3["sale_state"] == "stopped"
    link = a.get(f"/api/admin/products/{device}/customer-link").json()
    assert link["url"] == f"/mvp4/supercomputer.html?id={device}" and "판매 중지" in (link["reason"] or "")
    p(device, status="판매중")


def test_pc_link_follows_customer_catalog_after_edit(env):
    a, p, text = env["admin"], env["patch"], env["text"]
    pc = env["register"]("완제품 PC", "PC_COMPLETE")
    p(pc, sale_price=900000, stock_qty=1, status="판매중")
    with env["engine"].begin() as conn:     # 용도 평가 목록 행(관리자 API 없음 — 일회용 DB 에만)
        conn.execute(text("INSERT INTO product_fit_products (product_code, crawl_name, spec, source, evaluated_at)"
                          " VALUES (:c, :n, '{}'::jsonb, 'e2e', CURRENT_DATE)"), {"c": pc, "n": f"E2E 합성 PC {env['tag']}"})
    link = a.get(f"/api/admin/products/{pc}/customer-link").json()
    assert link["url"] == f"/mvp4/?screen=product&id={pc}"
    assert any(i["product_code"] == pc for i in a.get("/api/customer/pc-catalog").json()["items"])
    p(pc, status="품절")
    link = a.get(f"/api/admin/products/{pc}/customer-link").json()
    assert link["url"] is None and "「품절」" in link["reason"]
    assert not any(i["product_code"] == pc for i in a.get("/api/customer/pc-catalog").json()["items"])


def test_detail_gate_scope_by_kind(env, device):
    a = env["admin"]
    part = env["register"]("CPU", "CPU")
    pc = env["register"]("완제품 PC 2", "PC_COMPLETE")
    assert a.get(f"/api/admin/products/{device}").json()["gate_applies"] is False
    assert a.get(f"/api/admin/products/{pc}").json()["gate_applies"] is False
    d = a.get(f"/api/admin/products/{part}").json()
    assert d["gate_applies"] is True and d["gate_scope_note"] is None
    link = a.get(f"/api/admin/products/{part}/customer-link").json()
    assert (link["kind"], link["url"]) == ("part", None)
    assert a.get("/api/admin/products/999999999/customer-link").status_code == 404
