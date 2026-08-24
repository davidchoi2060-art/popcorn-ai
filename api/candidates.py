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

⚠ **총액(2026-08-24 신설 — customer-audit-2026-08-24.md §1-2)**: 위 배분율·태그는 슬롯
  «각각»만 본다 — 슬롯마다 후보가 1개씩 있어도 그 최저가들의 «합»이 예산을 넘을 수 있고,
  전에는 그걸 아무도 안 봤다(그래서 「222개 · 3구성 가능」 뒤에 확정을 누르면 「조립 불가」가
  나왔다). `count_candidates()`가 이제 재사용 슬롯을 뺀 필수 슬롯 전부의 최저가 합을 예산과
  대조한다(`over_budget`·`budget_floor_total` 필드, 함수 안 긴 주석 참조).

⚠ **호환 규칙(2026-08-24 같은 날 오후 후속 — 위 총액 판정이 스스로 적어 두던 한계 해소)**:
  위 총액 판정은 원래 "슬롯별 최저가끼리 소켓 등이 맞는지는 불문"했다 — 그 한계가 실제로
  게임 57·58·59만원·영상편집 90만원에서 고객에게 닿는 것을 제작자가 실측으로 확인했다
  (buildable=true를 냈지만 실제 `/api/recommend`는 세 티어 전부 null). recommend.py의 DFS
  가지치기가 같은 날 고쳐지며 이 확인을 실시간(count 호출마다)으로 감당할 수 있게 돼서,
  buildable이 "참"이 되려는 시점에 recommend.py의 "가성비(value)" 티어를 실제로 한 번 돌려
  진짜 조립 가능한 조합이 있는지 확인한다(`compat_checked`·`compat_infeasible` 필드, 함수 안
  "실제 조립 가능성 확인" 블록 참조). **여전히 v0인 지점**: 이 확인은 recommend.py를 그대로
  «부르는» 것이지 candidates.py가 호환 판정을 다시 구현한 게 아니다(§단일 원천) — 그리고
  탐색이 노드 상한에 닿아 "못 찾았다"(exhausted)면 "없다"로 단정하지 않고 기존 총액 판정을
  그대로 믿는다(정직한 미확인으로 남긴다).

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


def _slot_stats(parts: list[dict]) -> tuple:
    """(슬롯별 후보 수, 슬롯별 최저가) — 총액 판정(2026-08-24 신설, 아래 참조)에 쓴다.

    `_slot_view`와 같은 분할(part_type → 슬롯)이지만 한 번의 순회로 **최저가까지** 함께
    얻는다. `_floor_slot`(=taxonomy.slot_of, 이 파일 상단에서 이미 usage_floors 하한
    판정에 쓰고 있다)이 "COOLER_*는 COOLER, 그 외는 자기 자신"으로 QUOTE_SLOTS와 똑같은
    분할을 이미 하고 있어서, `_slot_view`처럼 슬롯 8개마다 전체 목록을 다시 훑지 않고
    **부품마다 한 번**만 본다(O(8n) → O(n)) — count는 화면이 타이핑할 때마다 부르므로
    가벼운 쪽을 쓴다. QUOTE_SLOTS에 없는 part_type(HDD 등)은 두 결과 어디에도 안 남는다
    — `_slot_view`가 HDD를 순회하지 않는 것과 같은 결과다.
    """
    counts: dict = {}
    mins: dict = {}
    for p in parts:
        s = _floor_slot(p["part_type"])
        if s not in QUOTE_SLOTS:
            continue
        counts[s] = counts.get(s, 0) + 1
        price = p["sale_price"]
        if s not in mins or price < mins[s]:
            mins[s] = price
    return counts, mins


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

    # ============================================================================
    # 총액 판정 (2026-08-24 신설) — customer-audit-2026-08-24.md §1-2 해소
    # ============================================================================
    # ■ 결함이었던 것: 이 아래 블록 전까지는 슬롯마다 "후보가 1개라도 있는가"만 봤다.
    #   게임+40만원에서 슬롯 8개 전부 후보가 있었다(가장 싼 CPU·가장 싼 GPU·... 각자
    #   1개 이상) — 그래서 buildable=true, "가성비·추천·고성능 3구성을 만들 수 있어요"
    #   라고 말했다. 그런데 그 슬롯들의 최저가를 **합치면** 예산을 넘었다 — 확정을 누르면
    #   `/api/recommend`(실제 DFS)가 그 사실을 정직하게 걸러 sets 전부를 null로 냈다
    #   (customer-audit §1-2). 카운터가 "슬롯이 찼다"만 보고 "그 슬롯들의 합이 예산
    #   안에 드는가"를 한 번도 안 물은 것이 거짓말의 근원이었다.
    #
    # ■ 왜 이 계산이 recommend.py와 일치하는가(검증 근거 — 줄번호는 적지 않는다, 코드는
    #   같은 물결에서 다른 제작자가 고치는 중이라 줄번호가 바로 낡는다 — MAKER-CHECKLIST
    #   §8. 심볼로 확인한다: `grep -n "def _dfs" api/recommend.py`)
    #   recommend.py의 `_dfs()`는 슬롯을 채워 가며 "지금까지 쓴 돈 + 지금 고르는 부품값 +
    #   **남은 슬롯 각각의 최저가 합**(변수명 `min_rest`) > 예산" 이면 그 자리에서
    #   가지치기한다. 탐색 시작 시점(첫 슬롯)에서 이 부등식을 풀면: "전체 슬롯 최저가
    #   합(min_rest[0]) > 예산"이면 그 풀로는 **가장 싼 후보조차** 가지치기당한다 — 즉
    #   min_rest[0] > 예산이면 그 풀로는 어떤 조합도 안 나온다. 반대로 min_rest[0] <=
    #   예산이면 슬롯마다 최저가를 그대로 고른 조합 자체가 예산 안이라 가지치기에 걸리지
    #   않는다(호환 규칙은 별개 문제 — 아래 한계 참조). 이 min_rest[0]이 바로 "용도 하한을
    #   만족하는 슬롯별 최저가의 합"이고, 그 계산에 쓰는 풀(아래 `common`, 예산만 뺀 풀)도
    #   recommend.py의 `common`(제약 목록을 돌며 "예산" 라벨만 건너뛰고 나머지를 순서대로
    #   적용하는 반복문 — 그 파일도 이 파일의 `_apply_one`을 그대로 가져다 쓴다)과 정확히
    #   같은 절차다 — **같은 판정을 두 벌 적지 않으려고**(§단일 원천) 이 함수도
    #   `_apply_one`을 그대로 재사용해 recommend.py와 똑같은 시퀀스를 돌린다.
    #   value 티어는 이 min_rest[0]<=cap이 바로 성립/불성립을 가른다(배분율 없이 `common`
    #   +cap 그대로 DFS를 돈다 — "가성비형은 배분율을 받지 않는다"는 그 파일 주석 그대로).
    #   recommend 티어는 배분율 캡(`capped`)이 먼저 실패하면 배분율 없는 `common`+cap으로
    #   재시도하므로 결국 같은 min_rest[0]<=cap 조건으로 귀결된다. highend 티어는
    #   cap*HIGHEND_CAP_X(1.5배)로 더 느슨하므로 value·recommend가 되면 highend는 예산
    #   쪽에서 항상 더 여유 있다. 그래서 **하나의 총액 판정(cap 기준)이 세 티어 전부의
    #   예산 가능성을 동시에 결정한다** — "3구성을 만들 수 있어요"라는 한 문장짜리 verdict와
    #   정확히 대응한다. TestClient로 실측 대조했다(제작 보고 ①·⑥ 참조) — 세 티어의
    #   sets가 예산 하나로 함께 나거나 함께 살아 있었고, 하나만 null인 조합은 못 봤다.
    #
    # ■ 배분율(BUDGET_ALLOC)을 총액 판정의 근거로 쓰지 않는 이유 — 지시서가 짚은 대로
    #   recommend.py를 읽어 확인했다: 배분율 캡으로 한 티어가 실패하면 recommend.py
    #   스스로 배분율을 버리고 총액(cap)만으로 다시 짓는다("균형을 못 지킬 바엔 균형을
    #   포기하고 견적을 낸다" — 그 파일 주석 원문. recommend·highend 둘 다 이 재시도가
    #   있다). 즉 **배분율로 걸러진 풀(이 함수 위쪽의 `parts`, 제약을 순서대로 다 적용한
    #   결과)을 총액 판정의 근거로 쓰면 안 된다** — 배분율 탓에 예산을 넘는 것처럼 보이는
    #   거짓 불가능 판정이 나온다. 그래서 총액 판정은 반드시 배분율이 빠진 `common`으로
    #   한다(아래 코드).
    #
    # ■ 한계 — 정직하게 남긴다(이 판정이 recommend.py의 "완전한 재현"은 아니다)
    #   ① 호환 규칙(compat_rules — 소켓·전원 호환 등)은 여기서 안 본다. v0 카운터는
    #      애초에 슬롯 사이의 호환을 본 적이 없다(이 파일 맨 위 docstring — "그 외 제약은
    #      applied=false로 정직 표기"에 호환은 처음부터 없었다). "슬롯별 최저가 합 <= 예산"
    #      이 참이어도 그 최저가 부품들끼리 호환이 안 맞으면 실제 DFS는 더 비싼 조합을
    #      찾아야 하고 드물게 그마저 실패할 수 있다 — 이 판정은 **예산만의** 필요충분
    #      조건이지 호환까지 포함한 것은 아니다. 이번 수정이 새로 만든 한계가 아니라 v0
    #      카운터가 원래 갖고 있던 한계 위에 "총액"이라는 차원 하나를 정확하게 추가할 뿐이다.
    #   ② 「부품」(GPU 칩셋) 핀이 걸려 있고 재고에 매칭되면, 아래 `common`도 그 칩셋으로
    #      GPU 슬롯이 좁혀진 채로 최저가를 잰다. recommend.py는 그 풀로 실패하면 핀을
    #      포기하고(honored=false) 다시 짓는 마지막 안전망이 있는데, 이 카운터는 그
    #      안전망까지는 재현하지 않는다 — 핀이 걸린 채로 예산이 빠듯하면 실제로는
    #      recommend.py가 대체 GPU로 성공할 수 있는데도 이 카운터는 over_budget=true로
    #      더 보수적으로(불가능 쪽으로) 판단할 수 있다. 이번 물결 재현 범위(§1-2, GPU 핀
    #      없는 용도+예산 조합)에는 걸리지 않았다(제작 보고 검증 ⑥ 참조) — 핀+빠듯한
    #      예산의 조합은 이번 지시서 범위 밖이라 남겨 둔다.
    budget_v = next((c.v for c in body.constraints if c.l in BUDGET_LABELS), "")
    cap = _budget_cap(budget_v)

    retried_slots: list[str] = []
    over_budget = False
    budget_floor_total = None
    if empty or cap is not None:
        # `common` — 예산(배분율 포함)만 뺀 풀. 재시도(아래)와 총액 판정(더 아래) 둘 다
        # 이 풀 하나를 쓴다(풀을 두 벌 만들지 않는다). **필요할 때만** 만든다 — count는
        # 화면이 타이핑할 때마다 부르므로, 예산도 없고 빈 슬롯도 없는 흔한 경우(대화
        # 초반)엔 이 블록 전체를 건너뛰어 예전과 같은 비용으로 응답한다.
        common = pool
        for c in body.constraints:
            if c.l not in BUDGET_LABELS:
                common, _, _ = _apply_one(common, c.l, c.v)
        common_counts, common_mins = _slot_stats(common)

        # ── 재시도 — 엔진과 같은 규칙(recommend.py가 배분율 캡으로 실패한 티어를 배분율
        # 없는 `common`+cap으로 다시 짓는 것과 동일한 패턴 — 위 첫 번째 문단 참조).
        # 배분율 필터(BUDGET_ALLOC)로 후보가 0이 된 슬롯이 있으면, 예산만 뺀 풀(common —
        # 용도 하한·태그는 그대로 두고 배분율만 제거)로 **그 슬롯만** 다시 센다. 용도
        # 하한·태그 필터는 조립 조건이라 재시도에서도 그대로 유지한다(예산만 뺀다).
        if empty:
            still_empty = []
            for s in empty:
                n = common_counts.get(s, 0)
                if n > 0:
                    slot_counts[s] = n
                    retried_slots.append(s)
                else:
                    still_empty.append(s)
            empty = still_empty

        # 재시도로 살아난 슬롯이 있으면 예산 효과의 사유가 더는 사실 전부를 말하지 않는다
        # — "초과 부품 제외"만 남겨두면, 그 슬롯에 한해 배분 상한을 걷어냈다는 사실이 빠져
        # 화면이 그대로 싣는 문구가 실제와 어긋난다(화면이 이 reason을 그대로 싣는다).
        if retried_slots:
            labels = " · ".join(SLOT_KO.get(s, s) for s in retried_slots)
            note = (f" — {labels}는 배분 상한 적용 시 후보가 없어 그 부품에 한해"
                    " 배분 상한 없이 다시 포함(총액 예산은 별도 적용)")
            for e in effects:
                if e["label"] in BUDGET_LABELS and e["applied"]:
                    e["reason"] = e["reason"] + note

        # ── 총액 판정 — 위 긴 주석의 결론: 재사용 슬롯을 뺀 필수 슬롯 전부의 최저가
        # 합(common 기준)이 예산을 넘으면, 슬롯이 다 찼어도 조립 가능한 조합이 없다.
        # `empty`(재시도 이후)가 아직 남아 있으면 이 판정 자체가 의미 없다 — 슬롯 자체가
        # 없는데 그 슬롯의 "최저가"를 말할 수 없다(그 경우는 위 empty_slots가 이미
        # 정직하게 말하고 있다). 정확히 같음(=)은 통과다 — recommend.py의 가지치기도
        # `>`(초과)일 때만 자르지 `>=`가 아니다(경계 — 제작 보고 검증 ③).
        if cap is not None and not empty:
            required = [s for s in QUOTE_SLOTS if s not in reuse_slots]
            if all(s in common_mins for s in required):
                budget_floor_total = sum(common_mins[s] for s in required)
                over_budget = budget_floor_total > cap

    # 경계 — 필수 8슬롯을 전부 재사용으로 고르면 buildable은 참이지만 "3구성을 만들 수
    # 있다"는 문장은 사실이 아니다(새로 살 부품이 없다). verdict만 갈라 정직하게 말한다
    # — buildable을 false로 바꾸지는 않는다(정말 "안 되는" 것과는 다른 사실이라서다).
    all_reused = bool(reuse_slots) and set(reuse_slots) == set(QUOTE_SLOTS)

    # ============================================================================
    # 실제 조립 가능성 확인 (2026-08-24 물결 후속 — customer-audit §1-2 잔여 한계 해소)
    # ============================================================================
    # ■ 무엇을 고치나: 위 총액 판정(over_budget)은 슬롯별 "최저가끼리 합"만 본다 — 그
    #   최저가들이 실제로 서로 조립되는지(소켓 등 compat_rules)는 안 본다고 위 총액
    #   판정 블록 스스로 "■ 한계 ①"에 이미 적어 뒀다. 그 한계가 고객에게 실제로 닿는지
    #   제작자가 직접 쟀다(TestClient + X-Popcorn-Test, DB에는 쓰지 않는 직접 함수 호출과
    #   테스트표식 HTTP 호출을 병행) — 2026-08-24 기준 게임 57·58·59만원·영상편집 90만원
    #   에서 이 함수는 buildable=true를 냈지만 실제 `/api/recommend`(호환 규칙까지 보는
    #   진짜 탐색)는 세 티어 전부 null(search_exhausted 전부 false — "못 찾음"이 아니라
    #   "없음"으로 확정)이었다. S1은 대화 중 이 카운터만 보고 "지금 조건으로 견적을 만들
    #   수 있어요"를 여러 번 들려주다가, 확정을 눌러야만 진짜 결과(불가)를 알려주고 있었다.
    #
    # ■ 왜 지금은 감당되나(넘겨짚지 않고 직접 쟀다 — 근거 전문은 제작 보고): 이 물결에서
    #   recommend.py의 DFS 가지치기가 고쳐졌다(`_price_cut`). 이 확인은 "가성비(value)"
    #   티어 하나만 재사용한다 — recommend.py 파일 상단 docstring이 "가성비(최소 구성)가
    #   불가능하면 전 티어 불가"라고 선언하므로 value 하나의 성패가 3티어 전부를 대변한다.
    #   value(가격 오름차순 + 예산 이진 컷)는 그 가지치기 수정의 최대 수혜자라, 성공·실패
    #   사례를 가리지 않고(극단 저예산 40만원·무상한 예산·다중 제약 포함) 실측에서 병리적
    #   사례가 한 번도 없었다(전부 exhausted=False) — DFS 자체는 1ms 미만~23ms, 신선한
    #   연결+`_load_pool`+`load_compat_rules`+DFS 전부 합쳐도 평균 65~98ms(최대 127ms,
    #   대부분 탐색이 아니라 풀 재조회 쪽)였다. S1은 이미 이 카운터를 300ms 디바운스
    #   뒤에만 부른다(s1-session.html scheduleCount) — 총 응답 시간이 기존(약 40~70ms)의
    #   2~3배(약 110~170ms)가 되지만 사람이 지연으로 느끼는 문턱 안쪽이다.
    #
    # ■ 언제 확인하나 — buildable이 "참"이 되려는 시점에만(empty·over_budget·all_reused
    #   중 무엇에도 안 걸려 진짜 "만들 수 있다"고 말하려는 바로 그 지점). 이미 불가능이
    #   확정된 앞의 세 분기에서 또 확인하면 물을 것이 없고 비용만 든다.
    #
    # ■ recommend.py를 고치지 않고 «부른다»(지시서 계약) — `_load_pool`·
    #   `load_compat_rules`·`_rules_for_active`·`_build_set`을 그대로 가져다 쓴다.
    #   예산만 뺀 풀을 만드는 절차(`_apply_one` 순차 적용)도 위 총액 판정·recommend.py의
    #   `common`이 이미 공유하는 절차 그대로다 — 새 판정 술어를 여기서 다시 적지 않는다
    #   (§단일 원천). 순환 import를 피하려고 recommend는 이 블록 안에서만 지연 import한다
    #   (모듈 최상단에서 서로를 import하면 recommend.py가 이미 candidates.py를 최상단에서
    #   import하고 있어 순환이 생긴다 — 함수 호출 시점 지연 import는 그 문제가 없다).
    #
    # ■ 무엇을 새로 더했나(기존 필드는 이름도 뜻도 그대로 — 지시서 「더하는 건 되고 빼는
    #   건 안 된다」) — `compat_checked`(이 확인을 실행했는가)·`compat_infeasible`(실행
    #   했고 실제로 조립되는 조합을 못 찾았는가) 둘만 새로 낸다. `over_budget`이 이미
    #   그렇듯, 이 판정으로 buildable이 false가 될 때도 `empty_slots`는 여전히 빈
    #   배열이다 — 슬롯 자체가 빈 게 아니라 "그 슬롯들끼리 안 맞아서"이기 때문이고, 그
    #   구분은 `verdict` 문장이 말로 한다(화면이 이 사유를 더 세분해 보여주는 것은
    #   s1-session.html 소관이라 이 지시서 범위 밖 — over_budget이 이미 겪고 있는
    #   한계와 같다: `empty_slots`가 비어 있으면 화면의 emptyCard()가 "0개" 문구로
    #   떨어진다).
    #
    # ■ 한계 — 탐색이 상한(DFS_NODE_CAP)에 닿아 "못 찾았다"(exhausted=True)면 그건
    #   "없다"가 아니다(recommend.py 자신의 구분, 파일 상단 참조). 그 경우는
    #   compat_infeasible을 true로 만들지 않는다 — 확인하지 못한 것을 "안 된다"로
    #   지어내지 않는다(§화면 정직성). 위 실측대로면 value 티어에서는 사실상 안 일어나지만,
    #   일어나도 이 함수는 정직한 쪽(모른다 → 기존 총액 판정을 그대로 유지)으로 떨어진다.
    #   DB 접속 실패 등으로 이 블록 자체가 예외를 내면 삼키지 않는다 — 이 함수의 첫 SELECT
    #   (파일 맨 위 `parts` 조회)도 같은 이유로 방어하지 않으므로, 이 파일의 기존 관례와
    #   같다(조용히 폴백하면 "더 정확한 확인 실패"가 "기존 판정도 무효"로 오인될 수 있다
    #   — 500으로 실패를 드러내는 쪽이 정직하다).
    compat_checked = False
    compat_infeasible = False
    if not empty and not over_budget and not all_reused:
        from . import recommend as _rec   # 지연 import — 위 긴 주석 "recommend.py를…" 참조
        with engine.connect() as conn2:
            wide_pool = _rec._load_pool(conn2)
            compat_rules = _rec.load_compat_rules(conn2)
        wide_common = wide_pool
        for c in body.constraints:
            if c.l not in BUDGET_LABELS:
                wide_common, _, _ = _apply_one(wide_common, c.l, c.v)
        active_slots = [s for s in _rec.SLOTS if s not in reuse_slots]
        rules_active, _rules_unknown = _rec._rules_for_active(compat_rules, reuse_slots)
        compat_checked = True
        real_meta: dict = {}
        built = _rec._build_set("value", wide_common, cap, rules_active,
                                 active_slots=active_slots, meta=real_meta)
        compat_infeasible = built is None and not real_meta.get("exhausted")

    if empty:
        verdict = ("조건이 너무 좁아 "
                   + " · ".join(SLOT_KO.get(s, s) for s in empty)
                   + " 후보가 없어요 — 견적을 만들 수 없습니다. 조건을 하나만 완화해 주세요.")
    elif over_budget:
        # 「슬롯은 찼는데 총액이 안 맞는다」— 빈 슬롯과는 다른 사실이므로 다른 문장이다.
        # 숫자는 전부 이 함수가 실제로 계산한 값이다(지어내지 않는다) — 최저가 합·예산
        # 둘 다 근거로 남긴다.
        verdict = (f"조건을 만족하는 부품은 자리마다 있지만, 가장 저렴하게만 담아도 "
                   f"{budget_floor_total:,}원으로 예산 {cap:,}원을 넘어요 — "
                   "견적을 만들 수 없습니다. 예산을 늘리거나 조건을 하나만 완화해 주세요.")
    elif all_reused:
        verdict = "선택하신 부품을 전부 재사용하시면 새로 담을 부품이 없습니다 — 이번 견적에는 새로 사는 부품이 없어요."
    elif compat_infeasible:
        # 총액(슬롯별 최저가 합)은 예산 안인데, 그 최저가 부품들끼리 실제로는 안 맞는
        # 경우(소켓 등 호환 규칙) — 위 "실제 조립 가능성 확인" 블록 참조. budget_floor_total
        # 은 이미 계산돼 있을 때만(cap 있고 빈 슬롯 없을 때) 근거로 함께 보여준다 — 못
        # 잰 값(cap 없는 예산 등)은 지어내지 않는다.
        floor_txt = (f" (가장 저렴하게 담으면 {budget_floor_total:,}원으로 예산 안에는 듭니다)"
                     if budget_floor_total is not None else "")
        verdict = ("조건을 만족하는 부품은 자리마다 있지만, 그 부품들끼리 실제로 조립되는 "
                   f"조합을 찾지 못했습니다(호환 규칙){floor_txt} — 견적을 만들 수 없습니다. "
                   "조건을 하나만 완화해 주세요.")
    else:
        # 문구 수정(2026-08-24) — "가성비·추천·고성능 3구성을 만들 수 있어요"는 셋 다
        # 된다고 못박는 문장인데, 이 verdict는 그렇게 말하지 않는다(아래로 이유).
        #
        # ⚠ 아래 문단은 2026-08-24 오전 시점의 실측 기록이고, 지금은 낡았다 — 낡은 채로
        # 지우지 않고 남긴다(왜 문구가 지금 모양인지의 경위이기 때문). 당시: 예산이 총액
        # 판정 경계에 가까운 좁은 구간(게임 실측 예: 62·64·70·75만원)에서 "가성비=성공·
        # 추천=null"이 실제로 나왔다 — 원인은 recommend.py `_dfs()`가 그때 갖고 있던
        # 특성(추천 티어가 가격 내림차순으로 탐색하다 `DFS_NODE_CAP`에 먼저 닿음)이었다.
        #
        # 지금(같은 날 오후, DFS_NODE_CAP 결함이 recommend.py `_price_cut`으로 고쳐진
        # 뒤) 같은 네 지점을 제작자가 다시 직접 쟀다(TestClient로 `/api/recommend` 실호출,
        # 세션은 정리함) — 게임 62·64·70·75만원 전부 sets.value/recommend/highend가
        # 모두 not null이고 search_exhausted도 전부 false다. 즉 그 반례는 더는 반례가
        # 아니다. 그리고 바로 위 `compat_infeasible` 확인이 신설되면서, 이 else에
        # 도달했다는 것 자체가 "총액도 맞고 실제로 조립되는 조합도 찾았다"(value 티어
        # 성공 확정)는 뜻이 됐다 — 이 카운터가 실제로 확인한 사실이 하나 늘었다.
        #
        # 그래도 "3구성"이라고 셋을 못박지는 않는다 — "추천"·"고성능" 티어는 각자 다른
        # 정렬(내림차순)과 다른 예산 상한(고성능은 1.5배)으로 별도 탐색하므로, 이 카운터가
        # 확인한 "가성비 하나의 성공"이 나머지 둘까지 논리적으로 보장하지는 않는다(둘 다
        # DFS_NODE_CAP에 닿을 가능성은 이론상 남아 있다 — 지금은 안 나오지만 "안 나온다"
        # 는 관측이지 증명은 아니다). 그래서 이 함수가 실제로 보장하는 것("총액이 맞고,
        # 적어도 하나의 실제 조립 가능한 조합을 찾았다")만 말한다.
        verdict = "지금 조건으로 견적을 만들 수 있어요."

    return {
        "total": total, "count": len(parts), "effects": effects,
        "slots": slot_counts,
        # 빈 슬롯이 없어도 총액이 예산을 넘거나(over_budget) 총액은 맞아도 그 최저가
        # 부품들끼리 실제로 안 맞으면(compat_infeasible) buildable은 여전히 false다 —
        # 그래야 이름 그대로 "조립 가능한가"를 말한다(customer-audit-2026-08-24 §1-2 및
        # 그 잔여 한계 해소). 기존 필드(true=조립 가능·false=조립 불가)의 «뜻»은 그대로다
        # — 그 판정에 반영하던 근거가 하나(빈 슬롯) → 둘(+ 총액) → 셋(+ 실제 조립 확인)
        # 으로 정확해졌을 뿐이다.
        "buildable": not empty and not over_budget and not compat_infeasible,
        "empty_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in empty],
        # 재사용을 고른 슬롯 — count·buildable에서 왜 그 슬롯이 안 보이는지 화면이
        # 설명할 수 있게(§화면 정직성: 판정을 지어내지 않으려면 근거가 실려야 한다).
        "reused_slots": [{"slot": s, "label": SLOT_KO.get(s, s)} for s in reuse_slots],
        # 신설 필드(2026-08-24) — 「슬롯은 찼는데 총액이 안 맞는다」를 empty_slots와
        # 구분해 화면이 쓸 수 있게 한다. 기존 필드(total·count·slots·buildable·
        # empty_slots·reused_slots·verdict)는 이름도 뜻도 그대로다 — 추가만 했다.
        "over_budget": over_budget,
        # 재사용 슬롯을 뺀 필수 슬롯 전부의 최저가 합(원) — 계산했을 때만 값이 있고,
        # 예산이 없거나(cap None) 빈 슬롯이 있어 계산 자체가 무의미하면 null이다
        # ("못 쟀음"과 "0"을 구분한다 — MAKER-CHECKLIST §5).
        "budget_floor_total": budget_floor_total,
        # 신설 필드 둘(2026-08-24, 이 물결) — 「실제 조립 가능성 확인」 블록(위) 참조.
        # 기존 필드는 하나도 지우지 않았다 — 이름도 뜻도 그대로, 추가만 했다.
        # compat_checked   이 확인을 이번 응답에서 실제로 실행했는가. empty·over_budget·
        #                  all_reused 중 하나라도 걸리면 물을 것이 없어 실행하지 않고
        #                  false로 남는다 — "확인 안 함"과 "확인했고 문제 없음"을 화면이
        #                  구분할 수 있게 한다(§화면 정직성: 모르는 것을 지어내지 않는다).
        "compat_checked": compat_checked,
        # compat_infeasible  확인했고, 실제로 조립되는 조합을 못 찾았다(탐색 상한 도달로
        #                    "못 찾았다"인 경우는 제외 — 위 블록의 "■ 한계" 참조, 그때는
        #                    false로 남아 기존 총액 판정을 그대로 믿는다).
        "compat_infeasible": compat_infeasible,
        # 화면이 그대로 쓸 수 있는 한 문장 — 서버와 화면이 다른 말을 하지 않게
        "verdict": verdict,
    }
