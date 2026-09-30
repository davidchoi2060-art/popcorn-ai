"""Workflow routing only; compatibility values/operators remain in compat_rules."""
from .part_explanations import is_current

POLICY_VERSION = 'recommendation-assembly-v1'


def issue_stages(row):
    """Only explicitly reviewed, exact-source issue dispositions may be deferred."""
    content = row.get('content') or {}
    routes = content.get('review_issue_routes') or []
    current = is_current(row) if row.get('product_code') is not None else False
    result = []
    for issue in content.get('review_issues', []):
        route = next((r for r in routes if current and r.get('issue') == issue
                      and r.get('source_fingerprint') == row.get('source_fingerprint')
                      and r.get('stage') == 'assembly' and r.get('reason')
                      and r.get('source_url', '').startswith('https://')), None)
        result.append(dict(issue=issue, stage='assembly' if route else 'recommendation',
                           customer_conditions=route.get('customer_conditions', []) if route else []))
    return result


def route_checks(checks, parts, specs):
    """Retain unknown/fail truth; route only narrow noncritical unknowns to assembly."""
    slots = {}
    for part in parts:
        if not part['pseudo']:
            slots.setdefault(part['slot'], []).append(part)
    integrated = (not slots.get('GPU') and len(slots.get('CPU', [])) == 1
                  and specs.get(slots['CPU'][0]['explanation_code'], {}).get('cpu_gpu') is True
                  and any(p['slot'] == 'GPU' and p['pseudo'] for p in parts))
    by_ordinal = {p['ordinal']: p for p in parts if not p['pseudo']}
    for check in checks:
        check['stage'] = 'recommendation'
        if check['state'] != 'unknown':
            continue
        rule = check['key'].split(':')[0]
        if integrated and rule == 'gpu_len':
            check.update(state='not_applicable', stage='none', detail='외장 GPU 없음 · CPU 내장그래픽 사양 및 구성 확인')
        elif integrated and rule == 'power' and slots.get('POWER') and all(
                isinstance(specs.get(p['explanation_code'], {}).get('rated_watt'), (int, float))
                and specs[p['explanation_code']]['rated_watt'] > 0 for p in slots['POWER']):
            check.update(stage='assembly', detail='외장 GPU 없음 · 조립 시 CPU를 포함한 전체 전력·전원 연결 확인 (전원 적합 판정 전)')
        elif rule == 'cooler_tdp' and check.get('missing_fields') == ['cooler_tdp']:
            _, left, right = check['key'].split(':')
            part = by_ordinal[int(left)]
            s = specs.get(part['explanation_code'], {})
            socket_key = f"cooler_socket:{left}:{right}"
            if s.get('part_type') in ('COOLER_CPU_AIR', 'COOLER_CPU_AIO') and any(
                    c['key'] == socket_key and c['state'] == 'pass' for c in checks):
                check.update(stage='assembly', label='CPU 냉각 성능 확인',
                             detail='장착 소켓은 일치합니다. 쿨러 냉각 수치는 미확인 상태이며, 조립 후 부하·온도·안정성 검수가 필요합니다.')
    return checks
