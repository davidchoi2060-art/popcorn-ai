"""MVP3 부품 직접 바꾸기 — 고른 판매 PC 의 구성표에서 부품 한 줄을 호환되는 판매 부품으로 바꾼다
(부품 상품화 3단계 · 2026-10-11 중헌 님 「부품들도 개별 제품으로 … 자유롭게 변경하되, 호환성 체크는 해야 함」).

■ #91(`api/mvp3_part_options`)과 무엇이 다른가
  #91 은 그 부품만 다른 «다른 판매 PC» 로 옮겼다. 여기는 **같은 PC 의 부품 한 줄**을 판매 중인 다른
  부품으로 바꾼다. 구성표(BOM)가 고객 공개된 PC 에서만 한다 — 공개되지 않은 구성표의 부품 목록을
  고객에게 내보이지 않기 위해서다. 구성표가 없거나 공개 전이면 화면은 #91 방식을 그대로 쓴다.

■ 호환   `api/build_check.evaluate`(관리자 검토·조립과 같은 판정). 바꾼 줄이 걸린 규칙은 전부
         «통과»여야 후보가 된다 — 사양이 없어 판정하지 못한 것(unknown)도 후보에서 뺀다.
■ 가격   기준 PC 판매가 + Σ(새 부품 판매가 − 원래 부품 판매가) × 수량.
         부품 판매가 원천은 `products.sale_price` 하나다(가격 자동 업데이트가 채우는 그 칸).
         관리자 구성표 부품 수정(`pc_configuration_parts_edit.compute_preview`)과 같은 규칙이다.
■ 읽기만 한다. 보관(`mvp3_saved_quotes`)과 쇼핑몰 연결(`mvp3_handoff`)은 같은 계산을 다시 부른다.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import customer_pc_offer, grid_public
from .build_check import DISPLAY_KEY, evaluate, load_rules, load_specs
from .db import engine
from .product_name import display_name
from .taxonomy import QUOTE_SLOTS, SLOT_LABELS, SLOTS, slot_of

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])

MAX_CHANGES = 8
CHEAPER, PRICIER = 5, 7      # 지금 부품보다 싼 쪽 · 비싼 쪽에서 가까운 것부터 보여 줄 수

BOM_SQL = """SELECT pp.ordinal, pp.slot, pp.quantity, pp.pseudo, e.product_code,
                    COALESCE(e.content->>'name', p.product_name) AS name, p.sale_price, p.status
               FROM pc_configuration_offers o
               JOIN pc_configuration_parts pp ON pp.configuration_id = o.configuration_id
               LEFT JOIN product_explanations e ON e.source_product_code = pp.explanation_code
               LEFT JOIN products p ON p.product_code = e.product_code
              WHERE o.offer_id = :offer
              ORDER BY pp.ordinal"""
CANDIDATE_SQL = """SELECT p.product_code, p.product_name, p.sale_price, p.part_type
                     FROM products p JOIN product_specs s ON s.product_code = p.product_code
                    WHERE p.status = '판매중' AND p.sale_price > 0 AND p.data_origin = 'real'
                      AND NOT p.review_required_yn
                      AND p.part_type = ANY(:types)"""
PARTS_SQL = """SELECT product_code, product_name, sale_price, status, part_type
                 FROM products WHERE product_code = ANY(:codes)"""


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ordinal: StrictInt = Field(ge=0)
    product_code: StrictInt = Field(gt=0)


class BuildBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: dict
    product_code: StrictInt = Field(gt=0)
    changes: list[Change] = Field(default_factory=list, max_length=MAX_CHANGES)


class OptionsBody(BuildBody):
    ordinal: StrictInt = Field(ge=0)


def _part(row):
    return dict(product_code=row['product_code'], name=display_name(row.get('name') or row.get('product_name')),
                price=row['sale_price'])


def base_pc(state_raw, code):
    """이 상담에 지금 판매 중으로 맞는 PC 이고, 구성표가 고객 공개된 것만. 아니면 None."""
    item = grid_public.eligible_sold_item(state_raw, code)
    if item is None or type(item.get('price')) is not int:
        return None, None
    customer_pc_offer.attach([item])
    return item, item.get('public_configuration')


def load_bom(conn, code):
    return [dict(r) for r in conn.execute(text(BOM_SQL), dict(offer=f'P{code}')).mappings()]


def swappable(line):
    """판매 상품으로 이어진 실제 부품 줄만 바꿀 수 있다(조립비 줄 · 조립 전용 부품은 아니다)."""
    return (not line['pseudo'] and line['product_code'] is not None and line['slot'] in SLOTS
            and type(line['sale_price']) is int and line['sale_price'] > 0)


def apply_changes(bom, changes, parts):
    """구성표에 바꾼 줄을 얹는다. parts = {product_code: products 행}. 잘못된 변경은 422/409."""
    lines = {l['ordinal']: dict(l) for l in bom}
    seen, out = set(), []
    for ch in changes:
        if ch.ordinal in seen:
            raise HTTPException(422, '같은 부품 줄을 두 번 바꿀 수 없어요.')
        seen.add(ch.ordinal)
        old = lines.get(ch.ordinal)
        if old is None or not swappable(old):
            raise HTTPException(422, '바꿀 수 없는 부품이에요.')
        new = parts.get(ch.product_code)
        if (new is None or new['status'] != '판매중' or type(new['sale_price']) is not int or new['sale_price'] <= 0):
            raise HTTPException(409, '고른 부품이 지금 판매 중이 아니에요. 다시 골라 주세요.')
        if slot_of(new['part_type'] or '') != old['slot']:
            raise HTTPException(422, '같은 종류의 부품으로만 바꿀 수 있어요.')
        if ch.product_code == old['product_code']:
            continue
        out.append(dict(ordinal=ch.ordinal, slot=old['slot'], label=SLOT_LABELS.get(old['slot'], old['slot']),
                        quantity=old['quantity'], before=_part(old), after=_part(new),
                        delta=(new['sale_price'] - old['sale_price']) * old['quantity']))
        lines[ch.ordinal].update(product_code=new['product_code'], sale_price=new['sale_price'], name=new['product_name'])
    return [lines[k] for k in sorted(lines)], out


def compat_lines(lines):
    return [dict(key=l['ordinal'], slot=l['slot'], spec_key=l['product_code'], label=str(l['product_code']))
            for l in lines if not l['pseudo'] and l['product_code'] is not None]


def touches(check, ordinals):
    """이 판정이 바꾼 줄을 보는가. 규칙 판정 키는 `rule_key:왼쪽줄:오른쪽줄` 이다."""
    keys = check['key'].split(':')[1:]
    return any(str(o) in keys for o in ordinals)


def settled(check, rules_by_key):
    """후보로 내밀어도 되는 판정인가 — 통과, 또는 상대 값이 없어 엔진도 넘기는 skip 규칙."""
    if check['state'] == 'pass':
        return True
    rule = rules_by_key.get(check['key'].split(':')[0])
    return (check['state'] == 'unknown' and rule is not None and rule.get('null_ref_mode') == 'skip'
            and check.get('missing_fields') == [rule['ref_field']])


def changed_lines(conn, bom, changes):
    codes = sorted({c.product_code for c in changes})
    parts = {r['product_code']: dict(r) for r in conn.execute(text(PARTS_SQL), dict(codes=codes)).mappings()} if codes else {}
    return apply_changes(bom, changes, parts)


def quote(conn, base_price, bom, changes, rules=None):
    """바꾼 구성의 금액과 호환 판정. 바꾼 줄이 만든 호환 실패가 있으면 409."""
    lines, applied = changed_lines(conn, bom, changes)
    rules = load_rules(conn) if rules is None else rules
    lines_c = compat_lines(lines)
    compat = evaluate(lines_c, load_specs(conn, [l['spec_key'] for l in lines_c]), rules)
    # 바꾸지 않은 줄끼리의 판정은 공개된 구성 그대로다 — 바꾼 줄이 만든 실패만 막는다.
    changed = [x['ordinal'] for x in applied]
    swapped_display = any(x['slot'] in ('CPU', 'GPU') for x in applied)
    new_fail = [f for f in compat['failures'] if touches(f, changed) or (swapped_display and f['key'] == DISPLAY_KEY)]
    if new_fail:
        raise HTTPException(409, '이 조합은 호환되지 않아요: ' + ' · '.join(f['label'] for f in new_fail))
    total = base_price + sum(x['delta'] for x in applied)
    return dict(base_price=base_price, total=total, changes=applied,
                compat=dict(ok=compat['ok'], rule_count=compat['rule_count'],
                            failures=[f['label'] for f in compat['failures']], unknown=len(compat['unknown'])))


def options_for(conn, lines, ordinal, rules):
    """한 줄을 바꿀 수 있는 판매 부품. 바꾼 줄이 걸린 규칙이 전부 통과여야 한다."""
    line = next((l for l in lines if l['ordinal'] == ordinal), None)
    if line is None or not swappable(line):
        raise HTTPException(422, '바꿀 수 없는 부품이에요.')
    rows = [dict(r) for r in conn.execute(text(CANDIDATE_SQL), dict(types=list(QUOTE_SLOTS[line['slot']]))).mappings()
            if r['product_code'] != line['product_code']]
    base_lines = compat_lines(lines)
    specs = load_specs(conn, [l['spec_key'] for l in base_lines] + [r['product_code'] for r in rows])
    by_key = {r['rule_key']: r for r in rules}
    ok, untested = [], 0
    for r in rows:
        trial = [dict(l, spec_key=r['product_code'], label=str(r['product_code'])) if l['key'] == ordinal else l for l in base_lines]
        out = evaluate(trial, specs, rules, display=line['slot'] in ('CPU', 'GPU'))
        mine = [c for c in out['checks'] if c['key'] == DISPLAY_KEY or touches(c, [ordinal])]
        if any(c['state'] == 'fail' for c in mine):
            continue
        if not all(settled(c, by_key) for c in mine):
            untested += 1
            continue
        ok.append(dict(product_code=r['product_code'], name=display_name(r['product_name']), price=r['sale_price'],
                       price_diff=(r['sale_price'] - line['sale_price']) * line['quantity']))
    seen, uniq = set(), []
    for o in sorted(ok, key=lambda o: (o['price'], o['product_code'])):
        if o['name'] not in seen:
            seen.add(o['name'])
            uniq.append(o)
    cheaper = [o for o in uniq if o['price_diff'] < 0][-CHEAPER:]
    pricier = [o for o in uniq if o['price_diff'] >= 0][:PRICIER]
    return dict(ordinal=ordinal, slot=line['slot'], label=SLOT_LABELS.get(line['slot'], line['slot']),
                current=_part(line), quantity=line['quantity'], options=cheaper + pricier,
                checked=len(rows), untested=untested)


def _base(body):
    item, configuration = base_pc(body.state, body.product_code)
    if item is None:
        raise HTTPException(409, '지금 판매 중인 추천 상품이 아니에요. 추천을 다시 조회해 주세요.')
    if not configuration:
        raise HTTPException(404, '이 PC는 부품 구성이 아직 공개되지 않아 부품을 하나씩 바꿀 수 없어요.')
    return item


def build_quote(state_raw, product_code, changes):
    """보관·쇼핑몰 연결이 다시 부르는 계산. (상품 공개 항목, 견적) 을 돌려준다."""
    body = BuildBody(state=state_raw, product_code=product_code, changes=changes)
    item = _base(body)
    with engine.connect() as c:
        return item, quote(c, item['price'], load_bom(c, product_code), body.changes)


@router.post('/build/options')
def build_options(body: OptionsBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    item = _base(body)
    with engine.connect() as c:
        rules = load_rules(c)
        bom = load_bom(c, body.product_code)
        q = quote(c, item['price'], bom, body.changes, rules)
        lines, _ = changed_lines(c, bom, body.changes)
        res = options_for(c, lines, body.ordinal, rules)
    for o in res['options']:
        o['total'] = q['total'] + o['price_diff']
    return {'ok': True, 'base_code': body.product_code, 'total': q['total'], **res,
            'note': '호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요. 금액은 PC 판매가에 부품 가격 차이를 더한 값이에요.'}


@router.post('/build/quote')
def build_quote_api(body: BuildBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    item = _base(body)
    with engine.connect() as c:
        q = quote(c, item['price'], load_bom(c, body.product_code), body.changes)
    return {'ok': True, 'base_code': body.product_code, **q}
