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
v1 제외: 예산 재판정(사용자 명시 선택 — 가격차로 정직).
교체 기록(swap_event_logs)은 슬라이스 46에서 시작한다 — 미뤘던 이유(레거시 users FK)는
user_id를 채우지 않고 session_id·slot·price_delta로 맥락을 남기는 방식(0013)으로 해소했다.
스왑은 게스트도 하므로 주체를 지어내지 않는다.
"""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response

from . import access_gate   # 소유자 확인의 단일 원천 — 여기서 다시 만들지 않는다
from . import visitor
from pydantic import BaseModel
from sqlalchemy import text

from .timeutil import iso, now_iso
from .db import engine
from .product_name import display_name   # 대안 제시도 고객이 보는 자리다
from .recommend import (check_rule_fields, SLOTS, SLOT_TYPES, _load_pool, _slot_ok, build_compat,
                        load_compat_rules, _cmp, _rule_applies)
from .taxonomy import SLOT_LABELS as SLOT_KO   # 단일 원천 — SSD를 여기만 "저장장치"로 쓰고 있었다

router = APIRouter(prefix="/api/swap")

# **호환 규칙이 참조하는 필드는 전부 여기 있어야 한다.** 하나라도 빠지면 그 규칙이
# NULL 불통과로 떨어져 **모든 대안이 사라진다**(대안 0건 = S3 부품 변경 무력).
# 실제로 슬라이스 39(socket_list)·43(form_factor_list) 추가 때 이 목록을 함께 늘리지
# 않아 전 슬롯 대안이 0이 됐고, 슬라이스 46에서야 발견했다 — 회귀에 스왑 항목을 넣은 이유다.
SPEC_COLS = ("socket, socket_list, mem_type, tdp_watt, rated_watt, required_power_watt,"
             " length_mm, gpu_max_mm, cooler_height_mm, cooler_tdp,"
             " radiator_rows, radiator_max_rows,"
             " form_factor, form_factor_list, tag_white, tag_silent")


class SwapQuery(BaseModel):
    session_id: int
    tier: str
    # ⚠ **기반 클래스에 둔다** — `ApplyBody` 가 이걸 상속한다. 파생에만 두면 이 클래스를
    #   쓰는 `candidates` 가 열쇠를 조용히 버린다(Pydantic extra='ignore'). 실제로
    #   `HandoffBody` 가 그 상태였다: 화면은 보냈는데 서버가 버리고 200 을 줬다.
    access_key: str | None = None


class Change(BaseModel):
    slot: str
    product_code: int


class ApplyBody(SwapQuery):
    changes: list[Change]
    # `access_key` 는 SwapQuery 에서 상속한다 — 여기서 다시 선언하지 않는다.


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
    """스냅샷 parts → 슬롯별 스펙 dict(_slot_ok·build_compat 입력). 스냅샷 가격 유지.

    ⚠ **SLOTS 8개 키를 전부 채운다** — 없는 슬롯은 None(미선택, `api/expert.py`의
    `chosen[slot] = None`과 같은 관례). 예전엔 parts에 있는 슬롯만 키로 넣었는데,
    S1 기본값이 '(선택 안 함)'으로 바뀐 뒤(2026-08-21) 빈 슬롯이 낀 스냅샷이 흔해졌고
    `_valid`·`_find_chain`·`candidates()`가 `for s in SLOTS: ... chosen[s]`로 8자리
    전부를 전제하고 있어 없는 키를 그대로 두면 KeyError로 500이 났다(실사고 재현·확인
    — session 7360 KeyError:'CPU' swap.py:186, session 7361 KeyError:'COOLER'
    swap.py:101). None으로라도 채워야 아래 `_valid`가 "미선택"과 "위반"을 구분한다.
    """
    chosen = {s: None for s in SLOTS}
    for it in parts:
        sp = specs.get(it["product_code"])
        if sp is None:
            raise HTTPException(404, {"error": "quote_stale",
                                      "detail": "구성 부품 정보를 찾을 수 없습니다 — 견적을 다시 받아주세요"})
        chosen[it["part_type"]] = {**sp, "snap_price": it["price"],
                                   "snap_name": it["name"], "snap_sku": it["sku"]}
    return chosen


def _partial_compat(chosen: dict, rules: dict) -> dict:
    """빈 슬롯(None)이 하나라도 있을 때의 판정 — `api/expert.py`의 `_partial_compat`과
    **같은 원칙**: 대상·참조 슬롯 중 하나라도 미선택이면 그 규칙은 pass=None(검증
    보류)이지 불통과가 아니다(CLAUDE.md "원천이 아직 답할 수 없는 것은 판정하지
    않는다"). `recommend.py`의 `_slot_ok`·`build_compat`은 8슬롯이 전부 dict라고
    전제해 None에서 AttributeError로 죽으므로 그대로 못 쓴다. `recommend.py`는
    고치지 않는다(담당 파일 밖) — expert.py가 이미 같은 이유로 이 판정 루프를 자기
    파일에 따로 둔 전례를 그대로 따른다(그 함수 주석: "엔진 정본에 새 공용 함수를
    늘리지 않고 각자 고친다" — 규칙 비교 `_cmp`·`_rule_applies`만 recommend.py 것을
    그대로 부른다).
    """
    checks, violations = [], []
    for slot in SLOTS:
        p = chosen[slot]
        for rule in rules.get(slot, ()):
            ref = chosen[rule["ref_slot"]]
            if p is None or ref is None:
                checks.append({"key": rule["rule_key"], "label": rule["label"], "pass": None,
                               "detail": "미선택 부품이 있어 이 항목은 검증을 보류합니다"})
                continue
            if not _rule_applies(rule, p):
                continue   # 겨냥하지 않은 부품(예: 라디에이터 규칙 vs 공랭) — build_compat과 동일
            v, r = p.get(rule["field"]), ref.get(rule["ref_field"])
            ok = _cmp(rule["op"], v, r)
            fmt = rule["detail_fmt"] or "{v} / {r}"
            checks.append({"key": rule["rule_key"], "label": rule["label"], "pass": ok,
                           "detail": fmt.replace("{v}", "—" if v is None else str(v))
                                         .replace("{r}", "—" if r is None else str(r))})
            if not ok:
                violations.append(slot)
    gpu, power = chosen.get("GPU"), chosen.get("POWER")
    headroom = (int(power["rated_watt"] / gpu["required_power_watt"] * 100)
                if gpu and power and power.get("rated_watt") and gpu.get("required_power_watt")
                else None)
    return {"power_headroom_pct": headroom, "checks": checks,
            "violations": sorted(set(violations))}


def _valid(chosen, rules) -> list:
    """위반 슬롯 목록. 빈 슬롯이 하나라도 있으면 `_partial_compat`(null-안전 경로)을
    쓴다 — 8슬롯이 전부 찬 기존 경로(대다수 · 7362 같은 정상 케이스)는 원래 코드를
    한 글자도 바꾸지 않는다(회귀 위험 최소화)."""
    if any(chosen[s] is None for s in SLOTS):
        return _partial_compat(chosen, rules)["violations"]
    return [s for s in SLOTS if not _slot_ok(s, chosen[s], chosen, rules)]


def _chain_reason(alt_slot: str, chain: list, chosen: dict, alt: dict) -> str:
    for c in chain:
        if c["_slot"] == "POWER":
            return (f"이 {SLOT_KO[alt_slot]}는 필요 전력이 {alt.get('required_power_watt')}W라"
                    f" 현재 파워({chosen['POWER']['rated_watt']}W)로는 부족해요"
                    " — 파워를 함께 바꿔야 조립할 수 있어요.")
    names = " · ".join(SLOT_KO[c["_slot"]] for c in chain)
    return f"이 부품을 쓰려면 {names}을(를) 함께 바꿔야 조립할 수 있어요."


def _find_chain(slot, alt, chosen, pool_by_slot, rules):
    """대안 적용 후 위반 슬롯을 가격 오름차순 교체로 해소(1패스). 실패·자기 슬롯 위반 → None."""
    trial = {**chosen, slot: alt}
    violations = _valid(trial, rules)
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
            if not _valid(t2, rules):
                chain.append({"_slot": vs, "_from": trial[vs], "_to": cand})
                trial = t2
                fixed = True
                break
        if not fixed:
            return None
    return chain if not _valid(trial, rules) else None


def _pool_ctx(conn):
    pool = _load_pool(conn)
    by_slot = {}
    for s in SLOTS:
        by_slot[s] = sorted([p for p in pool if p["part_type"] in SLOT_TYPES[s]],
                            key=lambda p: (p["sale_price"], p["product_code"]))
    return pool, by_slot, {p["product_code"] for p in pool}


@router.post("/candidates")
def candidates(body: SwapQuery, request: Request, k: str | None = None):
    """부품별 대안 목록 — **남의 견적 구성이 통째로 나오던 자리**(2026-08-17 사장님 확정).

    읽기지만 새는 것이 견적 전체다: `current`(부품명·가격·품절 여부) · `total` ·
    `compat`(호환 판정) · 슬롯별 대안과 연쇄 교체 근거. `explain` 이 막는 것과 같은 내용을
    이 경로가 열어 두고 있었다.

    ■ 이제 막을 수 있게 된 이유
      직전까지는 막으면 S3 가 **조용히 거짓 화면**이 됐다 — `s3-detail.html` 의 빈
      `catch` 가 실패를 삼켜 정적 목업 부품이 그대로 남았다. 화면이 열쇠를 싣고 빈
      `catch` 를 걷어내 사건별로 사유를 말하게 되면서 그 제약이 사라졌다.

    응답 규약(추가분) — `swap/apply` 와 같다
      403 {detail:{error:"forbidden", reason, detail}} · 503 {detail:{error:"gate_unavailable"}}
    """
    provided = body.access_key or access_gate.key_from_request(request, k)
    with engine.connect() as conn:
        access_gate.require_session_owner(
            conn, body.session_id, provided,
            what="swap.candidates", not_found_detail="그 상담을 찾을 수 없습니다")
        snap = _load_snapshot(conn, body.session_id, body.tier)
        parts = snap["items"]["parts"]
        specs = _specs_by_code(conn, [it["product_code"] for it in parts])
        chosen = _chosen_from_parts(parts, specs)
        pool, by_slot, pool_codes = _pool_ctx(conn)
        rules = load_compat_rules(conn)   # 엔진과 같은 규칙 원천(슬라이스 34)
    # 규칙이 참조하는 필드가 chosen(스냅샷 조인)에 실렸는지 확인 — 누락은 '대안 0건'이라는
    # 조용한 고장으로 나타난다. 경고로 드러낸다(슬라이스 46 전례).
    # None(미선택 슬롯)은 대표 샘플에서 뺀다 — check_rule_fields가 pool[0].keys()로
    # 필드 목록을 뽑으므로 None이 섞이면 AttributeError로 새 500이 생긴다.
    check_rule_fields([v for v in chosen.values() if v is not None], rules)

    current = [{"slot": it["part_type"], "product_code": it["product_code"],
                "sku": it["sku"], "name": it["name"], "price": it["price"],
                "unavailable": it["product_code"] not in pool_codes} for it in parts]
    slots = {}
    for s in SLOTS:
        if chosen[s] is None:
            # 아직 고르지 않은 자리 — 임의 부품으로 채우지 않는다(CLAUDE.md "모르는
            # 것을 지어내지 않는다"). "후보를 찾아봤는데 없다"(empty_reason 기존 문구)
            # 와는 사유가 달라 selected로 구분한다. 이 자리를 "채울" 후보 추천은
            # 스왑(교체)이 아니라 추가라 이번 회귀 수정 범위 밖으로 남긴다 — 지금
            # s3-detail.html도 C.current(채워진 슬롯)만 순회해 이 슬롯의 alternatives를
            # 아직 아무 데서도 읽지 않는다(2026-08-21 확인, mockups/mvp1/s3-detail.html
            # renderParts()).
            slots[s] = {"alternatives": [], "empty": True, "selected": False,
                        "empty_reason": "아직 선택하지 않은 부품이에요 — 먼저 골라야 대안을 보여드릴 수 있어요"}
            continue
        alts = []
        for alt in by_slot.get(s, []):
            if alt["product_code"] == chosen[s]["product_code"]:
                continue
            chain = _find_chain(s, alt, chosen, by_slot, rules)
            if chain is None:
                continue  # 해소 불가 — 미노출(UX-11 ①)
            entry = {"product_code": alt["product_code"], "sku": alt["sku"],
                     "name": display_name(alt["product_name"]), "price": alt["sale_price"],
                     "price_diff": alt["sale_price"] - chosen[s]["snap_price"],
                     "tags": {"silent": bool(alt.get("tag_silent")),
                              "white": bool(alt.get("tag_white"))},
                     "chain": None, "chain_reason": None}
            if chain:
                entry["chain"] = [{
                    "slot": c["_slot"],
                    "from": {"sku": c["_from"].get("snap_sku") or c["_from"].get("sku"),
                             # 스냅샷 이름은 그때 고객이 본 기록이라 손대지 않는다 — 파생은 카탈로그 쪽만
                             "name": c["_from"].get("snap_name") or display_name(c["_from"].get("product_name")),
                             "price": c["_from"].get("snap_price") or c["_from"].get("sale_price")},
                    "to": {"product_code": c["_to"]["product_code"], "sku": c["_to"]["sku"],
                           "name": display_name(c["_to"]["product_name"]), "price": c["_to"]["sale_price"],
                           "price_diff": c["_to"]["sale_price"]
                                         - (c["_from"].get("snap_price") or c["_from"].get("sale_price"))},
                } for c in chain]
                entry["chain_reason"] = _chain_reason(s, chain, chosen, alt)
            alts.append(entry)
        slots[s] = {"alternatives": alts, "empty": not alts, "selected": True,
                    "empty_reason": "지금 판매 중인 재고에 이 부품의 대안이 없어요" if not alts else None}
    return {"session_id": body.session_id, "tier": body.tier,
            "snapshot_id": snap["snapshot_id"], "total": snap["total_amount"],
            "generated_at": iso(snap["created_at"]),
            "current": current, "compat": snap["items"].get("compat"), "slots": slots}


@router.post("/apply")
def apply(body: ApplyBody, request: Request, response: Response, k: str | None = None):
    """부품 교체를 적용한다 — **남의 견적을 «바꿀» 수 있던 자리**(2026-08-17 사장님 확정).

    ■ 왜 이 경로가 제일 급했나
      `_load_snapshot` 은 `session_id`·`tier` 만 보고, `session_id` 는 연속 정수다
      (최근 10건 5872~5881). 즉 남의 번호를 세어 맞히면 **읽는 데서 그치지 않았다** —
      이 함수가 `swap_event_logs` 를 남기고 **새 `quote_snapshots` 행을 INSERT** 한다.
      다음 견적 조회·인계는 «최신 스냅샷»을 읽으므로, 진짜 주인이 자기가 고르지 않은
      구성을 보고 그대로 결제까지 갈 수 있었다. 읽기 유출보다 위험한 쓰기 유출이다.

    ■ 새 장치를 만들지 않았다
      `POST /api/recommend/explain` 과 **같은 함수**(`access_gate.require_session_owner`)를
      부른다. 열쇠도 같은 것 — 견적 응답이 준 `access_key` 하나다.

    응답 규약(추가분)
      403 {detail:{error:"forbidden", reason:"access_key_missing|access_key_mismatch|
                    no_access_key", detail}}
      503 {detail:{error:"gate_unavailable", table:"consult_sessions"}}  0055 미적용
      ⚠ 기존 400·404·409(잘못된 슬롯·견적 없음·품절·호환 불가)는 그대로다.
    """
    if not body.changes:
        raise HTTPException(400, "변경할 부품이 없습니다")
    ch_by_slot = {}
    for c in body.changes:
        if c.slot not in SLOTS or c.slot in ch_by_slot:
            raise HTTPException(400, f"잘못된 변경 슬롯: {c.slot}")
        ch_by_slot[c.slot] = c.product_code
    provided = body.access_key or access_gate.key_from_request(request, k)
    with engine.begin() as conn:
        # ⚠ 원장에 손대기 «전에» 막는다 — 검사가 INSERT 뒤에 오면 막아도 이미 남는다.
        access_gate.require_session_owner(
            conn, body.session_id, provided,
            what="swap.apply", not_found_detail="그 상담을 찾을 수 없습니다")
        uid = visitor.resolve(conn, request, response)   # 교체 이벤트를 사람에 잇는다
        snap = _load_snapshot(conn, body.session_id, body.tier)
        parts = snap["items"]["parts"]
        specs = _specs_by_code(conn, [it["product_code"] for it in parts])
        chosen = _chosen_from_parts(parts, specs)
        pool, by_slot, pool_codes = _pool_ctx(conn)
        # 규칙은 요청마다 로드한다(엔진과 같은 원천). 슬라이스 40에서 이 줄을 '중복'으로 보고
        # 지웠다가 apply가 NameError로 죽었다 — candidates와 apply는 각자 필요하다.
        rules = load_compat_rules(conn)
        live = {p["product_code"]: p for p in pool}

        for slot, code in ch_by_slot.items():
            alt = live.get(code)
            if alt is None or alt["part_type"] not in SLOT_TYPES[slot]:
                raise HTTPException(409, {"error": "swap_soldout",
                                          "detail": "방금 그 대안이 품절됐어요 — 목록을 새로고침해 주세요"})
            chosen[slot] = alt
        violations = _valid(chosen, rules)
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
                                  "sku": p["sku"], "name": display_name(p["product_name"]),
                                  "price": p["sale_price"]})
            else:
                new_parts.append(it)
        total = sum(it["price"] for it in new_parts)
        # 바꾸지 않은 슬롯이 여전히 미선택(None)일 수 있다 — build_compat은 8슬롯 전부
        # dict라고 전제해 None에서 AttributeError로 500이 난다(코드 확인으로 발견 —
        # apply는 원장에 쓰는 경로라 실호출로 재현하지 않았다). candidates()가 쓰는
        # 것과 같은 null-안전 경로(_partial_compat)로 넘긴다. 8슬롯이 전부 찬 기존
        # 경로는 그대로 build_compat을 쓴다(원래 코드 그대로 — 회귀 위험 없음).
        if any(chosen[s] is None for s in SLOTS):
            pc = _partial_compat(chosen, rules)
            compat = {"power_headroom_pct": pc["power_headroom_pct"], "checks": pc["checks"]}
        else:
            compat = build_compat(chosen, rules)

        # 교체 사실을 원장에 남긴다(슬라이스 46) — 그동안 swap_event_logs는 0행이었다.
        # 이 기록이 "고객이 어떤 추천을 어떤 부품으로 바꿨나"의 유일한 원천이고,
        # 추천 기준을 고칠 근거가 된다(부품 교체 기록 화면).
        before_by_slot = {it["part_type"]: it for it in parts}
        for slot, code in ch_by_slot.items():
            was = before_by_slot.get(slot) or {}
            delta = None
            if was.get("price") is not None:
                delta = chosen[slot]["sale_price"] - was["price"]
            conn.execute(text(
                "INSERT INTO swap_event_logs (from_product, to_product, session_id, slot,"
                " price_delta, user_id) VALUES (:fp, :tp, :s, :sl, :pd, :uid)"),
                {"fp": was.get("product_code"), "tp": code, "s": body.session_id,
                 "sl": slot, "pd": delta, "uid": uid})
        reasons = (snap["items"].get("reasons") or []) + ["고객 부품 변경 반영 (S3)"]
        sid = conn.execute(text(
            "INSERT INTO quote_snapshots (session_id, quote_type, items, companion, total_amount)"
            " VALUES (:s, :t, CAST(:it AS JSONB), CAST(:co AS JSONB), :ta) RETURNING snapshot_id"),
            {"s": body.session_id, "t": body.tier,
             "it": json.dumps({"parts": new_parts, "compat": compat, "reasons": reasons}),
             "co": json.dumps(snap["companion"]) if snap["companion"] is not None else None,
             "ta": total}).scalar()
    return {"snapshot_id": sid, "items": new_parts, "total": total, "compat": compat,
            "generated_at": now_iso()}
