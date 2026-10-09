"""Batch-register the existing 104 assembled-PC example images as representative images.

The archive (manifest.json + originals/P{product_code}.png) was generated on
2026-09-29 and lives on the development PC. Before this tool nothing linked it to
pc_media_jobs, so customer screens kept showing "이미지 준비 중".

Per item, without any generation call:
  1. archive check   PNG bytes match manifest sha256/size (a broken/mismatched file is
                     never registered or selected, only reported); QA notes exist.
  2. current check   the registered P offer is on sale and the current configuration
                     has exactly one CASE. A later revision or a different case does NOT
                     block registration; it withholds automatic selection unless
                     --force-select. An open image condition is reported, never forced.
  3. reuse authority api.pc_existing_media_import.ServerAuthority.verify_reuse and
                     verify_registration, wired to owner_reuse_verifier. Scope of the
                     owner decision (OWNER_DECISION: originals made by the owner, used
                     as-is without regeneration): the archive pinned by #22's
                     MANIFEST_SHA only; items listed in docs/rights/
                     pc-media-reuse-withdrawals.json are withdrawn; a reused original must
                     come from the same archive; a forced mismatch is revision/case only;
                     the principal is an active owner re-read on the same transaction.
                     Asked on the insert transaction, right before upload, inside the
                     ready transaction and inside the selection transaction. Never
                     granted by the manifest's reuse_exception text alone.
  4. apply           insert an origin_kind='existing_import' job bound to the
                     CURRENT visual/review basis, upload create-only to the private
                     bucket (same key layout as generated jobs), mark ready, and
                     select it unless a current ready representative is already
                     selected (a stale selection is replaced).

Default is a read-only dry run. --apply needs POPCORN_EXISTING_MEDIA_IMPORT_APPLY=1
and --operator-id of an active owner; that owner is the verified principal and actor.
Re-running is safe: the request id is derived from manifest+product+image hash.
"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = UUID('6f1d5a8e-3c2b-4b7e-9a51-0c4d2e8f7a19')
PNG = b'\x89PNG\r\n\x1a\n'
MAX_BYTES = 20 * 1024 * 1024
VERSION = 'pc-media-existing-import-v1'
# Owner decision recorded in the project chat (2026-10-09 18:35 / 18:41 KST): the archived
# originals were made by the owner and are used as-is; not regenerating them is no reason
# to discard them. This is the reuse authority basis; it is not publication permission.
OWNER_DECISION = dict(
    reference='project-chat:cmsg_012k6fnspU3tgfYTTB56KTuDK2hTCfHq5dVQu9X69SAbb8'
              '+cmsg_012k6fnspU3tgfYTTB56KTuDA5QazRckoWKUdcdRG2Gkgf',
    decided_at='2026-10-09T18:35:32+09:00',
    basis='owner_made_original_reuse_without_regeneration')
# Mismatch kinds the owner decision allows to be selected with --force-select.
FORCEABLE = frozenset({'revision', 'case'})
# Scope of that decision: exactly the archive pinned by #22 (tools/register_existing_pc_media).
# Another manifest is outside the decision and is denied.
WITHDRAWALS = ROOT / 'docs' / 'rights' / 'pc-media-reuse-withdrawals.json'


def decision_manifest_sha():
    from tools.register_existing_pc_media import MANIFEST_SHA
    return MANIFEST_SHA


def withdrawn(path=None):
    """Owner withdrawals of the reuse decision: {(product_code, original_sha256|None)}.
    An unreadable or malformed file withdraws everything (fail closed)."""
    try:
        data = json.loads(Path(path or WITHDRAWALS).read_text(encoding='utf-8'))
        rows = data['withdrawn']
        return {(int(r['product_code']), r.get('original_sha256')) for r in rows
                if type(r.get('product_code')) is int and str(r.get('reference', '')).strip()}
    except Exception:
        return None


@dataclass(frozen=True)
class ArchiveReuse:
    """What verify_reuse is asked about: one archived original for one current binding."""
    product_code: int
    original_sha256: str
    manifest_sha256: str
    file_reason: str | None
    reused_from: str | None
    reused_from_in_manifest: bool
    mismatch: tuple
    force_select: bool


def file_reason(item, raw):
    """None when the archived file itself is intact; otherwise a Korean reason."""
    if raw is None:
        return '원본 파일 없음'
    if not raw.startswith(PNG) or not 8 < len(raw) <= MAX_BYTES:
        return 'PNG 형식·크기 불일치'
    if item.get('original_sha256') != hashlib.sha256(raw).hexdigest() or item.get('original_bytes') != len(raw):
        return '원본 해시·크기가 manifest 와 다름'
    return None


def load_manifest(archive):
    raw = (Path(archive) / 'manifest.json').read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError('manifest.json 에 items 배열이 없습니다')
    return hashlib.sha256(raw).hexdigest(), items


def product_code(item):
    m = re.fullmatch(r'P([1-9][0-9]*)', str(item.get('configuration_id', '')))
    return int(m.group(1)) if m else None


def archive_reason(item, raw):
    """None when the archived image itself is usable; otherwise a Korean reason."""
    if product_code(item) is None:
        return '상품번호 형식 불일치'
    reason = file_reason(item, raw)
    if reason:
        return reason
    if item.get('generated_original') != f"originals/{item['configuration_id']}.png":
        return 'manifest 원본 경로 불일치'
    notes = item.get('qa_notes')
    if not isinstance(notes, list) or not notes or not all(isinstance(n, str) and n.strip() for n in notes):
        return 'QA 기록 없음'
    reused = item.get('reused_from')
    if reused and not re.fullmatch(r'P[1-9][0-9]*', str(reused)):
        return '재사용 원본 번호 형식 불일치'
    if type(item.get('db_configuration_revision')) is not int or not str(item.get('case_code', '')).isdigit():
        return 'manifest 구성 차수·케이스 정보 없음'
    return None


def current_binding(conn, code, item):
    """(binding, None) or (None, reason). binding['mismatch'] lists (kind, text) of how
    the current configuration differs from the one the original was made for; a
    mismatch does not block registration, it only withholds automatic selection."""
    from fastapi import HTTPException
    from sqlalchemy import text
    from api.pc_configuration_copy import read_sold_offer_configuration
    from api.pc_media import snapshot
    sold = conn.execute(text('SELECT status FROM products WHERE product_code=:c'), dict(c=code)).scalar()
    if sold != '판매중':
        return None, '판매중 아님'
    try:
        bound = read_sold_offer_configuration(conn, code)
    except HTTPException as error:
        return None, f'구성 연결 확인 실패({error.status_code})'
    identity = bound['configuration_id']
    current = snapshot(conn, identity)
    cases = [p for p in current['snapshot']['parts'] if p['slot'] == 'CASE']
    if len(cases) != 1 or not str(cases[0].get('code', '')).isdigit():
        return None, '현재 구성에 케이스 없음'
    mismatch = []
    if bound['revision'] != item['db_configuration_revision']:
        mismatch.append(('revision', f"구성 차수 변경({item['db_configuration_revision']}→{bound['revision']})"))
    if str(cases[0]['code']) != str(item['case_code']):
        mismatch.append(('case', f"케이스 변경({item['case_code']}→{cases[0]['code']})"))
    mismatch += [('image_condition', '이미지 조건: ' + e) for e in current['errors']]
    return dict(code=code, configuration_id=identity, offer_id=bound['offer_id'],
                revision=bound['revision'], case_product_code=int(cases[0]['code']),
                visual_basis=current['visual_basis'], review_basis=current['basis'],
                snapshot=current['snapshot'], mismatch=mismatch), None


def _texts(mismatch):
    return ' · '.join(text for _, text in mismatch)


def selectable(binding, force_select):
    """'auto' | 'forced' | None. Image conditions are never forced."""
    kinds = {kind for kind, _ in binding['mismatch']}
    if not kinds:
        return 'auto'
    return 'forced' if force_select and kinds <= FORCEABLE else None


def reuse_subject(item, raw, manifest_sha, binding, force_select, manifest_skus=()):
    reused = item.get('reused_from') or None
    return ArchiveReuse(product_code(item), item.get('original_sha256'), manifest_sha, file_reason(item, raw),
                        reused, reused is not None and reused in manifest_skus, tuple(binding['mismatch']),
                        force_select)


def owner_reuse_verifier(subject, principal, connection):
    """Reuse authority for the owner-made archive. ALLOW only when every scope holds:
    the archive is the one the decision covers (pinned manifest sha256), the item
    and its original hash are not withdrawn, a reused original comes from the same
    archive, the file is intact, a forced mismatch is revision/case only, and the
    principal is an active owner re-read on the caller's connection. Else DENY."""
    from sqlalchemy import text
    from tools.register_existing_pc_media import Decision
    if type(subject) is not ArchiveReuse or subject.file_reason or connection is None:
        return Decision.DENY
    if subject.manifest_sha256 != decision_manifest_sha() or type(subject.product_code) is not int:
        return Decision.DENY
    gone = withdrawn()
    if gone is None or (subject.product_code, None) in gone or (subject.product_code, subject.original_sha256) in gone:
        return Decision.DENY
    if subject.reused_from is not None and not subject.reused_from_in_manifest:
        return Decision.DENY
    if getattr(principal, 'role', None) != 'owner':
        return Decision.DENY
    row = connection.execute(text('SELECT role,status FROM admin_operators WHERE operator_id=:o FOR SHARE'),
                             dict(o=principal.operator_id)).mappings().first()
    if not row or row['role'] != 'owner' or row['status'] != '활성':
        return Decision.DENY
    kinds = {kind for kind, _ in subject.mismatch}
    if subject.force_select and not kinds <= FORCEABLE:
        return Decision.DENY
    return Decision.ALLOW


def authority(engine, operator_id):
    """ServerAuthority wired with the owner decision verifier; the principal is the
    named operator, read from the DB, never from the archive."""
    from sqlalchemy import text
    from api.pc_existing_media_import import ServerAuthority

    def operator():
        with engine.connect() as conn:
            row = conn.execute(text('SELECT operator_id,role,status FROM admin_operators WHERE operator_id=:o'),
                               dict(o=operator_id)).mappings().first()
        if not row or row['role'] != 'owner' or row['status'] != '활성':
            return None
        return dict(operator_id=row['operator_id'], role=row['role'])
    return ServerAuthority(reuse_verifier=owner_reuse_verifier, operator_reader=operator,
                           registration_verifier=owner_reuse_verifier)


def provenance(item, manifest_sha, binding, principal=None, selection=None):
    reference = f"manifest:sha256:{manifest_sha}#items/{item['configuration_id']}"
    reused = item.get('reused_from') or None
    return dict(version=VERSION, reuse_authority=dict(OWNER_DECISION, verified_by='ServerAuthority.verify_reuse',
        principal=principal.actor if principal else None, selection=selection,
        mismatch=[text for _, text in binding['mismatch']]), original=dict(
        source_sku=item['configuration_id'], original_revision=item['db_configuration_revision'],
        original_ref=item['generated_original'], original_sha256=item['original_sha256'],
        manifest_sha256=manifest_sha,
        qa_references=[f'{reference}/qa_notes/{i}' for i in range(len(item['qa_notes']))],
        qa_notes=list(item['qa_notes']), reused_from=reused,
        # Reuse is authorised by verify_reuse/OWNER_DECISION, not by the manifest text.
        reuse_exception_reference=(f'{reference}/reuse_exception' if item.get('reuse_exception')
                                   else OWNER_DECISION['reference']) if reused else None,
        reuse_exception_note=item.get('reuse_exception') if reused else None,
        ssd_facts_reference=None, generation_model=None, generation_actor=None,
        generation_time=None, original_visual_basis=None),
        current_binding=dict(sku=f"P{binding['code']}", offer_id=binding['offer_id'],
            configuration_id=binding['configuration_id'], revision=binding['revision'],
            case_product_code=binding['case_product_code'],
            visual_basis=binding['visual_basis'], review_basis=binding['review_basis']))


def require_apply_env(environment=None):
    """Every write entry point checks the apply switch, not only the CLI."""
    if (os.environ if environment is None else environment).get('POPCORN_EXISTING_MEDIA_IMPORT_APPLY') != '1':
        raise PermissionError('POPCORN_EXISTING_MEDIA_IMPORT_APPLY=1 이 필요합니다')


def request_id(manifest_sha, code, original_sha):
    return str(uuid5(NAMESPACE, f'{manifest_sha}:{code}:{original_sha}'))


def _row(conn, request):
    from sqlalchemy import text
    found = conn.execute(text('SELECT job_id,configuration_id,visual_basis,status,selected,asset,origin_kind '
                              'FROM pc_media_jobs WHERE request_id=:r FOR UPDATE'), dict(r=request)).mappings().first()
    return dict(found) if found else None


def _verified(conn, auth, principal, item, raw, manifest_sha, force_select, skus):
    """(binding, None) or (None, reason) on this transaction: current binding, then
    verify_reuse and verify_registration. Called before every write and upload."""
    from api.pc_existing_media_import import Denied
    binding, reason = current_binding(conn, product_code(item), item)
    if reason:
        return None, reason
    subject = reuse_subject(item, raw, manifest_sha, binding, force_select, skus)
    try:
        auth.verify_reuse(subject, principal, conn)
        auth.verify_registration(subject, principal, conn)
    except Denied:
        return None, '재사용 권한 확인 거부'
    return binding, None


def apply_one(engine, objects, item, raw, manifest_sha, auth, principal, select=True, force_select=False,
              new_job=uuid4, skus=()):
    """Returns (state, detail). Authority and the current binding are re-checked on
    the insert transaction, right before the upload, inside the ready transaction
    and inside the selection transaction; a change at any point stops the item."""
    from sqlalchemy import text
    from api.pc_media import NOTICE
    from api.pc_existing_media_import import canonical
    require_apply_env()
    code, request = product_code(item), request_id(manifest_sha, product_code(item), item['original_sha256'])
    actor = principal.actor
    with engine.begin() as conn:
        binding, reason = _verified(conn, auth, principal, item, raw, manifest_sha, False, skus)
        if reason:
            return 'skipped', reason
        row = _row(conn, request)
        if row is None:
            job = str(new_job())
            conn.execute(text('INSERT INTO pc_media_jobs(job_id,request_id,configuration_id,visual_basis,review_basis,'
                'snapshot,model,actor,origin_kind,import_provenance,status,phase,selected) VALUES '
                "(:j,:r,:id,:v,:b,CAST(:s AS jsonb),NULL,:a,'existing_import',CAST(:p AS jsonb),'running','storage',false)"),
                dict(j=job, r=request, id=binding['configuration_id'], v=binding['visual_basis'],
                     b=binding['review_basis'], s=canonical(binding['snapshot']), a=actor,
                     p=canonical(provenance(item, manifest_sha, binding, principal,
                                            selectable(binding, force_select) if select else None))))
            row = dict(job_id=job, configuration_id=binding['configuration_id'],
                       visual_basis=binding['visual_basis'], status='running', selected=False,
                       asset=None, origin_kind='existing_import')
        elif row['origin_kind'] != 'existing_import' or row['configuration_id'] != binding['configuration_id']:
            return 'skipped', '같은 요청번호의 다른 작업 존재'
        elif row['visual_basis'] != binding['visual_basis']:
            return 'skipped', '이전 등록 이후 구성 근거 변경 · 확인 필요'
    job = str(row['job_id'])
    if row['status'] != 'ready':
        # No network inside a transaction: check, close, upload, then re-check before ready.
        with engine.begin() as conn:
            binding, reason = _verified(conn, auth, principal, item, raw, manifest_sha, False, skus)
        if reason or binding['visual_basis'] != row['visual_basis']:
            return 'stopped', job + ' (업로드 전 중단: ' + (reason or '구성 근거 변경') + ')'
        receipt = objects.create_or_verify(job, raw)
        if receipt.sha256 != hashlib.sha256(raw).hexdigest() or receipt.size != len(raw):
            return 'failed', '클라우드 저장 확인 불일치'
        asset = dict(asdict(receipt), notice=NOTICE)
        with engine.begin() as conn:
            binding, reason = _verified(conn, auth, principal, item, raw, manifest_sha, False, skus)
            if reason or binding['visual_basis'] != row['visual_basis']:
                return 'stopped', job + ' (완료 처리 전 중단: ' + (reason or '구성 근거 변경') + ')'
            done = conn.execute(text("UPDATE pc_media_jobs SET status='ready',phase='complete',error=NULL,"
                "asset=CAST(:a AS jsonb),updated_at=now() WHERE job_id=:j AND origin_kind='existing_import' "
                "AND status<>'ready'"), dict(a=canonical(asset), j=job)).rowcount
            if done != 1:
                return 'failed', '등록 상태가 중간에 바뀜'
    if not select:
        return 'registered', job
    with engine.begin() as conn:
        binding, reason = current_binding(conn, code, item)
        if reason:
            return 'registered', job + ' (선택 보류: ' + reason + ')'
        if binding['visual_basis'] != row['visual_basis']:
            return 'registered', job + ' (선택 보류: 구성 근거 변경)'
        mode = selectable(binding, force_select)
        if mode is None:
            return 'registered_unselected', job + ' (선택 보류: ' + _texts(binding['mismatch']) + ')'
        binding, reason = _verified(conn, auth, principal, item, raw, manifest_sha, mode == 'forced', skus)
        if reason:
            return 'registered_unselected', job + ' (선택 보류: ' + reason + ')'
        chosen = conn.execute(text("SELECT job_id,visual_basis,status FROM pc_media_jobs "
                                   "WHERE configuration_id=:id AND selected FOR UPDATE"),
                              dict(id=binding['configuration_id'])).mappings().first()
        if chosen and str(chosen['job_id']) == job:
            return 'selected', job
        if chosen and chosen['status'] == 'ready' and chosen['visual_basis'] == binding['visual_basis']:
            return 'registered', job + ' (기존 대표 이미지 유지)'
        conn.execute(text('UPDATE pc_media_jobs SET selected=false WHERE configuration_id=:id AND selected'),
                     dict(id=binding['configuration_id']))
        conn.execute(text('UPDATE pc_media_jobs SET selected=true,updated_at=now() WHERE job_id=:j'), dict(j=job))
    return ('selected_by_decision' if mode == 'forced' else 'selected'), job


def _dry(engine, item, raw, manifest_sha, auth, principal, select, force_select, skus=()):
    from api.pc_existing_media_import import Denied
    with engine.connect() as conn:
        try:
            binding, reason = current_binding(conn, product_code(item), item)
            if reason:
                return 'skipped', reason
            mode = selectable(binding, force_select)
            if auth is not None:
                try:
                    subject = reuse_subject(item, raw, manifest_sha, binding, mode == 'forced', skus)
                    auth.verify_reuse(subject, principal, conn)
                    auth.verify_registration(subject, principal, conn)
                except Denied:
                    return 'skipped', '재사용 권한 확인 거부'
        finally:
            conn.rollback()
    if not select or mode is None:
        return 'would_register_only', _texts(binding['mismatch']) or '선택 안 함'
    if mode == 'forced':
        return 'would_select_by_decision', _texts(binding['mismatch'])
    return 'would_select', binding['configuration_id']


def run(archive, *, engine, objects=None, apply=False, operator_id=None, only=(), select=True,
        force_select=False, out=print):
    manifest_sha, items = load_manifest(archive)
    skus = {str(i.get('configuration_id')) for i in items if isinstance(i, dict)}
    rows, counts = [], {}
    auth = principal = None
    if operator_id is not None:
        auth = authority(engine, operator_id)
        try:
            principal = auth.principal()
        except Exception:
            raise PermissionError('활성 owner 계정만 적용할 수 있습니다') from None
    elif apply:
        raise PermissionError('--operator-id 가 필요합니다')
    if apply:
        require_apply_env()
    for item in items:
        code = product_code(item)
        if only and code not in only:
            continue
        path = Path(archive) / 'originals' / f"{item.get('configuration_id')}.png"
        raw = path.read_bytes() if code is not None and path.is_file() else None
        reason = archive_reason(item, raw)
        if reason:
            # A broken file is reported only; it is never registered or forced.
            state, detail = ('file_error' if file_reason(item, raw) else 'skipped'), reason
        elif not apply:
            state, detail = _dry(engine, item, raw, manifest_sha, auth, principal, select, force_select, skus)
        else:
            try:
                state, detail = apply_one(engine, objects, item, raw, manifest_sha, auth, principal, select=select,
                                          force_select=force_select, skus=skus)
            except Exception as error:   # one item must not stop the batch; reason is reported
                state, detail = 'failed', type(error).__name__
        counts[state] = counts.get(state, 0) + 1
        rows.append(dict(product_code=code, state=state, detail=detail))
        out(f'P{code}\t{state}\t{detail}')
    out('합계 ' + ' · '.join(f'{k} {v}' for k, v in sorted(counts.items())) + f' (manifest {len(items)}건)')
    return dict(manifest_sha256=manifest_sha, counts=counts, items=rows)


def main(argv=None, environment=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', type=Path, required=True, help='manifest.json 과 originals/ 가 있는 폴더')
    parser.add_argument('--apply', action='store_true', help='실제 등록(기본은 조회만)')
    parser.add_argument('--operator-id', type=int, help='--apply 시 활성 owner 운영자 번호')
    parser.add_argument('--only', type=int, action='append', default=[], help='이 상품번호만(반복 가능)')
    parser.add_argument('--no-select', action='store_true', help='등록만 하고 대표 선택은 하지 않음')
    parser.add_argument('--force-select', action='store_true',
                        help='구성 차수·케이스가 원본과 달라도 대표로 선택(기본은 등록만)')
    parser.add_argument('--report', type=Path, help='결과 JSON 저장 경로')
    args = parser.parse_args(argv)
    environment = os.environ if environment is None else environment
    if args.apply and (environment.get('POPCORN_EXISTING_MEDIA_IMPORT_APPLY') != '1' or not args.operator_id):
        parser.error('--apply 는 POPCORN_EXISTING_MEDIA_IMPORT_APPLY=1 과 --operator-id 가 필요합니다')
    from api.db import engine
    objects = None
    if args.apply:
        from api.pc_existing_media_import import GcsObjects
        objects = GcsObjects()
    result = run(args.archive, engine=engine, objects=objects, apply=args.apply,
                 operator_id=args.operator_id, only=set(args.only), select=not args.no_select, force_select=args.force_select)
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
