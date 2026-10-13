"""고객 회원 P2b -- 실제 세션 해석기 연결 (설계 docs/design/customer-social-login-v1.md §5).

꺼져 있으면(CUSTOMER_AUTH_ENABLED 없음) 아무것도 바뀌지 않는다 -- /api/auth/me·/api/my/* 는 503 그대로.
켜면 customer_auth_runtime 이 발급기 포트로 만든 해석기를 customer_auth 의 해석기 자리에 끼운다(C4 파일은 그대로 -- 해시 고정).
개발 DB 에서 가입 -> 세션 발급 -> 실제 조립 해석기로 resolve/confirm -> 철회·회원 개정·스위치 끔까지
한 트랜잭션으로 돌리고 ROLLBACK 한 검증 기록은 PR 본문에 있다.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import customer_auth as C4
from api import customer_auth_runtime as RT
from api import customer_identity as identity

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "a" * 64
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()
CONTEXT = "11111111-1111-4111-8111-111111111111"


def _snapshot():
    reg = identity.IssuerRegistration("google", "https://accounts.google.com", "google-app:abc", "oidc_id_token", "google")
    principal = identity.VerifiedPrincipal._from_server_verifier(reg, subject="g-1", verified_at=100)
    member = identity.CanonicalMember(member_id=101, auth_subject="22222222-2222-4222-8222-222222222222",
                                      principal_revision=1, status="active", nickname="회원", email=None)
    mapping = identity.VerifiedIdentityMapping(identity_id=17, member=member, issuer_key="google",
                                               issuer="https://accounts.google.com", subject="g-1", verified_at=90,
                                               verification_method="oidc_id_token", registration_ref="google-app:abc")
    session = identity.SessionContext(member_id=101, verified_identity_id=17, issued_auth_revision=1,
                                      session_context_id=CONTEXT, issued_at=100, expires_at=200)
    return C4.PersistedSessionSnapshot(credential_hash=DIGEST, principal=principal, mappings=(mapping,),
                                       session=session, now=120)


class _Repo:
    def schema_ready(self):
        return True

    def read_verified_session(self, digest):
        return _snapshot() if digest == DIGEST else None


class _Issuer:
    def ready(self):
        return True


@pytest.fixture
def restore_c4(monkeypatch):
    monkeypatch.setattr(C4, "RUNTIME_RESOLVER", C4.RUNTIME_RESOLVER)
    monkeypatch.setattr(C4, "_runtime_middleware", C4._runtime_middleware)
    routes = list(C4.router.routes)
    yield
    C4.router.routes[:] = routes


def _app():
    app = FastAPI()
    app.include_router(C4.router)
    app.include_router(RT.router)
    app.middleware("http")(C4.member_middleware)
    return TestClient(app, base_url="https://www.popcornai.co.kr")


def test_disabled_by_default_nothing_installed(restore_c4, monkeypatch):
    monkeypatch.delenv("CUSTOMER_AUTH_ENABLED", raising=False)
    before = C4.RUNTIME_RESOLVER
    assert RT.install(engine=object()) is False and C4.RUNTIME_RESOLVER is before
    c = _app()
    r = c.get("/api/auth/me", headers={"cookie": C4.COOKIE + "=" + TOKEN})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "auth_unavailable"
    assert c.get("/api/my/profile", headers={"cookie": C4.COOKIE + "=" + TOKEN,
                                             "x-popcorn-auth-context": CONTEXT}).status_code == 503


def test_import_without_switch_opens_no_db():
    code = ("import os,sys; os.environ.pop('CUSTOMER_AUTH_ENABLED',None); os.environ['DATABASE_URL']='postgresql+psycopg2://x:x@127.0.0.1:1/x';"
            "import api.customer_auth_runtime as RT; print(RT.INSTALLED, 'api.db' in sys.modules, 'api.customer_auth_issuer' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["False", "False", "False"], out.stderr[-500:]


def test_install_rejects_anything_but_verified_resolver(restore_c4):
    for bad in (None, object(), _Repo()):
        with pytest.raises(TypeError):
            RT.install_resolver(bad)


def test_installed_resolver_serves_me_profile_and_middleware(restore_c4):
    RT.install_resolver(C4.VerifiedSessionResolver(_Repo(), _Issuer()))
    c = _app()
    assert c.get("/api/auth/me").json()["phase"] == "signed-out"
    me = c.get("/api/auth/me", headers={"cookie": C4.COOKIE + "=" + TOKEN})
    body = me.json()
    assert me.status_code == 200 and body["authenticated"] is True and body["member"]["via"] == "google"
    assert body["auth_context"]["session_context_id"] == CONTEXT and "g-1" not in me.text   # 공급자 ID 안 보임
    assert me.headers["cache-control"] == "no-store"
    p = c.get("/api/my/profile", headers={"cookie": C4.COOKIE + "=" + TOKEN, "x-popcorn-auth-context": CONTEXT})
    assert p.status_code == 200 and p.json()["profile"]["nickname"] == "회원"
    assert c.get("/api/my/profile", headers={"cookie": C4.COOKIE + "=" + TOKEN}).status_code == 409     # 맥락 헤더 없음
    assert c.get("/api/my/profile", headers={"x-popcorn-auth-context": CONTEXT}).status_code == 401    # 쿠키 없음
    assert c.get("/api/auth/me", headers={"cookie": C4.COOKIE + "=" + "f" * 64}).status_code == 401  # 모르는 세션
    assert c.get("/api/my/saved", headers={"cookie": C4.COOKIE + "=" + TOKEN,
                                           "x-popcorn-auth-context": CONTEXT}).status_code == 503    # 다른 /api/my/* 는 아직 닫힘


def test_install_with_switch_uses_issuer_composition(restore_c4, monkeypatch):
    from api import customer_auth_issuer as ISS
    monkeypatch.setenv("CUSTOMER_AUTH_ENABLED", "on")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "g")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "s")
    seen = []
    monkeypatch.setattr(ISS, "build_runtime_resolver",
                        lambda engine: seen.append(engine) or C4.VerifiedSessionResolver(_Repo(), _Issuer()))
    eng = object()
    assert RT.install(engine=eng) is True and seen == [eng]
    assert type(C4.RUNTIME_RESOLVER.repository) is _Repo


def test_installed_middleware_is_create_member_middleware_product(restore_c4):
    resolver = C4.VerifiedSessionResolver(_Repo(), _Issuer())
    RT.install_resolver(resolver)
    mw = C4._runtime_middleware
    assert mw.__qualname__ == "create_member_middleware.<locals>.boundary"
    assert dict(zip(mw.__code__.co_freevars, (c.cell_contents for c in mw.__closure__)))["resolver"] is resolver
    assert C4.RUNTIME_RESOLVER is resolver


def test_c4_file_untouched_and_imports_no_db():
    src = (ROOT / "api" / "customer_auth.py").read_text(encoding="utf-8")
    assert "from .db" not in src and "sqlalchemy" not in src and "customer_auth_issuer" not in src
