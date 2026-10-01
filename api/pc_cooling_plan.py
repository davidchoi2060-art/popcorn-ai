"""CPU package contents are separate from the cooler actually selected in the BOM."""
import re
import json
from pathlib import Path
from .part_explanations import is_current

AMD_5500GT = 'https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5500gt.html'


PROFILES = json.loads(Path(__file__).with_name('pc_cpu_cooling_profiles.json').read_text(encoding='utf-8'))
METHOD_LABELS = {'air': '별도 공랭', 'liquid': '수랭', 'bundled_air': '기본 공랭', 'unknown': '냉각 방식 확인 필요'}


def cooling_guidance(parts, rows, specs, installed):
    """Read-only planning guidance; never changes BOM, prices or approval rules."""
    cpus = [p for p in parts if p['slot'] == 'CPU' and not p['pseudo']]
    coolers = [p for p in parts if p['slot'] == 'COOLER' and not p['pseudo']]
    kinds = [specs.get(p['explanation_code'], {}).get('part_type') for p in coolers]
    method = 'unknown'
    if kinds and all(k == 'COOLER_CPU_AIR' for k in kinds): method = 'air'
    elif kinds and all(k == 'COOLER_CPU_AIO' for k in kinds): method = 'liquid'
    elif not coolers and installed == 'bundled': method = 'bundled_air'
    result = dict(method=method, method_label=METHOD_LABELS[method], cpu_model=None,
                  manufacturer_guidance='CPU별 제조사 권장 확인 필요', planning_proposal='CPU 모델 근거 확인 후 냉각 방향 검토',
                  guidance_status='unknown', source_url=None,
                  validation_note='냉각 방향은 구성 검토 기준입니다. 실제 장착·부하 온도·소음 검수는 별도입니다.')
    if len(cpus) != 1 or cpus[0].get('quantity', 1) != 1: return result
    row = rows.get(cpus[0]['explanation_code'])
    if not row: return result
    if is_current(row): name = row.get('product_name') or ''
    elif row.get('product_code') is None and specs.get(cpus[0]['explanation_code'], {}).get('part_type') == 'CPU':
        # specs_for_review already verifies assembly-only source fingerprint and manufacturer evidence.
        name = (row.get('source_snapshot') or {}).get('name') or ''
    else: return result
    matches = [model for model in PROFILES if re.search(r'(?<![A-Za-z0-9])'+re.escape(model).replace(r'\ ', r'\s+')+r'(?![A-Za-z0-9])', name, re.I)]
    if len(matches) != 1: return result
    model = matches[0]
    result.update(PROFILES[model], cpu_model=model, guidance_status='planning', researched_at='2026-10-01')
    if method in ('air', 'bundled_air') and ('수랭 권장' in result['manufacturer_guidance'] or result['planning_proposal'].startswith('수랭 우선')):
        result['review_hint'] = '현재 공랭 구성은 유지합니다. 장시간 부하 온도·전력 설정·소음 검수 근거를 확인하고 필요하면 수랭 변경안을 검토합니다.'
    return result


def _package_plan(parts, rows):
    cpus = [p for p in parts if p['slot'] == 'CPU' and not p['pseudo']]
    coolers = [p for p in parts if p['slot'] == 'COOLER' and not p['pseudo']]
    result = dict(bundle_status='unknown', bundle_label='CPU 기본 쿨러 포함 여부 확인',
                  bundled_model=None, installed='separate' if coolers else 'unknown',
                  separate_codes=[p.get('source_code', p.get('explanation_code')) for p in coolers], evidence=None,
                  manufacturer_url=None, verified_bundle=False,
                  price_note='별도 쿨러 단가는 등록 부품 가격 기준',
                  action='CPU 포장과 실제 조립 쿨러를 각각 확인합니다.')
    if len(cpus) != 1 or cpus[0].get('quantity', 1) != 1:
        return result
    row = rows.get(cpus[0]['explanation_code'])
    if not row or not is_current(row):
        return result
    name, spec = row.get('product_name') or '', row.get('spec_source_text') or ''
    source = name + ' / ' + spec
    compact = re.sub(r'\s+', '', source).lower()
    absent = bool(re.search(r'쿨러(?:미포함|없음)|쿨러불포함', compact))
    included = bool(re.search(r'(?:쿨러포함|쿨러\)?포함)', compact))
    # "미포함" must never be mistaken for an included cooler.
    if included and (absent or '벌크' in name):
        result.update(bundle_status='conflict', bundle_label='CPU 쿨러 포함 정보 충돌')
    elif absent or '벌크' in name:
        result.update(bundle_status='not_included', bundle_label='CPU 패키지 기본 쿨러 미포함')
    elif included:
        model = 'AMD Wraith Stealth' if 'wraithstealth' in compact else None
        result.update(bundle_status='included', bundle_label='CPU 기본 쿨러 포함', bundled_model=model)
        # Narrow manufacturer/package match. Multipack alone is insufficient.
        verified = (model is not None and re.search(r'(?<!\d)5500GT(?!\w)', name, re.I)
                    and '멀티팩' in name and not absent)
        result.update(verified_bundle=bool(verified), manufacturer_url=AMD_5500GT if verified else None)
    result['evidence'] = dict(cpu_code=cpus[0]['source_code'], name=name, spec=spec,
                              source_fingerprint=row['source_fingerprint'])
    if result['bundle_status'] == 'included':
        if coolers:
            result.update(action='등록된 별도 쿨러를 유지합니다. 기본 쿨러와 동시에 장착하지 않으며, 업그레이드 이유와 미사용 기본 쿨러 동봉 여부를 확인합니다.')
        else:
            result.update(installed='bundled', price_note='CPU 가격에 포함 · 별도 쿨러 비용을 더하지 않음',
                          action='알뜰 구성은 기본 쿨러를 활용합니다. 저소음·장시간 부하·LED 요구가 있으면 검증된 별도 쿨러 변경안을 제시합니다.')
    elif coolers:
        result['action'] = '등록된 별도 쿨러를 유지하고 소켓·장착 공간·부하 온도를 확인합니다.'
    elif result['bundle_status'] == 'not_included':
        result['action'] = '별도 CPU 쿨러가 필요합니다. 검증된 쿨러를 구성에 추가하기 전에는 추천하지 않습니다.'
    return result


def cooling_plan(parts, rows, specs=None):
    result = _package_plan(parts, rows)
    if specs is not None:
        result.update(cooling_guidance(parts, rows, specs, result['installed']))
    return result
