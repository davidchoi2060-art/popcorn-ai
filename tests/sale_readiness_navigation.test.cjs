'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {resolutionHref,safeHref,readNavigation,readinessHref,createController,mount}=require('../mockups/shared/admin-sale-readiness.js');
const origin='https://admin.example';
const selected={id:'PC/듀얼',code:'SKU-OTHER',name:'격리 구성',state:'needs_check',checks:[],reasons:[]};
const state={scope:'configurations',q:'듀얼 SSD',offset:40,selectedId:selected.id};
const workspace='/admin2/pc-workspace?id='+encodeURIComponent(selected.id);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};}

test('each configuration reason opens its existing task and carries the selected list context',()=>{
 for(const [key,tab] of [['parts','parts'],['description','copy'],['sales:os','sales'],['sales_conditions','sales'],['review','review'],['review:unknown:1','review'],['price','review'],['stock','review'],['publication','review'],['assembly','review']]){
  const url=new URL(resolutionHref(workspace,selected,{key},state,origin),origin);
  assert.equal(url.searchParams.get('tab'),tab,key);
  assert.equal(url.searchParams.get('id'),selected.id);
  assert.equal(url.searchParams.get('from'),'sale-readiness');
  assert.equal(url.searchParams.get('sr_q'),state.q);
  assert.equal(url.searchParams.get('sr_offset'),'40');
  assert.equal(url.searchParams.get('sr_selected'),selected.id);
 }
 assert.equal(new URL(resolutionHref(workspace,selected,null,state,origin),origin).searchParams.get('tab'),'copy');
});
test('part review search uses canonical product_code identity instead of a displayed SKU',()=>{
 const url=new URL(resolutionHref('/admin2/reviews?admin=new',{id:'50683',code:'SKU-NOT-ID'},{key:'review'},{scope:'parts'},origin),origin);
 assert.equal(url.searchParams.get('keyword'),'50683');assert.equal(url.searchParams.get('admin'),'new');
});
test('unsafe paths, tabs, duplicate parameters and arbitrary return destinations remain rejected',()=>{
 for(const url of [workspace+'&tab=delete',workspace+'&return=https://evil.example',workspace+'&from=elsewhere',workspace+'&tab=sales&tab=review',workspace+'&from=sale-readiness&sr_offset=-40',workspace+'&from=sale-readiness&sr_offset=1',workspace+'&from=sale-readiness&sr_q=%00bad','/admin2/reviews?keyword=a&keyword=b'])assert.equal(safeHref(url,origin),null,url);
 assert.equal(resolutionHref('https://evil.example/admin2/pc-workspace',selected,{key:'price'},state,origin),null);
});
test('list context is bounded, round-trips special characters, and never contains an arbitrary URL',()=>{
 const context=readNavigation('?scope=parts&q='+encodeURIComponent('SSD & 2TB')+'&offset=80&selected=50683&return=https://evil.example');
 assert.deepEqual(context,{scope:'parts',q:'SSD & 2TB',offset:80,selectedId:'50683'});
 const restored=readNavigation(new URL(readinessHref(context),origin).search);assert.deepEqual(restored,context);
 assert.deepEqual(readNavigation('?scope=bad&q=%00abc&offset=-40&selected=%00bad'),{scope:'configurations',q:'abc',offset:0,selectedId:null});
 assert.equal(readNavigation('?q='+'a'.repeat(250)+'&offset=1000040').q.length,100);
 assert.equal(readNavigation('?offset=1000040').offset,0);
});
test('restored selection uses a fresh list and falls back when the old product disappeared',async()=>{
 const item=id=>({id,name:id,state:'needs_check',checks:[],reasons:[]});
 const urls=[];
 const controller=createController({get:async url=>{
  urls.push(url);return url.includes('?')?{scope:'configurations',offset:40,limit:40,total:42,counts:{needs_work:0,needs_check:42,basis_met:0,excluded:0},items:[item('first'),item('second')]}:item(url.split('/').pop());
 }},{...state,selectedId:'second'});
 await controller.load();assert.equal(controller.state.selectedId,'second');assert.match(urls[1],/second$/);assert.match(urls[0],/offset=40/);
 const absent=createController({get:async url=>url.includes('?')?{scope:'configurations',offset:0,limit:40,total:1,counts:{needs_work:0,needs_check:1,basis_met:0,excluded:0},items:[item('first')]}:item('first')},{selectedId:'gone'});
 await absent.load();assert.equal(absent.state.selectedId,'first');
});

function workspaceHarness(search,{detailPending=false,detailError=false}={}){
 const elements=new Map(),handlers={},windowHandlers={},requests=[],opened=[];
 const delayed=deferred();let salesDirty=false;
 function element(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,addEventListener(type,fn){this[type]=fn;},querySelector(selector){return {click(){opened.push(selector);}};},showModal(){opened.push('dialog');},close(){opened.push('close');}});return elements.get(id);}
 const document={activeElement:null,getElementById:element,addEventListener(type,fn){handlers[type]=fn;},querySelectorAll(){return [];},querySelector(){return null;}};
 const win={confirm(){return false;},addEventListener(type,fn){windowHandlers[type]=fn;},PcSalesConditions:{mount(){opened.push('sales');return {dirty:()=>salesDirty,processing:()=>false};}},PcCatalogDetail:{mount(host,data){opened.push('mount:'+data.configuration_id);}}};
 const data={configuration_id:'N02',revision:1,observed_date:'2026-10-05',content:{title:'격리 상품',intro:'격리 설명',scene:'격리 상황',facts:{},benefits:[],checks:[],faq:[]},parts:[],offers:[],current_review:{}};
 const fetch=async(url,options)=>{requests.push({url,method:options.method||'GET'});if(url.endsWith('/tasks'))return {ok:true,json:async()=>({items:[]})};if(url.includes('ai-proposals'))return delayed.promise;
  if(detailPending)return delayed.promise;return {ok:!detailError,json:async()=>detailError?{detail:'조회 실패'}:data};};
 vm.runInNewContext(fs.readFileSync('mockups/shared/pc-workspace.js','utf8'),{document,window:win,URLSearchParams,location:{search},fetch});
 const click=dataset=>{const button={dataset,closest:()=>true,hasAttribute:key=>key==='data-generate'&&dataset.generate!==undefined};handlers.click({target:{closest:()=>button}});};
 return {elements,element,handlers,windowHandlers,requests,opened,click,resolve:()=>delayed.resolve({ok:true,json:async()=>data}),setSalesDirty:()=>salesDirty=true};
}
test('workspace opens each requested existing tab after its asynchronous detail succeeds; no writes',async()=>{
 for(const tab of ['parts','copy','review','sales']){
  const h=workspaceHarness('?id=N02&tab='+tab,{detailPending:true});await flush();assert.deepEqual(h.opened,[]);
  h.resolve();await flush();
  if(tab==='sales')assert.deepEqual(h.opened,['sales']);else if(tab==='copy')assert.deepEqual(h.opened,[]);else assert.deepEqual(h.opened,['mount:N02','dialog','[data-tab="'+tab+'"]']);
  assert.ok(h.requests.every(r=>r.method==='GET'));
 }
});
test('failed detail or invalid/duplicate tab never opens a misleading task or writes data',async()=>{
 const failed=workspaceHarness('?id=N02&tab=review',{detailError:true});await flush();assert.deepEqual(failed.opened,[]);assert.equal(failed.element('pcw-message').textContent,'조회 실패');
 for(const query of ['?id=N02&tab=delete','?id=N02&tab=sales&tab=review']){const h=workspaceHarness(query);await flush();assert.deepEqual(h.opened,[]);assert.ok(h.requests.every(r=>r.method==='GET'));}
});
test('workspace return link restores only the fixed readiness route and bounded query fields',async()=>{
 const h=workspaceHarness('?id=N02&from=sale-readiness&sr_scope=configurations&sr_q=SSD%20%26%202TB&sr_offset=40&sr_selected=N02&return=https://evil.example');await flush();
 const html=h.element('pcw-product').innerHTML;assert.match(html,/판매 준비 현황으로 돌아가기/);assert.doesNotMatch(html,/evil\.example/);
 const href=html.match(/href="([^"]+)"/)[1].replaceAll('&amp;','&');assert.deepEqual(readNavigation(new URL(href,origin).search),{scope:'configurations',q:'SSD & 2TB',offset:40,selectedId:'N02'});
 const invalid=workspaceHarness('?id=N02&from=https://evil.example');await flush();assert.doesNotMatch(invalid.element('pcw-product').innerHTML,/판매 준비 현황으로 돌아가기/);
});
test('unsaved copy and sales changes retain beforeunload and detail guards',async()=>{
 const h=workspaceHarness('?id=N02&tab=copy');await flush();
 h.element('pcw-product').input({target:{id:'pcw-title',value:'미저장 변경'}});
 let prevented=false;const event={preventDefault(){prevented=true;}};h.windowHandlers.beforeunload(event);assert.equal(prevented,true);assert.equal(event.returnValue,'');
 h.click({tab:'review'});assert.deepEqual(h.opened,[]);assert.match(h.element('pcw-message').textContent,/저장하거나 되돌린/);
 const sales=workspaceHarness('?id=N02&tab=sales');await flush();sales.setSalesDirty();let salesPrevented=false;sales.windowHandlers.beforeunload({preventDefault(){salesPrevented=true;}});assert.equal(salesPrevented,true);
 sales.click({tab:'review'});assert.deepEqual(sales.opened,['sales']);
});
test('busy AI request retains the navigation guard and cannot open a detail on top',async()=>{
 const h=workspaceHarness('?id=N02&tab=copy');await flush();h.click({generate:''});await flush();
 let prevented=false;h.windowHandlers.beforeunload({preventDefault(){prevented=true;}});assert.equal(prevented,true);
 h.click({tab:'review'});assert.deepEqual(h.opened,[]);assert.equal(h.requests.filter(r=>r.method==='POST').length,1);
});

test('mounted readiness renders the target link and keeps the restored search and selection in the URL',async()=>{
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attrs={};this.handlers={};this.hidden=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.handlers[k]=v;}
  querySelectorAll(){return this.children.flatMap(li=>li.children).filter(n=>n.tag==='button');}
  focus(){}
 }
 const nodes=new Map(),byId=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);};
 const tabs=['configurations','parts'].map((scope,i)=>{const n=byId(i?'srParts':'srConfigurations');n.dataset.scope=scope;return n;});
 const doc={getElementById:byId,createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='.sr-tabs button'?tabs:[]};
 const replaced=[],requests=[];
 const item={id:'N02',code:'N02',name:'격리 PC',state:'needs_check',checks:[],reasons:[{key:'sales:os',label:'운영체제 미확인',detail:'격리 근거',severity:'unknown',href:'/admin2/pc-workspace?id=N02'}],href:'/admin2/pc-workspace?id=N02'};
 const win={location:{origin,search:'?scope=configurations&q=PC&offset=40&selected=N02'},history:{replaceState(a,b,url){replaced.push(url);}},matchMedia:()=>({matches:false}),addEventListener(){},fetch:async url=>{requests.push(url);return {ok:true,json:async()=>url.includes('?')?{scope:'configurations',limit:40,offset:40,total:41,counts:{needs_work:0,needs_check:41,basis_met:0,excluded:0},items:[item]}:item};}};
 const controller=mount(doc,win);await flush();
 assert.equal(byId('srSearch').value,'PC');assert.equal(controller.state.selectedId,'N02');
 assert.match(replaced.at(-1),/scope=configurations&q=PC&offset=40&selected=N02/);
 const descendants=n=>[n,...n.children.flatMap(descendants)];
 const action=descendants(byId('srDetail')).find(n=>n.tag==='a'&&n.attrs['aria-label']==='운영체제 미확인 · 작업 화면 열기');
 assert.ok(action);assert.equal(new URL(action.href,origin).searchParams.get('tab'),'sales');
 assert.equal(requests.length,2);
});
