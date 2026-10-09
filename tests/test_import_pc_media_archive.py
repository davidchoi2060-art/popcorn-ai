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
from api.pc_existing_media_import import ObjectReceipt
from tools.register_existing_pc_media import BUCKET

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
    def __init__(self): self.jobs, self.sql = {}, []
    def begin(self): return self
    def connect(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def rollback(self): pass

    def execute(self, clause, params=None):
        sql, p = str(clause), params or {}
        self.sql.append(sql)
        if sql.startswith('INSERT INTO pc_media_jobs'):
            self.jobs[p['j']] = dict(job_id=p['j'], request_id=p['r'], configuration_id=p['id'],
                visual_basis=p['v'], status='running', selected=False, asset=None,
                origin_kind='existing_import', provenance=json.loads(p['p']), actor=p['a'])
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
    def __init__(self): self.calls = []
    def create_or_verify(self, job, raw):
        self.calls.append(job)
        return ObjectReceipt(BUCKET, f'pc-configurations/{job}/representative.png',
                             hashlib.sha256(raw).hexdigest(), len(raw), '1')


class ArchiveChecks(unittest.TestCase):
    def test_good_item_passes(self):
        self.assertIsNone(m.archive_reason(item(), PNG))

    def test_rejections(self):
        cases = [(item(), None, '원본 파일 없음'), (item(), b'GIF89a' + PNG, 'PNG'),
                 (item(original_sha256='0' * 64), PNG, '해시'), (item(qa_notes=[]), PNG, 'QA'),
                 (item(reused_from='P113838'), PNG, '재사용 근거'), (item(configuration_id='X1'), PNG, '상품번호'),
                 (item(db_configuration_revision=None), PNG, '차수')]
        for value, raw, word in cases:
            with self.subTest(word=word):
                self.assertIn(word, m.archive_reason(value, raw))

    def test_reuse_with_recorded_exception_is_allowed(self):
        value = item(reused_from='P113838', reuse_exception='같은 케이스·색상')
        self.assertIsNone(m.archive_reason(value, PNG))
        o = m.provenance(value, 'e' * 64, binding())['original']
        self.assertEqual(o['reused_from'], 'P113838')
        self.assertTrue(o['reuse_exception_reference'].endswith('/reuse_exception'))

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


class Apply(unittest.TestCase):
    def setUp(self):
        self.db, self.objects = FakeDB(), Objects()

    def apply(self, b=None, reason=None, **kw):
        with patch.object(m, 'current_binding', return_value=(b or binding(), reason)):
            return m.apply_one(self.db, self.objects, item(), PNG, 'e' * 64, 'operator:1', **kw)

    def test_registers_uploads_and_selects(self):
        state, job = self.apply()
        self.assertEqual(state, 'selected')
        row = self.db.jobs[job]
        self.assertEqual((row['status'], row['selected'], row['actor']), ('ready', True, 'operator:1'))
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
        b = dict(binding(), mismatch=['구성 차수 변경(1→2)'])
        state, detail = self.apply(b=b)
        self.assertEqual(state, 'registered_unselected')
        self.assertIn('구성 차수 변경', detail)
        self.assertFalse(any(j['selected'] for j in self.db.jobs.values()))
        state, job = self.apply(b=b, force_select=True)
        self.assertEqual(state, 'selected')
        self.assertTrue(self.db.jobs[job]['selected'])

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
            good, missing = item(200001), item(200002)
            (Path(d) / 'originals' / 'P200001.png').write_bytes(PNG)
            (Path(d) / 'manifest.json').write_text(json.dumps(dict(items=[good, missing])), encoding='utf-8')
            db, lines = FakeDB(), []
            with patch.object(m, 'current_binding', return_value=(binding(), None)):
                result = m.run(d, engine=db, out=lines.append)
            self.assertEqual(result['counts'], {'would_select': 1, 'skipped': 1})
            self.assertEqual(db.jobs, {})
            self.assertIn('manifest 2건', lines[-1])


if __name__ == '__main__':
    unittest.main()
