// 「구성표 없는 PC 더 보기」 — 요청 중 다시 눌러도 같은 offset 을 두 번 받지 않는다(코덱스 검수 #101).
// 화면 스크립트를 그대로 읽어 가짜 DOM 위에서 돌린다.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const src=fs.readFileSync(path.join(__dirname,'../mockups/shared/part-catalog.js'),'utf8');
const els={};
const el=id=>els[id]||(els[id]={id,textContent:'',innerHTML:'',hidden:false,disabled:false,listeners:{},
  insertAdjacentHTML(_,h){this.innerHTML+=h;},addEventListener(t,f){this.listeners[t]=f;}});
const box={querySelector:s=>el(s)};
const calls=[],pending=[];
function fetch(url){
  calls.push(url);
  if(!url.includes('pcs-without-bom'))return Promise.resolve({ok:true,json:async()=>({summary:{used_by_state:{},by_state:{},used:0,total:0},state_labels:{},items:[],total:0,rule_count:0,note:''})});
  const off=Number(new URL(url,'http://x').searchParams.get('offset'));
  return new Promise(res=>pending.push(()=>res({ok:true,json:async()=>({total:60,note:'',
    items:Array.from({length:20},(_,i)=>({product_code:off+i,name:'PC'+(off+i),sale_price:1}))})})));
}
// 화면 스크립트는 칩(위 요약)과 표(아래 접힘)가 갈라져 있어 문서 기준으로 찾는다(코덱스 배치 A안).
vm.runInNewContext(src,{document:{getElementById:id=>id==='pc-cat'?box:null,querySelector:s=>el(s)},fetch,URLSearchParams,window:{}});
(async()=>{
  const flush=async()=>{while(pending.length){pending.shift()();await new Promise(r=>setImmediate(r));}};
  await flush();
  const nobom=()=>calls.filter(u=>u.includes('pcs-without-bom'));
  assert.equal(nobom().length,1);
  const more=el('#pc-cat-nobom-more').listeners.click;
  more();more();                                   // 응답 전에 두 번 누름
  assert.equal(el('#pc-cat-nobom-more').disabled,true);
  await flush();
  assert.deepEqual(nobom().map(u=>new URL(u,'http://x').searchParams.get('offset')),['0','20']);
  more();await flush();
  assert.deepEqual(nobom().map(u=>new URL(u,'http://x').searchParams.get('offset')),['0','20','40']);
  const codes=[...el('#pc-cat-nobom-list').innerHTML.matchAll(/<li>(\d+) ·/g)].map(m=>Number(m[1]));
  assert.equal(new Set(codes).size,codes.length);
  assert.equal(codes.length,60);
  assert.equal(el('#pc-cat-nobom-more').hidden,true);
  console.log('PASS part catalog no-BOM more button ignores clicks while loading');
})().catch(e=>{console.error(e);process.exit(1);});
