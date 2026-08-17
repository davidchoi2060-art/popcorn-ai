"""ADM-SRC-020 재고 입고 — 입출고 원장 쓰기 (ERD §8 T10, 3중 게이트의 마지막).

원장 계약(ERD §10.6): 입고 = stock_movements(inbound|adjust, qty_delta +) + products.stock_qty 증가.
**단가는 원장 밖** — stock_movements에 단가 컬럼이 없다(product_code·movement_type·qty_delta·
ref_kind·ref_id·created_at). 따라서 입고로 매입가를 바꾸지 않는다(매입가 갱신은 단가표
ADM-PRC-040·매입 견적 ADM-SRC-010 소관). 화면 매입가는 참조 표시.
품절 복귀: 입고로 재고>0이 되면 status='품절'→'판매중'(재고 없음이 품절의 사유였으므로).
'단종'·'삭제대기'는 건드리지 않는다.
undo = **역방향 원장 행**(adjust, -qty) — 원장은 삭제하지 않는다(order_events 전례).
pool_entered는 추측하지 않고 v_recommendation_candidates 실측으로 판정 — 재고만 열려도
검수·가격이 미완이면 false(3중 게이트).
목록 = 파생(stock_qty=0 ∨ 안전재고 미달, status NOT IN 단종·삭제대기) — **저장하는 컬럼이 없다.**
안전재고 미달도 LIVE 판정이다: `products.safety_stock` 컬럼이 실재하고(마이그레이션 0004)
`_PENDING`·`_PENDING_COUNT`·`_note_of` 셋이 실제로 그 컬럼을 읽는다. 2026-08-17까지 이
docstring이 「기준 컬럼이 없어 LIVE 제외」라고 반대로 적고 있었다(같은 파일 NOTE 상수는
처음부터 「기준은 상품별 safety_stock」이라 적었다 — 문서 두 줄이 서로 다른 말을 하고 있었다).
확인법: 이 파일에서 `safety_stock` 을 grep 하면 SQL 두 곳 + 사유 문구 한 곳이 나온다.

이력 조회(2026-08-17 신설, 승인 디자인 `docs/design/spec-stock-inbound.md`):
**되돌리기는 브라우저 변수가 아니라 «서버 이력»에서 고른다.** 구 화면은 `lastAction` JS
변수에 의존해 새로고침하면 되돌릴 방법이 사라졌는데, undo API 는 처음부터 과거 회차도
받았다(「마지막 입고」 제한 코드가 없다) — 화면이 그 목록을 못 갖고 있었을 뿐이다.
⚠ **「되돌릴 수 있는가」는 서버가 판정한다** — 화면이 판정하면 목록과 API 가 갈라진다.
그래서 판정은 `undo_inbound()` 가 실제로 던지는 **같은 술어·같은 순서**를 쓴다(§_undo_state).
⚠ 이력은 **이 화면으로 처리한 입고만** 다룬다(action='stock_inbound' 계열). 상품 상세의
편입 조정·카탈로그 적재·환불 복원은 여기 나오지 않는다 — 전체 원장은 상품 상세·작업 기록.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .admin_products import PART_TYPE_LABELS
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

WHY = ("inbound", "adjust")
NOTE = ("입고 대기 = 재고 0 또는 **안전재고 미달** 상품입니다(기준은 상품별 safety_stock)"
        " · 매입가 변경은 단가표·매입 견적 소관(입고 원장에는 단가를 남기지 않습니다).")

_PENDING = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.status, p.stock_qty,
           p.safety_stock, p.purchase_price, p.sale_price,
           p.review_required_yn, p.ai_candidate_yn,
           psp.cost_price, s.name AS supplier,
           EXISTS(SELECT 1 FROM product_specs sp WHERE sp.product_code = p.product_code) AS has_specs
    FROM products p
    LEFT JOIN (SELECT DISTINCT ON (product_code) product_code, supplier_id, cost_price
               FROM product_supplier_prices ORDER BY product_code, cost_price) psp
           USING (product_code)
    LEFT JOIN suppliers s USING (supplier_id)
    WHERE p.status NOT IN ('단종','삭제대기')
      AND (p.stock_qty = 0
           OR (p.safety_stock IS NOT NULL AND p.stock_qty < p.safety_stock))
      AND (:q = '' OR p.product_name ILIKE '%%' || :q || '%%' OR p.sku ILIKE '%%' || :q || '%%')
      AND (:part_type = '' OR p.part_type = :part_type)
    ORDER BY (p.stock_qty > 0), p.product_code
    LIMIT :size OFFSET :offset
"""

# 목록과 같은 조건의 총계 — 화면이 '전체 N건 중 이 페이지'를 정직하게 말하려면 필요하다
_PENDING_COUNT = """
    SELECT count(*) FROM products p
    WHERE p.status NOT IN ('단종','삭제대기')
      AND (p.stock_qty = 0
           OR (p.safety_stock IS NOT NULL AND p.stock_qty < p.safety_stock))
      AND (:q = '' OR p.product_name ILIKE '%%' || :q || '%%' OR p.sku ILIKE '%%' || :q || '%%')
      AND (:part_type = '' OR p.part_type = :part_type)
"""


# 되돌림 역참조 — **이 한 줄이 「이미 되돌렸는가」의 유일한 근거다**(규약 키 `ref_log_id`).
# undo 가드와 이력 판정이 «같은 문장»을 쓰도록 상수로 뺐다: 가드는 409 를 던지고 이력은
# 「이미 되돌림」을 표시하는데, 술어가 갈라지면 목록이 「되돌리기 가능」이라 말한 건에서
# 409 가 난다. {ref} 만 갈아 끼운다(:i = 단건 가드 · l.log_id = 목록 판정).
# ⚠ 활동 기록 화면(api/admin_activity_logs.py)은 **action 을 보지 않는** 더 넓은 EXISTS 를
#   쓴다. 거기서는 「어떤 되돌림이든 잡는다」가 맞지만, 여기서는 **undo 엔드포인트가
#   실제로 막는 조건과 한 글자도 달라선 안 된다** — 그래서 일부러 좁은 쪽을 쓴다.
_UNDO_ROW = ("SELECT u.log_id FROM admin_operator_activity_logs u"
             " WHERE u.action='stock_inbound_undo'"
             "   AND (u.detail->>'ref_log_id')::int = {ref}"
             " ORDER BY u.log_id LIMIT 1")

KIND_LABELS = {"inbound": "입고", "adjust": "실사 조정", "undo": "되돌림"}

# 이력이 다루는 범위를 «응답이 스스로 밝힌다» — 화면 각주가 아니라 서버 문장이어야
# 다음 화면이 같은 오해를 반복하지 않는다(정의서 §⑥-마).
HISTORY_SCOPE = ("이 화면으로 처리한 입고·되돌림만 표시합니다(작업 기록 action="
                 "'stock_inbound' 계열). 상품 상세의 중복 편입 조정 · 카탈로그 적재 ·"
                 " 환불 복원은 여기 나오지 않습니다 — 전체 재고 원장은 상품 상세와"
                 " 작업 기록에서 조회합니다.")


def _in_pool(conn, pc: int) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc AND stock_qty>0"),
        {"pc": pc}).first() is not None


def _note_of(r) -> str:
    if r["stock_qty"] > 0 and r["safety_stock"] and r["stock_qty"] < r["safety_stock"]:
        return (f"안전재고 미달 — 현재 {r['stock_qty']} / 기준 {r['safety_stock']}"
                " (판매는 계속되지만 소진 위험)")
    if r["review_required_yn"]:
        return "검수 미통과 — 입고해도 추천에 쓰이지 않습니다"
    if r["sale_price"] is None:
        return "판매가 미산정 — 가격 검토 후 추천 진입"
    if not r["has_specs"]:
        # 추천 뷰는 product_specs를 조인한다 — 사양 행이 없으면 재고·가격이 다 채워져도 미진입
        return "사양 미등록(specs 행 없음) — 재고만으로는 추천 진입 불가"
    if r["status"] == "품절":
        return "품절 표시 상태 — 입고 시 판매중으로 복귀하며 추천 진입"
    return "검수·가격 완료 — 입고 시 추천 가능 재고 진입"


@router.get("/stock-inbound")
def stock_inbound(page: int = 1, size: int = 50, q: str = "", part_type: str = "",
                  catalog_q: str = ""):
    """입고 대상 — **서버 페이지네이션**(슬라이스 54).

    전량 전송이던 것을 나눠 보낸다: 입고 대상 15,259건 · 카탈로그 22,838건을 매 요청마다
    보내면 화면이 느려지고 브라우저가 버티지 못한다(상품 관리는 이미 페이지네이션이다).
    직접 등록용 `catalog`은 **검색어가 있을 때만** 최대 50건 — 셀렉트 하나 때문에 전량을
    보낼 이유가 없다.
    """
    size = max(1, min(size, 200))
    page = max(1, page)
    p = {"q": q.strip(), "part_type": part_type.strip(),
         "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        rows = conn.execute(text(_PENDING), p).mappings().all()
        total = conn.execute(text(_PENDING_COUNT), p).scalar_one()
        cq = catalog_q.strip()
        catalog = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, purchase_price, stock_qty,"
            " sale_price, review_required_yn"
            " FROM products WHERE status NOT IN ('단종','삭제대기')"
            "   AND (product_name ILIKE '%%' || :cq || '%%' OR sku ILIKE '%%' || :cq || '%%')"
            " ORDER BY sku LIMIT 50"), {"cq": cq}).mappings().all() if cq else []
    return {
        "page": page, "size": size, "total": total,
        "pages": (total + size - 1) // size,
        "catalog_q": catalog_q.strip(),
        "items": [{
            "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "purchase": r["purchase_price"] or r["cost_price"],
            "supplier": r["supplier"] or "—", "stock": r["stock_qty"],
            "safety_stock": r["safety_stock"],
            "why": "adjust" if r["stock_qty"] > 0 else "inbound",  # 미달 보충 = 실사 조정 성격
            "priced": r["sale_price"] is not None,
            "reviewed": not r["review_required_yn"],
            "has_specs": r["has_specs"],
            "status": r["status"], "note": _note_of(r),
        } for r in rows],
        "catalog": [{
            "product_code": c["product_code"], "sku": c["sku"], "name": c["product_name"],
            "cat": PART_TYPE_LABELS.get(c["part_type"], c["part_type"]),
            "purchase": c["purchase_price"], "stock": c["stock_qty"],
            "priced": c["sale_price"] is not None, "reviewed": not c["review_required_yn"],
        } for c in catalog],
        "note": NOTE + (" 목록은 서버에서 나눠 보냅니다 — 화면은 '전체 N건 중 이 페이지'를"
                        " 표시합니다. 직접 등록 후보는 검색어를 입력해야 조회됩니다"
                        "(22,838건 전량 전송을 없앴습니다)."),
    }


# ledger_rows — **이 기록에 대응하는 원장 행이 실제로 있는가.**
# 이 화면은 원장 행의 `ref_id` 에 작업 기록 `log_id` 를 넣는다(입고·되돌림 두 INSERT 모두).
# 실측(2026-08-17)으로 **원장 행이 없는 기록이 2건 있다** — log 4231·4243(P-9107,
# 2026-08-05). 작업 기록 `stock_inbound` 16건인데 원장 `inbound`/`manual` 은 14건이다.
# **코드가 원장을 빼먹은 것이 아니다**: 그 INSERT 는 2026-07-25 커밋 `c827e62` 부터 작업
# 기록과 «같은 트랜잭션»에 있다(git log -S 로 확인). 원인은 **검사 잔재를 치우면서 원장
# 행만 지우고 작업 기록은 남긴 비대칭**이다(되돌림 쌍을 함께 지워 net 0 이라 불변식
# `stock_qty = SUM(qty_delta)` 는 여전히 0건 위반). 같은 형태가 `tests/regression.py`
# 에 지금도 있다 — 원장 행과 로그를 둘 다 지우지만, 지우는 조건이 서로 다르다.
# 그래서 이력이 「입고 5」라 말하는데 원장에는 아무것도 없는 행이 존재한다 —
# **감추지 않고 값으로 싣는다**(화면이 「원장 행 없음」을 그대로 보인다).
# ⚠ **되돌림 행의 `ref_id` 는 «원 기록» log_id 다** — 새로 만든 되돌림 로그의 id 가 아니다
#   (`undo_inbound` 가 `:ref` 에 원 log_id 를 넣는다). 그래서 되돌림 행을 `ref_id = 자기
#   log_id` 로 찾으면 **항상 0건**이 나와 「원장 행 없음」이 7건 전부에 거짓으로 뜬다
#   (처음 구현이 그랬고 실측으로 잡았다 — 거짓 경보는 감추는 것과 같은 정도로 나쁘다).
#   그래서 되돌림 행은 `ref_log_id` + `qty_delta < 0`, 입고 행은 `log_id` + `qty_delta > 0`
#   으로 «부호까지» 갈라 센다(같은 ref_id 에 두 행이 달리므로 부호가 유일한 구분이다).
# ⚠ `product_code` 를 함께 걸어 좁힌다: `ref_kind='manual'` 의 `ref_id` 는 이 화면에서는
#   log_id 지만 **상품 상세 편입에서는 «상대 product_code»** 다(정의서 §④-나).
# ⚠ SQL 문자열 안 주석에 «콜론 뒤 숫자»(예: 줄 번호 표기)를 쓰지 마라 — SQLAlchemy
#   `text()` 가 주석 안까지 훑어 bind 파라미터로 읽는다. 실제로 이 자리에서
#   "A value is required for bind parameter" 로 500 이 났다(2026-08-17). 그래서 긴 설명은
#   SQL 안이 아니라 여기 파이썬 주석에 둔다.
_HISTORY = """
    SELECT l.log_id, l.action, l.created_at, l.detail,
           COALESCE(o.name, '—') AS operator,
           (l.detail->>'product_code')::bigint AS pc,
           p.sku, p.product_name, p.part_type, p.stock_qty, p.status,
           (""" + _UNDO_ROW.format(ref="l.log_id") + """) AS undone_by,
           (SELECT count(*) FROM stock_movements m
             WHERE m.ref_kind = 'manual'
               AND m.product_code = (l.detail->>'product_code')::bigint
               AND m.ref_id = CASE WHEN l.action = 'stock_inbound_undo'
                                   THEN (l.detail->>'ref_log_id')::bigint
                                   ELSE l.log_id END
               AND CASE WHEN l.action = 'stock_inbound_undo'
                        THEN m.qty_delta < 0 ELSE m.qty_delta > 0 END) AS ledger_rows
    FROM admin_operator_activity_logs l
    LEFT JOIN admin_operators o USING (operator_id)
    LEFT JOIN products p ON p.product_code = (l.detail->>'product_code')::bigint
    WHERE l.action IN ('stock_inbound','stock_inbound_undo'){flt}
    ORDER BY l.log_id DESC
    LIMIT :size OFFSET :offset
"""

_HISTORY_COUNT = """
    SELECT count(*) FROM admin_operator_activity_logs l
    WHERE l.action IN ('stock_inbound','stock_inbound_undo'){flt}
"""

# 목록·총계에 같은 조건을 쓴다 — 한쪽만 좁히면 「전체 N건」이라 말하면서 M건을 보여준다
# (같은 파일 _PENDING_COUNT 와 같은 이유. 이 저장소가 이미 겪은 형태다).
_HIST_FLT = " AND (l.detail->>'product_code')::bigint = :pc"


def _undo_state(action: str, d: dict, stock_now, undone_by):
    """되돌릴 수 있는가 — **서버가 판정한다.** 화면은 이 판정을 표시만 한다.

    순서·술어가 `undo_inbound()` 와 같다. 갈라지면 목록이 「가능」이라 말한 건에서 409 가
    난다(그게 구 화면이 되돌리기로 겪은 종류의 사고다).

        undo_inbound()                          여기
        404 action != 'stock_inbound'      ->   not_inbound
        409 ref_log_id 역참조 존재          ->   undone
        404 상품 행 없음                    ->   product_missing
        409 stock_qty < detail.qty          ->   stock_short
        (통과)                              ->   ok
    """
    if action != "stock_inbound":
        return "not_inbound", "되돌림 기록은 되돌리지 않습니다", False
    if undone_by is not None:
        return "undone", f"이미 되돌린 입고입니다 (되돌림 기록 #{undone_by})", False
    if stock_now is None:
        return "product_missing", "상품을 찾을 수 없습니다 — 조회 이후 삭제됐습니다", False
    qty = d.get("qty")
    if qty is None:
        # 기록에 수량이 없으면 undo 는 detail["qty"] 에서 KeyError 로 500 이 난다.
        # 「가능」이라 말해 500 을 밟게 하지 않는다(실패를 삼키지 않는다).
        return "log_incomplete", "기록에 입고 수량이 없어 되돌릴 수 없습니다", False
    if stock_now < int(qty):
        return ("stock_short",
                f"입고분보다 재고가 적습니다 (현재 {stock_now} / 입고 {int(qty)})"
                " — 이후 판매·조정이 있어 되돌릴 수 없습니다", False)
    return "ok", "되돌리기 가능", True


def _hist_row(r) -> dict:
    d = r["detail"] or {}
    before_qty = after_qty = None
    if r["action"] == "stock_inbound_undo":
        kind, why = "undo", None
        qty = d.get("qty")
        delta = -int(qty) if qty is not None else None
        note = f"원 기록 #{d.get('ref_log_id')} 되돌림 — 역방향 원장 행으로 상쇄"
    else:
        why = d.get("why") or "inbound"
        kind = "adjust" if why == "adjust" else "inbound"
        qty = d.get("qty")
        delta = int(qty) if qty is not None else None
        b = d.get("before") or {}
        before_qty, before_status = b.get("stock_qty"), b.get("status")
        if before_qty is not None and delta is not None:
            after_qty = before_qty + delta
        bits = []
        # 화살표(→)를 서버 문자열에 넣지 않는다 — 서버 stdout 이 cp949 라 화살표·em-dash 가
        # 요청을 500 으로 만든 전례가 있다(슬라이스 40). 「이전 → 이후」 표기는 화면이
        # 그리고, 서버는 stock_before·stock_after 를 값으로 준다.
        if after_qty is not None:
            bits.append(f"입고 전 재고 {before_qty} · 입고 후 {after_qty}")
        elif before_qty is not None:
            bits.append(f"입고 전 재고 {before_qty}")
        if before_status == "품절":
            bits.append("품절 해제")
        note = " · ".join(bits) or "이전 재고 기록 없음"
    state, undo_note, undoable = _undo_state(r["action"], d, r["stock_qty"], r["undone_by"])
    if not r["ledger_rows"]:
        note += " · 원장 행 없음 — 이 기록에 대응하는 재고 원장 행이 조회되지 않습니다"
    return {
        "log_id": r["log_id"],
        "at": iso(r["created_at"]),
        "kind": kind, "kind_label": KIND_LABELS[kind],
        "qty_delta": delta,
        # 「이전 → 이후」는 화면이 그린다 — 서버는 값을 준다(입고 행만 있다. 되돌림 행은
        # 기록에 before 가 없어 null 이고, 지어내지 않는다).
        "stock_before": before_qty, "stock_after": after_qty,
        "operator": r["operator"],
        "why": why,
        "product_code": r["pc"],
        # sku·상품명은 **현재 상품 행**을 쓰고, 상품이 사라졌으면 기록 당시 값으로 떨어진다
        # (둘 다 없으면 지어내지 않고 null).
        "sku": r["sku"] or d.get("sku"),
        "name": r["product_name"],
        "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
        "stock_now": r["stock_qty"],
        "status": r["status"],
        "note": note,
        "ledger_rows": r["ledger_rows"],
        "ref_log_id": d.get("ref_log_id"),
        "undone_by": r["undone_by"],
        # ★ 화면이 판정하지 않는다 — 세 상태(+2)를 서버가 실어 보낸다
        "undoable": undoable, "undo_state": state, "undo_note": undo_note,
    }


@router.get("/stock-inbound/history")
def stock_inbound_history(page: int = 1, size: int = 20, product_code: int | None = None):
    """입고 이력 — **서버 페이지네이션**. 되돌릴 건을 «여기서» 고른다.

    `product_code` 를 주면 그 상품만(우 패널 「이 상품의 입고 이력」), 안 주면 이 화면으로
    처리한 전체(화면 하단 「입고 이력」). **두 자리가 같은 엔드포인트·같은 판정을 쓴다** —
    갈라 구현하면 한쪽만 고치는 사고가 난다(승인 디자인 §골격의 같은 이유).

    전 행을 반환하지 않는다. 「전체 N건 중 이 페이지」를 응답이 말한다(`total`·`pages`).
    """
    size = max(1, min(size, 200))
    page = max(1, page)
    flt = "" if product_code is None else _HIST_FLT
    p = {"size": size, "offset": (page - 1) * size}
    if product_code is not None:
        p["pc"] = product_code
    with engine.connect() as conn:
        rows = conn.execute(text(_HISTORY.format(flt=flt)), p).mappings().all()
        total = conn.execute(text(_HISTORY_COUNT.format(flt=flt)), p).scalar_one()
    op = current_operator() or {}
    role = op.get("role")
    return {
        "page": page, "size": size, "total": total,
        "pages": (total + size - 1) // size,
        "product_code": product_code,
        "items": [_hist_row(r) for r in rows],
        # 권한도 화면이 추정하지 않는다 — 403 은 단추를 감추지 않고 «비활성 + 사유 병기»다.
        "can_write": role in ("operator", "owner"),
        "can_write_note": ("" if role in ("operator", "owner")
                           else "조회 등급은 입고 확정·되돌리기를 할 수 없습니다"),
        "scope_note": HISTORY_SCOPE,
    }


class InboundBody(BaseModel):
    qty: int
    why: str = "inbound"


@router.post("/stock-inbound/{product_code}")
def inbound(product_code: int, body: InboundBody):
    if body.why not in WHY:
        raise HTTPException(400, f"알 수 없는 사유: {body.why}")
    if body.qty <= 0:
        raise HTTPException(400, "입고 수량은 1 이상이어야 합니다")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, stock_qty, status FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        if p["status"] in ("단종", "삭제대기"):
            raise HTTPException(400, f"'{p['status']}' 상품에는 입고할 수 없습니다")
        before, status_changed = p["stock_qty"], False
        log_id = _log(conn, "stock_inbound", p["sku"],
                      {"product_code": product_code, "sku": p["sku"], "qty": body.qty,
                       "why": body.why, "before": {"stock_qty": before, "status": p["status"]}},
                      kind="stock")
        conn.execute(text(
            "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
            " VALUES (:pc, :t, :q, 'manual', :ref)"),
            {"pc": product_code, "t": body.why, "q": body.qty, "ref": log_id})
        conn.execute(text(
            "UPDATE products SET stock_qty = stock_qty + :q, updated_at=now()"
            " WHERE product_code=:pc"), {"q": body.qty, "pc": product_code})
        if p["status"] == "품절":   # 재고가 들어왔으므로 품절 사유 소멸
            conn.execute(text(
                "UPDATE products SET status='판매중' WHERE product_code=:pc"), {"pc": product_code})
            status_changed = True
        return {"ok": True, "undo_id": log_id, "sku": p["sku"],
                "stock_before": before, "stock_after": before + body.qty,
                "status_changed": status_changed,
                "pool_entered": _in_pool(conn, product_code)}


@router.post("/stock-inbound/undo/{log_id}")
def undo_inbound(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "stock_inbound":
            raise HTTPException(404, "되돌릴 입고 기록이 없습니다")
        # 이력의 「이미 되돌림」 판정과 **같은 문장**을 쓴다(_UNDO_ROW) — 갈라지면 목록이
        # 「되돌리기 가능」이라 말한 건에서 409 가 난다.
        dup = conn.execute(text(_UNDO_ROW.format(ref=":i")), {"i": log_id}).scalar()
        if dup:
            raise HTTPException(409, f"이미 되돌린 입고입니다 (되돌림 기록 #{dup})")
        d = log["detail"]
        p = conn.execute(text(
            "SELECT stock_qty, status FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": d["product_code"]}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        if p["stock_qty"] < d["qty"]:
            raise HTTPException(409, "입고분보다 재고가 적습니다 — 이후 판매·조정이 있어 되돌릴 수 없습니다")
        # 원장은 삭제하지 않는다 — 역방향 행으로 상쇄(order_events 전례)
        conn.execute(text(
            "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
            " VALUES (:pc, 'adjust', :q, 'manual', :ref)"),
            {"pc": d["product_code"], "q": -d["qty"], "ref": log_id})
        conn.execute(text(
            "UPDATE products SET stock_qty = stock_qty - :q, updated_at=now()"
            " WHERE product_code=:pc"), {"q": d["qty"], "pc": d["product_code"]})
        before = d.get("before") or {}
        if before.get("status") == "품절" and p["status"] == "판매중":
            conn.execute(text(
                "UPDATE products SET status='품절' WHERE product_code=:pc"),
                {"pc": d["product_code"]})
        _log(conn, "stock_inbound_undo", str(log_id),
             {"ref_log_id": log_id, "product_code": d["product_code"], "qty": d["qty"]},
             kind="stock")
        return {"ok": True, "sku": d.get("sku"), "stock_after": p["stock_qty"] - d["qty"]}
