"""New runtime fixtures only. No real PG/GCS/provider or prior-suite execution."""
from contextlib import contextmanager
from dataclasses import replace
import copy
import functools
import hashlib
import json
from pathlib import Path
import sys

import types
import unittest
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.register_existing_pc_media import (
    CaseEvidence, ImportBinding, OriginalProvenance, ImportPlan, MANIFEST_SHA, Decision, BUCKET,
)
from api.pc_existing_media_import import (
    Capture, Expected, Runtime, ServerAuthority, CommitUnknown, Conflict,
    ObjectReceipt, ObjectUnknown, GcsObjects, PgStore, canonical, digest,
)
from api.pc_existing_media_import import _reservation
from api.pc_existing_media_import import provenance

ARCHIVE = Path('D:/WORK/PopcornAI') / 'outputs' / 'assembled-pc-images-20260929'

# Original archive bytes live only on the development PC (D:/WORK). Read lazily so
# tests that need them raise FileNotFoundError at run time, which tests/conftest.py
# reports as a PC-only skip when that root is absent; the rest still run.
@functools.lru_cache(maxsize=None)
def _raw():
    return (ARCHIVE / 'originals' / 'P113835.png').read_bytes()


REQUEST = 'b7c26ac6-38d7-4cbb-97ea-a0f8945374de'
WINNER = '5d8e2c70-8052-4543-a701-c15aa57a4b78'


class Fixture:
    def __init__(self):
        snapshot = dict(parts=[], cooling={'fixture': True}, notice='fixture')
        binding = ImportBinding(113835, 'P113835', 'P113835', 2, digest(snapshot),
            CaseEvidence(129552, 'DAVEN N1 MESH', 'black', 'closed_mesh_opaque', 'N1_MESH', 'fixture'))
        original = OriginalProvenance('P113835', 'originals/P113835.png', hashlib.sha256(_raw()).hexdigest(),
            MANIFEST_SHA, 1, ('fixture QA',), None, None, None)
        self.capture = Capture(ImportPlan(original, binding), 'b' * 64, canonical(snapshot))
        self.expected = Expected(2, binding.current_visual_basis, 'b' * 64,
                                 original.original_sha256, MANIFEST_SHA)
        self.allowed = Decision.ALLOW
        self.registration_allowed = Decision.ALLOW
        self.principal_dict = {'operator_id': 7, 'role': 'operator'}
        self.authority = ServerAuthority(lambda subject, actor, connection: self.allowed,
                                         lambda: self.principal_dict,
                                         lambda subject, actor, connection: self.registration_allowed)
        self.active = False
        self.jobs = {}
        self.commits = 0
        self.fail_commit = {}
        self.capture_count = 0
        self.mutate_final = False
        self.fail_final = False
        self.fail_reads = False
        self.winner = False
        self.ids = 0
        self.store = Store(self)
        self.objects = Objects(self)
        self.runtime = Runtime(self.store, self.objects, self.authority, self.new_uuid)

    def new_uuid(self):
        self.ids += 1
        return UUID(int=self.ids)


class Store:
    def __init__(self, fixture): self.f = fixture
    def original_bytes(self, code): return _raw()
    @contextmanager
    def transaction(self, readonly=False):
        f = self.f
        assert not f.active
        f.active = True
        working = copy.deepcopy(f.jobs)
        try:
            yield Tx(f, working, readonly)
            if not readonly:
                f.commits += 1
                mode = f.fail_commit.get(f.commits)
                if mode == 'before': raise CommitUnknown()
                f.jobs = working
                if mode == 'after': raise CommitUnknown()
        finally:
            f.active = False


class Tx:
    def __init__(self, fixture, working, readonly):
        self.f, self.working, self.readonly = fixture, working, readonly
    def capture(self, code, authority, principal):
        self.f.capture_count += 1
        capture = self.f.capture
        if self.f.mutate_final and self.f.capture_count >= 2:
            return replace(capture, plan=replace(capture.plan,
                binding=replace(capture.plan.binding, revision=3)))
        return capture
    def get(self, request, lock=False):
        if self.f.fail_reads: raise RuntimeError('private DB')
        return copy.deepcopy(self.working.get(request))
    def reserve(self, wanted):
        assert not self.readonly
        value = copy.deepcopy(wanted)
        if self.f.winner: value['job_id'] = WINNER
        self.working.setdefault(wanted['request_id'], value)
        return copy.deepcopy(self.working[wanted['request_id']])
    def finalize(self, request, job, asset):
        assert not self.readonly
        if self.f.fail_final: raise RuntimeError('private final error')
        row = self.working[request]
        assert row['job_id'] == job
        row.update(status='ready', phase='complete', asset=copy.deepcopy(asset))


class Objects:
    def __init__(self, fixture):
        self.f, self.objects, self.calls = fixture, {}, []
        self.fail = False
        self.withdraw = False
    def create_or_verify(self, job, raw):
        assert not self.f.active, 'network under transaction'
        self.calls.append(job)
        if self.fail: raise ObjectUnknown()
        self.objects.setdefault(job, raw)
        if self.objects[job] != raw: raise Conflict()
        if self.withdraw: self.f.allowed = Decision.WITHDRAWN
        return ObjectReceipt(BUCKET, f'pc-configurations/{job}/representative.png',
                             hashlib.sha256(raw).hexdigest(), len(raw), '123')
    def verify_existing(self, job, raw, generation):
        assert not self.f.active
        if job not in self.objects: raise ObjectUnknown()
        if self.objects[job] != raw or generation != '123': raise Conflict()
        return ObjectReceipt(BUCKET, f'pc-configurations/{job}/representative.png',
                             hashlib.sha256(raw).hexdigest(), len(raw), generation)


class RuntimeTests(unittest.TestCase):
    def test_missing_archive_after_reserve_stops_without_regeneration(self):
        f = Fixture()
        def missing(code): raise FileNotFoundError('private archive path')
        f.store.original_bytes = missing
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'source_unavailable')
        self.assertIn(REQUEST, f.jobs)
        self.assertFalse(f.objects.calls)
    def test_second_original_exception_ssd_and_current_binding_stay_separate(self):
        f = Fixture()
        p = replace(f.capture.plan.provenance, configuration_id='P113836',
                    original_path='originals/P113836.png', reused_from='P113838',
                    reuse_exception='closed white panel hides cooler difference',
                    facts_change_reference='SSD128462 500GB added')
        b = replace(f.capture.plan.binding, product_code=113836, offer_id='P113836',
                    configuration_id='P113836', revision=3,
                    case=replace(f.capture.plan.binding.case, product_code=129551, color='white'))
        value = provenance(replace(f.capture, plan=ImportPlan(p, b)))
        self.assertEqual(value['original']['reused_from'], 'P113838')
        self.assertIn('500GB', value['original']['ssd_facts_reference'])
        self.assertEqual(value['original']['original_revision'], 1)
        self.assertEqual(value['current_binding']['revision'], 3)
        self.assertIsNone(value['original']['generation_actor'])

    def test_current_case_change_after_upload_preserves_object(self):
        f = Fixture()
        original = f.objects.create_or_verify
        def changed_case(job, raw):
            receipt = original(job, raw)
            f.capture = replace(f.capture, plan=replace(f.capture.plan,
                binding=replace(f.capture.plan.binding,
                    case=replace(f.capture.plan.binding.case, front='changed-front'))))
            return receipt
        f.objects.create_or_verify = changed_case
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'stale')
        self.assertIn(result.job_id, f.objects.objects)

    def test_fresh_request_allocates_only_request_and_repeat_retains_pair(self):
        f = Fixture()
        result = f.runtime.apply(113835, f.expected)
        self.assertEqual(result.state, 'registered')
        self.assertEqual(f.ids, 1)
        again = f.runtime.apply(113835, f.expected, result.request_id)
        self.assertEqual((again.request_id, again.job_id), (result.request_id, result.job_id))
        self.assertEqual(f.ids, 1)
    def test_reuse_permission_is_not_registration_permission(self):
        for registration in (Decision.UNKNOWN, Decision.DENY, True):
            f = Fixture()
            f.registration_allowed = registration
            self.assertEqual(f.runtime.apply(113835, f.expected).state, 'denied')
            self.assertEqual(f.ids, 0)
            self.assertFalse(f.jobs or f.objects.calls)
        f = Fixture()
        f.authority.registration_verifier = None
        self.assertEqual(f.runtime.apply(113835, f.expected).state, 'denied')
    def test_success_selected_false_schema_provenance_and_real_actor(self):
        f = Fixture()
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'registered')
        row = f.jobs[REQUEST]
        self.assertIs(row['selected'], False)
        self.assertIsNone(row['model'])
        self.assertEqual(row['origin_kind'], 'existing_import')
        self.assertEqual(row['actor'], 'operator:7')
        self.assertEqual(row['phase'], 'complete')
        original = row['import_provenance']['original']
        for field in ('generation_model', 'generation_actor', 'generation_time', 'original_visual_basis'):
            self.assertIsNone(original[field])
        self.assertEqual(row['asset']['generation'], '123')
        self.assertEqual(f.ids, 0)

    def test_default_authority_denies_before_db_and_ids(self):
        f = Fixture()
        f.runtime.authority = ServerAuthority()
        self.assertEqual(f.runtime.apply(113835, f.expected).state, 'denied')
        self.assertEqual(f.ids, 0)
        self.assertFalse(f.jobs)
        self.assertFalse(f.objects.calls)

    def test_dry_run_never_writes_or_allocates_ids(self):
        f = Fixture()
        self.assertEqual(f.runtime.dry_run(113835, f.expected).state, 'dry_run')
        self.assertEqual(f.commits, 0)
        self.assertEqual(f.ids, 0)
        self.assertFalse(f.jobs or f.objects.calls)

    def test_permission_unknown_bool_and_role_failure(self):
        for permission in (Decision.UNKNOWN, Decision.WITHDRAWN, True, {'allowed': True}):
            f = Fixture()
            f.allowed = permission
            self.assertEqual(f.runtime.apply(113835, f.expected).state, 'denied')
            self.assertEqual(f.ids, 0)
        f = Fixture()
        f.principal_dict = {'operator_id': 7, 'role': 'customer'}
        self.assertEqual(f.runtime.apply(113835, f.expected).state, 'denied')

    def test_expected_pins_stale_before_reservation(self):
        f = Fixture()
        self.assertEqual(f.runtime.apply(113835, replace(f.expected, revision=3)).state, 'stale')
        self.assertEqual(f.ids, 0)

    def test_same_request_idempotency_and_mismatch(self):
        f = Fixture()
        one = f.runtime.apply(113835, f.expected, REQUEST)
        two = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual((one.job_id, two.job_id), (one.job_id, one.job_id))
        self.assertEqual(two.state, 'registered')
        self.assertEqual(len(f.objects.objects), 1)
        self.assertEqual(f.ids, 0)
        f.jobs[REQUEST]['import_provenance']['original']['qa_references'] = ['different']
        self.assertEqual(f.runtime.apply(113835, f.expected, REQUEST).state, 'conflict')

    def test_competing_reservation_uses_winning_job(self):
        f = Fixture()
        f.winner = True
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'registered')
        self.assertEqual(result.job_id, WINNER)
        self.assertEqual(f.objects.calls, [WINNER])

    def test_upload_then_db_failure_keeps_object_and_resumes_same_job(self):
        f = Fixture()
        f.fail_final = True
        first = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(first.state, 'db_unknown')
        self.assertIn(first.job_id, f.objects.objects)
        self.assertEqual(f.jobs[REQUEST]['status'], 'running')
        f.fail_final = False
        second = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(second.state, 'registered')
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(len(f.objects.objects), 1)

    def test_current_revision_change_after_upload_stops_preserving_object(self):
        f = Fixture()
        f.mutate_final = True
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'stale')
        self.assertIn(result.job_id, f.objects.objects)
        self.assertIsNone(f.jobs[REQUEST]['asset'])

    def test_revocation_after_upload_stops_without_delete(self):
        f = Fixture()
        f.objects.withdraw = True
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'denied')
        self.assertIn(result.job_id, f.objects.objects)
        self.assertIs(f.jobs[REQUEST]['selected'], False)

    def test_reserve_commit_unknown_reconciles_confirmed_job(self):
        f = Fixture()
        f.fail_commit[1] = 'after'
        self.assertEqual(f.runtime.apply(113835, f.expected, REQUEST).state, 'registered')
        self.assertEqual(len(f.objects.objects), 1)

    def test_reserve_unconfirmed_commit_never_uploads_new_object(self):
        f = Fixture()
        f.fail_commit[1] = 'before'
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertIn(result.state, ('db_unknown', 'conflict'))
        self.assertEqual(result.request_id, REQUEST)
        self.assertFalse(f.objects.calls)
        f.fail_commit.clear()
        retried = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(retried.state, 'registered')
        self.assertEqual(retried.job_id, result.job_id)
        self.assertEqual(f.ids, 0)

    def test_final_commit_unknown_confirmed_and_unconfirmed(self):
        for mode, expected in (('after', 'registered'), ('before', 'db_unknown')):
            with self.subTest(mode=mode):
                f = Fixture()
                f.fail_commit[2] = mode
                result = f.runtime.apply(113835, f.expected, REQUEST)
                self.assertEqual(result.state, expected)
                self.assertEqual(len(f.objects.objects), 1)

    def test_object_result_unknown_keeps_same_reservation(self):
        f = Fixture()
        f.objects.fail = True
        result = f.runtime.apply(113835, f.expected, REQUEST)
        self.assertEqual(result.state, 'object_unknown')
        self.assertIn(REQUEST, f.jobs)
        self.assertEqual(f.ids, 0)

    def test_selected_or_wrong_origin_resume_conflicts(self):
        for field, value in (('selected', True), ('origin_kind', 'generated'), ('model', 'fake-model')):
            f = Fixture()
            f.runtime.apply(113835, f.expected, REQUEST)
            f.jobs[REQUEST][field] = value
            self.assertEqual(f.runtime.apply(113835, f.expected, REQUEST).state, 'conflict')


class Response:
    def __init__(self, status=200, data=None, content=b''):
        self.status_code, self.data, self.content = status, data, content
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError('private network')
    def json(self): return self.data
    def iter_content(self, size): yield self.content


class Session:
    def __init__(self, existing=False, corrupt=False):
        self.existing, self.corrupt, self.posts, self.gets = existing, corrupt, [], []
        self.key = f'pc-configurations/{WINNER}/representative.png'
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kw):
        self.posts.append((url, kw))
        self.key = kw['params']['name']
        return Response(412 if self.existing else 200, self.metadata())
    def metadata(self):
        return dict(bucket=BUCKET, name=self.key, generation='123', size=str(len(_raw())), contentType='image/png')
    def get(self, url, **kw):
        self.gets.append((url, kw))
        return (Response(content=b'wrong' if self.corrupt else _raw()) if kw.get('params', {}).get('alt') == 'media'
                else Response(data=self.metadata()))


class GcsAdapterTests(unittest.TestCase):
    def test_ready_resume_reads_only_pinned_generation(self):
        session = Session()
        self.assertEqual(GcsObjects(lambda: session).verify_existing(WINNER, _raw(), '123').generation, '123')
        self.assertFalse(session.posts)
    def test_create_and_412_same_bytes_generation_pinned(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                session = Session(existing)
                receipt = GcsObjects(lambda: session).create_or_verify(WINNER, _raw())
                self.assertEqual(receipt.generation, '123')
                self.assertEqual(session.posts[0][1]['params']['ifGenerationMatch'], '0')
                self.assertEqual(session.gets[-1][1]['params'], {'alt': 'media', 'generation': '123'})
                self.assertFalse(hasattr(session, 'delete'))

    def test_412_mismatch_never_overwrites_or_deletes(self):
        session = Session(True, True)
        with self.assertRaises(Conflict):
            GcsObjects(lambda: session).create_or_verify(WINNER, _raw())
        self.assertEqual(len(session.posts), 1)

    def test_transport_unknown_no_cleanup(self):
        class Timeout(Session):
            def post(self, *args, **kwargs): raise TimeoutError('private')
        with self.assertRaises(ObjectUnknown):
            GcsObjects(lambda: Timeout()).create_or_verify(WINNER, _raw())


class SqlResult:
    def __init__(self, row=None, rowcount=1): self.row, self.rowcount = row, rowcount
    def mappings(self): return self
    def first(self): return self.row


class SqlConnection:
    def __init__(self):
        self.log, self.row, self.fail_commit = [], None, False
    def execution_options(self, **kwargs):
        self.log.append(('options', kwargs))
        return self
    def begin(self): self.log.append(('begin',)); return self
    def commit(self):
        self.log.append(('commit',))
        if self.fail_commit: raise RuntimeError('private commit result')
    def rollback(self): self.log.append(('rollback',))
    def close(self): self.log.append(('close',))
    def execute(self, sql, values=None):
        self.log.append((str(sql), copy.deepcopy(values)))
        if str(sql).startswith('INSERT'):
            self.row = dict(values, snapshot=json.loads(values['snapshot']),
                            import_provenance=json.loads(values['import_provenance']))
        if str(sql).startswith('SELECT product_code,status'):
            return SqlResult(dict(product_code=113835, status='판매중'))
        if str(sql).startswith('SELECT source_product_code,content'):
            return SqlResult(dict(source_product_code=129552, content={}, source_fingerprint='fixture'))
        if str(sql).startswith('SELECT job_id,request_id'):
            return SqlResult(self.row)
        return SqlResult()


class SqlEngine:
    def __init__(self, connection): self.connection = connection
    def connect(self): return self.connection


class PostgresAdapterTests(unittest.TestCase):
    def setUp(self):
        sqlalchemy = types.ModuleType('sqlalchemy')
        sqlalchemy.text = lambda value: value
        patcher = patch.dict(sys.modules, {'sqlalchemy': sqlalchemy})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = SqlConnection()
        self.fixture = Fixture()
        self.store = PgStore(SqlEngine(self.conn),
            ARCHIVE)

    def test_short_transaction_sql_json_shape_and_selected_false(self):
        f = self.fixture
        wanted = _reservation(f.capture, f.authority.principal(), REQUEST, WINNER)
        with self.store.transaction() as tx:
            row = tx.reserve(wanted)
            tx.finalize(REQUEST, WINNER, {'fixture': 'asset'})
        self.assertEqual(row['model'], None)
        self.assertEqual(row['origin_kind'], 'existing_import')
        original = row['import_provenance']['original']
        self.assertIsNone(original['generation_actor'])
        sql = [entry[0] for entry in self.conn.log]
        self.assertIn('SET TRANSACTION READ WRITE', sql)
        self.assertTrue(any('ON CONFLICT(request_id) DO NOTHING' in s for s in sql))
        self.assertTrue(any('origin_kind=\'existing_import\' AND selected=false' in s for s in sql))
        self.assertIn(('commit',), self.conn.log)
        self.assertFalse(any('DELETE' in s or 'CREATE ' in s for s in sql))

    def test_readonly_rolls_back_and_prevents_dml(self):
        with self.store.transaction(readonly=True) as tx:
            with self.assertRaises(Exception): tx.finalize(REQUEST, WINNER, {})
        self.assertIn(('options', {'isolation_level': 'REPEATABLE READ'}), self.conn.log)
        self.assertIn(('rollback',), self.conn.log)
        self.assertNotIn(('commit',), self.conn.log)

    def test_native_commit_error_maps_to_unknown_not_false_rollback_success(self):
        self.conn.fail_commit = True
        with self.assertRaises(CommitUnknown):
            with self.store.transaction(): pass
        self.assertIn(('close',), self.conn.log)

    def test_case_reader_unwired_fails_closed(self):
        with self.store.transaction(readonly=True) as tx:
            with self.assertRaises(Exception):
                tx.capture(113835, self.fixture.authority, self.fixture.authority.principal())

    def test_capture_calls_existing_mapping_snapshot_and_pure_validator(self):
        private = types.ModuleType('api.pc_configuration_copy')
        private.read_sold_offer_configuration = lambda conn, code: dict(
            offer_id='P113835', configuration_id='P113835', revision=2)
        media = types.ModuleType('api.pc_media')
        body = dict(parts=[dict(slot='CASE', code=129552)], cooling={'fixture': True}, notice='fixture')
        calls = []
        def snapshot(conn, identity, lock=False):
            calls.append((conn, identity, lock))
            return dict(errors=[], snapshot=body, visual_basis=digest(body), basis='b' * 64)
        media.snapshot = snapshot
        self.store.case_reader = lambda conn, row: self.fixture.capture.plan.binding.case
        with patch.dict(sys.modules, {'api.pc_configuration_copy': private, 'api.pc_media': media}):
            with self.store.transaction() as tx:
                result = tx.capture(113835, self.fixture.authority, self.fixture.authority.principal())
        self.assertEqual(result.plan.provenance.original_revision, 1)
        self.assertEqual(result.plan.binding.current_visual_basis, digest(body))
        self.assertEqual(calls, [(self.conn, 'P113835', True)])
        self.assertTrue(any('pg_advisory_xact_lock' in entry[0] for entry in self.conn.log))


if __name__ == '__main__': unittest.main()
