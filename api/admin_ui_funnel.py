# -*- coding: utf-8 -*-
"""유입 성과(ADM-HND-030 후보) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery,
`api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

**완전 신규 화면.** 계약 `docs/design/spec-funnel.md`(사장님 확정 2026-08-15 · **1a 안**
"끊긴 깔때기를 그대로 그린다"). 정의서 `docs/design/req/req-funnel-performance.md`.
데이터 API는 `api/admin_funnel.py`(그 파일 docstring이 인증·측정 근거를 전부 담는다 —
여기서 되풀이하지 않는다).

■ 화면 ID·경로는 아직 후보다 — 계약 §미정 그대로
  `ADM-HND-030`·`/admin2/funnel-performance` 둘 다 이 문서·`req-funnel-performance.md`의
  **제안**이지 확정이 아니다(§결정 1 "화면 ID·경로 확정"이 사장님 결정 대기). 계약 지시
  그대로 헤더 배지를 점선 테두리로 표시해 미확정임을 화면이 스스로 말한다(`funnel.html.j2`
  담당). `screen_id`/`domain`은 지금 아는 값(후보)을 그대로 넘긴다 — 나중에 확정되면 이
  두 인자만 바꾸면 된다(라우트 경로 자체를 바꾸는 것은 더 큰 변경이라 별도 검토가 필요하다).

■ 이 페이지가 데이터를 직접 로드하지 않는 이유
  `mall_sync`처럼 서버 렌더에 실데이터를 박는 방식 대신, `handoff_log`·`consult_sessions`
  처럼 **빈 셸 + AJAX**를 골랐다 — 이 화면은 계약이 요구하는 기간 탭(㉮/㉯/㉰)이 있어
  페이지 새로고침 없이 기간을 바꿔 다시 집계해야 한다(계약 §⑥ "기간을 선택하면 (A) 구간의
  지표가 그 기간으로 다시 계산된다"). 서버 렌더 1회만으로는 이 상호작용을 만들 수 없다.

■ 인증 — 이 파일은 자체 게이트를 두지 않는다
  `api/auth.py`(담당 밖, 읽기만 — 2026-08-15) `_is_gated()`가 `/admin2/*` 전체를 이미
  막는다(무세션이면 HTML 로그인 안내로 리다이렉트). 이 페이지는 실데이터를 셸에 싣지
  않으므로(위 참조) 이중 게이트가 없어도 새는 값이 없다. 실데이터는 `/api/admin/
  funnel-performance`가 별도로 게이트한다(그 파일 담당 — `/api/admin/*` 접두어라
  `_is_gated()`가 자동으로 JSON 401을 준다).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/funnel-performance", response_class=HTMLResponse)
def funnel_performance(request: Request) -> HTMLResponse:
    """유입 성과(ADM-HND-030 후보) — 조회 전용. 빈 셸만 그린다(실데이터는
    `GET /api/admin/funnel-performance`가 AJAX로 낸다 — `api/admin_funnel.py` 참조).
    """
    return render(request, "admin/funnel.html.j2",
                  screen_id="ADM-HND-030", domain="funnel-performance",
                  crumb_group="인계 · 성과", crumb_now="유입 성과")
