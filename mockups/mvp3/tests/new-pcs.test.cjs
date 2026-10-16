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

function harness(items=[pc],{fail=false}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('new-pcs.html'),{url:'https://qa.invalid/mvp3/new-pcs.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.CSS={escape:s=>String(s)};
  w.fetch=async(url,init)=>{const body=init.body?JSON.parse(init.body):null;calls.push({url,method:init.method,body});
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
    f.dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));
    await until(()=>h.d.querySelector('.new-pc-error'));
    assert.ok(text(h.d.querySelector('.new-pc-error')).includes('공개되어 있지 않아요'));
    assert.equal(h.d.querySelector('[data-form]').elements.phone.value,'010-1234-5678');
  }finally{h.close();}
  const g=harness([]);try{
    await until(()=>!text(g.d.querySelector('#new-pcs-list')).includes('불러오는 중'));
    assert.ok(text(g.d.querySelector('#new-pcs-list')).includes('지금 공개된 새 PC가 없어요'));
  }finally{g.close();}
});
