# -*- coding: utf-8 -*-
"""AI 슈퍼컴퓨터 상품별 고객 표시 정보 — 관리자 데이터 API (2026-10-20 카테고리 확장, 0166).

■ 상품을 고객 목록에 올리는 순서
  1) 관리자 「카테고리 매핑」(api/admin_category_mapping)에서 상품을 「AI 슈퍼컴퓨터」(public_key 'ai-supercomputer')로 옮긴다.
     → 그 순간 /mvp4 목록·상세·문의에 나온다. 가격·판매 상태는 products 의 지금 값이다.
  2) 이 API 로 그 상품의 표시 정보(제조사·모델명·사진·가속기/프로세서·메모리·저장장치·OS·아키텍처·상세 내용)를 적는다.
     적지 않은 값은 고객 화면에 «확인 필요»로 나온다 — 다른 상품의 값을 물려받지 않는다.

■ 할 수 있는 일
  GET  /api/admin/ai-device-profiles          카테고리에 분류된 상품과 표시 정보(비어 있는 항목 표시)
  PUT  /api/admin/ai-device-profiles/{code}   표시 정보 저장(운영자 이상, 활동 로그). 카테고리에 없는 상품은 거부.
  사진 경로는 /mvp4 정적 자산(assets/images/…) 또는 승인된 상품 사진(/api/product-images/{code}/…)만 받는다.
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

router = APIRouter(prefix="/api/admin")

FIELDS = ('display_name', 'maker', 'model_name', 'accelerator', 'processor', 'memory', 'storage', 'os', 'architecture',
          'model_group', 'model_label')
_IMG = re.compile(r'^(assets/images/[A-Za-z0-9/_.-]+\.(?:png|jpe?g|webp)|/api/product-images/\d+/(?:detail|thumbnail))$')


def _me(write=False):
    me = current_operator() or {}
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    if write and me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 표시 정보를 바꿀 수 있습니다")
    return me


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
    images: list[Image] = Field(default_factory=list, max_length=8)
    detail: dict = Field(default_factory=dict)


def clean(body: ProfileBody) -> dict:
    for im in body.images:
        if not _IMG.match(im.src):
            raise HTTPException(422, "사진은 /mvp4 자산(assets/images/…) 또는 승인된 상품 사진 경로만 쓸 수 있습니다")
    if len(json.dumps(body.detail, ensure_ascii=False)) > 20000:
        raise HTTPException(422, "상세 내용이 너무 깁니다")
    out = {k: ((getattr(body, k) or '').strip() or None) for k in FIELDS}
    out['featured_rank'] = body.featured_rank
    out['images'] = json.dumps([im.model_dump() for im in body.images], ensure_ascii=False)
    out['detail'] = json.dumps(body.detail, ensure_ascii=False)
    return out


@router.get("/ai-device-profiles")
def list_profiles():
    _me()
    with engine.connect() as conn:
        cat = SC.category(conn)
        items = list(SC.load(conn).values()) if cat else []
    empty = [k for k in ('maker', 'accelerator', 'memory', 'storage', 'os')]
    return {"category": {"key": SC.KEY, "name": cat["name"], "category_id": cat["category_id"]} if cat else None,
            "items": [dict(i, missing=[k for k in empty if not i.get(k)] + ([] if i['images'] else ['images']))
                      for i in items],
            "note": "카테고리에 넣으면 고객 목록에 바로 나옵니다. 비어 있는 항목은 고객 화면에 «확인 필요»로 보입니다."}


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
            " VALUES (:code, " + ", ".join(':' + k for k in FIELDS) + ", :featured_rank, CAST(:images AS JSONB), CAST(:detail AS JSONB), now(), :by)"
            " ON CONFLICT (product_code) DO UPDATE SET " + ", ".join(f"{k} = EXCLUDED.{k}" for k in FIELDS) +
            ", featured_rank = EXCLUDED.featured_rank, images = EXCLUDED.images, detail = EXCLUDED.detail,"
            " updated_at = now(), updated_by = EXCLUDED.updated_by"),
            dict(vals, code=code, by=str(me.get("name") or me.get("operator_id") or "")))
        _log(conn, "AI 슈퍼컴퓨터 표시 정보 저장", str(code),
             {k: vals[k] for k in FIELDS if vals[k]}, kind="product")
    return {"ok": True, "verdict": f"상품 {code}의 표시 정보를 저장했습니다"}
