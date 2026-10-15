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
■ 데스크톱 메모리  RAM 줄은 노트북용(SO-DIMM)·서버용(REG) 메모리로 바꾸지 않는다. 호환 규칙(`mem`)은
         DDR 세대만 비교해 노트북 DDR5 도 통과시켰다(2026-10-11 코덱스 검수 재현: 영상 PC 에 Crucial 노트북
         DDR5 16GB). 판정은 `catalog_map` 의 분류 토큰(적재와 같은 기준)에 더해 상품명이 노트북·SO-DIMM 을
         스스로 밝힌 것도 뺀다 — 후보에서 하나 덜 보이는 쪽이 꽂히지 않는 램을 파는 쪽보다 싸다.
■ 후보와 직접 계산은 같은 수용 기준(`refusal`)을 쓴다 — 목록을 거치지 않은 요청도 같은 이유로 거절한다.
■ 읽기만 한다. 보관(`mvp3_saved_quotes`)과 쇼핑몰 연결(`mvp3_handoff`)은 같은 계산을 다시 부른다.
"""
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from . import customer_pc_offer, grid_public, mvp3_quantity as QTY
from .catalog_map import is_accessory, is_server_ram, is_sodimm, wrong_slot
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
CANDIDATE_SQL = """SELECT p.product_code, p.product_name, p.sale_price, p.part_type, p.spec_source_text
                     FROM products p JOIN product_specs s ON s.product_code = p.product_code
                    WHERE p.status = '판매중' AND p.sale_price > 0 AND p.data_origin = 'real'
                      AND NOT p.review_required_yn
                      AND p.part_type = ANY(:types)"""
PARTS_SQL = """SELECT product_code, product_name, sale_price, status, part_type, spec_source_text
                 FROM products WHERE product_code = ANY(:codes)"""


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ordinal: StrictInt = Field(ge=0)
    product_code: StrictInt = Field(gt=0)
    # 메모리·저장장치 줄의 수량(api/mvp3_quantity). 없으면 구성표 수량 그대로다.
    quantity: StrictInt | None = Field(default=None, ge=1, le=QTY.MAX_LINE_QTY)


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


NOT_DESKTOP_NAME = re.compile(r'노트북|SO[\s\-]?DIMM|랩탑|laptop|notebook', re.I)


def not_desktop_ram(row):
    """데스크톱 보드 메모리 슬롯에 꽂히지 않는 RAM 인가(노트북용 · 서버용)."""
    if (row.get('part_type') or '') != 'RAM':
        return False
    raw = row.get('spec_source_text') or ''
    return is_sodimm(raw) or is_server_ram(raw) or bool(NOT_DESKTOP_NAME.search(row.get('product_name') or ''))


# 저장장치 자리에 메모리·도킹스테이션이 올라와 있었다(2026-10-15 코덱스 오픈테스트 C02-F01 -- 「TREAVE DDR4 3200
# CL22 (8GB)」 · 「NVMe 듀얼 도킹스테이션 (SSD미포함)」이 「호환 규칙을 통과한 부품」으로 떴다). 분류는 적재 소관이지만,
# 고객 앞 후보에서는 원문·상품명이 스스로 저장장치가 아니라고 말하는 것을 뺀다.
NOT_DRIVE_NAME = re.compile(r'SSD\s*미포함|도킹|인클로저|외장\s*(케이스|하드\s*케이스)', re.I)


def not_storage(row):
    """저장장치(SSD·HDD) 자리에 왔지만 실제로는 메모리·액세서리인가."""
    if (row.get('part_type') or '') not in ('SSD', 'HDD'):
        return False
    raw, name = row.get('spec_source_text') or '', row.get('product_name') or ''
    return bool(wrong_slot(row['part_type'], raw + ' ' + name) or is_accessory(raw)
                or NOT_DRIVE_NAME.search(raw + ' ' + name))


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
        if not_desktop_ram(new):
            raise HTTPException(409, '노트북용·서버용 메모리는 이 PC에 꽂을 수 없어요. 다른 메모리를 골라 주세요.')
        if not_storage(new):
            raise HTTPException(409, '저장장치가 아닌 상품이에요. 다른 저장장치를 골라 주세요.')
        qty = old['quantity'] if ch.quantity is None else ch.quantity
        if qty != old['quantity'] and old['slot'] not in QTY.QTY_SLOTS:
            raise HTTPException(422, '메모리와 저장장치만 수량을 바꿀 수 있어요.')
        if ch.product_code == old['product_code'] and qty == old['quantity']:
            continue
        out.append(dict(ordinal=ch.ordinal, slot=old['slot'], label=SLOT_LABELS.get(old['slot'], old['slot']),
                        quantity=qty, base_quantity=old['quantity'], before=_part(old), after=_part(new),
                        delta=new['sale_price'] * qty - old['sale_price'] * old['quantity']))
        lines[ch.ordinal].update(product_code=new['product_code'], sale_price=new['sale_price'], name=new['product_name'],
                                 quantity=qty)
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
    if check['state'] == 'unknown' and rule is not None and 'missing_slots' in check:
        # 비교 쪽 줄이 아예 없을 때도 skip 규칙은 엔진처럼 넘긴다(예: 그래픽카드 없는 PC 의 파워 규칙).
        # 대상 쪽 줄이 없으면(예: 보드 없는 구성의 소켓 규칙) 판정하지 못한 것이다.
        return rule.get('null_ref_mode') == 'skip' and check['missing_slots'] == [rule['ref_slot']]
    return (check['state'] == 'unknown' and rule is not None and rule.get('null_ref_mode') == 'skip'
            and check.get('missing_fields') == [rule['ref_field']])


# 구성표에 이 슬롯 줄이 없거나 가상 줄(「기본 쿨러」 등)뿐이면, 그 슬롯이 걸린 규칙의 미판정은 거절하지 않고
# 경고만 한다(2026-10-11 쿨러 줄이 가상 줄인 초안 PC). 보드 같은 다른 슬롯이 없으면 여전히 거절한다.
WARN_MISSING_SLOTS = {'COOLER'}
BUILD_NOTE = '호환 규칙을 모두 통과한 판매 중 부품만 보여 드려요. 금액은 PC 판매가에 부품 가격 차이를 더한 값이에요.'
# 쿨러 미확인 경고가 있을 때는 「모두 통과」라고 말하지 않는다 — 안내와 경고가 한 문장이 되게 한다
# (2026-10-11 코덱스 검수 #129 문구 지적).
BUILD_NOTE_WARNED = ('쿨러를 뺀 호환 규칙을 통과한 판매 중 부품을 보여 드려요. 이 PC 구성표에는 CPU 쿨러가 따로 적혀 있지 않아 '
                     '쿨러 호환은 따로 확인해 주세요. 금액은 PC 판매가에 부품 가격 차이를 더한 값이에요.')
WARNING_TEXT = {'COOLER': '쿨러 호환은 확인되지 않았습니다(이 PC 구성표에 따로 적힌 CPU 쿨러가 없습니다).'}


def warn_only(check, rules_by_key):
    """줄이 없어 판정 못 한 규칙인데, 빠진 줄이 경고만 하는 슬롯(쿨러)뿐인가."""
    missing = check.get('missing_slots')
    return (check['state'] == 'unknown' and check['key'] in rules_by_key and bool(missing)
            and set(missing) <= WARN_MISSING_SLOTS)


def _mine(checks, ordinals, slots, by_key, display):
    # 줄이 없어 줄 번호 없이 남은 규칙 판정도 바꾼 슬롯에 걸린 규칙이면 내 것이다 — 화면 출력 통과가
    # 그 미판정을 가리지 않게 한다(2026-10-11 코덱스 검수 #121: CPU+GPU, 보드 없음).
    return [c for c in checks if (display and c['key'] == DISPLAY_KEY) or touches(c, ordinals)
            or (':' not in c['key'] and c['key'] in by_key
                and slots & {by_key[c['key']]['slot'], by_key[c['key']]['ref_slot']})]


def warnings(checks, ordinals, slots, rules, display):
    """받아들이되 고객에게 알릴 것 — 빠진 쿨러 줄 때문에 확인하지 못한 호환."""
    by_key = {r['rule_key']: r for r in rules}
    out = []
    for c in _mine(checks, ordinals, slots, by_key, display):
        if warn_only(c, by_key):
            for slot in c['missing_slots']:
                if WARNING_TEXT[slot] not in out:
                    out.append(WARNING_TEXT[slot])
    return out


def rule_slots(rules):
    return {x for r in rules for x in (r['slot'], r['ref_slot'])}


def refusal(checks, ordinals, slots, rules, display):
    """바꾼 줄(ordinals, 그 줄의 슬롯 slots)에 대한 판정 묶음을 받아들일 수 없는 이유. 받아들이면 None.

    후보 목록(options_for)과 직접 계산(quote)이 같은 기준을 쓴다.
      fail      바꾼 줄이 걸린 규칙에 걸렸다
      unknown   바꾼 줄이 걸린 규칙을 판정하지 못했다(엔진도 넘기는 skip 규칙의 상대 값 없음만 예외)
      빈 판정    그 슬롯에 걸린 규칙이 있는데 바꾼 줄을 본 판정이 하나도 없다 — 통과로 세지 않는다
    쿨러 줄이 없어(또는 가상 줄뿐이라) 판정 못 한 규칙은 거절하지 않는다 — `warnings` 가 알린다.
    """
    by_key = {r['rule_key']: r for r in rules}
    mine = _mine(checks, ordinals, slots, by_key, display)
    failed = [c for c in mine if c['state'] == 'fail']
    if failed:
        return 'fail', failed
    unsettled = [c for c in mine if not settled(c, by_key) and not warn_only(c, by_key)]
    if unsettled:
        return 'unknown', unsettled
    if not rules or (not mine and slots & rule_slots(rules)):
        return 'unknown', []
    return None


def changed_lines(conn, bom, changes):
    codes = sorted({c.product_code for c in changes})
    parts = {r['product_code']: dict(r) for r in conn.execute(text(PARTS_SQL), dict(codes=codes)).mappings()} if codes else {}
    return apply_changes(bom, changes, parts)


def quantity_usage(conn, lines):
    """메인보드·메모리·저장장치 줄이 쓰는 자리(api/mvp3_quantity.usage)."""
    codes = sorted({l['product_code'] for l in lines if l['slot'] in ('MB', 'RAM', 'SSD', 'HDD') and l['product_code']})
    rows = list(conn.execute(text(PARTS_SQL), dict(codes=codes)).mappings()) if codes else []
    raws = {r['product_code']: r['spec_source_text'] for r in rows}
    # 묶음(8Gx2)은 상품명이 말한다 -- 줄 이름이 비어 있거나 다르게 줄었어도 상품 원래 이름으로 본다.
    names = {r['product_code']: r['product_name'] for r in rows}
    return QTY.usage(lines, load_specs(conn, codes), raws, names)


def quote(conn, base_price, bom, changes, rules=None):
    """바꾼 구성의 금액과 호환 판정. 바꾼 줄이 만든 호환 실패 · 판정 못 한 호환이 있으면 409."""
    lines, applied = changed_lines(conn, bom, changes)
    raised = {x['ordinal']: x['quantity'] for x in applied if x['quantity'] > x['base_quantity']}
    usage = quantity_usage(conn, lines) if raised or any(x['slot'] == 'RAM' for x in applied) else None
    if raised:
        # 늘린 수량은 바꾼 뒤 구성의 메인보드 기준으로 본다(메인보드를 함께 바꿨으면 새 보드다).
        why = QTY.refusal(usage, raised)
        if why:
            raise HTTPException(409, why)
    # 메모리 줄을 바꾸면(부품·수량) 바꾼 뒤 구성의 시스템 메모리 합계를 그 줄에 싣는다 -- 상품 소개 글의
    # 「시스템 메모리는 16GB」는 기본 구성 기준이라, 16GB × 2 로 바꾼 뒤에도 16GB 로 남았다(2026-10-15 코덱스 C04-F04).
    # 줄 수량 × 상품 용량의 합이다. 한 줄이라도 용량을 모르면 None(지어내지 않는다).
    if usage is not None:
        total_gb = QTY.ram_total_gb(usage)
        for x in applied:
            if x['slot'] == 'RAM':
                x['system_ram_gb'] = total_gb
    rules = load_rules(conn) if rules is None else rules
    lines_c = compat_lines(lines)
    compat = evaluate(lines_c, load_specs(conn, [l['spec_key'] for l in lines_c]), rules)
    # 바꾸지 않은 줄끼리의 판정은 공개된 구성 그대로다 — 바꾼 줄이 만든 문제만 막는다.
    # 후보 목록과 같은 기준(refusal)이다: 실패뿐 아니라 판정하지 못한 것도 받지 않는다.
    warned = []
    for x in applied:
        if x['after']['product_code'] == x['before']['product_code']:
            continue      # 수량만 바꾼 줄 -- 부품은 공개된 구성 그대로다(개수는 위 메인보드 기준이 본다)
        args = (compat['checks'], [x['ordinal']], {x['slot']}, rules, x['slot'] in ('CPU', 'GPU'))
        why = refusal(*args)
        if why and why[0] == 'fail':
            raise HTTPException(409, '이 조합은 호환되지 않아요: ' + ' · '.join(f['label'] for f in why[1]))
        if why:
            names = ' · '.join(dict.fromkeys(c['label'] for c in why[1])) or '호환 규칙'
            raise HTTPException(409, f"{x['label']} 부품의 호환을 확인하지 못해 바꿀 수 없어요: {names}")
        warned += [w for w in warnings(*args) if w not in warned]
    total = base_price + sum(x['delta'] for x in applied)
    return dict(base_price=base_price, total=total, changes=applied, warnings=warned,
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
    ok, untested, warned = [], 0, []
    for r in rows:
        if not_desktop_ram(r) or not_storage(r):
            continue
        trial = [dict(l, spec_key=r['product_code'], label=str(r['product_code'])) if l['key'] == ordinal else l for l in base_lines]
        display = line['slot'] in ('CPU', 'GPU')
        out = evaluate(trial, specs, rules, display=display)
        why = refusal(out['checks'], [ordinal], {line['slot']}, rules, display)
        if why and why[0] == 'fail':
            continue
        if why:
            untested += 1
            continue
        warned += [w for w in warnings(out['checks'], [ordinal], {line['slot']}, rules, display) if w not in warned]
        ok.append(dict(product_code=r['product_code'], name=display_name(r['product_name']), price=r['sale_price'],
                       price_diff=(r['sale_price'] - line['sale_price']) * line['quantity']))
    seen, uniq = set(), []
    for o in sorted(ok, key=lambda o: (o['price'], o['product_code'])):
        if o['name'] not in seen:
            seen.add(o['name'])
            uniq.append(o)
    cheaper = [o for o in uniq if o['price_diff'] < 0][-CHEAPER:]
    pricier = [o for o in uniq if o['price_diff'] >= 0][:PRICIER]
    qty = (QTY.limit_for(quantity_usage(conn, lines), ordinal, line['quantity'])
           if line['slot'] in QTY.QTY_SLOTS else None)
    return dict(ordinal=ordinal, slot=line['slot'], label=SLOT_LABELS.get(line['slot'], line['slot']),
                current=_part(line), quantity=line['quantity'], quantity_limit=qty, options=cheaper + pricier,
                checked=len(rows), untested=untested, warnings=warned)


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
            'note': BUILD_NOTE_WARNED if res['warnings'] else BUILD_NOTE}


@router.post('/build/quote')
def build_quote_api(body: BuildBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    item = _base(body)
    with engine.connect() as c:
        q = quote(c, item['price'], load_bom(c, body.product_code), body.changes)
    return {'ok': True, 'base_code': body.product_code, **q}
