"""CODE/MOCK runtime registration, never generation/selection/publication.

Real adapters are lazy and unwired by default. Server identity, independently
verified reuse authority and normalized case evidence must be supplied by the
server; neither CLI arguments nor an operator role alone grants reuse authority.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID, uuid4, uuid5

from tools.register_existing_pc_media import (
    BUCKET, MANIFEST_SHA, Decision, ImportBinding, ImportPlan, OriginalInput,
    Ports, ReuseSubject, plan_import,
)


class Denied(Exception): pass
class Conflict(Exception): pass
class Stale(Exception): pass
class CommitUnknown(Exception): pass
class ObjectUnknown(Exception): pass
class SourceUnavailable(Exception): pass


@dataclass(frozen=True)
class Principal:
    operator_id: int
    role: str

    @property
    def actor(self):
        return f'operator:{self.operator_id}'


@dataclass(frozen=True)
class Capture:
    plan: ImportPlan
    review_basis: str
    snapshot_json: str


@dataclass(frozen=True)
class Expected:
    revision: int
    visual_basis: str
    review_basis: str
    original_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ObjectReceipt:
    bucket: str
    key: str
    sha256: str
    size: int
    generation: str


@dataclass(frozen=True)
class Outcome:
    state: str
    request_id: str | None = None
    job_id: str | None = None
    plan_digest: str | None = None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def provenance(capture):
    p, b = capture.plan.provenance, capture.plan.binding
    reference = f'manifest:sha256:{p.manifest_sha256}#items/{p.configuration_id}'
    return dict(version='pc-media-existing-import-v1', original=dict(
        source_sku=p.configuration_id, original_revision=p.original_revision,
        original_ref=p.original_path, original_sha256=p.original_sha256,
        manifest_sha256=p.manifest_sha256,
        qa_references=[f'{reference}/qa_notes/{i}' for i in range(len(p.qa_notes))],
        qa_notes=list(p.qa_notes), reused_from=p.reused_from,
        reuse_exception_reference=f'{reference}/reuse_exception' if p.reuse_exception else None,
        reuse_exception_note=p.reuse_exception,
        ssd_facts_reference=p.facts_change_reference, generation_model=None,
        generation_actor=None, generation_time=None, original_visual_basis=None),
        current_binding=dict(sku=f'P{b.product_code}', offer_id=b.offer_id,
            configuration_id=b.configuration_id, revision=b.revision,
            case_product_code=b.case.product_code, case_evidence=asdict(b.case),
            visual_basis=b.current_visual_basis, review_basis=capture.review_basis))


class ServerAuthority:
    """Default denied. A trusted server integration must bind both verifiers.
    operator_reader defaults to the existing server current_operator source.
    reuse_verifier must verify exact source decision/scope/withdrawal, not bool.
    Verifiers use the supplied coherent DB connection or local trusted evidence;
    network/provider work inside these transaction callbacks is prohibited.
    """
    def __init__(self, reuse_verifier=None, operator_reader=None, registration_verifier=None):
        self.reuse_verifier = reuse_verifier
        self.operator_reader = operator_reader
        self.registration_verifier = registration_verifier

    def principal(self):
        if not callable(self.reuse_verifier):
            raise Denied('reuse_authority_unwired')
        if self.operator_reader is None:
            from .auth import current_operator
            value = current_operator()
        else:
            value = self.operator_reader()
        if (not isinstance(value, dict) or type(value.get('operator_id')) is not int
                or value['operator_id'] <= 0 or value.get('role') not in ('operator', 'owner')):
            raise Denied('server_operator_unavailable')
        return Principal(value['operator_id'], value['role'])

    def verify_reuse(self, subject, principal, connection=None):
        if (type(principal) is not Principal or self.principal() != principal
                or self.reuse_verifier(subject, principal, connection) is not Decision.ALLOW):
            raise Denied('reuse_permission_unavailable')

    def verify_registration(self, subject, principal, connection=None):
        if (not callable(self.registration_verifier) or self.principal() != principal
                or self.registration_verifier(subject, principal, connection) is not Decision.ALLOW):
            raise Denied('registration_permission_unwired_or_denied')


def _checked(tx, code, expected, authority, principal):
    if authority.principal() != principal:
        raise Denied()
    capture = tx.capture(code, authority, principal)
    if type(capture) is not Capture or type(capture.plan) is not ImportPlan:
        raise Denied()
    b, p = capture.plan.binding, capture.plan.provenance
    actual = Expected(b.revision, b.current_visual_basis, capture.review_basis,
                      p.original_sha256, p.manifest_sha256)
    if (type(expected) is not Expected or type(expected.revision) is not int
            or expected.revision <= 0 or not all(_hash(x) for x in (
                expected.visual_basis, expected.review_basis, expected.original_sha256,
                expected.manifest_sha256))):
        raise Denied()
    if actual != expected:
        raise Stale()
    if b.product_code != code or b.offer_id != f'P{code}':
        raise Conflict()
    if digest(json.loads(capture.snapshot_json)) != b.current_visual_basis:
        raise Conflict()
    subject = ReuseSubject(p, b)
    authority.verify_reuse(subject, principal, getattr(tx, 'conn', None))
    if not tx.readonly:
        authority.verify_registration(subject, principal, getattr(tx, 'conn', None))
    return capture


def _reservation(capture, principal, request, job):
    p = provenance(capture)
    # Actor is this real server registration principal, never original generation actor.
    document = dict(provenance=p, snapshot=json.loads(capture.snapshot_json), actor=principal.actor)
    plan_hash = digest(document)
    p['registration_plan_digest'] = plan_hash
    return dict(request_id=request, job_id=job,
        configuration_id=capture.plan.binding.configuration_id,
        visual_basis=capture.plan.binding.current_visual_basis, review_basis=capture.review_basis,
        snapshot=json.loads(capture.snapshot_json), actor=principal.actor,
        origin_kind='existing_import', model=None, import_provenance=p,
        status='running', phase='import_storage', selected=False, asset=None)


def _same(row, wanted, *, exact_job=False):
    keys = ('request_id', 'configuration_id', 'visual_basis', 'review_basis',
            'snapshot', 'actor', 'origin_kind', 'model', 'import_provenance')
    if (not row or any(row.get(k) != wanted[k] for k in keys)
            or not _uuid(row.get('job_id')) or row.get('selected') is not False
            or row.get('status') not in ('running', 'failed', 'ready')
            or row.get('phase') not in ('import_storage', 'import_failed', 'complete')):
        raise Conflict()
    if exact_job and row['job_id'] != wanted['job_id']:raise Conflict()
    return row


def _receipt_valid(receipt, job, raw):
    return (type(receipt) is ObjectReceipt and receipt.bucket == BUCKET
            and receipt.key == f'pc-configurations/{job}/representative.png'
            and receipt.sha256 == hashlib.sha256(raw).hexdigest()
            and receipt.size == len(raw) and type(receipt.generation) is str
            and re.fullmatch('[1-9][0-9]*', receipt.generation) is not None)


class RefreshBinding:
    """Request-local trusted injection. No provider/source installed by default.
    Scope is server-pinned and verified against every actual transaction capture.
    """
    def __init__(self, contract, scope):
        self.contract, self.scope = contract, scope
        self.proof = None


class _TransactionAuthority:
    def __init__(self, base, binding, envelope, connection):
        self.base, self.binding, self.envelope, self.connection = base, binding, envelope, connection
        self.proof = None
    def principal(self):return self.base.principal()
    def verify_registration(self, subject, principal, connection=None):
        if connection is not self.connection:raise Denied('refresh_connection_changed')
        return self.base.verify_registration(subject,principal,connection)
    def verify_reuse(self, subject, principal, connection=None):
        from .pc_existing_media_refresh import Unavailable, BoundaryViolation
        if connection is not self.connection or connection is None:raise Denied('refresh_connection_changed')
        scope = self.binding.scope
        p,b = subject.original,subject.current
        if ((p.configuration_id,b.offer_id,b.configuration_id,b.revision,b.current_visual_basis,
                p.original_sha256,p.manifest_sha256,b.case.product_code) !=
            (scope.source_sku,scope.offer_id,scope.configuration_id,scope.revision,scope.visual_basis,
                scope.original_sha256,scope.manifest_sha256,scope.case_product_code)):
            raise Stale()
        if self.proof is None:
            try:self.proof = self.binding.contract.consume(self.envelope,scope,connection)
            except (Unavailable,BoundaryViolation):raise Denied('refresh_local_evidence_unavailable') from None
            self.binding.proof = self.proof
        # Independent actual reuse/session checks remain, on every callback.
        return self.base.verify_reuse(subject,principal,connection)


class Runtime:
    def __init__(self, store, objects, authority, uuid_factory=uuid4, *, refresh=None):
        self.store, self.objects, self.authority = store, objects, authority
        self.uuid_factory = uuid_factory
        self.refresh = refresh

    @contextmanager
    def _transaction(self, stage, expected, readonly=False):
        from .pc_existing_media_refresh import Stage, RefreshContract, Unavailable, BoundaryViolation
        binding = self.refresh
        if (type(binding) is not RefreshBinding or type(binding.contract) is not RefreshContract
                or not binding.contract.deferred_completion):
            raise Denied('refresh_unwired')
        scope = binding.scope
        if (scope.revision,scope.visual_basis,scope.review_basis,scope.original_sha256,scope.manifest_sha256) != (
                expected.revision,expected.visual_basis,expected.review_basis,expected.original_sha256,expected.manifest_sha256):
            raise Stale()
        try:envelope = binding.contract.refresh(Stage(stage),scope)
        except (Unavailable,BoundaryViolation):raise Denied('refresh_unavailable') from None
        with self.store.transaction(readonly=readonly) as tx:
            authority = _TransactionAuthority(self.authority,binding,envelope,getattr(tx,'conn',None))
            yield tx,authority
            if authority.proof is None:raise Denied('refresh_not_consumed')

    def _acknowledge(self, request, job, row):
        from .pc_existing_media_refresh import DatabaseResult, scope_hash, Unavailable, BoundaryViolation
        binding = self.refresh
        if binding is None or binding.proof is None:raise Denied('refresh_completion_unavailable')
        if row['job_id'] != job:raise Conflict()
        result = DatabaseResult(row['request_id'],row['job_id'],scope_hash(binding.scope),
            binding.proof.round_number,row['status'],row['phase'],row['selected'])
        try:binding.contract.acknowledge(binding.proof,request,binding.scope,result,expected_job_id=job)
        except (Unavailable,BoundaryViolation):raise CommitUnknown() from None

    def dry_run(self, code, expected):
        try:
            if type(code) is not int or code not in (113835, 113836): raise Denied()
            principal = self.authority.principal()
            with self._transaction('read_only',expected,readonly=True) as (tx,authority):
                capture = _checked(tx, code, expected, authority, principal)
                value = digest(dict(provenance=provenance(capture),
                                    snapshot=json.loads(capture.snapshot_json), actor=principal.actor))
            return Outcome('dry_run', plan_digest=value)
        except Stale: return Outcome('stale')
        except Denied: return Outcome('denied')
        except Conflict: return Outcome('conflict')
        except Exception: return Outcome('db_unknown')

    def _reconcile(self, code, expected, principal, wanted, *, exact_job=False):
        with self._transaction('read_only',expected,readonly=True) as (tx,authority):
            capture = _checked(tx, code, expected, authority, principal)
            fresh = _reservation(capture, principal, wanted['request_id'], wanted['job_id'])
            if fresh != wanted: raise Stale()
            row = tx.get(wanted['request_id'])
            if row is None: raise CommitUnknown()
            return _same(row, wanted, exact_job=exact_job)

    def apply(self, code, expected, request_id=None):
        request, job, wanted = request_id, None, None
        try:
            if type(code) is not int or code not in (113835, 113836): raise Denied()
            if request is not None and not _uuid(request): raise Denied()
            principal = self.authority.principal()
            try:
                with self._transaction('before_reserve',expected) as (tx,authority):
                    capture = _checked(tx, code, expected, authority, principal)
                    # No IDs until apply authority and expected pins have been checked.
                    if request is None: request = str(self.uuid_factory())
                    previous = tx.get(request)
                    # Same request yields the same candidate job even if the
                    # earlier COMMIT is unresolved and not yet visible.
                    job = previous['job_id'] if previous else str(uuid5(UUID(request), 'pc-existing-media-import-v1'))
                    if not _uuid(request) or not _uuid(job): raise Conflict()
                    wanted = _reservation(capture, principal, request, job)
                    row = _same(tx.reserve(wanted), wanted)
            except CommitUnknown:
                row = self._reconcile(code, expected, principal, wanted)
            # A competing same-request reservation can win with its own job ID.
            job = row['job_id']
            wanted['job_id'] = job
            if row['status'] == 'ready':
                if row['phase'] != 'complete' or not row.get('asset'): raise Conflict()
                # Recheck exact object on resumes; do not trust a DB success alone.
            try: raw = self.store.original_bytes(code)
            except Exception as error: raise SourceUnavailable() from error
            if (type(raw) is not bytes or not raw.startswith(b'\x89PNG\r\n\x1a\n')
                    or hashlib.sha256(raw).hexdigest() != expected.original_sha256):
                raise Conflict()
            # No network under any DB transaction/row lock.
            receipt = (self.objects.verify_existing(job, raw, row['asset'].get('generation'))
                       if row['status'] == 'ready' else self.objects.create_or_verify(job, raw))
            if not _receipt_valid(receipt, job, raw): raise Conflict()
            asset = dict(asdict(receipt), notice=capture.plan.notice)
            if row['status'] == 'ready' and row['asset'] != asset: raise Conflict()
            try:
                with self._transaction('before_finalize',expected) as (tx,authority):
                    current = _checked(tx, code, expected, authority, principal)
                    fresh = _reservation(current, principal, request, job)
                    if fresh != wanted: raise Stale()
                    now = _same(tx.get(request, lock=True), wanted, exact_job=True)
                    if now['status'] == 'ready' and now['asset'] != asset: raise Conflict()
                    if now['status'] != 'ready':
                        tx.finalize(request, job, asset)
                    now = _same(tx.get(request, lock=True), wanted, exact_job=True)
            except CommitUnknown:
                now = self._reconcile(code, expected, principal, wanted, exact_job=True)
                if now['status'] != 'ready' or now.get('asset') != asset:
                    return Outcome('db_unknown', request, job)
            self._acknowledge(request,job,now)
            return Outcome('registered', request, job, wanted['import_provenance']['registration_plan_digest'])
        except Denied: return Outcome('denied', request, job)
        except Stale: return Outcome('stale', request, job)
        except Conflict: return Outcome('conflict', request, job)
        except ObjectUnknown: return Outcome('object_unknown', request, job)
        except SourceUnavailable: return Outcome('source_unavailable', request, job)
        except Exception: return Outcome('db_unknown', request, job)


class PgStore:
    """PostgreSQL adapter. Engine, authority and case reader are SERVER wiring.
    case_reader must authenticate normalized exterior evidence; default denied.
    No schema application, permission changes, staging bytes or generation.
    """
    def __init__(self, engine, archive, case_reader=None):
        self.engine, self.archive, self.case_reader = engine, Path(archive), case_reader

    def original_bytes(self, code):
        if code not in (113835, 113836): raise Denied()
        return (self.archive / 'originals' / f'P{code}.png').read_bytes()

    @contextmanager
    def transaction(self, readonly=False):
        from sqlalchemy import text
        conn = self.engine.connect().execution_options(isolation_level='REPEATABLE READ')
        transaction = conn.begin()
        try:
            conn.execute(text('SET TRANSACTION READ ONLY' if readonly else 'SET TRANSACTION READ WRITE'))
            yield _PgTx(conn, self, readonly)
            if readonly:
                transaction.rollback()
            else:
                try: transaction.commit()
                except Exception as error: raise CommitUnknown() from error
        except Exception:
            try: transaction.rollback()
            except Exception: pass
            raise
        finally: conn.close()


class _PgTx:
    def __init__(self, conn, store, readonly):
        self.conn, self.store, self.readonly = conn, store, readonly

    def capture(self, code, authority, principal):
        if not callable(self.store.case_reader): raise Denied('case_authority_unwired')
        from sqlalchemy import text
        from .pc_configuration_copy import read_sold_offer_configuration
        from .pc_media import snapshot
        from tools.register_existing_pc_media import CaseEvidence
        conn, store = self.conn, self.store
        sold = conn.execute(text('SELECT product_code,status FROM products WHERE product_code=:code'),
                            dict(code=code)).mappings().first()
        if not sold or sold['product_code'] != code or sold['status'] != '판매중': raise Denied()
        if not self.readonly:
            # Lock exact registered mapping as well as configuration; no network here.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
            conn.execute(text('SELECT offer_id FROM pc_configuration_offers WHERE offer_id=:offer FOR SHARE'),
                         dict(offer=f'P{code}')).first()
        bound = read_sold_offer_configuration(conn, code)
        identity = bound['configuration_id']
        current = snapshot(conn, identity, lock=not self.readonly)
        if current['errors']: raise Denied('image_requirements_unresolved')
        cases = [x for x in current['snapshot']['parts'] if x['slot'] == 'CASE']
        if len(cases) != 1: raise Denied()
        row = conn.execute(text('SELECT source_product_code,content,source_fingerprint FROM product_explanations '
                                'WHERE source_product_code=:code'), dict(code=cases[0]['code'])).mappings().first()
        case = store.case_reader(conn, dict(row)) if row else None
        if type(case) is not CaseEvidence or case.product_code != cases[0]['code']: raise Denied()
        binding = ImportBinding(code, bound['offer_id'], identity, bound['revision'],
                                current['visual_basis'], case)
        class Inputs:
            def current_binding(self, value):
                if value != code: raise Denied()
                return binding
            def original(self, value):
                if value != code: raise Denied()
                return OriginalInput((store.archive / 'manifest.json').read_bytes(), store.original_bytes(value))
        class Permission:
            def verify_reuse(self, subject):
                authority.verify_reuse(subject, principal, conn)
                return Decision.ALLOW
        result = plan_import(code, Ports(Inputs(), Permission()))
        if result.state != 'planned': raise Denied()
        return Capture(result.plan, current['basis'], canonical(current['snapshot']))

    def get(self, request, lock=False):
        from sqlalchemy import text
        row = self.conn.execute(text('SELECT job_id,request_id,configuration_id,visual_basis,review_basis,'
            'snapshot,actor,origin_kind,model,import_provenance,status,phase,selected,asset '
            'FROM pc_media_jobs WHERE request_id=:request' + (' FOR UPDATE' if lock else '')),
            dict(request=request)).mappings().first()
        if not row: return None
        value = dict(row)
        value['job_id'], value['request_id'] = str(value['job_id']), str(value['request_id'])
        return value

    def reserve(self, wanted):
        from sqlalchemy import text
        if self.readonly: raise Denied()
        values = dict(wanted, snapshot=canonical(wanted['snapshot']),
                      import_provenance=canonical(wanted['import_provenance']))
        self.conn.execute(text('INSERT INTO pc_media_jobs '
            '(job_id,request_id,configuration_id,visual_basis,review_basis,snapshot,model,actor,'
            'origin_kind,import_provenance,status,phase,selected) VALUES '
            '(:job_id,:request_id,:configuration_id,:visual_basis,:review_basis,CAST(:snapshot AS jsonb),'
            'NULL,:actor,:origin_kind,CAST(:import_provenance AS jsonb),:status,:phase,false) '
            'ON CONFLICT(request_id) DO NOTHING'), values)
        row = self.get(wanted['request_id'], lock=True)
        if row is None:
            # An ON CONFLICT winner may be newer than this RR snapshot.
            # Reconcile in a fresh snapshot; never allocate/upload another job.
            raise CommitUnknown()
        return row

    def finalize(self, request, job, asset):
        from sqlalchemy import text
        if self.readonly: raise Denied()
        result = self.conn.execute(text("UPDATE pc_media_jobs SET status='ready',phase='complete',"
            "asset=CAST(:asset AS jsonb),error=NULL,updated_at=now() "
            "WHERE request_id=:request AND job_id=:job AND origin_kind='existing_import' AND selected=false"),
            dict(request=request, job=job, asset=canonical(asset)))
        if result.rowcount != 1: raise Conflict()


class GcsObjects:
    """Create-only exact-job objects. No overwrite/delete or provider method."""
    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    def _session(self):
        if self.session_factory: return self.session_factory()
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
        return AuthorizedSession(credentials)

    def _verified(self, session, meta, job, raw):
        from urllib.parse import quote
        key = f'pc-configurations/{job}/representative.png'
        generation = meta.get('generation')
        if (meta.get('bucket') != BUCKET or meta.get('name') != key
                or type(generation) is not str or not re.fullmatch('[1-9][0-9]*', generation)
                or str(meta.get('size')) != str(len(raw)) or meta.get('contentType') != 'image/png'):
            raise Conflict()
        url = f'https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(key, safe="")}'
        response = session.get(url, params=dict(alt='media', generation=generation),
                               timeout=(10, 30), allow_redirects=False, stream=True)
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > len(raw): raise Conflict()
            chunks.append(chunk)
        data = b''.join(chunks)
        if data != raw: raise Conflict()
        return ObjectReceipt(BUCKET, key, hashlib.sha256(data).hexdigest(), len(data), generation)

    def verify_existing(self, job, raw, generation):
        from urllib.parse import quote
        if not _uuid(job) or type(generation) is not str or not re.fullmatch('[1-9][0-9]*', generation):
            raise Conflict()
        key = f'pc-configurations/{job}/representative.png'
        url = f'https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(key, safe="")}'
        try:
            with self._session() as session:
                response = session.get(url, params=dict(generation=generation),
                                       timeout=(10, 30), allow_redirects=False)
                response.raise_for_status()
                meta = response.json()
                if meta.get('generation') != generation: raise Conflict()
                return self._verified(session, meta, job, raw)
        except Conflict: raise
        except Exception as error: raise ObjectUnknown() from error

    def create_or_verify(self, job, raw):
        from urllib.parse import quote
        if not _uuid(job) or type(raw) is not bytes or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise Conflict()
        key = f'pc-configurations/{job}/representative.png'
        metadata_url = f'https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(key, safe="")}'
        try:
            with self._session() as session:
                response = session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o',
                    params=dict(uploadType='media', name=key, ifGenerationMatch='0'), data=raw,
                    headers={'Content-Type': 'image/png'}, timeout=(10, 40), allow_redirects=False)
                if response.status_code == 412:
                    response = session.get(metadata_url, timeout=(10, 30), allow_redirects=False)
                response.raise_for_status()
                return self._verified(session, response.json(), job, raw)
        except Conflict: raise
        except Exception as error: raise ObjectUnknown() from error
