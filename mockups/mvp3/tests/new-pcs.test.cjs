'use strict';
// 2026-10-11 중헌 님 「신규 조립PC 제품도 출시할 수 있어야 함」(부품 상품화 4단계).
// 「새로 구성된 PC」는 서버가 준 공개 PC 와 그 가격만 보이고, 구매는 그 PC 번호를 붙인 구매 상담 신청으로 받는다.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<400;n++){if(check())return;await tick();}throw Error('render did not settle');}
const pc={configuration_id:'A0123456789ABCDEF',title:'새 게임 PC',intro:'배그를 위해 고른 구성',scene:null,
  benefits:[{title:'빠름',text:'고사양 게임도 부드러워요'}],checks:['윈도우는 따로 사야 해요'],facts:{},
  parts:[{slot:'CPU',slot_label:'CPU',name:'CPU A',quantity:1},{slot:'RAM',slot_label:'메모리',name:'램 16GB',quantity:2}],
  price:1430000,price_note:'부품 판매가 합계 + 조립비 30,000원 · 오늘 판매가 기준',released_at:'2026-10-11T00:00:00Z'};

function harness(items=[pc],{fail=false,listResponses=null,hash=''}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('new-pcs.html'),{url:'https://qa.invalid/mvp3/new-pcs.html'+hash,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.CSS={escape:s=>String(s)};
  w.fetch=async(url,init)=>{const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
    if(url==='/api/mvp3/custom-pcs'&&listResponses?.length){const value=listResponses.shift();return {ok:value.ok!==false,status:value.ok===false?503:200,json:async()=>value};}
    if(url==='/api/mvp3/purchase-inquiries'&&fail)return {ok:false,status:409,json:async()=>({detail:'이 PC는 지금 공개되어 있지 않아요.'})};
    const data=url==='/api/mvp3/custom-pcs'?{ok:true,items,note:'팝콘PC가 새로 만든 조립PC예요.'}:
      url==='/api/mvp3/purchase-inquiries/form'?{ok:true,topics:['주문 희망'],consent_text:'연락처를 받습니다.'}:
      {ok:true,inquiry_no:'PI-1001',note:'구매 상담 신청을 받았어요.'};
    return {ok:true,status:200,json:async()=>data};};
  w.eval(read('new-pcs.js'));
  return {w,d:w.document,errors,calls,close:()=>w.close()};
}
const text=e=>e.textContent.replace(/\s+/g,' ').trim();

test('lists released PCs with the server price and parts only',async()=>{
  const h=harness();try{
    await until(()=>h.d.querySelector('[data-pc]'));
    const card=text(h.d.querySelector('[data-pc]'));
    assert.ok(card.includes('새 게임 PC')&&card.includes('1,430,000원')&&card.includes('램 16GB × 2'));
    assert.ok(card.includes('쇼핑몰 상품 페이지가 아직 없는 PC'));
    assert.equal(text(h.d.querySelector('#new-pcs-note')),'팝콘PC가 새로 만든 조립PC예요.');
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('purchase inquiry carries the PC number and shows the receipt',async()=>{
  const h=harness();try{
    await until(()=>h.d.querySelector('[data-inquiry]'));
    h.d.querySelector('[data-inquiry]').click();
    await until(()=>h.d.querySelector('[data-form]'));
    const f=h.d.querySelector('[data-form]');
    assert.ok(text(f).includes('연락처를 받습니다.'));
    f.elements.phone.value='010-1234-5678';f.elements.consent.checked=true;
    f.dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>h.d.querySelector('.new-pc-done'));
    const sent=h.calls.find(c=>c.url==='/api/mvp3/purchase-inquiries');
    assert.equal(sent.body.configuration_id,'A0123456789ABCDEF');assert.equal(sent.body.topic,'주문 희망');
    assert.ok(text(h.d.querySelector('.new-pc-done')).includes('PI-1001'));
    assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('a refused inquiry keeps the typed contact and says why; empty list says so',async()=>{
  const h=harness([pc],{fail:true});try{
    await until(()=>h.d.querySelector('[data-inquiry]'));
    h.d.querySelector('[data-inquiry]').click();
    await until(()=>h.d.querySelector('[data-form]'));
    const f=h.d.querySelector('[data-form]');f.elements.phone.value='010-1234-5678';f.elements.consent.checked=true;
    f.elements.phone.focus();f.elements.phone.setSelectionRange(4,8);
    f.dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>h.d.querySelector('.new-pc-error'));
    assert.ok(text(h.d.querySelector('.new-pc-error')).includes('공개되어 있지 않아요'));
    assert.equal(h.d.querySelector('[data-form]').elements.phone.value,'010-1234-5678');
    assert.equal(h.d.activeElement,h.d.querySelector('[data-form]').elements.phone);
    assert.equal(h.d.activeElement.selectionStart,4);assert.equal(h.d.activeElement.selectionEnd,8);
  }finally{h.close();}
  const g=harness([]);try{
    await until(()=>!text(g.d.querySelector('#new-pcs-list')).includes('불러오는 중'));
    assert.ok(text(g.d.querySelector('#new-pcs-list')).includes('새로 구성된 PC를 준비하고 있어요.'));
    assert.equal(g.d.querySelector('.new-pcs-empty a').getAttribute('href'),'index.html#welcome');
  }finally{g.close();}
});

test('the full list keeps all seven items and all provided parts in server order',async()=>{
  const entries=Array.from({length:7},(_,i)=>({...pc,configuration_id:'pc-'+i,title:i===0?'<b>'+('긴 상품명 '.repeat(30))+'</b>':'PC '+i,
    parts:[...pc.parts,{slot:'CASE',slot_label:'케이스',name:'실제 케이스 '+i,quantity:1}]}));
  const h=harness(entries);try{
    await until(()=>h.d.querySelectorAll('[data-pc]').length===7);
    assert.deepEqual([...h.d.querySelectorAll('[data-pc]')].map(e=>e.dataset.pc),entries.map(e=>e.configuration_id));
    const first=h.d.querySelector('[data-pc]');assert.equal(first.querySelector('h2').textContent,entries[0].title);assert.equal(first.querySelector('h2 b'),null);
    assert.equal(first.querySelector('.new-pc-key-parts').textContent.includes('실제 케이스'),false);
    assert.match(first.querySelector('table').textContent,/실제 케이스 0/);
    assert.equal(h.calls.filter(c=>c.method==='POST').length,0);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('missing metadata never creates a price, usage, part or photo; actual fields remain in configuration',async()=>{
  const h=harness([{configuration_id:'minimal',title:'제목만 있는 PC',price:null},
    {...pc,configuration_id:'zero',price:0,intro:'운영자가 부품을 선택한 신규 구성입니다.',scene:'실제 장면',usages:[{usage:'영상편집',level:'기본'},{usage:'게임',level:'FHD'}]}]);
  try{
    await until(()=>h.d.querySelectorAll('[data-pc]').length===2);
    const cards=[...h.d.querySelectorAll('[data-pc]')];
    assert.equal(cards[0].querySelector('.new-pc-price').textContent,'금액 확인 중');
    assert.equal(cards[0].querySelector('.new-pc-usages'),null);assert.equal(cards[0].querySelector('.new-pc-key-parts'),null);
    assert.equal(cards[0].querySelector('table'),null);assert.equal(cards[0].querySelector('img:not(.ui-icon)'),null);
    assert.equal(cards[1].querySelector('.new-pc-price').textContent,'0원');
    assert.deepEqual([...cards[1].querySelectorAll('.new-pc-usages em')].map(text),['영상편집 기본','게임 FHD']);
    assert.match(text(cards[1]),/실제 장면/);assert.match(text(cards[1]),/이런 점이 좋아요.*빠름.*고사양 게임도 부드러워요/);
    assert.match(text(cards[1]),/구매 전에 확인해 주세요.*윈도우는 따로 사야 해요/);
    assert.doesNotMatch(text(cards[1]),/운영자가 부품을 선택한/);assert.deepEqual(h.errors,[]);
    assert.equal(h.calls.filter(c=>c.method==='POST').length,0);
  }finally{h.close();}
});

test('failed list retries the actual GET and updates only from its new response',async()=>{
  const h=harness([],{listResponses:[{ok:false},{items:[pc]}]});try{
    await until(()=>h.d.querySelector('[data-retry]'));
    assert.match(text(h.d.querySelector('#new-pcs-list')),/PC 목록을 불러오지 못했어요.*잠시 후 다시 확인해 주세요/);
    h.d.querySelector('[data-retry]').click();await until(()=>h.d.querySelector('[data-pc]'));
    assert.equal(h.calls.filter(c=>c.url==='/api/mvp3/custom-pcs').length,2);
    assert.equal(h.d.querySelector('#new-pcs-list').getAttribute('aria-busy'),'false');assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});

test('deep link opens the matching configuration and switching inquiry forms keeps drafts',async()=>{
  const h=harness([pc,{...pc,configuration_id:'second',title:'두 번째 PC'}],{hash:'#second'});try{
    await until(()=>h.d.querySelectorAll('[data-pc]').length===2);
    const second=h.d.querySelector('[data-pc="second"]');assert.ok(second.classList.contains('is-target'));
    assert.equal(second.querySelector('details').open,true);
    h.d.querySelector('[data-inquiry]').click();await until(()=>h.d.querySelector('[data-form]'));
    let f=h.d.querySelector('[data-form]');f.elements.phone.value='010-0000-0000';f.elements.message.value='작성 중인 문장';f.elements.consent.checked=true;
    f.elements.message.dispatchEvent(new h.w.Event('input',{bubbles:true}));
    h.d.querySelector('[data-inquiry="second"]').click();await until(()=>h.d.querySelector('[data-form="second"]'));
    h.d.querySelector('[data-inquiry="'+pc.configuration_id+'"]').click();await until(()=>h.d.querySelector('[data-form="'+pc.configuration_id+'"]'));
    f=h.d.querySelector('[data-form]');assert.equal(f.elements.phone.value,'010-0000-0000');assert.equal(f.elements.message.value,'작성 중인 문장');assert.equal(f.elements.consent.checked,true);
    assert.equal(h.calls.filter(c=>c.method==='POST').length,0);assert.deepEqual(h.errors,[]);
  }finally{h.close();}
});
