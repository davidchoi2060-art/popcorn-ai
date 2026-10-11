"""신규 조립PC 고객 공개 — 현재 상태 판정 한 곳 (2026-10-11 부품 상품화 4단계).

관리자 「신규 조립PC 생성」(`api/admin_pc_builder.py`)이 만든 구성은 쇼핑몰 상품번호가 없다.
운영자가 「고객 공개」를 누르면 `custom_pc_release_events` 에 한 줄이 쌓이고(0142), 고객 화면은
그 구성을 **지금 값으로 다시 판정한 뒤에만** 보인다. 관리자 공개 점검과 고객 목록이 이 모듈 하나를 쓴다.

■ 지금 값으로 다시 보는 것 (공개 뒤에도 매번)
  부품마다    판매 상품 연결 · 「판매중」 · 판매가 > 0
  가격        부품 판매가 × 수량의 합 + 조립비(`api/orders.ASSEMBLY_FEE`). 가격 원천은
              `products.sale_price` 하나이고, 판매가가 바뀌면 고객 가격도 그대로 따라간다
  호환        `api/build_check.evaluate` — 실패가 하나라도 있으면 고객에게 내지 않는다
  공개 기록   마지막 기록이 release 이고, 그때의 구성 판·부품 지문이 지금과 같고,
              구성 검토 상태가 승인(approved)일 때만 공개 중이다

■ 공개할 때만 보는 것
  구성 검토 승인(`pc_configuration_review.load_review` 의 eligible) — 검토 근거에 부품 판매가가
  들어 있어 가격이 바뀌면 검토가 다시 필요해진다. 그래서 검토 승인은 «공개하는 순간»의 조건이고,
  공개 뒤 가격 변동으로 고객 화면에서 빠지지는 않는다.
"""
from sqlalchemy import text

from .build_check import evaluate, load_rules, load_specs
from .orders import ASSEMBLY_FEE
from .taxonomy import SLOT_LABELS

ADMIN_OFFER = 'ADMIN-'
PLACEHOLDER_INTRO = '운영자가 부품을 선택한 신규 구성입니다.'
PRICE_NOTE = f'부품 판매가 합계 + 조립비 {ASSEMBLY_FEE:,}원 · 오늘 판매가 기준'

PARTS_SQL = '''
SELECT cp.configuration_id, cp.ordinal, cp.slot, cp.quantity, cp.pseudo, cp.source_code, cp.explanation_code,
       e.product_code, e.status AS explanation_status, (e.content ? 'image_asset') AS has_photo,
       e.content->>'name' AS explanation_name,
       p.product_name, p.sale_price, p.status AS sale_status
  FROM pc_configuration_parts cp
  LEFT JOIN product_explanations e ON e.source_product_code = cp.explanation_code
  LEFT JOIN products p ON p.product_code = e.product_code
 WHERE cp.configuration_id = ANY(:ids)
 ORDER BY cp.configuration_id, cp.ordinal'''

CONFIGS_SQL = '''
SELECT c.configuration_id, c.revision, c.status, c.bom_fingerprint, c.content, c.updated_at
  FROM pc_configurations c
 WHERE EXISTS (SELECT 1 FROM pc_configuration_offers o
                WHERE o.configuration_id = c.configuration_id AND o.offer_id LIKE 'ADMIN-%')'''

LATEST_SQL = '''
SELECT DISTINCT ON (configuration_id) event_id, configuration_id, action, revision, bom_fingerprint,
       price_at_release, operator_id, note, created_at
  FROM custom_pc_release_events
 WHERE configuration_id = ANY(:ids)
 ORDER BY configuration_id, event_id DESC'''


def part_name(p):
    return p.get('product_name') or p.get('explanation_name') or p.get('source_code')


def evaluate_parts(parts, specs, rules):
    """구성 하나의 지금 상태. parts 는 PARTS_SQL 행(그 구성의 것만)."""
    real = [p for p in parts if not p['pseudo']]
    problems, lines, subtotal, priced = [], [], 0, bool(real)
    for p in real:
        label = f"{SLOT_LABELS.get(p['slot'], p['slot'])} · {part_name(p)}"
        if p.get('product_code') is None or p.get('sale_status') != '판매중' or not p.get('sale_price') or p['sale_price'] <= 0:
            priced = False
        if p.get('product_code') is None:
            problems.append(label + ': 판매 상품 연결 없음')
        elif p.get('sale_status') != '판매중':
            problems.append(label + f": 판매중 아님({p.get('sale_status') or '상태 없음'})")
        elif not p.get('sale_price') or p['sale_price'] <= 0:
            problems.append(label + ': 판매가 없음')
        else:
            subtotal += p['sale_price'] * p['quantity']
        lines.append(dict(key=p['ordinal'], slot=p['slot'], spec_key=p.get('product_code'), label=part_name(p)))
    if not real:
        problems.append('구성 부품 없음')
    compat = evaluate(lines, specs, rules)
    if not rules:
        problems.append('활성 호환 규칙 없음')
    for f in compat['failures']:
        problems.append(f"호환 불일치: {f['label']} · {f['detail']}")
    price = subtotal + ASSEMBLY_FEE if priced else None
    return dict(ok=not problems, problems=problems, price=price, subtotal=subtotal if price else None,
                assembly_fee=ASSEMBLY_FEE, compat=dict(ok=compat['ok'], checks=compat['checks'],
                failures=compat['failures'], unknown=compat['unknown']),
                parts=[dict(ordinal=p['ordinal'], slot=p['slot'], slot_label=SLOT_LABELS.get(p['slot'], p['slot']),
                            name=part_name(p), product_code=p.get('product_code'), quantity=p['quantity'],
                            sale_price=p.get('sale_price'), sale_status=p.get('sale_status'),
                            explanation_approved=p.get('explanation_status') == 'approved',
                            has_photo=bool(p.get('has_photo'))) for p in real])


def is_live_release(config, latest):
    """마지막 공개 기록이 지금 구성에 그대로 해당하는가(가격·호환은 따로 본다)."""
    return bool(latest and latest['action'] == 'release' and config['status'] == 'approved'
                and latest['revision'] == config['revision']
                and latest['bom_fingerprint'] == config['bom_fingerprint'])


def load(conn, ids=None):
    """신규 조립PC(ADMIN 오퍼가 있는 구성)마다 (config, latest, state). ids 가 없으면 전부."""
    sql = CONFIGS_SQL + (' AND c.configuration_id = ANY(:ids)' if ids is not None else '') + ' ORDER BY c.updated_at DESC'
    configs = [dict(r) for r in conn.execute(text(sql), dict(ids=list(ids or []))).mappings()]
    if not configs:
        return []
    keys = [c['configuration_id'] for c in configs]
    latest = {r['configuration_id']: dict(r) for r in conn.execute(text(LATEST_SQL), dict(ids=keys)).mappings()}
    parts = {}
    for r in conn.execute(text(PARTS_SQL), dict(ids=keys)).mappings():
        parts.setdefault(r['configuration_id'], []).append(dict(r))
    specs = load_specs(conn, [p['product_code'] for ps in parts.values() for p in ps if not p['pseudo']])
    rules = load_rules(conn)
    return [(c, latest.get(c['configuration_id']), evaluate_parts(parts.get(c['configuration_id'], []), specs, rules))
            for c in configs]


def customer_view(config, latest, state):
    content = config['content'] or {}
    return dict(configuration_id=config['configuration_id'], title=content.get('title'),
                intro=content.get('intro'), scene=content.get('scene') or None,
                benefits=[dict(title=b[0], text=b[1]) for b in content.get('benefits', []) if isinstance(b, (list, tuple)) and len(b) == 2],
                checks=list(content.get('checks', [])), facts=content.get('facts', {}),
                parts=[dict(slot=p['slot'], slot_label=p['slot_label'], name=p['name'], quantity=p['quantity'])
                       for p in state['parts']],
                price=state['price'], price_note=PRICE_NOTE, released_at=latest['created_at'].isoformat())


def customer_list(conn, ids=None):
    """고객에게 지금 보여도 되는 신규 조립PC. 하나라도 어긋나면 빠진다."""
    return [customer_view(c, l, s) for c, l, s in load(conn, ids) if is_live_release(c, l) and s['ok']]
