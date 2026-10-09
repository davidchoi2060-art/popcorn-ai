const {chromium}=require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright');
const out=process.argv[2],B='http://localhost:8767';
const label=async(p,txt)=>p.evaluate(t=>{const d=document.createElement('div');d.textContent=t;d.style.cssText='position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#222;color:#fff;font:12px/1.5 monospace;padding:4px 8px;opacity:.9';document.body.appendChild(d);},txt);
(async()=>{const b=await chromium.launch();const log=[];
async function page(w,h){const p=await b.newPage({viewport:{width:w,height:h}});p.errs=[];p.on('console',m=>{if(m.type()==='error')p.errs.push(m.text())});p.on('pageerror',e=>p.errs.push('PAGEERR '+e.message));p.on('response',r=>{if(r.status()>=400)p.errs.push(r.status()+' '+r.url())});return p;}
const src=(w,h,fx)=>`CODE/MOCK · head 5a4c7b9 · fixture ${fx} · viewport ${w}x${h} · 실데이터 아님`;
// media
for(const [w,h] of [[1440,2300],[390,5200]]){const p=await page(w,h);await p.goto(B+'/admin2/pc-media?id=FX-P1');await p.waitForSelector('.pca-job');await p.waitForTimeout(500);
 await p.evaluate(()=>document.querySelectorAll('.pca-job.selected details').forEach(d=>d.open=true));
 await label(p,src(w,h,'media.json (3 ready cards, 2번 선택됨, 출처 펼침)'));
 await p.screenshot({path:`${out}/media-${w}-full.png`});
 const sel=await p.evaluate(()=>[...document.querySelectorAll('.pca-job button')].map(b=>b.textContent+(b.disabled?'(disabled)':'')));
 log.push({shot:`media-${w}-full.png`,errors:p.errs,buttons:sel,hscroll:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});await p.close();}
// floors
for(const [w,h] of [[1440,1400],[390,2600]]){const p=await page(w,h);await p.goto(B+'/admin2/usage-floors');await p.waitForSelector('.uf-btn-change');await p.waitForTimeout(400);
 const fx=f=>src(w,h,f);
 await p.click('.uf-btn-change[data-floor-id="1"]');await p.waitForSelector('#expValueInput');
 const before=await p.evaluate(()=>({save:document.querySelector('#expSaveBtn').disabled,label:document.querySelector('#expSaveBtn').textContent}));
 await p.fill('#expValueInput','650');await p.dispatchEvent('#expValueInput','input');
 await p.click('#expPreviewBtn');await p.waitForTimeout(600);
 const after=await p.evaluate(()=>({save:document.querySelector('#expSaveBtn').disabled,label:document.querySelector('#expSaveBtn').textContent,preview:(document.querySelector('.uf-exp-preview-text')||{}).textContent}));
 if(w<768){await p.evaluate(()=>{const t=document.querySelector('.uf-tablewrap');t.scrollLeft=t.scrollWidth;});}
 await p.evaluate(()=>{const t=document.querySelector('.uf-tablewrap');const r=document.querySelector('.uf-row.on');if(r)t.scrollTop=r.offsetTop-60;});
 await label(p,fx('floors.json + floor-preview.json (행 1 펼침 · 550→650 미리보기)'+(w<768?' · 표 오른쪽 끝으로 가로 스크롤':'')));
 await p.screenshot({path:`${out}/floors-${w}-expanded.png`});
 const btn=await p.evaluate(()=>{const b=document.querySelector('.uf-btn-change[data-floor-id="1"]').getBoundingClientRect();return {x:Math.round(b.x),w:Math.round(b.width),right:Math.round(b.right),vw:innerWidth};});
 log.push({shot:`floors-${w}-expanded.png`,errors:p.errs,saveBeforePreview:before,saveAfterPreview:after,actionButtonRect:btn,hscroll:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});await p.close();}
require('fs').writeFileSync(out+'/evidence.json',JSON.stringify(log,null,1));console.log(JSON.stringify(log,null,1));await b.close();})();
