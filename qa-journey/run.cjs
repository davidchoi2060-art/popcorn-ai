// 고객 여정 끝까지 검수 — 일회용. 개발 서버 공개 고객 화면만 고객처럼 누른다. 비밀값·DB 접속 없음.
// 첫 화면 → 대화 → 카드 → 추천 구성 상세 → 최종 견적 확인 → 쇼핑몰 구매 단추.
// 단계마다 PC(1440) 캡처 뒤 같은 화면을 390폭으로 줄여 모바일 캡처도 남긴다(MODE=mobile 이면 처음부터 모바일 기기로).
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const BASE='https://popcornai.co.kr';
const OUT=process.env.OUT,MODE=process.env.MODE||'pc';
const ONLY=(process.env.SCEN||'').split(',').filter(Boolean);
fs.mkdirSync(OUT,{recursive:true});
const FOLLOW=['FHD 144Hz 모니터 써요.','그냥 알아서 추천해 주세요.','네, 그 조건으로 보여 주세요.'];
// kind: game(그래픽카드 필요) · heavy(고사양 게임) · edit(영상·디자인, 그래픽카드 권장) · office
const S={
  s01:{kind:'heavy',budget:150,text:'배그랑 롤 해요. 고사양 게임도 하고 가끔 문서 작업도 해요. 예산은 150만원이에요.'},
  s02:{kind:'game',budget:150,text:'배그랑 롤 하는 대학생이에요. 예산은 150만원 정도요.'},
  s03:{kind:'game',budget:80,text:'롤만 하는 학생이에요. 80만원 이하로 맞춰 주세요.'},
  s04:{kind:'game',budget:100,text:'발로란트 하려고요. 예산 100만원이요.'},
  s05:{kind:'heavy',budget:250,text:'사이버펑크2077을 QHD 높음 옵션으로 하고 싶어요. 250만원까지 돼요.'},
  s06:{kind:'heavy',budget:200,text:'배틀그라운드를 QHD 165Hz로 하고 싶어요. 예산 200만원.'},
  s07:{kind:'game',budget:120,text:'오버워치2랑 피파 해요. 120만원 생각해요.'},
  s08:{kind:'game',budget:180,text:'로스트아크 쾌적하게 돌릴 PC요. 180만원 이하.'},
  s09:{kind:'heavy',budget:400,text:'최신 고사양 게임을 4K로 하고 싶어요. 예산 400만원.'},
  s10:{kind:'game',budget:70,text:'메이플스토리하고 유튜브 보는 용도예요. 70만원이요.'},
  s11:{kind:'edit',budget:250,text:'프리미어로 4K 유튜브 영상을 편집해요. 예산은 250만원이에요.'},
  s12:{kind:'edit',budget:150,text:'유튜브 FHD 영상 편집 입문용 PC 찾아요. 150만원 정도요.'},
  s13:{kind:'edit',budget:300,text:'다빈치 리졸브로 영상 편집하고 배그도 해요. 300만원.'},
  s14:{kind:'edit',budget:130,text:'포토샵이랑 일러스트로 디자인 작업해요. 130만원 이하로요.'},
  s15:{kind:'office',budget:60,text:'엑셀이랑 문서 작업만 해요. 60만원 이하로요.'},
  s16:{kind:'office',budget:100,text:'사무용 PC 100만원으로 추천해 주세요.'},
  s17:{kind:'office',budget:90,text:'주식 차트 보면서 듀얼 모니터로 사무 작업해요. 90만원.'},
  s18:{kind:'edit',budget:200,text:'영상 편집도 하고 게임도 해요. 200만원 이하.'},
  s19:{kind:'game',budget:50,text:'배그 할 수 있는 PC 50만원으로 가능해요?'},
  s20:{kind:'game',budget:null,text:'게임용 PC 추천해 주세요. 예산은 아직 모르겠어요.'},
  s21:{kind:'game',budget:120,text:'롤 하고 회사 문서 작업도 해요. 120만원.'},
};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const won=s=>{const m=String(s||'').replace(/,/g,'').match(/(-?\d+)\s*원/);return m?Number(m[1]):null;};

async function layout(page){
  return page.evaluate(()=>{
    const vw=innerWidth,vh=innerHeight,sw=document.documentElement.scrollWidth;
    // 화면 왼쪽 반/오른쪽 반에 놓인 글자 면적(보이는 글 블록 기준) — 쏠림 지표
    let L=0,R=0;const root=document.querySelector('#view')||document.querySelector('.tk-layout')||document.body;
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
    while((n=walker.nextNode())){if(!n.textContent.trim())continue;const r=document.createRange();r.selectNodeContents(n);for(const b of r.getClientRects()){if(!b.width)continue;const mid=vw/2;const a=b.width*b.height;if(b.right<=mid)L+=a;else if(b.left>=mid)R+=a;else{L+=(mid-b.left)*b.height;R+=(b.right-mid)*b.height;}}}
    const q=s=>[...document.querySelectorAll(s)].filter(e=>e.offsetParent!==null||getComputedStyle(e).position==='fixed');
    const ctas=q('button.primary, a.primary').map(e=>{const b=e.getBoundingClientRect();return {text:e.innerText.trim().slice(0,40),top:Math.round(b.top+scrollY),left:Math.round(b.left),inFirstView:b.top+scrollY<vh,disabled:!!e.disabled};});
    return {vw,vh,scrollWidth:sw,overflowX:sw>vw+1,docHeight:document.documentElement.scrollHeight,textLeft:Math.round(L),textRight:Math.round(R),ctas};
  });
}

(async()=>{
  const browser=await chromium.launch();
  const ids=ONLY.length?ONLY:Object.keys(S);
  for(const id of ids){
    const sc=S[id],tag=id+'-'+MODE;const rows=[],turns=[],extra={};let shotN=0;
    const ctx=await browser.newContext(MODE==='pc'?{viewport:{width:1440,height:900},locale:'ko-KR',timezoneId:'Asia/Seoul'}:{viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:2,locale:'ko-KR',timezoneId:'Asia/Seoul',userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'});
    const page=await ctx.newPage();
    const errs=[];page.on('pageerror',e=>errs.push('pageerror: '+e.message));page.on('console',m=>{if(m.type()==='error')errs.push('console: '+m.text().slice(0,200));});
    page.on('dialog',d=>{extra.dialogs=(extra.dialogs||[]).concat(d.message());d.accept();});
    const api=[];page.on('response',r=>{const u=r.url();if(u.includes('/api/'))api.push({at:new Date().toISOString(),m:r.request().method(),u:u.replace(BASE,''),s:r.status()});});
    const row=(step,ok,symptom,shots)=>{rows.push({step,ok,symptom:symptom||'',shots:shots||[]});console.log(id,(ok===true?'O':ok===false?'X':'-'),step,symptom||'');};
    // 단계 캡처: 첫 화면(보이는 그대로) + 전체 + (pc 모드면) 390폭 전체
    async function shots(name){
      const base=tag+'-'+String(++shotN).padStart(2,'0')+'-'+name;const out=[];
      await page.evaluate(()=>window.scrollTo(0,0)).catch(()=>{});await sleep(300);
      const lay=await layout(page).catch(()=>null);
      await page.screenshot({path:path.join(OUT,base+'-첫화면.png')}).catch(()=>{});out.push(base+'-첫화면.png');
      await page.screenshot({path:path.join(OUT,base+'-전체.png'),fullPage:true}).catch(()=>{});out.push(base+'-전체.png');
      let mob=null;
      if(MODE==='pc'){
        await page.setViewportSize({width:390,height:844});await sleep(700);
        mob=await layout(page).catch(()=>null);
        await page.screenshot({path:path.join(OUT,base+'-390전체.png'),fullPage:true}).catch(()=>{});out.push(base+'-390전체.png');
        await page.setViewportSize({width:1440,height:900});await sleep(500);
      }
      extra.layout=(extra.layout||[]).concat({step:name,pc:lay,m390:mob});
      return out;
    }
    async function talkIdle(timeout=150000){
      await page.waitForFunction(()=>document.querySelector('#tk-send')?.disabled,null,{timeout:4000}).catch(()=>{});
      await page.waitForFunction(()=>{const s=document.querySelector('#tk-send');return s&&!s.disabled&&document.querySelector('#tk-status').hidden;},null,{timeout});
      await sleep(500);
    }
    async function snap(){return page.evaluate(()=>[...document.querySelectorAll('#tk-log > *')].map(k=>({kind:k.classList.contains('tk-cards')?'cards':k.classList.contains('is-user')?'user':k.classList.contains('is-ai')?'ai':k.className,text:k.innerText.trim().slice(0,2500),past:k.classList.contains('is-past')})));}
    async function cardInfo(){
      return page.$$eval('.tk-cards:not(.is-past) .tk-card',cs=>cs.map(c=>({pill:c.querySelector('.pill')?.innerText.trim(),fit:c.querySelector('.tk-fit')?.innerText.trim()||null,name:c.querySelector('h4')?.innerText.trim(),group:c.closest('.tk-cards').querySelector('.tk-group')?.innerText.trim()||null,price:c.querySelector('.tk-price strong')?.innerText.trim(),gap:[...c.querySelectorAll('p.muted,p.warn-text')].map(p=>p.innerText.trim()).filter(t=>/예산/.test(t))[0]||null,spec:[...c.querySelectorAll('.tk-spec div, .tk-spec li')].map(d=>d.innerText.replace(/\s+/g,' ').trim()),photo:!!c.querySelector('.tk-photo img')})));
    }
    async function afterTurn(n,sent,ms){
      const s=await snap();const i=s.map(x=>x.kind).lastIndexOf('user');const after=s.slice(i+1);
      const ai=after.filter(x=>x.kind==='ai').map(x=>x.text);
      const ci=after.findIndex(x=>x.kind==='cards'&&!x.past);
      const cards=ci>=0?await cardInfo():[];
      const t={turn:n,sent,ms,ai,questions:ai.join(' ').split(/[?？]/).length-1,cards,cardsEmptyText:ci>=0&&!cards.length?after[ci].text:null,aiAbove:ci>=0?after.slice(0,ci).some(x=>x.kind==='ai'):null,aiBelow:ci>=0&&after.slice(ci+1).some(x=>x.kind==='ai'),error:after.filter(x=>/is-error/.test(x.kind)).map(x=>x.text)};
      turns.push(t);return t;
    }
    // 단추 누르기 전후: 단추가 사라지는지, 결과가 화면 밖에 생기는지
    async function clickWatch(locator,label){
      const before=await locator.boundingBox().catch(()=>null);const sy=await page.evaluate(()=>scrollY);
      await locator.click();await sleep(1500);
      const still=await page.getByText(label,{exact:false}).first().isVisible().catch(()=>false);
      const sy2=await page.evaluate(()=>scrollY);
      return {before,still,scrollFrom:sy,scrollTo:sy2};
    }
    try{
      // 1 첫 화면
      await page.goto(BASE+'/mvp3/#start',{waitUntil:'networkidle',timeout:60000});await sleep(800);
      row('1 첫 화면',await page.locator('#gateway-text').isVisible().catch(()=>false),'제목 「'+(await page.locator('h1:visible').first().innerText().catch(()=>''))+'」',await shots('첫화면'));
      // 2 대화
      await page.fill('#gateway-text',sc.text);await page.click('#gateway-chat button[type=submit]');
      await page.waitForURL(/talk\.html/,{timeout:20000});
      await talkIdle().catch(()=>{});let n=1;let t=await afterTurn(n,sc.text,null);
      row('2 대화 턴1',!t.error.length&&t.ai.length>0,'되묻기 '+t.questions+'개 · 카드 '+t.cards.length+'장'+(t.error.length?' · 오류 '+t.error.join(' / ').slice(0,200):''),await shots('대화1'));
      const fq=FOLLOW.slice();
      while(!t.cards.length&&fq.length&&!t.error.length){
        n++;const a=fq.shift();const t0=Date.now();await page.fill('#tk-input',a);await page.press('#tk-input','Enter');await talkIdle().catch(()=>{});
        t=await afterTurn(n,a,Date.now()-t0);
        row('2 대화 턴'+n+' 「'+a+'」',!t.error.length&&t.ai.length>0,'되묻기 '+t.questions+'개 · 카드 '+t.cards.length+'장 · '+Math.round((Date.now()-t0)/1000)+'초',await shots('대화'+n));
      }
      const multi=turns.filter(x=>x.questions>1);
      row('원칙: 되묻기 한 번에 하나',!multi.length,multi.map(x=>'턴'+x.turn+' 물음표 '+x.questions+'개').join(', ')||'모두 1개 이하');
      if(!t.cards.length){row('3 카드',false,'카드 없음 '+(t.cardsEmptyText||'').slice(0,200));throw new Error('카드 없음 — 여기서 멈춤');}
      row('원칙: LLM 설명 위, 카드 바로 아래',t.aiAbove===true&&!t.aiBelow,t.aiAbove?(t.aiBelow?'카드 아래에도 AI 말':'설명 → 카드'):'카드 위 설명 없음');
      // 3 카드 — 조건과 맞는지
      const c=t.cards;const needGpu=sc.kind!=='office';
      const issues=[];
      c.forEach((x,i)=>{
        const sp=x.spec.join(' | ');const gpuLine=x.spec.find(s=>/그래픽|GPU|VGA/i.test(s))||'';
        if(needGpu&&(!gpuLine||/내장|없음|UHD|Iris|Radeon Graphics|정보 없음/i.test(gpuLine)))issues.push('카드'+(i+1)+' 그래픽카드 없음/내장 「'+(gpuLine||'줄 없음')+'」');
        const p=won(x.price);if(sc.budget&&p){const r=p/(sc.budget*10000);if(r>1.15)issues.push('카드'+(i+1)+' 예산의 '+Math.round(r*100)+'%');if(r<0.45&&sc.kind!=='office')issues.push('카드'+(i+1)+' 예산의 '+Math.round(r*100)+'%(너무 낮음)');}
        const why=(x.fit||'')+' '+(x.group||'')+' '+(x.pill||'');
        if(sc.kind!=='office'&&/사무|문서/.test(why)&&!/게임|편집|작업/.test(why))issues.push('카드'+(i+1)+' 이유가 사무용 「'+why.trim().slice(0,60)+'」');
        if(sc.kind==='office'&&/고사양 게임/.test(why))issues.push('카드'+(i+1)+' 사무용인데 고사양 게임 이유');
        if(/정보 없음/.test(sp))issues.push('카드'+(i+1)+' 사양에 「정보 없음」');
      });
      extra.cards=c;
      row('3 카드 조건 맞음',!issues.length,c.map((x,i)=>(i+1)+') ['+(x.group||'-')+'] '+x.name+' '+x.price+' · '+(x.fit||'')).join(' / ')+(issues.length?' ‖ 문제: '+issues.join('; '):''),await shots('카드'));
      // 4 첫 카드 상세 보기 → 추천 구성 상세
      const det=page.locator('.tk-cards:not(.is-past) [data-action="detail"]').first();
      await det.scrollIntoViewIfNeeded();await det.click();
      await page.waitForURL(/#detail/,{timeout:20000}).catch(()=>{});
      await page.waitForSelector('.final-table',{timeout:60000}).catch(()=>{});await sleep(1500);
      const tbl=await page.evaluate(()=>{
        const rs=[...document.querySelectorAll('#view .final-table tbody tr')].filter(r=>!r.classList.contains('build-options-row')).map(r=>{const tds=r.querySelectorAll('td');return {part:r.querySelector('h4 span')?.innerText.trim()||'',name:r.querySelector('.part-name')?.innerText.trim()||r.querySelector('h4')?.innerText.trim()||'',desc:r.querySelector('.final-part-description p')?.innerText.trim()||'',price:(r.querySelector('.final-part-price')||tds[1])?.innerText.trim()||'',change:r.querySelector('[data-action="build-options"]')?(r.querySelector('[data-action="build-options"]').disabled?'비활성':'활성'):'-'};});
        const foot=[...document.querySelectorAll('#view .final-table tfoot tr')].map(r=>r.innerText.replace(/\s+/g,' ').trim());
        const head=document.querySelector('#view .live-summary, #view .final-summary, #view section')?.innerText.slice(0,600)||'';
        const reasons=[...document.querySelectorAll('#view .live-explanation li')].map(l=>l.innerText.trim()).slice(0,8);
        const chips=[...document.querySelectorAll('#view .condition-chips button, #view .chips button, #view [data-chip]')].map(b=>b.innerText.trim());
        return {rows:rs,foot,head,reasons,chips};
      });
      extra.detail=tbl;
      const sum=tbl.rows.reduce((a,r)=>a+(won(r.price)||0),0);
      const total=won((tbl.foot.find(f=>/참고 금액|합계|구성 금액/.test(f))||'').replace(/.*?(금액|합계)/,''));
      const etc=won((tbl.foot.find(f=>/조립|기타/.test(f))||''));
      const dIssues=[];
      tbl.rows.forEach(r=>{if(/정보 없음/.test(r.name+r.desc))dIssues.push(r.part+' 「정보 없음」');if(!r.name)dIssues.push(r.part+' 이름 빈 줄');if(!won(r.price)&&!/포함/.test(r.price))dIssues.push(r.part+' 금액 「'+r.price+'」');});
      if(needGpu&&!tbl.rows.some(r=>/그래픽/.test(r.part)&&!/정보 없음|내장/.test(r.name)))dIssues.push('그래픽카드 줄 없음/정보 없음');
      if(total&&etc!==null&&total>0&&etc/total>0.15)dIssues.push('조립·기타 '+etc.toLocaleString()+'원 = 합계의 '+Math.round(etc/total*100)+'%');
      if(total&&sum&&etc!==null&&Math.abs(sum+etc-total)>1000)dIssues.push('부품합 '+sum.toLocaleString()+' + 기타 '+etc.toLocaleString()+' ≠ 합계 '+total.toLocaleString());
      row('4 추천 구성 상세',tbl.rows.length>0&&!dIssues.length,'부품 '+tbl.rows.length+'줄 · 부품합 '+sum.toLocaleString()+'원 · 표 아래 「'+tbl.foot.join(' / ')+'」'+(dIssues.length?' ‖ 문제: '+dIssues.join('; '):''),await shots('상세'));
      // 5 저장 → 최종 견적 확인
      const save=page.locator('#actions button[data-action="save"], #actions button:has-text("저장")').first();
      if(await save.count()){
        const w=await clickWatch(save,'이 견적 저장하기');
        await page.waitForFunction(()=>/#final/.test(location.hash),null,{timeout:30000}).catch(()=>{});
        await page.waitForFunction(()=>!/보관 확인 중|서버 확인 중/.test(document.querySelector('#view')?.innerText||''),null,{timeout:60000}).catch(()=>{});await sleep(1200);
        const st=await page.locator('.save-status').innerText().catch(()=>'');
        row('5 저장 → 최종 견적 확인',/#final/.test(page.url())&&/보관됨/.test(st),'주소 '+page.url().replace(BASE,'')+' · 상태 「'+st+'」',await shots('최종견적'));
        // 보관이 안 된 경우 「견적 보관하기」
        const keep=page.locator('.final-buttons [data-action="save"]:not([disabled])');
        if(await keep.count()){await keep.click();await page.waitForFunction(()=>/보관됨|보관되지/.test(document.querySelector('.save-status')?.innerText||''),null,{timeout:60000}).catch(()=>{});}
        // 6 쇼핑몰 구매 단추
        const buy=page.locator('.final-buttons [data-action="handoff"]');
        if(await buy.count()){
          const bb=await buy.boundingBox();
          const w2=await clickWatch(buy,'팝콘PC 쇼핑몰에서 구매하기');
          await page.waitForSelector('.live-handoff, #view .warn-text, [role=alert]',{timeout:60000}).catch(()=>{});await sleep(1200);
          const panel=await page.evaluate(()=>{const p=document.querySelector('.live-handoff');if(!p)return null;const b=p.getBoundingClientRect();return {text:p.innerText.replace(/\s+/g,' ').slice(0,300),top:Math.round(b.top),inView:b.top<innerHeight&&b.bottom>0,left:Math.round(b.left),width:Math.round(b.width)};});
          extra.handoff={buttonBox:bb,watch:w2,panel};
          row('6 쇼핑몰 구매 단추',!!panel,(w2.still?'단추 남음':'누른 단추가 사라짐')+' · 결과 칸 '+(panel?(panel.inView?'화면 안':'화면 밖(아래 '+panel.top+'px)')+' · 「'+panel.text.slice(0,120)+'」':'안 나옴'),await shots('쇼핑몰단추후'));
          const link=page.locator('.live-handoff a.primary');
          if(await link.count()){
            const href=await link.getAttribute('href');
            const [pop]=await Promise.all([ctx.waitForEvent('page',{timeout:20000}).catch(()=>null),link.click()]);
            let info='';if(pop){await pop.waitForLoadState('domcontentloaded',{timeout:30000}).catch(()=>{});await sleep(1500);info=pop.url()+' · 제목 「'+(await pop.title().catch(()=>''))+'」';await pop.screenshot({path:path.join(OUT,tag+'-99-쇼핑몰.png')}).catch(()=>{});await pop.close();}
            row('7 쇼핑몰 상품 페이지',!!pop,'링크 '+href+(pop?' → '+info:' · 새 창 안 열림'),[tag+'-99-쇼핑몰.png']);
          }
        }else row('6 쇼핑몰 구매 단추',false,'단추 없음 (저장 상태 「'+(await page.locator('.save-status').innerText().catch(()=>''))+'」)',await shots('구매단추없음'));
      }else row('5 저장',false,'상세 화면 아래 저장 단추 없음',await shots('저장없음'));
    }catch(e){row('진행 중 멈춤',false,e.message.split('\n')[0].slice(0,250),await shots('멈춤').catch(()=>[]));}
    extra.pageErrors=errs.slice(0,30);
    fs.writeFileSync(path.join(OUT,tag+'.json'),JSON.stringify({id,mode:MODE,scenario:sc,at:new Date().toISOString(),rows,turns,api,extra},null,2));
    await ctx.close();
  }
  await browser.close();
})();
