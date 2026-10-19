# -*- coding: utf-8 -*-
"""고객용 AI 슈퍼컴퓨터(고정 완제품 SKU) — /mvp4 v15 메인 진열·상세·문의의 원천 (2026-10-19 대표 승인 v15).

■ 무엇인가
  Dell Pro Max GB10 두 모델은 몰에 따로 등록된 완제품 상품이다(129615 = M.2 2TB · 129614 = M.2 4TB).
  조립PC 구성(P 오퍼)이 아니라서 /api/customer/pc-catalog 에 나오지 않는다. 그래서 두 상품번호만 여기서 낸다.
  부품 변경·교체 부품 선택은 없다 — 모델(두 상품번호 중 하나)과 수량만 고른다. 다른 조립PC 정책은 그대로다.

■ 원천
  products 의 지금 값(상품명·판매가·상태·노출). 가격은 그때그때 이 응답이 정한다 — 화면은 값을 다시 적지 않는다.
  상품명이 GB10 이 아니게 바뀌었거나, 판매중이 아니거나, 판매가가 없으면 가격을 내지 않고 «판매 확인 필요»로 낸다.

■ 내지 않는 것 (allowlist 만 낸다)
  매입가·공급처·재고 수량·몰 상품고시. 몰 상품고시(특히 2TB)의 항목/값에 오류가 있어 옮기지 않는다 — 화면 사양표는
  두 모델이 같은 고정 사양(GB10 · 128GB 통합 메모리 · DGX OS)과 저장장치 용량만 쓰며, 용량은 상품명에서 읽는다.
  재고·배송일·보증·성능은 약속하지 않는다(문의에서 확인).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from .db import engine

router = APIRouter()

# 화면 순서 = 이 순서(2TB 먼저). 두 번호 밖의 상품은 이 경로로 내지 않는다.
CODES = (129615, 129614)
_GB10 = re.compile(r'GB10', re.I)
_STORAGE = re.compile(r'M\.2\s*(\d+\s*TB)', re.I)
SALE = '판매중'


def _item(r) -> dict:
    name = r['product_name'] or ''
    m = _STORAGE.search(name)
    storage = m.group(1).replace(' ', '').upper() if m else None
    ok_name = bool(_GB10.search(name))
    price = r['sale_price'] if isinstance(r['sale_price'], int) and r['sale_price'] > 0 else None
    on_sale = r['status'] == SALE and bool(r['is_visible']) and ok_name and price is not None and storage is not None
    return {
        'product_code': r['product_code'],
        'name': 'Dell Pro Max GB10',
        'official_name': name,
        'storage': storage,
        'memory': '128GB',
        # 판매 확인이 필요한 상품은 가격을 내지 않는다(화면은 «가격 확인 필요»·«판매 여부 확인 중»).
        'price': price if on_sale else None,
        'sale_state': 'on_sale' if on_sale else 'check',
    }


def load(conn, codes=CODES) -> dict[int, dict]:
    rows = conn.execute(text(
        "SELECT product_code, product_name, sale_price, status, is_visible"
        " FROM products WHERE product_code = ANY(:c)"), {'c': list(codes)}).mappings()
    return {r['product_code']: _item(r) for r in rows}


@router.get('/api/customer/supercomputers')
def supercomputers(response: Response):
    with engine.connect() as conn:
        found = load(conn)
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'items': [found[c] for c in CODES if c in found]}


@router.get('/api/customer/supercomputers/{code}')
def supercomputer(code: int, response: Response):
    if code not in CODES:
        raise HTTPException(404, '이 상품은 AI 슈퍼컴퓨터 목록에 없습니다.')
    with engine.connect() as conn:
        item = load(conn, (code,)).get(code)
    if item is None:
        raise HTTPException(404, '상품 정보를 찾을 수 없습니다.')
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'item': item}
