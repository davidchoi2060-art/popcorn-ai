# -*- coding: utf-8 -*-
"""ASUS 기획전 3종 — DB 원천 · 입력 규칙 · 고객 읽기 API (2026-11-06, 0178).

■ 왜 전용 표인가
  이 3종은 판매 상품이 아니다. 399·599·1,299만원은 「기획 검토가 · ASUS 협의 전」이고 부품 후보는 미확정이다.
  products / sale_price / 추천 후보에 넣으면 장바구니·추천·재고가 «확정 상품»으로 읽는다. 그래서 이 모듈은
  products 를 읽지도 쓰지도 않는다. 부품 후보의 표시가는 조회 기록이지 실시간 가격이 아니다.

■ 무엇이 DB 이고 무엇이 코드인가
  DB   : 모델별 이름 · 문구 · 이미지 · 추천 대상 · 활용 예시 · 부품 후보 · 상태 · 표시가 · 기획 검토가
  코드 : 「기획 검토가 · ASUS 협의 전」 표기, 합계 없음 · 호환 · 배송 · 조립비 고지, 문의 항목 매핑(asus-data.js).
         저장으로 고지를 지울 수 없게 일부러 코드에 둔다. 고지를 바꾸는 것은 정책 결정이고 배포를 거친다.

■ 고객 API 가 내지 않는 것
  mall_no(몰 상품번호 · 대조용) · version · updated_by. 허용 필드만 다시 조립한다(public_model) — 새 필드가 생겨도
  자동으로 새어 나가지 않는다.

■ 실패를 숨기지 않는다
  표가 없거나 DB 가 실패하면 503, 비어 있으면 빈 목록, 저장값이 규칙에 어긋나면 그 모델만 unavailable 로 낸다.
  화면은 어떤 경우에도 코드의 옛 값으로 대신하지 않는다(코드에 모델 값이 없다).
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db import engine

log = logging.getLogger(__name__)
router = APIRouter()

MODEL_IDS = ('business', 'video', 'local-ai')
PLAN_LABEL = '기획 검토가 · ASUS 협의 전'
PLAN_NOTE = '아직 판매 가격이 정해지지 않았습니다.'
PRICE_MAX = 99_999_999

# 값 = 고객 화면 표기. 화면(asus-data.js STATES)과 같아야 한다 — tests/test_asus_campaign_20261106.py 가 대조한다.
STATES = {'sale': '판매중 확인', 'candidate': '구성 후보', 'check': '확인 필요',
          'conflict': '자료 확인 전 확정 불가', 'supply': '공급 확인 필요', 'separate': '별도 문의'}
PLAIN = 'plain'     # 그래픽 메모리 줄: 상태·후보가 없는 표기 전용
# 항목은 고정이다. 운영체제·쿨러·파워 같은 미확정 줄을 저장으로 지울 수 없다.
PART_LABELS = ('CPU(중앙처리장치)', 'GPU(그래픽카드)', '그래픽 메모리', '메모리(RAM)', 'SSD(저장장치)', '메인보드',
               '파워(PSU)', '케이스', 'CPU 쿨러', '추가 시스템팬', '운영체제')
ICONS = ('file-text', 'headset', 'user', 'video-camera', 'users', 'image', 'code', 'cpu')
# mockups/mvp4/assets/images/asus/ 의 소재만. 경로·외부 주소·새 파일명은 받지 않는다.
HERO_IMAGES = ('gt502-black-cutout.webp',)
USE_IMAGES = ('use-business-1.webp', 'use-business-2.webp', 'use-business-3.webp',
              'use-video-1.webp', 'use-video-2.webp', 'use-video-3.webp',
              'use-ai-1.webp', 'use-ai-2.webp', 'use-ai-3.webp')
_NO_PRICE_STATES = ('supply', 'separate')
_BAD_TEXT = re.compile(r'[<>\x00-\x1f\x7f]|javascript\s*:|data\s*:\s*text|\bon[a-z]+\s*=', re.I)
_DATA_FILE = Path(__file__).resolve().parents[1] / 'db/migrations/data/asus_campaign_models_20261106.json'


def _optional_line(value):
    """한 줄 글자만 받는다. 화면은 다시 이스케이프하지만, 저장 단계에서 먼저 막는다. 빈 값은 None."""
    if value is None:
        return None
    value = value.strip()
    if _BAD_TEXT.search(value):
        raise ValueError('꺾쇠·제어 문자·스크립트 표현은 쓸 수 없습니다')
    return value or None


def _required_line(value):
    value = _optional_line(value)
    if value is None:
        raise ValueError('값을 입력해 주세요')
    return value


Line = Annotated[str, AfterValidator(_required_line)]
OptLine = Annotated[str | None, AfterValidator(_optional_line)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Who(_Strict):
    text: Line = Field(max_length=40)
    icon: Literal['file-text', 'headset', 'user', 'video-camera', 'users', 'image', 'code', 'cpu']


class Use(_Strict):
    title: Line = Field(max_length=60)
    text: Line = Field(max_length=300)
    example: OptLine = Field(default=None, max_length=120)
    steps: list[Annotated[Line, Field(max_length=30)]] = Field(min_length=1, max_length=6)
    image: str = Field(max_length=60)
    alt: Line = Field(max_length=100)

    @field_validator('image')
    @classmethod
    def _image(cls, v):
        if v not in USE_IMAGES:
            raise ValueError('허용된 활용 이미지가 아닙니다')
        return v


class Option(_Strict):
    name: Line = Field(max_length=120)
    state: Literal['sale', 'candidate', 'check', 'conflict', 'supply', 'separate']
    # StrictInt: 문자열·소수·참거짓을 숫자로 바꿔 받지 않는다. 0은 받지 않는다(0원 표시 금지) — 모르면 null 이다.
    price: StrictInt | None = Field(default=None, ge=1, le=PRICE_MAX)
    premium: StrictInt | None = Field(default=None, ge=1, le=PRICE_MAX)
    note: OptLine = Field(default=None, max_length=200)
    mall_no: StrictInt | None = Field(default=None, ge=1, le=99_999_999)

    @field_validator('note')
    @classmethod
    def _note(cls, v):
        return v or ''

    @model_validator(mode='after')
    def _prices(self):
        if self.state in _NO_PRICE_STATES and (self.price is not None or self.premium is not None):
            raise ValueError(f'「{STATES[self.state]}」 후보에는 가격을 넣을 수 없습니다')
        if self.premium is not None and self.price is None:
            raise ValueError('일반회원가 없이 프리미엄 표시가만 넣을 수 없습니다')
        return self


class Part(_Strict):
    label: str = Field(max_length=30)
    head: Line = Field(max_length=80)
    status: Literal['sale', 'candidate', 'check', 'conflict', 'supply', 'separate', 'plain']
    options: list[Option] = Field(default_factory=list, max_length=6)

    @model_validator(mode='after')
    def _shape(self):
        if self.label == '그래픽 메모리':
            if self.status != PLAIN or self.options:
                raise ValueError('그래픽 메모리는 표기만 있는 줄입니다')
            return self
        if self.status == PLAIN or not self.options:
            raise ValueError(f'{self.label}: 상태와 후보가 필요합니다')
        if self.label == '운영체제' and self.status != 'separate':
            raise ValueError('운영체제는 별도 문의 상태를 유지합니다')
        return self


class Content(_Strict):
    name: Line = Field(max_length=30)
    tagline: Line = Field(max_length=80)
    hero_image: str = Field(max_length=60)
    hero_alt: Line = Field(max_length=100)
    for_who: list[Who] = Field(min_length=1, max_length=4)
    uses: list[Use] = Field(min_length=1, max_length=3)
    prepare: OptLine = Field(default=None, max_length=200)
    explain: OptLine = Field(default=None, max_length=300)
    limit: OptLine = Field(default=None, max_length=200)
    price_basis: Line = Field(max_length=400)
    parts: list[Part] = Field(min_length=len(PART_LABELS), max_length=len(PART_LABELS))

    @field_validator('hero_image')
    @classmethod
    def _hero(cls, v):
        if v not in HERO_IMAGES:
            raise ValueError('허용된 대표 이미지가 아닙니다')
        return v

    @model_validator(mode='after')
    def _labels(self):
        if tuple(p.label for p in self.parts) != PART_LABELS:
            raise ValueError('부품 항목과 순서는 바꿀 수 없습니다')
        return self


def valid_plan(value) -> bool:
    """기획 검토가. None = 미정(0원으로 표시하지 않는다)."""
    return value is None or (type(value) is int and 1 <= value <= PRICE_MAX)


def check_model(model_id: str, content: Content) -> None:
    """모델별 고지. 로컬 AI 모델은 «모든 모델이 실행되는 것은 아님» 고지를 비울 수 없다."""
    if model_id == 'local-ai' and not content.limit:
        raise ValueError('로컬 AI 모델은 실행 제한 안내가 필요합니다')


def _part(content: dict, label: str) -> dict:
    return next(p for p in content['parts'] if p['label'] == label)


def public_model(model_id: str, plan, content: dict) -> dict:
    """고객에게 나가는 값 전부. 허용 필드만 고른다. 규칙에 어긋난 저장값은 ValueError 다."""
    parsed = Content.model_validate(content)
    check_model(model_id, parsed)
    if not valid_plan(plan):
        raise ValueError('plan_review_price')
    c = parsed.model_dump()
    parts = [{'label': p['label'], 'head': p['head'], 'status': p['status'],
              'options': [{k: o[k] for k in ('name', 'state', 'price', 'premium', 'note')} for o in p['options']]}
             for p in c['parts']]
    return {'id': model_id, 'name': c['name'], 'tagline': c['tagline'],
            'hero_image': c['hero_image'], 'hero_alt': c['hero_alt'],
            'for_who': c['for_who'], 'uses': c['uses'], 'prepare': c['prepare'], 'explain': c['explain'],
            'limit': c['limit'], 'price_basis': c['price_basis'], 'parts': parts,
            'plan_review_price': plan, 'plan_label': PLAN_LABEL, 'plan_note': PLAN_NOTE,
            # 상단·카드 표기는 전체 표의 머리값과 같아야 하므로 따로 저장하지 않고 여기서 만든다.
            'cpu': _part(c, 'CPU(중앙처리장치)')['head'], 'gpu': _part(c, 'GPU(그래픽카드)')['head'],
            'gpu_status': _part(c, 'GPU(그래픽카드)')['status'], 'vram': _part(c, '그래픽 메모리')['head'],
            'ram': _part(c, '메모리(RAM)')['head'], 'ssd': _part(c, 'SSD(저장장치)')['head']}


def read_rows(conn) -> dict:
    rows = conn.execute(text("SELECT model_id, plan_review_price, content, version, origin, updated_at, updated_by"
                             " FROM asus_campaign_models")).mappings()
    return {r['model_id']: r for r in rows}


def seed_models() -> dict:
    """PR447 초깃값(0178 과 같은 파일)."""
    return json.loads(_DATA_FILE.read_text(encoding='utf-8'))['models']


@router.get('/api/customer/asus-campaign')
def customer_campaign(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        with engine.connect() as conn:
            rows = read_rows(conn)
    except SQLAlchemyError:
        log.exception('[asus-campaign] customer read failed')
        raise HTTPException(503, '기획전 정보를 불러오지 못했습니다.') from None
    models, unavailable = [], []
    for model_id in MODEL_IDS:
        row = rows.get(model_id)
        if row is None:
            continue
        try:
            models.append(public_model(model_id, row['plan_review_price'], row['content']))
        except (ValidationError, ValueError, TypeError):
            log.warning('[asus-campaign] stored row rejected: %s', model_id)
            unavailable.append(model_id)
    return {'ok': True, 'checked_at': datetime.now(timezone.utc).isoformat(), 'models': models,
            'unavailable': unavailable}
