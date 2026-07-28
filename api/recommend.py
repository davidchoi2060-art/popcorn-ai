"""견적 생성 엔진 v1 — POST /api/recommend.

A-02: 같은 입력 + 같은 재고 = 같은 구성. A-03: LLM 없음(reasons는 고정 템플릿).
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
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import usage_floors as UF
from .candidates import BUDGET_ALLOC, SLOT_KO, _apply_one, _budget_cap
from .db import engine

router = APIRouter(prefix="/api")

SLOTS = ["CPU", "MB", "RAM", "GPU", "CASE", "COOLER", "POWER", "SSD"]
SLOT_TYPES = {s: (s,) for s in SLOTS} | {"COOLER": ("COOLER_CPU_AIR", "COOLER_CPU_AIO")}
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
    return [dict(r) for r in conn.execute(text(
        "SELECT product_code, sku, product_name, part_type, sale_price, stock_qty,"
        " socket, socket_list, mem_type, tdp_watt, rated_watt, required_power_watt,"
        " form_factor, form_factor_list, capacity_gb,"
        " length_mm, gpu_max_mm, cooler_height_mm, cooler_tdp, tag_white, tag_silent,"
        " spec_sources, data_origin"
        " FROM v_recommendation_candidates WHERE stock_qty > 0")).mappings().all()]


def load_compat_rules(conn) -> dict:
    """compat_rules(ERD §3.7)를 슬롯별로 로드 — **엔진의 단일 원천**(슬라이스 34).

    로드 시 계약 검증: ref_slot이 탐색 순서상 slot보다 앞이어야 한다. 위반 규칙은
    건너뛰고 경고한다(잘못된 규칙이 KeyError로 엔진을 죽이지 않게).
    """
    rows = conn.execute(text(
        "SELECT rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, blocking"
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


def _slot_ok(slot, p, chosen, rules: dict):
    """슬롯 진입 호환 검사 — DB 규칙을 그대로 적용. 규칙 없는 슬롯(CPU·GPU·SSD)은 독립.

    필드가 풀에 없으면 `.get()`이 None을 주고 NULL 불통과 규칙이 걸린다 — 500으로 죽는 대신
    "판정할 수 없으니 통과시키지 않는다"로 떨어진다(누락은 check_rule_fields가 경고로 알린다).
    """
    for rule in rules.get(slot, ()):
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
                   "sku": chosen[s]["sku"], "name": chosen[s]["product_name"],
                   "price": chosen[s]["sale_price"]} for s in SLOTS],
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
        common = pool
        for label, value in (("용도", SHOWCASE["usage"]),):
            common, _, _ = _apply_one(common, label, value)
        capped, _, _ = _apply_one(common, "예산", SHOWCASE["budget"])
        pick = _build_set("recommend", capped, cap, rules)
        if pick is None:                    # 배분율이 막으면 푼다(견적 경로와 같은 규칙)
            pick = _build_set("recommend", common, cap, rules)

    data = {
        # S1 후보 카운터와 **같은 정의**다 — S0에서 다른 수를 보여주면 다음 화면에서
        # 갑자기 줄어든 것처럼 보인다.
        "pool": len(pool),
        "rules": sum(len(v) for v in rules.values()),
        "usage": SHOWCASE["usage"], "budget_label": SHOWCASE["budget"],
        "pick": pick and {"items": pick["items"], "total": pick["total"]},
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
                    "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
                    "price": r["sale_price"], "stock": r["stock_qty"], "spec": spec})
    order = ["MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM"]
    return sorted(out, key=lambda c: order.index(c["part_type"]))


@router.post("/recommend")
def recommend(body: RecommendBody):
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

        session_id = conn.execute(text(
            "INSERT INTO consult_sessions (member_id, mode, constraints) VALUES"
            " (NULL, :m, CAST(:c AS JSONB)) RETURNING session_id"),
            {"m": body.mode,
             "c": json.dumps([{"l": c.l, "v": c.v} for c in body.constraints])}).scalar()
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

    return {"session_id": session_id, "generated_at": datetime.now().isoformat(),
            "funnel": {"total": total_n, "passed": len(passed)},
            # 서버가 실제로 건 하한 — 화면이 지어내지 않고 이것만 말한다
            "usage_floors": {"usage": UF.label_of(usage_v), "items": floors},
            "highend_cap_x": HIGHEND_CAP_X,
            "sets": sets, "companion": comp}
