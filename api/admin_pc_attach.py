"""구성표 없는 판매중 완제품 PC 에 구성표 붙이기 (2026-10-11 부품 상품화 5단계).

몰에서 파는 완제품 PC 중 구성표(BOM)가 없는 것은 고객 카드에 사진·부품 설명이 없고 부품 바꾸기도
못 한다(`api/part_catalog.NO_BOM_SQL` · 개발 서버 120221 · 113837 · 92802). 운영자가 「신규 조립PC 생성」의
부품 고르기를 그대로 써서 그 상품에 구성표를 붙인다. 부품 판정·가격·호환 검사·미리보기 근거는
`api/admin_pc_builder.prepare` 한 곳이다.

■ 무엇이 생기나
  구성(pc_configurations, 검토 대기) + 부품 줄 + 몰 상품 연결 오퍼 `P{상품번호}`.
  오퍼 금액은 그 상품의 지금 판매가(`products.sale_price`)다 — 구성 부품 합계가 아니다(몰에서 파는 값).
  연결 규약은 기존 몰 구성과 같다(content.source='기존' · source_ids 에 `P{상품번호}` ·
  `pc_configuration_copy.read_sold_offer_configuration` 이 확인하는 형식). 고객 공개는 기존 검토·공개
  절차를 그대로 거친다 — 붙이는 것만으로 고객에게 보이지 않는다.
■ 기존 값은 바꾸지 않는다 — 이미 구성표가 있는 상품이면 409.
"""
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, StrictInt
from sqlalchemy import text

from .admin_pc_builder import Build, permission, prepare
from .db import engine
from .pc_configuration_copy import digest
from .product_name import display_name
from .timeutil import KST

router = APIRouter()

TARGET_SQL = '''SELECT p.product_code, p.product_name, p.sale_price, p.status, p.part_type,
  EXISTS (SELECT 1 FROM pc_configuration_offers o WHERE o.offer_id = 'P' || p.product_code::text) AS bound
  FROM products p WHERE p.product_code = :code'''


class Attach(Build):
    product_code: StrictInt = Field(gt=0)


class AlreadyBound(Exception):
    pass


def target(c, code, lock=False, raise_bound=False):
    row = c.execute(text(TARGET_SQL + (' FOR UPDATE OF p' if lock else '')), dict(code=code)).mappings().first()
    if not row or row['part_type'] != 'PC_COMPLETE':
        raise HTTPException(404, '완제품 PC 상품이 아닙니다.')
    if row['bound']:
        if raise_bound:
            raise AlreadyBound()
        raise HTTPException(409, '이미 구성표가 붙은 상품입니다.')
    if row['status'] != '판매중' or not row['sale_price'] or row['sale_price'] <= 0:
        raise HTTPException(409, '판매중이고 판매가가 있는 완제품에만 구성표를 붙일 수 있습니다.')
    return dict(row)


@router.get('/api/admin/pc-builder/attach-target')
def attach_target(product_code: int = Query(gt=0)):
    with engine.connect() as c:
        row = target(c, product_code)
    return dict(ok=True, product_code=row['product_code'], name=display_name(row['product_name']),
                sale_price=row['sale_price'],
                note='고른 부품으로 이 완제품의 구성표를 만듭니다. 쇼핑몰 판매가는 바뀌지 않고, 고객 공개는 검토 뒤 따로 진행합니다.')


def _same_request(c, code, request_id):
    """이미 붙은 구성표가 «같은 요청»으로 붙은 것이면 그 구성을 돌려준다(응답을 못 받은 재시도)."""
    return c.execute(text(
        "SELECT c.configuration_id FROM pc_configuration_offers o"
        " JOIN pc_configurations c ON c.configuration_id = o.configuration_id"
        " WHERE o.offer_id = :offer AND c.content->'_admin_creation'->>'request_id' = :rid"
        " AND c.content->'_admin_creation'->>'attached_product' = :code"),
        dict(offer=f"P{code}", rid=request_id, code=str(code))).scalar()


def attach_build(c, body, actor):
    build = Build(**body.model_dump(exclude={'product_code'}))
    try:
        product = target(c, body.product_code, lock=True, raise_bound=True)
    except AlreadyBound:
        # 첫 요청이 붙이고 응답만 잃었으면 같은 요청 번호로 다시 온다 — 409 대신 그 결과를 돌려준다
        # (2026-10-11 코덱스 검수 #114 지적 반영). 다른 요청이면 그대로 409.
        done = _same_request(c, body.product_code, build.request_id)
        if done:
            return dict(configuration_id=done, status='review_required', reused=True)
        raise HTTPException(409, '이미 구성표가 붙은 상품입니다.')
    r, duplicate = prepare(c, build, lock=True)
    offer_id = f"P{product['product_code']}"
    if duplicate:
        creation = duplicate['content'].get('_admin_creation', {})
        if (creation.get('request_id') == build.request_id and creation.get('attached_product') == product['product_code']):
            return dict(configuration_id=duplicate['configuration_id'], status='review_required', reused=True)
        raise HTTPException(409, '같은 부품·수량 구성의 제품군이 이미 있습니다: ' + duplicate['configuration_id'])
    if not build.preview_token or build.preview_token != r['preview_token']:
        raise HTTPException(409, '부품·가격·재고·검사 근거가 바뀌었습니다. 구성 확인을 다시 진행해 주세요.')
    if not r['can_save']:
        raise HTTPException(422, '등록된 호환 불일치 또는 호환 규칙 누락을 먼저 해결해 주세요.')
    identity = 'A' + uuid4().hex[:16].upper()
    content = r['content']
    content.update(source='기존', source_ids=[offer_id])
    content['_admin_creation'].update(actor=dict(operator_id=actor['operator_id'], name=actor.get('name', '')),
        input_hash=digest(build.model_dump(exclude={'preview_token'})), preview_basis=r['preview_token'],
        review=r['review'], attached_product=product['product_code'])
    price = product['sale_price']
    payload = dict(id=offer_id, price=price, base_price=price, assembly_fee_added=0, price_basis='쇼핑몰 판매가',
                   price_note=f"쇼핑몰 판매가 · 구성 부품 판매가 합계 {r['subtotal']:,}원 + 조립비 {r['assembly_fee']:,}원은 참고값",
                   parts_total=r['total'])
    c.execute(text('''INSERT INTO pc_configurations(configuration_id,bom_fingerprint,content,content_hash,copy_hash,status,observed_date)
        VALUES(:id,:bom,CAST(:content AS jsonb),:hash,:copy_hash,'review_required',:observed)'''),
        dict(id=identity, bom=r['bom_fingerprint'], content=json.dumps(content, ensure_ascii=False, default=str),
             hash=digest(dict(content=content, parts=r['parts'], offers=[payload])),
             copy_hash=digest(dict(content=content, parts=r['parts'])), observed=datetime.now(KST).date()))
    for p in r['parts']:
        c.execute(text('''INSERT INTO pc_configuration_parts(configuration_id,ordinal,slot,source_code,explanation_code,quantity,pseudo,selection_note,explanation_hash)
            VALUES(:id,:ordinal,:slot,:source_code,:explanation_code,:quantity,:pseudo,:selection_note,:explanation_hash)'''), dict(id=identity, **p))
    c.execute(text('INSERT INTO pc_configuration_offers(offer_id,configuration_id,price_snapshot,payload) VALUES(:offer,:id,:price,CAST(:payload AS jsonb))'),
              dict(offer=offer_id, id=identity, price=price, payload=json.dumps(payload, ensure_ascii=False)))
    return dict(configuration_id=identity, status='review_required', reused=False, product_code=product['product_code'],
                offer_id=offer_id, price=price, parts_total=r['total'])


@router.post('/api/admin/pc-builder/attach')
def attach(body: Attach, request: Request):
    actor = permission(request)
    with engine.begin() as c:
        return attach_build(c, body, actor)
