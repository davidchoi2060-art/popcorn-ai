# -*- coding: utf-8 -*-
"""내 정보(ADM-SYS-022) — admin2 페이지 라우트. `api/main.py`가 자동으로 싣는다.

■ 계약 — `docs/design/spec-my-profile.md`(**1a 안** · 사장님 확정 2026-08-18) ·
  요구사항 정의서 `docs/design/req/req-my-profile.md` · 결정 A-62~A-65.
  원안 `docs/design/dc-my-profile.html` 의 **`id="1a"` 구획**에서 가져온 것은
  «치수와 배치»뿐이다 — 색·서체는 `/shared/admin2/admin2.css` 토큰만 쓴다.
  ⚠ 같은 원안 파일에 `1b` 도 들어 있으나 **정본이 아니다**(캔버스에 안이 둘).

■ 이 파일은 «페이지 라우트만» 갖는다 — 데이터 API 는 전부 이미 있다. 새로 만들지 않는다.
      GET   /api/admin/my-profile                          본인 계정 전체 (api/admin_profile.py)
      PATCH /api/admin/my-profile                          이름 · 연락처 · 직무
      GET   /api/admin/my-profile/sessions                 열려 있는 세션
      POST  /api/admin/my-profile/sessions/revoke-others   현재 세션만 남기고 철회
      GET   /api/admin/my-profile/devices                  기억된 기기
      POST  /api/admin/my-profile/devices/{id}/revoke      기기 하나 철회
      GET   /api/admin/my-profile/photo                    사진 — 바이너리 그대로
      POST  /api/admin/my-profile/photo                    등록 · 교체 (본문이 이미지 바이트)
      DELETE /api/admin/my-profile/photo                   삭제 (되돌리기 없음)
      GET   /api/admin/my-profile/photo-policy             사진 정책 (2026-08-18 신설)
      GET   /api/admin/auth/password-policy                비밀번호 규칙
      POST  /api/admin/auth/password                       본인 비밀번호 변경

■ 권한 — 별도 코드 없이 이미 만족된다
  `api/auth.py` `required_role()` 이 `/api/admin/my-profile` 로 시작하는 경로를
  **쓰기까지 viewer** 로 연다(`/api/admin/operators` owner 규칙보다 먼저 검사한다).
  그래서 이 화면에는 **403 이 나지 않는다** — 권한 부족 상태가 성립하지 않는다.
  권한 상승은 등급이 아니라 `admin_profile.EDITABLE` 화이트리스트가 막는다(422).

■ 세션·잠금 상수를 마크업에 박지 않는다
  하단 띠가 말하는 「절대 8시간 · 유휴 480분 · 5회 실패 15분 잠금 · 기기 기억 30일」은
  전부 `api/auth.py` 의 상수다. 박으면 낡는다 — 실제로 `IDLE_MINUTES` 가 30 -> 480 으로
  바뀌며 정의서 하나가 반나절 만에 낡은 전례가 있다. 그래서 **상수를 그대로 읽어**
  템플릿 컨텍스트로 넘긴다(`api/admin_ui_login.py` 가 이미 쓰는 방식 · 같은 근거).
  ⚠ `from .auth import ...` 는 순환이 아니다 — `api/auth.py` 는 `admin_ui_*` 를 모듈
  수준에서 가져오지 않는다(`admin_ui_common` 을 함수 안에서만 늦게 가져온다).

■ LNB 항목이 없는 화면이다
  IA 정본 `api/admin_nav.py` 에 이 화면 항목이 **0건**이다(확인법
  `grep -n "my-profile" api/admin_nav.py`). 진입점은 **상단바 아바타**로 확정됐는데
  (2026-08-18), 그 링크는 **이 화면이 검증을 통과한 뒤** 셸(정본 파일)에 단다 —
  지금 달면 없는 화면을 가리키는 죽은 링크가 41개 화면에 동시에 생긴다.
  그래서 `crumb_group` 이 `admin_nav.NAV` 의 그룹명과 «맞출 대상이 없다» —
  승인 디자인 1a 의 상위 라벨 「내 계정」을 그대로 쓴다(원안 헤더 실측).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .auth import (ABSOLUTE_HOURS, IDLE_MINUTES, LOCK_MINUTES, MAX_FAILS,
                   REMEMBER_DEVICE_DAYS)

router = APIRouter(tags=["admin-ui"])


@router.get("/admin2/my-profile", response_class=HTMLResponse)
def my_profile_page(request: Request) -> HTMLResponse:
    """본인 계정 조회·수정 화면.

    라우트가 화면의 사실(ID·소속 라벨·이름)을 말하는 유일한 곳이다 — 마크업에 박지
    않는다(`api/admin_ui_common.render` docstring §단일 원천).

    ⚠ 이 경로는 인증 게이트 «안»이다 — `api/auth.py` `_is_gated()` 가 `/admin2/*` 를
    막고, 무세션이면 `admin_ui_common.login_required_html()` 로 로그인 화면에 보낸다.
    서버 렌더로 싣는 것은 **세션 규칙 상수 다섯과 화면 자기 식별자뿐**이고 운영자
    데이터는 한 건도 싣지 않는다 — 계정 정보는 전부 화면이 `/api/admin/*` 로 받는다.
    """
    return render(request, "admin/my_profile.html.j2",
                  screen_id="ADM-SYS-022", domain="my_profile",
                  crumb_group="내 계정", crumb_now="내 정보",
                  session_hours=ABSOLUTE_HOURS,
                  idle_minutes=IDLE_MINUTES,
                  max_fails=MAX_FAILS,
                  lock_minutes=LOCK_MINUTES,
                  remember_days=REMEMBER_DEVICE_DAYS)
