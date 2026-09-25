// CUS-QUO-010 — A-128 ③ 실 API 연결 + A-135 격자 매트릭스 재설계(2026-09-16) + 격자 안내 재설계(2026-09-16 오후).
//   ① POST /api/talk/parse   {text, state(이전 턴 TalkState|null), chat_flow(잡담 카운터|null), history}
//        → state(누적 좌표)·missing·dropped·reply·pc_related·chat_flow·stage·silent
//   ② POST /api/grid/recommend {state}            → card_sets[](용도별 묶음) · assumed[] · ai_estimated[] · needs[]
//        카드마다 quotes 3종(가성비/추천/고성능, 재조회 없이 탭 전환)
//   ③ GET  /api/grid/workstations?usage=&budget_won= → shown 일 때 AI 워크스테이션 진열(격자 카드와 별도)
// 파싱은 서버만 한다 — 화면에 정규식 파서를 두지 않는다(둘이 갈린다).
//
// ── 격자 안내 재설계(docs/design/talk-grid-guide-redesign-2026-09-16.md §4·§6·§7) 화면 계약 ──
//   · state.talk 가 서버 TalkState 그대로다(usages[], budget_won, budget_bound, platform, tier_key,
//     game{names,grade,grade_src,resolution}, exclude[], prefs[]). 매 턴 되돌려 보내고 응답 state 로 교체한다.
//     화면은 state 를 고치지 않는다 — 조건 변경은 문장으로 파서에 보낸다(닫힌 어휘를 화면이 다시 들지 않는다).
//   · missing 이 비어 있을 때만 격자를 부른다. missing 이 있으면 AI 가 reply 로 이미 되물었다.
//   · 서버 내부 사유(notes[]/note)는 화면에 싣지 않는다 — console.debug 로만(결함 ④ 해소).
//     needs[] 가 있으면 카드 없이 끝, 안내 문구도 띄우지 않는다(되묻기는 AI 의 reply 뿐).
//   · 서버 응답의 필드명은 아래 TALK / GRID 조회 함수 한 곳에서만 읽는다 — 서버 제작자가 이름을
//     다르게 지으면 거기만 고친다.
// 실패는 삼키지 않는다 — 고객에게는 읽을 수 있는 한 줄 + 다시 시도(폴백 UI 없음, A-128). 서버 원문은 console.warn 으로만.
// 파일 구조: [렌더 — 순수 함수, DOM 없음 · node 에서 require 가능] → [브라우저 — fetch·DOM]. 렌더는 인자만 본다.
//
// ── A-135 재설계 메모(원안: docs/design/incoming/dc-grid-matrix-2026-09-16.html) ──
// 원안은 DesignComposer 프로토타입(React 류사)이고 우리는 순수 vanilla다 — 마크업을 그대로
// 옮기지 않고 "이렇게 보여야 한다"는 구조만 우리 스택으로 재구현했다:
//   · 카드 1차 축이 가격 → 스펙 하한(티어)으로 바뀐다. 티어 이름을 크게, 가격은 관측값으로 작게.
//   · 카드 "안"에 가성비/추천/고성능 3종 탭 — 클릭해도 네트워크 요청이 없다(서버가 3종 다 이미 보낸 것을
//     클라이언트 상태(state.cardVariant)로만 전환). quoteMarkup(오른쪽 패널)도 같은 방식으로 탭을 가진다.
//   · 생략된 슬롯(예: iGPU 확정으로 그래픽카드 생략)은 스펙 행에서 지우지 않고 "생략 — 사유"로 남긴다
//     (payload.omitted, 서버 값 그대로 — 화면이 사유를 지어내지 않는다).
//   · 원안의 6칸(팝콘1~5·X) 고정 매트릭스는 그대로 못 그린다 — 고객단 /api/grid/recommend 는
//     "조회된 tiers_considered"(중심 ± 최대 2, 최대 3개)만 준다. 전체 6티어 목록을 내려주는
//     고객단 엔드포인트가 없어(관리자용 /api/admin/grid 는 인증 게이트 뒤) 6칸을 채우면 없는 3칸을
//     지어내는 것이 된다 — 그래서 matrixMarkup 은 서버가 실제로 준 tiers_considered 개수만큼만 그린다.
//     (보고 대상 — 이 파일 담당 밖인 api/grid_public.py 가 전체 티어 목록 필드를 추가하면 해소된다.)
//   · 원안의 TIERS/USAGES/VARIANTS 배열은 샘플 값(가격·스펙 리터럴)이라 코드에 옮기지 않았다
//     (CLAUDE.md §화면 정직성 — 서버 응답만 쓴다).
//   · 카드·quotes 응답의 정확한 필드명(quotes.value/reco/perf 또는 quotes.가성비/추천/고성능,
//     tier_key vs tier_name 등)은 api/grid_public.py 재작성이 끝나야 확정된다(다른 제작자 작업 중,
//     2026-09-16). 아래 cardQuotes()/tierKeyOf()/tierDisplayName() 는 흔히 쓰일 후보 키를 전부
//     시도하는 방어적 조회로 짰다 — 실제 응답이 오면 이 조회 순서를 좁혀야 할 수 있다(보고에 남김).
(function(root){'use strict';
const money=n=>Number.isFinite(n)?new Intl.NumberFormat('ko-KR').format(n):'—';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=x=>JSON.parse(JSON.stringify(x));
const HISTORY_MAX=6;         // api/talk.HISTORY_MAX_TURNS 와 같은 수(서버도 잘라낸다)
const USAGE_AI='AI 작업';    // api/grid_workstations.USAGE_AI 와 같은 값
const POSTER='assets/pc-front.png';   // 대표 예시 이미지(④ 소관) — 카드·견적 공통, 캡션으로 예시임을 밝힌다
const IMG_NOTE='이미지는 예시입니다. 부품·가격·재고는 실제 값입니다.';
const NOT_READY='부품 조정은 준비 중입니다.';
// 0106 — 서버가 «제외»라고는 했는데 사유 문자열이 비어 온 경우에만 쓴다. 사유를 지어내지 않는다.
const OMITTED_NO_REASON='이 용도는 이 구성을 두지 않습니다. 사유는 서버에서 받지 못했습니다.';
// 조립공임 — 금액·문구는 ../shared/assembly-fee.js 한 곳에서 온다(§단일 원천).
//   · 브라우저는 index.html 이 먼저 실은 window.PopcornAssemblyFee 를 쓴다.
//   · node(회귀 검사)는 require 로 같은 파일을 읽는다 — 두 경로가 같은 숫자를 본다.
//   · 총액(v.total)에 더하지 않는다 — 공임은 장바구니·주문 단계에서 더해진다(사장님 확정).
const FEE=(function(){
 if(root&&root.PopcornAssemblyFee)return root.PopcornAssemblyFee;
 try{return require('../shared/assembly-fee.js');}catch(e){return null;}
})();
// 원천이 없으면 금액을 지어내지 않고 못 불렀다고 말한다(§실패를 삼키지 않는다).
const FEE_UNKNOWN='조립공임 안내를 불러오지 못했습니다.';
function feeNote(kind){return FEE?FEE.noteText(kind):FEE_UNKNOWN;}
// 가격이 보이는 자리마다 붙이는 한 줄. 값이 없는 카드(미배치·제외)에는 붙이지 않는다.
function feeNoteMarkup(kind,cls){return `<p class="${cls}" data-assembly-fee-note="${kind}">${esc(feeNote(kind))}</p>`;}

// ── A-135: 카드 안 3종 탭 ────────────────────────────────────────────────────
const VARIANT_DEFS=[{key:'value',label:'가성비'},{key:'reco',label:'추천'},{key:'perf',label:'고성능'}];
const DEFAULT_VARIANT='reco';
// 스펙 4행(카드 상단) — 슬롯 코드 기준. 표시 라벨과 서버가 줄 수 있는 여러 표기를 함께 흡수한다.
const SPEC_SLOTS=['CPU','GPU','RAM','SSD'];
const SLOT_LABEL={CPU:'CPU',GPU:'그래픽카드',RAM:'메모리',SSD:'저장장치',MB:'메인보드',CASE:'케이스',COOLER:'쿨러',POWER:'파워'};
// 서버가 cat(라벨) 로 줄 수도, slot/part_type(코드) 로 줄 수도 있다 — 둘 다 같은 슬롯으로 귀결시킨다.
const SLOT_ALIAS={
 'CPU':'CPU','GPU':'GPU','그래픽카드':'GPU','RAM':'RAM','메모리':'RAM','SSD':'SSD','저장장치':'SSD',
 'MB':'MB','메인보드':'MB','CASE':'CASE','케이스':'CASE','COOLER':'COOLER','쿨러':'COOLER','CPU쿨러':'COOLER',
 'POWER':'POWER','파워':'POWER',
};
function slotOf(x){return SLOT_ALIAS[x]||x||'';}

// ── 서버 계약 조회 — 응답 필드명을 읽는 유일한 자리 ─────────────────────────
// 설계서 §4(TalkState) · §7(card_sets). 서버 제작자가 이름을 다르게 지으면 여기만 고친다.
const TALK={
 state:p=>p&&p.state&&typeof p.state==='object'?p.state:null,
 missing:p=>Array.isArray(p&&p.missing)?p.missing:[],
 dropped:p=>Array.isArray(p&&p.dropped)?p.dropped:[],
 reply:p=>(p&&p.reply)||'',
 // ── 답변 경로 [B] (2026-09-21 · talk_design_v2 §6-2) ─────────────────────
 // ★ 이 연결이 끊기면 고객은 답을 받지 못한다(2026-09-21 사장님 실측 사고).
 //   서버는 `answer` 를 내려보내는데 화면이 읽지 않아, 세 번 물은 고객이 세 번 다
 //   되묻기만 받았다. 회귀 [59] 가 이 줄을 지킨다.
 answer:p=>(p&&typeof p.answer==='string')?p.answer:'',
 sources:p=>Array.isArray(p&&p.sources)?p.sources:[],
 narrowing:p=>(p&&typeof p.narrowing==='string')?p.narrowing:null,
 // 「조금 걸린다」 안내 — **웹검색 턴에만** 서버가 준다(늘 있는 것이 아니다).
 answerNotice:p=>(p&&typeof p.answer_notice==='string'&&p.answer_notice)?p.answer_notice:'',
 // 필터가 무엇을 손댔는가 — 화면에 싣지 않는다(서버 내부 사유). console.debug 로만.
 answerFilter:p=>(p&&p.answer_filter&&typeof p.answer_filter==='object')?p.answer_filter:null,
 answerError:p=>(p&&typeof p.answer_error==='string')?p.answer_error:null,
 answerGameNames:p=>Array.isArray(p&&p.answer_game_names)?p.answer_game_names:[],
 pcRelated:p=>p?p.pc_related:null,
 // 잡담 흐름(2026-09-17) — 서버 talk_schema.ChatFlow 그대로. state 와 **형제**다(격자 좌표가 아니다).
 // 화면은 이 수를 «해석하지 않고» 다음 요청에 되돌려 보내기만 한다 — 경계(3/4/5)는 서버가 정한다.
 chatFlow:p=>(p&&p.chat_flow&&typeof p.chat_flow==='object')?p.chat_flow:null,
 stage:p=>(p&&typeof p.stage==='string')?p.stage:null,
 silent:p=>p?p.silent===true:false,
 assumed:p=>Array.isArray(p&&p.assumed)?p.assumed:[],
 evidence:p=>Array.isArray(p&&p.evidence)?p.evidence:[],
};
// TalkState 안 좌표
const ST={
 usages:s=>Array.isArray(s&&s.usages)?s.usages.filter(Boolean):[],
 budgetWon:s=>s&&Number.isFinite(s.budget_won)?s.budget_won:null,
 budgetBound:s=>(s&&s.budget_bound)||null,
 platform:s=>(s&&s.platform)||null,
 tierKey:s=>(s&&s.tier_key)||null,
 game:s=>s&&s.game&&typeof s.game==='object'?s.game:null,
 gameNames:s=>{const g=ST.game(s);return Array.isArray(g&&g.names)?g.names.filter(Boolean):[];},
 gameGrade:s=>{const g=ST.game(s);return (g&&g.grade)||null;},
 gameGradeSrc:s=>{const g=ST.game(s);return (g&&g.grade_src)||null;},
 gameResolution:s=>{const g=ST.game(s);return (g&&g.resolution)||null;},
 exclude:s=>Array.isArray(s&&s.exclude)?s.exclude.filter(Boolean):[],
 prefs:s=>Array.isArray(s&&s.prefs)?s.prefs.filter(Boolean):[],
};
const ASSUMED_RES_1080='game.resolution=1080p';   // 설계서 §6 ③ — 서버가 해상도를 1080p 로 가정했다는 표시
const GRID={
 // card_sets[] 가 없고 cards[] 만 오면(하위호환·옛 서버) 응답 자체를 set 하나로 본다 — 지어내지 않고 감싼다.
 sets:g=>{
  if(Array.isArray(g&&g.card_sets))return g.card_sets.filter(s=>s&&typeof s==='object');
  if(g&&Array.isArray(g.cards))return [g];
  return [];
 },
 setUsage:s=>(s&&(s.usage||s.usage_grid))||'',
 setUsageGrid:s=>(s&&(s.usage_grid||s.usage))||'',
 setKind:s=>(s&&s.kind)||(s&&s.usage_kind)||null,
 setCards:s=>Array.isArray(s&&s.cards)?s.cards:[],
 setCenterTier:s=>(s&&(s.center_tier_key||s.center_tier))||null,
 setEmptyCells:s=>Array.isArray(s&&s.empty_cells)?s.empty_cells:[],
 // 등급·해상도 — 실측(2026-09-16 오후) 서버는 set 이 아니라 응답 최상위(game_grade/game_resolution)와 카드마다 준다.
 // set 에 있으면 그것, 없으면 그 set 의 첫 카드, 그다음 응답 최상위 순(값은 어느 자리든 서버 것).
 setGrade:(s,g)=>(s&&(s.game_grade||s.grade))||(GRID.setCards(s)[0]||{}).game_grade||(g&&g.game_grade)||null,
 setResolution:(s,g)=>(s&&(s.game_resolution||s.resolution))||(GRID.setCards(s)[0]||{}).game_resolution||(g&&g.game_resolution)||null,
 assumed:g=>Array.isArray(g&&g.assumed)?g.assumed:[],
 assumedRes1080:g=>GRID.assumed(g).some(a=>a===ASSUMED_RES_1080||a==='resolution=1080p'),
 aiEstimated:g=>Array.isArray(g&&g.ai_estimated)?g.ai_estimated.filter(e=>e&&typeof e==='object'):[],
 needs:g=>Array.isArray(g&&g.needs)?g.needs:[],
 // notes[]/note — 서버 내부 사유. 화면에 실리지 않는다(console.debug 전용). 이 함수의 반환값을 마크업에 넣지 말 것.
 internalNotes:g=>{const out=[];if(Array.isArray(g&&g.notes))out.push(...g.notes);if(g&&typeof g.note==='string'&&g.note)out.push(g.note);return out;},
 budgetWon:g=>g&&Number.isFinite(g.budget_won)?g.budget_won:null,
 budgetBound:g=>(g&&g.budget_bound)||null,
 // card.game_context — reasons(엔진, 매 요청 계산)의 «형제 필드»다(api/grid_public._game_context
 // docstring 그대로). 사람이 검수해 둔 문구라 원천·갱신 주기가 다르고, 그래서 화면 구역도
 // 「이렇게 골랐어요」와 분리한다(사장님 확정). 비게임 카드·검수본 없음이면 null — 그리지 않는다.
 gameContext:card=>(card&&card.game_context&&typeof card.game_context==='object')?card.game_context:null,
};

// ── 렌더(순수) ─────────────────────────────────────────────────────────────
function usageOf(talk){const u=ST.usages(talk);return u.length?u[0]:null;}
// state.talk → 조건 칩 목록(라벨·값). 예산·용도들·게임명·등급·해상도·플랫폼·제외 순 — 서버 값만.
function conditionChips(talk){
 const chips=[];
 const b=ST.budgetWon(talk);
 if(b!=null)chips.push({l:'예산',v:money(b)+'원'+(ST.budgetBound(talk)?' '+ST.budgetBound(talk):'')});
 ST.usages(talk).forEach(u=>chips.push({l:'용도',v:u}));
 ST.gameNames(talk).forEach(n=>chips.push({l:'게임',v:n}));
 const grade=ST.gameGrade(talk);
 if(grade)chips.push({l:'등급',v:grade+(ST.gameGradeSrc(talk)==='ai_estimate'?' (AI 추정)':'')});
 const res=ST.gameResolution(talk);
 if(res)chips.push({l:'해상도',v:res});
 const pf=ST.platform(talk);
 if(pf)chips.push({l:'플랫폼',v:pf});
 ST.exclude(talk).forEach(x=>chips.push({l:'제외',v:x}));
 return chips;
}
function purposeButtons(usages,talk){const cur=ST.usages(talk);return (usages||[]).map(u=>{const on=cur.includes(u.label);return `<button type="button" data-purpose="${esc(u.label)}" aria-pressed="${on}" class="${on?'active':''}"><span class="purpose-radio" aria-hidden="true"></span><span><b>${esc(u.label)}</b>${u.floor_note?`<small>${esc(u.floor_note)}</small>`:''}</span></button>`;}).join('');}
function conditionsMarkup(talk,usages){
 const chips=conditionChips(talk).map(c=>`<button data-action="conditions">${esc(c.l)}: ${esc(c.v)} ✎</button>`).join('');
 return `<div class="purpose-picker"><div class="purpose-heading"><b>용도를 바꾸려면 고르세요</b><span>여러 개면 함께 말해 주세요</span></div><div class="purpose-options" role="group" aria-label="PC 사용 용도">${usages?purposeButtons(usages,talk):'<span class="condition-note">용도 목록 불러오는 중…</span>'}</div></div><div class="condition-row"><span class="condition-label">내 조건</span>${chips||'<span class="condition-note">읽힌 조건 없음</span>'}</div>`;
}
function partLine(p){return esc(p&&p.name||'이름 없음')+(p&&p.in_stock===false?' <em>재고 확인 필요</em>':'');}
// 서버 필드명이 items(신) 또는 parts(구) 일 수 있고, 슬롯 표기가 cat(라벨)/slot/part_type(코드)일 수 있다.
// 화면 나머지(specRows·detailMarkup·quoteMarkup)는 언제나 이 정규화된 {cat,name,price,product_code,in_stock} 형태만 본다.
function normalizeParts(list){
 return (Array.isArray(list)?list:[]).map(p=>({
  cat:p.cat||SLOT_LABEL[slotOf(p.slot||p.part_type)]||p.slot||p.part_type||'',
  slot:slotOf(p.slot||p.part_type||p.cat),
  name:p.name,price:p.price,product_code:p.product_code,in_stock:p.in_stock,
 }));
}
function normalizeOmitted(list){
 return (Array.isArray(list)?list:[]).map(o=>({
  slot:slotOf(o.slot||o.part_type),
  label:o.label||SLOT_LABEL[slotOf(o.slot)]||o.slot||'',
  note:o.note||o.reason_text||o.reason||'생략',
 }));
}
function findPart(parts,slot){return parts.find(p=>slotOf(p.slot||p.cat)===slot);}
function findOmitted(omitted,slot){return omitted.find(o=>o.slot===slot);}
function specRows(parts,omitted){
 return SPEC_SLOTS.map(slot=>{
  const p=findPart(parts,slot);
  if(p)return `<div><dt>${esc(SLOT_LABEL[slot]||slot)}</dt><dd>${partLine(p)}</dd></div>`;
  const om=findOmitted(omitted,slot);
  if(om)return `<div><dt>${esc(SLOT_LABEL[slot]||slot)}</dt><dd class="omitted-spec">${esc(om.note)}</dd></div>`;
  return `<div><dt>${esc(SLOT_LABEL[slot]||slot)}</dt><dd>—</dd></div>`;
 }).join('');
}
function omittedRows(omitted){return omitted.map(o=>`<tr class="omitted"><td class="category">${esc(o.label)}</td><td class="part-name">${esc(o.note)}</td><td class="part-price">—</td></tr>`).join('');}
function tierRangeText(r){if(!r||typeof r!=='object')return '';const a=Number.isFinite(r.min)?money(r.min)+'원':null,b=Number.isFinite(r.max)?money(r.max)+'원':null;if(!a&&!b)return '';return `${a||'?'} ~ ${b||'상한 없음'}`;}

// ── A-135: 카드 하나가 quotes 3종(가성비/추천/고성능)을 갖는다 ───────────────
// 정본 키는 api/grid_public.py 재작성이 끝나야 확정된다 — 영문 키(value/reco/perf)와
// 국문 라벨 키(가성비/추천/고성능) 둘 다 시도한다(다른 제작자 작업 중, 보고 대상).
function cardQuotes(card){
 const raw=card&&card.quotes&&typeof card.quotes==='object'?card.quotes:null;
 if(!raw)return null;
 const pick=(...keys)=>{for(const k of keys){if(raw[k]!=null)return raw[k];}return null;};
 return {value:pick('value','가성비'),reco:pick('reco','추천'),perf:pick('perf','고성능')};
}
function tierKeyOf(card){return card&&(card.tier_key||card.tier||card.cell_tier||null);}
function tierDisplayName(card){
 if(!card)return '이름 미확인';
 return card.tier_name||card.popcorn_name||card.tier_label||card.brand||card.name||card.tier_key||card.tier||'이름 미확인';
}
function variantOver(v,card){return v&&v.over_budget===true || (!v||v.over_budget==null)&&card&&card.over_budget===true;}
// 카드에 quotes 3종이 없으면(서버가 아직 구조를 못 준 경우) 카드 자체를 단일 "추천" 구성으로 본다 —
// 탭은 비활성으로 보여주고 그 사실을 밝힌다(지어낸 3종을 만들지 않는다).
function variantsOf(card){
 const q=cardQuotes(card);
 if(q)return q;
 return {value:null,reco:card,perf:null};
}
// ── 0106: «만들지 않기로 한 구성»과 «아직 없는 구성»은 다른 말이다 ───────────
// 서버가 card.omitted_variants[{variant,key,reason}] 로 «두지 않기로 한» 구성과 그 사유를
// 함께 준다(api/grid_public._load_omissions → grid_variant_omissions.reason_public 원문).
// 화면은 그 문자열을 **그대로** 쓴다 — 요약·재작성·수치 추가를 하지 않는다(§화면 정직성).
// 사유가 없는 용도(영상편집 등)는 [] 로 오므로 아래 조회가 전부 null 을 낸다.
function omissionsOf(card){
 const list=card&&card.omitted_variants;
 return (Array.isArray(list)?list:[]).filter(o=>o&&typeof o==='object'&&o.key);
}
function omissionFor(card,key){
 if(!key)return null;
 return omissionsOf(card).find(o=>o.key===key)||null;
}
// 사유 문자열이 비어 오면 «우리가 대신 지어내지» 않는다 — 제외 사실만 말하고 사유는 없다고 밝힌다.
function omissionReason(o){
 const r=o&&typeof o.reason==='string'?o.reason.trim():'';
 return r||OMITTED_NO_REASON;
}
// ⚠ 제외된 구성의 탭을 **지우지도, 비활성으로 막지도 않는다.**
//   · 탭을 없애면 고객은 「왜 여긴 두 개지」를 스스로 지어내 답한다 — 사유를 전할 자리가 사라진다.
//   · disabled 로 두면 누를 수 없어 사유를 열 수 없다(브라우저가 클릭 이벤트를 안 준다).
//   그래서 «누를 수 있는» 탭으로 두고, 누르면 서버가 준 사유를 본문에 편다.
//   「아직 없는 것」(서버가 제외라고 말한 적 없는 것)만 여전히 disabled + 기존 문구다.
function variantTabsMarkup(scope,index,active,available,card){
 return `<div class="tier-tabs" role="tablist">${VARIANT_DEFS.map(v=>{
  const om=omissionFor(card,v.key);
  if(om){
   const reason=omissionReason(om);
   return `<button type="button" class="tier-tab omitted${v.key===active?' active':''}" role="tab" aria-selected="${v.key===active}" data-variant-scope="${scope}" data-variant-index="${index}" data-variant-key="${v.key}" data-variant-omitted="1" title="${esc(reason)}">${esc(v.label)}<span class="tier-tab-mark" aria-hidden="true">✳</span><span class="sr-only"> — 이 용도는 이 구성을 두지 않습니다. 눌러서 사유 보기</span></button>`;
  }
  const has=available[v.key]!=null;
  return `<button type="button" class="tier-tab${v.key===active?' active':''}" role="tab" aria-selected="${v.key===active}" data-variant-scope="${scope}" data-variant-index="${index}" data-variant-key="${v.key}" ${has?'':'disabled title="이 구성 정보가 아직 없습니다"'}>${esc(v.label)}</button>`;
 }).join('')}</div>`;
}
// 제외 사유 본문 — 서버 문자열 하나만 싣는다.
function omittedReasonMarkup(om){
 return `<p class="omitted-reason" data-omitted-reason="1"><b>이 구성은 두지 않습니다</b>${esc(omissionReason(om))}</p>`;
}
function detailMarkup(v,om){
 if(!v)return om?omittedReasonMarkup(om):'<p class="condition-note">이 구성 정보가 아직 없습니다.</p>';
 const reasons=Array.isArray(v.reasons)?v.reasons:[];
 const parts=normalizeParts(v.items||v.parts);
 const omitted=normalizeOmitted(v.omitted);
 return `<details class="tradeoff"><summary><span>부품 ${parts.length}종 · 이유 ${reasons.length}개</span><svg class="chev" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg></summary>${reasons.length?'<ol class="reason-list">'+reasons.map(r=>`<li>${esc(r)}</li>`).join('')+'</ol>':'<p class="condition-note">서버가 준 이유가 없습니다.</p>'}<table class="parts"><tbody>${parts.map(p=>`<tr><td class="category">${esc(p.cat)}</td><td class="part-name">${partLine(p)}</td><td class="part-price">${money(p.price)}</td></tr>`).join('')}${omittedRows(omitted)}</tbody></table></details>`;
}
function cardMarkup(card,i,centerTier,activeVariant){
 const activeKey=activeVariant||DEFAULT_VARIANT;
 const vs=variantsOf(card);
 const hasThree=!!cardQuotes(card);
 // 제외된 구성을 고른 상태면 **다른 구성으로 대신 채우지 않는다** — 그러면 고객은
 // 「고성능을 눌렀는데 추천이 나온다」고 읽는다. v 를 비워 두고 사유만 편다.
 const om=omissionFor(card,activeKey);
 const v=om?null:(vs[activeKey]||vs.reco||vs.value||vs.perf||null);
 // 서버는 center_tier(이름)·center_tier_key(키) 둘을 준다 — 어느 쪽으로 와도 같은 카드가 중심이다.
 const featured=!!centerTier&&(tierKeyOf(card)===centerTier||tierDisplayName(card)===centerTier);
 const over=variantOver(v,card);
 const overBy=(over&&v&&Number.isFinite(v.total)&&Number.isFinite(v.budget_won))?money(v.total-v.budget_won):'';
 const parts=v?normalizeParts(v.items||v.parts):[];
 const omitted=v?normalizeOmitted(v.omitted):[];
 const reasons=v&&Array.isArray(v.reasons)?v.reasons:[];
 const badges=[featured?'<span class="rec-tag">내 조건 중심</span>':'',over?`<span class="rec-tag over">예산 초과${overBy?' +'+overBy+'원':''}</span>`:''].join('');
 const tierName=tierDisplayName(card);
 const priceBlock=v&&Number.isFinite(v.total)
  ?`<div class="tier-price-row"><div class="tier-price">${money(v.total)}<small>원</small></div>${card.platform?`<span class="tier-price-note">배치 관측가 · ${esc(card.platform)}</span>`:''}</div>${feeNoteMarkup('short','tier-fee-note')}`
  :(om?'':'<p class="condition-note">이 구성은 아직 배치되지 않았습니다.</p>');
 const range=v?tierRangeText(v.tier_range||card.tier_range):'';
 // 제외된 구성일 때는 값이 없는 스펙표(— 4줄)를 그리지 않는다 — 사유 한 덩이만 남긴다.
 const specBlock=om?'':`<dl class="rec-specs">${specRows(parts,omitted)}</dl><p class="rec-desc">${esc(reasons[0]||'')}</p>`;
 return `<article class="rec-card${featured?' featured':''}${om?' has-omitted':''}" data-card-index="${i}"><button class="rec-media" data-build-video="${i}" aria-label="${esc(tierName)} 대표 예시 이미지 보기"><img src="${POSTER}" alt="대표 예시 이미지 — 실제 구성과 다릅니다"><span class="rec-media-badge">대표 예시 이미지</span><span class="rec-media-play" aria-hidden="true">▶</span><span class="rec-media-caption">대표 예시 이미지 ↗</span></button><div class="rec-top"><span class="rec-num">구성 0${i+1}</span><span>${badges}</span></div><span class="tier-kicker">${esc(tierKeyOf(card)||'')}</span><h3 class="tier-name">${esc(tierName)}</h3>${variantTabsMarkup('card',i,activeKey,vs,card)}${!hasThree?'<p class="condition-note">이 카드는 아직 단일 구성만 제공합니다 — 3종 비교는 준비 중입니다.</p>':''}${priceBlock}${range?`<p class="condition-note">티어 예산대 ${range}</p>`:''}${specBlock}${detailMarkup(v,om)}<div class="card-actions"><button class="primary" data-select="${i}" data-select-variant="${activeKey}" ${v?'':'disabled'}${om?' title="두지 않기로 한 구성이라 자세히 볼 내용이 없습니다"':''}>이 구성 자세히 보기 ↗</button></div></article>`;
}
// 원안 §매트릭스(팝콘1~5·X 6칸)는 고객단 응답이 tiers_considered(최대 3개)만 주므로 그만큼만 그린다 —
// 없는 티어를 채워 6칸으로 지어내지 않는다(§화면 정직성). 전체 티어 목록이 필요하면 grid_public.py에
// 필드 추가가 필요하다(담당 밖 — 보고만).
function matrixMarkup(g){
 const items=Array.isArray(g.tiers_considered)?g.tiers_considered:[];
 if(!items.length)return '';
 const cells=items.map(t=>{
  const key=typeof t==='string'?t:(t.tier_key||t.tier||t.name||'');
  const label=typeof t==='string'?t:(t.tier_name||t.popcorn_name||t.name||key);
  const isCenter=!!(g.center_tier)&&(key===g.center_tier||label===g.center_tier);
  return `<div class="tier-cell${isCenter?' is-center':' is-hit'}" title="${esc(label)}"><span class="tier-cell-key">${esc(label)}</span></div>`;
 }).join('');
 return `<div class="tier-matrix"><span class="tier-matrix-caption">스펙 티어 축 · 조회된 ${items.length}개 티어(전체 목록은 준비 중)</span><div class="tier-strip">${cells}</div></div>`;
}
// ── card_sets 렌더(설계서 §6 ① · §7) ─────────────────────────────────────────
// 카드 번호(data-card-index)는 set 을 가로질러 한 줄로 이어진다 — state.quotes 가 평평한 목록이라
// 선택·탭 전환이 set 을 몰라도 된다. flattenSets 가 그 순서를 정하는 유일한 자리.
function flattenSets(g){
 const out=[];
 GRID.sets(g).forEach((s,si)=>GRID.setCards(s).forEach(c=>out.push({card:c,setIndex:si,centerTier:GRID.setCenterTier(s)})));
 return out;
}
// set 제목 줄 — 용도 · 등급 · 해상도(게임) / 용도(비게임). 배지: "1080p 기준"(assumed) · "AI 추정 ○등급"(ai_estimated).
// 값은 전부 서버 응답에서 온다 — 화면이 등급·해상도를 지어내지 않는다.
function setHeadingText(s,g){
 const parts=[GRID.setUsage(s)||'용도 미확인'];
 if(GRID.setKind(s)==='game'){const gr=GRID.setGrade(s,g),res=GRID.setResolution(s,g);if(gr)parts.push(gr+'등급');if(res)parts.push(res);}
 return parts.join(' · ');
}
function aiEstimateFor(g,s){
 if(GRID.setKind(s)!=='game')return null;
 const list=GRID.aiEstimated(g);
 if(!list.length)return null;
 const gr=GRID.setGrade(s,g);
 return list.find(e=>!gr||!e.grade||e.grade===gr)||null;
}
function setHeadingMarkup(g,s,showHeading){
 const isGame=GRID.setKind(s)==='game';
 const est=aiEstimateFor(g,s);
 const badges=[
  isGame&&GRID.assumedRes1080(g)?'<span class="rec-tag">1080p 기준</span>':'',
  est&&est.grade?`<span class="rec-tag">AI 추정 ${esc(est.grade)}등급</span>`:'',
 ].join('');
 const estLine=est&&est.grade?`<p class="condition-note">이 게임은 AI 가 ${esc(est.grade)}등급으로 추정했습니다.</p>`:'';
 if(!showHeading&&!badges&&!estLine)return '';
 // 제목 줄은 기존 .parts-heading(굵은 제목 + 작은 보조) 를 그대로 쓴다 — 새 배치를 그리지 않는다.
 return `<div class="parts-heading set-heading" data-set-usage="${esc(GRID.setUsage(s))}"><b>${showHeading?esc(setHeadingText(s,g)):'추천 구성'}</b><span>${badges}</span></div>${estLine}`;
}
// 2026-09-25 재설계 4단계 — kind==='sold' 는 조합 카드가 아니라 «지금 파는 몰 조립PC» 최대 2개다
// (api/sold_reco). 가격·수준·근거·링크는 전부 서버 값이고, 화면은 워크스테이션 카드와 같은 틀로 그린다.
function soldSpecText(sp){
 if(!sp||typeof sp!=='object')return '사양 정보 없음';
 const out=[];if(sp.cpu)out.push('CPU '+sp.cpu);if(sp.gpu)out.push('그래픽 '+sp.gpu);if(sp.ram_gb!=null)out.push('메모리 '+sp.ram_gb+'GB');if(sp.ssd_gb!=null)out.push('SSD '+(sp.ssd_gb>=1000?(sp.ssd_gb/1000)+'TB':sp.ssd_gb+'GB'));
 return out.join(' · ')||'사양 정보 없음';
}
function soldCardMarkup(it,i){
 const reasons=Array.isArray(it.reasons)?it.reasons:[];
 return `<article class="rec-card${i===0?' featured':''}" data-sold-code="${esc(it.product_code)}"><div class="rec-top"><span class="rec-num">${esc(it.tag||'')}</span><span>${it.over_budget===true?'<span class="rec-tag over">예산 초과</span>':''}<span class="rec-tag">${esc(it.level||'')}</span></span></div><h3>${esc(it.name||'이름 없음')}</h3><div class="rec-price">${money(it.price)}<small>원</small></div><p class="rec-desc">${esc(soldSpecText(it.spec))}</p>${reasons.length?'<ul class="tradeoff">'+reasons.map(r=>`<li>${esc(r)}</li>`).join('')+'</ul>':''}${it.mall_url?`<a class="primary" href="${esc(it.mall_url)}" target="_blank" rel="noopener">팝콘PC 몰에서 보기 ↗</a>`:'<span class="condition-note">몰 링크 없음</span>'}</article>`;
}
function soldSetMarkup(g,s,showHeading){
 const items=Array.isArray(s.items)?s.items:[];
 const head=`<div class="parts-heading set-heading" data-set-usage="${esc(GRID.setUsage(s))}"><b>${showHeading?esc(setHeadingText(s,g)):'추천 상품'}</b><span>${s.min_level?esc(s.min_level+' 이상 · '+(s.min_level_work||'')):''}</span></div>`;
 const empty=s.empty_reason?`<p class="condition-note"><b>${esc(s.empty_reason)}</b> ${esc(s.empty_note||'')}</p>`:'';
 const ctx=s.game_context?`<div data-sold-game-context="${esc(GRID.setUsage(s))}"></div>`:'';
 return `${head}${empty}${items.length?`<div class="recommendations">${items.map(soldCardMarkup).join('')}</div>`:''}${ctx}<p class="condition-note">실제 판매 중인 조립PC 입니다. 가격은 조회 시점 몰 판매가이며 조립비·보증이 포함돼 있습니다.</p>`;
}
function cardSetMarkup(g,s,offset,showHeading){
 if(GRID.setKind(s)==='sold')return soldSetMarkup(g,s,showHeading);
 const cards=GRID.setCards(s);
 const center=GRID.setCenterTier(s);
 const cardHtml=cards.map((q,i)=>cardMarkup(q,offset+i,center,DEFAULT_VARIANT)).join('');
 const emptyHtml=GRID.setEmptyCells(s).map(e=>`<p class="condition-note">${esc(e.tier||'')}: ${esc(e.reason||'')}</p>`).join('');
 const none=cards.length?'':'<p class="condition-note">이 조건에 맞는 격자 카드가 없습니다.</p>';
 return `${setHeadingMarkup(g,s,showHeading)}${matrixMarkup(s)}<div class="recommendations">${cardHtml}</div>${none}${emptyHtml}${GRID.setUsageGrid(s)===USAGE_AI?`<div data-workstations data-set-usage="${esc(GRID.setUsageGrid(s))}"></div>`:''}`;
}
// 서버 내부 사유(notes/note)는 여기서 읽지 않는다 — 마크업에 실을 경로가 없다(결함 ④).
function recommendationMarkup(g){
 const sets=GRID.sets(g);
 if(!sets.length)return `<p class="condition-note">이 조건에 맞는 격자 카드가 없습니다.</p><p class="demo-note">${IMG_NOTE}</p>`;
 const multi=sets.length>1;
 let offset=0;
 const html=sets.map(s=>{const h=cardSetMarkup(g,s,offset,multi);offset+=GRID.setCards(s).length;return h;}).join('');
 return `${html}<p class="demo-note">${IMG_NOTE}</p>`;
}
function specSummary(spec){
 if(!spec||typeof spec!=='object')return '사양 정보 없음';
 const out=[];if(spec.cpu)out.push('CPU '+spec.cpu);if(spec.ram_gb!=null)out.push('메모리 '+spec.ram_gb+'GB');if(spec.ssd)out.push('SSD '+spec.ssd);if(spec.gpu)out.push('GPU '+spec.gpu+(spec.gpu_count>1?' ×'+spec.gpu_count:''));
 return out.join(' · ')||'사양 정보 없음';
}
// AI 워크스테이션은 격자 카드와 별개 진열(usage===AI 일 때만) — 예산 하한 삭제 정책은 서버(grid_workstations.py)
// 가 이미 반영했으므로 화면은 shown 판정만 그대로 따른다(코드 변경 없음, 확인만).
function workstationsMarkup(w){
 if(!w||w.shown!==true)return '';   // 서버 판정 — 안 보일 때는 자리도 두지 않는다
 const items=Array.isArray(w.items)?w.items:[];
 const cards=items.map(it=>`<article class="rec-card"><div class="rec-top"><span class="rec-num">완제품</span><span>${it.over_budget===true?'<span class="rec-tag over">예산 초과</span>':''}${it.in_stock===false?'<span class="rec-tag">재고 확인 필요</span>':''}</span></div><h3>${esc(it.name||'이름 없음')}</h3><div class="rec-price">${money(it.price)}<small>원</small></div><p class="rec-desc">${esc(specSummary(it.spec))}</p>${it.mall_url?`<a class="primary" href="${esc(it.mall_url)}" target="_blank" rel="noopener">팝콘PC 몰에서 보기 ↗</a>`:'<span class="condition-note">몰 링크 없음</span>'}</article>`).join('');
 return `<div class="parts-heading"><b>팝콘PC AI 워크스테이션</b><span>완제품 · 격자와 별도 진열</span></div>${cards?`<div class="recommendations">${cards}</div>`:'<p class="condition-note">진열할 완제품이 없습니다.</p>'}`;   // w.note(서버 내부 사유)는 화면에 싣지 않는다 — 브라우저 쪽 console.debug
}
// 오른쪽 "내 견적" 패널도 카드와 같은 3종 탭을 갖는다(같은 state.quotes 원본을 다시 읽을 뿐 재조회 없음).
function quoteMarkup(card,activeVariant){
 const activeKey=activeVariant||DEFAULT_VARIANT;
 const vs=variantsOf(card);
 const hasThree=!!cardQuotes(card);
 const om=omissionFor(card,activeKey);
 const v=om?null:(vs[activeKey]||vs.reco||vs.value||vs.perf||null);
 const parts=v?normalizeParts(v.items||v.parts):[];
 const omitted=v?normalizeOmitted(v.omitted):[];
 const reasons=v&&Array.isArray(v.reasons)?v.reasons:[];
 const over=!card.fromSaved&&variantOver(v,card);
 const verdict=over?'<span class="under over">예산 초과</span>':'';
 const tierName=tierDisplayName(card);
 return `<div class="quote-top"><span class="eyebrow">내 구성${tierKeyOf(card)?' · '+esc(tierKeyOf(card)):''}</span></div><div class="quote-title"><div><h2>${esc(tierName)}</h2><p>${esc([card.usage,card.platform].filter(Boolean).join(' · '))}</p></div><div class="quote-total">${v&&Number.isFinite(v.total)?money(v.total):'—'}<small>원</small>${verdict}</div></div>${v&&Number.isFinite(v.total)?feeNoteMarkup('quote','quote-fee-note'):''}${variantTabsMarkup('quote',0,activeKey,vs,card)}${om?omittedReasonMarkup(om):''}${!hasThree?'<p class="condition-note">이 견적은 아직 단일 구성만 제공합니다.</p>':''}<div class="quote-media"><img src="${POSTER}" alt="대표 예시 이미지 — 실제 구성과 다릅니다"><div class="media-caption">대표 예시 이미지<small>실제 부품은 아래 목록 기준</small></div><button data-action="video" aria-label="대표 예시 이미지 크게 보기">▶</button></div><div class="quote-reason"><b>✦ 이렇게 골랐어요</b>${reasons.length?'<ul>'+reasons.map(r=>`<li>${esc(r)}</li>`).join('')+'</ul>':'<br>서버가 준 이유가 없습니다.'}</div><div class="parts-heading"><b>구성 부품 <span>${parts.length}종</span></b><span>서버 가격 · 원</span></div><table class="parts" aria-label="현재 견적 부품 목록"><tbody>${parts.map(p=>`<tr><td class="category">${esc(p.cat)}</td><td class="part-name">${partLine(p)}</td><td class="part-price">${money(p.price)}</td></tr>`).join('')}${omittedRows(omitted)}</tbody></table><p class="quote-disclaimer">재고는 조회 시점 기준입니다.${v&&v.generated_at?' 견적 생성 '+esc(String(v.generated_at).slice(0,10))+'.':''} ${NOT_READY}</p><div class="quote-actions"><button class="secondary" data-action="save">견적 저장</button><button class="primary" data-action="cart" disabled title="장바구니는 준비 중입니다">장바구니 담기(준비 중)</button></div>`;
}
// ── ③단계: 「이 게임에 대해」 구역 — game_context (2026-09-22) ───────────────
// `quote-reason`(위 quoteMarkup, «이렇게 골랐어요»)과 **섞지 않는다**. reasons 는 엔진이
// 매 요청 계산하는 값이고 game_context 는 사람이 검수해 둔 문구다(api/grid_public.py
// `_game_context` docstring — "섞으면 «엔진이 말했다»로 읽혀 검수 책임이 지워진다").
// null 이면 빈 상자도 "근거 없음" 문구도 없다(§화면 정직성 그대로 — 없는 것은 없는 대로 둔다).
// innerHTML 을 쓰지 않는다 — 이 문구는 사람이 자유 텍스트로 쓴 것이라(LLM 은 아니지만 운영자
// 입력도 같은 원칙) drawAnswer/answerFragment 의 관례를 그대로 따른다: doc 를 인자로 받아
// node 에서도 검증 가능하게 한다.

// 순수 함수 — 그릴 줄들의 배열만 만든다(DOM 없음). spec_summary → why_this_pc → upgrade_hint
// → caution(「주의: 」 접두 — 함정 문구를 본문과 구분해 읽게) 순, 비어 있지 않은 것만.
// 넷 다 비면 [](reviewed_at 도 붙이지 않는다 — 붙일 본문이 없는데 검수일만 남는 것은 이상하다).
// confidence·source.fields(DB 컬럼명)는 고객에게 의미가 없어 그리지 않는다. 화면이 수치나
// 문장을 보태지 않는다 — 서버가 준 문자열만 옮긴다.
function gameContextBlocks(ctx){
 if(!ctx||typeof ctx!=='object')return [];
 const lines=[];
 const push=s=>{if(typeof s==='string'&&s.trim())lines.push(s.trim());};
 push(ctx.spec_summary);
 push(ctx.why_this_pc);
 push(ctx.upgrade_hint);
 if(typeof ctx.caution==='string'&&ctx.caution.trim())lines.push('주의: '+ctx.caution.trim());
 if(!lines.length)return [];
 if(typeof ctx.reviewed_at==='string'&&ctx.reviewed_at)lines.push('검수 '+ctx.reviewed_at.slice(0,10));
 return lines;
}
// source.url 이 http(s) 일 때만 링크 후보로 돌려준다 — sourceItems 와 같은 규칙(javascript: 를
// 링크로 만들지 않는다). gameContextBlocks 와 분리한 순수 함수라 node 에서 따로도 검증된다.
function gameContextLink(ctx){
 const url=ctx&&ctx.source&&typeof ctx.source==='object'?ctx.source.url:null;
 return (typeof url==='string'&&/^https?:\/\//i.test(url))?url:null;
}
// DOM 생성 — doc 를 인자로 받는다(node/jsdom 에서도 같은 코드가 돈다, answerFragment 관례).
// createElement·createTextNode·appendChild·setAttribute 만 쓴다 — innerHTML 금지.
function gameContextElement(ctx,doc){
 const blocks=gameContextBlocks(ctx);
 if(!blocks.length)return null;
 const box=doc.createElement('div');box.className='quote-game';
 const b=doc.createElement('b');
 b.appendChild(doc.createTextNode('✦ 이 게임에 대해'));
 box.appendChild(b);
 if(ctx&&typeof ctx.game_name==='string'&&ctx.game_name.trim())
  box.appendChild(doc.createTextNode(' · '+ctx.game_name.trim()));
 for(const line of blocks){
  const p=doc.createElement('p');
  p.appendChild(doc.createTextNode(line));
  box.appendChild(p);
 }
 const url=gameContextLink(ctx);
 if(url){
  const a=doc.createElement('a');
  a.setAttribute('href',url);a.setAttribute('target','_blank');a.setAttribute('rel','noopener');
  a.appendChild(doc.createTextNode('출처 보기'));
  box.appendChild(a);
 }
 return box;
}
// ── 답변(answer) 렌더 — 2026-09-21 · talk_design_v2 §6-2 ────────────────────
// 서버 /api/talk/parse 가 `answer`(질문에 대한 답)와 `reply`(되묻기)를 **둘 다** 준다.
// 실측(2026-09-21, 로컬 :8000 · 사장님 3턴 + 잡담 1턴):
//   answer  게임 질문일 때만 채워진다. 잡담('오늘 날씨 좋네요')이면 '' 이다.
//           줄바꿈이 **하나도 없다** — 목록을 ' - **이름**: 내용' 처럼 한 줄에 이어 붙여 온다.
//   reply   언제나 있다(잡담 포함). 침묵 단계(silent=true)에서만 '' 이다.
// 그래서 화면은 **말풍선 하나** 안에 [answer 본문] → [근거] → [되묻기] 순으로 쌓는다.
// 말풍선을 둘로 나누면 고객이 «두 사람이 말한다»고 느낀다(사장님 화면 = 상담 창구다).
//
// ⚠ innerHTML 을 쓰지 않는다. 여기 들어오는 문자열은 LLM 이 쓴 것이다 — 태그를 만들어
//   붙이면 그대로 XSS 경로가 된다. 아래는 **텍스트 노드 + 우리가 만든 태그**만 쓴다.
const ANSWER_LIST_MIN=2;              // ' - ' 조각이 이만큼 있어야 «목록»으로 본다(아래 근거)
const WAIT_SHORT='조건을 읽는 중…';
// 「고객에게는 조금 시간이 걸린다고 얘기하고」(사장님 확정). 응답이 실측 5~7초라
// 기다리는 동안 화면이 죽은 것처럼 보이면 안 된다. **화면 문구**이지 서버 값이 아니다 —
// 서버가 `answer_notice`(웹검색 턴만)를 주면 그건 말풍선 안에 따로 싣는다.
const WAIT_LONG='답을 찾고 있어요. 자료를 확인하느라 조금 걸릴 수 있어요.';
const WAIT_LONG_MS=2500;
const SOURCES_HEADING='근거';

// 「한 줄로 온 목록」을 줄로 편다. ' - ' 가 ANSWER_LIST_MIN 개 이상일 때만 편다 —
// 한 번뿐이면 본문 속 줄표(«라이엇 게임즈 — 1위» 같은 것)일 수 있어 건드리지 않는다.
// 서버가 나중에 진짜 줄바꿈으로 바꿔 보내도 이 함수는 그대로 통과시킨다.
function answerNormalize(text){
 let s=String(text==null?'':text).replace(/\r\n?/g,'\n').trim();
 if(!s)return '';
 const hits=(s.match(/(?:^|[\s\n])[-*]\s+\S/g)||[]).length;
 if(hits>=ANSWER_LIST_MIN)s=s.replace(/[ \t]+[-*][ \t]+(?=\S)/g,'\n- ');
 return s;
}
// '**굵게**' 만 본다. 나머지 별표·기호는 **그냥 글자**로 남는다(지원 범위를 넓히지 않는다).
function answerSpans(text){
 const t=String(text==null?'':text);
 const out=[];let i=0,m;const re=/\*\*([\s\S]+?)\*\*/g;
 while((m=re.exec(t))){
  if(m.index>i)out.push({bold:false,text:t.slice(i,m.index)});
  out.push({bold:true,text:m[1]});
  i=re.lastIndex;
 }
 if(i<t.length)out.push({bold:false,text:t.slice(i)});
 return out.filter(x=>x.text!=='');
}
// 블록으로 쪼갠다 — {type:'ul',items:[spans]} | {type:'p',spans}. DOM 을 만들지 않는다(node 검증 가능).
function answerBlocks(text){
 const s=answerNormalize(text);
 if(!s)return [];
 const out=[];
 for(const raw of s.split('\n')){
  const line=raw.trim();
  if(!line)continue;
  const m=/^[-*]\s+(.*)$/.exec(line);
  if(!m){out.push({type:'p',spans:answerSpans(line)});continue;}
  const last=out[out.length-1];
  if(last&&last.type==='ul')last.items.push(answerSpans(m[1]));
  else out.push({type:'ul',items:[answerSpans(m[1])]});
 }
 return out;
}
// 근거 목록 — 서버 sources[] 를 화면이 읽을 수 있는 모양으로만 접는다(지어내지 않는다).
// url 은 http(s) 만 통과시킨다(javascript: 를 링크로 만들지 않는다).
function sourceItems(sources){
 return (Array.isArray(sources)?sources:[])
  .filter(s=>s&&typeof s==='object'&&s.label)
  .map(s=>({kind:s.kind==='web'?'web':'own',label:String(s.label),
            url:(typeof s.url==='string'&&/^https?:\/\//i.test(s.url))?s.url:null}));
}
// ── DOM 생성 — document 를 인자로 받는다(node/jsdom 에서도 같은 코드가 돈다) ──
function appendSpans(host,spans,doc){
 for(const sp of (spans||[])){
  if(!sp||!sp.text)continue;
  if(sp.bold){const b=doc.createElement('strong');b.appendChild(doc.createTextNode(sp.text));host.appendChild(b);}
  else host.appendChild(doc.createTextNode(sp.text));
 }
 return host;
}
function answerFragment(blocks,doc){
 const frag=doc.createDocumentFragment();
 for(const b of (blocks||[])){
  if(!b)continue;
  if(b.type==='ul'){
   const ul=doc.createElement('ul');ul.className='answer-list';
   for(const spans of (b.items||[])){const li=doc.createElement('li');appendSpans(li,spans,doc);ul.appendChild(li);}
   if(ul.childNodes.length)frag.appendChild(ul);
  }else{
   const p=doc.createElement('p');p.className='answer-para';
   appendSpans(p,b.spans,doc);
   if(p.childNodes.length)frag.appendChild(p);
  }
 }
 return frag;
}
function sourcesElement(items,doc){
 const box=doc.createElement('p');box.className='answer-sources';
 const h=doc.createElement('b');h.textContent=SOURCES_HEADING;box.appendChild(h);
 (items||[]).forEach(s=>{
  box.appendChild(doc.createTextNode(' '));
  if(s.url){const a=doc.createElement('a');a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=s.label;box.appendChild(a);}
  else box.appendChild(doc.createTextNode(s.label));
 });
 return box;
}
// ★ 말풍선 본문 하나. answer 가 비면 reply 만, reply 가 비면 answer 만 — 둘 다 없으면 null.
//   (cap=null 전례 — 어느 필드가 없어도 화면이 죽지 않는다.)
function answerBody(p,doc){
 const answer=TALK.answer(p),reply=TALK.reply(p);
 if(!answer&&!reply)return null;
 const body=doc.createElement('div');body.className='assistant-text';
 if(answer){
  const notice=TALK.answerNotice(p);
  if(notice){const n=doc.createElement('p');n.className='answer-notice';n.textContent=notice;body.appendChild(n);}
  const box=doc.createElement('div');box.className='answer-body';
  box.appendChild(answerFragment(answerBlocks(answer),doc));
  if(box.childNodes.length)body.appendChild(box);
  // 본문이 이미 «출처는 gametrics입니다» 라고 말하는 턴이 있다(실측 T1). 그래도 근거 줄은
  // 남긴다 — 저 문장은 LLM 이 쓴 것이고, 이 줄은 **서버가 준 sources[]** 다. 둘은 다른 축이고
  // 「모든 견적에는 이유가 있습니다」는 우리가 보증하는 쪽을 보여주는 것이다. 다만 한 줄로
  // 작게 두어 본문과 겹쳐 읽히지 않게 한다(말풍선을 나누지 않는다).
  const src=sourceItems(TALK.sources(p));
  if(src.length)body.appendChild(sourcesElement(src,doc));
 }
 if(reply){
  const r=doc.createElement('p');
  r.className=answer?'answer-followup':'answer-reply';
  r.textContent=reply;body.appendChild(r);
 }
 return body;
}
// 오류 문구 — 502 는 AI 연결 불가(폴백 UI 없음). 서버 detail 은 console 로만.
function errorMessage(status,data){
 const d=data&&data.detail;
 if(status===502)return 'AI 연결이 지금 안 됩니다. 잠시 후 다시 시도해 주세요.';
 if(status===429)return '요청이 많아 잠시 기다려 주세요'+(d&&typeof d==='object'&&Number.isFinite(d.retry_after_sec)?`(${d.retry_after_sec}초 후)`:'');
 if(typeof d==='string')return (status>=500?'서버 오류':'요청 오류')+`(${status}) — ${d}`;
 if(d&&typeof d==='object'&&d.message)return String(d.message);
 return (status>=500?'서버 오류':'요청 오류')+`(${status})`;
}
const render={money,esc,soldSetMarkup,soldCardMarkup,soldSpecText,feeNote,feeNoteMarkup,FEE,conditionsMarkup,conditionChips,cardMarkup,recommendationMarkup,cardSetMarkup,setHeadingMarkup,setHeadingText,flattenSets,workstationsMarkup,quoteMarkup,matrixMarkup,specSummary,tierRangeText,errorMessage,usageOf,cardQuotes,tierKeyOf,tierDisplayName,normalizeParts,normalizeOmitted,omissionsOf,omissionFor,omissionReason,omittedReasonMarkup,gameContextBlocks,gameContextLink,gameContextElement,answerNormalize,answerSpans,answerBlocks,answerFragment,answerBody,sourceItems,sourcesElement,TALK,ST,GRID,ASSUMED_RES_1080,VARIANT_DEFS,IMG_NOTE,NOT_READY,OMITTED_NO_REASON,WAIT_SHORT,WAIT_LONG,WAIT_LONG_MS,SOURCES_HEADING};
if(typeof module!=='undefined'&&module.exports){module.exports=render;return;}   // node(자기검증) — 여기서 끝
if(!root.document||root.PopcornApp)return;

// ── 브라우저 ────────────────────────────────────────────────────────────────
const $=s=>document.querySelector(s);
const API='';   // 같은 오리진(127.0.0.1:8000)에서 서빙 — 외부 CDN·절대 주소 없음
const SAVE_KEY='popcorn-quotes-v2';   // 옛 키(popcorn-demo-quotes)는 가짜 가격이라 읽지 않는다
const state={talk:null,chatFlow:null,history:[],quotes:[],grid:null,selected:null,selectedVariant:DEFAULT_VARIANT,cardVariant:{},busy:false,retry:null,usages:null,videoUrl:null,saved:[]};
// state.talk = 서버 TalkState(설계서 §4) 그대로. 화면은 이것을 만들거나 고치지 않는다 — 파서 응답으로만 교체된다.
// state.chatFlow = 서버 ChatFlow(잡담 카운터) 그대로. **talk 안에 넣지 않는다** — 격자 좌표가 아니고
//   /api/grid/recommend 에 보내는 state 에 섞이면 안 된다(api/talk_schema.py §1-b 근거).
try{const saved=JSON.parse(localStorage.getItem(SAVE_KEY)||'[]');if(Array.isArray(saved))state.saved=saved.filter(x=>x&&Array.isArray(x.parts)&&Number.isFinite(x.total)).slice(0,10);}catch{}
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),3200);}

async function api(method,url,body){
 let res;
 try{res=await fetch(API+url,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});}
 catch(e){throw new Error('서버에 연결하지 못했습니다(네트워크) — '+e.message);}
 let data=null;try{data=await res.json();}catch{}
 if(!res.ok){console.warn('api error',url,res.status,data&&data.detail);throw new Error(errorMessage(res.status,data));}
 return data||{};
}
function pushHistory(role,text){state.history.push({role,text:String(text).slice(0,300)});state.history=state.history.slice(-HISTORY_MAX);}
function setBusy(on){state.busy=on;document.querySelectorAll('#startForm .send,#chatForm .send,[data-purpose],[data-chat],[data-prompt],[data-action="retry"]').forEach(b=>{if(b.dataset.done)return;b.disabled=on;});}

function addMessage(role,content,html=false){const node=document.createElement('div');node.className='message '+role;node.innerHTML=role==='user'?`<div class="user-bubble">${esc(content)}</div>`:`<div class="assistant-label"><span class="ai-mark">✦</span>팝콘PC AI</div><div class="assistant-text">${html?content:esc(content)}</div>`;$('#messages').append(node);scrollChat();return node;}
// ★ answer/reply 말풍선 — **innerHTML 을 쓰지 않는다**. 본문은 LLM 이 쓴 문자열이라
//   태그 문자열로 조립하면 그대로 XSS 경로가 된다. 라벨(우리 고정 마크업)만 innerHTML 로
//   두고, 서버 문자열은 전부 answerBody() 가 만든 텍스트 노드로 들어간다.
//   answer·reply 가 둘 다 비면 말풍선 자체를 만들지 않는다(빈 풍선 금지 · null 가드).
function drawAnswer(p){
 const body=answerBody(p,document);
 if(!body)return null;
 const node=document.createElement('div');node.className='message assistant';
 const label=document.createElement('div');label.className='assistant-label';
 label.innerHTML='<span class="ai-mark">✦</span>팝콘PC AI';
 node.appendChild(label);node.appendChild(body);
 $('#messages').append(node);scrollChat();return node;
}
function showError(err,retry){state.retry=retry;addMessage('assistant',`<strong>요청에 실패했습니다.</strong>\n${esc(err&&err.message||err)}<div class="change-actions"><button class="secondary" data-action="retry">다시 시도</button></div>`,true);}
function scrollChat(){requestAnimationFrame(()=>{$('#messages').scrollTop=$('#messages').scrollHeight;});}
function showWorkspace(){ $('#welcome').hidden=true;$('#welcomeFoot').hidden=true;$('#workspace').hidden=false; }
// 빠른 버튼 = 파서로 다시 보내는 문장(조건 변경). 부품 교체 문구는 두지 않는다(준비 중).
function setQuick(){$('#quickActions').innerHTML=['예산을 바꿀게요','용도를 바꿀게요'].map(t=>`<button data-chat="${esc(t)}">${esc(t)}</button>`).join('');}

// ── ① 입력 → 파서 ──────────────────────────────────────────────────────────
async function submit(text){
 text=(text||'').trim();if(!text||state.busy)return;
 showWorkspace();selectTab('chat');
 addMessage('user',text);
 const history=state.history.slice(-HISTORY_MAX);   // 이번 문장 이전의 최근 6턴
 // ⑤ 「고객에게는 조금 시간이 걸린다고 얘기하고」 — 실측 응답이 5~7초다. 2.5초를 넘기면
 //   같은 말풍선의 문구만 길게 바꾼다(말풍선을 새로 만들지 않는다 — 기록이 안내문으로 덮인다).
 const thinking=addMessage('assistant',WAIT_SHORT);
 const waitTimer=setTimeout(()=>{const t=thinking.querySelector('.assistant-text');if(t)t.textContent=WAIT_LONG;},WAIT_LONG_MS);
 setBusy(true);
 let p;
 try{p=await api('POST','/api/talk/parse',{text,state:state.talk,chat_flow:state.chatFlow,history});}   // 이전 턴 state·잡담 카운터를 되돌려 보낸다(누적)
 catch(e){clearTimeout(waitTimer);thinking.remove();setBusy(false);showError(e,()=>submit(text));return;}
 clearTimeout(waitTimer);
 thinking.remove();
 pushHistory('user',text);
 const next=TALK.state(p);
 if(next)state.talk=next;   // 서버가 state 를 안 주면(옛 서버) 이전 것을 유지 — 화면이 state 를 만들지 않는다
 else console.warn('talk/parse: 응답에 state 가 없습니다(옛 계약?)',Object.keys(p||{}));
 const flow=TALK.chatFlow(p);
 if(flow)state.chatFlow=flow;   // 화면은 이 수를 해석하지 않는다 — 다음 요청에 그대로 돌려보낼 뿐(경계는 서버가 센다)
 const reply=TALK.reply(p);
 const answer=TALK.answer(p);
 const afilter=TALK.answerFilter(p);
 if(afilter)console.debug('talk/parse answer_filter(서버 내부 사유 — 화면에 싣지 않음)',afilter);
 if(TALK.answerError(p))console.warn('talk/parse answer 경로 실패(서버 사유)',TALK.answerError(p));
 // ── 잡담 5회차~ : 말풍선을 만들지 않는다 ────────────────────────────────────
 // 사장님 지시는 「양해를 구하고 답변하지 않는다」이고, 그 양해는 4회차(stage='guide')에
 // 이미 한 번 나갔다. 여기서 짧은 안내를 다시 말풍선으로 내면 그것도 «답변»이고, 잡담이
 // 이어지는 동안 같은 문장이 매 턴 쌓여 대화 기록이 안내문으로 덮인다(4회차 한 번이라는
 // 지시도 사실상 깨진다). 그래서 **대화에는 아무것도 남기지 않는다**.
 // 다만 화면이 죽은 것처럼 보이면 안 되므로, 기록에 남지 않는 toast 로 «받긴 했다»만
 // 알린다(말풍선 아님 · history 에 안 들어감 · 3.2초 뒤 사라짐). 입력창은 그대로 살아
 // 있다 — PC 질문 한 마디면 서버가 카운터를 0 으로 되돌려 즉시 복귀한다(④⑤).
 //
 // ★ 2026-09-21 — **`answer` 가 있으면 침묵하지 않는다.** 서버 talk.py(수-3)가 같은
 //   판단을 이미 했다: 침묵은 「PC 견적 창구에서 무관한 잡담을 끊는다」는 규약이지
 //   「게임 질문에 답하지 않는다」가 아니다. 화면에도 같은 병이 있었다 — 여기서 끊으면
 //   서버가 애써 만든 답이 버려진다. 답이 있으면 그것만 그리고(되묻기 reply 는 이 단계에
 //   애초에 비어 있다) 격자로는 가지 않는다.
 if(TALK.silent(p)){
  console.debug('talk/parse silent — 잡담 단계',TALK.stage(p),TALK.chatFlow(p));
  if(answer)drawAnswer(p);
  else toast('PC 견적 이야기를 해주시면 이어서 도와드릴게요.');
  setBusy(false);return;
 }
 // ★ answer(질문에 대한 답) + reply(되묻기)를 **한 말풍선**에 쌓는다.
 //   둘을 따로 addMessage 하면 고객이 «두 사람이 말한다»고 느낀다(사장님 화면 = 상담 창구).
 //   answer 가 비어 있으면(잡담 턴 — 실측 '오늘 날씨 좋네요' -> answer:'') reply 만 그려
 //   지금까지의 동작이 그대로 유지된다.
 if(answer||reply){
  drawAnswer(p);
  // 이력에는 **한 줄로 접어** 넣는다. answer 가 600자까지 오는데 그대로 쌓으면 다음 턴
  // 프롬프트가 답변문으로 덮인다(서버도 300자로 자른다 — pushHistory).
  pushHistory('assistant',answer||reply);
 }
 const dropped=TALK.dropped(p);
 if(dropped.length){addMessage('assistant','반영하지 못한 조건: '+dropped.map(d=>`${d.field||d.l||'?'}=${d.value??d.v??'?'}(${d.reason||'사유 없음'})`).join(' · '));}
 if(TALK.evidence(p).length)console.debug('talk/parse evidence',TALK.evidence(p));
 if(TALK.pcRelated(p)===false){setBusy(false);return;}   // 서버 판정 — 카드로 가지 않는다(null 은 모름이라 진행)
 const missing=TALK.missing(p);
 if(missing.length){console.debug('talk/parse missing — 격자를 부르지 않는다(AI 가 reply 로 되물었다)',missing);setBusy(false);return;}
 if(!next){setBusy(false);return;}   // state 가 없으면 격자에 보낼 것이 없다
 await recommend({missingWasEmpty:true});
 setBusy(false);
}

// ── ② state → 격자 카드(용도별 card_sets, 카드마다 3종 내장) ─────────────────
async function recommend(opts){
 if(!state.talk){toast('먼저 용도와 예산을 말씀해 주세요.');return;}
 document.querySelectorAll('[data-select]').forEach(b=>b.disabled=true);
 let g;
 try{g=await api('POST','/api/grid/recommend',{state:state.talk});}
 catch(e){showError(e,()=>{setBusy(true);recommend(opts).finally(()=>setBusy(false));});return;}
 const notes=GRID.internalNotes(g);
 if(notes.length)console.debug('grid/recommend notes(서버 내부 사유 — 화면에 싣지 않음)',notes);
 state.grid=g;state.quotes=flattenSets(g).map(x=>x.card);state.selected=null;state.cardVariant={};
 $('#workspace').classList.remove('has-quote','mobile-quote');
 const needs=GRID.needs(g);
 if(needs.length){   // 서버가 더 필요하다고 한 것 — 카드 없이 끝. 안내 문구도 띄우지 않는다(되묻기는 AI 의 reply 뿐)
  if(opts&&opts.missingWasEmpty)console.warn('grid/recommend needs 가 있는데 talk/parse missing 은 비어 있었다 — 두 서버의 판정이 어긋남',needs,state.talk);
  else console.debug('grid/recommend needs',needs);
  return;
 }
 const node=document.createElement('div');node.className='message recommendation-message';
 node.innerHTML=conditionsMarkup(state.talk,state.usages)+recommendationMarkup(g);
 $('#messages').append(node);setQuick();
 requestAnimationFrame(()=>{const m=$('#messages');m.scrollTop=node.offsetTop-m.offsetTop-16;});
 loadUsages(node);
 for(const s of GRID.sets(g)){
  if(GRID.setKind(s)==='sold'&&s.game_context){try{const slot=node.querySelector(`[data-sold-game-context="${CSS.escape(GRID.setUsage(s))}"]`);const el=slot&&gameContextElement(s.game_context,document);if(el)slot.replaceWith(el);}catch(e){console.warn('sold: game_context 렌더 실패',e);}}
  if(GRID.setKind(s)!=='sold'&&GRID.setUsageGrid(s)===USAGE_AI)await workstations(node,g,s);
 }
}
async function loadUsages(node){
 if(!state.usages){try{const u=await api('GET','/api/usages');state.usages=Array.isArray(u.usages)?u.usages:[];}catch(e){state.usages=null;const box=node.querySelector('.purpose-options');if(box)box.innerHTML=`<span class="condition-note">용도 목록을 불러오지 못했습니다 — ${esc(e.message)}</span>`;return;}}
 const box=node.querySelector('.purpose-options');if(box)box.innerHTML=purposeButtons(state.usages,state.talk);
}

// ── ③ AI 워크스테이션 진열 — 격자 카드와 별도(set 의 용도===AI 일 때만) ─────
async function workstations(node,g,s){
 const usage=GRID.setUsageGrid(s);
 const slot=node.querySelector(`[data-workstations][data-set-usage="${CSS.escape(usage)}"]`)||node.querySelector('[data-workstations]');if(!slot)return;
 const q=new URLSearchParams({usage});
 const budget=GRID.budgetWon(g)??ST.budgetWon(state.talk);
 const bound=GRID.budgetBound(g)||ST.budgetBound(state.talk);
 if(Number.isFinite(budget))q.set('budget_won',String(budget));
 if(bound)q.set('budget_bound',bound);
 let w;
 try{w=await api('GET','/api/grid/workstations?'+q.toString());}
 catch(e){slot.innerHTML=`<p class="condition-note">AI 워크스테이션 진열을 불러오지 못했습니다 — ${esc(e.message)} <button class="secondary" data-action="retry">다시 시도</button></p>`;state.retry=()=>workstations(node,g,s);return;}
 if(w&&w.note)console.debug('grid/workstations note(서버 내부 사유 — 화면에 싣지 않음)',w.note);
 slot.innerHTML=workstationsMarkup(w);
}

// ── A-135: 카드 안 탭 전환 — 재조회 없이 DOM 만 갱신 ────────────────────────
function setCardVariant(index,key){
 state.cardVariant[index]=key;
 const card=state.quotes[index];if(!card)return;
 const article=document.querySelector(`.rec-card[data-card-index="${index}"]`);
 if(!article)return;
 const entry=flattenSets(state.grid)[index];
 const html=cardMarkup(card,index,entry?entry.centerTier:null,key);
 const tmp=document.createElement('div');tmp.innerHTML=html;
 article.replaceWith(tmp.firstElementChild);
}
function setQuoteVariant(key){
 state.selectedVariant=key;
 renderQuote();
}

// ── 카드 선택 → 오른쪽 패널(서버 카드 그대로, 선택 당시 탭을 이어받는다) ───
function selectQuote(index,variantKey){const q=state.quotes[index];if(!q)return;state.selected=copy(q);state.selectedIndex=index;state.selectedVariant=variantKey||state.cardVariant[index]||DEFAULT_VARIANT;$('#workspace').classList.add('has-quote');addMessage('user',(tierDisplayName(q)||'선택한 구성')+' 자세히 볼게요.');addMessage('assistant','오른쪽에 부품과 이유를 펼쳤어요. '+NOT_READY);renderQuote();selectTab('quote');}
function renderQuote(){
 const q=state.selected;if(!q)return;
 const pane=$('#quotePane');
 pane.innerHTML=quoteMarkup(q,state.selectedVariant);
 // game_context 는 innerHTML 뒤에 심는다 — 이 블록이 던져도 위 견적 패널은 이미
 // 그려진 뒤다(순서가 곧 가드다. §화면이 죽으면 조용히 다른 것을 판다 전례 —
 // cap=null 을 toLocaleString 에 넘겨 TypeError 가 나자 뒷단 전체가 멈춘 적이 있다).
 try{
  const el=gameContextElement(GRID.gameContext(q),document);
  if(el){
   const anchor=pane.querySelector('.quote-reason');
   const before=pane.querySelector('.parts-heading');
   if(anchor)anchor.after(el);
   else if(before)before.before(el);
   else pane.appendChild(el);
  }
 }catch(e){console.warn('renderQuote: game_context 렌더 실패',e);}
}
// 부품 교체 대화 API 는 아직 없다 — 구성이 선택된 뒤의 입력은 준비 중으로 답한다. 선택 전이면 파서로(조건 변경).
function requestChange(text){
 text=(text||'').trim();if(!text)return;
 if(!state.selected){submit(text);return;}
 addMessage('user',text);addMessage('assistant',NOT_READY+' 예산·용도를 바꾸려면 「＋ 새 대화」에서 다시 말씀해 주세요.');
}
function selectTab(tab){$('#workspace').classList.toggle('mobile-quote',tab==='quote');document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));}
function save(){if(!state.selected)return;const om=omissionFor(state.selected,state.selectedVariant);if(om){toast('두지 않기로 한 구성이라 저장할 내용이 없어요.');return;}const v=variantsOf(state.selected)[state.selectedVariant]||variantsOf(state.selected).reco;if(!v)return;const flat={name:tierDisplayName(state.selected),total:v.total,parts:normalizeParts(v.items||v.parts),talk:state.talk?copy(state.talk):null,savedAt:new Date().toISOString()};state.saved.unshift(flat);state.saved=state.saved.slice(0,10);try{localStorage.setItem(SAVE_KEY,JSON.stringify(state.saved));toast('이 브라우저에 견적을 저장했어요.');}catch{toast('브라우저 저장이 제한되어 이번 화면에서만 보관해요.');}$('#savedCount').textContent=state.saved.length;}
function showSaved(){$('#savedList').innerHTML=state.saved.length?state.saved.map((q,i)=>`<div class="saved-item"><div><b>${esc(q.name)}</b><small>${money(q.total)}원 · ${new Date(q.savedAt).toLocaleDateString('ko-KR')}</small><small class="saved-fee-note" data-assembly-fee-note="short">${esc(feeNote('short'))}</small></div><button class="primary" data-load="${i}">불러오기</button></div>`).join(''):'<div class="empty-saved">아직 저장한 견적이 없어요.<br>구성을 선택한 뒤 “견적 저장”을 눌러주세요.</div>';$('#savedDialog').showModal();}
// 조건 다이얼로그 — 현재 값은 state.talk(서버 TalkState)에서 읽는다. 제출은 문장으로 파서에 보낸다(init 참고) —
// 화면이 state 를 직접 고쳐 recommend 를 부르면 서버 검증(§5)을 건너뛰게 되므로 하지 않는다.
async function showConditions(){const f=$('#conditionsForm');const won=ST.budgetWon(state.talk);f.elements.budget.value=won!=null?Math.round(won/10000):'';const cur=ST.usages(state.talk);
 if(!state.usages){try{const u=await api('GET','/api/usages');state.usages=Array.isArray(u.usages)?u.usages:[];}catch(e){toast('용도 목록을 불러오지 못했습니다 — '+e.message);}}
 const sel=f.elements.purpose;sel.innerHTML=(state.usages||[]).map(u=>`<option value="${esc(u.label)}"${u.label===cur[0]?' selected':''}>${esc(u.label)}</option>`).join('')||(cur[0]?`<option value="${esc(cur[0])}" selected>${esc(cur[0])}</option>`:'');f.elements.monitor.checked=ST.exclude(state.talk).includes('모니터 보유');$('#conditionsDialog').showModal();}
function addToCart(){toast('장바구니는 준비 중입니다.');}
function openVideo(q){$('#videoDialog h2').textContent=q?tierDisplayName(q)+' · 대표 예시 이미지':'만들어지는 순간까지, 투명하게.';$('#previewVideo').pause();$('#previewVideo').removeAttribute('src');$('#previewVideo').poster=POSTER;$('#videoPoster').src=POSTER;const video=state.videoUrl;$('#previewVideo').hidden=!video;$('#videoPoster').hidden=!!video;$('#videoEmpty').hidden=!!video;if(video){$('#previewVideo').src=video;$('#previewVideo').load();}$('#videoDialog').showModal();}
function home(){$('#welcome').hidden=false;$('#welcomeFoot').hidden=false;$('#workspace').hidden=true;$('#messages').innerHTML='';$('#quotePane').innerHTML='<div class="quote-empty"><span class="ai-mark">✦</span><h2>마음에 드는 구성을<br>골라주세요.</h2><p>구성을 고르면<br>부품과 이유를 볼 수 있어요.</p></div>';/* 교체 대화가 붙으면 「대화로 조정할 수 있어요」로 되돌린다 */state.selected=null;state.selectedIndex=null;state.selectedVariant=DEFAULT_VARIANT;state.cardVariant={};state.talk=null;state.history=[];state.quotes=[];state.grid=null;state.retry=null;$('#workspace').classList.remove('has-quote','mobile-quote');$('#startInput').value='';window.scrollTo(0,0);$('#startInput').focus();}

document.addEventListener('click',e=>{
 const tabBtn=e.target.closest('[data-variant-key]');
 if(tabBtn&&!tabBtn.disabled){
  const scope=tabBtn.dataset.variantScope,key=tabBtn.dataset.variantKey;
  if(scope==='card')setCardVariant(Number(tabBtn.dataset.variantIndex),key);
  else if(scope==='quote')setQuoteVariant(key);
  return;
 }
 const b=e.target.closest('button');if(!b)return;
 if(b.dataset.close){$('#'+b.dataset.close).close();return;}
 if(b.dataset.prompt){$('#messages').innerHTML='';submit(b.dataset.prompt);return;}
 if(b.dataset.chat){requestChange(b.dataset.chat);return;}
 if(b.dataset.purpose){submit(b.dataset.purpose+'용으로 쓸 거예요');return;}
 if(b.dataset.buildVideo!==undefined){openVideo(state.quotes[Number(b.dataset.buildVideo)]);return;}
 if(b.dataset.select!==undefined){selectQuote(Number(b.dataset.select),b.dataset.selectVariant);return;}
 if(b.dataset.tab){selectTab(b.dataset.tab);return;}
 if(b.dataset.load!==undefined){const q=copy(state.saved[Number(b.dataset.load)]);if(!q)return;$('#savedDialog').close();showWorkspace();state.talk=q.talk&&typeof q.talk==='object'?q.talk:null;q.fromSaved=true;q.quotes={reco:q};state.selected=q;state.selectedVariant='reco';$('#messages').innerHTML='';$('#workspace').classList.add('has-quote');addMessage('assistant','저장한 '+(q.name||'견적')+'을 불러왔어요(저장 시점 값 — 현재 가격·재고와 다를 수 있어요).');setQuick();renderQuote();selectTab('quote');return;}
 const actions={home,saved:showSaved,video:()=>openVideo(state.selected),conditions:showConditions,save,cart:addToCart,retry:()=>{const r=state.retry;state.retry=null;if(r){b.disabled=true;b.dataset.done='1';r();}/* A7: 한 번 누른 '다시 시도'는 성공 후에도 다시 살리지 않는다 */}};
 actions[b.dataset.action]?.();
});
function init(){
 if(!$('#startForm')||!$('#videoFile')||!$('#toast')){setTimeout(init,120);return;}
 if(init.done)return;init.done=true;
 $('#startForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#startInput').value.trim();if(text){$('#messages').innerHTML='';submit(text);}});
 $('#chatForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#chatInput').value.trim();$('#chatInput').value='';requestChange(text);});
 document.querySelectorAll('textarea').forEach(t=>t.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();t.form.requestSubmit();}}));
 // 조건 수정 다이얼로그 — 화면이 조건을 직접 만들지 않는다. 문장으로 바꿔 파서에 보낸다.
 $('#conditionsForm').addEventListener('submit',e=>{e.preventDefault();const f=e.currentTarget;const budget=Number(f.elements.budget.value);const label=f.elements.purpose.value;const parts=[];if(Number.isFinite(budget)&&budget>0)parts.push(`예산 ${budget}만원 이하`);if(label)parts.push(`${label}용`);if(f.elements.monitor.checked)parts.push('모니터는 있어요');$('#conditionsDialog').close();state.selected=null;submit('조건을 바꿀게요. '+parts.join(', '));});
 $('#videoFile').addEventListener('change',e=>{const f=e.target.files[0];if(!f)return;if(!f.type.startsWith('video/')){toast('동영상 파일을 선택해주세요.');return;}if(state.videoUrl)URL.revokeObjectURL(state.videoUrl);state.videoUrl=URL.createObjectURL(f);$('#previewVideo').src=state.videoUrl;$('#previewVideo').hidden=false;$('#videoPoster').hidden=true;$('#videoEmpty').hidden=true;$('#previewVideo').play().catch(()=>toast('재생 버튼을 눌러 영상을 확인해주세요.'));});
 $('#previewVideo').addEventListener('error',()=>{toast('이 브라우저에서 재생 가능한 MP4 또는 WebM 영상을 선택해주세요.');$('#previewVideo').hidden=true;$('#videoPoster').hidden=false;$('#videoEmpty').hidden=false;});
 $('#videoDialog').addEventListener('close',()=>$('#previewVideo').pause());
 document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
 $('#savedCount').textContent=state.saved.length;
}
root.PopcornApp={init,render};
// 선택적 페이지 도구 — 화면과 같은 상태(서버 값)를 읽는다.
if(document.modelContext?.registerTool){
 const lifecycle=new AbortController();
 const toolSpecs=[
  {name:'start_pc_recommendation',description:'Send a Korean PC request to the parser and grid APIs (live server data).',inputSchema:{type:'object',properties:{request:{type:'string',minLength:1,maxLength:300}},required:['request'],additionalProperties:false},async execute(input){if(typeof input?.request!=='string'||!input.request.trim()||input.request.length>300)throw new Error('A request of 1–300 characters is required.');await submit(input.request);return {state:state.talk?copy(state.talk):null,builds:state.quotes.map((q,i)=>{const v=variantsOf(q)[state.cardVariant[i]||DEFAULT_VARIANT];return {index:i,tier:tierDisplayName(q),total:v&&v.total,over_budget:v&&v.over_budget};})};}},
  {name:'select_pc_build',description:'Select one of the current recommendation cards and show it in the quote pane.',inputSchema:{type:'object',properties:{index:{type:'integer',minimum:0}},required:['index'],additionalProperties:false},execute(input){if(!Number.isInteger(input?.index)||!state.quotes[input.index])throw new Error('Choose an available build index.');selectQuote(input.index);const v=variantsOf(state.selected)[state.selectedVariant];return {tier:tierDisplayName(state.selected),total:v&&v.total};}},
  {name:'read_pc_quote',description:'Read the currently selected quote (server card) without modifying it.',annotations:{readOnlyHint:true},inputSchema:{type:'object',properties:{},additionalProperties:false},execute(){return {state:state.talk?copy(state.talk):null,quote:copy(state.selected),variant:state.selectedVariant};}}
 ];
 for(const spec of toolSpecs){try{Promise.resolve(document.modelContext.registerTool({...spec,annotations:{readOnlyHint:false,...spec.annotations}},{signal:lifecycle.signal})).catch(()=>{});}catch{}}
 window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
})(typeof window!=='undefined'?window:globalThis);
