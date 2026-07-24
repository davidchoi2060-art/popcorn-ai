"""MY-030 결제 내역 — 회원 결제 원장 읽기 (읽기 전용 슬라이스).

인증: localStorage popcorn-member 기반 mock — email 파라미터는 로컬 데모 한정(실 인증 이관).
원장 계약: payments **전 행**(승인·취소·환불이 각 한 줄) 반환. my_orders.py의
DISTINCT ON(order_id)(주문당 최신 1행)을 복붙하면 84219처럼 승인+환불 두 행인 주문에서
승인 행이 소실되므로 금지. pg_ref·payment_id는 고객 화면 미노출 계약 — 응답에서 제외(미전송).
정렬: paid_at DESC NULLS LAST, payment_id DESC(결정론 타이브레이크).
KPI(이번 달·누적)는 클라 계산 — 응답 rows가 단일 원천(목록·KPI 괴리 구조적 차단).
이관 유지: 실 인증, '대기' 상태 색 성문화(현 쓰기 경로상 발생 불가), paid_at 타임존 정규화,
settlements·pg_ref 노출은 ADM-PAY-010 몫.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/my")


@router.get("/payments")
def list_payments(email: str = ""):
    with engine.connect() as conn:
        m = conn.execute(text(
            "SELECT member_id FROM members WHERE email=:e"), {"e": email}).first()
        if m is None:
            return {"items": []}  # 미가입 — 정직 빈 목록(my_orders 동일)
        rows = conn.execute(text(
            "SELECT o.order_no, p.pay_mode, p.method, p.amount, p.status, p.paid_at"
            " FROM payments p JOIN orders o USING (order_id)"
            " WHERE o.member_id=:m"
            " ORDER BY p.paid_at DESC NULLS LAST, p.payment_id DESC"),
            {"m": m[0]}).mappings().all()
    return {"items": [{
        "order_no": r["order_no"], "mode": r["pay_mode"], "method": r["method"],
        "amount": r["amount"], "status": r["status"],
        "at": r["paid_at"].isoformat() if r["paid_at"] else None,
    } for r in rows]}
