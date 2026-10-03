"""ADM-SRC-030: approved NEW supplier workspace; shared shell/auth stay unchanged."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .auth import current_operator
from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

@router.get("/suppliers", response_class=HTMLResponse)
def suppliers_page(request: Request) -> HTMLResponse:
    op = current_operator()
    return render(request, "admin/suppliers.html.j2",
                  screen_id="ADM-SRC-030", domain="suppliers",
                  crumb_group="설정 · 자료 관리", crumb_now="공급처",
                  admin_mode="new",
                  supplier_can_write=bool(op and op.get("role") in ("operator", "owner")))
