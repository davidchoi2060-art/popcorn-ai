// Exercise the rendered queue and its real event handlers without network or catalog writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

async function workspace(rows) {
  const elements = new Map(), handlers = {};
  function element(id) {
    if (!elements.has(id)) elements.set(id, {innerHTML:'',textContent:'',value:'',
      addEventListener(type,fn) {this[type]=fn;},querySelector(){return null;}});
    return elements.get(id);
  }
  const document = {getElementById:element,addEventListener(type,fn){handlers[type]=fn;},
    querySelectorAll(){return [];},querySelector(){return null;}};
  const calls = [];
  const context = {document,window:{addEventListener(){},confirm(){return false;}},
    URLSearchParams,location:{search:''},fetch:async url => {
      calls.push(url);
      const id = decodeURIComponent(url.split('/').pop());
      const data = url.endsWith('/tasks') ? {items:rows} : {
        configuration_id:id,revision:2,observed_date:'2026-10-05',
        content:{title:id,intro:'설명',scene:'일상 작업',benefits:[['구성','안내']],facts:{}},
        current_review:{eligible:false},offers:[],parts:[]};
      return {ok:true,json:async()=>data};
    }};
  vm.runInNewContext(fs.readFileSync('mockups/shared/pc-workspace.js','utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  async function click(dataset) {
    const button={dataset,closest(){return {};},hasAttribute(){return false;}};
    handlers.click({target:{closest(){return button;}}});
    await new Promise(resolve=>setImmediate(resolve));
  }
  return {element,click,calls};
}
const multiple = {configuration_id:'A',title:'듀얼 SSD',price:2133000,search_parts:[],
  task_kind:'price',task_reason:'가격 확인',task_kinds:['price','copy','review'],
  task_reasons:[{kind:'price',text:'가격 확인'},{kind:'copy',text:'설명 보완'},
    {kind:'review',text:'장착 근거 <img src=x onerror=alert(1)>'}]};
const review = {configuration_id:'B',title:'일반 PC',price:1000000,task_kind:'review',
  task_reason:'검토 기록 작성 필요'};

test('one product appears in every unfinished kind without duplicate queue rows',async()=>{
  const w=await workspace([multiple,review]);
  assert.equal(w.element('pcw-count').textContent,'2개 제품');
  assert.match(w.element('pcw-filters').innerHTML,/검토 2/);
  assert.match(w.element('pcw-filters').innerHTML,/설명 1/);
  assert.match(w.element('pcw-filters').innerHTML,/가격 1/);
  for (const kind of ['price','copy','review']) {
    await w.click({filter:kind});
    assert.match(w.element('pcw-tasks').innerHTML,/data-product="A"/);
    assert.equal((w.element('pcw-tasks').innerHTML.match(/data-product="A"/g)||[]).length,1);
  }
});
test('secondary reason can be searched and catalog text is escaped',async()=>{
  const w=await workspace([multiple,review]);
  const input=w.element('pcw-search'); input.input({target:{value:'장착 근거'}});
  assert.equal(w.element('pcw-count').textContent,'1개 제품');
  assert.match(w.element('pcw-tasks').innerHTML,/&lt;img/);
  assert.doesNotMatch(w.element('pcw-tasks').innerHTML,/<img/);
  input.input({target:{value:'없는 상품'}});
  assert.match(w.element('pcw-tasks').innerHTML,/해당 작업이 없습니다/);
});
test('previous API response remains usable during code rollout',async()=>{
  const w=await workspace([review]);
  await w.click({filter:'review'});
  assert.equal(w.element('pcw-count').textContent,'1개 제품');
  assert.match(w.element('pcw-tasks').innerHTML,/검토 기록 작성 필요/);
  await w.click({filter:'copy'});
  assert.equal(w.element('pcw-count').textContent,'0개 제품');
});
test('filtering does not discard the selected product or bypass dirty navigation guard',async()=>{
  const w=await workspace([multiple,review]);
  w.element('pcw-product').input({target:{id:'pcw-title',value:'작성 중 설명'}});
  await w.click({filter:'review'});
  assert.equal(w.element('pcw-title').value,'작성 중 설명');
  await w.click({product:'B'});
  assert.ok(!w.calls.includes('/api/admin/pc-configurations/B'));
  assert.equal(w.element('pcw-title').value,'작성 중 설명');
});

async function home(rows) {
  const elements=new Map(), buttons=['','price','copy','review'].map(kind=>({dataset:{kind},
    setAttribute(){},addEventListener(type,fn){this[type]=fn;}}));
  const element=id=>{
    if(!elements.has(id)) elements.set(id,{innerHTML:'',textContent:'',value:'',
      addEventListener(type,fn){this[type]=fn;}});
    return elements.get(id);
  };
  const context={document:{getElementById:element,querySelectorAll(){return buttons;}},
    localStorage:{getItem(){return null;},setItem(){}},fetch:async()=>({ok:true,json:async()=>({
      items:rows,counts:{price:1,copy:1,review:2}})})};
  vm.runInNewContext(fs.readFileSync('mockups/shared/admin-new.js','utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  return {element,filter:kind=>buttons.find(button=>button.dataset.kind===kind).click()};
}
test('NEW overview counts and filtered rows agree for overlapping work',async()=>{
  const h=await home([multiple,review]);
  assert.equal(h.element('an-review').textContent,'2');
  h.filter('review');
  assert.match(h.element('an-status').textContent,/작업 2건/);
  assert.match(h.element('an-rows').innerHTML,/구성·호환·근거 검토/);
  h.filter('copy');
  assert.match(h.element('an-status').textContent,/작업 1건/);
  assert.match(h.element('an-rows').innerHTML,/설명·AI 초안 확인/);
  assert.doesNotMatch(h.element('an-rows').innerHTML,/<img/);
});
test('NEW overview searches secondary reasons and component names',async()=>{
  const h=await home([{...multiple,search_parts:[{name:'검색용 부품'}]},review]);
  for(const query of ['장착 근거','검색용 부품']) {
    const search=h.element('an-search');search.value=query;search.input();
    assert.match(h.element('an-status').textContent,/작업 1건/);
    assert.match(h.element('an-rows').innerHTML,/듀얼 SSD/);
  }
});
