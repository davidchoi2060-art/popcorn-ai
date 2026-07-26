"""MY-010 계정 연결 · MY-040 후기 작성 — 고객 축 쓰기 (슬라이스 29 목업 설계의 관통).

계정 연결(동의 기반, ERD §10.1):
  관리자가 ADM-CUS-010에서 매핑 요청을 발송하면(mall_map_requested_at) 고객 화면에 안내가 뜨고,
  **고객의 동의로만** mall_member_id가 채워진다(관리자가 임의로 채우지 않는다 — 슬라이스 20에서
  "실제 매핑 완료는 범위 밖"으로 남겨둔 자리가 여기서 닫힌다).
  거절 = 요청 해제(mall_map_requested_at NULL) — 재요청은 관리자 몫.
  **쇼핑몰 계정 ID는 연동 원천이 없어 데모 규칙으로 발급**(MALL-2200+member_id) — 실 연동 시 교체(이관).
후기 작성(구매 인증, ERD §10.7):
  member_reviews.order_item_id NOT NULL이 "구매 인증만" 원칙의 DB 강제.
  검증 3중: ① 그 라인이 이 회원의 주문인가 ② 주문이 '완료'인가(배송 완료 후에만)
  ③ 같은 라인에 이미 후기가 있는가(중복 차단). 등록분은 '게시' 상태로 시작하고
  관리자 화면(ADM-CUS-020)의 숨김·신고 처리 대상이 된다.
인증(슬라이스 38): **회원 경계는 세션이 정한다** — 요청 본문의 이메일은 더 이상 받지 않는다.
수정·삭제는 범위 밖(관리자 숨김만 — 목업에도 없음).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .customer_auth import require_member
from .db import engine

router = APIRouter(prefix="/api/my")

MALL_BASE = 2200  # 데모 발급 규칙 — 실 쇼핑몰 연동 시 교체(이관)


def _member(conn, member_id: int):
    m = conn.execute(text(
        "SELECT member_id, nickname, mall_member_id, mall_map_requested_at"
        " FROM members WHERE member_id=:i FOR UPDATE"), {"i": member_id}).mappings().first()
    if m is None:
        raise HTTPException(404, "회원이 없습니다")
    return m


@router.get("/account")
def account():
    me = require_member()                        # 회원 경계 = 세션(슬라이스 38)
    with engine.connect() as conn:
        m = conn.execute(text(
            "SELECT member_id, nickname, mall_member_id, mall_map_requested_at"
            " FROM members WHERE member_id=:i"), {"i": me["member_id"]}).mappings().first()
        if m is None:
            return {"member": None, "map_state": "none"}
        state = ("mapped" if m["mall_member_id"]
                 else ("requested" if m["mall_map_requested_at"] else "none"))
        # 후기 = 주문(구성) 단위 — 주문마다 **대표 라인 1개**에 매단다.
        # 통합 구성 라인(product_code NULL)이 있으면 그것, 없으면(부품별 주문) 첫 라인.
        rows = conn.execute(text(
            "SELECT DISTINCT ON (o.order_id) oi.item_id, o.order_id, o.order_no, o.created_at,"
            " oi.name_snap, oi.price_snap, oi.qty, r.review_id, o.status,"
            " (SELECT COUNT(*) FROM order_items x WHERE x.order_id=o.order_id) AS lines,"
            " (SELECT SUM(x.price_snap * x.qty) FROM order_items x WHERE x.order_id=o.order_id) AS order_total"
            " FROM order_items oi JOIN orders o USING (order_id)"
            " LEFT JOIN member_reviews r ON r.order_item_id = oi.item_id"
            " WHERE o.member_id=:m AND o.status='완료'"
            " ORDER BY o.order_id, (oi.product_code IS NULL) DESC, oi.item_id"),
            {"m": m["member_id"]}).mappings().all()
        rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    return {
        "member": {"id": m["member_id"], "nickname": m["nickname"]},
        "map_state": state, "mall_member_id": m["mall_member_id"],
        "requested_at": m["mall_map_requested_at"].isoformat() if m["mall_map_requested_at"] else None,
        "reviewable": [{
            "item_id": r["item_id"], "order_no": r["order_no"],
            "at": r["created_at"].isoformat(),
            "item": r["name_snap"] + (f" 외 {r['lines'] - 1}건" if (r["lines"] or 1) > 1 else ""),
            "total": r["order_total"] or 0,
            "written": r["review_id"] is not None,
        } for r in rows],
        "note": ("쇼핑몰 계정 ID는 연동 원천이 없어 데모 규칙으로 발급합니다(실 연동 시 교체) ·"
                 " 후기는 배송이 완료된 주문의 구성 라인에만 남길 수 있습니다."),
    }


class MapBody(BaseModel):
    agree: bool


@router.post("/account/map")
def account_map(body: MapBody):
    me = require_member()
    """동의 = 연결 확정 / 거절 = 요청 해제. 요청이 없는 상태에서는 둘 다 불가(관리자 발송 선행)."""
    with engine.begin() as conn:
        m = _member(conn, me["member_id"])
        if m["mall_member_id"]:
            raise HTTPException(409, "이미 쇼핑몰 계정과 연결돼 있습니다")
        if not m["mall_map_requested_at"]:
            raise HTTPException(409, "연결 요청이 없습니다 — 관리자 요청이 도착해야 진행할 수 있습니다")
        if body.agree:
            mall_id = f"MALL-{MALL_BASE + m['member_id']}"
            conn.execute(text(
                "UPDATE members SET mall_member_id=:mid WHERE member_id=:i"),
                {"mid": mall_id, "i": m["member_id"]})
            return {"ok": True, "map_state": "mapped", "mall_member_id": mall_id}
        conn.execute(text(
            "UPDATE members SET mall_map_requested_at=NULL WHERE member_id=:i"),
            {"i": m["member_id"]})
        return {"ok": True, "map_state": "none"}


class ReviewBody(BaseModel):
    item_id: int
    rating: int
    body: str


@router.post("/reviews")
def write_review(body: ReviewBody):
    me = require_member()
    if not 1 <= body.rating <= 5:
        raise HTTPException(400, "별점은 1~5 사이여야 합니다")
    text_body = (body.body or "").strip()
    if len(text_body) < 10:
        raise HTTPException(400, "후기는 10자 이상 적어 주세요")
    with engine.begin() as conn:
        m = _member(conn, me["member_id"])
        line = conn.execute(text(
            "SELECT oi.item_id, o.member_id, o.status, o.order_no FROM order_items oi"
            " JOIN orders o USING (order_id) WHERE oi.item_id=:i FOR UPDATE"),
            {"i": body.item_id}).mappings().first()
        if line is None:
            raise HTTPException(404, "주문 구성을 찾을 수 없습니다")
        if line["member_id"] != m["member_id"]:
            raise HTTPException(403, "본인 주문에만 후기를 남길 수 있습니다")
        if line["status"] != "완료":
            raise HTTPException(409, f"배송 완료 후에 남길 수 있습니다(현재 '{line['status']}')")
        if conn.execute(text(
                "SELECT 1 FROM member_reviews WHERE order_item_id=:i"),
                {"i": body.item_id}).first():
            raise HTTPException(409, "이미 이 주문에 후기를 남기셨습니다")
        rid = conn.execute(text(
            "INSERT INTO member_reviews (member_id, order_item_id, rating, body, status, cite_s2)"
            " VALUES (:m, :i, :r, :b, '게시', false) RETURNING review_id"),
            {"m": m["member_id"], "i": body.item_id, "r": body.rating, "b": text_body}).scalar()
        return {"ok": True, "review_id": rid, "order_no": line["order_no"], "status": "게시"}
