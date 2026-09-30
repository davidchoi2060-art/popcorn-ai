"""Build review drafts from an explicit audit directory. No DB writes or LLM calls."""
import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.product_name import remove_discount_label
from api.ram_bundle import ram_bundle, bundle_facts

ROLES = {
 'CPU':('프로그램의 명령과 연산을 처리하는 중심 부품입니다.','사용할 프로그램과 동시 작업량, 메인보드의 CPU 지원 목록과 BIOS를 함께 확인하세요.'),
 'GPU':('게임 화면과 그래픽 연산을 처리합니다. GPU 가속을 지원하는 작업에도 사용됩니다.','메모리 용량만으로 성능을 판단하지 않습니다. GPU 모델, 해상도, 프로그램 지원, 파워 커넥터와 케이스 여유를 함께 확인하세요.'),
 'RAM':('실행 중인 프로그램의 데이터를 임시로 보관합니다.','DDR 규격과 메인보드 지원을 확인하세요. 상품 1개의 용량·모듈 수와 PC 전체 장착 용량은 다릅니다.'),
 'SSD':('운영체제·프로그램·파일을 저장하고 불러오는 장치입니다.','저장 용량, M.2 또는 SATA 연결 방식과 메인보드 지원을 확인하세요. 표기 최고 속도가 실제 작업에서 항상 유지되는 것은 아닙니다.'),
 'MB':('CPU·메모리·저장장치와 주변기기를 연결하는 기반입니다.','CPU 소켓만 같다고 모두 지원하지 않습니다. 정확한 보드 리비전과 BIOS, 메모리 규격, 저장장치 슬롯을 확인하세요.'),
 'POWER':('컴퓨터의 각 부품에 필요한 전력을 공급합니다.','정격 출력, GPU 권장 전력과 전원 커넥터를 함께 확인하세요. 효율 인증만으로 소음이나 전체 품질을 보장할 수는 없습니다.'),
 'CASE':('부품을 고정하고 냉각 공기가 흐를 공간을 제공합니다.','메인보드 크기, GPU 길이, 쿨러 높이와 라디에이터 간섭을 확인하세요. 지원 최대 길이는 다른 부품 설치에 따라 줄어들 수 있습니다.'),
 'COOLER':('CPU에서 발생한 열을 방열판과 팬 또는 냉각수로 내보냅니다.','CPU 소켓용 장착 부속과 케이스 여유를 확인하세요. 표기 TDP만으로 모든 CPU의 온도나 소음을 보장하지 않습니다.')}
PATTERNS = {
 'CPU':[('모델',r'(?:코어i[3579]-[\w]+|울트라[579] 시리즈\d+ [\w]+|라이젠[^/]+)'),('코어 구성',r'코어 갯수\s*:\s*([^/]+)'),('스레드',r'쓰레드\s*:\s*([^/]+)'),('소켓',r'\b(?:LGA\d+|AM[45])\b'),('기본 클럭',r'동작 클럭\s*:\s*([^/]+)'),('최대 클럭',r'터보 클럭\s*:\s*([^/]+)'),('내장그래픽',r'내장그래픽\s*:\s*([^/]+)')],
 'GPU':[('GPU 모델',r'\b(?:RTX|GTX|RX)\s*\d+[^/]*'),('그래픽 메모리',r'메모리용량\s*:\s*([^/]+)'),('메모리 규격',r'GDDR\d+X?'),('카드 길이',r'길이\s*:\s*([^/]+)'),('권장 파워',r'정격\s*[\d,]+\(W\)\s*이상'),('팬 개수',r'팬쿨러 개수\s*:\s*([^/]+)'),('모니터 수',r'모니터지원수\s*:\s*([^/]+)')],
 'RAM':[('메모리 규격',r'\bDDR[345]\b'),('상품 용량',r'(?:^|/)\s*(?:용량\s*:\s*)?(\d+(?:\.\d+)?\s*\(?GB\)?)\s*(?=/|$)'),('표기 속도',r'[\d,]+\(MHz\),PC[^/]+'),('패키지 구성',r'패키지 구성\s*:\s*([^/]+)'),('전압',r'전압\s*:\s*([^/]+)'),('타이밍',r'CL\d+[^/]*')],
 'SSD':[('용량',r'(?:^|/)\s*(?:용량\s*:\s*)?(\d+(?:\.\d+)?\s*\(?(?:GB|TB)\)?)\s*(?=/|$)'),('연결 형태',r'M\.2\([^)]*\)|SATA[^/]*'),('M.2 크기',r'M\.2사이즈\s*:\s*([^/]+)'),('플래시 종류',r'메모리타입\s*:\s*([^/]+)'),('최대 읽기',r'읽기속도\s*:\s*([\d,]+\s*\(MB/s\))'),('최대 쓰기',r'쓰기속도\s*:\s*([\d,]+\s*\(MB/s\))')],
 'MB':[('CPU 소켓',r'\b(?:LGA\d+|AM[45])\b'),('메모리 규격',r'\bDDR[345]\b'),('보드 크기',r'(?:m-ATX|M-ATX|ATX|Mini-ITX|ITX)'),('메모리 슬롯',r'(?<!PCI)슬롯\s*:\s*([^/]+)'),('최대 메모리',r'최대\s*[\d,]+\(GB\)'),('M.2 슬롯',r'M\.2\s*:\s*([^/]+)'),('유선 네트워크',r'(?:[\d.]+기가비트|기가비트)')],
 'POWER':[('정격 출력',r'(?:^|/)\s*(\d+\(W\))'),('파워 규격',r'\b(?:ATX|SFX|TFX)\b'),('효율 표기',r'80PLUS\s*:\s*([^/]+)'),('팬 크기',r'팬크기\s*:\s*([^/]+)'),('보증 표기',r'무상\s*\d+\(년\)'),('SATA 전원',r'SATA\s*:\s*([^/]+)')],
 'CASE':[('형태',r'(?:미들타워|미니타워|빅타워|슬림|미니ITX)'),('지원 파워',r'지원 파워\s*:\s*([^/]+)'),('쿨러 높이',r'CPU쿨러장착높이\s*:\s*([^/]+)'),('GPU 장착 길이',r'VGA장착길이\s*:\s*([^/]+)'),('수랭 지원',r'수랭쿨러 지원\s*:\s*([^/]+)'),('팬 구성 표기',r'장착 팬 개수\s*:\s*([^/]+)'),('크기',r'너비\s*:\s*[^/]+/\s*높이\s*:\s*[^/]+/\s*깊이\s*:\s*[^/]+')],
 'COOLER':[('냉각 방식',r'공랭|수랭'),('높이',r'높이\s*:\s*([^/]+)'),('라디에이터',r'라디에이터[^/]*'),('히트파이프',r'히트파이프\s*:\s*([^/]+)'),('팬 최대 회전수',r'최대 팬속도\s*:\s*([^/]+)'),('보증 표기',r'A/S기간\s*:\s*([^/]+)')]}

def clean(value):
    return html.unescape(re.sub('<[^>]*>','',value or '')).strip()

def extract(slot, spec):
    facts=[]
    for label,pattern in PATTERNS[slot]:
        m=re.search(pattern,spec,re.I)
        if m:
            facts.append(dict(label=label,value=(m[1] if m.lastindex else m[0]).strip(),source_id='merchant',verification='판매처 원문'))
    return facts

def build(directory):
    read=lambda n:json.loads((directory/n).read_text(encoding='utf-8-sig'))
    data=read('current-catalog-after-import.json'); admin=read('admin-selling-latest.json')
    raw={str(r['자체상품코드']):r for r in admin['rows']}
    items={i['code']:i for c in data['catalog'] for i in c['items'] if not i['pseudo']}
    output=[]
    for code,item in sorted(items.items()):
        row=raw[code]; name=remove_discount_label(clean(row['상품명'])); spec=row.get('스펙') or ''; slot=item['slot']
        facts=extract(slot,spec);role,caution=ROLES[slot]
        source_url=f'https://www.popcornpc.co.kr/shop/product_detail.html?pd_no={code}'
        sources=[dict(id='merchant',kind='merchant',title='팝콘PC 관리자 상품 사양',url=source_url,observed_at=admin['observed_at'])]
        issues=[];image_url=None
        if not facts:
            facts=[dict(label='등록 상품명',value=name,source_id='merchant',verification='사양 보완 필요')]
            issues.append('구조화 가능한 사양 원문 부족')
        local=directory/'raw'/f'part_{code}.html'
        if local.exists():
            image=re.search(r'<img\b[^>]*id=[\"\x27]viewimg[\"\x27][^>]*>',local.read_text(encoding='utf-8'))
            if image:
                match=re.search(r'src=[\"\x27]([^\"\x27]+)',image[0])
                if match:image_url=urljoin(source_url,html.unescape(match[1]))
        if not image_url:issues.append('해당 상품 대표 이미지 미확인')
        if code in ('127201','127203'):issues.append('조립 전용 부품: 상품 DB 연결 대기')
        if slot=='RAM' and ram_bundle(name):
            facts=[f for f in facts if f['label'] not in ('상품 용량','패키지 구성','모듈당 용량')
                   and not (f['label']=='타이밍' and re.search(r'GB',f['value'],re.I))]
            facts=bundle_facts(name)+facts
        if code=='110899':
            sources.append(dict(id='samsung',kind='manufacturer',title='Samsung PM9A1 용량별 사양표',url='https://download.semiconductor.samsung.com/resources/brochure/Product%20Overviews%20PM9A1%20SSD%20Storage%20for%20the%20Next-Generation%20PC.pdf',observed_at='2026-09-28'))
            for f in facts:
                if f['label'] in ('최대 읽기','최대 쓰기'):
                    f.update(value={'최대 읽기':'6,400 MB/s','최대 쓰기':'2,700 MB/s'}[f['label']],source_id='samsung',verification='제조사 256GB 표 대조')
            issues.append('판매처 속도는 다른 용량 값과 혼재. 제조사 256GB 표로 설명 초안 정정, 실물 P/N 확인 필요')
        if code=='113685':
            sources.append(dict(id='gigabyte',kind='manufacturer',title='H610M H V2 DDR4 rev.1.0 사양',url='https://www.gigabyte.com/pk/Motherboard/H610M-H-V2-DDR4-rev-10/sp',observed_at='2026-09-28'))
            facts.append(dict(label='영상 출력 (rev.1.0)',value='HDMI·D-Sub, CPU 내장그래픽 필요',source_id='gigabyte',verification='리비전 확인 필요'))
            issues.append('판매처 원문의 DVI 표기와 제조사 rev.1.0 출력 목록 차이. 출고 리비전 확인 필요')
        if slot=='CPU' and '내장그래픽 : 없음' in spec:
            caution+=' 이 CPU는 별도 그래픽카드가 필요합니다.'
        if slot=='RAM' and '패키지' in name:
            caution+=' 패키지 1세트의 모듈 개수와 PC 장착 세트 수를 따로 계산합니다.'
        summary=' · '.join(f"{f['label']} {f['value']}" for f in facts[:3]) or name
        highlights=[f"{f['label']}: {f['value']}" for f in facts[:3]]
        snapshot=dict(name=row['상품명'],spec=spec)
        fp=hashlib.sha256(json.dumps([row['상품명'] or '',spec],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        content=dict(name=name,slot=slot,summary=summary,role=role,facts=facts,highlights=highlights,
            cautions=[caution],image_url=image_url,image_caption='판매처 등록 이미지' if image_url else '제품 이미지 미확인',
            image_source_url=source_url,sources=sources,review_issues=issues,
            questions=[dict(question='이 부품은 어떤 역할을 하나요?',answer=role),dict(question='선택할 때 무엇을 확인하나요?',answer=caution)],
            usage_note='전체 PC의 용도 적합성과 선택 이유는 고객 조건 및 전체 구성 평가 후 제공')
        output.append(dict(code=int(code),snapshot=snapshot,fingerprint=fp,content=content))
    assert len(output)==201 and all(x['content']['facts'] for x in output)
    return dict(source_observed_at=admin['observed_at'],status='draft',items=output)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('audit_directory',type=Path);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=build(args.audit_directory);args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(items=len(result['items']),images=sum(bool(x['content']['image_url']) for x in result['items'])),ensure_ascii=False))
