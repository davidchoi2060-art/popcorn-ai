from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .admin_ui_common import render
from .admin_nav import workspace_nav

router = APIRouter(prefix='/admin2', tags=['admin-ui'])


@router.get('/pc-workspace', response_class=HTMLResponse)
def page(request: Request):
    return render(request, 'admin/pc_workspace.html.j2', screen_id='ADM-PRD-060',
                  domain='catalog', crumb_group='상품관리', crumb_now='처리할 일 · AI 도움',
                  workspace_nav=workspace_nav())
