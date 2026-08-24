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
from .catalog_map import gpu_chipset_key   # 「부품」(GPU 칩셋) 라벨 정규화 — 단일 원천(A-101)
from .db import engine
from .taxonomy import SLOT_LABELS as SLOT_KO, PART_LABELS, QUOTE_SLOTS   # 단일 원천(슬라이스 A)

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
# 아래 여섯이 **들어오는 라벨 전부에 대한 처분표**다(A-101로 PART_PIN_LABELS 추가,
# 2026-08-24 물결로 REUSE_LABELS 추가 — BUDGET_LABELS·USAGE_LABELS·TAG_LABELS·
# VERBATIM_LABELS·PART_PIN_LABELS·REUSE_LABELS). 여기 없는 라벨은 거르지 않는다.
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
# 부품 지정 라벨(A-101 신설, 이번 물결 계약 ①) — 값은 `catalog_map.gpu_chipset_key()`가
# 돌려주는 정규형("RTX 4070 SUPER" 형태). **지금은 GPU만 다룬다** — 다른 슬롯 지정은
# 아직 없다(공유 계약 ①). GPU 슬롯 후보를 그 칩셋과 일치하는 것만으로 좁힌다. 재고에
# 그 칩셋이 하나도 없으면 **거르지 않는다**(applied=false) — 후보 수를 0으로 떨어뜨리는
# 대신 화면이 "재고에 없는 부품"이라는 사실을 말할 수 있게 한다(그 자리는
# `recommend.py`의 핀 정책이 맡는다 — 이 파일은 카운터일 뿐 구성을 짜지 않는다).
PART_PIN_LABELS = frozenset({"부품"})

# 재사용 라벨(2026-08-24 물결 — customer-audit-2026-08-24.md §1-1 해소, 공유 계약 ①).
# guided 「업그레이드(일부 재사용)」에서 "그래픽카드·파워는 쓰던 거 쓸게요"를 고르면
# 화면이 { "l": "재사용", "v": "GPU" } 를 보낸다. 값은 슬롯 키(CPU·MB·RAM·GPU·CASE·
# COOLER·POWER·SSD) 또는 HDD(견적 8슬롯엔 없지만 핵심 부품이라 재고엔 있다).
#
# ⚠ 설계 판단 — 이 라벨은 **후보를 거르는 조건이 아니다** (다른 다섯과 다른 성격):
#   TAG_LABELS·USAGE_LABELS 등은 "이 조건을 만족하는 부품만 남긴다"이지만, 재사용은
#   "이 슬롯은 아예 새로 고르지 않는다"다 — 남길 후보를 고르는 게 아니라 슬롯 자체를
#   대상에서 뺀다. 그래서 값을 판정 기준(비교값)이 아니라 **제외 대상 슬롯 지정**으로 쓴다.
#
#   ① count(「조건 통과 부품 수」)에서 뺀다 — 그 슬롯은 이번 견적에서 사지 않을 것이므로,
#      "조건을 통과해 살 수 있는 부품 수"에 포함하면 사지도 않을 부품을 산다는 셈이 된다
#      (customer-audit §1-1이 잡은 바로 그 결함 — 재사용을 골라도 count·총액에 반영이
#      안 됐다). **하한값(2026-08-22 정정과 같은 정신)이 아니라 그 슬롯 자체를 뺀다.**
#   ② 그런데 **buildable 판정(_slot_view의 empty)에서는 예외로 둔다** — 그 슬롯의 후보가
#      0개인 이유가 "재고에 없어서"가 아니라 "안 사기로 해서"이기 때문이다. 그대로
#      두면 매번 "GPU 후보가 없어 견적을 만들 수 없습니다"라는 **거짓** verdict가 뜬다
#      (재고에는 있는데 "없다"고 말하는 것 — CLAUDE.md 「없다」와「범위 밖」을 구분한다의
#      반대쪽 오류). count_candidates()가 reuse_slots를 따로 계산해 empty에서 뺀다.
#   ③ HDD는 QUOTE_SLOTS(8슬롯)에 없다 — 견적에 필수가 아닌 선택 부품이라 애초에
#      "빈 슬롯"으로 잡힌 적이 없다(_slot_view가 HDD를 순회조차 안 한다). 그래서 HDD는
#      ②가 필요 없고 ①(count 제외)만 적용된다 — 별도 분기 없이 자연히 그렇게 된다.
#   ④ 모르는 값("COOLER_CPU_AIR"처럼 part_type을 그대로 보내는 등)은 applied=false로
#      정직하게 표기한다 — 값을 짐작해 임의 슬롯을 지우면 고객이 재사용하겠다고 하지
#      않은 부품이 조용히 빠질 수 있다(반대 방향의 사고가 더 위험한 쪽이다).
REUSE_LABELS = frozenset({"재사용"})


def _reuse_part_types(value: str):
    """재사용 값(슬롯 키 또는 HDD) → 뺄 part_type 집합. 모르는 값이면 None(정직한 미적용)."""
    if value in QUOTE_SLOTS:
        return QUOTE_SLOTS[value]
    if value == "HDD":
        return ("HDD",)
    return None


def _reuse_label_ko(value: str) -> str:
    """재사용 값의 한글 표시 — 슬롯 어휘가 정본이고, HDD처럼 슬롯이 아니면 부품 어휘로 보완."""
    return SLOT_KO.get(value) or PART_LABELS.get(value, value)


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

    ⚠ 2026-08-24 방어(공유 계약 ③ — customer-audit-2026-08-24 §2-5): "예산 -500만원"이
    부호만 사라진 채 양수 상한 500만원으로 쓰이고 있었다 — `-`를 안 보는 옛 정규식이
    "-500만원"에서 "500"만 집었기 때문이다. **음수를 거르는 «판정»은 여기서 새로 만들지
    않는다** — `api/talk.py`의 `_norm_budget`가 AI 파싱 경로의 단일 원천으로 dropped
    처리한다(같은 판정을 두 벌 두지 않는다, CANON §1). 이 함수가 하는 건 **판정이 아니라
    방어**다: talk.py를 거치지 않고 직접 들어오는 값(guided 칩 등)까지 포함해, 부호가
    "-"인 예산 값은 **어떤 경우에도 상한으로 쓰지 않는다**(None = 미적용). 왜 음수인지
    이유는 가리지 않고, "상한으로 쓰지 않는다"만 지키면 부호 소실로 잘못된 상한이
    매겨지는 사고는 막힌다.
    """
    if "이상" in value:
        return None
    m = re.search(r"(-)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*만", value)
    if not m:
        return None
    if m.group(1):
        return None   # 음수 예산 — 부호를 지우고 양수 상한으로 쓰지 않는다(위 방어 참조)
    return int(m.group(2).replace(",", "")) * 10000


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
    if label in PART_PIN_LABELS:
        # A-101: GPU 슬롯만 다룬다. product_name → gpu_chipset_key() 정규형이 value와
        # 같은 것만 남긴다. 값 자체가 이미 정규형이라 여기서 재정규화하지 않는다.
        matched = [p for p in parts if p["part_type"] == "GPU"
                   and gpu_chipset_key(p.get("product_name") or "") == value]
        if not matched:
            return parts, False, f"재고에 없는 부품: {value}"
        kept = [p for p in parts if p["part_type"] != "GPU"] + matched
        return kept, True, f"지정 부품(GPU) 일치 상품만 유지: {value}"
    if label in REUSE_LABELS:
        # 위 REUSE_LABELS 정의부의 ①~④ 설계 판단 참조. 필터가 아니라 **제외**다 — 값과
        # 비교해 일부만 남기는 게 아니라, 그 슬롯의 part_type을 통째로 뺀다.
        types = _reuse_part_types(value)
        if types is None:
            return parts, False, f"알 수 없는 재사용 부품 종류 — 후보 수에는 영향 없음: {value}"
        kept = [p for p in parts if p["part_type"] not in types]
        label_ko = _reuse_label_ko(value)
        return kept, True, f"{label_ko} — 쓰시던 부품을 재사용(신규 구매 대상에서 제외)"
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
# QUOTE_SLOTS는 파일 상단에서 이미 import했다(REUSE_LABELS 처분표도 그 표를 쓴다) —
# 같은 이름을 두 번 들여오면 다음 사람이 "둘이 다른가?"를 의심한다.


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
            # product_name — 「부품」(GPU 칩셋 지정, A-101) 판정에 필요(gpu_chipset_key 입력).
            "SELECT part_type, sale_price, tag_white, tag_silent, product_name, "
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

    # 재사용 슬롯 — REUSE_LABELS 정의부 ②: 그 슬롯이 empty인 이유는 "후보가 없어서"가
    # 아니라 "사지 않기로 해서"다. buildable 판정에서는 뺀다 — 안 그러면 재고에 GPU가
    # 있어도 매번 "GPU 후보가 없어 견적을 만들 수 없습니다"라는 거짓 verdict가 뜬다.
    # HDD는 QUOTE_SLOTS(8슬롯)에 없어 _slot_view가 애초에 순회하지 않으므로 여기 대상이
    # 아니다(③) — reuse_slots는 순수히 "이번엔 안 채워도 되는 필수 슬롯" 집합이다.
    reuse_slots = [s for s in QUOTE_SLOTS
                   if any(c.l in REUSE_LABELS and c.v == s for c in body.constraints)]
    empty = [s for s in empty if s not in reuse_slots]

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

    # 경계 — 필수 8슬롯을 전부 재사용으로 고르면 buildable은 참이지만 "3구성을 만들 수
    # 있다"는 문장은 사실이 아니다(새로 살 부품이 없다). verdict만 갈라 정직하게 말한다
    # — buildable을 false로 바꾸지는 않는다(정말 "안 되는" 것과는 다른 사실이라서다).
    all_reused = bool(reuse_slots) and set(reuse_slots) == set(QUOTE_SLOTS)
    if empty:
        verdict = ("조건이 너무 좁아 "
                   + " · ".join(SLOT_KO.get(s, s) for s in empty)
                   + " 후보가 없어요 — 견적을 만들 수 없습니다. 조건을 하나만 완화해 주세요.")
    elif all_reused:
        verdict = "선택하신 부품을 전부 재사용하시면 새로 담을 부품이 없습니다 — 이번 견적에는 새로 사는 부품이 없어요."
    else:
        verdict = "지금 조건으로 가성비·추천·고성능 3구성을 만들 수 있어요."

    return {
        "total": total, "count": len(parts), "effects": effects,
        "slots": slot_counts,
        "buildable": not empty,
        "empty_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in empty],
        # 재사용을 고른 슬롯 — count·buildable에서 왜 그 슬롯이 안 보이는지 화면이
        # 설명할 수 있게(§화면 정직성: 판정을 지어내지 않으려면 근거가 실려야 한다).
        "reused_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in reuse_slots],
        # 화면이 그대로 쓸 수 있는 한 문장 — 서버와 화면이 다른 말을 하지 않게
        "verdict": verdict,
    }
