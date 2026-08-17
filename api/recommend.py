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
가성비(최소 구성)가 불가능하면 전 티어 불가 — 최소 구성이 예산 밖이면 견적 자체가 불성립.

v1 정직 한계(문서·응답에 명기): 성능 지표(벤치·FPS) 미보유 — 가격을 사양 근사(proxy)로 사용.
NULL 스펙 필드는 해당 호환 검사 불통과로 간주(검증 불가 부품은 조립 보증 불가 → 제외).
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from . import access_gate   # 접근 게이트의 단일 원천 — 열쇠 생성·소유자 확인·횟수 제한
from . import llm       # LLM 호출의 단일 원천 — 이 파일에서 프로바이더를 직접 부르지 않는다
from . import visitor

from . import spec_fields   # 부품 종류별 "설명에 쓸 사양"의 단일 원천(spec_field_defs)
from . import usage_floors as UF
from .timeutil import iso, now_iso
from .candidates import BUDGET_ALLOC, SLOT_KO, _apply_one, _budget_cap
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
        " spec_sources, data_origin"
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


def _tier_sort(parts, tier, has_cap):
    if tier == "value":
        return sorted(parts, key=lambda p: (p["sale_price"], p["product_code"]))
    if tier == "highend" or has_cap:  # 추천(숫자 예산) = 내림차순 + 가지치기
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


def _dfs(slot_pools, budget_limit, rules: dict):
    """사전식 첫 완성 구성 탐색. budget_limit 있으면 합 가지치기.

    min_rest(남은 슬롯 최저가 합)는 **좁히기 전 전체 풀** 기준으로 둔다 — 더 느슨한 하한이라
    가지치기가 결과를 바꾸지 않는다(좁힌 풀로 계산하면 chosen에 따라 값이 달라져 계산 불가).
    """
    min_rest = [0] * (len(SLOTS) + 1)
    for i in range(len(SLOTS) - 1, -1, -1):
        min_rest[i] = min_rest[i + 1] + min(p["sale_price"] for p in slot_pools[SLOTS[i]])
    idx = build_search_index(slot_pools, rules)
    nodes = [0]

    def go(i, chosen, total):
        if i == len(SLOTS):
            return dict(chosen)
        slot = SLOTS[i]
        for p in _narrow(slot, chosen, idx, slot_pools[slot]):
            nodes[0] += 1
            if nodes[0] > DFS_NODE_CAP:
                return None
            if budget_limit is not None and total + p["sale_price"] + min_rest[i + 1] > budget_limit:
                continue
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
    if got is None and nodes[0] > DFS_NODE_CAP:
        print(f"[recommend] 탐색 노드 상한({DFS_NODE_CAP:,}) 도달, 구성 없음으로 처리")
    return got


def build_compat(chosen: dict, rules: dict) -> dict:
    """호환성 요약 — **DB 규칙에서 생성**(슬라이스 34). recommend와 swap이 공유.

    표시 항목이 규칙과 1:1이 되어, 규칙을 추가하면 화면 근거도 자동으로 늘어난다.
    detail은 규칙의 detail_fmt({v}=대상값 / {r}=상대값)로 조립한다.
    """
    checks = []
    for slot in SLOTS:
        for rule in rules.get(slot, ()):
            # 겨냥하지 않은 부품에는 검사를 내밀지 않는다. 수랭 구성에 '쿨러 높이 여유'를
            # 띄우면 검증한 적 없는 것을 검증했다고 말하는 셈이다(슬라이스 82).
            if not _rule_applies(rule, chosen[slot]):
                continue
            v = chosen[slot].get(rule["field"])
            r = chosen[rule["ref_slot"]].get(rule["ref_field"])
            fmt = rule["detail_fmt"] or "{v} / {r}"
            checks.append({
                "key": rule["rule_key"], "label": rule["label"],
                "pass": _cmp(rule["op"], v, r),
                "detail": fmt.replace("{v}", str(v)).replace("{r}", str(r)),
            })
    gpu, power = chosen["GPU"], chosen["POWER"]
    headroom = (int(power["rated_watt"] / gpu["required_power_watt"] * 100)
                if power["rated_watt"] and gpu["required_power_watt"] else None)
    return {"power_headroom_pct": headroom, "checks": checks}


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


def _build_set(tier, pool, cap, rules, floor_note=None, relax_note=None, limit_override=None):
    slot_pools = {}
    for s in SLOTS:
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
    chosen = _dfs(slot_pools, limit, rules)
    if chosen is None:
        return None
    total = sum(p["sale_price"] for p in chosen.values())
    verdict = "none" if cap is None else ("within" if total <= cap else "over")
    reasons = {
        "value": ["조건 통과 부품에서 예산 안 최저가 조합", "조립 불가 조합은 탐색에서 제외"],
        "recommend": ["예산 안에서 가격 기준 최고 사양 조합",
                      "성능 지표 미보유 — 가격을 사양 근사로 사용(정직 표기)"],
        "highend": [f"예산의 {HIGHEND_CAP_X:g}배까지 허용한 최고 사양 조합"
                    f"(부품별 배분 상한은 유지 — 초과분은 아래에 정직 표기)"],
    }[tier]
    reasons = reasons + [n for n in (floor_note, relax_note) if n]
    return {
        "label": TIER_LABELS[tier],
        "items": [{"part_type": s, "product_code": chosen[s]["product_code"],
                   "sku": chosen[s]["sku"], "name": display_name(chosen[s]["product_name"]),
                   "price": chosen[s]["sale_price"], "maker": chosen[s].get("maker"),
                   "spec": _explain_spec(chosen[s]), "tags": _pref_tags(chosen[s])}
                  for s in SLOTS],
        "total": total,
        "compat": build_compat(chosen, rules),
        "budget": {"cap": cap, "verdict": verdict,
                   "over_by": max(0, total - cap) if cap is not None else 0},
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

        # funnel.passed = v0 count와 동일 규칙(전 제약 순차 적용) — S1 카운터와 일치
        passed = pool
        for c in body.constraints:
            passed, _, _ = _apply_one(passed, c.l, c.v)

        # 3티어 공통 = 태그만 적용(예산 제외), 캡 풀 = 예산까지 적용
        common = pool
        for c in body.constraints:
            if c.l != "예산":
                common, _, _ = _apply_one(common, c.l, c.v)
        capped = common
        if cap is not None:
            capped, _, _ = _apply_one(capped, "예산", budget_v)

        # 용도 하한(슬라이스 58) — 서버가 실제로 건 하한만 근거로 말한다.
        # GPU는 성능 지표가 없어 권장 전원을 계층 근사로 쓴다. 그 사실을 숨기지 않는다.
        usage_v = next((c.v for c in body.constraints if c.l in ("용도", "상황")), "")
        floors = UF.summary(usage_v)
        floor_note = None
        if floors:
            # 근거에는 **숫자가 있어야 한다**. "고사양 게임 GPU 등급"만으로는 무엇을 걸렀는지
            # 알 수 없다 — 얼마 이상인지가 근거다.
            unit = {"required_power_watt": "W", "capacity_gb": "GB"}
            said = " · ".join(f"{SLOT_KO.get(f['slot'], f['slot'])} "
                              f"{f['value']:,}{unit.get(f['field'], '')} 이상" for f in floors)
            floor_note = (f"{UF.label_of(usage_v)} 하한 — {said}."
                          " GPU는 성능 지표가 없어 권장 전원을 등급 근사로 사용합니다")

        # 고성능 풀 = 예산 배분율을 HIGHEND_CAP_X배로 늘려 적용(전면 해제가 아니다).
        # `common`(배분 미적용)을 그대로 주면 램 931만원이 다시 들어온다.
        hi_pool = common
        if cap is not None:
            hi_cap = int(cap * HIGHEND_CAP_X)
            hi_pool = [p for p in common
                       if p["sale_price"] <= int(hi_cap * BUDGET_ALLOC.get(p["part_type"], 1.0))]

        rules = load_compat_rules(conn)   # 요청당 1회 로드 — 규칙 변경이 즉시 반영된다
        check_rule_fields(pool, rules)    # 규칙 필드 누락은 조용한 전면 불통과 → 경고로 드러낸다
        # 가성비형은 **부품별 배분율을 받지 않는다**(슬라이스 58). 최저가를 고르는 티어에
        # "비싼 부품 차단" 상한은 무의미한데, 슬롯 후보를 예산마다 다르게 만들어
        # 150만원이 70만원보다 비싼 가성비 구성을 내놓았다(회귀 '가성비는 전 예산 공통' 실패).
        # 진짜 제약은 총액이고 그건 DFS 가지치기가 건다.
        sets = {"value": _build_set("value", common, cap, rules, floor_note)}
        if sets["value"] is None:
            # 최소 구성이 예산 밖이면 견적 불성립 — 전 티어 불가(정직)
            sets["recommend"] = sets["highend"] = None
        else:
            # 배분율은 "한 부품에 몰빵하지 마라"는 균형 장치일 뿐 조립 조건이 아니다.
            # 저예산에서는 그것이 슬롯을 전멸시켜 견적을 못 만든다 — 실측: 50만원 사무용에서
            # RAM 배분 10%(5만원)가 DDR4 램(최저 84,900원)을 전부 걸러 남은 DDR5 8GB 하나가
            # 남은 DDR4 보드와 맞지 않았다. **균형을 못 지킬 바엔 균형을 포기하고 견적을 낸다** —
            # 총액 상한은 그대로 지킨다. 포기했으면 근거에 그렇게 적는다(정직).
            relaxed = "부품별 배분 상한으로는 조합이 없어 균형 제약을 풀었습니다(총액 상한은 유지)"
            sets["recommend"] = _build_set("recommend", capped, cap, rules, floor_note)
            if sets["recommend"] is None:
                sets["recommend"] = _build_set("recommend", common, cap, rules, floor_note,
                                               relaxed)
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
            sets["highend"] = _build_set("highend", hi_pool, cap, rules, floor_note,
                                         hi_note, hi_limit)
            if sets["highend"] is None:
                sets["highend"] = _build_set("highend", common, cap, rules, floor_note,
                                             hi_note or relaxed, hi_limit)

        uid = visitor.resolve(conn, request, response)
        # 이 견적의 「추측 못 할 열쇠」 — session_id 가 연속 정수라(최근 10건 5872~5881)
        # 번호만으로는 남의 견적을 막을 수 없다. 열쇠는 **이 응답을 받은 쪽에만** 간다.
        # 스키마(0055)가 아직 없으면 열쇠 없이 그대로 만든다 — 그 행은 나중에 설명을
        # 부를 수 없고(403), 게이트가 왜 못 서는지는 서버 로그가 말한다.
        gate_on = access_gate.column_ready(conn, "consult_sessions")
        access_key = access_gate.new_key() if gate_on else None
        params = {"m": body.mode, "u": uid,
                  "c": json.dumps([{"l": c.l, "v": c.v} for c in body.constraints])}
        cols, vals = "member_id, mode, constraints, user_id", "NULL, :m, CAST(:c AS JSONB), :u"
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
