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
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from . import access_gate, mall, visitor
from .auth import current_operator      # 관리자 「인계 기록」은 세션으로 본다(열쇠가 아니라)
from .customer_auth import current_member
from .db import engine
from .product_name import display_name

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)      # 로그 문자열은 ASCII 기호만 (서버 stdout 이 cp949)

ASSEMBLY_CODE = 92983          # 몰 「제작 공임1」 — 금액을 우리가 정하지 않는다
# 2026-08-17 사장님 확정: 「3시간」 안정성 테스트(고객 화면과 같은 문구). **앞으로만** 바뀐다 —
# 이 값은 인계를 만들 때 `handoff_items.name_snap` 에 복사되고, 과거 인계를 읽는 자리는
# 전부 그 스냅샷을 읽는다(`api/admin_ui_handoff_log.py` L203·249 · 이 파일 L233).
# 기존 3건은 옛 이름을 그대로 들고 있다 — 원장은 당시와 같은 말을 해야 한다.
ASSEMBLY_NAME = "전문가 조립 · 선정리 · 3시간 검사"


class PeriphSel(BaseModel):
    code: int
    qty: int = 1


class HandoffBody(BaseModel):
    session_id: int
    tier: str
    periph: list[PeriphSel] = []
    # ⚠ 이 줄이 없던 동안 화면이 보내는 열쇠를 **Pydantic 이 조용히 버렸다**(extra='ignore').
    #   서버는 200 을 주고 화면은 막힌 줄 알았다 — 「받는 자리가 없으면 안 보낸 것과 같다」.
    access_key: str | None = None


def _no(conn) -> str:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('handoff_no'))"))
    seq = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(substring(handoff_no FROM 4) AS INTEGER)), 1000) + 1"
        " FROM handoffs WHERE handoff_no ~ '^HO-[0-9]+$'")).scalar()
    return "HO-%d" % seq


@router.post("/handoff")
def create_handoff(body: HandoffBody, request: Request, response: Response,
                   k: str | None = None):
    """견적을 인계 원장에 남기고, 쇼핑몰 장바구니에 담을 목록을 돌려준다.

    ■ 접근 게이트 (2026-08-17 사장님 확정 — 쓰기라 급했다)
      `session_id` 는 연속 정수다. 막기 전에는 남의 번호로 **남의 견적을 몰에 넘길 수**
      있었고, 그 사실이 `handoffs` 원장에 남았다. 응답의 `cart`·`changed` 에는 남의
      부품명·가격이 전부 실려 나갔다 — 읽기 유출과 쓰기 유출이 한 경로에 겹쳐 있었다.

      확인은 `access_gate.require_session_owner()` 하나가 한다 — `recommend/explain`·
      `swap/apply` 와 **같은 함수·같은 열쇠**다(새 장치를 만들지 않았다).

    ■ ⚠ 검사를 «가장 먼저» 둔다
      아래로 내려가면 `_no(conn)` 가 채번하고 `handoffs`·`handoff_items` 에 INSERT 한다.
      검사가 그 뒤에 오면 막아도 원장에 흔적이 남는다. 몰 가격 재확인(외부 요청)도
      이 검사 뒤에 있어야 남의 번호로 바깥 요청을 유발할 수 없다.

    응답 규약(추가분)
      403 {detail:{error:"forbidden", reason:"access_key_missing|access_key_mismatch|
                    no_access_key", detail}}
      503 {detail:{error:"gate_unavailable", table:"consult_sessions"}}  0055 미적용
      ⚠ 기존 400·404·409(티어·견적 없음·결제 모드·주변기기)는 그대로다.
    """
    if body.tier not in ("value", "recommend", "highend"):
        raise HTTPException(400, "알 수 없는 티어: %s" % body.tier)

    provided = body.access_key or access_gate.key_from_request(request, k)
    with engine.begin() as conn:
        # ⚠ 채번·INSERT·몰 조회 전. 여기서 막으면 원장에 아무것도 남지 않는다.
        access_gate.require_session_owner(
            conn, body.session_id, provided,
            what="handoff.create", not_found_detail="그 상담을 찾을 수 없습니다")

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
        # 인계 기록의 「추측 못 할 열쇠」 (2026-08-17 사장님 확정).
        # `handoff_no` 는 MAX+1 순번(HO-1001,1002,1003)이라 번호만으로는 못 막는다.
        # 스키마(0055)가 아직 없으면 열쇠 없이 만들고, 그 행은 링크로 열 수 없다(403).
        gate_on = access_gate.column_ready(conn, "handoffs")
        access_key = access_gate.new_key() if gate_on else None
        params = {"no": no, "s": body.session_id, "snap": snap["snapshot_id"], "t": body.tier,
                  "m": member_id, "u": uid, "tq": total_quoted, "tm": total_mall,
                  "chk": checked_all, "ch": len(changed),
                  "note": json.dumps({"unknown": [l["code"] for l in unknown]},
                                     ensure_ascii=False) if unknown else None}
        cols = ("handoff_no, session_id, snapshot_id, quote_type, member_id, user_id,"
                " total_quoted, total_mall, price_checked, changed_cnt, soldout_cnt,"
                " status, note")
        vals = ":no, :s, :snap, :t, :m, :u, :tq, :tm, :chk, :ch, 0, '인계', :note"
        if gate_on:
            cols, vals = cols + ", access_key", vals + ", :ak"
            params["ak"] = access_key
        hid = conn.execute(text(
            f"INSERT INTO handoffs ({cols}) VALUES ({vals}) RETURNING handoff_id"),
            params).scalar()
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
        # 이 인계 기록을 여는 열쇠. **이 응답을 받은 쪽에만** 간다(로그에는 찍지 않는다).
        # null 이면 게이트 스키마 미적용이고, 그 기록은 링크로 열 수 없다.
        "access_key": access_key,
        # 사장님 확정: "인계 기록을 링크로 열 수 있게 한다". 열쇠를 실은 완성 링크다.
        "record_url": ("/api/handoff/%s?k=%s" % (no, access_key)) if access_key else None,
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
def get_handoff(handoff_no: str, request: Request, k: str | None = None):
    """인계 한 건 조회 — 완료 화면과 관리자 「인계 기록」이 함께 쓴다.

    ■ 접근 게이트 (2026-08-17 사장님 확정)
      이 경로는 `current_member()`·`current_operator()` 를 **한 번도 부르지 않고** 전체를
      돌려주고 있었다. `handoff_no` 는 순번(HO-1001,1002,1003)이라 남의 것을 세어서
      맞힐 수 있었다. 여는 길은 둘뿐이다:
        ① 열쇠      `?k=<access_key>` 또는 `X-Access-Key` 헤더 — 인계 생성 응답이 준 값
        ② 운영자    관리자 세션(`current_operator()`) — 「인계 기록」 화면의 경로
      둘 다 아니면 403. 열쇠는 **응답에 되싣지 않는다**(CANON §2-5) — 받을 자격이 있는
      쪽은 이미 갖고 있고, 되실으면 화면 캡처·로그로 새어 나간다.

    응답 규약
      200 {handoff, items}   (`handoff.access_key` 는 «항상» 제거하고 내려보낸다)
      403 {error:"forbidden", reason:"access_key_missing|access_key_mismatch|no_access_key"}
      404                    그 번호의 인계 기록이 없음
      503 {error:"gate_unavailable"}  마이그레이션 0055 미적용 — 운영자 세션은 그래도 통과한다
          (관리자 화면을 스키마 사정으로 멈추지 않는다. 열쇠 경로만 못 연다)
    """
    provided = access_gate.key_from_request(request, k)
    is_operator = current_operator() is not None
    with engine.connect() as conn:
        gate_on = access_gate.column_ready(conn, "handoffs")
        if not gate_on and not is_operator:
            raise access_gate.gate_unavailable("handoffs")
        h = conn.execute(text(
            "SELECT * FROM handoffs WHERE handoff_no=:n"), {"n": handoff_no}).mappings().first()
        if h is None:
            raise HTTPException(404, "인계 기록이 없습니다")
        if not is_operator:
            stored = h.get("access_key")
            if not stored:
                log.info("[handoff] denied no=%s: stored key is NULL (pre-gate row)"
                         " provided=%s", handoff_no, "yes" if provided else "no")
                raise access_gate.forbidden(
                    "no_access_key", "게이트 도입 이전 인계 기록이라 열쇠가 없습니다")
            if not access_gate.matches(stored, provided):
                log.info("[handoff] denied no=%s: key mismatch provided=%s",
                         handoff_no, "yes" if provided else "no")
                raise access_gate.forbidden(
                    "access_key_mismatch" if provided else "access_key_missing",
                    "이 인계 기록의 열쇠가 아닙니다 - 본인 링크로 다시 열어주세요")
        items = conn.execute(text(
            "SELECT line_no, product_code, item_kind, part_type, name_snap,"
            "       price_quoted, price_mall, qty, mall_status"
            "  FROM handoff_items WHERE handoff_id=:h ORDER BY line_no"),
            {"h": h["handoff_id"]}).mappings().all()
    out = dict(h)
    out.pop("access_key", None)     # 열쇠를 되싣지 않는다 — 가진 쪽은 이미 갖고 있다
    return {"handoff": out, "items": [dict(r) for r in items]}
