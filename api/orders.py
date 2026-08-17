"""S4 주문 확인·자체 결제 — 커머스 원장 첫 쓰기 (ERD §8 T7).

단일 트랜잭션: orders+order_items(스냅샷) → stock_reservations(hold) → 목업 PG 승인
→ hold converted + stock_movements(own_sale) 차감 → 결제완료.
실 PG 도입 시 분리 지점: 주문 생성(hold·접수)과 결제 확인(승인·차감)을 2엔드포인트로 —
stock_reservations(hold)가 존재하는 이유가 그 미래 분리다(§10.5).

원칙: 라인 가격은 전부 견적 스냅샷(quote_snapshots) 기준 — 클라이언트 가격을 신뢰하지 않고,
"고객에게 보여준 그대로"(원칙 6)를 원장에 남긴다. products는 재고·상태 검증에만 쓴다.
mall 주문 생성은 v1 제외(쇼핑몰 연동 없는 가짜 원장 — 인계 연출은 목업 폴백 존치).
회원(슬라이스 38): 세션이 있으면 세션 회원으로 귀속, 없으면 게스트 주문(email upsert 유지).
"""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response

from . import access_gate   # 소유자 확인의 단일 원천 — 여기서 다시 만들지 않는다
from . import visitor
from pydantic import BaseModel
from sqlalchemy import text

from .customer_auth import current_member
from .db import engine
from .product_name import display_name   # 품절 알림도 고객이 읽는다

router = APIRouter(prefix="/api")

ASSEMBLY_FEE = 30000
# 2026-08-17 사장님 확정: 안정성 테스트는 24시간이 아니라 **3시간**이다(고객 화면 12곳과 같은 문구).
# ⚠ **앞으로만 바뀐다** — 이 상수는 주문을 «만들 때» `order_items.name_snap` 에 «복사»되고
#   (아래 `add_item`), 과거 주문을 읽는 자리는 전부 그 스냅샷 컬럼을 읽는다
#   (`api/my_orders.py` L39-42 · `api/admin_orders.py` L98-101 · `api/admin_member_reviews.py` L45).
#   그래서 상수를 바꿔도 **이미 있는 17건은 옛 이름을 그대로 들고 있다** — 원장이 당시와
#   다른 말을 하지 않는다(`api/product_name.py` L34 「스냅샷·원장은 기록된 대로 보여준다」).
ASSEMBLY_NAME = "전문가 조립 · 선정리 · 3시간 검사"
VIA_MAP = {"카카오": "kakao", "네이버": "naver", "이메일": "email",
           "kakao": "kakao", "naver": "naver", "email": "email"}


class PeriphSel(BaseModel):
    code: int
    qty: int = 1


class MemberIn(BaseModel):
    nick: str
    email: str
    via: str = "email"


class ShippingIn(BaseModel):
    name: str
    phone: str
    addr: str


class OrderBody(BaseModel):
    session_id: int
    tier: str
    periph: list[PeriphSel] = []
    member: MemberIn
    shipping: ShippingIn
    method: str = "카드"
    # 견적 응답(`POST /api/recommend`)이 준 열쇠. 쿼리 `?k=`·헤더 `X-Access-Key` 로도 받는다.
    # ⚠ 이 줄이 «없으면» 화면이 보내도 Pydantic 이 조용히 버린다(extra='ignore') —
    #   `HandoffBody`·`SwapQuery` 가 실제로 그 상태였다(서버는 200 을 주고 화면은 막힌 줄 안다).
    access_key: str | None = None


@router.get("/ops")
def get_ops():
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all())


@router.post("/orders")
def create_order(body: OrderBody, request: Request, response: Response,
                 k: str | None = None):
    """자체 결제 주문 생성.

    ■ 접근 게이트 (2026-08-17 사장님 확정 — 커머스 원장을 여는 마지막 자리)
      `session_id` 는 연속 정수라, 막기 전에는 남의 번호로 **남의 견적을 주문할 수** 있었다.
      실측(전부 ROLLBACK): `pay=own` 으로 켠 상태에서 제3자가 피해자의 session_id 로 부르면
      **주문이 실제로 생겼다** — `orders` +1 · `order_items` +9 · `stock_reservations` +8 ·
      `stock_movements` +8 · `payments` +1, 재고까지 실제로 깎였고 응답에 피해자의 부품
      구성 9줄이 그대로 실렸다. 오늘 이 경로가 닫혀 있던 이유는 소유자 확인이 아니라
      **운영 스위치 하나**였다(`ops_settings.pay`). 스위치를 켜는 날 뚫려 있으면 그때는
      원장에 실주문이 남는다.

      확인은 `access_gate.require_session_owner()` 하나가 한다 — `recommend/explain`·
      `swap/candidates`·`swap/apply`·`handoff.create` 와 **같은 함수·같은 열쇠**다.

    ■ ⚠ 검사 자리 — 「운영 스위치 «다음», 쓰기 «전»」
      **`pay_mode_mall`(409)보다 앞에 두지 않는다.** 앞에 두면 지금처럼 몰 인계 모드일 때
      「자체 결제가 꺼져 있다」가 아니라 403 이 나가 **오늘 동작이 바뀐다** — 화면은 결제
      모드 안내를 못 하고 열쇠 탓으로 오해한다.
      **재고 예약·원장·주문/결제 INSERT 보다는 앞이다.** 뒤에 두면 막아도 흔적이 남는다.

    응답 규약(추가분)
      403 {detail:{error:"forbidden", reason:"access_key_missing|access_key_mismatch|
                    no_access_key", detail}}
      503 {detail:{error:"gate_unavailable", table:"consult_sessions"}}  0055 미적용
      ⚠ 기존 400·404·409(티어·견적 없음·결제 모드·품절·주변기기)는 그대로다.
    """
    if body.tier not in ("value", "recommend", "highend"):
        raise HTTPException(400, f"알 수 없는 티어: {body.tier}")
    provided = body.access_key or access_gate.key_from_request(request, k)
    with engine.begin() as conn:
        ops = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all())
        if ops.get("pay") != "own":
            raise HTTPException(409, {"error": "pay_mode_mall",
                                      "detail": "결제가 쇼핑몰 인계 모드입니다 — 자체 결제 불가(운영 전환은 관리자 설정)"})

        # 운영 스위치 «다음» · 재고 예약과 원장 «전».
        access_gate.require_session_owner(
            conn, body.session_id, provided,
            what="orders.create", not_found_detail="그 상담을 찾을 수 없습니다")

        snap = conn.execute(text(
            "SELECT items, companion, total_amount FROM quote_snapshots"
            " WHERE session_id=:s AND quote_type=:t ORDER BY snapshot_id DESC LIMIT 1"),
            {"s": body.session_id, "t": body.tier}).mappings().first()
        if snap is None:
            raise HTTPException(404, {"error": "quote_not_found",
                                      "detail": "견적 스냅샷이 없습니다 — 견적을 다시 받아주세요"})
        parts = snap["items"]["parts"]
        offered = {c["product_code"]: c for c in (snap["companion"] or {}).get("offered", [])}
        periph_lines = []
        for p in body.periph:
            if p.code not in offered:
                raise HTTPException(400, {"error": "periph_not_offered",
                                          "detail": f"제안되지 않은 주변기기: {p.code}"})
            periph_lines.append((offered[p.code], p.qty))

        # 재고 검증 — 실물 전 품목 잠금(정렬 순서 고정으로 교착 방지)
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('order_no'))"))
        codes = sorted([it["product_code"] for it in parts] + [c["product_code"] for c, _ in periph_lines])
        stock = {r["product_code"]: r for r in conn.execute(text(
            "SELECT product_code, sku, product_name, status, stock_qty FROM products"
            " WHERE product_code = ANY(:codes) ORDER BY product_code FOR UPDATE"),
            {"codes": codes}).mappings().all()}
        need = {}
        for it in parts:
            need[it["product_code"]] = need.get(it["product_code"], 0) + 1
        for c, q in periph_lines:
            need[c["product_code"]] = need.get(c["product_code"], 0) + q
        soldout = [{"sku": stock[pc]["sku"], "name": display_name(stock[pc]["product_name"])}
                   for pc, q in need.items()
                   if pc not in stock or stock[pc]["status"] != "판매중" or stock[pc]["stock_qty"] < q]
        if soldout:
            raise HTTPException(409, {"error": "soldout", "items": soldout})

        # 회원 — **세션이 있으면 세션 회원**(확인된 신원). 없으면 게스트 주문으로
        # email upsert를 유지한다(슬라이스 38: 견적을 보려고 가입을 강요하지 않는다는
        # A-10 결정을 인증이 뒤집지 않는다). 게스트 주문의 이메일은 자기신고값이며,
        # 그 주문 내역은 같은 이메일로 로그인해야 MY에서 보인다.
        me = current_member()
        if me is not None:
            member_id = me["member_id"]
        else:
            member_id = conn.execute(text(
                "SELECT member_id FROM members WHERE email=:e"),
                {"e": body.member.email}).scalar()
            if member_id is None:
                member_id = conn.execute(text(
                    "INSERT INTO members (email, nickname, joined_via) VALUES (:e, :n, :v)"
                    " RETURNING member_id"),
                    {"e": body.member.email, "n": body.member.nick,
                     "v": VIA_MAP.get(body.member.via, "email")}).scalar()

        # 발번 — 시드 형식 ORD-##### 승계 (advisory lock으로 직렬화, UNIQUE 백스톱)
        seq = conn.execute(text(
            "SELECT COALESCE(MAX(CAST(substring(order_no FROM 5) AS INTEGER)), 84000) + 1"
            " FROM orders WHERE order_no ~ '^ORD-[0-9]+$'")).scalar()
        order_no = f"ORD-{seq}"

        total = snap["total_amount"] + ASSEMBLY_FEE + sum(c["price"] * q for c, q in periph_lines)
        # 방문자 키 — 이 주문을 앞선 상담·클릭과 잇는 실. 없으면 NULL 로 남고 주문은 진행된다.
        uid = visitor.resolve(conn, request, response)
        visitor.promote(conn, uid, member_id)      # 익명으로 상담하다 가입해도 앞 행동이 이어진다
        order_id = conn.execute(text(
            "INSERT INTO orders (order_no, member_id, channel, status, total_amount,"
            " ops_snapshot, shipping_snap, session_id, user_id)"
            " VALUES (:no, :m, 'own', '접수', :t, CAST(:ops AS JSONB), CAST(:ship AS JSONB), :sid, :uid)"
            " RETURNING order_id"),
            {"no": order_no, "m": member_id, "t": total, "uid": uid,
             "ops": json.dumps(ops),
             "ship": json.dumps({"name": body.shipping.name, "phone": body.shipping.phone,
                                 "addr": body.shipping.addr}),
             "sid": body.session_id}).scalar()
        conn.execute(text(
            "INSERT INTO order_events (order_id, from_state, to_state, actor)"
            " VALUES (:o, NULL, '접수', '고객')"), {"o": order_id})

        # 라인 — 전부 스냅샷 가격
        def add_item(pc, kind, name, price, spec, qty=1):
            conn.execute(text(
                "INSERT INTO order_items (order_id, product_code, item_kind, name_snap, price_snap, spec_snap, qty)"
                " VALUES (:o, :pc, :k, :n, :p, CAST(:s AS JSONB), :q)"),
                {"o": order_id, "pc": pc, "k": kind, "n": name, "p": price,
                 "s": json.dumps(spec) if spec else None, "q": qty})
        for it in parts:
            add_item(it["product_code"], "core_part", it["name"], it["price"],
                     {"part_type": it["part_type"], "sku": it["sku"]})
        add_item(None, "assembly_service", ASSEMBLY_NAME, ASSEMBLY_FEE, None)
        for c, q in periph_lines:
            add_item(c["product_code"], "peripheral", c["name"], c["price"],
                     {"part_type": c["part_type"], "sku": c["sku"], "spec": c.get("spec")}, q)

        # hold → 목업 PG 승인 → 차감 전환 (실 PG 시 이 지점에서 2단계 분리)
        for pc, q in need.items():
            conn.execute(text(
                "INSERT INTO stock_reservations (order_id, product_code, qty, status, expires_at)"
                " VALUES (:o, :pc, :q, 'held', now() + interval '1 day')"),
                {"o": order_id, "pc": pc, "q": q})
        pg_ref = f"TX-{seq}"
        conn.execute(text(
            "INSERT INTO payments (order_id, pay_mode, method, pg_ref, amount, status, paid_at)"
            " VALUES (:o, 'own', :m, :ref, :a, '승인', now())"),
            {"o": order_id, "m": body.method, "ref": pg_ref, "a": total})
        conn.execute(text(
            "UPDATE stock_reservations SET status='converted' WHERE order_id=:o"), {"o": order_id})
        for pc, q in need.items():
            conn.execute(text(
                "INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id)"
                " VALUES (:pc, 'own_sale', :d, 'order', :o)"),
                {"pc": pc, "d": -q, "o": order_id})
            conn.execute(text(
                "UPDATE products SET stock_qty = stock_qty - :q, updated_at=now()"
                " WHERE product_code=:pc"), {"q": q, "pc": pc})
        conn.execute(text(
            "UPDATE orders SET status='결제완료' WHERE order_id=:o"), {"o": order_id})
        conn.execute(text(
            "INSERT INTO order_events (order_id, from_state, to_state, actor)"
            " VALUES (:o, '접수', '결제완료', 'PG(목업)')"), {"o": order_id})

        lines = [{"kind": "core_part", "code": it["product_code"], "sku": it["sku"],
                  "name": it["name"], "price": it["price"], "qty": 1} for it in parts]
        lines.append({"kind": "assembly_service", "code": None, "sku": None,
                      "name": ASSEMBLY_NAME, "price": ASSEMBLY_FEE, "qty": 1})
        lines += [{"kind": "peripheral", "code": c["product_code"], "sku": c["sku"],
                   "name": c["name"], "price": c["price"], "qty": q} for c, q in periph_lines]
        return {"order_id": order_id, "order_no": order_no, "status": "결제완료",
                "total": total, "held": len(need),
                "payment": {"method": body.method, "pg_ref": pg_ref}, "lines": lines}
