"""Unwired outside-tx refresh contract; no CLI, engine, network or grant defaults.

Read-response integrity, execution permission and source freshness are separate.
Trusted callbacks are supplied by future server integration, never request input.
Existing runtime/admin/authority are deliberately unchanged.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re

from tools.register_existing_pc_media import Decision


class Stage(Enum):
    BEFORE_RESERVE = 'before_reserve'
    BEFORE_FINALIZE = 'before_finalize'
    READ_ONLY = 'read_only'


class BoundaryViolation(Exception):
    pass


class Unavailable(Exception):
    """Safe unknown/denied reason, never a raw transport exception."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Scope:
    source_sku: str
    offer_id: str
    configuration_id: str
    revision: int
    visual_basis: str
    review_basis: str
    original_sha256: str
    manifest_sha256: str
    case_product_code: int
    record_path: str
    record_sha256: str
    record_version: int


def _hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def scope_hash(scope):
    if (type(scope) is not Scope or scope.source_sku not in ('P113835','P113836')
            or scope.offer_id != scope.source_sku
            or type(scope.configuration_id) is not str or not scope.configuration_id.strip()
            or type(scope.revision) is not int or scope.revision <= 0
            or type(scope.case_product_code) is not int
            or scope.case_product_code != {'P113835':129552,'P113836':129551}[scope.source_sku]
            or type(scope.record_version) is not int or scope.record_version <= 0
            or type(scope.record_path) is not str or not scope.record_path.startswith('기록/팝콘AI/')
            or not all(_hash(v) for v in (scope.visual_basis,scope.review_basis,
                scope.original_sha256,scope.manifest_sha256,scope.record_sha256))):
        raise Unavailable('scope_unknown')
    return hashlib.sha256(json.dumps(asdict(scope),ensure_ascii=False,
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True, repr=False)
class Record:
    path: str
    body: str
    sha: str
    version: int
    updated: str


def parse_record(response, scope):
    """Validate the actual workroom note shape; not a freshness/withdrawal check."""
    scope_hash(scope)
    if type(response) is not dict or set(response) != {'path','body','sha','version','updated'}:
        raise Unavailable('record_shape_unknown')
    path, body, sha, version, updated = (response[k] for k in ('path','body','sha','version','updated'))
    try:
        body_sha = hashlib.sha256(body.encode()).hexdigest() if type(body) is str else None
    except UnicodeError:
        raise Unavailable('record_body_unknown') from None
    if (type(path) is not str or path != scope.record_path
            or type(body) is not str or not body.strip() or not _hash(sha)
            or body_sha != sha
            or type(version) is not int or version <= 0
            or sha != scope.record_sha256 or version != scope.record_version
            or type(updated) is not str
            or re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',updated) is None):
        raise Unavailable('record_mismatch_or_unknown')
    try:
        value = datetime.fromisoformat(updated.replace('Z','+00:00'))
        if value.utcoffset() is None:raise ValueError()
    except ValueError:
        raise Unavailable('record_updated_unknown') from None
    return Record(path,body,sha,version,updated)


@dataclass(frozen=True, repr=False)
class ReadObservation:
    record: object
    # Newly identified correction/withdrawal at another ID is not silently ignored.
    # Empty does not prove the absence of such records.
    related_changes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceConfirmation:
    stage: Stage
    round_number: int
    record_sha256: str
    scope_sha256: str
    decision: Decision
    source_reference: str
    freshness_confirmed: bool | None
    withdrawal_coverage_confirmed: bool | None
    withdrawn: bool | None


@dataclass(frozen=True, repr=False)
class Envelope:
    stage: Stage
    round_number: int
    scope_sha256: str
    record: Record | None
    confirmation: SourceConfirmation | None
    state: Decision
    reason: str

    def __bool__(self):
        raise TypeError('refresh envelope is not an execution permission')


@dataclass(frozen=True)
class LocalEvidence:
    """Single-consumption coordination proof, not production FreshReuseEvidence."""
    stage: Stage
    round_number: int
    scope_sha256: str
    record_sha256: str

    def __bool__(self):
        raise TypeError('local evidence is not an execution permission')


class RefreshContract:
    """One request's reserve/final refresh rounds and same-connection consumption.

    record_reader and optional server_confirmer may do future source IO only in
    refresh(), while tx_active() is False. server_confirmer must independently
    establish actual currentness and complete withdrawal coverage each round.
    It is not inferred from path/body SHA/version/updated or related_changes=().

    local_verifier(scope,envelope,connection) must read current DB binding and
    permission via the supplied active tx connection, using local evidence only.
    No actual callbacks/transport/hooks, TTL, signature or policy are installed.
    """
    def __init__(self, *, tx_active, record_reader=None, server_confirmer=None,
                 local_verifier=None, deferred_completion=False):
        self._tx_active = tx_active
        self._reader = record_reader
        self._confirmer = server_confirmer
        self._local = local_verifier
        self._round = 0
        self._current = None
        self._reserved = None
        self._scope = None
        self._finished = False
        self._deferred_completion = deferred_completion is True
        self._pending_final = False
        self._last_proof = None

    @property
    def deferred_completion(self):return self._deferred_completion

    def _boundary(self, active):
        if not callable(self._tx_active) or self._tx_active() is not active:
            raise BoundaryViolation('trusted transaction boundary unavailable')

    def _confirmation_matches(self, confirmation, stage, record, scope_sha):
        return (type(confirmation) is SourceConfirmation
            and confirmation.stage is stage and type(confirmation.round_number) is int
            and confirmation.round_number == self._round
            and confirmation.record_sha256 == record.sha and confirmation.scope_sha256 == scope_sha
            and confirmation.decision is Decision.ALLOW
            and type(confirmation.source_reference) is str and bool(confirmation.source_reference.strip())
            and confirmation.freshness_confirmed is True
            and confirmation.withdrawal_coverage_confirmed is True and confirmation.withdrawn is False)

    def refresh(self, stage, scope):
        self._boundary(False)
        if type(stage) is not Stage or self._finished:
            raise Unavailable('refresh_order_unknown')
        expected = Stage.BEFORE_RESERVE if self._reserved is None else Stage.BEFORE_FINALIZE
        if stage is not expected and not (self._deferred_completion and stage is Stage.READ_ONLY):
            raise Unavailable('refresh_order_unknown')
        self._current = None  # An attempted new round invalidates any old snapshot.
        self._round += 1
        h = scope_hash(scope)
        if self._scope is not None and h != self._scope:
            raise Unavailable('scope_changed')
        record = confirmation = None
        state, reason = Decision.UNKNOWN, 'source_unwired'
        try:
            if not callable(self._reader):raise Unavailable('read_source_unwired')
            try:raw = self._reader(scope.record_path)
            except Exception:raise Unavailable('source_read_unknown') from None
            self._boundary(False)
            if type(raw) is ReadObservation:
                if type(raw.related_changes) is not tuple or raw.related_changes:
                    raise Unavailable('related_change_unknown')
                raw = raw.record
            record = parse_record(raw,scope)
            if self._reserved is not None and record != self._reserved:
                raise Unavailable('record_changed')
            if not callable(self._confirmer):raise Unavailable('fresh_source_unwired')
            self._boundary(False)
            try:confirmation = self._confirmer(record,scope,stage,self._round)
            except Exception:raise Unavailable('source_read_unknown') from None
            self._boundary(False)
            if not self._confirmation_matches(confirmation,stage,record,h):
                raise Unavailable('freshness_withdrawal_or_scope_unknown')
            # This decision comes from the explicit trusted source, never parsing.
            state, reason = confirmation.decision, 'local_revalidation_required'
        except BoundaryViolation:
            raise
        except Unavailable as error:
            reason = error.reason
        except Exception:
            reason = 'source_read_unknown'
        envelope = Envelope(stage,self._round,h,record,confirmation,state,reason)
        self._current = envelope
        return envelope

    def consume(self, envelope, scope, connection):
        self._boundary(True)
        if (type(envelope) is not Envelope or envelope is not self._current
                or connection is None):
            raise Unavailable('stale_or_unbound_envelope')
        self._current = None  # Single use even if local verification fails.
        h = scope_hash(scope)
        if (h != envelope.scope_sha256 or envelope.state is not Decision.ALLOW
                or envelope.record is None
                or not self._confirmation_matches(envelope.confirmation,envelope.stage,envelope.record,h)):
            raise Unavailable('local_evidence_unknown')
        if not callable(self._local):raise Unavailable('local_verifier_unwired')
        # No source refresh, CLI or network invocation on this path.
        if self._local(scope,envelope,connection) is not Decision.ALLOW:
            raise Unavailable('current_binding_or_permission_unknown')
        self._boundary(True)
        if envelope.stage is Stage.BEFORE_RESERVE:
            self._reserved, self._scope = envelope.record,h
        elif envelope.stage is Stage.BEFORE_FINALIZE:
            if self._deferred_completion:self._pending_final = True
            else:self._finished = True
        proof = LocalEvidence(envelope.stage,envelope.round_number,h,envelope.record.sha)
        self._last_proof = proof
        return proof

    def acknowledge(self, proof, request_id, scope, db_result, *, expected_job_id=None):
        """Trusted runtime supplies actual row read after successful tx exit.
        This is completion bookkeeping only, never a grant or local permission.
        """
        self._boundary(False)
        if (not self._deferred_completion or not self._pending_final
                or proof is not self._last_proof or type(db_result) is not DatabaseResult
                or db_result.request_id != request_id
                or type(expected_job_id) is not str or db_result.job_id != expected_job_id
                or db_result.scope_sha256 != scope_hash(scope)
                or proof.scope_sha256 != db_result.scope_sha256
                or db_result.round_number != proof.round_number
                or db_result.state != 'ready' or db_result.phase != 'complete'
                or db_result.selected is not False):
            raise Unavailable('database_completion_unknown')
        from uuid import UUID
        try:
            if str(UUID(request_id)) != request_id or str(UUID(expected_job_id)) != expected_job_id:
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise Unavailable('database_identity_unknown') from None
        self._finished = True


@dataclass(frozen=True)
class DatabaseResult:
    request_id: str
    job_id: str
    scope_sha256: str
    round_number: int
    state: str
    phase: str
    selected: bool

