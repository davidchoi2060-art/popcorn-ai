"""고객 세션 발급·철회 + 읽기 쪽 신뢰 포트 (설계 docs/design/customer-social-login-v1.md §3·§4·§5·§6, P2).

■ 쓰기 (모두 호출부가 연 트랜잭션 conn 안에서 -- 한 덩어리로 커밋되거나 함께 되돌아간다)
  begin_attempt     로그인 시작: state·nonce 해시, PKCE verifier 를 10분짜리 한 번용 행으로
  consume_attempt   콜백: state 일치·미사용·10분 이내·공급자 일치 -> «사용됨»
  find_member       (issuer_key, subject) 정확 일치 + 철회 안 됨 + 회원 active
  create_pending    연결된 회원이 없을 때 -- 동의 전 신원(회원 아님, 10분 한 번용)
  join              동의(필수 3개) 확인 -> 회원 + 신원 + 동의 기록 + 세션 (+ 이 브라우저 기록 귀속)
  issue_session     쿠키 토큰(64 hex) 발급 -- 영수증과 세션을 같은 트랜잭션에(서버엔 sha256 만)
  revoke_session    로그아웃 -- revoked_at_epoch 만 채운다(지우지 않음)
  attach_guest      이 브라우저(방문자 user_id + 견적 보관 키 해시)의 기록을 회원에 붙인다(이미 다른 회원 것은 그대로)

■ 읽기 쪽 포트 (기존 V2 연결 고리의 빈 두 자리 -- customer_auth_store.P1PrincipalBridgeV2 에 끼운다)
  PgIssuanceAuthority          발급 영수증 표를 proof_ref 로 «따로» 읽는다(P1 IndependentIssuanceAuthority)
  ConfiguredPrincipalRestorer  서버 설정의 공급자 등록과 대조해 VerifiedPrincipal 을 다시 만든다(I1 복원)
  build_runtime_resolver()     위를 모두 이어 세션 해석기를 만든다 -- ★ 아직 customer_auth.RUNTIME_RESOLVER 에 넣지 않는다(P2b)
"""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid

from sqlalchemy import text

from . import customer_identity as identity
from . import customer_auth_provenance as p1
from . import customer_oidc as OIDC

SESSION_DAYS = 14                      # customer_auth.ABSOLUTE_DAYS 와 같은 값(ERD §3.11 계약)
ATTEMPT_TTL = 600                      # 로그인 시도 · 동의 전 신원 -- 10분
REQUIRED_CONSENTS = ("terms", "privacy", "age14")
OPTIONAL_CONSENTS = ("marketing",)
CONSENT_VERSION = "2026-10-13"         # 약관 문구 확정 뒤 그 날짜로 바꾼다(동의 기록에 남는 버전)
DEFAULT_RETURN = "/mvp3/"


class AuthFlowError(Exception):
    """흐름 실패 -- status 와 고객에게 보일 사유 코드만."""
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def now_epoch() -> int:
    return int(time.time())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_return(path) -> str:
    """같은 사이트 고객 화면 경로만(열린 리다이렉트 방지)."""
    if not isinstance(path, str) or not path.startswith("/mvp3/") or "//" in path or "\\" in path \
            or len(path) > 300 or any(c in path for c in "\r\n"):
        return DEFAULT_RETURN
    return path


# ── 로그인 시도 ───────────────────────────────────────────────────────────────
def begin_attempt(conn, provider: str, return_path: str, *, now: int | None = None):
    """-> (state, nonce, verifier). state 원문은 브라우저 쿠키와 공급자 왕복에만 쓰고 DB 엔 해시만."""
    state, nonce, verifier = OIDC.new_secret(), OIDC.new_secret(), OIDC.new_secret()
    conn.execute(text(
        "INSERT INTO oauth_login_attempts (attempt_id, provider, state_hash, nonce_hash, pkce_verifier, return_path,"
        " created_at_epoch) VALUES (:a, :p, :s, :n, :v, :r, :t)"),
        {"a": str(uuid.uuid4()), "p": provider, "s": digest(state), "n": digest(nonce), "v": verifier,
         "r": safe_return(return_path), "t": now if now is not None else now_epoch()})
    return state, nonce, verifier


def consume_attempt(conn, provider: str, state: str, cookie_state: str | None, *, now: int | None = None) -> dict:
    """콜백의 state 가 이 브라우저가 시작한 시도인지(쿠키 대조 -- 로그인 위조 방지) -> 한 번만 쓴다."""
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        raise AuthFlowError(400, "state_mismatch")
    t = now if now is not None else now_epoch()
    row = conn.execute(text(
        "UPDATE oauth_login_attempts SET used_at_epoch = :t WHERE state_hash = :s AND provider = :p"
        " AND used_at_epoch IS NULL AND created_at_epoch >= :lo"
        " RETURNING nonce_hash, pkce_verifier, return_path, purpose, link_member_id"),
        {"t": t, "s": digest(state), "p": provider, "lo": t - ATTEMPT_TTL}).mappings().first()
    if row is None:
        raise AuthFlowError(400, "attempt_expired")
    return dict(row)


# ── 회원 찾기 · 동의 전 신원 ──────────────────────────────────────────────────
def find_member(conn, principal) -> dict | None:
    """(issuer_key, subject) 정확 일치. 이메일로 찾지 않는다. 철회된 신원·active 아닌 회원은 None 이 아니라 거절."""
    row = conn.execute(text(
        "SELECT i.identity_id, i.revoked_at_epoch, m.member_id, m.status, m.auth_revision, m.auth_subject"
        " FROM member_verified_identities i JOIN members m ON m.member_id = i.member_id"
        " WHERE i.issuer_key = :k AND i.subject = :s"),
        {"k": principal.issuer_key, "s": principal.subject}).mappings().first()
    if row is None:
        return None
    if row["revoked_at_epoch"] is not None:
        raise AuthFlowError(401, "identity_revoked")
    if row["status"] != "active" or row["auth_revision"] is None:
        raise AuthFlowError(401, "member_inactive")
    return dict(row)


def create_pending(conn, login: OIDC.VerifiedLogin, return_path: str, *, now: int | None = None) -> str:
    p = login.principal
    token = secrets.token_hex(32)
    conn.execute(text(
        "INSERT INTO member_join_pending (pending_id, token_hash, issuer_key, issuer, subject, verification_method,"
        " registration_ref, verified_at_epoch, display_nickname, display_email, return_path, created_at_epoch)"
        " VALUES (:id, :h, :k, :i, :s, :vm, :rr, :va, :dn, :de, :r, :t)"),
        {"id": str(uuid.uuid4()), "h": digest(token), "k": p.issuer_key, "i": p.issuer, "s": p.subject,
         "vm": p.verification_method, "rr": p.registration_ref, "va": p.verified_at, "dn": login.display_nickname,
         "de": login.display_email, "r": safe_return(return_path), "t": now if now is not None else now_epoch()})
    return token


def read_pending(conn, token: str | None, *, now: int | None = None, consume: bool = False) -> dict:
    if not token or len(token) != 64:
        raise AuthFlowError(401, "join_expired")
    t = now if now is not None else now_epoch()
    sql = ("UPDATE member_join_pending SET used_at_epoch = :t WHERE token_hash = :h AND used_at_epoch IS NULL"
           " AND created_at_epoch >= :lo RETURNING *") if consume else \
          ("SELECT * FROM member_join_pending WHERE token_hash = :h AND used_at_epoch IS NULL AND created_at_epoch >= :lo")
    row = conn.execute(text(sql), {"t": t, "h": digest(token), "lo": t - ATTEMPT_TTL}).mappings().first()
    if row is None:
        raise AuthFlowError(401, "join_expired")
    return dict(row)


def principal_from_pending(row: dict):
    """동의 전 신원 -> VerifiedPrincipal. 지금 서버 설정의 공급자 등록과 같을 때만(키가 바뀌었으면 거절)."""
    cfg = OIDC.providers().get(row["issuer_key"])
    if cfg is None or (cfg.issuer, cfg.registration_ref, cfg.verification_method) != (
            row["issuer"], row["registration_ref"], row["verification_method"]):
        raise AuthFlowError(503, "auth_unavailable")
    return identity.VerifiedPrincipal._from_server_verifier(cfg.registration(), subject=row["subject"],
                                                            verified_at=row["verified_at_epoch"])


# ── 가입 ──────────────────────────────────────────────────────────────────────
def validate_consents(consents) -> set[str]:
    if not isinstance(consents, dict):
        raise AuthFlowError(422, "consent_required")
    agreed = {k for k, v in consents.items() if v is True and k in REQUIRED_CONSENTS + OPTIONAL_CONSENTS}
    if not set(REQUIRED_CONSENTS) <= agreed:
        raise AuthFlowError(422, "consent_required")     # 만 14세 확인 포함 -- 빠지면 가입하지 않는다
    return agreed


def join(conn, pending_token: str, consents, *, nickname: str | None = None, now: int | None = None) -> dict:
    agreed = validate_consents(consents)
    t = now if now is not None else now_epoch()
    row = read_pending(conn, pending_token, now=t, consume=True)
    principal = principal_from_pending(row)
    if find_member(conn, principal) is not None:          # 그 사이 같은 신원으로 가입됐다(두 번 누름 등)
        raise AuthFlowError(409, "already_joined")
    name = (nickname or row.get("display_nickname") or "").strip()[:100] or "회원"
    member_id = conn.execute(text(
        "INSERT INTO members (email, nickname, joined_via, provider_uid, status, auth_subject, auth_revision, last_login_at)"
        " VALUES (NULL, :n, :via, NULL, 'active', :sub, 1, now()) RETURNING member_id"),
        {"n": name, "via": principal.via, "sub": str(uuid.uuid4())}).scalar()
    identity_id = conn.execute(text(
        "INSERT INTO member_verified_identities (member_id, issuer_key, issuer, subject, verification_method,"
        " registration_ref, verified_at_epoch) VALUES (:m, :k, :i, :s, :vm, :rr, :va) RETURNING identity_id"),
        {"m": member_id, "k": principal.issuer_key, "i": principal.issuer, "s": principal.subject,
         "vm": principal.verification_method, "rr": principal.registration_ref, "va": principal.verified_at}).scalar()
    for kind in sorted(agreed):
        conn.execute(text("INSERT INTO member_consents (member_id, kind, version, agreed_at_epoch) VALUES (:m, :k, :v, :t)"),
                     {"m": member_id, "k": kind, "v": CONSENT_VERSION, "t": t})
    return {"member_id": member_id, "identity_id": identity_id, "auth_revision": 1, "principal": principal,
            "return_path": row["return_path"]}


# ── 세션 ──────────────────────────────────────────────────────────────────────
def issue_session(conn, *, member_id: int, identity_id: int, auth_revision: int, principal,
                  user_agent: str | None = None, now: int | None = None) -> str:
    """-> 쿠키에 넣을 토큰(64 hex). 영수증 -> 세션 순서로 같은 트랜잭션에 쓴다(8열 FK)."""
    t = now if now is not None else now_epoch()
    if principal.verified_at > t:
        raise AuthFlowError(503, "auth_unavailable")
    token = secrets.token_hex(32)
    row = {"p": str(uuid.uuid4()), "h": digest(token), "m": member_id, "i": identity_id, "c": str(uuid.uuid4()),
           "r": auth_revision, "a": t, "e": t + SESSION_DAYS * 86400, "k": principal.issuer_key, "iss": principal.issuer,
           "s": principal.subject, "va": principal.verified_at, "vm": principal.verification_method,
           "rr": principal.registration_ref, "ar": OIDC.AUTHORITY_REF, "ua": (user_agent or "")[:300] or None}
    conn.execute(text(
        "INSERT INTO member_session_issuance_receipts (proof_ref, credential_hash, member_id, verified_identity_id,"
        " auth_context_id, issued_auth_revision, issued_at_epoch, expires_at_epoch, issuer_key, issuer, subject,"
        " principal_verified_at_epoch, verification_method, registration_ref, authority_ref)"
        " VALUES (:p, :h, :m, :i, :c, :r, :a, :e, :k, :iss, :s, :va, :vm, :rr, :ar)"), row)
    conn.execute(text(
        "INSERT INTO member_verified_sessions (credential_hash, member_id, verified_identity_id, auth_context_id,"
        " issued_auth_revision, issued_at_epoch, expires_at_epoch, proof_ref, user_agent)"
        " VALUES (:h, :m, :i, :c, :r, :a, :e, :p, :ua)"), row)
    conn.execute(text("UPDATE members SET last_login_at = now() WHERE member_id = :m"), {"m": member_id})
    return token


def revoke_session(conn, token: str | None, *, now: int | None = None) -> bool:
    if not token or len(token) != 64:
        return False
    r = conn.execute(text("UPDATE member_verified_sessions SET revoked_at_epoch = :t"
                          " WHERE credential_hash = :h AND revoked_at_epoch IS NULL"),
                     {"t": now if now is not None else now_epoch(), "h": digest(token)})
    return r.rowcount == 1


def session_member(conn, token: str | None, *, now: int | None = None) -> int | None:
    """쓰기 경로(기록 귀속)에서 쓰는 가벼운 확인 -- 유효한 세션의 회원 번호. 개인 데이터 읽기는 해석기(P2b)가 한다."""
    if not token or len(token) != 64:
        return None
    t = now if now is not None else now_epoch()
    return conn.execute(text(
        "SELECT s.member_id FROM member_verified_sessions s JOIN members m ON m.member_id = s.member_id"
        " WHERE s.credential_hash = :h AND s.revoked_at_epoch IS NULL AND s.expires_at_epoch > :t"
        " AND m.status = 'active' AND s.issued_auth_revision = m.auth_revision"),
        {"h": digest(token), "t": t}).scalar()


def attach_guest(conn, member_id: int, *, user_id: int | None, owner_key_hash: str | None) -> dict:
    """이 브라우저를 쥔 사람 = 그 기록의 주인(지금의 소유 판정 그대로). 이미 다른 회원에 붙은 것은 옮기지 않는다."""
    out = {"quotes": 0, "inquiries": 0, "handoffs": 0}
    if user_id is None:
        return out
    if owner_key_hash:
        out["quotes"] = conn.execute(text(
            "UPDATE mvp3_saved_recommendations SET member_id = :m WHERE user_id = :u AND owner_key_hash = :o"
            " AND member_id IS NULL"), {"m": member_id, "u": user_id, "o": owner_key_hash}).rowcount
    out["inquiries"] = conn.execute(text(
        "UPDATE purchase_inquiries SET member_id = :m WHERE user_id = :u AND member_id IS NULL"),
        {"m": member_id, "u": user_id}).rowcount
    out["handoffs"] = conn.execute(text(
        "UPDATE handoffs SET member_id = :m WHERE user_id = :u AND member_id IS NULL"),
        {"m": member_id, "u": user_id}).rowcount
    return out


# ── 읽기 쪽 신뢰 포트 ─────────────────────────────────────────────────────────
class PgIssuanceAuthority:
    """P1 IndependentIssuanceAuthority -- 세션 조회(Q1)와 «따로» 영수증 표를 proof_ref 로 읽는다."""

    def __init__(self, engine):
        self._engine = engine

    def ready(self) -> bool:
        if not OIDC.enabled():
            return False
        try:
            with self._engine.connect() as conn:
                return conn.execute(text("SELECT to_regclass('public.member_session_issuance_receipts') IS NOT NULL")).scalar() is True
        except Exception:  # noqa: BLE001
            return False

    def read_verified_issuance(self, proof_ref: str):
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM member_session_issuance_receipts WHERE proof_ref = CAST(:p AS uuid)"),
                {"p": proof_ref}).mappings().all()
        out = []
        for r in rows:
            r = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in dict(r).items()}
            out.append(p1.AuthorityReceipt(
                binding=p1.IssuanceBinding(proof_ref=r["proof_ref"], credential_hash=r["credential_hash"],
                    member_id=r["member_id"], verified_identity_id=r["verified_identity_id"],
                    auth_context_id=r["auth_context_id"], issued_auth_revision=r["issued_auth_revision"],
                    issued_at=r["issued_at_epoch"], expires_at=r["expires_at_epoch"]),
                provenance=p1.IssuanceProvenance(issuer_key=r["issuer_key"], issuer=r["issuer"], subject=r["subject"],
                    verified_at=r["principal_verified_at_epoch"], verification_method=r["verification_method"],
                    registration_ref=r["registration_ref"]),
                authority_ref=r["authority_ref"]))
        return tuple(out)


class ConfiguredPrincipalRestorer:
    """I1 복원 -- 영수증의 출처가 지금 서버 설정의 공급자 등록과 정확히 같을 때만 VerifiedPrincipal 을 다시 만든다."""

    def ready(self) -> bool:
        return OIDC.enabled()

    def restore_verified_principal(self, evidence):
        pv = evidence.provenance
        cfg = OIDC.providers().get(pv.issuer_key)
        if cfg is None or (cfg.issuer, cfg.registration_ref, cfg.verification_method) != (
                pv.issuer, pv.registration_ref, pv.verification_method):
            raise p1.IssuanceUnavailable()
        return identity.VerifiedPrincipal._from_server_verifier(cfg.registration(), subject=pv.subject,
                                                                verified_at=pv.verified_at)


def build_runtime_resolver(engine):
    """V2 연결 고리를 실제 포트로 잇는다. ★ P2b 전까지 customer_auth.RUNTIME_RESOLVER 에 넣지 않는다."""
    from . import customer_auth as C4
    from . import customer_auth_store as R1
    from .customer_auth_pg_read import PostgresReadExecutor
    from .customer_auth_sql_read import SQLReadPort
    verifier = p1.IssuanceEvidenceVerifier(PgIssuanceAuthority(engine), authority_ref=OIDC.AUTHORITY_REF)
    principal = R1.P1PrincipalBridgeV2(verifier, ConfiguredPrincipalRestorer(), authority_ref=OIDC.AUTHORITY_REF)
    repository = R1.SessionReadAdapterV2(R1.Q1ReadBridgeV2(SQLReadPort(PostgresReadExecutor(engine))),
                                         principal, C4.PersistedSessionSnapshot)
    return C4.VerifiedSessionResolver(repository, principal)
