from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .admin_ui_common import render

router=APIRouter(prefix='/admin2',tags=['admin-ui'])


@router.get('/pc-configurations',response_class=HTMLResponse)
def page(request:Request):
    return render(request,'admin/pc_configurations.html.j2',screen_id='ADM-PRD-050',
                  domain='catalog',crumb_group='상품관리',crumb_now='조립PC 제품군 목록')
