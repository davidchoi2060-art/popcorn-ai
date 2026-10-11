"""MVP3 보관 견적 -> 팝콘PC 쇼핑몰 인계 (2026-10-11 품질관리 1단계).

■ 왜 있는가
  지금 고객 화면(mvp3)은 판매 중인 몰 조립PC 한 대를 권하고 「견적 보관하기」로 끝났다.
  쇼핑몰로 넘어갈 길이 없어 고객이 거기서 멈췄고, 관리자 「인계 기록」에도 아무것도
  남지 않았다. 결제는 `ops_settings.pay = 'mall'`(쇼핑몰)이라 우리가 할 일은 기존
  `api/handoff.py` 와 같다 — **넘기고 기록한다.** 결제·재고 차감·배송지는 하지 않는다.

■ 왜 «보관 견적»에서만 넘기나
  보관 견적은 서버가 이미 「지금 추천에 실제로 나온 상품 · 그 가격」을 확인해 저장한
  기록이다(`mvp3_saved_recommendations`, 보관 키로 소유자 확인). 화면이 보내는 상품코드·
  가격을 다시 믿지 않고 그 기록을 근거로 넘긴다. 기존 인계(`api/handoff.py`)는 부품
  조립 견적(consult_sessions·quote_snapshots)용이라 완제품 한 대를 넣을 자리가 없어,
  같은 원장(`handoffs`·`handoff_items`)에 «세션 없이» 한 줄로 남긴다:

      handoffs.session_id   NULL  (mvp3 는 상담 세션을 만들지 않는다)
      handoffs.quote_type   'mvp3'
      handoffs.note         {"source":"mvp3","mvp3_quote_id":"<uuid>", ...}
      handoff_items         한 줄 · item_kind 'built_pc' · 상품코드 = 몰 pd_no

■ 넘기기 직전 몰 가격·품절을 다시 본다 (`api/handoff.py` 와 같은 규칙)
  다르면 고객에게 말한다. 조용히 바꾸지 않는다. 품절이어도 막지 않고 알린다.

■ 같은 보관 견적을 두 번 누르면 같은 인계 기록을 돌려준다(원장에 중복을 쌓지 않는다).
"""
import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from . import access_gate, mall, visitor
from .db import engine
from .handoff import _no
from .mvp3_saved_quotes import owner_hash, same_origin

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])
log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

POLICY_KEY = 'visitor.mvp3_handoff'
PER_MINUTE = 5
PER_DAY = 30
LIMIT_MESSAGES = {
    'minute': '잠시 동안 구매 연결 요청이 많았습니다. {retry_after_sec}초 후 다시 시도해 주세요.',
    'day': '오늘 보낼 수 있는 구매 연결 요청 수에 도달했습니다. 내일 다시 시도해 주세요.',
}


def _marker(quote_id: str) -> str:
    return '"mvp3_quote_id": "%s"' % quote_id


def _result(h, item, quote_id):
    code = item['product_code']
    return {
        'ok': True, 'handoff_no': h['handoff_no'], 'quote_id': quote_id,
        'product_code': code, 'name': item['name_snap'],
        'price_quoted': item['price_quoted'], 'price_mall': item['price_mall'],
        'mall_status': item['mall_status'],
        'mall_url': mall.DETAIL % code,
    }


def _existing(conn, quote_id):
    h = conn.execute(text(
        "SELECT handoff_id, handoff_no FROM handoffs WHERE quote_type='mvp3'"
        " AND note LIKE :m ORDER BY handoff_id DESC LIMIT 1"),
        {'m': '%' + _marker(quote_id) + '%'}).mappings().first()
    if not h:
        return None
    item = conn.execute(text(
        "SELECT product_code, name_snap, price_quoted, price_mall, mall_status"
        " FROM handoff_items WHERE handoff_id=:h ORDER BY line_no LIMIT 1"),
        {'h': h['handoff_id']}).mappings().first()
    return (h, item) if item else None


@router.post('/saved-quotes/{quote_id}/handoff')
def handoff_saved_quote(quote_id: UUID, request: Request, response: Response):
    same_origin(request)
    owner = owner_hash(request)
    qid = str(quote_id)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request)
        if uid is None:
            raise HTTPException(409, '내 견적을 먼저 조회해 연결을 준비해 주세요.')
        quote = conn.execute(text(
            "SELECT product_snapshot FROM mvp3_saved_recommendations"
            " WHERE quote_id=:q AND user_id=:u AND owner_key_hash=:o"),
            {'q': qid, 'u': uid, 'o': owner}).mappings().first()
        if quote is None:
            raise HTTPException(404, '이 브라우저에서 보관한 견적을 찾지 못했습니다.')
        ops = dict(conn.execute(text("SELECT key, mode FROM ops_settings")).all())
        if ops.get('pay') != 'mall':
            raise HTTPException(409, {'error': 'pay_mode_own',
                                      'detail': '지금은 쇼핑몰 구매 연결을 사용할 수 없습니다.'})
        found = _existing(conn, qid)
        if found:
            return _result(found[0], found[1], qid)
        access_gate.check_rate(conn, request, what='mvp3.handoff', policy_key=POLICY_KEY,
                               default_per_minute=PER_MINUTE, default_per_day=PER_DAY,
                               messages=LIMIT_MESSAGES)
    product = quote['product_snapshot'] or {}
    code, quoted = product.get('product_code'), product.get('price')
    if type(code) is not int or type(quoted) is not int or quoted < 0:
        raise HTTPException(409, '보관 견적의 상품 정보를 확인할 수 없습니다.')

    # 외부 조회는 트랜잭션 밖에서 한다(몰 응답을 기다리는 동안 DB 연결을 잡지 않는다).
    got = (mall.fetch_prices([code]) or {}).get(code) or {}
    price_mall = got.get('price') if got.get('ok') else None
    if price_mall is None:
        status = '확인못함'
    elif got.get('soldout'):
        status = '품절'
    elif price_mall != quoted:
        status = '가격변동'
    else:
        status = '확인됨'
    name = product.get('name') or ('상품 %d' % code)

    with engine.begin() as conn:
        found = _existing(conn, qid)       # 그 사이 같은 요청이 먼저 끝났으면 그것을 돌려준다
        if found:
            return _result(found[0], found[1], qid)
        no = _no(conn)
        gate_on = access_gate.column_ready(conn, 'handoffs')
        note = json.dumps({'source': 'mvp3', 'mvp3_quote_id': qid,
                           'unknown': [code] if status == '확인못함' else []}, ensure_ascii=False)
        params = {'no': no, 'u': uid, 'tq': quoted,
                  'tm': price_mall if price_mall is not None else quoted,
                  'chk': price_mall is not None, 'ch': 1 if status == '가격변동' else 0,
                  'so': 1 if status == '품절' else 0, 'note': note}
        cols = ('handoff_no, session_id, snapshot_id, quote_type, member_id, user_id,'
                ' total_quoted, total_mall, price_checked, changed_cnt, soldout_cnt, status, note')
        vals = ":no, NULL, NULL, 'mvp3', NULL, :u, :tq, :tm, :chk, :ch, :so, '인계', :note"
        if gate_on:
            cols, vals = cols + ', access_key', vals + ', :ak'
            params['ak'] = access_gate.new_key()
        hid = conn.execute(text(
            f"INSERT INTO handoffs ({cols}) VALUES ({vals}) RETURNING handoff_id"), params).scalar()
        conn.execute(text(
            "INSERT INTO handoff_items (handoff_id, line_no, product_code, item_kind,"
            " part_type, name_snap, price_quoted, price_mall, qty, mall_status)"
            " VALUES (:h, 1, :c, 'built_pc', NULL, :nm, :pq, :pm, 1, :st)"),
            {'h': hid, 'c': code, 'nm': name, 'pq': quoted, 'pm': price_mall, 'st': status})
    log.info('[mvp3-handoff] %s code=%s status_ok=%s', no, code, status == '확인됨')
    return {'ok': True, 'handoff_no': no, 'quote_id': qid, 'product_code': code, 'name': name,
            'price_quoted': quoted, 'price_mall': price_mall, 'mall_status': status,
            'mall_url': mall.DETAIL % code}
