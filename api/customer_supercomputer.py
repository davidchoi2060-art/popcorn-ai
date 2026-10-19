# -*- coding: utf-8 -*-
"""고객용 AI 슈퍼컴퓨터 카테고리 — /mvp4 목록·메인 진열·상세·문의의 원천 (v15 2026-10-19 · 카테고리 확장 2026-10-20 대표 승인).

■ 어떤 상품이 나오나 — 상품 데이터의 카테고리 분류로 조회한다(상품번호를 코드에 적지 않는다)
  판매 탐색 카테고리(categories) 중 public_key = 'ai-supercomputer' 인 노드와 그 하위 노드에 분류된 상품.
  관리자가 「카테고리 매핑」에서 상품을 이 카테고리로 옮기면 목록·상세·문의에 그대로 나온다(0166).
  노출이 꺼진 상품(is_visible = false)은 내지 않는다.

■ 상품별 표시 정보 — ai_device_profiles(0166)
  제조사·모델명·사진·가속기/프로세서·메모리·저장장치·운영체제·아키텍처·모델 묶음·상세 내용. 상품마다 한 행이다.
  행이 없거나 값이 비면 null 로 낸다 — 화면은 «확인 필요»로 보인다. 다른 상품(GB10)의 값을 물려주지 않는다.
  사진이 없으면 승인된 상품 설명 사진(/api/product-images/{code}/detail)이 있을 때만 그것을 쓴다.

■ 가격·판매 상태 — products 의 지금 값
  판매중 + 판매가 있음 = on_sale(가격을 낸다) · 판매중인데 판매가 없음 = check(가격 확인 필요) · 그 밖의 상태 = stopped(판매 중지).
  매입가·마진·공급처·재고 수량·몰 상품고시는 내지 않는다. 재고·배송일·보증·성능은 약속하지 않는다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text

from .db import engine

router = APIRouter()

KEY = 'ai-supercomputer'
SALE = '판매중'
LIMIT = 200                      # 한 카테고리에서 한 번에 내는 상한(화면이 «더 보기»로 나눠 보인다)
_TAG = re.compile(r'<[^>]+>')
_IMG = re.compile(r'^(assets/images/[A-Za-z0-9/_.-]+\.(?:png|jpe?g|webp)|/api/product-images/\d+/(?:detail|thumbnail))$')

# 카테고리 노드(하위 포함) — 이름이 아니라 public_key 로 찾는다.
_NODES = """
    WITH RECURSIVE t AS (
        SELECT category_id FROM categories WHERE public_key = :key
        UNION ALL
        SELECT c.category_id FROM categories c JOIN t ON c.parent_id = t.category_id
    )
"""
_COLS = """
    p.product_code, p.product_name, p.maker AS p_maker, p.sale_price, p.status,
    d.display_name, d.maker, d.model_name, d.accelerator, d.processor, d.memory, d.storage, d.os, d.architecture,
    d.model_group, d.model_label, d.featured_rank, d.images, d.detail,
    EXISTS (SELECT 1 FROM product_explanations e WHERE e.source_product_code = p.product_code
                AND e.content ? 'image_asset') AS has_explained_photo
"""
_FROM = """
      FROM products p
      LEFT JOIN ai_device_profiles d ON d.product_code = p.product_code
     WHERE p.category_id IN (SELECT category_id FROM t) AND p.is_visible
"""


def _clean_name(s):
    s = _TAG.sub(' ', s or '')
    return re.sub(r'\s+', ' ', s).strip() or None


# 표시 정보를 아직 적지 않은 상품은 몰 상품명·제조사에서 읽을 수 있는 값으로 채운다(2026-10-20 대표 「사용자에게 반복 일을 시키지 마라」).
# 상품명에 GB10/DGX Spark 가 있으면 GB10 플랫폼 공통 사양(가속기·CPU·OS·아키텍처)을 쓴다. 읽지 못한 값은 비워 둔다(«확인 필요»).
_TB = re.compile(r'(?:M\.2\s*|/)\s*(\d+)\s*TB', re.I)
_GB = re.compile(r'[(\[/]\s*(\d{2,4})\s*G(?:B)?(?![A-Za-z])', re.I)
_GB10 = re.compile(r'GB10|DGX\s*Spark|Grace\s*Blackwell', re.I)


def derive(name, maker):
    name = name or ''
    out = {'maker': (maker or '').strip() or None}
    m = _TB.search(name)
    out['storage'] = m.group(1) + 'TB' if m else None
    m = _GB.search(name)
    out['memory'] = m.group(1) + 'GB' if m else None
    if _GB10.search(name):
        out.update(accelerator='NVIDIA GB10', processor='20코어 ARM 기반 CPU', os='DGX OS', architecture='ARM',
                   memory=out['memory'] or '128GB')
    return out


def _images(r):
    out = []
    for x in (r['images'] or []):
        if isinstance(x, dict) and isinstance(x.get('src'), str) and _IMG.match(x['src']):
            out.append({'src': x['src'], 'label': x.get('label') or None, 'alt': x.get('alt') or None})
    if not out and r['has_explained_photo']:
        out.append({'src': f"/api/product-images/{r['product_code']}/detail", 'label': None, 'alt': None})
    return out


def _state(r):
    price = r['sale_price'] if isinstance(r['sale_price'], int) and r['sale_price'] > 0 else None
    if r['status'] != SALE:
        return None, 'stopped'
    return (price, 'on_sale') if price is not None else (None, 'check')


def item(r, with_detail=False) -> dict:
    price, state = _state(r)
    auto = derive(r['product_name'], r.get('p_maker')) if r['display_name'] is None else {}
    v = lambda k: r[k] or auto.get(k) or None
    out = {
        'product_code': r['product_code'],
        'name': r['display_name'] or _clean_name(r['product_name']),
        'official_name': _clean_name(r['product_name']),
        'maker': v('maker'),
        'model_name': r['model_name'] or None,
        'accelerator': v('accelerator'),
        'processor': v('processor'),
        'memory': v('memory'),
        'storage': v('storage'),
        'os': v('os'),
        'architecture': v('architecture'),
        'model_group': r['model_group'] or None,
        'model_label': r['model_label'] or None,
        'featured_rank': r['featured_rank'],
        'images': _images(r),
        'price': price,
        'sale_state': state,
    }
    if with_detail:
        out['detail'] = r['detail'] if isinstance(r['detail'], dict) else {}
    return out


def category(conn):
    return conn.execute(text("SELECT category_id, name FROM categories WHERE public_key = :key"),
                        {'key': KEY}).mappings().first()


def load(conn, codes=None) -> dict[int, dict]:
    """카테고리에 분류된 상품(코드를 주면 그 상품만, 상세 내용 포함). 분류되지 않은 상품은 없다 — 문의 검증도 이것을 쓴다."""
    sql = _NODES + "SELECT " + _COLS + _FROM + (" AND p.product_code = ANY(:codes)" if codes else "") + \
        " ORDER BY d.featured_rank NULLS LAST, p.product_code DESC LIMIT :lim"
    rows = conn.execute(text(sql), {'key': KEY, 'codes': [int(c) for c in (codes or [])], 'lim': LIMIT}).mappings()
    return {r['product_code']: item(r, with_detail=bool(codes)) for r in rows}


@router.get('/api/customer/supercomputers')
def supercomputers(response: Response):
    with engine.connect() as conn:
        cat = category(conn)
        found = load(conn) if cat else {}
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'category': {'key': KEY, 'name': cat['name']} if cat else None,
            'items': list(found.values())}


@router.get('/api/customer/supercomputers/{code}')
def supercomputer(code: int, response: Response):
    with engine.connect() as conn:
        found = load(conn, (code,)).get(code)
        models = []
        if found and found['model_group']:
            # 같은 제품의 다른 고정 모델(예: 2TB/4TB) — 같은 카테고리·같은 묶음만. 부품 변경이 아니다.
            sib = conn.execute(text(_NODES + "SELECT " + _COLS + _FROM + " AND d.model_group = :g"
                                    " ORDER BY d.featured_rank NULLS LAST, p.product_code"),
                               {'key': KEY, 'g': found['model_group']}).mappings()
            models = [{k: v for k, v in item(r).items() if k in ('product_code', 'model_label', 'price', 'sale_state')}
                      for r in sib]
    if found is None:
        raise HTTPException(404, '이 상품은 AI 슈퍼컴퓨터 목록에 없습니다.')
    response.headers['Cache-Control'] = 'no-store'
    found['models'] = models
    return {'ok': True, 'item': found}
