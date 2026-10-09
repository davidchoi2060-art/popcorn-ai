"""Bulk publication approval: read-only precheck before any write, first-time approvals
only, executor re-checked in every write transaction, per-step results. No real DB/GCS."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from tools import approve_pc_publication_bulk as m
from api import part_explanation_approval as part
from api import part_photo_approval as photo
from api import pc_configuration_review as review
from api import pc_customer_publication as publication
from api import pc_publication_source_reader as source

RIGHTS = m.RIGHTS_ATTESTATION
ENV = {m.APPLY_ENV: '1', m.RIGHTS_ENV: RIGHTS}
REFS = ['project-chat:cmsg_A', 'manifest:sha256:' + 'b' * 64]
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
        if 'FROM part_photo_approval_events' in sql:
            return Rows([dict(total=0, same=0)])
        if 'FROM admin_operators' in sql:
            if 'FOR SHARE' in sql:
                self.db.guards += 1
                if self.db.stop_after is not None and self.db.guards > self.db.stop_after:
                    self.db.operator = dict(OWNER, status='정지')
            return Rows([self.db.operator])
        if 'FROM pc_media_jobs' in sql or 'FROM pc_configurations' in sql:
            return Rows([(i,) for i in self.db.configs])
        if 'FROM pc_configuration_parts' in sql:
            return Rows([(c,) for c in self.db.parts[params['id']]])
        raise AssertionError(sql)


class Rows:
    def __init__(self, rows): self.rows = rows
    def __iter__(self): return iter(self.rows)
    def mappings(self): return self
    def first(self): return self.rows[0] if self.rows else None


class DB:
    def __init__(self, configs=('C1', 'C2'), parts=None, operator=OWNER, stop_after=None):
        self.configs, self.operator, self.isolation = list(configs), dict(operator), []
        self.parts = parts or {'C1': [101, 102], 'C2': [102, 103]}
        self.guards, self.stop_after = 0, stop_after
    def connect(self): return Conn(self)


class World:
    """Approval state the patched module functions read and write."""
    def __init__(self):
        self.explained, self.photographed, self.reviewed, self.published = set(), set(), set(), set()
        self.hold, self.blocked_photo, self.missing, self.calls = set(), set(), set(), []
        self.part_state, self.photo_state, self.review_state, self.pub_state = {}, {}, {}, {}
        self.legacy, self.fail_part, self.extra_required = set(), {}, {}

    def patches(self):
        w = self
        row = lambda code: dict(source_product_code=code, product_code=code,
                                approved_by=7 if code in w.legacy else None,
                                approved_at='2026-09-01T10:00:00+09:00' if code in w.legacy else None,
                                content=dict(image_asset=dict(bucket='b', detail_key=f'products/{code}/x/detail.png')))
        def read(c, code, lock=False):
            if code in w.missing:
                raise HTTPException(404, 'part_approval_explanation_missing')
            return row(code)
        def cur(code, done, states):
            state, seq = states.get(code, ('approved', 1) if code in done else ('unapproved', 0))
            return dict(allowed=state == 'approved', state=state, event_seq=seq,
                        reason=None if state in ('approved', 'unapproved') else f'{state}_reason',
                        operator_id=9 if seq else None, approved_at='2026-09-02' if seq else None)
        def review_state(conn, identity, lock=False):
            approved = identity in w.reviewed
            saved, prior = w.review_state.get(identity, (None, None))
            required = {'copy': '설명', 'price': '가격'} | w.extra_required.get(identity, {})
            return None, None, None, dict(
                state='approved' if approved else (saved or 'pending'), revision=3, basis='r' * 64,
                blockers=['소켓 · 현재 DB 사양 불일치'] if identity in w.hold else [],
                recommendation_state='hold' if identity in w.hold else 'ready', required=required,
                approved_by=prior, approved_at='2026-09-03' if prior else None, prior_review=None)
        def save(conn, identity, body, actor):
            w.calls.append(('review', identity, {k: v.evidence for k, v in body.findings.items()}, actor['operator_id']))
            w.reviewed.add(identity)
        def pub_current(conn, identity, source_reader=None):
            c = cur(identity, w.published, w.pub_state)
            ok = identity in w.reviewed
            return dict(c, revision=4, basis='r' * 64, publication_basis='p' * 64 if ok else None,
                        reason=c['reason'] or (None if ok else 'publication_recommendation_not_current'))
        def pub(conn, identity, **kw):
            w.calls.append(('publish', identity, kw['expected_seq'], kw['actor']['operator_id'])); w.published.add(identity)
        def part_approve(conn, code, **kw):
            if code in w.fail_part:
                raise HTTPException(*w.fail_part[code])
            w.calls.append(('explain', code, kw['expected_seq'], kw['request_id'])); w.explained.add(code)
        def photo_approve(conn, code, **kw):
            proof = kw['provenance_reader'](conn, row=row(code), expected_basis='q' * 64)
            w.calls.append(('photo', code, proof.rights_reference, proof.source_reference)); w.photographed.add(code)
        return [
            patch.object(part, 'read_current', lambda c, code: cur(code, w.explained, w.part_state)),
            patch.object(part, '_read', read),
            patch.object(part, '_source_reason', lambda r: None),
            patch.object(part, 'basis', lambda r: 'e' * 64),
            patch.object(part, 'approve', part_approve),
            patch.object(photo, 'read_current', lambda c, code, **kw: cur(code, w.photographed, w.photo_state)),
            patch.object(photo, '_model_reason', lambda r: 'photo_model_missing_or_stale' if r['source_product_code'] in w.blocked_photo else None),
            patch.object(photo, '_asset_reason', lambda a, c: None),
            patch.object(photo, '_model', lambda r: r['content']),
            patch.object(photo, 'basis', lambda r: 'q' * 64),
            patch.object(photo, 'approve', photo_approve),
            patch.object(review, 'load_review', review_state),
            patch.object(review, 'save_review', save),
            patch.object(publication, 'read_current', pub_current),
            patch.object(publication, 'approve', pub),
            patch.object(source, 'make_source_reader', lambda **kw: object()),
        ]


def go(world, db=None, apply=False, **kw):
    lines = []
    if apply:
        kw = dict(dict(operator_id=1, references=REFS, environment=ENV), **kw)
    for p in world.patches(): p.start()
    try:
        kw.setdefault('note', '중헌 승인: 104개 구성 발행 승인')
        result = m.run(db or DB(), apply=apply, rights=RIGHTS, image_reader=lambda *a: b'', out=lines.append, **kw)
    finally:
        patch.stopall()
    return result, lines


def by_id(result, identity):
    return next(r for r in result['configurations'] if r['configuration_id'] == identity)


class Bulk(unittest.TestCase):
    def test_dry_run_writes_nothing_and_reports(self):
        w = World()
        result, _ = go(w)
        self.assertEqual(w.calls, [])
        s = result['summary']
        self.assertEqual((s['configurations'], s['parts'], s['photos']), (2, {'ready': 3}, {'ready': 3}))
        self.assertEqual((s['precheck'], s['review']), ({'ok': 2}, {'would_approve': 2}))
        self.assertEqual(s['publication'], {'after_previous_steps': 2})
        self.assertEqual(result['shared_parts'], {'102': ['C1', 'C2']})

    def test_apply_runs_four_steps_in_order_once_per_part(self):
        w = World()
        result, _ = go(w, apply=True)
        kinds = [c[0] for c in w.calls]
        self.assertEqual(kinds, ['explain', 'explain', 'photo', 'photo', 'review', 'publish',
                                 'explain', 'photo', 'review', 'publish'])
        self.assertEqual(result['summary']['part_writes'], {'committed': 3})
        self.assertEqual(result['summary']['publication'], {'committed': 2})
        self.assertTrue(all(c[2] == 0 for c in w.calls if c[0] in ('explain', 'publish')))
        photo_call = next(c for c in w.calls if c[0] == 'photo')
        self.assertEqual(photo_call[2:], (RIGHTS, 'gcs:b/products/101/x/detail.png'))
        self.assertEqual(by_id(result, 'C2')['steps']['parts'], {102: ('committed', None), 103: ('committed', None)})

    def test_review_evidence_is_per_configuration_and_only_copy_price(self):
        w = World()
        go(w, apply=True)
        evidence = next(c for c in w.calls if c[:2] == ('review', 'C1'))[2]
        self.assertEqual(set(evidence), {'copy', 'price'})
        for text in evidence.values():
            for needle in ('구성 C1', '차수 3', 'r' * 64, *REFS, RIGHTS):
                self.assertIn(needle, text)
        w = World(); w.extra_required['C1'] = {'cooler:1:2': '쿨러 · 추천 전 근거 확인'}
        result, _ = go(w, apply=True)
        self.assertEqual(by_id(result, 'C1')['precheck'][0], 'blocked')
        self.assertNotIn('C1', {c[1] for c in w.calls if c[0] in ('review', 'publish')})

    def test_rerun_skips_already_approved(self):
        w = World()
        go(w, apply=True)
        w.calls.clear()
        result, _ = go(w, apply=True)
        self.assertEqual(w.calls, [])
        self.assertEqual(result['summary']['publication'], {'already': 2})

    def test_hold_is_found_before_any_part_or_photo_write(self):
        w = World(); w.hold.add('C1')
        result, _ = go(w, apply=True)
        touched = {c[1] for c in w.calls}
        self.assertNotIn(101, touched)           # only C1 uses 101: never written
        self.assertNotIn('C1', touched)
        c1 = by_id(result, 'C1')
        self.assertEqual(c1['precheck'][0], 'hold')
        self.assertIn('소켓', c1['precheck'][1])
        self.assertEqual(c1['steps']['parts'], {})
        self.assertEqual(by_id(result, 'C2')['publication'][0], 'committed')

    def test_revoked_stale_or_legacy_is_never_reapproved(self):
        cases = [('part_state', 101, ('revoked', 2)), ('part_state', 101, ('stale', 1)),
                 ('part_state', 101, ('draft', 1)), ('photo_state', 101, ('stale', 1)),
                 ('photo_state', 101, ('unknown', 1)), ('pub_state', 'C1', ('revoked', 3)),
                 ('review_state', 'C1', ('revoked', dict(operator_id=7))),
                 ('review_state', 'C1', ('stale', dict(operator_id=7))), ('legacy', 101, None)]
        for attr, key, value in cases:
            with self.subTest(attr=attr, value=value):
                w = World()
                if attr == 'legacy':
                    w.legacy.add(key)
                else:
                    getattr(w, attr)[key] = value
                result, _ = go(w, apply=True)
                c1 = by_id(result, 'C1')
                self.assertEqual(c1['precheck'][0], 'needs_explicit_reapproval')
                self.assertNotIn(101, {c[1] for c in w.calls})
                self.assertNotIn('C1', {c[1] for c in w.calls})
                self.assertEqual(by_id(result, 'C2')['publication'][0], 'committed')
        w = World(); w.legacy.add(101)
        result, _ = go(w)
        self.assertEqual(by_id(result, 'C1')['part_prior'][101]['approved_by'], 7)

    def test_new_request_id_cannot_bypass_revocation(self):
        w = World(); w.part_state[101] = ('revoked', 2)
        with patch.object(m, 'rid', lambda *a: '00000000-0000-4000-8000-000000000001'):
            go(w, apply=True, note='다른 승인 문장으로 다시 실행')
        self.assertNotIn(101, {c[1] for c in w.calls})

    def test_owner_stopped_between_steps_stops_the_batch(self):
        w = World()
        db = DB(stop_after=3)   # explain 101, explain 102, photo 101 commit; then the owner is stopped
        result, _ = go(w, db=db, apply=True)
        self.assertEqual([c[0] for c in w.calls], ['explain', 'explain', 'photo'])
        self.assertTrue(result['summary']['stopped'])
        self.assertEqual(by_id(result, 'C1')['precheck'][0], 'stopped')
        self.assertEqual(by_id(result, 'C2')['precheck'][0], 'not_run')

    def test_owner_rechecked_right_before_review_and_publication(self):
        for stop_after, done in [(4, ['explain', 'explain', 'photo', 'photo']),
                                 (5, ['explain', 'explain', 'photo', 'photo', 'review'])]:
            with self.subTest(stop_after=stop_after):
                w = World()
                result, _ = go(w, db=DB(stop_after=stop_after), apply=True)
                self.assertEqual([c[0] for c in w.calls], done)
                self.assertEqual(by_id(result, 'C1')['precheck'][0], 'stopped')

    def test_partial_failure_is_recorded_per_step(self):
        w = World(); w.fail_part[103] = (503, 'part_approval_metadata_write_mismatch')
        result, _ = go(w, apply=True)
        c1, c2 = by_id(result, 'C1'), by_id(result, 'C2')
        self.assertEqual(c1['publication'][0], 'committed')
        self.assertEqual(c2['steps']['parts'][102], ('committed', None))
        self.assertEqual(c2['steps']['parts'][103], ('failed', 'part_approval_metadata_write_mismatch'))
        self.assertEqual(c2['steps']['photos'], {})
        self.assertEqual((c2['review'][0], c2['publication'][0]), ('not_run', 'not_attempted'))

    def test_request_digest_conflict_is_reported_not_retried(self):
        w = World(); w.fail_part[101] = (409, 'part_approval_request_conflict')
        result, _ = go(w, apply=True)
        self.assertEqual(by_id(result, 'C1')['steps']['parts'][101], ('failed', 'part_approval_request_conflict'))
        self.assertEqual(result['summary']['part_writes'], {'failed': 1, 'committed': 2})

    def test_missing_explanation_is_reported_and_skipped(self):
        w = World(); w.missing.add(101)
        result, _ = go(w, apply=True)
        c1 = by_id(result, 'C1')
        self.assertEqual(c1['precheck'], ('missing', '설명 없음 1건'))
        self.assertNotIn(101, w.photographed)
        db = DB(parts={'C1': [101, None], 'C2': [103]}); w = World()
        result, _ = go(w, db=db, apply=True)
        self.assertEqual(by_id(result, 'C1')['unlinked_parts'], 1)
        self.assertEqual(by_id(result, 'C1')['publication'][0], 'not_attempted')
        self.assertNotIn(101, {c[1] for c in w.calls})

    def test_publication_uses_repeatable_read(self):
        db = DB()
        go(World(), db=db, apply=True)
        self.assertIn('REPEATABLE READ', db.isolation)

    def test_direct_run_is_guarded(self):
        for kw in [dict(environment={}), dict(environment={m.APPLY_ENV: '1'}),
                   dict(environment=dict(ENV, **{m.RIGHTS_ENV: 'workroom:x@v1:' + 'a' * 64})),
                   dict(references=()), dict(operator_id=None)]:
            with self.subTest(kw=kw), self.assertRaises(PermissionError):
                go(World(), apply=True, **kw)
        with self.assertRaises(PermissionError):
            go(World(), db=DB(operator=dict(OWNER, role='operator')), apply=True)
        w = World()
        with patch.dict(m.os.environ, {}, clear=True), self.assertRaises(m.Stop):
            m.Batch(DB(), apply=False, operator_id=1, rights=RIGHTS, image_reader=lambda *a: b'').guard(Conn(DB()))

    def test_rights_line(self):
        for p in World().patches(): p.start()
        try:
            self.assertIn('미설정', m.rights_line(DB(), None))
            self.assertIn('형식 불일치', m.rights_line(DB(), 'workroom:x@v1:short'))
            self.assertIn('형식 일치', m.rights_line(DB(), RIGHTS))
        finally:
            patch.stopall()

    def test_targets_option(self):
        result, _ = go(World(), only=['C2'])
        self.assertEqual([r['configuration_id'] for r in result['configurations']], ['C2'])


class Cli(unittest.TestCase):
    def test_apply_guards(self):
        base = ['--apply', '--operator-id', '1', '--approval-note', '중헌 승인 문장 그대로 기록',
                '--approval-reference', REFS[0]]
        other = 'workroom:x@v1:' + 'a' * 64
        for argv, env in [(base, {m.RIGHTS_ENV: RIGHTS}), (base, {m.APPLY_ENV: '1'}),
                          (base, dict(ENV, **{m.RIGHTS_ENV: other})), (base[:3], ENV),
                          (base[:1] + base[3:], ENV), (base[:5], ENV),
                          (base[:6] + ['has space'], ENV)]:
            with self.subTest(argv=argv, env=sorted(env.items())), self.assertRaises(SystemExit):
                m.main(argv, environment=env)


if __name__ == '__main__':
    unittest.main()
