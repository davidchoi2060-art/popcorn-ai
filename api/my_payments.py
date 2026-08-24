"""MY-030 결제 내역 — 회원 결제 원장 읽기 (읽기 전용 슬라이스).

인증: localStorage popcorn-member 기반 mock — email 파라미터는 로컬 데모 한정(실 인증 이관).
원장 계약: payments **전 행**(승인·취소·환불이 각 한 줄) 반환. my_orders.py의
DISTINCT ON(order_id)(주문당 최신 1행)을 복붙하면 84219처럼 승인+환불 두 행인 주문에서
승인 행이 소실되므로 금지. pg_ref·payment_id는 고객 화면 미노출 계약 — 응답에서 제외(미전송).
정렬: paid_at DESC NULLS LAST, payment_id DESC(결정론 타이브레이크).
KPI(이번 달·누적)는 클라 계산 — 응답 rows가 단일 원천(목록·KPI 괴리 구조적 차단).
이관 유지: 실 인증, '대기' 상태 색 성문화(현 쓰기 경로상 발생 불가), paid_at 타임존 정규화,
settlements·pg_ref 노출은 ADM-PAY-010 몫.

■ 인계(handoffs)는 여기 섞지 않는다 (2026-08-24, customer-audit-2026-08-24.md §1-3 판단)
  my-payments.html은 "결제 방식과 무관하게 전 건이 기록됩니다"라고 적어 두었고, 지금
  운영 모드(mall)에서는 이 표가 사실상 항상 비어 보인다 — 그래서 얼핏 my_orders.py와
  같은 문제(정본 handoffs를 안 본다)처럼 보인다. **판단은 다르게 냈다**:

    이 표의 계약(위 docstring)은 "payments 전 행 — 승인·취소·환불이 각 한 줄"이다.
    handoffs 행은 **결제가 아니다** — api/handoff.py 자신의 정의("결제하지 않는다 ·
    재고를 차감하지 않는다")가 이미 그렇게 못박았고, CANON §3도 결제는 몰 소관이라
    적었다. handoffs에는 method(결제 수단)도 paid_at(결제 시각)도 없다 — total_quoted·
    total_mall은 "견적/몰 확인가"이지 "결제 승인액"이 아니다. 억지로 payments 모양
    (method·status·paid_at)을 만들면 **일어나지 않은 결제를 일어난 것처럼 지어내는
    것**이라 CANON §2-3("모르는 것을 지어내지 않는다")을 어긴다.

  그래서 이 API는 그대로 두고(payments만, 변경 없음), **화면 문구가 지키지 못할
  약속을 하고 있다는 사실만** 보고한다 — my-payments.html의 "결제 방식과 무관하게
  전 건이 기록됩니다"는 지금 운영 모드에서 사실이 아니다(인계는 결제가 아니므로
  영원히 여기 안 남는다). 문구를 "본 시스템에서 결제한 내역만 표시합니다 — 인계 후
  몰에서 결제한 내역은 주문 내역(인계)에서 확인하세요" 류로 고치는 것이 맞다고
  판단하지만, **그 문구를 고치는 것은 이 파일이 아니라 mockups/mvp1/my-payments.html
  소관**(담당 제작자 E)이라 여기서는 고치지 않는다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .timeutil import iso
from .customer_auth import require_member
from .db import engine

router = APIRouter(prefix="/api/my")


@router.get("/payments")
def list_payments():
    member_id = require_member()["member_id"]   # 회원 경계 = 세션(슬라이스 38)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT o.order_no, p.pay_mode, p.method, p.amount, p.status, p.paid_at"
            " FROM payments p JOIN orders o USING (order_id)"
            " WHERE o.member_id=:m"
            " ORDER BY p.paid_at DESC NULLS LAST, p.payment_id DESC"),
            {"m": member_id}).mappings().all()
    return {"items": [{
        "order_no": r["order_no"], "mode": r["pay_mode"], "method": r["method"],
        "amount": r["amount"], "status": r["status"],
        "at": iso(r["paid_at"]) if r["paid_at"] else None,
    } for r in rows]}
