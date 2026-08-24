"""견적 생성 엔진 v1 — POST /api/recommend.

A-02: 같은 입력 + 같은 재고 = 같은 구성. **구성 선택에는 LLM이 없다** — 이 파일의 탐색·
정렬·판정은 전부 결정론이고 `reasons`도 엔진이 적는 고정 문구다. LLM은 A-03이 허용한
「설명」에만 쓰이고, 그 자리는 견적 경로 밖의 `POST /api/recommend/explain` 하나다
(파일 맨 아래 — 확정 저장된 견적을 읽어 설명 문구만 만든다. 구성은 건드리지 않는다).
고정 슬롯 순서 DFS(백트래킹) — 호환성 5종은 제약, 티어는 슬롯 내 정렬 순서로만 구분:
  가성비 = 예산 캡 풀 + 가격 오름차순
  추천   = 예산 캡 풀 + 가격 내림차순 + 예산 총액 가지치기(현재 합+남은 슬롯 최저가 합>예산이면 prune)
           ("캡 내 최고가 합산"은 캡 합이 136%라 예산 초과 — DFS 가지치기로 해소)
  고성능 = 전체 풀 + 가격 내림차순, 예산 캡 미적용(초과는 budget.verdict='over'로 정직 표기)
숫자 예산이 없으면 캡·합 제약 없이 추천은 중간 순위 우선. tie-break = product_code 오름차순.
가성비 탐색이 실패하면 전 티어 불가 — 예산 안에 드는 조합을 하나도 못 찾으면 견적 자체가
불성립(추천·고성능도 시도하지 않는다).

⚠ **가성비는 "최저가 조합"이 아니다.** `_dfs()`는 가격 오름차순으로 후보를 훑다가 처음
성립하는 조합을 그 자리에서 확정할 뿐, 전체 조합을 나열해 총액을 비교하지 않는다(사전식
첫 완성 구성 탐색). 왜 그런지·언제부터 이랬는지·실측 결과는 `_dfs()` 참조.

v1 정직 한계(문서·응답에 명기): 성능 지표(벤치·FPS) 미보유 — 가격을 사양 근사(proxy)로 사용.
NULL 스펙 필드는 해당 호환 검사 불통과로 간주(검증 불가 부품은 조립 보증 불가 → 제외).
"""
import json
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from . import access_gate   # 접근 게이트의 단일 원천 — 열쇠 생성·소유자 확인·횟수 제한
from . import llm       # LLM 호출의 단일 원천 — 이 파일에서 프로바이더를 직접 부르지 않는다
from . import visitor
from .catalog_map import gpu_chipset_key   # 「부품」(GPU 칩셋) 핀 정책 — 단일 원천(A-101)
from .auth import LOCAL_HOSTS   # localhost 판정 — dev-login과 같은 정의를 그대로 쓴다(새로 만들지 않는다)

from . import spec_fields   # 부품 종류별 "설명에 쓸 사양"의 단일 원천(spec_field_defs)
from . import usage_floors as UF
from .timeutil import iso, now_iso
from .candidates import BUDGET_ALLOC, SLOT_KO, _apply_one, _budget_cap, REUSE_LABELS
from .db import engine
from .product_name import display_name   # 견적은 파는 이름이 아니라 설명하는 이름을 쓴다

router = APIRouter(prefix="/api")
log = logging.getLogger("recommend")

from .taxonomy import SLOTS, QUOTE_SLOTS as SLOT_TYPES   # 단일 원천(슬라이스 A)
# 안전망 — 병리적 조합 폭발을 막는 상한. 실규모 실측(슬라이스 40)에 맞춰 상향했다.
# 시드 30종 시절엔 100,000이 "도달 불가"였지만 실카탈로그(추천 후보 3,046)에서는
# 예산 100만원 추천이 682,419노드를 써서 답을 찾는다(0.11초). 100,000은 답이 있는데도
# 없다고 말하게 만드는 값이었다. 탐색 자체는 싸다 — 100,007노드가 0.02초다.
DFS_NODE_CAP = 2_000_000

TIER_LABELS = {"value": "가성비형 견적", "recommend": "추천형 견적", "highend": "고성능형 견적"}

# 고성능 티어가 예산을 넘어도 되는 배수(슬라이스 58 · U-13).
# "예산 무시"는 견적이 아니다 — 램 하나에 예산의 776%를 쓰는 구성이 나왔다.
# 1.5배는 "조금 더 쓰면 이만큼 나아진다"를 보여주면서 부품 균형을 지키는 선이다.
HIGHEND_CAP_X = 1.5


class Constraint(BaseModel):
    l: str
    v: str


class RecommendBody(BaseModel):
    mode: str
    constraints: list[Constraint] = []


def _load_pool(conn):
    # 규칙이 참조하는 필드는 전부 여기서 실려야 한다 — 규칙을 추가하면 이 목록도 함께 늘린다
    # (슬라이스 39에서 socket_list를 빼먹어 KeyError로 견적이 500이 됐다).
    #
    # maker·chipset·clock_mhz·pcie_gen·interface·tag_rgb(아래 6개)는 호환 판정에는 안
    # 쓴다 — 견적 응답의 부품 항목이 가격·이름뿐이라 "왜 이 부품인가"를 설명할 재료가
    # 없던 것을 메우려고 추가했다(재료 늘리기 단계 · AI는 안 붙임). 전부 이미 조인된
    # v_recommendation_candidates 컬럼이라 추가 조회가 아니라 SELECT 목록만 늘어난다.
    # `brand`·`warranty_months`는 뺐다 — 후보 풀 3,059건 전수 확인 결과 **둘 다 0%
    # 채움**(products.brand·warranty_months가 전부 NULL)이라 실어도 null만 나간다.
    # "제조사"가 필요한 자리는 100% 채워진 `maker`로 대신한다(brand가 아니라 maker다).
    return [dict(r) for r in conn.execute(text(
        "SELECT product_code, sku, product_name, part_type, sale_price, stock_qty,"
        " maker, chipset, socket, socket_list, mem_type, clock_mhz, tdp_watt, rated_watt,"
        " required_power_watt, pcie_gen, interface,"
        " form_factor, form_factor_list, capacity_gb,"
        " length_mm, gpu_max_mm, cooler_height_mm, cooler_tdp,"
        " radiator_rows, radiator_max_rows, tag_white, tag_silent, tag_rgb,"
        " spec_sources, data_origin, market_price"
        # 가격 게이트는 뷰가 건다(0017). 여기서도 한 번 더 막는 이유: 값이 없는 부품이
        # 들어오면 예산 비교가 TypeError로 **견적 API 전체를 500**으로 만든다.
        # 조용히 결과가 줄어드는 게 아니라 화면이 통째로 죽는 자리라 이중으로 막는다.
        " FROM v_recommendation_candidates"
        " WHERE stock_qty > 0 AND sale_price IS NOT NULL")).mappings().all()]


def load_compat_rules(conn) -> dict:
    """compat_rules(ERD §3.7)를 슬롯별로 로드 — **엔진의 단일 원천**(슬라이스 34).

    로드 시 계약 검증: ref_slot이 탐색 순서상 slot보다 앞이어야 한다. 위반 규칙은
    건너뛰고 경고한다(잘못된 규칙이 KeyError로 엔진을 죽이지 않게).
    """
    rows = conn.execute(text(
        "SELECT rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, blocking,"
        " part_types"
        " FROM compat_rules WHERE active ORDER BY sort_order, rule_id")).mappings().all()
    by_slot: dict = {}
    for r in rows:
        if r["slot"] not in SLOTS or r["ref_slot"] not in SLOTS:
            print(f"[compat_rules] 알 수 없는 슬롯, 규칙 건너뜀: {r['rule_key']}")
            continue
        if SLOTS.index(r["ref_slot"]) >= SLOTS.index(r["slot"]):
            print(f"[compat_rules] ref_slot이 탐색 순서상 뒤, 규칙 건너뜀: {r['rule_key']}")
            continue
        by_slot.setdefault(r["slot"], []).append(dict(r))
    return by_slot


def _rules_for_active(rules: dict, reused) -> tuple:
    """호환 규칙을 재사용 슬롯 기준으로 나눈다 — (판정 가능한 규칙, 판정 불가 규칙) (2026-08-24).

    customer-audit-2026-08-24 §1-1 · 공유 계약 ② — 재사용 슬롯은 **어떤 모델인지 모른다**.
    그 슬롯을 slot(직접 대상)으로 삼는 규칙은 대상 부품 자체가 없어 평가할 수 없고,
    ref_slot(비교 대상)으로 삼는 규칙은 비교할 값이 없다 — `_cmp`의 NULL 원칙("값을
    모르면 통과시키지 않는다")과 같은 정신이지만, 여기서는 "불통과"가 아니라 "판정
    자체를 하지 않는다"다(불통과로 처리하면 "재사용 GPU가 호환 안 됨"이라는, 실제로는
    확인한 적 없는 결론을 지어내게 된다 — §화면 정직성이 금지하는 바로 그것).

    반환한 `active`는 DFS(_dfs·_slot_ok·_narrow·_fwd_ok·build_search_index)에 그대로
    넘긴다 — 그 함수들은 `chosen[ref_slot]`을 직접 읽으므로, ref_slot이 재사용이면
    chosen에 그 키 자체가 없어 KeyError가 난다. active는 그런 규칙을 아예 안 담으므로
    DFS는 재사용 슬롯을 참조하는 규칙을 만날 일이 없다. `unknown`은 화면에 "판정 못 함"을
    정직하게 보여주는 재료로만 쓴다(build_compat).
    """
    active: dict = {}
    unknown: list = []
    for slot, rs in rules.items():
        if slot in reused:
            unknown.extend(rs)
            continue
        keep = [r for r in rs if r["ref_slot"] not in reused]
        unknown.extend(r for r in rs if r["ref_slot"] in reused)
        if keep:
            active[slot] = keep
    return active, unknown


def applied_rule_count(rules: dict) -> int:
    """한 구성에 **실제로 걸리는** 검사 수 — 등록 규칙 수와 다르다.

    등록은 9종인데 그중 둘은 쿨러 방식에 따라 **배타적**이다:
    쿨러 높이(공랭 전용)와 라디에이터(수랭 전용). 한 구성의 쿨러는 하나뿐이라
    둘 중 하나만 걸린다 — 그래서 **어떤 구성도 9종을 다 통과하지 않고 항상 8종이다.**

    첫 화면이 "호환성 9종 통과"라고 말하면 S2·S3 가 같은 견적을 "8종"이라 말한다.
    두 화면이 서로 다른 말을 하는 것은 '호환성 5종'과 같은 종류의 거짓이고,
    방향만 반대다. 그래서 **화면에는 이 수를 준다**(사용자 결정 2026-08-08 · A안).

    세는 법: 슬롯마다 제한 없는 규칙은 전부 세고, 제한 있는 규칙은 **한 종류가 고를 수
    있는 최대치**만 센다(같은 part_type 에 규칙이 둘이면 둘 다 걸리므로 2).
    8을 상수로 박지 않는 이유 — 규칙은 이미 8종에서 9종으로 한 번 늘었다.
    """
    n = 0
    for _slot, rs in rules.items():
        free = [r for r in rs if not r.get("part_types")]
        limited = [r for r in rs if r.get("part_types")]
        best = 0
        if limited:
            types: set = set()
            for r in limited:
                types |= set(r["part_types"])
            for t in types:
                best = max(best, sum(1 for r in limited if t in r["part_types"]))
        n += len(free) + best
    return n


def _cmp(op: str, v, r) -> bool:
    """NULL 불통과 — 값을 모르는 부품을 호환으로 판정하지 않는다(ERD §3.7 계약)."""
    if v is None or r is None:
        return False
    if op == "eq":
        return v == r
    if op == "gte":
        return v >= r
    if op == "lte":
        return v <= r
    if op == "contains":
        # 다중값 필드(쿨러 socket_list) — 상대 값이 목록에 있는가. 빈 목록은 불통과.
        # 실측 근거: 쿨러는 소켓을 평균 5~6개 지원해 단일값 비교로는 표현할 수 없다(슬라이스 39).
        return bool(v) and r in v
    return False   # 미지의 연산자 — 불통과(조용히 통과시키지 않는다)


def _rule_applies(rule, p) -> bool:
    """이 규칙이 이 부품을 겨냥하는가 — `part_types`가 비면 슬롯 전체(기존 동작).

    한 슬롯에 성격이 다른 부품이 들어온다: 쿨러 슬롯은 공랭과 수랭을 함께 받는다.
    공랭용 높이 규칙이 수랭에도 걸려 **수랭 49개가 통째로 탈락**하고 있었다(슬라이스 82).
    NULL 불통과라 실패가 아니라 '조용한 전멸'로 나타난다.
    """
    pts = rule.get("part_types") or []
    return not pts or p.get("part_type") in pts


def _slot_ok(slot, p, chosen, rules: dict):
    """슬롯 진입 호환 검사 — DB 규칙을 그대로 적용. 규칙 없는 슬롯(CPU·GPU·SSD)은 독립.

    필드가 풀에 없으면 `.get()`이 None을 주고 NULL 불통과 규칙이 걸린다 — 500으로 죽는 대신
    "판정할 수 없으니 통과시키지 않는다"로 떨어진다(누락은 check_rule_fields가 경고로 알린다).
    """
    for rule in rules.get(slot, ()):
        if not _rule_applies(rule, p):
            continue
        v = p.get(rule["field"])
        r = chosen[rule["ref_slot"]].get(rule["ref_field"])
        if not _cmp(rule["op"], v, r):
            return False
    return True


def check_rule_fields(pool, rules: dict) -> list:
    """규칙이 참조하는 필드가 풀에 실렸는지 확인 — 누락은 조용한 전면 불통과를 만든다."""
    if not pool:
        return []
    keys = set(pool[0].keys())
    missing = sorted({f for rs in rules.values() for r in rs
                      for f in (r["field"], r["ref_field"]) if f not in keys})
    if missing:
        print(f"[recommend] 경고: 규칙 참조 필드가 후보 풀에 없습니다: {missing}"
              " (_load_pool SELECT 목록에 추가해야 합니다)")
    return missing


def _order_of(tier, has_cap) -> str:
    """정렬 방향의 단일 판정 — `_tier_sort`(실제 정렬)와 `_dfs`(예산 이진 컷, 아래)가
    같은 판단을 쓴다(2026-08-24 신설 — DFS_NODE_CAP 결함 수정). 둘이 따로 판단하면
    한쪽만 바뀌었을 때 이진 컷이 정렬과 다른 방향으로 잘라 결과를 조용히 바꿀 수
    있다(§단일 원천) — 그래서 판단을 이 함수 하나로 모은다. `_build_set`가
    `_tier_sort`를 부를 때 쓴 것과 **같은 (tier, has_cap)**을 `_dfs`에도 그대로 넘긴다.
    """
    if tier == "value":
        return "asc"
    if tier == "highend" or has_cap:
        return "desc"
    return "median"   # 추천 + 숫자 예산 없음 — 가격에 대해 단조가 아니라 이진 컷 대상 아님


def _tier_sort(parts, tier, has_cap):
    order = _order_of(tier, has_cap)
    if order == "asc":
        return sorted(parts, key=lambda p: (p["sale_price"], p["product_code"]))
    if order == "desc":  # 추천(숫자 예산)·고성능 = 내림차순 + 가지치기
        return sorted(parts, key=lambda p: (-p["sale_price"], p["product_code"]))
    # 추천 + 숫자 예산 없음 — 중간 순위 우선
    asc = sorted(parts, key=lambda p: (p["sale_price"], p["product_code"]))
    mid = (len(asc) - 1) // 2
    return sorted(asc, key=lambda p: (abs(asc.index(p) - mid), asc.index(p)))


def build_search_index(slot_pools, rules: dict) -> dict:
    """탐색 가속 인덱스 (슬라이스 40) — **결정론을 바꾸지 않는다.**

    두 가지만 한다: ① 후보 집합을 줄인다(순서는 티어 정렬 그대로 유지) ② 확실히 실패할
    분기를 미리 자른다. 둘 다 원래 DFS가 어차피 버렸을 경로만 건드리므로 **첫 완성 구성은
    동일**하다. 회귀 세트의 고정 기대값이 그 증거다(150만 1,500,000 · 200만+ 2,145,200 불변).

    **실측 이득은 작다(정직 기록)**: 예산 70만원 추천에서 노드 46,738 → 45,888(2%).
    병목이 eq 규칙 슬롯이 아니라 예산 가지치기에 걸리는 조합의 대량 순회였기 때문이다.
    100만원 추천이 안 나온 진짜 원인은 노드 상한값이었고 그건 DFS_NODE_CAP 상향으로 고쳤다.
    이 인덱스는 부품이 더 늘어날 때를 위한 구조로 남긴다 — 결과는 바뀌지 않음이 확인됐다.

    ① **eq / contains 규칙 → 값 인덱스**: MB는 CPU 소켓별, RAM은 MB 메모리 규격별,
       쿨러는 지원 소켓별로 미리 묶는다. 상대 값이 정해지면 그 그룹만 본다
       (기존에는 전 후보를 순회하며 하나씩 비교했다).
    **적용 부품이 슬롯의 일부인 규칙은 여기서 제외한다**(슬라이스 82-B) — 아래 두 최적화는
    모두 "슬롯 전체가 이 규칙을 받는다"를 전제로 자르기 때문이다. 전제가 깨지면 자르기가
    유효한 구성을 없애고, 그건 '규칙이 막았다'보다 나쁘다(막힌 이유를 설명할 수 없다).

    ② **gte / lte 규칙 → 극값 전방 검사**: 슬롯의 field 최대·최소를 미리 계산해,
       상대 슬롯을 고른 즉시 "대상 슬롯에 후보가 0인가"를 O(1)로 판정한다.
       예: GPU 길이가 케이스 최대 장착 길이보다 크면 그 GPU는 즉시 버린다
       (케이스 수백 개를 순회한 뒤 실패하지 않는다). 극값으로 0을 확정할 때만 자르므로
       판정이 느슨한 방향이고, 결과는 바뀌지 않는다.
    """
    eq_idx: dict = {}
    fwd: list = []
    for slot, rs in rules.items():
        pool = slot_pools.get(slot) or []
        for rule in rs:
            # **적용 부품이 슬롯의 일부인 규칙은 인덱스에 넣지 않는다**(슬라이스 82-B).
            # 인덱스와 전방 검사는 "이 규칙은 슬롯 전체에 걸린다"를 전제로 자른다.
            # 수랭 전용 라디에이터 규칙을 그대로 넣었더니, 수랭 최대 열이 비어 있는
            # 케이스를 "붙을 쿨러가 없다"며 통째로 잘라냈다 — 공랭을 쓰는 구성까지
            # 더 비싼 케이스로 밀려 가성비 총액이 316,400에서 323,800이 됐다.
            # 규칙이 막은 게 아니라 **탐색이 유효한 구성을 못 찾은 것**이라 더 나쁘다.
            # 자르지 않으면 느려질 뿐이지만, 잘못 자르면 결과가 조용히 달라진다.
            scope = rule.get("part_types") or []
            if scope and not set(SLOT_TYPES.get(slot, ())) <= set(scope):
                continue
            op, fld = rule["op"], rule["field"]
            if op in ("eq", "contains"):
                g: dict = {}
                for p in pool:
                    v = p.get(fld)
                    if v is None:
                        continue          # NULL 불통과 — 인덱스에 넣지 않는다
                    for key in (v if op == "contains" else (v,)):
                        g.setdefault(key, []).append(p)
                eq_idx.setdefault(slot, []).append((rule, g))
            elif op in ("gte", "lte"):
                vals = [p.get(fld) for p in pool if p.get(fld) is not None]
                if vals:
                    fwd.append((rule["ref_slot"], rule, slot,
                                max(vals) if op == "gte" else min(vals)))
    return {"eq": eq_idx, "fwd": fwd}


def _narrow(slot, chosen, idx, pool):
    """eq/contains 인덱스로 후보를 좁힌다 — 티어 정렬 순서는 그대로 남는다."""
    lists = []
    for rule, g in idx["eq"].get(slot, ()):
        ref = chosen[rule["ref_slot"]].get(rule["ref_field"])
        if ref is None:
            return []                     # 상대 값을 모른다 → 전부 불통과(NULL 원칙)
        got = g.get(ref)
        if not got:
            return []
        lists.append(got)
    if not lists:
        return pool
    lists.sort(key=len)
    base = lists[0]
    for other in lists[1:]:
        codes = {p["product_code"] for p in other}
        base = [p for p in base if p["product_code"] in codes]
    return base


def _fwd_ok(slot, p, idx):
    """이 후보를 고르면 뒤 슬롯이 확실히 비는가 — 비면 지금 자른다(극값 기준)."""
    for ref_slot, rule, _target, ext in idx["fwd"]:
        if ref_slot != slot:
            continue
        rv = p.get(rule["ref_field"])
        if rv is None:
            return False                  # 상대 값이 없으면 대상 슬롯이 전부 불통과
        if rule["op"] == "gte" and ext < rv:
            return False
        if rule["op"] == "lte" and ext > rv:
            return False
    return True


def _price_cut(cands, order, threshold):
    """가격 정렬 후보에서 예산 상한을 넘을 «수밖에 없는» 구간을 이진 탐색으로 건너뛴다.

    ㉰ 가지치기 추가 — 2026-08-24 「추천형이 예산 충분한데도 null」결함 수정의 핵심.
    아래 `_dfs`의 docstring에 원인 실측이 있다 — 요약하면 **하나씩 `continue`로
    건너뛰던 예산 초과 후보가 노드 카운터를 계속 소모해 DFS_NODE_CAP에 먼저 닿았다.**

    `_narrow()`가 돌려주는 리스트는 `_tier_sort`가 정한 순서(가격 오름/내림차순)를
    그대로 유지한다 — eq/contains 좁히기(인덱스 그룹·교집합)는 원본 리스트의 상대
    순서를 보존하는 **필터**일 뿐 재정렬하지 않는다(`_narrow` 참조). 그 순서가 가격에
    대해 단조이므로, "합계 + 남은 슬롯 최저가 합 > 예산" 판정도 이 슬롯 후보 하나의
    가격이 "threshold(=예산 − 합계 − 남은 최저가 합)를 넘는가"라는 **가격 하나에 대한
    단조 조건**으로 바꿔 쓸 수 있다. 단조 구간은 이진 탐색으로 한 번에 자를 수 있다 —
    하나씩 검사하며 세지 않는다.

    **결과를 바꾸지 않는다는 것이 이 함수의 전제다**: 잘라내는 것은 원래 루프가
    `total + price + min_rest > budget_limit`로 하나씩 `continue`했을 바로 그
    후보들뿐이다 — 남는 후보의 **집합과 순서**는 원래와 완전히 같다. 그래서 이미
    노드 상한에 안 닿고 성공하던 입력은 이 함수가 있든 없든 **같은 첫 완성 구성**을
    찾는다(먼저 찾는 후보의 순서 자체를 바꾸지 않으므로). 다만 상한에 막혀 실패하던
    입력은 낭비되던 노드가 사라진 만큼 더 깊이 갈 수 있어 **찾던 못 찾던 결과가
    달라질 수 있다** — 이건 버그가 아니라 이 수정이 고치려는 대상 그 자체다.

    order="desc"(추천·고성능 — 예산 안 최고가 우선)면 threshold 이하가 시작되는
    지점부터 끝까지 남기고, order="asc"(가성비 — 최저가 우선)면 threshold 이하인
    접두만 남긴다. order="median"(추천 · 숫자 예산 미지정)은 가격에 대해 단조가
    아니므로 자르지 않는다 — 그 경로는 budget_limit 자체가 항상 None이라(`_build_set`
    이 tier=="recommend"·cap=None일 때 limit_override 없이 그대로 None을 넘긴다)
    호출자가 이 함수를 아예 부르지 않는다.
    """
    if order == "median":
        return cands
    lo, hi = 0, len(cands)
    if order == "desc":
        # cands[mid] 가 threshold 를 넘는 동안 오른쪽을 좁힌다 — "threshold 이하가
        # 시작되는" 첫 위치를 찾는다. 그 앞은 전부 초과이므로 통째로 버린다.
        while lo < hi:
            mid = (lo + hi) // 2
            if cands[mid]["sale_price"] <= threshold:
                hi = mid
            else:
                lo = mid + 1
        return cands[lo:]
    # order == "asc" — "threshold 를 처음 넘는" 위치를 찾는다. 그 뒤는 전부 초과다.
    while lo < hi:
        mid = (lo + hi) // 2
        if cands[mid]["sale_price"] <= threshold:
            lo = mid + 1
        else:
            hi = mid
    return cands[:lo]


def _dfs(slot_pools, budget_limit, rules: dict, slots=None, order="desc"):
    """사전식 첫 완성 구성 탐색. budget_limit 있으면 합 가지치기.

    min_rest(남은 슬롯 최저가 합)는 **좁히기 전 전체 풀** 기준으로 둔다 — 더 느슨한 하한이라
    가지치기가 결과를 바꾸지 않는다(좁힌 풀로 계산하면 chosen에 따라 값이 달라져 계산 불가).

    `slots`(2026-08-24 추가) — 이번에 실제로 채울 자리 목록. 기본은 전체 SLOTS(8종).
    재사용 슬롯이 있으면 `_build_set`이 그 슬롯을 뺀 부분집합을 넘긴다 — DFS는 그 자리를
    아예 방문하지 않는다(고르지 않는다). SLOTS의 부분집합이라 상대 순서는 그대로다.

    `order`(2026-08-24 추가) — `slot_pools`가 정렬된 방향("asc"/"desc"/"median").
    `_build_set`이 `_order_of(tier, cap is not None)`로 계산해 넘긴다(정렬을 만든
    판단과 **같은 판단** — 두 곳에서 따로 판단하면 한쪽만 바뀔 때 어긋난다). 이 값으로
    `_price_cut`이 예산 초과가 확정된 구간을 이진 탐색으로 건너뛴다(아래 결함 기록 참조).

    ── 결함(2026-08-24, customer-audit 후속 실측) ─────────────────────────────────
    추천형(has_cap=True → 가격 내림차순)이 **예산이 충분한데도** 노드 상한
    (DFS_NODE_CAP=2,000,000)에 먼저 닿아 «구성 없음»으로 처리되는 결함이 있었다
    (게임·62/64/70/75만원 재현). 원인은 예산이 아니라 **탐색**이었다 — 실측
    (게임·70만원, 예산 배분율(BUDGET_ALLOC)로는 RAM·SSD 슬롯이 통째로 비어 즉시
    폴백하는 「배분 없음(common)」풀 기준, 깊이별 방문 수):

        슬롯      방문(node)     예산초과 continue       비고
        CPU            172           151(88%)
        MB           1,367         1,319(96%)
        RAM          4,337         4,197(97%)          MB.mem_type eq 로 좁혀도 이 비율
        GPU         31,970        31,784(99%)          겨냥 규칙 없음 — 전량 순회
        CASE       137,999       134,412(97%)
        COOLER     650,500       647,328(99%)
        POWER    1,173,661     1,160,442(99%)          겨냥 규칙이 gte라 좁히기 인덱스가
                                                        없다 — COOLER 성공마다 507개
                                                        (POWER 전량)를 처음부터 재순회
        합계     2,000,006(=DFS_NODE_CAP+6)  — SSD는 방문조차 못 함

    즉 **노드의 97~99%가 "규칙에 안 맞아서"가 아니라 "지금 남은 예산보다 비싸서"
    버려졌다.** 내림차순이라 매 슬롯에서 제일 비싼 것부터 시도하는 게 원인이고,
    그 버림을 하나씩 `continue`로 처리하며 매번 nodes[0]를 소모한 것이 상한 도달의
    직접 원인이다(narrow 인덱스는 eq/contains 규칙만 좁히고, POWER의 규칙은 gte라
    좁혀지지 않는다 — GPU는 겨냥 규칙 자체가 없다). `_price_cut`이 이 구간을
    이진 탐색으로 건너뛴다 — 방향 판단(㉯ 슬롯 순서 변경 대신 ㉰ 가지치기 추가를
    고른 이유)과 검증 결과는 이 파일이 아니라 작업 보고에 남긴다.

    ── 가성비는 "최저가"를 보장하지 않는다 (2026-08-24, 가성비 문구 정정 후속) ────────
    대외 문구(모듈 docstring·`_build_set`의 reasons["value"])가 한동안 "예산 안
    최저가 조합"·"최소 구성"이라 말했는데 거짓이었다 — 이 함수는 전체 조합을 나열해
    비교하지 않고 처음 성립하는 조합을 그 자리에서 확정한다(사전식 첫 완성 구성 탐색,
    위 함수 설명 그대로). 엔진 최초 커밋(2026-07-23)부터 이 구조였다 — 오늘 생긴
    문제가 아니다.

    메커니즘: 슬롯은 호환 규칙(소켓·규격)으로 서로 묶여 있다. 오름차순 탐색이 앞
    슬롯에서 고른 최저가 후보와 호환되는 뒤 슬롯 후보 중에는 비싼 것만 남을 수 있다.
    예산을 올리면 그 "싼 앞 슬롯 + 비싼 뒤 슬롯" 경로가 새로 budget_limit을 통과해
    (오름차순이라 더 싼 앞 슬롯 후보가 먼저 시도된다) 먼저 성립해 버려서, 예산을
    낮췄을 때 찾았던(뒤로 밀려 있던 다른 앞 슬롯 후보의) 조합보다 총액이 더 높은 채로
    확정될 수 있다 — 코드 버그가 아니라 "비교 없이 첫 성공을 반환"하는 탐색 방식의
    구조적 한계다.

    ⚠ 이 물결 지시서(2026-08-24)는 실제 사례로 게임·예산 34만원→339,800원,
    36만원→348,300원을 제시했다(조사자 실측). 문구 교정 작업 중 이 사례를 TestClient·
    `_build_set` 직접 호출로 재현을 시도했으나 — 11개 용도 × 2,000~5,000원 간격 예산
    스윕(6,600건 이상, 20만~300만원 구간, 무용도 풀·GPU 부품 핀 포함) — **가성비
    티어에서는 재현되지 않았다**(불성립 구간 다음은 항상 예산과 무관한 상수, 즉 오늘
    조회된 카탈로그에서는 단조였다). 이 저장소는 재고·가격이 상시 변동한다(CANON.md·
    CLAUDE.md 여러 곳 기록) — 조사 시점 이후 카탈로그가 바뀌었을 수 있다. 같은 스윕에서
    **추천 티어(내림차순 + 예산 가지치기)는 지금도 비단조 구간이 실제로 있다** — 이
    부류의 탐색이 비단조를 만들 수 있다는 사실 자체는 오늘도 확인된다. 위 메커니즘은
    코드 구조이지 카탈로그 스냅샷이 아니다 — 특정 두 금액이 지금 재현되지 않는다고 이
    사실 자체가 바뀌지는 않는다.
    """
    slots = SLOTS if slots is None else slots
    min_rest = [0] * (len(slots) + 1)
    for i in range(len(slots) - 1, -1, -1):
        min_rest[i] = min_rest[i + 1] + min(p["sale_price"] for p in slot_pools[slots[i]])
    idx = build_search_index(slot_pools, rules)
    nodes = [0]

    def go(i, chosen, total):
        if i == len(slots):
            return dict(chosen)
        slot = slots[i]
        cands = _narrow(slot, chosen, idx, slot_pools[slot])
        if budget_limit is not None:
            cands = _price_cut(cands, order, budget_limit - total - min_rest[i + 1])
        for p in cands:
            nodes[0] += 1
            if nodes[0] > DFS_NODE_CAP:
                return None
            if budget_limit is not None and total + p["sale_price"] + min_rest[i + 1] > budget_limit:
                continue   # _price_cut 이후엔 걸릴 일이 없어야 정상 — 안전망으로 남긴다
            if not _slot_ok(slot, p, chosen, rules):
                continue
            if not _fwd_ok(slot, p, idx):
                continue
            chosen[slot] = p
            r = go(i + 1, chosen, total + p["sale_price"])
            if r is not None:
                return r
            del chosen[slot]
        return None

    got = go(0, {}, 0)
    exhausted = got is None and nodes[0] > DFS_NODE_CAP
    if exhausted:
        print(f"[recommend] 탐색 노드 상한({DFS_NODE_CAP:,}) 도달, 구성 없음으로 처리")
    # (chosen, exhausted) 튜플로 반환한다(2026-08-24 추가) — 「없다」와 「못 찾았다」는
    # 다른 사실이라 구분해 돌려준다(§화면 정직성). exhausted=True는 got=None을 항상
    # 동반한다(cands 순회 중 nodes[0]가 상한을 넘는 즉시 그 자리에서 None을 반환하므로
    # "상한을 넘겼는데 그 다음에 성공"은 있을 수 없다 — 상호배타적이다).
    return got, exhausted


def build_compat(chosen: dict, rules: dict, unknown_rules=()) -> dict:
    """호환성 요약 — **DB 규칙에서 생성**(슬라이스 34). recommend와 swap이 공유.

    표시 항목이 규칙과 1:1이 되어, 규칙을 추가하면 화면 근거도 자동으로 늘어난다.
    detail은 규칙의 detail_fmt({v}=대상값 / {r}=상대값)로 조립한다.

    `unknown_rules`(2026-08-24 추가) — 재사용 슬롯이 껴서 판정 자체를 할 수 없는 규칙
    (`recommend()`가 `_rules_for_active`로 갈라 넘긴다). **조용히 빠뜨리지 않는다** —
    `rules`(판정 가능한 규칙)에서는 이미 빠져 있으므로, 여기서 pass/fail 이 아닌
    unknown=True 항목으로 따로 올린다. 빠뜨리면 "검사 안 함"이 그냥 "언급 없음"이 되어
    고객이 "통과했나 보다"로 오독할 수 있다(§화면 정직성 — 판정할 수 없는 것을 통과로
    만들지 않는다). `expert.py`·`swap.py`는 이 인자를 안 넘긴다 — 기본값 `()`이라
    기존 동작(재사용 개념이 없는 호출)은 그대로다.

    ⚠ **`unknown_rules`는 "판정 불가"와 "이 구성엔 애초에 대상이 아님"을 섞어서 담고
    있다**(2026-08-24 결함 수정 — customer-audit-2026-08-24 §1-1 후속). `_rules_for_active`는
    재사용 슬롯을 slot(대상)·ref_slot(비교 상대) 어느 쪽으로 겨냥하든 전부 이 목록에
    넣는다 — 갈라 담지 않는 것이 그 함수 안에서는 맞다(대상 슬롯이 재사용이면 chosen에
    그 키 자체가 없어 `_rule_applies`를 부를 수 없다). 그런데 아래 루프에서 그대로 다
    "확인 보류"로 찍으면, 대상 슬롯은 우리가 이미 아는 부품인데(재사용 아님) 그 규칙이
    겨냥하는 종류가 아닌 경우(예: 공랭 쿨러 구성에서 수랭 전용 `radiator`)까지 「확인
    보류」분모에 들어간다 — 존재하지도 않는 검사를 "아직 확인 못 함"으로 만드는 것이라
    §화면 정직성이 금지하는 "판정을 지어낸다"의 다른 얼굴이다. 그래서 아래 루프에서
    **기존 `_rule_applies`를 그대로 재사용해**(새 판정 술어를 적지 않는다 — §단일 원천)
    "대상 슬롯을 이미 아는가"부터 가른다.
    """
    checks = []
    for slot in SLOTS:
        for rule in rules.get(slot, ()):
            # 겨냥하지 않은 부품에는 검사를 내밀지 않는다. 수랭 구성에 '쿨러 높이 여유'를
            # 띄우면 검증한 적 없는 것을 검증했다고 말하는 셈이다(슬라이스 82).
            # rules가 이미 재사용 슬롯을 slot·ref_slot 어느 쪽으로도 안 담고 있으므로
            # (_rules_for_active) chosen[slot]·chosen[ref_slot]은 항상 안전하다.
            if not _rule_applies(rule, chosen[slot]):
                continue
            v = chosen[slot].get(rule["field"])
            r = chosen[rule["ref_slot"]].get(rule["ref_field"])
            fmt = rule["detail_fmt"] or "{v} / {r}"
            # 결측 참조 필드(None)를 str()에 그대로 넣으면 문구에 "None"이 샌다
            # (재현: "라디에이터 장착 불통과 · 3열 ≤ 케이스 None열" — 판정(_cmp)은
            # 이미 NULL 불통과로 맞고 문구만 오염됐다). 화면(S1 inspectBlock 등)이
            # 이미 쓰는 관례인 "—"로 바꾼다 — 값이 있는데 "—"로 지워지는 방향이
            # 아니라 없는 값만 대체하므로 판정과는 무관하다.
            # guided·chat·talk 는 DFS가 결측 참조 필드를 남기는 조합 자체를 탐색에서
            # 제외해 이 코드가 실사용자에게 노출된 적이 없었다 — expert 모드가 엔진이
            # 절대 만들지 않던 조합을 사람이 직접 만들 수 있게 열면서 드러났다.
            checks.append({
                "key": rule["rule_key"], "label": rule["label"],
                "pass": _cmp(rule["op"], v, r), "unknown": False,
                "detail": fmt.replace("{v}", "—" if v is None else str(v))
                             .replace("{r}", "—" if r is None else str(r)),
            })
    for rule in unknown_rules:
        # customer-audit-2026-08-24 §1-1 후속 결함 수정 — `unknown_rules`를 그대로 다
        # 찍으면 «애초에 이 구성의 대상이 아닌 규칙»까지 「확인 보류」로 세게 된다.
        # 두 가지를 분명히 가른다:
        #   ① 규칙의 대상 슬롯(rule["slot"]) 자체가 재사용이라 chosen에 그 부품이 없다
        #      → 그 부품이 무엇인지 몰라 규칙이 적용되는지조차 판정할 수 없다.
        #      (예: gpu_len·case_board — 대상 CASE 자체가 재사용) → **계속 unknown**.
        #   ② 대상 슬롯은 재사용이 아니라 chosen에 실제 부품이 있다(우리가 이미 아는
        #      부품) — 이때는 기존 `_rule_applies`(§단일 원천, 판정 술어를 다시 적지
        #      않는다)를 그대로 적용해, 그 부품의 part_type이 애초에 이 규칙의 대상이
        #      아니면(예: 공랭 쿨러 구성에서 수랭 전용 `radiator` 규칙) **아예 목록에서
        #      뺀다** — "확인 못 함"이 아니라 "해당 없음"이라 분모에도 들지 않는다.
        # ref_slot(비교 상대)이 재사용인 것은 ①·② 어느 쪽이든 그대로 유지된다 —
        # 대상 부품이 이 규칙에 걸린다는 것은 알아도 비교할 상대값을 모르기 때문이다.
        known_target = chosen.get(rule["slot"])
        if known_target is not None and not _rule_applies(rule, known_target):
            continue
        checks.append({
            "key": rule["rule_key"], "label": rule["label"],
            "pass": None, "unknown": True,
            "detail": "재사용 부품이라 확인할 수 없습니다",
        })
    # GPU·POWER 어느 한쪽이라도 재사용이면 chosen에 그 키가 없다 — .get()으로 안전하게
    # 읽고, 여유율은 null(계산 불가)로 낸다. null이 "사양 결측"과 "재사용이라 모름"
    # 두 사유를 다 가질 수 있어 power_headroom_unknown으로 사유를 가른다.
    gpu, power = chosen.get("GPU"), chosen.get("POWER")
    headroom = (int(power["rated_watt"] / gpu["required_power_watt"] * 100)
                if gpu and power and power.get("rated_watt") and gpu.get("required_power_watt")
                else None)
    return {"power_headroom_pct": headroom, "checks": checks,
            "power_headroom_unknown": gpu is None or power is None}


# ---- 견적 이유의 재료 (재료 늘리기 단계 — AI는 붙이지 않는다) ----
# A-03: LLM은 "왜 이 부품인가"를 설명만 한다, 견적을 만들지 않는다. 설명하려면 설명할
# 사실이 있어야 하는데 지금까지 items[]는 이름·가격뿐이었다. 아래 둘은 그 재료를
# `_load_pool()`이 이미 읽어 둔 값에서 뽑아 실을 뿐, 판정·정렬 로직은 건드리지 않는다.

_TAG_FIELDS = ("tag_silent", "tag_white", "tag_rgb")


def _pref_tags(p: dict) -> list:
    """확정된 선호 태그만 — **참인 것만** 이름으로 올린다.

    CLAUDE.md §데이터: 태그 백필은 "명시 표현만 인정, 추론 금지 — false는 아직 판정
    안 함"이다. `tag_silent: false`를 그대로 실으면 "판정 안 함"이 "조용하지 않음"으로
    오독되고, 다음 단계(LLM)가 근거 없는 부정 서술을 쓸 재료가 된다. 그래서 false는
    아예 적지 않는다.
    """
    return [name for name, field in
            (("silent", "tag_silent"), ("white", "tag_white"), ("rgb", "tag_rgb"))
            if p.get(field)]


def _explain_spec(p: dict) -> dict:
    """부품 설명에 쓸 사양만 종류별로 고른다 — 전부 싣지 않는다.

    "어떤 사양이 어떤 부품 종류에 뜻이 있는가"는 이미 `spec_field_defs`가 정의한다
    (→ `api.spec_fields.fields_for`, 프로세스 캐시라 요청마다 DB를 새로 안 읽는다).
    여기서 두 번째 매핑을 만들지 않는다(CANON §1 — 정본 복제 금지) — 그래서 CPU엔
    socket·tdp_watt만, SSD엔 capacity_gb·form_factor·interface만 남고 CPU에
    capacity_gb, SSD에 socket 같은 무의미한 None이 섞이지 않는다. 값이 없는 필드는
    설명 재료가 못 되므로 뺀다(모르는 것을 지어내지 않는다).
    """
    out = {}
    for f in spec_fields.fields_for(p.get("part_type")):
        k = f["field_key"]
        if k in _TAG_FIELDS:
            continue   # 태그는 _pref_tags()가 참인 것만 따로 싣는다
        v = p.get(k)
        if v is not None:
            out[k] = v
    return out


def _build_set(tier, pool, cap, rules, floor_note=None, relax_note=None, limit_override=None,
               active_slots=None, unknown_rules=None, reuse_note=None, meta=None,
               alloc_capped=True):
    """`active_slots`·`unknown_rules`·`reuse_note`(2026-08-24 추가) — 재사용 슬롯 처리
    (customer-audit-2026-08-24 §1-1). 기본값은 전부 None/생략과 같은 뜻이라 기존 호출부
    (`api/expert.py`·이 파일의 `/api/showcase`)는 손대지 않아도 그대로 동작한다.

    active_slots  실제로 채울 자리(기본 SLOTS 전체). 재사용 슬롯을 뺀 부분집합이 오면
                  그 자리는 DFS가 방문하지 않는다 — **고르지 않고, 값도 안 매긴다.**
    unknown_rules 재사용 슬롯이 껴서 판정할 수 없는 호환 규칙 — build_compat에 그대로
                  전달해 unknown으로 정직하게 표시한다(통과로 지어내지 않는다).
    reuse_note    reasons에 덧붙일 재사용 안내(전력·호환 확인 불가 캐치프레이즈 포함).
    meta          (2026-08-24 추가 — DFS_NODE_CAP 결함 수정 후속) 호출자가 준 딕셔너리에
                  **부작용으로** `{"exhausted": bool}`을 채운다. 반환값의 `None | dict`
                  계약은 그대로 지킨다(expert.py 등 기존 호출부는 이 인자를 안 줘서
                  영향이 없다) — `chosen`이 None이어도 **왜** None인지(슬롯 자체가
                  비었나 / DFS가 상한에 닿았나)를 반환값 하나로는 구분할 수 없어서
                  마련한 별도 채널이다. `exhausted=True`는 "이 조건엔 구성이 없다"가
                  아니라 "정해진 노드 안에서 못 찾았다"는 뜻 — 다른 사실이다
                  (§화면 정직성, `/api/recommend`의 `search_exhausted` 계약 참조).
    alloc_capped  (2026-08-24 추가 — "최고 사양" 문구 정직화 후속) 이 호출의 `pool`이
                  부품별 배분 상한(BUDGET_ALLOC)이 걸린 풀인가. 고성능형 reasons의
                  "배분 상한은 유지" 문구가 호출부 조건과 무관하게 고정돼 있어, 배분
                  상한 풀로 못 찾아 배분 없는 풀로 다시 지은 호출까지 "유지"라고
                  말하는 자기모순이 있었다(205건 실측 — 응답 하나 안에서 서로 다른
                  말을 하면 §화면 정직성 위반). 기본값 True는 기존 호출부
                  (`api/expert.py`)의 겉보기 문구를 그대로 둔다 — 그 파일은 담당 밖이라
                  이 값을 넘기지 않는다.
    """
    if meta is not None:
        meta["exhausted"] = False   # 기본값 — 슬롯이 비어 DFS를 아예 안 부르는 경우 등
    slots = active_slots if active_slots is not None else SLOTS
    slot_pools = {}
    for s in slots:
        cands = [p for p in pool if p["part_type"] in SLOT_TYPES[s]]
        if not cands:
            return None
        slot_pools[s] = _tier_sort(cands, tier, cap is not None)
    # 고성능도 총액 상한을 받는다(슬라이스 58). 상한 없이 가격 내림차순으로 두면
    # 120만원 예산에 램 931만원 + 데이터센터 SSD 492만원을 얹은 1,741만원이 나온다 —
    # GPU는 그대로 RTX 4060인 채로. "가장 비싼 것"은 "용도에 필요한 최고 성능"이 아니다.
    limit = cap if cap is not None else None
    if limit is not None and tier == "highend":
        limit = int(limit * HIGHEND_CAP_X)
    if limit_override is not None:
        limit = limit_override
    # order는 slot_pools를 정렬한 것과 같은 판단이어야 한다(_order_of가 단일 원천) —
    # 위 _tier_sort 호출도 같은 (tier, cap is not None)을 썼다.
    chosen, exhausted = _dfs(slot_pools, limit, rules, slots, order=_order_of(tier, cap is not None))
    if meta is not None:
        meta["exhausted"] = exhausted
    if chosen is None:
        return None
    total = sum(p["sale_price"] for p in chosen.values())
    verdict = "none" if cap is None else ("within" if total <= cap else "over")
    # 「최고 사양」은 가성비의 옛 「최저가」와 정확히 대칭인 과장이었다(2026-08-24 정정) —
    # 같은 `_dfs`가 여기서도 "사전식 첫 성립 구성"을 반환할 뿐, 전체 조합을 나열해
    # 비교하지 않는다(§_dfs 결함 기록 「가성비는 최저가를 보장하지 않는다」와 같은 구조).
    # 방향은 `_order_of`(정렬 판단의 단일 원천 — `_tier_sort`·`_dfs`와 같은 판단)로
    # 정한다 — 추천은 숫자 예산이 없으면 내림차순이 아니라 중간가 우선이라
    # (`_order_of` 참조), 문구를 "내림차순"으로 고정하면 그 경로에서 다시 거짓말이 된다.
    order_ko = {"asc": "오름차순", "desc": "내림차순",
                "median": "중간가 우선"}[_order_of(tier, cap is not None)]
    # 고성능형의 "배분 상한은 유지"는 조건과 무관하게 단정할 수 없다 — 배분 상한 풀
    # (hi_pool)로 못 찾아 배분 없는 common으로 다시 지은 호출은 alloc_capped=False로
    # 온다(호출부가 넘긴다). 그런 호출에도 "유지"라 고정해 말하면, 폴백 시 relax_note로
    # 붙는 "…풀었습니다" 문구와 한 응답 안에서 서로 다른 말을 하게 된다(실사고 —
    # 205건, 14.2%).
    alloc_txt = "부품별 배분 상한은 유지" if alloc_capped else "부품별 배분 상한으로는 조합이 없어 해제"
    reasons = {
        "value": ["조건 통과 부품에서 가격 오름차순 첫 성립 조합", "조립 불가 조합은 탐색에서 제외"],
        "recommend": [f"조건 통과 부품에서 가격 {order_ko} 첫 성립 조합",
                      "성능 지표 미보유 — 가격을 사양 근사로 사용(정직 표기)"],
        "highend": [f"예산의 {HIGHEND_CAP_X:g}배까지 허용한 가격 {order_ko} 첫 성립 조합"
                    f"({alloc_txt} — 초과분은 아래에 정직 표기)"],
    }[tier]
    reasons = reasons + [n for n in (floor_note, relax_note, reuse_note) if n]
    # market_price 배선(A-100 · 공유 계약 ②) — 몰 최저가 비교 재료.
    # ⚠ 실측(2026-08-23, 이 물결 조사): `products.market_price`는 컬럼 자체는 NULL이
    # 거의 없지만(재고 후보 3,059건 중 NULL 1건) **값이 있는 행도 거의 전부 0**이다
    # (GPU 246/246 = 0, MB·SSD·CASE·POWER·GPU·HDD·쿨러 전 part_type = 0, 전체에서
    # 양수 값은 CPU 1건·RAM 1건 «둘»뿐). PC 부품 시장가가 0원일 수 없으므로 이건
    # "채워진 값"이 아니라 "아직 못 채운 값이 0으로 저장된 것"이다 — 그대로 내보내면
    # "시장가 0원(최저가)"이라는 지어낸 사실이 된다(§화면 정직성 「0으로 지어내지
    # 마라」의 정확한 위반 사례). 그래서 **엔진 경계에서 0 이하를 null로 정규화**한다
    # (DB 컬럼 자체를 고치는 것은 이 파일의 소관이 아니다 — 적재 로직 소관).
    def _mp(p):
        v = p.get("market_price")
        return v if (v is not None and v > 0) else None
    # market_pairs: SLOTS를 «한 번만» 순회해 (시세, 우리가격)을 함께 모은다.
    # market_total·market_compare_total을 따로 계산하면 언젠가 갈라진다(§단일 원천).
    # market_compare_total(신규, 2026-08-23) — market_total과 반드시 «같은 부품
    # 집합»의 우리 가격 합. 근거(2026-08-23 하네스 실측): 추천형(게임·150만원)에서
    # GPU 하나만 market_price가 없어, 화면이 "우리 총액(부품 8개 전부) vs
    # market_total(시세 있는 7개만)"을 비교하고 있었다 — 579,190원 "더 비싸 보였다."
    # 같은 7개끼리 비교하면 실제로는 5,910원 "더 쌌다"(§화면 정직성 위반 — 시세
    # 없는 부품 하나가 통째로 우리 쪽에만 더해져 실제보다 훨씬 비싸 보이는 방향으로
    # 틀렸다). market_total이 null이면 market_compare_total도 null.
    market_pairs = [(_mp(chosen[s]), chosen[s]["sale_price"]) for s in slots]
    market_vals = [mp for mp, _ in market_pairs]
    market_present = [mp for mp, _ in market_pairs if mp is not None]
    compare_present = [sp for mp, sp in market_pairs if mp is not None]
    return {
        "label": TIER_LABELS[tier],
        "items": [{"part_type": s, "product_code": chosen[s]["product_code"],
                   "sku": chosen[s]["sku"], "name": display_name(chosen[s]["product_name"]),
                   "price": chosen[s]["sale_price"], "maker": chosen[s].get("maker"),
                   "market_price": _mp(chosen[s]),
                   "spec": _explain_spec(chosen[s]), "tags": _pref_tags(chosen[s])}
                  for s in slots],
        "total": total,
        "compat": build_compat(chosen, rules, unknown_rules or ()),
        "budget": {"cap": cap, "verdict": verdict,
                   "over_by": max(0, total - cap) if cap is not None else 0},
        "totals": {"market_total": sum(market_present) if market_present else None,
                   "market_compare_total": sum(compare_present) if market_present else None,
                   "market_missing": len(market_vals) - len(market_present)},
        # 「부품」 핀이 없으면 빈 배열 — 화면이 매번 undefined 가드를 안 짜도 되게
        # 항상 이 키를 둔다. 핀이 있으면 `_attach_pin()`이 덮어쓴다.
        "pinned": [],
        # 재사용을 고른 슬롯 — 「이 자리는 쓰시던 부품을 그대로 쓰고, 이 견적에는 안
        # 들어 있다」는 사실을 화면이 말할 수 있게(customer-audit-2026-08-24 §1-1,
        # 공유 계약 ②). SLOTS 기준으로 slots(active)에 없는 자리를 역산한다 — 재사용
        # 여부를 또 다른 곳에서 재판정하지 않는다(§단일 원천, active_slots가 이미 정답).
        "reused": [{"slot": s, "label": SLOT_KO.get(s, s),
                    "note": "쓰시던 부품을 사용합니다 - 이 견적에 포함되지 않았습니다"}
                   for s in SLOTS if s not in slots],
        "reasons": reasons,
    }


# ---- 슬라이스 59: 첫 화면이 말하는 수를 서버가 책임진다 ----
# main-landing과 S0은 "실시간 재고 검증"·"검증 통과 견적"이라고 써 붙이고 **API를 한 번도
# 부르지 않았다.** 재고 26,480개(어느 실제 값과도 다름) · 호환성 5종(실제 8종) ·
# RTX 4060 Ti 645,000원(실제 428,000원)을 고객이 처음 보는 화면에서 말하고 있었다.
#
# 견적 API를 그대로 쓰지 않는 이유: 그건 consult_sessions·quote_snapshots를 남긴다.
# 랜딩 방문마다 상담 세션이 쌓이면 원장이 오염된다. 여기서는 **읽기만** 한다.
SHOWCASE = {"usage": "게임", "budget": "150만원"}   # 대표 조건 — 화면이 이 조건을 밝힌다
_SHOW_CACHE: dict = {"at": 0.0, "data": None}
SHOWCASE_TTL = 300.0                                # 5분 — 재고가 움직여도 그 안에 따라온다


SHOWCASE_SCAN = 40      # 훑어볼 최근 견적 수 — 이 안에서 지금도 살 수 있는 것만 고른다
# part_type -> 슬롯명 역매핑(SLOT_TYPES의 역). 쿨러만 두 종류가 한 슬롯이다.
_SLOT_OF = {t: s for s, ts in SLOT_TYPES.items() for t in ts}


def _slot_of(part_type: str) -> str:
    return _SLOT_OF.get(part_type, part_type)


def _recent_pick(conn):
    """실제로 만들어진 최근 견적 중 **지금도 유효한 것**을 고른다(슬라이스 60).

    고정 조건으로 매번 같은 구성을 만들면 첫 화면이 죽어 있다. 실제 견적을 보여주면
    새 상담이 생길 때마다 바뀐다 — 그게 '실시간 재고 기반'이라는 말에 맞다.

    다만 **과거 견적을 그대로 내걸 수는 없다**: 그때는 있던 부품이 지금 품절일 수 있고,
    가격도 움직인다. '검증 통과 견적'이라고 말하려면 지금 이 순간 살 수 있어야 한다.
    그래서 ① 전 부품이 현재도 추천 후보이며 재고가 있는 것만 통과시키고
    ② 금액은 **스냅샷이 아니라 현재 가격**으로 다시 합산한다.

    회원·세션 식별자는 읽지 않는다 — 남의 상담 기록이 아니라 구성만 보여준다.
    """
    rows = conn.execute(text(
        "SELECT snapshot_id, items, created_at FROM quote_snapshots"
        " WHERE quote_type = 'recommend' ORDER BY snapshot_id DESC LIMIT :n"),
        {"n": SHOWCASE_SCAN}).mappings().all()
    if not rows:
        return None

    codes = {p.get("product_code") for r in rows
             for p in ((r["items"] or {}).get("parts") or []) if p.get("product_code")}
    if not codes:
        return None
    live = {r["product_code"]: r for r in conn.execute(text(
        "SELECT product_code, product_name, sale_price, part_type"
        " FROM v_recommendation_candidates WHERE stock_qty > 0"
        "   AND product_code = ANY(:c)"), {"c": list(codes)}).mappings().all()}

    ok = []
    for r in rows:
        parts = (r["items"] or {}).get("parts") or []
        if len(parts) != len(SLOTS):
            continue
        cur = [live.get(p.get("product_code")) for p in parts]
        if any(c is None for c in cur):      # 하나라도 품절·후보 이탈이면 못 보여준다
            continue
        # part_type을 **슬롯명으로 되돌린다** — 뷰는 COOLER_CPU_AIR/AIO로 나누지만
        # 견적 API가 주는 이름은 COOLER다. 화면은 견적 응답 기준으로 만들어져 있어서
        # 그대로 내보내면 'COOLER_CPU_AIR'이 고객 화면에 그대로 찍힌다.
        ok.append({
            "items": [{"part_type": _slot_of(c["part_type"]), "product_code": c["product_code"],
                       "name": display_name(c["product_name"]), "price": c["sale_price"]} for c in cur],
            "total": sum(c["sale_price"] for c in cur),
            "at": iso(r["created_at"]) if r["created_at"] else None,
        })
    if not ok:
        return None
    # 캐시가 갱신될 때마다 다음 것으로 넘어간다 — 상담이 뜸해도 첫 화면은 계속 움직인다
    _SHOW_CACHE["turn"] = (_SHOW_CACHE.get("turn", 0) + 1) % len(ok)
    return ok[_SHOW_CACHE["turn"]] | {"live_count": len(ok)}


@router.get("/showcase")
def showcase():
    """첫 화면용 대표 구성 — 세션을 만들지 않는 읽기 전용 경로."""
    import time

    now = time.time()
    if _SHOW_CACHE["data"] is not None and now - _SHOW_CACHE["at"] < SHOWCASE_TTL:
        return _SHOW_CACHE["data"] | {"cached": True}

    cap = _budget_cap(SHOWCASE["budget"])
    with engine.begin() as conn:
        pool = _load_pool(conn)
        rules = load_compat_rules(conn)
        pick, source = _recent_pick(conn), "recent"
        if pick is None:
            # 아직 견적이 없거나 전부 품절됐다 — 지금 재고로 하나 만들어 보여준다
            common = pool
            common, _, _ = _apply_one(common, "용도", SHOWCASE["usage"])
            capped, _, _ = _apply_one(common, "예산", SHOWCASE["budget"])
            built = _build_set("recommend", capped, cap, rules)
            if built is None:               # 배분율이 막으면 푼다(견적 경로와 같은 규칙)
                built = _build_set("recommend", common, cap, rules)
            pick = built and {"items": built["items"], "total": built["total"], "at": None}
            source = "built"

    data = {
        # S1 후보 카운터와 **같은 정의**다 — S0에서 다른 수를 보여주면 다음 화면에서
        # 갑자기 줄어든 것처럼 보인다.
        "pool": len(pool),
        # `rules` = 등록 규칙 수(운영자용) · `rules_applied` = 한 구성에 실제 걸리는 수.
        # **화면이 '통과'와 함께 말하는 숫자는 rules_applied 다** — 배타 규칙 때문에
        # 어떤 구성도 등록 수 전부를 통과하지 않는다(위 applied_rule_count 주석).
        "rules": sum(len(v) for v in rules.values()),
        "rules_applied": applied_rule_count(rules),
        "usage": SHOWCASE["usage"], "budget_label": SHOWCASE["budget"],
        "source": source,                   # recent = 실제 견적 · built = 지금 만든 것
        "pick": pick,
        "cached": False,
    }
    _SHOW_CACHE.update({"at": now, "data": data})
    return data


def _companion(conn):
    rows = conn.execute(text(
        "SELECT product_code, sku, product_name, part_type, sale_price, stock_qty,"
        " size_inch, resolution, refresh_hz, panel, switch_type, connection"
        " FROM v_companion_candidates WHERE stock_qty > 0 ORDER BY product_code")).mappings().all()
    labels = {"MONITOR": "모니터", "KEYBOARD": "키보드", "MOUSE": "마우스",
              "HEADSET": "헤드셋", "SPEAKER": "스피커", "WEBCAM": "웹캠"}
    out, seen = [], set()
    for r in rows:
        if r["part_type"] in seen:
            continue
        seen.add(r["part_type"])
        if r["part_type"] == "MONITOR":
            # 사양이 부분만 채워진 모니터가 있다 — `:g` 포맷이 NULL을 만나 500이 났다
            # (슬라이스 52: 검수 승인으로 일부 필드가 채워지자 드러났다).
            # 없는 값은 지어내지 않고 그 자리를 비운다.
            parts = []
            if r["size_inch"] is not None:
                parts.append(f"{r['size_inch']:g}형")
            for k, suf in (("resolution", ""), ("refresh_hz", "Hz"), ("panel", "")):
                if r[k] is not None:
                    parts.append(f"{r[k]}{suf}")
            spec = " ".join(parts)
        elif r["part_type"] == "KEYBOARD":
            spec = f"{r['switch_type'] or ''} {r['connection'] or ''}".strip()
        else:
            spec = r["connection"] or ""
        out.append({"part_type": r["part_type"], "label": labels.get(r["part_type"], r["part_type"]),
                    "product_code": r["product_code"], "sku": r["sku"], "name": display_name(r["product_name"]),
                    "price": r["sale_price"], "stock": r["stock_qty"], "spec": spec})
    order = ["MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM"]
    return sorted(out, key=lambda c: order.index(c["part_type"]))


# ============================================================================
# 회귀 트래픽 표시 — consult_sessions.data_origin 분기 (2026-08-20 사장님 확정)
# ============================================================================
# ■ 무엇을 막나
#   tests/regression.py 는 BASE=localhost:8000(로컬 API)을 두드리는데, 로컬 API는
#   배포 서버와 **같은 Cloud SQL**을 본다(`.env`의 DATABASE_URL 공유). 그래서 회귀를
#   돌릴 때마다 아래 세션 INSERT가 실제 상담 원장에 쌓였다 — 조사자 실측:
#   consult_sessions 6,893건 중 6,732건(97.7%)이 회귀가 만든 행이었다.
#
# ■ 헤더 이름 — "X-Popcorn-Test"
#   이 저장소의 커스텀 헤더 선례는 `access_gate.HEADER`("X-Access-Key") 하나뿐이고
#   `X-` 접두어만 관례다. "Popcorn"을 더 붙인 이유는 이게 우리 앱 전용 자기 신고
#   표식임을 분명히 하기 위해서다 — 표준 헤더나 nginx/프록시가 붙이는 헤더와 이름이
#   겹칠 일이 없다. 값은 내용이 아니라 존재 자체가 신호라 "1"이면 충분하다.
#
# ■ 왜 헤더를 그대로 믿지 않는가 — 자기 신고라 아무나 실을 수 있다
#   그대로 믿으면 외부에서 이 헤더를 실어 **실고객 세션을 'test'로 감출 수 있다**
#   (지금 겪는 오염과 반대 방향의 오염). 그래서 `UI_CHECK_DEV_LOGIN`
#   (`api/auth.py` `dev_login` · CLAUDE.md §브라우저 점검 계정)과 같은 이중 게이트를
#   그대로 따른다:
#     ① `.env`의 `POPCORN_TEST_HEADER_ENABLED=1` (기본 꺼짐)
#     ② **localhost 요청만** — 판정은 `api/auth.py`의 기존 관례를 그대로 따른다:
#        `request.client.host`를 직접 신뢰한다(`_client_ip`, api/auth.py:227-254 —
#        운영 배포는 uvicorn ProxyHeadersMiddleware가 nginx 뒤에서 이미 실제
#        클라이언트 IP로 바꿔 두므로, 인터넷의 실고객 요청은 여기서 "localhost"로
#        보일 수 없다). 새 판정 로직을 만들지 않고 `LOCAL_HOSTS`(위 import)를
#        그대로 가져다 쓴다.
#   ①을 추가로 요구하는 이유: ②만으로는 "운영 박스 안에서 loopback으로 이 API를
#   두드리는 내부 프로세스"(헬스체크·크론 등)까지는 못 막는다. 스위치를 기본
#   꺼짐으로 두고 **운영 서버 `.env`에는 아예 넣지 않으면**(배포 절차
#   `deploy/README.md`) 그 경로 자체가 운영에서 항상 닫힌다 — `UI_CHECK_DEV_LOGIN`과
#   같은 방어선이다. 이 값은 로컬 개발 `.env`에만 켠다.
#
# ■ data_origin 값 = 'test' — products 축의 'demo'와 다른 뜻
#   컬럼은 이미 있다(마이그레이션 0033_demo_data_axis · consult_sessions.data_origin
#   VARCHAR(10) NOT NULL DEFAULT 'real'). `'demo'`는 products·orders·members·
#   csv_import_jobs가 쓰는 "시연용 가짜 상품/주문" 축이고, 이건 "테스트 스위트가
#   만든 상담"이라 뜻이 다르다 — 같은 값을 쓰면 나중에 "이 데모 세션이 회귀가 만든
#   것인지 실제 시연인지" 구분할 길이 없어진다. 0033 자신의 존재 이유가 "무엇을
#   비울지 구분 못 하면 못 비운다"였다 — 그 원칙을 그대로 지킨다.
TEST_HEADER = "X-Popcorn-Test"


def _test_header_enabled() -> bool:
    return os.environ.get("POPCORN_TEST_HEADER_ENABLED", "").strip() in ("1", "true", "True", "yes")


def _resolve_data_origin(request: Request) -> str:
    """이 요청이 회귀 표식을 달고, 그 표식을 신뢰할 수 있는 경로로 왔으면 'test'.

    `api/expert.py`도 이 함수를 그대로 가져다 쓴다 — 이 파일의 언더스코어 함수를
    다른 모듈이 import하는 것은 이 저장소의 기존 관례다(`swap.py`가 이 파일의
    `_build_set` 등을 그대로 쓰는 것과 같다. api/expert.py 상단 주석 참조).
    """
    if not _test_header_enabled():
        return "real"
    if not (request.headers.get(TEST_HEADER) or "").strip():
        return "real"
    host = (request.client.host if request.client else "") or ""
    if host not in LOCAL_HOSTS:
        return "real"
    return "test"


@router.post("/recommend")
def recommend(body: RecommendBody, request: Request, response: Response):
    # 방문자 키 — 이 상담을 나중에 클릭·교체·주문과 잇는 실이다(슬라이스 2026-08-09).
    # 발급이 실패하면 None 이고 상담은 그대로 진행된다.
    if body.mode not in ("guided", "chat", "expert", "talk"):
        raise HTTPException(400, f"알 수 없는 모드: {body.mode}")
    labels = {c.l for c in body.constraints}
    missing = []
    if "용도" not in labels and "상황" not in labels:
        missing.append("용도 또는 상황")
    if "예산" not in labels:
        missing.append("예산")
    if missing:  # U-08 확정(2026-07-23): (용도 또는 상황) + 예산
        raise HTTPException(400, {"error": "constraints_insufficient", "missing": missing})

    budget_v = next((c.v for c in body.constraints if c.l == "예산"), "")
    cap = _budget_cap(budget_v)

    with engine.begin() as conn:
        pool = _load_pool(conn)
        total_n = len(pool)

        # ── 재사용 슬롯(2026-08-24 · customer-audit-2026-08-24 §1-1 · 공유 계약 ①②) ──
        # 화면이 {"l":"재사용","v":"GPU"} 형태로 보낸다. 어휘·「필터가 아니라 제외」라는
        # 판정은 candidates.REUSE_LABELS 처분표 하나뿐이다(여기서 다시 정의하지 않는다,
        # CANON §1) — 이 함수가 새로 하는 일은 "그 슬롯을 DFS가 아예 안 채운다"뿐이다.
        # 값은 SLOTS(8종)만 받는다 — HDD는 견적 슬롯이 아니라 애초에 채울 자리가 없다.
        reuse_slots = {c.v for c in body.constraints if c.l in REUSE_LABELS and c.v in SLOTS}
        active_slots = [s for s in SLOTS if s not in reuse_slots]   # SLOTS 순서를 보존한 부분집합

        # ── 「부품」 핀 정책(A-101 · 공유 계약 ①②) — 지금은 GPU만 다룬다 ──────────
        # candidates.PART_PIN_LABELS 분기(아래 common/capped/hi_pool 구성 루프가 그대로
        # 통과시킨다)가 재고에 있으면 GPU 슬롯 후보를 이 값으로 이미 좁힌다 — 그래서
        # common/capped/hi_pool은 **이미 핀이 적용된 풀**이다. 여기서 따로 재는 것은
        # **핀이 실패했을 때 무엇을 말할지**뿐이다: 재고 자체에 없는지, 아니면 있지만
        # 이 티어 상한을 못 넘는지를 구분해야 화면이 정직하게 사유를 댈 수 있다.
        part_v = next((c.v for c in body.constraints if c.l == "부품"), None)
        # ⚠ 설계 판단 — GPU를 재사용으로 고르면 「부품」 핀은 무시한다. "이 슬롯은 손대지
        # 말라"(재사용)와 "이 모델을 사라"(핀)는 같은 슬롯에 동시에 성립할 수 없는
        # 모순이고, 재사용 쪽이 더 구체적인 신호(값이 아니라 슬롯 자체를 지정)라고 본다.
        # 무시하지 않으면 GPU가 active_slots에서 빠져 아래 GPU_I 색인이 다른 슬롯의
        # item을 가리키게 된다(_attach_pin이 엉뚱한 부품에 "지정 부품 반영"이라고 쓰는
        # 사고) — 그 사고를 피하는 방편이 아니라, 모순을 조용히 삼키지 않고 이유를 말로
        # 남기는 쪽을 택한 것이다(아래 reuse_note에 합쳐 reasons로 나간다).
        pin_conflict_note = None
        if part_v and "GPU" in reuse_slots:
            pin_conflict_note = "그래픽카드를 재사용하기로 하셔서 지정하신 부품 요청은 반영하지 않았습니다"
            part_v = None
        gpu_matches = []
        if part_v:
            gpu_matches = [p for p in pool if p["part_type"] == "GPU"
                           and gpu_chipset_key(p.get("product_name") or "") == part_v]
        gpu_min_price = min((p["sale_price"] for p in gpu_matches), default=None)
        # SLOTS.index가 아니라 active_slots.index다 — items는 이제 active_slots 기준으로
        # 만들어진다. CPU·MB·RAM 중 하나라도 재사용이면 GPU의 SLOTS상 위치(3)와 items
        # 안에서의 실제 위치가 달라진다(앞쪽 슬롯이 빠지면 뒤 인덱스가 당겨진다) — 옛
        # SLOTS.index를 그대로 썼다면 GPU가 아닌 다른 슬롯의 item에 핀을 붙이는 색인
        # 사고가 났을 자리다. part_v가 살아있으면(위에서 GPU 재사용 시 이미 None 처리했다)
        # "GPU"는 반드시 active_slots에 있다.
        GPU_I = active_slots.index("GPU") if "GPU" in active_slots else None

        def _attach_pin(built, honored, cap_display):
            """built(성공한 구성)에 pinned·reasons를 덧붙인다 — part_v가 없으면 아무 것도 안 한다."""
            if not part_v or built is None:
                return
            gi = built["items"][GPU_I]
            if honored:
                note = f"지정 부품 반영: {gi['name']} {gi['price']:,}원"
            elif not gpu_matches:
                note = f"재고에 없는 부품: {part_v}"
            else:
                cap_txt = f"{cap_display:,}원" if cap_display is not None else "상한 없음"
                note = f"지정 부품 최저가 {gpu_min_price:,}원 · 이 티어 상한 {cap_txt}"
            built["pinned"] = [{"slot": "GPU", "requested": part_v, "chosen": gi["name"],
                                 "honored": honored, "note": note}]
            built["reasons"] = built["reasons"] + [note]

        # funnel.passed = v0 count와 동일 규칙(전 제약 순차 적용) — S1 카운터와 일치
        passed = pool
        for c in body.constraints:
            passed, _, _ = _apply_one(passed, c.l, c.v)

        # 3티어 공통 = 태그만 적용(예산 제외), 캡 풀 = 예산까지 적용
        # ⚠ 이 루프는 「부품」도 포함해 적용한다 — PART_PIN_LABELS가 재고에 있으면 GPU
        # 슬롯을 지정 칩셋으로 좁힌다. 그래서 common/capped는 **이미 핀이 걸린 풀**이다.
        # 핀이 실패했을 때 되돌아갈 곳이 필요해 「부품」만 뺀 `*_full` 풀을 따로 만든다 —
        # 재고에 없으면(gpu_matches==[]) PART_PIN_LABELS 자신이 거르지 않으므로
        # 두 풀은 자동으로 같아진다(추가 분기 없이 이 사실 하나로 c 케이스가 정리된다).
        common = pool
        for c in body.constraints:
            if c.l != "예산":
                common, _, _ = _apply_one(common, c.l, c.v)
        capped = common
        if cap is not None:
            capped, _, _ = _apply_one(capped, "예산", budget_v)

        common_full = pool
        for c in body.constraints:
            if c.l not in ("예산", "부품"):
                common_full, _, _ = _apply_one(common_full, c.l, c.v)
        capped_full = common_full
        if cap is not None:
            capped_full, _, _ = _apply_one(capped_full, "예산", budget_v)

        # 용도 하한(슬라이스 58) — 서버가 실제로 건 하한만 근거로 말한다.
        # GPU는 성능 지표가 없어 권장 전원을 계층 근사로 쓴다. 그 사실을 숨기지 않는다.
        usage_v = next((c.v for c in body.constraints if c.l in ("용도", "상황")), "")
        floors = UF.summary(usage_v)
        # ⚠ 설계 판단 — 재사용 슬롯의 하한은 "확인했다"고 말하지 않는다(customer-audit
        # -2026-08-24 「전력 합계·용도 하한도 같은 문제다」). 그 슬롯은 애초에 고르지
        # 않으니 비교할 값 자체가 없다 — floors(응답 usage_floors.items, 이 용도에
        # 정의된 하한 목록)는 그대로 두고("정의돼 있다"는 사실 자체는 참이다),
        # floor_note(근거 문구, "실제로 걸렀다"는 주장)만 확인 가능한 것과 확인
        # 불가능한 것을 가른다 — 확인 못 한 걸 확인했다고 말하지 않는다.
        floor_note = None
        floors_checked = [f for f in floors if f["slot"] not in reuse_slots]
        floors_unchecked = [f for f in floors if f["slot"] in reuse_slots]
        if floors_checked:
            # 근거에는 **숫자가 있어야 한다**. "고사양 게임 GPU 등급"만으로는 무엇을 걸렀는지
            # 알 수 없다 — 얼마 이상인지가 근거다.
            unit = {"required_power_watt": "W", "capacity_gb": "GB"}
            said = " · ".join(f"{SLOT_KO.get(f['slot'], f['slot'])} "
                              f"{f['value']:,}{unit.get(f['field'], '')} 이상" for f in floors_checked)
            floor_note = (f"{UF.label_of(usage_v)} 하한 — {said}."
                          " GPU는 성능 지표가 없어 권장 전원을 등급 근사로 사용합니다")
        if floors_unchecked:
            skip = " · ".join(SLOT_KO.get(f["slot"], f["slot"]) for f in floors_unchecked)
            skip_note = f"{skip} 하한은 재사용 부품이라 확인하지 못했습니다"
            # floor_note가 이미 있으면 마침표로 문장을 끊는다 — 안 그러면 "…사용합니다
            # 그래픽카드 하한은…"처럼 두 문장이 붙어 읽힌다(실측으로 발견, TestClient
            # 검증 중 reasons[] 출력에서 잡았다).
            floor_note = f"{floor_note}. {skip_note}" if floor_note else skip_note

        # 고성능 풀 = 예산 배분율을 HIGHEND_CAP_X배로 늘려 적용(전면 해제가 아니다).
        # `common`(배분 미적용)을 그대로 주면 램 931만원이 다시 들어온다.
        hi_pool = common
        hi_pool_full = common_full
        if cap is not None:
            hi_cap = int(cap * HIGHEND_CAP_X)
            hi_pool = [p for p in common
                       if p["sale_price"] <= int(hi_cap * BUDGET_ALLOC.get(p["part_type"], 1.0))]
            hi_pool_full = [p for p in common_full
                            if p["sale_price"] <= int(hi_cap * BUDGET_ALLOC.get(p["part_type"], 1.0))]

        rules = load_compat_rules(conn)   # 요청당 1회 로드 — 규칙 변경이 즉시 반영된다
        check_rule_fields(pool, rules)    # 규칙 필드 누락은 조용한 전면 불통과 → 경고로 드러낸다
        # 재사용 슬롯이 낀 규칙은 DFS에서 아예 뺀다(rules_active) — chosen에 그 슬롯이
        # 없어 규칙이 참조하면 KeyError가 난다. 뺀 규칙은 화면에서 사라지지 않고
        # build_compat이 unknown으로 올린다(rules_unknown). 판정 규약은
        # `_rules_for_active` 정본 하나다.
        rules_active, rules_unknown = _rules_for_active(rules, reuse_slots)
        # 재사용 안내 — SLOTS 순서로 고정해 매 요청 같은 문구가 나오게 한다(순서가
        # constraints 입력 순서를 타면 같은 조건인데 다른 문장이 나올 수 있다).
        reuse_note = None
        if reuse_slots:
            names = " · ".join(SLOT_KO.get(s, s) for s in SLOTS if s in reuse_slots)
            reuse_note = (f"{names} — 쓰시던 부품을 재사용합니다(새로 사지 않음). "
                          "그 부품이 관련된 호환성·전력 적합성은 확인할 수 없습니다")
        if pin_conflict_note:
            # 마침표로 문장을 끊는다 — floor_note 이어붙이기와 같은 이유(위 참조),
            # 같은 함정을 여기서도 반복하지 않는다.
            reuse_note = f"{reuse_note}. {pin_conflict_note}" if reuse_note else pin_conflict_note
        # 가성비형은 **부품별 배분율을 받지 않는다**(슬라이스 58). 가격 오름차순으로 훑는
        # 티어에 "비싼 부품 차단" 상한은 무의미한데, 슬롯 후보를 예산마다 다르게 만들어
        # 150만원이 70만원보다 비싼 가성비 구성을 내놓았다(회귀 '가성비는 전 예산 공통' 실패).
        # 진짜 제약은 총액이고 그건 DFS 가지치기가 건다.
        # 탐색 소진 여부(2026-08-24 추가) — 티어별로 하나씩, 그 티어의 마지막(=sets에
        # 실제로 남는) _build_set 호출이 덮어쓴다. "슬롯이 비었다"·"애초에 안 돌렸다"는
        # False(소진 아님)로 남는다 — DFS_NODE_CAP에 닿은 경우만 True다(_build_set의
        # meta 계약 참조). 아래 `search_exhausted` 응답 필드가 이 값을 그대로 낸다.
        meta_v, meta_r, meta_h = {}, {}, {}

        # ── 가성비형 ──────────────────────────────────────────────────────────
        built_v = _build_set("value", common, cap, rules_active, floor_note,
                             active_slots=active_slots, unknown_rules=rules_unknown,
                             reuse_note=reuse_note, meta=meta_v)
        honored_v = None
        if part_v:
            if gpu_matches and built_v is None:
                # 핀 풀(common)로는 성립하지 않는다 — 「부품」을 뺀 풀로 다시 짓는다(핀 해제).
                built_v = _build_set("value", common_full, cap, rules_active, floor_note,
                                     active_slots=active_slots, unknown_rules=rules_unknown,
                                     reuse_note=reuse_note, meta=meta_v)
                honored_v = False
            else:
                honored_v = bool(gpu_matches)   # 재고에 아예 없으면 애초에 핀이 안 걸린 것
        sets = {"value": built_v}
        _attach_pin(sets["value"], honored_v, cap)

        # 배분율은 "한 부품에 몰빵하지 마라"는 균형 장치일 뿐 조립 조건이 아니다.
        # 저예산에서는 그것이 슬롯을 전멸시켜 견적을 못 만든다 — 실측: 50만원 사무용에서
        # RAM 배분 10%(5만원)가 DDR4 램(최저 84,900원)을 전부 걸러 남은 DDR5 8GB 하나가
        # 남은 DDR4 보드와 맞지 않았다. **균형을 못 지킬 바엔 균형을 포기하고 견적을 낸다** —
        # 총액 상한은 그대로 지킨다. 포기했으면 근거에 그렇게 적는다(정직).
        relaxed = "부품별 배분 상한으로는 조합이 없어 균형 제약을 풀었습니다(총액 상한은 유지)"

        def _build_highend(hi_note, hi_limit):
            """고성능형 한 번 짓기 — 가성비 성립/실패 두 경로가 공유한다(2026-08-24
            결함 수정). 고성능 상한(cap × HIGHEND_CAP_X)은 가성비·추천의 상한(cap)보다
            «더 넓다» — 「총액 ≤ cap인 조합이 없다」가 「총액 ≤ cap×1.5인 조합이 없다」를
            함의하지 않는다(조사자 실측 — 가성비 실패 264건 중 162건(61.4%)에서 고성능형이
            실제로 성립, 11개 용도 전부에서 발생). 옛 코드는 가성비가 None이면 이 시도
            자체를 안 했다 — 그래서 고성능으로도 지을 수 있던 견적이 "견적 불가"로 나갔다.
            hi_pool(배분 상한 적용) 실패 시 common(배분 해제)으로 푸는 순서·부품 핀 처리는
            기존 고성능형 로직을 그대로 옮겼을 뿐이다(§단일 원천 — 새 판정을 만들지 않는다).
            """
            hi_cap_display = hi_limit if hi_limit is not None else (
                int(cap * HIGHEND_CAP_X) if cap is not None else None)
            # alloc_capped는 "이 풀에 실제로 배분 상한이 걸렸는가"를 그대로 말한다 —
            # cap이 None이면 hi_pool 계산 자체가 배분 필터를 건너뛰어(위 hi_pool 정의
            # 참조) hi_pool이 common과 같아진다. 그런데도 True로 고정하면 "배분 상한은
            # 유지"라고 말하는 게 다시 지어낸 사실이 된다 — cap 유무로 그대로 판정한다.
            hi_alloc = cap is not None
            built = _build_set("highend", hi_pool, cap, rules_active, floor_note, hi_note, hi_limit,
                               active_slots=active_slots, unknown_rules=rules_unknown,
                               reuse_note=reuse_note, meta=meta_h, alloc_capped=hi_alloc)
            if built is None:
                built = _build_set("highend", common, cap, rules_active, floor_note,
                                   hi_note or relaxed, hi_limit,
                                   active_slots=active_slots, unknown_rules=rules_unknown,
                                   reuse_note=reuse_note, meta=meta_h, alloc_capped=False)
            honored = None
            if part_v:
                if gpu_matches and built is None:
                    built = _build_set("highend", hi_pool_full, cap, rules_active, floor_note,
                                       hi_note, hi_limit, active_slots=active_slots,
                                       unknown_rules=rules_unknown, reuse_note=reuse_note,
                                       meta=meta_h, alloc_capped=hi_alloc)
                    if built is None:
                        built = _build_set("highend", common_full, cap, rules_active, floor_note,
                                           hi_note or relaxed, hi_limit, active_slots=active_slots,
                                           unknown_rules=rules_unknown, reuse_note=reuse_note,
                                           meta=meta_h, alloc_capped=False)
                    honored = False
                else:
                    honored = bool(gpu_matches)
            sets["highend"] = built
            _attach_pin(sets["highend"], honored, hi_cap_display)

        if sets["value"] is None:
            # 가성비 탐색이 예산 밖이면 추천형은 시도하지 않는다(그대로 둔다 — 정직 +
            # 낭비 방지) — 추천의 폴백 풀(common)이 가성비가 쓰는 풀과 완전히 같고
            # 상한(cap)도 같다. 가성비가 못 찾았으면 추천도 못 찾는다(조사자 실측 ·
            # 표본 3건 재확인 — 추천형은 건드리지 않는다).
            sets["recommend"] = None
            # 고성능형은 위 이유로 «따로» 시도한다(2026-08-24 결함 수정) — 상한이
            # 가성비보다 넓어 가성비 실패가 고성능 실패를 뜻하지 않는다. 예산이 있을
            # 때만 시도한다: 예산이 없으면(cap=None) 상한을 잡을 유일한 근거가 추천
            # 구성 총액인데 추천을 안 지었으니 기준이 없고, 그 경우 가성비 실패는
            # 예산이 아니라 구조(풀·규칙) 문제라 상한을 넓혀도 풀리지 않는다.
            if cap is not None:
                _build_highend(None, None)
            else:
                sets["highend"] = None
        else:
            # ── 추천형 ────────────────────────────────────────────────────────
            built_r = _build_set("recommend", capped, cap, rules_active, floor_note,
                                 active_slots=active_slots, unknown_rules=rules_unknown,
                                 reuse_note=reuse_note, meta=meta_r)
            if built_r is None:
                built_r = _build_set("recommend", common, cap, rules_active, floor_note, relaxed,
                                     active_slots=active_slots, unknown_rules=rules_unknown,
                                     reuse_note=reuse_note, meta=meta_r)
            honored_r = None
            if part_v:
                if gpu_matches and built_r is None:
                    built_r = _build_set("recommend", capped_full, cap, rules_active, floor_note,
                                         active_slots=active_slots, unknown_rules=rules_unknown,
                                         reuse_note=reuse_note, meta=meta_r)
                    if built_r is None:
                        built_r = _build_set("recommend", common_full, cap, rules_active, floor_note,
                                             relaxed, active_slots=active_slots,
                                             unknown_rules=rules_unknown, reuse_note=reuse_note,
                                             meta=meta_r)
                    honored_r = False
                else:
                    honored_r = bool(gpu_matches)
            sets["recommend"] = built_r
            _attach_pin(sets["recommend"], honored_r, cap)

            # 예산을 숫자로 말하지 않아도(‘200만원 이상’·‘AI 추천 예산’) 상한은 있어야 한다.
            # 없으면 고성능이 3,025만원이 된다 — 램 하나에 931만원을 쓰던 그 구성이
            # 예산 없는 경로로 그대로 돌아온다. 기준선은 **추천 구성**이다:
            # "예산을 안 정하셨으니 추천 구성의 1.5배까지 봅니다"가 말이 되는 유일한 기준이다.
            hi_note, hi_limit = None, None
            if cap is None and sets["recommend"]:
                hi_limit = int(sets["recommend"]["total"] * HIGHEND_CAP_X)
                hi_note = (f"예산 상한을 정하지 않으셔서 추천 구성"
                           f"({sets['recommend']['total']:,}원)의 {HIGHEND_CAP_X:g}배"
                           f"({hi_limit:,}원)까지로 잡았습니다")

            # ── 고성능형 ──────────────────────────────────────────────────────
            _build_highend(hi_note, hi_limit)

        uid = visitor.resolve(conn, request, response)
        # 이 견적의 「추측 못 할 열쇠」 — session_id 가 연속 정수라(최근 10건 5872~5881)
        # 번호만으로는 남의 견적을 막을 수 없다. 열쇠는 **이 응답을 받은 쪽에만** 간다.
        # 스키마(0055)가 아직 없으면 열쇠 없이 그대로 만든다 — 그 행은 나중에 설명을
        # 부를 수 없고(403), 게이트가 왜 못 서는지는 서버 로그가 말한다.
        gate_on = access_gate.column_ready(conn, "consult_sessions")
        access_key = access_gate.new_key() if gate_on else None
        params = {"m": body.mode, "u": uid,
                  "c": json.dumps([{"l": c.l, "v": c.v} for c in body.constraints]),
                  "do": _resolve_data_origin(request)}
        cols = "member_id, mode, constraints, user_id, data_origin"
        vals = "NULL, :m, CAST(:c AS JSONB), :u, :do"
        if gate_on:
            cols, vals = cols + ", access_key", vals + ", :ak"
            params["ak"] = access_key
        session_id = conn.execute(text(
            f"INSERT INTO consult_sessions ({cols}) VALUES ({vals}) RETURNING session_id"),
            params).scalar()
        comp = _companion(conn)
        for qt, s in sets.items():
            if s is None:
                continue
            conn.execute(text(
                "INSERT INTO quote_snapshots (session_id, quote_type, items, companion, total_amount)"
                " VALUES (:sid, :qt, CAST(:it AS JSONB), CAST(:co AS JSONB), :ta)"),
                {"sid": session_id, "qt": qt,
                 "it": json.dumps({"parts": s["items"], "compat": s["compat"], "reasons": s["reasons"]}),
                 "co": json.dumps({"offered": comp}),  # 제시본(offered) — 선택 스냅샷은 이후 단계
                 "ta": s["total"]})

    return {"session_id": session_id, "generated_at": now_iso(),
            # 이 견적의 열쇠. 화면은 이걸 들고 `POST /api/recommend/explain` 을 부른다.
            # null 이면 게이트 스키마 미적용 상태다 — 그 경우 explain 은 503 을 준다.
            "access_key": access_key,
            "funnel": {"total": total_n, "passed": len(passed)},
            # 서버가 실제로 건 하한 — 화면이 지어내지 않고 이것만 말한다
            "usage_floors": {"usage": UF.label_of(usage_v), "items": floors},
            "highend_cap_x": HIGHEND_CAP_X,
            # 재사용 슬롯 — 티어별 sets[tier].reused와 같은 정보를 요청 단위로도 낸다.
            # 전 티어가 None(불성립)이어도 "무엇을 재사용으로 골랐는지"는 화면이 알아야
            # 한다(customer-audit-2026-08-24 §1-1) — sets 안에 묻으면 실패 시 사라진다.
            "reused_slots": [{"slot": s, "label": SLOT_KO.get(s, s)}
                             for s in SLOTS if s in reuse_slots],
            # 「없다」와 「못 찾았다」는 다른 사실이다(2026-08-24 추가 — DFS_NODE_CAP
            # 결함 수정 계약). sets[tier]가 null인 이유가 둘 중 하나다:
            #   True   탐색이 노드 상한(DFS_NODE_CAP)에 닿아 «포기»했다 — 이 조건에
            #          맞는 구성이 있는지 없는지 **확인을 끝내지 못했다.**
            #   False  탐색이 끝까지 갔고 그 안에 맞는 구성이 없었다(또는 그 티어의
            #          모든 슬롯 후보가 이미 비어 있어 탐색조차 시작하지 않았다) —
            #          «없다»고 말할 수 있는 확정 판정이다.
            # sets[tier]가 실제 구성(dict)이면 그 탐색은 성립을 «찾은» 것이므로 항상
            # False다(_dfs가 성공과 상한 도달을 동시에 반환할 수 없다 — _dfs 참조).
            # 화면은 담당 밖이다 — 이 필드를 읽어 "지금은 답을 못 찾았습니다"처럼
            # "구성이 없습니다"와 다른 문구를 쓸지는 화면 몫이다(이 파일은 계약만 낸다).
            "search_exhausted": {"value": meta_v.get("exhausted", False),
                                  "recommend": meta_r.get("exhausted", False),
                                  "highend": meta_h.get("exhausted", False)},
            "sets": sets, "companion": comp}


# ============================================================================
# S2 「이 구성을 고른 이유」 — 이미 결정된 구성을 **설명만** 한다 (A-01·A-02·A-03)
#
# ■ 왜 견적 응답(POST /api/recommend)에 싣지 않았나
#   그 경로는 고객이 기다리는 자리다. LLM 호출 한 번은 견적 생성보다 몇 배 느리고,
#   근거 문구 하나 때문에 견적 전체가 늦어지면 안 된다. 그래서 **화면이 견적을 받은 뒤
#   따로 부르는** 별도 경로로 둔다 — 견적 응답 시간은 이 변경으로 바뀌지 않는다.
#   문구가 도착하기 전까지 화면에는 엔진이 적어 보낸 고정 문구가 그대로 보인다.
#
# ■ 왜 화면이 부품을 실어 보내지 않고 session_id·tier만 보내나
#   프롬프트의 재료를 화면이 실어 보내면 그 순간 재료를 클라이언트가 지어낼 수 있게 된다
#   (§화면 정직성 — 화면이 숫자를 지어내지 않는다는 규칙의 서버 쪽 짝). 재료는 전부
#   서버가 원장(consult_sessions · quote_snapshots)에서 다시 읽는다. 즉 이 엔드포인트는
#   **엔진을 다시 돌리지 않고**, 그때 확정돼 저장된 구성을 그대로 읽어 설명한다.
#
# ■ 지키는 계약
#   A-01·A-02  LLM은 구성을 바꾸지 않는다 — 프롬프트로 금지하고, 결과에 **사실에 없는
#              숫자**가 섞이면 그 답을 버린다(_unbacked_numbers). 지어낸 수치를 고객
#              화면에 올리느니 고정 문구가 낫다.
#   실패 은폐 금지  키 미설정·한도 초과·프로바이더 오류·검증 탈락은 전부 `ok:false`와
#              사유로 돌려주고 서버 로그에 남긴다(로그는 ASCII 기호만 — stdout이 cp949다).
# ============================================================================
EXPLAIN_TASK_KEY = "task.s2_explain"
EXPLAIN_MAX_CHARS = 400          # 프롬프트는 200자를 요구한다. 넘치면 설명이 아니라 작문이다
EXPLAIN_TIMEOUT_SEC = 25
EXPLAIN_MAX_TOKENS = 400

# 같은 (상담, 티어)를 다시 물으면 다시 사지 않는다 — 탭을 오갈 때마다 과금되면 안 된다.
# 견적이 확정 저장본이라 같은 입력에는 같은 재료가 나온다(캐시가 다른 답을 감추지 않는다).
_EXPLAIN_CACHE: dict = {}
_EXPLAIN_CACHE_MAX = 300

_NUM_RE = re.compile(r"\d+")

_EXPLAIN_SYSTEM = (
    "너는 PC 견적의 근거를 설명하는 사람이다. 구성은 이미 확정됐고, 너는 그 구성을"
    " 고객에게 설명만 한다.\n"
    "1. 부품을 바꾸거나 더하거나 빼자고 말하지 않는다. 다른 제품을 권하지 않는다.\n"
    "2. 주어진 사실에 없는 수치는 한 개도 쓰지 않는다 — 가격·후보 수·순위·점수·FPS·"
    "성능 배수를 지어내지 않는다. 숫자를 쓸 때는 주어진 값을 그대로 옮긴다.\n"
    "3. 성능 벤치마크 자료는 없다. '가장 빠르다'·'최고 성능' 같은 단정을 하지 않는다.\n"
    "4. 한국어 존댓말 평서체(~합니다)로 2~3문장, 200자 이내. 한 문단으로 쓰고 목록·"
    "머리기호·마크다운·따옴표를 쓰지 않는다.\n"
    "5. 고객이 말한 조건(용도·예산)과 실제로 선택된 부품을 연결해 왜 이 구성인지를 말한다."
)


def _spec_ko(spec: dict) -> dict:
    """사양 키를 표시 라벨로 바꾼다 — 라벨의 정본은 `spec_field_defs`다(CANON §1).

    여기서 두 번째 어휘표를 만들지 않는다. 정의를 못 찾으면 원래 키를 그대로 쓴다.
    """
    out = {}
    for k, v in (spec or {}).items():
        d = spec_fields.by_key(k)
        name = (d or {}).get("label") or k
        unit = (d or {}).get("unit")
        out[name] = f"{v}{unit}" if unit else v
    return out


def _explain_facts(conn, session_id: int, tier: str) -> dict | None:
    """설명의 재료 — **원장에 저장된 그 견적**에서만 모은다. 없으면 None.

    엔진을 다시 돌리지 않는다: 지금 재고·가격이 그때와 달라도 고객이 보고 있는 것은
    그때 만들어진 견적이므로, 설명도 그 견적을 설명해야 한다.
    """
    sess = conn.execute(text(
        "SELECT constraints FROM consult_sessions WHERE session_id = :s"),
        {"s": session_id}).mappings().first()
    if sess is None:
        return None
    snap = conn.execute(text(
        "SELECT items, total_amount FROM quote_snapshots"
        " WHERE session_id = :s AND quote_type = :t"
        " ORDER BY snapshot_id DESC LIMIT 1"), {"s": session_id, "t": tier}).mappings().first()
    if snap is None:
        return None

    items = snap["items"] or {}
    parts = items.get("parts") or []
    compat = items.get("compat") or {}
    checks = compat.get("checks") or []
    cons = sess["constraints"] or []
    budget_v = next((c.get("v") for c in cons if c.get("l") == "예산"), "")
    cap = _budget_cap(budget_v)
    total = int(snap["total_amount"] or 0)

    # 금액은 **표시 표기 그대로** 넘긴다. 정수로 주면 답에 "1499800원"이 그대로 실린다 —
    # 화면에 올릴 문장이라 자릿수 구분이 있는 쪽이 맞고, 검증(_unbacked_numbers)은 쉼표를
    # 지우고 비교하므로 어느 표기로 인용하든 통과한다.
    def won(v):
        return f"{int(v):,}원"

    return {
        "견적_종류": TIER_LABELS.get(tier, tier),
        "고객_조건": [{"항목": c.get("l"), "값": c.get("v")} for c in cons],
        # None이면 숫자 상한이 없는 표현('AI 추천 예산'·'200만원 이상')이다
        "예산_상한": won(cap) if cap is not None else None,
        "예산_판정": ("상한 없음" if cap is None
                     else ("예산 이내" if total <= cap else "예산 초과")),
        "총액": won(total),
        "부품_수": len(parts),
        "부품": [{"종류": SLOT_KO.get(p.get("part_type"), p.get("part_type")),
                  "이름": p.get("name"), "제조사": p.get("maker"),
                  "가격": won(p.get("price") or 0), "사양": _spec_ko(p.get("spec") or {}),
                  "선호_태그": p.get("tags") or []}
                 for p in parts],
        "호환_검사_수": len(checks),
        "호환_검사": [{"항목": c.get("label"), "통과": c.get("pass"), "값": c.get("detail")}
                     for c in checks],
        "파워_여유율_퍼센트": compat.get("power_headroom_pct"),
        "엔진이_적은_근거": items.get("reasons") or [],
    }


def _unbacked_numbers(out_text: str, facts_json: str) -> list:
    """문장에 있는데 **사실에는 없는** 숫자를 찾는다 — 있으면 그 답은 버린다.

    A-01의 "응답에 없는 수치를 쓰지 않는다"를 프롬프트만으로 믿지 않는 장치다. 자릿수
    구분 쉼표는 지우고 비교한다(사실의 428000과 문장의 428,000이 같은 값이다).
    """
    allowed = set(_NUM_RE.findall(facts_json.replace(",", "")))
    return sorted({n for n in _NUM_RE.findall(out_text.replace(",", "")) if n not in allowed})


def _explain_clean(s: str) -> str:
    """한 문단으로 편다 — 줄바꿈·머리기호·감싼 따옴표를 없앤다(화면은 한 문단 자리다)."""
    s = re.sub(r"\s+", " ", (s or "").replace("*", "").replace("- ", " ")).strip()
    if len(s) >= 2 and s[0] in "\"'“‘" and s[-1] in "\"'”’":
        s = s[1:-1].strip()
    return s


class ExplainBody(BaseModel):
    session_id: int
    tier: str
    # 견적 응답(`POST /api/recommend`)이 준 열쇠. 쿼리 `?k=`·헤더 `X-Access-Key` 로도 받는다.
    access_key: str | None = None


@router.post("/recommend/explain")
def recommend_explain(body: ExplainBody, request: Request, k: str | None = None):
    """확정된 견적 하나에 대한 「이 구성을 고른 이유」 문구를 만든다.

    ■ 접근 게이트 (2026-08-17 사장님 확정 — 세 구멍 중 ①·②)
      이 경로는 **남의 session_id 를 넣으면 남의 견적 구성·가격이 그대로 나오던 자리**다.
      session_id 는 연속 정수라 세면 맞힐 수 있다. 그래서 열쇠를 요구한다.
      횟수 제한은 **캐시에 없는 요청**, 즉 실제로 LLM 비용이 나가는 자리 직전에만 센다.

    응답 규약
      200 {ok:true, text}   설명 생성 성공
      200 {ok:false, reason} LLM 미설정·한도 초과·프로바이더 오류·검증 탈락 —
          **문구를 만들지 못했을 뿐 요청은 정상**이라 200이다. 화면은 기존 고정 문구를
          지키고, 왜 못 만들었는지는 사유와 서버 로그가 말한다(조용한 실패가 아니다).
      400 / 404             알 수 없는 견적 종류 / 그런 상담·견적이 없음 — 요청 자체가
          틀린 경우다. 이걸 200으로 덮으면 잘못된 호출이 "AI가 답을 못 했다"로 보인다.
      403 {error:"forbidden", reason, detail}
          `access_key_missing`  열쇠를 안 보냈다
          `access_key_mismatch` 남의 견적이다(또는 열쇠가 틀렸다)
          `no_access_key`       게이트 도입 이전 상담이라 열쇠 자체가 없다(NULL)
      429 {error:"rate_limited", scope:"visitor", window, used, limit, retry_after_sec, detail}
          방문자별 호출 한도 초과. `Retry-After` 헤더를 함께 준다.
      503 {error:"gate_unavailable"}  마이그레이션 0055 미적용 — 게이트를 세울 수 없다.
          **열어 두지 않는다.** 열어 두면 "막았다"는 보고가 거짓이 된다.

      ⚠ 403 과 429 는 **다른 응답**이다 — 화면이 "본인 링크로 다시 여십시오"와
        "잠시 뒤 다시"를 구분해 말할 수 있어야 한다(§실패를 삼키지 않는다).
    """
    if body.tier not in TIER_LABELS:
        raise HTTPException(400, f"알 수 없는 견적 종류: {body.tier}")

    provided = body.access_key or access_gate.key_from_request(request, k)
    cache_key = (body.session_id, body.tier)

    with engine.connect() as conn:
        # 소유자 확인은 `api/access_gate` 하나가 한다 — swap.apply 도 같은 함수를 부른다.
        # 게이트 도입 이전 행(열쇠 NULL)은 아무도 못 연다: 열쇠를 지어내 채우지 않았다
        # (0055 docstring). 화면은 그때 엔진 고정 문구를 그대로 쓴다.
        access_gate.require_session_owner(
            conn, body.session_id, provided,
            what="recommend.explain", not_found_detail="그 상담의 해당 견적이 없습니다")

        # 소유자가 맞다. 캐시에 있으면 비용이 0 이라 횟수로 세지 않는다.
        if cache_key in _EXPLAIN_CACHE:
            return {"ok": True, "tier": body.tier, "cached": True} | _EXPLAIN_CACHE[cache_key]

        access_gate.check_rate(conn, request, what="recommend.explain")
        facts = _explain_facts(conn, body.session_id, body.tier)
    if facts is None:
        raise HTTPException(404, "그 상담의 해당 견적이 없습니다")

    facts_json = json.dumps(facts, ensure_ascii=False)
    prompt = ("아래는 우리 엔진이 이미 확정한 견적이다. 이 구성을 고른 이유를 고객에게"
              " 설명하는 문단 하나를 써라. 사실(JSON):\n" + facts_json)

    try:
        res = llm.call(prompt, task_key=EXPLAIN_TASK_KEY, system=_EXPLAIN_SYSTEM,
                       customer_facing=True, max_output_tokens=EXPLAIN_MAX_TOKENS,
                       timeout_sec=EXPLAIN_TIMEOUT_SEC)
    except Exception as e:                                   # noqa: BLE001
        # 삼키지 않는다: 무엇이 왜 실패했는지 서버 로그에 남긴다(ASCII 기호만).
        log.warning("[s2_explain] LLM call failed session=%s tier=%s: %s: %s",
                    body.session_id, body.tier, type(e).__name__, e)
        return {"ok": False, "tier": body.tier,
                "reason": f"{type(e).__name__}: {e}"}

    out = _explain_clean(res.text)
    bad = _unbacked_numbers(out, facts_json)
    if bad or not out or len(out) > EXPLAIN_MAX_CHARS:
        why = ("unbacked numbers " + ",".join(bad) if bad
               else ("empty text" if not out else f"too long ({len(out)} chars)"))
        log.warning("[s2_explain] rejected answer session=%s tier=%s provider=%s model=%s: %s",
                    body.session_id, body.tier, res.provider, res.model, why)
        return {"ok": False, "tier": body.tier, "reason": f"answer rejected - {why}"}

    if len(_EXPLAIN_CACHE) >= _EXPLAIN_CACHE_MAX:
        _EXPLAIN_CACHE.clear()
    _EXPLAIN_CACHE[cache_key] = {"text": out, "provider": res.provider, "model": res.model}
    return {"ok": True, "tier": body.tier, "cached": False} | _EXPLAIN_CACHE[cache_key]
