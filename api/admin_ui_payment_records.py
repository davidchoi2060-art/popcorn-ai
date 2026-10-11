"""결제·정산 기록장(ADM-PAY-020) 페이지 라우트 — 2026-10-11 사장님 「기록장」 확정.
`api/main.py` 가 자동으로 싣는다. 데이터·쓰기는 `api/admin_payment_records.py` 가 한다.

관리자가 은행·PG·쇼핑몰에서 확인한 거래를 적는 화면이다. 시스템이 은행·PG 와 대조하지 않고,
기록해도 주문·결제·환불 상태는 바뀌지 않는다. 옛 정산 계산(ADM-PAY-010)은 참고 금액으로만 보인다.
신 관리자 「주문 운영」 묶음에 속한다 — 주문 운영 화면에서 들어오고 돌아가기 줄로 돌아간다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/payment-records", response_class=HTMLResponse)
def payment_records_page(request: Request) -> HTMLResponse:
    return render(request, "admin/payment_records.html.j2", screen_id="ADM-PAY-020",
                  domain="payment-records", crumb_group="주문 운영", crumb_now="결제·정산 기록",
                  admin_mode="new")
