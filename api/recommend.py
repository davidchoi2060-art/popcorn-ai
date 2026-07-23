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

from .candidates import BUDGET_ALLOC, _apply_one, _budget_cap
from .db import engine

router = APIRouter(prefix="/api")

SLOTS = ["CPU", "MB", "RAM", "GPU", "CASE", "COOLER", "POWER", "SSD"]
SLOT_TYPES = {s: (s,) for s in SLOTS} | {"COOLER": ("COOLER_CPU_AIR", "COOLER_CPU_AIO")}
DFS_NODE_CAP = 100_000  # 안전망 — v1 풀 규모(18)에선 도달 불가

TIER_LABELS = {"value": "가성비형 견적", "recommend": "추천형 견적", "highend": "고성능형 견적"}


class Constraint(BaseModel):
    l: str
    v: str


class RecommendBody(BaseModel):
    mode: str
    constraints: list[Constraint] = []


def _load_pool(conn):
    return [dict(r) for r in conn.execute(text(
        "SELECT product_code, sku, product_name, part_type, sale_price, stock_qty,"
        " socket, mem_type, tdp_watt, rated_watt, required_power_watt,"
        " length_mm, gpu_max_mm, cooler_height_mm, cooler_tdp, tag_white, tag_silent"
        " FROM v_recommendation_candidates WHERE stock_qty > 0")).mappings().all()]


def _slot_ok(slot, p, chosen):
    """슬롯 진입 호환 검사 — 앞 슬롯만 참조. NULL 필드는 불통과."""
    if slot == "MB":
        return p["socket"] is not None and p["socket"] == chosen["CPU"]["socket"]
    if slot == "RAM":
        return p["mem_type"] is not None and p["mem_type"] == chosen["MB"]["mem_type"]
    if slot == "CASE":
        return (p["gpu_max_mm"] is not None and chosen["GPU"]["length_mm"] is not None
                and p["gpu_max_mm"] >= chosen["GPU"]["length_mm"])
    if slot == "COOLER":
        return (p["socket"] == chosen["CPU"]["socket"]
                and p["cooler_tdp"] is not None and chosen["CPU"]["tdp_watt"] is not None
                and p["cooler_tdp"] >= chosen["CPU"]["tdp_watt"]
                and p["cooler_height_mm"] is not None
                and p["cooler_height_mm"] <= chosen["CASE"]["cooler_height_mm"])
    if slot == "POWER":
        return (p["rated_watt"] is not None and chosen["GPU"]["required_power_watt"] is not None
                and p["rated_watt"] >= chosen["GPU"]["required_power_watt"])
    return True  # CPU·GPU·SSD — 독립


def _tier_sort(parts, tier, has_cap):
    if tier == "value":
        return sorted(parts, key=lambda p: (p["sale_price"], p["product_code"]))
    if tier == "highend" or has_cap:  # 추천(숫자 예산) = 내림차순 + 가지치기
        return sorted(parts, key=lambda p: (-p["sale_price"], p["product_code"]))
    # 추천 + 숫자 예산 없음 — 중간 순위 우선
    asc = sorted(parts, key=lambda p: (p["sale_price"], p["product_code"]))
    mid = (len(asc) - 1) // 2
    return sorted(asc, key=lambda p: (abs(asc.index(p) - mid), asc.index(p)))


def _dfs(slot_pools, budget_limit):
    """사전식 첫 완성 구성 탐색. budget_limit 있으면 합 가지치기."""
    min_rest = [0] * (len(SLOTS) + 1)
    for i in range(len(SLOTS) - 1, -1, -1):
        min_rest[i] = min_rest[i + 1] + min(p["sale_price"] for p in slot_pools[SLOTS[i]])
    nodes = [0]

    def go(i, chosen, total):
        if i == len(SLOTS):
            return dict(chosen)
        slot = SLOTS[i]
        for p in slot_pools[slot]:
            nodes[0] += 1
            if nodes[0] > DFS_NODE_CAP:
                return None
            if budget_limit is not None and total + p["sale_price"] + min_rest[i + 1] > budget_limit:
                continue
            if not _slot_ok(slot, p, chosen):
                continue
            chosen[slot] = p
            r = go(i + 1, chosen, total + p["sale_price"])
            if r is not None:
                return r
            del chosen[slot]
        return None

    return go(0, {}, 0)


def _build_set(tier, pool, cap):
    slot_pools = {}
    for s in SLOTS:
        cands = [p for p in pool if p["part_type"] in SLOT_TYPES[s]]
        if not cands:
            return None
        slot_pools[s] = _tier_sort(cands, tier, cap is not None)
    limit = cap if (cap is not None and tier in ("value", "recommend")) else None
    chosen = _dfs(slot_pools, limit)
    if chosen is None:
        return None
    total = sum(p["sale_price"] for p in chosen.values())
    cpu, mb, ram, gpu = chosen["CPU"], chosen["MB"], chosen["RAM"], chosen["GPU"]
    case, cooler, power = chosen["CASE"], chosen["COOLER"], chosen["POWER"]
    headroom = int(power["rated_watt"] / gpu["required_power_watt"] * 100)
    verdict = "none" if cap is None else ("within" if total <= cap else "over")
    reasons = {
        "value": ["조건 통과 부품에서 예산 안 최저가 조합", "조립 불가 조합은 탐색에서 제외"],
        "recommend": ["예산 안에서 가격 기준 최고 사양 조합",
                      "성능 지표 미보유 — 가격을 사양 근사로 사용(정직 표기)"],
        "highend": ["예산 상한 없이 가격 기준 최고 사양 조합(초과분은 아래에 정직 표기)"],
    }[tier]
    return {
        "label": TIER_LABELS[tier],
        "items": [{"part_type": s, "product_code": chosen[s]["product_code"],
                   "sku": chosen[s]["sku"], "name": chosen[s]["product_name"],
                   "price": chosen[s]["sale_price"]} for s in SLOTS],
        "total": total,
        "compat": {
            "power_headroom_pct": headroom,
            "checks": [
                {"key": "socket", "label": "CPU 소켓 규격 일치", "pass": True,
                 "detail": f"{cpu['socket']} = {mb['socket']} (쿨러 {cooler['socket']})"},
                {"key": "mem", "label": "메모리 규격 일치", "pass": True,
                 "detail": f"{ram['mem_type']} = {mb['mem_type']}"},
                {"key": "cooler_tdp", "label": "쿨러 발열(TDP) 통과", "pass": True,
                 "detail": f"{cooler['cooler_tdp']}W ≥ {cpu['tdp_watt']}W"},
                {"key": "fit", "label": "케이스 장착 공간 여유", "pass": True,
                 "detail": f"GPU {gpu['length_mm']}≤{case['gpu_max_mm']}mm · 쿨러 {cooler['cooler_height_mm']}≤{case['cooler_height_mm']}mm"},
            ],
        },
        "budget": {"cap": cap, "verdict": verdict,
                   "over_by": max(0, total - cap) if cap is not None else 0},
        "reasons": reasons,
    }


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
            spec = f"{r['size_inch']:g}형 {r['resolution']} {r['refresh_hz']}Hz {r['panel']}"
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

        sets = {"value": _build_set("value", capped, cap)}
        if sets["value"] is None:
            # 최소 구성이 예산 밖이면 견적 불성립 — 전 티어 불가(정직)
            sets["recommend"] = sets["highend"] = None
        else:
            sets["recommend"] = _build_set("recommend", capped, cap)
            sets["highend"] = _build_set("highend", common, cap)

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
            "sets": sets, "companion": comp}
