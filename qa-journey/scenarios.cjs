// 테스트시나리오-v2.md 와 같은 번호. kind: game|heavy|edit|office|none(판정용)
const FOLLOW=['FHD 144Hz 모니터 써요.','그냥 알아서 추천해 주세요.','네, 그 조건으로 보여 주세요.'];
const S={};
const add=(id,o)=>S[id]=Object.assign({entry:'chat',depth:'detail',follow:true},o);
// A 입구별 끝까지
add('A1',{kind:'heavy',budget:150,depth:'full',text:'배그랑 롤 해요. 고사양 게임도 하고 가끔 문서 작업도 해요. 예산은 150만원이에요.',changePart:true,roundtrip:2,talkSave:true,mobile:true});
add('A2',{kind:'game',budget:150,depth:'full',entry:'chip',usage:'game',budgetSel:'150',mobile:true});
add('A3',{kind:'game',budget:120,depth:'full',entry:'card:new_pc',text:'발로란트랑 오버워치2 해요. 120만원이요.',changePart:true,mobile:true});
add('A4',{kind:'none',budget:60,depth:'full',entry:'card:upgrade',text:'지금 i5-8400, GTX 1060, 램 16GB예요. 60만원 안에서 업그레이드할까요 새로 살까요?',mobile:true});
add('A5',{kind:'none',budget:null,depth:'full',entry:'card:parts',text:'RTX 5060이랑 5060 Ti 차이가 뭐예요?',follow:false,mobile:true});
add('A6',{kind:'office',budget:80,depth:'full',entry:'talk',text:'사무실 직원용, 엑셀이랑 문서만 해요. 한 대 80만원 이하요.',changePart:true,mobile:true});
// B 24조합
const T={game:'배그랑 롤, 발로란트 해요. 예산은 X만원이에요.',heavy:'배그랑 롤을 고사양 옵션으로 하고 싶어요. 예산은 X만원이에요.',edit:'프리미어로 4K 컷 편집하고 자막 넣어요. 예산은 X만원이에요.',office:'문서 작업, 큰 엑셀, 웹, 화상회의용이에요. 예산은 X만원이에요.'};
let i=0;for(const k of ['game','heavy','edit','office'])for(const b of [60,80,100,150,200,300]){i++;const id='B'+String(i).padStart(2,'0');add(id,{kind:k,budget:b,text:T[k].replace('X',b),mobile:id==='B04'||id==='B22'});}
add('B25',{kind:'heavy',budget:200,text:'배틀그라운드 QHD 144Hz로 하고 싶어요. 예산 200만원.'});
add('B26',{kind:'heavy',budget:400,text:'최신 고사양 게임을 4K로 하고 싶어요. 예산 400만원.'});
add('B27',{kind:'game',budget:120,text:'120만원으로 롤, 오버워치2, 로스트아크 할 건데 구성 좀 짜줘'});
add('B28',{kind:'edit',budget:200,text:'영상 편집용 PC 200만원으로 추천해주세요'});
add('B29',{kind:'edit',budget:null,text:'포토샵이랑 일러스트 작업용으로 컴퓨터 추천해 주세요'});
add('B30',{kind:'office',budget:50,text:'사무용 컴퓨터 50만원 정도로 맞출 수 있어요?'});
add('B31',{kind:'game',budget:null,text:'초등학생 아이 공부용이랑 마인크래프트용 컴퓨터요'});
// C 예외
add('C1',{kind:'none',depth:'cards',follow:false,expectNoCards:true,text:'램 16GB랑 32GB 차이만 설명해 주세요. 아직 PC 추천은 필요 없어요.'});
add('C2',{kind:'none',depth:'cards',text:'150만원 게임 PC랑 100만원 사무 PC 두 대요'});
add('C3',{kind:'none',depth:'cards',follow:false,text:'10만원으로 모든 게임 4K 최고옵션'});
add('C4',{kind:'game',budget:150,depth:'cards',text:'gaming pc under 150만원 please'});
add('C5',{kind:'game',budget:150,depth:'cards',follow:false,text:'배그 150만원 PC 추천해줘',then:['배그 150만원 PC 추천해줘','배그 150만원 PC 추천해줘']});
add('C6',{kind:'game',budget:150,depth:'cards',text:'배그PC 추천하고 배송일과 환불도 알려줘'});
// E 이상한 패턴
add('E01',{kind:'heavy',budget:150,depth:'cards',text:'사무용인데 사이버펑크도 최고 옵션으로 돌리고 싶어요. 150만원.'});
add('E02',{kind:'none',depth:'cards',follow:false,text:'4K 최고 옵션 게임 PC 50만원으로요.'});
add('E03',{kind:'none',depth:'cards',follow:false,text:'무소음인데 가장 작은 케이스에 제일 센 그래픽카드요.'});
add('E04',{kind:'none',depth:'cards',follow:false,text:'게임용 PC 1만원이요.'});
add('E05',{kind:'heavy',depth:'cards',text:'게임용 PC 예산 1억이에요.'});
add('E06',{kind:'game',budget:150,depth:'cards',text:'배그 150'});
add('E07a',{kind:'game',budget:150,depth:'cards',text:'배그용 백오십만원'});
add('E07b',{kind:'game',budget:150,depth:'cards',text:'배그용 1,500,000원'});
add('E07c',{kind:'game',budget:150,depth:'cards',text:'배그용 150만 원 이하'});
add('E08',{kind:'game',budget:200,depth:'cards',text:'100~200만원 사이 게임 PC'});
add('E09',{kind:'game',budget:150,depth:'cards',text:'ㅂㄱ ㄹ 하는 컴 150'});
add('E10',{kind:'game',budget:100,depth:'cards',text:'발로 옵치 롤 겜컴 ㄱㄱ 백만'});
add('E11',{kind:'game',budget:100,depth:'cards',text:'배그돌아가느컴츄터 백만원'});
add('E12',{kind:'heavy',budget:250,depth:'detail',entry:'chip',usage:'office',budgetSel:'100',text:'배그 고사양으로 250만원'});
add('E13',{kind:'edit',budget:300,depth:'cards',text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',then:['아 사실 영상 편집용이에요. 예산 300만원.']});
add('E14',{kind:'game',budget:150,depth:'cards',text:'배그 150만원 PC 추천해줘',then:['더 싸게','아니 더 좋게','처음 거로']});
add('E15',{kind:'game',budget:150,depth:'detail',text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',op:'backforward'});
add('E16',{kind:'game',budget:150,depth:'full',text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',op:'reload'});
add('E17',{kind:'game',budget:150,depth:'cards',text:'배그 150만원 PC 추천해줘',op:'sendspam',follow:false});
add('E18',{kind:'game',budget:150,depth:'full',text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',op:'buttonspam'});
add('E19',{kind:'game',budget:150,depth:'full',text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',op:'rotate',mobileOnly:true});
add('E20',{kind:'game',budget:150,depth:'cards',text:'배그 150만원 PC 추천해줘',op:'twotabs'});
add('E21',{kind:'game',budget:150,depth:'cards',text:'배그 150만원 PC 추천해줘',op:'offline',follow:false});
add('E22a',{kind:'game',budget:150,depth:'cards',text:'gaming pc under 150만원 please'});
add('E22b',{kind:'game',depth:'cards',text:'げーむ用PCありますか'});
add('E22c',{kind:'edit',depth:'cards',text:'视频剪辑电脑推荐'});
add('E23a',{kind:'none',depth:'cards',follow:false,expectNoCards:true,text:'너 바보야?'});
add('E23b',{kind:'none',depth:'cards',follow:false,expectNoCards:true,text:'오늘 저녁 뭐 먹지?'});
add('E23c',{kind:'none',depth:'cards',follow:false,expectNoCards:true,text:'추천 완전 별로네 짜증나'});
add('E24a',{kind:'game',budget:150,depth:'cards',longText:3000,text:'예산은 150만원이에요. 어떤 PC가 좋을까요?'});
add('E24b',{kind:'game',budget:150,depth:'cards',longText:19000,text:'예산은 150만원이에요. 어떤 PC가 좋을까요?'});
add('E25',{kind:'none',depth:'cards',op:'junk',follow:false,expectNoCards:true,text:''});
add('E26',{kind:'game',budget:150,depth:'cards',follow:false,text:'<b>배그</b> 150만원 <script>alert(1)</script>'});
add('E27',{kind:'none',depth:'cards',follow:false,text:'제 카드번호 1234-5678-9012-3456이에요, 전화 010-1234-5678'});
add('E28',{kind:'game',budget:150,depth:'cards',follow:false,text:'배그 150만원 PC 추천해줘',then:['배그 150만원 PC 추천해줘','배그 150만원 PC 추천해줘']});
// D 화면 자체 (AI 없음, A1 결과 화면을 쓰는 D2는 A1 안에서)
add('D1',{op:'addresses',depth:'none'});
add('D3',{kind:'game',budget:150,depth:'full',text:'배그 150만원 PC 추천해줘',op:'navmenu'});
module.exports={S,FOLLOW};
