"""NEW commerce order page; shared renderer and automatic discovery own integration."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix='/admin2', tags=['admin-ui'])


@router.get('/commerce-orders', response_class=HTMLResponse)
def commerce_orders_page(request: Request):
    return render(request, 'admin/commerce_orders.html.j2', screen_id='ADM-ORD-040',
                  domain='commerce-orders', crumb_group='신 관리자', crumb_now='주문 운영',
                  admin_mode='new')
