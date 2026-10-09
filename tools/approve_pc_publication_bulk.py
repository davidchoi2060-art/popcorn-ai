"""Bulk-approve customer publication for assembled PCs: part explanation -> part photo
-> configuration recommendation review -> publication, in that order.

Every step goes through the existing approval module, never a direct UPDATE:
  1. part explanation   api.part_explanation_approval.approve (per distinct part)
  2. part photo         api.part_photo_approval.approve; provenance records
                        rights_reference = RIGHTS_ATTESTATION (the 2026-10-06 business
                        photo-use attestation; the env value must equal it byte for byte)
                        and the private-bucket detail image as source_reference
  3. recommendation     api.pc_configuration_review.save_review(action='approve').
                        Only the MANUAL findings copy/price, and only when the owner
                        decision named by --approval-decision in
                        docs/rights/pc-publication-approval-ledger.json covers them and
                        this configuration (its selected representative image comes from
                        the decision's archive manifest; not withdrawn). Each finding's
                        evidence names the configuration, revision, review basis, archive,
                        decision id and its project-chat message ids. Any other required
                        key, or a configuration outside the decision, blocks it
  4. publication        api.pc_customer_publication.approve with the native
                        source reader, in a REPEATABLE READ transaction

First-time approvals only. A step is written only when it has never been approved
(state 'unapproved', event_seq 0, no legacy approved_by). Revoked, stale, draft,
unknown, rights-changed or legacy states are reported as needs_explicit_reapproval
with the prior approver/time, and never re-approved here (a new request id cannot
bypass this: the check is on state, not on the request).

Read-only precheck first. For each configuration all four steps are read before
any write; a hold, blocker, missing/unlinked part, unknown required key or a
needs_explicit_reapproval anywhere means nothing is written for it. Parts shared
by several configurations are written once and the report lists who shares them.

Executor: the server shell, --operator-id of an active owner. That owner is
re-read FOR SHARE inside every write transaction, and the apply switch is
re-checked there too (run()/Batch called directly are guarded the same way). If
the owner stops being an active owner, the batch stops and the rest is not_run.
No web session route is involved.

Targets: configurations with a selected, ready representative image (registered
by tools/import_pc_media_archive.py). --all takes every configuration with a sold
P offer. --only limits to configuration ids.

Default is a read-only dry run. --apply needs POPCORN_PUBLICATION_BULK_APPROVE_APPLY=1,
POPCORN_PART_PHOTO_RIGHTS_REFERENCE equal to RIGHTS_ATTESTATION, --operator-id,
--approval-note and --approval-decision. Each step is its own transaction and its
result is recorded as committed / already / committed_by_other (a shared part written
for an earlier configuration) / not_run / failed, also when the batch stops midway.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = UUID('0d6c3b2a-8e41-4f7a-b5c9-6a2e1f04d873')
APPLY_ENV = 'POPCORN_PUBLICATION_BULK_APPROVE_APPLY'
RIGHTS_ENV = 'POPCORN_PART_PHOTO_RIGHTS_REFERENCE'
# 2026-10-06 business product-photo use attestation (sha256 of the document bytes).
RIGHTS_ATTESTATION = ('workroom:기록/팝콘AI/결정/popcorn-business-product-photo-use-attestation-20261006.md@v1:'
                      '8851f92e8e98f041f948cfcda04bfdf4d51949b14fbc4395ba69ada0c88ea6a2')
AUTO_FINDINGS = {'copy', 'price'}
APPROVALS = ROOT / 'docs' / 'rights' / 'pc-publication-approval-ledger.json'
APPROVALS_REF = 'ledger:docs/rights/pc-publication-approval-ledger.json'
STEPS = ['explanation', 'photo', 'review', 'publication']


class LedgerError(ValueError):
    """The publication approval ledger is unreadable or one of its rows is malformed."""


def _rows(data, key):
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise LedgerError(f'{key} 가 배열이 아닙니다')
    for n, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise LedgerError(f'{key} {n}번째 행이 객체가 아닙니다')
    return rows


def parse_approvals(path=None):
    """Strict parse: {'decisions': {id: decision}, 'withdrawn': {(decision_id, configuration_id)}}.
    Any malformed or duplicate row raises LedgerError naming it."""
    try:
        data = json.loads(Path(path or APPROVALS).read_text(encoding='utf-8'))
    except Exception as error:
        raise LedgerError(f'승인 원장을 읽을 수 없습니다: {type(error).__name__}') from None
    decisions = {}
    for n, d in enumerate(_rows(data, 'decisions'), 1):
        scope, refs = d.get('scope'), d.get('references')
        if (not isinstance(d.get('id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,80}', d['id'])
                or not isinstance(refs, list) or not refs
                or not all(isinstance(r, str) and re.fullmatch(r'project-chat:cmsg_[A-Za-z0-9]{20,80}', r) for r in refs)
                or not isinstance(d.get('quotes'), list) or len(d['quotes']) != len(refs)
                or not all(isinstance(q, str) and q.strip() for q in d['quotes'])
                or not isinstance(scope, dict)
                or not isinstance(scope.get('media_manifest_sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', scope['media_manifest_sha256'])
                or not isinstance(scope.get('findings'), list) or not scope['findings']
                or not set(scope['findings']) <= AUTO_FINDINGS
                or scope.get('steps') != STEPS):
            raise LedgerError(f'decisions {n}번째 행 형식 불일치')
        if d['id'] in decisions:
            raise LedgerError(f'decisions {n}번째 행의 id 가 앞 행과 중복')
        decisions[d['id']] = d
    gone = set()
    for n, w in enumerate(_rows(data, 'withdrawn'), 1):
        ref = w.get('reference')
        if (w.get('decision') not in decisions or not isinstance(w.get('configuration_id'), str)
                or not w['configuration_id'].strip() or not isinstance(ref, str) or not ref.strip()):
            raise LedgerError(f'withdrawn {n}번째 행 형식 불일치')
        gone.add((w['decision'], w['configuration_id']))
    return dict(decisions=decisions, withdrawn=gone)


def media_manifest(conn, identity):
    """Archive manifest of the configuration's selected, ready representative image (or None)."""
    from sqlalchemy import text
    rows = [r[0] for r in conn.execute(text("""SELECT j.import_provenance->'original'->>'manifest_sha256'
        FROM pc_media_jobs j WHERE j.configuration_id=:id AND j.selected AND j.status='ready'"""), dict(id=identity))]
    return rows[0] if len(rows) == 1 else None


class OutOfScope(Exception):
    """This configuration is no longer covered by the owner decision (withdrawn,
    decision removed, or media manifest changed). Only this configuration fails."""


class Stop(Exception):
    """The executor is no longer allowed to write: stop the whole batch."""


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


def owner(conn, operator_id, lock=False):
    from sqlalchemy import text
    row = conn.execute(text('SELECT operator_id,name,role,status FROM admin_operators WHERE operator_id=:o'
                            + (' FOR SHARE' if lock else '')), dict(o=operator_id)).mappings().first()
    if not row or row['role'] != 'owner' or row['status'] != '활성':
        raise PermissionError('활성 owner 계정만 적용할 수 있습니다')
    return dict(row)


def require_apply(rights, environment=None):
    environment = os.environ if environment is None else environment
    if environment.get(APPLY_ENV) != '1':
        raise PermissionError(f'{APPLY_ENV}=1 이 아니면 적용하지 않습니다')
    if rights != RIGHTS_ATTESTATION or environment.get(RIGHTS_ENV) != RIGHTS_ATTESTATION:
        raise PermissionError(f'{RIGHTS_ENV} 가 2026-10-06 확인서 값과 바이트 일치하지 않습니다')


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


def _prior(by, at):
    return dict(approved_by=by, approved_at=str(at) if at is not None else None) if by is not None or at else None


def _first_time(cur, legacy=None):
    """None when the step may be approved for the first time; else the reason it may not."""
    if cur['allowed']:
        return None
    if cur['state'] != 'unapproved' or cur['event_seq'] != 0 or legacy:
        return f"{cur['state']}:{'legacy_approved_by' if legacy else cur.get('reason')}"
    return None


class Batch:
    def __init__(self, engine, *, apply=False, operator_id=None, note='', decision=None, rights=None,
                 image_reader=None, environment=None, out=print):
        self.engine, self.apply, self.operator_id, self.note = engine, apply, operator_id, note
        self.decision_id, self.rights, self.environment, self.out = decision, rights, environment, out
        if apply:
            require_apply(rights, environment)
            if operator_id is None or not note.strip() or not decision:
                raise PermissionError('--operator-id, --approval-note, --approval-decision 이 필요합니다')
        # A malformed ledger stops the run before anything is read or written (LedgerError).
        self.decision = self.current_decision() if decision else None
        if decision and self.decision is None:
            raise PermissionError(f'승인 원장에 결정 {decision} 이 없습니다')
        self.row = None                             # configuration being processed (kept on stop)
        self.part_by, self.photo_by = {}, {}        # code -> configuration that wrote it
        if image_reader is None:
            from api.product_images import read_image as image_reader
        self.image_reader = image_reader
        self.pre_parts, self.pre_photos = {}, {}    # code -> (state, detail, prior)
        self.parts, self.photos = {}, {}            # code -> (result, detail) of the write step
        self.users = {}                             # code -> configuration ids sharing it

    def current_decision(self):
        return parse_approvals()['decisions'].get(self.decision_id)

    def scope_reason(self, conn, identity, decision=None):
        """None when the owner decision covers this configuration; else the reason."""
        if decision is None:
            found = parse_approvals()
            decision = found['decisions'].get(self.decision_id)
            if decision is None or (self.decision_id, identity) in found['withdrawn']:
                return '승인 결정 없음 또는 철회'
        manifest = media_manifest(conn, identity)
        if manifest != decision['scope']['media_manifest_sha256']:
            return f'대표 이미지 묶음이 승인 범위와 다름({manifest})'
        return None

    def check_scope(self, conn, identity):
        """Re-read the ledger now: the decision still exists, this configuration is not
        withdrawn, and its media manifest is still the approved one. Returns the decision."""
        found = parse_approvals()   # LedgerError: the whole run stops
        decision = found['decisions'].get(self.decision_id)
        if decision is None or (self.decision_id, identity) in found['withdrawn']:
            raise OutOfScope('approval_decision_missing_or_withdrawn')
        if self.scope_reason(conn, identity, decision):
            raise OutOfScope('out_of_scope')
        return decision

    def guard(self, conn, identity):
        """Inside every write transaction: the switch is still on, the executor is still
        an active owner (FOR SHARE holds it until commit), and the owner decision still
        covers this configuration. Returns (actor, decision)."""
        try:
            require_apply(self.rights, self.environment)
            actor = owner(conn, self.operator_id, lock=True)
        except PermissionError as error:
            raise Stop(str(error)) from None
        return actor, self.check_scope(conn, identity)

    def shared(self, done, by, code, identity):
        """A part/photo another configuration already handled in this run. The cached
        result says only what that write did; this configuration's own scope is checked
        again before it may count on it."""
        try:
            with self.engine.connect() as conn:
                self.check_scope(conn, identity)
        except OutOfScope as error:
            return ('failed', str(error))
        state, detail = done[code]
        return ('committed_by_other', by[code]) if state == 'committed' else (state, detail)

    # read-only precheck ---------------------------------------------------
    def pre_part(self, code):
        if code in self.pre_parts:
            return self.pre_parts[code]
        from api import part_explanation_approval as part
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                cur = part.read_current(conn, code)
                row = part._read(conn, code)
                prior = _prior(row.get('approved_by'), row.get('approved_at'))
                legacy = not cur['allowed'] and row.get('approved_by') is not None
                if cur['allowed']:
                    result = ('already', None, prior)
                elif _first_time(cur, legacy):
                    result = ('needs_explicit_reapproval', _first_time(cur, legacy), prior)
                elif part._source_reason(row):
                    result = ('blocked', part._source_reason(row), prior)
                else:
                    result = ('ready', None, prior)
        except HTTPException as error:
            result = ('missing' if error.status_code == 404 else 'failed', error.detail, None)
        finally:
            conn.close()
        self.pre_parts[code] = result
        return result

    def pre_photo(self, code):
        if code in self.pre_photos:
            return self.pre_photos[code]
        from api import part_explanation_approval as part
        from api import part_photo_approval as photo
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                cur = photo.read_current(conn, code, provenance_reader=photo_reader(self.rights),
                                         image_reader=self.image_reader, business_rights_reference=self.rights)
                row = part._read(conn, code)
                reason = photo._model_reason(row) or photo._asset_reason(photo._model(row)['image_asset'], code)
                prior = _prior(cur.get('operator_id'), cur.get('approved_at'))
                if cur['allowed']:
                    result = ('already', None, prior)
                elif _first_time(cur):
                    result = ('needs_explicit_reapproval', _first_time(cur), prior)
                elif reason:
                    result = ('blocked', reason, prior)
                else:
                    result = ('ready', None, prior)
        except HTTPException as error:
            result = ('failed', error.detail, None)
        finally:
            conn.close()
        self.pre_photos[code] = result
        return result

    def pre_review(self, identity):
        from api.pc_configuration_review import load_review
        conn = _tx(self.engine)
        try:
            with conn.begin():
                _, _, _, state = load_review(conn, identity)
        finally:
            conn.close()
        prior = state.get('prior_review') or {}
        actor = state.get('approved_by') or prior.get('actor')
        info = dict(revision=state['revision'], basis=state['basis'],
                    prior=_prior(actor.get('operator_id') if isinstance(actor, dict) else actor,
                                 state.get('approved_at') or prior.get('at')))
        if state['state'] == 'approved':
            return ('already', None, info)
        if state['blockers'] or state['recommendation_state'] == 'hold':
            reasons = state['blockers'] or [v for k, v in state['required'].items() if k not in AUTO_FINDINGS]
            return ('hold', ' / '.join(reasons) or 'hold', info)
        allowed = AUTO_FINDINGS & set(self.decision['scope']['findings'] if self.decision else AUTO_FINDINGS)
        other = sorted(set(state['required']) - allowed)
        if other:
            return ('blocked', '자동 확인 대상이 아닌 필수 항목: ' + ', '.join(other), info)
        if state['state'] != 'pending' or state.get('approved_by') or state.get('prior_review'):
            return ('needs_explicit_reapproval', state['state'], info)
        return ('ready', ', '.join(sorted(state['required'])), info)

    def pre_publication(self, identity):
        from api import pc_customer_publication as publication
        from api.pc_publication_source_reader import make_source_reader
        reader = make_source_reader(image_reader=self.image_reader, business_rights_reference=self.rights)
        conn = _tx(self.engine, repeatable=True)
        try:
            with conn.begin():
                cur = publication.read_current(conn, identity, source_reader=reader)
        finally:
            conn.close()
        if cur['allowed']:
            return ('already', None)
        if _first_time(cur):
            return ('needs_explicit_reapproval', _first_time(cur))
        return ('ready', cur.get('reason'))

    def precheck(self, identity):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            linked = [r[0] for r in conn.execute(text(
                'SELECT explanation_code FROM pc_configuration_parts WHERE configuration_id=:id AND NOT pseudo'),
                dict(id=identity))]
        codes = sorted({c for c in linked if c is not None})
        for c in codes:
            self.users.setdefault(c, []).append(identity)
        unlinked = sum(c is None for c in linked)
        parts = {c: self.pre_part(c) for c in codes}
        # A missing explanation is reported only; its photo cannot be approved either.
        photos = {c: self.pre_photo(c) for c in codes if parts[c][0] != 'missing'}
        review = self.pre_review(identity)
        publication = self.pre_publication(identity)
        states = [v[0] for v in list(parts.values()) + list(photos.values())] + [review[0], publication[0]]
        missing = unlinked + sum(v[0] == 'missing' for v in parts.values())
        scope = None
        if self.decision_id:
            with self.engine.connect() as conn:
                scope = self.scope_reason(conn, identity)
        if scope:
            verdict = ('out_of_scope', scope)
        elif missing:
            verdict = ('missing', f'설명 없음 {missing}건')
        elif review[0] == 'hold':
            verdict = ('hold', review[1])
        else:
            bad = next((s for s in ('needs_explicit_reapproval', 'blocked', 'failed') if s in states), None)
            verdict = (bad, '; '.join(f'{k} {v[1]}' for k, v in
                                      [*(('part ' + str(c), v) for c, v in parts.items()),
                                       *(('photo ' + str(c), v) for c, v in photos.items()),
                                       ('review', review), ('publication', publication)] if v[0] == bad)) if bad else ('ok', None)
        return dict(codes=codes, unlinked=unlinked, parts=parts, photos=photos, review=review,
                    publication=publication, verdict=verdict)

    # writes -----------------------------------------------------------------
    def write_part(self, code, identity):
        if code in self.parts:
            return self.shared(self.parts, self.part_by, code, identity)
        from api import part_explanation_approval as part
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                actor, _ = self.guard(conn, identity)
                cur = part.read_current(conn, code)
                row = part._read(conn, code)
                if cur['allowed']:
                    result = ('already', None)
                elif _first_time(cur, row.get('approved_by') is not None) or part._source_reason(row):
                    result = ('failed', 'state_changed_since_precheck')
                else:
                    part.approve(conn, code, expected_seq=0, expected_basis=part.basis(row),
                                 request_id=rid('explain', code, part.basis(row)), note=self.note, actor=actor)
                    result = ('committed', None)
        except OutOfScope as error:   # this configuration only: not cached for the others
            return ('failed', str(error))
        except HTTPException as error:
            result = ('failed', error.detail)
        finally:
            conn.close()
        self.parts[code], self.part_by[code] = result, identity
        return result

    def write_photo(self, code, identity):
        if code in self.photos:
            return self.shared(self.photos, self.photo_by, code, identity)
        from api import part_explanation_approval as part
        from api import part_photo_approval as photo
        from fastapi import HTTPException
        reader = photo_reader(self.rights)
        conn = _tx(self.engine)
        try:
            with conn.begin():
                actor, _ = self.guard(conn, identity)
                cur = photo.read_current(conn, code, provenance_reader=reader, image_reader=self.image_reader,
                                         business_rights_reference=self.rights)
                if cur['allowed']:
                    result = ('already', None)
                elif _first_time(cur):
                    result = ('failed', 'state_changed_since_precheck')
                else:
                    basis = photo.basis(part._read(conn, code))
                    photo.approve(conn, code, expected_seq=0, expected_basis=basis,
                                  request_id=rid('photo', code, basis, self.rights), note=self.note, actor=actor,
                                  provenance_reader=reader, image_reader=self.image_reader,
                                  business_rights_reference=self.rights)
                    result = ('committed', None)
        except OutOfScope as error:   # this configuration only: not cached for the others
            return ('failed', str(error))
        except HTTPException as error:
            result = ('failed', error.detail)
        finally:
            conn.close()
        self.photos[code], self.photo_by[code] = result, identity
        return result

    def evidence(self, identity, revision, basis, label, decision):
        refs = ' '.join(r.split(':', 1)[1] for r in decision['references'])
        text = (f'{label} 확인 · 구성 {identity} · 차수 {revision} · 검토 근거 {basis} · '
                f"대표 이미지 묶음 {decision['scope']['media_manifest_sha256']} · "
                f"승인 결정 {APPROVALS_REF}#{decision['id']} (원문 {refs}) · 사진 권리 {self.rights}")
        if len(text) > 2000:
            raise ValueError('근거 문장이 2000자를 넘습니다')
        return text

    def write_review(self, identity):
        from api.pc_configuration_review import load_review, save_review, ReviewEdit, Finding
        from fastapi import HTTPException
        conn = _tx(self.engine)
        try:
            with conn.begin():
                actor, decision = self.guard(conn, identity)
                _, _, _, state = load_review(conn, identity)
                if state['state'] == 'approved':
                    return ('already', None)
                if (state['blockers'] or state['recommendation_state'] == 'hold'
                        or set(state['required']) - (AUTO_FINDINGS & set(decision['scope']['findings']))
                        or state['state'] != 'pending' or state.get('approved_by') or state.get('prior_review')):
                    return ('failed', 'state_changed_since_precheck')
                findings = {k: Finding(confirmed=True,
                                       evidence=self.evidence(identity, state['revision'], state['basis'], v, decision))
                            for k, v in state['required'].items()}
                save_review(conn, identity, ReviewEdit(revision=state['revision'], basis=state['basis'], action='approve',
                                                       findings=findings, note=self.note), actor)
                return ('committed', None)
        except OutOfScope as error:
            return ('failed', str(error))
        except HTTPException as error:
            return ('failed', error.detail)
        finally:
            conn.close()

    def write_publication(self, identity):
        from api import pc_customer_publication as publication
        from api.pc_publication_source_reader import make_source_reader
        from fastapi import HTTPException
        reader = make_source_reader(image_reader=self.image_reader, business_rights_reference=self.rights)
        conn = _tx(self.engine, repeatable=True)
        try:
            with conn.begin():
                actor, _ = self.guard(conn, identity)
                cur = publication.read_current(conn, identity, source_reader=reader)
                if cur['allowed']:
                    return ('already', None)
                if _first_time(cur) or cur['publication_basis'] is None:
                    return ('failed', cur.get('reason') or 'state_changed_since_precheck')
                publication.approve(conn, identity, expected_seq=0, revision=cur['revision'],
                                    review_basis=cur['basis'], publication_basis=cur['publication_basis'],
                                    request_id=rid('publish', identity, cur['publication_basis']),
                                    note=self.note, actor=actor, source_reader=reader)
                return ('committed', None)
        except OutOfScope as error:
            return ('failed', str(error))
        except HTTPException as error:
            return ('failed', error.detail)
        finally:
            conn.close()

    def configuration(self, identity):
        pre = self.precheck(identity)
        steps = dict(parts={}, photos={}, review=('not_run', None), publication=('not_run', None))
        row = dict(configuration_id=identity, parts=len(pre['codes']), unlinked_parts=pre['unlinked'],
                   precheck=pre['verdict'], review_prior=pre['review'][2]['prior'],
                   part_prior={c: v[2] for c, v in pre['parts'].items() if v[2]},
                   photo_prior={c: v[2] for c, v in pre['photos'].items() if v[2]},
                   issues={f'{k} {c}': v[:2] for k, group in (('part', pre['parts']), ('photo', pre['photos']))
                           for c, v in group.items() if v[0] not in ('ready', 'already')},
                   review=pre['review'][:2], publication=pre['publication'], steps=steps)
        self.row = row
        if pre['verdict'][0] != 'ok':
            row['publication'] = ('not_attempted', pre['verdict'][0])
            return row
        if not self.apply:
            row['review'] = ('would_approve', pre['review'][1]) if pre['review'][0] == 'ready' else pre['review'][:2]
            row['publication'] = (('after_previous_steps' if pre['publication'][1] else 'would_approve'), None) \
                if pre['publication'][0] == 'ready' else pre['publication']
            return row
        row['review'], row['publication'] = ('not_run', None), ('not_run', None)
        for c in pre['codes']:
            steps['parts'][c] = self.write_part(c, identity) if pre['parts'][c][0] != 'already' else ('already', None)
        if any(v[0] == 'failed' for v in steps['parts'].values()):
            row['review'], row['publication'] = ('not_run', 'part'), ('not_attempted', 'part')
            return row
        for c in pre['codes']:
            steps['photos'][c] = self.write_photo(c, identity) if pre['photos'][c][0] != 'already' else ('already', None)
        if any(v[0] == 'failed' for v in steps['photos'].values()):
            row['review'], row['publication'] = ('not_run', 'photo'), ('not_attempted', 'photo')
            return row
        steps['review'] = self.write_review(identity) if pre['review'][0] != 'already' else ('already', None)
        row['review'] = steps['review']
        if steps['review'][0] == 'failed':
            row['publication'] = ('not_attempted', 'review')
            return row
        steps['publication'] = self.write_publication(identity)
        row['publication'] = steps['publication']
        return row


def rights_line(engine, rights):
    """One line: is the env value well-formed, and do recorded photo approvals carry
    exactly (byte for byte) the same rights_reference?"""
    from sqlalchemy import text
    from api.part_photo_approval import _reference
    if not _reference(rights, rights=True):
        return f'권리 참조값: {RIGHTS_ENV} 미설정 또는 형식 불일치 · 부품 사진 승인과 발행은 적용 단계에서 거부된다'
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT count(*) AS total,
            count(*) FILTER (WHERE convert_to(snapshot->'provenance'->>'rights_reference','UTF8')=convert_to(:r,'UTF8')) AS same
            FROM (SELECT DISTINCT ON (source_product_code) snapshot FROM part_photo_approval_events
                  ORDER BY source_product_code, event_seq DESC) latest"""), dict(r=rights)).mappings().first()
    total, same = (row['total'], row['same']) if row else (0, 0)
    return f'권리 참조값: env 형식 일치 · 기존 사진 승인 최신 {total}건 중 env 와 바이트 일치 {same}건 · 새 승인은 env 값으로 기록'


def _interrupted(batch, identity, state, detail):
    """Keep what the interrupted configuration already wrote; mark the rest not_run."""
    if batch.row and batch.row['configuration_id'] == identity:
        row = dict(batch.row, interrupted=(state, detail))
    else:   # stopped before the precheck finished: nothing was written for it
        row = dict(configuration_id=identity, precheck=(state, detail), interrupted=(state, detail),
                   steps=dict(parts={}, photos={}, review=('not_run', None), publication=('not_run', None)))
    for key in ('review', 'publication'):
        if row.get(key, ('not_run',))[0] not in ('committed', 'already', 'failed', 'not_attempted'):
            row[key] = ('not_run', None)
    return row


def run(engine, *, apply=False, operator_id=None, note='', decision=None, rights=None, all_configs=False,
        only=(), image_reader=None, environment=None, out=print):
    if apply or operator_id is not None:
        with engine.connect() as conn:
            owner(conn, operator_id)
    batch = Batch(engine, apply=apply, operator_id=operator_id, note=note, decision=decision, rights=rights,
                  image_reader=image_reader, environment=environment, out=out)
    out(rights_line(engine, rights))
    with engine.connect() as conn:
        ids = targets(conn, all_configs, set(only))
    rows, stopped, ledger_error = [], None, None
    for identity in ids:
        if stopped:
            rows.append(dict(configuration_id=identity, precheck=('not_run', stopped),
                             review=('not_run', None), publication=('not_run', None), steps={}))
            continue
        batch.row = None
        try:
            row = batch.configuration(identity)
        except Stop as error:      # executor no longer allowed: nothing more is written
            stopped = str(error)
            row = _interrupted(batch, identity, 'stopped', stopped)
        except LedgerError as error:   # the whole run stops; what was written is still reported
            stopped = ledger_error = f'승인 원장 {APPROVALS.name}: {error}'
            row = _interrupted(batch, identity, 'ledger_error', ledger_error)
        except Exception as error:   # one configuration must not stop the batch
            row = _interrupted(batch, identity, 'failed', type(error).__name__)
        rows.append(row)
        out(f"{identity}\t부품 {row.get('parts', '-')}\t사전검사 {row['precheck'][0]}\t검토 {row['review'][0]}"
            f"\t발행 {row['publication'][0]}" + (f"\t{row['precheck'][1]}" if row['precheck'][0] != 'ok' else '')
            + (f"\t중단 {row['interrupted'][0]}: {row['interrupted'][1]}" if row.get('interrupted') else ''))
    shared = {c: users for c, users in batch.users.items() if len(users) > 1}
    summary = dict(configurations=len(ids), stopped=stopped,
                   precheck=dict(Counter(r['precheck'][0] for r in rows)),
                   interrupted=dict(Counter(r['interrupted'][0] for r in rows if r.get('interrupted'))),
                   parts=dict(Counter(v[0] for v in batch.pre_parts.values())),
                   photos=dict(Counter(v[0] for v in batch.pre_photos.values())),
                   part_writes=dict(Counter(v[0] for v in batch.parts.values())),
                   photo_writes=dict(Counter(v[0] for v in batch.photos.values())),
                   review=dict(Counter(r['review'][0] for r in rows)),
                   publication=dict(Counter(r['publication'][0] for r in rows)),
                   shared_parts=len(shared))
    out(f"구성 {summary['configurations']}개 · 부품 {len(batch.pre_parts)}종(여러 구성 공유 {len(shared)}종)"
        + (f' · 중단: {stopped}' if stopped else ''))
    for key in ('precheck', 'parts', 'photos', 'part_writes', 'photo_writes', 'review', 'publication'):
        out(f'  {key}: ' + ' · '.join(f'{k} {v}' for k, v in sorted(summary[key].items())))
    return dict(mode='apply' if apply else 'dry-run', ledger_error=ledger_error,
                decision=f'{APPROVALS_REF}#{decision}' if decision else None, summary=summary,
                configurations=rows, shared_parts={str(c): u for c, u in shared.items()})


def main(argv=None, environment=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='실제 승인(기본은 조회만)')
    parser.add_argument('--operator-id', type=int, help='--apply 시 활성 owner 운영자 번호')
    parser.add_argument('--approval-note', default='', help='owner 승인 문장(--apply 시 10자 이상)')
    parser.add_argument('--approval-decision', help='docs/rights/pc-publication-approval-ledger.json 의 결정 id')
    parser.add_argument('--all', action='store_true', help='대표 이미지 유무와 관계없이 판매중 구성 전체')
    parser.add_argument('--only', action='append', default=[], help='이 구성 id만(반복 가능)')
    parser.add_argument('--report', type=Path, help='결과 JSON 저장 경로')
    args = parser.parse_args(argv)
    environment = os.environ if environment is None else environment
    rights = environment.get(RIGHTS_ENV)
    if args.apply:
        try:
            require_apply(rights, environment)
        except PermissionError as error:
            parser.error(str(error))
        if not args.operator_id or len(args.approval_note.strip()) < 10 or not args.approval_decision:
            parser.error('--apply 는 --operator-id, --approval-note(10자 이상), --approval-decision 이 필요합니다')
    if args.apply or args.approval_decision:
        try:
            found = parse_approvals()
        except LedgerError as error:
            parser.error(f'승인 원장 {APPROVALS.name}: {error} -- 전체 실행을 중단합니다')
        if args.approval_decision not in found['decisions']:
            parser.error(f'승인 원장에 결정 {args.approval_decision} 이 없습니다 -- 적용하지 않습니다')
    from api.db import engine
    result = run(engine, apply=args.apply, operator_id=args.operator_id, note=args.approval_note.strip(),
                 decision=args.approval_decision, rights=rights, all_configs=args.all, only=args.only,
                 environment=environment)
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if result['ledger_error']:   # report saved first; the run still counts as stopped
        print(f"{result['ledger_error']} -- 전체 실행을 중단했습니다", file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
