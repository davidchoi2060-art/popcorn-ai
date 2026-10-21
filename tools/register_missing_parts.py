"""판매 PC 구성 부품 중 부품 설명 목록에 없는 것 등록 · 설명 승인 · 사진 승인 (2026-10-21 사장님 「신규 부품 추가된거 확인하고 넣으라고 했잖아」).

■ 왜
  판매 PC 322개의 몰 구성 부품 346종 중 189종이 공개 부품 설명(/api/part-explanations/{code})에 없었다
  (db/migrations/data/missing_parts_20261021.json · 121846 은 tools/remake25_cooler.py 가 따로 한다).
  설명이 없으면 부품 바꾸기·구성표 수정·승인 구성에서 그 부품을 고를 수 없다.

■ 무엇을 하나 — tools/remake25_cooler.py 의 ensure_part 와 같은 순서 · 같은 승인 모듈
  부품마다 «한 트랜잭션»: 설명 행이 없으면 초안(tools/build_part_explanations 규칙 · 몰 원문 사양만) ->
  설명 승인(api.part_explanation_approval) -> 몰 사진을 전용 저장소에 올리고 사진 승인(api.part_photo_approval).
  어느 하나라도 실패하면 그 부품만 통째로 되돌리고 이유를 남긴다. 처음 승인만 한다(되돌린 적 있는 것은 건너뛴다).

■ 하지 않는 것
  products 행을 만들거나 고치지 않는다 — 상품 행이 없거나 판매중이 아니거나 사양 원문이 없으면 건너뛴다.

실행: 연습(dry)·결과 조회는 러너가 api/internal_missing_parts.py(127.0.0.1 전용)를 부른다(.github/workflows/missing-parts.yml).
실제 반영은 배포 때 마이그레이션이 run_safely('apply') 를 한 번 부른다 — 결과 .cache/missing-parts/report-apply.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / 'db' / 'migrations' / 'data' / 'missing_parts_20261021.json'
# 2차분(0177): 몰 부품 상세 페이지에서 받은 자료로 남은 5개를 채운다 — 상품 행 신설(create)·
# 상품명 기준 사양 보충(spec_extra)·gif 사진(image_ext). 상품 행은 ai_candidate_yn 기본값(false)이라 추천 후보에 들어가지 않는다.
DATA_B = ROOT / 'db' / 'migrations' / 'data' / 'missing_parts_20261021b.json'
WORK = Path(os.environ.get('POPCORN_MISSING_PARTS_WORK', str(ROOT / '.cache' / 'missing-parts')))
SLOTS = {'프로세서(CPU)': 'CPU', 'CPU쿨러': 'COOLER', '메모리(RAM)': 'RAM', '메인보드': 'MB', '그래픽(VGA)': 'GPU',
         '초고속(SSD)': 'SSD', '케이스': 'CASE', '파워': 'POWER'}
NOTE = ('2026-10-21 사장님 지시 「신규 부품 추가된거 확인하고 넣으라고 했잖아」: 판매 PC 몰 구성 부품 중 부품 설명이 없던 것 '
        '등록 · 몰 원문 사양만 사용 · 원문 cmsg_012k6fnspU3tgfYTTB56KTuDGrJJPXgW9DaMJeCzxSAJ3U')


NS = UUID('9c2e51a4-3b7d-4f08-a6e1-5d0b7c48e219')
PREPARED_AT = '2026-10-21T13:00:00+00:00'   # 미래 시각이면 사진 승인이 거절한다(연습 때 14:00 전 29건 실패)


def rid(*parts):
    return str(uuid5(NS, ':'.join(str(p) for p in parts)))


class Storage:
    """전용 저장소에 «처음 올릴 때만» 쓴다 — 같은 키가 있으면 내용이 같은지 확인만 한다(tools/remake25_cooler.Storage 와 같다)."""
    def __init__(self):
        from api.pc_media import cloud_session
        from api.product_images import MEDIA_BUCKET
        self.session, self.bucket = cloud_session, MEDIA_BUCKET

    def put(self, key, raw, content_type):
        from urllib.parse import quote
        with self.session() as s:
            r = s.post(f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o',
                       params=dict(uploadType='media', name=key, ifGenerationMatch='0'), data=raw,
                       headers={'Content-Type': content_type}, timeout=(10, 60))
            if r.status_code == 412:
                r = s.get(f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{quote(key, safe="")}?alt=media',
                          timeout=(10, 60))
                r.raise_for_status()
                if hashlib.sha256(r.content).digest() != hashlib.sha256(raw).digest():
                    raise RuntimeError(f'storage_conflict {key}')
                return 'existing'
            r.raise_for_status()
            return 'uploaded'


def content(src, slot, code, asset, spec_extra='', image_ext='jpg'):
    from tools.build_part_explanations import ROLES, clean, extract
    from api.product_name import remove_discount_label
    name = remove_discount_label(clean(src['product_name']))
    facts = extract(slot, ' / '.join(x for x in (src['spec_source_text'], spec_extra) if x))
    if not facts:
        raise RuntimeError('part_facts_empty')
    role, caution = ROLES[slot]
    url = f'https://www.popcornpc.co.kr/shop/product_detail.html?pd_no={code}'
    return dict(name=name, slot=slot, summary=' · '.join(f"{f['label']} {f['value']}" for f in facts[:3]),
                role=role, facts=facts, highlights=[f"{f['label']}: {f['value']}" for f in facts[:3]],
                cautions=[caution], image_url=f'https://www.popcornpc.co.kr/data/pimg/{code // 1000}/{code}_600.{image_ext}',
                image_caption='판매처 등록 이미지', image_source_url=url,
                sources=[dict(id='merchant', kind='merchant', title='팝콘PC 관리자 상품 사양', url=url,
                              observed_at='2026-10-21T22:00:00+09:00')],
                review_issues=[],
                questions=[dict(question='이 부품은 어떤 역할을 하나요?', answer=role),
                           dict(question='선택할 때 무엇을 확인하나요?', answer=caution)],
                usage_note='전체 PC의 용도 적합성과 선택 이유는 고객 조건 및 전체 구성 평가 후 제공',
                image_asset=asset)


def asset_for(storage, code, out, image_ext='jpg'):
    from tools.prepare_product_images import prepare
    folder = WORK / 'img' / str(code)
    r = prepare(dict(product_code=code, name=str(code),
                     merchant_image_url=f'https://www.popcornpc.co.kr/data/pimg/{code // 1000}/{code}_600.{image_ext}'), folder)
    if r.get('status') != 'ready':
        raise RuntimeError(f"part_photo_unavailable {r.get('status')} {r.get('error')}")
    types = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif'}
    for key in (r['original_key'], r['detail_key'], r['thumbnail_key']):
        out[key] = storage.put(key, (folder / key).read_bytes(), types[key.rsplit('.', 1)[1]])
    asset = {k: r[k] for k in ('original_key', 'detail_key', 'thumbnail_key', 'sha256', 'detail_sha256', 'crop_box',
                               'original_size', 'detail_size', 'crop_mode')}
    asset.update(bucket=storage.bucket, prepared_at=PREPARED_AT)
    return asset


def one(conn, code, slot, actor, rights, image_reader, storage, uploads, extra=None):
    from sqlalchemy import text
    from api import part_explanation_approval as part
    from api import part_photo_approval as photo
    from api.part_explanations import fingerprint
    from tools.approve_pc_publication_bulk import photo_reader
    steps = []
    extra = extra or {}
    if extra.get('create'):
        c = extra['create']
        added = conn.execute(text('''INSERT INTO products(product_code,product_name,maker,part_type,category_group,status,
            sale_price,market_price,spec_source_text,data_origin) VALUES(:c,:n,:m,:t,'core_part','판매중',:p,:p,:s,'real')
            ON CONFLICT (product_code) DO NOTHING RETURNING product_code'''),
            dict(c=code, n=c['product_name'], m=c['maker'], t=c['part_type'], p=c['sale_price'],
                 s=c['spec_source_text'])).scalar()
        if added is not None:
            conn.execute(text('''INSERT INTO product_price_history(product_code,field,old_price,new_price,reason)
                VALUES(:c,'sale',NULL,:p,'mall_part_page_20261021')'''), dict(c=code, p=c['sale_price']))
            steps.append('product_row_created')
    src = conn.execute(text('SELECT product_code,product_name,spec_source_text,status FROM products WHERE product_code=:c'),
                       dict(c=code)).mappings().first()
    if not src:
        return 'skipped', ['no_product_row']
    if src['status'] != '판매중' or not (src['spec_source_text'] or '').strip():
        return 'skipped', [f"product_not_ready {src['status']}"]
    exists = conn.execute(text('SELECT status FROM product_explanations WHERE source_product_code=:c'), dict(c=code)).scalar()
    if exists is None:
        asset = asset_for(storage, code, uploads, extra.get('image_ext', 'jpg'))
        body = content(src, slot, code, asset, extra.get('spec_extra', ''), extra.get('image_ext', 'jpg'))
        snapshot = dict(name=src['product_name'], spec=src['spec_source_text'])
        conn.execute(text('''INSERT INTO product_explanations(source_product_code,product_code,content,source_snapshot,source_fingerprint)
            VALUES(:c,:c,CAST(:content AS jsonb),CAST(:snap AS jsonb),:fp)'''),
                     dict(c=code, content=json.dumps(body, ensure_ascii=False),
                          snap=json.dumps(snapshot, ensure_ascii=False), fp=fingerprint(snapshot['name'], snapshot['spec'])))
        steps.append('explanation_draft_created')
    cur = part.read_current(conn, code)
    if not cur['allowed']:
        if cur['state'] != 'unapproved' or cur['event_seq'] != 0:
            return 'skipped', [f"explanation_not_first_time {cur['state']} {cur.get('reason')}"]
        row = part._read(conn, code)
        part.approve(conn, code, expected_seq=0, expected_basis=part.basis(row),
                     request_id=rid('missing-explain', code, part.basis(row)), note=NOTE, actor=actor)
        steps.append('explanation_approved')
    reader = photo_reader(rights)
    pcur = photo.read_current(conn, code, provenance_reader=reader, image_reader=image_reader,
                              business_rights_reference=rights)
    if not pcur['allowed']:
        if pcur['state'] != 'unapproved' or pcur['event_seq'] != 0:
            raise RuntimeError(f"photo_not_first_time {pcur['state']} {pcur.get('reason')}")
        b = photo.basis(part._read(conn, code))
        photo.approve(conn, code, expected_seq=0, expected_basis=b, request_id=rid('missing-photo', code, b, rights),
                      note=NOTE, actor=actor, provenance_reader=reader, image_reader=image_reader,
                      business_rights_reference=rights)
        steps.append('photo_approved')
    return ('committed' if steps else 'already'), steps


def pick_actor(conn):
    """부품 설명을 가장 최근에 승인한 활성 owner."""
    from sqlalchemy import text
    row = conn.execute(text('''SELECT o.operator_id,o.name,o.role,o.status FROM part_explanation_approval_events e
        JOIN admin_operators o ON o.operator_id=e.operator_id
        WHERE e.action='approve' AND o.role='owner' AND o.status='활성' ORDER BY e.recorded_at DESC LIMIT 1''')).mappings().first()
    if not row:
        raise RuntimeError('actor_not_found')
    return dict(row)


def run(engine, apply=False, image_reader=None, storage=None, data_path=None):
    from tools.approve_pc_publication_bulk import RIGHTS_ATTESTATION, RIGHTS_ENV
    from api.customer_pc_offer import rights_reference
    if image_reader is None:
        from api.product_images import read_image as image_reader
    storage = storage or Storage()
    rights = rights_reference() or ''
    if rights != RIGHTS_ATTESTATION:
        raise RuntimeError(f'{RIGHTS_ENV} mismatch')
    data = json.loads((data_path or DATA).read_text(encoding='utf-8'))
    report = dict(mode='apply' if apply else 'dry-run', started=datetime.now(timezone.utc).isoformat(), parts=[], uploads={})
    with engine.connect() as conn:
        actor = pick_actor(conn)
    report['actor'] = dict(operator_id=actor['operator_id'], role=actor['role'])
    for p in data['parts']:
        slot = SLOTS.get(p['cate'])
        item = dict(code=p['code'], cate=p['cate'])
        if not slot:
            item.update(result='skipped', steps=['not_a_pc_slot'])
            report['parts'].append(item)
            continue
        conn = engine.connect().execution_options(isolation_level='REPEATABLE READ')
        try:
            trans = conn.begin()
            try:
                item['result'], item['steps'] = one(conn, p['code'], slot, actor, rights, image_reader, storage, report['uploads'], p)
                if apply:
                    trans.commit()
                else:
                    trans.rollback()
            except Exception as error:
                trans.rollback()
                item['result'] = 'failed'
                item['error'] = f'{type(error).__name__}: {getattr(error, "detail", None) or error}'[:500]
        finally:
            conn.close()
        report['parts'].append(item)
    report['summary'] = {k: sum(i['result'] == k for i in report['parts']) for k in ('committed', 'already', 'skipped', 'failed')}
    report['finished'] = datetime.now(timezone.utc).isoformat()
    return report


def run_safely(mode='apply', batch=''):
    """마이그레이션에서 부른다 — 예외를 올리지 않는다(배포를 멈추지 않는다)."""
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o755)
    path = WORK / f'report-{mode}{batch}.json'
    try:
        from api.db import engine
        report = run(engine, apply=(mode == 'apply'), data_path=DATA_B if batch == 'b' else None)
    except Exception as error:
        report = dict(fatal=f'{type(error).__name__}: {error}', trace=traceback.format_exc(limit=8)[-3000:])
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    os.chmod(path, 0o644)
    return report


def read_report(batch=''):
    path = WORK / f'report-apply{batch}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(missing=True)


if __name__ == '__main__':
    print(json.dumps(run_safely('apply' if '--apply' in sys.argv else 'dry').get('summary'), ensure_ascii=False))
