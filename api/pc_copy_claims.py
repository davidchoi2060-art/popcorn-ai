"""Narrow claim checks for observed copy failures, not a general fact checker.

The catalog has no authoritative OS/peripheral inclusion or warranty source.
Neither BOM omissions, existing copy, nor model notes establish sales terms.
"""
import re

SALES_SUBJECTS = {
    'os': r'운영\s*체제|(?<![A-Za-z])OS(?![A-Za-z])|윈도우|Windows',
    'keyboard': r'키보드',
    'mouse': r'마우스',
    'monitor': r'모니터',
    'peripherals': r'주변\s*기기',
}
LABELS = dict(os='운영체제', keyboard='키보드', mouse='마우스', monitor='모니터',
              peripherals='주변기기', warranty='보증', software='프로그램 요구 조건')
INCLUSION = re.compile(
    r'(?:미\s*포함|불\s*포함|포함\s*(?:되어\s*있지|되지|하지|안\s*되|됩니다|돼|되어|된|하고|한다|합니다|입니다)|'
    r'기본\s*(?:제공|구성)|제공\s*(?:됩니다|되지|하지|합니다)|별도\s*(?:구매|구입|설치|준비)|제외\s*(?:됩니다|된|합니다))', re.I)
UNCERTAIN_TAIL = re.compile(r'^\s*(?:여부|인지|인가요|경우|되는지|되지\s*않는지|하는지|하지\s*않는지|할지|될지)')
SOFTWARE = re.compile(r'(?:프로그램|소프트웨어|앱).{0,60}(?:조건|사양|요구).{0,30}(?:충족(?:합니다|했다|하는|한|됩니다)|갖췄|갖추었|만족(?:합니다|하는|했다))', re.I)
WARRANTY = re.compile(r'(?:보증|무상\s*(?:AS|A/S|수리)).{0,30}(?:\d+\s*(?:년|개월)|제공합니다|보장합니다)', re.I)


def sales_context():
    # Deliberately no extraction from description/facts/BOM. No verified source exists yet.
    return {key: {'state': 'unknown'} for key in (*SALES_SUBJECTS, 'warranty')}


def statements(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from statements(item)
    elif isinstance(value, dict):
        # FAQ questions are questions, not assertions. Check answers independently.
        if 'answer' in value:
            yield from statements(value['answer'])
        else:
            for item in value.values():
                yield from statements(item)


def claim_issues(value, field=None):
    issues = set()
    if field == 'benefits':
        # A feature title and its description express one claim together.
        value = [' '.join(pair) for pair in value]
    for text in statements(value):
        for clause in re.split(r'[.!?。\n;]', text):
            for key, subject in SALES_SUBJECTS.items():
                for match in re.finditer(subject, clause, re.I):
                    tail = clause[match.end():]
                    assertion = INCLUSION.search(tail[:100])
                    if assertion and not UNCERTAIN_TAIL.match(tail[assertion.end():]):
                        issues.add(key)
            if any(not UNCERTAIN_TAIL.match(clause[m.end():]) for m in WARRANTY.finditer(clause)):
                issues.add('warranty')
            if SOFTWARE.search(clause):
                issues.add('software')
    return sorted(issues)


def filter_changes(proposal):
    safe, notes = [], list(proposal['notes'])
    for change in proposal['changes']:
        issues = claim_issues(change['value'], change['field'])
        if issues:
            labels = '·'.join(LABELS[key] for key in issues)
            notes.insert(0, f"근거 확인 필요: {change['field']} 제안 제외 ({labels}). 판매조건은 등록된 확정 근거가 없으며 프로그램 요구 조건은 별도 대조가 필요합니다.")
        else:
            safe.append(change)
    return dict(proposal, changes=safe, notes=list(dict.fromkeys(notes))[:15])
