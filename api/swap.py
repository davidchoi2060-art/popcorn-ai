"""S3 부품 변경·연쇄 스왑 — 스왑 = 같은 session·tier의 새 quote_snapshot INSERT.

orders.py가 최신 스냅샷 1건(ORDER BY snapshot_id DESC)을 집으므로 S4 주문에 자동 반영된다.
UX-11: ① 호환 100% 통과 대안만 노출 ③ 연쇄는 정직 설명 후 승인 시 자동 동시 교체.

원칙:
- 가격 = 스냅샷 보존: 비변경 슬롯은 스냅샷 가격 유지, 변경 슬롯만 라이브 풀 가격
  ("고객에게 보여준 그대로" — 원칙 6). price_diff = 라이브 신가 − 스냅샷 구가.
- 현 구성 재구성 = products⨝product_specs 직조인(뷰 아님 — 품절·검수 전환 부품도
  렌더 가능, unavailable 정직 표기). 대안·연쇄 후보는 판매 풀(_load_pool) 한정.
- 연쇄 1패스: 위반 슬롯을 가격 오름차순 순회 교체 후 전체 재검증. 실패하거나
  위반 슬롯이 스왑 슬롯 자신이면(예: 파워 하향) 미노출. tie=product_code(A-02).
- chain_reason은 고정 템플릿(A-03 — LLM 없음).
v1 제외: 예산 재판정(사용자 명시 선택 — 가격차로 정직), swap_event_logs(레거시 users FK — 이관).
"""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine
from .recommend import SLOTS, SLOT_TYPES, _load_pool, _slot_ok, build_compat

router = APIRouter(prefix="/api/swap")

SLOT_KO = {"CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
           "CASE": "케이스", "COOLER": "CPU쿨러", "POWER": "파워", "SSD": "저장장치"}
SPEC_COLS = ("socket, mem_type, tdp_watt, rated_watt, required_power_watt,"
             " length_mm, gpu_max_mm, cooler_height_mm, cooler_tdp, tag_white, tag_silent")


class SwapQuery(BaseModel):
    session_id: int
    tier: str


class Change(BaseModel):
    slot: str
    product_code: int


class ApplyBody(SwapQuery):
    changes: list[Change]


def _load_snapshot(conn, session_id: int, tier: str):
    snap = conn.execute(text(
        "SELECT snapshot_id, items, companion, total_amount, created_at FROM quote_snapshots"
        " WHERE session_id=:s AND quote_type=:t ORDER BY snapshot_id DESC LIMIT 1"),
        {"s": session_id, "t": tier}).mappings().first()
    if snap is None:
        raise HTTPException(404, {"error": "quote_not_found",
                                  "detail": "견적 스냅샷이 없습니다 — 견적을 다시 받아주세요"})
    return snap


def _specs_by_code(conn, codes):
    """직조인 — 품절·검수 전환 부품도 스펙 확보(렌더·검증용)."""
    cols = ", ".join("ps." + c.strip() for c in SPEC_COLS.split(","))
    return {r["product_code"]: dict(r) for r in conn.execute(text(
        f"SELECT p.product_code, p.sku, p.product_name, p.part_type, p.sale_price, {cols}"
        " FROM products p JOIN product_specs ps USING (product_code)"
        " WHERE p.product_code = ANY(:c)"), {"c": list(codes)}).mappings().all()}


def _chosen_from_parts(parts, specs):
    """스냅샷 parts → 슬롯별 스펙 dict(_slot_ok·build_compat 입력). 스냅샷 가격 유지."""
    chosen = {}
    for it in parts:
        sp = specs.get(it["product_code"])
        if sp is None:
            raise HTTPException(404, {"error": "quote_stale",
                                      "detail": "구성 부품 정보를 찾을 수 없습니다 — 견적을 다시 받아주세요"})
        chosen[it["part_type"]] = {**sp, "snap_price": it["price"],
                                   "snap_name": it["name"], "snap_sku": it["sku"]}
    return chosen


def _valid(chosen) -> list:
    return [s for s in SLOTS if not _slot_ok(s, chosen[s], chosen)]


def _chain_reason(alt_slot: str, chain: list, chosen: dict, alt: dict) -> str:
    for c in chain:
        if c["_slot"] == "POWER":
            return (f"이 {SLOT_KO[alt_slot]}는 필요 전력이 {alt.get('required_power_watt')}W라"
                    f" 현재 파워({chosen['POWER']['rated_watt']}W)로는 부족해요"
                    " — 파워를 함께 바꿔야 조립할 수 있어요.")
    names = " · ".join(SLOT_KO[c["_slot"]] for c in chain)
    return f"이 부품을 쓰려면 {names}을(를) 함께 바꿔야 조립할 수 있어요."


def _find_chain(slot, alt, chosen, pool_by_slot):
    """대안 적용 후 위반 슬롯을 가격 오름차순 교체로 해소(1패스). 실패·자기 슬롯 위반 → None."""
    trial = {**chosen, slot: alt}
    violations = _valid(trial)
    if not violations:
        return []
    if slot in violations:
        return None
    chain = []
    for vs in [s for s in SLOTS if s in violations]:
        fixed = False
        for cand in pool_by_slot.get(vs, []):
            if cand["product_code"] == trial[vs]["product_code"]:
                continue
            t2 = {**trial, vs: cand}
            if not _valid(t2):
                chain.append({"_slot": vs, "_from": trial[vs], "_to": cand})
                trial = t2
                fixed = True
                break
        if not fixed:
            return None
    return chain if not _valid(trial) else None


def _pool_ctx(conn):
    pool = _load_pool(conn)
    by_slot = {}
    for s in SLOTS:
        by_slot[s] = sorted([p for p in pool if p["part_type"] in SLOT_TYPES[s]],
                            key=lambda p: (p["sale_price"], p["product_code"]))
    return pool, by_slot, {p["product_code"] for p in pool}


@router.post("/candidates")
def candidates(body: SwapQuery):
    with engine.connect() as conn:
        snap = _load_snapshot(conn, body.session_id, body.tier)
        parts = snap["items"]["parts"]
        specs = _specs_by_code(conn, [it["product_code"] for it in parts])
        chosen = _chosen_from_parts(parts, specs)
        pool, by_slot, pool_codes = _pool_ctx(conn)

    current = [{"slot": it["part_type"], "product_code": it["product_code"],
                "sku": it["sku"], "name": it["name"], "price": it["price"],
                "unavailable": it["product_code"] not in pool_codes} for it in parts]
    slots = {}
    for s in SLOTS:
        alts = []
        for alt in by_slot.get(s, []):
            if alt["product_code"] == chosen[s]["product_code"]:
                continue
            chain = _find_chain(s, alt, chosen, by_slot)
            if chain is None:
                continue  # 해소 불가 — 미노출(UX-11 ①)
            entry = {"product_code": alt["product_code"], "sku": alt["sku"],
                     "name": alt["product_name"], "price": alt["sale_price"],
                     "price_diff": alt["sale_price"] - chosen[s]["snap_price"],
                     "tags": {"silent": bool(alt.get("tag_silent")),
                              "white": bool(alt.get("tag_white"))},
                     "chain": None, "chain_reason": None}
            if chain:
                entry["chain"] = [{
                    "slot": c["_slot"],
                    "from": {"sku": c["_from"].get("snap_sku") or c["_from"].get("sku"),
                             "name": c["_from"].get("snap_name") or c["_from"].get("product_name"),
                             "price": c["_from"].get("snap_price") or c["_from"].get("sale_price")},
                    "to": {"product_code": c["_to"]["product_code"], "sku": c["_to"]["sku"],
                           "name": c["_to"]["product_name"], "price": c["_to"]["sale_price"],
                           "price_diff": c["_to"]["sale_price"]
                                         - (c["_from"].get("snap_price") or c["_from"].get("sale_price"))},
                } for c in chain]
                entry["chain_reason"] = _chain_reason(s, chain, chosen, alt)
            alts.append(entry)
        slots[s] = {"alternatives": alts, "empty": not alts,
                    "empty_reason": "지금 판매 중인 재고에 이 부품의 대안이 없어요" if not alts else None}
    return {"session_id": body.session_id, "tier": body.tier,
            "snapshot_id": snap["snapshot_id"], "total": snap["total_amount"],
            "generated_at": snap["created_at"].isoformat(),
            "current": current, "compat": snap["items"].get("compat"), "slots": slots}


@router.post("/apply")
def apply(body: ApplyBody):
    if not body.changes:
        raise HTTPException(400, "변경할 부품이 없습니다")
    ch_by_slot = {}
    for c in body.changes:
        if c.slot not in SLOTS or c.slot in ch_by_slot:
            raise HTTPException(400, f"잘못된 변경 슬롯: {c.slot}")
        ch_by_slot[c.slot] = c.product_code
    with engine.begin() as conn:
        snap = _load_snapshot(conn, body.session_id, body.tier)
        parts = snap["items"]["parts"]
        specs = _specs_by_code(conn, [it["product_code"] for it in parts])
        chosen = _chosen_from_parts(parts, specs)
        pool, by_slot, pool_codes = _pool_ctx(conn)
        live = {p["product_code"]: p for p in pool}

        for slot, code in ch_by_slot.items():
            alt = live.get(code)
            if alt is None or alt["part_type"] not in SLOT_TYPES[slot]:
                raise HTTPException(409, {"error": "swap_soldout",
                                          "detail": "방금 그 대안이 품절됐어요 — 목록을 새로고침해 주세요"})
            chosen[slot] = alt
        violations = _valid(chosen)
        if violations:
            raise HTTPException(409, {"error": "incompatible", "violations": violations,
                                      "detail": "이 조합은 조립할 수 없어요 — " +
                                                " · ".join(SLOT_KO[v] for v in violations) + " 재검토 필요"})

        # 라인 재조립 — 비변경=스냅샷 그대로, 변경=라이브
        new_parts = []
        for it in parts:
            s = it["part_type"]
            if s in ch_by_slot:
                p = chosen[s]
                new_parts.append({"part_type": s, "product_code": p["product_code"],
                                  "sku": p["sku"], "name": p["product_name"],
                                  "price": p["sale_price"]})
            else:
                new_parts.append(it)
        total = sum(it["price"] for it in new_parts)
        compat = build_compat(chosen)
        reasons = (snap["items"].get("reasons") or []) + ["고객 부품 변경 반영 (S3)"]
        sid = conn.execute(text(
            "INSERT INTO quote_snapshots (session_id, quote_type, items, companion, total_amount)"
            " VALUES (:s, :t, CAST(:it AS JSONB), CAST(:co AS JSONB), :ta) RETURNING snapshot_id"),
            {"s": body.session_id, "t": body.tier,
             "it": json.dumps({"parts": new_parts, "compat": compat, "reasons": reasons}),
             "co": json.dumps(snap["companion"]) if snap["companion"] is not None else None,
             "ta": total}).scalar()
    return {"snapshot_id": sid, "items": new_parts, "total": total, "compat": compat,
            "generated_at": datetime.now().isoformat()}
