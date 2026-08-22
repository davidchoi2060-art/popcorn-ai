"""결정론 엔진 v0 — S1 후보 풀 카운터 (POST /api/candidates/count).

A-02: 같은 입력 + 같은 재고 = 같은 출력. LLM 없음, 뷰 1쿼리 + Python 순차 필터.
base = v_recommendation_candidates ∧ stock_qty > 0 (UX-08 "조건 통과 부품 수").

v0 하드필터(정직한 최소 룰 — 그 외 제약은 applied=false로 정직 표기):
- 예산: 부품별 상한 배분율(아래 BUDGET_ALLOC — 휴리스틱, S2 엔진 배분 로직으로 대체 예정).
  '이상'·숫자 없음('AI 추천 예산' 등)은 미적용.
- 태그: **「선호」 라벨에 한해** 값에 '저소음' → tag_silent (스코프: GPU·POWER·CASE·COOLER —
  스코프 밖 부품은 무조건 통과. tag false의 이중 의미(미태깅) 때문에 전 부품 적용 시 전멸 위험),
  '화이트' → tag_white (스코프: CASE).
  ⚠ 라벨을 안 보고 값만 보던 시절엔 「요청」(고객 원문 요약)까지 걸러 같은 필터가 두 번
  걸렸다(2026-08-17 수정). 어느 라벨이 무엇을 거르는지는 아래 처분표가 정본이다.

effects = 제약 배열 순서대로 누적 적용한 델타. 순서를 바꾸면 최종 count는 같고
델타 배분만 달라진다 — 이것이 이 계약의 정의된 결정론이다.
"""
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from . import usage_floors as UF
from .db import engine
from .taxonomy import SLOT_LABELS as SLOT_KO   # 단일 원천(슬라이스 A)

router = APIRouter(prefix="/api")

# 용도 하한이 쓰는 사양 — 풀 SELECT에 반드시 실려야 한다.
# 빠뜨리면 `.get()`이 None을 주고 NULL 불통과로 **조용히** 전멸한다(규칙 필드 전례).
FLOOR_COLS = ("capacity_gb", "required_power_watt")


from .taxonomy import slot_of as _floor_slot   # part_type → 하한 슬롯(단일 원천)

# 예산 상한 배분율 — "어느 부품도 자기 배분율 상한을 초과할 수 없다"
BUDGET_ALLOC = {
    "CPU": 0.25, "GPU": 0.40, "MB": 0.15, "RAM": 0.10, "SSD": 0.12, "HDD": 0.08,
    "POWER": 0.10, "CASE": 0.08, "COOLER_CPU_AIR": 0.08, "COOLER_CPU_AIO": 0.08,
}
SILENT_SCOPE = {"GPU", "POWER", "CASE", "COOLER_CPU_AIR", "COOLER_CPU_AIO"}
WHITE_SCOPE = {"CASE"}

# ── 라벨이 「거를 자격」을 정한다 — 값 문자열이 아니다 (2026-08-17) ────────────────
# 아래 넷이 **들어오는 라벨 전부에 대한 처분표**다. 여기 없는 라벨은 거르지 않는다.
#
# 병(실측 2026-08-17): 태그 필터가 라벨을 보지 않고 값에 '저소음'·'화이트'가 「들어 있는지」만
#   봤다. 그래서 「요청」(고객 원문 요약)까지 필터를 받아 **같은 필터가 두 번** 걸렸다.
#     chat 「화이트로」 -> 요청 delta 469 · 선호 delta 0 (선호가 걸 것이 이미 없다)
#   결과: 완화 칩이 둘 뜨고, 「선호 조건 풀기」를 눌러도 3,059 가 아니라 2,590 까지만 돌아왔다.
#   같은 날 「우선순위 -> 선호」 통합으로 막은 「풀었는데 안 풀린다」 함정의 재발 경로였다.
#
# 왜 「값만 보는 것」이 구조적으로 틀렸나 — 셋이 동시에 성립했다:
#   ① 필터를 받을 자격은 라벨의 「뜻」이 정한다. 「요청」은 원문 요약이라 그 안에 어떤 낱말이
#      있든 조건이 아니다 — **그 라벨 자신의 reason 이 이미 그렇게 선언하고 있었다.**
#      코드가 자기 계약을 안 지키는 상태였고, 계약은 주석이 아니라 표로 지켜야 한다.
#   ② 판정이 낱말 운에 좌우됐다. 실측: 요청 '화이트로' -> applied=true(469 제외) ·
#      요청 '조용하게 해주세요' -> applied=false. **뜻이 같은데 결과가 다르다.**
#      고객이 우연히 태그 낱말을 그대로 쳤을 때만 걸리는 것은 규칙이 아니라 사고다.
#   ③ 그래서 「몇 개를 걸렀나」를 세는 검사는 이걸 못 잡는다 — 둘 다 「걸렀다」이므로 통과한다.
#      증명해야 하는 것은 **「이 라벨이 거를 자격이 있는가」**이고, 그건 세어서 알 수 없다.
#      표로 선언해야만 「자격 없는 라벨이 걸렀다」가 관측 가능한 사실이 된다.
#      (회귀 [26]·[42] 가 「문자열 모양」으로 동작을 추정하다 조용히 빠져나간 것과 같은 계열.)
#
# ⚠ 라벨을 여기 «빠뜨리면» 안 거르고 applied=false 로 정직하게 표기된다 — 화면은 그 제약을
#   완화 칩으로 내밀지 않으므로 조용한 오작동이 아니라 **눈에 보이는 미적용**이 된다.
#   반대 방향(자격 없는 라벨을 넣는 것)이 위험한 쪽이라, 넓히려면 근거를 여기 적는다.
BUDGET_LABELS = frozenset({"예산"})
USAGE_LABELS = frozenset({"용도", "상황"})
# 태그 필터를 받는 유일한 라벨. 화면(`s1-session.html` CONS_ALIAS)이 우선순위·소음·외관을
# 「선호」로 접어서 보내고, 서버 파서(`api/talk.py` LABELS)도 「선호」만 낸다 — 어휘의 정본은
# 그 둘이다. 여기서 별칭을 다시 정의하면 같은 어휘가 두 벌이 된다(CANON §1).
TAG_LABELS = frozenset({"선호"})
# 원문 보관 라벨 — 「거르지 않는다」가 계약이다. 고객이 친 말을 그대로 담는 자리라
# 조건이 아니고, 후보 수에 영향을 주지 않는다. 다만 **무시하지는 않는다**:
# `/api/recommend` 가 consult_sessions.constraints 에 저장하고, 근거 설명 경로
# (`recommend._explain_facts` 의 `고객_조건`)가 이 값을 그대로 재료로 쓴다.
VERBATIM_LABELS = frozenset({"요청"})


class Constraint(BaseModel):
    l: str
    v: str


class CountBody(BaseModel):
    constraints: list[Constraint] = []


def _budget_cap(value: str):
    """예산 라벨 → 상한(원) 또는 None(미적용). '200만원 이상'은 상한이 아니다.

    ⚠ 2026-08-22 수정: 옛 정규식 `\\d{2,3}`은 자릿수를 2~3자리로 못박아 "1500만원"에서
    뒤 세 자리 "500"만 집었다 — 예산 1,500만원 고객과 500만원 고객이 같은 상한(500만원)을
    받는 결함(조사자 실측). 자릿수 제한을 없애고 "1,500만원" 같은 콤마 구분 표기도 받는다.
    '만'이 없는 순수 숫자("150")·한글 수사("백오십만원")는 여전히 못 받는다 — 단위를
    지어내 해석하지 않는다.
    """
    if "이상" in value:
        return None
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*만", value)
    if not m:
        return None
    return int(m.group(1).replace(",", "")) * 10000


def _apply_one(parts: list[dict], label: str, value: str):
    """제약 1건 적용 — (남은 parts, applied, reason). 한 제약에 복수 태그면 순차 결합."""
    if label in BUDGET_LABELS:
        cap = _budget_cap(value)
        if cap is None:
            return parts, False, "상한 없는 예산 표현 — 후보 수에는 영향 없음"
        kept = [p for p in parts
                if p["sale_price"] <= int(cap * BUDGET_ALLOC.get(p["part_type"], 1.0))]
        return kept, True, "부품별 예산 상한(CPU 25%·GPU 40% 등 배분율) 초과 부품 제외"
    if label in USAGE_LABELS:
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
    if label in VERBATIM_LABELS:
        # 원문 요약이라 조건이 아니다. 값 안에 '화이트'·'저소음'이 들어 있어도 거르지 않는다 —
        # 거르면 화면의 선호 경로와 **같은 필터가 두 번** 걸린다(위 처분표 ①·②).
        return parts, False, "고객 원문 요약 — 조건이 아니므로 후보 수에는 영향 없음"
    if label in TAG_LABELS:
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
from .taxonomy import QUOTE_SLOTS   # 단일 원천 — recommend.SLOT_TYPES와 같은 표였다(슬라이스 A)


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
    pool = parts   # 원본(무필터) — 아래 재시도가 배분율만 뺀 풀을 다시 만드는 데 쓴다
    effects = []
    for c in body.constraints:
        before = len(parts)
        parts, applied, reason = _apply_one(parts, c.l, c.v)
        effects.append({
            "label": c.l, "value": c.v, "applied": applied,
            "delta": before - len(parts), "count_after": len(parts), "reason": reason,
        })
    slot_counts, empty = _slot_view(parts)

    # ── 재시도 — 엔진과 같은 규칙(recommend.py:757-761 「recommend」 티어와 동일 패턴) ──
    # 배분율 필터(BUDGET_ALLOC)로 후보가 0이 된 슬롯이 있으면, 예산만 뺀 풀(엔진의
    # `common` — 용도 하한·태그는 그대로 두고 배분율만 제거)로 **그 슬롯만** 다시 센다.
    # 새 방식이 아니다: recommend.py는 capped 로 실패하면 common 으로 다시 짓는다
    # (752-756행 근거: 배분율은 "한 부품에 몰빵하지 마라"는 균형 장치일 뿐 조립 조건이
    # 아니다) — 그 규칙을 이 파일의 슬롯 단위 카운터에 그대로 옮겼다. 용도 하한·태그
    # 필터는 조립 조건이라 재시도에서도 그대로 유지한다(예산만 뺀다).
    retried_slots: list[str] = []
    if empty:
        common = pool
        for c in body.constraints:
            if c.l not in BUDGET_LABELS:
                common, _, _ = _apply_one(common, c.l, c.v)
        common_counts, _ = _slot_view(common)
        still_empty = []
        for s in empty:
            n = common_counts.get(s, 0)
            if n > 0:
                slot_counts[s] = n
                retried_slots.append(s)
            else:
                still_empty.append(s)
        empty = still_empty

    # 재시도로 살아난 슬롯이 있으면 예산 효과의 사유가 더는 사실 전부를 말하지 않는다 —
    # "초과 부품 제외"만 남겨두면, 그 슬롯에 한해 배분 상한을 걷어냈다는 사실이 빠져
    # 화면이 그대로 싣는 문구가 실제와 어긋난다(화면이 이 reason을 그대로 싣는다).
    if retried_slots:
        labels = " · ".join(SLOT_KO.get(s, s) for s in retried_slots)
        note = (f" — {labels}는 배분 상한 적용 시 후보가 없어 그 부품에 한해"
                " 배분 상한 없이 다시 포함(총액 예산은 별도 적용)")
        for e in effects:
            if e["label"] in BUDGET_LABELS and e["applied"]:
                e["reason"] = e["reason"] + note

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
