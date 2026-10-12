// 코덱스 지적 재현 확인 — 일회용
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
const BASE='https://popcornai.co.kr',OUT=process.env.OUT;fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const res={};
async function idle(p,t=120000){await p.waitForFunction(()=>document.querySelector('#tk-send')?.disabled,null,{timeout:4000}).catch(()=>{});await p.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled&&document.querySelector('#tk-status').hidden;},null,{timeout:t});await sleep(500);}
async function send(p,t){await p.fill('#tk-input',t);await p.press('#tk-input','Enter');await idle(p);}
async function bubbles(p){return p.$$eval('#tk-log .tk-msg.is-ai',e=>e.map(x=>x.innerText.trim()));}
const count=(arr,re)=>arr.filter(x=>re.test(x)).length;
(async()=>{
  const b=await chromium.launch();
  // A: 설명만
  for(const [k,txt] of [['explainA','RAM 16GB랑 32GB 차이만 설명해 주세요. 아직 PC 추천은 필요 없어요.'],['explainB','사무용으로 SSD 500GB와 1TB 차이가 큰가요? 기준만 알려 주세요.']]){
    const c=await b.newContext({viewport:{width:1440,height:1000},locale:'ko-KR'});const p=await c.newPage();
    await p.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await send(p,txt);
    res[k]={text:txt,ai:await bubbles(p),cards:await p.$$eval('.tk-card',e=>e.length)};
    await p.screenshot({path:path.join(OUT,k+'.png'),fullPage:true});await c.close();
  }
  // B: 상세↔대화 왕복, SSD 바꾸기 후 제목·요약
  const c=await b.newContext({viewport:{width:1440,height:1000},locale:'ko-KR'});const p=await c.newPage();
  p.on('dialog',d=>d.accept());
  await p.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await send(p,'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.');
  const log=[];const snap=async(tag)=>{const a=await bubbles(p);log.push({tag,url:p.url().replace(BASE,''),ai_count:a.length,more_q:count(a,/더 싼 PC나|더 높은 사양을 보거나/),refresh:count(a,/새로고침 전/)});};
  await snap('추천 직후');
  await p.locator('[data-action="choose"]').first().click();await sleep(800);
  for(let round=1;round<=2;round++){
    await p.locator('#tk-now-body [data-action="open-detail"][data-focus="parts"]').click();
    await p.waitForURL(/#detail/,{timeout:20000});await p.waitForSelector('[data-action="build-options"]',{timeout:60000});await sleep(1000);
    if(round===1){
      const t=p.locator('[data-action="build-options"][aria-label*="저장"]').first();
      await t.click();await p.waitForSelector('[data-action="build-pick"]',{timeout:60000});
      // 용량 큰 후보(1TB) 고르기
      const opts=await p.$$eval('[data-build-option]',l=>l.map(x=>({code:x.dataset.buildOption,name:x.querySelector('strong').innerText})));
      const pick=opts.find(o=>/1TB|1000GB|1 TB/i.test(o.name))||opts[0];res.ssdPick=pick;
      await p.click('[data-action="build-pick"][data-code="'+pick.code+'"]');await sleep(4000);
      res.detailAfterSwap=await p.$eval('#view',e=>e.innerText.slice(0,900));
      res.detailSpecRows=await p.$$eval('.live-spec-grid div, dl div',d=>d.slice(0,8).map(x=>x.innerText.replace(/\s+/g,' ')));
      await p.screenshot({path:path.join(OUT,'swap-detail.png'),fullPage:true});
    }
    await p.click('#back-to-talk');await p.waitForURL(/talk\.html/);await sleep(2500);await idle(p,60000).catch(()=>{});
    await snap('왕복 '+round+'회 뒤');
    if(round===1){res.nowPanel=await p.$eval('#tk-now-body',e=>e.innerText);await p.screenshot({path:path.join(OUT,'back1.png'),fullPage:true});}
  }
  res.roundtrip=log;
  // 저장 후 쇼핑몰 링크
  const sv=p.locator('#tk-now-body [data-action="save"]');if(await sv.count()){await sv.click();await idle(p,60000).catch(()=>{});}
  const ho=p.locator('#tk-now-body [data-action="handoff"]');if(await ho.count()){await ho.click();await idle(p,60000).catch(()=>{});}
  res.buyBlock=await p.$eval('#tk-now-body',e=>e.innerText).catch(()=>null);
  await p.screenshot({path:path.join(OUT,'handoff.png'),fullPage:true});
  await b.close();fs.writeFileSync(path.join(OUT,'extra.json'),JSON.stringify(res,null,2));console.log(JSON.stringify(res,null,1).slice(0,4000));
})();
