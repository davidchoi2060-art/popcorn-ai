"""Unpublished existing-image admin route. Default denied, no live grant wired.
Module router is discoverable by existing main; no main/auth policy changes.
"""
from dataclasses import asdict, dataclass
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


def server_wiring():
    return ServerWiring()  # Fail closed. Never configure via request/CLI/env role.


def server_context(request: Request):
    from .auth import COOKIE
    from .admin_pc_builder import permission
    actor = permission(request)  # Existing authenticated operator/owner + same-site.
    return ServerContext(request.cookies.get(COOKIE,''),actor['operator_id'],
                         actor['role'],request.headers.get('sec-fetch-site'))


def build_runtime(context, wiring):
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
    from .db import engine
    from .pc_existing_media_import import Runtime, PgStore, GcsObjects
    archive = ROOT.parents[1] / 'outputs' / 'assembled-pc-images-20260929'
    return Runtime(PgStore(engine,archive,case_reader=wiring.case_reader),GcsObjects(),authority)


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
        runtime = build_runtime(context,wiring)
        expected = Expected(**body.expected.model_dump())
        outcome = (runtime.apply(int(product_code),expected,body.request_id)
            if body.mode == 'apply' else runtime.dry_run(int(product_code),expected))
    except Denied:
        raise HTTPException(403,'existing-image authority unavailable') from None
    # Outcome has no session, raw source data, credentials or DSN.
    return asdict(outcome)
