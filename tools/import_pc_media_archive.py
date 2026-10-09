"""Batch-register the existing 104 assembled-PC example images as representative images.

The archive (manifest.json + originals/P{product_code}.png) was generated on
2026-09-29 and lives on the development PC. Before this tool nothing linked it to
pc_media_jobs, so customer screens kept showing "이미지 준비 중".

Per item, without any generation call:
  1. archive check   PNG bytes match manifest sha256/size; QA notes exist;
                     images reused from another configuration are skipped
                     (those need an individual decision, see PR #22).
  2. current check   the registered P offer is on sale, image requirements are met,
                     configuration revision == manifest db_configuration_revision,
                     current CASE product == manifest case_code.
  3. apply           insert an origin_kind='existing_import' job bound to the
                     CURRENT visual/review basis, upload create-only to the private
                     bucket (same key layout as generated jobs), mark ready, and
                     select it unless a current ready representative is already
                     selected (a stale selection is replaced).

Default is a read-only dry run. --apply needs POPCORN_EXISTING_MEDIA_IMPORT_APPLY=1
and --operator-id of an active owner; that owner is recorded as the actor.
Re-running is safe: the request id is derived from manifest+product+image hash.
"""
import argparse
from dataclasses import asdict
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
    if raw is None:
        return '원본 파일 없음'
    if not raw.startswith(PNG) or not 8 < len(raw) <= MAX_BYTES:
        return 'PNG 형식·크기 불일치'
    if item.get('original_sha256') != hashlib.sha256(raw).hexdigest() or item.get('original_bytes') != len(raw):
        return '원본 해시·크기가 manifest 와 다름'
    if item.get('generated_original') != f"originals/{item['configuration_id']}.png":
        return 'manifest 원본 경로 불일치'
    notes = item.get('qa_notes')
    if not isinstance(notes, list) or not notes or not all(isinstance(n, str) and n.strip() for n in notes):
        return 'QA 기록 없음'
    if item.get('reused_from'):
        return '다른 구성 이미지 재사용 · 개별 확인 필요'
    if type(item.get('db_configuration_revision')) is not int or not str(item.get('case_code', '')).isdigit():
        return 'manifest 구성 차수·케이스 정보 없음'
    return None


def current_binding(conn, code, item):
    """(binding, None) when the configuration still matches the archived image."""
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
    if bound['revision'] != item['db_configuration_revision']:
        return None, f"구성 차수 변경({item['db_configuration_revision']}→{bound['revision']}) · 새 이미지 필요"
    current = snapshot(conn, identity)
    if current['errors']:
        return None, '이미지 조건 미충족: ' + ', '.join(current['errors'])
    cases = [p for p in current['snapshot']['parts'] if p['slot'] == 'CASE']
    if len(cases) != 1 or str(cases[0]['code']) != str(item['case_code']):
        return None, '케이스 변경 · 새 이미지 필요'
    return dict(code=code, configuration_id=identity, offer_id=bound['offer_id'],
                revision=bound['revision'], case_product_code=int(cases[0]['code']),
                visual_basis=current['visual_basis'], review_basis=current['basis'],
                snapshot=current['snapshot']), None


def provenance(item, manifest_sha, binding):
    reference = f"manifest:sha256:{manifest_sha}#items/{item['configuration_id']}"
    return dict(version=VERSION, original=dict(
        source_sku=item['configuration_id'], original_revision=item['db_configuration_revision'],
        original_ref=item['generated_original'], original_sha256=item['original_sha256'],
        manifest_sha256=manifest_sha,
        qa_references=[f'{reference}/qa_notes/{i}' for i in range(len(item['qa_notes']))],
        qa_notes=list(item['qa_notes']), reused_from=None, reuse_exception_reference=None,
        ssd_facts_reference=None, generation_model=None, generation_actor=None,
        generation_time=None, original_visual_basis=None),
        current_binding=dict(sku=f"P{binding['code']}", offer_id=binding['offer_id'],
            configuration_id=binding['configuration_id'], revision=binding['revision'],
            case_product_code=binding['case_product_code'],
            visual_basis=binding['visual_basis'], review_basis=binding['review_basis']))


def request_id(manifest_sha, code, original_sha):
    return str(uuid5(NAMESPACE, f'{manifest_sha}:{code}:{original_sha}'))


def owner_actor(conn, operator_id):
    from sqlalchemy import text
    row = conn.execute(text('SELECT role,status FROM admin_operators WHERE operator_id=:o'),
                       dict(o=operator_id)).mappings().first()
    if not row or row['role'] != 'owner' or row['status'] != '활성':
        raise PermissionError('활성 owner 계정만 적용할 수 있습니다')
    return f'operator:{operator_id}'


def _row(conn, request):
    from sqlalchemy import text
    found = conn.execute(text('SELECT job_id,configuration_id,visual_basis,status,selected,asset,origin_kind '
                              'FROM pc_media_jobs WHERE request_id=:r FOR UPDATE'), dict(r=request)).mappings().first()
    return dict(found) if found else None


def apply_one(engine, objects, item, raw, manifest_sha, actor, select=True, new_job=uuid4):
    """Returns (state, detail). Every DB step re-reads the current binding."""
    from sqlalchemy import text
    from api.pc_media import NOTICE
    from api.pc_existing_media_import import canonical
    code, request = product_code(item), request_id(manifest_sha, product_code(item), item['original_sha256'])
    with engine.begin() as conn:
        binding, reason = current_binding(conn, code, item)
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
                     p=canonical(provenance(item, manifest_sha, binding))))
            row = dict(job_id=job, configuration_id=binding['configuration_id'],
                       visual_basis=binding['visual_basis'], status='running', selected=False,
                       asset=None, origin_kind='existing_import')
        elif row['origin_kind'] != 'existing_import' or row['configuration_id'] != binding['configuration_id']:
            return 'skipped', '같은 요청번호의 다른 작업 존재'
        elif row['visual_basis'] != binding['visual_basis']:
            return 'skipped', '이전 등록 이후 구성 근거 변경 · 새 이미지 필요'
    job = str(row['job_id'])
    if row['status'] != 'ready':
        receipt = objects.create_or_verify(job, raw)
        if receipt.sha256 != hashlib.sha256(raw).hexdigest() or receipt.size != len(raw):
            return 'failed', '클라우드 저장 확인 불일치'
        asset = dict(asdict(receipt), notice=NOTICE)
        with engine.begin() as conn:
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
    return 'selected', job


def run(archive, *, engine, objects=None, apply=False, operator_id=None, only=(), select=True, out=print):
    manifest_sha, items = load_manifest(archive)
    rows, counts = [], {}
    actor = None
    if apply:
        with engine.connect() as conn:
            actor = owner_actor(conn, operator_id)
    for item in items:
        code = product_code(item)
        if only and code not in only:
            continue
        path = Path(archive) / 'originals' / f"{item.get('configuration_id')}.png"
        raw = path.read_bytes() if code is not None and path.is_file() else None
        reason = archive_reason(item, raw)
        if reason:
            state, detail = 'skipped', reason
        elif not apply:
            with engine.connect() as conn:
                binding, reason = current_binding(conn, code, item)
                conn.rollback()
            state, detail = ('ready_to_import', binding['configuration_id']) if not reason else ('skipped', reason)
        else:
            try:
                state, detail = apply_one(engine, objects, item, raw, manifest_sha, actor, select=select)
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
                 operator_id=args.operator_id, only=set(args.only), select=not args.no_select)
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
