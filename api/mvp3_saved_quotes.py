"""MVP3 saved public recommendations; never an order or a component-change approval."""
import hashlib
import json
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import access_gate, grid_public, visitor
from .db import engine
from .talk_schema import load_vocab, validate_state
from .timeutil import iso

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])


class SaveBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    product_code: StrictInt = Field(gt=0)
    expected_price: StrictInt = Field(ge=0)
    state: dict


def same_origin(request):
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != expected):
        raise HTTPException(403, '같은 고객 화면에서 저장해 주세요.')


def fingerprint(body):
    raw = json.dumps(body.model_dump(mode='json'), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    if len(raw.encode('utf-8')) > 16384:
        raise HTTPException(422, '상담 조건이 너무 큽니다.')
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def owner_hash(request):
    key = access_gate.key_from_request(request, None)
    if not key or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', key):
        raise HTTPException(403, '이 브라우저의 견적 보관 키가 필요합니다.')
    return hashlib.sha256(key.encode('ascii')).hexdigest()


def public_product(item):
    code, price = item.get('product_code'), item.get('price')
    if type(code) is not int or type(price) is not int or price < 0:
        raise HTTPException(409, '상품 가격을 다시 확인해 주세요.')
    # Use the already public sold recommendation, never administrative rows.
    out = {k: item.get(k) for k in ('product_code', 'name', 'price', 'price_src', 'spec', 'level', 'tag', 'over_budget')}
    spec = item.get('spec')
    if isinstance(spec, dict):
        # Public component descriptions/capacities, never evaluation internals.
        out['spec'] = {k: v for k, v in spec.items()
                       if (k in ('cpu', 'gpu') and isinstance(v, str))
                       or (k in ('ram_gb', 'ssd_gb', 'vram_gb')
                           and type(v) in (int, float) and v >= 0)}
    else:
        out['spec'] = spec if isinstance(spec, str) else None
    out['reasons'] = [v for v in item.get('reasons', []) if isinstance(v, str)]
    out['price_confirmed'] = False
    return out


def selected_product(recommendation, code, expected_price):
    items = [p for group in recommendation.get('card_sets', [])
             if group.get('kind') == 'sold' for p in group.get('items', [])]
    found = next((p for p in items if p.get('product_code') == code), None)
    if found is None:
        raise HTTPException(409, '현재 상담 조건의 추천 상품이 아닙니다. 다시 조회해 주세요.')
    product = public_product(found)
    if product['price'] != expected_price:
        raise HTTPException(409, '상품 가격이 변경되었습니다. 다시 조회한 가격을 확인해 주세요.')
    return product


def render_quote(row):
    return {'id': str(row['quote_id']), 'product': row['product_snapshot'],
            'state': row['talk_state'], 'saved_at': iso(row['saved_at'])}


@router.get('/saved-quotes')
def list_quotes(request: Request, response: Response, limit: int = Query(default=20, ge=1, le=50)):
    owner = owner_hash(request)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request, response)
        if uid is None:
            raise HTTPException(503, '견적 보관을 위한 방문자 연결을 준비하지 못했습니다.')
        rows = conn.execute(text('''SELECT quote_id,product_snapshot,talk_state,saved_at
          FROM mvp3_saved_recommendations WHERE user_id=:u AND owner_key_hash=:owner
          ORDER BY saved_at DESC,quote_id DESC LIMIT :n'''), {'u': uid, 'owner': owner, 'n': limit + 1}).mappings().all()
    return {'ok': True, 'quotes': [render_quote(r) for r in rows[:limit]], 'has_more': len(rows) > limit}


@router.post('/saved-quotes')
def save_quote(body: SaveBody, request: Request, response: Response):
    same_origin(request)
    owner = owner_hash(request)
    basis = fingerprint(body)
    response.headers['Cache-Control'] = 'no-store'
    # The browser first calls GET to establish pc_vid. Do not create a fresh
    # identity during an ambiguous first POST, which would defeat idempotency.
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request)
        if uid is None:
            raise HTTPException(409, '내 견적을 먼저 조회해 저장 연결을 준비해 주세요.')
        previous = conn.execute(text('''SELECT quote_id,product_snapshot,talk_state,saved_at,request_basis
          FROM mvp3_saved_recommendations WHERE user_id=:u AND owner_key_hash=:owner AND request_id=:r'''),
          {'u': uid, 'owner': owner, 'r': str(body.request_id)}).mappings().first()
        if previous:
            if previous['request_basis'] != basis:
                raise HTTPException(409, '같은 저장 요청의 내용이 달라졌습니다.')
            return {'ok': True, 'quote': render_quote(previous)}
        state, _ = validate_state(body.state, load_vocab(conn))
    public = grid_public.recommend(grid_public.RecommendBody(state=state.model_dump()))
    product = selected_product(public, body.product_code, body.expected_price)
    params = {'id': str(uuid4()), 'u': uid, 'owner': owner, 'r': str(body.request_id), 'basis': basis,
              'product': json.dumps(product, ensure_ascii=False),
              'state': json.dumps(state.model_dump(), ensure_ascii=False)}
    with engine.begin() as conn:
        # Recheck the opaque owner cookie in the insertion transaction.
        if visitor.resolve(conn, request) != uid:
            raise HTTPException(403, '견적 보관 연결이 변경되었습니다.')
        conn.execute(text('''INSERT INTO mvp3_saved_recommendations
          (quote_id,user_id,owner_key_hash,request_id,request_basis,product_snapshot,talk_state)
          VALUES (:id,:u,:owner,:r,:basis,CAST(:product AS jsonb),CAST(:state AS jsonb))
          ON CONFLICT (user_id,owner_key_hash,request_id) DO NOTHING'''), params)
        row = conn.execute(text('''SELECT quote_id,product_snapshot,talk_state,saved_at,request_basis
          FROM mvp3_saved_recommendations WHERE user_id=:u AND owner_key_hash=:owner AND request_id=:r'''), params).mappings().one()
        if row['request_basis'] != basis:
            raise HTTPException(409, '같은 저장 요청의 내용이 달라졌습니다.')
        return {'ok': True, 'quote': render_quote(row)}
