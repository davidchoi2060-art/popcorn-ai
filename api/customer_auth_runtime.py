"""고객 세션 해석기 연결 (설계 docs/design/customer-social-login-v1.md §5, P2b).

서버가 뜰 때 `api/main.py` 의 라우터 자동 탐색이 이 모듈을 한 번 import 한다(customer_auth 다음, 라우터를 싣기 전).
CUSTOMER_AUTH_ENABLED=on 이고 공급자 키가 하나라도 있으면 발급기 쪽 포트로 만든 실제 해석기를
`install_resolver()` 로 끼운다 -- 그 뒤로
  GET /api/auth/me        로그인 상태(signed-out / authenticated)
  GET /api/my/profile     회원 정보(X-Popcorn-Auth-Context 필요)
  고객 경로 미들웨어       current_member()/require_member()
가 실제 세션을 읽는다. 꺼져 있으면 아무것도 바꾸지 않는다(전부 503 그대로).

★ C4(customer_auth.py)는 파일 전체 해시와 «DB 를 import 하지 않는다»가 테스트로 고정돼 있다(커머스 V3 계약 포함).
  그래서 C4 파일은 고치지 않고, C4 가 이미 «호출 시점에» 찾아 쓰는 세 자리만 서버 조립 단계에서 바꾼다:
    RUNTIME_RESOLVER      me() 가 부른다
    _runtime_middleware   member_middleware() 가 매 요청 부른다(create_member_middleware 결과 그대로)
    router.routes         /api/auth/me 를 새 해석기로 -- main 이 라우터를 싣기 «전»이라 그대로 반영된다
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import customer_auth as C4
from . import customer_identity as identity
from . import customer_oidc as OIDC

log = logging.getLogger("customer_auth_runtime")
router = APIRouter(prefix="/api/my")


def install_resolver(resolver) -> None:
    if type(resolver) is not C4.VerifiedSessionResolver:
        raise TypeError("VerifiedSessionResolver required")
    C4.RUNTIME_RESOLVER = resolver
    C4._runtime_middleware = C4.create_member_middleware(resolver)
    C4.router.routes[:] = C4.create_auth_router(resolver).routes


def install(engine=None) -> bool:
    """켜져 있으면 실제 해석기를 끼우고 True. 꺼져 있으면 아무것도 안 하고 False."""
    if not OIDC.enabled():
        return False
    from . import customer_auth_issuer as ISS
    if engine is None:
        from .db import engine
    install_resolver(ISS.build_runtime_resolver(engine))
    log.warning("[customer-auth] runtime resolver installed providers=%s", ",".join(sorted(OIDC.providers())))
    return True


@router.get("/profile")
def my_profile(request: Request):
    """미들웨어가 세션·인증 맥락을 이미 확인했다. 내보내기 직전에 한 번 더 새로 읽는다(require_verified_session)."""
    try:
        current = C4.require_verified_session()
        body = identity.profile_payload(current.member, current.session, now=current.now,
                                        expected_context=request.headers.get("x-popcorn-auth-context"))
    except identity.IdentityError as e:
        raise HTTPException(e.status if e.status in (401, 409) else 503,
                            detail={"code": e.code if e.status in (401, 409) else "auth_unavailable"},
                            headers=C4.NO_STORE) from None
    return JSONResponse(body, headers=C4.NO_STORE)


INSTALLED = install()
