"""Read-only exception grouping over a current audit, not a second approval engine."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audit_pc_catalog import analyze
from tools.enrich_pc_catalog_sources import validate_source
from api.pc_review_specs import specs_for_review
from api.pc_review_policy import issue_stages


def triage(data, plan):
    audit = analyze(data)
    rows = {r['source_product_code']: r for r in data['rows']}
    specs = {r['product_code']: r for r in data['specs']}
    rules = {r['rule_key']: r for r in data['rules']}
    resolved = specs_for_review(rows, specs)
    by_config = defaultdict(list)
    for part in data['parts']:
        by_config[part['configuration_id']].append(part)
    eligible = {}; rejected = []
    for item in plan:
        code = item['code']
        try:
            row = rows[code]
            validate_source(item, row)
            fields = item.get('specs', {})
            if (not fields or row['status'] != 'draft' or row['content'].get('review_issues')
                    or any(s['id'] == item['source']['id'] for s in row['content']['sources'])
                    or any(f not in ('cooler_tdp', 'gpu_power_draw_watt')
                           or type(v) is not int or v <= 0 or specs[code].get(f) is not None
                           for f, v in fields.items())):
                raise ValueError('Not a missing unlocked-model fact / already applied')
            for field in fields:
                eligible[code, field] = item
        except (KeyError, ValueError) as exc:
            rejected.append(dict(code=code, reason=str(exc)))
    tasks = {}

    def add(kind, key, title, ids, code=None):
        task = tasks.setdefault(key, dict(kind=kind, key=key, title=title,
                                         code=code, configurations=set()))
        task['configurations'].update(ids)

    for part in audit['common_parts']:
        for issue in part['issues']:
            routed = any(i['issue']==issue and i['stage']=='assembly' for i in issue_stages(rows.get(part['code'],{})))
            add('조립 단계 공통 확인' if routed else '공통 부품 확인', f"part:{part['code']}:{issue}", issue,
                part['configurations'], part['code'])
    for cfg in audit['configurations']:
        if cfg['group'] == '추천 가능 후보':
            continue
        for check in cfg['review'].get('assembly_checks', []):
            if check['key'].startswith('part:'):
                continue
            # Ordinals are local to a BOM; do not merge different components.
            rule_key, *ordinals = check['key'].split(':')
            identities = [str(p['explanation_code']) for p in by_config[cfg['id']]
                          if str(p['ordinal']) in ordinals and not p['pseudo']]
            task_key = 'assembly:' + rule_key + ':' + ':'.join(sorted(identities))
            if not identities:
                task_key += ':' + cfg['id']
            add('조립 단계 공통 확인',task_key,check['label']+' · '+check['detail'],[cfg['id']])
        for check in cfg['unknown'] + cfg['failed']:
            rule = rules[check['key'].split(':')[0]]
            slots = defaultdict(list)
            for part in by_config[cfg['id']]:
                if not part['pseudo']:
                    slots[part['slot']].append(part)
            left, right = slots[rule['slot']], slots[rule['ref_slot']]
            if not left or not right:
                gpu_absent = rule['ref_slot'] == 'GPU' and left and not right
                add('검사 적용 대상 점검' if gpu_absent else '실제 구성 식별',
                    'missing:'+rule['rule_key'], check['label']+' · 구성/적용 여부', [cfg['id']])
                continue
            # The existing review keys identify the precise pair, including multi-slot BOMs.
            _, lnum, rnum = check['key'].split(':')
            lp = next(p for p in left if p['ordinal'] == int(lnum))
            rp = next(p for p in right if p['ordinal'] == int(rnum))
            if check['state'] == 'fail':
                add('충돌 확인·대체 검토', f"conflict:{lp['explanation_code']}:{rp['explanation_code']}:{rule['rule_key']}",
                    check['label']+' · '+check['detail'], [cfg['id']], lp['explanation_code'])
                continue
            # Resolve both ends with the same assembly/retail rules as the audit.
            missing = [(p, field) for p, field in ((lp, rule['field']), (rp, rule['ref_field']))
                       if resolved.get(p['explanation_code'], {}).get(field) is None]
            for part, field in missing:
                code = part['explanation_code']
                kind = '자동 보완 후보' if (code, field) in eligible else '공통 사양 근거 확보'
                add(kind, f'field:{code}:{field}', f'{code} · {field}', [cfg['id']], code)
            if not missing:
                add('개별 검토', 'rule:'+check['key'], check['detail'], [cfg['id']])
        for label in cfg['structural'] + cfg['price_notes']:
            add('개별 검토', f"config:{cfg['id']}:{label}", label, [cfg['id']])
        # Preserve blockers not already covered by shared component issues.
        covered = [t for t in tasks.values() if cfg['id'] in t['configurations'] and t['key'].startswith('part:')]
        for label in cfg['review']['blockers']:
            if label.startswith(('호환성',)) or any(str(t['code']) in label for t in covered):
                continue
            if any(check['label'] in label for check in cfg['failed']):
                continue
            add('개별 검토', f"block:{cfg['id']}:{label}", label, [cfg['id']])
    output = []
    for task in tasks.values():
        task['configurations'] = sorted(task['configurations'])
        task['affected_count'] = len(task['configurations'])
        output.append(task)
    output.sort(key=lambda t: (-t['affected_count'], t['key']))
    auto_only = [c['id'] for c in audit['configurations'] if c['group'] == '보완 필요'
                 and (linked := [t for t in output if c['id'] in t['configurations']])
                 and all(t['kind'] == '자동 보완 후보' for t in linked)]
    return dict(at=data['at'], counts=audit['counts'], total=audit['total'],
                task_counts=dict(Counter(t['kind'] for t in output)), tasks=output,
                auto_only_configurations=auto_only, rejected_plan=rejected,
                note='읽기 전용 분류. 잠금·동시 수정 검사는 적용 트랜잭션에서 재확인. 승인/출고 아님. 관련 구성 수는 중복 가능.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = triage(json.loads(args.source.read_text(encoding='utf8')),
                    json.loads(args.plan.read_text(encoding='utf8')))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k != 'tasks'}, ensure_ascii=False))
