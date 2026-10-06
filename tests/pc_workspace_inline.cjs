// Source-only DOM/MOCK regression. No network, database or operating writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..'),clone=x=>JSON.parse(JSON.stringify(x));
const files=['pc-sales-conditions.js','pc-description-editor.js','pc-parts-editor.js','pc-quote-assembly.js','pc-review-editor.js','pc-configuration-detail.js'];
function fixture(id='MOCK-A'){
 const required={specs:'MOCK 사양 근거'};
 const review={configuration_id:id,revision:1,basis:'a'.repeat(64),checks:[],blockers:[],required,findings:{specs:{confirmed:false,evidence:''}},note:'',state:'pending',eligible:false,recommendation_state:'ready',assembly_checks:[],assembly_checklist:[]};
 return {configuration_id:id,revision:1,content:{title:id+' CODE/MOCK',intro:'MOCK 등록 소개',scene:'MOCK 사용 상황',benefits:[['MOCK 특징','MOCK 설명']],checks:[],faq:[],recommendation_policy:{},facts:{}},offers:[{offer_id:'MOCK-O',price_snapshot:100,payload:{}}],parts:[{ordinal:0,slot:'RAM',slot_label:'메모리',quantity:1,source_code:'100',explanation_code:100,pseudo:false,current_unit_price:100,explanation:{name:'MOCK RAM',facts:[],role:'MOCK 메모리'}}],current_review:review,sales_conditions:{},observed_date:'MOCK',needs_review:false};
}
const html='<main class="pcw"><aside><input id="pcw-search"><div id="pcw-filters"></div><p id="pcw-count"></p><div id="pcw-tasks"></div></aside><section><p id="pcw-message"></p><div id="pcw-product"></div></section></main><dialog id="pcw-detail"><button id="pcw-close"></button><div id="pcw-detail-body"></div></dialog>';
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:v=>resolve(v)};};
const response=(value,status=200)=>({ok:status>=200&&status<300,status,json:async()=>clone(value)});
async function until(fn,label){for(let i=0;i<250;i++){if(fn())return;await new Promise(setImmediate);}throw Error('DOM/MOCK timeout: '+label);}
async function setup({entry='copy',fetchHook,quotes=false}={}){
 const dom=new JSDOM(html,{url:'https://mock.invalid/admin2/pc-workspace?id=MOCK-A&tab='+entry,runScripts:'outside-only'}),w=dom.window,requests=[],data={'MOCK-A':fixture(),'MOCK-B':fixture('MOCK-B')};
 // jsdom lacks native dialog methods/layout; these test-only browser shims are
 // absent from application code. Native loopback QA uses actual Chromium dialogs.
 w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
 w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new w.Event('close'));};
 w.HTMLElement.prototype.scrollIntoView=function(){};w.confirm=()=>false;
 const quote={quote:{current_version:1},assembly_state:'not_verified',version:{total_amount:100,bom:[]},drafts:[],open_issues:[],events:[],validations:[]};
 w.fetch=async(url,init={})=>{
  const u=new URL(url,w.location.href),method=init.method||'GET',req={url:u.pathname,method,body:init.body?JSON.parse(init.body):null};requests.push(req);
  const custom=await fetchHook?.(req,{data,w});if(custom)return custom;
  if(u.pathname==='/api/admin/pc-workspace/tasks')return response({items:Object.values(data).map(d=>({configuration_id:d.configuration_id,title:d.content.title,task_kind:'review',task_reason:'MOCK 근거 확인',price:null,search_parts:[]}))});
  if(u.pathname==='/api/admin/pc-quote-assembly')return response({items:quotes?[{quote_id:'MOCK-Q',current_version:1}]:[]});
  if(u.pathname==='/api/admin/pc-quote-assembly/MOCK-Q')return response(quote);
  const match=u.pathname.match(/^\/api\/admin\/pc-configurations\/([^/]+)(?:\/(.*))?$/);if(match){const d=data[decodeURIComponent(match[1])];if(!d)return response({detail:'MOCK missing'},404);if(!match[2])return response(d);if(match[2]==='review'&&method==='GET')return response(d.current_review);if(match[2]==='description-history')return response({items:[]});}
  return response({detail:'MOCK unconfigured endpoint'},404);
 };
 for(const f of files)w.eval(fs.readFileSync(path.join(root,'mockups/shared',f),'utf8'));
 w.eval(fs.readFileSync(path.join(root,'mockups/shared/pc-workspace.js'),'utf8'));
 const $=s=>w.document.querySelector(s),click=s=>{const b=$(s);assert(b,'missing '+s);b.click();},input=(s,value)=>{const x=$(s);x.value=value;x.dispatchEvent(new w.Event('input',{bubbles:true}));};
 await until(()=>$('[data-tab="parts"]'),'initial product');
 return {dom,w,$,click,input,data,requests,close:()=>dom.window.close()};
}
let passed=0;async function test(name,fn){await fn();passed++;console.log('PASS '+name);}
async function main(){
 await test('outer tabs reuse one inline host; no nested sidebar/tablist/dialog; entry review',async()=>{const t=await setup({entry:'review'});try{await until(()=>t.$('[data-review-note]'),'review');assert.equal(t.$('#pcw-detail').open,false);assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');assert.equal(t.$('#pcw-copy-columns').hidden,true);assert.equal(t.$('#pcw-inline .pcd-overview'),null);assert.equal(t.$('#pcw-inline [role=tablist]'),null);assert.equal(t.$('#pcw-inline [data-detail-close]'),null);assert.equal(t.$('#pcw-inline #pcd-panel-copy'),null);const host=t.$('#pcw-inline .pcd-main');t.click('.pcw-tabs [data-tab=parts]');t.click('.pcw-tabs [data-tab=review]');assert.equal(t.$('#pcw-inline .pcd-main'),host);assert.equal(t.$('#pcw-detail').open,false);}finally{t.close();}});
 await test('parts dirty protects tabs/product/next/unload; cancel restores navigation',async()=>{const t=await setup({entry:'parts'});try{t.click('[data-pcp-start]');const qty=t.$('[data-pcp-qty]');qty.value='2';qty.dispatchEvent(new t.w.Event('change',{bubbles:true}));t.click('.pcw-tabs [data-tab=review]');t.click('[data-product=MOCK-B]');t.click('[data-next-task]');assert.equal(t.$('.pcw-tabs [data-tab=parts]').getAttribute('aria-pressed'),'true');assert.match(t.$('.pcw-header').textContent,/MOCK-A/);const unload=new t.w.Event('beforeunload',{cancelable:true});t.w.dispatchEvent(unload);assert.equal(unload.defaultPrevented,true);t.click('[data-pcp-cancel]');t.click('[data-pcp-drop]');t.click('.pcw-tabs [data-tab=review]');assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');}finally{t.close();}});
 await test('copy and sales dirty/busy guards preserve existing editors',async()=>{const t=await setup();try{t.input('#pcw-intro','MOCK edited');t.click('.pcw-tabs [data-tab=parts]');assert.equal(t.$('#pcw-inline').hidden,true);t.click('[data-undo]');t.click('.pcw-tabs [data-tab=sales]');const area=t.$('#pcw-sales textarea');assert(area);area.value='MOCK condition';area.dispatchEvent(new t.w.Event('input',{bubbles:true}));t.click('.pcw-tabs [data-tab=parts]');assert.equal(t.$('#pcw-sales').hidden,false);assert.equal(area.value,'MOCK condition');}finally{t.close();}});
 await test('review PUT 409/404 preserves input, exact payload, no automatic repeat',async()=>{for(const status of [409,404]){const t=await setup({entry:'review',fetchHook:r=>r.method==='PUT'?response({detail:'MOCK '+status},status):null});try{await until(()=>t.$('[data-review-note]'),'review');t.input('[data-review-note]','MOCK retained note');t.click('[data-review-draft]');await until(()=>t.$('[data-review-message]').textContent.includes('유지'),'save failure');assert.equal(t.$('[data-review-note]').value,'MOCK retained note');assert.equal(t.requests.filter(r=>r.method==='PUT').length,1);assert.deepEqual(t.requests.find(r=>r.method==='PUT').body,{revision:1,basis:'a'.repeat(64),action:'draft',findings:{specs:{confirmed:false,evidence:''}},note:'MOCK retained note'});t.click('.pcw-tabs [data-tab=copy]');assert.equal(t.$('#pcw-inline').hidden,false);}finally{t.close();}}});
 await test('review busy locks actual controls and submitted snapshot; callback reload holds navigation',async()=>{const write=deferred(),read=deferred();let afterWrite=false;const t=await setup({entry:'review',fetchHook:async(r,{data})=>{if(r.method==='PUT'){await write.promise;data['MOCK-A'].revision=2;data['MOCK-A'].current_review.revision=2;afterWrite=true;return response(data['MOCK-A'].current_review);}if(afterWrite&&r.url==='/api/admin/pc-configurations/MOCK-A'){await read.promise;return response(data['MOCK-A']);}}});try{await until(()=>t.$('[data-review-note]'),'review');t.input('[data-review-note]','MOCK sent');t.click('[data-review-draft]');await until(()=>t.requests.some(r=>r.method==='PUT'),'PUT');assert.equal(t.$('[data-review-note]').disabled,true);t.input('[data-review-note]','MOCK attempted during busy');t.click('[data-product=MOCK-B]');assert.match(t.$('.pcw-header').textContent,/MOCK-A/);assert.equal(t.requests.find(r=>r.method==='PUT').body.note,'MOCK sent');write.resolve();await until(()=>afterWrite,'write finished');t.click('[data-product=MOCK-B]');assert.match(t.$('.pcw-header').textContent,/MOCK-A/);read.resolve();await until(()=>t.$('[data-review-draft]')&&!t.$('[data-review-draft]').disabled&&t.requests.some(r=>r.url.endsWith('/review')&&r.method==='GET'&&r!==t.requests[1]),'fresh review');assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');assert.equal(t.requests.filter(r=>r.method==='PUT').length,1);}finally{t.close();}});
 await test('parts save/new id keeps parts tab and refreshes queue; failure input survives',async()=>{for(const status of [409,200]){const t=await setup({entry:'parts',fetchHook:(r,{data})=>{if(r.url.endsWith('/parts-preview'))return response({total:200,delta:100,price_note:'MOCK',assembly_note:'MOCK',preview_token:'MOCK-T',changes:[{ordinal:0,label:'MOCK RAM',before:{name:'MOCK RAM',quantity:1,unit_price:100,total:100},after:{name:'MOCK RAM',quantity:2,unit_price:100,total:200},delta:100}]});if(r.method==='PUT'&&r.url.endsWith('/parts')){if(status!==200)return response({detail:'MOCK conflict'},status);data['MOCK-B'].parts[0].quantity=2;return response({configuration_id:'MOCK-B'});}}});try{t.click('[data-pcp-start]');const x=t.$('[data-pcp-qty]');x.value='2';x.dispatchEvent(new t.w.Event('change',{bubbles:true}));t.click('[data-pcp-review]');await until(()=>t.$('[data-pcp-save]'),'preview');t.$('[name=pcp-mode][value=new]').checked=true;t.click('[data-pcp-save]');if(status===200){await until(()=>t.$('.pcw-header')?.textContent.includes('MOCK-B'),'saved new configuration');assert.equal(t.$('.pcw-tabs [data-tab=parts]').getAttribute('aria-pressed'),'true');assert.equal(t.$('#pcw-detail').open,false);}else{await until(()=>t.$('[data-pcp-message]').textContent.includes('유지'),'failed parts');assert(t.$('[data-pcp-save]'));assert.match(t.$('.pcp-review').textContent,/2개/);}assert.deepEqual(t.requests.find(r=>r.method==='PUT').body,{revision:1,offer_id:'MOCK-O',replacements:[{ordinal:0,code:100,quantity:2}],mode:'new',preview_token:'MOCK-T'});}finally{t.close();}}});
 await test('save success / subsequent GET failure is separate; never repeats PUT',async()=>{let committed=false;const t=await setup({entry:'review',fetchHook:r=>{if(r.method==='PUT'){committed=true;return response({});}if(committed&&r.url==='/api/admin/pc-configurations/MOCK-A')return response({detail:'MOCK unavailable'},503);}});try{await until(()=>t.$('[data-review-draft]'),'review');t.click('[data-review-draft]');await until(()=>t.$('#pcw-inline').textContent.includes('저장은 처리됐지만'),'refresh failure');assert.equal(t.requests.filter(r=>r.method==='PUT').length,1);assert.equal(t.$('[data-review-draft]'),null);assert.match(t.$('#pcw-message').textContent,/저장 후 조회 실패/);}finally{t.close();}});
 await test('late review GET cannot replace newly selected product',async()=>{const old=deferred();const t=await setup({entry:'parts',fetchHook:async r=>r.url==='/api/admin/pc-configurations/MOCK-A/review'?await old.promise:null});try{t.click('[data-product=MOCK-B]');await until(()=>t.$('.pcw-header')?.textContent.includes('MOCK-B'),'B selected');t.click('.pcw-tabs [data-tab=review]');await until(()=>t.$('[data-review-note]'),'B review');old.resolve(response({...fixture().current_review,note:'MOCK OLD PRIVATE'}));await new Promise(setImmediate);assert.equal(t.$('[data-review-note]').value,'');assert.doesNotMatch(t.$('#pcw-product').textContent,/OLD PRIVATE/);}finally{t.close();}});
 await test('quote dirty and in-flight write protect tab/product/next/unload',async()=>{const pending=deferred();const t=await setup({entry:'review',quotes:true,fetchHook:async r=>r.method==='POST'&&r.url.endsWith('/assembly')?await pending.promise:null});try{await until(()=>t.$('[data-q-select] option[value=MOCK-Q]'),'quote list');const select=t.$('[data-q-select]');select.value='MOCK-Q';select.dispatchEvent(new t.w.Event('change'));await until(()=>t.$('[data-q-note]'),'quote body');t.input('[data-q-note]','MOCK quote record');t.click('.pcw-tabs [data-tab=parts]');t.click('[data-product=MOCK-B]');assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');const unload=new t.w.Event('beforeunload',{cancelable:true});t.w.dispatchEvent(unload);assert(unload.defaultPrevented);t.click('[data-q-action=issue]');await until(()=>t.requests.some(r=>r.method==='POST'),'quote POST');t.click('[data-product=MOCK-B]');assert.match(t.$('.pcw-header').textContent,/MOCK-A/);assert.equal(select.disabled,true);pending.resolve(response({detail:'MOCK unavailable'},503));await until(()=>t.$('[data-q-status]').textContent.includes('유지'),'quote failed');assert.equal(t.$('[data-q-note]').value,'MOCK quote record');}finally{t.close();}});
 await test('default standalone modal structure, description, dirty close guard and save/close event remain',async()=>{const t=await setup({fetchHook:r=>r.method==='PUT'&&r.url.endsWith('/review')?response({}):null});try{t.click('[data-edit-full]');await until(()=>t.$('#pcw-detail [data-review-note]'),'modal review');assert(t.$('#pcw-detail').open);assert(t.$('#pcw-detail .pcd-overview'));assert(t.$('#pcw-detail [role=tablist]'));assert(t.$('#pcw-detail [data-save-copy]'));const host=t.$('#pcw-detail-body');assert(host.pcDescriptionDirty);t.$('#pcw-detail [data-tab=review]').click();t.input('#pcw-detail [data-review-note]','MOCK standalone');t.click('#pcw-close');assert(t.$('#pcw-detail').open);let saved=0;host.addEventListener('pc-review-saved',()=>saved++);t.click('#pcw-detail [data-review-draft]');await until(()=>!t.$('#pcw-detail').open,'modal closed after save');assert.equal(saved,1);assert.equal(t.$('#pcw-inline').hidden,true);}finally{t.close();}});
 await test('late quote GET inherits review inert lock; success/error/dispose restore prior accessibility state',async()=>{
  for(const status of [200,409]){
   const quoteRead=deferred(),write=deferred();
   const t=await setup({entry:'review',quotes:true,fetchHook:async r=>{
    if(r.url==='/api/admin/pc-quote-assembly/MOCK-Q')return await quoteRead.promise;
    if(r.method==='PUT')return await write.promise;
   }});
   try{
    await until(()=>t.$('[data-q-select] option[value=MOCK-Q]'),'quote list');
    const panel=t.$('#pcd-panel-review'),select=t.$('[data-q-select]');
    panel.setAttribute('aria-busy','false');panel.inert=false;
    select.value='MOCK-Q';select.dispatchEvent(new t.w.Event('change'));
    await until(()=>t.requests.some(r=>r.url.endsWith('/MOCK-Q')),'selected quote GET pending');
    assert.equal(t.$('[data-q-note]'),null);
    t.click('[data-review-draft]');
    await until(()=>t.requests.some(r=>r.method==='PUT'),'review PUT pending');
    assert.equal(panel.inert,true);assert.equal(panel.getAttribute('aria-busy'),'true');
    quoteRead.resolve(response({quote:{current_version:1},assembly_state:'not_verified',version:{total_amount:100,bom:[]},drafts:[],open_issues:[],events:[],validations:[]}));
    await until(()=>t.$('[data-q-note]'),'late quote DOM during PUT');
    const late=t.$('[data-q-note]');
    assert.equal(late.disabled,false);assert.equal(late.closest('#pcd-panel-review'),panel);
    // jsdom cannot exercise native inert keyboard behavior. This asserts the
    // inherited browser interaction boundary, not fabricated input blocking.
    assert.equal(panel.inert,true);assert.equal(panel.getAttribute('aria-busy'),'true');
    t.click('.pcw-tabs [data-tab=parts]');t.click('[data-product=MOCK-B]');
    assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');
    assert.match(t.$('.pcw-header').textContent,/MOCK-A/);
    write.resolve(response(status===200?{}:{detail:'MOCK conflict'},status));
    if(status===200){
     await until(()=>!panel.isConnected,'success refresh disposed old panel');
     await until(()=>t.$('[data-review-note]')&&!t.$('[data-review-note]').disabled,'fresh review');
     assert.equal(t.$('#pcd-panel-review').inert===true,false);
    }else{
     await until(()=>t.$('[data-review-message]').textContent.includes('유지'),'review failure unlocked');
     assert.equal(late.isConnected,true);assert.equal(late.disabled,false);
     t.input('[data-q-note]','MOCK input after failed save');
     assert.equal(late.value,'MOCK input after failed save');
     assert.equal(t.$('#pcw-inline').pcReviewDirty(),true);
    }
    assert.equal(panel.inert,false);assert.equal(panel.getAttribute('aria-busy'),'false');
    assert.equal(t.requests.filter(r=>r.method==='PUT').length,1);
    assert.equal(t.requests.filter(r=>r.method==='POST').length,0);
   }finally{t.close();}
  }
  // Disposal of a still-processing shared editor restores a pre-existing lock.
  const pending=deferred(),t=await setup({entry:'review',fetchHook:async r=>r.method==='PUT'?await pending.promise:null});
  try{
   await until(()=>t.$('[data-review-note]'),'review for direct disposal');
   const holder=t.w.document.createElement('div');t.w.document.body.append(holder);
   holder.innerHTML='<div class="pcd-main"><section id="pcd-panel-review" inert aria-busy="original"></section></div>';
   const panel=holder.querySelector('#pcd-panel-review');panel.inert=true;
   const editor=t.w.PcReviewEditor.mount(holder,fixture(),{inline:true});
   await until(()=>holder.querySelector('[data-review-draft]'),'shared editor mounted');
   holder.querySelector('[data-review-draft]').click();
   await until(()=>holder.pcReviewProcessing(),'shared editor busy');
   editor.dispose();assert.equal(panel.inert,true);assert.equal(panel.getAttribute('aria-busy'),'original');
   pending.resolve(response({}));await new Promise(setImmediate);
   assert.equal(holder.pcReviewProcessing,null);
  }finally{t.close();}
 });
 await test('queue GET failure after confirmed fresh detail preserves refreshed review and never repeats PUT',async()=>{
  let saved=false;const t=await setup({entry:'review',fetchHook:(r,{data})=>{
   if(r.method==='PUT'){saved=true;data['MOCK-A'].revision=2;data['MOCK-A'].current_review.revision=2;return response({});}
   if(saved&&r.url==='/api/admin/pc-workspace/tasks')return response({detail:'MOCK queue unavailable'},503);
  }});
  try{
   await until(()=>t.$('[data-review-draft]'),'review');t.click('[data-review-draft]');
   await until(()=>t.$('#pcw-message').textContent.includes('작업 목록 갱신 실패'),'queue failure');
   await until(()=>t.$('[data-review-note]')&&!t.$('[data-review-note]').disabled,'fresh review survives');
   assert.equal(t.$('.pcw-tabs [data-tab=review]').getAttribute('aria-pressed'),'true');
   assert.equal(t.$('#pcw-detail').open,false);assert.equal(t.requests.filter(r=>r.method==='PUT').length,1);
   assert.doesNotMatch(t.$('#pcw-inline').textContent,/저장은 처리됐지만/);
  }finally{t.close();}
 });
 console.log('Workspace inline DOM/MOCK: '+passed+' groups PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
