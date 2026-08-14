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
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .timeutil import iso
from .pricing import sale_from_purchase, formula_text
from .candidates import BUDGET_ALLOC, SILENT_SCOPE, WHITE_SCOPE
from .db import engine
from .recommend import SLOTS, TIER_LABELS, HIGHEND_CAP_X

router = APIRouter(prefix="/api/admin")

# 호환 규칙은 이제 compat_rules 테이블이 단일 원천(슬라이스 34) — 하드코딩 제거.
# "contains"가 빠져 있었다(조립 호환 규칙 화면이 클라이언트에서 보정해 땜질했다 —
# 2026-08-15 확인자·제작자 실측). DB 실측 op 4종(eq·gte·lte·contains) 전수 대조로 채웠다.
# 의미는 recommend._cmp의 그대로다: v(다중값 목록)에 r이 있는가(쿨러 socket_list 등).
OP_KO = {"eq": "=", "gte": "≥", "lte": "≤", "contains": "포함"}
from .taxonomy import PART_LABELS as PART_KO   # 단일 원천(슬라이스 A)

# 총액 처리 — spec-policy-weights.md 1a 표의 「총액 처리」 열과 같은 문구(UX-31).
# highend만 상수를 문장에 꽂는다 — recommend.HIGHEND_CAP_X를 복제하지 않고 그 모듈에서 읽는다.
TIER_RULES = [
    {"key": "value", "label": TIER_LABELS["value"], "order": "슬롯별 가격 오름차순",
     "cap": "예산 상한 적용", "note": "최소 구성이 예산 밖이면 전 티어 불성립",
     "total_handling": "슬롯별 최저가 합산"},
    {"key": "recommend", "label": TIER_LABELS["recommend"],
     "order": "캡 내 가격 내림차순 + 총액 가지치기(DFS)",
     "cap": "예산 상한 적용", "note": "캡 내 최고가 합산이 예산을 넘지 않도록 총액으로 다시 자른다",
     "total_handling": "DFS로 조합 탐색해 예산 안 최댓값"},
    {"key": "highend", "label": TIER_LABELS["highend"], "order": "전체 풀 가격 내림차순",
     "cap": "예산 상한 미적용", "note": "예산 초과 시 'over'로 정직 표기 — 숨기지 않는다",
     "total_handling": f"추천형 총액의 {HIGHEND_CAP_X:g}배로 폭주 제한"},
]


def _load_skip_reason(r) -> str | None:
    """recommend.load_compat_rules()와 **정확히 같은 조건**으로 판정한다(UX-28).

    다른 계산을 쓰면 화면이 "적용됨"이라 말하는데 엔진은 건너뛰는 일이 난다 — 그래서
    엔진의 슬롯 인덱스 비교를 그대로 옮겼다(고치지 않고 읽기만 했다). active 여부와는
    별개의 구조적 사실이다 — 규칙을 켜는 순간 이 조건이 함께 걸린다.
    """
    if r["slot"] not in SLOTS or r["ref_slot"] not in SLOTS:
        return f"알 수 없는 슬롯({r['slot']} 또는 {r['ref_slot']})이라 엔진이 이 규칙을 건너뜁니다"
    if SLOTS.index(r["ref_slot"]) >= SLOTS.index(r["slot"]):
        return (f"ref_slot({r['ref_slot']})이 slot({r['slot']})보다 탐색 순서상 뒤라"
                " 엔진이 이 규칙을 건너뜁니다(경고 로그만 남기고 조용히 통과)")
    return None


@router.get("/engine-rules")
def engine_rules():
    with engine.connect() as conn:
        s = conn.execute(text(
            "SELECT card_fee_rate, margin_rate, effective_from FROM pricing_settings"
            " ORDER BY effective_from DESC LIMIT 1")).mappings().first()
        # 마진 정책은 이제 **판매 분류 노드**에 걸린다(0030). 예전엔 자유 문자열
        # 키에 0행이었고 어느 화면도 저장하지 않았다 — 죽은 표였다.
        cat_rows = conn.execute(text(
            "SELECT c.name AS category, m.margin_rate, m.updated_at"
            "  FROM category_margin_policies m"
            "  JOIN categories c ON c.category_id = m.category_id"
            " ORDER BY c.sort_order, c.name")).mappings().all()
        weights = conn.execute(text(
            "SELECT key, weight, updated_at FROM policy_weights ORDER BY key")).mappings().all()
        pool = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")).scalar_one()
        rule_rows = conn.execute(text(
            "SELECT rule_key, slot, field, op, ref_slot, ref_field, label, blocking, active,"
            " part_types"
            " FROM compat_rules ORDER BY sort_order, rule_id")).mappings().all()

    checks = []
    for r in rule_rows:
        skip_reason = _load_skip_reason(r)
        checks.append({
            "key": r["rule_key"], "label": r["label"],
            "rule": f"{r['slot']}.{r['field']} {OP_KO.get(r['op'], r['op'])} {r['ref_slot']}.{r['ref_field']}",
            "source": f"product_specs.{r['field']} / {r['ref_field']}",
            "blocking": r["blocking"], "active": r["active"],
            # 빈 목록 = 슬롯 전체. 값이 있으면 그 종류에만 걸린다 — 쿨러 슬롯처럼 성격이
            # 다른 부품이 섞이는 자리에서 겨냥하지 않은 부품까지 죽이지 않기 위한 조건이다.
            "part_types": r["part_types"] or [],
            # UX-28 — ref_slot이 탐색 순서상 slot보다 뒤면 엔진이 조용히 건너뛴다.
            # 화면이 이걸 안 보여주면 "공랭 쿨러 높이를 아무도 안 막는 상태"가 안 드러난다.
            "load_skipped": skip_reason is not None,
            "load_skip_reason": skip_reason,
        })

    # 카테고리별 필수 사양 — 화면이 표를 하드코딩하고 있었다(존재하지 않는 {igpu}·{m2_slots}·
    # {pcie_power}·{slot_width}까지). 게이트가 실제로 읽는 것은 spec_field_defs 메타다.
    from .spec_fields import required_map, all_fields, rule_readers
    labels = {f["field_key"]: f["label"] for f in all_fields()}
    rm = required_map()
    with engine.connect() as conn:
        readers = rule_readers(conn)     # 두 화면이 같은 답을 하도록 한 곳에서 계산한다

    required = [{
        "part_type": pt, "part_label": PART_KO.get(pt, pt),
        "fields": [{"key": k, "label": labels.get(k, k),
                    "used_by": readers.get((pt, k), [])}
                   for k in sorted(rm.get(pt, []))],
    } for pt in sorted(rm) if rm.get(pt)]

    fee = float(s["card_fee_rate"]) if s else 0.0
    margin = float(s["margin_rate"]) if s else 0.0
    sample = 100_000
    return {
        "compat": {
            "checks": checks,
            "slots": SLOTS,
            "required": required,
            "note": ("호환 규칙은 compat_rules 테이블이 단일 원천입니다(슬라이스 34) —"
                     " 엔진이 매 견적마다 이 표를 읽어 판정합니다. NULL 값은 불통과(값을 모르는"
                     " 부품을 호환으로 판정하지 않음) · 규칙 편집 UI·버전 발행은 이관."),
            "required_note": ("필수 사양은 spec_field_defs 메타가 단일 원천입니다 —"
                              " 게이트가 읽는 그 목록입니다. '읽는 규칙'이 비어 있으면"
                              " 어떤 호환 검사도 그 값을 쓰지 않는다는 뜻입니다"
                              " — 근거 없이 상품을 검수 대기로 묶고 있는 것입니다."),
        },
        "tiers": {
            "rules": TIER_RULES,
            "tie_break": "동일 조건이면 product_code 오름차순 — 같은 입력·같은 재고면 항상 같은 결과(A-02)",
            "performance_proxy": "성능 지표는 벤치마크 원천이 없어 가격을 대리값으로 씁니다(정직 명기 — 스코어 엔진 도입 시 교체)",
            "pool_size": pool,
            # UX-31 — highend 티어의 "추천형 총액의 1.5배" 사실을 상수 그대로 노출한다.
            # 화면이 이 숫자를 하드코딩하지 않고 여기서 읽게 한다(recommend.HIGHEND_CAP_X 원본).
            "highend_cap_x": HIGHEND_CAP_X,
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
            # 소수 셋째 자리까지 낸다 — 2.585%를 2.59%로 줄여 보이면 사용자가 정한 값이
            # 화면에서 다른 값이 된다(슬라이스 E에서 실제로 겪었다).
            "card_fee_pct": round(fee * 100, 3), "margin_pct": round(margin * 100, 3),
            "card_fee_rate": fee, "margin_rate": margin,
            "effective_from": iso(s["effective_from"]) if s and s["effective_from"] else None,
            "formula": formula_text(fee, margin),
            "example": {"purchase": sample,
                        "sale": sale_from_purchase(sample, fee, margin)},
            "categories": [{"category": c["category"], "pct": round(float(c["margin_rate"]) * 100, 2)}
                           for c in cat_rows],
            "category_note": ("카테고리별 마진 정책은 아직 등록된 행이 없습니다 —"
                              " 현재는 전 카테고리에 위 기본값이 적용됩니다(끝자리 규칙·최소 마진·"
                              "정책 버전 발행은 이관)."),
        },
        "weights": {
            "rows": [{"key": w["key"], "weight": float(w["weight"])} for w in weights],
            "note": ("추천 가중치 저장소(policy_weights)는 비어 있습니다 — 현재 추천은"
                     " 가중치 스코어가 아니라 티어별 정렬 + 호환 제약으로 결정됩니다."
                     " 스코어 엔진 도입 시 이 표가 실값으로 채워집니다."),
        },
    }


# ---- 슬라이스 74: 마진 정책 저장 ----
# "마진정책을 수정해도 변경이 안 된다"는 보고. 확인해 보니 **저장 기능이 아예 없었다** —
# 화면은 SCREEN="margin"인데 그 분기가 없어 표가 전부 마크업 더미였고, 쓰기 API도 없었다.
#
# pricing_settings는 **이력 테이블**이다(effective_from). 고치는 게 아니라 새 행을 넣는다 —
# 과거 견적을 그때 정책으로 재현할 수 있어야 하기 때문이다.
#
# **바꿔도 기존 판매가는 움직이지 않는다.** 산정은 단가표 반영 때 일어난다.
# 그 사실을 응답이 먼저 말한다 — 안 그러면 "바꿨는데 가격이 그대로"라고 읽는다.


class PricingBody(BaseModel):
    card_fee_rate: float          # 0.022 = 2.2%
    margin_rate: float            # 0.13  = 13%


@router.post("/pricing-settings")
def save_pricing(body: PricingBody):
    from .admin_orders import _log
    from .auth import current_operator

    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 바꿀 수 있습니다")
    # 비율은 0~1로 받는다. 13을 넣으면 1300%가 되어 가격이 폭주한다.
    for name, v in (("카드 수수료율", body.card_fee_rate), ("마진율", body.margin_rate)):
        if not (0 <= v < 1):
            raise HTTPException(400, f"{name}은 0 이상 1 미만이어야 합니다(0.13 = 13%)")

    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT card_fee_rate, margin_rate FROM pricing_settings"
            " ORDER BY effective_from DESC LIMIT 1")).mappings().first()
        # 부동소수점을 그대로 비교하면 2.2%를 다시 넣어도 '다른 값'이 된다
        # (2.2/100이 0.022000000000000002이 될 수 있다). 소수 6자리로 맞춰 본다.
        def _same(a, b):
            return round(float(a), 6) == round(float(b), 6)

        if cur and _same(cur["card_fee_rate"], body.card_fee_rate)                 and _same(cur["margin_rate"], body.margin_rate):
            raise HTTPException(400, "현재 값과 같습니다 — 바뀐 것이 없습니다")
        conn.execute(text(
            "INSERT INTO pricing_settings (card_fee_rate, margin_rate, effective_from,"
            " created_by) VALUES (:f, :m, now(), :by)"),
            {"f": body.card_fee_rate, "m": body.margin_rate,
             "by": me.get("operator_id")})
        log_id = _log(conn, "pricing_settings", "전역",
                      {"from": {"card_fee_rate": float(cur["card_fee_rate"]) if cur else None,
                                "margin_rate": float(cur["margin_rate"]) if cur else None},
                       "to": {"card_fee_rate": body.card_fee_rate,
                              "margin_rate": body.margin_rate}}, kind="price")
        # 이 정책으로 다시 산정될 대상이 몇 건인지 — 영향 규모를 숫자로 말한다
        affected = conn.execute(text(
            "SELECT count(*) FROM products WHERE purchase_price IS NOT NULL")).scalar_one()

    return {"ok": True, "undo_id": log_id, "affected_candidates": affected,
            "note": ("정책을 새 버전으로 저장했습니다."
                     f" 매입가가 있는 {affected:,}건이 다음 단가표 반영 때 이 값으로 산정됩니다."
                     " 기존 판매가는 지금 바뀌지 않습니다 —"
                     " 지금 맞추려면 판매가 재산정(reprice.html)에서 미리보기 후 반영하세요."),
            "reprice_href": "reprice.html"}


# 카테고리별 마진 저장은 **카테고리 관리 화면으로 옮겼다**(2026-08-05):
#   PUT /api/admin/categories/{cid}/margin
# 여기 있던 `POST /category-margins`는 자유 문자열 키에 값을 넣었고, 그 키가 어느
# 카테고리인지 아무도 몰랐다(FK 없음·0행·부르는 화면 없음). 고르는 자리와 값을 정하는
# 자리를 갈라 두면 둘이 어긋난다 — 트리에서 노드를 고르는 그 자리에서 정한다.
