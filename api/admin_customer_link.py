# -*- coding: utf-8 -*-
"""관리자 상품 → 고객(/mvp4) 상세 주소 판정 (2026-11-02 · Codex 「MVP4 고객 화면과 관리자 연결」 1번).

■ 무엇을 하나
  관리자 상품 확인 창의 「고객 화면 보기」가 쓸 주소를 서버가 정한다. 관리자 화면이 상품 번호를
  주소에 붙여 만들지 않는다 — 고객 상세가 없는 상품(부품 · 목록에 없는 PC · 노출이 꺼진 장비)에
  가짜 링크가 생기기 때문이다.

■ 판정은 고객 화면과 «같은 함수»로 한다 — 조건을 다시 베껴 적지 않는다
  - AI 슈퍼컴퓨터: `customer_supercomputer.load(conn, (code,))` — 고객 상세 API 가 쓰는 그 함수다.
    돌려주면 고객 상세가 열린다(판매 중지·가격 확인 상태도 상세는 열린다).
  - 조립 PC: `customer_pc_catalog.listed_item()` — 고객 PC 목록(`catalog()`)과 같은 판정(추천 풀 ∩ listed)을
    상품 하나에만 적용한다. 고객 상세 화면은
    이 목록에 있어야 상품을 그리고(`mockups/mvp4/assets/js/design-boot.js` stateAfterLoad), 가격이
    없으면 「가격 확인」 안내를 그린다. 2026-11-02 사용자 확정에 따라 관리자 숨김도 적용한다.
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
REASON_PC_HIDDEN = "노출이 꺼져 있어 고객 PC 목록과 상세에 표시되지 않습니다."
REASON_SC_HIDDEN = "노출이 꺼져 있어 고객 AI 슈퍼컴퓨터 목록에 없습니다."
NOTE_PRICE_CHECK = "고객 화면에는 「가격 확인」 안내로 보입니다."
NOTE_STOPPED = "고객 화면에는 「판매 중지」로 보입니다."


def safe_url(url):
    """같은 환경의 /mvp4 상세 두 모양만 통과. 그 밖(외부 주소·스킴·다른 경로)은 None."""
    return url if isinstance(url, str) and _SAFE.match(url) else None


def judge(code: int, *, part_type, status, supercomputer_item, in_supercomputer_category,
          fit_row, pc_item, product_visible=True) -> dict:
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
    if product_visible is not True and (part_type == "PC_COMPLETE" or fit_row is not None):
        return {"kind": "pc", "url": None, "state": "hidden", "reason": REASON_PC_HIDDEN}
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


def in_supercomputer_category(conn, code) -> bool:
    """AI 슈퍼컴퓨터 카테고리(하위 포함)에 분류된 상품인가 — 노출 여부와 무관."""
    return bool(conn.execute(text(_CATEGORY_SQL), {"key": customer_supercomputer.KEY, "code": code}).scalar())


GATE_NOT_PART_NOTE = ("부품 견적 추천 기준(부품 분류·사양·검수)은 부품에만 적용됩니다. "
                      "이 상품의 고객 노출은 「고객 화면 보기」에서 확인합니다.")


def part_gate_applies(conn, code, part_type) -> bool:
    """상품 상세의 「추천 후보」 점검(부품 견적 엔진 v_recommendation_candidates 기준)이 이 상품에 맞는가.

    완제품 PC(part_type PC_COMPLETE)와 AI 슈퍼컴퓨터 카테고리 상품은 부품 견적 엔진의 후보가 될 수 없다 —
    고객에게는 PC 목록·슈퍼컴퓨터 상세로 나간다. 그 상품에 부품 기준을 대면 늘 「추천 제외 · 부품 분류 아님」이
    되어 목록의 판매 상태와 반대말을 한다(2026-11-02 Codex 검수: 113835 · 129774).
    그 밖(ETC 로 잘못 들어간 부품 포함)은 지금처럼 부품 기준을 적용한다 — 분류 오류를 고칠 단서다.
    """
    return not (part_type == "PC_COMPLETE" or in_supercomputer_category(conn, code))


@router.get("/products/{product_code}/customer-link")
def customer_link(product_code: int):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT part_type, status, is_visible FROM products WHERE product_code = :c"),
                           {"c": product_code}).mappings().first()
        if row is None:
            raise HTTPException(404, "없는 상품입니다.")
        sc_item = customer_supercomputer.load(conn, (product_code,)).get(product_code)
        inside = bool(sc_item) or in_supercomputer_category(conn, product_code)
        fit = conn.execute(text("SELECT excluded FROM product_fit_products WHERE product_code = :c"),
                           {"c": product_code}).mappings().first()
    pc_item = None
    if fit is not None and sc_item is None and row["is_visible"] is True:
        # 고객 PC 목록과 같은 판정(추천 풀 ∩ listed)을 상품 하나에만 적용한다 — 전체 목록을 다시 만들지 않는다.
        # 캐시를 두지 않는다: 가격·판매 상태·공개는 매번 현재 값이어야 한다.
        pc_item = customer_pc_catalog.listed_item(product_code)
    out = judge(product_code, part_type=row["part_type"], status=row["status"], supercomputer_item=sc_item,
                in_supercomputer_category=inside, fit_row=dict(fit) if fit is not None else None, pc_item=pc_item,
                product_visible=row["is_visible"])
    return {"ok": True, "product_code": product_code, **out}
