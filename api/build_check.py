"""조립 호환 검사 — 부품 목록 하나를 `compat_rules` 로 판정한다 (부품 상품화 2단계).

고객 부품 바꾸기, 운영자 신규 조립PC 생성, 구성표 부품 수정, 관리자 검토가 **같은 판정**을
쓰게 하려고 둔다. 규칙의 비교 자체(`rule_verdict` · `_rule_applies` · `rule_ref_value`)는
견적 엔진(`api/recommend.py`)의 것을 그대로 쓴다 — 여기서 비교식을 다시 적지 않는다.

엔진의 탐색(`_slot_ok`)과 다른 점: 엔진은 슬롯마다 부품 하나를 고르는 중에 보지만, 여기는
**이미 정해진 구성 전체**를 본다. 메모리·저장장치가 여러 줄이면 줄마다 따로 판정한다.

판정은 셋이다.
  pass      규칙을 통과했다
  fail      규칙에 걸렸다 — 이 구성은 조립할 수 없다
  unknown   대상 부품이 없거나 사양 값이 없어 판정하지 못했다 — 「통과」로 세지 않는다
"""
from sqlalchemy import text

from . import std_specs
from .recommend import rule_verdict, rule_ref_value, _rule_applies

RULES_SQL = 'SELECT * FROM compat_rules WHERE active ORDER BY sort_order, rule_id'
DISPLAY_KEY = 'display_output'
DISPLAY_LABEL = '화면 출력(그래픽카드 또는 CPU 내장 그래픽)'


def load_rules(conn):
    return [dict(r) for r in conn.execute(text(RULES_SQL)).mappings()]


def load_specs(conn, product_codes):
    codes = sorted({int(c) for c in product_codes if c is not None})
    if not codes:
        return {}
    rows = [dict(r) for r in conn.execute(
        text('SELECT * FROM product_specs WHERE product_code = ANY(:codes)'), dict(codes=codes)).mappings()]
    return {r['product_code']: r for r in std_specs.attach(conn, rows)}   # 케이스 지원 파워 규격(0161)


def rule_checks(lines, specs, rules):
    """규칙마다, 해당 슬롯 줄 × 비교 슬롯 줄을 판정한다.

    lines: [{'key': 줄 구분값, 'slot': 'CPU', 'spec_key': specs 조회 키, 'label': 화면에 쓸 부품 표시}]
    """
    checks = []
    by_slot = {}
    for line in lines:
        by_slot.setdefault(line['slot'], []).append(line)
    for rule in rules:
        left, right = by_slot.get(rule['slot'], []), by_slot.get(rule['ref_slot'], [])
        if not left or not right:
            checks.append(dict(key=rule['rule_key'], label=rule['label'], state='unknown',
                               detail='대상 부품 또는 비교 부품 없음 · 내장/기본 포함 여부 근거 확인',
                               missing_slots=[x for x, side in ((rule['slot'], left), (rule['ref_slot'], right))
                                              if not side]))
            continue
        for p in left:
            s = specs.get(p['spec_key'], {})
            if s.get('part_type') and not _rule_applies(rule, s):
                continue
            for q in right:
                key = f"{rule['rule_key']}:{p['key']}:{q['key']}"
                ref = specs.get(q['spec_key'], {})
                v, r = s.get(rule['field']), ref.get(rule['ref_field'])
                if rule.get('null_ref_mode') == 'skip_any' and rule_verdict(rule, v, r) is None:
                    continue    # 어느 쪽 값이든 모르면 엔진처럼 판정하지 않는다(0160) — 「확인 필요」를 새로 만들지 않는다
                state = 'unknown'
                detail = f"{p['label']} {rule['field']}={v}; {q['label']} {rule['ref_field']}={r}"
                if v is not None and r is not None and s.get('part_type') and rule['op'] in ('eq', 'gte', 'lte', 'contains', 'in'):
                    try:
                        state = 'pass' if rule_verdict(rule, v, r) else 'fail'
                        detail = (rule.get('detail_fmt') or '{v} / {r}').replace('{v}', str(v)).replace('{r}', str(rule_ref_value(rule, r)))
                        if state == 'fail' and rule['op'] == 'in':
                            detail = f"파워 규격 {v} / 케이스 지원 {r} · 목록에 없음"
                        if state == 'fail' and rule['op'] == 'contains':
                            detail = f"등록 지원 목록 {v} / 대상 {r} · 목록에 없음"
                        if rule['rule_key'] == 'power':
                            detail = f"파워 정격 {v}W / GPU {r}W + 규칙 여유 {rule.get('ref_offset') or 0}W"
                    except (TypeError, ValueError):
                        detail += ' · 사양 형식 확인 필요'
                checks.append(dict(key=key, label=rule['label'], state=state, detail=detail,
                                   missing_fields=[field for field, value in ((rule['field'], v), (rule['ref_field'], r)) if value is None]))
    return checks


def display_check(lines, specs):
    """그래픽카드가 없으면 CPU 내장 그래픽이 있어야 화면이 나온다(`swap._display_lost` 와 같은 뜻)."""
    if any(l['slot'] == 'GPU' for l in lines):
        return dict(key=DISPLAY_KEY, label=DISPLAY_LABEL, state='pass', detail='그래픽카드 장착')
    cpu = next((l for l in lines if l['slot'] == 'CPU'), None)
    value = specs.get(cpu['spec_key'], {}).get('cpu_gpu') if cpu else None
    if value is True:
        return dict(key=DISPLAY_KEY, label=DISPLAY_LABEL, state='pass', detail='CPU 내장 그래픽 사용')
    if value is False:
        return dict(key=DISPLAY_KEY, label=DISPLAY_LABEL, state='fail', detail='그래픽카드 없음 · CPU 내장 그래픽 없음')
    return dict(key=DISPLAY_KEY, label=DISPLAY_LABEL, state='unknown', detail='그래픽카드 없음 · CPU 내장 그래픽 정보 없음')


def evaluate(lines, specs, rules, display=True):
    """구성 하나의 판정 묶음. `ok` 는 실패가 없다는 뜻이지 모르는 것이 없다는 뜻이 아니다."""
    checks = rule_checks(lines, specs, rules)
    if display:
        checks.append(display_check(lines, specs))
    failures = [c for c in checks if c['state'] == 'fail']
    unknown = [c for c in checks if c['state'] == 'unknown']
    return dict(ok=bool(rules) and not failures, rule_count=len(rules), checks=checks,
                failures=failures, unknown=unknown)


def product_lines(parts):
    """[{'slot','product_code', ...}] 를 판정 줄로 바꾼다. 줄 구분값은 순서 번호다."""
    return [dict(key=i, slot=p['slot'], spec_key=p['product_code'], label=str(p['product_code']))
            for i, p in enumerate(parts) if p.get('product_code') is not None]


def check(conn, parts, rules=None):
    """판매 상품 부품 목록 [{'slot','product_code'}] 을 DB 사양으로 판정한다."""
    rules = load_rules(conn) if rules is None else rules
    lines = product_lines(parts)
    return evaluate(lines, load_specs(conn, [l['spec_key'] for l in lines]), rules)
