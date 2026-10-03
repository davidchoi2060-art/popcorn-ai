"""NEW member page. Shared shell/auth remain owned by the integration team."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix='/admin2', tags=['admin-ui'])


@router.get('/members', response_class=HTMLResponse)
def members_page(request: Request):
    return render(request, 'admin/members.html.j2', screen_id='ADM-CUS-010',
                  domain='members', crumb_group='신 관리자', crumb_now='회원 관리',
                  admin_mode='new')
