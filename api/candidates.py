"""결정론 엔진 v0 — S1 후보 풀 카운터 (POST /api/candidates/count).

A-02: 같은 입력 + 같은 재고 = 같은 출력. LLM 없음, 뷰 1쿼리 + Python 순차 필터.
base = v_recommendation_candidates ∧ stock_qty > 0 (UX-08 "조건 통과 부품 수").

v0 하드필터(정직한 최소 룰 — 그 외 제약은 applied=false로 정직 표기):
- 예산: 부품별 상한 배분율(아래 BUDGET_ALLOC — 휴리스틱, S2 엔진 배분 로직으로 대체 예정).
  '이상'·숫자 없음('AI 추천 예산' 등)은 미적용.
- 태그: 값에 '저소음' → tag_silent (스코프: GPU·POWER·CASE·COOLER — 스코프 밖 부품은
  무조건 통과. tag false의 이중 의미(미태깅) 때문에 전 부품 적용 시 전멸 위험),
  '화이트' → tag_white (스코프: CASE).

effects = 제약 배열 순서대로 누적 적용한 델타. 순서를 바꾸면 최종 count는 같고
델타 배분만 달라진다 — 이것이 이 계약의 정의된 결정론이다.
"""
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from . import usage_floors as UF
from .db import engine

router = APIRouter(prefix="/api")

# 용도 하한이 쓰는 사양 — 풀 SELECT에 반드시 실려야 한다.
# 빠뜨리면 `.get()`이 None을 주고 NULL 불통과로 **조용히** 전멸한다(규칙 필드 전례).
FLOOR_COLS = ("capacity_gb", "required_power_watt")


def _floor_slot(part_type: str) -> str:
    """part_type → 하한 슬롯. 쿨러만 두 종류가 한 슬롯이다(엔진과 같은 정의)."""
    return "COOLER" if part_type.startswith("COOLER_") else part_type

# 예산 상한 배분율 — "어느 부품도 자기 배분율 상한을 초과할 수 없다"
BUDGET_ALLOC = {
    "CPU": 0.25, "GPU": 0.40, "MB": 0.15, "RAM": 0.10, "SSD": 0.12, "HDD": 0.08,
    "POWER": 0.10, "CASE": 0.08, "COOLER_CPU_AIR": 0.08, "COOLER_CPU_AIO": 0.08,
}
SILENT_SCOPE = {"GPU", "POWER", "CASE", "COOLER_CPU_AIR", "COOLER_CPU_AIO"}
WHITE_SCOPE = {"CASE"}


class Constraint(BaseModel):
    l: str
    v: str


class CountBody(BaseModel):
    constraints: list[Constraint] = []


def _budget_cap(value: str):
    """예산 라벨 → 상한(원) 또는 None(미적용). '200만원 이상'은 상한이 아니다."""
    if "이상" in value:
        return None
    m = re.search(r"(\d{2,3})\s*만", value)
    if not m:
        return None
    return int(m.group(1)) * 10000


def _apply_one(parts: list[dict], label: str, value: str):
    """제약 1건 적용 — (남은 parts, applied, reason). 한 제약에 복수 태그면 순차 결합."""
    if label == "예산":
        cap = _budget_cap(value)
        if cap is None:
            return parts, False, "상한 없는 예산 표현 — 후보 수에는 영향 없음"
        kept = [p for p in parts
                if p["sale_price"] <= int(cap * BUDGET_ALLOC.get(p["part_type"], 1.0))]
        return kept, True, "부품별 예산 상한(CPU 25%·GPU 40% 등 배분율) 초과 부품 제외"
    if label in ("용도", "상황"):
        # 슬라이스 58: 용도가 실제로 부품을 거른다. 이전에는 "구성 단계(스코어)에서 반영"이라고
        # 답하고 아무것도 하지 않아, 고사양 게임에 GT710 2GB가 나왔다.
        floors = UF.slot_floors(value)
        if not floors:
            return parts, False, "하한이 정의되지 않은 용도 — 후보 수에는 영향 없음"
        kept = [p for p in parts
                if not (fs := floors.get(_floor_slot(p["part_type"]))) or UF.passes(p, fs)]
        unit = {"required_power_watt": "W", "capacity_gb": "GB"}
        why = " · ".join(f"{SLOT_KO.get(s, s)} {f[2]:,}{unit.get(f[0], '')} 이상"
                         for s, fl in floors.items() for f in fl[:1])
        return kept, True, f"용도 하한 미달 부품 제외 — {why}"
    applied, reasons = False, []
    if "저소음" in value:
        parts = [p for p in parts
                 if p["part_type"] not in SILENT_SCOPE or p["tag_silent"]]
        applied = True
        reasons.append("소음원 부품(GPU·파워·케이스·쿨러) 중 저소음 태그 없는 부품 제외")
    if "화이트" in value:
        parts = [p for p in parts
                 if p["part_type"] not in WHITE_SCOPE or p["tag_white"]]
        applied = True
        reasons.append("케이스 중 화이트 태그 없는 부품 제외")
    if applied:
        return parts, True, " · ".join(reasons)
    return parts, False, "구성 단계(스코어)에서 반영 — 후보 수에는 영향 없음"


# 견적 슬롯 = 엔진과 같은 정의(recommend.SLOTS / SLOT_TYPES).
# **part_type 단위로 세면 오판한다**: 쿨러는 공랭·수냉이 한 슬롯이라 AIO가 0이어도
# AIR가 남아 있으면 견적이 성립한다(슬라이스 48에서 실제로 헷갈렸다).
QUOTE_SLOTS = {
    "CPU": ("CPU",), "MB": ("MB",), "RAM": ("RAM",), "GPU": ("GPU",),
    "CASE": ("CASE",), "COOLER": ("COOLER_CPU_AIR", "COOLER_CPU_AIO"),
    "POWER": ("POWER",), "SSD": ("SSD",),
}
SLOT_KO = {"CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
           "CASE": "케이스", "COOLER": "CPU쿨러", "POWER": "파워", "SSD": "SSD"}


def _slot_view(parts: list[dict]) -> tuple:
    """(슬롯별 남은 수, 빈 슬롯 목록) — 빈 슬롯이 하나라도 있으면 견적을 만들 수 없다.

    후보 수가 수백이어도 한 슬롯이 0이면 조립이 불가능하다. 그 사실을 화면이 알아야
    "N개로 3구성을 만들 수 있어요"라고 잘못 말하지 않는다(슬라이스 48).
    """
    counts, empty = {}, []
    for slot, types in QUOTE_SLOTS.items():
        n = sum(1 for p in parts if p["part_type"] in types)
        counts[slot] = n
        if n == 0:
            empty.append(slot)
    return counts, empty


@router.post("/candidates/count")
def count_candidates(body: CountBody):
    with engine.connect() as conn:
        parts = [dict(r) for r in conn.execute(text(
            "SELECT part_type, sale_price, tag_white, tag_silent, "
            + ", ".join(FLOOR_COLS)
            + " FROM v_recommendation_candidates WHERE stock_qty > 0")).mappings().all()]
    total = len(parts)
    effects = []
    for c in body.constraints:
        before = len(parts)
        parts, applied, reason = _apply_one(parts, c.l, c.v)
        effects.append({
            "label": c.l, "value": c.v, "applied": applied,
            "delta": before - len(parts), "count_after": len(parts), "reason": reason,
        })
    slot_counts, empty = _slot_view(parts)
    return {
        "total": total, "count": len(parts), "effects": effects,
        "slots": slot_counts,
        "buildable": not empty,
        "empty_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in empty],
        # 화면이 그대로 쓸 수 있는 한 문장 — 서버와 화면이 다른 말을 하지 않게
        "verdict": ("지금 조건으로 가성비·추천·고성능 3구성을 만들 수 있어요."
                    if not empty else
                    "조건이 너무 좁아 "
                    + " · ".join(SLOT_KO.get(s, s) for s in empty)
                    + " 후보가 없어요 — 견적을 만들 수 없습니다. 조건을 하나만 완화해 주세요."),
    }
