// 개발 서버 mvp3 고객 화면을 실제 브라우저로 열어 추천 카드를 캡처한다 — 읽기 전용.
//
// 상담 문장을 화면에 입력해 추천 카드를 띄우고 PC(1440px)·모바일(390px) 캡처를 OUT 에 남긴다.
// 화면이 부르는 고객 API(/api/talk/parse → /api/grid/recommend)만 쓰고, 비밀값·DB 접속은 없다.
// 사진 판정은 브라우저가 실제로 받은 결과(naturalWidth)로 한다 — 응답의 URL만 보고 「있다」고
// 말하지 않는다.
//
// 환경변수
//   BASE   https://dev.popcornai.co.kr
//   CASES  「파일이름=상담 문장」을 | 로 구분 (예: 배그롤150=배그와 롤 150만원|사무용100=사무용 100만원)
//   OUT    캡처를 쓸 폴더
//   PAGES  index(옛 상담 화면) · talk(대화 화면 talk.html)를 쉼표로. 기본 「talk」(옛 화면은 #202 뒤 상담창이 걷혀 입력칸을 못 찾는다 -- 필요하면 index 를 직접 준다).
//          대화 화면은 「AI 설명 -> 안내 -> 카드 -> 다음 선택 단추」 순서를 함께 적는다(2026-10-12).
//   QTY    1 이면 대화 화면 카드마다 메모리·저장장치 줄의 수량 한도(/api/mvp3/build/options quantity_limit)를
//          화면이 쓰는 클라이언트로 읽어 적고, 첫 카드의 부품 구성 화면에서 메모리 수량 칸을 캡처한다(2026-10-12 7번).
//          읽기만 한다 -- build/options 는 계산만 하고 저장하지 않는다.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');

const BASE=(process.env.BASE||'https://dev.popcornai.co.kr').replace(/\/+$/,'');
const OUT=process.env.OUT||'mvp3-captures';
const CASES=(process.env.CASES||'').split('|').map(x=>x.trim()).filter(Boolean).map(x=>{
  const i=x.indexOf('=');return i>0?{name:x.slice(0,i).trim(),text:x.slice(i+1).trim()}:{name:x.replace(/[^\p{L}\p{N}_-]+/gu,''),text:x};
});
if(!CASES.length){console.error('CASES 가 비어 있습니다');process.exit(2);}
const QTY=process.env.QTY==='1';
const PAGES=(process.env.PAGES||'talk').split(',').map(x=>x.trim()).filter(x=>x==='index'||x==='talk');
fs.mkdirSync(OUT,{recursive:true});

async function loadImages(page){
  // loading="lazy" 사진은 화면에 들어와야 받는다. 카드를 하나씩 보이게 한 뒤 끝날 때까지 기다린다.
  for(const el of await page.$$('.live-product-card'))await el.scrollIntoViewIfNeeded().catch(()=>{});
  await page.waitForFunction(()=>[...document.querySelectorAll('.live-product-card img')].every(i=>i.complete),null,{timeout:30000}).catch(()=>{});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.waitForTimeout(500);
}

// 대화 화면: 입력창에 문장을 넣어 보내고, 최신 카드·단추와 대화 칸의 차례를 남긴다.
async function captureTalk(browser,c){
  const r={name:c.name+'-대화',text:c.text,cards:[],errors:[],shots:[]};
  const ctx=await browser.newContext({viewport:{width:1440,height:1000},locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page=await ctx.newPage();
  page.on('pageerror',e=>r.errors.push('pageerror: '+e.message));
  page.on('console',m=>{if(m.type()==='error')r.errors.push('console: '+m.text());});
  let reco=null;
  page.on('response',async res=>{if(res.url().endsWith('/api/grid/recommend')&&res.ok()){
    try{reco={state:JSON.parse(res.request().postData()||'{}').state,body:await res.json()};}catch{}}});
  try{
    await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle',timeout:60000});
    await page.fill('#tk-input',c.text);
    await page.press('#tk-input','Enter');
    await page.waitForSelector('.tk-cards:not(.is-past), .tk-msg.is-error',{timeout:90000});
    await page.waitForFunction(()=>!document.querySelector('#tk-send').disabled,null,{timeout:90000}).catch(()=>{});
    await page.waitForTimeout(500);
    r.alert=await page.$eval('.tk-msg.is-error',e=>e.innerText.trim()).catch(()=>null);
    r.order=await page.$$eval('#tk-log > *',els=>els.map(e=>e.classList.contains('tk-cards')?'카드':e.classList.contains('is-user')?'손님':e.classList.contains('is-ai')?'AI: '+e.textContent.trim().slice(0,40):e.className));
    r.buttons=await page.$$eval('.tk-cards:not(.is-past) .tk-next button',bs=>bs.map(b=>b.textContent.trim()));
    r.cards=await page.$$eval('.tk-cards:not(.is-past) .tk-card',cards=>cards.map(card=>({
      tag:card.querySelector('.pill')?.textContent.trim()||null,
      name:card.querySelector('h4')?.textContent.trim()||null,
      fit:card.querySelector('.tk-fit')?.innerText.replace(/\s+/g,' ').trim()||null,
      part_photos:[],broken_images:[...card.querySelectorAll('img')].filter(i=>i.complete&&i.naturalWidth===0).length})));
    // 최신 카드 묶음이 화면 위쪽에 오게 둔다(그 위 안내 말풍선도 보이게 조금 위에서).
    await page.evaluate(()=>{const log=document.querySelector('#tk-log'),last=[...document.querySelectorAll('.tk-cards:not(.is-past)')].pop();
      if(last&&log)log.scrollTop=Math.max(0,last.offsetTop-log.offsetTop-260);});
    const pc=path.join(OUT,r.name+'-PC.png');
    await page.screenshot({path:pc});r.shots.push(pc);
    await page.setViewportSize({width:390,height:900});
    await page.waitForTimeout(300);
    const mobile=path.join(OUT,r.name+'-모바일.png');
    await page.screenshot({path:mobile,fullPage:true});r.shots.push(mobile);
    r.overflow_px=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
    if(QTY&&reco)await captureQuantity(page,r,reco);
  }catch(e){
    r.errors.push('capture: '+e.message.split('\n')[0]);
    const fail=path.join(OUT,r.name+'-실패.png');
    await page.screenshot({path:fail,fullPage:true}).catch(()=>{});
    if(fs.existsSync(fail))r.shots.push(fail);
  }
  await ctx.close();
  return r;
}

// 7번 수량: 카드마다 메모리·저장장치 줄의 한도를 읽고, 첫 카드의 부품 구성 화면에서 메모리 수량 칸을 찍는다.
async function captureQuantity(page,r,reco){
  r.quantity=await page.evaluate(async({state,body})=>{
    const out=[];
    const items=(body.card_sets||[]).filter(g=>g.kind==='sold').flatMap(g=>g.items||[]);
    for(const it of items){
      const parts=it.public_configuration?.parts||[];
      if(!parts.length){out.push({code:it.product_code,bom:false});continue;}
      for(const p of parts.filter(p=>!p.pseudo&&(p.slot==='RAM'||p.slot==='SSD'))){
        try{const o=await window.MVP3Api.buildOptions(state,it.product_code,[],p.ordinal);
          out.push({code:it.product_code,slot:p.slot,quantity:o.quantity,limit:o.quantity_limit});}
        catch(e){out.push({code:it.product_code,slot:p.slot,error:String(e?.message||e).slice(0,80)});}
      }
    }
    return out;
  },reco);
  await page.setViewportSize({width:1440,height:1000});
  const choose=page.locator('.tk-cards:not(.is-past) [data-action=choose]').first();
  if(!await choose.isVisible().catch(()=>false))return;
  await choose.click();
  await page.click('[data-action=open-detail]');
  await page.waitForSelector('.public-bom, #part-change',{timeout:60000});
  const rows=await page.$$eval('[data-action=build-options]',bs=>bs.map(b=>({ordinal:b.dataset.ordinal,label:b.getAttribute('aria-label')})));
  const target=rows.find(x=>/메모리/.test(x.label||''))||rows.find(x=>/저장|SSD/.test(x.label||''));
  if(target){
    await page.click('[data-action=build-options][data-ordinal="'+target.ordinal+'"]');
    await page.waitForSelector('.part-options [data-part-qty], .part-options .warn-text, .part-option-list',{timeout:60000}).catch(()=>{});
    await page.waitForTimeout(500);
  }
  await page.evaluate(()=>(document.querySelector('[data-part-qty]')||document.querySelector('#part-change'))?.scrollIntoView({block:'center'}));
  r.qty_panel=await page.$eval('[data-part-qty]',e=>e.innerText.replace(/\s+/g,' ').trim()).catch(()=>null);
  r.sets_panel=await page.$eval('[data-sets]',e=>e.innerText.replace(/\s+/g,' ').trim()).catch(()=>null);
  const pc=path.join(OUT,r.name+'-수량-PC.png');
  await page.screenshot({path:pc});r.shots.push(pc);
  await page.setViewportSize({width:390,height:900});
  await page.waitForTimeout(300);
  await page.evaluate(()=>(document.querySelector('[data-part-qty]')||document.querySelector('#part-change'))?.scrollIntoView({block:'center'}));
  const mobile=path.join(OUT,r.name+'-수량-모바일.png');
  await page.screenshot({path:mobile});r.shots.push(mobile);
}

async function capture(browser,c){
  const r={name:c.name,text:c.text,cards:[],errors:[],shots:[]};
  const ctx=await browser.newContext({viewport:{width:1440,height:1000},locale:'ko-KR',timezoneId:'Asia/Seoul'});
  const page=await ctx.newPage();
  page.on('pageerror',e=>r.errors.push('pageerror: '+e.message));
  page.on('console',m=>{if(m.type()==='error')r.errors.push('console: '+m.text());});
  try{
    await page.goto(BASE+'/mvp3/index.html',{waitUntil:'networkidle',timeout:60000});
    // 첫 화면에서 고객처럼 「바로 상담하기」를 누른 뒤 문장을 넣는다.
    const direct=page.getByRole('button',{name:/바로 상담하기/}).or(page.getByRole('link',{name:/바로 상담하기/})).first();
    if(await direct.isVisible().catch(()=>false))await direct.click();
    await page.fill('#request',c.text);
    await page.press('#request','Enter');
    await page.waitForSelector('.live-product-card, .live-error',{timeout:90000});
    await loadImages(page);
    r.alert=await page.$eval('.live-error',e=>e.innerText.trim()).catch(()=>null);
    r.cards=await page.$$eval('.live-product-card',cards=>cards.map(card=>{
      const imgs=[...card.querySelectorAll('img[data-product-image], img[data-card-part-image]')];
      return {
        tag:card.querySelector('.pill')?.textContent.trim()||null,
        name:(card.querySelector('.live-product-name')||card.querySelector('h3'))?.textContent.trim()||null,
        main_photo:card.querySelector('[data-product-photo]')?.dataset.imageState||(card.querySelector('img[data-product-image]')?'image':null),
        main_photo_text:card.querySelector('.live-product-image-status:not([hidden])')?.textContent.trim()||null,
        part_photos:[...card.querySelectorAll('.card-part-photos li')].map(li=>({label:li.textContent.trim(),loaded:(li.querySelector('img')?.naturalWidth||0)>0,hidden:li.hidden})),
        spec:[...card.querySelectorAll('.live-card-spec div')].map(d=>d.querySelector('dt')?.textContent.trim()+' '+d.querySelector('dd')?.textContent.trim()),
        broken_images:imgs.filter(i=>i.complete&&i.naturalWidth===0).length
      };
    }));
    const pc=path.join(OUT,c.name+'-PC.png');
    await page.screenshot({path:pc});r.shots.push(pc);
    await page.setViewportSize({width:390,height:900});
    await page.waitForTimeout(300);
    await loadImages(page);
    const mobile=path.join(OUT,c.name+'-모바일.png');
    await page.screenshot({path:mobile,fullPage:true});r.shots.push(mobile);
    r.overflow_px=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
  }catch(e){
    r.errors.push('capture: '+e.message.split('\n')[0]);
    const fail=path.join(OUT,c.name+'-실패.png');
    await page.screenshot({path:fail,fullPage:true}).catch(()=>{});
    if(fs.existsSync(fail))r.shots.push(fail);
  }
  await ctx.close();
  return r;
}

(async()=>{
  const browser=await chromium.launch();
  const results=[];
  for(const c of CASES){
    if(PAGES.includes('index'))results.push(await capture(browser,c));
    if(PAGES.includes('talk'))results.push(await captureTalk(browser,c));
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),results},null,2));
  const lines=['### mvp3 화면 캡처 ('+BASE+')',''];
  for(const r of results){
    lines.push('**'+r.name+'** — 「'+r.text+'」');
    if(r.alert)lines.push('- 화면 오류 안내: '+r.alert.replace(/\s+/g,' '));
    if(r.order)lines.push('- 대화 차례: '+r.order.join(' / '));
    if(r.buttons)lines.push('- 카드 아래 단추: '+(r.buttons.join(' · ')||'없음'));
    if(r.overflow_px)lines.push('- 가로 넘침 '+r.overflow_px+'px');
    for(const q of r.quantity||[])lines.push('- 수량 '+q.code+' '+(q.bom===false?'구성표 미공개':q.slot+' '+(q.error||('지금 '+q.quantity+' · 최대 '+(q.limit?.max??'-')+' · '+(q.limit?.known?'확인':'모름')+' · '+(q.limit?.basis||'')))));
    if(r.qty_panel)lines.push('- 수량 칸: '+r.qty_panel);
    if(r.sets_panel)lines.push('- 대수 칸: '+r.sets_panel);
    for(const k of r.cards){
      const ok=k.part_photos.filter(p=>p.loaded).length;
      if(k.fit!==undefined){lines.push('- '+(k.tag||'')+' · '+(k.fit||'작업 수준 없음')+' · '+(k.name||'')+(k.broken_images?' · 깨진 이미지 '+k.broken_images:''));continue;}
      lines.push('- '+(k.tag||'')+' · '+(k.name||'')+' · 대표 사진 '+(k.main_photo_text||k.main_photo||'없음')+' · 부품 사진 '+ok+'/'+k.part_photos.length+'장 표시'+(k.broken_images?' · 깨진 이미지 '+k.broken_images:''));
    }
    if(!r.cards.length&&!r.alert)lines.push('- 카드 없음');
    for(const e of r.errors)lines.push('- '+e);
    lines.push('');
  }
  const text=lines.join('\n');
  console.log(text);
  if(process.env.GITHUB_STEP_SUMMARY)fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY,text+'\n');
  // 작업 로그·artifact 를 못 받는 곳(클라우드 작업 세션)도 check-run 주석으로 요약을 읽게 한다.
  if(process.env.GITHUB_ACTIONS){
    const blocks=text.split('\n\n').slice(1).filter(b=>b.trim());
    for(const b of blocks){const [head,...rest]=b.split('\n');console.log('::notice title='+head.replace(/[*,:]/g,'').trim()+'::'+rest.join('\n').replace(/%/g,'%25').replace(/\r/g,'%0D').replace(/\n/g,'%0A'));}
  }
  process.exit(results.every(r=>r.cards.length)?0:1);
})();
