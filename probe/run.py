"""골드 14400F 상품 대조 — 개발 서버 공개 GET 과 몰 공개 상품 페이지만 읽는다(쓰기·LLM 호출 없음)."""
import json, os, re, sys, urllib.request
BASE = 'https://popcornai.co.kr'
OUT = os.environ.get('OUT', 'out'); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 popcorn-probe'}
def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
        return (r.status, b) if raw else (r.status, json.loads(b))
st, cat = get(BASE + '/api/customer/pc-catalog')
items = cat['items']
print(f'catalog status={st} count={len(items)}')
json.dump(cat, open(f'{OUT}/catalog.json', 'w'), ensure_ascii=False)
pat = re.compile(r'14400F|102112|12400F/16G[B]?/500G[B]?/RTX ?5060', re.I)
hits = [it for it in items if pat.search((it.get('name') or '') + ' ' + (it.get('official_name') or ''))]
gold = [it for it in items if (it.get('name') or '').startswith('골드') or (it.get('official_name') or '').startswith('골드')]
print('## pattern hits'); [print(json.dumps({k: it.get(k) for k in ('product_code','name','official_name','price','sale_status','mall_url','spec','category','configuration_public','photo_hint')}, ensure_ascii=False)) for it in hits]
print('## gold names'); [print(it['product_code'], '|', it['name'], '|', it.get('official_name'), '|', it['price']) for it in gold]
for it in hits:
    code = it['product_code']
    for path in (f'/api/customer/pc-offers/{code}', f'/api/customer/products/{code}'):
        try:
            s, body = get(BASE + path, raw=True)
        except Exception as e:
            s, body = getattr(e, 'code', type(e).__name__), (e.read() if hasattr(e, 'read') else b'')
        open(f"{OUT}/{path.strip('/').replace('/', '_')}.json", 'wb').write(body or b'')
        print(path, s, len(body or b''), (body or b'')[:600].decode('utf-8', 'replace'))
    url = it.get('mall_url')
    if url:
        try:
            s, html = get(url, raw=True)
            for enc in ('utf-8', 'euc-kr', 'cp949'):
                try: t = html.decode(enc); break
                except Exception: t = html.decode('utf-8', 'replace')
            open(f'{OUT}/mall_{code}.html', 'w').write(t)
            title = re.search(r'<title>(.*?)</title>', t, re.S)
            og = re.findall(r'<meta[^>]+property="og:(?:title|description)"[^>]+content="([^"]*)"', t)
            nm = re.findall(r'NO\.\s*04\.\s*\d+[^<"]{0,80}', t)[:5]
            soldout = re.findall(r'품절|판매중지|일시품절', t)[:5]
            print('MALL', code, s, url, '| title:', title.group(1).strip()[:200] if title else None, '| og:', og[:2], '| NO:', nm, '| soldout:', soldout)
        except Exception as e:
            print('MALL', code, 'ERR', url, e)
