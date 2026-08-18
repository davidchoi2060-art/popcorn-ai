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
목록 행의 후보 진입 판정(`pool_state`·`pool_label`·`pool_note`)도 **같은 뷰를 실조회한다**
(2026-08-18 신설 — 그전에는 화면이 reviewed·priced·has_specs 셋을 조합했다. 근거·실측은
§_pool_of 주석).
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
from sqlalchemy.exc import IntegrityError

from .admin_orders import _log
from .admin_products import PART_TYPE_LABELS
from .auth import current_operator, current_operator_id
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

WHY = ("inbound", "adjust")
NOTE = ("입고 대기 = 재고 0 또는 **안전재고 미달** 상품입니다(기준은 상품별 safety_stock)"
        " · 매입가 변경은 단가표·매입 견적 소관(입고 원장에는 단가를 남기지 않습니다).")

# ───────────────────────── 입고 대기 조건 — **정본은 여기 하나다** ─────────────────────────
# 이 조건은 2026-08-17 까지 **세 파일에 SQL 문자열로 복제**돼 있었다(정의서 §④-다):
#     api/admin_stock.py(여기) · api/admin_sourcing.py `_WHERE` · api/admin_dashboard.py `pending_counts`
# 셋이 같아야 한다는 것은 «규약이 아니라 검사»로 이미 못박혀 있다 —
#     tests/regression.py  「입고 대기 = 대시보드 집계」 · 「매입 대기 = 입고 대기(같은 파생 조건)」
# 보류(0056)를 여기서만 제외하면 **그 두 검사가 실패한다.** 그래서 조건을 함수 하나로 내보내고
# 나머지 두 파일이 이것을 부르게 한다(그 두 파일은 이 작업의 담당 밖 — 보고로 넘긴다).
# ⚠ 별칭은 **`p` 고정**이다. 부르는 쪽이 `FROM products p` 로 써야 한다.
HOLD_ACTIVE = ("EXISTS (SELECT 1 FROM stock_inbound_holds h"
               " WHERE h.product_code = p.product_code AND h.released_at IS NULL)")

_PENDING_BASE = """p.status NOT IN ('단종','삭제대기')
      AND (p.stock_qty = 0
           OR (p.safety_stock IS NOT NULL AND p.stock_qty < p.safety_stock))"""

HOLD_MODES = ("exclude", "only", "all")

HOLD_SCOPE = (" 보류분은 기본 조회에서 빠집니다(hold=only 로 보류분만 조회)."
              " 보류는 서버 상태이며 해제는 행 삭제가 아니라 해제 시각 기록입니다."
              " 보류 중인 상품에는 입고를 확정할 수 없습니다 — 보류를 먼저 해제하십시오"
              "(되돌리기는 보류 중에도 할 수 있습니다).")


def pending_where(hold: str = "exclude") -> str:
    """입고 대기 조건 — **단일 원천.** 다른 모듈은 이 함수를 부른다(문자열을 다시 적지 않는다).

        exclude  기본 — 보류분을 «뺀다»(승인 디자인: 「보류분은 기본 조회에서 빠진다」)
        only     보류분만 — 「별도 조건으로 다시 본다」
        all      보류 여부를 따지지 않는다(보류 도입 이전과 같은 모집단)

    ⚠ 대시보드·매입 견적은 **`exclude`(기본)** 를 써야 한다 — 「입고 대기」라는 같은 말을
      세 화면이 다른 수로 말하면 안 된다(회귀가 그 일치를 검사한다).
    """
    if hold == "only":
        return f"{_PENDING_BASE}\n      AND {HOLD_ACTIVE}"
    if hold == "all":
        return _PENDING_BASE
    return f"{_PENDING_BASE}\n      AND NOT {HOLD_ACTIVE}"


_PENDING = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.status, p.stock_qty,
           p.safety_stock, p.purchase_price, p.sale_price,
           p.review_required_yn, p.ai_candidate_yn,
           psp.cost_price, s.name AS supplier,
           EXISTS(SELECT 1 FROM product_specs sp WHERE sp.product_code = p.product_code) AS has_specs,
           h.hold_id, h.reason AS hold_reason, h.held_at, COALESCE(ho.name, '—') AS hold_by
    FROM products p
    LEFT JOIN (SELECT DISTINCT ON (product_code) product_code, supplier_id, cost_price
               FROM product_supplier_prices ORDER BY product_code, cost_price) psp
           USING (product_code)
    LEFT JOIN suppliers s USING (supplier_id)
    -- 활성 보류는 상품당 최대 1건이다(0056 부분 유니크 인덱스) — 그래서 이 LEFT JOIN 이
    -- 행을 늘리지 않는다. 인덱스가 없었다면 목록 건수가 조용히 부풀었을 자리다.
    LEFT JOIN stock_inbound_holds h
           ON h.product_code = p.product_code AND h.released_at IS NULL
    LEFT JOIN admin_operators ho ON ho.operator_id = h.held_by
    WHERE {where}
      AND (:q = '' OR p.product_name ILIKE '%%' || :q || '%%' OR p.sku ILIKE '%%' || :q || '%%')
      AND (:part_type = '' OR p.part_type = :part_type)
    ORDER BY (p.stock_qty > 0), p.product_code
    LIMIT :size OFFSET :offset
"""

# 목록과 같은 조건의 총계 — 화면이 '전체 N건 중 이 페이지'를 정직하게 말하려면 필요하다
_PENDING_COUNT = """
    SELECT count(*) FROM products p
    WHERE {where}
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


# ───────────── 목록 행의 후보 진입 판정 — **서버가 뷰를 실조회한다** ─────────────
# 계약 §3중 게이트: 「서버가 v_recommendation_candidates 를 실조회한다 — 화면이 판정하지
# 않는다」. 2026-08-18 까지 이 판정을 **화면이** 했다(`verdictOf()` 가 reviewed·priced·
# has_specs 셋을 조합). 그 조합은 뷰가 함께 거르는 나머지를 못 본다 —
#     ai_candidate_yn · category_group='core_part' · part_type(핵심 10종) ·
#     data_origin <> 'demo' · status='판매중'
# 실측(2026-08-18 · 입고 대기 15,725행): 셋을 다 통과한 행 10,540건 중 **3,876건은
# 그 밖의 조건 때문에 뷰에 영영 들어가지 않는다.** 재고>0 인 2건(P-4101·P-4103)도
# 셋을 다 통과하지만 `data_origin='demo'` 라 후보가 아닌데, 화면은 「후보 진입 가능」
# 이라 말하고 있었다 — **미래형인 것도 틀렸고 판정 자체도 틀렸다.**
#
# 그래서 판정을 뷰 실조회로 옮긴다. 확정 응답 `pool_entered` 가 부르는 그 뷰이므로
# **확정 전 라벨과 확정 후 값이 같은 원천**을 쓴다(갈라지면 확정하는 순간 말이 바뀐다).
#
# ⚠ 뷰는 재고를 거르지 않지만 **status='판매중' 은 거른다.** 그런데 입고 확정이 하는
#   일 중 하나가 「품절 -> 판매중」이다. 즉 **품절 행은 뷰가 false 를 주는 이유가
#   「입고가 없앨 그 조건」 자체**라, 그 false 로는 나머지 게이트를 알 수 없다.
#   그런 행에 「진입 불가」를 붙이면 지어내는 것이고, 「진입 가능」을 붙여도 지어내는
#   것이다 — 그래서 **판정하지 않고**(`unknown`) 사유(note)만 보인다.
#   품절 행까지 정확히 판정하려면 「재고·상태를 뺀 후보 자격」이 뷰나 함수로 하나
#   있어야 한다(여기서 술어를 다시 적으면 admin_pool.py 가 이미 겪은 갈라짐이다 —
#   그 파일 주석의 3,219 대 3,242 가 그 사고다). **신설은 마이그레이션 소관이라 이
#   작업의 범위 밖이다** — 보고로 넘긴다.
POOL_LABELS = {
    "in": "추천 후보 포함",
    "enters": "입고 확정 시 후보 진입",
    "out": "추천 후보 제외",
    "blocked": "입고 확정 후에도 진입 불가",
    "unknown": "입고 확정 후 판정",
}


def _pool_gaps(r) -> list:
    """뷰 조건 중 **이 응답이 직접 읽는 셋**의 미충족 목록 — 예측이 아니라 사실이다.

    ⚠ 방향이 하나뿐이다. 뷰의 WHERE 는 여덟 조각의 **AND** 이므로
        · 셋 중 하나라도 거짓 -> 전체가 거짓 -> 「진입 불가」는 **참**이다(읽은 것만으로 증명된다)
        · 셋이 다 참 -> 나머지 다섯을 모르므로 **아무 말도 못 한다**(이게 3,876행을 만든 방향이다)
    `blocked` 는 앞의 방향만 쓴다. 뒤의 방향은 오직 뷰 실조회(`in_view`)가 답한다.
    """
    gaps = []
    if r["review_required_yn"]:
        gaps.append("검수 미통과")
    if r["sale_price"] is None:
        gaps.append("판매가 미산정")
    if not r["has_specs"]:
        # 추천 뷰는 product_specs 를 조인한다 — 사양 행이 없으면 재고·가격이 다 차도 미진입
        gaps.append("사양 행 없음")
    return gaps


def _pool_of(r, in_view: bool) -> dict:
    """행 하나의 후보 진입 «판정 + 사유» — **한 원천에서 둘 다 나온다.**

    2026-08-18 후속 개정. 처음에는 판정(`pool_label`)만 여기서 만들고 사유는 `note`
    (구 `_note_of`)를 그대로 썼는데, 화면이 둘을 한 행에 나란히 그리면서
    **「추천 후보 제외」 옆에 「입고 시 추천 가능 재고 진입」**이 동시에 떴다(확인자 재현
    P-9103). 라벨만 새 원천으로 바꾸고 사유를 옛 원천에 두면 결함이 형태만 바꿔 재발한다.
    그래서 **사유는 판정과 같은 자리에서 만든다** — 화면은 이 둘만 붙여 쓴다.
    """
    stock = r["stock_qty"] or 0
    gaps = _pool_gaps(r)
    if in_view:
        st = "in" if stock > 0 else "enters"
        note = ("추천 후보 뷰 조회됨 · 재고 있음" if stock > 0
                else "추천 후보 뷰 조회됨 · 재고만 미충족")
    elif r["status"] != "품절":
        # 판매중인데 뷰에 없다 = **지금 상태가 곧 답이다**(미래형으로 말할 것이 없다)
        st = "out"
        note = "추천 후보 뷰 미조회 — " + (" · ".join(gaps) if gaps
                                          else "재고 외 조건 미충족")
    elif gaps:
        st = "blocked"
        note = "뷰 조건 미충족 — " + " · ".join(gaps) + " (입고로 해소되지 않음)"
    else:
        st = "unknown"
        note = ("검수·판매가·사양 행 충족 · 품절 상태가 후보 뷰 조건이라 확정 전 판정 없음"
                " (확정 응답 pool_entered 로 확인)")
    return {"pool_state": st, "pool_label": POOL_LABELS[st], "pool_note": note}


def _note_of(r) -> str:
    """이 행이 **왜 입고 대기인가** — 대기 유형(사실)만 말한다.

    2026-08-18 개정. 그전에는 이 문장이 「입고 시 추천 가능 재고 진입」처럼 **후보 진입을
    약속**했다. 그 약속은 뷰 여덟 조건 중 셋만 보고 한 것이라 실측 3,876행에서 거짓이었고,
    판정을 뷰 실조회로 옮긴 뒤에는 **같은 행에서 라벨과 정반대 문장**이 됐다.
    **후보 진입은 `pool_*` 셋이 전담한다 — 여기서는 말하지 않는다.**
    (대기 조건 정본은 §입고 대기 조건: 재고 0 ∨ 안전재고 미달. 이 함수는 그 둘 중
     어느 쪽인지를 값과 함께 말하는 자리다.)
    """
    stock = r["stock_qty"] or 0
    if stock > 0:
        if r["safety_stock"] and stock < r["safety_stock"]:
            return (f"안전재고 미달 — 현재 {stock} / 기준 {r['safety_stock']}"
                    " (판매는 계속되지만 소진 위험)")
        # 대기 조건 밖 — 조회와 표시 사이에 재고가 들어온 행이다. 지어내지 않고 값만 말한다.
        return f"재고 {stock} — 대기 조건 밖(조회 이후 변동)"
    if r["status"] == "품절":
        return "재고 0 · 품절 표시 — 입고 확정 시 판매중 복귀"
    return "재고 0"


@router.get("/stock-inbound")
def stock_inbound(page: int = 1, size: int = 50, q: str = "", part_type: str = "",
                  catalog_q: str = "", hold: str = "exclude"):
    """입고 대상 — **서버 페이지네이션**(슬라이스 54).

    전량 전송이던 것을 나눠 보낸다: 입고 대상 15,259건 · 카탈로그 22,838건을 매 요청마다
    보내면 화면이 느려지고 브라우저가 버티지 못한다(상품 관리는 이미 페이지네이션이다).
    직접 등록용 `catalog`은 **검색어가 있을 때만** 최대 50건 — 셀렉트 하나 때문에 전량을
    보낼 이유가 없다.

    `hold` — **보류분은 기본 조회에서 빠진다**(`exclude`). `only` 로 보류분만 다시 보고,
    `all` 은 보류 여부를 따지지 않는다. 구 화면은 보류를 «브라우저 배열»에서만 지워
    다음 조회에 그대로 되살아났다 — 이제 서버 상태다(마이그레이션 0056).
    """
    if hold not in HOLD_MODES:
        raise HTTPException(400, f"알 수 없는 보류 조건: {hold}"
                                 f" (허용값 {' · '.join(HOLD_MODES)})")
    size = max(1, min(size, 200))
    page = max(1, page)
    p = {"q": q.strip(), "part_type": part_type.strip(),
         "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        rows = conn.execute(text(_PENDING.format(where=pending_where(hold))), p).mappings().all()
        total = conn.execute(text(
            _PENDING_COUNT.format(where=pending_where(hold))), p).scalar_one()
        # 「보류 N건 제외」를 화면이 세지 않게 서버가 준다 — 같은 조회 조건(q·분류)에서 센다.
        held_total = conn.execute(text(
            _PENDING_COUNT.format(where=pending_where("only"))), p).scalar_one()
        cq = catalog_q.strip()
        catalog = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, purchase_price, stock_qty,"
            " sale_price, review_required_yn, status,"
            # `_pool_gaps()` 가 셋을 다 읽어야 「진입 불가」를 증명할 수 있다 — 사양 행만
            # 빠지면 카탈로그 행에서 그 판정을 못 한다(최대 50행이라 EXISTS 비용은 작다).
            " EXISTS(SELECT 1 FROM product_specs sp"
            "        WHERE sp.product_code = products.product_code) AS has_specs"
            " FROM products WHERE status NOT IN ('단종','삭제대기')"
            "   AND (product_name ILIKE '%%' || :cq || '%%' OR sku ILIKE '%%' || :cq || '%%')"
            " ORDER BY sku LIMIT 50"), {"cq": cq}).mappings().all() if cq else []
        # ★ 후보 진입 판정 — 이 페이지에 실제로 나가는 코드만 뷰에 물어본다(최대 100건).
        #   목록 SQL 안의 상관 서브쿼리로 넣지 않는다: ORDER BY + LIMIT 앞에서 15,725행
        #   전부에 대해 평가될 수 있다(statement_timeout 15초를 쓰는 엔진이다 — db.py).
        codes = [r["product_code"] for r in rows] + [c["product_code"] for c in catalog]
        in_view = set(conn.execute(text(
            "SELECT product_code FROM v_recommendation_candidates"
            " WHERE product_code = ANY(:codes)"), {"codes": codes}).scalars()) if codes else set()
    return {
        "page": page, "size": size, "total": total,
        "pages": (total + size - 1) // size,
        "catalog_q": catalog_q.strip(),
        # 「전체 N건 중 이 페이지」와 별개로 **보류가 몇 건 빠졌는지**를 함께 말한다 —
        # 안 그러면 어제와 오늘의 total 이 왜 다른지 화면이 설명하지 못한다.
        "hold": hold, "held_total": held_total,
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
            # ★ 화면이 판정하지 않는다 — 뷰 실조회 결과를 서버가 문구까지 실어 보낸다
            **_pool_of(r, r["product_code"] in in_view),
            # 보류는 «서버 상태»다 — 화면 배열이 아니다(구 화면 결함 2).
            # exclude 조회에서는 언제나 null 이고, only·all 에서만 값이 선다.
            "hold": None if r["hold_id"] is None else {
                "hold_id": r["hold_id"], "reason": r["hold_reason"],
                "held_at": iso(r["held_at"]), "held_by": r["hold_by"]},
        } for r in rows],
        "catalog": [{
            "product_code": c["product_code"], "sku": c["sku"], "name": c["product_name"],
            "cat": PART_TYPE_LABELS.get(c["part_type"], c["part_type"]),
            "purchase": c["purchase_price"], "stock": c["stock_qty"],
            "priced": c["sale_price"] is not None, "reviewed": not c["review_required_yn"],
            "status": c["status"], "has_specs": c["has_specs"],
            # 직접 등록 후보도 같은 판정을 받는다 — 이 응답에는 사양 행 정보가 없어
            # 화면이 조합할 수 없던 자리다(그래서 「판정 없음」이 떴다).
            **_pool_of(c, c["product_code"] in in_view),
        } for c in catalog],
        "note": NOTE + (" 목록은 서버에서 나눠 보냅니다 — 화면은 '전체 N건 중 이 페이지'를"
                        " 표시합니다. 직접 등록 후보는 검색어를 입력해야 조회됩니다"
                        "(22,838건 전량 전송을 없앴습니다).") + HOLD_SCOPE,
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
        note += " · 원장 행 없음 — 대응 원장 행 미조회"
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
        # 문구는 계약 §서버 응답 표 원문 그대로다. 화면이 이 값으로 단추 title 을 덮으므로
        # 화면 폴백과 다르게 적으면 **응답 전후로 같은 자리의 문구가 바뀐다**
        # (화면 폴백은 처음부터 계약 원문이었고 여기만 등급 이름을 달리 불렀다).
        "can_write_note": ("" if role in ("operator", "owner")
                           else "viewer 등급은 입고 확정·되돌리기를 할 수 없습니다"),
        "scope_note": HISTORY_SCOPE,
    }


class InboundBody(BaseModel):
    qty: int
    why: str = "inbound"


@router.post("/stock-inbound/{product_code}")
def inbound(product_code: int, body: InboundBody):
    if body.why not in WHY:
        # 계약 §서버 응답 표 원문. 화면의 사전검증도 같은 문구를 쓴다 — 서버만 달랐다.
        raise HTTPException(400, "알 수 없는 사유입니다 (허용값 inbound·adjust 둘뿐)")
    if body.qty <= 0:
        raise HTTPException(400, "입고 수량은 1 이상이어야 합니다")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, stock_qty, status FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            # 계약 §서버 응답 표 「상품 없음」 원문. `_undo_state()` 의 product_missing 분기가
            # 처음부터 이 문장을 썼는데 **같은 사실을 가리키는 이 파일의 404 넷은 더 짧은
            # 다른 문장**이었다 — 목록이 사유를 한 문장으로 말해 놓고 실제로 누르면 다른
            # 문장이 떴다. 넷을 이 문장으로 모았다(2026-08-18).
            raise HTTPException(404, "상품을 찾을 수 없습니다 — 조회 이후 삭제됐습니다")
        if p["status"] in ("단종", "삭제대기"):
            raise HTTPException(400, f"'{p['status']}' 상품에는 입고할 수 없습니다")
        # ★ 보류 중이면 입고를 «막는다» (2026-08-17 판정 — 근거를 남긴다).
        #   보류는 「지금 이 상품에 손대지 않는다」는 뜻이다. 막지 않으면 보류가
        #   «목록에서만 안 보이는 화면 편의»가 되고, 그것이 정확히 구 화면의 결함
        #   (서버가 모르는 보류)과 같은 결과다 — 상태로 남긴 이유가 사라진다.
        #   ⚠ 실제 입고를 막는 것이 아니다: 해제가 한 번의 호출이고 그 해제가 기록으로
        #     남는다. 즉 「물건이 들어왔으니 보류를 푼다」가 원장에 남는 편이 낫다.
        #   ⚠ **되돌리기(undo)는 막지 않는다** — 되돌리기는 새 입고가 아니라 «교정»이다.
        #     보류가 교정을 막으면 잘못 넣은 수량이 보류 때문에 굳는다.
        held = conn.execute(text(
            "SELECT hold_id, reason FROM stock_inbound_holds"
            " WHERE product_code=:pc AND released_at IS NULL"),
            {"pc": product_code}).mappings().first()
        if held:
            raise HTTPException(409, f"보류 중인 상품입니다 (보류 #{held['hold_id']}"
                                     f" · 사유 {held['reason']})"
                                     " — 보류를 먼저 해제한 뒤 입고를 확정하십시오")
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


class HoldBody(BaseModel):
    reason: str = ""


@router.post("/stock-inbound/hold/{product_code}")
def hold_product(product_code: int, body: HoldBody):
    """입고 보류 — **서버 상태로 남긴다**(사장님 확정 ㉡ · 마이그레이션 0056).

    구 화면은 `R.splice(i,1)` 로 브라우저 배열에서만 지우고 「보류 — 재고 미반영」을
    띄웠다. 대기 목록은 파생이라 **다음 조회에 그대로 되살아났다** — 운영자는 처리됐다고
    읽는데 서버는 몰랐다. 이제 보류는 행이고, 조회에서 실제로 빠진다.
    """
    reason = (body.reason or "").strip()
    if not reason:
        # `reason` 은 NOT NULL 이다(0056). 빈 값을 넣어 DB 오류(500)로 만들지 않고
        # **왜 안 되는지를 사람 말로** 돌려준다.
        raise HTTPException(400, "보류 사유를 입력하십시오")
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, status, stock_qty FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품을 찾을 수 없습니다 — 조회 이후 삭제됐습니다")
        if p["status"] in ("단종", "삭제대기"):
            # 대기 목록에 애초에 없는 상품이다 — 보류할 것이 없다.
            raise HTTPException(400, f"'{p['status']}' 상품은 입고 대기 대상이 아니므로"
                                     " 보류할 수 없습니다")
        cur = conn.execute(text(
            "SELECT hold_id, reason, held_at FROM stock_inbound_holds"
            " WHERE product_code=:pc AND released_at IS NULL"),
            {"pc": product_code}).mappings().first()
        if cur:
            # 부분 유니크 인덱스(ux_stock_inbound_holds_active)가 DB 에서 막는 것을
            # **사람 말로 옮긴다.** 인덱스는 최후의 보루로 남는다(아래 IntegrityError).
            raise HTTPException(409, f"이미 보류 중입니다 (보류 #{cur['hold_id']}"
                                     f" · 사유 {cur['reason']}"
                                     f" · 보류 시각 {iso(cur['held_at'])})")
        try:
            hold_id = conn.execute(text(
                "INSERT INTO stock_inbound_holds (product_code, reason, held_by)"
                " VALUES (:pc, :r, :op) RETURNING hold_id"),
                {"pc": product_code, "r": reason, "op": current_operator_id()}).scalar()
        except IntegrityError:
            # 위 조회와 INSERT 사이에 다른 작업자가 먼저 넣은 경우. 상품 행을 FOR UPDATE 로
            # 잡고 있어 실제로는 거의 나지 않지만, **DB 가 막은 것을 500 으로 흘리지 않는다.**
            raise HTTPException(409, "이미 보류 중입니다 — 다른 작업자가 방금 보류했습니다")
        log_id = _log(conn, "stock_hold", p["sku"],
                      {"hold_id": hold_id, "product_code": product_code,
                       "sku": p["sku"], "reason": reason,
                       "before": {"stock_qty": p["stock_qty"], "status": p["status"]}},
                      kind="stock")
        return {"ok": True, "hold_id": hold_id, "log_id": log_id, "sku": p["sku"],
                "product_code": product_code, "reason": reason,
                "note": "보류 중에는 입고를 확정할 수 없습니다."
                        " 목록 기본 조회에서 빠지며 hold=only 로 다시 조회합니다."}


@router.post("/stock-inbound/hold/{product_code}/release")
def release_hold(product_code: int):
    """보류 해제 — **행을 지우지 않는다.** `released_at` 을 기록한다(원장·되돌림 규약).

    DELETE 가 아니라 POST `/release` 인 것이 계약이다 — 삭제로 부르면 언젠가 삭제로 짓는다.
    """
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품을 찾을 수 없습니다 — 조회 이후 삭제됐습니다")
        cur = conn.execute(text(
            "SELECT hold_id FROM stock_inbound_holds"
            " WHERE product_code=:pc AND released_at IS NULL"),
            {"pc": product_code}).mappings().first()
        if cur is None:
            # **사유를 갈라 말한다** — 되돌리기가 404(기록 없음) / 409(이미 되돌림)를
            # 가르는 것과 같은 형태다. 「해제할 게 없다」와 「이미 해제됐다」는 다른 사실이고,
            # 운영자가 다음에 할 일도 다르다.
            last = conn.execute(text(
                "SELECT hold_id, released_at FROM stock_inbound_holds"
                " WHERE product_code=:pc ORDER BY hold_id DESC LIMIT 1"),
                {"pc": product_code}).mappings().first()
            if last:
                raise HTTPException(409, f"이미 해제된 보류입니다 (보류 #{last['hold_id']}"
                                         f" · 해제 시각 {iso(last['released_at'])})")
            raise HTTPException(404, "보류 기록이 없습니다")
        conn.execute(text(
            "UPDATE stock_inbound_holds SET released_at = now(), released_by = :op"
            " WHERE hold_id = :h"), {"op": current_operator_id(), "h": cur["hold_id"]})
        # ⚠ 역참조 키로 `ref_log_id` 를 «쓰지 않는다». 그 키는 «되돌림»의 표식이고,
        #   활동 기록 화면이 그것으로 원 기록에 「되돌려짐」 배지를 붙인다. 해제는
        #   되돌림이 아니다 — 보류가 틀렸다는 뜻이 아니라 끝났다는 뜻이다. 대신
        #   `hold_id`(표의 행)로 잇는다. 그 편이 로그 id 보다 오래 남는 연결이다.
        log_id = _log(conn, "stock_hold_release", p["sku"],
                      {"hold_id": cur["hold_id"], "product_code": product_code,
                       "sku": p["sku"]}, kind="stock")
        return {"ok": True, "hold_id": cur["hold_id"], "log_id": log_id, "sku": p["sku"],
                "product_code": product_code,
                "note": "보류를 해제했습니다. 입고 대기 목록에 다시 나타납니다"
                        "(보류 행은 지우지 않고 해제 시각을 기록했습니다)."}


@router.post("/stock-inbound/undo/{log_id}")
def undo_inbound(log_id: int):
    # ⚠ 보류 중이어도 되돌리기는 «막지 않는다» — 근거는 inbound() 의 보류 가드 주석.
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
            raise HTTPException(404, "상품을 찾을 수 없습니다 — 조회 이후 삭제됐습니다")
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
