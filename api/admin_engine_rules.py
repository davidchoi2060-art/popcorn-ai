"""추천 설정 3화면(호환 규칙·추천 기준·마진 정책)의 실근거 노출 — 읽기 전용.

**호환 규칙은 compat_rules 테이블이 단일 원천**(슬라이스 34 — 엔진이 이 표를 읽어 판정한다).
나머지는 아직 저장 테이블이 비어 있어(policy_weights·category_margin_policies 0행) 코드에
살아 있는 규칙을 노출한다 — 티어 정렬·예산 배분율(candidates.BUDGET_ALLOC)·태그 스코프·
가격 공식(pricing_settings 실값 + 천원 half-up). 화면이 연출값을 보여주는 대신
**지금 견적을 만드는 그 규칙**을 그대로 노출한다("모든 견적에는 이유가 있습니다"의 근거).

정직 표기: 버전 관리(v5·v12 같은 발행 번호)와 가중치 튜닝 저장소는 미모델링이므로
'현행값 1벌'만 존재한다 — 화면은 버전 대신 '현재 적용 중'으로 표기하고 이관을 밝힌다.
값을 바꾸는 기능은 이 슬라이스 범위 밖(코드 상수·pricing_settings 직접 수정 영역).
"""
from fastapi import APIRouter
from sqlalchemy import text

from .timeutil import iso
from .admin_price_import import _half_up_1000
from .candidates import BUDGET_ALLOC, SILENT_SCOPE, WHITE_SCOPE
from .db import engine
from .recommend import SLOTS, TIER_LABELS

router = APIRouter(prefix="/api/admin")

# 호환 규칙은 이제 compat_rules 테이블이 단일 원천(슬라이스 34) — 하드코딩 제거.
OP_KO = {"eq": "=", "gte": "≥", "lte": "≤"}

TIER_RULES = [
    {"key": "value", "label": TIER_LABELS["value"], "order": "슬롯별 가격 오름차순",
     "cap": "예산 상한 적용", "note": "최소 구성이 예산 밖이면 전 티어 불성립"},
    {"key": "recommend", "label": TIER_LABELS["recommend"],
     "order": "캡 내 가격 내림차순 + 총액 가지치기(DFS)",
     "cap": "예산 상한 적용", "note": "캡 내 최고가 합산이 예산을 넘지 않도록 총액으로 다시 자른다"},
    {"key": "highend", "label": TIER_LABELS["highend"], "order": "전체 풀 가격 내림차순",
     "cap": "예산 상한 미적용", "note": "예산 초과 시 'over'로 정직 표기 — 숨기지 않는다"},
]


@router.get("/engine-rules")
def engine_rules():
    with engine.connect() as conn:
        s = conn.execute(text(
            "SELECT card_fee_rate, margin_rate, effective_from FROM pricing_settings"
            " ORDER BY effective_from DESC LIMIT 1")).mappings().first()
        cat_rows = conn.execute(text(
            "SELECT category, margin_rate, updated_at FROM category_margin_policies"
            " ORDER BY category")).mappings().all()
        weights = conn.execute(text(
            "SELECT key, weight, updated_at FROM policy_weights ORDER BY key")).mappings().all()
        pool = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")).scalar_one()
        rule_rows = conn.execute(text(
            "SELECT rule_key, slot, field, op, ref_slot, ref_field, label, blocking, active"
            " FROM compat_rules ORDER BY sort_order, rule_id")).mappings().all()

    checks = [{
        "key": r["rule_key"], "label": r["label"],
        "rule": f"{r['slot']}.{r['field']} {OP_KO.get(r['op'], r['op'])} {r['ref_slot']}.{r['ref_field']}",
        "source": f"product_specs.{r['field']} / {r['ref_field']}",
        "blocking": r["blocking"], "active": r["active"],
    } for r in rule_rows]

    fee = float(s["card_fee_rate"]) if s else 0.0
    margin = float(s["margin_rate"]) if s else 0.0
    sample = 100_000
    return {
        "compat": {
            "checks": checks,
            "slots": SLOTS,
            "note": ("호환 규칙은 **compat_rules 테이블이 단일 원천**입니다(슬라이스 34) —"
                     " 엔진이 매 견적마다 이 표를 읽어 판정합니다. NULL 값은 불통과(값을 모르는"
                     " 부품을 호환으로 판정하지 않음) · 규칙 편집 UI·버전 발행은 이관."),
        },
        "tiers": {
            "rules": TIER_RULES,
            "tie_break": "동일 조건이면 product_code 오름차순 — 같은 입력·같은 재고면 항상 같은 결과(A-02)",
            "performance_proxy": "성능 지표는 벤치마크 원천이 없어 **가격**을 대리값으로 씁니다(정직 명기 — 스코어 엔진 도입 시 교체)",
            "pool_size": pool,
        },
        "budget": {
            "alloc": [{"part_type": k, "pct": round(v * 100, 1)} for k, v in BUDGET_ALLOC.items()],
            "note": ("부품별 상한 배분율(휴리스틱) — '이상'·숫자 없는 예산 표현에는 적용하지 않습니다."
                     " S2 엔진 배분 로직으로 대체 예정(이관)."),
            "tag_scope": [
                {"tag": "저소음", "field": "tag_silent", "scope": sorted(SILENT_SCOPE)},
                {"tag": "화이트", "field": "tag_white", "scope": sorted(WHITE_SCOPE)},
            ],
            "tag_note": "스코프 밖 부품은 무조건 통과 — 미태깅 부품이 전멸하는 것을 막기 위한 규칙",
        },
        "pricing": {
            "card_fee_pct": round(fee * 100, 2), "margin_pct": round(margin * 100, 2),
            "effective_from": iso(s["effective_from"]) if s and s["effective_from"] else None,
            "formula": "판매가 = 매입가 × (1 + 카드수수료 + 마진) → 1,000원 단위 half-up",
            "example": {"purchase": sample,
                        "sale": _half_up_1000(sample * (1 + fee + margin))},
            "categories": [{"category": c["category"], "pct": round(float(c["margin_rate"]) * 100, 2)}
                           for c in cat_rows],
            "category_note": ("카테고리별 마진 정책은 아직 등록된 행이 없습니다 —"
                              " 현재는 전 카테고리에 위 기본값이 적용됩니다(끝자리 규칙·최소 마진·"
                              "정책 버전 발행은 이관)."),
        },
        "weights": {
            "rows": [{"key": w["key"], "weight": float(w["weight"])} for w in weights],
            "note": ("추천 가중치 저장소(policy_weights)는 비어 있습니다 — 현재 추천은"
                     " 가중치 스코어가 아니라 **티어별 정렬 + 호환 제약**으로 결정됩니다."
                     " 스코어 엔진 도입 시 이 표가 실값으로 채워집니다."),
        },
    }
