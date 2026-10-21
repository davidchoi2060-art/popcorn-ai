"""MVP3 구매 상담 신청 — 고객이 연락처를 남긴다 (2026-10-11 품질관리 · 관리자 확인 R4·F12).

■ 왜 있는가
  고객 AI 는 여러 대 구매·할인·세금계산서·주문을 정할 수 없다(`api/talk_rules` ⑤ 가 그렇게
  말한다). 그런데 고객이 연락처를 남길 곳이 없어, 관리자가 그 고객에게 다시 연락할 수
  없었다. 이 경로는 신청을 받아 관리자 「구매 상담 신청」(`api/admin_purchase_inquiries.py`)
  으로 넘긴다. 주문·결제·가격 약속은 하지 않는다.

■ 받는 것
  주제 · 연락처(전화 또는 이메일 중 하나 이상) · 이름(선택) · 내용(선택, 500자) ·
  개인정보 수집 동의(필수). 보관 견적 번호가 오면 이 방문자의 견적일 때만 잇는다.

■ 개인정보
  연락처는 이 표에만 둔다. 로그에는 신청 번호만 찍는다. 보관 기한은 신청 후 180일.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import text

from . import access_gate, customer_supercomputer, customer_surface, visitor
from .db import engine
from .mvp3_contact import EMAIL_RE, KEEP_DAYS, PHONE_RE   # 정규식·보관 기한은 한 곳(mvp3_contact)
from .mvp3_saved_quotes import same_origin
from .orders import ASSEMBLY_FEE
from .mvp3_free_build import Pick as FreePick, quote_build as free_quote
from .recommend import _resolve_data_origin

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])
log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

TOPICS = ('여러 대 구매', '할인', '세금계산서·영수증', '주문 희망', '기타')
POLICY_KEY = 'visitor.purchase_inquiry'
PER_MINUTE = 3
PER_DAY = 10
LIMIT_MESSAGES = {
    'minute': '잠시 동안 신청이 많았습니다. {retry_after_sec}초 후 다시 시도해 주세요.',
    'day': '오늘 남길 수 있는 구매 상담 신청 수에 도달했습니다. 내일 다시 시도해 주세요.',
}
# /mvp4 AI 슈퍼컴퓨터(고정 완제품) 문의의 주제 — 일반 상담 주제 목록(TOPICS)에는 넣지 않는다(0165).
FIXED_TOPICS = {'quote': 'AI 슈퍼컴퓨터 견적', 'adoption': 'AI 도입 상담'}
# /mvp4 기업 AI 업무개선 컨설팅 신청 화면만 쓰는 주제(0174). 일반 상담 주제 목록(TOPICS)에는 넣지 않고, 상품·견적을 함께 받지 않는다.
SERVICE_TOPICS = ('기업 AI 업무개선 컨설팅',)
PURPOSES = {'local-llm': '로컬 AI 모델 실행', 'documents': '사내 문서 검색·업무 활용',
            'development': 'AI 개발·연구', 'other': '그 밖의 용도·아직 미정'}
CONSENT_TEXT = ('구매 상담 연락을 위해 이름·연락처·문의 내용을 받고, 신청 후 %d일이 지나면 지웁니다. '
                '동의하지 않으셔도 되지만, 이 경우 상담 신청은 할 수 없습니다.' % KEEP_DAYS)


class FixedPick(BaseModel):
    """AI 슈퍼컴퓨터 상세에서 고른 모델의 수량·문의 목적. 상품번호는 InquiryBody.product_code 로 온다."""
    model_config = ConfigDict(extra='forbid')
    intent: Literal['quote', 'adoption']
    quantity: StrictInt = Field(ge=1, le=10)
    purpose: Literal['local-llm', 'documents', 'development', 'other'] | None = None
    # 고객이 화면에서 본 1대 가격. 지금 판매가와 달라도 접수한다 — 두 값을 함께 남기고 상담사가 전화로 조정한다(2026-10-20 대표).
    seen_unit_price: StrictInt | None = Field(default=None, ge=0)


class InquiryBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: str
    name: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=500)
    consent: StrictBool
    quote_id: UUID | None = None
    product_code: StrictInt | None = Field(default=None, gt=0)
    configuration_id: str | None = Field(default=None, pattern=r'^A[0-9A-F]{16}$')
    # 「부품 직접 고르기」 구성(api/mvp3_free_build). 화면이 보낸 값은 부품 번호·수량만 믿고 금액·호환은 다시 센다.
    free_build: list[FreePick] | None = Field(default=None, min_length=1, max_length=8)
    # 화면이 신청마다 만든 키(/mvp4 AI 패키지 문의, 0163). 같은 방문자·같은 키는 한 번만 접수하고 같은 번호를 돌려준다.
    client_key: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{6,64}$')
    # /mvp4 AI 슈퍼컴퓨터 문의(0165). product_code 가 AI 슈퍼컴퓨터 카테고리에 분류된 상품이어야 한다(0166).
    fixed: FixedPick | None = None


def _clean(body: InquiryBody):
    if body.fixed is not None:
        if body.topic != FIXED_TOPICS[body.fixed.intent]:
            raise HTTPException(422, '문의 주제를 확인해 주세요.')
        # 상품이 AI 슈퍼컴퓨터 카테고리에 분류돼 있는지는 접수 트랜잭션에서 본다(customer_supercomputer.load, 0166).
        if body.product_code is None:
            raise HTTPException(422, 'AI 슈퍼컴퓨터 모델을 다시 선택해 주세요.')
        if body.quote_id is not None or body.configuration_id is not None or body.free_build is not None:
            raise HTTPException(422, '슈퍼컴퓨터 문의에는 다른 견적을 함께 보낼 수 없어요.')
    elif body.topic in SERVICE_TOPICS:
        if body.product_code is not None or body.quote_id is not None or body.configuration_id is not None or body.free_build is not None:
            raise HTTPException(422, '기업 컨설팅 상담에는 상품이나 견적을 함께 보낼 수 없어요.')
    elif body.topic not in TOPICS:
        raise HTTPException(422, '문의 주제를 골라 주세요.')
    if body.consent is not True:
        raise HTTPException(422, '연락처를 받으려면 개인정보 수집에 동의해 주세요.')
    phone = re.sub(r'\s+', '', body.phone or '') or None
    email = (body.email or '').strip() or None
    if not phone and not email:
        raise HTTPException(422, '전화번호나 이메일 중 하나는 적어 주세요.')
    if phone and not PHONE_RE.match(phone):
        raise HTTPException(422, '전화번호 형식을 확인해 주세요. 예: 010-1234-5678')
    if email and not EMAIL_RE.match(email):
        raise HTTPException(422, '이메일 형식을 확인해 주세요.')
    return phone, email, (body.name or '').strip() or None, (body.message or '').strip() or None


def _no(conn) -> str:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('purchase_inquiry_no'))"))
    seq = conn.execute(text(
        "SELECT COALESCE(MAX(CAST(substring(inquiry_no FROM 4) AS INTEGER)), 1000) + 1"
        " FROM purchase_inquiries WHERE inquiry_no ~ '^PI-[0-9]+$'")).scalar()
    return 'PI-%d' % seq


@router.get('/purchase-inquiries/form')
def form_meta(request: Request, response: Response):
    """신청 칸이 쓰는 선택지와 동의 문구 — 화면이 다시 적지 않게 서버가 준다.

    방문자 연결(쿠키)도 여기서 맺는다 — 신청 전에 맺어 두어야, 응답을 못 받은 화면이 같은 브라우저로
    결과를 확인할 수 있다(by-key). 개인정보는 받지 않는다.
    """
    with engine.begin() as conn:
        visitor.resolve(conn, request, response)
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'topics': list(TOPICS), 'consent_text': CONSENT_TEXT}


def _by_key(conn, uid, key):
    return conn.execute(text(
        "SELECT inquiry_no FROM purchase_inquiries WHERE user_id = :u AND client_key = :k"),
        {'u': uid, 'k': key}).scalar()


@router.get('/purchase-inquiries/by-key/{key}')
def inquiry_by_key(key: str, request: Request, response: Response):
    """같은 브라우저가 보낸 그 키의 신청이 접수됐는가. 연락처·내용은 돌려주지 않는다(번호만).

    방문자 쿠키가 없으면 403 — 이 브라우저의 신청인지 알 수 없다(«접수 안 됨»으로 답하지 않는다).
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', key):
        raise HTTPException(422, '요청 키 형식이 올바르지 않습니다.')
    response.headers['Cache-Control'] = 'no-store'
    with engine.connect() as conn:
        uid = visitor.resolve(conn, request)
        if uid is None:
            raise HTTPException(403, '이 브라우저의 신청을 확인할 수 없습니다.')
        no = _by_key(conn, uid, key)
    return {'ok': True, 'found': no is not None, 'inquiry_no': no}


@router.post('/purchase-inquiries')
def create_inquiry(body: InquiryBody, request: Request, response: Response):
    same_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    phone, email, name, message = _clean(body)
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request, response)
        if body.client_key is not None and uid is not None:
            done = _by_key(conn, uid, body.client_key)
            if done is not None:                 # 같은 요청의 재전송 — 새로 접수하지 않고 같은 번호
                return {'ok': True, 'inquiry_no': done, 'already': True,
                        'note': '이미 접수된 신청이에요. 같은 신청을 두 번 받지 않았어요.'}
        access_gate.check_rate(conn, request, what='mvp3.purchase_inquiry', policy_key=POLICY_KEY,
                               default_per_minute=PER_MINUTE, default_per_day=PER_DAY,
                               messages=LIMIT_MESSAGES)
        qid, code = None, body.product_code
        if body.quote_id is not None:
            q = conn.execute(text(
                "SELECT quote_id, product_snapshot FROM mvp3_saved_recommendations"
                " WHERE quote_id = :q AND user_id = :u"),
                {'q': str(body.quote_id), 'u': uid}).mappings().first()
            # 이 방문자의 견적이 아니면 잇지 않는다. 신청 자체는 받는다 — 연락처를 남기려는
            # 고객을 견적 번호 때문에 돌려보내지 않는다(남의 견적은 이어 붙지 않는다).
            if q is not None:
                qid = str(q['quote_id'])
                snap_code = (q['product_snapshot'] or {}).get('product_code')
                code = snap_code if type(snap_code) is int else code
        cfg = None
        if body.configuration_id is not None:
            # 「새로 구성된 PC」에서 온 신청만 잇는다 — 지금 공개 중인 신규 조립PC 일 때만(부품 상품화 4단계).
            from .custom_pc import customer_list
            if not customer_list(conn, [body.configuration_id]):
                raise HTTPException(409, '이 PC는 지금 공개되어 있지 않아요. 목록을 새로 열어 확인해 주세요.')
            cfg = body.configuration_id
        free = None
        if body.free_build is not None:
            # 지금 판매가·호환으로 다시 계산한 구성만 붙인다 — 판매 중이 아니거나 호환이 깨졌으면 409(고객이 다시 고른다).
            picks, built = free_quote(conn, body.free_build)
            free = json.dumps({'parts': [dict(slot=s, product_code=p['product_code'], name=p['name'],
                                              quantity=p['quantity'], sale_price=p['row']['sale_price'])
                                         for s, p in picks.items() if p is not None],
                               'empty': [s for s, p in picks.items() if p is None],
                               'assembly_fee': ASSEMBLY_FEE, 'total': built['total'],
                               'warnings': built['warnings'], 'priced_at': datetime.now(timezone.utc).isoformat()},
                              ensure_ascii=False)
        fixed = None
        if body.fixed is not None:
            # 접수를 막지 않는다(2026-10-20 대표: 금액·사양이 안 맞으면 전문 상담사가 전화로 조정해 판매한다).
            # 신청 순간의 판매가와 고객이 본 가격을 함께 남겨 상담사가 본다. 카테고리에서 빠진 상품도 번호 그대로 받는다.
            item = customer_supercomputer.load(conn, (body.product_code,)).get(body.product_code) or {
                'product_code': body.product_code, 'official_name': None, 'storage': None, 'price': None, 'sale_state': 'unknown'}
            price = item['price']
            fixed = json.dumps({'product_code': item['product_code'], 'name': item['official_name'],
                                'seen_unit_price': body.fixed.seen_unit_price,
                                'price_differs': body.fixed.seen_unit_price is not None and body.fixed.seen_unit_price != price,
                                'storage': item['storage'], 'intent': body.fixed.intent,
                                'quantity': body.fixed.quantity,
                                'purpose': PURPOSES.get(body.fixed.purpose) if body.fixed.purpose else None,
                                'unit_price': price, 'total': price * body.fixed.quantity if price is not None else None,
                                'sale_state': item['sale_state'],
                                'priced_at': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
        no = _no(conn)
        now = datetime.now(timezone.utc)
        conn.execute(text("""
            INSERT INTO purchase_inquiries
                (inquiry_no, user_id, quote_id, product_code, topic, contact_name, contact_phone,
                 contact_email, message, consent_at, data_origin, purge_at, surface, client_key""" + (', configuration_id' if cfg else '')
            + (', free_build' if free else '') + (', fixed_product' if fixed else '') + """)
            VALUES (:no, :u, :q, :c, :t, :n, :p, :e, :m, :now, :origin, :purge, :surface, :ck""" + (', :cfg' if cfg else '')
            + (', CAST(:free AS jsonb)' if free else '') + (', CAST(:fixed AS jsonb)' if fixed else '') + """)
        """), {'no': no, 'u': uid, 'q': qid, 'c': code, 'cfg': cfg, 'free': free, 'fixed': fixed, 't': body.topic, 'n': name,
               'p': phone, 'e': email, 'm': message, 'now': now,
               'origin': _resolve_data_origin(request), 'purge': now + timedelta(days=KEEP_DAYS),
               'surface': customer_surface.surface_of(request), 'ck': body.client_key})
    log.info('[purchase-inquiry] %s topic_ok=%s quote=%s', no, True, qid is not None)
    return {'ok': True, 'inquiry_no': no,
            'note': '구매 상담 신청을 받았어요. 팝콘PC 담당자가 신청을 확인한 뒤 남겨 주신 연락처로 연락드려요.'}
