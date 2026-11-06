# -*- coding: utf-8 -*-
"""ASUS 기획전 3종 — 관리자 데이터 API (2026-11-06, 0178). 화면 = /admin2/asus-campaign.

  GET /api/admin/asus-campaign        세 모델 요약 · 쓰기 가능 여부 · 저장 영향 안내
  GET /api/admin/asus-campaign/{id}   한 모델 전체(몰 번호 포함) · 버전
  PUT /api/admin/asus-campaign/{id}   저장(운영자 이상) — expected_version 이 다르면 409, 값이 같으면 저장하지 않는다

■ 권한  읽기 viewer · 쓰기 operator 이상. 미들웨어(auth.required_role)가 먼저 막고 여기서 한 번 더 본다.
■ 동시 편집  저장소에 낙관적 잠금 선례가 없어(2026-11-06 확인) version 열로 새로 둔다. 먼저 저장한 사람의 값을
  덮어쓰지 않고, 화면은 입력을 유지한 채 최신값을 다시 불러오게 안내한다.
■ 감사  admin_operator_activity_logs(target_kind='asus_campaign') — 바뀐 칸과 전후 값을 같은 트랜잭션에 남긴다.
■ 범위  asus_campaign_models 한 표만 쓴다. products · 가격 · 재고 · 원가를 건드리지 않는다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import asus_campaign as AC
from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

SAVE_NOTE = ("저장하면 ASUS 기획전 서브메인 · 해당 모델 상세 · 문의 안내에 바로 반영됩니다. 승인 단계가 없습니다. "
             "일반 상품 · 판매가 · 재고 · 추천에는 영향이 없고, 홈 배너와 공통 고지(합계 · 호환 · 배송 안내)는 바뀌지 않습니다.")
PRICE_NOTE = "부품 표시가를 고치면 「가격 기준 안내」의 조회일도 함께 확인해 주세요. 이 값은 실시간 가격이 아닙니다."
MISSING_ROW = "이 모델의 DB 값이 없습니다. 초기화(마이그레이션 0178) 상태를 확인해 주세요."
LOG_MAX_PATHS = 40


class SaveBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: StrictInt = Field(ge=1)
    plan_review_price: StrictInt | None = Field(default=None, ge=1, le=AC.PRICE_MAX)
    content: AC.Content


def _me(write=False):
    me = current_operator() or {}
    if not me:
        raise HTTPException(401, "로그인이 필요합니다")
    if write and me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 기획전 정보를 바꿀 수 있습니다")
    return me


def _known(model_id: str) -> None:
    if model_id not in AC.MODEL_IDS:
        raise HTTPException(404, "알 수 없는 기획전 모델입니다")


def _flat(value, path=''):
    """바뀐 칸만 감사에 남기려고 펼친다."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(_flat(v, f'{path}.{k}' if path else k))
        return out
    if isinstance(value, list):
        out = {f'{path}#count': len(value)}
        for i, v in enumerate(value):
            out.update(_flat(v, f'{path}[{i}]'))
        return out
    return {path: value}


def changes(old: dict, new: dict) -> dict:
    a, b = _flat(old), _flat(new)
    return {k: {'before': a.get(k), 'after': b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def _db_fail():
    return HTTPException(503, "기획전 표를 읽지 못했습니다. 마이그레이션 0178 적용 여부를 확인해 주세요.")


@router.get("/asus-campaign")
def list_models():
    me = _me()
    try:
        with engine.connect() as conn:
            rows = AC.read_rows(conn)
    except SQLAlchemyError:
        raise _db_fail() from None
    items = [{"id": i, "name": (rows[i]['content'] or {}).get('name'), "version": rows[i]['version'],
              "origin": rows[i]['origin'], "updated_at": iso(rows[i]['updated_at'])}
             for i in AC.MODEL_IDS if i in rows]
    return {"ok": True, "items": items, "missing": [i for i in AC.MODEL_IDS if i not in rows],
            "can_write": me.get("role") in ("owner", "operator"), "save_note": SAVE_NOTE, "price_note": PRICE_NOTE}


@router.get("/asus-campaign/{model_id}")
def get_model(model_id: str):
    me = _me()
    _known(model_id)
    try:
        with engine.connect() as conn:
            row = AC.read_rows(conn).get(model_id)
            by = None
            if row is not None and row['updated_by'] is not None:
                by = conn.execute(text("SELECT name FROM admin_operators WHERE operator_id = :i"),
                                  {"i": row['updated_by']}).scalar()
    except SQLAlchemyError:
        raise _db_fail() from None
    if row is None:
        raise HTTPException(404, MISSING_ROW)
    return {"ok": True, "id": model_id, "version": row['version'], "origin": row['origin'],
            "updated_at": iso(row['updated_at']), "updated_by": by,
            "plan_review_price": row['plan_review_price'], "content": row['content'],
            "plan_label": AC.PLAN_LABEL, "states": AC.STATES, "icons": AC.ICONS,
            "hero_images": AC.HERO_IMAGES, "use_images": AC.USE_IMAGES,
            "can_write": me.get("role") in ("owner", "operator"), "save_note": SAVE_NOTE, "price_note": PRICE_NOTE}


@router.put("/asus-campaign/{model_id}")
def save_model(model_id: str, body: SaveBody):
    me = _me(write=True)
    _known(model_id)
    try:
        AC.check_model(model_id, body.content)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    new = body.content.model_dump()
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT plan_review_price, content, version FROM asus_campaign_models"
                                    " WHERE model_id = :i FOR UPDATE"), {"i": model_id}).mappings().first()
            if row is None:
                raise HTTPException(404, MISSING_ROW)
            if row['version'] != body.expected_version:
                raise HTTPException(409, f"다른 사람이 먼저 저장했습니다(현재 버전 {row['version']}). "
                                         "입력한 내용을 확인한 뒤 최신값을 다시 불러와 주세요.")
            diff = changes({'plan_review_price': row['plan_review_price'], 'content': row['content']},
                           {'plan_review_price': body.plan_review_price, 'content': new})
            if not diff:
                return {"ok": True, "changed": False, "version": row['version'],
                        "verdict": "바뀐 내용이 없어 저장하지 않았습니다."}
            saved = conn.execute(text(
                "UPDATE asus_campaign_models SET content = CAST(:c AS JSONB), plan_review_price = :p,"
                " version = version + 1, origin = 'admin', updated_at = now(), updated_by = :by"
                " WHERE model_id = :i AND version = :v RETURNING version, updated_at"),
                {"c": json.dumps(new, ensure_ascii=False), "p": body.plan_review_price, "by": me.get("operator_id"),
                 "i": model_id, "v": body.expected_version}).mappings().one()
            paths = list(diff)
            _log(conn, "ASUS 기획전 구성 저장", model_id,
                 {"version_from": body.expected_version, "version_to": saved['version'], "changed_count": len(paths),
                  "changes": {k: diff[k] for k in paths[:LOG_MAX_PATHS]},
                  "changes_truncated": len(paths) > LOG_MAX_PATHS}, kind="asus_campaign")
    except SQLAlchemyError:
        raise _db_fail() from None
    return {"ok": True, "changed": True, "version": saved['version'], "updated_at": iso(saved['updated_at']),
            "changed_count": len(paths), "verdict": f"저장했습니다(버전 {saved['version']}).", "note": SAVE_NOTE}
