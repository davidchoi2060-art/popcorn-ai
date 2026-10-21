"""기존 승인 PC 25개: CPU쿨러 123395 -> 121846 교체 · 새 대표 사진 · 재승인 (2026-10-21 사장님 「사진 다시 만들 때 같이」).

■ 왜
  몰이 이 25개의 CPU쿨러를 [ABKO] 자이로스 120X4 FRGB 블랙(123395)에서 [JIUSHARK] JF120R Emerald RGB 블랙(121846)으로
  바꿨다(db/migrations/data/mall_parts_20261021.json · public_configuration=true 25개). 승인 구성·대표 사진은 옛 쿨러 그대로였고,
  0171 이 몰 구성 원문 쿨러칸을 승인 구성에 맞춰 일부러 되돌려 두었다. 코덱스가 새 쿨러로 대표 사진을 다시 만들었다
  (db/migrations/data/remake25_20261021/full-manifest25.csv).

■ 무엇을 하나 — 기존 승인 모듈을 그대로 부른다(직접 승인 UPDATE 없음)
  0. 부품 121846   설명 행이 없으면 초안을 만든다(tools/build_part_explanations 규칙 · 몰 원문 사양만) · 몰 사진을 받아
                   전용 저장소에 올린다(tools/prepare_product_images 와 같은 자르기) · 설명 승인 · 사진 승인.
  1. 구성마다      «한 트랜잭션»(REPEATABLE READ): 이력 남김 -> 쿨러 줄만 121846 으로 -> 몰 원문 쿨러칸(0170 데이터) ->
                   추천 검토 승인(copy·price) -> 새 대표 사진 등록·선택(existing_import) -> 공개 재승인 -> 고객 화면 판정 확인.
                   어느 하나라도 실패하면 그 구성은 통째로 되돌린다 — 고객 화면에서 승인 설명·사진이 빠지는 틈이 없다.
  드라이런은 같은 일을 다 해 보고 되돌린다(저장소 업로드만 남는다 — 내용 주소 키라 다시 올려도 같다).

■ 하지 않는 것
  다른 슬롯·설명 문구·가격·오퍼는 건드리지 않는다. 쿨러가 123395 가 아닌 구성, 공개 승인이 지금 유효하지 않은 구성은 건너뛴다.

실행: 드라이런·상태 조회는 API 안의 내부 경로(api/internal_remake25.py · 127.0.0.1 직접 접속만)를 러너가 부른다
(.github/workflows/remake25.yml · 결과는 data/remake25-report 가지). 실제 반영은 마이그레이션이 배포 때 한 번 부른다
(서버 env 를 읽은 popcorn 계정) — 결과는 .cache/remake25/report-apply.json 에 남고 상태 조회가 같이 돌려준다.
"""
from __future__ import annotations

import csv
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CODES = [90675, 90678, 90687, 90691, 92805, 93454, 96311, 96988, 97000, 98149, 99025, 99413, 100866,
         103732, 110785, 113840, 121227, 121228, 121257, 121262, 121265, 121290, 121499, 121508, 121513]
OLD, NEW = 123395, 121846
NS = UUID('5b0f3c1e-7a42-4d6b-9e18-2c7a1f0d4e93')
DATA = ROOT / 'db' / 'migrations' / 'data' / 'remake25_20261021'
MANIFEST = DATA / 'full-manifest25.csv'
MALL_PARTS = ROOT / 'db' / 'migrations' / 'data' / 'mall_parts_20261021.json'
# API 서비스는 ProtectSystem=strict · PrivateTmp 라 쓸 수 있는 곳이 .cache 뿐이다(deploy/popcorn-api.service).
WORK = Path(os.environ.get('POPCORN_REMAKE25_WORK', str(ROOT / '.cache' / 'remake25')))
PNG_URL = 'https://raw.githubusercontent.com/davidchoi2060-art/popcorn-ai/data/remake25/{code}.png'
PREPARED_AT = '2026-10-21T12:00:00+00:00'
REFS = ['project-chat:cmsg_012k6fnspU3tgfYTTB56KTuDJ5eHJoGjMXfk52rRcLco43',   # 「사진 다시 만들 때 같이」
        'project-chat:cmsg_012k6fnspU3tgfYTTB56KTuDNQJz2TUcc2Ta3LVtSDYvBe',   # 「사진 25개 작업은 별도로 유지 … A/B 질문 불필요」
        'project-chat:cmsg_012k6fnspU3tgfYTTB56KTuDCtETQEhoZF9WbCEmM8fQws',   # 코덱스 최종 25장 납품
        'thread:cmsg_012k6fnspU3tgfYTTB56KTuDLB7bUAHKZVTkiGggx8GZfd']   # 사장님 「허락..」 (사장님 계정으로 재승인 기록)
NOTE = ('2026-10-21 사장님 지시 「사진 다시 만들 때 같이」: 몰이 바꾼 CPU쿨러 123395 -> 121846 교체, 코덱스 재제작 대표 사진 반영, '
        '쿨러 외 구성·설명·가격 변동 없음 · 원문 ' + ' '.join(r.split(':', 1)[1] for r in REFS))


def rid(*parts):
    return str(uuid5(NS, ':'.join(str(p) for p in parts)))


def manifest():
    raw = MANIFEST.read_bytes()
    rows = {int(r['product_code']): r for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))}
    if sorted(rows) != sorted(CODES) or any(r['cooler_code'] != str(NEW) for r in rows.values()):
        raise RuntimeError('manifest_scope_mismatch')
    return hashlib.sha256(raw).hexdigest(), rows


def png(code, row):
    path = WORK / 'in' / f'{code}.png'
    if path.exists():
        raw = path.read_bytes()
    else:   # 코덱스 납품 원본은 데이터 가지에 있다(리포 main 을 무겁게 하지 않는다) · 해시로 확인한다
        import requests
        r = requests.get(PNG_URL.format(code=code), timeout=(10, 60))
        r.raise_for_status()
        raw = r.content
        if hashlib.sha256(raw).hexdigest() == row['sha256']:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    if hashlib.sha256(raw).hexdigest() != row['sha256'] or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError(f'png_sha_mismatch {code}')
    return raw


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- storage (create-only, content-checked)
class Storage:
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


# ---------------------------------------------------------------- part 121846
def part_source(conn):
    from sqlalchemy import text
    row = conn.execute(text('SELECT product_code,product_name,spec_source_text,status,part_type FROM products '
                            'WHERE product_code=:c'), dict(c=NEW)).mappings().first()
    if not row or row['status'] != '판매중' or not (row['spec_source_text'] or '').strip():
        raise RuntimeError(f'part_source_unavailable {dict(row) if row else None}')
    return dict(row)


def part_content(src, asset):
    from tools.build_part_explanations import ROLES, clean, extract
    from api.product_name import remove_discount_label
    name = remove_discount_label(clean(src['product_name']))
    facts = extract('COOLER', src['spec_source_text'])
    if not facts:
        raise RuntimeError('part_facts_empty')
    role, caution = ROLES['COOLER']
    url = f'https://www.popcornpc.co.kr/shop/product_detail.html?pd_no={NEW}'
    return dict(name=name, slot='COOLER', summary=' · '.join(f"{f['label']} {f['value']}" for f in facts[:3]),
                role=role, facts=facts, highlights=[f"{f['label']}: {f['value']}" for f in facts[:3]],
                cautions=[caution], image_url=f'https://www.popcornpc.co.kr/data/pimg/{NEW // 1000}/{NEW}_600.jpg',
                image_caption='판매처 등록 이미지', image_source_url=url,
                sources=[dict(id='merchant', kind='merchant', title='팝콘PC 관리자 상품 사양', url=url,
                              observed_at='2026-10-21T21:00:00+09:00')],
                review_issues=[],
                questions=[dict(question='이 부품은 어떤 역할을 하나요?', answer=role),
                           dict(question='선택할 때 무엇을 확인하나요?', answer=caution)],
                usage_note='전체 PC의 용도 적합성과 선택 이유는 고객 조건 및 전체 구성 평가 후 제공',
                image_asset=asset)


def part_asset(storage, out):
    """몰 사진 -> 원본·자른 상세·썸네일. 키는 원본 sha 로 정해져 다시 돌려도 같다."""
    from tools.prepare_product_images import prepare
    folder = WORK / 'part'
    r = prepare(dict(product_code=NEW, name=str(NEW),
                     merchant_image_url=f'https://www.popcornpc.co.kr/data/pimg/{NEW // 1000}/{NEW}_600.jpg'), folder)
    if r.get('status') != 'ready':
        raise RuntimeError(f"part_photo_unavailable {r.get('status')} {r.get('error')}")
    types = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif'}
    for key in (r['original_key'], r['detail_key'], r['thumbnail_key']):
        out[key] = storage.put(key, (folder / key).read_bytes(), types[key.rsplit('.', 1)[1]])
    asset = {k: r[k] for k in ('original_key', 'detail_key', 'thumbnail_key', 'sha256', 'detail_sha256', 'crop_box',
                               'original_size', 'detail_size', 'crop_mode')}
    asset.update(bucket=storage.bucket, prepared_at=PREPARED_AT)
    return asset


def ensure_part(conn, actor, rights, asset, image_reader):
    """121846 설명 행(없으면 초안) + 설명 승인 + 사진 승인을 caller 트랜잭션에서. 결과 단계 목록."""
    from sqlalchemy import text
    from api import part_explanation_approval as part
    from api import part_photo_approval as photo
    from api.part_explanations import fingerprint
    from tools.approve_pc_publication_bulk import photo_reader
    steps = []
    src = part_source(conn)
    exists = conn.execute(text('SELECT status FROM product_explanations WHERE source_product_code=:c'), dict(c=NEW)).scalar()
    if exists is None:
        content = part_content(src, asset)
        snapshot = dict(name=src['product_name'], spec=src['spec_source_text'])
        conn.execute(text('''INSERT INTO product_explanations(source_product_code,product_code,content,source_snapshot,source_fingerprint)
            VALUES(:c,:c,CAST(:content AS jsonb),CAST(:snap AS jsonb),:fp)'''),
                     dict(c=NEW, content=json.dumps(content, ensure_ascii=False),
                          snap=json.dumps(snapshot, ensure_ascii=False), fp=fingerprint(snapshot['name'], snapshot['spec'])))
        steps.append('explanation_draft_created')
    cur = part.read_current(conn, NEW)
    if not cur['allowed']:
        row = part._read(conn, NEW)
        if cur['state'] != 'unapproved' or cur['event_seq'] != 0:
            raise RuntimeError(f"part_explanation_not_first_time {cur['state']} {cur.get('reason')}")
        part.approve(conn, NEW, expected_seq=0, expected_basis=part.basis(row),
                     request_id=rid('explain', NEW, part.basis(row)), note=NOTE, actor=actor)
        steps.append('explanation_approved')
    reader = photo_reader(rights)
    pcur = photo.read_current(conn, NEW, provenance_reader=reader, image_reader=image_reader,
                              business_rights_reference=rights)
    if not pcur['allowed']:
        if pcur['state'] != 'unapproved' or pcur['event_seq'] != 0:
            raise RuntimeError(f"part_photo_not_first_time {pcur['state']} {pcur.get('reason')}")
        basis = photo.basis(part._read(conn, NEW))
        photo.approve(conn, NEW, expected_seq=0, expected_basis=basis, request_id=rid('photo', NEW, basis, rights),
                      note=NOTE, actor=actor, provenance_reader=reader, image_reader=image_reader,
                      business_rights_reference=rights)
        steps.append('photo_approved')
    return steps


# ---------------------------------------------------------------- one configuration
def spec_text_swap(conn, code):
    from sqlalchemy import text
    m = _module(ROOT / 'db' / 'migrations' / 'versions' / '0170_mall_parts_20261021.py', 'm0170_remake25')
    item = next(p for p in json.loads(MALL_PARTS.read_text(encoding='utf-8'))['products'] if p['code'] == code)
    if not item['public_configuration'] or [c['slot'] for c in item['changes']] != ['CPU쿨러']:
        raise RuntimeError('mall_change_scope_mismatch')
    ch = item['changes'][0]
    sst = conn.execute(text('SELECT spec_source_text FROM products WHERE product_code=:c FOR UPDATE'), dict(c=code)).scalar()
    if sst and m._key(ch['new']) in m._key(sst):
        return 'already'
    new = m._swap(sst or '', 'CPU쿨러', m._key(ch['old']), ch['new'])
    if new is None:
        raise RuntimeError('mall_text_cooler_cell_not_found')
    conn.execute(text('UPDATE products SET spec_source_text=:t WHERE product_code=:c'), dict(t=new, c=code))
    return 'swapped'


def configuration(conn, code, actor, rights, image_reader, storage, mrow, msha, uploads):
    from sqlalchemy import text
    from api import pc_customer_publication as publication
    from api import pc_media
    from api.pc_configuration_copy import digest, explanation_digest
    from api.pc_configuration_parts_edit import bom_hash
    from api.pc_configuration_review import load_review, save_review, ReviewEdit, Finding
    from api.pc_publication_source_reader import make_source_reader
    from api import part_explanation_approval as part
    identity = f'P{code}'
    reader = make_source_reader(image_reader=image_reader, business_rights_reference=rights)
    out = dict(product_code=code, configuration_id=identity, steps=[])
    before = publication.read_current(conn, identity, source_reader=reader)
    out['before'] = {k: before[k] for k in ('revision', 'state', 'event_seq', 'reason')}
    if not before['allowed']:
        raise RuntimeError(f"publication_not_current {before['state']} {before.get('reason')}")
    config, parts, offers, state = load_review(conn, identity, lock=True)
    if config['status'] != 'approved':
        raise RuntimeError(f"config_not_approved {config['status']}")
    coolers = [p for p in parts if p['slot'] == 'COOLER' and not p['pseudo']]
    if len(coolers) != 1 or coolers[0]['explanation_code'] != OLD or any(p['explanation_code'] == NEW for p in parts):
        raise RuntimeError('cooler_part_unexpected ' + json.dumps([(p['slot'], p['explanation_code']) for p in coolers]))
    cooler = coolers[0]
    new_row = part._read(conn, NEW)
    # 1. 이력 + 쿨러 줄 교체 + 구성 차수
    edit = dict(kind='parts', operator_id=actor['operator_id'], name=actor.get('name', ''), mode='update', source_id=identity,
                source_revision=config['revision'],
                changes=[dict(slot='COOLER', ordinal=cooler['ordinal'], before=OLD, after=NEW, reason='mall_change_20261021')])
    conn.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:rev,CAST(:s AS jsonb))'),
                 dict(id=identity, rev=config['revision'],
                      s=json.dumps(dict(config, parts=parts, offers=offers, edit=edit), ensure_ascii=False, default=str)))
    conn.execute(text('''UPDATE pc_configuration_parts SET source_code=:sc,explanation_code=:ec,explanation_hash=:eh
        WHERE configuration_id=:id AND ordinal=:o AND explanation_code=:old'''),
                 dict(sc=str(NEW), ec=NEW, eh=explanation_digest(new_row), id=identity, o=cooler['ordinal'], old=OLD))
    content = copy.deepcopy(config['content'])
    content['_admin_bom_edit'] = dict(review_required=True, parent_id=identity, parent_revision=config['revision'],
                                      changed_slots=['COOLER'], price_basis='몰 판매가 그대로(쿨러 교체는 몰이 같은 가격으로 바꾼 구성)',
                                      copy_status='needs_review', edit=edit)
    new_parts = [dict(p) for p in conn.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),
                                               dict(id=identity)).mappings()]
    conn.execute(text('''UPDATE pc_configurations SET bom_fingerprint=:bom,content=CAST(:content AS jsonb),content_hash=:hash,
        copy_hash=:copy,status='review_required',revision=revision+1,updated_at=now() WHERE configuration_id=:id'''),
                 dict(bom=bom_hash(new_parts), content=json.dumps(content, ensure_ascii=False),
                      hash=digest(dict(content=content, parts=new_parts, offers=offers)),
                      copy=digest(dict(content=content, parts=new_parts)), id=identity))
    out['steps'].append('cooler_swapped')
    # 2. 몰 구성 원문 쿨러칸
    out['steps'].append('mall_text_' + spec_text_swap(conn, code))
    # 3. 추천 검토 승인
    _, _, _, st = load_review(conn, identity, lock=True)
    out['review_required'] = sorted(st['required'])
    if st['blockers'] or st['recommendation_state'] == 'hold':
        raise RuntimeError('review_blocked ' + ' / '.join(st['blockers'] or ['hold']))
    other = set(st['required']) - {'copy', 'price'}
    if other:
        raise RuntimeError('review_manual_findings ' + ', '.join(sorted(other)))
    findings = {k: Finding(confirmed=True, evidence=(
        f'{v} 확인 · 구성 {identity} · 차수 {st["revision"]} · 검토 근거 {st["basis"]} · 바뀐 것은 CPU쿨러 {OLD}->{NEW} 한 줄뿐, '
        f'상품 설명에 쿨러 언급 없음, 오퍼·판매가 그대로 · 원문 {" ".join(r.split(":", 1)[1] for r in REFS)}'))
        for k, v in st['required'].items()}
    save_review(conn, identity, ReviewEdit(revision=st['revision'], basis=st['basis'], action='approve',
                                           findings=findings, note=NOTE), actor)
    out['steps'].append('review_approved')
    # 4. 새 대표 사진 (existing_import · 코덱스 납품 원본)
    s = pc_media.snapshot(conn, identity, lock=True)
    if s['errors']:
        raise RuntimeError('media_snapshot_errors ' + ' / '.join(s['errors']))
    raw = png(code, mrow)
    case = next(p for p in s['snapshot']['parts'] if p['slot'] == 'CASE')
    cur_config = conn.execute(text('SELECT revision FROM pc_configurations WHERE configuration_id=:id'), dict(id=identity)).scalar()
    job_id = rid('job', identity, mrow['sha256'], s['visual_basis'], s['basis'])
    key = f'pc-configurations/{job_id}/representative.png'
    uploads[key] = storage.put(key, raw, 'image/png')
    provenance = dict(version='pc-media-existing-import-v1',
        original=dict(source_sku=identity, original_revision=cur_config,
                      original_ref=f'codex:popcorn-image-remake25-return-20261021:products/{code}.png',
                      original_sha256=mrow['sha256'], manifest_sha256=msha,
                      qa_references=[REFS[2], 'repo:db/migrations/data/remake25_20261021/full-manifest25.csv'],
                      reused_from=None, reuse_exception_reference=None, ssd_facts_reference=None,
                      generation_model=None, generation_actor=None, generation_time=None, original_visual_basis=None),
        current_binding=dict(sku=identity, offer_id=identity, configuration_id=identity, revision=cur_config,
                             case_product_code=case['code'], visual_basis=s['visual_basis'], review_basis=s['basis']))
    conn.execute(text('UPDATE pc_media_jobs SET selected=false,updated_at=now() WHERE configuration_id=:id AND selected'), dict(id=identity))
    conn.execute(text('''INSERT INTO pc_media_jobs(job_id,request_id,configuration_id,visual_basis,review_basis,snapshot,model,actor,
        origin_kind,import_provenance,status,phase,asset,selected)
        VALUES(:j,:r,:id,:v,:b,CAST(:s AS jsonb),NULL,:a,'existing_import',CAST(:p AS jsonb),'ready','complete',CAST(:asset AS jsonb),true)'''),
                 dict(j=job_id, r=rid('request', job_id), id=identity, v=s['visual_basis'], b=s['basis'],
                      s=json.dumps(s['snapshot'], ensure_ascii=False), a=str(actor['operator_id']),
                      p=json.dumps(provenance, ensure_ascii=False),
                      asset=json.dumps(dict(bucket=storage.bucket, key=key, sha256=mrow['sha256'], notice=pc_media.NOTICE))))
    out['steps'].append('photo_selected')
    # 5. 공개 재승인
    cur = publication.read_current(conn, identity, source_reader=reader)
    if cur['publication_basis'] is None:
        raise RuntimeError(f"publication_evidence_unavailable {cur.get('reason')}")
    publication.approve(conn, identity, expected_seq=cur['event_seq'], revision=cur['revision'], review_basis=cur['basis'],
                        publication_basis=cur['publication_basis'], request_id=rid('publish', identity, cur['publication_basis']),
                        note=NOTE, actor=actor, source_reader=reader)
    after = publication.read_current(conn, identity, source_reader=reader)
    out['after'] = {k: after[k] for k in ('revision', 'state', 'event_seq', 'reason')}
    if not after['allowed']:
        raise RuntimeError(f"publication_not_allowed_after {after['state']} {after.get('reason')}")
    # 6. 고객 화면 판정(같은 스냅샷)
    from api.customer_pc_offer import _public_offer
    view = _public_offer(conn, code)
    view = view[0] if isinstance(view, tuple) else view
    pc = view.get('public_configuration') or {}
    cool = [p for p in pc.get('parts', []) if p.get('slot') == 'COOLER']
    out['customer'] = dict(photo=view.get('photo', {}).get('state'), cooler=[p.get('name') for p in cool],
                           cooler_photo=[(p.get('photo') or {}).get('url') for p in cool])
    if view.get('photo', {}).get('state') != 'available' or not pc or [str(NEW) in ((p.get('photo') or {}).get('url') or '') for p in cool] != [True]:
        raise RuntimeError('customer_view_unexpected ' + json.dumps(out['customer'], ensure_ascii=False))
    out['steps'].append('publication_approved')
    return out


# ---------------------------------------------------------------- run
def pick_actor(conn):
    """이 25개의 공개 승인을 마지막으로 한 활성 owner(한 명이어야 한다)."""
    from sqlalchemy import text
    ids = {r[0] for r in conn.execute(text('''SELECT DISTINCT ON (configuration_id) operator_id FROM pc_customer_publication_events
        WHERE configuration_id=ANY(:ids) AND action='approve' ORDER BY configuration_id,event_seq DESC'''),
                                         dict(ids=[f'P{c}' for c in CODES]))}
    if len(ids) != 1:
        raise RuntimeError(f'actor_ambiguous {sorted(ids)}')
    row = conn.execute(text('SELECT operator_id,name,role,status FROM admin_operators WHERE operator_id=:o'),
                       dict(o=ids.pop())).mappings().first()
    if not row or row['role'] != 'owner' or row['status'] != '활성':
        raise RuntimeError('actor_not_active_owner')
    return dict(row)


def run(engine, apply=False, image_reader=None, storage=None, only=None):
    from tools.approve_pc_publication_bulk import RIGHTS_ATTESTATION, RIGHTS_ENV
    if image_reader is None:
        from api.product_images import read_image as image_reader
    storage = storage or Storage()
    report = dict(mode='apply' if apply else 'dry-run', started=datetime.now(timezone.utc).isoformat(),
                  part={}, configurations=[], uploads={})
    rights = os.environ.get(RIGHTS_ENV, '')
    if rights != RIGHTS_ATTESTATION:
        raise RuntimeError(f'{RIGHTS_ENV} mismatch')
    msha, mrows = manifest()
    report['manifest_sha256'] = msha
    for code, row in mrows.items():
        png(code, row)
    with engine.connect() as conn:
        actor = pick_actor(conn)
    report['actor'] = dict(operator_id=actor['operator_id'], role=actor['role'])
    asset = part_asset(storage, report['uploads'])
    report['part']['asset'] = {k: asset[k] for k in ('detail_key', 'sha256', 'crop_mode')}

    def tx():
        return engine.connect().execution_options(isolation_level='REPEATABLE READ')

    if apply:
        conn = tx()
        try:
            with conn.begin():
                report['part']['steps'] = ensure_part(conn, actor, rights, asset, image_reader)
        finally:
            conn.close()
    for code in (only or CODES):
        conn = tx()
        item = dict(product_code=code)
        try:
            trans = conn.begin()
            try:
                if not apply:
                    item['part_steps'] = ensure_part(conn, actor, rights, asset, image_reader)
                item.update(configuration(conn, code, actor, rights, image_reader, storage, mrows[code], msha, report['uploads']))
                item['result'] = 'committed' if apply else 'would_commit'
                if apply:
                    trans.commit()
                else:
                    trans.rollback()
            except Exception as error:
                trans.rollback()
                item['result'] = 'failed'
                item['error'] = f'{type(error).__name__}: {getattr(error, "detail", None) or error}'
                item['trace'] = traceback.format_exc(limit=6)[-1500:]
        finally:
            conn.close()
        report['configurations'].append(item)
    report['summary'] = {k: sum(i['result'] == k for i in report['configurations'])
                         for k in ('committed', 'would_commit', 'failed')}
    report['finished'] = datetime.now(timezone.utc).isoformat()
    return report


def status(engine, image_reader=None):
    """읽기만: 25개 지금 쿨러 · 공개 판정 · 선택된 대표 사진 sha · 몰 원문 쿨러칸 + 121846 승인 상태 + 마지막 반영 결과."""
    from sqlalchemy import text
    from tools.approve_pc_publication_bulk import RIGHTS_ATTESTATION, RIGHTS_ENV
    from api import pc_customer_publication as publication
    from api.pc_publication_source_reader import make_source_reader
    if image_reader is None:
        from api.product_images import read_image as image_reader
    reader = make_source_reader(image_reader=image_reader, business_rights_reference=os.environ.get(RIGHTS_ENV, ''))
    _, mrows = manifest()
    out = dict(rights_env_ok=os.environ.get(RIGHTS_ENV, '') == RIGHTS_ATTESTATION, configurations=[])
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with conn.begin():
            conn.execute(text('SET TRANSACTION READ ONLY'))
            out['part'] = dict(conn.execute(text('''SELECT e.status,e.approved_by,e.approved_at,
                (SELECT count(*) FROM part_explanation_approval_events WHERE source_product_code=:c) AS explain_events,
                (SELECT count(*) FROM part_photo_approval_events WHERE source_product_code=:c) AS photo_events
                FROM product_explanations e WHERE e.source_product_code=:c'''), dict(c=NEW)).mappings().first() or {})
            out['part_product'] = dict(conn.execute(text('SELECT status,left(spec_source_text,300) AS spec FROM products '
                                                         'WHERE product_code=:c'), dict(c=NEW)).mappings().first() or {})
            for code in CODES:
                identity = f'P{code}'
                item = dict(product_code=code)
                try:
                    item['cooler'] = [r[0] for r in conn.execute(text("SELECT explanation_code FROM pc_configuration_parts "
                        "WHERE configuration_id=:id AND slot='COOLER'"), dict(id=identity))]
                    item['config'] = dict(conn.execute(text('SELECT status,revision FROM pc_configurations WHERE configuration_id=:id'),
                                                       dict(id=identity)).mappings().first() or {})
                    job = conn.execute(text("SELECT asset->>'sha256' FROM pc_media_jobs WHERE configuration_id=:id AND selected AND status='ready'"),
                                       dict(id=identity)).scalar()
                    item['photo'] = 'new' if job == mrows[code]['sha256'] else ('old' if job else None)
                    sst = conn.execute(text('SELECT spec_source_text FROM products WHERE product_code=:c'), dict(c=code)).scalar() or ''
                    item['mall_text'] = 'JF120R' if 'JF120R' in sst else ('ABKO' if '자이로스' in sst else '?')
                    cur = publication.read_current(conn, identity, source_reader=reader)
                    item['publication'] = {k: cur[k] for k in ('revision', 'state', 'event_seq', 'reason')}
                except Exception as error:
                    item['error'] = f'{type(error).__name__}: {getattr(error, "detail", None) or error}'
                out['configurations'].append(item)
    path = WORK / 'report-apply.json'
    if path.exists():
        out['apply_report'] = json.loads(path.read_text(encoding='utf-8'))
    return out


def run_safely(mode):
    """마이그레이션에서 부른다 — 무슨 일이 있어도 예외를 올리지 않는다(배포를 멈추지 않는다)."""
    WORK.mkdir(parents=True, exist_ok=True)
    os.chmod(WORK, 0o755)
    path = WORK / f'report-{mode}.json'
    try:
        from api.db import engine
        report = run(engine, apply=(mode == 'apply'))
    except Exception as error:
        report = dict(mode=mode, fatal=f'{type(error).__name__}: {error}', trace=traceback.format_exc(limit=8)[-3000:])
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    os.chmod(path, 0o644)
    return report


if __name__ == '__main__':
    mode = 'apply' if '--apply' in sys.argv else 'dry'
    print(json.dumps(run_safely(mode).get('summary'), ensure_ascii=False))
