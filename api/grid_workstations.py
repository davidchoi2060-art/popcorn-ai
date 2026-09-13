# -*- coding: utf-8 -*-
"""고객용 AI 워크스테이션 진열 API — `GET /api/grid/workstations` (CUS-QUO-010 부속, 2026-09-13).

■ 정본 = `docs/design/req/req-ai-workstation-shelf.md` ④-2. 이 파일은 그 계약을 그대로 옮긴
  것이다 — 계약이 바뀌면 정의서를 먼저 고친다.

■ 무엇을 하나
  격자 카드(`grid_public.recommend`) 아래에 붙는 **몰 완제품 진열 한 줄**의 데이터.
  원천은 사장님이 구성해 파는 `products`(`part_type='PC_COMPLETE'`)이고, 그중
  `builtpc_kind='ai_workstation'`(0088) 로 표시된 상품만 고른다. 「AI 워크스테이션인가」의
  판정은 **컬럼**이 한다 — 상품명을 여기서 다시 파싱하지 않는다.

■ 읽기 전용 — SELECT 만. 세션도 원장도 쓰지 않는다(`grid_public.py` 와 같은 등급이라
  같은 `/api/grid/*` 접두 · 인증 게이트 밖 — 그 파일 머리말의 실측 그대로).

■ 노출 판정(사장님 확정 2026-09-13)
      shown = (usage == "AI 작업") AND (budget_won is None OR budget_won >= threshold_won)
  threshold_won 은 **`grid_cells` 의 `팝콘 9` `budget_min`** 을 요청마다 읽는다
  (`grid_public._load_tiers` 와 같은 이유 — 리터럴을 두지 않는다. 0082 가 경계를 바꾸면
  이 파일은 고칠 것이 없다). 회귀 `tests/regression.py` 가 이 파일에 550만 리터럴이
  없음을 감시한다.

■ 400/500 을 내지 않는다 — 격자 API 관례 「부족한 것은 말로 한다」.
  · usage 없음 → shown:false · reason:"usage_missing"
  · usage ≠ AI 작업 → shown:false · reason:"usage_not_ai"
  · 예산 < 하한 → shown:false · reason:"budget_below_threshold"
  · budget_won 이 정수가 아니거나 0 이하 → 「예산 없음」으로 보고 note 에 사유
  · `builtpc_kind` 컬럼 없음(0088 미적용) → shown 은 조건대로 · items:[] · note "0088 미적용"

■ 지어내지 않는 것
  · `spec` 은 `builtpc_spec` jsonb 그대로. 비어 있으면 null — 상품명에서 파싱하지 않는다.
  · `name` 은 `product_name` 에서 HTML 태그만 벗긴다(`display_name()`). 사양 문자열
    `[CPU/RAM/SSD/GPU]` 는 **떼지 않는다**(정의서 ⑦-B W-3 ㉮ — 몰과 같은 이름).
  · 이미지·영상·격자 티어명·부품 목록은 넣지 않는다(정의서 ④-2 「넣지 않는 것」).
  · `in_stock` 은 요청 시점 `stock_qty > 0`. 재고 0 도 빼지 않는다.
"""
from fastapi import APIRouter, Query
from sqlalchemy import text

from .db import engine
from .mall import DETAIL as MALL_DETAIL
from .product_name import display_name

router = APIRouter(prefix="/api/grid", tags=["grid-public"])

USAGE_AI = "AI 작업"           # talk.py 용도 라벨 · grid_public.USAGE_TO_GRID 의 키와 같은 값
THRESHOLD_TIER = "팝콘 9"       # 하한을 읽어 올 티어 — 값(budget_min)은 grid_cells 가 정본
OVER_BUDGET_N = 2              # 예산 초과분 중 「바로 위」 몇 개
NO_BUDGET_N = 5                # 예산 없을 때 가격 오름차순 몇 개
BUILTPC_KIND = "ai_workstation"

# 몰 상품 페이지 — `api/mall.py` DETAIL 형식(부품 상품에서 실측). ⚠ 완제품(PC_COMPLETE)이
# 같은 경로로 열리는지는 미실측(정의서 ⑦-B W-1) — 사장님 확인 대기. 응답에는 적지 않는다.
MALL_URL = MALL_DETAIL

_SQL_THRESHOLD = text(
    "SELECT MIN(budget_min) FROM grid_cells WHERE tier = :t")

_SQL_ITEMS = text(
    "SELECT product_code, product_name, sale_price, stock_qty, builtpc_spec"
    " FROM products"
    " WHERE part_type = 'PC_COMPLETE' AND status = '판매중' AND builtpc_kind = :k"
    " AND sale_price IS NOT NULL"
    " ORDER BY sale_price ASC, product_code ASC")


def _parse_budget(raw: str | None) -> tuple[int | None, str | None]:
    """쿼리 문자열 → (원, 무시 사유). 정수가 아니거나 0 이하면 (None, 사유) — 422 를 내지 않는다."""
    if raw is None or str(raw).strip() == "":
        return None, None
    s = str(raw).strip().replace(",", "")
    try:
        won = int(s)
    except ValueError:
        return None, f"budget_won '{raw}' 는 정수가 아님 — 예산 없음으로 봄"
    if won <= 0:
        return None, f"budget_won {won} 은 0 이하 — 예산 없음으로 봄"
    return won, None


def _load_threshold(conn) -> int | None:
    v = conn.execute(_SQL_THRESHOLD, {"t": THRESHOLD_TIER}).scalar()
    return int(v) if v is not None else None


def _load_items(conn) -> tuple[list[dict], str | None]:
    """AI 워크스테이션 판매중 전부(가격·코드 오름차순). 0088 미적용이면 ([], 사유)."""
    try:
        rows = conn.execute(_SQL_ITEMS, {"k": BUILTPC_KIND}).mappings().all()
    except Exception as e:                                   # noqa: BLE001
        msg = str(getattr(e, "orig", e))
        if "builtpc_kind" in msg or "builtpc_spec" in msg:
            return [], "0088 미적용 — builtpc_kind 없음"
        raise
    return [dict(r) for r in rows], None


def _item(r: dict, over_budget: bool) -> dict:
    spec = r.get("builtpc_spec")
    qty = int(r.get("stock_qty") or 0)
    code = int(r["product_code"])
    return {
        "product_code": code,
        "name": display_name(r.get("product_name")),
        "price": int(r["sale_price"]),
        "spec": spec if isinstance(spec, dict) and spec else None,
        "in_stock": qty > 0,
        "stock_qty": qty,
        "over_budget": bool(over_budget),
        "mall_url": MALL_URL % code,
    }


def _select(rows: list[dict], budget_won: int | None) -> tuple[list[dict], dict]:
    """정의서 ④-2 선정 규칙. rows 는 이미 sale_price ASC, product_code ASC."""
    if budget_won is None:
        picked = [_item(r, False) for r in rows[:NO_BUDGET_N]]
        return picked, {"within_budget": None, "over_budget": 0}
    within = [r for r in rows if r["sale_price"] <= budget_won]
    over = [r for r in rows if r["sale_price"] > budget_won][:OVER_BUDGET_N]
    picked = [_item(r, False) for r in within] + [_item(r, True) for r in over]
    return picked, {"within_budget": len(within), "over_budget": len(over)}


@router.get("/workstations")
def workstations(usage: str | None = Query(default=None),
                 budget_won: str | None = Query(default=None),
                 budget_bound: str | None = Query(default=None)):
    """AI 워크스테이션 진열. 응답 {ok, shown, reason, usage, budget_won, budget_bound,
    threshold_won, items[], counts{within_budget, over_budget}, note}."""
    usage_v = (usage or "").strip() or None
    won, budget_note = _parse_budget(budget_won)
    bound = (budget_bound or "").strip() or None
    notes: list[str] = []
    if budget_note:
        notes.append(budget_note)

    def _out(shown, reason, threshold, items, counts):
        return {
            "ok": True,
            "shown": bool(shown),
            "reason": reason,
            "usage": usage_v,
            "budget_won": won,
            "budget_bound": bound,
            "threshold_won": threshold,
            "items": items,
            "counts": counts,
            "note": " · ".join(notes),
        }

    empty_counts = {"within_budget": None if won is None else 0, "over_budget": 0}

    with engine.connect() as conn:
        threshold = _load_threshold(conn)
        if threshold is None:
            notes.append(f"grid_cells 에 '{THRESHOLD_TIER}' 없음 — 하한을 정할 수 없어 노출하지 않음")

        # 판정 — 용도 먼저, 예산 다음 (정의서 ⑦-A 순서)
        if usage_v is None:
            return _out(False, "usage_missing", threshold, [], empty_counts)
        if usage_v != USAGE_AI:
            return _out(False, "usage_not_ai", threshold, [], empty_counts)
        if threshold is None:
            return _out(False, "budget_below_threshold", threshold, [], empty_counts)
        if won is not None and won < threshold:
            return _out(False, "budget_below_threshold", threshold, [], empty_counts)

        rows, why = _load_items(conn)

    if why:
        notes.append(why)
        return _out(True, None, threshold, [], empty_counts)

    items, counts = _select(rows, won)
    if not rows:
        notes.append("현재 판매 중인 AI 워크스테이션 없음")
    elif won is None:
        notes.append(f"예산 기준 없음 — 가격 낮은 순 {len(items)}개")
    elif counts["within_budget"] == 0:
        notes.append(f"예산 안 완제품 없음 — 바로 위 {counts['over_budget']}개")
    return _out(True, None, threshold, items, counts)
