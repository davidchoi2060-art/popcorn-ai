"""고객 소셜 로그인 HTTP 경로 (설계 docs/design/customer-social-login-v1.md §2.1·§3, P2) -- `api/main.py` 가 자동으로 싣는다.

  GET  /api/auth/providers                 켜진 공급자 목록(화면이 버튼을 그릴지 정한다)
  GET  /api/auth/{provider}/start          로그인 시작 -> 공급자로 302 (state 는 이 브라우저 쿠키에도)
  GET  /api/auth/{provider}/callback       공급자에서 돌아옴 -> 회원이면 세션 쿠키 + 원래 화면, 아니면 가입 동의 화면
  GET  /api/auth/join/pending              가입 동의 화면이 보일 표시용 정보(공급자 · 닉네임 기본값)
  POST /api/auth/join                      동의(필수 3개) -> 회원 + 세션 + 이 브라우저 기록 귀속
  POST /api/auth/attach-guest              로그인 뒤 이 브라우저의 보관 견적을 회원에 붙인다(견적 보관 키 헤더 필요)
  POST /api/auth/signout                   세션 철회 + 쿠키 삭제

★ CUSTOMER_AUTH_ENABLED=on 과 공급자 키가 없으면 전부 503 auth_unavailable(providers 만 enabled:false).
  기존 /api/auth/login(이메일)·/logout 은 customer_auth.py 그대로(503). /me 는 켜지면 customer_auth_runtime 이 실제 해석기로 바꾼다.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import customer_auth_issuer as ISS
from . import customer_oidc as OIDC
from . import visitor
from .customer_auth import COOKIE, NO_STORE, cookie_secure
from .db import engine

log = logging.getLogger("customer_auth_oauth")     # ASCII 로그만(공급자 이름 · 사유 코드)
router = APIRouter(prefix="/api/auth")

STATE_COOKIE = "popcorn_oauth_state"
PENDING_COOKIE = "popcorn_join_pending"
JOIN_PAGE = "/mvp3/join.html"                       # 화면은 코덱스 디자인 뒤 P3
PROVIDERS = ("google", "kakao", "naver")


def _closed():
    return HTTPException(503, detail={"code": "auth_unavailable"}, headers=NO_STORE)


def _config(provider: str) -> OIDC.ProviderConfig:
    if provider not in PROVIDERS or not OIDC.enabled():
        raise _closed()
    cfg = OIDC.providers().get(provider)
    if cfg is None:
        raise _closed()
    return cfg


def _cookie(resp, name, value, *, max_age, path):
    resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=cookie_secure(), path=path)


def _same_origin(request: Request):
    from .mvp3_saved_quotes import same_origin
    same_origin(request)


def _redirect(url: str):
    r = RedirectResponse(url, status_code=302)
    r.headers.update(NO_STORE)
    return r


def _fail_redirect(return_path: str, code: str):
    sep = "&" if "?" in return_path else "?"
    r = _redirect(ISS.safe_return(return_path) + sep + "login_error=" + quote(code))
    r.delete_cookie(STATE_COOKIE, path="/api/auth/")
    return r


@router.get("/providers")
def list_providers():
    on = OIDC.enabled()
    return JSONResponse({"enabled": on, "providers": sorted(OIDC.providers()) if on else []}, headers=NO_STORE)


@router.get("/join/pending")
def join_pending(request: Request):
    if not OIDC.enabled():
        raise _closed()
    try:
        with engine.connect() as conn:
            row = ISS.read_pending(conn, request.cookies.get(PENDING_COOKIE))
    except ISS.AuthFlowError as e:
        raise HTTPException(e.status, detail={"code": e.code}, headers=NO_STORE) from None
    return JSONResponse({"provider": row["issuer_key"], "nickname": row["display_nickname"],
                         "consent_version": ISS.CONSENT_VERSION,
                         "required": list(ISS.REQUIRED_CONSENTS), "optional": list(ISS.OPTIONAL_CONSENTS)},
                        headers=NO_STORE)


class JoinBody(BaseModel):
    consents: dict = Field(default_factory=dict)
    nickname: str | None = Field(default=None, max_length=100)


def _owner_hash(request: Request) -> str | None:
    from .mvp3_saved_quotes import owner_hash
    try:
        return owner_hash(request)
    except HTTPException:
        return None


def _visitor(conn, request: Request) -> int | None:
    return visitor.resolve(conn, request)            # 읽기만(쿠키가 없으면 None)


@router.post("/join")
def join(request: Request, body: JoinBody | None = None):
    if not OIDC.enabled():
        raise _closed()
    _same_origin(request)
    body = body or JoinBody()
    try:
        with engine.begin() as conn:
            r = ISS.join(conn, request.cookies.get(PENDING_COOKIE), body.consents, nickname=body.nickname)
            token = ISS.issue_session(conn, member_id=r["member_id"], identity_id=r["identity_id"],
                                      auth_revision=r["auth_revision"], principal=r["principal"],
                                      user_agent=request.headers.get("user-agent"))
            uid = _visitor(conn, request)
            attached = ISS.attach_guest(conn, r["member_id"], user_id=uid, owner_key_hash=_owner_hash(request))
            visitor.promote(conn, uid, r["member_id"])
    except ISS.AuthFlowError as e:
        raise HTTPException(e.status, detail={"code": e.code}, headers=NO_STORE) from None
    log.info("[customer-auth] join ok provider=%s", r["principal"].issuer_key)
    resp = JSONResponse({"ok": True, "return_path": r["return_path"], "attached": attached}, headers=NO_STORE)
    _cookie(resp, COOKIE, token, max_age=ISS.SESSION_DAYS * 86400, path="/")
    resp.delete_cookie(PENDING_COOKIE, path="/api/auth/")
    return resp


@router.post("/attach-guest")
def attach_guest(request: Request):
    if not OIDC.enabled():
        raise _closed()
    _same_origin(request)
    with engine.begin() as conn:
        member_id = ISS.session_member(conn, request.cookies.get(COOKIE))
        if member_id is None:
            raise HTTPException(401, detail={"code": "unauthenticated"}, headers=NO_STORE)
        attached = ISS.attach_guest(conn, member_id, user_id=_visitor(conn, request),
                                    owner_key_hash=_owner_hash(request))
    return JSONResponse({"ok": True, "attached": attached}, headers=NO_STORE)


@router.post("/signout")
def signout(request: Request):
    _same_origin(request)
    revoked = False
    if OIDC.enabled():
        with engine.begin() as conn:
            revoked = ISS.revoke_session(conn, request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True, "revoked": revoked}, headers=NO_STORE)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/{provider}/start")
def start(provider: str, request: Request):
    cfg = _config(provider)
    with engine.begin() as conn:
        state, nonce, verifier = ISS.begin_attempt(conn, provider, request.query_params.get("return") or ISS.DEFAULT_RETURN)
    resp = _redirect(OIDC.authorize_url(cfg, state=state, nonce=nonce, verifier=verifier))
    _cookie(resp, STATE_COOKIE, state, max_age=ISS.ATTEMPT_TTL, path="/api/auth/")
    return resp


@router.get("/{provider}/callback")
def callback(provider: str, request: Request):
    cfg = _config(provider)
    q = request.query_params
    state = q.get("state") or ""
    if q.get("error"):                                  # 고객이 공급자 화면에서 취소했다
        log.info("[customer-auth] callback cancelled provider=%s", provider)
        return _fail_redirect(ISS.DEFAULT_RETURN, "cancelled")
    try:
        with engine.begin() as conn:
            attempt = ISS.consume_attempt(conn, provider, state, request.cookies.get(STATE_COOKIE))
        login = OIDC.verify_callback(cfg, code=q.get("code") or "", verifier=attempt["pkce_verifier"],
                                     nonce_hash=attempt["nonce_hash"], state=state)
        with engine.begin() as conn:
            found = ISS.find_member(conn, login.principal)
            if found is not None:
                token = ISS.issue_session(conn, member_id=found["member_id"], identity_id=found["identity_id"],
                                          auth_revision=found["auth_revision"], principal=login.principal,
                                          user_agent=request.headers.get("user-agent"))
                uid = _visitor(conn, request)
                ISS.attach_guest(conn, found["member_id"], user_id=uid, owner_key_hash=None)
                visitor.promote(conn, uid, found["member_id"])
                pending = None
            else:
                pending = ISS.create_pending(conn, login, attempt["return_path"])
                token = None
    except ISS.AuthFlowError as e:
        log.info("[customer-auth] callback refused provider=%s code=%s", provider, e.code)
        return _fail_redirect(ISS.DEFAULT_RETURN, e.code)
    except OIDC.ProviderError as e:
        log.info("[customer-auth] provider failed provider=%s code=%s", provider, e.code)
        return _fail_redirect(ISS.DEFAULT_RETURN, "provider_failed")
    if token:
        log.info("[customer-auth] login ok provider=%s", provider)
        resp = _redirect(attempt["return_path"])
        _cookie(resp, COOKIE, token, max_age=ISS.SESSION_DAYS * 86400, path="/")
    else:
        log.info("[customer-auth] join needed provider=%s", provider)
        resp = _redirect(JOIN_PAGE)
        _cookie(resp, PENDING_COOKIE, pending, max_age=ISS.ATTEMPT_TTL, path="/api/auth/")
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/")
    return resp

