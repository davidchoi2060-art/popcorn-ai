import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Sparkles, X, Send, ArrowRight, Info, Check, ExternalLink, SlidersHorizontal, MessageCircle, RotateCcw} from 'lucide-react';
import './part-advisor.css';

const money = n => `${Number(n || 0).toLocaleString('ko-KR')}원`;
const PURPOSE = {gaming:'게임', office:'사무·일상', creator:'영상·작업'};
const CATEGORY = {cpu:'CPU',board:'메인보드',memory:'메모리',gpu:'그래픽카드',storage:'저장장치',cooler:'CPU 쿨러',case:'케이스',power:'파워'};
const STARTERS = {
  gpu:['그래픽카드만 80만원 이하로 골라줘','MSI와 차이는?','영상 작업도 해요'],
  cpu:['여러 작업을 동시에 해요','내장 그래픽이 필요해요','가격이 중요해요'],
  board:['지금 CPU에 맞춰줘','메모리 확장도 생각해요','가격이 중요해요'],
  memory:['16GB부터 볼게요','32GB가 필요해요','가격이 중요해요'],
  storage:['500GB면 돼요','1TB가 필요해요','가격이 중요해요'],
  cooler:['케이스에 맞춰줘','장착 정보부터 확인','가격이 중요해요'],
  case:['그래픽카드 공간이 중요해요','블랙으로 보고 싶어요','가격이 중요해요'],
  power:['그래픽카드에 맞춰줘','700W 이상으로 볼게요','가격이 중요해요'],
};
const NOTES = {
  gpu:'게임 이름·해상도·원하는 설정에 따라 필요한 GPU가 달라져요. 이 예시는 상품의 표시 메모리와 가격을 비교합니다.',
  cpu:'CPU는 소켓과 사용 조건을 함께 봐요. 코어 수만으로 프로그램의 체감 성능을 확정하지 않아요.',
  board:'선택한 CPU의 소켓과 메모리 규격을 먼저 확인해요. BIOS·출력 단자·확장성은 상세 확인이 필요해요.',
  memory:'총 용량과 판매단위를 함께 봐요. 16GB 단품과 16GB 두 개로 구성된 32GB 키트는 다른 상품이에요.',
  storage:'저장할 파일에 맞춰 용량부터 정해요. M.2 슬롯·규격과 실제 장착 가능 여부는 추가 확인이 필요해요.',
  cooler:'소켓뿐 아니라 케이스 높이와 장착 조건도 중요해요. 소음·온도 측정값은 이 데이터에 없어요.',
  case:'선택한 그래픽카드 길이와 쿨러 높이를 비교해요. 케이블·라디에이터까지 포함한 최종 공간은 별도 확인해요.',
  power:'선택한 GPU의 판매처 권장 파워 표기와 정격 출력을 비교해요. 실제 소비전력·연결 단자 검증은 아직 아니에요.',
};
const clean = s => String(s || '').replace(/\s+/g,'').toLowerCase();
function capacity(p) {
  const text = (p.specs || []).join(' ');
  if (p.category === 'storage') { const m = text.match(/(\d+(?:\.\d+)?)\s*(TB|GB)/i); return m ? Number(m[1]) * (m[2].toUpperCase() === 'TB' ? 1000 : 1) : null; }
  const m = text.match(/총\s*(\d+)GB/) || text.match(/(?:·\s*|^)(\d+)GB/) || text.match(/(\d+)GB\s*단품/);
  return m ? Number(m[1]) : null;
}
function matchesCriteria(p,c) {
  return (!c.requireIntegrated || p.facts?.integratedGraphics === true || p.specs?.some(spec => /내장\s*그래픽\s*(지원|포함)/.test(spec)))
    && (!c.minCapacity || (capacity(p) || 0) >= c.minCapacity)
    && (!c.minWatts || (p.facts?.watts || 0) >= c.minWatts)
    && (!c.maxPrice || p.price <= c.maxPrice)
    && (!c.color || /블랙|BLACK/i.test(`${p.name} ${p.specs?.join(' ')}`));
}
function informativeSpec(p) { return p.specs?.find(s => !/판매단위|미확인/.test(s)) || '상세 사양 확인 필요'; }

export default function PartAdvisor({category, parts=[], selection={}, byId={}, purpose='gaming', budget=0, conflict, onChoose, onClose}) {
  const [input,setInput] = useState('');
  const [criteria,setCriteria] = useState({mode:'balanced',minCapacity:null,minWatts:null,color:null,maxPrice:null,preferredId:null});
  const [focusId,setFocusId] = useState(null);
  const [messages,setMessages] = useState([]);
  const logRef = useRef(null);
  const inputRef = useRef(null);
  const current = byId[selection[category.id]];
  const selected = Object.entries(selection).map(([cat,id]) => ({cat,part:byId[id]})).filter(x => x.part);
  const total = selected.reduce((sum,x) => sum + x.part.price,0);
  const otherTotal = total - (current?.price || 0);
  const numericBudget = Number(budget) || 0;
  const available = numericBudget > 0 ? numericBudget - otherTotal : null;
  const remainingSlots = Math.max(0,8 - selected.length - (current ? 0 : 1));
  const hasConflict = p => typeof conflict === 'function' ? conflict(p,selection,byId) : false;
  const categoryParts = parts.filter(p => p.category === category.id && p.price > 0 && p.stock === 'listed');
  const eligible = categoryParts.filter(p => !hasConflict(p) && !(p.category === 'power' && !p.facts?.watts) && !(p.category === 'cooler' && p.specs?.some(s => s.includes('미확인'))));
  const candidates = useMemo(() => {
    let list = eligible.filter(p => matchesCriteria(p,criteria));
    // Budget is for all currently selected parts, not a GPU-only or component-only budget.
    const within = available !== null ? list.filter(p => p.price <= available) : list;
    if (within.length) list = within;
    return list.sort((a,b) => criteria.preferredId && a.id!==b.id && (a.id===criteria.preferredId || b.id===criteria.preferredId) ? (a.id===criteria.preferredId?-1:1) : criteria.mode === 'capacity' ? (capacity(b) || 0) - (capacity(a) || 0) || a.price - b.price : a.price - b.price).slice(0,3);
  },[parts,selection,byId,category.id,criteria,available]);
  const focused = candidates.find(p => p.id === focusId) || candidates[0];
  const contextIntro = `지금 고른 ${selected.length}개 부품은 그대로 두고, ${category.name} 후보만 함께 볼게요. ${NOTES[category.id]}`;

  useEffect(() => { setMessages([{role:'assistant',text:contextIntro}]); setCriteria({mode:'balanced',minCapacity:null,minWatts:null,color:null}); setFocusId(null); setInput(''); },[category.id]);
  useEffect(() => { if(logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; },[messages]);

  function evidence(p) {
    const reasons=[];
    const number=(part,re)=>Number((part?.specs||[]).join(' ').match(re)?.[1])||null;
    if(criteria.maxPrice) reasons.push(`부품가 ${money(p.price)} ≤ ${category.name} 상한 ${money(criteria.maxPrice)}`);
    if(p.category==='gpu') {
      reasons.push(`표시 사양: ${informativeSpec(p)}`);
      const needed=number(p,/권장 파워 표기 (\d+)W/),watts=byId[selection.power]?.facts?.watts;
      const length=number(p,/길이 (\d+)mm/),space=number(byId[selection.case],/GPU 최대 (\d+)mm/);
      if(needed&&watts) reasons.push(`선택한 파워 ${watts}W ≥ 판매처 권장 ${needed}W`);
      else if(needed) reasons.push(`판매처 권장 ${needed}W · 선택 파워 정격은 아직 미확인`);
      if(length&&space) reasons.push(`선택한 케이스 허용 ${space}mm ≥ 카드 길이 ${length}mm`);
      else if(length) reasons.push(`카드 길이 ${length}mm · 케이스 공간은 아직 미확인`);
    } else {
      reasons.push(`표시 사양: ${informativeSpec(p)}`);
      if(p.facts?.socket) reasons.push(`선택 후보의 소켓: ${p.facts.socket}`);
      if(p.facts?.memoryType) reasons.push(`메모리 규격: ${p.facts.memoryType}`);
      if(criteria.minCapacity) reasons.push(`표시 용량 ${capacity(p)}GB · 요청한 최소 용량 충족`);
      if(p.facts?.watts) reasons.push(`정격 출력: ${p.facts.watts}W`);
    }
    return reasons;
  }
  function why(p) {
    if (!p) return '조건을 만족하는 후보가 없어 먼저 조건을 조정해야 해요.';
    const facts = informativeSpec(p);
    const priceReason = available === null ? `개별 판매가는 ${money(p.price)}예요.` : p.price <= available ? `다른 선택을 유지한 합계 ${money(otherTotal+p.price)}이 전체 예산 ${money(numericBudget)} 안에 있어요.` : `다른 선택을 유지하면 합계 ${money(otherTotal+p.price)}로 전체 예산을 ${money(otherTotal+p.price-numericBudget)} 넘어요.`;
    const specific = category.id === 'gpu' ? `판매처에 ${facts}로 표시돼 있어요. VRAM 표기를 비교할 후보이며, 게임 FPS나 작업 성능을 보장하는 추천은 아니에요.` : `확인한 표기는 ‘${facts}’예요. ${criteria.mode === 'price' ? '조건에 맞는 후보를 낮은 가격부터 비교하도록 정렬했어요.' : '현재 선택과 확인 가능한 기본 규격에서 충돌이 발견되지 않은 후보예요.'}`;
    return `${p.shortName || p.name}: ${specific}\n${evidence(p).join('\n')}\n${priceReason}${remainingSlots ? ` 아직 ${remainingSlots}개 미선택 부품의 비용은 포함하지 않았어요.` : ''} 확인된 표시 규격의 비교이며 전체 호환성 검증은 아니에요.`;
  }
  function compatibilityAnswer(p) {
    if (!p) return '현재 기본 규격에 맞는 후보가 없어요. 선택한 CPU·메모리·파워 등을 함께 확인해야 해요.';
    const next = {...selection,[category.id]:p.id};
    if (typeof conflict === 'function' && conflict(p,next,byId)) return '현재 선택과 확인된 기본 규격이 충돌해요. 이 시안에서는 그 상태로 선택할 수 없어요.';
    const pieces = [];
    if (p.facts?.socket) pieces.push(`소켓 ${p.facts.socket}`);
    if (p.facts?.memoryType) pieces.push(`메모리 ${p.facts.memoryType}`);
    if (category.id === 'gpu' || category.id === 'power') {
      const gpu = category.id === 'gpu' ? p : byId[selection.gpu];
      const psu = category.id === 'power' ? p : byId[selection.power];
      if (gpu) pieces.push(gpu.specs?.find(s => s.includes('권장 파워')) || 'GPU 권장 파워 미확인');
      pieces.push(psu?.facts?.watts ? `선택한 파워 ${psu.facts.watts}W` : '파워 미선택 또는 정격 미확인');
    }
    return `${p.shortName || p.name}은 현재 시안의 기본 규격 필터에서 충돌이 발견되지 않았어요.${pieces.length ? ` 비교한 표기: ${pieces.join(' · ')}.` : ''} 전원 커넥터·BIOS·전체 장착 공간과 실재고까지 검증한 결과는 아니에요.`;
  }
  function ask(raw) {
    const text = raw.trim(); if (!text) return;
    let answer = '', nextCriteria = null;
    const q = clean(text);
    const amount = text.replace(/,/g,'').match(/(\d+(?:\.\d+)?)\s*만\s*원/);
    if (/왜|이유|추천근거/.test(q)) answer = why(focused);
    else if (category.id==='gpu' && /msi|엠에스아이/i.test(q) && /차이|비교|어때|다른/.test(q)) {
      const gigabyte=parts.find(p=>p.id==='128424'),msi=parts.find(p=>p.id==='124631');
      answer=gigabyte&&msi ? `${gigabyte.shortName}과 ${msi.shortName}의 판매처 표시를 비교하면, 각각 ${money(gigabyte.price)} / ${money(msi.price)}으로 MSI가 ${money(msi.price-gigabyte.price)} 높아요. 둘 다 RTX 5060 Ti·GDDR7 8GB로 표시돼요. 길이는 281mm / 227mm로 MSI가 54mm 짧고, 권장 파워 표기는 650W / 600W예요. 실측 성능·소음 우열은 확인하지 못했어요.${criteria.maxPrice&&msi.price>criteria.maxPrice?` MSI는 설정한 그래픽카드 상한 ${money(criteria.maxPrice)}을 ${money(msi.price-criteria.maxPrice)} 넘으므로 현재 추천 카드에서 제외했어요.`:''} 다른 부품은 그대로예요.` : '비교할 두 상품의 자료를 찾을 수 없어 정확히 비교할 수 없어요.';
    }
    else if (amount && !/전체|총예산|총액/.test(q) && /이하|상한|안으로|예산|그래픽카드만|부품만/.test(q)) {
      const maxPrice=Number(amount[1])*10000;
      nextCriteria={...criteria,maxPrice,mode:'price',preferredId:category.id==='gpu'&&maxPrice>=778100?'128424':null};
      const fitting=eligible.filter(p=>matchesCriteria(p,nextCriteria));
      const msi=parts.find(p=>p.id==='124631');
      answer=`${category.name} 한 항목의 상한을 ${money(maxPrice)}으로 설정했어요. 전체 PC 예산 ${numericBudget>0?money(numericBudget):'미입력'}은 바꾸지 않았어요. ${fitting.length?`현재 기본 규격과 이 금액 조건에 맞는 후보 ${fitting.length}개를 비교해볼게요.`:'현재 기본 규격과 이 금액을 동시에 만족하는 후보가 없어요.'}${category.id==='gpu'&&maxPrice===800000&&fitting.some(p=>p.id==='128424')?` GIGABYTE RTX 5060 Ti는 778,100원으로 상한 안에 있어요.${fitting.some(p=>p.id==='128419')?' PALIT RTX 3050은 더 낮은 가격의 별도 사양 대안이에요.':''}`: ''}${category.id==='gpu'&&msi&&msi.price>maxPrice?` MSI RTX 5060 Ti는 ${money(msi.price)}으로 부품 상한을 ${money(msi.price-maxPrice)} 넘어 제외해요.`:''} 적용 후 전체 합계는 카드에서 따로 확인해주세요.`;
    }
    else if (/맞나요|호환|지금cpu|케이스에맞|그래픽카드에맞|장착정보|공간/.test(q)) answer = compatibilityAnswer(focused);
    else if (/더저렴|가격이중요|아끼|싼|저렴한|가성비/.test(q)) {
      nextCriteria = {...criteria,mode:'price',preferredId:null};
      const cheaper = focused && eligible.filter(p => p.id !== focused.id && p.price < focused.price && matchesCriteria(p,criteria)).sort((a,b) => a.price-b.price)[0];
      answer = cheaper ? `${focused?.shortName || '현재 후보'}보다 저렴한 ${cheaper.shortName}은 ${money(cheaper.price)}예요. 차액은 ${money(focused.price-cheaper.price)}이며, 상품 사양이 달라지는 점을 카드에서 비교해주세요. 현재 선택은 바꾸지 않았어요.` : '현재 기본 규격과 조건에 맞는 후보를 낮은 가격부터 다시 보여드려요. 더 낮은 가격의 대안이 없을 수 있고, 지금 고른 부품은 그대로예요.';
    }
    else if (/재고|배송|주문|오늘살|바로살/.test(q)) answer = '이 자료는 2026-10-23에 판매목록과 구매 버튼을 확인한 상품이에요. 실제 보유 수량·현재 주문 가능 여부·배송일은 연결되어 있지 않아 답할 수 없어요. 구매 전 팝콘PC에서 다시 확인해야 해요.';
    else if (/fps|프레임|몇배|벤치|성능보장/.test(q)) answer = '실측 FPS·벤치마크 자료가 없어서 숫자로 성능을 답할 수 없어요. 게임·프로그램, 해상도와 설정을 확인한 뒤 별도 검증이 필요해요. 여기서는 확인된 상품 사양과 가격만 비교해요.';
    else if (/예산|총액|합계|얼마남/.test(q)) answer = `현재 선택 부품 합계는 ${money(total)}이고, 이 ${category.name} 자리를 제외한 합계는 ${money(otherTotal)}예요. ${available === null ? '전체 예산이 입력되지 않았어요.' : `전체 예산 ${money(numericBudget)}에서 이 자리에 사용할 수 있는 금액은 ${available >= 0 ? money(available) : `이미 ${money(-available)} 초과한 상태`}예요.`} 미선택 부품·조립·배송·OS 비용은 별도예요.`;
    else if (category.id === 'gpu' && /영상|편집|작업/.test(q)) { nextCriteria = {...criteria,mode:'capacity',minCapacity:8}; answer = '영상·작업 조건으로 표시 메모리 8GB 이상 후보를 비교해볼게요. VRAM 용량만으로 작업 적합성을 확정하지는 않아요. 사용하는 프로그램·코덱·작업 해상도에 따른 검증이 필요하며, 가격이 예산을 넘으면 그대로 알려드려요.'; }
    else if (category.id === 'gpu' && /게임|fhd|qhd|4k|배그|롤/.test(q)) { nextCriteria = {...criteria,mode:'price',minCapacity:null}; answer = '게임용 후보를 현재 기본 규격과 가격 순서로 보여드릴게요. FHD·QHD·4K와 게임 설정에 따라 결과가 달라지므로 이 예시에서 FPS나 “충분하다”는 판정을 내리지는 않아요. “왜 이 부품인가요?”로 표시 사양과 예산 근거를 확인해보세요.'; }
    else if (category.id === 'memory' && /16gb|32gb/.test(q)) { const amount = q.includes('32gb') ? 32 : 16; nextCriteria = {...criteria,minCapacity:amount,mode:'price'}; answer = `총 ${amount}GB 이상으로 좁혔어요. 카드 가격은 판매단위 1개 또는 1키트 가격이에요. 32GB 키트는 16GB × 2개라는 구성까지 표시하니 단품 가격과 혼동하지 않도록 확인해주세요.`; }
    else if (category.id === 'storage' && /500gb|1tb/.test(q)) { const amount = q.includes('1tb') ? 1000 : 500; nextCriteria = {...criteria,minCapacity:amount,mode:'price'}; answer = `${amount===1000?'1TB':'500GB'} 이상 용량의 후보를 보여드려요. 표시 용량이며 실제 사용 가능 공간은 다를 수 있어요. 메인보드의 M.2 슬롯 수·규격과 기존 저장장치도 구매 전에 확인해야 해요.`; }
    else if (category.id === 'power' && /700w/.test(q)) { nextCriteria = {...criteria,minWatts:700,mode:'price'}; answer = '정격 출력이 확인된 700W 이상 상품만 비교해볼게요. GPU의 권장 파워 표기도 함께 적용하지만 전체 소비전력이나 커넥터 검증을 대신하지는 않아요.'; }
    else if (category.id === 'case' && /블랙|검정/.test(q)) { nextCriteria = {...criteria,color:'black'}; answer = '상품명과 표시 사양에서 블랙 색상이 확인되는 후보로 좁혔어요. 선택한 GPU 길이·쿨러 높이의 확인 가능한 값은 비교하고, 전체 조립 공간은 별도 확인이 필요해요.'; }
    else if (category.id === 'cpu' && /내장그래픽/.test(q)) { nextCriteria = {...criteria,requireIntegrated:true}; answer = '내장 그래픽이 필요하다는 조건을 반영했어요. “내장그래픽 없음”인 CPU는 제외하고, 지원 근거가 확인된 상품만 추천할게요. 현재 조사 자료에는 지원 확정 근거가 없어 후보를 보류합니다. 정확한 모델의 공식 사양을 확인한 뒤 선택해야 해요.'; }
    else if (category.id === 'cpu' && /동시|여러작업/.test(q)) answer = '각 CPU의 코어·스레드 표기를 카드에서 비교할 수 있어요. 다만 프로그램과 병렬 처리 방식에 따라 결과가 달라 코어 수만으로 더 빠르다고 정하지는 않을게요. 현재 소켓 조건과 예산에 맞는 후보를 유지했어요.';
    else if (category.id === 'board' && /확장|메모리슬롯/.test(q)) answer = '메인보드 카드에 표시된 메모리 슬롯 수를 비교해주세요. 지금 선택한 CPU 소켓·메모리 규격과 맞는 후보만 유지하며, 최대 용량·메모리 호환 목록과 BIOS는 추가 확인이 필요해요.';
    else answer = '이 질문은 현재 규칙형 상담 예시에 준비된 범위를 벗어나 정확히 답할 수 없어요. 실제 LLM에는 아직 연결되지 않았어요. 아래 질문으로 가격·표시 사양·현재 구성의 기본 규격을 비교할 수 있어요.';
    if (nextCriteria) {setCriteria(nextCriteria);setFocusId(null);}
    setMessages(m => [...m.slice(-11),{role:'user',text},{role:'assistant',text:answer}]);setInput('');
  }
  function tradeoff(p) {
    const lower = eligible.filter(x => x.price < p.price && matchesCriteria(x,criteria)).sort((a,b) => a.price-b.price)[0];
    if (lower) return `${lower.shortName}보다 ${money(p.price-lower.price)} 높아요. ${informativeSpec(p)} 표기가 필요한지 비교해보세요.`;
    return '현재 질문 조건에 맞는 조사 후보 중 가장 낮은 가격이에요. 더 비싼 상품과 사양은 다를 수 있어요.';
  }
  const chips = [PURPOSE[purpose] || '용도 확인', numericBudget>0 ? `전체 예산 ${money(numericBudget)}` : '전체 예산 미입력',criteria.maxPrice?`${category.name} 상한 ${money(criteria.maxPrice)}`:null,criteria.mode==='price'?'가격 비교':criteria.mode==='capacity'?'표시 용량 비교':'기본 규격 우선',criteria.minCapacity?`${category.id==='storage'&&criteria.minCapacity>=1000?`${criteria.minCapacity/1000}TB`:`${criteria.minCapacity}GB`} 이상`:null,criteria.minWatts?`${criteria.minWatts}W 이상`:null,criteria.color?'블랙':null,criteria.requireIntegrated?'내장 그래픽 지원 확인 필요':null].filter(Boolean);

  return <div className="part-advisor">
    <header className="pa-header"><div><span className="pa-demo"><Sparkles size={14}/> AI 상담 예시 · 실제 LLM 연결 전</span><h2>{category.name}, 이유를 듣고 골라보세요.</h2><p>지금 고른 부품은 유지하고, 이 항목만 함께 비교해요.</p></div><button type="button" className="pa-close" onClick={onClose} aria-label={`${category.name} AI 상담 닫기`}><X size={22}/></button></header>
    <div className="pa-context"><div className="pa-chips" aria-label="상담에 반영한 조건">{chips.map(c=><span key={c}>{c}</span>)}</div><details className="pa-selection"><summary>현재 선택 {selected.length}개 · {money(total)}</summary><ul>{selected.length?selected.map(({cat,part})=><li key={cat}><span>{CATEGORY[cat]}</span><strong>{part.shortName}</strong></li>):<li>아직 선택한 부품이 없어요.</li>}</ul></details>{current&&<p className="pa-current"><Check size={14}/> 현재 {current.shortName} 선택 유지 중 · 선택 버튼을 누르기 전에는 바뀌지 않아요.</p>}</div>
    <div className="pa-layout">
      <section className="pa-conversation" aria-label="부품 상담 예시"><div className="pa-section-title"><MessageCircle size={17}/><h3>조건을 더 알려주세요</h3></div><div className="pa-chatlog" ref={logRef} role="log" aria-live="polite" aria-relevant="additions">{messages.map((m,i)=><div key={`${category.id}-${i}`} className={`pa-message ${m.role}`}><span className="pa-speaker">{m.role==='assistant'?'AI 상담 예시':'나'}</span><p>{m.text}</p></div>)}</div><div className="pa-starters" aria-label="조건 질문">{STARTERS[category.id]?.map(q=><button type="button" key={q} onClick={()=>ask(q)}>{q}</button>)}</div><form className="pa-input" onSubmit={e=>{e.preventDefault();ask(input);}}><label htmlFor={`pa-question-${category.id}`}>추가 질문</label><div><input ref={inputRef} id={`pa-question-${category.id}`} maxLength={300} value={input} onChange={e=>setInput(e.target.value)} placeholder="가격이나 현재 구성과의 차이를 물어보세요"/><button type="submit" disabled={!input.trim()} aria-label="추가 질문 보내기"><Send size={18}/></button></div></form><p className="pa-example-note">입력은 이 화면의 예시 답변에만 사용돼요. 외부로 전송되지 않아요.</p></section>
      <section className="pa-recommendations" aria-label={`${category.name} 추천 후보`}><div className="pa-section-title"><SlidersHorizontal size={17}/><h3>지금 조건의 후보</h3><span>최대 3개</span></div><div className="pa-budget"><span>다른 선택 부품 합계 <strong>{money(otherTotal)}</strong></span><span>{available===null?'전체 예산을 정하면 금액을 비교해요.':available>=0?`전체 예산에서 이 자리에 남은 금액 ${money(available)}`:`다른 선택만으로 전체 예산 ${money(-available)} 초과`}</span>{remainingSlots>0&&<small>아직 고르지 않은 나머지 {remainingSlots}개 부품 비용은 제외된 금액이에요.</small>}</div><div className="pa-card-list">{candidates.map((p,index)=>{const chosen=current?.id===p.id, over=available!==null&&p.price>available;return <article key={p.id} className={`pa-card ${p.id===focused?.id?'focused':''}`}><div className="pa-card-top"><img src={p.image} alt={p.shortName}/><div><div className="pa-card-tags"><span>{chosen?'현재 선택':index===0?'먼저 비교할 후보':'함께 볼 대안'}</span>{over&&<span className="over">전체 예산 초과</span>}</div><h4>{p.shortName || p.name}</h4><p className="pa-product-full">{p.name}</p><p className="pa-specs">{p.specs?.join(' · ')}</p></div></div><div className="pa-reason"><strong><Sparkles size={13}/> 왜 이 후보인가요?</strong><ul className="pa-evidence">{evidence(p).map(reason=><li key={reason}>{reason}</li>)}</ul><small>{tradeoff(p)}</small></div><div className="pa-price"><div><strong>{money(p.price)}</strong><span>{p.unit} 기준 · 개별 부품가</span></div><small>이 부품 적용 후 선택 합계 <b>{money(otherTotal+p.price)}</b></small></div><div className="pa-card-actions"><button type="button" className="pa-question-button" onClick={()=>{setFocusId(p.id);setMessages(m=>[...m.slice(-11),{role:'user',text:`${p.shortName}, 왜 추천하나요?`},{role:'assistant',text:why(p)}]);}}>이유 더 듣기</button><button type="button" className="pa-choose" onClick={()=>onChoose(p)} disabled={hasConflict(p)}>{chosen?'현재 선택 유지':'이 부품 선택'}{chosen?<Check size={16}/>:<ArrowRight size={16}/>}</button></div><a className="pa-source" href={p.sourceUrl} target="_blank" rel="noreferrer">팝콘PC 원상품 {p.id}<ExternalLink size={11}/></a></article>;})}</div>{!candidates.length&&<div className="pa-empty"><Info size={26}/><h4>지금 조건으로 제안할 후보가 없어요.</h4><p>규격이 충돌하거나 요청한 용량·정격을 확인할 수 없는 상품은 제외했어요. 선택한 부품을 유지한 채 조건부터 다시 살펴보세요.</p><button type="button" onClick={()=>{setCriteria({mode:'balanced',minCapacity:null,minWatts:null,color:null});setFocusId(null);}}><RotateCcw size={15}/>상담 조건만 초기화</button></div>}<div className="pa-followups" aria-label="추천 부품에 추가 질문"><span>{focused?`${focused.shortName}에 대해`:'현재 조건에 대해'}</span>{['왜 이 부품인가요?','더 저렴한 대안','지금 고른 부품과 맞나요?'].map(q=><button type="button" key={q} onClick={()=>ask(q)}>{q}</button>)}</div></section>
    </div><footer className="pa-footer"><Info size={15}/><p>2026-10-23 조사 상품·판매가 기반의 규칙형 예시예요. 전체 호환성·실재고·실시간 가격은 미확인이며, 조립·배송·OS 비용은 별도예요.</p></footer>
  </div>;
}
