// 상세 왕복 2회째 바꾼 부품이 사라지는 원인 추적용 일회용. 각 단계마다 이 탭의 대화 보관값과 build 요청을 적는다.
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
const BASE='https://popcornai.co.kr',OUT=process.env.OUT;fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const log=[];
(async()=>{
  const b=await chromium.launch();const ctx=await b.newContext({viewport:{width:1440,height:900},locale:'ko-KR'});const page=await ctx.newPage();
  page.on('request',r=>{if(/\/api\/(mvp3|grid)/.test(r.url()))log.push({ev:'req',u:r.url().replace(BASE,''),body:(r.postData()||'').slice(0,1500)});});
  page.on('response',async r=>{if(/\/api\/mvp3\/build/.test(r.url())){let t='';try{t=(await r.text()).slice(0,600);}catch{}log.push({ev:'res',u:r.url().replace(BASE,''),s:r.status(),t});}});
  page.on('console',m=>log.push({ev:'console',t:m.text().slice(0,300)}));
  const store=async step=>{const v=await page.evaluate(()=>{const r=sessionStorage.getItem('popcorn-mvp3-conversation-v1');if(!r)return null;const j=JSON.parse(r);return {bytes:r.length,current:j.current,msgs:j.messages.length};}).catch(e=>'err '+e.message);log.push({ev:'store',step,url:page.url().replace(BASE,''),v});console.log(step,JSON.stringify(v).slice(0,400));};
  const idle=async()=>{await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled&&document.querySelector('#tk-status').hidden;},null,{timeout:150000});await sleep(800);};
  await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await sleep(1500);
  await page.fill('#tk-input','배그랑 롤, 발로란트 해요. 예산은 150만원이에요.');await page.click('#tk-send');await sleep(3000);await idle();
  await page.locator('.tk-cards:not(.is-past) [data-action="detail"]').first().click();await page.waitForSelector('#view .final-table',{timeout:40000});await sleep(1500);await store('1 상세 처음');
  let tg=page.locator('[data-action="build-options"][aria-label*="그래픽"]:not([disabled])');await tg.first().click();
  await page.waitForSelector('[data-action="build-pick"]',{timeout:60000});await page.locator('[data-action="build-pick"]').first().click();await sleep(4000);await store('2 부품 바꾼 뒤');
  for(let k=1;k<=3;k++){
    await page.click('#back-to-talk');await page.waitForURL(/talk\.html/);await sleep(2000);await idle().catch(()=>{});await sleep(1500);await store(k+'회 대화 복귀');
    await page.screenshot({path:path.join(OUT,'dbg-talk-'+k+'.png'),fullPage:true});
    await page.locator('#tk-now-body [data-action="open-detail"]').first().click();await page.waitForURL(/index\.html/);await store(k+'회 상세 이동 직후');
    await page.waitForSelector('#view .final-table',{timeout:40000}).catch(()=>{});await sleep(2500);await store(k+'회 상세 다시 연 뒤');
    log.push({ev:'detail-msgs',k,t:await page.$$eval('#messages .message',ms=>ms.map(m=>m.innerText.slice(0,200))).catch(()=>[])});
    await page.screenshot({path:path.join(OUT,'dbg-detail-'+k+'.png'),fullPage:true});
  }
  fs.writeFileSync(path.join(OUT,'dbg.json'),JSON.stringify(log,null,1));await b.close();
})().catch(e=>{console.log('fail',e.message);fs.writeFileSync(path.join(OUT,'dbg.json'),JSON.stringify(log,null,1));process.exit(0);});
