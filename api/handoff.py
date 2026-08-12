# -*- coding: utf-8 -*-
"""S4 인계 — 견적을 팝콘PC 쇼핑몰로 넘긴다 (범위 결정 2026-08-11)

■ 무엇을 **하지 않는가** 가 이 모듈의 정의다
  결제하지 않는다 · 재고를 차감하지 않는다 · 배송지를 묻지 않는다 · 회원을 만들지 않는다.
  전부 쇼핑몰의 일이다. 팝콘AI 는 **신규 고객 유입 채널**이고 판매자가 아니다.

  `api/orders.py`(자체 결제)와 이 모듈은 **`ops_settings.pay` 스위치로 갈린다** —
  `own` 이면 주문, `mall` 이면 인계. 둘이 동시에 열리지 않는다.

■ 인계 직전에 몰 가격을 다시 본다 (사용자 결정 2026-08-11)
  2026-08-11 표본 10건 중 2건이 어긋나 있었다. HDD 는 189,000 원으로 안내 중인데
  실제는 194,100 원이었다 — **싸게 불러 놓고 넘기면 장바구니에서 신뢰가 깨진다.**
  그래서 넘기기 전에 확인하고, 다르면 **고객에게 말한다.** 조용히 바꾸지 않는다.

  못 읽은 건은 «확인 못 함»으로 남긴다. 견적 시점 가격을 사실인 양 넘기지 않는다.

■ 조립비는 몰 상품이다
  `pd_no=92983` 「제작 공임1」 30,000 원(2026-08-11 실측). 우리가 금액을 지어내지 않고
  몰의 상품 한 줄로 담는다 — 그래야 견적 합계와 몰 결제 금액이 맞는다.
"""
import json

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from . import mall, visitor
from .customer_auth import current_member
from .db import engine
from .product_name import display_name

router = APIRouter(prefix="/api")

ASSEMBLY_CODE = 92983          # 몰 「제작 공임1」 — 금액을 우리가 정하지 않는다
ASSEMBLY_NAME = "전문가 조립 · 선정리 · 24시간 검사"


class PeriphSel(BaseModel):
    code: int
    qty: int = 1


class HandoffBody(BaseModel):
    session_id: int
    tier: str
    periph: list[PeriphSel] = []


def _no(conn) -> str:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('handoff_no'))"))
    seq = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(substring(handoff_no FROM 4) AS INTEGER)), 1000) + 1"
        " FROM handoffs WHERE handoff_no ~ '^HO-[0-9]+$'")).scalar()
    return "HO-%d" % seq


@router.post("/handoff")
def create_handoff(body: HandoffBody, request: Request, response: Response):
    """견적을 인계 원장에 남기고, 쇼핑몰 장바구니에 담을 목록을 돌려준다."""
    if body.tier not in ("value", "recommend", "highend"):
        raise HTTPException(400, "알 수 없는 티어: %s" % body.tier)

    with engine.begin() as conn:
        ops = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all())
        if ops.get("pay") != "mall":
            raise HTTPException(409, {
                "error": "pay_mode_own",
                "detail": "결제가 자체 모드입니다 — 인계 불가(운영 전환은 관리자 설정)"})

        snap = conn.execute(text(
            "SELECT snapshot_id, items, companion, total_amount FROM quote_snapshots"
            " WHERE session_id=:s AND quote_type=:t ORDER BY snapshot_id DESC LIMIT 1"),
            {"s": body.session_id, "t": body.tier}).mappings().first()
        if snap is None:
            raise HTTPException(404, {"error": "quote_not_found",
                                      "detail": "견적 스냅샷이 없습니다 — 견적을 다시 받아주세요"})

        parts = snap["items"]["parts"]
        offered = {c["product_code"]: c
                   for c in (snap["companion"] or {}).get("offered", [])}
        periph = []
        for p in body.periph:
            if p.code not in offered:
                raise HTTPException(400, {"error": "periph_not_offered",
                                          "detail": "제안되지 않은 주변기기: %s" % p.code})
            periph.append((offered[p.code], p.qty))

        # ── 줄 세우기 — 부품 · 조립비 · 주변기기 ─────────────────────────
        lines = []
        for it in parts:
            lines.append({"code": it["product_code"], "kind": "core_part",
                          "part_type": it.get("part_type"),
                          "name": display_name(it["name"]),
                          "quoted": it["price"], "qty": 1})
        lines.append({"code": ASSEMBLY_CODE, "kind": "assembly_service", "part_type": None,
                      "name": ASSEMBLY_NAME, "quoted": None, "qty": 1})
        for c, q in periph:
            lines.append({"code": c["product_code"], "kind": "peripheral",
                          "part_type": c.get("part_type"),
                          "name": display_name(c["name"]),
                          "quoted": c["price"], "qty": q})

        # ── 몰 가격 재확인 ────────────────────────────────────────────
        got = mall.fetch_prices([l["code"] for l in lines])
        checked_all = bool(got) and all(v["ok"] for v in got.values())
        changed, unknown = [], []
        total_quoted = total_mall = 0
        for l in lines:
            g = got.get(l["code"]) or {}
            l["mall"] = g.get("price") if g.get("ok") else None
            # 조립비는 견적에 우리가 금액을 안 실었다 — 몰 값을 그대로 쓴다
            if l["quoted"] is None:
                l["quoted"] = l["mall"]
            if l["mall"] is None:
                l["status"] = "확인못함"
                unknown.append(l)
            elif l["quoted"] is not None and l["mall"] != l["quoted"]:
                l["status"] = "가격변동"
                changed.append(l)
            else:
                l["status"] = "확인됨"
            total_quoted += (l["quoted"] or 0) * l["qty"]
            total_mall += (l["mall"] if l["mall"] is not None else (l["quoted"] or 0)) * l["qty"]

        # ── 원장 ─────────────────────────────────────────────────────
        uid = visitor.resolve(conn, request, response)
        me = current_member()
        member_id = me["member_id"] if me else None
        if member_id:
            visitor.promote(conn, uid, member_id)

        no = _no(conn)
        hid = conn.execute(text(
            "INSERT INTO handoffs (handoff_no, session_id, snapshot_id, quote_type,"
            " member_id, user_id, total_quoted, total_mall, price_checked, changed_cnt,"
            " soldout_cnt, status, note)"
            " VALUES (:no, :s, :snap, :t, :m, :u, :tq, :tm, :chk, :ch, 0, '인계', :note)"
            " RETURNING handoff_id"),
            {"no": no, "s": body.session_id, "snap": snap["snapshot_id"], "t": body.tier,
             "m": member_id, "u": uid, "tq": total_quoted, "tm": total_mall,
             "chk": checked_all, "ch": len(changed),
             "note": json.dumps({"unknown": [l["code"] for l in unknown]},
                                ensure_ascii=False) if unknown else None}).scalar()
        for i, l in enumerate(lines, start=1):
            conn.execute(text(
                "INSERT INTO handoff_items (handoff_id, line_no, product_code, item_kind,"
                " part_type, name_snap, price_quoted, price_mall, qty, mall_status)"
                " VALUES (:h, :n, :c, :k, :pt, :nm, :pq, :pm, :q, :st)"),
                {"h": hid, "n": i, "c": l["code"], "k": l["kind"], "pt": l["part_type"],
                 "nm": l["name"], "pq": l["quoted"] or 0, "pm": l["mall"],
                 "q": l["qty"], "st": l["status"]})

    # ── 응답 — 화면이 그대로 쓸 모양 ──────────────────────────────────
    return {
        "handoff_no": no,
        "total_quoted": total_quoted,
        "total_mall": total_mall,
        "price_checked": checked_all,
        "changed": [{"code": l["code"], "name": l["name"],
                     "quoted": l["quoted"], "mall": l["mall"],
                     "diff": (l["mall"] or 0) - (l["quoted"] or 0)} for l in changed],
        "unknown": [{"code": l["code"], "name": l["name"]} for l in unknown],
        # 쇼핑몰 장바구니에 담을 목록. API 가 나오면 서버가 직접 담고 이 배열은 근거로만 쓴다
        "cart": [{"pd_no": l["code"], "amount": l["qty"],
                  "name": l["name"], "price": l["mall"] if l["mall"] is not None else l["quoted"]}
                 for l in lines],
        "cart_url": mall.BASE + "/shop/order_basket_list.html",
    }


@router.get("/handoff/{handoff_no}")
def get_handoff(handoff_no: str):
    """인계 한 건 조회 — 완료 화면과 관리자 「인계 기록」이 함께 쓴다."""
    with engine.connect() as conn:
        h = conn.execute(text(
            "SELECT * FROM handoffs WHERE handoff_no=:n"), {"n": handoff_no}).mappings().first()
        if h is None:
            raise HTTPException(404, "인계 기록이 없습니다")
        items = conn.execute(text(
            "SELECT line_no, product_code, item_kind, part_type, name_snap,"
            "       price_quoted, price_mall, qty, mall_status"
            "  FROM handoff_items WHERE handoff_id=:h ORDER BY line_no"),
            {"h": h["handoff_id"]}).mappings().all()
    return {"handoff": dict(h), "items": [dict(r) for r in items]}
