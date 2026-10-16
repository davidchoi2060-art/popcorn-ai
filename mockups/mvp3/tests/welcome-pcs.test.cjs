'use strict';
// 첫 화면 아래 「팝콘PC가 맞춰 둔 PC」(welcome-pcs.js · 2026-10-16 단일 첫 화면). jsdom 없이 돈다.
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
  return {html:window.MVP3WelcomePcs.html,events,calls};
}
const pc=(id,extra={})=>({configuration_id:id,title:'맞춘 PC '+id,intro:'소개 '+id,price:1234000,...extra});
test('lists published curated PCs with server price and a link to their detail, escaping text',async()=>{
  const w=await load(()=>({data:{ok:true,items:[pc('c1'),pc('a b',{title:'<b>PC</b>',intro:'',price:null})]}}));
  assert.deepEqual(w.calls.map(c=>c[0]),['/api/mvp3/custom-pcs']);assert.equal(w.calls[0][1].credentials,'same-origin');
  assert.deepEqual(w.events,['mvp3:welcome-pcs']);
  const html=w.html();
  assert.match(html,/팝콘PC가 맞춰 둔 PC/);
  assert.match(html,/href="new-pcs.html#c1"><strong>맞춘 PC c1<\/strong><span>소개 c1<\/span><b>1,234,000원<\/b>/);
  assert.match(html,/href="new-pcs.html#a%20b"><strong>&lt;b&gt;PC&lt;\/b&gt;<\/strong><b>금액 확인 중<\/b>/,'no made-up price, no empty intro');
  assert.doesNotMatch(html,/전체 보기/,'all fit, no "see all" link');
});
test('shows at most six and links to the full list when there are more',async()=>{
  const w=await load(()=>({data:{items:Array.from({length:8},(_,i)=>pc('c'+i))}}));
  const html=w.html();assert.equal((html.match(/class="welcome-pc"/g)||[]).length,6);assert.match(html,/<a href="new-pcs.html">전체 보기<\/a>/);
});
test('no section and no redraw when nothing is published, the server fails, or the network throws',async()=>{
  for(const respond of [()=>({data:{ok:true,items:[]}}),()=>({ok:false,data:{}}),()=>{throw Error('down');},()=>({data:{items:[{title:'번호 없음'}]}})]){
    const w=await load(respond);assert.equal(w.html(),'');assert.deepEqual(w.events,[]);
  }
});
