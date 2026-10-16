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
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import text

from . import access_gate, visitor
from .db import engine
from .mvp3_contact import EMAIL_RE, KEEP_DAYS, PHONE_RE   # 정규식·보관 기한은 한 곳(mvp3_contact)
from .mvp3_saved_quotes import same_origin
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
CONSENT_TEXT = ('구매 상담 연락을 위해 이름·연락처·문의 내용을 받고, 신청 후 %d일이 지나면 지웁니다.'
                % KEEP_DAYS)


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


def _clean(body: InquiryBody):
    if body.topic not in TOPICS:
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
def form_meta():
    """신청 칸이 쓰는 선택지와 동의 문구 — 화면이 다시 적지 않게 서버가 준다."""
    return {'ok': True, 'topics': list(TOPICS), 'consent_text': CONSENT_TEXT}


@router.post('/purchase-inquiries')
def create_inquiry(body: InquiryBody, request: Request, response: Response):
    same_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    phone, email, name, message = _clean(body)
    with engine.begin() as conn:
        uid = visitor.resolve(conn, request, response)
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
        no = _no(conn)
        now = datetime.now(timezone.utc)
        conn.execute(text("""
            INSERT INTO purchase_inquiries
                (inquiry_no, user_id, quote_id, product_code, topic, contact_name, contact_phone,
                 contact_email, message, consent_at, data_origin, purge_at""" + (', configuration_id' if cfg else '') + """)
            VALUES (:no, :u, :q, :c, :t, :n, :p, :e, :m, :now, :origin, :purge""" + (', :cfg' if cfg else '') + """)
        """), {'no': no, 'u': uid, 'q': qid, 'c': code, 'cfg': cfg, 't': body.topic, 'n': name,
               'p': phone, 'e': email, 'm': message, 'now': now,
               'origin': _resolve_data_origin(request), 'purge': now + timedelta(days=KEEP_DAYS)})
    log.info('[purchase-inquiry] %s topic_ok=%s quote=%s', no, True, qid is not None)
    return {'ok': True, 'inquiry_no': no,
            'note': '구매 상담 신청을 받았어요. 팝콘PC 담당자가 신청을 확인한 뒤 남겨 주신 연락처로 연락드려요.'}
