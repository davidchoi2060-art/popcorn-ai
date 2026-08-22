# -*- coding: utf-8 -*-
"""팝콘톡 응답 패턴(ADM-TLK-010 · 가칭) — 화면 라우터.

`api/main.py` 가 자동으로 싣는다(pkgutil 1단계 스캔 — 등록 코드 없음).

승인 디자인 **1b「목록 전면」**(`docs/design/dc-talk-patterns.html`, 사장님 확정
2026-08-22) · 정의서 `docs/design/req/req-talk-patterns.md` · 결정 **A-95**·**A-96**.

■ 빈 셸만 그린다
  실데이터는 `GET /api/admin/talk-patterns*` 가 AJAX 로 낸다
  (`api/admin_talk_patterns.py`) — 화면이 수를 세지 않는다(§화면 정직성).

■ 화면 ID 는 아직 «가칭»이다
  `admin-identity.md` 카탈로그 등재가 안 됐다(정의서 §9 ㉠). 그래도 `screen_id` 를
  비우지 않는 이유는, 공통 셸이 그 값으로 헤더 배지를 그리고 회귀가 `data-screen-id`
  존재를 검사하기 때문이다. **확정되면 이 한 줄만 바꾼다.**

■ ⚠ 좌측 메뉴(`api/admin_nav.py`)에는 아직 걸지 않았다
  T-02 ②: **href 연결은 검증이 끝난 화면만.** 검증 통과를 하네스가 통보한 뒤
  기록자가 등재한다 — 검증 안 된 화면을 메뉴에 노출하면 운영자가 먼저 들어간다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/talk-patterns", response_class=HTMLResponse)
def talk_patterns(request: Request) -> HTMLResponse:
    return render(request, "admin/talk_patterns.html.j2",
                  screen_id="ADM-TLK-010", domain="talk-patterns",
                  # crumb_group 은 `api/admin_nav.NAV` 의 그룹명과 맞춘다
                  # (정본은 여전히 admin_nav — 여기서 다시 정의하지 않는다).
                  crumb_group="AI 관리", crumb_now="팝콘톡 응답 패턴")
