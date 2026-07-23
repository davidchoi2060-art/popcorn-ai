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

from .db import engine

router = APIRouter(prefix="/api")

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


@router.post("/candidates/count")
def count_candidates(body: CountBody):
    with engine.connect() as conn:
        parts = [dict(r) for r in conn.execute(text(
            "SELECT part_type, sale_price, tag_white, tag_silent"
            " FROM v_recommendation_candidates WHERE stock_qty > 0")).mappings().all()]
    total = len(parts)
    effects = []
    for c in body.constraints:
        before = len(parts)
        parts, applied, reason = _apply_one(parts, c.l, c.v)
        effects.append({
            "label": c.l, "value": c.v, "applied": applied,
            "delta": before - len(parts), "count_after": len(parts), "reason": reason,
        })
    return {"total": total, "count": len(parts), "effects": effects}
