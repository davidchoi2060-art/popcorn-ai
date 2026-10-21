"""MVP3 saved public recommendations; never an order or a component-change approval."""
import hashlib
import json
import re
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import access_gate, customer_pc_catalog, customer_supercomputer, customer_pc_offer, customer_surface, grid_public, mall_price_live, mvp3_build, mvp3_contact, mvp3_quantity, visitor
from .sold_reco import public_spec
from .db import engine
from .recommend import _resolve_data_origin
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
    # 같은 구성을 몇 대 사나(2026-10-12 중헌 님 7번). 금액(price)은 한 대 값 그대로 두고 대수만 함께 보관한다.
    sets: StrictInt = Field(default=1, ge=1, le=mvp3_quantity.MAX_SETS)
    # 연락처(2026-10-16 대표 지시): 이 방문자에게 유효한 연락처가 없으면 보관하려면 전화번호 + 동의가 필요하다.
    # 있으면 보내지 않아도 된다(재사용). 연락처는 지문(fingerprint)에 넣지 않는다 -- 같은 요청의 재전송은 연락처 없이도 같은 결과다.
    contact: mvp3_contact.ContactIn | None = None
    # 'handoff' = 쇼핑몰 상품 「팝콘PC로 이동」을 위해 인계 기록에 걸 견적을 조용히 보관한다(고객이 견적 보관을 누른 것이 아니다).
    # 연락처를 받지도 쓰지도 않는다. 상담 신청은 연락처가 있어야 하므로(from-quote) 이 견적으로 상담을 신청하면 그때 묻는다.
    purpose: Literal['keep', 'handoff'] = 'keep'
    # 상품 종류(2026-10-21 구매 1번 승인). 'ai_device' = AI 슈퍼컴퓨터 카테고리 상품을 그 화면에서 보관한다.
    # 장비 보관은 상담 신청이 아니다 -- 연락처를 받지도 요구하지도 않고, 상담 조건(state)도 쓰지 않는다.
    kind: Literal['pc', 'ai_device'] = 'pc'


def same_origin(request):
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != expected):
        raise HTTPException(403, '같은 고객 화면에서 저장해 주세요.')


def fingerprint(body):
    dump = body.model_dump(mode='json')
    dump.pop('contact', None)         # 연락처·목적은 견적 내용이 아니다 -- 지문에 넣으면 재전송이 다른 요청이 된다
    dump.pop('purpose', None)
    if not dump.get('changes'):
        dump.pop('changes', None)     # 부품을 바꾸지 않은 저장은 예전과 같은 지문이다
    for c in dump.get('changes') or []:
        if c.get('quantity') is None:
            c.pop('quantity', None)   # 수량을 바꾸지 않은 줄도 예전과 같은 지문이다
    if dump.get('sets') == 1:
        dump.pop('sets', None)
    if dump.get('kind') == 'pc':
        dump.pop('kind', None)        # 일반 PC 저장은 예전과 같은 지문이다
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
    # 상품 종류는 서버가 판정한 값만 보관한다(2026-10-16 독립 검수 F2). 쇼핑몰 상품 주소는 공개값이고
    # 보관 뒤 다시 열 때도 「팝콘PC에서 상품 보기」가 같은 주소를 쓴다. 팝콘AI 구성은 서버 추천 항목이
    # ai_composed 를 true 로 실었고 쇼핑몰 주소가 없을 때만 true 다 -- 고객 요청 값이나 주소 누락만으로 정하지 않는다.
    url = item.get('mall_url')
    out['mall_url'] = url if isinstance(url, str) and url.startswith('https://') and len(url) <= 2048 else None
    out['ai_composed'] = item.get('ai_composed') is True and out['mall_url'] is None
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
    # 화면이 본 가격과 지금 판매가가 달라도 보관을 막지 않는다 — 지금 판매가로 보관하고, 구매 상담에서 상담사가 조정한다
    # (2026-10-20 대표 「판매를 사전에 차단하지 마」). expected_price 는 비교에만 쓰고 저장하지 않는다.
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
            AND NOT (product_snapshot ? 'hidden_at')
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
            contact_row = mvp3_contact.current(conn, uid)
        else:
            contact_row = mvp3_contact.current(conn, uid)
            if body.purpose == 'keep' and body.kind == 'pc':
                if body.contact is not None:
                    mvp3_contact.clean(body.contact)         # 형식·동의가 틀리면 한도를 쓰기 전에 422
                elif contact_row is None:
                    raise mvp3_contact.required_error()      # 연락처 없이 처음 보관하는 요청
            # Idempotent replays above are free; only new saves count.
            access_gate.check_rate(conn, request, what='mvp3.save', policy_key=SAVE_POLICY_KEY,
                                   default_per_minute=SAVE_PER_MINUTE, default_per_day=SAVE_PER_DAY,
                                   messages=SAVE_LIMIT_MESSAGES)
            state = None if body.kind == 'ai_device' else validate_state(body.state, load_vocab(conn))[0]
    if previous:
        return {'ok': True, 'quote': with_live_offer([quote])[0], 'contact': mvp3_contact.view(contact_row)}
    if body.kind == 'ai_device':
        return save_device(body, request, uid, owner, basis)
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
    if body.sets > 1:
        product['sets'] = body.sets
    params = {'id': quote_id, 'u': uid, 'owner': owner, 'r': str(body.request_id), 'basis': basis,
              'product': json.dumps(product, ensure_ascii=False),
              'state': json.dumps(state.model_dump(), ensure_ascii=False),
              'surface': customer_surface.surface_of(request)}
    with engine.begin() as conn:
        # Recheck the opaque owner cookie in the insertion transaction.
        if visitor.resolve(conn, request) != uid:
            raise HTTPException(403, '견적 보관 연결이 변경되었습니다.')
        if body.purpose == 'keep':
            # 연락처 등록(또는 변경)은 견적 보관과 같은 트랜잭션이다 -- 한쪽만 남지 않는다.
            if body.contact is not None:
                mvp3_contact.upsert(conn, uid, body.contact, _resolve_data_origin(request))
            elif mvp3_contact.current(conn, uid) is None:
                raise mvp3_contact.required_error()          # 그 사이 기한이 지난 경우
            contact_row = mvp3_contact.current(conn, uid)
        conn.execute(text('''INSERT INTO mvp3_saved_recommendations
          (quote_id,user_id,owner_key_hash,request_id,request_basis,product_snapshot,talk_state,surface)
          VALUES (:id,:u,:owner,:r,:basis,CAST(:product AS jsonb),CAST(:state AS jsonb),:surface)
          ON CONFLICT (user_id,owner_key_hash,request_id) DO NOTHING'''), params)
        row = conn.execute(text('''SELECT quote_id,product_snapshot,talk_state,saved_at,request_basis
          FROM mvp3_saved_recommendations WHERE user_id=:u AND owner_key_hash=:owner AND request_id=:r'''), params).mappings().one()
        if row['request_basis'] != basis:
            raise HTTPException(409, '같은 저장 요청의 내용이 달라졌습니다.')
        quote = render_quote(row)
    return {'ok': True, 'quote': with_live_offer([quote])[0], 'contact': mvp3_contact.view(contact_row)}


def built_product(state_raw, body):
    """부품을 바꾼 견적 — 기준 PC 는 같은 판정(eligible_sold_item)으로, 금액은 서버가 다시 계산한다."""
    item, q = mvp3_build.build_quote(state_raw, body.product_code, body.changes)
    product = public_product(item)
    if q['total'] != body.expected_price:
        raise HTTPException(409, '상품 가격이 변경되었습니다. 다시 조회한 가격을 확인해 주세요.')
    product['price'] = q['total']
    product['build'] = {'base_price': q['base_price'], 'changes': q['changes'], 'compat': q['compat'],
                        'warnings': q.get('warnings', [])}
    return product


def recommended_product(state, body):
    if not state.model_dump().get('usages'):
        # 상담 없이 상품 목록(/mvp4)에서 직접 고른 PC -- 판매중 추천 풀 상품을 지금 판매가로만 받는다(2026-10-19).
        item = customer_pc_catalog.sold_item(body.product_code)
        return selected_product({'card_sets': [{'kind': 'sold', 'items': [item] if item else []}]},
                                body.product_code, body.expected_price)
    public = grid_public.recommend(grid_public.RecommendBody(state=state.model_dump()))
    if not in_recommendation(public, body.product_code):
        # 「더 싸게」·「더 좋게」·추가 조건으로 본 카드는 조건만으로 다시 조회한 목록에 없을 수 있다.
        # 같은 판매 원천에서 이 상담 용도의 최소 수준을 채우는 상품일 때만 받는다(api/sold_reco.eligible_item).
        item = grid_public.eligible_sold_item(state.model_dump(), body.product_code)
        if item is not None:
            public = {'card_sets': [{'kind': 'sold', 'items': [item]}]}
    return selected_product(public, body.product_code, body.expected_price)


def device_product(code, expected_price):
    """AI 슈퍼컴퓨터 카테고리의 판매중 상품만 받는다(관리자 행·다른 카테고리·임의 코드는 409).

    가격은 지금 판매가 그대로 보관한다. 팝콘PC몰 가격을 읽어 우리 판매가를 고치는 장치(mall_price_live)는
    부르지 않는다 -- 고객의 보관 한 번이 판매가를 바꾸면 안 된다. 그래서 «몰에서 최종 가격 확인»으로 남긴다.
    """
    with engine.connect() as conn:
        found = customer_supercomputer.load(conn, (code,)).get(code)
    if found is None or found['sale_state'] != 'on_sale' or type(found['price']) is not int:
        raise HTTPException(409, '지금 보관할 수 있는 AI 슈퍼컴퓨터가 아닙니다. 판매 상태와 가격을 다시 확인해 주세요.')
    return {'product_code': code, 'kind': 'ai_device', 'name': found['name'], 'model_label': found['model_label'],
            'price': found['price'], 'price_src': '팝콘AI 표시 금액', 'memory': found['memory'], 'storage': found['storage'],
            'accelerator': found['accelerator'], 'mall_url': found['mall_url'], 'price_confirmed': False,
            'price_changed_since_view': found['price'] != expected_price}


def save_device(body, request, uid, owner, basis):
    product = device_product(body.product_code, body.expected_price)
    product['price_check'] = {'status': 'unchecked', 'quoted': body.expected_price, 'mall': None}
    if body.sets > 1:
        product['sets'] = body.sets
    quote_id = str(uuid4())
    params = {'id': quote_id, 'u': uid, 'owner': owner, 'r': str(body.request_id), 'basis': basis,
              'product': json.dumps(product, ensure_ascii=False), 'state': '{}',
              'surface': customer_surface.surface_of(request)}
    with engine.begin() as conn:
        if visitor.resolve(conn, request) != uid:
            raise HTTPException(403, '견적 보관 연결이 변경되었습니다.')
        conn.execute(text('''INSERT INTO mvp3_saved_recommendations
          (quote_id,user_id,owner_key_hash,request_id,request_basis,product_snapshot,talk_state,surface)
          VALUES (:id,:u,:owner,:r,:basis,CAST(:product AS jsonb),CAST(:state AS jsonb),:surface)
          ON CONFLICT (user_id,owner_key_hash,request_id) DO NOTHING'''), params)
        row = conn.execute(text('''SELECT quote_id,product_snapshot,talk_state,saved_at,request_basis
          FROM mvp3_saved_recommendations WHERE user_id=:u AND owner_key_hash=:owner AND request_id=:r'''), params).mappings().one()
        if row['request_basis'] != basis:
            raise HTTPException(409, '같은 저장 요청의 내용이 달라졌습니다.')
        contact_row = mvp3_contact.current(conn, uid)
    return {'ok': True, 'quote': render_quote(row), 'contact': mvp3_contact.view(contact_row)}


# 내 견적 개별 삭제(2026-10-21 구매 1번 승인 「내 견적에서 삭제하는 버튼」).
# 행을 지우지 않고 고객 목록에서 숨긴다(product_snapshot.hidden_at) -- 이 견적에 걸린 상담 신청(purchase_inquiries.quote_id)·
# 인계 기록은 그대로 남고, 같은 브라우저에서 「되돌리기」로 실제로 되살릴 수 있다. 다른 견적·상담·주문·상품은 건드리지 않는다.
# 이 브라우저의 보관 키(owner)와 방문자(user)가 모두 맞는 행만 바꾼다. 이미 숨긴 행을 다시 숨기면 같은 결과(멱등)다.
def _owned(conn, request, quote_id):
    try:
        qid = str(UUID(quote_id))
    except ValueError:
        raise HTTPException(404, '보관한 견적을 찾을 수 없습니다.')
    owner = owner_hash(request)
    uid = visitor.resolve(conn, request)
    if uid is None:
        raise HTTPException(409, '내 견적을 먼저 조회해 주세요.')
    return qid, uid, owner


@router.delete('/saved-quotes/{quote_id}')
def hide_quote(quote_id: str, request: Request, response: Response):
    same_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        qid, uid, owner = _owned(conn, request, quote_id)
        row = conn.execute(text('''UPDATE mvp3_saved_recommendations
          SET product_snapshot = CASE WHEN product_snapshot ? 'hidden_at' THEN product_snapshot
                                      ELSE product_snapshot || jsonb_build_object('hidden_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')) END
          WHERE quote_id=:q AND user_id=:u AND owner_key_hash=:owner RETURNING quote_id'''),
          {'q': qid, 'u': uid, 'owner': owner}).first()
    if row is None:
        raise HTTPException(404, '보관한 견적을 찾을 수 없습니다.')
    return {'ok': True, 'id': qid, 'hidden': True, 'restorable': True}


@router.post('/saved-quotes/{quote_id}/restore')
def restore_quote(quote_id: str, request: Request, response: Response):
    same_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        qid, uid, owner = _owned(conn, request, quote_id)
        row = conn.execute(text('''UPDATE mvp3_saved_recommendations
          SET product_snapshot = product_snapshot - 'hidden_at'
          WHERE quote_id=:q AND user_id=:u AND owner_key_hash=:owner
          RETURNING quote_id,product_snapshot,talk_state,saved_at'''), {'q': qid, 'u': uid, 'owner': owner}).mappings().first()
    if row is None:
        raise HTTPException(404, '보관한 견적을 찾을 수 없습니다.')
    return {'ok': True, 'quote': with_live_offer([render_quote(row)])[0]}
