"""Empty-BOM creation. Preview and save share current prices and review evidence."""
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from typing import Literal
from sqlalchemy import text

from .auth import current_operator
from .db import engine
from .taxonomy import SLOT_LABELS, slot_of
from .part_explanations import is_current
from .pc_configuration_copy import digest, explanation_digest
from .pc_configuration_parts_edit import bom_hash, capacity, part_view
from .pc_configuration_review import assess
from .pc_review_specs import specs_for_review
from .pc_cooling_plan import cooling_plan
from .orders import ASSEMBLY_FEE
from .timeutil import KST

router = APIRouter()
SLOTS = ('CPU', 'GPU', 'RAM', 'SSD', 'MB', 'COOLER', 'POWER', 'CASE')
REQUIRED = {'CPU', 'RAM', 'SSD', 'MB', 'POWER', 'CASE'}
SELECT = '''SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status,
 p.sale_price,p.part_type,p.stock_qty FROM product_explanations e
 JOIN products p ON p.product_code=e.product_code'''


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(ge=1, le=16)
    source: Literal['sale', 'owned'] = 'sale'


class Build(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=180)
    parts: list[Selection] = Field(min_length=1, max_length=20)
    integrated_gpu: bool = False
    bundled_cooler: bool = False
    request_id: str = Field(pattern=r'^[A-Za-z0-9-]{16,64}$')
    preview_token: str | None = Field(default=None, max_length=64)


def permission(request):
    actor = current_operator()
    if not actor or actor.get('role') not in ('operator', 'owner'):
        raise HTTPException(403, '신규 구성을 저장할 권한이 없습니다.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '같은 관리자 화면에서 요청해 주세요.')
    return actor


@router.get('/api/admin/pc-builder/parts')
def candidates(slot: Literal['CPU','GPU','RAM','SSD','MB','COOLER','POWER','CASE'],
               q: str = Query('', max_length=100), source: Literal['sale','owned']='sale',
               offset: int=Query(0,ge=0), limit: int=Query(20,ge=1,le=50)):
    where = """ WHERE e.content->>'slot'=:slot AND p.status='판매중' AND p.sale_price>0
      AND (:q='' OR p.product_name ILIKE :search OR e.source_product_code::text=:q)
      AND (:source!='owned' OR p.stock_qty>0)"""
    args = dict(slot=slot,q=q.strip(),search='%'+q.strip()+'%',source=source,offset=offset,limit=limit)
    with engine.connect() as c:
        total=c.execute(text('SELECT count(*) FROM ('+SELECT+where+') x'),args).scalar_one()
        rows=c.execute(text(SELECT+where+' ORDER BY p.sale_price,e.source_product_code LIMIT :limit OFFSET :offset'),args).mappings()
        items=[dict(part_view(r),stock_qty=r['stock_qty'],source=source) for r in rows]
    return dict(items=items,total=total,offset=offset,limit=limit,
        stock_note='보유 부품은 DB 재고 기준이며 실사·예약·출고 가능 확인은 별도입니다.')


def calculate(body, rows, specs, rules):
    """Pure validation/calculation, also used inside the saving transaction."""
    if not body.title.strip():
        raise HTTPException(422,'상품명을 입력해 주세요.')
    codes=[p.code for p in body.parts]
    if len(set(codes))!=len(codes):
        raise HTTPException(422,'같은 부품은 행을 중복 추가하지 말고 수량을 변경해 주세요.')
    parts=[]; lines=[]; count={}
    for ordinal,s in enumerate(body.parts):
        r=rows.get(s.code)
        if not r or r['sale_status']!='판매중' or not r['sale_price'] or r['sale_price']<=0:
            raise HTTPException(409,'판매중인 부품과 유효한 현재 판매가를 다시 확인해 주세요.')
        slot=slot_of(r['part_type'])
        if slot not in SLOTS or r['content'].get('slot')!=slot:
            raise HTTPException(422,'조립 가능한 부품 종류와 설명 분류를 확인해 주세요.')
        if not is_current(r):
            raise HTTPException(409,'선택 부품의 원문과 설명이 변경됐습니다. 부품 자료를 갱신해 주세요.')
        count[slot]=count.get(slot,0)+s.quantity
        if slot not in ('RAM','SSD') and count[slot]!=1:
            raise HTTPException(422,'CPU·보드·GPU·쿨러·파워·케이스는 각각 한 개를 선택해 주세요.')
        if s.source=='owned' and (r.get('stock_qty') or 0)<s.quantity:
            raise HTTPException(409,'보유 부품의 DB 재고 수량이 부족합니다. 판매 부품 기준으로 다시 확인해 주세요.')
        parts.append(dict(ordinal=ordinal,slot=slot,source_code=str(s.code),explanation_code=s.code,
            quantity=s.quantity,pseudo=False,selection_note='운영자 신규 구성 · '+('DB 보유 부품' if s.source=='owned' else '판매 DB 부품'),
            explanation_hash=explanation_digest(r)))
        lines.append(dict(part_view(r),quantity=s.quantity,total=r['sale_price']*s.quantity,source=s.source,stock_qty=r['stock_qty']))
    missing=REQUIRED-set(count)
    if missing:
        raise HTTPException(422,'필수 부품 누락: '+', '.join(SLOT_LABELS[k] for k in SLOTS if k in missing))
    cpu=next(p for p in parts if p['slot']=='CPU')
    if body.integrated_gpu:
        if count.get('GPU') or specs.get(cpu['explanation_code'],{}).get('cpu_gpu') is not True:
            raise HTTPException(422,'내장그래픽 지원 근거가 있는 CPU를 선택하고 별도 GPU를 제거해 주세요.')
    elif not count.get('GPU'):
        raise HTTPException(422,'그래픽카드를 선택하거나 내장그래픽 사용을 확인해 주세요.')
    if body.bundled_cooler:
        if count.get('COOLER') or not cooling_plan(parts,rows,specs)['verified_bundle']:
            raise HTTPException(422,'기본 쿨러 포함 근거가 확인된 CPU를 선택하고 별도 쿨러를 제거해 주세요.')
    elif not count.get('COOLER'):
        raise HTTPException(422,'쿨러를 선택하거나 CPU 기본 쿨러 사용을 확인해 주세요.')
    facts=dict(cpu=rows[cpu['explanation_code']]['content'].get('name'),gpu='내장그래픽' if body.integrated_gpu else None)
    for slot,key,label in [('RAM','ram_gb','상품 용량'),('SSD','storage_gb','용량')]:
        values=[]
        for p in parts:
            if p['slot']==slot:
                fields={f['label']:f['value'] for f in rows[p['explanation_code']]['content'].get('facts',[])}
                v=capacity(fields.get(label)); values.append(None if v is None else v*p['quantity'])
        facts[key]=sum(values) if all(v is not None for v in values) else None
    for p in parts:
        if p['slot']=='GPU': facts['gpu']=rows[p['explanation_code']]['content'].get('name')
    content=dict(title=body.title.strip(),intro='운영자가 부품을 선택한 신규 구성입니다. 상품 설명과 장착 조건을 검토해 주세요.',
        source='신규',source_ids=[],facts=facts,benefits=[],checks=[],faq=[],scene='',
        _admin_bom_edit=dict(review_required=True,copy_status='needs_review'),
        _admin_creation=dict(request_id=body.request_id,parts=[s.model_dump() for s in body.parts],
            integrated_gpu=body.integrated_gpu,bundled_cooler=body.bundled_cooler))
    subtotal=sum(x['total'] for x in lines); total=subtotal+ASSEMBLY_FEE
    offer=dict(offer_id='PREVIEW',price_snapshot=total,payload=dict(price=total,base_price=subtotal,
        assembly_fee_added=ASSEMBLY_FEE,price_note=f'현재 개별 부품 판매가 합계 + 조립비 {ASSEMBLY_FEE:,}원 · 예상 금액',
        quote_only=True,customer_publishable=False))
    config=dict(configuration_id='PREVIEW',revision=1,status='review_required',content=content)
    review=assess(config,parts,[offer],rows,specs,rules)
    conflicts=[x for x in review['checks'] if x['state']=='fail']
    token=digest(dict(input=body.model_dump(exclude={'preview_token'}),rows=rows,specs=specs,rules=rules,fee=ASSEMBLY_FEE))
    return dict(parts=parts,lines=lines,content=content,offer=offer,subtotal=subtotal,assembly_fee=ASSEMBLY_FEE,total=total,
        review=review,can_save=bool(rules) and not conflicts,conflicts=conflicts,preview_token=token,
        bom_fingerprint=bom_hash(parts),price_note=offer['payload']['price_note'])


def prepare(c,body,lock=False):
    if lock: c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    codes=[s.code for s in body.parts]
    rows={r['source_product_code']:dict(r) for r in c.execute(text(SELECT+' WHERE e.source_product_code=ANY(:codes) ORDER BY e.source_product_code'+(' FOR SHARE OF e,p' if lock else '')),dict(codes=codes)).mappings()}
    product_codes=[r['product_code'] for r in rows.values()]
    by_product={r['product_code']:dict(r) for r in c.execute(text('SELECT * FROM product_specs WHERE product_code=ANY(:codes) ORDER BY product_code'+(' FOR SHARE' if lock else '')),dict(codes=product_codes)).mappings()}
    rules=[dict(r) for r in c.execute(text('SELECT * FROM compat_rules WHERE active ORDER BY rule_id'+(' FOR SHARE' if lock else ''))).mappings()]
    result=calculate(body,rows,specs_for_review(rows,by_product),rules)
    duplicate=c.execute(text('SELECT configuration_id,content FROM pc_configurations WHERE bom_fingerprint=:bom'),dict(bom=result['bom_fingerprint'])).mappings().first()
    result['duplicate_id']=duplicate['configuration_id'] if duplicate else None
    return result,duplicate


@router.post('/api/admin/pc-builder/preview')
def preview(body:Build,request:Request):
    permission(request)
    with engine.connect() as c: return prepare(c,body)[0]


def save_build(c,body,actor):
    r,duplicate=prepare(c,body,lock=True)
    if duplicate:
        creation=duplicate['content'].get('_admin_creation',{})
        if creation.get('request_id')==body.request_id and creation.get('input_hash')==digest(body.model_dump(exclude={'preview_token'})):
            return dict(configuration_id=duplicate['configuration_id'],status='review_required',reused=True)
        raise HTTPException(409,'같은 부품·수량 구성의 제품군이 이미 있습니다: '+duplicate['configuration_id'])
    if not body.preview_token or body.preview_token!=r['preview_token']:
        raise HTTPException(409,'부품·가격·재고·검사 근거가 바뀌었습니다. 구성 확인을 다시 진행해 주세요.')
    if not r['can_save']:
        raise HTTPException(422,'등록된 호환 불일치 또는 호환 규칙 누락을 먼저 해결해 주세요.')
    identity='A'+uuid4().hex[:16].upper()
    content=r['content']; content['source_ids']=[identity]
    content['_admin_creation'].update(actor=dict(operator_id=actor['operator_id'],name=actor.get('name','')),
        input_hash=digest(body.model_dump(exclude={'preview_token'})),preview_basis=r['preview_token'],review=r['review'])
    offer=r['offer']; offer['offer_id']='ADMIN-'+identity
    offer['payload']['id']=offer['offer_id']
    c.execute(text('''INSERT INTO pc_configurations(configuration_id,bom_fingerprint,content,content_hash,copy_hash,status,observed_date)
        VALUES(:id,:bom,CAST(:content AS jsonb),:hash,:copy_hash,'review_required',:observed)'''),
        dict(id=identity,bom=r['bom_fingerprint'],content=json.dumps(content,ensure_ascii=False,default=str),
            hash=digest(dict(content=content,parts=r['parts'],offers=[offer])),copy_hash=digest(dict(content=content,parts=r['parts'])),
            observed=datetime.now(KST).date()))
    for p in r['parts']:
        c.execute(text('''INSERT INTO pc_configuration_parts(configuration_id,ordinal,slot,source_code,explanation_code,quantity,pseudo,selection_note,explanation_hash)
            VALUES(:id,:ordinal,:slot,:source_code,:explanation_code,:quantity,:pseudo,:selection_note,:explanation_hash)'''),dict(id=identity,**p))
    c.execute(text('INSERT INTO pc_configuration_offers(offer_id,configuration_id,price_snapshot,payload) VALUES(:offer,:id,:price,CAST(:payload AS jsonb))'),
        dict(offer=offer['offer_id'],id=identity,price=r['total'],payload=json.dumps(offer['payload'],ensure_ascii=False)))
    # Initial audit snapshot; later edits preserve revision 1 through the existing history workflow.
    return dict(configuration_id=identity,status='review_required',reused=False,total=r['total'],customer_publishable=False)


@router.post('/api/admin/pc-builder/save')
def save(body:Build,request:Request):
    actor=permission(request)
    with engine.begin() as c: return save_build(c,body,actor)
