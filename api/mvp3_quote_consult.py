"""MVP3 견적 보관 뒤의 두 가지 -- 연락처 확인·변경, 보관 견적으로 상담 신청 접수 (2026-10-16 대표 지시).

■ 두 상태를 나눈다
  견적 보관(`api/mvp3_saved_quotes`)과 상담 신청 접수는 별개다. 보관만으로 신청(PI)은 생기지 않고
  상담사가 먼저 연락하지도 않는다. 고객이 보관 견적서에서 「상담 신청 접수」를 눌렀을 때만 이 모듈이
  보관 견적과 등록된 연락처로 `purchase_inquiries` 에 한 줄을 만든다(관리자 「구매 상담 신청」이 그대로 읽는다).

■ 상담 신청 접수(`POST /api/mvp3/purchase-inquiries/from-quote`)
  · 이 방문자(방문자 쿠키 + 보관 키)의 견적일 때만 -- 아니면 404. 견적 참조 없이 성공 처리하지 않는다
    (일반 문의 `POST /purchase-inquiries` 는 quote_id 가 선택이라 따로 둔다 -- 그쪽은 그대로다).
  · 등록된 연락처가 없으면 409 `contact_required`(화면이 연락처 입력으로 보낸다).
  · 문의 주제는 기존 값 「주문 희망」으로 정한다(새 값을 만들지 않는다).
  · 같은 견적에 이미 접수된 신청이 있으면 새로 만들지 않고 그것을 `already: true` 로 돌려준다.
    견적 하나에 잠금을 잡고 보므로 동시에 두 번 눌러도 한 건이다.
  · 접수 순서는 서버가 받은 시각(`created_at`)과 신청 번호 순서다. 연락 시각·기한은 약속하지 않는다.

■ 개인정보
  응답에는 가린 번호만 싣는다. 로그에는 신청 번호만 찍는다(번호·이메일은 찍지 않는다).
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from . import access_gate, mvp3_contact, visitor
from .db import engine
from .mvp3_purchase_inquiry import TOPICS, _no
from .mvp3_saved_quotes import owner_hash, same_origin
from .recommend import _resolve_data_origin

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])
log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

FROM_QUOTE_TOPIC = '주문 희망'          # 기존 TOPICS 의 값 -- 새 주제를 만들지 않는다
assert FROM_QUOTE_TOPIC in TOPICS

CONTACT_POLICY_KEY = 'visitor.mvp3_contact'
CONTACT_PER_MINUTE = 5
CONTACT_PER_DAY = 30
CONTACT_LIMIT_MESSAGES = {
    'minute': '잠시 동안 연락처 요청이 많았습니다. {retry_after_sec}초 후 다시 시도해 주세요.',
    'day': '오늘 연락처를 바꿀 수 있는 횟수에 도달했습니다. 내일 다시 시도해 주세요.',
}
CONSULT_POLICY_KEY = 'visitor.mvp3_quote_consult'
CONSULT_PER_MINUTE = 3
CONSULT_PER_DAY = 10
CONSULT_LIMIT_MESSAGES = {
    'minute': '잠시 동안 상담 신청이 많았습니다. {retry_after_sec}초 후 다시 시도해 주세요.',
    'day': '오늘 접수할 수 있는 상담 신청 수에 도달했습니다. 내일 다시 시도해 주세요.',
}


class FromQuoteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_id: UUID
    message: str | None = Field(default=None, max_length=500)


@router.get('/contact')
def get_contact(request: Request, response: Response):
    """이 방문자의 등록 연락처가 있는지 -- 가린 번호와 이름만. 전체 번호는 돌려주지 않는다."""
    owner_hash(request)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request, response)
        if uid is None:
            raise HTTPException(503, '연락처 확인을 위한 방문자 연결을 준비하지 못했습니다.')
        row = mvp3_contact.current(conn, uid)
    return {'ok': True, **mvp3_contact.view(row), 'consent_text': mvp3_contact.CONSENT_TEXT}


@router.put('/contact')
def put_contact(body: mvp3_contact.ContactIn, request: Request, response: Response):
    """연락처를 바꾼다(고객이 「연락처 변경」을 눌렀을 때). 이미 보관한 견적은 그대로다."""
    same_origin(request)
    owner_hash(request)
    response.headers['Cache-Control'] = 'no-store'
    mvp3_contact.clean(body)            # 형식·동의가 틀리면 한도를 쓰기 전에 422
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request)
        if uid is None:
            raise HTTPException(409, '내 견적을 먼저 조회해 연락처 연결을 준비해 주세요.')
        access_gate.check_rate(conn, request, what='mvp3.contact', policy_key=CONTACT_POLICY_KEY,
                               default_per_minute=CONTACT_PER_MINUTE, default_per_day=CONTACT_PER_DAY,
                               messages=CONTACT_LIMIT_MESSAGES)
        mvp3_contact.upsert(conn, uid, body, _resolve_data_origin(request))
        row = mvp3_contact.current(conn, uid)
    log.info('[mvp3-contact] updated')
    return {'ok': True, **mvp3_contact.view(row)}


@router.post('/purchase-inquiries/from-quote')
def inquiry_from_quote(body: FromQuoteBody, request: Request, response: Response):
    same_origin(request)
    owner = owner_hash(request)
    qid = str(body.quote_id)
    response.headers['Cache-Control'] = 'no-store'
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request)
        if uid is None:
            raise HTTPException(409, '내 견적을 먼저 조회해 연결을 준비해 주세요.')
        quote = conn.execute(text(
            'SELECT quote_id, product_snapshot FROM mvp3_saved_recommendations'
            ' WHERE quote_id = :q AND user_id = :u AND owner_key_hash = :o'),
            {'q': qid, 'u': uid, 'o': owner}).mappings().first()
        if quote is None:
            # 견적 참조가 맞지 않으면 접수하지 않는다 -- 일반 문의처럼 참조 없이 받지 않는다.
            raise HTTPException(404, '이 브라우저에서 보관한 견적을 찾지 못했습니다.')
        # 같은 견적의 동시 요청 둘이 모두 「없음」을 읽고 둘 다 넣지 않게 견적 하나에 잠금을 잡는다.
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'), {'k': 'mvp3_quote_consult:' + qid})
        contact = mvp3_contact.current(conn, uid)
        found = conn.execute(text(
            'SELECT inquiry_no, contact_phone FROM purchase_inquiries'
            ' WHERE quote_id = :q AND user_id = :u AND contact_purged_at IS NULL'
            ' ORDER BY inquiry_id LIMIT 1'), {'q': qid, 'u': uid}).mappings().first()
        if found:
            phone = found['contact_phone'] or (contact['contact_phone'] if contact else None)
            return {'ok': True, 'already': True, 'inquiry_no': found['inquiry_no'], 'quote_id': qid,
                    'masked_phone': mvp3_contact.mask_phone(phone)}
        if contact is None:
            raise HTTPException(409, {'error': 'contact_required', 'contact_required': True,
                                      'detail': '상담 신청을 접수하려면 연락처가 필요해요. 연락처를 먼저 등록해 주세요.',
                                      'consent_text': mvp3_contact.CONSENT_TEXT})
        access_gate.check_rate(conn, request, what='mvp3.quote_consult', policy_key=CONSULT_POLICY_KEY,
                               default_per_minute=CONSULT_PER_MINUTE, default_per_day=CONSULT_PER_DAY,
                               messages=CONSULT_LIMIT_MESSAGES)
        code = (quote['product_snapshot'] or {}).get('product_code')
        code = code if type(code) is int else None
        no = _no(conn)
        now = datetime.now(timezone.utc)
        conn.execute(text(
            'INSERT INTO purchase_inquiries (inquiry_no, user_id, quote_id, product_code, topic, contact_name,'
            ' contact_phone, contact_email, message, consent_at, data_origin, purge_at)'
            ' VALUES (:no, :u, :q, :c, :t, :n, :p, :e, :m, :consent, :origin, :purge)'),
            {'no': no, 'u': uid, 'q': qid, 'c': code, 't': FROM_QUOTE_TOPIC, 'n': contact['contact_name'],
             'p': contact['contact_phone'], 'e': contact['contact_email'],
             'm': (body.message or '').strip() or None, 'consent': contact['consent_at'],
             'origin': _resolve_data_origin(request), 'purge': now + timedelta(days=mvp3_contact.KEEP_DAYS)})
    log.info('[quote-consult] %s accepted', no)
    return {'ok': True, 'already': False, 'inquiry_no': no, 'quote_id': qid,
            'masked_phone': mvp3_contact.mask_phone(contact['contact_phone'])}
