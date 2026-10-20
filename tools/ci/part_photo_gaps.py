"""판매 PC 부품 사진 빈칸 집계(읽기 전용) — dev-screen-check.yml 이 GAPS=1 일 때 부른다.

공개 고객 API 만 부른다(비밀값·DB 없음):
  GET /api/customer/pc-catalog                 판매 PC 목록
  GET /api/customer/pc-registered/{code}       공개 구성이 없는 PC 의 몰 등록 구성
  GET /api/customer/pc-offers/{code}           공개 구성이 있는 PC 의 승인 구성
  HEAD 팝콘PC 몰 대표 사진                     공개 사진이 없는 PC 의 몰 사진 유무
사진 없는 부품을 슬롯·문구별로 묶어 마크다운으로 낸다.
"""
import collections
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get('BASE', 'https://popcornai.co.kr').rstrip('/')
MALL = 'https://www.popcornpc.co.kr/data/pimg/{d}/{c}_600.jpg'


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {'_http': e.code}


def head(url):
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, int(r.headers.get('Content-Length') or 0)
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:
        return type(e).__name__, 0


def page_imgs(code):
    import re
    req = urllib.request.Request(f'https://www.popcornpc.co.kr/shop/system_detail.html?pd_no={code}',
                                 headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode('euc-kr', 'replace')
    except Exception as e:
        return [type(e).__name__]
    found = re.findall(r'(?:og:image"[^>]*content="([^"]+)")|(/data/pimg/[^"\' >]+)', html)
    return list(dict.fromkeys(a or b for a, b in found))[:6]


def offer_parts(body):
    conf = (body or {}).get('public_configuration') or {}
    for x in conf.get('parts') or []:
        if x.get('pseudo') or not x.get('name'):
            continue
        ph = x.get('photo') or {}
        yield x.get('slot'), x.get('name'), ph.get('state') == 'approved'


def supercomputers():
    """AI 슈퍼컴퓨터 목록 — 사진 유무와 판매가, 메인 하단 «낮은 가격순 2개» 선정 근거."""
    import datetime
    d = get('/api/customer/supercomputers')
    items = d.get('items') or []
    print(f"### AI 슈퍼컴퓨터 {len(items)}종 (조회 {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}, checked_at {d.get('checked_at')})")
    print('```')
    for x in items:
        img = (x.get('images') or [{}])[0].get('src') or '-'
        print(f"{x.get('product_code')}\t{x.get('sale_state')}\t{x.get('price')}\t{x.get('name')}\t{x.get('memory')}/{x.get('storage')}\t{img}")
    sale = sorted((x for x in items if x.get('sale_state') == 'on_sale' and isinstance(x.get('price'), int) and x['price'] > 0),
                  key=lambda x: (x['price'], x['product_code']))
    print('cheapest2: ' + ' | '.join(f"{x['product_code']} {x['name']} {x['price']}" for x in sale[:2]))
    print('```\n')


def main():
    supercomputers()
    items = get('/api/customer/pc-catalog').get('items') or []
    reg_gap, off_gap = collections.Counter(), collections.Counter()
    reg_n = reg_ph = off_n = off_ph = 0
    no_mall = []
    for it in items:
        c = it['product_code']
        if it.get('configuration_public'):
            for slot, name, ok in offer_parts(get(f'/api/customer/pc-offers/{c}')):
                off_n += 1
                off_ph += ok
                if not ok:
                    off_gap[(slot, name)] += 1
        else:
            for x in (get(f'/api/customer/pc-registered/{c}').get('parts') or []):
                reg_n += 1
                if x.get('photo'):
                    reg_ph += 1
                else:
                    reg_gap[(x.get('slot'), x.get('name'))] += 1
        if not it.get('photo_hint'):
            st, size = head(MALL.format(d=c // 1000, c=c))
            if st != 200 or size < 2000:      # 화면은 .jpg 가 없으면 .gif 로 다시 읽는다(live-catalog.js)
                st, size = head(MALL.format(d=c // 1000, c=c)[:-4] + '.gif')
            if st != 200 or size < 2000:
                no_mall.append((c, it.get('name'), st, size))
    print(f'### 판매 PC {len(items)}대')
    print(f'- 몰 등록 구성: 부품 {reg_n}개 중 사진 {reg_ph}개, 빈칸 {reg_n - reg_ph}개(문구 {len(reg_gap)}종)')
    print(f'- 승인 구성: 부품 {off_n}개 중 사진 {off_ph}개, 빈칸 {off_n - off_ph}개(문구 {len(off_gap)}종)')
    print(f'- 공개 사진 없고 몰 대표 사진(.jpg·.gif)도 없는 PC: {len(no_mall)}대')
    for title, gap in (('몰 등록 구성 빈칸', reg_gap), ('승인 구성 빈칸', off_gap)):
        print(f'\n#### {title}\n```')
        for (slot, name), n in sorted(gap.items(), key=lambda kv: (str(kv[0][0]), -kv[1])):
            print(f'{slot}\t{n}\t{name}')
        print('```')
    print('\n#### 몰 사진 없는 PC\n```')
    for row in no_mall:
        print('\t'.join(map(str, row)))
        c = row[0]
        for x in (get(f'/api/customer/pc-registered/{c}').get('parts') or []):
            print(f"  {x.get('slot')}\t{'O' if x.get('photo') else '-'}\t{x.get('name')}")
        print('  page-imgs: ' + ' '.join(page_imgs(c)))
    print('```')


if __name__ == '__main__':
    main()
