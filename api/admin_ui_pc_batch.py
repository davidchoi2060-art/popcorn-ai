from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .admin_ui_common import render
from .admin_nav import workspace_nav

router=APIRouter(prefix='/admin2',tags=['admin-ui'])


@router.get('/pc-batch',response_class=HTMLResponse)
def page(request:Request):
    return render(request,'admin/pc_batch.html.j2',screen_id='ADM-PRD-061',domain='catalog',
                  crumb_group='상품관리',crumb_now='AI 일괄 보완',workspace_nav=workspace_nav())
