# -*- coding: utf-8 -*-
"""AI 슈퍼컴퓨터 상품별 고객 표시 정보 — 관리자 데이터 API (2026-10-20 카테고리 확장, 0166 · 2026-10-31 화면 연결, 관리자단 개선 PR-2).

■ 상품을 고객 목록에 올리는 순서
  1) 관리자 「카테고리 매핑」(api/admin_category_mapping)에서 상품을 「AI 슈퍼컴퓨터」(public_key 'ai-supercomputer')로 옮긴다.
     → 그 순간 /mvp4 목록·상세·문의에 나온다. 가격·판매 상태는 products 의 지금 값이다.
  2) 이 API(화면 /admin2/ai-device-profiles · templates/admin/ai_device_profiles.html.j2)로 그 상품의 표시 정보
     (제조사·모델명·사진·가속기/프로세서·메모리·저장장치·OS·아키텍처·모델 묶음·진열 순위)를 적는다.
     적지 않은 값은 고객 화면에 «확인 필요»로 나온다 — 다른 상품의 값을 물려받지 않는다.
     다만 표시 이름(display_name)이 비어 있는 동안은 상품명에서 읽을 수 있는 값(용량 · GB10 플랫폼 공통 사양)을
     api/customer_supercomputer.derive 가 고객 화면에 채운다 — 그것은 «상품명 기준» 값이지 저장값이 아니다.
     이 API 는 둘을 따로 낸다(saved · derived · customer). 표시 이름을 저장하면 그 자동 채움이 꺼진다(customer_supercomputer.item).

■ 할 수 있는 일
  GET  /api/admin/ai-device-profiles          카테고리에 분류된 상품과 표시 정보(비어 있는 항목 · 마지막 저장)
  GET  /api/admin/ai-device-profiles/{code}   한 상품 — 저장값(saved) · 상품명 기준 값(derived) · 고객 화면이 지금 보이는 값(customer)
  PUT  /api/admin/ai-device-profiles/{code}   표시 정보 저장(운영자 이상, 활동 로그). 카테고리에 없는 상품은 거부.
       글 칸(FIELDS)과 진열 순위는 보낸 값으로 바뀐다(비우면 비운다). **images · detail 은 보내지 않으면 그대로 둔다**
       (2026-10-31 전에는 보내지 않은 사진·상세가 빈 값으로 덮였다). 상세(detail)는 이 화면에서 고치지 않는다.
  사진 경로는 /mvp4 정적 자산(assets/images/…) 또는 승인된 상품 사진(/api/product-images/{code}/…)만 받는다.
  저장은 고객 화면에 바로 반영된다(승인 단계 없음) — 화면이 그 사실을 저장 단추 옆에 밝힌다.
"""
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from . import customer_supercomputer as SC
from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

FIELDS = ('display_name', 'maker', 'model_name', 'accelerator', 'processor', 'memory', 'storage', 'os', 'architecture',
          'model_group', 'model_label')
FIELD_LABELS = {'display_name': '표시 이름', 'maker': '제조사', 'model_name': '모델명', 'accelerator': '가속기',
                'processor': '프로세서', 'memory': '메모리', 'storage': '저장장치', 'os': '운영체제',
                'architecture': '아키텍처', 'model_group': '모델 묶음 키', 'model_label': '모델 라벨'}
# 고객 화면이 «확인 필요»로 보이는 다섯 + 사진 — 목록의 「비어 있는 항목」은 고객 화면이 지금 보이는 값(상품명 기준 포함) 기준이다.
CUSTOMER_REQUIRED = ('maker', 'accelerator', 'memory', 'storage', 'os')
_IMG = re.compile(r'^(assets/images/[A-Za-z0-9/_.-]+\.(?:png|jpe?g|webp)|/api/product-images/\d+/(?:detail|thumbnail))$')
IMAGE_RULE = "사진은 /mvp4 자산(assets/images/…) 또는 승인된 상품 사진(/api/product-images/{상품코드}/detail · thumbnail) 경로만 쓸 수 있습니다."
SAVE_NOTE = "저장하면 고객 화면(/mvp4 AI 슈퍼컴퓨터 목록 · 상세)에 바로 반영됩니다. 승인 단계가 없습니다."
LIST_NOTE = "카테고리에 넣으면 고객 목록에 바로 나옵니다. 비어 있는 항목은 고객 화면에 «확인 필요»로 보입니다."


def _me(write=False):
    me = current_operator() or {}
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    if write and me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 표시 정보를 바꿀 수 있습니다")
    return me


def _can_write(me) -> bool:
    return (me or {}).get("role") in ("owner", "operator")


class Image(BaseModel):
    model_config = ConfigDict(extra='forbid')
    src: str = Field(max_length=200)
    label: str | None = Field(default=None, max_length=40)
    alt: str | None = Field(default=None, max_length=120)


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str | None = Field(default=None, max_length=80)
    maker: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=80)
    accelerator: str | None = Field(default=None, max_length=80)
    processor: str | None = Field(default=None, max_length=80)
    memory: str | None = Field(default=None, max_length=40)
    storage: str | None = Field(default=None, max_length=40)
    os: str | None = Field(default=None, max_length=60)
    architecture: str | None = Field(default=None, max_length=30)
    model_group: str | None = Field(default=None, pattern=r'^[a-z0-9-]{2,60}$')
    model_label: str | None = Field(default=None, max_length=30)
    featured_rank: int | None = Field(default=None, ge=1, le=99)
    # None = 보내지 않음 = 기존 값 유지. 빈 목록/빈 객체는 «비운다»는 뜻이다.
    images: list[Image] | None = Field(default=None, max_length=8)
    detail: dict | None = None


def clean(body: ProfileBody) -> dict:
    for im in (body.images or []):
        if not _IMG.match(im.src):
            raise HTTPException(422, "사진은 /mvp4 자산(assets/images/…) 또는 승인된 상품 사진 경로만 쓸 수 있습니다")
    if body.detail is not None and len(json.dumps(body.detail, ensure_ascii=False)) > 20000:
        raise HTTPException(422, "상세 내용이 너무 깁니다")
    out = {k: ((getattr(body, k) or '').strip() or None) for k in FIELDS}
    out['featured_rank'] = body.featured_rank
    out['images'] = None if body.images is None else json.dumps([im.model_dump() for im in body.images], ensure_ascii=False)
    out['detail'] = None if body.detail is None else json.dumps(body.detail, ensure_ascii=False)
    return out


def _missing(item: dict) -> list:
    return [k for k in CUSTOMER_REQUIRED if not item.get(k)] + ([] if item.get('images') else ['images'])


@router.get("/ai-device-profiles")
def list_profiles():
    me = _me()
    with engine.connect() as conn:
        cat = SC.category(conn)
        items = list(SC.load(conn).values()) if cat else []
        saved = {r['product_code']: r for r in conn.execute(text(
            "SELECT product_code, updated_at, updated_by FROM ai_device_profiles")).mappings()} if cat else {}
    out = []
    for i in items:
        s = saved.get(i['product_code'])
        out.append(dict(i, missing=_missing(i), has_profile=s is not None,
                        saved_at=iso(s['updated_at']) if s else None, saved_by=s['updated_by'] if s else None))
    return {"category": {"key": SC.KEY, "name": cat["name"], "category_id": cat["category_id"]} if cat else None,
            "items": out, "can_write": _can_write(me),
            # 한 번에 내는 상한(customer_supercomputer.LIMIT) — 넘으면 목록이 잘린 것이지 상품이 없는 것이 아니다.
            "limit": SC.LIMIT, "truncated": len(items) >= SC.LIMIT,
            "fields": list(FIELDS), "field_labels": FIELD_LABELS, "image_rule": IMAGE_RULE, "save_note": SAVE_NOTE,
            "note": LIST_NOTE}


@router.get("/ai-device-profiles/{code}")
def get_profile(code: int):
    me = _me()
    with engine.connect() as conn:
        customer = SC.load(conn, (code,)).get(code)
        if customer is None:
            raise HTTPException(404, "AI 슈퍼컴퓨터 카테고리에 분류된 상품이 아닙니다")
        row = conn.execute(text("SELECT " + ", ".join(FIELDS) + ", featured_rank, images, detail, updated_at, updated_by"
                                " FROM ai_device_profiles WHERE product_code = :c"), {"c": code}).mappings().first()
        p = conn.execute(text("SELECT product_name, maker, sale_price, status FROM products WHERE product_code = :c"),
                         {"c": code}).mappings().one()
    saved = None
    if row:
        saved = {k: row[k] for k in FIELDS}
        saved.update(featured_rank=row['featured_rank'], images=row['images'] or [], detail=row['detail'] or {},
                     updated_at=iso(row['updated_at']), updated_by=row['updated_by'])
    derived = {k: v for k, v in SC.derive(p['product_name'], p['maker']).items() if v}
    return {"ok": True, "product_code": code,
            "product": {"product_name": p['product_name'], "maker": p['maker'], "sale_price": p['sale_price'],
                        "status": p['status'], "price": customer['price'], "sale_state": customer['sale_state'],
                        "mall_url": customer['mall_url']},
            "saved": saved, "derived": derived,
            # customer_supercomputer.item 과 같은 조건 — 표시 이름이 비어 있을 때만 상품명 기준 값이 고객 화면을 채운다.
            "derive_active": saved is None or not saved.get('display_name'),
            "customer": customer, "missing": _missing(customer),
            "fields": list(FIELDS), "field_labels": FIELD_LABELS,
            "can_write": _can_write(me), "image_rule": IMAGE_RULE, "save_note": SAVE_NOTE}


@router.put("/ai-device-profiles/{code}")
def put_profile(code: int, body: ProfileBody):
    _me(write=True)
    vals = clean(body)
    with engine.begin() as conn:
        if SC.load(conn, (code,)).get(code) is None:
            raise HTTPException(409, "AI 슈퍼컴퓨터 카테고리에 분류된 상품만 표시 정보를 적을 수 있습니다")
        me = current_operator() or {}
        conn.execute(text(
            "INSERT INTO ai_device_profiles (product_code, " + ", ".join(FIELDS) + ", featured_rank, images, detail, updated_at, updated_by)"
            " VALUES (:code, " + ", ".join(':' + k for k in FIELDS) + ", :featured_rank,"
            "  COALESCE(CAST(:images AS JSONB), '[]'::jsonb), COALESCE(CAST(:detail AS JSONB), '{}'::jsonb), now(), :by)"
            " ON CONFLICT (product_code) DO UPDATE SET " + ", ".join(f"{k} = EXCLUDED.{k}" for k in FIELDS) +
            ", featured_rank = EXCLUDED.featured_rank,"
            # 보내지 않은(NULL) 사진·상세는 기존 값을 지킨다 — 빈 목록/빈 객체를 보내면 비운다.
            "  images = COALESCE(CAST(:images AS JSONB), ai_device_profiles.images),"
            "  detail = COALESCE(CAST(:detail AS JSONB), ai_device_profiles.detail),"
            "  updated_at = now(), updated_by = EXCLUDED.updated_by"),
            dict(vals, code=code, by=str(me.get("name") or me.get("operator_id") or "")))
        _log(conn, "AI 슈퍼컴퓨터 표시 정보 저장", str(code),
             dict({k: vals[k] for k in FIELDS if vals[k]}, featured_rank=vals['featured_rank'],
                  images=('유지' if body.images is None else '%d장' % len(body.images)),
                  detail=('유지' if body.detail is None else '변경')), kind="product")
    return {"ok": True, "verdict": f"상품 {code}의 표시 정보를 저장했습니다", "note": SAVE_NOTE}
