// 고객단(mvp3) 카드별 클릭 검수 — 일회용. 개발 서버 공개 화면만 고객처럼 누른다.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const BASE='https://popcornai.co.kr';
const ENTRY=process.env.ENTRY,VP=process.env.VP,OUT=process.env.OUT;
fs.mkdirSync(OUT,{recursive:true});
const P={
  game:{name:'게임용 학생',first:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.',answers:['FHD 144Hz 모니터 써요.','그냥 추천해 주세요.','네, 그 조건으로 보여 주세요.']},
  video:{name:'영상 편집자',first:'프리미어로 4K 유튜브 영상을 편집해요. 예산은 250만원이에요.',answers:['새로 사려고 해요. 추천해 주세요.','그냥 추천해 주세요.','네, 보여 주세요.']},
  videoUp:{name:'영상 편집자',first:'프리미어로 4K 편집하는데 지금 PC가 너무 느려요. i5-9400F, GTX1660, 램 16GB예요. 100만원 안에서 업그레이드하고 싶어요.',answers:['그래픽카드랑 램 위주로 바꾸고 싶어요.','새 PC로 사는 것도 괜찮아요. 250만원까지 추천해 주세요.','그냥 추천해 주세요.']},
  office:{name:'사무용 사장님',first:'사무실 직원용 PC가 필요해요. 엑셀이랑 문서 작업만 하고 한 대 80만원 이하로요.',answers:['한 대 기준으로 먼저 보여 주세요.','그냥 추천해 주세요.','네.']},
  officeParts:{name:'사무용 사장님',first:'사무용은 CPU i3랑 i5 차이가 큰가요? 엑셀이랑 문서 작업용으로 한 대 80만원 이하요.',answers:['그럼 그 조건으로 PC 추천해 주세요.','그냥 추천해 주세요.','네.']},
};
const ENTRIES={
  new_pc:{label:'카드1 새 PC 고르기',persona:'game'},
  upgrade:{label:'카드2 쓰던 PC 업그레이드',persona:'videoUp'},
  parts:{label:'카드3 부품·구성 알아보기',persona:'officeParts'},
  chat:{label:'처음 화면 채팅창',persona:'video'},
  talk:{label:'편하게 상담하기',persona:'office'},
  root:{label:'경로 없는 주소',persona:null},
};
const E=ENTRIES[ENTRY],persona=E.persona?P[E.persona]:null;
const rows=[],turns=[],extra={};let shotN=0;
const tag=ENTRY+'-'+VP;
function row(step,ok,symptom,shot){rows.push({entry:E.label,persona:persona?.name||'-',viewport:VP,step,ok,symptom:symptom||'',shot:shot||''});console.log((ok===true?'O':ok===false?'X':'-'),step,symptom||'');}
async function shot(page,name){const f=tag+'-'+String(++shotN).padStart(2,'0')+'-'+name+'.png';await page.screenshot({path:path.join(OUT,f),fullPage:true}).catch(()=>{});return f;}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function visibleText(page,sel){return page.$$eval(sel,els=>els.filter(e=>e.offsetParent!==null||getComputedStyle(e).position==='fixed').map(e=>e.innerText.trim())).catch(()=>[]);}
async function talkIdle(page,timeout=120000){
  await page.waitForFunction(()=>document.querySelector('#tk-send')?.disabled,null,{timeout:4000}).catch(()=>{});
  await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled&&document.querySelector('#tk-status').hidden;},null,{timeout});
  await sleep(400);
}
async function openNow(page){
  const t=page.locator('[data-action="toggle-now"]');
  if(await t.isVisible().catch(()=>false)&&!(await page.$eval('#tk-now',e=>e.classList.contains('is-open')))){await t.click();await sleep(300);}
}
async function logSnapshot(page){
  return page.evaluate(()=>{
    const kids=[...document.querySelectorAll('#tk-log > *')];
    return kids.map(k=>({kind:k.classList.contains('tk-cards')?'cards':k.classList.contains('is-user')?'user':k.classList.contains('is-ai')?'ai':k.className,text:k.innerText.trim().slice(0,1500),past:k.classList.contains('is-past')}));
  });
}
async function cardInfo(page){
  return page.$$eval('.tk-cards:not(.is-past) .tk-card',cs=>cs.map(c=>({pill:c.querySelector('.pill')?.innerText.trim(),name:c.querySelector('h4')?.innerText.trim(),group:c.closest('.tk-cards').querySelector('.tk-group')?.innerText.trim()||null,price:c.querySelector('.tk-price strong')?.innerText.trim(),gap:[...c.querySelectorAll('p.muted,p.warn-text')].map(p=>p.innerText.trim()).filter(t=>/예산/.test(t))[0]||null,spec:[...c.querySelectorAll('.tk-spec div')].map(d=>d.innerText.replace(/\s+/g,' ').trim()),reason:c.querySelector('.tk-reason')?.innerText.trim()||null,photo:!!c.querySelector('.tk-photo img')})));
}
async function send(page,text,n){
  const t0=Date.now();
  await page.fill('#tk-input',text);await page.press('#tk-input','Enter');
  await talkIdle(page);
  return Date.now()-t0;
}
async function afterTurn(page,n,sent,ms){
  const snap=await logSnapshot(page);
  // 이번 턴: 마지막 user 뒤 항목
  let i=snap.map(x=>x.kind).lastIndexOf('user');const after=snap.slice(i+1);
  const ai=after.filter(x=>x.kind==='ai').map(x=>x.text);
  const cardsIdx=after.findIndex(x=>x.kind==='cards'&&!x.past);
  const aiBefore=cardsIdx>0&&after.slice(0,cardsIdx).some(x=>x.kind==='ai');
  const aiAfter=cardsIdx>=0&&after.slice(cardsIdx+1).some(x=>x.kind==='ai');
  const qs=ai.join(' ').split(/[?？]/).length-1;
  const cards=cardsIdx>=0?await cardInfo(page):[];
  const err=after.filter(x=>/is-error/.test(x.kind)).map(x=>x.text);
  const t={turn:n,sent,ms,ai,questions:qs,cards:cards.length,cardsEmpty:cardsIdx>=0&&!cards.length?after[cardsIdx].text:null,aiAboveCards:cardsIdx>=0?aiBefore:null,aiBelowCards:aiAfter,error:err,cardDetail:cards};
  turns.push(t);return t;
}
async function talkConversation(page,firstAlreadySent,firstText){
  let n=1,t;
  if(firstAlreadySent){await talkIdle(page,120000).catch(()=>{});t=await afterTurn(page,n,firstText,null);}
  else{const ms=await send(page,firstText);t=await afterTurn(page,n,firstText,ms);}
  const s1=await shot(page,'turn1');
  row('첫 턴 답변 (턴 '+n+')',t.error.length?false:t.ai.length>0,(t.ai.length?'AI 답 있음':'AI 답 없음')+' · 되묻기 '+t.questions+'개'+(t.cards?' · 카드 '+t.cards+'장':'')+(t.ms?' · '+Math.round(t.ms/1000)+'초':'')+(t.error.length?' · 오류: '+t.error.join(' / ').slice(0,200):''),s1);
  const qa=persona.answers.slice();
  while(!t.cards&&qa.length&&n<4&&!t.error.length){
    n++;const a=qa.shift();const ms=await send(page,a);t=await afterTurn(page,n,a,ms);
    row('되묻기에 답 (턴 '+n+': 「'+a+'」)',t.error.length?false:t.ai.length>0,'되묻기 '+t.questions+'개'+(t.cards?' · 카드 '+t.cards+'장':' · 카드 없음')+' · '+Math.round(ms/1000)+'초'+(t.error.length?' · 오류: '+t.error.join(' / ').slice(0,200):''),await shot(page,'turn'+n));
  }
  const multiQ=turns.filter(x=>x.questions>1);
  row('되묻기 한 턴에 하나 이하',multiQ.length===0,multiQ.length?multiQ.map(x=>'턴 '+x.turn+'에 물음표 '+x.questions+'개').join(', '):'모든 턴 물음표 1개 이하');
  return t;
}
(async()=>{
  const browser=await chromium.launch();
  const ctx=await browser.newContext(VP==='PC'?{viewport:{width:1440,height:1000},locale:'ko-KR',timezoneId:'Asia/Seoul'}:{viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:2,locale:'ko-KR',timezoneId:'Asia/Seoul',userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'});
  const page=await ctx.newPage();
  const errs=[];page.on('pageerror',e=>errs.push('pageerror: '+e.message));page.on('console',m=>{if(m.type()==='error')errs.push('console: '+m.text().slice(0,200));});
  page.on('dialog',d=>{extra.dialogs=(extra.dialogs||[]).concat(d.message());d.accept();});
  const apiLog=[];page.on('response',r=>{const u=r.url();if(u.includes('/api/'))apiLog.push({at:new Date().toISOString(),method:r.request().method(),url:u.replace(BASE,''),status:r.status()});});
  try{
    if(ENTRY==='root'){
      for(const u of ['/','/mvp3/','/mvp3/index.html','/mvp3/index.html#welcome','/mvp3/talk.html']){
        const res=await page.goto(BASE+u,{waitUntil:'networkidle',timeout:60000}).catch(e=>null);await sleep(800);
        const h=await visibleText(page,'h1');const ask=await page.getByText('어떤 PC를 찾으세요?').first().isVisible().catch(()=>false);
        row('주소 '+u+' 열기',res?res.status()<400:false,'최종 주소 '+page.url().replace(BASE,'')+' · 상태 '+(res?res.status():'실패')+' · 보이는 제목 「'+h.join(' / ')+'」 · 「어떤 PC를 찾으세요?」 '+(ask?'보임':'안 보임'),await shot(page,'addr'+u.replace(/[^a-z0-9]+/gi,'_')));
      }
      return;
    }
    await page.goto(BASE+'/mvp3/index.html',{waitUntil:'networkidle',timeout:60000});
    const gh=await visibleText(page,'h1');
    row('처음 화면 열기',gh.length>0,'제목 「'+gh.join(' / ')+'」 · 「어떤 PC를 찾으세요?」 '+((await page.getByText('어떤 PC를 찾으세요?').first().isVisible().catch(()=>false))?'보임':'안 보임'),await shot(page,'gateway'));
    let first=persona.first,already=false;
    if(['new_pc','upgrade','parts'].includes(ENTRY)){
      await page.click('button[data-start="'+ENTRY+'"]');await page.waitForURL(/talk\.html/,{timeout:20000});await sleep(1000);
      const v=await page.inputValue('#tk-input');const label=await page.$eval('.demo-label',e=>e.innerText).catch(()=>'');
      row('카드 누르기 → 대화 화면',/talk\.html/.test(page.url())&&v.length>0,'대화 화면으로 이동 · 입력창 초안 「'+v+'」 · 상단 「'+label+'」',await shot(page,'card-click'));
      first=v.trim()+' '+persona.first;
    }else if(ENTRY==='chat'){
      await page.fill('#gateway-text',persona.first);await page.click('#gateway-chat button[type=submit]');
      await page.waitForURL(/talk\.html/,{timeout:20000});already=true;
      row('채팅창에 쓰고 보내기 → 대화 화면',/talk\.html/.test(page.url()),'대화 화면으로 이동, 글이 자동으로 보내지는지 확인');
    }else if(ENTRY==='talk'){
      await page.click('.gateway-talk-link');await page.waitForURL(/talk\.html/,{timeout:20000});await sleep(800);
      const h=await visibleText(page,'h1');
      row('「편하게 상담하기」 누르기 → 대화 화면',/talk\.html/.test(page.url()),'제목 「'+h.join(' / ')+'」 · 시작 단추 '+(await page.$$('#tk-starters button')).length+'개',await shot(page,'talk-open'));
    }
    const t=await talkConversation(page,already,first);
    if(ENTRY==='chat'){const u=turns[0];row('채팅창 글 자동 전송',!!(u&&u.ai.length),u&&u.ai.length?'보낸 글이 첫 메시지로 나가고 답이 옴':'자동 전송 안 됨');}
    const label=await page.$eval('.demo-label',e=>e.innerText).catch(()=>'');extra.flowLabel=label;
    if(!t.cards){
      row('추천 카드 나옴',false,'턴 '+turns.length+'까지 카드 없음'+(t.cardsEmpty?' · 빈 카드 안내: '+t.cardsEmpty.slice(0,150):''),await shot(page,'no-cards'));
    }else{
      const c=t.cardDetail;
      row('추천 카드 나옴',true,c.length+'장 · '+c.map(x=>x.name+' '+x.price).join(' / '));
      row('AI 설명이 카드 위',t.aiAboveCards===true&&!t.aiBelowCards,t.aiAboveCards?(t.aiBelowCards?'카드 아래에도 AI 말풍선 있음':'설명 → 카드 순서'):'카드 위 AI 설명 없음');
      const usage=c.every(x=>x.group||/게임|편집|사무|문서|작업|용/.test((x.reason||'')+(x.pill||'')));
      row('카드에 용도 보임',usage,c.map(x=>'['+(x.group||'용도 머리 없음')+'] 꼬리표 「'+(x.pill||'-')+'」 · 이유 「'+(x.reason||'-').slice(0,60)+'」').join(' / '));
      const level=c.every(x=>x.pill&&!/^판매 중 PC$/.test(x.pill));
      row('카드에 작업 수준 보임',level,c.map(x=>'꼬리표 「'+(x.pill||'-')+'」 · 사양 '+x.spec.length+'줄').join(' / '));
      row('카드에 예산 차이 보임',c.every(x=>x.gap),c.map(x=>x.gap||'예산 문구 없음').join(' / '));
      // 이 구성 선택
      await page.locator('.tk-cards:not(.is-past) [data-action="choose"]').first().click();await sleep(800);
      await openNow(page);
      const now=await page.$eval('#tk-now-body',e=>e.innerText).catch(()=>'');
      row('이 구성 선택 → 지금 견적',/지금 선택한 구성/.test(now),now.split('\n').slice(0,4).join(' · ').slice(0,200),await shot(page,'chosen'));
      const priceBefore=await page.$eval('#tk-now-body .tk-price strong',e=>e.innerText).catch(()=>null);
      // 부품 바꾸기 → 기존 상세
      await page.locator('#tk-now-body [data-action="open-detail"][data-focus="parts"]').click();
      await page.waitForURL(/index\.html#detail/,{timeout:20000}).catch(()=>{});
      await page.waitForSelector('[data-action="build-options"], .public-bom-empty',{timeout:60000}).catch(()=>{});await sleep(1200);
      const back=await page.locator('#back-to-talk').isVisible().catch(()=>false);
      const ask=await page.getByText('어떤 PC를 찾으세요?').first().isVisible().catch(()=>false);
      const s=await shot(page,'detail');
      row('부품 바꾸기 → 상세 화면',/#detail/.test(page.url()),'주소 '+page.url().replace(BASE,'')+' · 「대화로 돌아가기」 '+(back?'보임':'안 보임')+' · 왼쪽 「어떤 PC를 찾으세요?」 '+(ask?'보임':'안 보임'),s);
      extra.detailAskVisible=ask;
      const opts=page.locator('[data-action="build-options"]:not([disabled])');
      const nOpts=await opts.count();
      if(!nOpts){row('부품 변경 단추',false,'바꿀 수 있는 줄 없음 · '+((await visibleText(page,'.public-bom-empty')).join(' ')||''));}
      else{
        let target=page.locator('[data-action="build-options"][aria-label*="그래픽"]:not([disabled])');
        if(!(await target.count()))target=page.locator('[data-action="build-options"][aria-label*="메모리"]:not([disabled])');
        if(!(await target.count()))target=opts;
        const which=await target.first().getAttribute('aria-label');
        await target.first().scrollIntoViewIfNeeded();await target.first().click();
        await page.waitForFunction(()=>{const p=document.querySelector('.build-options-row .part-options');return p&&!/중이에요/.test(p.innerText);},null,{timeout:60000}).catch(()=>{});
        const panel=await page.$eval('.build-options-row .part-options',e=>e.innerText).catch(()=>'패널 없음');
        const picks=page.locator('[data-action="build-pick"]');const np=await picks.count();
        row('「변경」 → 바꿀 부품 목록 ('+which+')',np>0,'후보 '+np+'개 · 안내 「'+panel.split('\n').slice(1,2).join('')+'」',await shot(page,'build-options'));
        if(np){
          const totalBefore=await page.$eval('#actions strong',e=>e.innerText).catch(()=>null);
          await picks.first().click();
          await page.waitForFunction(()=>!document.querySelector('.part-options')||!/중이에요/.test(document.querySelector('.part-options')?.innerText||''),null,{timeout:60000}).catch(()=>{});await sleep(1500);
          const totalAfter=await page.$eval('#actions strong',e=>e.innerText).catch(()=>null);
          const foot=await page.$eval('.final-table tfoot',e=>e.innerText.replace(/\s+/g,' ')).catch(()=>'');
          const changed=await page.$$eval('tr.build-changed',r=>r.map(x=>x.innerText.replace(/\s+/g,' ').slice(0,160)));
          const viewText=await page.$eval('#view',e=>e.innerText).catch(()=>'');
          const budgetLine=(viewText.match(/예산(보다|과)[^\n]*/)||[null])[0];
          const status=(viewText.match(/[^\n]*(호환|확인)[^\n]*/g)||[]).filter(x=>!/조립 검수|재확인|구매 전/.test(x)).slice(0,3);
          const err=(await visibleText(page,'[role=alert]')).join(' / ');
          row('부품 바꾸기 결과: 바뀐 줄',changed.length>0,changed.join(' / ')||('바뀐 줄 없음'+(err?' · 오류: '+err:'')),await shot(page,'build-picked'));
          row('부품 바꾸기 결과: 새 총액',!!(totalAfter&&totalAfter!==totalBefore&&/바꾼 구성 금액/.test(foot)),'하단 금액 '+totalBefore+' → '+totalAfter+' · 표 아래 「'+foot+'」');
          row('부품 바꾸기 결과: 예산 차이',!!budgetLine,budgetLine||'상세 화면에 예산 대비 문구 없음');
          row('부품 바꾸기 결과: 확인 상태',status.length>0,status.join(' / ')||'호환·확인 상태 문구 없음');
          extra.detailText=viewText.slice(0,6000);
        }
      }
      // 대화로 돌아가기
      if(await page.locator('#back-to-talk').isVisible().catch(()=>false)){
        await page.click('#back-to-talk');await page.waitForURL(/talk\.html/,{timeout:20000}).catch(()=>{});await sleep(1500);
        await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled;},null,{timeout:60000}).catch(()=>{});
        await openNow(page);
        const msgs=(await logSnapshot(page)).filter(x=>x.kind==='user').length;
        const now2=await page.$eval('#tk-now-body',e=>e.innerText).catch(()=>'');
        const p2=await page.$eval('#tk-now-body .tk-price strong',e=>e.innerText).catch(()=>null);
        row('「대화로 돌아가기」',/talk\.html/.test(page.url())&&msgs>=1,'대화 화면 복귀 · 내 말 '+msgs+'개 남음 · 지금 견적 금액 '+priceBefore+' → '+p2+(/바꾼 부품/.test(now2)?' · 「바꾼 부품」 표시 있음':' · 「바꾼 부품」 표시 없음'),await shot(page,'back-to-talk'));
      }else row('「대화로 돌아가기」',false,'상세 화면에 단추가 안 보임');
      // 견적 저장
      if(/talk\.html/.test(page.url())){
        await openNow(page);
        const save=page.locator('#tk-now-body [data-action="save"]');
        if(await save.count()&&!(await save.isDisabled())){
          await save.click();await talkIdle(page,60000).catch(()=>{});await openNow(page);
          const st=await page.$eval('#tk-now-body .tk-save-state',e=>e.innerText).catch(()=>'');
          row('견적 저장',/저장했어요/.test(st),st,await shot(page,'saved'));
        }else row('견적 저장',false,'저장 단추 없음 또는 눌리지 않음 ('+((await save.count())?await save.innerText():'없음')+')');
        // 쇼핑몰 이동
        const ho=page.locator('#tk-now-body [data-action="handoff"]');
        if(await ho.count()){
          await ho.click();await talkIdle(page,60000).catch(()=>{});await openNow(page);
          const link=page.locator('#tk-now-body a.tk-link');
          if(await link.count()){
            const href=await link.getAttribute('href');
            const [pop]=await Promise.all([ctx.waitForEvent('page',{timeout:20000}).catch(()=>null),link.click()]);
            let mall='';if(pop){await pop.waitForLoadState('domcontentloaded',{timeout:30000}).catch(()=>{});mall=pop.url()+' · 제목 「'+(await pop.title().catch(()=>''))+'」';await pop.screenshot({path:path.join(OUT,tag+'-mall.png')}).catch(()=>{});await pop.close();}
            row('쇼핑몰 이동',!!pop,'링크 '+href+(pop?' → 새 창 '+mall:' · 새 창 안 열림'),tag+'-mall.png');
          }else{const e=(await visibleText(page,'[role=alert]')).join(' / ');row('쇼핑몰 이동',false,'쇼핑몰 링크 안 나옴 '+e.slice(0,200),await shot(page,'handoff-fail'));}
        }else row('쇼핑몰 이동',false,'「쇼핑몰에서 구매 이어가기」 단추 없음(저장 뒤에만 나옴)');
      }
    }
    // 문의 접수
    if(/talk\.html/.test(page.url())){
      await openNow(page);
      const iq=page.locator('#tk-now-body [data-action="inquiry-open"]').first();
      if(await iq.count()){
        await iq.click();await page.waitForSelector('[data-inquiry="phone"]',{timeout:30000}).catch(()=>{});
        if(await page.locator('[data-inquiry="phone"]').count()){
          const topics=await page.$$eval('[data-inquiry="topic"] option',o=>o.map(x=>x.value).filter(Boolean));
          if(topics.length)await page.selectOption('[data-inquiry="topic"]',topics[0]);
          await page.fill('[data-inquiry="name"]','QA-카드검수');await page.fill('[data-inquiry="phone"]','010-0000-0000');
          await page.fill('[data-inquiry="message"]','QA 카드 검수 자동 문의입니다('+tag+'). 처리하지 않으셔도 됩니다.');
          await page.check('[data-inquiry="consent"]');
          await page.click('[data-action="inquiry-send"]');
          await page.waitForFunction(()=>/신청 번호|warn-text/.test(document.querySelector('.tk-inquiry')?.innerHTML||''),null,{timeout:60000}).catch(()=>{});
          const box=await page.$eval('.tk-inquiry',e=>e.innerText.replace(/\s+/g,' ')).catch(()=>'');
          row('문의 접수',/신청 번호/.test(box),box.slice(0,200),await shot(page,'inquiry'));
        }else row('문의 접수',false,'문의 양식이 안 열림',await shot(page,'inquiry-fail'));
      }else row('문의 접수',false,'문의 단추 없음');
      // 기존 상담 화면 링크
      const old=await page.$eval('#tk-old',e=>e.getAttribute('href')).catch(()=>null);extra.oldLink=old;
    }
  }catch(e){row('진행 중 멈춤',false,e.message.split('\n')[0].slice(0,250),await shot(page,'crash'));}
  finally{
    extra.pageErrors=errs.slice(0,30);
    fs.writeFileSync(path.join(OUT,tag+'.json'),JSON.stringify({entry:ENTRY,viewport:VP,persona:persona?.name,at:new Date().toISOString(),rows,turns,apiLog,extra},null,2));
    await browser.close();
  }
})();
