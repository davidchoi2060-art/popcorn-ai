"""Unwired, pure import planner for two already generated case-focused examples.
Server adapters own freshness, registered-offer validation and independent reuse
authority. No files, DB, cloud, network, provider, UUID or clock access here.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Protocol

MANIFEST_SHA = '48b0999b276d8a2aff0152a18cb65f5e98c9833489a2edac13bf57cb536b1e39'
BUCKET = 'popcorn-ai-product-media-045e861b'
NOTICE = 'AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음'
MAX_BYTES = 20 * 1024 * 1024


class Decision(Enum):
    ALLOW = 'allow'
    UNKNOWN = 'unknown'
    DENY = 'deny'
    WITHDRAWN = 'withdrawn'


class Unavailable(Exception):
    pass


class InfrastructureFailure(Exception):
    pass


@dataclass(frozen=True)
class CaseEvidence:
    product_code: int
    model: str
    color: str
    side_panel: str
    front: str
    source_reference: str


@dataclass(frozen=True)
class OriginalInput:
    manifest_bytes: bytes
    original_bytes: bytes


@dataclass(frozen=True)
class ImportBinding:
    product_code: int
    offer_id: str
    configuration_id: str
    revision: int
    current_visual_basis: str
    case: CaseEvidence


@dataclass(frozen=True)
class OriginalProvenance:
    configuration_id: str
    original_path: str
    original_sha256: str
    manifest_sha256: str
    original_revision: int
    qa_notes: tuple[str, ...]
    reused_from: str | None
    reuse_exception: str | None
    facts_change_reference: str | None
    generation_model: None = None
    generation_time: None = None
    generation_actor: None = None
    original_visual_basis: None = None


@dataclass(frozen=True)
class ReuseSubject:
    original: OriginalProvenance
    current: ImportBinding


class Sources(Protocol):
    def original(self, product_code: int) -> OriginalInput | None:
        """Return bytes from the existing pinned archive, never regenerate."""

    def current_binding(self, product_code: int) -> ImportBinding | None:
        """Fresh trusted offer/configuration/case read. Verify payload ID,
        source_ids, source, quote_only and revision identity using server rules.
        Case fields are normalized from genuine referenced evidence, not client
        assertions. Own coherent read scope; do not infer configuration from SKU.
        """


class ReusePermission(Protocol):
    def verify_reuse(self, subject: ReuseSubject) -> Decision:
        """Independently verify exact original/case reuse scope from authority.
        Selection, component approval and client bool/dict cannot mint permission.
        This is not DB-write, selection, customer-publication or deploy permission.
        """


@dataclass(frozen=True)
class Ports:
    sources: Sources
    permission: ReusePermission


@dataclass(frozen=True)
class ImportPlan:
    provenance: OriginalProvenance
    binding: ImportBinding
    kind: str = 'existing_generated_case_example_import'
    notice: str = NOTICE
    bucket_contract: str = BUCKET
    # A contract only. No actual job UUID or registration timestamp is allocated.
    object_key_contract: str = 'pc-configurations/<new-job-uuid>/representative.png'


@dataclass(frozen=True)
class Result:
    state: str
    plan: ImportPlan | None = None


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _expected(code):
    if code == 113835:
        return ('f3b7b3705e3c4e5fe3914ab5e9d8e6ca1dedf276822946a580fbc0eb78e1251b',
                129552, 'black')
    if code == 113836:
        return ('dfc6a733f425dfec21e3ae50c078ce3b6653f862a8413eb57fe718070cb3c48b',
                129551, 'white')


def _binding(binding, code, expected):
    if type(binding) is not ImportBinding or type(binding.case) is not CaseEvidence:
        return False
    case = binding.case
    return (type(binding.product_code) is int and binding.product_code == code
            and binding.offer_id == f'P{code}'
            and type(binding.configuration_id) is str and bool(binding.configuration_id.strip())
            and type(binding.revision) is int and binding.revision > 0
            and _hash(binding.current_visual_basis)
            and type(case.product_code) is int and case.product_code == expected[1]
            and case.model == 'DAVEN N1 MESH' and case.color == expected[2]
            and case.side_panel == 'closed_mesh_opaque' and case.front == 'N1_MESH'
            and type(case.source_reference) is str and bool(case.source_reference.strip()))


def _original(value, code, expected):
    if type(value) is not OriginalInput:
        return None
    manifest, raw = value.manifest_bytes, value.original_bytes
    if (type(manifest) is not bytes or not 0 < len(manifest) <= 10 * 1024 * 1024
            or hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA
            or type(raw) is not bytes or not 8 < len(raw) <= MAX_BYTES
            or not raw.startswith(b'\x89PNG\r\n\x1a\n')
            or hashlib.sha256(raw).hexdigest() != expected[0]):
        return None
    data = json.loads(manifest.decode('utf-8-sig'))
    items = [item for item in data['items'] if item['configuration_id'] == f'P{code}']
    if len(items) != 1:
        return None
    item = items[0]
    if (item['original_sha256'] != expected[0] or item['original_bytes'] != len(raw)
            or item['generated_original'] != f'originals/P{code}.png'
            or item['case_code'] != str(expected[1]) or item['db_configuration_revision'] != 1):
        return None
    reused, exception = item.get('reused_from'), item.get('reuse_exception')
    if code == 113836 and (reused != 'P113838' or not exception):
        return None
    return OriginalProvenance(f'P{code}', item['generated_original'], expected[0],
                              MANIFEST_SHA, 1, tuple(item['qa_notes']), reused, exception,
                              'media-current-db-read-boundary-20261008/후속-정확두상품-대응.json: '
                              'SSD128462 facts에 용량500GB 추가' if code == 113836 else None)


def plan_import(product_code: int, ports: Ports | None = None) -> Result:
    """Only server code constructs ports. Permission fixtures are not approval.
    Existing original provenance and fresh import binding remain separate. A
    plan grants no write/publication permission and invokes no side-effect port.
    """
    refused = Result('unavailable')
    if type(product_code) is not int or product_code not in (113835, 113836) or type(ports) is not Ports:
        return refused
    try:
        if not all(callable(getattr(obj, name, None)) for obj, name in (
                (ports.sources, 'original'), (ports.sources, 'current_binding'),
                (ports.permission, 'verify_reuse'))):
            return refused
        expected = _expected(product_code)
        binding = ports.sources.current_binding(product_code)
        if not _binding(binding, product_code, expected):
            return refused
        original = _original(ports.sources.original(product_code), product_code, expected)
        if original is None:
            return refused
        subject = ReuseSubject(original, binding)
        if ports.permission.verify_reuse(subject) is not Decision.ALLOW:
            return refused
        if (ports.sources.current_binding(product_code) != binding
                or ports.permission.verify_reuse(subject) is not Decision.ALLOW):
            return refused
        return Result('planned', ImportPlan(original, binding))
    except Unavailable:
        return refused
    except Exception:
        return Result('temporarily_unavailable')
