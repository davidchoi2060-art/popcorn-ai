"""MVP3 부품 수량 — 메모리·저장장치를 메인보드가 받을 수 있는 만큼만 늘린다
(2026-10-12 중헌 님 7번 「메모리와 저장 장치는 메인보드의 지원 조건까지 수량 조절이 가능하면 좋겠습니다」).

■ 무엇을 세나
  메모리   꽂히는 모듈 수 = 줄 수량 × 상품 한 개의 모듈 수(16GB×2 묶음이면 2) ≤ 메인보드 메모리 슬롯
           합계 용량 = 줄 수량 × 상품 용량 ≤ 메인보드 최대 메모리
  저장장치 M.2 SSD 수 ≤ 메인보드 M.2 슬롯 · SATA SSD·HDD 수 ≤ 메인보드 SATA 포트
■ 원천   `product_specs` 의 칸(mem_slots · mem_max_gb · m2_slots · sata_ports · module_count · capacity_gb ·
         form_factor · interface)이 있으면 그 값, 없으면 같은 상품의 `spec_source_text` 를
         `tools/std_parse.py` 와 같은 규칙으로 읽는다. 둘 다 없으면 «모른다» — 늘리지 않는다.
■ 줄이는 것은 1개까지 언제나 된다(빼는 쪽은 메인보드 조건과 무관하다). 줄을 없애지는 않는다.
"""
import re

from .ram_bundle import ram_bundle

QTY_SLOTS = ('RAM', 'SSD')
MAX_LINE_QTY = 8
MAX_SETS = 10

_RX = {
    'mem_slots': r'(?:^|/)\s*슬롯\s*:\s*(\d+)',
    'mem_max_gb': r'최대\s*([\d,]+)\s*\(GB\)',
    'm2_slots': r'M\.2\s*:\s*(\d+)',
    'sata_ports': r'SATA3?\s*:\s*(\d+)',
    'module_count': r'패키지\s*구성\s*:\s*(\d+)',
}


def _num(key, raw):
    m = re.search(_RX[key], raw or '')
    return int(m[1].replace(',', '')) if m else None


def _pos(v):
    return v if type(v) is int and v > 0 else None


def _pick(spec, raw, key):
    return _pos((spec or {}).get(key)) or _pos(_num(key, raw))


def board(spec, raw):
    """메인보드가 받는 개수. 모르는 칸은 None."""
    return {k: _pick(spec, raw, k) for k in ('mem_slots', 'mem_max_gb', 'm2_slots', 'sata_ports')}


def ram_unit(spec, raw, name):
    """상품 한 개의 (모듈 수, 용량 GB). 용량을 모르면 None."""
    bundle = ram_bundle(name or '')
    modules = _pick(spec, raw, 'module_count') or (bundle['module_count'] if bundle else 1)
    cap = _pos((spec or {}).get('capacity_gb')) or (bundle['total_gb'] if bundle else None)
    return modules, cap


def storage_kind(spec, raw, slot):
    """'m2' · 'sata' · None(모름). HDD 는 SATA 다."""
    if slot == 'HDD':
        return 'sata'
    s = spec or {}
    words = ' '.join(str(s.get(k) or '') for k in ('form_factor', 'interface'))
    if re.search(r'M\.2', words, re.I):
        return 'm2'
    if re.search(r'SATA|2\.5|3\.5', words, re.I):
        return 'sata'
    if re.search(r'M\.2|NVMe', raw or '', re.I):
        return 'm2'
    if re.search(r'SATA|6\.4cm|8\.9cm|2\.5형|3\.5형', raw or '', re.I):
        return 'sata'
    return None


def usage(lines, specs, raws):
    """구성 전체가 쓰는 자리. lines = [{ordinal, slot, product_code, quantity, name}]."""
    out = dict(board=None, ram=[], storage=[])
    for l in lines:
        code, slot = l.get('product_code'), l.get('slot')
        if code is None:
            continue
        spec, raw = specs.get(code), raws.get(code)
        if slot == 'MB':
            out['board'] = board(spec, raw)
        elif slot == 'RAM':
            modules, cap = ram_unit(spec, raw, l.get('name'))
            out['ram'].append(dict(ordinal=l['ordinal'], quantity=l['quantity'], modules=modules, cap=cap))
        elif slot in ('SSD', 'HDD'):
            out['storage'].append(dict(ordinal=l['ordinal'], quantity=l['quantity'],
                                       kind=storage_kind(spec, raw, slot)))
    return out


def _room(limit, used, per):
    return None if limit is None or per is None else (limit - used) // per


def line_limit(u, ordinal):
    """그 줄을 몇 개까지 둘 수 있나 → (최대 · 근거 문장). 최대가 None 이면 늘릴 수 없다(근거를 모른다)."""
    b = u['board'] or {}
    ram = next((r for r in u['ram'] if r['ordinal'] == ordinal), None)
    if ram is not None:
        others = [r for r in u['ram'] if r['ordinal'] != ordinal]
        if b.get('mem_slots') is None or any(r['cap'] is None for r in u['ram']):
            return None, '메인보드 메모리 슬롯이나 메모리 용량 정보를 확인하지 못해 수량을 늘릴 수 없어요.'
        sticks = sum(r['quantity'] * r['modules'] for r in others)
        top = _room(b['mem_slots'], sticks, ram['modules'])
        basis = f"메인보드 메모리 슬롯 {b['mem_slots']}개"
        if b.get('mem_max_gb') is not None:
            gb = sum(r['quantity'] * r['cap'] for r in others)
            top = min(top, _room(b['mem_max_gb'], gb, ram['cap']))
            basis += f" · 최대 {b['mem_max_gb']}GB"
        return max(0, min(top, MAX_LINE_QTY)), basis + ' 기준이에요.'
    disk = next((s for s in u['storage'] if s['ordinal'] == ordinal), None)
    if disk is not None:
        if disk['kind'] is None:
            return None, '이 저장장치가 M.2인지 SATA인지 확인하지 못해 수량을 늘릴 수 없어요.'
        key, word = ('m2_slots', 'M.2 슬롯') if disk['kind'] == 'm2' else ('sata_ports', 'SATA 포트')
        if b.get(key) is None:
            return None, f'메인보드 {word} 수를 확인하지 못해 수량을 늘릴 수 없어요.'
        used = sum(s['quantity'] for s in u['storage'] if s['ordinal'] != ordinal and s['kind'] == disk['kind'])
        return max(0, min(b[key] - used, MAX_LINE_QTY)), f'메인보드 {word} {b[key]}개 기준이에요.'
    return None, '수량을 바꿀 수 없는 부품이에요.'


def limit_for(u, ordinal, current):
    """화면에 줄 최대 수량 — 지금 수량보다 작게 말하지 않는다(기본 구성이 이미 그만큼이다)."""
    top, basis = line_limit(u, ordinal)
    return dict(min=1, max=max(current, top or 0), basis=basis, known=top is not None)


def refusal(u, raised):
    """늘린 줄(raised = {ordinal: 수량})이 메인보드 조건을 넘으면 그 이유. 넘지 않으면 None."""
    for ordinal, qty in raised.items():
        top, basis = line_limit(u, ordinal)
        if top is None:
            return basis
        if qty > top:
            return f'메인보드가 받을 수 있는 수량을 넘어요({basis.removesuffix(" 기준이에요.")}). {top}개까지 고를 수 있어요.'
    return None
