"""Read-only readiness workspace; authentication and navigation use the shared shell."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix='/admin2', tags=['admin-ui'])


@router.get('/sale-readiness', response_class=HTMLResponse)
def sale_readiness_page(request: Request):
    return render(request, 'admin/sale_readiness.html.j2',
                  domain='sale-readiness', crumb_group='신 관리자',
                  crumb_now='판매 준비 현황', admin_mode='new')
