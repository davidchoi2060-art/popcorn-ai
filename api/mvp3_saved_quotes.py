"""MVP3 saved public recommendations; never an order or a component-change approval."""
import hashlib
import json
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import access_gate, customer_pc_offer, grid_public, mall_price_live, mvp3_build, visitor
from .sold_reco import public_spec
from .db import engine
from .talk_schema import load_vocab, validate_state
from .timeutil import iso

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])

# Each new save reruns the public recommendation, so writes get their own per-visitor
# limit, separate from the AI call budget (rate_limit_policies key overrides these).
SAVE_POLICY_KEY = 'visitor.mvp3_save'
SAVE_PER_MINUTE = 10
SAVE_PER_DAY = 100
# Customer wording is Codex's (PR #2 comment 6057234341); copy verbatim. The day window
# resets at KST midnight (access_gate), which is what "내일" promises.
SAVE_LIMIT_MESSAGES = {
    'minute': '잠시 동안 견적 저장 요청이 많았습니다. {retry_after_sec}초 후 다시 저장해 주세요.',
    'day': '오늘 저장할 수 있는 견적 수에 도달했습니다. 내일 다시 저장해 주세요.',
}


class SaveBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    product_code: StrictInt = Field(gt=0)
    expected_price: StrictInt = Field(ge=0)
    state: dict
    # 부품 직접 바꾸기(api/mvp3_build). 있으면 서버가 금액·호환을 다시 계산해 그 값으로 보관한다.
    changes: list[mvp3_build.Change] = Field(default_factory=list, max_length=mvp3_build.MAX_CHANGES)


def same_origin(request):
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != expected):
        raise HTTPException(403, '같은 고객 화면에서 저장해 주세요.')


def fingerprint(body):
    dump = body.model_dump(mode='json')
    if not dump.get('changes'):
        dump.pop('changes', None)     # 부품을 바꾸지 않은 저장은 예전과 같은 지문이다
    raw = json.dumps(dump, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
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
    out = {k: item.get(k) for k in ('product_code', 'name', 'price', 'price_src', 'spec', 'level', 'tag', 'role', 'over_budget')}
    # Public component descriptions/capacities, never evaluation internals.
    out['spec'] = public_spec(item.get('spec'))
    out['reasons'] = [v for v in item.get('reasons', []) if isinstance(v, str)]
    out['price_confirmed'] = False
    return out


def in_recommendation(recommendation, code):
    return any(p.get('product_code') == code for group in recommendation.get('card_sets', [])
               if group.get('kind') == 'sold' for p in group.get('items', []))


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
    return {'id': str(row['quote_id']), 'product': dict(row['product_snapshot']),
            'state': row['talk_state'], 'saved_at': iso(row['saved_at'])}


def with_live_offer(quotes):
    # Photo and public configuration are read live at response time and never
    # stored in the snapshot: approval or the selected photo can change later.
    customer_pc_offer.attach([q['product'] for q in quotes if isinstance(q.get('product'), dict)])
    return quotes


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
    return {'ok': True, 'quotes': with_live_offer([render_quote(r) for r in rows[:limit]]), 'has_more': len(rows) > limit}


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
            quote = render_quote(previous)
        else:
            # Idempotent replays above are free; only new saves count.
            access_gate.check_rate(conn, request, what='mvp3.save', policy_key=SAVE_POLICY_KEY,
                                   default_per_minute=SAVE_PER_MINUTE, default_per_day=SAVE_PER_DAY,
                                   messages=SAVE_LIMIT_MESSAGES)
            state, _ = validate_state(body.state, load_vocab(conn))
    if previous:
        return {'ok': True, 'quote': with_live_offer([quote])[0]}
    if body.changes:
        product = built_product(state.model_dump(), body)
    else:
        product = recommended_product(state, body)
    quote_id = str(uuid4())
    # 2겹 실시간 안전장치(cart): 보관하는 순간 쇼핑몰 현재가와 비교한다. 다르면 우리 판매가를
    # 고치고(api/mall_price_live) 고객에게 알린 뒤 쇼핑몰 가격으로 보관한다. 못 읽으면 막지 않는다.
    # 쇼핑몰에 있는 것은 기준 PC 다 — 부품을 바꾼 견적은 기준 가격만 비교하고 차액만큼 총액을 옮긴다.
    build = product.get('build')
    quoted = build['base_price'] if build else product['price']
    check = mall_price_live.confirm('cart', body.product_code, quoted,
                                    quote_id=quote_id, visitor_ref=uid)
    if check['status'] == 'changed':
        product['price'] += check['mall'] - quoted
        if build:
            build['base_price'] = check['mall']
    product['price_check'] = check
    params = {'id': quote_id, 'u': uid, 'owner': owner, 'r': str(body.request_id), 'basis': basis,
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
        quote = render_quote(row)
    return {'ok': True, 'quote': with_live_offer([quote])[0]}


def built_product(state_raw, body):
    """부품을 바꾼 견적 — 기준 PC 는 같은 판정(eligible_sold_item)으로, 금액은 서버가 다시 계산한다."""
    item, q = mvp3_build.build_quote(state_raw, body.product_code, body.changes)
    product = public_product(item)
    if q['total'] != body.expected_price:
        raise HTTPException(409, '상품 가격이 변경되었습니다. 다시 조회한 가격을 확인해 주세요.')
    product['price'] = q['total']
    product['build'] = {'base_price': q['base_price'], 'changes': q['changes'], 'compat': q['compat']}
    return product


def recommended_product(state, body):
    public = grid_public.recommend(grid_public.RecommendBody(state=state.model_dump()))
    if not in_recommendation(public, body.product_code):
        # 「더 싸게」·「더 좋게」·추가 조건으로 본 카드는 조건만으로 다시 조회한 목록에 없을 수 있다.
        # 같은 판매 원천에서 이 상담 용도의 최소 수준을 채우는 상품일 때만 받는다(api/sold_reco.eligible_item).
        item = grid_public.eligible_sold_item(state.model_dump(), body.product_code)
        if item is not None:
            public = {'card_sets': [{'kind': 'sold', 'items': [item]}]}
    return selected_product(public, body.product_code, body.expected_price)
