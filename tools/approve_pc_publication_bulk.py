"""Bulk-approve customer publication for assembled PCs: part explanation -> part photo
-> configuration recommendation review -> publication, in that order.

Every step goes through the existing approval module, never a direct UPDATE:
  1. part explanation   api.part_explanation_approval.approve (per distinct part)
  2. part photo         api.part_photo_approval.approve; provenance records
                        rights_reference = POPCORN_PART_PHOTO_RIGHTS_REFERENCE
                        (docs/rights/part-photo-rights.md) and the private-bucket
                        detail image as source_reference; current bytes are re-read
  3. recommendation     api.pc_configuration_review.save_review(action='approve').
                        A configuration on hold or with blockers is NOT touched;
                        it is counted and its reasons reported
  4. publication        api.pc_customer_publication.approve with the native
                        source reader, in a REPEATABLE READ transaction

Targets: configurations with a selected, ready representative image (registered
by tools/import_pc_media_archive.py). --all takes every configuration with a sold
P offer. --only limits to configuration ids.

Default is a read-only dry run that reports what each step would do. --apply
needs POPCORN_PUBLICATION_BULK_APPROVE_APPLY=1, POPCORN_PART_PHOTO_RIGHTS_REFERENCE,
--operator-id of an active owner and --approval-note (the owner's approval line;
recorded as the note of every event and as the evidence of review findings).
Re-running is safe: approved steps are skipped and request ids are derived from
the bound basis. Each configuration runs in its own transactions; one failure is
reported and the batch continues.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = UUID('0d6c3b2a-8e41-4f7a-b5c9-6a2e1f04d873')
APPLY_ENV = 'POPCORN_PUBLICATION_BULK_APPROVE_APPLY'
RIGHTS_ENV = 'POPCORN_PART_PHOTO_RIGHTS_REFERENCE'


def rid(*parts):
    return str(uuid5(NAMESPACE, ':'.join(str(p) for p in parts)))


def targets(conn, all_configs=False, only=()):
    from sqlalchemy import text
    if all_configs:
        sql = '''SELECT DISTINCT c.configuration_id FROM pc_configurations c
            JOIN pc_configuration_offers o USING(configuration_id)
            JOIN products p ON o.offer_id ~ '^P[1-9][0-9]*$' AND p.product_code=substring(o.offer_id FROM 2)::bigint
            WHERE c.status<>'retired' AND p.status='판매중' ORDER BY 1'''
    else:
        sql = '''SELECT DISTINCT j.configuration_id FROM pc_media_jobs j JOIN pc_configurations c USING(configuration_id)
            WHERE j.selected AND j.status='ready' AND c.status<>'retired' ORDER BY 1'''
    ids = [r[0] for r in conn.execute(text(sql))]
    return [i for i in ids if not only or i in only]


def owner(conn, operator_id):
    from sqlalchemy import text
    row = conn.execute(text('SELECT operator_id,name,role,status FROM admin_operators WHERE operator_id=:o'),
                       dict(o=operator_id)).mappings().first()
    if not row or row['role'] != 'owner' or row['status'] != '활성':
        raise PermissionError('활성 owner 계정만 적용할 수 있습니다')
    return dict(row)


def photo_reader(rights):
    """Server provenance for a registered product photo: the private-bucket detail
    image this row points at, under the business rights reference."""
    from api import part_photo_approval as photo

    def provenance(conn, *, row, expected_basis):
        asset = row['content']['image_asset']
        return photo.PhotoProvenance(row['source_product_code'], row['product_code'], expected_basis, photo.SCOPE,
                                     f"gcs:{asset['bucket']}/{asset['detail_key']}", rights)
    return provenance


def _tx(engine, repeatable=False):
    conn = engine.connect()
    if repeatable:
        conn = conn.execution_options(isolation_level='REPEATABLE READ')
    return conn


class Batch:
    def __init__(self, engine, *, apply=False, actor=None, note='', rights=None, image_reader=None, out=print):
        self.engine, self.apply, self.actor, self.note = engine, apply, actor, note
        self.rights, self.out = rights, out
        if image_reader is None:
            from api.product_images import read_image as image_reader
        self.image_reader = image_reader
        self.parts, self.photos = {}, {}       # code -> (state, detail), shared across configurations

    # 1. part explanation -------------------------------------------------
    def part(self, code):
        if code in self.parts:
            return self.parts[code]
        from api import part_explanation_approval as part
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                cur = part.read_current(conn, code)
                row = part._read(conn, code)
                reason = None if cur['allowed'] else part._source_reason(row)
                if cur['allowed']:
                    result = ('already', None)
                elif reason:
                    result = ('blocked', reason)
                elif not self.apply:
                    result = ('would_approve', cur['state'])
                else:
                    part.approve(conn, code, expected_seq=cur['event_seq'], expected_basis=part.basis(row),
                                 request_id=rid('explain', code, part.basis(row)), note=self.note, actor=self.actor)
                    result = ('approved', None)
        except HTTPException as error:
            result = ('missing' if error.status_code == 404 else 'failed', error.detail)
        finally:
            conn.close()
        self.parts[code] = result
        return result

    # 2. part photo ---------------------------------------------------------
    def photo(self, code):
        if code in self.photos:
            return self.photos[code]
        from api import part_explanation_approval as part
        from api import part_photo_approval as photo
        from fastapi import HTTPException
        reader = photo_reader(self.rights)
        conn = _tx(self.engine)
        try:
            with conn.begin():
                cur = photo.read_current(conn, code, provenance_reader=reader, image_reader=self.image_reader,
                                         business_rights_reference=self.rights)
                row = part._read(conn, code)
                reason = photo._model_reason(row) or photo._asset_reason(photo._model(row)['image_asset'], code)
                if cur['allowed']:
                    result = ('already', None)
                elif reason:
                    result = ('blocked', reason)
                elif not self.apply:
                    result = ('would_approve', cur['reason'])
                else:
                    basis = photo.basis(row)
                    photo.approve(conn, code, expected_seq=cur['event_seq'], expected_basis=basis,
                                  request_id=rid('photo', code, basis, self.rights), note=self.note, actor=self.actor,
                                  provenance_reader=reader, image_reader=self.image_reader,
                                  business_rights_reference=self.rights)
                    result = ('approved', None)
        except HTTPException as error:
            result = ('failed', error.detail)
        finally:
            conn.close()
        self.photos[code] = result
        return result

    # 3. recommendation review ---------------------------------------------
    def review(self, identity):
        from api.pc_configuration_review import load_review, save_review, ReviewEdit, Finding
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                _, _, _, state = load_review(conn, identity)
                if state['state'] == 'approved':
                    return 'already', None
                if state['blockers'] or state['recommendation_state'] == 'hold':
                    reasons = state['blockers'] or [v for k, v in state['required'].items() if k not in ('copy', 'price')]
                    return 'hold', ' / '.join(reasons) or 'hold'
                if not self.apply:
                    return 'would_approve', ', '.join(sorted(state['required']))
                body = ReviewEdit(revision=state['revision'], basis=state['basis'], action='approve',
                                  findings={k: Finding(confirmed=True, evidence=self.note) for k in state['required']},
                                  note=self.note)
                save_review(conn, identity, body, self.actor)
                return 'approved', None
        except HTTPException as error:
            return 'failed', error.detail
        finally:
            conn.close()

    # 4. publication -----------------------------------------------------------
    def publish(self, identity):
        from api import pc_customer_publication as publication
        from api.pc_publication_source_reader import make_source_reader
        from fastapi import HTTPException
        reader = make_source_reader(image_reader=self.image_reader, business_rights_reference=self.rights)
        conn = _tx(self.engine, repeatable=True)
        try:
            with conn.begin():
                cur = publication.read_current(conn, identity, source_reader=reader)
                if cur['allowed']:
                    return 'already', None
                if cur['publication_basis'] is None:
                    return ('after_previous_steps' if not self.apply else 'blocked'), cur['reason']
                if not self.apply:
                    return 'would_approve', None
                publication.approve(conn, identity, expected_seq=cur['event_seq'], revision=cur['revision'],
                                    review_basis=cur['basis'], publication_basis=cur['publication_basis'],
                                    request_id=rid('publish', identity, cur['publication_basis']),
                                    note=self.note, actor=self.actor, source_reader=reader)
                return 'approved', None
        except HTTPException as error:
            return 'failed', error.detail
        finally:
            conn.close()

    def configuration(self, identity):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            linked = [r[0] for r in conn.execute(text(
                'SELECT explanation_code FROM pc_configuration_parts WHERE configuration_id=:id AND NOT pseudo'),
                dict(id=identity))]
        codes = sorted({c for c in linked if c is not None})
        unlinked = sum(c is None for c in linked)
        parts = {c: self.part(c) for c in codes}
        # A missing explanation is reported only; its photo cannot be approved either.
        photos = {c: self.photo(c) for c in codes if parts[c][0] != 'missing'}
        ready = not unlinked and len(photos) == len(codes) and all(
            s in ('already', 'approved', 'would_approve') for s, _ in list(parts.values()) + list(photos.values()))
        missing = unlinked + sum(v[0] == 'missing' for v in parts.values())
        review = (self.review(identity) if ready else
                  ('after_previous_steps', f'설명 없음 {missing}건' if missing else '부품 설명·사진 승인 필요'))
        if review[0] in ('already', 'approved'):
            publish = self.publish(identity)
        elif review[0] == 'would_approve':
            publish = ('after_previous_steps', None)
        else:
            publish = ('not_attempted', review[0])
        return dict(configuration_id=identity, parts=len(codes),
                    part_states=dict(Counter(s for s, _ in parts.values())),
                    photo_states=dict(Counter(s for s, _ in photos.values())),
                    unlinked_parts=unlinked,
                    part_issues={c: v for c, v in parts.items() if v[0] in ('blocked', 'failed', 'missing')},
                    photo_issues={c: v for c, v in photos.items() if v[0] in ('blocked', 'failed')},
                    review=review, publication=publish)


def run(engine, *, apply=False, operator_id=None, note='', rights=None, all_configs=False, only=(),
        image_reader=None, out=print):
    actor = None
    if apply or operator_id is not None:
        with engine.connect() as conn:
            actor = owner(conn, operator_id)
    from api.part_photo_approval import _reference
    if not _reference(rights, rights=True):
        out(f'주의: {RIGHTS_ENV} 미설정 또는 형식 불일치 · 부품 사진 승인과 발행은 적용 단계에서 거부된다')
    with engine.connect() as conn:
        ids = targets(conn, all_configs, set(only))
    batch = Batch(engine, apply=apply, actor=actor, note=note, rights=rights, image_reader=image_reader, out=out)
    rows = []
    for identity in ids:
        try:
            row = batch.configuration(identity)
        except Exception as error:   # one configuration must not stop the batch
            row = dict(configuration_id=identity, review=('failed', type(error).__name__), publication=('not_attempted', None))
        rows.append(row)
        out(f"{identity}\t부품 {row.get('parts', '-')}\t검토 {row['review'][0]}\t발행 {row['publication'][0]}"
            + (f"\t{row['review'][1]}" if row['review'][0] in ('hold', 'failed') else ''))
    summary = dict(configurations=len(ids),
                   parts=dict(Counter(s for s, _ in batch.parts.values())),
                   photos=dict(Counter(s for s, _ in batch.photos.values())),
                   review=dict(Counter(r['review'][0] for r in rows)),
                   publication=dict(Counter(r['publication'][0] for r in rows)))
    out(f"구성 {summary['configurations']}개 · 부품 {len(batch.parts)}종")
    for key in ('parts', 'photos', 'review', 'publication'):
        out(f'  {key}: ' + ' · '.join(f'{k} {v}' for k, v in sorted(summary[key].items())))
    return dict(mode='apply' if apply else 'dry-run', summary=summary, configurations=rows)


def main(argv=None, environment=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='실제 승인(기본은 조회만)')
    parser.add_argument('--operator-id', type=int, help='--apply 시 활성 owner 운영자 번호')
    parser.add_argument('--approval-note', default='', help='owner 승인 문장(--apply 시 10자 이상)')
    parser.add_argument('--all', action='store_true', help='대표 이미지 유무와 관계없이 판매중 구성 전체')
    parser.add_argument('--only', action='append', default=[], help='이 구성 id만(반복 가능)')
    parser.add_argument('--report', type=Path, help='결과 JSON 저장 경로')
    args = parser.parse_args(argv)
    environment = os.environ if environment is None else environment
    rights = environment.get(RIGHTS_ENV)
    if args.apply:
        from api.part_photo_approval import _reference
        if (environment.get(APPLY_ENV) != '1' or not args.operator_id
                or len(args.approval_note.strip()) < 10 or not _reference(rights, rights=True)):
            parser.error(f'--apply 는 {APPLY_ENV}=1, {RIGHTS_ENV}, --operator-id, --approval-note(10자 이상)가 필요합니다')
    from api.db import engine
    result = run(engine, apply=args.apply, operator_id=args.operator_id, note=args.approval_note.strip(),
                 rights=rights, all_configs=args.all, only=args.only)
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
