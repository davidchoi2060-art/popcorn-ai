# -*- coding: utf-8 -*-
"""판매가 관리(ADM-PRC-060) — 페이지 라우트 + 데이터 API. `api/main.py`가 자동으로 싣는다.

■ 계약 — `docs/design/spec-sale-price.md`(1b 골격 + 1a 우측 서랍, 사장님 확정 2026-08-15)

■ 이 화면의 정체 — 값을 «정하는» 곳이 아니라 «예외를 잡는» 곳이다
    기본 = 몰 가격 그대로 · 예외 = 직접 소싱해 덮어쓰고 잠근 값
    경보 = 잠기지 않았는데 몰과 어긋난 건(동기화 누락)
  정상(일치·손대지 않음)은 목록에 올리지 않는다.

■ 데이터 실측(2026-08-15, 읽기 전용 쿼리로 확인 — 보고서에 근거 남김)
    ① 판매가·매입가          products.sale_price · products.purchase_price (ERD §3.2)
    ② 몰값 저장 자리          **없다.** 저장 컬럼이 아니라 그때그때 조회하는 값(계약대로).
                              대신 두 원천이 있다:
                                출처① handoff_items.price_mall + mall_status
                                      (인계 시점 관측 — handoffs.handoff_no/created_at과 조인)
                                출처② api/mall.py의 fetch_prices() — **실시간 조회 함수는
                                      있으나 관리자 API로 노출된 적이 없다**(api/handoff.py
                                      내부에서만 호출됨, grep으로 확인 — 다른 어떤 라우터도
                                      mall 모듈을 쓰지 않는다). 그래서 「지금 물어보기」는
                                      이번 화면에서 짓지 않는다(사장님 확정 2026-08-15:
                                      "실서비스 조회는 API로 만들 예정 업무로 기록" — 새로
                                      만들지 말고 잠그라는 지시). 아래 LIVE_CHECK_* 상수가
                                      그 잠금 사유를 담는다.
    ③ 잠금                    products.locked_fields JSONB (@> '["sale_price"]')
    ④ 가격 이력                product_price_history(product_code, field, old_price, new_price,
                              reason, ref_id, changed_at) — 읽기용 참고 구현이 이미 있다
                              (api/admin_price_history.py, 이 화면은 그 파일을 고치지 않고
                              같은 테이블을 직접 읽는다 — 화면 하나 = 파일 하나 규약).
    ⑤ 인계(HO-xxxx) 기록의 몰 가격   handoff_items.price_mall + handoffs.handoff_no/created_at.
                              실측: handoffs 3건(HO-1001~1003) · handoff_items 27행 ·
                              item_kind='core_part' 24행 · distinct product 16종.
    ⑥ 쓰기 API                **없었다.** 비슷해 보이는 후보 둘을 확인했지만 둘 다 안 맞는다:
                                `PATCH /api/admin/products/{code}` — sale_price를 고치지만
                                  **product_price_history에 쓰지 않는다**(직접 확인 —
                                  실제로 locked_fields=['sale_price']인 상품 46158의 이력이
                                  2026-08-05에서 멈춰 있는데 현재값은 그 이후 값이다.
                                  이 화면 소관 밖의 기존 격차이지 이번에 만든 문제가 아니다).
                                `POST /api/admin/price-review/{code}/decide` — 전제 조건이
                                  `sale_price IS NULL`(첫 산정 전용, ADM-PRC-010 소관)이라
                                  이미 판매가가 있는 예외 큐 항목에는 애초에 안 걸린다.
                              그래서 이 화면 전용 쓰기 엔드포인트 둘(match/lock)을 새로
                              만들었다 — product_price_history를 **반드시** 남기도록.

■ 권한 — 별도 코드 없이 이미 만족된다
  `/api/admin/*`의 기본 규칙(api/auth.py required_role)이 GET=viewer, 그 외(POST)=operator다.
  `sale-price`는 OWNER_WRITE_PREFIXES에 없으므로 맞추기·잠그기는 자동으로 operator 이상만
  통과한다 — 계약의 "맞추기·잠그기 operator 이상"이 이미 전역 미들웨어로 충족된다.

■ 매입가 토글 — 잠근다
  판매가 쪽과 달리 "몰 매입가"라는 개념 자체가 없다(몰은 소비자가 페이지라 판매가·딜러가만
  노출한다 — api/mall.py가 읽는 필드도 price/dealer_price뿐이다). 비교 대상이 없으므로
  API 유무를 떠나 이 화면에서 매입가 축은 만들 수 없다 — 토글을 잠그고 그 사실을 밝힌다.

■ 문구 — CLAUDE.md §문구 표준과 원안의 예시 문장이 어긋나는 지점(판단 기록)
  원안은 카드 설명 예시에 "우리 견적"을, 서랍 버튼에 "우리가 소싱한"을 쓴다. 다만 이 두 자리는
  "「이 화면이 지키는 것」 5줄(그대로 쓴다)"처럼 verbatim으로 못박히지 않은 **예시**다(그
  5줄만 "그대로 쓴다"고 명시됨). 관리도구 문체 규약("「우리」 같은 대화체 주어 금지")과
  충돌하므로, 동적으로 생성하는 문구에서는 "우리"를 빼고 객체 중심으로 다시 쓴다. 5줄
  자체는 원문 그대로 옮긴다(그 블록은 verbatim 지시가 명시돼 있다). 서랍 섹션 제목
  "「이 값을 어떻게 할까요」"도 의문형이라 명사형 "처리 방법"으로 바꿨다 — 같은 이유.
"""
import json as _json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .admin_ui_common import render
from .auth import current_operator_id
from .db import engine
from .taxonomy import part_label
from .timeutil import iso

router = APIRouter(tags=["admin-ui"])

# 「지금 물어보기」— 실서비스를 실제로 치는 기능. 서버에 관리자용 조회 API가 없고(위 docstring
# ⑥), 사장님 확정(2026-08-15)으로 "API로 만들 예정 업무"로 이관됐다 — 여기서 새로 안 만든다.
LIVE_CHECK_AVAILABLE = False
LIVE_CHECK_REASON = "실서비스 조회 API 준비 중"

# 매입가 축 — 비교할 몰 매입가 개념 자체가 없다(위 docstring 참조).
PURCHASE_AXIS_AVAILABLE = False
PURCHASE_AXIS_REASON = "몰에는 매입가 개념이 없어 비교 대상이 없습니다"

# 관측 대상 — 실제 판매 대상 상품만(조립비 같은 서비스 라인은 이 화면 소관이 아니다).
OBS_KINDS = ("core_part", "peripheral")


def _signed_won(n) -> str | None:
    return None if n is None else f"{n:+,}원"


def _latest_obs_rows(conn):
    """관측(인계) 이력이 있는 상품의 최신 1건 + 현재 판매가·잠금 상태."""
    return conn.execute(text("""
        WITH latest_obs AS (
          SELECT DISTINCT ON (hi.product_code)
                 hi.product_code, hi.price_mall, hi.mall_status,
                 h.handoff_no, h.created_at AS observed_at
          FROM handoff_items hi JOIN handoffs h USING (handoff_id)
          WHERE hi.product_code IS NOT NULL AND hi.item_kind = ANY(:kinds)
          ORDER BY hi.product_code, h.created_at DESC
        )
        SELECT lo.product_code, lo.price_mall, lo.mall_status, lo.handoff_no, lo.observed_at,
               p.sku, p.product_name, p.part_type, p.sale_price, p.status, p.data_origin,
               (p.locked_fields @> '["sale_price"]'::jsonb) AS locked,
               (CASE WHEN lo.observed_at < now() - interval '30 days' THEN 'stale'
                     WHEN lo.observed_at < now() - interval '8 days' THEN 'mid'
                     ELSE 'fresh' END) AS freshness
        FROM latest_obs lo JOIN products p USING (product_code)
        ORDER BY p.product_code
    """), {"kinds": list(OBS_KINDS)}).mappings().all()


def _locked_all_rows(conn):
    return conn.execute(text("""
        SELECT product_code, sku, product_name, part_type, sale_price, status, data_origin
        FROM products WHERE locked_fields @> '["sale_price"]'::jsonb
        ORDER BY product_code
    """)).mappings().all()


def _last_price_change(conn, codes: list[int]) -> dict:
    if not codes:
        return {}
    rows = conn.execute(text(
        "SELECT product_code, MAX(changed_at) AS last_at FROM product_price_history"
        " WHERE field='sale' AND product_code = ANY(:codes) GROUP BY product_code"),
        {"codes": codes}).mappings().all()
    return {r["product_code"]: r["last_at"] for r in rows}


def _single_obs(conn, product_code: int):
    """상품 하나의 최신 관측(서랍 상세용) — 없으면 None."""
    return conn.execute(text("""
        SELECT hi.price_mall, hi.mall_status, h.handoff_no, h.created_at AS observed_at
        FROM handoff_items hi JOIN handoffs h USING (handoff_id)
        WHERE hi.product_code = :pc AND hi.item_kind = ANY(:kinds)
        ORDER BY h.created_at DESC LIMIT 1
    """), {"pc": product_code, "kinds": list(OBS_KINDS)}).mappings().first()


def _classify(locked: bool, observed: bool, price_mall, sale_price) -> str:
    """상태 판정 — **"시도했는데 실패"와 "아예 시도한 적 없음"을 다른 상태로 가른다.**

    큐(summary)는 관측이 있는 라인만 다루므로 observed는 언제나 True다.
    detail()은 임의 상품을 받으므로 관측이 통째로 없는 경우(22,841건 중 대다수)가
    실제로 나온다 — 이걸 "확인 못함"(시도했으나 실패)과 같은 배지로 묶으면
    "시도해봤는데 안 됐다"는 사실이 아닌 말이 된다.
    """
    if locked:
        return "locked"
    if not observed:
        return "no_check"
    if price_mall is None:
        return "unknown"
    if price_mall != sale_price:
        return "alert"
    return "normal"


def _reason_text(kind: str, *, sale_price=None, mall_price=None, handoff_no=None) -> str:
    if kind == "alert":
        diff = mall_price - sale_price
        if diff < 0:
            return f"몰이 {abs(diff):,}원 더 쌉니다. 판매가가 몰보다 비싸면 견적의 신뢰가 깨집니다."
        return f"몰이 {diff:,}원 더 비쌉니다. 판매가가 몰 가격 변동을 반영하지 못했습니다."
    if kind == "unknown":
        return f"인계 시점({handoff_no})에 몰 가격을 확인하지 못했습니다."
    if kind == "no_check":
        return "몰 값을 확인한 적이 없는 상품입니다."
    if kind == "locked":
        if mall_price is None:
            return f"직접 소싱해 {sale_price:,}원으로 잠갔습니다. 몰 값은 확인된 적이 없습니다."
        return f"직접 소싱해 {sale_price:,}원으로 잠갔습니다. 몰은 {mall_price:,}원입니다."
    return ""


KIND_LABEL = {"alert": "경보", "unknown": "확인 못함", "locked": "예외(잠금)",
              "no_check": "미확인", "normal": "정상"}


# ══════════════════════════════════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════════════════════════════════
@router.get("/admin2/sale-price", response_class=HTMLResponse)
def sale_price_page(request: Request) -> HTMLResponse:
    return render(request, "admin/sale_price.html.j2",
                  screen_id="ADM-PRC-060", domain="sale-price",
                  crumb_group="판매가", crumb_now="판매가 관리")


# ══════════════════════════════════════════════════════════════════════════
# 데이터 API
# ══════════════════════════════════════════════════════════════════════════
@router.get("/api/admin/sale-price/summary")
def summary():
    with engine.connect() as conn:
        obs = _latest_obs_rows(conn)
        locked_all = _locked_all_rows(conn)
        total_products = conn.execute(text("SELECT count(*) FROM products")).scalar_one()

    obs_codes = {r["product_code"] for r in obs}
    codes_for_history = list(obs_codes | {r["product_code"] for r in locked_all})
    with engine.connect() as conn:
        last_change = _last_price_change(conn, codes_for_history)

    alert, unknown, locked_in_sample = [], [], []
    stale_n = mid_n = fresh_n = 0
    for r in obs:
        kind = _classify(r["locked"], True, r["price_mall"], r["sale_price"])
        if kind == "locked":
            locked_in_sample.append(r)
        elif kind == "unknown":
            unknown.append(r)
        elif kind == "alert":
            alert.append(r)
        if r["freshness"] == "stale":
            stale_n += 1
        elif r["freshness"] == "mid":
            mid_n += 1
        else:
            fresh_n += 1

    locked_extra = [r for r in locked_all if r["product_code"] not in obs_codes]

    def _card(r, kind, *, is_extra=False):
        pc = r["product_code"]
        mall_price = None if is_extra else r["price_mall"]
        sale_price = r["sale_price"]
        diff = (mall_price - sale_price) if (mall_price is not None and sale_price is not None) else None
        return {
            "product_code": pc, "sku": r["sku"], "name": r["product_name"],
            "part_type": r["part_type"], "cat": part_label(r["part_type"]),
            "status": r["status"], "data_origin": r["data_origin"],
            "kind": kind, "kind_label": KIND_LABEL[kind],
            "sale_price": sale_price, "mall_price": mall_price,
            "diff": diff, "diff_display": _signed_won(diff),
            "handoff_no": None if is_extra else r["handoff_no"],
            "observed_at": None if is_extra else iso(r["observed_at"]),
            "last_change_at": iso(last_change.get(pc)),
            "reason": _reason_text(kind, sale_price=sale_price, mall_price=mall_price,
                                    handoff_no=None if is_extra else r["handoff_no"]),
        }

    cards = []
    cards += [_card(r, "alert") for r in alert]
    cards += [_card(r, "unknown") for r in unknown]
    cards += [_card(r, "locked") for r in locked_in_sample]
    cards += [_card(r, "locked", is_extra=True) for r in locked_extra]
    # 차액 큰 순 — 차액이 없는 카드(확인 못함 · 관측 없는 잠금)는 뒤로 보낸다
    cards.sort(key=lambda c: (c["diff"] is None, -(abs(c["diff"]) if c["diff"] is not None else 0)))

    sample_n = len(obs)
    mismatch_m = len(alert)
    mismatch_rate = round(mismatch_m / sample_n * 100, 1) if sample_n else None
    locked_cnt = len(locked_all)
    unknown_cnt = len(unknown)
    last_obs_at = max((r["observed_at"] for r in obs), default=None)

    return {
        "total_products": total_products,
        "trust": {
            "sample_n": sample_n, "mismatch_m": mismatch_m, "mismatch_rate": mismatch_rate,
            "headline": (f"확인해 본 {sample_n}라인 중 {mismatch_m}건이 몰과 달랐습니다."
                         if sample_n else "인계 시점에 확인된 라인이 아직 없습니다."),
            "sample_note": (f"표본이 인계된 상품 {sample_n}라인뿐입니다 — "
                            f"전체 {total_products:,}건의 상태가 아닙니다."),
        },
        "kpi": {
            "alert": {"value": mismatch_m, "note": f"확인한 {sample_n}라인 중"},
            "locked": {"value": locked_cnt, "note": f"전체 {total_products:,}건 중"},
            "unknown": {"value": unknown_cnt, "note": f"확인한 {sample_n}라인 중"},
            "recent": {
                "observed": sample_n,
                "no_history": total_products - sample_n,
                "stale_30d": stale_n, "mid_8_30d": mid_n, "fresh_under_8d": fresh_n,
                "last_at": iso(last_obs_at),
                "note": f"관측 이력 있음 {sample_n}건 · 전체 {total_products:,}건 중",
            },
        },
        "queue": cards,
        "mall_source_note": ("몰값은 저장된 값이 아니라 실서비스 페이지를 매번 읽어오는 값입니다."
                              " 건당 최대 6초·동시 4건 제한(\"남의 서버다\") 때문에 전량 조회는"
                              " 수 시간 단위입니다 — 그래서 이 화면은 인계 시점에 이미 확인된"
                              " 라인과 사람이 지목한 상품만 비교합니다."),
        "live_check_available": LIVE_CHECK_AVAILABLE, "live_check_reason": LIVE_CHECK_REASON,
        "purchase_axis_available": PURCHASE_AXIS_AVAILABLE, "purchase_axis_reason": PURCHASE_AXIS_REASON,
    }


@router.get("/api/admin/sale-price/{product_code}")
def detail(product_code: int):
    with engine.connect() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, status, data_origin,"
            " sale_price, locked_fields"
            " FROM products WHERE product_code=:pc"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        obs = _single_obs(conn, product_code)
        hist = conn.execute(text(
            "SELECT history_id, old_price, new_price, reason, ref_id, changed_at"
            " FROM product_price_history WHERE product_code=:pc AND field='sale'"
            " ORDER BY changed_at DESC, history_id DESC"), {"pc": product_code}).mappings().all()
        locked_cnt = conn.execute(text(
            "SELECT count(*) FROM products WHERE locked_fields @> '[\"sale_price\"]'::jsonb"
        )).scalar_one()
        total_products = conn.execute(text("SELECT count(*) FROM products")).scalar_one()

    locked = "sale_price" in (p["locked_fields"] or [])
    mall_price = obs["price_mall"] if obs else None
    kind = _classify(locked, obs is not None, mall_price, p["sale_price"])
    diff = (mall_price - p["sale_price"]) if (mall_price is not None and p["sale_price"] is not None) else None

    REASON_KO = {"csv": "일괄 등록", "sourcing": "매입 확정", "margin_policy": "가격 검토 승인",
                 "margin_policy_undo": "가격 검토 승인 되돌림", "manual": "운영자 직접 수정",
                 "manual_match": "몰 값 맞춤", "price_import": "단가표 반영",
                 "price_import_undo": "단가표 반영 되돌림"}

    return {
        "product_code": p["product_code"], "sku": p["sku"], "name": p["product_name"],
        "part_type": p["part_type"], "cat": part_label(p["part_type"]),
        "status": p["status"],
        "data_origin": p["data_origin"], "data_origin_label": ("실데이터" if p["data_origin"] == "real" else "시연용"),
        "locked": locked,
        "sale_price": p["sale_price"],
        "our_price_note": "판매가",
        "mall": {
            "known": mall_price is not None,
            "price": mall_price,
            "status": (obs["mall_status"] if obs else None),
            "handoff_no": (obs["handoff_no"] if obs else None),
            "observed_at": iso(obs["observed_at"]) if obs else None,
        },
        "kind": kind, "kind_label": KIND_LABEL.get(kind, "정상"),
        "diff": diff, "diff_display": _signed_won(diff),
        "reason": _reason_text(kind, sale_price=p["sale_price"], mall_price=mall_price,
                                handoff_no=(obs["handoff_no"] if obs else None)) if kind != "normal" else "",
        "locked_cnt": locked_cnt, "total_products": total_products,
        "locked_note": f"지금 판매가가 잠긴 상품은 전체 {total_products:,}건 중 {locked_cnt:,}건뿐입니다.",
        "history": [{
            "id": h["history_id"], "at": iso(h["changed_at"]),
            "old": h["old_price"], "new": h["new_price"],
            "delta": (h["new_price"] - h["old_price"])
                     if (h["old_price"] is not None and h["new_price"] is not None) else None,
            "reason": h["reason"], "reason_label": REASON_KO.get(h["reason"], h["reason"]),
            "ref_id": h["ref_id"],
        } for h in hist],
        "live_check_available": LIVE_CHECK_AVAILABLE, "live_check_reason": LIVE_CHECK_REASON,
    }


# ── 쓰기: 맞추기 · 잠그기 ────────────────────────────────────────────────
# 권한은 api/auth.py의 전역 규칙으로 이미 operator 이상만 통과한다(모듈 docstring 참조).
# 두 액션 모두 FOR UPDATE로 행을 잠그고, 값이 바뀌면 반드시 product_price_history에 남긴다
# (PATCH /api/admin/products가 이걸 안 남기는 기존 격차를 여기서 반복하지 않는다).

class MatchBody(BaseModel):
    mall_price: int | None = None   # 화면이 본 값(있으면 동시성 가드로 대조)


@router.post("/api/admin/sale-price/{product_code}/match")
def match_to_mall(product_code: int, body: MatchBody):
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, sale_price, locked_fields FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        obs = _single_obs(conn, product_code)
        if obs is None or obs["price_mall"] is None:
            raise HTTPException(400, "몰 값을 확인한 적이 없어 맞출 수 없습니다")
        mall_price = obs["price_mall"]
        if body.mall_price is not None and body.mall_price != mall_price:
            raise HTTPException(409, "몰 값이 바뀌었습니다 — 새로고침 후 다시 시도하세요")

        locked = list(p["locked_fields"] or [])
        was_locked = "sale_price" in locked
        # ⚠ 2026-08-15 확인자 결함 보고 반영 — "값이 같으면 얼리리턴"과 "잠긴 상품은
        # 얼리리턴 안 함"을 예전엔 한 조건(`== and not was_locked`)에 같이 걸었다.
        # `not was_locked`는 지운다고 될 게 아니다: 잠긴 상품이 우연히 몰 값과 같아도
        # 이 함수를 부른 이상 잠금은 항상 풀려야 한다(그러라고 있는 조건 — 지우면
        # "잠긴 채 우연히 값이 같은" 상품은 영영 잠금이 안 풀린다). 대신 "가격이 실제로
        # 바뀌었는가"(price_changed)와 "잠금을 풀 것인가"(was_locked)를 분리해, 가격
        # 이력 INSERT만 price_changed일 때로 좁힌다 — 값이 그대로인데 old==new(델타 0)
        # 이력 행이 생기면 "가격이 바뀐 척"하는 행이 되어, 그 행을 세는 다른 집계
        # (기간별 가격 변동 건수)가 실제로는 없던 변경을 1건으로 센다. 이 저장소 선례
        # (admin_price_import.py:166 · admin_products.py:572 · catalog_ingest — 값이
        # 같으면 원장에 안 남긴다)와 맞춘다. 라이브 재현은 못 했다(잠긴 상품이 46158
        # 하나뿐이고 그 상품엔 몰 관측 이력 자체가 없어 오늘은 이 분기에 못 들어간다 —
        # 읽기 전용으로 확인, 46158 자체는 건드리지 않았다). 코드 경로로만 검증했다.
        price_changed = p["sale_price"] != mall_price
        if not price_changed and not was_locked:
            return {"ok": True, "changed": False, "sale_price": mall_price,
                    "note": "이미 몰 값과 일치합니다."}

        if was_locked:
            locked = [f for f in locked if f != "sale_price"]
        log_id = _log(conn, "sale_price_match", p["sku"] or str(product_code),
                      {"product_code": product_code, "sku": p["sku"],
                       "before": {"sale_price": p["sale_price"], "locked": was_locked},
                       "after": {"sale_price": mall_price, "locked": False},
                       "handoff_no": obs["handoff_no"]}, kind="product")
        conn.execute(text(
            "UPDATE products SET sale_price=:v, locked_fields=CAST(:lf AS JSONB), updated_at=now()"
            " WHERE product_code=:pc"),
            {"v": mall_price, "lf": _json.dumps(locked, ensure_ascii=False), "pc": product_code})
        if price_changed:
            conn.execute(text(
                "INSERT INTO product_price_history"
                " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                " VALUES (:pc, 'sale', :o, :n, 'manual_match', :ref, :op)"),
                {"pc": product_code, "o": p["sale_price"], "n": mall_price,
                 "ref": log_id, "op": current_operator_id()})
    note = (f"판매가를 몰 값 {mall_price:,}원으로 맞췄습니다." if price_changed
            else f"판매가는 이미 몰 값과 같습니다({mall_price:,}원).")
    if was_locked:
        note += " 잠금을 해제했습니다."
    return {"ok": True, "changed": True, "sale_price": mall_price, "unlocked": was_locked,
            "log_id": log_id, "note": note}


class LockBody(BaseModel):
    pass


@router.post("/api/admin/sale-price/{product_code}/lock")
def lock_current(product_code: int, body: LockBody = LockBody()):
    with engine.begin() as conn:
        p = conn.execute(text(
            "SELECT product_code, sku, sale_price, locked_fields FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if p is None:
            raise HTTPException(404, "상품이 없습니다")
        locked = list(p["locked_fields"] or [])
        if "sale_price" in locked:
            return {"ok": True, "changed": False, "locked": True, "note": "이미 잠긴 값입니다."}
        locked.append("sale_price")
        log_id = _log(conn, "sale_price_lock", p["sku"] or str(product_code),
                      {"product_code": product_code, "sku": p["sku"],
                       "sale_price": p["sale_price"]}, kind="product")
        conn.execute(text(
            "UPDATE products SET locked_fields=CAST(:lf AS JSONB), updated_at=now()"
            " WHERE product_code=:pc"),
            {"lf": _json.dumps(locked, ensure_ascii=False), "pc": product_code})
    price_txt = f"{p['sale_price']:,}원" if p["sale_price"] is not None else "값 없음"
    return {"ok": True, "changed": True, "locked": True, "log_id": log_id,
            "note": f"판매가를 {price_txt}에서 잠갔습니다. 자동 경로가 이 값을 바꾸지 않습니다."}
