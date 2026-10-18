"""조립 부품 판매 준비 — 조립PC 부품을 하나하나 판매 상품으로 볼 때 막히는 이유 (부품 상품화 1단계).

판정 정의는 여기 한 곳이다. 고객 부품 바꾸기·운영자 조립(2~4단계)도 이 판정을 쓴다.

  ready            판매 상품 연결 · 판매중 · 판매가 있음 · 호환 검사에 필요한 사양이 다 있음
  no_product       판매 상품 행이 없다(조립 전용 부품 등) — 가짜 상품을 만들지 않는다
  not_on_sale      상품은 있으나 판매중이 아니다(품절·단종·삭제대기)
  no_price         판매가가 없다
  missing_specs    호환 규칙이 읽는 사양 칸이 비어 있다 — 이대로면 호환 검사가 「판정 못 함」이 된다
  no_rules         활성 호환 규칙이 하나도 없다 — 사양을 따질 기준이 없으니 「판매 가능」이라 하지 않는다
                   (코덱스 검수 #95). 다른 막힘이 있으면 그것이 먼저다

필요한 사양은 **지금 활성 호환 규칙(`compat_rules`)에서 뽑는다** — 규칙이 늘면 기준도 따라 는다.
재고 0 은 막힘이 아니다(공급처에서 받아 파는 부품이 있다). 화면에 수만 함께 보인다.

가격 원천은 `products.sale_price` 하나다. 여기서 값을 만들거나 고치지 않는다(읽기 전용).
"""
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import text

from .db import engine
from .pc_review_specs import specs_for_review
from .product_name import display_name
from .recommend import _rule_applies
from .taxonomy import SLOT_LABELS, slot_of

router = APIRouter()

STATES = ('ready', 'no_product', 'not_on_sale', 'no_price', 'missing_specs', 'no_rules')
STATE_LABELS = {
    'ready': '판매 가능',
    'no_product': '판매 상품 없음',
    'not_on_sale': '판매중 아님',
    'no_price': '판매가 없음',
    'missing_specs': '호환 사양 부족',
    'no_rules': '호환 규칙 없음',
}
FIELD_LABELS = {
    'socket': '소켓', 'socket_list': '지원 소켓 목록', 'mem_type': '메모리 규격', 'form_factor': '폼팩터',
    'form_factor_list': '지원 폼팩터', 'tdp_watt': 'TDP', 'rated_watt': '정격 출력', 'required_power_watt': '권장 파워',
    'gpu_power_draw_watt': '그래픽카드 소비 전력', 'length_mm': '길이', 'gpu_max_mm': '그래픽카드 장착 길이',
    'cooler_height_mm': '쿨러 높이', 'cooler_tdp': '쿨러 TDP', 'cpu_gpu': '내장 그래픽',
    'radiator_rows': '라디에이터 크기', 'radiator_max_rows': '라디에이터 장착 크기',
}

RULES_SQL = """SELECT rule_key, slot, field, ref_slot, ref_field, part_types, null_ref_mode
               FROM compat_rules WHERE active ORDER BY sort_order, rule_id"""
ROWS_SQL = """SELECT v.*, e.content, e.source_snapshot, e.source_fingerprint
              FROM v_assembly_parts v JOIN product_explanations e USING (source_product_code)
              ORDER BY v.slot, v.source_product_code"""


def required_fields(rules, slot, part_type, conditional=False):
    """이 부품이 호환 검사를 받으려면 채워져 있어야 하는 사양 칸.

    왼쪽(slot)에 서면 `field` 가, 비교 대상(ref_slot)에 서면 `ref_field` 가 필요하다.
    `null_ref_mode='skip'` 규칙의 비교 대상 값은 없으면 「판정 못 함」으로 넘어가므로 필수로 세지 않는다.

    비교 대상 쪽이라도 규칙이 특정 종류만 겨냥하면(`part_types` — 예: 공랭 쿨러 높이 ↔ 케이스)
    그 종류와 짝지을 때만 필요하다. 그런 칸은 `conditional=True` 로 따로 받는다 — 막힘으로 세지 않는다.
    """
    fields = []
    for r in rules:
        if (not conditional and r['slot'] == slot and r.get('null_ref_mode') != 'skip_any'
                and _rule_applies(r, {'part_type': part_type})):
            fields.append(r['field'])
        if r['ref_slot'] == slot and r.get('null_ref_mode') not in ('skip', 'skip_any') and bool(r.get('part_types')) == conditional:
            fields.append(r['ref_field'])
    return list(dict.fromkeys(f for f in fields if f))


def judge(row, spec, rules):
    """한 부품의 판매 준비 상태와 이유. 이유는 막힌 것부터 순서대로 전부 적는다."""
    reasons = []
    if row.get('product_code') is None:
        reasons.append('no_product')
    else:
        if row.get('sale_status') != '판매중':
            reasons.append('not_on_sale')
        if not row.get('sale_price') or row['sale_price'] <= 0:
            reasons.append('no_price')
    slot = row.get('slot') or slot_of(row.get('part_type') or '')
    part_type = (spec or {}).get('part_type') or row.get('part_type') or slot
    empty = lambda f: (spec or {}).get(f) in (None, '', [])
    missing = [f for f in required_fields(rules, slot, part_type) if empty(f)]
    if missing:
        reasons.append('missing_specs')
    if not rules:
        reasons.append('no_rules')
    later = [f for f in required_fields(rules, slot, part_type, conditional=True) if empty(f)]
    return dict(state=reasons[0] if reasons else 'ready', reasons=reasons, missing_fields=missing,
                conditional_missing=later)


def load(conn):
    """조립 부품 전부와 판정. 행 수는 부품 설명 수(수백)라 한 번에 읽는다."""
    rules = [dict(r) for r in conn.execute(text(RULES_SQL)).mappings()]
    rows = {r['source_product_code']: dict(r) for r in conn.execute(text(ROWS_SQL)).mappings()}
    codes = [r['product_code'] for r in rows.values() if r['product_code'] is not None]
    by_product = {r['product_code']: dict(r) for r in conn.execute(
        text('SELECT * FROM product_specs WHERE product_code = ANY(:codes)'), dict(codes=codes)).mappings()} if codes else {}
    specs = specs_for_review(rows, by_product)
    items = []
    for code, row in rows.items():
        verdict = judge(row, specs.get(code), rules)
        items.append(dict(
            code=code, product_code=row['product_code'], slot=row['slot'],
            slot_label=SLOT_LABELS.get(row['slot'], row['slot']), name=row['part_name'],
            availability_scope=row['availability_scope'], sale_status=row['sale_status'],
            sale_price=row['sale_price'], stock_qty=row['stock_qty'],
            configuration_count=row['configuration_count'],
            active_configuration_count=row['active_configuration_count'],
            state=verdict['state'], state_label=STATE_LABELS[verdict['state']],
            reasons=[STATE_LABELS[r] for r in verdict['reasons']],
            missing_fields=[FIELD_LABELS.get(f, f) for f in verdict['missing_fields']],
            conditional_missing=[FIELD_LABELS.get(f, f) for f in verdict['conditional_missing']]))
    return items, len(rules)


def summarize(items):
    used = [i for i in items if i['active_configuration_count'] > 0]
    return dict(total=len(items), used=len(used),
                by_state={s: sum(1 for i in items if i['state'] == s) for s in STATES},
                used_by_state={s: sum(1 for i in used if i['state'] == s) for s in STATES})


@router.get('/api/admin/part-catalog')
def catalog(state: Literal['', 'ready', 'no_product', 'not_on_sale', 'no_price', 'missing_specs', 'no_rules'] = '',
            slot: str = Query('', max_length=20), used: bool = True,
            offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    with engine.connect() as c:
        items, rule_count = load(c)
    summary = summarize(items)
    rows = [i for i in items if (not used or i['active_configuration_count'] > 0)
            and (not state or i['state'] == state) and (not slot or i['slot'] == slot)]
    # 막힌 것을 먼저, 많이 쓰이는 부품을 먼저 본다.
    rows.sort(key=lambda i: (i['state'] == 'ready', -i['active_configuration_count'], i['code']))
    return dict(summary=summary, rule_count=rule_count, total=len(rows), offset=offset, limit=limit,
                items=rows[offset:offset + limit], state_labels=STATE_LABELS,
                note='판매가는 상품 관리의 판매가 그대로이며, 이 화면에서는 값을 바꾸지 않습니다.')


# 판매중 완제품 PC 인데 구성표(BOM)가 붙지 않은 것 — 사진·부품 설명·부품 바꾸기가 모두 구성표에서 오므로
# 이 PC 들은 고객 카드에서 그 셋이 비어 있다. 구성표 연결은 offer_id 'P{상품번호}' 다(pc_configuration_copy).
NO_BOM_SQL = """SELECT p.product_code, p.product_name, p.sale_price, p.stock_qty
  FROM products p
 WHERE p.part_type = 'PC_COMPLETE' AND p.status = '판매중'
   AND NOT EXISTS (SELECT 1 FROM pc_configuration_offers o WHERE o.offer_id = 'P' || p.product_code::text)
 ORDER BY p.sale_price NULLS LAST, p.product_code"""


@router.get('/api/admin/part-catalog/pcs-without-bom')
def pcs_without_bom(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(NO_BOM_SQL)).mappings()]
    items = [dict(product_code=r['product_code'], name=display_name(r['product_name']),
                  sale_price=r['sale_price'], stock_qty=r['stock_qty']) for r in rows[offset:offset + limit]]
    return dict(total=len(rows), offset=offset, limit=limit, items=items,
                note='구성표가 없으면 고객 카드에 사진·부품 설명이 없고 부품 바꾸기를 할 수 없습니다.')
