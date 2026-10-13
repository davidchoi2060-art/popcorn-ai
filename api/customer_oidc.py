"""I1 -- 구글·카카오·네이버 신원 검증 어댑터 (설계 docs/design/customer-social-login-v1.md §2·§3·§5, P2).

공급자에서 돌아온 code 를 서버가 토큰으로 바꾸고 신원을 검증한 뒤, 그때만 C1 의 VerifiedPrincipal 을 만든다
(`VerifiedPrincipal._from_server_verifier` -- 클라이언트 값으로는 못 만든다).

  구글·카카오  OpenID Connect -- ID 토큰 서명을 공급자 JWKS 로 검증하고 iss·aud·exp·nonce 를 확인한다.
  네이버       OAuth 2.0 -- 받은 access token 으로 프로필 API(openapi.naver.com/v1/nid/me)를 서버가 한 번 부른다.

받는 것은 공급자 고유 ID(subject) 하나가 필수이고, 닉네임·이메일은 «표시용 선택 정보»다(회원 식별에 쓰지 않는다).
공급자 access/refresh token 은 검증 직후 버린다 -- 어디에도 저장하지 않는다.

설정은 /etc/popcorn-ai.env 의 환경 변수에서만 읽는다(저장소·채팅에 키를 두지 않는다):
  CUSTOMER_AUTH_ENABLED=on · CUSTOMER_AUTH_BASE_URL(기본 https://www.popcornai.co.kr)
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
  KAKAO_REST_API_KEY / KAKAO_CLIENT_SECRET
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
키가 없는 공급자는 «준비 안 됨»이다(그 버튼만 닫힌다).
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from . import customer_identity as identity

AUTHORITY_REF = "popcorn-oidc-v1"     # 이 서버가 검증해 발급했다는 영수증의 발급원 이름(설정 값 -- SQL 이 고르지 않는다)
DEFAULT_BASE_URL = "https://www.popcornai.co.kr"
HTTP_TIMEOUT = (5, 10)
CLOCK_SKEW_SEC = 120


class ProviderError(Exception):
    """공급자 통신·검증 실패. 사유 코드만 담는다(토큰·응답 원문은 담지 않는다)."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderConfig:
    provider: str             # google | kakao | naver  (= IssuerRegistration.via)
    issuer: str
    authorize_url: str
    token_url: str
    scope: str
    client_id: str
    client_secret: str
    verification_method: str  # oidc_id_token | oauth2_profile_api
    jwks_url: str | None = None
    profile_url: str | None = None
    pkce: bool = True

    @property
    def issuer_key(self) -> str:
        return self.provider

    @property
    def registration_ref(self) -> str:
        """등록 앱을 가리키는 고정 문자열. 클라이언트 ID 원문 대신 해시 앞부분을 쓴다.
        키를 바꾸면 값이 달라져 기존 세션이 복원되지 않는다(다시 로그인) -- 의도한 동작이다."""
        return "%s-app:%s" % (self.provider, hashlib.sha256(self.client_id.encode()).hexdigest()[:12])

    def registration(self) -> identity.IssuerRegistration:
        return identity.IssuerRegistration(issuer_key=self.issuer_key, issuer=self.issuer,
                                           registration_ref=self.registration_ref,
                                           verification_method=self.verification_method, via=self.provider)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def providers() -> dict[str, ProviderConfig]:
    """키가 갖춰진 공급자만. 매번 환경에서 읽는다(서버 재시작 없이 키를 넣는 경우는 없지만 시험이 쉽다)."""
    out: dict[str, ProviderConfig] = {}
    gid, gsec = _env("GOOGLE_OAUTH_CLIENT_ID"), _env("GOOGLE_OAUTH_CLIENT_SECRET")
    if gid and gsec:
        out["google"] = ProviderConfig(
            "google", "https://accounts.google.com", "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token", "openid email profile", gid, gsec, "oidc_id_token",
            jwks_url="https://www.googleapis.com/oauth2/v3/certs", pkce=True)
    kid, ksec = _env("KAKAO_REST_API_KEY"), _env("KAKAO_CLIENT_SECRET")
    if kid and ksec:
        out["kakao"] = ProviderConfig(
            "kakao", "https://kauth.kakao.com", "https://kauth.kakao.com/oauth/authorize",
            "https://kauth.kakao.com/oauth/token", "openid", kid, ksec, "oidc_id_token",
            jwks_url="https://kauth.kakao.com/.well-known/jwks.json", pkce=True)
    nid, nsec = _env("NAVER_CLIENT_ID"), _env("NAVER_CLIENT_SECRET")
    if nid and nsec:
        out["naver"] = ProviderConfig(
            "naver", "https://nid.naver.com", "https://nid.naver.com/oauth2.0/authorize",
            "https://nid.naver.com/oauth2.0/token", "", nid, nsec, "oauth2_profile_api",
            profile_url="https://openapi.naver.com/v1/nid/me", pkce=False)
    return out


def enabled() -> bool:
    return _env("CUSTOMER_AUTH_ENABLED") == "on" and bool(providers())


def base_url() -> str:
    return (_env("CUSTOMER_AUTH_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def redirect_uri(provider: str) -> str:
    return "%s/api/auth/%s/callback" % (base_url(), provider)


# ── 요청 위조 방지 값 ─────────────────────────────────────────────────────────
def new_secret() -> str:
    return secrets.token_urlsafe(32)          # 43자


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorize_url(cfg: ProviderConfig, *, state: str, nonce: str, verifier: str) -> str:
    q = {"response_type": "code", "client_id": cfg.client_id, "redirect_uri": redirect_uri(cfg.provider),
         "state": state}
    if cfg.scope:
        q["scope"] = cfg.scope
    if cfg.verification_method == "oidc_id_token":
        q["nonce"] = nonce
    if cfg.pkce:
        q["code_challenge"], q["code_challenge_method"] = pkce_challenge(verifier), "S256"
    if cfg.provider == "google":
        q["prompt"] = "select_account"
    return cfg.authorize_url + "?" + urlencode(q)


# ── 토큰 교환 · 검증 ──────────────────────────────────────────────────────────
def _post_token(cfg: ProviderConfig, *, code: str, verifier: str, state: str, session=requests) -> dict:
    data = {"grant_type": "authorization_code", "client_id": cfg.client_id, "client_secret": cfg.client_secret,
            "code": code, "redirect_uri": redirect_uri(cfg.provider)}
    if cfg.pkce:
        data["code_verifier"] = verifier
    if cfg.provider == "naver":
        data["state"] = state
    try:
        r = session.post(cfg.token_url, data=data, timeout=HTTP_TIMEOUT,
                         headers={"Accept": "application/json"})
    except Exception:  # noqa: BLE001 - 통신 실패는 사유 코드로만
        raise ProviderError("token_unreachable") from None
    if r.status_code != 200:
        raise ProviderError("token_rejected")
    try:
        body = r.json()
    except ValueError:
        raise ProviderError("token_unreadable") from None
    if not isinstance(body, dict) or body.get("error"):
        raise ProviderError("token_rejected")
    return body


_jwks_clients: dict = {}


def _verify_id_token(cfg: ProviderConfig, id_token: str, *, nonce_hash: str) -> dict:
    """서명·iss·aud·exp 검증 뒤 nonce 대조. DB 엔 nonce 해시만 있으므로 토큰의 nonce 를 sha256 해서 비교한다."""
    import jwt                                    # PyJWT[crypto] -- 이 경로에서만 쓴다
    try:
        client = _jwks_clients.get(cfg.jwks_url)
        if client is None:
            client = _jwks_clients[cfg.jwks_url] = jwt.PyJWKClient(cfg.jwks_url, cache_keys=True, timeout=10)
        key = client.get_signing_key_from_jwt(id_token).key
        issuers = [cfg.issuer] + (["accounts.google.com"] if cfg.provider == "google" else [])
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=cfg.client_id, issuer=issuers,
                            leeway=CLOCK_SKEW_SEC, options={"require": ["sub", "iss", "aud", "exp", "iat"]})
    except Exception:  # noqa: BLE001 - 서명·클레임 실패는 하나의 사유로
        raise ProviderError("id_token_invalid") from None
    if not nonce_hash or not secrets.compare_digest(sha256_hex(str(claims.get("nonce") or "")), nonce_hash):
        raise ProviderError("nonce_mismatch")
    return claims


def _naver_profile(cfg: ProviderConfig, access_token: str, session=requests) -> dict:
    try:
        r = session.get(cfg.profile_url, headers={"Authorization": "Bearer " + access_token}, timeout=HTTP_TIMEOUT)
        body = r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        raise ProviderError("profile_unreachable") from None
    if not isinstance(body, dict) or body.get("resultcode") != "00" or not isinstance(body.get("response"), dict):
        raise ProviderError("profile_rejected")
    return body["response"]


def _short(value, limit):
    return value[:limit] if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class VerifiedLogin:
    principal: identity.VerifiedPrincipal
    display_nickname: str | None       # 가입 화면 기본값으로만 쓴다(회원 원장 연락처가 아니다)
    display_email: str | None


def verify_callback(cfg: ProviderConfig, *, code: str, verifier: str, nonce_hash: str, state: str,
                    session=requests, now: int | None = None) -> VerifiedLogin:
    """code -> 검증된 신원. 실패는 ProviderError(사유 코드)."""
    if not isinstance(code, str) or not code or len(code) > 2048:
        raise ProviderError("code_missing")
    tokens = _post_token(cfg, code=code, verifier=verifier, state=state, session=session)
    verified_at = int(now if now is not None else time.time())
    if cfg.verification_method == "oidc_id_token":
        claims = _verify_id_token(cfg, str(tokens.get("id_token") or ""), nonce_hash=nonce_hash)
        subject = claims.get("sub")
        nickname = claims.get("nickname") or claims.get("name")
        email = claims.get("email") if claims.get("email_verified") in (True, "true") else None
    else:
        profile = _naver_profile(cfg, str(tokens.get("access_token") or ""), session=session)
        subject, nickname, email = profile.get("id"), profile.get("nickname"), profile.get("email")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise ProviderError("subject_missing")
    principal = identity.VerifiedPrincipal._from_server_verifier(cfg.registration(), subject=subject,
                                                                 verified_at=verified_at)
    return VerifiedLogin(principal, _short(nickname, 100), _short(email, 255))
