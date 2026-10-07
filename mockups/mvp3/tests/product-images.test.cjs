'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{webcrypto}=require('node:crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const base=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(base,n),'utf8');
const product={product_code:113836,name:'CODE/MOCK <PC>',price:900000,spec:{cpu:'CPU'},image_url:'https://untrusted.invalid/fake.png'};
const qid='22222222-2222-4222-8222-222222222222';
const quote={id:qid,product,state:{usages:['사무용']},saved_at:'2026-10-07T00:00:00Z'};
const rec={ok:true,card_sets:[{kind:'sold',usage:'사무용',items:[product]}]};
const tick=()=>new Promise(r=>setImmediate(r));
async function until(check){for(let n=0;n<50;n++){if(check())return;await tick();}throw Error('render did not settle');}
function harness({saved=false,item=product}={}){
  const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(read('index.html'),{url:'https://qa.invalid/mvp3/#'+(saved?'saved':'welcome'),runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
  const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.TextEncoder=TextEncoder;
  Object.defineProperty(w,'crypto',{value:webcrypto});w.localStorage.setItem('popcorn-mvp3-guest-access-v1','a'.repeat(64));
  w.eval(read('live-model.js'));w.eval(read('api-client.js'));
  w.MVP3Api=w.MVP3Api.createClient({storage:w.localStorage,cryptoImpl:webcrypto,fetchImpl:async(url,options)=>{
    calls.push({url,method:options.method});
    const data=url==='/api/talk/parse'?{ok:true,state:{usages:['사무용']},history:[],missing:[]}:url==='/api/grid/recommend'?{...rec,card_sets:[{kind:'sold',usage:'사무용',items:[item]}]}:{ok:true,quotes:[quote],has_more:false};
    return {ok:true,status:200,json:async()=>data,headers:{get:()=>null}};
  }});w.eval(read('live-flow.js'));w.eval(read('app.js'));
  return {dom,w,calls,errors,click:s=>w.document.querySelector(s).click(),close:()=>dom.window.close()};
}
async function recommend(h){const input=h.w.document.querySelector('#request');input.value='CODE/MOCK 사무용';input.dispatchEvent(new h.w.Event('input',{bubbles:true}));h.w.document.querySelector('#chat-form').dispatchEvent(new h.w.Event('submit',{bubbles:true,cancelable:true}));await until(()=>h.w.document.querySelector('.live-product-card'));}

test('actual product_code binds same-origin thumbnail and detail; payload image URLs never become src',async()=>{
  const h=harness();try{await recommend(h);const image=h.w.document.querySelector('[data-product-image]');assert.equal(image.getAttribute('src'),'/api/product-images/113836/thumbnail');assert.equal(image.alt,'CODE/MOCK <PC> 대표 이미지');assert.equal(h.w.document.querySelector('[src*="untrusted"]'),null);h.click('[data-action=detail]');assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),'/api/product-images/113836/detail');assert.equal(h.calls.length,2);assert.deepEqual(h.errors,[]);}finally{h.close();}
});
test('image 404/error yields clear fallback without fabricated photo, retry POST, or lost product selection',async()=>{
  const h=harness();try{await recommend(h);const image=h.w.document.querySelector('[data-product-image]'),photo=image.parentElement;image.dispatchEvent(new h.w.Event('error'));assert.equal(image.hidden,true);assert.equal(photo.querySelector('figcaption').hidden,false);assert.match(photo.textContent,/등록된 상품 사진이 없거나 불러올 수 없어요/);assert.equal(photo.dataset.imageState,'unavailable');assert.equal(photo.querySelector('[src*=gateway-pc-example]'),null);assert.equal(h.calls.length,2);h.click('[data-action=detail]');assert.match(h.w.document.querySelector('.live-summary').textContent,/CODE\/MOCK <PC>/);const detailed=h.w.document.querySelector('[data-product-image]');detailed.dispatchEvent(new h.w.Event('load'));assert.equal(detailed.hidden,false);assert.equal(detailed.parentElement.querySelector('figcaption').hidden,true);assert.equal(h.calls.length,2);}finally{h.close();}
});
test('saved quote uses current catalog media and identifies it without changing saved amount/date',async()=>{
  const h=harness({saved:true});try{await until(()=>h.w.document.querySelector('[data-action=load]'));assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),'/api/product-images/113836/thumbnail');h.click('[data-action=load]');assert.match(h.w.document.querySelector('.live-summary').textContent,/이미지는 현재 등록본/);assert.equal(h.w.document.querySelector('[data-product-image]').getAttribute('src'),'/api/product-images/113836/detail');assert.match(h.w.document.querySelector('.live-summary').textContent,/900,000/);assert.ok(h.calls.every(c=>c.method==='GET'));}finally{h.close();}
});
test('unsafe product code cannot form media request; other icon errors remain outside product fallback',async()=>{
  const h=harness({item:{...product,product_code:Number.MAX_SAFE_INTEGER+1}});try{await until(()=>h.w.document.querySelector('.welcome-card'));const icon=h.w.document.querySelector('.brand-mark');icon.dispatchEvent(new h.w.Event('error'));assert.equal(icon.hidden,false);await recommend(h);assert.equal(h.w.document.querySelector('[data-product-image]'),null);assert.match(h.w.document.querySelector('.live-product-card').textContent,/등록된 상품 사진이 없거나 불러올 수 없어요/);}finally{h.close();}
});
test('every deployed landing start CTA invokes approved MVP3 destination in the real handler',()=>{
  const dom=new JSDOM(read('../mvp1/main-landing.html'),{runScripts:'outside-only'});try{
    const source=Array.from(dom.window.document.scripts).find(s=>s.textContent.includes('window.location.href')&&s.textContent.includes('[data-cta="start"]'))?.textContent;assert.ok(source);
    const location={href:''};new Function('document','window','setTimeout',source)(dom.window.document,{location},()=>{});
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    const starts=dom.window.document.querySelectorAll('[data-cta="start"]');assert.ok(starts.length>=5);
    for(const start of starts){location.href='';start.click();assert.equal(location.href,'/mvp3/');}
  }finally{dom.window.close();}
});
