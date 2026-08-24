"""MY-020 고객 주문 내역·환불 접수 — 고객 축의 원장 열람 + 환불 원장 첫 기록.

인증: email 쿼리 파라미터 = mock 인증(localStorage popcorn-member 기반, 로컬 데모 한정 수용).
실 인증(세션·토큰)은 별도 슬라이스. 미가입 이메일은 items:[] 정직 빈 목록.

환불 접수(POST /refunds): 접수만 기록(refunds 행 = 원장) — 주문 상태는 불변.
고객 접수 즉시 관리자 주문·배송 화면의 상태 전이가 잠긴다(admin_orders._guard_refund 409).
접수 가능 상태: 결제완료(주문 취소)·조립중(주문 취소)·배송중(환불)·완료(반품·교환, 활성 환불 없을 때).
이관(ADM-CLM-010): reason_detail 저장 컬럼·부분 환불·접수 철회(현재 불가 — 접수 주문은 활성 잠금).

고객 쓰기 잠금(2026-08-20, 지인·테스터 오픈 준비): 환불 접수는 `customer_write_lock`
스위치가 켜져 있으면 403으로 거부된다 — 근거·켜는 법은 그 모듈 docstring 참조.
기본은 꺼짐(지금 동작 그대로). ⚠ `ops_snapshot`의 `refund`(own/mall)와는 다른 축이다 —
그건 접수된 건을 누가 처리하는지를 정할 뿐 접수 자체를 막지 않는다(아래 create_refund
실측 그대로).

■ 주문 원장에 인계(handoffs)도 섞는다 (2026-08-24, customer-audit-2026-08-24.md §1-3 해소)
  my-orders.html은 "주문 원장은 결제 방식(자체/쇼핑몰 인계)과 무관하게 항상 여기에 남습니다"
  라고 약속하는데, 지금 운영 모드(ops_settings.pay='mall')에서는 정상 경로 고객 전원이
  orders에 단 한 줄도 안 남는다 — 인계는 orders를 쓰지 않는다(api/handoff.py 범위 결정:
  결제·재고 차감이 없어 "주문"이 아니라는 판단 그대로). 화면의 약속과 실제 조회 범위가
  어긋나 있던 것 — 그래서 이 API가 orders와 handoffs를 **합쳐** 시각순으로 돌려준다.
  각 항목은 "kind":"order"|"handoff"로 구분되고, order 항목의 필드·의미는 한 글자도
  바뀌지 않는다(화면·회귀가 이미 그 모양을 쓴다) — handoff 항목은 더 작은 별도 필드 집합.

  회원 경계(무엇이 "이 회원의 인계"인가 — api/handoff.py·api/visitor.py 실코드 기준):
    ① handoffs.member_id가 직접 채워진 것 — 인계 시점에 이미 로그인 상태였던 경우
    ② handoffs.user_id가 이 회원의 members.user_id로 승격된 것 — 익명으로 인계한 뒤
       **같은 브라우저**로 나중에 로그인하면 api/visitor.py의 promote()가 그 방문자 키를
       회원에 붙인다(api/customer_auth.py:199, 로그인할 때마다 실행).
  ⚠ **①·② 어느 쪽으로도 안 이어지는 인계가 있다 — 지어내지 않는다.** 다른 브라우저로
  로그인했거나 쿠키가 지워졌으면 익명 인계와 회원을 이을 방법이 db 스키마에 없다
  (handoffs에 회원 쪽 FK 제약도, 이메일 같은 신원 단서도 없다 — 실측: db/migrations/
  versions/0042_handoffs.py). 2026-08-24 실측으로 지금 handoffs 6건 전부가 member_id
  NULL이고 어느 회원의 user_id와도 안 이어진다(테스트 세션들이라 아무도 그 방문자
  쿠키로 다시 로그인한 적이 없다) — 그래서 이 코드가 배포돼도 "당장 눈에 보이는 인계"는
  0건일 수 있다. 그건 이 쿼리의 결함이 아니라 **지금 데이터의 실제 상태**다.

■ 결제 내역(my_payments.py)에는 인계를 넣지 않았다 — 판단 근거는 그 파일 docstring 참고.
"""
from datetime import timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import mall
from .timeutil import iso
from .admin_orders import STEP, _item_label, refund_label
from .customer_auth import require_member
from .customer_write_lock import write_locked, REASON as WRITE_LOCK_REASON
from .db import engine

router = APIRouter(prefix="/api/my")

REASONS = ("단순 변심", "초기 불량", "오배송·구성 오류", "기타")
ACTIVE_REFUND = ("접수", "검토", "수거·처리")

# 인계 항목의 "몰에서 확인하는 경로" — 인계 시 담아준 장바구니와 같은 페이지
# (api/handoff.py의 cart_url과 동일한 값). handoff마다 다른 딥링크가 아니다 — 몰이
# 우리 handoff_no를 모르고, 인계 시점의 access_key는 CANON §2-5(비밀값 재노출 금지)에
# 따라 생성 응답 한 번에만 실리고 어디에도 다시 저장·재노출하지 않는다
# (api/handoff.py get_handoff()가 조회 때마다 access_key를 항상 pop하는 것과 같은 이유).
MALL_CART_URL = mall.BASE + "/shop/order_basket_list.html"


@router.get("/orders")
def my_orders():
    # 회원 경계는 **세션**이 정한다(슬라이스 38). 요청이 주장하는 이메일은 더 이상 믿지 않는다.
    member_id = require_member()["member_id"]
    with engine.connect() as conn:
        orders = conn.execute(text(
            "SELECT order_id, order_no, channel, status, total_amount, ops_snapshot, created_at"
            " FROM orders WHERE member_id=:m ORDER BY created_at DESC, order_id DESC"),
            {"m": member_id}).mappings().all()
        ids = [o["order_id"] for o in orders]
        items_by, pays, ships, refunds = {}, {}, {}, {}
        if ids:
            for r in conn.execute(text(
                    "SELECT order_id, item_kind, name_snap, price_snap, qty, spec_snap"
                    " FROM order_items WHERE order_id = ANY(:ids) ORDER BY item_id"), {"ids": ids}).mappings():
                items_by.setdefault(r["order_id"], []).append(
                    [_item_label(r["item_kind"], r["spec_snap"]), r["name_snap"],
                     r["price_snap"] * r["qty"]])
            pays = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, pay_mode, method, status, paid_at"
                " FROM payments WHERE order_id = ANY(:ids) ORDER BY order_id, payment_id DESC"),
                {"ids": ids}).mappings()}
            ships = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, carrier, tracking_no FROM shipments"
                " WHERE order_id = ANY(:ids) ORDER BY order_id, shipment_id DESC"),
                {"ids": ids}).mappings()}
            refunds = {r["order_id"]: r for r in conn.execute(text(
                "SELECT DISTINCT ON (order_id) order_id, refund_id, refund_mode, reason_type, status"
                " FROM refunds WHERE order_id = ANY(:ids) ORDER BY order_id, refund_id DESC"),
                {"ids": ids}).mappings()}

        # 인계(handoffs) — 회원 경계는 ① 직접 붙은 member_id ② 방문자 승격(visitor.promote)
        # 으로 이 회원의 user_id와 이어진 것. 둘 다 이 쿼리 하나가 스스로 스코프한다
        # (다른 회원의 handoff가 섞일 길이 없다 — 서브쿼리도 :m으로 같은 회원만 본다).
        handoffs = conn.execute(text(
            "SELECT handoff_id, handoff_no, created_at, status,"
            " COALESCE(total_mall, total_quoted) AS total"
            " FROM handoffs"
            " WHERE member_id=:m OR (user_id IS NOT NULL AND user_id ="
            "       (SELECT user_id FROM members WHERE member_id=:m))"
            " ORDER BY created_at DESC, handoff_id DESC"),
            {"m": member_id}).mappings().all()
        hids = [h["handoff_id"] for h in handoffs]
        part_counts = {}
        if hids:
            # "부품 수" = core_part 줄만 센다. 조립비(assembly_service)는 부품이 아니고,
            # 몰이 제안한 주변기기(peripheral)까지 섞으면 견적 화면이 말한 부품 수와 어긋난다.
            part_counts = dict(conn.execute(text(
                "SELECT handoff_id, COUNT(*) FROM handoff_items"
                " WHERE handoff_id = ANY(:ids) AND item_kind='core_part'"
                " GROUP BY handoff_id"), {"ids": hids}).all())

    # order·handoff를 한 이력으로 섞는다 — 정렬은 시각 내림차순(고객에겐 하나의 이력이다).
    # orders.created_at은 naive(DB가 UTC로 돈다는 사실만 있고 tzinfo가 없음),
    # handoffs.created_at은 이미 tz-aware — 섞어서 비교하면 TypeError가 난다.
    # timeutil.iso()와 같은 규약(naive=UTC로 간주)으로 맞춘 뒤 정렬한다.
    def _aware(dt):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    merged = []
    for o in orders:
        oid = o["order_id"]
        p, s, rf = pays.get(oid), ships.get(oid), refunds.get(oid)
        pay = None
        if p:
            suffix = " (자체 결제)" if p["pay_mode"] == "own" else " (인계)"
            pay = {"method": p["method"] + suffix, "state": p["status"],
                   "at": iso(p["paid_at"]) if p["paid_at"] else None}
        merged.append((o["created_at"], {
            "kind": "order",
            "no": o["order_no"], "created_at": iso(o["created_at"]),
            "channel": o["channel"], "status": o["status"],
            "step": STEP.get(o["status"], 1), "total": o["total_amount"],
            "items": items_by.get(oid, []),
            "pay": pay,
            "ship": {"carrier": s["carrier"], "no": s["tracking_no"]} if s else None,
            "refund_mode": (o["ops_snapshot"] or {}).get("refund", "mall"),  # 접수 전 안내문(주문 시점 스냅샷)
            "refund": {"no": refund_label(rf["refund_id"]), "reason": rf["reason_type"],
                       "status": rf["status"], "mode": rf["refund_mode"]} if rf else None,
        }))
    for h in handoffs:
        merged.append((h["created_at"], {
            "kind": "handoff",
            "no": h["handoff_no"], "created_at": iso(h["created_at"]),
            "total": h["total"], "item_count": part_counts.get(h["handoff_id"], 0),
            "status": h["status"], "mall_url": MALL_CART_URL,
        }))
    merged.sort(key=lambda t: _aware(t[0]), reverse=True)
    return {"items": [d for _, d in merged]}


class RefundBody(BaseModel):
    order_no: str
    reason_type: str


@router.post("/refunds")
def create_refund(body: RefundBody):
    me = require_member()
    if write_locked():
        # my-orders.html 은 res.j.detail 을 객체로 보고 .detail/.error 를 꺼낸다
        # (409 invalid_state·refund_active 와 같은 모양) — 문자열만 주면
        # "잠시 후 다시 시도해 주세요"로 뭉개져 사유가 안 보인다.
        raise HTTPException(403, {"error": "write_locked", "detail": WRITE_LOCK_REASON})
    if body.reason_type not in REASONS:
        raise HTTPException(400, f"알 수 없는 사유: {body.reason_type}")
    with engine.begin() as conn:
        o = conn.execute(text(
            "SELECT o.order_id, o.status, o.total_amount, o.ops_snapshot, o.member_id"
            " FROM orders o WHERE o.order_no=:n FOR UPDATE OF o"),
            {"n": body.order_no}).mappings().first()
        if o is None:
            raise HTTPException(404, "주문이 없습니다")
        if o["member_id"] != me["member_id"]:
            raise HTTPException(403, "본인 주문만 접수할 수 있습니다")
        if o["status"] in ("접수", "취소"):
            raise HTTPException(409, {"error": "invalid_state",
                                      "detail": f"'{o['status']}' 상태의 주문은 접수할 수 없습니다"})
        if conn.execute(text(
                "SELECT 1 FROM refunds WHERE order_id=:o AND status = ANY(:st) LIMIT 1"),
                {"o": o["order_id"], "st": list(ACTIVE_REFUND)}).first():
            raise HTTPException(409, {"error": "refund_active",
                                      "detail": "이미 접수된 건이 진행 중입니다"})
        mode = (o["ops_snapshot"] or {}).get("refund", "mall")
        rid = conn.execute(text(
            "INSERT INTO refunds (order_id, refund_mode, reason_type, amount, status)"
            " VALUES (:o, :m, :r, :a, '접수') RETURNING refund_id"),
            {"o": o["order_id"], "m": mode, "r": body.reason_type,
             "a": o["total_amount"]}).scalar()
    return {"refund_no": refund_label(rid), "status": "접수", "mode": mode}
