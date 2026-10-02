from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .admin_ui_common import render
from .taxonomy import SLOT_LABELS

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/part-explanations", response_class=HTMLResponse)
def page(request: Request):
    return render(request,"admin/part_explanations.html.j2",screen_id="ADM-PRD-030",domain="catalog",
                  crumb_group="상품관리",crumb_now="부품 관리",part_slots=SLOT_LABELS.items())
