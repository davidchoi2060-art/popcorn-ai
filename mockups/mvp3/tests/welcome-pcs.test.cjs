'use strict';
// 첫 화면 「새로 구성된 PC」(welcome-pcs.js · 2026-10-16 단일 첫 화면 · 같은 날 「새로 나온 PC」에서 이름 변경). jsdom 없이 돈다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const SRC=fs.readFileSync(path.join(__dirname,'..','welcome-pcs.js'),'utf8');
async function load(respond){
  const events=[],calls=[];
  const window={dispatchEvent:e=>events.push(e.type)};
  const ctx={window,Event:class{constructor(type){this.type=type;}},encodeURIComponent,
    fetch:async(url,opts)=>{calls.push([url,opts]);const r=await respond(url);return {ok:r.ok!==false,json:async()=>r.data};}};
  vm.runInNewContext(SRC,ctx);
  for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));
  return {html:window.MVP3WelcomePcs.html,context:window.MVP3WelcomePcs.context,events,calls};
}
const pc=(id,extra={})=>({configuration_id:id,title:'맞춘 PC '+id,intro:'소개 '+id,price:1234000,...extra});
test('lists published curated PCs with server price and a link to their detail, escaping text',async()=>{
  const w=await load(()=>({data:{ok:true,items:[pc('c1'),pc('a b',{title:'<b>PC</b>',intro:'',price:null})]}}));
  assert.deepEqual(w.calls.map(c=>c[0]),['/api/mvp3/custom-pcs']);assert.equal(w.calls[0][1].credentials,'same-origin');
  assert.deepEqual(w.events,['mvp3:welcome-pcs']);
  const html=w.html();
  assert.match(html,/<h2 id="welcome-pcs-title" tabindex="-1">새로 구성된 PC<\/h2><p>팝콘PC가 용도에 맞춰 부품을 직접 골라 구성했어요.<\/p>/);
  assert.doesNotMatch(html,/새로 나온 PC|맞춰 둔 PC/);
  assert.match(html,/<h3>맞춘 PC c1<\/h3><p class="welcome-pc-blurb">소개 c1<\/p><b>1,234,000원<\/b>/);
  assert.match(html,/href="new-pcs.html#c1">구성 보기/);
  assert.match(html,/<h3>&lt;b&gt;PC&lt;\/b&gt;<\/h3><b>금액 확인 중<\/b>/,'no made-up price, no empty intro');
  assert.match(html,/href="new-pcs.html#a%20b">구성 보기/);
  assert.match(html,/전체 보기/,'the approved first screen always offers the full list');
  assert.doesNotMatch(html,/<figure|src="(?!assets\/icons\/)/,'no invented product image or placeholder');
});
test('shows server-judged usages in order and only provided key parts and quantities',async()=>{
  const usages=[{usage:'게임',level:'QHD'},{usage:'영상편집',level:'쾌적'},{usage:'사무용',level:'쾌적'},{usage:'개발',level:'기본'}];
  const parts=[{slot:'CPU',slot_label:'CPU',name:'라이젠5 7500F'},{slot:'GPU',slot_label:'그래픽카드',name:'RTX 5070'},{slot:'RAM',slot_label:'메모리',name:'DDR5 16GB',quantity:2},{slot:'CASE',slot_label:'케이스',name:'본체'}];
  const w=await load(()=>({data:{items:[pc('u1',{usages,parts,intro:'운영자가 부품을 선택한 신규 구성입니다.',scene:''})]}}));
  const html=w.html();
  assert.match(html,/<span class="welcome-pc-usages" aria-label="맞춘 용도"><em>게임 QHD<\/em><em>영상편집 쾌적<\/em><em>사무용 쾌적<\/em><\/span><h3>/);
  assert.doesNotMatch(html,/개발 기본|운영자가 부품을 선택한|본체/);
  assert.match(html,/<dt>CPU<\/dt><dd>라이젠5 7500F<\/dd><\/div><div><dt>그래픽카드<\/dt><dd>RTX 5070<\/dd>/);
  assert.match(html,/<dt>메모리<\/dt><dd>DDR5 16GB × 2<\/dd>/);
  const v=await load(()=>({data:{items:[pc('u2',{scene:'퇴근 후 QHD 게임'})]}}));
  assert.match(v.html(),/<p class="welcome-pc-blurb">퇴근 후 QHD 게임<\/p>/,'scene goes first');
  assert.doesNotMatch(v.html(),/welcome-pc-usages|welcome-pc-parts/,'nothing judged, nothing shown');
});
test('one, two and seven items retain API order, cap home at three, and show zero as a real price',async()=>{
  for(const count of [1,2,7]){
    const w=await load(()=>({data:{items:Array.from({length:count},(_,i)=>pc('c'+i,{price:0}))}}));
    const html=w.html();assert.equal((html.match(/class="welcome-pc"/g)||[]).length,Math.min(count,3));
    assert.match(html,/class="welcome-pcs-all" href="new-pcs.html">전체 보기/);
    assert.equal(html.includes('<ul class="one-item">'),count===1);
    assert.ok(html.indexOf('new-pcs.html#c0')<html.indexOf('new-pcs.html#c1')||count===1);
    assert.doesNotMatch(html,/new-pcs.html#c3/);assert.match(html,/<b>0원<\/b>/);
  }
});
test('no section and no redraw when nothing is published, the server fails, or the network throws',async()=>{
  for(const respond of [()=>({data:{ok:true,items:[]}}),()=>({ok:false,data:{}}),()=>{throw Error('down');},()=>({data:{items:[{title:'번호 없음'}]}})]){
    const w=await load(respond);assert.equal(w.html(),'');assert.deepEqual(w.events,[]);assert.equal(w.context().length,0);
  }
});

test('the consultation context contains only the displayed first three public configuration IDs in order',async()=>{
  const w=await load(()=>({data:{items:Array.from({length:7},(_,i)=>pc('configuration-'+i,{title:'PRIVATE_TITLE',price:999999,parts:[{name:'PRIVATE_PART'}]}))}}));
  const expected=[{configuration_id:'configuration-0'},{configuration_id:'configuration-1'},{configuration_id:'configuration-2'}];
  const context=w.context();assert.deepEqual(JSON.parse(JSON.stringify(context)),expected);
  assert.doesNotMatch(JSON.stringify(context),/PRIVATE_TITLE|PRIVATE_PART|999999|configuration-3/);
  context[0].configuration_id='mutated';context.push({configuration_id:'not-shown'});
  assert.deepEqual(JSON.parse(JSON.stringify(w.context())),expected,'caller mutations cannot change actual home cards');
});
