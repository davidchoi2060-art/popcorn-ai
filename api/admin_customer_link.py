# -*- coding: utf-8 -*-
"""관리자 상품 → 고객(/mvp4) 상세 주소 판정 (2026-11-02 · Codex 「MVP4 고객 화면과 관리자 연결」 1번).

■ 무엇을 하나
  관리자 상품 확인 창의 「고객 화면 보기」가 쓸 주소를 서버가 정한다. 관리자 화면이 상품 번호를
  주소에 붙여 만들지 않는다 — 고객 상세가 없는 상품(부품 · 목록에 없는 PC · 노출이 꺼진 장비)에
  가짜 링크가 생기기 때문이다.

■ 판정은 고객 화면과 «같은 함수»로 한다 — 조건을 다시 베껴 적지 않는다
  - AI 슈퍼컴퓨터: `customer_supercomputer.load(conn, (code,))` — 고객 상세 API 가 쓰는 그 함수다.
    돌려주면 고객 상세가 열린다(판매 중지·가격 확인 상태도 상세는 열린다).
  - 조립 PC: `customer_pc_catalog.catalog()` — 고객 PC 목록 API 가 쓰는 그 함수다. 고객 상세 화면은
    이 목록에 있어야 상품을 그리고(`mockups/mvp4/assets/js/design-boot.js` stateAfterLoad), 가격이
    없으면 「가격 확인」 안내를 그린다. 이 목록은 `products.is_visible` 을 보지 않는다 — 고객 화면의
    정책이 그렇다. 여기서 정책을 바꾸지 않는다.
  - 그 밖(부품 · 주변기기 등): 고객 단독 상세가 없다(부품은 PC 상세 안에서만 보인다). 주소 없음 + 사유.

■ 주소는 같은 환경의 상대 경로만 낸다
  개발 관리자에서 운영 고객 도메인으로, 또는 외부 몰로 보내지 않는다. `/mvp4/` 로 시작하는 두 모양만
  허용하고(`safe_url`), 그 밖이면 주소를 내지 않는다.

■ 읽기 전용. 쓰기·캐시 없음.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from . import customer_pc_catalog, customer_supercomputer
from .db import engine

router = APIRouter(prefix="/api/admin")

PC_URL = "/mvp4/?screen=product&id={code}"
SUPERCOMPUTER_URL = "/mvp4/supercomputer.html?id={code}"
_SAFE = re.compile(r"^/mvp4/(\?screen=product&id=[1-9][0-9]{0,17}|supercomputer\.html\?id=[1-9][0-9]{0,17})$")

SALE = "판매중"
REASON_PART = "부품·주변기기는 고객 단독 상세가 없습니다. 고객 화면에서는 PC 상세 안에서만 보입니다."
REASON_PC_NOT_FIT = "고객 PC 목록(용도 평가 목록)에 없는 PC라 고객 상세가 없습니다."
REASON_PC_EXCLUDED = "고객 PC 목록에서 제외된 상품이라 고객 상세가 없습니다."
REASON_SC_HIDDEN = "노출이 꺼져 있어 고객 AI 슈퍼컴퓨터 목록에 없습니다."
NOTE_PRICE_CHECK = "고객 화면에는 「가격 확인」 안내로 보입니다."
NOTE_STOPPED = "고객 화면에는 「판매 중지」로 보입니다."


def safe_url(url):
    """같은 환경의 /mvp4 상세 두 모양만 통과. 그 밖(외부 주소·스킴·다른 경로)은 None."""
    return url if isinstance(url, str) and _SAFE.match(url) else None


def judge(code: int, *, part_type, status, supercomputer_item, in_supercomputer_category,
          fit_row, pc_item) -> dict:
    """판정만 하는 순수 함수 — 입력은 고객 화면 함수가 돌려준 값 그대로다.

    반환: kind(pc|supercomputer|part|none) · url(상대 경로 또는 None) · state · reason(사유/안내 문구 또는 None)
    """
    if supercomputer_item is not None:
        state = supercomputer_item.get("sale_state")
        note = {"on_sale": None, "check": NOTE_PRICE_CHECK, "stopped": NOTE_STOPPED}.get(state)
        return {"kind": "supercomputer", "url": safe_url(SUPERCOMPUTER_URL.format(code=code)),
                "state": state, "reason": note}
    if in_supercomputer_category:
        return {"kind": "supercomputer", "url": None, "state": "hidden", "reason": REASON_SC_HIDDEN}
    if pc_item is not None:
        price = pc_item.get("price")
        priced = isinstance(price, int) and price > 0
        return {"kind": "pc", "url": safe_url(PC_URL.format(code=code)),
                "state": "on_sale" if priced else "check", "reason": None if priced else NOTE_PRICE_CHECK}
    if fit_row is not None:
        if fit_row.get("excluded"):
            reason = REASON_PC_EXCLUDED
        elif status != SALE:
            reason = f"판매 상태가 「{status or '미정'}」라 고객 PC 목록에 없습니다."
        else:
            reason = REASON_PC_NOT_FIT
        return {"kind": "pc", "url": None, "state": "not_listed", "reason": reason}
    if part_type == "PC_COMPLETE":
        return {"kind": "pc", "url": None, "state": "not_listed", "reason": REASON_PC_NOT_FIT}
    return {"kind": "part", "url": None, "state": "no_detail", "reason": REASON_PART}


_CATEGORY_SQL = customer_supercomputer._NODES + """
    SELECT EXISTS (SELECT 1 FROM products p WHERE p.product_code = :code
                     AND p.category_id IN (SELECT category_id FROM t)) AS inside
"""


@router.get("/products/{product_code}/customer-link")
def customer_link(product_code: int):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT part_type, status FROM products WHERE product_code = :c"),
                           {"c": product_code}).mappings().first()
        if row is None:
            raise HTTPException(404, "없는 상품입니다.")
        sc_item = customer_supercomputer.load(conn, (product_code,)).get(product_code)
        inside = bool(sc_item) or bool(conn.execute(text(_CATEGORY_SQL),
                                                    {"key": customer_supercomputer.KEY, "code": product_code}).scalar())
        fit = conn.execute(text("SELECT excluded FROM product_fit_products WHERE product_code = :c"),
                           {"c": product_code}).mappings().first()
    pc_item = None
    if fit is not None and sc_item is None:
        # 고객 PC 목록 함수 그대로 — 무거운 전체 목록이라 용도 평가 목록에 있는 상품일 때만 부른다.
        pc_item = next((it for it in customer_pc_catalog.catalog() if it["product_code"] == product_code), None)
    out = judge(product_code, part_type=row["part_type"], status=row["status"], supercomputer_item=sc_item,
                in_supercomputer_category=inside, fit_row=dict(fit) if fit is not None else None, pc_item=pc_item)
    return {"ok": True, "product_code": product_code, **out}
