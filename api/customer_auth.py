"""C4 persisted customer session boundary, with an unavailable runtime adapter.

Only explicit trusted server repository/verifier ports may resolve a session.
C2/I1 are not connected here. No DB, issuer, secret-file or session initialization
occurs on import. Positive repositories exist only in the boundary tests.
GET /api/my/profile is the sole private-read scope; C5 supplies its handler.
"""
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import hmac
import os
import re
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import customer_identity as identity

COOKIE = "popcorn_member_session"
ABSOLUTE_DAYS = 14
VIA = {"카카오":"kakao", "네이버":"naver", "구글":"google", "이메일":"email",
       "kakao":"kakao", "naver":"naver", "google":"google", "email":"email", "dev":"email"}
GUARDED_PREFIX = "/api/my/"
OPEN_PREFIXES = ("/api/auth/", "/shared/", "/design-system/", "/admin2/", "/admin/", "/api/admin/")
NO_STORE = {"Cache-Control":"no-store", "Pragma":"no-cache", "Expires":"0"}
_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
_RESOLUTION_SEAL = object()
_current = ContextVar("current_member", default=None)


def _error(status, code):
    return HTTPException(status, detail={"code":code}, headers=NO_STORE)


def _no_store(response):
    response.headers.update(NO_STORE)
    for name in ("etag", "last-modified"):
        if name in response.headers:
            del response.headers[name]
    return response


def cookie_secure() -> bool:
    """Existing visitor-cookie helper; never enables customer auth."""
    return os.environ.get("COOKIE_SECURE", "").strip() in ("1", "true", "True", "yes")


@dataclass(frozen=True, slots=True, repr=False)
class PersistedSessionSnapshot:
    """Trusted current read of verified issuance provenance, mapping and session.

    C2 must provide fresh persisted provenance/FKs/state and a consistent now.
    This typed DTO alone does not establish persistence or cryptographic proof.
    """
    credential_hash: str
    principal: identity.VerifiedPrincipal
    mappings: tuple[identity.VerifiedIdentityMapping, ...]
    session: identity.SessionContext
    now: int


class VerifiedSessionRepository(Protocol):
    def schema_ready(self) -> bool: ...
    def read_verified_session(self, credential_hash: str) -> PersistedSessionSnapshot | None: ...


class IssuerReadiness(Protocol):
    def ready(self) -> bool: ...


class RuntimeSessionRepository:
    """No live schema/DB reader is connected. No legacy fallback."""
    def schema_ready(self):
        return False
    def read_verified_session(self, credential_hash):
        raise _error(503, "auth_unavailable")


class RuntimeIssuerReadiness:
    def ready(self):
        return False
    def verify(self, proof):
        return identity.RuntimeIssuerVerifier().verify(proof)


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedSessionResolution:
    member: identity.VerifiedMember
    session: identity.SessionContext
    credential_hash: str
    now: int
    _seal: object

    def key(self):
        if self._seal is not _RESOLUTION_SEAL:
            raise _error(401, "unauthenticated")
        canonical = self.member.member
        return (canonical.member_id, canonical.auth_subject, self.member.identity_id,
                self.session.session_context_id, canonical.principal_revision,
                self.member.principal.issuer_key, self.member.principal.issuer,
                self.member.principal.subject, self.member.principal.verification_method,
                self.member.principal.registration_ref)


class VerifiedSessionResolver:
    """Server-injected ports only. Client fields/env flags cannot select them."""
    def __init__(self, repository: VerifiedSessionRepository, issuer: IssuerReadiness):
        self.repository, self.issuer = repository, issuer

    def _ready(self):
        try:
            ready = self.issuer.ready() is True and self.repository.schema_ready() is True
        except Exception:
            raise _error(503, "auth_unavailable") from None
        if not ready:
            raise _error(503, "auth_unavailable")

    def resolve(self, sid, *, expected_context=None):
        self._ready()
        if sid is None:
            return None
        if type(sid) is not str:
            raise _error(401, "unauthenticated")
        if sid == "":
            return None
        if not _TOKEN.fullmatch(sid):
            raise _error(401, "unauthenticated")
        digest = hashlib.sha256(sid.encode("ascii")).hexdigest()
        try:
            row = self.repository.read_verified_session(digest)
        except Exception:
            raise _error(503, "auth_unavailable") from None
        if row is None:
            raise _error(401, "unauthenticated")
        if (type(row) is not PersistedSessionSnapshot
                or type(row.credential_hash) is not str or not _TOKEN.fullmatch(row.credential_hash)
                or type(row.mappings) is not tuple):
            raise _error(503, "auth_unavailable")
        if not hmac.compare_digest(row.credential_hash, digest):
            raise _error(401, "unauthenticated")
        try:
            member = identity.resolve_identity(row.principal, row.mappings, now=row.now)
            identity.auth_context(member, row.session, now=row.now, expected_context=expected_context)
        except identity.IdentityError as error:
            if error.status in (401,409):
                raise _error(error.status, error.code) from None
            raise _error(503, "auth_unavailable") from None
        self._ready()
        return VerifiedSessionResolution(member, row.session, digest, row.now, _RESOLUTION_SEAL)

    def confirm(self, sid, before, *, expected_context=None):
        """Fresh read before query/emission; never reuse a cached snapshot."""
        if type(before) is not VerifiedSessionResolution or before._seal is not _RESOLUTION_SEAL:
            raise _error(401, "unauthenticated")
        current = self.resolve(sid, expected_context=expected_context)
        if current is None:
            raise _error(401, "unauthenticated")
        if current.credential_hash != before.credential_hash or current.key() != before.key():
            raise _error(409, "auth_context_changed")
        return current


RUNTIME_RESOLVER = VerifiedSessionResolver(RuntimeSessionRepository(), RuntimeIssuerReadiness())


def _cookie(request):
    values = request.headers.getlist("cookie")
    if len(values) > 1:
        raise _error(401, "unauthenticated")
    found = []
    for part in (values[0].split(";") if values else ()):
        name, separator, value = part.strip().partition("=")
        if name == COOKIE:
            if not separator:
                raise _error(401, "unauthenticated")
            found.append(value)
    if len(found) > 1:
        raise _error(401, "unauthenticated")
    return found[0] if found else None


def _expected(request):
    values = request.headers.getlist("x-popcorn-auth-context")
    if len(values) != 1 or not values[0]:
        raise _error(409, "auth_context_changed")
    return values[0]


@dataclass(frozen=True, slots=True, repr=False)
class _RequestScope:
    resolver: VerifiedSessionResolver
    sid: str
    resolution: VerifiedSessionResolution
    expected_context: str


def require_verified_session():
    """C5 calls again immediately before query and immediately before emit."""
    scope = _current.get()
    if type(scope) is not _RequestScope:
        raise _error(401, "unauthenticated")
    return scope.resolver.confirm(scope.sid, scope.resolution, expected_context=scope.expected_context)


def current_member() -> dict | None:
    if _current.get() is None:
        return None
    current = require_verified_session()
    canonical = current.member.member
    return {"member_id":canonical.member_id, "auth_subject":canonical.auth_subject,
            "email":canonical.email, "nickname":canonical.nickname, "via":current.member.principal.via}


def require_member() -> dict:
    member = current_member()
    if member is None:
        raise _error(401, "unauthenticated")
    return member


def resolve_session(sid):
    """Legacy optional-member compatibility; runtime cannot restore a member."""
    return None


def _new_session(*args, **kwargs):
    raise _error(503, "auth_unavailable")


def _needs_member_resolution(path, method):
    # Preserve accepted owner/detail/support/fulfillment exceptions.
    return (path != "/api/commerce/owner-context"
            and not (method == "GET" and len(path.split("/")) == 5
                     and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                     and path.split("/")[4] != "")
            and not (len(path.split("/")) in (6, 7)
                     and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                     and path.split("/")[4] != "" and path.split("/")[5] == "support"
                     and (len(path.split("/")) == 6 or path.split("/")[6] == ""))
            and not (method == "GET" and len(path.split("/")) in (6, 7)
                     and path.split("/")[:4] == ["", "api", "commerce", "orders"]
                     and path.split("/")[4] != "" and path.split("/")[5] == "fulfillment"
                     and (len(path.split("/")) == 6 or path.split("/")[6] == ""))
            and not path.startswith(OPEN_PREFIXES))


def create_member_middleware(resolver):
    async def boundary(request, call_next):
        path, method = request.url.path, request.method
        protected = path.startswith(("/api/auth/", GUARDED_PREFIX))
        token = _current.set(None)
        try:
            if _needs_member_resolution(path, method) and path.startswith(GUARDED_PREFIX):
                resolver._ready()
                sid = _cookie(request)
                current = await run_in_threadpool(resolver.resolve, sid)
                if current is None:
                    raise _error(401, "unauthenticated")
                if (method,path) != ("GET","/api/my/profile"):
                    raise _error(503, "auth_unavailable")
                expected = _expected(request)
                current = await run_in_threadpool(resolver.confirm, sid, current, expected_context=expected)
                _current.set(_RequestScope(resolver, sid, current, expected))
            # Public/guest/admin paths get no member principal or repository lookup.
            response = await call_next(request)
            if protected:
                if response.status_code == 304:
                    response = JSONResponse({"detail":{"code":"auth_unavailable"}}, status_code=503)
                _no_store(response)
            return response
        except HTTPException as error:
            return _no_store(JSONResponse({"detail":error.detail},status_code=error.status_code))
        except Exception:
            if protected:
                return _no_store(JSONResponse({"detail":{"code":"auth_unavailable"}},status_code=503))
            raise
        finally:
            _current.reset(token)
    return boundary


_runtime_middleware = create_member_middleware(RUNTIME_RESOLVER)


async def member_middleware(request, call_next):
    return await _runtime_middleware(request, call_next)


class LoginBody(BaseModel):
    email: str
    nickname: str | None = None
    provider: str = "dev"


def login(body: LoginBody, request: Request, response: Response):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다", headers=NO_STORE)
    raise _error(503, "auth_unavailable")


def logout(request: Request, response: Response):
    # Clear the browser credential without claiming persisted revocation.
    # No live verified revocation adapter or legacy DB mutation is used.
    result = JSONResponse({"detail":{"code":"auth_unavailable"}},status_code=503)
    result.delete_cookie(COOKIE,path="/")
    return _no_store(result)


def _me(request, resolver):
    resolver._ready()
    sid = _cookie(request)
    before = resolver.resolve(sid)
    if before is None:
        resolver._ready()
        return identity.signed_out_payload()
    current = resolver.confirm(sid,before)
    return identity.authenticated_payload(current.member,current.session,now=current.now)


def me(request: Request):
    return _me(request,RUNTIME_RESOLVER)


def create_auth_router(resolver):
    """Explicit server composition for fixtures/future accepted adapters."""
    result = APIRouter(prefix="/api/auth")
    result.add_api_route("/login",login,methods=["POST"])
    result.add_api_route("/logout",logout,methods=["POST"])
    def fixture_or_server_me(request: Request):
        try:
            return _no_store(JSONResponse(_me(request,resolver)))
        except HTTPException as error:
            return _no_store(JSONResponse({"detail":error.detail},status_code=error.status_code))
    result.add_api_route("/me",fixture_or_server_me,methods=["GET"])
    return result


router = create_auth_router(RUNTIME_RESOLVER)
