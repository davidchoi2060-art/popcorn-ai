"""Batch archive import: archive checks, provenance shape, idempotent apply. No real DB/GCS."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import import_pc_media_archive as m
from api.pc_existing_media_import import ObjectReceipt, Principal, ServerAuthority
from tools.register_existing_pc_media import BUCKET, Decision, MANIFEST_SHA as M

PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 64


def item(code=200001, raw=PNG, **over):
    value = dict(configuration_id=f'P{code}', generated_original=f'originals/P{code}.png',
                 original_sha256=hashlib.sha256(raw).hexdigest(), original_bytes=len(raw),
                 qa_notes=['케이스 전면 확인'], reused_from=None, reuse_exception=None,
                 db_configuration_revision=1, case_code='129552')
    value.update(over)
    return value


def binding(code=200001, visual='a' * 64):
    return dict(code=code, configuration_id=f'C{code}', offer_id=f'P{code}', revision=1,
                case_product_code=129552, visual_basis=visual, review_basis='b' * 64,
                snapshot={'parts': []}, mismatch=[])


class Result:
    def __init__(self, rows=(), rowcount=1): self.rows, self.rowcount = list(rows), rowcount
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def scalar(self): return self.rows[0] if self.rows else None


class FakeDB:
    """Minimal pc_media_jobs table keyed by job_id."""
    def __init__(self, operator=('owner', '활성'), suspend_after_insert=False):
        self.jobs, self.sql, self.operator = {}, [], operator
        self.suspend_after_insert = suspend_after_insert
    def begin(self): return self
    def connect(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def rollback(self): pass

    def execute(self, clause, params=None):
        sql, p = str(clause), params or {}
        self.sql.append(sql)
        if 'FROM admin_operators' in sql:
            return Result([dict(operator_id=p['o'], role=self.operator[0], status=self.operator[1])])
        if sql.startswith('INSERT INTO pc_media_jobs'):
            self.jobs[p['j']] = dict(job_id=p['j'], request_id=p['r'], configuration_id=p['id'],
                visual_basis=p['v'], status='running', selected=False, asset=None,
                origin_kind='existing_import', provenance=json.loads(p['p']), actor=p['a'])
            if self.suspend_after_insert: self.operator = ('owner', '정지')
            return Result()
        if 'WHERE request_id=:r' in sql:
            return Result([dict(j) for j in self.jobs.values() if j['request_id'] == p['r']])
        if sql.startswith("UPDATE pc_media_jobs SET status='ready'"):
            j = self.jobs[p['j']]
            if j['status'] == 'ready': return Result(rowcount=0)
            j.update(status='ready', asset=json.loads(p['a'])); return Result()
        if 'WHERE configuration_id=:id AND selected FOR UPDATE' in sql:
            return Result([dict(j) for j in self.jobs.values()
                           if j['configuration_id'] == p['id'] and j['selected']])
        if sql.startswith('UPDATE pc_media_jobs SET selected=false'):
            for j in self.jobs.values():
                if j['configuration_id'] == p['id']: j['selected'] = False
            return Result()
        if sql.startswith('UPDATE pc_media_jobs SET selected=true'):
            self.jobs[p['j']]['selected'] = True; return Result()
        raise AssertionError(sql)


class Objects:
    def __init__(self, during=None): self.calls, self.during = [], during
    def create_or_verify(self, job, raw):
        self.calls.append(job)
        if self.during: self.during()
        return ObjectReceipt(BUCKET, f'pc-configurations/{job}/representative.png',
                             hashlib.sha256(raw).hexdigest(), len(raw), '1')


class ArchiveChecks(unittest.TestCase):
    def test_good_item_passes(self):
        self.assertIsNone(m.archive_reason(item(), PNG))

    def test_rejections(self):
        cases = [(item(), None, '원본 파일 없음'), (item(), b'GIF89a' + PNG, 'PNG'),
                 (item(original_sha256='0' * 64), PNG, '해시'), (item(qa_notes=[]), PNG, 'QA'),
                 (item(reused_from='113838'), PNG, '재사용 원본'), (item(configuration_id='X1'), PNG, '상품번호'),
                 (item(db_configuration_revision=None), PNG, '차수')]
        for value, raw, word in cases:
            with self.subTest(word=word):
                self.assertIn(word, m.archive_reason(value, raw))

    def test_reuse_reference_comes_from_owner_decision_not_text(self):
        bare = m.provenance(item(reused_from='P113838'), M, binding())
        ref = 'ledger:docs/rights/pc-media-reuse-ledger.json#pc-media-reuse-20261009'
        self.assertEqual(bare['original']['reuse_exception_reference'], ref)
        self.assertEqual(bare['reuse_authority']['decision'], ref)
        self.assertEqual(len(bare['reuse_authority']['references']), 2)
        noted = m.provenance(item(reused_from='P113838', reuse_exception='같은 케이스'), M, binding())
        self.assertTrue(noted['original']['reuse_exception_reference'].endswith('/reuse_exception'))

    def test_request_id_is_stable_and_specific(self):
        a = m.request_id('f' * 64, 1, 'a' * 64)
        self.assertEqual(a, m.request_id('f' * 64, 1, 'a' * 64))
        self.assertNotEqual(a, m.request_id('f' * 64, 2, 'a' * 64))
        self.assertNotEqual(a, m.request_id('f' * 64, 1, 'b' * 64))

    def test_provenance_matches_0134_shape(self):
        p = m.provenance(item(), 'e' * 64, binding())
        self.assertEqual(p['version'], 'pc-media-existing-import-v1')
        o, c = p['original'], p['current_binding']
        for key in ('generation_model', 'generation_actor', 'generation_time', 'original_visual_basis',
                    'reused_from', 'reuse_exception_reference', 'ssd_facts_reference'):
            self.assertIsNone(o[key])
        self.assertEqual(len(o['qa_references']), 1)
        self.assertEqual(c['configuration_id'], 'C200001')
        self.assertEqual(c['visual_basis'], 'a' * 64)
        self.assertEqual(c['review_basis'], 'b' * 64)
        self.assertEqual(c['case_product_code'], 129552)


def auth():
    return ServerAuthority(reuse_verifier=m.owner_reuse_verifier, registration_verifier=m.owner_reuse_verifier,
                           operator_reader=lambda: dict(operator_id=1, role='owner'))


REV = ('revision', '구성 차수 변경(1→2)')
IMG = ('image_condition', '이미지 조건: 장착 CPU 쿨러 확인 필요')


class ReuseAuthority(unittest.TestCase):
    def subject(self, raw=PNG, mismatch=(), force=False, sha=M, value=None, skus=()):
        return m.reuse_subject(value or item(), raw, sha, dict(binding(), mismatch=list(mismatch)), force, skus)

    def test_ledger_decision_is_allowed(self):
        self.assertIs(m.owner_reuse_verifier(self.subject(), Principal(1, 'owner'), FakeDB()), Decision.ALLOW)

    def test_denials(self):
        cases = [(self.subject(raw=PNG + b'x'), Principal(1, 'owner'), FakeDB()),
                 (self.subject(mismatch=[IMG], force=True), Principal(1, 'owner'), FakeDB()),
                 (self.subject(sha='e' * 64), Principal(1, 'owner'), FakeDB()),
                 (self.subject(value=item(reused_from='P999999')), Principal(1, 'owner'), FakeDB())]
        for subject, principal, conn in cases:
            with self.subTest(subject=subject):
                self.assertIs(m.owner_reuse_verifier(subject, principal, conn), Decision.DENY)

    def test_reuse_inside_the_same_archive_is_allowed(self):
        s = self.subject(value=item(reused_from='P113838'), skus={'P113838', 'P200001'})
        self.assertIs(m.owner_reuse_verifier(s, Principal(1, 'owner'), FakeDB()), Decision.ALLOW)

    def test_withdrawal_ledger(self):
        base = json.loads(m.LEDGER.read_text(encoding='utf-8'))
        sha = item()['original_sha256']
        w = lambda **kw: dict(base, withdrawn=[dict(dict(decision='pc-media-reuse-20261009', reference='x'), **kw)])
        bad_scope = dict(base, decisions=[dict(base['decisions'][0], scope=dict(reused_from='any', forceable_mismatch=[]))])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'ledger.json'
            for body, expected in [(base, Decision.ALLOW),
                                   (w(product_code=200001, original_sha256=None), Decision.DENY),
                                   (w(product_code=200001, original_sha256=sha), Decision.DENY),
                                   (w(product_code=200002, original_sha256=None), Decision.ALLOW),
                                   (w(product_code=200001, original_sha256=None, decision='other'), Decision.ALLOW),
                                   (w(product_code='200001', original_sha256=None), Decision.DENY),
                                   (dict(base, decisions=[]), Decision.DENY), (bad_scope, Decision.DENY),
                                   ('not json', Decision.DENY)]:
                path.write_text(body if isinstance(body, str) else json.dumps(body), encoding='utf-8')
                with self.subTest(body=body), patch.object(m, 'LEDGER', path):
                    self.assertIs(m.owner_reuse_verifier(self.subject(), Principal(1, 'owner'), FakeDB()), expected)

    def test_repo_ledger_is_valid_and_pins_the_22_archive(self):
        found = m.ledger()
        self.assertEqual(set(found['decisions']), {M})
        self.assertEqual(found['withdrawn'], set())

    def test_operator_binding_is_separate(self):
        from api.pc_existing_media_import import Denied
        m.bind_operator(FakeDB(), Principal(1, 'owner'), 1)
        for principal, db, bound in [(Principal(1, 'operator'), FakeDB(), 1), (Principal(2, 'owner'), FakeDB(), 1),
                                     (Principal(1, 'owner'), FakeDB(operator=('owner', '정지')), 1),
                                     (Principal(1, 'owner'), FakeDB(operator=('operator', '활성')), 1)]:
            with self.subTest(principal=principal, operator=db.operator), self.assertRaises(Denied):
                m.bind_operator(db, principal, bound)

    def test_forced_revision_mismatch_is_allowed(self):
        s = self.subject(mismatch=[REV], force=True)
        self.assertIs(m.owner_reuse_verifier(s, Principal(1, 'owner'), FakeDB()), Decision.ALLOW)

    def test_selectable(self):
        self.assertEqual(m.selectable(binding(), False), 'auto')
        self.assertIsNone(m.selectable(dict(binding(), mismatch=[REV]), False))
        self.assertEqual(m.selectable(dict(binding(), mismatch=[REV, ('case', 'x')]), True), 'forced')
        self.assertIsNone(m.selectable(dict(binding(), mismatch=[REV, IMG]), True))


class Apply(unittest.TestCase):
    def setUp(self):
        self.db, self.objects = FakeDB(), Objects()
        env = patch.dict('os.environ', {'POPCORN_EXISTING_MEDIA_IMPORT_APPLY': '1'})
        env.start(); self.addCleanup(env.stop)

    def test_apply_switch_is_checked_at_the_write_entry(self):
        with patch.dict('os.environ', {'POPCORN_EXISTING_MEDIA_IMPORT_APPLY': '0'}), self.assertRaises(PermissionError):
            self.apply()
        self.assertEqual((self.db.jobs, self.objects.calls), ({}, []))

    def apply(self, b=None, reason=None, raw=PNG, **kw):
        with patch.object(m, 'current_binding', return_value=(b or binding(), reason)):
            return m.apply_one(self.db, self.objects, item(), raw, M, auth(), Principal(1, 'owner'), **kw)

    def test_registers_uploads_and_selects(self):
        state, job = self.apply()
        self.assertEqual(state, 'selected')
        row = self.db.jobs[job]
        self.assertEqual((row['status'], row['selected'], row['actor']), ('ready', True, 'operator:1'))
        self.assertEqual(row['provenance']['reuse_authority']['principal'], 'operator:1')
        self.assertEqual(row['asset']['key'], f'pc-configurations/{job}/representative.png')
        from api.pc_media import NOTICE
        self.assertEqual(row['asset']['notice'], NOTICE)

    def test_rerun_is_idempotent(self):
        first = self.apply()
        second = self.apply()
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(len(self.objects.calls), 1)

    def test_stale_binding_is_skipped_without_writes(self):
        self.assertEqual(self.apply(reason='케이스가 원본과 다름 · 확인 필요')[0], 'skipped')
        self.assertEqual(self.db.jobs, {})
        self.assertEqual(self.objects.calls, [])

    def test_keeps_current_selection_replaces_stale(self):
        self.db.jobs['old'] = dict(job_id='old', request_id='x', configuration_id='C200001',
            visual_basis='a' * 64, status='ready', selected=True, asset={}, origin_kind='generated')
        state, detail = self.apply()
        self.assertEqual(state, 'registered')
        self.assertTrue(self.db.jobs['old']['selected'])
        self.db, self.objects = FakeDB(), Objects()
        self.db.jobs['old'] = dict(job_id='old', request_id='x', configuration_id='C200001',
            visual_basis='z' * 64, status='ready', selected=True, asset={}, origin_kind='generated')
        state, job = self.apply()
        self.assertEqual(state, 'selected')
        self.assertFalse(self.db.jobs['old']['selected'])

    def test_mismatch_registers_without_selecting_unless_forced(self):
        b = dict(binding(), mismatch=[REV])
        state, detail = self.apply(b=b)
        self.assertEqual(state, 'registered_unselected')
        self.assertIn('구성 차수 변경', detail)
        self.assertFalse(any(j['selected'] for j in self.db.jobs.values()))
        state, job = self.apply(b=b, force_select=True)
        self.assertEqual(state, 'selected_by_decision')
        self.assertTrue(self.db.jobs[job]['selected'])

    def test_image_condition_is_never_forced(self):
        state, detail = self.apply(b=dict(binding(), mismatch=[IMG]), force_select=True)
        self.assertEqual(state, 'registered_unselected')
        self.assertFalse(any(j['selected'] for j in self.db.jobs.values()))

    def test_withdrawn_between_insert_and_upload_stops_before_upload(self):
        self.db = FakeDB(suspend_after_insert=True)
        state, detail = self.apply()
        self.assertEqual(state, 'stopped')
        self.assertIn('업로드 전 중단', detail)
        self.assertEqual(self.objects.calls, [])
        self.assertEqual([j['status'] for j in self.db.jobs.values()], ['running'])

    def test_withdrawn_during_upload_is_not_marked_ready(self):
        self.objects = Objects(during=lambda: setattr(self.db, 'operator', ('owner', '정지')))
        state, detail = self.apply()
        self.assertEqual(state, 'stopped')
        self.assertIn('완료 처리 전 중단', detail)
        self.assertEqual([(j['status'], j['selected']) for j in self.db.jobs.values()], [('running', False)])

    def test_withdrawn_before_selection_is_not_selected(self):
        calls = []
        real = m.owner_reuse_verifier
        def verifier(subject, principal, conn):
            calls.append(1)
            return real(subject, principal, conn) if len(calls) <= 6 else Decision.DENY
        with patch.object(m, 'owner_reuse_verifier', verifier):
            a = ServerAuthority(reuse_verifier=verifier, registration_verifier=verifier,
                                operator_reader=lambda: dict(operator_id=1, role='owner'))
            with patch.object(m, 'current_binding', return_value=(binding(), None)):
                state, detail = m.apply_one(self.db, self.objects, item(), PNG, M, a, Principal(1, 'owner'))
        self.assertEqual(state, 'registered_unselected')
        self.assertFalse(any(j['selected'] for j in self.db.jobs.values()))

    def test_other_manifest_writes_nothing(self):
        with patch.object(m, 'current_binding', return_value=(binding(), None)):
            result = m.apply_one(self.db, self.objects, item(), PNG, 'e' * 64, auth(), Principal(1, 'owner'))
        self.assertEqual(result, ('skipped', '재사용 권한 확인 거부'))
        self.assertEqual((self.db.jobs, self.objects.calls), ({}, []))

    def test_denied_authority_writes_nothing(self):
        self.db = FakeDB(operator=('owner', '정지'))
        self.assertEqual(self.apply(), ('skipped', '실행자 확인 거부'))
        self.assertEqual((self.db.jobs, self.objects.calls), ({}, []))

    def test_no_select_only_registers(self):
        state, job = self.apply(select=False)
        self.assertEqual(state, 'registered')
        self.assertFalse(self.db.jobs[job]['selected'])

    def test_basis_change_after_registration_is_not_reused(self):
        self.apply(select=False)
        state, reason = self.apply(b=binding(visual='c' * 64))
        self.assertEqual(state, 'skipped')
        self.assertIn('근거 변경', reason)


class Cli(unittest.TestCase):
    def test_apply_needs_env_and_operator(self):
        with tempfile.TemporaryDirectory() as d:
            for argv, env in [(['--archive', d, '--apply'], {'POPCORN_EXISTING_MEDIA_IMPORT_APPLY': '1'}),
                              (['--archive', d, '--apply', '--operator-id', '1'], {})]:
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    m.main(argv, environment=env)

    def test_dry_run_reports_without_writes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'originals').mkdir()
            good, missing, broken = item(200001), item(200002), item(200003)
            (Path(d) / 'originals' / 'P200001.png').write_bytes(PNG)
            (Path(d) / 'originals' / 'P200003.png').write_bytes(PNG + b'cut')
            (Path(d) / 'manifest.json').write_text(json.dumps(dict(items=[good, missing, broken])), encoding='utf-8')
            db, lines = FakeDB(), []
            pinned = hashlib.sha256((Path(d) / 'manifest.json').read_bytes()).hexdigest()
            with patch.object(m, 'current_binding', return_value=(binding(), None)), \
                    patch.object(m, 'authority', return_value=auth()):
                outside = m.run(d, engine=db, operator_id=1, out=lambda _: None)
                ledger = json.loads(m.LEDGER.read_text(encoding='utf-8'))
                ledger['decisions'][0]['manifest_sha256'] = pinned
                (Path(d) / 'ledger.json').write_text(json.dumps(ledger), encoding='utf-8')
                with patch.object(m, 'LEDGER', Path(d) / 'ledger.json'):
                    result = m.run(d, engine=db, operator_id=1, force_select=True, out=lines.append)
            self.assertEqual(outside['counts'], {'skipped': 1, 'file_error': 2})
            self.assertEqual(result['counts'], {'would_select': 1, 'file_error': 2})
            self.assertEqual(db.jobs, {})
            self.assertIn('manifest 3건', lines[-1])


if __name__ == '__main__':
    unittest.main()
