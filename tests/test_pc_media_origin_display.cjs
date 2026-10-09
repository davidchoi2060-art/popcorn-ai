// New browser-render semantics via isolated VM DOM/fetch mocks. No network.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../mockups/shared/pc-media.js'),'utf8');
let passed=0;
function check(name,fn){fn();passed++;console.log('PASS '+name);}
const job=(origin,status='ready',phase='complete',extra={})=>({job_id:'job-'+origin,status,phase,origin_kind:origin,current:true,selected:false,created_at:'2026-10-08T03:00:00Z',updated_at:'2026-10-08T03:00:00Z',model:null,image_url:'/private-authorized-image',staged_available:false,interrupted:false,...extra});
async function render(jobs,extra={}){
 const root={innerHTML:'',addEventListener(){}},nodes={'#media-root':root,'#media-message':{textContent:''},'#media-back':{},'#media-video':{}};
 const state={title:'test',snapshot:{parts:[{slot:'CASE',code:129552,name:'CASE',quantity:1}],cooling:{},notice:'AI 조립 예시 · 실제 출고 사진 아님'},assembly_checks:[],errors:[],provider_ready:true,cloud_ready:true,model:'DEFAULT-CONFIG-MODEL',jobs,...extra};
 let calls=[];
 vm.runInNewContext(source,{document:{querySelector:s=>nodes[s]},location:{search:'?id=P113835'},URLSearchParams,
  fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>state};},setTimeout:()=>0,clearTimeout(){},crypto:{randomUUID(){throw Error('automatic generation forbidden');}}});
 await new Promise(resolve=>setImmediate(resolve));return {html:root.innerHTML,calls};
}
const gallery=html=>html.slice(html.indexOf('<h2>이미지 목록</h2>'));
const articles=html=>gallery(html).match(/<article[\s\S]*?<\/article>/g)||[];
(async()=>{
 let r=await render([job('existing_import'),job('generated'),job(null)]),cards=articles(r.html);
 check('three explicit origin badges',()=>{assert.equal(cards.length,3);assert.match(cards[0],/기존 원본 반입/);assert.match(cards[1],/AI 생성/);assert.match(cards[2],/출처 미확인/);});
 check('gallery neutral filter and no default model replacement',()=>{assert.match(r.html,/aria-label="이미지 필터"/);cards.forEach(c=>assert.doesNotMatch(c,/DEFAULT-CONFIG-MODEL/));assert.match(cards[1],/모델 기록 없음/);});
 check('import model and history separated from registration',()=>{assert.match(cards[0],/이번 등록 모델<\/dt><dd>해당 없음/);assert.match(cards[0],/시각·생성자 기록 없음/);assert.match(cards[0],/2026-10-08 03:00/);assert.match(cards[0],/요청이 기록된 시각/);});
 check('reuse selection publication independent and unknown',()=>{cards.forEach(c=>{assert.match(c,/원본 재사용<\/dt><dd>미확인/);assert.match(c,/고객 공개<\/dt><dd>미확인/);});});
 check('ready current selection still enabled for all origins',()=>cards.forEach(c=>assert.doesNotMatch(c.match(/<button data-select[^>]*>/)[0],/disabled/)));
 check('unknown and imported ready cards do not reuse AI snapshot notice',()=>{for(const index of [0,2]){assert.doesNotMatch(cards[index],/AI 조립 예시 · 실제 출고 사진 아님/);assert.match(cards[index],/실제 출고 사진이 아닙니다/);assert.match(cards[index],/원본 생성 이력은 확인되지 않았습니다/);}});
 check('explicit generated ready retains actual snapshot notice',()=>{assert.match(cards[1],/AI 조립 예시 · 실제 출고 사진 아님/);assert.doesNotMatch(cards[1],/원본 생성 이력은 확인되지 않았습니다/);});
 check('GET only no automatic mutation',()=>{assert.equal(r.calls.length,1);assert.equal(r.calls[0].options.method,'GET');});
 const states=[['generated','running','generation','이미지 생성 중'],['generated','running','storage','생성 이미지 저장 중'],['existing_import','running','import_storage','원본 등록·저장 중'],['existing_import','failed','import_failed','원본 등록 실패'],[null,'running','other','처리 중'],[null,'failed','storage','처리 실패'],['generated','failed','other','생성 처리 실패 · 단계 확인 필요'],['existing_import','failed','other','원본 등록 처리 실패 · 단계 확인 필요'],['generated','unexpected','generation','상태 확인 필요']];
 for(const [origin,status,phase,label] of states){const html=(await render([job(origin,status,phase)])).html;check('safe status '+origin+'/'+status+'/'+phase,()=>assert.ok(articles(html)[0].includes(label)));}
 r=await render([job('existing_import','failed','storage',{staged_available:true,error:'SECRET-EXCEPTION /private/server'})]);
 check('import no general retry or regeneration or exception leak',()=>{assert.doesNotMatch(gallery(r.html),/data-retry|별도 재생성|SECRET-EXCEPTION|private\/server/);});
 r=await render([job(null,'failed','storage',{staged_available:true})]);
 check('unknown no general storage retry',()=>assert.doesNotMatch(gallery(r.html),/data-retry|별도 재생성/));
 r=await render([job('generated','failed','storage',{staged_available:true})]);
 check('generated storage retry stays enabled when existing conditions met',()=>{const b=gallery(r.html).match(/<button data-retry[^>]*>/)[0];assert.doesNotMatch(b,/disabled/);});
 r=await render([job('generated','failed','storage')]);
 check('generated retry disabled if staged unavailable',()=>assert.match(gallery(r.html).match(/<button data-retry[^>]*>/)[0],/disabled/));
 r=await render([job('existing_import','running','import_storage')]);
 check('import busy label',()=>assert.match(r.html,/disabled>원본 등록·저장 진행 중/));
 r=await render([job('generated','running','generation'),job('existing_import','running','import_storage')]);
 check('mixed busy neutral label',()=>assert.match(r.html,/disabled>이미지 작업 진행 중/));
 r=await render([job('generated','ready','complete',{model:'recorded-model'})]);
 check('individual recorded generated model used',()=>assert.match(gallery(r.html),/recorded-model/));
 r=await render([job('existing_import','ready','complete',{selected:true})]);
 check('selected preview neutral and selected separate from public',()=>{assert.match(r.html,/alt="현재 선택된 대표 이미지"/);assert.match(gallery(r.html),/대표 선택<\/dt><dd>선택됨/);assert.match(gallery(r.html),/고객 공개<\/dt><dd>미확인/);assert.match(gallery(r.html).match(/<button data-select[^>]*>/)[0],/disabled/);});
 r=await render([job('generated','running','generation',{interrupted:true})]);
 check('interrupted neutral notice without automatic new request advice',()=>{assert.match(gallery(r.html),/작업 중단 가능 · 상태 확인 필요/);assert.doesNotMatch(gallery(r.html),/별도 생성|새 UUID/);});
 r=await render([job('generated','ready','complete',{model:'<script>SECRET</script>',error:'SECRET-ERROR',actor:'SECRET-ACTOR',import_provenance:{original_ref:'/SECRET-PATH'}})]);
 check('model escaped and raw actor provenance error unused',()=>{assert.match(gallery(r.html),/&lt;script&gt;/);assert.doesNotMatch(gallery(r.html),/<script>|SECRET-ERROR|SECRET-ACTOR|SECRET-PATH/);});
 r=await render([]);check('neutral empty list',()=>assert.match(r.html,/등록된 이미지 없음/));
 r=await render([job(null,'ready','complete',{current:false})]);check('stale ready selection stays disabled',()=>assert.match(gallery(r.html).match(/<button data-select[^>]*>/)[0],/disabled/));
 if(process.argv[2]){const jobs=[];for(const status of ['ready','running','failed'])for(const origin of ['existing_import','generated',null])jobs.push(job(origin,status,status==='ready'?'complete':origin==='existing_import'?(status==='failed'?'import_failed':'import_storage'):'storage',{job_id:'fixture-'+jobs.length}));r=await render(jobs);fs.writeFileSync(path.join(process.argv[2],'rendered-mock-body.html'),r.html);fs.writeFileSync(path.join(process.argv[2],'render-fixture.json'),JSON.stringify(jobs,null,2));}
 console.log('TOTAL '+passed+' PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
