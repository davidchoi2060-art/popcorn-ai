"""MVP3 방문자 연락처 -- 견적을 처음 보관할 때 한 번만 받는다 (2026-10-16 대표 지시).

■ 규칙
  · 전화번호 필수, 이름·이메일 선택. 방문자(`visitor.resolve` 의 user_id) 한 명에 한 줄.
  · 다음 견적은 이 줄을 재사용한다. 바꾸는 것은 고객이 「연락처 변경」을 눌렀을 때뿐이다.
  · 견적 보관은 상담 신청이 아니다. 이 줄이 있다고 상담사가 먼저 연락하지 않는다.
  · 응답에는 가린 번호만 싣는다. 전체 번호와 이메일은 되돌려 주지 않는다.
  · 보관 기한 180일(`KEEP_DAYS`) -- 등록·변경 때마다 새로 잡고, 지난 줄은 「없는 것」으로 읽는다.
    값은 일일 작업(`api/retention_purge.py` 의 `visitor_contact`)이 비운다.
  · 로그에는 번호·이메일을 찍지 않는다(ASCII 문구만).

■ 이 모듈은 라우터가 없다
  `api/mvp3_saved_quotes` 가 가져다 쓰고, `api/mvp3_purchase_inquiry` 가 같은 정규식을 쓴다.
  라우트(GET/PUT /contact · from-quote)는 `api/mvp3_quote_consult` 에 둔다 -- 순환 import 를 피한다.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import text

KEEP_DAYS = 180
PHONE_RE = re.compile(r'^0\d{1,2}-?\d{3,4}-?\d{4}$')
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,100}\.[^@\s]{2,}$')
# ⚠ 대표가 실제 개인정보 처리 방침(수집 항목 · 보유 기간 · 동의 범위)을 확인하기 전의 문구다.
#   고치면 이 상수 하나만 고친다 -- 화면은 서버가 준 문구만 쓴다. 동의 시점의 문구는 줄에 함께 남긴다.
CONSENT_TEXT = ('견적 보관과 고객님이 신청한 구매 상담 연락을 위해 전화번호(필수)와 이름·이메일(선택)을 받고, '
                '등록하거나 바꾼 뒤 %d일이 지나면 지웁니다. 상담을 신청하기 전에는 먼저 연락드리지 않습니다.' % KEEP_DAYS)
REQUIRED_MESSAGE = '견적을 보관하려면 전화번호를 입력하고 개인정보 수집·이용에 동의해 주세요.'


class ContactIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    phone: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    consent: StrictBool = False


def clean(contact):
    """입력을 검사해 (phone, name, email) 로 돌려준다. 틀리면 422."""
    if contact.consent is not True:
        raise HTTPException(422, '전화번호를 받으려면 개인정보 수집·이용에 동의해 주세요.')
    phone = re.sub(r'\s+', '', contact.phone or '')
    if not phone:
        raise HTTPException(422, '전화번호를 입력해 주세요.')
    if not PHONE_RE.match(phone):
        raise HTTPException(422, '전화번호 형식을 확인해 주세요. 예: 010-1234-5678')
    email = (contact.email or '').strip() or None
    if email and not EMAIL_RE.match(email):
        raise HTTPException(422, '이메일 형식을 확인해 주세요.')
    return phone, (contact.name or '').strip() or None, email


def mask_phone(phone):
    """010-1234-5678 -> 010-****-5678. 숫자가 모자라면 앞을 모두 가린다."""
    d = re.sub(r'\D', '', phone or '')
    if len(d) < 9:
        return '****' if d else None
    head = d[:3] if len(d) == 11 or not d.startswith('02') else d[:2]
    return '%s-****-%s' % (head, d[-4:])


def required_error():
    """연락처가 없을 때의 422 본문 -- 화면은 `contact_required` 로 보관 창을 연다."""
    return HTTPException(422, {'error': 'contact_required', 'contact_required': True, 'detail': REQUIRED_MESSAGE,
                               'consent_text': CONSENT_TEXT})


def current(conn, uid):
    """이 방문자의 유효한 연락처 줄(없거나 기한이 지났으면 None)."""
    return conn.execute(text(
        'SELECT contact_phone, contact_name, contact_email, consent_at, purge_at FROM mvp3_visitor_contacts'
        ' WHERE user_id = :u AND contact_purged_at IS NULL AND contact_phone IS NOT NULL AND purge_at > :now'),
        {'u': uid, 'now': datetime.now(timezone.utc)}).mappings().first()


def upsert(conn, uid, contact, origin):
    """연락처를 등록하거나 바꾼다(같은 트랜잭션에서). 기한은 지금부터 다시 잡는다."""
    phone, name, email = clean(contact)
    now = datetime.now(timezone.utc)
    conn.execute(text(
        'INSERT INTO mvp3_visitor_contacts (user_id, contact_phone, contact_name, contact_email, consent_at,'
        ' consent_text, data_origin, created_at, updated_at, purge_at, contact_purged_at)'
        ' VALUES (:u, :p, :n, :e, :now, :t, :o, :now, :now, :purge, NULL)'
        ' ON CONFLICT (user_id) DO UPDATE SET contact_phone = EXCLUDED.contact_phone,'
        ' contact_name = EXCLUDED.contact_name, contact_email = EXCLUDED.contact_email,'
        ' consent_at = EXCLUDED.consent_at, consent_text = EXCLUDED.consent_text,'
        ' updated_at = EXCLUDED.updated_at, purge_at = EXCLUDED.purge_at, contact_purged_at = NULL'),
        {'u': uid, 'p': phone, 'n': name, 'e': email, 'now': now, 't': CONSENT_TEXT, 'o': origin,
         'purge': now + timedelta(days=KEEP_DAYS)})
    return {'phone': phone, 'name': name, 'email': email}


def view(row):
    """응답용 -- 가린 번호만. 전체 번호·이메일은 내보내지 않는다."""
    if not row:
        return {'has_contact': False, 'masked_phone': None, 'name': None}
    return {'has_contact': True, 'masked_phone': mask_phone(row['contact_phone']), 'name': row['contact_name']}
