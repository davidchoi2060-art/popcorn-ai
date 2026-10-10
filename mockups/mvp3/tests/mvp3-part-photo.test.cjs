'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const M=require('../live-model.js');
// Part photo contract mirrors api/customer_pc_offer._public_offer:
// parts[].photo = {state:'approved', url:'/api/product-images/{code}/detail'} | {state:'none', url:null}.
function fixture(photos){return {product_code:99413,configuration_id:'P10',revision:1,offer_id:'P99413',
  description:{title:'검증 PC',intro:'근거 설명',scene:null,benefits:[],checks:[],faq:[]},
  parts:[{ordinal:0,slot:'CPU',quantity:1,pseudo:false,name:'CPU 이름',description:'역할',specs:[],photo:photos[0]},
    {ordinal:1,slot:'MB',quantity:1,pseudo:false,name:'MB 이름',description:'역할',specs:[],photo:photos[1]},
    {ordinal:8,slot:'SERVICE',quantity:1,pseudo:true,name:null,description:null,specs:[],photo:photos[2]}],
  price:{state:'unknown',amount:null,checked_at:null,observed_date:null,model:null},stock:{state:'unknown',checked_at:null},
  compatibility:{document_state:'pass',public_summary:null,assembly_state:'unknown'},photo:{state:'unresolved',url:null},
  customer_conditions:Object.fromEntries(['os','keyboard','mouse','monitor','warranty'].map(k=>[k,{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'구매 전에 확인해 주세요.'}]))};}
const ok=code=>({state:'approved',url:'/api/product-images/'+code+'/detail'}),none={state:'none',url:null};
function render(configuration){
  const p=M.product({product_code:99413,name:'검증 PC',price:900000,spec:{cpu:'CPU'},reasons:['근거'],public_configuration:configuration});
  const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
  const code=app.slice(app.indexOf('function publicBomDetails('),app.indexOf('function finalConditions('));
  return vm.runInNewContext(code+'\nproductDetails(false)',{M,state:{selected:p,selectedContext:null,selectionState:{usages:['게임']},talk:{}},
    esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    uiIcon:name=>'<i data-icon="'+name+'"></i>',
    button:(label,action,cls='',data='')=>'<button type="button" class="'+cls+'" data-action="'+action+'" '+data+'>'+label+'</button>',
    money:v=>Number.isInteger(v)?v+'원':'금액 미확인'});
}
test('partPhoto accepts only the approved product-image detail route',()=>{
  assert.deepEqual(M.partPhoto({photo:ok(123034)}),ok(123034));
  for(const photo of [none,null,undefined,'x',{state:'approved',url:null},{state:'pending',url:ok(1).url},
    {state:'approved',url:'https://example.invalid/a.png'},{state:'approved',url:'/api/product-images/0/detail'},
    {state:'approved',url:'/api/product-images/12/thumb'},{state:'approved',url:'/api/product-images/12/detail?x=1'},
    {state:'approved',url:'/api/product-images/99999999999999999/detail'},{state:'approved',url:'javascript:alert(1)'}])
    assert.deepEqual(M.partPhoto({photo}),none,JSON.stringify(photo));
  assert.deepEqual(M.partPhoto({pseudo:true,photo:ok(5)}),none);
});
test('public configuration keeps each part photo and old responses without photo stay none',()=>{
  const out=M.publicConfiguration(fixture([ok(11),none,ok(12)]),99413);
  assert.deepEqual(out.parts.map(p=>p.photo),[ok(11),none,none]);
  const legacy=fixture([]);for(const p of legacy.parts)delete p.photo;
  assert.deepEqual(M.publicConfiguration(legacy,99413).parts.map(p=>p.photo),[none,none,none]);
});
test('approved part photo renders an image; missing photo keeps the explicit placeholder',()=>{
  const html=render(fixture([ok(11),none,none]));
  assert.match(html,/<figure class="public-bom-photo" data-product-photo><img data-product-image src="\/api\/product-images\/11\/detail" alt="CPU 이름 부품 사진"/);
  assert.equal((html.match(/<img data-product-image/g)||[]).length,1);
  assert.equal((html.match(/<div class="public-bom-photo">정보 없음<\/div>/g)||[]).length,2);
  assert.doesNotMatch(html,/부품 사진 미확인|등록 사양 미확인|항목명 미확인|등록 설명 미확인/);
  assert.match(html,/data-product-image-status hidden>부품 사진을 불러오지 못했습니다/);
});
