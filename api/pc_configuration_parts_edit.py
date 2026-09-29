"""Admin BOM drafts: explicit replacements, server-priced previews, versioned saves."""
import copy
import hashlib
import json
import re
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from .auth import current_operator
from .db import engine
from .part_explanations import is_current
from .pc_configuration_copy import digest, explanation_digest, read_configuration
from .taxonomy import SLOT_LABELS, slot_of

router = APIRouter()


class Replacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ordinal: StrictInt = Field(ge=0)
    code: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(ge=1, le=16)


class PartsEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: StrictInt = Field(gt=0)
    offer_id: str = Field(min_length=1, max_length=100)
    replacements: list[Replacement] = Field(min_length=1, max_length=16)
    mode: Literal['update', 'new'] = 'update'
    preview_token: str | None = Field(default=None, max_length=64)


PART_SQL = '''SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status,
 p.sale_price,p.part_type FROM product_explanations e
 JOIN products p ON p.product_code=e.product_code'''


def part_view(row):
    content = row['content']
    return dict(code=row['source_product_code'], name=content.get('name') or row['product_name'],
                slot=content.get('slot'), unit_price=row['sale_price'],
                facts=content.get('facts', []), summary=content.get('summary', ''),
                image_url=f"/api/product-images/{row['source_product_code']}/detail",
                sale_status=row['sale_status'], source_current=is_current(row),
                review_issues=content.get('review_issues', []))


@router.get('/api/admin/pc-configurations/{identity}/part-candidates')
def candidates(identity: str, ordinal: int = Query(ge=0), q: str = Query('', max_length=100),
               offset: int = Query(0, ge=0), limit: int = Query(12, ge=1, le=30)):
    with engine.connect() as c:
        part = c.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id AND ordinal=:n'),
                         dict(id=identity, n=ordinal)).mappings().first()
        if not part or part['pseudo']:
            raise HTTPException(422, '교체 가능한 부품 행이 아닙니다.')
        where = ''' WHERE e.content->>'slot'=:slot AND p.status='판매중' AND p.sale_price>0
          AND (:q='' OR p.product_name ILIKE :search OR e.source_product_code::text=:q)'''
        args = dict(slot=part['slot'], q=q.strip(), search='%'+q.strip()+'%', offset=offset, limit=limit)
        total = c.execute(text('SELECT count(*) FROM ('+PART_SQL+where+') candidates'), args).scalar_one()
        rows = c.execute(text(PART_SQL+where+' ORDER BY p.sale_price,e.source_product_code LIMIT :limit OFFSET :offset'), args).mappings()
        return dict(total=total, offset=offset, limit=limit, items=[part_view(r) for r in rows],
                    scope='설명이 등록된 판매중 부품 · 호환성은 별도 검토')


def bom_hash(parts):
    signature = sorted((p['slot'], str(p['source_code']), p['quantity']) for p in parts
                       if not (p['slot'] == 'GPU' and p['pseudo']))
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def capacity(value):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*\(?\s*(GB|TB)\s*\)?\s*', str(value), re.I)
    return float(match[1]) * (1000 if match[2].upper() == 'TB' else 1) if match else None


def compute_preview(prior, parts, offers, replacements, rows, offer_id):
    """Pure calculation; unchanged components are never repriced."""
    offer = next((o for o in offers if o['offer_id'] == offer_id), None)
    if not offer:
        raise HTTPException(422, '가격 기준이 되는 판매 구성을 선택해 주세요.')
    ordinals = [r.ordinal for r in replacements]
    if len(ordinals) != len(set(ordinals)):
        raise HTTPException(422, '같은 부품 행을 중복 변경할 수 없습니다.')
    by_ordinal = {p['ordinal']: p for p in parts}
    updated = copy.deepcopy(parts)
    changes = []
    for r in replacements:
        old = by_ordinal.get(r.ordinal)
        if not old or old['pseudo']:
            raise HTTPException(422, '교체 가능한 부품 행이 아닙니다.')
        if str(r.code) == str(old['source_code']) and r.quantity == old['quantity']:
            continue
        new_row, old_row = rows.get(r.code), rows.get(old['explanation_code'])
        if not new_row or new_row['sale_status'] != '판매중':
            raise HTTPException(409, '선택한 부품의 판매 상태가 변경되었습니다. 후보를 다시 선택해 주세요.')
        if new_row['content'].get('slot') != old['slot'] or slot_of(new_row['part_type']) != old['slot']:
            raise HTTPException(422, '같은 종류의 부품만 교체할 수 있습니다.')
        if old['slot'] not in ('RAM','SSD') and r.quantity != old['quantity']:
            raise HTTPException(422, '이 부품의 수량은 기존 구성과 동일하게 유지해 주세요.')
        if not is_current(new_row) or new_row['content'].get('review_issues'):
            raise HTTPException(409, '선택한 부품의 설명·사양을 먼저 갱신해 주세요.')
        if not old_row or not old_row['sale_price'] or not new_row['sale_price'] or old_row['sale_price'] <= 0 or new_row['sale_price'] <= 0:
            raise HTTPException(422, '기존·교체 부품의 현재 판매가가 모두 있어야 차액을 계산할 수 있습니다.')
        before, after = part_view(old_row), part_view(new_row)
        before.update(quantity=old['quantity'], total=old_row['sale_price'] * old['quantity'])
        after.update(quantity=r.quantity, total=new_row['sale_price'] * r.quantity)
        changes.append(dict(ordinal=r.ordinal, slot=old['slot'], label=SLOT_LABELS.get(old['slot'], old['slot']),
                            before=before, after=after, delta=after['total'] - before['total']))
        p = next(p for p in updated if p['ordinal'] == r.ordinal)
        p.update(source_code=str(r.code), explanation_code=r.code, quantity=r.quantity,
                 explanation_hash=explanation_digest(new_row),
                 selection_note='관리자 변경 구성 · 선택 이유 및 호환성 재검토 필요')
    if not changes:
        raise HTTPException(422, '변경된 부품이 없습니다.')
    delta = sum(x['delta'] for x in changes)
    total = offer['price_snapshot'] + delta
    if total <= 0:
        raise HTTPException(422, '계산한 구성 금액을 확인해 주세요.')
    fingerprint = bom_hash(updated)
    derived = {}
    changed_slots = {x['slot'] for x in changes}
    for slot, key, label in [('RAM','ram_gb','상품 용량'),('SSD','storage_gb','용량')]:
        if slot not in changed_slots:
            continue
        values = []
        for p in updated:
            if p['slot'] != slot or p['pseudo']:
                continue
            fields = {f['label']:f['value'] for f in rows.get(p['explanation_code'],{}).get('content',{}).get('facts',[])}
            value = capacity(fields.get(label))
            values.append(None if value is None else value*p['quantity'])
        derived[key] = sum(values) if values and all(v is not None for v in values) else None
    for x in changes:
        if x['slot'] in ('CPU','GPU'):
            derived[x['slot'].lower()] = x['after']['name']
    token = digest(dict(revision=prior['revision'], offer=offer, changes=changes, bom=fingerprint,
                        evidence={str(k):explanation_digest(v) for k,v in rows.items()}))
    return dict(changes=changes, base_price=offer['price_snapshot'], delta=delta, total=total,
                price_note='기존 완제품 기준가 + 변경 부품의 현재 개별 판매가 차액 · 예상 금액',
                assembly_note='기존 조립·서비스 포함 조건 유지 · 조립비 추가 가산 없음',
                original_price_note=offer['payload'].get('price_note', ''),
                preview_token=token, bom_fingerprint=fingerprint, parts=updated, derived_facts=derived)


def prepare(c, identity, body, lock=False):
    if lock:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    prior = c.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id'+(' FOR UPDATE' if lock else '')),
                      dict(id=identity)).mappings().first()
    if not prior:
        raise HTTPException(404, '조립PC 구성 없음')
    if prior['revision'] != body.revision or prior['status'] == 'retired':
        raise HTTPException(409, '제품군이 변경되었거나 보관되었습니다. 최신 내용을 다시 열어 주세요.')
    parts = [dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),dict(id=identity)).mappings()]
    offers = [dict(r) for r in c.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY offer_id'),dict(id=identity)).mappings()]
    codes = sorted({r.code for r in body.replacements} | {p['explanation_code'] for p in parts if not p['pseudo']})
    rows = {r['source_product_code']:dict(r) for r in c.execute(text(PART_SQL+' WHERE e.source_product_code=ANY(:codes) ORDER BY e.source_product_code'+(' FOR SHARE OF e,p' if lock else '')), dict(codes=codes)).mappings()}
    result = compute_preview(prior, parts, offers, body.replacements, rows, body.offer_id)
    duplicate = c.execute(text('SELECT configuration_id FROM pc_configurations WHERE bom_fingerprint=:bom AND configuration_id<>:id'),
                          dict(bom=result['bom_fingerprint'],id=identity)).scalar()
    result['duplicate_id'] = duplicate
    return dict(prior), parts, offers, result


@router.post('/api/admin/pc-configurations/{identity}/parts-preview')
def preview(identity: str, body: PartsEdit):
    with engine.connect() as c:
        return prepare(c, identity, body)[3]


def revised_content(prior, preview, identity, mode):
    content = copy.deepcopy(prior['content'])
    # Never claim that old copy/facts still describe a different BOM.
    invalid = {'CPU':('cpu','entry','high','work','pro'), 'GPU':('gpu','vram_gb','discrete'),
               'RAM':('ram_gb',), 'SSD':('storage_gb',), 'CASE':('form','color')}
    for change in preview['changes']:
        for key in invalid.get(change['slot'], ()):
            content.setdefault('facts', {})[key] = None
    content['_admin_bom_edit'] = dict(review_required=True, parent_id=prior['configuration_id'],
        parent_revision=prior['revision'], changed_slots=[x['slot'] for x in preview['changes']],
        price_basis=preview['price_note'], copy_status='needs_review')
    content['similar_build'] = None
    content.setdefault('facts',{}).update(preview.get('derived_facts',{}))
    if mode == 'new':
        content['source'] = '신규'
        content['source_ids'] = [identity]
        content['title'] = content.get('title','조립PC')[:191] + ' · 변경 구성'
    return content


def save_parts(c, identity, body, actor):
    prior, old_parts, offers, result = prepare(c, identity, body, lock=True)
    if not body.preview_token or body.preview_token != result['preview_token']:
        raise HTTPException(409, '가격·부품 정보가 변경되었습니다. 변경 내용 확인을 다시 진행해 주세요.')
    if result['duplicate_id']:
        raise HTTPException(409, f"같은 구성의 제품군이 있습니다: {result['duplicate_id']}. 중복 등록하지 않았습니다.")
    target = identity if body.mode == 'update' else 'A'+uuid4().hex[:16].upper()
    content = revised_content(prior, result, target, body.mode)
    edit = dict(kind='parts', operator_id=actor['operator_id'], name=actor.get('name',''),
                mode=body.mode, source_id=identity, source_revision=prior['revision'], changes=result['changes'])
    content['_admin_bom_edit']['edit'] = edit
    if body.mode == 'update':
        snapshot = dict(prior, parts=old_parts, offers=offers, edit=edit)
        c.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:rev,CAST(:s AS jsonb))'),
                  dict(id=identity,rev=prior['revision'],s=json.dumps(snapshot,ensure_ascii=False,default=str)))
    selected_offer = next(o for o in offers if o['offer_id'] == body.offer_id)
    payload = dict(id='ADMIN-'+target, price=result['total'], base_price=result['total'], assembly_fee_added=0,
                   price_basis='관리자 변경 구성 예상가', price_note=result['price_note']+' · '+result['assembly_note'],
                   original_offer=selected_offer, quote_only=True, customer_publishable=False)
    parts = [{k:v for k,v in p.items() if k!='configuration_id'} for p in result['parts']]
    values = dict(id=target, bom=result['bom_fingerprint'], content=json.dumps(content,ensure_ascii=False),
                  hash=digest(dict(content=content,parts=parts,offers=[payload])),
                  copy_hash=digest(dict(content=content,parts=parts)), observed=date.today())
    if body.mode == 'update':
        c.execute(text('''UPDATE pc_configurations SET bom_fingerprint=:bom,content=CAST(:content AS jsonb),
          content_hash=:hash,copy_hash=:copy_hash,status='review_required',revision=revision+1,
          observed_date=:observed,updated_at=now() WHERE configuration_id=:id'''), values)
        for table in ('pc_configuration_parts','pc_configuration_offers'):
            c.execute(text(f'DELETE FROM {table} WHERE configuration_id=:id'), dict(id=target))
    else:
        c.execute(text('''INSERT INTO pc_configurations(configuration_id,bom_fingerprint,content,content_hash,copy_hash,status,observed_date)
           VALUES(:id,:bom,CAST(:content AS jsonb),:hash,:copy_hash,'review_required',:observed)'''),values)
    for p in parts:
        c.execute(text('''INSERT INTO pc_configuration_parts(configuration_id,ordinal,slot,source_code,explanation_code,quantity,pseudo,selection_note,explanation_hash)
          VALUES(:id,:ordinal,:slot,:source_code,:explanation_code,:quantity,:pseudo,:selection_note,:explanation_hash)'''),dict(id=target,**p))
    c.execute(text('INSERT INTO pc_configuration_offers(offer_id,configuration_id,price_snapshot,payload) VALUES(:offer,:id,:price,CAST(:payload AS jsonb))'),
              dict(offer=payload['id'],id=target,price=result['total'],payload=json.dumps(payload,ensure_ascii=False,default=str)))
    return dict(configuration_id=target, mode=body.mode, detail=read_configuration(c,target))


@router.put('/api/admin/pc-configurations/{identity}/parts')
def update_parts(identity: str, body: PartsEdit, request: Request):
    actor = current_operator()
    if not actor or actor.get('role') not in ('operator','owner'):
        raise HTTPException(403, '구성을 저장할 권한이 없습니다.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '같은 관리자 화면에서 저장해 주세요.')
    with engine.begin() as c:
        return save_parts(c, identity, body, actor)
