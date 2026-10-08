"""Unpublished existing-image admin route. Default denied, no live grant wired.
Module router is discoverable by existing main; no main/auth policy changes.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pc_existing_media_authority import ServerContext, SessionAuthority
from .pc_existing_media_import import Denied, Expected, ServerAuthority
from tools.register_existing_pc_media import Decision, MANIFEST_SHA, ReuseSubject

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]


class ExpectedPins(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(gt=0)
    visual_basis: str = Field(pattern='^[a-f0-9]{64}$')
    review_basis: str = Field(pattern='^[a-f0-9]{64}$')
    original_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    manifest_sha256: str = Field(pattern='^[a-f0-9]{64}$')


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mode: Literal['dry_run','apply'] = 'dry_run'
    request_id: str | None = None
    expected: ExpectedPins

    @model_validator(mode='after')
    def request_identity(self):
        if self.mode == 'apply' and self.request_id is None:
            raise ValueError('apply requires request_id')
        if self.request_id is not None:
            try:
                if str(UUID(self.request_id)) != self.request_id:
                    raise ValueError()
            except (ValueError,TypeError,AttributeError):
                raise ValueError('canonical request_id required') from None
        return self


APPROVAL_RECORD = '기록/팝콘AI/결정/popcorn-case-centered-representative-image-decision-20261008-v1.md'
APPROVAL_SHA = '81828180ef89ee00c164429a88f0494688634f457977a0cbe17f5b6a6f4d0faa'


@dataclass(frozen=True)
class FreshReuseEvidence:
    """Trusted provider result, not a client grant or a freshness assertion flag.

    Provider must actually check current source/withdrawal on every invocation.
    No implementation/transport for that provider is selected here.
    """
    decision: Decision
    record_path: str
    record_version: int
    record_sha256: str
    manifest_sha256: str
    source_sku: str
    original_sha256: str
    case_product_code: int
    withdrawn: bool | None


def _matches_grant(value, subject):
    if type(value) is not FreshReuseEvidence or type(subject) is not ReuseSubject:
        return False
    try:
        return (value.decision is Decision.ALLOW and value.withdrawn is False
            and value.record_path == APPROVAL_RECORD and type(value.record_version) is int
            and value.record_version == 1 and value.record_sha256 == APPROVAL_SHA
            and value.manifest_sha256 == MANIFEST_SHA == subject.original.manifest_sha256
            and value.source_sku == subject.original.configuration_id == subject.current.offer_id
            and value.original_sha256 == subject.original.original_sha256
            and type(value.case_product_code) is int
            and value.case_product_code == subject.current.case.product_code)
    except AttributeError:
        return False


@dataclass(frozen=True)
class ServerWiring:
    # Trusted server callback contract: freshly verify exact source decision,
    # scope and withdrawal via supplied connection/local evidence at EACH call.
    # No production implementation/provider transport has been selected.
    fresh_reuse_verifier: Callable | None = None
    case_reader: Callable | None = None
    apply_enabled: bool = False
    # Trusted server closures only. Expected pins and HTTP body are never inputs
    # to scope_reader; real source/withdrawal adapters remain unselected.
    scope_reader: Callable | None = field(default=None, kw_only=True)
    record_reader: Callable | None = field(default=None, kw_only=True)
    server_confirmer: Callable | None = field(default=None, kw_only=True)
    local_verifier: Callable | None = field(default=None, kw_only=True)


def server_wiring():
    return ServerWiring()  # Fail closed. Never configure via request/CLI/env role.


def server_context(request: Request):
    from .auth import COOKIE
    from .admin_pc_builder import permission
    actor = permission(request)  # Existing authenticated operator/owner + same-site.
    return ServerContext(request.cookies.get(COOKIE,''),actor['operator_id'],
                         actor['role'],request.headers.get('sec-fetch-site'))


class _RequestStore:
    """Request-owned transaction boundary; uncertain cleanup poisons this request.

    Active includes enter, commit/rollback and close, not just the yielded body.
    Inspect the actual connection; an open/unknown exit is never reported inactive.
    """
    def __init__(self, base):
        self.base = base
        self._active = False
        self._connection = None
        self._poisoned = False

    def active(self):
        if self._poisoned:return None
        return self._active

    def verify_connection(self, connection):
        if (self.active() is not True or connection is None
                or connection is not self._connection):
            raise Denied('refresh_connection_unavailable')
        try:
            if connection.closed is not False or connection.in_transaction() is not True:
                raise Denied('refresh_transaction_unavailable')
        except Denied:raise
        except Exception:raise Denied('refresh_transaction_unknown') from None

    def original_bytes(self, code):return self.base.original_bytes(code)

    @contextmanager
    def transaction(self, readonly=False):
        if self.active() is not False:
            self._poisoned = True
            raise Denied('refresh_nested_or_unknown_transaction')
        self._active = True
        connection = None
        try:
            with self.base.transaction(readonly=readonly) as tx:
                connection = getattr(tx,'conn',None)
                self._connection = connection
                self.verify_connection(connection)
                yield tx
                if self._poisoned:raise Denied('refresh_transaction_poisoned')
        finally:
            # Even when enter/exit fails, only an observed closed owned connection
            # proves the base contextmanager finished its cleanup.
            try:closed = connection is not None and connection.closed is True
            except Exception:closed = False
            if not closed:self._poisoned = True
            self._connection = None
            self._active = False
            if not closed:raise Denied('refresh_transaction_cleanup_unknown')


def _refresh_scope(context, wiring, product_code):
    callbacks = (wiring.scope_reader,wiring.record_reader,
                 wiring.server_confirmer,wiring.local_verifier)
    if all(value is None for value in callbacks):return None
    if not all(callable(value) for value in callbacks):
        raise Denied('refresh_server_inputs_unavailable')
    if type(product_code) is not int or product_code not in (113835,113836):
        raise Denied('refresh_target_unavailable')
    from .pc_existing_media_refresh import Scope, scope_hash
    try:
        scope = wiring.scope_reader(context,product_code)
        scope_hash(scope)
    except Exception:raise Denied('refresh_scope_unavailable') from None
    if (type(scope) is not Scope or scope.source_sku != f'P{product_code}'
            or scope.record_path != APPROVAL_RECORD or scope.record_version != 1
            or scope.record_sha256 != APPROVAL_SHA or scope.manifest_sha256 != MANIFEST_SHA):
        raise Denied('refresh_scope_pins_changed')
    return scope


def build_runtime(context, wiring, *, product_code=None):
    if (type(context) is not ServerContext or type(wiring) is not ServerWiring
            or not callable(wiring.fresh_reuse_verifier) or not callable(wiring.case_reader)):
        raise Denied('actual_wiring_unavailable')
    session = SessionAuthority(lambda:context)
    session.operator_reader()  # Reject invalid server context before DB setup.
    def reuse(subject, principal, connection=None):
        # Also validates actual session in dry-run and ready reconciliation reads.
        session.verify_registration(subject,principal,connection)
        if not _matches_grant(wiring.fresh_reuse_verifier(subject,principal,connection),subject):
            raise Denied('fresh_reuse_authority_unavailable')
        return Decision.ALLOW
    authority = ServerAuthority(reuse,session.operator_reader,session.verify_registration)
    scope = _refresh_scope(context,wiring,product_code)
    from .db import engine
    from .pc_existing_media_import import Runtime, PgStore, GcsObjects
    archive = ROOT.parents[1] / 'outputs' / 'assembled-pc-images-20260929'
    base = PgStore(engine,archive,case_reader=wiring.case_reader)
    if scope is None:
        return Runtime(base,GcsObjects(),authority)  # Old signature, still unwired.
    from .pc_existing_media_import import RefreshBinding
    from .pc_existing_media_refresh import RefreshContract, scope_hash
    store = _RequestStore(base)
    def local(current,envelope,connection):
        store.verify_connection(connection)
        if (current != scope or envelope.scope_sha256 != scope_hash(scope)
                or envelope.record is None or envelope.record.path != scope.record_path
                or envelope.record.sha != scope.record_sha256
                or envelope.record.version != scope.record_version):
            raise Denied('refresh_local_scope_changed')
        # Local current binding/reuse source verification only. Session and typed
        # FreshReuseEvidence checks still run via base authority on EVERY reuse.
        value = wiring.local_verifier(current,envelope,connection)
        store.verify_connection(connection)
        return value
    contract = RefreshContract(tx_active=store.active,record_reader=wiring.record_reader,
        server_confirmer=wiring.server_confirmer,local_verifier=local,deferred_completion=True)
    return Runtime(store,GcsObjects(),authority,refresh=RefreshBinding(contract,scope))


@router.post('/api/admin/pc-media/{product_code}/existing-import')
def existing_import(product_code: str, body: ImportRequest, request: Request,
                    context: ServerContext = Depends(server_context),
                    wiring: ServerWiring = Depends(server_wiring)):
    # HTTP path values are strings. Canonical allowlist rejects leading zero/sign,
    # bool, float, whitespace, alternate SKU spellings and every other product.
    if product_code not in ('113835','113836'):
        raise HTTPException(422,'exact existing-image target required')
    if body.mode == 'apply' and wiring.apply_enabled is not True:
        raise HTTPException(403,'existing-image apply unavailable')
    try:
        runtime = build_runtime(context,wiring,product_code=int(product_code))
        expected = Expected(**body.expected.model_dump())
        outcome = (runtime.apply(int(product_code),expected,body.request_id)
            if body.mode == 'apply' else runtime.dry_run(int(product_code),expected))
    except Denied:
        raise HTTPException(403,'existing-image authority unavailable') from None
    # Outcome has no session, raw source data, credentials or DSN.
    return asdict(outcome)
