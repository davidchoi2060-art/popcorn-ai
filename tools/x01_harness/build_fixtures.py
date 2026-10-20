# -*- coding: utf-8 -*-
"""X01 격리 재현 — AI 슈퍼컴퓨터 «신규 장비 추가» 예외 fixture 만들기 (2026-10-20 대표 요청).

DB·네트워크를 쓰지 않는다. 상품 행(products + ai_device_profiles 를 합친 모양)을 이 파일에 직접 적고,
실제 백엔드 함수 `api.customer_supercomputer.item()` 으로 고객 API 응답(목록·상세)을 만든다.
  · Dell 두 행의 표시 정보는 마이그레이션 0166 의 값(`_gb10`, `IMAGES`)을 그대로 불러 쓴다(따로 베끼지 않는다).
  · 표시 정보가 없는 행은 백엔드의 상품명 추론(`derive`)을 거친다 — 응답의 `derived` 에 추론한 칸이 남는다.
  · «비노출»은 실제 reader 의 SQL 조건(`p.is_visible`)이 결과에서 뺀다. 여기서는 그 결과를 흉내 내 목록에서 뺀다
    (SQL 조건 자체는 tests/test_supercomputer_three_fixes_20261020.py 가 소스로 확인한다).
출력: tools/x01_harness/fixtures/<케이스>.json  (+ manifest.json: 파일별 SHA256)

실행: python tools/x01_harness/build_fixtures.py
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg2://x:x@127.0.0.1:1/x')   # 연결하지 않는다(가져오기용)
from api import customer_supercomputer as SC   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / 'fixtures'


def _mig(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'db/migrations/versions' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M66 = _mig('0166_ai_supercomputer_category')


def row(code, name, price, **kw):
    base = {'product_code': code, 'product_name': name, 'p_maker': None, 'sale_price': price, 'status': '판매중',
            'display_name': None, 'maker': None, 'model_name': None, 'accelerator': None, 'processor': None, 'memory': None,
            'storage': None, 'os': None, 'architecture': None, 'model_group': None, 'model_label': None, 'featured_rank': None,
            'images': None, 'detail': None, 'has_explained_photo': False, 'visible': True}
    base.update(kw)
    return base


def dell(code, storage, price, rank, **kw):
    return row(code, f'DELL Pro Max GB10 (128GB, M.2 {storage})', price, p_maker='DELL', display_name='Dell Pro Max GB10',
               maker='Dell', model_name='Pro Max GB10', accelerator='NVIDIA GB10', processor='20코어 ARM 기반 CPU',
               memory='128GB', storage=storage, os='DGX OS', architecture='ARM', model_group=M66.GROUP,
               model_label=storage, featured_rank=rank, images=M66.IMAGES, detail=M66._gb10(storage), **kw)


# 가상 상품번호(900xxx)는 실제 판매 상품이 아니다 — 격리 재현용.
ASUS_GB10 = lambda **kw: row(900001, 'ASUS Ascent GX10 GB10 (128GB, M.2 4TB)', 9000000, p_maker='ASUS', **kw)
SPARK_OEM = lambda **kw: row(900002, '[테스트] 미니 AI PC [128GB/2TB NVMe] NVIDIA DGX Spark기반', 8000000, p_maker='TESTMAKER', **kw)
NON_GB10 = lambda **kw: row(900003, '워크스테이션 [14900K/64G/2TB+4TB/RTX5090]', 15000000, p_maker='팝콘', **kw)
HP_PROFILE = lambda **kw: row(900004, 'HP Z2 Mini G1a (128GB, M.2 2TB)', 7000000, p_maker='HP', display_name='HP Z2 Mini G1a',
                              maker='HP', model_name='Z2 Mini G1a', processor='AMD Ryzen AI Max+ PRO 395', memory='128GB',
                              storage='2TB', os=None, architecture='x86-64', **kw)

D15 = lambda rank=1, **kw: dell(129615, '2TB', 12052100, rank, **kw)
D14 = lambda rank=2, **kw: dell(129614, '4TB', 14209400, rank, **kw)

# (케이스 ID, 목적, 행 목록, 기대값)
#   ad_models  메인 GB10 광고 모델 줄의 상품번호(순서대로). [] = «제품 목록 보기» 안내
#   ad_cta     대표 버튼 «제품 사양·가격 보기»의 상품번호. None = 버튼 숨김
#   list       AI 슈퍼컴퓨터 목록에 보일 상품번호(순서 무관)
#   details    {상품번호: 상세 기대} — dell_content: Dell 사진·DGX OS·포트·2TB/4TB FAQ 가 나오면 안 됨(False)
CASES = [
    ('C01-current', '지금과 같은 Dell 2종 + 표시 정보가 있는 타사 1종', [D15(), D14(), HP_PROFILE()],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [129615, 129614, 900004]}),
    ('C02-other-ranked-first', '타사 장비가 대표 순위 1위(Dell 은 2·3위)', [HP_PROFILE(featured_rank=1), D15(rank=2), D14(rank=3)],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [900004, 129615, 129614]}),
    ('C03-no-ranks', '대표 순위가 모두 비어 있음', [ASUS_GB10(), D14(rank=None), D15(rank=None)],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [900001, 129614, 129615]}),
    ('C04-same-ranks', '타사·Dell 대표 순위가 모두 같음(1)', [ASUS_GB10(featured_rank=1), D14(rank=1), D15(rank=1)],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [900001, 129614, 129615]}),
    ('C05-no-dell', 'Dell GB10 이 카테고리에 없음(같은 GB10 칩 타사 + 비GB10 타사만)', [ASUS_GB10(), NON_GB10()],
     {'ad_models': [], 'ad_cta': None, 'list': [900001, 900003]}),
    ('C06-dell-hidden', 'Dell 두 상품이 비노출(reader SQL 이 빼는 결과를 흉내)', [D15(visible=False), D14(visible=False), HP_PROFILE()],
     {'ad_models': [], 'ad_cta': None, 'list': [900004]}),
    ('C07-dell-stopped', 'Dell 두 상품이 판매 중지(품절)', [D15(status='품절'), D14(status='품절'), HP_PROFILE()],
     {'ad_models': [], 'ad_cta': None, 'list': [129615, 129614, 900004]}),
    ('C08-empty', '카테고리 전체가 비어 있음', [],
     {'ad_models': [], 'ad_cta': None, 'list': []}),
    ('C09-one-dell', 'Dell 모델 하나(4TB)만 남음', [D14(), HP_PROFILE()],
     {'ad_models': [129614], 'ad_cta': 129614, 'list': [129614, 900004]}),
    ('C10-missing-profile', '표시 정보·사진이 없는 타사 3종(GB10 이름 · DGX Spark 이름 · 비GB10)', [D15(), D14(), ASUS_GB10(), SPARK_OEM(), NON_GB10()],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [129615, 129614, 900001, 900002, 900003],
      'details': {900001: {'accelerator': 'NVIDIA GB10', 'spec_accelerator': 'NVIDIA GB10 (상품명 기준)', 'derived_note': True, 'os': '확인 필요', 'images': 0, 'models': 0, 'dell_content': False},
                  900002: {'accelerator': 'NVIDIA GB10', 'spec_accelerator': 'NVIDIA GB10 (상품명 기준)', 'derived_note': True, 'os': '확인 필요', 'images': 0, 'models': 0, 'dell_content': False},
                  900003: {'accelerator': None, 'spec_accelerator': '확인 필요', 'derived_note': True, 'processor': '확인 필요', 'os': '확인 필요', 'images': 0, 'models': 0, 'dell_content': False}}}),
    ('C11-price-unknown', 'Dell 2TB 판매가 없음 · 타사 판매가 없음', [D15(sale_price=None), D14(), ASUS_GB10(sale_price=None)],
     {'ad_models': [129615, 129614], 'ad_cta': 129615, 'list': [129615, 129614, 900001], 'prices': {129615: '가격 확인 필요', 900001: '가격 확인 필요'}}),
]


def build(case_id, purpose, rows, expect):
    visible = [r for r in rows if r['visible']]
    # 목록 응답 = 실제 reader 와 같은 정렬(대표 순위, 비면 뒤로 · 상품번호 내림차순)
    visible.sort(key=lambda r: (r['featured_rank'] is None, r['featured_rank'] or 0, -r['product_code']))
    items = [SC.item(r) for r in visible]
    details = {}
    for r in visible:
        d = SC.item(r, with_detail=True)
        d['models'] = ([{k: v for k, v in SC.item(x).items() if k in ('product_code', 'model_label', 'price', 'sale_state')}
                        for x in sorted(visible, key=lambda x: (x['featured_rank'] is None, x['featured_rank'] or 0, x['product_code']))
                        if r['model_group'] and x['model_group'] == r['model_group']])
        details[str(r['product_code'])] = {'ok': True, 'item': d}
    return {'case': case_id, 'purpose': purpose, 'expect': expect,
            'input_rows': rows,
            'list': {'ok': True, 'category': {'key': SC.KEY, 'name': 'AI 슈퍼컴퓨터'}, 'items': items},
            'detail': details}


def main():
    OUT.mkdir(exist_ok=True)
    manifest = {}
    for case_id, purpose, rows, expect in CASES:
        data = build(case_id, purpose, rows, expect)
        p = OUT / f'{case_id}.json'
        p.write_bytes((json.dumps(data, ensure_ascii=False, indent=1, default=str) + '
').encode('utf-8'))   # 줄바꿈 LF 고정(SHA256 이 OS 와 무관)
        manifest[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
        print(case_id, manifest[p.name][:16], len(data['list']['items']))
    (OUT / 'manifest.json').write_bytes((json.dumps(manifest, indent=1) + '
').encode('utf-8'))


if __name__ == '__main__':
    main()
