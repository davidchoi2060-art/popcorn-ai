// 개발 서버 mvp3 고객 화면을 실제 브라우저로 열어 추천 카드를 캡처한다 — 읽기 전용.
//
// 상담 문장을 화면에 입력해 추천 카드를 띄우고 PC(1440px)·모바일(390px) 캡처를 OUT 에 남긴다.
// 화면이 부르는 고객 API(/api/talk/parse → /api/grid/recommend)만 쓰고, 비밀값·DB 접속은 없다.
// 사진 판정은 브라우저가 실제로 받은 결과(naturalWidth)로 한다 — 응답의 URL만 보고 「있다」고
// 말하지 않는다.
//
// 환경변수
//   BASE   https://popcornai.co.kr
//   CASES  「파일이름=상담 문장」을 | 로 구분 (예: 배그롤150=배그와 롤 150만원|사무용100=사무용 100만원)
//   OUT    캡처를 쓸 폴더
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');

const BASE=(process.env.BASE||'https://popcornai.co.kr').replace(/\/+$/,'');
const OUT=process.env.OUT||'mvp3-captures';
const CASES=(process.env.CASES||'').split('|').map(x=>x.trim()).filter(Boolean).map(x=>{
  const i=x.indexOf('=');return i>0?{name:x.slice(0,i).trim(),text:x.slice(i+1).trim()}:{name:x.replace(/[^\p{L}\p{N}_-]+/gu,''),text:x};
});
if(!CASES.length){console.error('CASES 가 비어 있습니다');process.exit(2);}
fs.mkdirSync(OUT,{recursive:true});

async function loadImages(page){
  // loading="lazy" 사진은 화면에 들어와야 받는다. 카드를 하나씩 보이게 한 뒤 끝날 때까지 기다린다.
  for(const el of await page.$$('.live-product-card'))await el.scrollIntoViewIfNeeded().catch(()=>{});
  await page.waitForFunction(()=>[...document.querySelectorAll('.live-product-card img')].every(i=>i.complete),null,{timeout:30000}).catch(()=>{});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.waitForTimeout(500);
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
  for(const c of CASES)results.push(await capture(browser,c));
  await browser.close();
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),results},null,2));
  const lines=['### mvp3 화면 캡처 ('+BASE+')',''];
  for(const r of results){
    lines.push('**'+r.name+'** — 「'+r.text+'」');
    if(r.alert)lines.push('- 화면 오류 안내: '+r.alert.replace(/\s+/g,' '));
    for(const k of r.cards){
      const ok=k.part_photos.filter(p=>p.loaded).length;
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
