import json, re, urllib.request
B='https://popcornai.co.kr'
items=json.load(urllib.request.urlopen(B+'/api/customer/pc-catalog',timeout=60))['items']
for it in items:
    if it.get('configuration_public'): continue
    c=it['product_code']
    try: parts=json.load(urllib.request.urlopen(B+f'/api/customer/pc-registered/{c}',timeout=60))['parts']
    except Exception: continue
    if any('M60' in (p['name'] or '') and not p['photo'] for p in parts):
        html=urllib.request.urlopen(urllib.request.Request(f'https://www.popcornpc.co.kr/shop/system_detail.html?pd_no={c}',headers={'User-Agent':'Mozilla/5.0'}),timeout=20).read().decode('euc-kr','replace')
        out=[]
        for m in re.finditer(r'M60', html):
            out.append(re.sub(r'\s+',' ',html[max(0,m.start()-700):m.start()+200]))
        print(c); print('\n----\n'.join(out[:4])); break
