"""Bulk publication approval: step order, hold/skip rules, dry-run writes nothing. No real DB/GCS."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import approve_pc_publication_bulk as m
from api import part_explanation_approval as part
from api import part_photo_approval as photo
from api import pc_configuration_review as review
from api import pc_customer_publication as publication
from api import pc_publication_source_reader as source

RIGHTS = 'workroom:docs/rights/part-photo-rights.md@v1:' + 'a' * 64
OWNER = dict(operator_id=1, name='중헌', role='owner', status='활성')


class Conn:
    def __init__(self, db): self.db = db
    def begin(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def close(self): pass
    def execution_options(self, **kw): self.db.isolation.append(kw.get('isolation_level')); return self

    def execute(self, clause, params=None):
        sql = str(clause)
        if 'FROM admin_operators' in sql:
            return Rows([self.db.operator])
        if 'FROM pc_media_jobs' in sql or 'FROM pc_configurations' in sql:
            return Rows([(i,) for i in self.db.configs])
        if 'FROM pc_configuration_parts' in sql:
            assert 'IS NOT NULL' not in sql
            return Rows([(c,) for c in self.db.parts[params['id']]])
        raise AssertionError(sql)


class Rows:
    def __init__(self, rows): self.rows = rows
    def __iter__(self): return iter(self.rows)
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None


class DB:
    def __init__(self, configs=('C1', 'C2'), parts=None, operator=OWNER):
        self.configs, self.operator, self.isolation = list(configs), operator, []
        self.parts = parts or {'C1': [101, 102], 'C2': [102, 103]}
    def connect(self): return Conn(self)


class World:
    """Approval state the patched module functions read and write."""
    def __init__(self):
        self.explained, self.photographed, self.reviewed, self.published = set(), set(), set(), set()
        self.hold, self.blocked_photo, self.missing, self.calls = set(), set(), set(), []

    def patches(self):
        w = self
        row = lambda code: dict(source_product_code=code, product_code=code,
                                content=dict(image_asset=dict(bucket='b', detail_key=f'products/{code}/x/detail.png')))
        def missing(code):
            if code in w.missing:
                from fastapi import HTTPException
                raise HTTPException(404, 'part_approval_explanation_missing')
        def review_state(conn, identity, lock=False):
            approved = identity in w.reviewed
            return None, None, None, dict(state='approved' if approved else 'pending', revision=3, basis='r' * 64,
                blockers=['소켓 · 현재 DB 사양 불일치'] if identity in w.hold else [],
                recommendation_state='hold' if identity in w.hold else 'ready',
                required={'copy': '설명', 'price': '가격'})
        def save(conn, identity, body, actor):
            w.calls.append(('review', identity, body.action, sorted(body.findings), actor['operator_id']))
            w.reviewed.add(identity)
        def pub_current(conn, identity, source_reader=None):
            ok = identity in w.reviewed
            return dict(allowed=identity in w.published, event_seq=0, revision=4, basis='r' * 64,
                        publication_basis='p' * 64 if ok else None, reason=None if ok else 'publication_recommendation_not_current')
        def pub(conn, identity, **kw):
            w.calls.append(('publish', identity, kw['note'])); w.published.add(identity)
        def part_approve(conn, code, **kw):
            w.calls.append(('explain', code, kw['note'])); w.explained.add(code)
        def photo_approve(conn, code, **kw):
            proof = kw['provenance_reader'](conn, row=row(code), expected_basis='q' * 64)
            w.calls.append(('photo', code, proof.rights_reference, proof.source_reference)); w.photographed.add(code)
        return [
            patch.object(part, 'read_current', lambda c, code: dict(allowed=code in w.explained, event_seq=0, state='unapproved', reason=None)),
            patch.object(part, '_read', lambda c, code, lock=False: missing(code) or row(code)),
            patch.object(part, '_source_reason', lambda r: None),
            patch.object(part, 'basis', lambda r: 'e' * 64),
            patch.object(part, 'approve', part_approve),
            patch.object(photo, 'read_current', lambda c, code, **kw: dict(allowed=code in w.photographed, event_seq=0, reason=None)),
            patch.object(photo, '_model_reason', lambda r: 'photo_model_missing_or_stale' if r['source_product_code'] in w.blocked_photo else None),
            patch.object(photo, '_asset_reason', lambda a, c: None),
            patch.object(photo, 'basis', lambda r: 'q' * 64),
            patch.object(photo, 'approve', photo_approve),
            patch.object(review, 'load_review', review_state),
            patch.object(review, 'save_review', save),
            patch.object(publication, 'read_current', pub_current),
            patch.object(publication, 'approve', pub),
            patch.object(source, 'make_source_reader', lambda **kw: object()),
        ]


def go(world, db=None, **kw):
    lines = []
    for p in world.patches(): p.start()
    try:
        result = m.run(db or DB(), rights=RIGHTS, note='중헌 승인: 104개 구성 발행 승인', image_reader=lambda *a: b'',
                       out=lines.append, **kw)
    finally:
        patch.stopall()
    return result, lines


class Bulk(unittest.TestCase):
    def test_dry_run_writes_nothing_and_reports(self):
        w = World()
        result, lines = go(w)
        self.assertEqual(w.calls, [])
        s = result['summary']
        self.assertEqual((s['configurations'], s['parts'], s['photos']), (2, {'would_approve': 3}, {'would_approve': 3}))
        self.assertEqual(s['review'], {'would_approve': 2})
        self.assertEqual(s['publication'], {'after_previous_steps': 2})

    def test_apply_runs_four_steps_in_order_once_per_part(self):
        w = World()
        result, _ = go(w, apply=True, operator_id=1)
        kinds = [c[0] for c in w.calls]
        self.assertEqual(kinds, ['explain', 'explain', 'photo', 'photo', 'review', 'publish',
                                 'explain', 'photo', 'review', 'publish'])
        self.assertEqual(result['summary']['parts'], {'approved': 3})
        self.assertEqual(result['summary']['publication'], {'approved': 2})
        photo_call = next(c for c in w.calls if c[0] == 'photo')
        self.assertEqual(photo_call[2], RIGHTS)
        self.assertEqual(photo_call[3], 'gcs:b/products/101/x/detail.png')
        self.assertEqual(next(c for c in w.calls if c[0] == 'review')[3], ['copy', 'price'])

    def test_rerun_skips_already_approved(self):
        w = World()
        go(w, apply=True, operator_id=1)
        w.calls.clear()
        result, _ = go(w, apply=True, operator_id=1)
        self.assertEqual(w.calls, [])
        self.assertEqual(result['summary']['publication'], {'already': 2})

    def test_hold_configuration_is_reported_not_touched(self):
        w = World(); w.hold.add('C1')
        result, lines = go(w, apply=True, operator_id=1)
        self.assertNotIn(('review', 'C1'), [c[:2] for c in w.calls])
        self.assertNotIn(('publish', 'C1'), [c[:2] for c in w.calls])
        c1 = next(r for r in result['configurations'] if r['configuration_id'] == 'C1')
        self.assertEqual(c1['review'][0], 'hold')
        self.assertIn('소켓', c1['review'][1])
        self.assertEqual(result['summary']['review'], {'hold': 1, 'approved': 1})

    def test_blocked_photo_stops_that_configuration_only(self):
        w = World(); w.blocked_photo.add(101)
        result, _ = go(w, apply=True, operator_id=1)
        c1, c2 = result['configurations']
        self.assertEqual((c1['review'][0], c1['publication'][0]), ('after_previous_steps', 'not_attempted'))
        self.assertEqual(c2['publication'][0], 'approved')
        self.assertIn(101, c1['photo_issues'])

    def test_missing_explanation_is_reported_and_skipped(self):
        w = World(); w.missing.add(101)
        result, _ = go(w, apply=True, operator_id=1)
        c1 = result['configurations'][0]
        self.assertEqual(c1['review'], ('after_previous_steps', '설명 없음 1건'))
        self.assertNotIn(101, w.photographed)
        self.assertEqual(result['summary']['parts'], {'missing': 1, 'approved': 2})
        db = DB(parts={'C1': [101, None], 'C2': [103]}); w = World()
        result, _ = go(w, db=db, apply=True, operator_id=1)
        self.assertEqual(result['configurations'][0]['unlinked_parts'], 1)
        self.assertEqual(result['configurations'][0]['publication'][0], 'not_attempted')

    def test_publication_uses_repeatable_read(self):
        db = DB()
        go(World(), db=db, apply=True, operator_id=1)
        self.assertIn('REPEATABLE READ', db.isolation)

    def test_non_owner_is_refused(self):
        with self.assertRaises(PermissionError):
            go(World(), db=DB(operator=dict(OWNER, role='operator')), apply=True, operator_id=1)

    def test_targets_option(self):
        result, _ = go(World(), only=['C2'])
        self.assertEqual([r['configuration_id'] for r in result['configurations']], ['C2'])


class Cli(unittest.TestCase):
    def test_apply_guards(self):
        ok = {m.APPLY_ENV: '1', m.RIGHTS_ENV: RIGHTS}
        base = ['--apply', '--operator-id', '1', '--approval-note', '중헌 승인 문장 그대로 기록']
        for argv, env in [(base, {m.RIGHTS_ENV: RIGHTS}), (base, {m.APPLY_ENV: '1'}),
                          (base, {m.APPLY_ENV: '1', m.RIGHTS_ENV: 'workroom:x@v1:short'}),
                          (base[:3], ok), (base[:1] + base[3:], ok)]:
            with self.subTest(argv=argv, env=sorted(env)), self.assertRaises(SystemExit):
                m.main(argv, environment=env)


if __name__ == '__main__':
    unittest.main()
