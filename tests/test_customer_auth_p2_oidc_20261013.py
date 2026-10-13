"""고객 회원 P2a -- 구글·카카오·네이버 신원 검증 + 로그인/가입 경로 (설계 docs/design/customer-social-login-v1.md §2·§3·§5).

공급자 통신은 가짜(서명은 진짜 RSA 키로 만든 ID 토큰)로, DB 는 가짜 엔진으로 돌린다.
발급·가입 SQL 을 개발 DB 에서 한 트랜잭션으로 돌리고 ROLLBACK 한 검증 기록은 PR 본문에 있다.
"""
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import customer_auth_issuer as ISS
from api import customer_auth_oauth as R
from api import customer_identity as identity
from api import customer_oidc as OIDC

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def keys(monkeypatch):
    for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET",
              "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "CUSTOMER_AUTH_ENABLED", "CUSTOMER_AUTH_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "gid.apps")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "gsec")
    monkeypatch.setenv("NAVER_CLIENT_ID", "nid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "nsec")
    return monkeypatch


# ── 설정 ──────────────────────────────────────────────────────────────────────
def test_only_configured_providers_and_flag_required(keys):
    assert sorted(OIDC.providers()) == ["google", "naver"]          # 카카오 키 없음 -> 그 버튼만 닫힘
    assert OIDC.enabled() is False                                   # 켜는 스위치는 따로
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    assert OIDC.enabled() is True
    reg = OIDC.providers()["google"].registration()
    assert type(reg) is identity.IssuerRegistration and reg.via == "google"
    assert "gid.apps" not in reg.registration_ref                   # 클라이언트 ID 원문을 남기지 않는다


def test_authorize_url_has_state_nonce_pkce(keys):
    g = urlparse(OIDC.authorize_url(OIDC.providers()["google"], state="S", nonce="N", verifier="V" * 43))
    q = {k: v[0] for k, v in parse_qs(g.query).items()}
    assert q["state"] == "S" and q["nonce"] == "N" and q["code_challenge_method"] == "S256"
    assert q["code_challenge"] == OIDC.pkce_challenge("V" * 43) and q["scope"] == "openid email profile"
    assert q["redirect_uri"] == "https://www.popcornai.co.kr/api/auth/google/callback"
    n = {k: v[0] for k, v in parse_qs(urlparse(OIDC.authorize_url(OIDC.providers()["naver"], state="S", nonce="N",
                                                                  verifier="V")).query).items()}
    assert "nonce" not in n and "code_challenge" not in n and n["state"] == "S"   # 네이버는 OAuth 2.0


# ── ID 토큰 검증 ──────────────────────────────────────────────────────────────
class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _Http:
    def __init__(self, token_body, profile=None):
        self.token_body, self.profile, self.calls = token_body, profile, []

    def post(self, url, data=None, **kw):
        self.calls.append(("post", url, dict(data)))
        return _Resp(200, self.token_body)

    def get(self, url, headers=None, **kw):
        self.calls.append(("get", url, headers))
        return _Resp(200, self.profile)


def _id_token(**over):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": "gid.apps", "sub": "g-123", "iat": now, "exp": now + 300,
              "nonce": "N0", "name": "홍길동", "email": "a@b.c", "email_verified": True}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, KEY, algorithm="RS256")


@pytest.fixture
def google(keys, monkeypatch):
    cfg = OIDC.providers()["google"]
    monkeypatch.setitem(OIDC._jwks_clients, cfg.jwks_url, _Jwks())
    return cfg


def test_google_id_token_verified_to_principal(google):
    http = _Http({"id_token": _id_token(), "access_token": "x"})
    got = OIDC.verify_callback(google, code="c", verifier="v", nonce_hash=OIDC.sha256_hex("N0"), state="S", session=http)
    p = got.principal
    assert type(p) is identity.VerifiedPrincipal
    assert (p.issuer_key, p.issuer, p.subject, p.via) == ("google", "https://accounts.google.com", "g-123", "google")
    assert (got.display_nickname, got.display_email) == ("홍길동", "a@b.c")
    assert http.calls[0][2]["code_verifier"] == "v"                    # PKCE 보냄


@pytest.mark.parametrize("over,code", [
    ({"aud": "other"}, "id_token_invalid"),
    ({"iss": "https://evil.example"}, "id_token_invalid"),
    ({"exp": int(time.time()) - 3600}, "id_token_invalid"),
    ({"nonce": "other"}, "nonce_mismatch"),
    ({"nonce": None}, "nonce_mismatch"),
])
def test_bad_id_token_refused(google, over, code):
    http = _Http({"id_token": _id_token(**over)})
    with pytest.raises(OIDC.ProviderError) as e:
        OIDC.verify_callback(google, code="c", verifier="v", nonce_hash=OIDC.sha256_hex("N0"), state="S", session=http)
    assert e.value.code == code


def test_forged_signature_refused(google):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode({"iss": "https://accounts.google.com", "aud": "gid.apps", "sub": "x", "iat": now,
                         "exp": now + 300, "nonce": "N0"}, other, algorithm="RS256")
    with pytest.raises(OIDC.ProviderError) as e:
        OIDC.verify_callback(google, code="c", verifier="v", nonce_hash=OIDC.sha256_hex("N0"), state="S",
                             session=_Http({"id_token": forged}))
    assert e.value.code == "id_token_invalid"


def test_unverified_email_not_shown(google):
    http = _Http({"id_token": _id_token(email_verified=False)})
    got = OIDC.verify_callback(google, code="c", verifier="v", nonce_hash=OIDC.sha256_hex("N0"), state="S", session=http)
    assert got.display_email is None


def test_naver_profile_api(keys):
    cfg = OIDC.providers()["naver"]
    http = _Http({"access_token": "AT"}, {"resultcode": "00", "response": {"id": "n-9", "nickname": "nick"}})
    got = OIDC.verify_callback(cfg, code="c", verifier="v", nonce_hash="", state="S", session=http)
    assert (got.principal.issuer_key, got.principal.subject, got.display_nickname) == ("naver", "n-9", "nick")
    assert http.calls[0][2]["state"] == "S" and "code_verifier" not in http.calls[0][2]
    bad = _Http({"access_token": "AT"}, {"resultcode": "024", "message": "fail"})
    with pytest.raises(OIDC.ProviderError):
        OIDC.verify_callback(cfg, code="c", verifier="v", nonce_hash="", state="S", session=bad)


def test_token_error_and_missing_code(google):
    with pytest.raises(OIDC.ProviderError) as e:
        OIDC.verify_callback(google, code="", verifier="v", nonce_hash="h", state="S", session=_Http({}))
    assert e.value.code == "code_missing"
    with pytest.raises(OIDC.ProviderError) as e:
        OIDC.verify_callback(google, code="c", verifier="v", nonce_hash="h", state="S",
                             session=_Http({"error": "invalid_grant"}))
    assert e.value.code == "token_rejected"


# ── 발급기 순수 규칙 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,want", [
    ("/mvp3/talk.html?x=1", "/mvp3/talk.html?x=1"),
    ("https://evil.example/", "/mvp3/"), ("//evil.example", "/mvp3/"), ("/admin2/", "/mvp3/"),
    ("/mvp3/\r\nSet-Cookie:x", "/mvp3/"), (None, "/mvp3/"),
])
def test_safe_return_blocks_open_redirect(path, want):
    assert ISS.safe_return(path) == want


def test_consents_require_terms_privacy_age14():
    assert ISS.validate_consents({"terms": True, "privacy": True, "age14": True}) == {"terms", "privacy", "age14"}
    assert "marketing" in ISS.validate_consents({"terms": True, "privacy": True, "age14": True, "marketing": True})
    for missing in ("terms", "privacy", "age14"):
        c = {"terms": True, "privacy": True, "age14": True}
        c[missing] = False
        with pytest.raises(ISS.AuthFlowError) as e:
            ISS.validate_consents(c)
        assert (e.value.status, e.value.code) == (422, "consent_required")
    with pytest.raises(ISS.AuthFlowError):
        ISS.validate_consents({"terms": "yes", "privacy": 1, "age14": True})   # True 만 동의로 친다


def test_consume_attempt_needs_matching_cookie():
    for state, cookie in (("a", None), ("a", "b"), ("", "")):
        with pytest.raises(ISS.AuthFlowError) as e:
            ISS.consume_attempt(None, "google", state, cookie)                  # DB 를 보기 전에 거절
        assert e.value.code == "state_mismatch"


# ── 경로 ──────────────────────────────────────────────────────────────────────
class _Conn:
    pass


class _Begin:
    def __enter__(self):
        return _Conn()

    def __exit__(self, *a):
        return False


class _Engine:
    def begin(self):
        return _Begin()

    connect = begin


@pytest.fixture
def client(keys, monkeypatch):
    monkeypatch.setattr(R, "engine", _Engine())
    monkeypatch.setattr(R.visitor, "resolve", lambda conn, request: 77)
    monkeypatch.setattr(R.visitor, "promote", lambda conn, uid, mid: None)
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app, base_url="https://www.popcornai.co.kr", follow_redirects=False)


def test_everything_closed_until_enabled(client):
    assert client.get("/api/auth/providers").json() == {"enabled": False, "providers": []}
    for method, path in (("get", "/api/auth/google/start"), ("get", "/api/auth/google/callback?state=x&code=y"),
                         ("get", "/api/auth/join/pending"), ("post", "/api/auth/join"),
                         ("post", "/api/auth/attach-guest")):
        r = getattr(client, method)(path)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "auth_unavailable", path
    assert client.post("/api/auth/signout").status_code == 200                # 쿠키 지우기는 언제나


def test_unknown_or_unconfigured_provider_closed(client, keys):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    assert client.get("/api/auth/kakao/start").status_code == 503             # 키 없음
    assert client.get("/api/auth/github/start").status_code == 503
    assert client.get("/api/auth/providers").json() == {"enabled": True, "providers": ["google", "naver"]}


def test_start_sets_state_cookie_and_redirects(client, keys, monkeypatch):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    seen = {}
    monkeypatch.setattr(ISS, "begin_attempt", lambda conn, p, ret: seen.update(p=p, ret=ret) or ("ST", "NO", "VE" * 22))
    r = client.get("/api/auth/google/start?return=/mvp3/talk.html")
    assert r.status_code == 302 and r.headers["location"].startswith("https://accounts.google.com/")
    assert "state=ST" in r.headers["location"] and seen == {"p": "google", "ret": "/mvp3/talk.html"}
    c = r.headers["set-cookie"]
    assert "popcorn_oauth_state=ST" in c and "HttpOnly" in c and "Path=/api/auth/" in c and "samesite=lax" in c.lower()
    assert r.headers["cache-control"] == "no-store"


def _principal():
    return OIDC.verify_callback.__globals__["identity"].VerifiedPrincipal._from_server_verifier(
        OIDC.providers()["google"].registration(), subject="g-1", verified_at=int(time.time()) - 5)


def test_callback_existing_member_gets_session(client, keys, monkeypatch):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    monkeypatch.setattr(ISS, "consume_attempt", lambda conn, p, s, c: {
        "nonce_hash": "nh", "pkce_verifier": "pv", "return_path": "/mvp3/talk.html"})
    monkeypatch.setattr(OIDC, "verify_callback", lambda cfg, **kw: OIDC.VerifiedLogin(_principal(), "n", None))
    monkeypatch.setattr(ISS, "find_member", lambda conn, p: {"member_id": 5, "identity_id": 9, "auth_revision": 1})
    monkeypatch.setattr(ISS, "issue_session", lambda conn, **kw: "a" * 64)
    attached = []
    monkeypatch.setattr(ISS, "attach_guest", lambda conn, m, **kw: attached.append((m, kw)))
    client.cookies.set("popcorn_oauth_state", "ST", domain="www.popcornai.co.kr", path="/api/auth/")
    r = client.get("/api/auth/google/callback?state=ST&code=C")
    assert r.status_code == 302 and r.headers["location"] == "/mvp3/talk.html"
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("popcorn_member_session=" + "a" * 64) and "HttpOnly" in c and "Path=/" in c for c in cookies)
    assert attached == [(5, {"user_id": 77, "owner_key_hash": None})]


def test_callback_new_identity_goes_to_join(client, keys, monkeypatch):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    monkeypatch.setattr(ISS, "consume_attempt", lambda conn, p, s, c: {
        "nonce_hash": "nh", "pkce_verifier": "pv", "return_path": "/mvp3/"})
    monkeypatch.setattr(OIDC, "verify_callback", lambda cfg, **kw: OIDC.VerifiedLogin(_principal(), "n", None))
    monkeypatch.setattr(ISS, "find_member", lambda conn, p: None)
    monkeypatch.setattr(ISS, "create_pending", lambda conn, login, ret: "b" * 64)
    r = client.get("/api/auth/google/callback?state=ST&code=C")
    assert r.headers["location"] == R.JOIN_PAGE
    assert any(c.startswith("popcorn_join_pending=" + "b" * 64) for c in r.headers.get_list("set-cookie"))
    assert not any(c.startswith("popcorn_member_session=") for c in r.headers.get_list("set-cookie"))


@pytest.mark.parametrize("raise_in,code", [("consume", "state_mismatch"), ("provider", "provider_failed"),
                                            ("cancel", "cancelled")])
def test_callback_failure_returns_with_reason_only(client, keys, monkeypatch, raise_in, code):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")

    def consume(conn, p, s, c):
        if raise_in == "consume":
            raise ISS.AuthFlowError(400, "state_mismatch")
        return {"nonce_hash": "nh", "pkce_verifier": "pv", "return_path": "/mvp3/"}

    def verify(cfg, **kw):
        raise OIDC.ProviderError("id_token_invalid")
    monkeypatch.setattr(ISS, "consume_attempt", consume)
    monkeypatch.setattr(OIDC, "verify_callback", verify)
    q = "error=access_denied&state=ST" if raise_in == "cancel" else "state=ST&code=C"
    r = client.get("/api/auth/google/callback?" + q)
    assert r.status_code == 302 and r.headers["location"] == "/mvp3/?login_error=" + code
    assert not any(c.startswith("popcorn_member_session=") for c in r.headers.get_list("set-cookie"))


def test_join_requires_same_origin_and_consents(client, keys, monkeypatch):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    r = client.post("/api/auth/join", json={"consents": {}}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    monkeypatch.setattr(ISS, "join", lambda conn, tok, c, nickname=None: (_ for _ in ()).throw(
        ISS.AuthFlowError(422, "consent_required")))
    r = client.post("/api/auth/join", json={"consents": {"terms": True}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "consent_required"


def test_join_issues_session_and_attaches(client, keys, monkeypatch):
    keys.setenv("CUSTOMER_AUTH_ENABLED", "on")
    monkeypatch.setattr(ISS, "join", lambda conn, tok, c, nickname=None: {
        "member_id": 5, "identity_id": 9, "auth_revision": 1, "principal": _principal(), "return_path": "/mvp3/q.html"})
    monkeypatch.setattr(ISS, "issue_session", lambda conn, **kw: "c" * 64)
    monkeypatch.setattr(ISS, "attach_guest", lambda conn, m, **kw: {"quotes": 0, "inquiries": 2, "handoffs": 0})
    r = client.post("/api/auth/join", json={"consents": {"terms": True, "privacy": True, "age14": True}})
    assert r.status_code == 200 and r.json() == {"ok": True, "return_path": "/mvp3/q.html",
                                                 "attached": {"quotes": 0, "inquiries": 2, "handoffs": 0}}
    assert any(c.startswith("popcorn_member_session=" + "c" * 64) for c in r.headers.get_list("set-cookie"))


def test_resolver_still_not_wired():
    from api import customer_auth
    assert "customer_auth_issuer" not in (R.__file__ and open(customer_auth.__file__, encoding="utf-8").read())
    assert customer_auth.RuntimeIssuerReadiness().ready() is False             # 해석기 연결은 P2b
