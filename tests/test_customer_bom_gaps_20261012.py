"""고객 화면 부품 정보 빈칸 -- 기존 데이터 -> 팝콘PC 공개 페이지 -> 운영자 확인 (2026-10-12 사장님 지시).

  > "만약 팝콘PC 웹 크롤링을 해서도 확인이 정 안되면 운영자(사람)가 하게 하도록"

빈칸을 추측 값으로 채우지 않는다: 공개 페이지가 «판매중 · 우리 판매가와 같은 값»일 때만 근거로 남기고, 나머지는 「운영자 확인
필요」로 관리자 화면에 올린다. 운영자 확정도 지금 판매가와 같을 때만 받는다.
"""
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import customer_bom_gaps as G

ROOT = Path(__file__).resolve().parent.parent


def _row(**kw):
    base = {"explanation_code": 109547, "part_code": 109547, "slot": "RAM", "sale_price": 225_800,
            "n_supply": 0, "n_available": 0, "has_evidence": False, "pc_count": 27, "pc_examples": [93454]}
    base.update(kw)
    return base


# ── 1단계: 고객 화면이 가격을 숨기는 이유 (customer_pc_offer 와 같은 판정) ─────────────────────────
@pytest.mark.parametrize("kw,cause", [
    ({"part_code": None, "sale_price": None}, G.CAUSE_UNLINKED),
    ({"sale_price": None}, G.CAUSE_NO_PRICE),
    ({"sale_price": 0}, G.CAUSE_NO_PRICE),
    ({"n_supply": 0}, G.CAUSE_NO_SUPPLY),
    ({"n_supply": 2, "n_available": 0}, G.CAUSE_SOLDOUT),
    ({"n_supply": 2, "n_available": 1}, None),
    ({"n_supply": 2, "n_available": 0, "has_evidence": True}, None),
])
def test_cause(kw, cause):
    assert G.cause_of(_row(**kw)) == cause


# ── 2단계: 공개 페이지 결과는 «판매중 · 같은 가격»만 근거 ───────────────────────────────────────
@pytest.mark.parametrize("mall,outcome", [
    ({"ok": True, "price": 225_800, "soldout": False}, "same"),
    ({"ok": True, "price": 221_700, "soldout": False}, "held"),     # 실측 109547 -- 팝콘PC 가격이 다르다
    ({"ok": True, "price": 225_800, "soldout": True}, "stale"),
    ({"ok": False, "price": None}, "failed"),
    (None, "failed"),
])
def test_judge_mall(mall, outcome):
    assert G.judge_mall(225_800, mall)[0] == outcome


def test_status_and_todo():
    st, todo = G.status_of(dict(_row(), cause=G.CAUSE_SOLDOUT), {"outcome": "held"})
    assert st == "operator" and "판매가" in todo
    st, todo = G.status_of(dict(_row(), cause=G.CAUSE_UNLINKED), None)
    assert st == "operator" and "부품 설명 관리" in todo
    st, _ = G.status_of(dict(_row(has_evidence=True), cause="x"), None)
    assert st == "confirmed"


class _Conn:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((str(sql), params))


def test_check_mall_records_only_same_as_evidence():
    gaps = [dict(_row(), cause=G.CAUSE_NO_SUPPLY, status="operator"),
            dict(_row(explanation_code=124852, part_code=124852, sale_price=667_200), cause=G.CAUSE_SOLDOUT,
                 status="operator"),
            dict(_row(explanation_code=127201, part_code=None, sale_price=None), cause=G.CAUSE_UNLINKED,
                 status="operator"),
            dict(_row(explanation_code=1, part_code=1, sale_price=None), cause=G.CAUSE_NO_PRICE, status="operator")]
    mall = {109547: {"ok": True, "price": 225_800, "soldout": False},
            124852: {"ok": True, "price": 708_200, "soldout": False},
            127201: {"ok": True, "price": 363_000, "soldout": False}}
    seen, store = [], []

    def fetch(codes):
        seen.extend(codes)
        return mall
    with contextlib.ExitStack() as st:
        st.enter_context(patch.object(G, "price_gaps", lambda conn: gaps))
        st.enter_context(patch.object(G.engine, "connect", lambda: _Conn([])))
        st.enter_context(patch.object(G.engine, "begin", lambda: _Conn(store)))
        out = G.check_mall(fetch=fetch)
    assert sorted(seen) == [109547, 124852, 127201]          # 판매가 없음은 공개 페이지로 채울 수 없어 읽지 않는다
    assert out["confirmed"] == 1 and out["operator"] == 2
    by_code = {p["c"]: p for _sql, p in store}
    assert by_code[109547]["out"] == "same" and by_code[109547]["n"] == G.NOTE_ON_SALE
    assert by_code[124852]["out"] == "held" and by_code[124852]["n"].startswith(G.NOTE_PREFIX)
    assert by_code[127201]["out"] == "held"                   # 판매 상품에 안 이어진 부품은 같아 보여도 근거가 아니다
    assert all("INSERT INTO mall_price_checks" in sql for sql, _p in store)


# ── 3단계: 운영자 확정은 지금 판매가와 같을 때만 ───────────────────────────────────────────────
class _ConfirmConn(_Conn):
    def __init__(self, store, sale):
        super().__init__(store)
        self.sale = sale

    def execute(self, sql, params=None):
        s = str(sql)
        self.store.append((s, params))

        class R:
            def __init__(self, row):
                self.row = row

            def mappings(self):
                return self

            def first(self):
                return self.row
        if s.startswith("SELECT product_code, sku, sale_price"):
            return R({"product_code": params["c"], "sku": "SKU", "sale_price": self.sale})
        return R(None)


def test_confirm_rejects_different_price_and_records_same():
    store = []
    with patch.object(G.engine, "begin", lambda: _ConfirmConn(store, 225_800)), \
            patch("api.admin_orders._log", lambda *a, **k: 77):
        with pytest.raises(HTTPException) as e:
            G.confirm(109547, G.ConfirmBody(price=221_700))
        assert e.value.status_code == 409
        assert not any("INSERT INTO mall_price_checks" in s for s, _ in store)
        out = G.confirm(109547, G.ConfirmBody(price=225_800, memo="팝콘PC 확인"))
    assert out["ok"] and out["log_id"] == 77
    ins = [p for s, p in store if "INSERT INTO mall_price_checks" in s][0]
    assert ins["out"] == "same" and ins["n"].startswith(G.NOTE_OPERATOR) and ins["mp"] == 225_800


# ── 고객 화면과 같은 판정을 쓰는가 · 화면·권한 ────────────────────────────────────────────────
def test_customer_offer_uses_same_evidence():
    from api import customer_pc_offer as O
    src = (ROOT / "api" / "customer_pc_offer.py").read_text(encoding="utf-8")
    assert O.BOM_EVIDENCE_SQL is G.EVIDENCE_SQL and "BOM_EVIDENCE_SQL" in src
    assert "last.mall_price = p.sale_price" in G.EVIDENCE_SQL      # 판매가가 바뀌면 바로 무효
    assert "interval '%d days'" % G.EVIDENCE_DAYS in G.EVIDENCE_SQL


def test_permissions_and_navigation():
    from api.auth import required_role
    from api.admin_page_intro import back_for
    assert required_role("GET", "/api/admin/customer-bom-gaps") == "viewer"
    assert required_role("POST", "/api/admin/customer-bom-gaps/check") == "operator"
    assert required_role("POST", "/api/admin/customer-bom-gaps/parts/1/confirm") == "operator"
    assert "/admin2/customer-bom-gaps" in (ROOT / "api" / "admin_nav.py").read_text(encoding="utf-8")
    assert back_for("/admin2/customer-bom-gaps")["href"] == "/admin2/part-explanations"


def test_screen_copy():
    body = (ROOT / "templates" / "admin" / "customer_bom_gaps.html.j2").read_text(encoding="utf-8")
    for needed in ("운영자 확인 필요", "팝콘PC에서 다시 확인", "확인 완료", "추측 값으로 채우지 않습니다",
                   "/api/admin/customer-bom-gaps"):
        assert needed in body, needed
