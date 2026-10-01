"""CPU package contents are separate from the cooler actually selected in the BOM."""
import re
from .part_explanations import is_current

AMD_5500GT = 'https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen/ryzen-5000-series/amd-ryzen-5-5500gt.html'


def cooling_plan(parts, rows):
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
