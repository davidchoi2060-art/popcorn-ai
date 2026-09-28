"""Export the actual DB drafts for a local-only review using the shared renderer."""
import argparse
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.part_explanations import list_explanations

def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);a=parser.parse_args()
    root=Path(__file__).resolve().parents[1];a.output.mkdir(parents=True,exist_ok=True)
    rows=[];offset=0
    while True:
        result=list_explanations(q='',slot='',offset=offset,limit=50);rows+=result['items']
        offset+=len(result['items'])
        if offset>=result['total']:break
    for name in ['part-explanations.js','part-explanations.css','assembly-fee.js']:
        shutil.copyfile(root/'mockups/shared'/name,a.output/name)
    shutil.copyfile(root/'design-system/tokens.css',a.output/'tokens.css')
    data=json.dumps(rows,ensure_ascii=False,default=str).replace('<','\\u003c')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>팝콘AI 부품 상세 검토</title><link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="part-explanations.css"><style>*{box-sizing:border-box}body{margin:0;background:var(--card);font-family:var(--font);color:var(--on)}header{padding:1.2rem 2rem;border-bottom:1px solid var(--outline-variant);color:var(--primary);font-size:1.4rem;font-weight:700}main{max-width:1200px;margin:auto;padding:1.5rem}h1{font-size:1.8rem}form,nav{display:flex;gap:1rem;flex-wrap:wrap;align-items:center;margin:1rem 0}input,select,button{font:inherit;padding:.6rem;border:1px solid var(--outline-variant);border-radius:.5rem;background:var(--card);color:var(--on)}#count,.note{color:var(--on-variant);font-size:.9rem}button{cursor:pointer}button:disabled{opacity:.45}a{color:var(--primary)}@media(max-width:600px){main{padding:1rem}input{max-width:100%}}</style><header>팝콘AI <small>부품 상세 검토</small></header><main><h1>부품 구성과 상세 설명</h1><p class="note">판매처에 등록된 제품별 사양과 이미지를 기준으로 정리했습니다.</p><p class="note" data-assembly-fee-note="short"></p><form id="search"><label>상품명·코드 <input id="q" placeholder="예: 14100F, PM9A1"></label><label>종류 <select id="slot"><option value="">전체</option><option>CPU</option><option>GPU</option><option>RAM</option><option>SSD</option><option>MB</option><option>POWER</option><option>CASE</option><option>COOLER</option></select></label><button>검색</button></form><p id="count" role="status"></p><div id="parts"></div><nav><button id="prev">이전</button><button id="next">다음</button></nav></main><script src="assembly-fee.js"></script><script src="part-explanations.js"></script><script>const DATA=__DATA__;let offset=0;const $=id=>document.getElementById(id);function draw(){const q=$('q').value.toLowerCase(),slot=$('slot').value;const hits=DATA.filter(p=>(!slot||p.slot===slot)&&(p.name.toLowerCase().includes(q)||String(p.product_code).includes(q)));const rows=hits.slice(offset,offset+10);$('parts').innerHTML=rows.map((p,i)=>PopcornPartExplanations.markup(p,{review:true,open:i===0})).join('')||'<p>일치하는 부품이 없습니다.</p>';PopcornPartExplanations.attach($('parts'),rows);$('count').textContent='전체 '+hits.length+'개 중 '+(hits.length?offset+1:0)+'–'+Math.min(offset+10,hits.length)+'개';$('prev').disabled=!offset;$('next').disabled=offset+10>=hits.length;} $('search').onsubmit=e=>{e.preventDefault();offset=0;draw();};$('prev').onclick=()=>{offset=Math.max(0,offset-10);draw();};$('next').onclick=()=>{offset+=10;draw();};draw();</script></html>'''
    (a.output/'index.html').write_text(page.replace('__DATA__',data),encoding='utf-8')
    (a.output/'부품설명-201종.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    report=['# 부품 설명 초안','', '각 항목은 검토 초안입니다. 판매처 원문과 제조사 대조 결과를 구분하며 실제 성능·호환·출고 승인을 뜻하지 않습니다.','']
    for p in rows:
        report += [f"## {p['product_code']} · {p['name']}",'',p['role'],'','| 항목 | 내용 | 근거 상태 |','|---|---|---|']
        report += [f"| {f['label']} | {f['value'].replace('|','/')} | {f['verification']} |" for f in p['facts']]
        report += ['', '확인사항: '+' '.join(p['cautions']), '', '확인사항: '+' / '.join(p['review_issues']), '']
        report += [f"- [{s['title']}]({s['url']})" for s in p['sources']]
        report += ['']
    (a.output/'부품설명-201종.md').write_text('\n'.join(report),encoding='utf-8')
    print('Exported DB drafts:',len(rows))

if __name__=='__main__':main()
