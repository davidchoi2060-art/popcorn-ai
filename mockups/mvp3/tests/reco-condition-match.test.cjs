'use strict';
// 조건과 추천 PC 불일치 -- 2026-10-12 코덱스 24조합 검수 v2 (요청자 중헌 님). jsdom 없이 실제 app.js 선언을 실행한다.
//  1번 상세 대표 소개: 영상편집 상담에서 「게임 화면의 화질과 움직임」이 대표 문장으로 나왔다
//  4번 부품 구성표 없는 상품: 상세에 완제품 한 줄만 나와 카드 사양(CPU·GPU·케이스·파워)이 보이지 않았다
//  6번 가격 확인 중 부품: 어느 부품이 빠졌는지·PC 금액에 포함인지 몰랐고, 수량 2 줄 금액이 단가인지 합계인지 몰랐다
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const M=require('../live-model.js');
const APP=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx=(extra)=>({M,esc,
  uiIcon:(name,cls='')=>'<img class="ui-icon '+cls+'" src="assets/icons/'+name+'.svg" alt="">',
  button:(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>',
  money:v=>Number.isInteger(v)?v.toLocaleString('ko-KR')+'원':'금액 미확인',...extra});
function slice(from,to){const a=APP.indexOf(from),b=APP.indexOf(to);assert.ok(a>=0&&b>a,from);return APP.slice(a,b);}
function configuration(parts,description){return {product_code:98149,configuration_id:'P10',revision:1,offer_id:'P98149',
  description:description||{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},parts,
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
const part=(ordinal,slot,price,quantity=1)=>({ordinal,slot,quantity,pseudo:false,name:slot+' 부품',description:'역할',specs:[],price});
function details(product,usages=['게임']){
  const p=M.product(product);
  return vm.runInNewContext(slice('function publicBomDetails(','function finalConditions(')+'\nproductDetails(false)',
    ctx({state:{selected:p,selectedContext:null,selectionState:{usages},talk:{}}}));
}
const SPEC={cpu:'라이젠5 8600G',gpu:'Radeon 760M(내장)',ram_gb:16,ssd_gb:500,case:'[DARKFLASH] DMO11 블랙',psu:'[마이크로닉스] COOLMAX VISION II 500W'};

test('6번: 수량 2 줄은 줄 합계와 「단가 × 수량」을 함께 적는다',()=>{
  const c=configuration([part(0,'CPU',186400),part(2,'RAM',159500,2)]);
  const html=details({product_code:98149,name:'[14400F/32G/1TB/RTX5060Ti]',price:1871100,spec:{cpu:'i5-14400F'},reasons:['게임 FHD'],public_configuration:c});
  assert.match(html,/class="final-part-price">319,000원<small class="muted foot-note">159,500원 × 2개<\/small>/);
  assert.match(html,/class="final-part-price">186,400원<\/span>/);   // 수량 1 은 그대로
});

test('6번: 가격 확인 중 부품이 있으면 어느 부품인지와 PC 금액에 포함이라는 것을 말한다',()=>{
  const c=configuration([part(0,'CPU',159500),part(1,'GPU',null),part(2,'RAM',null),part(3,'POWER',42600)]);
  const html=details({product_code:98149,name:'[12400F/16GB/500GB/RTX5060]',price:1624400,spec:{cpu:'i5-12400F'},reasons:['게임 FHD'],public_configuration:c});
  assert.match(html,/가격 확인 중인 부품이 있어 계산하지 않았어요<small class="muted foot-note">가격 확인 중: 그래픽카드·메모리 · PC 금액에는 이 부품들이 포함돼 있어요<\/small>/);
  assert.doesNotMatch(html,/<th scope="row">조립·기타<\/th><td class="final-part-price">[0-9,]+원/);   // 차액을 조립비처럼 내지 않는다
});

test('4번: 부품 구성표가 없는 상품도 상세에 카드와 같은 사양(케이스·파워 포함)을 보인다',()=>{
  const html=details({product_code:120221,name:'오피스 초슬림/미니타워[8600G/16G/500G/Radeon 7]',price:1195100,spec:SPEC,reasons:['사무용 쾌적 — 대용량 엑셀'],public_configuration:null},['사무·인강']);
  assert.match(html,/부품 구성 정보는 아직 연결되지 않았어요\./);
  assert.match(html,/<dl class="live-spec-grid" data-card-spec>/);
  for(const [label,value] of [['CPU','라이젠5 8600G'],['GPU','Radeon 760M\\(내장\\)'],['케이스','\\[DARKFLASH\\] DMO11 블랙'],['파워','\\[마이크로닉스\\] COOLMAX VISION II 500W']])
    assert.match(html,new RegExp('<dt>'+label+'</dt><dd>'+value+'</dd>'));
});

test('1번: 게임이 아닌 상담에서는 게임 중심 공개 소개를 대표 문장으로 쓰지 않는다',()=>{
  const fn=slice('function summaryDescription(','function productSummary(');
  const game={title:'게임 화면의 화질과 움직임을 함께 고민한다면',intro:'높은 화질이나 프레임을 목표로'};
  const office={title:'오래 켜 두는 업무용 PC',intro:'문서와 화상회의'};
  const run=(d,usages)=>vm.runInNewContext(fn+'\nsummaryDescription({public_configuration:{description:d}})',{d,state:{selectionState:{usages},talk:{}}});
  assert.equal(run(game,['영상편집']),null);
  assert.equal(run(game,['사무·인강']),null);
  assert.deepEqual(run(game,['고사양 게임']),game);
  assert.deepEqual(run(office,['영상편집']),office);
  assert.equal(vm.runInNewContext(fn+'\nsummaryDescription({public_configuration:null})',{state:{talk:{}}}),null);
});
