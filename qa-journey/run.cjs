// 고객 여정 끝까지 검수 v2 — 일회용. 테스트시나리오-v2.md 번호대로. 개발 서버 공개 고객 화면만 누른다. 비밀값·DB 접속 없음.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const {S,FOLLOW}=require('./scenarios.cjs');
const BASE='https://popcornai.co.kr';
const OUT=process.env.OUT;fs.mkdirSync(OUT,{recursive:true});
const JOBS=(process.env.SCEN||'').split(',').filter(Boolean); // 'A1' = PC, 'A1@m' = 모바일
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const won=s=>{const m=String(s||'').replace(/,/g,'').match(/(-?\d+)\s*원/);return m?Number(m[1]):null;};
const MOBILE={viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:2,locale:'ko-KR',timezoneId:'Asia/Seoul',userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'};
const PC={viewport:{width:1440,height:900},locale:'ko-KR',timezoneId:'Asia/Seoul'};

async function layout(page){
  return page.evaluate(()=>{
    const vw=innerWidth,vh=innerHeight,sw=document.documentElement.scrollWidth;let L=0,R=0;
    const root=document.querySelector('#view:not([hidden])')||document.querySelector('.tk-layout')||document.body;
    const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
    while((n=w.nextNode())){if(!n.textContent.trim())continue;const r=document.createRange();r.selectNodeContents(n);for(const b of r.getClientRects()){if(!b.width)continue;const mid=vw/2;if(b.right<=mid)L+=b.width*b.height;else if(b.left>=mid)R+=b.width*b.height;else{L+=(mid-b.left)*b.height;R+=(b.right-mid)*b.height;}}}
    const vis=e=>e.offsetParent!==null||getComputedStyle(e).position==='fixed';
    const ctas=[...document.querySelectorAll('button.primary, a.primary')].filter(vis).map(e=>{const b=e.getBoundingClientRect();return {text:e.innerText.trim().slice(0,40),top:Math.round(b.top+scrollY),inFirstView:b.top+scrollY<vh,disabled:!!e.disabled};});
    return {vw,vh,scrollWidth:sw,overflowX:sw>vw+1,docHeight:document.documentElement.scrollHeight,textLeft:Math.round(L),textRight:Math.round(R),ctas};
  });
}

async function runJob(browser,job){
  const [id,m]=job.split('@');const sc=S[id];const mobile=m==='m'||sc.mobileOnly;const MODE=mobile?'모바일':'PC';const tag=id+'-'+MODE;
  const rows=[],turns=[],extra={};let shotN=0;
  const ctx=await browser.newContext(mobile?MOBILE:PC);let page=await ctx.newPage();
  const errs=[],api=[],dialogs=[];
  const wire=p=>{p.on('pageerror',e=>errs.push('pageerror: '+e.message));p.on('console',x=>{if(x.type()==='error')errs.push('console: '+x.text().slice(0,200));});p.on('dialog',d=>{dialogs.push(d.type()+': '+d.message());d.accept();});p.on('response',r=>{const u=r.url();if(u.includes('/api/'))api.push({at:new Date().toISOString(),m:r.request().method(),u:u.replace(BASE,'').split('?')[0],s:r.status()});});};
  wire(page);
  const row=(step,ok,symptom,shots)=>{rows.push({step,ok,symptom:symptom||'',shots:shots||[]});console.log(tag,(ok===true?'O':ok===false?'X':'-'),step,(symptom||'').slice(0,200));};
  const W=mobile?390:1440,H=mobile?844:900;
  async function shots(name,{alt=true}={}){
    const base=tag+'-'+String(++shotN).padStart(2,'0')+'-'+name;const out=[];
    await page.evaluate(()=>window.scrollTo(0,0)).catch(()=>{});await sleep(300);
    const lay=await layout(page).catch(()=>null);
    await page.screenshot({path:path.join(OUT,base+'-첫화면.png')}).catch(()=>{});out.push(base+'-첫화면.png');
    await page.screenshot({path:path.join(OUT,base+'-전체.png'),fullPage:true}).catch(()=>{});out.push(base+'-전체.png');
    let alt390=null;
    if(!mobile&&alt){await page.setViewportSize({width:390,height:844});await sleep(700);alt390=await layout(page).catch(()=>null);await page.screenshot({path:path.join(OUT,base+'-390전체.png'),fullPage:true}).catch(()=>{});out.push(base+'-390전체.png');await page.setViewportSize({width:W,height:H});await sleep(500);}
    extra.layout=(extra.layout||[]).concat({step:name,main:lay,alt390});
    return out;
  }
  const count=(re,method)=>api.filter(a=>re.test(a.u)&&(!method||a.m===method)).length;
  // ---------- 대화 화면 ----------
  async function talkIdle(timeout=150000){
    await page.waitForFunction(()=>document.querySelector('#tk-send')?.disabled,null,{timeout:4000}).catch(()=>{});
    await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled&&document.querySelector('#tk-status').hidden;},null,{timeout});
    await sleep(500);
  }
  const snap=()=>page.evaluate(()=>[...document.querySelectorAll('#tk-log > *')].map(k=>({kind:k.classList.contains('tk-cards')?'cards':k.classList.contains('is-user')?'user':k.classList.contains('is-ai')?'ai':k.className,text:k.innerText.trim().slice(0,3000),html:k.classList.contains('is-user')?k.innerHTML.slice(0,400):undefined,past:k.classList.contains('is-past')})));
  const cardInfo=()=>page.$$eval('.tk-cards:not(.is-past) .tk-card',cs=>cs.map(c=>({pill:c.querySelector('.pill')?.innerText.trim(),fit:c.querySelector('.tk-fit')?.innerText.trim()||null,name:c.querySelector('h4')?.innerText.trim(),group:(()=>{let e=c.closest('ul.tk-card-list');while(e&&(e=e.previousElementSibling)){if(e.matches('h3.tk-group'))return e.innerText.trim();if(e.matches('ul.tk-card-list'))break;}return null;})(),note:(()=>{const u=c.closest('ul.tk-card-list');const n=u?.previousElementSibling;return n&&n.matches('.tk-group-note')?n.innerText.trim():null;})(),price:c.querySelector('.tk-price strong')?.innerText.trim(),gap:[...c.querySelectorAll('p.muted,p.warn-text')].map(p=>p.innerText.trim()).filter(t=>/예산/.test(t))[0]||null,spec:[...c.querySelectorAll('.tk-spec div, .tk-spec li, dl div')].map(d=>d.innerText.replace(/\s+/g,' ').trim())})));
  async function afterTurn(n,sent,ms){
    const s=await snap();const i=s.map(x=>x.kind).lastIndexOf('user');const after=s.slice(i+1);
    const ai=after.filter(x=>x.kind==='ai').map(x=>x.text);const ci=after.findIndex(x=>x.kind==='cards'&&!x.past);
    const cards=ci>=0?await cardInfo():[];
    const t={turn:n,sent:String(sent).slice(0,300),ms,ai,questions:ai.join(' ').split(/[?？]/).length-1,cards,cardsEmptyText:ci>=0&&!cards.length?after[ci].text:null,aiAbove:ci>=0?after.slice(0,ci).some(x=>x.kind==='ai'):null,aiBelow:ci>=0&&after.slice(ci+1).some(x=>x.kind==='ai'),aiBelowText:ci>=0?after.slice(ci+1).filter(x=>x.kind==='ai').map(x=>x.text.slice(0,200)):[],error:after.filter(x=>/is-error/.test(x.kind)).map(x=>x.text),userHtml:s[i]?.html};
    turns.push(t);return t;
  }
  async function talkSend(text){const t0=Date.now();await page.fill('#tk-input',text);await page.press('#tk-input','Enter');await talkIdle().catch(()=>{});return Date.now()-t0;}
  function turnRow(t,label,sh){
    const bad=[];if(t.error.length)bad.push('오류 '+t.error.join(' / ').slice(0,150));
    const all=t.ai.join(' ');if(/정리하지 못했어요/.test(all))bad.push('「정리하지 못했어요」');
    if(/(배틀그라운드|배그|리그 오브 레전드|롤|발로란트)[^.]{0,30}확인된 자료가 없/.test(all))bad.push('유명 게임 「확인된 자료가 없어」');
    if(t.questions>1)bad.push('되묻기 '+t.questions+'개');if(t.ms&&t.ms>60000)bad.push(Math.round(t.ms/1000)+'초');
    row(label,!bad.length&&t.ai.length>0,'AI 답 '+t.ai.length+'개 · 되묻기 '+t.questions+'개 · 카드 '+t.cards.length+'장'+(t.ms?' · '+Math.round(t.ms/1000)+'초':'')+' · 첫 답 「'+(t.ai[0]||'').replace(/\s+/g,' ').slice(0,160)+'」'+(bad.length?' ‖ 문제: '+bad.join('; '):''),sh);
  }
  function judgeCards(t){
    const c=t.cards,need=['game','heavy','edit'].includes(sc.kind),iss=[];
    if(t.aiAbove!==true)iss.push('카드 위 AI 설명 없음');if(t.aiBelow)iss.push('카드 아래 AI 말풍선: 「'+t.aiBelowText.join(' / ').slice(0,120)+'」');
    const firstGroup=c[0]?.group||null;
    c.forEach((x,i)=>{
      if(firstGroup&&x.group!==firstGroup&&/사무/.test(x.group||''))return; // 두 번째 사무용 묶음은 기록만
      const g=x.spec.find(s=>/그래픽|GPU|VGA/i.test(s))||'';
      if(need&&(!g||/내장|없음|UHD|Iris|Radeon Graphics|정보 없음/i.test(g)))iss.push('카드'+(i+1)+' 그래픽카드 없음/내장 「'+(g||'줄 없음')+'」');
      const p=won(x.price);if(sc.budget&&p){const r=p/(sc.budget*10000);if(r>1.15)iss.push('카드'+(i+1)+' 예산의 '+Math.round(r*100)+'%');}
      const why=[x.fit,x.group,x.pill].filter(Boolean).join(' ');
      if(need&&/사무|문서/.test(why)&&!/게임|편집|작업|그래픽/.test(why))iss.push('카드'+(i+1)+' 이유가 사무용 「'+why.slice(0,60)+'」');
      if(sc.kind==='office'&&/고사양 게임|게임 QHD|게임 FHD/.test(why))iss.push('카드'+(i+1)+' 사무용인데 게임 이유');
      if(x.spec.join(' ').includes('정보 없음'))iss.push('카드'+(i+1)+' 「정보 없음」');
    });
    if(need&&/사무/.test(firstGroup||''))iss.push('첫 묶음이 사무용 「'+firstGroup+'」');
    if(sc.budget&&c.length){const ins=c.filter(x=>x.group===firstGroup).map(x=>won(x.price)).filter(p=>p&&p<=sc.budget*10000);const first=won(c[0].price);if(ins.length&&first>sc.budget*10000)iss.push('예산 안 카드가 있는데 첫 카드가 예산 초과');}
    return iss;
  }
  // ---------- 옛 상담 화면(index) ----------
  async function oldIdle(timeout=150000){await sleep(1500);await page.waitForFunction(()=>document.querySelector('#operation-status')?.hidden!==false,null,{timeout}).catch(()=>{});await sleep(800);}
  const oldMsgs=()=>page.$$eval('#messages .message',ms=>ms.map(m=>({who:m.classList.contains('user')?'user':'ai',text:m.innerText.trim().slice(0,2000)})));
  // ---------- 상세 ----------
  async function priceCheck(where){
    const d=await page.evaluate(()=>{
      const rs=[...document.querySelectorAll('#view .final-table tbody tr')].filter(r=>!r.classList.contains('build-options-row')).map(r=>({part:r.querySelector('h4 span')?.innerText.trim()||'',name:r.querySelector('.part-name')?.innerText.trim()||'',desc:r.querySelector('.final-part-description p')?.innerText.trim()||'',price:r.querySelector('.final-part-price')?.innerText.trim()||r.querySelectorAll('td')[1]?.innerText.trim()||''}));
      const foot=[...document.querySelectorAll('#view .final-table tfoot tr')].map(r=>r.innerText.replace(/\s+/g,' ').trim());
      const v=document.querySelector('#view')?.innerText||'';
      return {rows:rs,foot,budgetLine:(v.match(/예산(보다|과) [^\n]*/)||[''])[0],bar:document.querySelector('#actions:not([hidden]) strong')?.innerText||''};
    });
    const sumP=d.rows.reduce((a,r)=>a+(won(r.price)||0),0);
    const totalRow=d.foot.find(f=>/바꾼 구성 금액/.test(f))||d.foot.find(f=>/참고 금액/.test(f))||'';const total=won(totalRow.replace(/.*?금액/,''));
    const etcRow=d.foot.find(f=>/조립|기타/.test(f));const etc=etcRow?won(etcRow):0;const base=won((d.foot.find(f=>/기본 구성 금액/.test(f))||'').replace(/.*?금액/,''));
    const P=[];
    if(total&&sumP&&Math.abs(sumP+(etc||0)-total)>1000)P.push('P2 부품합 '+sumP.toLocaleString()+' + 기타 '+(etc||0).toLocaleString()+' ≠ 총액 '+total.toLocaleString());
    if(total&&etc&&etc/total>0.1)P.push('P3 조립·기타 '+etc.toLocaleString()+'원 = 총액의 '+Math.round(etc/total*100)+'%');
    d.rows.forEach(r=>{if(/포함/.test(r.price)&&/그래픽|CPU|메모리|저장/.test(r.part))P.push('P3 '+r.part+' 금액이 「'+r.price+'」');});
    if(/금액 미확인|정보 없음/.test(d.rows.map(r=>r.price).join(' ')+d.foot.join(' '))||d.rows.some(r=>won(r.price)===0))P.push('P6 금액 빈칸·미확인');
    const bl=d.budgetLine.match(/예산보다 ([\d,]+)원 (낮아요|높아요)/);
    if(bl&&sc.budget&&total){const exp=sc.budget*10000-total;const got=(bl[2]==='낮아요'?1:-1)*won(bl[1]+'원');if(Math.abs(exp-got)>1000)P.push('P5 예산 문구 「'+d.budgetLine+'」 ≠ 계산 '+exp.toLocaleString());}
    if(d.bar&&total&&won(d.bar)!==total)P.push('P1 하단 금액 '+d.bar+' ≠ 표 총액 '+total.toLocaleString());
    extra.parts=(extra.parts||[]).concat(d.rows.map(r=>({where,part:r.part,name:r.name,price:won(r.price),priceText:r.price})));
    extra.prices=(extra.prices||[]).concat({where,sumP,etc,total,base,foot:d.foot,budgetLine:d.budgetLine,issues:P});
    return {...d,sumP,etc,total,P};
  }
  async function analyzeDetail(label){
    await page.waitForSelector('.final-table, .public-bom-empty',{timeout:60000}).catch(()=>{});await sleep(1500);
    const d=await page.evaluate(()=>{
      const rs=[...document.querySelectorAll('#view .final-table tbody tr')].filter(r=>!r.classList.contains('build-options-row')).map(r=>({part:r.querySelector('h4 span')?.innerText.trim()||'',name:r.querySelector('.part-name')?.innerText.trim()||'',desc:r.querySelector('.final-part-description p')?.innerText.trim()||'',price:r.querySelector('.final-part-price')?.innerText.trim()||r.querySelectorAll('td')[1]?.innerText.trim()||''}));
      const foot=[...document.querySelectorAll('#view .final-table tfoot tr')].map(r=>r.innerText.replace(/\s+/g,' ').trim());
      const title=document.querySelector('#view h3, #view .product-summary h3, #view [class*=summary] h3')?.innerText||'';
      const sum=document.querySelector('#view section')?.innerText.slice(0,500)||'';
      const reasons=[...document.querySelectorAll('#view .live-explanation li')].map(l=>l.innerText.trim()).slice(0,8);
      const ask=[...document.querySelectorAll('h1')].some(h=>/어떤 PC를 찾으세요/.test(h.innerText)&&h.offsetParent!==null);
      return {rows:rs,foot,title,sum,reasons,ask,url:location.href};
    });
    const sumP=d.rows.reduce((a,r)=>a+(won(r.price)||0),0);
    const totalRow=d.foot.find(f=>/참고 금액|바꾼 구성 금액/.test(f))||'';const total=won(totalRow.replace(/.*?금액/,''));
    const etcRow=d.foot.find(f=>/조립|기타/.test(f));const etc=etcRow?won(etcRow):0;
    const iss=[];const need=['game','heavy','edit'].includes(sc.kind);
    d.rows.forEach(r=>{if(/정보 없음/.test(r.name+r.desc))iss.push(r.part+' 「정보 없음」');if(!r.name)iss.push((r.part||'?')+' 이름 빈 줄');if(!won(r.price)&&!/포함/.test(r.price))iss.push(r.part+' 금액 「'+r.price+'」');});
    if(need&&d.rows.length&&!d.rows.some(r=>/그래픽/.test(r.part)&&r.name&&!/정보 없음|내장/.test(r.name)))iss.push('그래픽카드 줄 없음/정보 없음');
    if(total&&etc&&etc/total>0.1)iss.push('P3 조립·기타 '+etc.toLocaleString()+'원 = 합계의 '+Math.round(etc/total*100)+'%');
    if(total&&sumP&&Math.abs(sumP+(etc||0)-total)>1000)iss.push('P2 부품합 '+sumP.toLocaleString()+' + 기타 '+(etc||0).toLocaleString()+' ≠ 합계 '+total.toLocaleString());
    if(d.ask)iss.push('옛 상담창 「어떤 PC를 찾으세요?」 보임');
    if(need&&d.reasons.join(' ').match(/사무|문서/)&&!d.reasons.join(' ').match(/게임|편집/))iss.push('추천 이유가 사무용');
    const pc=await priceCheck(label);pc.P.filter(x=>!/^P2|^P3 조립/.test(x)).forEach(x=>iss.push(x));
    extra.detail=(extra.detail||[]).concat({label,...d,sumP,etc,total});
    const sh=await shots(label);
    const lay=extra.layout[extra.layout.length-1];if(lay?.main?.overflowX||lay?.alt390?.overflowX)iss.push('가로 넘침 '+(lay.main.overflowX?lay.main.scrollWidth:lay.alt390.scrollWidth)+'px');
    row(label,d.rows.length>0&&!iss.length,'부품 '+d.rows.length+'줄 · 부품합 '+sumP.toLocaleString()+'원 · 「'+d.foot.join(' / ')+'」'+(iss.length?' ‖ 문제: '+iss.join('; '):''),sh);
    return d;
  }
  async function reopenDetail(label){
    await page.locator('#tk-now-body [data-action="open-detail"]').first().click();await page.waitForURL(/index\.html/,{timeout:20000}).catch(()=>{});
    await page.waitForSelector('#view .final-table',{timeout:30000}).catch(()=>{});await sleep(1500);
    const ok=/#detail/.test(page.url())&&await page.locator('#view .final-table').count()>0;
    if(!ok)row(label,false,'「구성 자세히 보기」를 눌렀는데 상세가 아님 · 주소 '+page.url().replace(BASE,'')+' · 제목 「'+(await page.locator('#view h2:visible').first().innerText().catch(()=>''))+'」',await shots('상세재진입실패'));
    if(!ok){await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'}).catch(()=>{});await sleep(2000);const d=page.locator('.tk-cards:not(.is-past) [data-action="detail"]').first();if(await d.count()){await d.click();await page.waitForURL(/#detail/,{timeout:20000}).catch(()=>{});await page.waitForSelector('#view .final-table',{timeout:30000}).catch(()=>{});await sleep(1500);}row(label+' · 카드 「상세 보기」로 다시 시도',/#detail/.test(page.url()),'주소 '+page.url().replace(BASE,''));}
    return ok;
  }
  async function toFinalAndBuy(){
    const fin=page.locator('#actions [data-action="final"]');
    if(!(await fin.count())){row('S5 최종 견적 확인',false,'상세 아래 「이 견적 저장하기」 없음',await shots('저장없음'));return;}
    const barBefore=won(await page.locator('#actions strong').innerText().catch(()=>''));
    if(sc.op==='buttonspam'){const n0=count(/saved-quotes/,'POST');for(let k=0;k<3;k++)await fin.click({force:true,noWaitAfter:true}).catch(()=>{});await sleep(4000);extra.spamFinal={savePosts:count(/saved-quotes/,'POST')-n0};}
    else await fin.click();
    await page.waitForFunction(()=>/#final/.test(location.hash),null,{timeout:30000}).catch(()=>{});await sleep(1500);
    const keep=page.locator('.final-buttons [data-action="save"]:not([disabled])');
    if(await keep.count()){const n0=count(/saved-quotes/,'POST');if(sc.op==='buttonspam'){for(let k=0;k<3;k++)await keep.click({force:true,noWaitAfter:true}).catch(()=>{});}else await keep.click();await page.waitForFunction(()=>/보관됨|보관되지|미확인/.test(document.querySelector('.save-status')?.innerText||''),null,{timeout:60000}).catch(()=>{});if(sc.op==='buttonspam')extra.spamSave={savePosts:count(/saved-quotes/,'POST')-n0};}
    await sleep(1000);
    const st=await page.locator('.save-status').innerText().catch(()=>'');
    const fp=await priceCheck('최종');
    const sh=await shots('최종견적');const lay=extra.layout[extra.layout.length-1].main;
    const ratio=lay&&lay.textRight?+(lay.textLeft/Math.max(1,lay.textRight)).toFixed(1):null;
    const buyCta=lay?.ctas.find(c=>/쇼핑몰/.test(c.text));
    const iss=[...fp.P];if(barBefore&&fp.total&&barBefore!==fp.total)iss.push('P1 상세 '+barBefore.toLocaleString()+'원 ≠ 최종 '+fp.total.toLocaleString()+'원');if(!/보관됨/.test(st))iss.push('상태 「'+st+'」');if(!mobile&&ratio&&ratio>4)iss.push('왼쪽 쏠림 '+ratio+':1');if(buyCta&&!buyCta.inFirstView)iss.push('구매 단추가 첫 화면 밖('+buyCta.top+'px)');
    row('S5 최종 견적 확인',!iss.length,'총액 '+(fp.total||0).toLocaleString()+'원 · 부품합 '+fp.sumP.toLocaleString()+' · 조립·기타 '+(fp.etc||0).toLocaleString()+' · 상태 「'+st+'」 · 좌:우 글자 '+ratio+':1 · 구매 단추 '+(buyCta?buyCta.top+'px':'없음')+(iss.length?' ‖ 문제: '+iss.join('; '):''),sh);
    if(id==='A1'&&!mobile){const out=[];for(const w of [320,390,1280,1920,2560]){await page.setViewportSize({width:w,height:900});await sleep(700);const l=await layout(page);const f=tag+'-D2-'+w+'.png';await page.screenshot({path:path.join(OUT,f),fullPage:true});out.push(f);extra['D2_'+w]=l;}await page.setViewportSize({width:W,height:H});row('D2 화면 폭별 최종 견적',null,[320,390,1280,1920,2560].map(w=>w+'폭 좌:우 '+(extra['D2_'+w].textLeft/Math.max(1,extra['D2_'+w].textRight)).toFixed(1)+(extra['D2_'+w].overflowX?' 넘침':'')).join(' · '),out);}
    if(sc.op==='reload'){await page.reload({waitUntil:'networkidle'});await sleep(2000);const st2=await page.locator('.save-status').innerText().catch(()=>'');const h=page.url();row('E16 새로고침 · 최종 견적',/#final/.test(h)&&!!st2,'주소 '+h.replace(BASE,'')+' · 상태 「'+st2+'」',await shots('새로고침-최종'));}
    if(sc.op==='rotate'){await page.setViewportSize({width:844,height:390});await sleep(800);const l=await layout(page);const f=await shots('회전-최종',{alt:false});await page.setViewportSize({width:390,height:844});row('E19 회전 · 최종',!l.overflowX,'844×390 넘침 '+(l.overflowX?l.scrollWidth+'px':'없음'),f);}
    const buy=page.locator('.final-buttons [data-action="handoff"]');
    if(!(await buy.count())){row('S6 쇼핑몰 구매 단추',false,'단추 없음 (상태 「'+st+'」)');return;}
    const n0=count(/handoff/,'POST');
    if(sc.op==='buttonspam'){for(let k=0;k<3;k++)await buy.click({force:true,noWaitAfter:true}).catch(()=>{});}else await buy.click();
    await page.waitForSelector('.live-handoff, [role=alert]',{timeout:60000}).catch(()=>{});await sleep(1500);
    const still=await page.locator('.final-buttons [data-action="handoff"]').isVisible().catch(()=>false);
    const panel=await page.evaluate(()=>{const p=document.querySelector('.live-handoff');if(!p)return null;const b=p.getBoundingClientRect();return {text:p.innerText.replace(/\s+/g,' ').slice(0,300),top:Math.round(b.top),inView:b.top<innerHeight&&b.bottom>0};});
    const iss2=[];if(!still&&!(panel&&panel.inView))iss2.push('누른 단추가 사라지고 결과가 화면 밖');if(!panel)iss2.push('결과 칸 안 나옴');
    if(sc.op==='buttonspam'){const k=count(/handoff/,'POST')-n0;extra.spamHandoff={posts:k};if(k>1)iss2.push('연결 요청 '+k+'번');}
    if(panel){const m=panel.text.match(/쇼핑몰 (?:현재 )?가격(?:도|은) ([\d,]+)원/);if(m&&fp.total&&won(m[1]+'원')!==fp.total&&!/달라|고쳤어요/.test(panel.text))iss2.push('P1 쇼핑몰 '+m[1]+'원 ≠ 견적 '+fp.total.toLocaleString()+'원, 차이 안내 없음');}
    row('S6 쇼핑몰 구매 단추',!iss2.length,(still?'단추 남음':'단추 사라짐')+' · 결과 칸 '+(panel?(panel.inView?'화면 안':'화면 밖(아래 '+panel.top+'px)')+' 「'+panel.text.slice(0,140)+'」':'없음')+(iss2.length?' ‖ 문제: '+iss2.join('; '):''),await shots('쇼핑몰단추후',{alt:false}));
    const link=page.locator('.live-handoff a.primary');
    if(await link.count()){const href=await link.getAttribute('href');const [pop]=await Promise.all([ctx.waitForEvent('page',{timeout:20000}).catch(()=>null),link.click()]);let info='';const f=tag+'-99-쇼핑몰.png';if(pop){await pop.waitForLoadState('domcontentloaded',{timeout:30000}).catch(()=>{});await sleep(2000);info=pop.url()+' · 「'+(await pop.title().catch(()=>''))+'」';await pop.screenshot({path:path.join(OUT,f)}).catch(()=>{});await pop.close();}
      row('S7 쇼핑몰 상품 페이지',!!pop,'링크 '+href+(pop?' → '+info:' · 새 창 안 열림'),pop?[f]:[]);}
  }
  // ---------- 진행 ----------
  try{
    if(sc.op==='addresses'){
      for(const u of ['/','/mvp3/','/mvp3/index.html','/mvp3/talk.html']){const res=await page.goto(BASE+u,{waitUntil:'networkidle',timeout:60000}).catch(()=>null);await sleep(800);const h=await page.locator('h1:visible').first().innerText().catch(()=>'');row('D1 주소 '+u,!!res&&res.status()<400&&/mvp3/.test(page.url()),'→ '+page.url().replace(BASE,'')+' · 제목 「'+h+'」',await shots('주소'+u.replace(/[^a-z0-9]+/gi,'_'),{alt:false}));}
      return;
    }
    // S1 첫 화면
    if(sc.entry!=='direct'&&!sc.longText&&sc.op!=='offline'){
      await page.goto(BASE+'/mvp3/#start',{waitUntil:'networkidle',timeout:60000});await sleep(800);
      const l=await layout(page);row('S1 첫 화면',(await page.locator('#gateway-text').isVisible())&&!l.overflowX,'제목 「'+(await page.locator('h1:visible').first().innerText().catch(()=>''))+'」'+(l.overflowX?' ‖ 가로 넘침 '+l.scrollWidth:''),await shots('첫화면'));
    }
    let t=null,old=false;
    // S2 입구
    if(sc.op==='junk'){
      await page.click('#gateway-chat button[type=submit]');await sleep(800);const note=await page.locator('#gateway-chat-status').innerText().catch(()=>'');
      row('E25 첫 화면 빈 입력',/talk\.html/.test(page.url())?false:true,'주소 '+page.url().replace(BASE,'')+' · 안내 「'+note+'」',await shots('빈입력',{alt:false}));
      await page.fill('#gateway-text','                    ');await page.click('#gateway-chat button[type=submit]');await sleep(800);
      row('E25 첫 화면 공백 20개',!/talk\.html/.test(page.url()),'주소 '+page.url().replace(BASE,''));
      await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await sleep(800);const n0=count(/talk\/parse/,'POST');
      await page.fill('#tk-input','');await page.click('#tk-send').catch(()=>{});await sleep(1500);
      row('E25 대화 화면 빈 보내기',count(/talk\/parse/,'POST')===n0,'parse 호출 '+(count(/talk\/parse/,'POST')-n0)+'번');
      let n=0;for(const x of ['?????','😀😀😀','./\\<>!@#$']){n++;const ms=await talkSend(x);t=await afterTurn(n,x,ms);turnRow(t,'E25 「'+x+'」',await shots('잡문'+n,{alt:false}));row('E25 「'+x+'」 카드 없음',!t.cards.length,'카드 '+t.cards.length+'장');}
      return;
    }
    if(sc.op==='offline'){
      await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await sleep(800);
      await page.fill('#tk-input',sc.text);await ctx.setOffline(true);await page.press('#tk-input','Enter');await sleep(15000);
      const sh1=await shots('끊김중',{alt:false});const st=await page.locator('#tk-status').innerText().catch(()=>'');const err=(await snap()).filter(x=>/is-error/.test(x.kind)).map(x=>x.text);
      await ctx.setOffline(false);await sleep(5000);const retry=page.locator('[data-action="retry"]');const hasRetry=await retry.count();
      row('E21 끊긴 동안',err.length>0||/연결|네트워크|다시/.test(st),'상태 「'+st+'」 · 오류 「'+err.join(' / ').slice(0,150)+'」 · 다시 보내기 단추 '+(hasRetry?'있음':'없음'),sh1);
      const n0=count(/talk\/parse/,'POST');if(hasRetry){await retry.first().click();await talkIdle().catch(()=>{});}
      t=await afterTurn(1,sc.text,null);row('E21 다시 연결 뒤',t.ai.length>0&&count(/talk\/parse/,'POST')-n0<=1,'parse '+(count(/talk\/parse/,'POST')-n0)+'번 · 카드 '+t.cards.length+'장 · 내 말 '+(await snap()).filter(x=>x.kind==='user').length+'개',await shots('다시연결',{alt:false}));
      return;
    }
    if(sc.longText){
      await page.goto(BASE+'/mvp3/talk.html',{waitUntil:'networkidle'});await sleep(800);
      const seed='저는 PC 게임을 오래 했어요. 처음엔 스타크래프트를 했고 그다음 리그 오브 레전드, 요즘은 배틀그라운드를 친구들과 해요. ';let s='';while(s.length<sc.longText)s+=seed;s=s.slice(0,sc.longText)+' '+sc.text;
      const ms=await talkSend(s);t=await afterTurn(1,'(긴 글 '+s.length+'자) '+sc.text,ms);const bub=await page.evaluate(()=>{const u=[...document.querySelectorAll('#tk-log .is-user')].pop();return u?Math.round(u.getBoundingClientRect().width):0;});
      turnRow(t,'E24 긴 글 '+s.length+'자',await shots('긴글'));row('E24 말풍선 폭',bub<=W,'말풍선 '+bub+'px / 화면 '+W+'px');
    }else if(sc.entry==='chip'){
      await page.getByRole('button',{name:/용도와 예산부터 고르기/}).click();await sleep(800);
      await page.click('[data-usage="'+sc.usage+'"]');await page.selectOption('#gateway-budget',sc.budgetSel);await sleep(500);
      const sh=await shots('칩선택');await page.click('[data-action="gateway-begin"]');await sleep(1200);
      const draft=await page.inputValue('#request').catch(()=>'');row('S2 칩 → 상담 초안',!!draft,'초안 「'+draft+'」 · 주소 '+page.url().replace(BASE,''),sh);
      if(sc.text)await page.fill('#request',sc.text);
      await page.click('#chat-form button[type=submit]');await oldIdle();old=true;
      let n=1;let msgs=await oldMsgs();row('S2 옛 화면 답 턴1',msgs.some(x=>x.who==='ai'),'AI 「'+(msgs.filter(x=>x.who==='ai').pop()?.text||'').replace(/\s+/g,' ').slice(0,200)+'」',await shots('옛화면대화1'));
      const fq=FOLLOW.slice();while(!(await page.locator('#view [data-action="detail"]').count())&&fq.length){n++;await page.fill('#request',fq.shift());await page.click('#chat-form button[type=submit]');await oldIdle();msgs=await oldMsgs();row('S2 옛 화면 답 턴'+n,true,'AI 「'+(msgs.filter(x=>x.who==='ai').pop()?.text||'').replace(/\s+/g,' ').slice(0,200)+'」',await shots('옛화면대화'+n));}
      extra.oldMessages=msgs;
      const cards=await page.$$eval('#view [data-action="detail"]',bs=>bs.map(b=>(b.closest('article,li,section,div')?.innerText||'').replace(/\s+/g,' ').slice(0,300)));
      extra.oldCards=cards;row('S3 옛 화면 추천 목록',cards.length>0,cards.length+'개 · '+cards.map((c,i)=>(i+1)+') '+c.slice(0,120)).join(' / '),await shots('옛화면카드'));
      if(!cards.length)throw new Error('옛 화면 추천 없음');
      await page.locator('#view [data-action="detail"]').first().click();await sleep(1500);
    }else{
      if(sc.entry==='chat'){
        await page.fill('#gateway-text',sc.text);
        if(sc.op==='sendspam'){for(let k=0;k<5;k++)await page.click('#gateway-chat button[type=submit]',{force:true,noWaitAfter:true}).catch(()=>{});}
        else await page.click('#gateway-chat button[type=submit]');
        await page.waitForURL(/talk\.html/,{timeout:20000});await talkIdle().catch(()=>{});t=await afterTurn(1,sc.text,null);
        if(sc.op==='sendspam')row('E17 첫 화면 보내기 5번 연타',count(/talk\/parse/,'POST')<=1&&(await snap()).filter(x=>x.kind==='user').length===1,'parse '+count(/talk\/parse/,'POST')+'번 · 내 말 '+(await snap()).filter(x=>x.kind==='user').length+'개');
      }else{
        if(sc.entry.startsWith('card:')){await page.click('button[data-start="'+sc.entry.slice(5)+'"]');}
        else if(sc.entry==='talk'){await page.click('.gateway-talk-link');}
        await page.waitForURL(/talk\.html/,{timeout:20000});await sleep(1000);
        if(sc.entry==='talk'){const st=page.locator('[data-action="starter"][data-entry="new_pc"]');if(await st.count())await st.click();}
        const v=(await page.inputValue('#tk-input')).trim();row('S2 입구 → 대화 화면 초안',sc.entry==='talk'||v.length>0,'초안 「'+v+'」 · 자동 전송 '+((await snap()).some(x=>x.kind==='user')?'됨(안 돼야 함)':'안 됨'),await shots('입구'));
        const first=(v?v+' ':'')+sc.text;const ms=await talkSend(first);t=await afterTurn(1,first,ms);
      }
      turnRow(t,'S2 대화 턴1',await shots('대화1'));
      if(sc.follow){const fq=FOLLOW.slice();let n=1;while(!t.cards.length&&fq.length&&!t.error.length){n++;const a=fq.shift();if(sc.op==='sendspam'&&n===2){const n0=count(/talk\/parse/,'POST');await page.fill('#tk-input',a);for(let k=0;k<5;k++)await page.click('#tk-send',{force:true,noWaitAfter:true}).catch(()=>{});await talkIdle().catch(()=>{});t=await afterTurn(n,a,null);row('E17 대화 화면 보내기 5번 연타',count(/talk\/parse/,'POST')-n0<=1,'parse '+(count(/talk\/parse/,'POST')-n0)+'번');}else{const ms=await talkSend(a);t=await afterTurn(n,a,ms);}turnRow(t,'S2 대화 턴'+n+' 「'+a+'」',await shots('대화'+n));}}
      if(sc.op==='sendspam'&&!sc.follow){const n0=count(/talk\/parse/,'POST');await page.fill('#tk-input','FHD 144Hz 모니터 써요.');for(let k=0;k<5;k++)await page.click('#tk-send',{force:true,noWaitAfter:true}).catch(()=>{});await talkIdle().catch(()=>{});const u=(await snap()).filter(x=>x.kind==='user').length;row('E17 대화 화면 보내기 5번 연타',count(/talk\/parse/,'POST')-n0<=1,'parse '+(count(/talk\/parse/,'POST')-n0)+'번 · 내 말 누적 '+u+'개',await shots('연타',{alt:false}));t=await afterTurn(99,'연타',null);}
      for(const [k,a] of (sc.then||[]).entries()){const ms=await talkSend(a);const tt=await afterTurn(turns.length+1,a,ms);turnRow(tt,'S2 이어서 「'+a+'」',await shots('이어서'+(k+1)));if(tt.cards.length||!t.cards.length)t=tt;}
      if(sc.then?.length){const names=turns.map(x=>x.cards.map(c=>c.name+' '+c.price).join(', ')||'(카드 없음)');row('S2 이어서 · 턴별 카드',null,names.map((x,i)=>'턴'+(i+1)+': '+x.slice(0,140)).join(' / '));}
      if(sc.op==='twotabs'){
        const p2=await ctx.newPage();wire(p2);const keep=page;page=p2;await page.goto(BASE+'/mvp3/#start',{waitUntil:'networkidle'});await page.fill('#gateway-text','사무용 80만원 PC 추천해 주세요.');await page.click('#gateway-chat button[type=submit]');await page.waitForURL(/talk\.html/);await talkIdle().catch(()=>{});
        const t2=await afterTurn(1,'(둘째 탭) 사무용 80만원',null);const sh2=await shots('둘째탭',{alt:false});
        if(t2.cards.length){await page.locator('.tk-cards:not(.is-past) [data-action="choose"]').first().click();await sleep(1000);}
        const chosen2=t2.cards[0]?.name||'';page=keep;await page.reload({waitUntil:'networkidle'});await sleep(2500);
        const now1=await page.$eval('#tk-now-body',e=>e.innerText).catch(()=>'');const log1=(await snap()).filter(x=>x.kind==='user').map(x=>x.text);
        row('E20 두 탭',!(chosen2&&now1.includes(chosen2))&&!log1.some(x=>/사무용 80만원/.test(x)),'둘째 탭에서 고른 「'+chosen2.slice(0,60)+'」 · 첫 탭 새로고침 뒤 지금 견적 「'+now1.replace(/\s+/g,' ').slice(0,100)+'」 · 첫 탭 내 말 '+log1.length+'개',sh2.concat(await shots('첫탭새로고침',{alt:false})));
        await p2.close();
      }
      if(sc.expectNoCards){row('C/E 카드 없어야 함',!t.cards.length,'카드 '+t.cards.length+'장');return;}
      if(!t.cards.length){row('S3 카드',false,'카드 없음 '+(t.cardsEmptyText||'').slice(0,200),await shots('카드없음'));return;}
      const iss=judgeCards(t);extra.cards=t.cards;const nextBtns=await page.$$eval('.tk-cards:not(.is-past) [data-action="explore"], .tk-cards:not(.is-past) [data-action="cond-open"]',b=>b.map(x=>x.innerText.trim()));if(/아래에서 골라/.test(t.ai.join(' '))&&!nextBtns.length)iss.push('「아래에서 골라 주세요」인데 고를 단추 없음');extra.nextButtons=nextBtns;
      row('S3 카드',!iss.length,t.cards.map((x,i)=>(i+1)+') ['+(x.group||'-')+'] '+x.name+' '+x.price+' · '+(x.fit||'')+(x.gap?' · '+x.gap:'')).join(' / ')+(iss.length?' ‖ 문제: '+iss.join('; '):''),await shots('카드'));
      if(sc.op==='reload'){await page.reload({waitUntil:'networkidle'});await sleep(2500);const c2=await cardInfo();row('E16 새로고침 · 카드 화면',c2.length===t.cards.length,'카드 '+t.cards.length+' → '+c2.length+'장',await shots('새로고침-카드',{alt:false}));}
      if(sc.op==='rotate'){await page.setViewportSize({width:844,height:390});await sleep(800);const l=await layout(page);const f=await shots('회전-카드',{alt:false});await page.setViewportSize({width:390,height:844});row('E19 회전 · 카드',!l.overflowX,'844×390 넘침 '+(l.overflowX?l.scrollWidth+'px':'없음'),f);}
      if(sc.depth==='cards')return;
      const det=page.locator('.tk-cards:not(.is-past) [data-action="detail"]').first();await det.scrollIntoViewIfNeeded();await det.click();
      await page.waitForURL(/#detail/,{timeout:20000}).catch(()=>{});
    }
    // S4 상세
    const d=await analyzeDetail('S4 상세');
    if(!old&&t){const c0=t.cards[0];const same=d.rows.length&&c0&&(d.sum+d.title).includes(c0.name.slice(0,10));const tot=d.foot.find(f=>/참고 금액/.test(f));row('S4 카드와 같은 상품·금액',!!same&&(!tot||won(tot.replace(/.*금액/,''))===won(c0.price)),'카드 「'+c0.name.slice(0,50)+'」 '+c0.price+' · 상세 「'+(tot||'')+'」');}
    if(sc.op==='backforward'){await page.goBack();await sleep(2500);const u1=page.url();const c=(await cardInfo().catch(()=>[])).length;const sh=await shots('뒤로가기',{alt:false});await page.goForward();await sleep(2500);const u2=page.url();row('E15 뒤로 → 앞으로',/talk\.html/.test(u1)&&c>0&&/#detail/.test(u2),'뒤로 '+u1.replace(BASE,'')+' (카드 '+c+'장) → 앞으로 '+u2.replace(BASE,''),sh.concat(await shots('앞으로가기',{alt:false})));}
    if(sc.op==='reload'){await page.reload({waitUntil:'networkidle'});await sleep(2500);const d2=await page.$$eval('#view .final-table tbody tr',r=>r.length).catch(()=>0);row('E16 새로고침 · 상세',/#detail/.test(page.url())&&d2>0,'주소 '+page.url().replace(BASE,'')+' · 부품 줄 '+d2,await shots('새로고침-상세',{alt:false}));}
    if(sc.op==='rotate'){await page.setViewportSize({width:844,height:390});await sleep(800);const l=await layout(page);const f=await shots('회전-상세',{alt:false});await page.setViewportSize({width:390,height:844});row('E19 회전 · 상세',!l.overflowX,'844×390 넘침 '+(l.overflowX?l.scrollWidth+'px':'없음'),f);}
    if(sc.depth==='detail')return;
    // A 추가 조작
    if(sc.changePart){
      let tg=page.locator('[data-action="build-options"][aria-label*="그래픽"]:not([disabled])');if(!(await tg.count()))tg=page.locator('[data-action="build-options"][aria-label*="메모리"]:not([disabled])');if(!(await tg.count()))tg=page.locator('[data-action="build-options"]:not([disabled])');
      if(await tg.count()){const which=await tg.first().getAttribute('aria-label');await tg.first().scrollIntoViewIfNeeded();await tg.first().click();
        await page.waitForFunction(()=>{const p=document.querySelector('.build-options-row .part-options');return p&&!/중이에요/.test(p.innerText);},null,{timeout:60000}).catch(()=>{});
        const picks=page.locator('[data-action="build-pick"]');const np=await picks.count();const sh=await shots('변경후보',{alt:false});
        if(np){const before=d.title;await picks.first().click();await sleep(3000);const after=await page.evaluate(()=>({title:document.querySelector('#view h3')?.innerText||'',changed:[...document.querySelectorAll('tr.build-changed')].map(r=>r.innerText.replace(/\s+/g,' ').slice(0,140)),foot:[...document.querySelectorAll('#view .final-table tfoot tr')].map(r=>r.innerText.replace(/\s+/g,' ')),budget:(document.querySelector('#view').innerText.match(/예산(보다|과)[^\n]*/)||[''])[0]}));
          row('A 부품 바꾸기 ('+which+')',after.changed.length>0,'후보 '+np+'개 · 바뀐 줄 「'+after.changed.join(' / ')+'」 · 합계 「'+after.foot.join(' / ')+'」 · '+after.budget+' · 제목 '+(after.title===before?'그대로(X1)':'바뀜'),sh.concat(await shots('부품바꾼뒤')));}
        else row('A 부품 바꾸기 ('+which+')',false,'후보 없음',sh);
      }else row('A 부품 바꾸기',false,'바꿀 수 있는 줄 없음');
    }
    if(!old&&(sc.changePart||sc.roundtrip||sc.talkSave)){
      const rt=Math.max(1,sc.roundtrip||1);const counts=[];
      for(let k=0;k<rt;k++){
        if(!(await page.locator('#back-to-talk').isVisible().catch(()=>false))){row('A 대화로 돌아가기',false,'단추 안 보임');break;}
        await page.click('#back-to-talk');await page.waitForURL(/talk\.html/,{timeout:20000}).catch(()=>{});await sleep(2000);
        await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled;},null,{timeout:60000}).catch(()=>{});
        const s=await snap();counts.push({ai:s.filter(x=>x.kind==='ai').length,user:s.filter(x=>x.kind==='user').length});
        const tg=page.locator('[data-action="toggle-now"]');if(await tg.isVisible().catch(()=>false)&&!(await page.$eval('#tk-now',e=>e.classList.contains('is-open'))))await tg.click();
        const now=await page.$eval('#tk-now-body',e=>e.innerText).catch(()=>'');
        row('A 대화로 돌아가기 '+(k+1)+'회',/지금 선택한 구성/.test(now),'AI 말풍선 '+counts.map(c=>c.ai).join('→')+'개 · 지금 견적 「'+now.replace(/\s+/g,' ').slice(0,140)+'」',await shots('대화복귀'+(k+1),{alt:k===0}));
        if(k<rt-1||!sc.talkSave){if(!(await reopenDetail('A 대화 → 상세 다시 열기 '+(k+1)+'회')))break;}
      }
      if(counts.length>1)row('A 왕복해도 말풍선 안 쌓임',counts[counts.length-1].ai===counts[0].ai,'AI 말풍선 '+counts.map(c=>c.ai).join(' → '));
      if(sc.talkSave&&/talk\.html/.test(page.url())){
        const sv=page.locator('#tk-now-body [data-action="save"]');
        if(await sv.count()){await sv.click();await talkIdle(60000).catch(()=>{});const st=await page.$eval('#tk-now-body .tk-save-state',e=>e.innerText).catch(()=>'');row('A 대화 화면 견적 저장',/저장했어요/.test(st),st,await shots('대화저장',{alt:false}));
          const ho=page.locator('#tk-now-body [data-action="handoff"]');if(await ho.count()){await ho.click();await talkIdle(60000).catch(()=>{});const link=page.locator('#tk-now-body a.tk-link');row('A 대화 화면 쇼핑몰 이어가기',await link.count()>0,(await link.count())?'링크 '+await link.getAttribute('href'):'링크 안 나옴',await shots('대화쇼핑몰',{alt:false}));}}
        else row('A 대화 화면 견적 저장',false,'저장 단추 없음');
        await reopenDetail('A 저장·쇼핑몰 뒤 상세 다시 열기');
      }
    }
    await toFinalAndBuy();
    if(sc.op==='navmenu'){
      const items=[['내 견적','[data-action="saved"]'],['대화로 돌아가기','#back-to-talk'],['대화 화면','a.nav-link[href="talk.html"]:not(#back-to-talk)'],['새로 나온 PC','a.nav-link[href="new-pcs.html"]'],['새 상담','.topbar [data-action="new"]']];
      for(const [name,sel] of items){await page.goto(BASE+'/mvp3/index.html#final',{waitUntil:'networkidle'}).catch(()=>{});await sleep(2000);const el=page.locator(sel).first();const vis=await el.isVisible().catch(()=>false);if(!vis){row('D3 「'+name+'」',false,'안 보임');continue;}await el.click();await sleep(2500);const h=await page.locator('h1:visible, h2:visible').first().innerText().catch(()=>'');row('D3 「'+name+'」',true,'→ '+page.url().replace(BASE,'')+' · 제목 「'+h.slice(0,40)+'」'+(dialogs.length?' · 확인창 「'+dialogs[dialogs.length-1].slice(0,60)+'」':''),await shots('메뉴-'+name.replace(/\s/g,''),{alt:false}));}
    }
  }catch(e){row('진행 중 멈춤',false,e.message.split('\n')[0].slice(0,250),await shots('멈춤').catch(()=>[]));}
  finally{
    extra.pageErrors=errs.slice(0,30);extra.dialogs=dialogs;
    fs.writeFileSync(path.join(OUT,tag+'.json'),JSON.stringify({id,mode:MODE,scenario:sc,at:new Date().toISOString(),rows,turns,api,extra},null,2));
    await ctx.close();
  }
}
(async()=>{const browser=await chromium.launch();for(const j of JOBS){await runJob(browser,j).catch(e=>console.log(j,'실패',e.message));}await browser.close();})();
