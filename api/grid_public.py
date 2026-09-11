# -*- coding: utf-8 -*-
"""고객용 격자 추천 API — `POST /api/grid/recommend` (A-128 ② 단계, 2026-09-11).

■ 무엇을 하나
  talk.py 가 낸 constraints(예산·용도·플랫폼 …)를 받아 사전 생성 견적 격자
  (grid_cells × grid_quotes.is_current, 0072)에서 **인접 티어 최대 3칸**의 견적을
  카드로 돌려준다. 실시간 recommend 엔진을 돌리지 않는다 — 격자가 추천 원천이다
  (A-126 「LLM 은 분류만, 조합은 배치가」·A-128 「격자는 화면 뒤의 추천 원천」).

■ 읽기 전용이다 — SELECT 만. 세션도 원장도 쓰지 않는다(`recommend.showcase()` 와 같은
  등급). 그래서 `/api/admin/*` 이 아니라 `/api/grid/*` 에 둔다.

■ 인증 게이트 밖이다 (2026-09-11 실측, 담당 밖 파일은 읽기만)
  · `api/auth.py` `_is_gated()` = `path.startswith("/api/admin/") or _is_admin2_path(path)`
    → `/api/grid/` 는 게이트 대상이 아니다.
  · `api/customer_auth.py` `member_middleware` 는 `/api/my/` 만 401 을 내고 그 밖은
    세션이 있으면 주체만 붙인다 → 게스트도 통과한다.
  확인법: `grep -n "def _is_gated" -A 30 api/auth.py` · `grep -n "GUARDED_PREFIX" api/customer_auth.py`

■ 사장님 확정 (2026-09-11)
  · 티어 범위 = 중심 티어 + 위 2개. 예산 초과 카드는 `over_budget` 로 표시(빼지 않는다).
  · 기본 플랫폼 인텔 — 고객이 AMD 를 말했을 때만 AMD.
  · 예산 없으면 팝콘 5 중심.
  · 격자에 없으면 있는 만큼만 — 억지로 3장 채우지 않는다.

■ 지어내지 않는 것
  · `reasons` 는 payload.reasons 그대로(재작성 금지).
  · 카드 이름은 payload.label 을 쓰지 않는다 — 조사자 실측(2026-09-11)으로 70건 전부
    '추천형 견적' 동일이라 정보가 없다. 티어 + 용도로 합성한다("팝콘 5 · 온라인게임").
  · 이미지·영상 필드는 넣지 않는다 — A-128 ④ 단계 소관. 자리가 생기면 그때 붙인다.
  · `in_stock` 은 `products.stock_qty` 를 그 자리에서 다시 읽은 값이다
    (`admin_grid.grid_cell()` 과 같은 이유 — 저장 시점 재고를 믿으면 이미 틀린 사실을 말한다).
"""
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine
from .taxonomy import SLOT_LABELS
from .timeutil import iso as _iso

router = APIRouter(prefix="/api/grid", tags=["grid-public"])

# ── 티어 — 0072 TIERS 와 같은 값 ──────────────────────────────────────────
# 정본은 grid_cells 의 budget_min/budget_max 다. 이 API 는 요청마다 grid_cells 에서
# 티어 표를 다시 읽는다(`_load_tiers`) — 여기엔 리터럴을 두지 않는다. 0072 가
# 경계를 바꾸면 이 파일은 고칠 것이 없다.

DEFAULT_TIER = "팝콘 5"          # 예산 없을 때 중심(사장님 확정 2026-09-11)
TIERS_UP = 2                     # 중심 + 위 2개
DEFAULT_PLATFORM = "인텔"        # 0072 PLATFORMS[0] · 사장님 확정
PLATFORMS = ("인텔", "AMD")      # 0072 PLATFORMS — grid_cells.platform 이 정본

# ── 용도 11 → 8 매핑 ────────────────────────────────────────────────────
# 키 = `usage_floors.usage_label`(파서 talk.py 가 내는 용도 값, 11종 — `GET /api/usages`
# 로 확인). 값 = 0072 USAGES 리터럴(grid_cells.usage). 근거 = A-128 ② 단계 지시
# (2026-09-11): 격자 8칸은 하한 11종보다 굵어서 여러 용도가 한 칸으로 접힌다.
#   · 사무·인강 / 인터넷·시청 / 영화·시청 / 주식·트레이딩 → 사무·인터넷 : 전부 GPU 를
#     안 쓰는 저부하 — 격자 문서 §3 U1 정의("사무·인터넷")에 들어간다.
#   · 방송 송출 / 영상편집 → 영상편집·방송 : U4 이름 자체가 둘을 합쳐 두었다.
#   · 게임 → 온라인게임(라이트~중급) · 고사양 게임 → 고사양게임(4K·하이엔드).
#   · 저소음·컴팩트(U8)로 가는 파서 용도는 없다 — U8 은 시드부터 전 칸 intended_empty.
USAGE_TO_GRID = {
    "고사양 게임": "고사양게임 (4K·하이엔드)",
    "AI 작업": "AI 작업",
    "게임": "온라인게임 (라이트~중급)",
    "디자인": "디자인·3D설계",
    "개발": "개발·프로그래밍",
    "방송 송출": "영상편집·방송",
    "영상편집": "영상편집·방송",
    "사무·인강": "사무·인터넷",
    "인터넷·시청": "사무·인터넷",
    "영화·시청": "사무·인터넷",
    "주식·트레이딩": "사무·인터넷",
}

# 카드 이름에 붙는 짧은 용도명 — 격자 리터럴의 괄호 부연을 뗀 것("온라인게임 (라이트~중급)"
# → "온라인게임"). 표시용이지 어휘가 아니다 — usage_grid 필드는 원문 그대로 나간다.
def _usage_short(usage_grid: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", usage_grid)

# ── 부품 순서·라벨 — 화면(mockups/mvp2/app.js makeQuotes) 순서 ──────────────
# app.js: cats=['CPU','메인보드','메모리','그래픽카드','저장장치','케이스','쿨러','파워'].
# payload.items 는 taxonomy.SLOTS 순(CPU·MB·RAM·GPU·CASE·COOLER·POWER·SSD)이라 여기서
# 화면 순으로 재배열한다.
PART_ORDER = ("CPU", "MB", "RAM", "GPU", "SSD", "CASE", "COOLER", "POWER")

# 화면 표시용 라벨 — taxonomy.SLOT_LABELS 가 정본이다. 화면(app.js)이 '저장장치'·'쿨러'
# 라 부르는 두 자리만 여기서 덮는다(정본은 'SSD'·'CPU쿨러'). 새 어휘를 만드는 것이
# 아니라 화면 문구에 맞춘 표시명이다 — 다른 자리는 전부 SLOT_LABELS 그대로.
DISPLAY_OVERRIDE = {"SSD": "저장장치", "COOLER": "쿨러"}


def _cat_label(slot: str) -> str:
    return DISPLAY_OVERRIDE.get(slot) or SLOT_LABELS.get(slot, slot)


# ── 입력 ────────────────────────────────────────────────────────────────
class Constraint(BaseModel):
    l: str | None = None
    v: str | None = None


class RecommendBody(BaseModel):
    constraints: list[Constraint] = []
    history_note: str | None = None     # 받기만 한다 — 이 단계에선 판정에 쓰지 않는다


# ── 예산 문자열 → 원 ───────────────────────────────────────────────────────
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_budget(s: str | None) -> tuple[int | None, str | None]:
    """'1,500만원' · '150만원 이하' · '130만' · '1300000원' → (원, bound).

    bound ∈ {'이상','이하',None}. 콤마를 떼고 첫 숫자를 읽는다. '만' 이 있으면 ×10000,
    없고 값이 10000 미만이면 만원 단위로 간주해 ×10000, 그 밖은 원 그대로.
    못 읽으면 (None, None) — 지어내지 않는다.
    """
    if not s:
        return None, None
    raw = s.replace(",", "").strip()
    m = _NUM.search(raw)
    if not m:
        return None, None
    n = float(m.group(1))
    tail = raw[m.end():]
    if "만" in tail or ("만" not in raw and n < 10000):
        won = int(round(n * 10000))
    else:
        won = int(round(n))
    bound = "이상" if "이상" in raw else ("이하" if "이하" in raw else None)
    return won, bound


def _load_tiers(conn) -> list[dict]:
    """grid_cells 에서 티어 표(오름차순) — 0072 TIERS 와 같은 값이지만 DB 가 정본."""
    return [dict(r) for r in conn.execute(text(
        "SELECT tier AS name, budget_min, budget_max FROM grid_cells"
        " GROUP BY tier, budget_min, budget_max ORDER BY budget_min")).mappings().all()]


def tier_index_for(tiers: list[dict], won: int | None, bound: str | None) -> int:
    """반열림 [budget_min, budget_max) 로 중심 티어 인덱스를 고른다.

    · 예산 없음 → DEFAULT_TIER.
    · '이하' 는 상한이다 — 경계값(예: 150만)이 그대로 다음 티어 [150,220) 에 떨어지면
      「150만 이하」에 220만짜리 칸이 중심이 된다. 그래서 (값-1) 이 들어가는 티어로.
    · '이상'·bound 없음 → 그 값이 들어가는 티어(지시 그대로).
    """
    if won is None:
        for i, t in enumerate(tiers):
            if t["name"] == DEFAULT_TIER:
                return i
        return 0
    probe = max(won - 1, 0) if bound == "이하" else won
    for i, t in enumerate(tiers):
        lo, hi = t["budget_min"], t["budget_max"]
        if probe >= lo and (hi is None or probe < hi):
            return i
    return len(tiers) - 1        # 경계 밖(음수 등)은 마지막 티어로 — 실제론 위 루프가 항상 맞는다


# ── 제약 읽기 ───────────────────────────────────────────────────────────
def _pick(constraints: list[Constraint], label: str) -> str | None:
    for c in constraints:
        if (c.l or "").strip() == label and (c.v or "").strip():
            return c.v.strip()
    return None


def _platform_of(constraints: list[Constraint]) -> str:
    """'플랫폼' 라벨이 정본. 없으면 '선호' 값에 AMD/라이젠·인텔이 명시돼 있을 때만 그것,
    그 밖은 인텔(사장님 확정)."""
    v = _pick(constraints, "플랫폼")
    cands = [v] if v else [c.v for c in constraints if (c.l or "").strip() == "선호" and c.v]
    for s in cands:
        u = (s or "").upper()
        if "AMD" in u or "라이젠" in u or "RYZEN" in u:
            return "AMD"
        if "인텔" in u or "INTEL" in u:
            return "인텔"
    return DEFAULT_PLATFORM


def _usage_grid_of(constraints: list[Constraint]) -> tuple[str | None, str | None]:
    """(격자 용도, 파서 용도). 파서 값이 11종 라벨과 정확히 같지 않아도 라벨이 값에
    포함되면 받는다(긴 라벨 우선 — '고사양 게임' 이 '게임' 보다 먼저)."""
    v = _pick(constraints, "용도")
    if not v:
        return None, None
    if v in USAGE_TO_GRID:
        return USAGE_TO_GRID[v], v
    for lab in sorted(USAGE_TO_GRID, key=len, reverse=True):
        if lab in v:
            return USAGE_TO_GRID[lab], v
    return None, v


# ── 본체 ────────────────────────────────────────────────────────────────
@router.post("/recommend")
def recommend(body: RecommendBody):
    """constraints → 격자 카드 최대 3장. 400 을 내지 않는다 — 부족한 것은 `needs` 로
    말하고 카드 0장(화면/LLM 이 되묻는다).

    응답 {ok, cards[], center_tier, tiers_considered[], usage_grid, platform,
          budget_won, needs[], note, empty_cells[]}
      empty_cells  고려한 티어 중 카드가 안 나온 칸의 사유 — intended_empty 면 그 사실,
                   현재본 견적이 없으면 '현재본 없음'. 「없다」와 「의도적으로 비웠다」를
                   구분한다(MAKER-CHECKLIST §5).
    """
    cons = body.constraints or []
    budget_won, bound = parse_budget(_pick(cons, "예산"))
    usage_grid, usage_raw = _usage_grid_of(cons)
    platform = _platform_of(cons)

    needs: list[str] = []
    notes: list[str] = []
    if usage_grid is None:
        needs.append("용도")
        if usage_raw:
            notes.append(f"용도 '{usage_raw}' 는 격자 용도로 대응되지 않음")
    if budget_won is None:
        notes.append(f"예산 없음 — {DEFAULT_TIER} 중심")

    with engine.connect() as conn:
        tiers = _load_tiers(conn)
        ci = tier_index_for(tiers, budget_won, bound)
        considered = tiers[ci: ci + 1 + TIERS_UP]
        center = tiers[ci]["name"]

        cards: list[dict] = []
        empty_cells: list[dict] = []
        if usage_grid is not None:
            rows = conn.execute(text(
                "SELECT c.cell_id, c.tier, c.usage, c.platform, c.budget_min, c.budget_max,"
                " c.intended_empty, q.quote_id, q.generated_at, q.total, q.status, q.payload"
                " FROM grid_cells c"
                " LEFT JOIN grid_quotes q ON q.cell_id = c.cell_id AND q.is_current"
                " WHERE c.usage = :u AND c.platform = :p AND c.tier = ANY(:t)"
                " ORDER BY c.budget_min"),
                {"u": usage_grid, "p": platform,
                 "t": [t["name"] for t in considered]}).mappings().all()

            # in_stock 실조회 — 카드 전부의 product_code 를 한 번에 읽는다
            codes: set = set()
            for r in rows:
                for it in ((r["payload"] or {}).get("items") or []):
                    if it.get("product_code") is not None:
                        codes.add(it["product_code"])
            stock_by_code: dict = {}
            if codes:
                stock_by_code = {s["product_code"]: s["stock_qty"] for s in conn.execute(text(
                    "SELECT product_code, stock_qty FROM products"
                    " WHERE product_code = ANY(:c)"), {"c": list(codes)}).mappings().all()}

            for r in rows:
                tier_range = {"min": r["budget_min"], "max": r["budget_max"]}
                if r["intended_empty"]:
                    empty_cells.append({
                        "cell_id": r["cell_id"], "tier": r["tier"], "tier_range": tier_range,
                        "reason": "의도적으로 비운 칸 — 이 티어×용도 조합은 격자가 만들지 않는다"})
                    continue
                if r["quote_id"] is None:
                    empty_cells.append({
                        "cell_id": r["cell_id"], "tier": r["tier"], "tier_range": tier_range,
                        "reason": "현재본 견적 없음"})
                    continue
                payload = r["payload"] or {}
                by_slot = {it.get("part_type"): it for it in (payload.get("items") or [])}
                parts = []
                for slot in PART_ORDER:
                    it = by_slot.get(slot)
                    if it is None:
                        continue      # 그 자리가 없으면(예: 기본 쿨러 생략) 빈 항목을 지어내지 않는다
                    parts.append({
                        "cat": _cat_label(slot),
                        "name": it.get("name"),
                        "price": it.get("price"),
                        "product_code": it.get("product_code"),
                        "in_stock": stock_by_code.get(it.get("product_code"), 0) > 0,
                    })
                total = r["total"] if r["total"] is not None else payload.get("total")
                cards.append({
                    "quote_id": r["quote_id"], "cell_id": r["cell_id"],
                    "tier": r["tier"], "tier_range": tier_range,
                    "usage": r["usage"], "platform": r["platform"],
                    "name": f"{r['tier']} · {_usage_short(r['usage'])}",
                    "total": total,
                    "over_budget": bool(budget_won is not None and total is not None
                                        and total > budget_won),
                    "status": r["status"],
                    "parts": parts,
                    "reasons": list(payload.get("reasons") or []),
                    "generated_at": _iso(r["generated_at"]),
                })

    if usage_grid is not None and not cards:
        notes.append("고려한 티어에 카드 없음")
    return {
        "ok": True,
        "cards": cards,
        "center_tier": center,
        "tiers_considered": [t["name"] for t in considered],
        "usage_grid": usage_grid,
        "platform": platform,
        "budget_won": budget_won,
        "budget_bound": bound,
        "needs": needs,
        "note": " · ".join(notes),
        "empty_cells": empty_cells,
    }
