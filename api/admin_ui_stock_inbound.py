# -*- coding: utf-8 -*-
"""재고 입고(ADM-SRC-020) — admin2 페이지 라우트. `api/main.py`가 자동으로 싣는다.

■ 계약 — `docs/design/spec-stock-inbound.md`(1b 골격 + 1a 「목록에서 바로 확정」 혼합,
  사장님 확정 2026-08-17) · 요구사항 정의서 `docs/design/req/req-stock-inbound.md` ·
  결정 A-58(IA 제외 근거가 틀렸다 · 화면 다시 짓는다) · 「보류 = 서버 상태」 ·
  「안전재고 = 상품 상세에서, 이 화면은 읽기 전용」.

■ 이 파일은 «페이지 라우트만» 갖는다 — 데이터 API 는 전부 `api/admin_stock.py` 에 이미 있다
  (2026-08-17 이력·보류 신설 포함). 여기서 API 를 다시 만들지 않는다(§단일 원천).
      GET  /api/admin/stock-inbound                     목록 · 서버 페이지네이션 · hold=exclude|only|all
      GET  /api/admin/stock-inbound/history             이력 · product_code 로 좁힘 · 되돌림 판정 포함
      POST /api/admin/stock-inbound/{product_code}      확정 {qty, why}
      POST /api/admin/stock-inbound/hold/{product_code} 보류 {reason}
      POST /api/admin/stock-inbound/hold/{product_code}/release
      POST /api/admin/stock-inbound/undo/{log_id}
      GET  /api/admin/product-meta                      분류 선택지(used_parts) — 화면이 페이지에서 뽑지 않는다

■ 권한 — 별도 코드 없이 이미 만족된다
  `/api/admin/*` 전역 규칙(api/auth.py required_role)이 GET=viewer · 그 외=operator 다.
  `stock-inbound` 는 OWNER_WRITE_PREFIXES 에 없다 — 계약의 「조회 viewer · 쓰기 operator 이상
  (owner 전용 아님)」이 전역 미들웨어로 충족된다. 403 은 화면이 단추를 감추지 않고
  «비활성 + 사유 병기» 한다(history 응답의 can_write·can_write_note 를 그대로 쓴다).

■ 라우트가 화면의 사실(ID·소속 그룹·이름)을 말하는 유일한 곳이다 — 마크업에 박지 않는다
  (`api/admin_ui_common.render` docstring §단일 원천). `crumb_group` 은 `api/admin_nav.NAV`
  의 그룹명 「매입 · 소싱」과 같은 문자열이다(정본은 admin_nav — 여기서 다시 정의하지 않는다).
  ⚠ LNB 항목 연결(`admin_nav.py`)은 이 파일 소관이 아니다 — 검증 뒤 기록자가 잇는다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(tags=["admin-ui"])


@router.get("/admin2/stock-inbound", response_class=HTMLResponse)
def stock_inbound_page(request: Request) -> HTMLResponse:
    return render(request, "admin/stock_inbound.html.j2",
                  screen_id="ADM-SRC-020", domain="sourcing",
                  crumb_group="매입 · 소싱", crumb_now="재고 입고")
