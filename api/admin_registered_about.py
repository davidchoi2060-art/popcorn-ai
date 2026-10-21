# -*- coding: utf-8 -*-
"""승인 구성이 없는 판매 PC 의 상세 소개 조회·수정 (0171 pc_registered_about · 2026-10-21 대표 「DB화」).

관리자가 고친 소개는 origin='admin' 으로 남고, 고치기 전 내용은 history 에 쌓인다(되돌릴 근거).
고객 상세(/api/customer/pc-registered/{code})는 이 표를 그대로 읽는다.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text

from .auth import current_operator
from .customer_pc_registered import about_inputs
from .db import engine
from .registered_about import build

router = APIRouter()
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Paragraph = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]


class About(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Short
    intro: Paragraph
    benefits: list[tuple[Short, Paragraph]] = Field(max_length=12)
    scene: Paragraph = ""


@router.get("/api/admin/registered-about/{code}")
def read_about(code: int):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT content, origin, updated_at, jsonb_array_length(history) AS edits"
                                " FROM pc_registered_about WHERE product_code = :c"), {"c": code}).mappings().first()
        if row:
            return {"ok": True, "product_code": code, "saved": True, **dict(row)}
        name, spec, fits = about_inputs(conn, code)
    content = build(name, spec, fits)
    if content is None:
        raise HTTPException(404, "소개를 만들 근거(상품명 사양·용도 평가)가 없습니다.")
    return {"ok": True, "product_code": code, "saved": False, "content": content, "origin": "auto",
            "updated_at": None, "edits": 0}


@router.put("/api/admin/registered-about/{code}")
def save_about(code: int, body: About, request: Request):
    actor = current_operator()
    if not actor or actor.get("role") not in ("operator", "owner"):
        raise HTTPException(403, "소개를 저장할 권한이 없습니다.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "같은 관리자 화면에서 저장해 주세요.")
    content = {**body.model_dump(), "benefits": [list(b) for b in body.benefits], "basis": "admin"}
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM products WHERE product_code = :c AND part_type = 'PC_COMPLETE'"),
                        {"c": code}).first() is None:
            raise HTTPException(404, "완제PC 상품이 아닙니다.")
        row = conn.execute(text(
            "INSERT INTO pc_registered_about (product_code, content, origin, updated_by)"
            " VALUES (:c, CAST(:j AS JSONB), 'admin', :op)"
            " ON CONFLICT (product_code) DO UPDATE SET"
            "   history = pc_registered_about.history || jsonb_build_array(jsonb_build_object("
            "     'content', pc_registered_about.content, 'origin', pc_registered_about.origin,"
            "     'updated_at', pc_registered_about.updated_at, 'updated_by', pc_registered_about.updated_by)),"
            "   content = EXCLUDED.content, origin = 'admin', updated_by = EXCLUDED.updated_by, updated_at = now()"
            " RETURNING content, origin, updated_at, jsonb_array_length(history) AS edits"),
            {"c": code, "j": json.dumps(content, ensure_ascii=False), "op": actor.get("operator_id")}).mappings().one()
    return {"ok": True, "product_code": code, "saved": True, **dict(row)}
