"""Unwired server adapters. No engine, CLI, credentials, DML or default reuse grant.
Only a trusted server closure may supply context and explicitly pinned CASE fields.
The caller owns the short transaction and must call again at reserve/finalize.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from .pc_existing_media_import import Denied, Principal
from tools.register_existing_pc_media import CaseEvidence, Decision, ReuseSubject


@dataclass(frozen=True, repr=False)
class ServerContext:
    session_id: str
    operator_id: int
    role: str
    sec_fetch_site: str | None


def _idle_minutes():
    # Reuse existing server configuration, never resolve_session (which writes).
    from .auth import IDLE_MINUTES
    return IDLE_MINUTES


class SessionAuthority:
    """Construction is server-only; no request body/CLI parser is provided.

    Context must be captured by trusted request integration, not from a caller's
    asserted role. operator_reader supplies identity only, not registration/reuse
    permission. Actual route/factory binding is deliberately outside this module.
    """
    def __init__(self, context_reader, *, idle_minutes_reader=_idle_minutes):
        self._context_reader = context_reader
        self._idle_minutes_reader = idle_minutes_reader
        self._bound_context = None

    def _context(self):
        if not callable(self._context_reader):
            raise Denied('server_context_unwired')
        c = self._context_reader()
        if (type(c) is not ServerContext or type(c.session_id) is not str
                or not c.session_id.strip() or type(c.operator_id) is not int
                or c.operator_id <= 0 or c.role not in ('operator', 'owner')
                or (c.sec_fetch_site is not None and type(c.sec_fetch_site) is not str)
                or c.sec_fetch_site == 'cross-site'):
            raise Denied('server_context_unavailable')
        if self._bound_context is not None and self._bound_context != c:
            raise Denied('server_context_changed')
        self._bound_context = c
        return c

    def operator_reader(self):
        c = self._context()
        return dict(operator_id=c.operator_id, role=c.role)

    def verify_registration(self, subject, principal, connection=None):
        if type(subject) is not ReuseSubject or type(principal) is not Principal:
            raise Denied('registration_subject_unavailable')
        c = self._context()
        if principal != Principal(c.operator_id, c.role) or connection is None:
            raise Denied('registration_identity_changed')
        idle = self._idle_minutes_reader()
        if type(idle) is not int or idle <= 0:
            raise Denied('session_configuration_unavailable')
        from sqlalchemy import text
        # Exact existing auth schema and DB-time boundary; same caller connection.
        # No SELECT FOR UPDATE, last_seen refresh, commit, rollback or new engine.
        row = connection.execute(text(
            'SELECT s.operator_id, o.role, o.status,'
            ' (s.revoked_at IS NOT NULL) AS revoked,'
            ' (s.expires_at <= now()) AS expired,'
            " (s.last_seen_at <= now() - :idle * interval '1 minute') AS idle"
            ' FROM admin_sessions s JOIN admin_operators o USING (operator_id)'
            ' WHERE s.session_id=:s'), dict(s=c.session_id, idle=idle)).mappings().first()
        if (not row or type(row.get('operator_id')) is not int
                or row.get('operator_id') != c.operator_id or row.get('role') != c.role
                or row.get('status') != '활성'
                or any(row.get(k) is not False for k in ('revoked', 'expired', 'idle'))):
            raise Denied('session_invalid_or_changed')
        return Decision.ALLOW  # registration only; never reuse permission

    def verify_reuse(self, subject, principal, connection=None):
        # Approval record and withdrawal source have not been selected/bound.
        # Existing approval facts are not rescinded; absence of an adapter is unknown.
        return Decision.UNKNOWN


@dataclass(frozen=True)
class FieldPin:
    path: tuple[str | int, ...]
    value: str
    reference: str


@dataclass(frozen=True)
class CasePins:
    product_code: int
    source_fingerprint: str
    content_sha256: str
    model: FieldPin
    color: FieldPin
    side_panel: FieldPin
    front: FieldPin


def _hash(v):
    return type(v) is str and re.fullmatch('[a-f0-9]{64}', v) is not None


def _content_hash(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _field(content, pin):
    if (type(pin) is not FieldPin or type(pin.path) is not tuple or not pin.path
            or type(pin.value) is not str or not pin.value.strip()
            or pin.value.strip().lower() in ('unknown', 'null', 'none', '미확인')
            or type(pin.reference) is not str or not pin.reference.strip()):
        raise Denied('case_field_unavailable')
    value = content
    for part in pin.path:
        if type(part) is str and type(value) is dict and part in value:
            value = value[part]
        elif type(part) is int and part >= 0 and type(value) is list and part < len(value):
            value = value[part]
        else:
            raise Denied('case_field_missing')
    # Canonical explicit values only. No inference from model/name/photo/expected SKU.
    if type(value) is not str or value != pin.value:
        raise Denied('case_field_changed')
    return value


class ExplicitCaseReader:
    """Pins are trusted per-field source evidence, never client assertions.

    Does not choose fields or facts for an operator. Exact paths must already
    contain canonical explicit values. Unstructured prose/aliases are unknown.
    Content hash additionally detects content changes with unchanged fingerprint.
    Actual current CASE facts/pins remain to be supplied by approved integration.
    """
    def __init__(self, pins):
        self._pins = tuple(pins)

    def __call__(self, connection, row):
        if connection is None or type(row) is not dict:
            raise Denied('case_connection_unavailable')
        code = row.get('source_product_code')
        matches = [p for p in self._pins if type(p) is CasePins and p.product_code == code]
        if type(code) is not int or len(matches) != 1:
            raise Denied('case_pins_unavailable')
        p = matches[0]
        content = row.get('content')
        if (type(p.product_code) is not int or p.product_code <= 0
                or not _hash(p.source_fingerprint) or not _hash(p.content_sha256)
                or row.get('source_fingerprint') != p.source_fingerprint
                or type(content) is not dict):
            raise Denied('case_fingerprint_unavailable_or_changed')
        try:
            if _content_hash(content) != p.content_sha256:
                raise Denied('case_content_changed')
        except (TypeError, ValueError):
            raise Denied('case_content_unavailable') from None
        fields = [p.model, p.color, p.side_panel, p.front]
        values = [_field(content, f) for f in fields]
        if len({f.path for f in fields}) != 4:
            raise Denied('case_distinct_fields_required')
        if values[1] not in ('black', 'white') or values[2] != 'closed_mesh_opaque' or values[3] != 'N1_MESH':
            raise Denied('case_normalized_fields_unavailable')
        ref = json.dumps(dict(source='product_explanations', product_code=code,
            source_fingerprint=p.source_fingerprint, content_sha256=p.content_sha256,
            fields={name:dict(path=f.path, value=f.value, reference=f.reference)
                for name, f in zip(('model','color','side_panel','front'), fields)}),
            ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return CaseEvidence(code, *values, ref)


@dataclass(frozen=True)
class ManifestCasePins:
    sku: str
    product_code: int
    source_fingerprint: str
    content_sha256: str
    name: str
    qa_note: str
    case_reference_sha256: str


class ManifestCaseReader:
    """Exact existing name + external QA, never synthetic product facts.

    Server supplies reviewed observation pins and a local immutable manifest reader.
    Every call compares current DB row against those pins; an old PM observation is
    not a promise of future freshness. No pins are chosen by this adapter.
    """
    def __init__(self, pins, manifest_reader):
        self._pins, self._manifest_reader = tuple(pins), manifest_reader

    def __call__(self, connection, row):
        from tools.register_existing_pc_media import MANIFEST_SHA
        if connection is None or type(row) is not dict or not callable(self._manifest_reader):
            raise Denied('case_sources_unwired')
        code = row.get('source_product_code')
        targets = {129552:('P113835','DAVEN N1 MESH (블랙)','black',
            '검정 메쉬 측판·전면 형태 확인, 유리 없음. 내부 RGB 공랭 쿨러는 닫힌 패널로 가려짐'),
            129551:('P113836','DAVEN N1 MESH (화이트)','white',
            '흰 N1 닫힌 메쉬 측판 외관. 패널로 내부 쿨러가 가려져 G012 외관 예시 재사용; 생성된 개방 측판 버전은 폐기')}
        if type(code) is not int or code not in targets:
            raise Denied('case_target_unavailable')
        matched = [p for p in self._pins if type(p) is ManifestCasePins and p.product_code == code]
        if len(matched) != 1:
            raise Denied('case_pins_unavailable')
        p, target = matched[0], targets[code]
        if (p.sku != target[0] or p.name != target[1] or p.qa_note != target[3]
                or not all(_hash(v) for v in (p.source_fingerprint,p.content_sha256,p.case_reference_sha256))
                or row.get('source_fingerprint') != p.source_fingerprint
                or type(row.get('content')) is not dict):
            raise Denied('case_pins_changed')
        content = row['content']
        try:
            if (_content_hash(content) != p.content_sha256 or content.get('name') != p.name
                    or content.get('slot') != 'CASE'):
                raise Denied('case_content_changed')
            raw = self._manifest_reader()
            if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
                raise Denied('case_manifest_changed')
            manifest = json.loads(raw)
            items = [i for i in manifest['items'] if i.get('configuration_id') == p.sku]
            if len(items) != 1:
                raise Denied('case_manifest_target_changed')
            item = items[0]
            refs = [r for r in item['references'] if r.get('slot') == 'CASE']
            if len(refs) != 1:
                raise Denied('case_reference_unavailable')
            ref = refs[0]
            if (item.get('case_code') != str(code) or ref.get('code') != str(code)
                    or ref.get('name') != p.name or _content_hash(ref) != p.case_reference_sha256
                    or item['qa_notes'][0] != p.qa_note):
                raise Denied('case_qa_reference_changed')
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):
            raise Denied('case_evidence_unavailable') from None
        # Normalization is restricted to the exact reviewed name + entire QA text
        # above AND immutable manifest evidence. It is not a substring classifier.
        reference = json.dumps(dict(source='explicit-name-and-external-manifest-QA',
            product_code=code, sku=p.sku, source_fingerprint=p.source_fingerprint,
            content_sha256=p.content_sha256,
            model_color=dict(source='product_explanations.content',path=['name'],raw=p.name),
            exterior=dict(source='external_QA',manifest_sha256=MANIFEST_SHA,
                path=f'items[configuration_id={p.sku}]/qa_notes/0',raw=p.qa_note),
            case_reference=dict(path=f'items[configuration_id={p.sku}]/references[slot=CASE]',
                sha256=p.case_reference_sha256,code=ref['code'],name=ref['name'],
                source_url=ref.get('source_url'),image_asset=ref.get('db_image_asset'))),
            ensure_ascii=False,sort_keys=True,separators=(',',':'))
        return CaseEvidence(code,'DAVEN N1 MESH',target[2],'closed_mesh_opaque','N1_MESH',reference)
