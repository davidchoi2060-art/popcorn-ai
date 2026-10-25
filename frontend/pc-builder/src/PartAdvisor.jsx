import React, {useEffect, useRef, useState} from 'react';
import {Sparkles, X, Send, ArrowRight, Info, Check, ExternalLink, SlidersHorizontal, MessageCircle, RotateCcw, AlertCircle, Loader2} from 'lucide-react';
import {advise, ApiError, budgetValue, selectionKey} from './api.js';
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
const AI_LABEL = {ok:'AI 답변', skipped:'서버 안내', fallback:'서버 확인 후보', invalid:'서버 확인 후보', unavailable:'서버 확인 후보', limited:'서버 확인 후보', unconfigured:'서버 확인 후보'};

export default function PartAdvisor({category, byId={}, selection={}, purpose='gaming', budget=0, onChoose, onClose}) {
  const [input,setInput] = useState('');
  const [messages,setMessages] = useState([]);          // 화면에 보이는 대화(AI 답·서버 안내 포함)
  const [conditions,setConditions] = useState({partBudget:null,totalBudget:null});
  const [result,setResult] = useState(null);            // 마지막 서버 응답(추천·후보·예산 판단)
  const [loading,setLoading] = useState(false);
  const [choices,setChoices] = useState([]);            // 예산 확인 질문의 선택지
  const [failed,setFailed] = useState(null);            // 다시 보낼 질문(시간 초과·연결 실패)
  const logRef = useRef(null);
  const seq = useRef(0);
  const ctrl = useRef(null);
  const current = byId[selection[category.id]];
  const selected = Object.entries(selection).map(([cat,id]) => ({cat,part:byId[id]})).filter(x => x.part);
  const total = selected.reduce((sum,x) => sum + (x.part.price || 0),0);
  const askedKey = useRef(selectionKey(selection));

  useEffect(() => { if(logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; },[messages,loading]);
  useEffect(() => {
    setMessages([{role:'assistant',kind:'server',text:`지금 고른 ${selected.length}개 부품은 그대로 두고, ${category.name} 후보를 서버에서 확인한 뒤 AI가 추천 이유와 대안을 알려드릴게요.`}]);
    setConditions({partBudget:null,totalBudget:null}); setResult(null); setChoices([]); setFailed(null);
    send(null, []);
    return () => ctrl.current?.abort();
  },[category.id]);

  async function send(question, history, nextConditions=conditions) {
    ctrl.current?.abort();
    const mine = ++seq.current, c = new AbortController(); ctrl.current = c;
    askedKey.current = selectionKey(selection);
    setLoading(true); setFailed(null); setChoices([]);
    try {
      const r = await advise({category:category.id, selection, purpose, budgetTotal:budgetValue(budget), conditions:nextConditions,
                              question:question || null, history:history.filter(m => m.kind !== 'server').slice(-8).map(m => ({role:m.role,text:m.text}))}, {signal:c.signal});
      if (mine !== seq.current) return;                                      // 더 늦게 보낸 질문이 있다
      if (selectionKey(selection) !== askedKey.current) return;              // 그 사이 구성이 바뀌었다
      if (r.kind === 'clarify') {
        setMessages(m => [...m.slice(-15),{role:'assistant',kind:'server',text:r.question}]);
        setChoices(r.choices || []);
        if (r.conditions) setConditions(r.conditions);
        return;
      }
      setResult(r); setConditions(r.conditions || nextConditions);
      setMessages(m => [...m.slice(-15),{role:'assistant',kind:r.ai?.status === 'ok' ? 'ai' : 'server',text:r.answer}]);
    } catch (e) {
      if (mine !== seq.current || (e instanceof ApiError && e.kind === 'cancel')) return;
      setMessages(m => [...m.slice(-15),{role:'assistant',kind:'server',error:true,text:e instanceof ApiError ? e.message : '답변을 받지 못했어요. 다시 시도해 주세요.'}]);
      if (!(e instanceof ApiError) || ['timeout','network','server'].includes(e.kind)) setFailed({question, history});
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }
  function ask(raw) {
    const text = String(raw || '').trim(); if (!text || loading) return;
    const history = [...messages,{role:'user',text}];
    setMessages(m => [...m.slice(-15),{role:'user',text}]); setInput('');
    send(text, history);
  }
  function resetConditions() {
    const empty = {partBudget:null,totalBudget:null};
    setConditions(empty);
    setMessages(m => [...m.slice(-15),{role:'assistant',kind:'server',text:'상담 조건(부품 예산·이번 질문의 전체 예산)을 지웠어요. 구성은 그대로예요.'}]);
    send(null, [], empty);
  }

  const recs = result?.recommendations || [];
  const others = (result?.candidates || []).filter(c => !recs.some(r => r.id === c.id));
  const ai = result?.ai;
  const numericBudget = conditions.totalBudget || budgetValue(budget) || 0;
  const otherTotal = result?.otherTotal ?? (total - (current?.price || 0));
  const feas = result?.feasibility;
  const chips = [PURPOSE[purpose] || '용도 확인', numericBudget>0 ? `전체 예산 ${money(numericBudget)}` : '전체 예산 미입력',
    conditions.partBudget ? `${category.name} 상한 ${money(conditions.partBudget)}` : null,
    result ? `서버 확인 후보 ${(result.candidates || []).length}개` : null].filter(Boolean);

  function card(p, index, isRec) {
    const part = byId[p.id], chosen = current?.id === p.id;
    const over = p.withinTotalBudget === false, overPart = p.withinPartBudget === false;
    return <article key={p.id} className={`pa-card ${index===0&&isRec?'focused':''}`}>
      <div className="pa-card-top"><img src={part?.image} alt={p.shortName}/><div>
        <div className="pa-card-tags"><span>{chosen?'현재 선택':isRec?(p.label||'추천'):'함께 볼 후보'}</span>{overPart&&<span className="over">부품 상한 초과</span>}{over&&<span className="over">전체 예산 초과 가능</span>}{p.state==='unknown'&&<span className="over">규격 확인 필요</span>}</div>
        <h4>{p.shortName || p.name}</h4><p className="pa-product-full">{p.name}</p>{part?.specs?.length?<p className="pa-specs">판매처 표기(조사 시점): {part.specs.join(' · ')}</p>:null}</div></div>
      <div className="pa-reason"><strong><Sparkles size={13}/> {isRec&&ai?.status==='ok'?'왜 이 후보인가요?':'서버가 확인한 근거'}</strong>
        {isRec&&p.reason?<p className="pa-ai-reason">{p.reason}</p>:null}
        <ul className="pa-evidence">{Object.entries(p.facts || {}).slice(0,4).map(([k,v]) => <li key={k}>{k}: {Array.isArray(v)?v.join(', '):String(v)}</li>)}
          <li>{p.state==='ok'?'고른 부품과 서버 호환 판정 통과':`확인 필요: ${(p.checks||[]).join(', ')}`}</li>{(p.notes||[]).map(n => <li key={n}>{n}</li>)}</ul>
        {isRec&&p.tradeoff?<small>{p.tradeoff}</small>:null}</div>
      <div className="pa-price"><div><strong>{money(p.price)}</strong><span>{part?.unit || '1개'} 기준 · 서버 판매가</span></div><small>{p.priceDiff!=null?`지금 선택보다 ${p.priceDiff>=0?'+':''}${money(p.priceDiff)} · `:''}이 부품 적용 후 선택 합계 <b>{money(p.totalAfter)}</b></small></div>
      <div className="pa-card-actions"><button type="button" className="pa-question-button" disabled={loading} onClick={()=>ask(`${p.shortName}, 왜 이 부품을 추천하나요? 다른 후보와 비교해 주세요.`)}>이유 더 듣기</button>
        <button type="button" className="pa-choose" disabled={!part || loading} onClick={()=>onChoose(part)}>{chosen?'현재 선택 유지':'이 부품 선택'}{chosen?<Check size={16}/>:<ArrowRight size={16}/>}</button></div>
      {part?.sourceUrl&&<a className="pa-source" href={part.sourceUrl} target="_blank" rel="noreferrer">팝콘PC 원상품 {p.id}<ExternalLink size={11}/></a>}
    </article>;
  }

  return <div className="part-advisor">
    <header className="pa-header"><div><span className="pa-demo"><Sparkles size={14}/> AI 상담 · 서버가 확인한 후보 안에서 추천</span><h2>{category.name}, 이유를 듣고 골라보세요.</h2><p>지금 고른 부품은 유지하고, 이 항목만 함께 비교해요. 질문만으로 구성은 바뀌지 않아요.</p></div><button type="button" className="pa-close" onClick={onClose} aria-label={`${category.name} AI 상담 닫기`}><X size={22}/></button></header>
    <div className="pa-context"><div className="pa-chips" aria-label="상담에 반영한 조건">{chips.map(c=><span key={c}>{c}</span>)}</div><details className="pa-selection"><summary>현재 선택 {selected.length}개 · {money(total)}</summary><ul>{selected.length?selected.map(({cat,part})=><li key={cat}><span>{CATEGORY[cat]}</span><strong>{part.shortName}</strong></li>):<li>아직 선택한 부품이 없어요.</li>}</ul></details>{current&&<p className="pa-current"><Check size={14}/> 현재 {current.shortName} 선택 유지 중 · 선택 버튼을 누르기 전에는 바뀌지 않아요.</p>}</div>
    <div className="pa-layout">
      <section className="pa-conversation" aria-label="부품 상담"><div className="pa-section-title"><MessageCircle size={17}/><h3>조건을 더 알려주세요</h3></div>
        <div className="pa-chatlog" ref={logRef} role="log" aria-live="polite" aria-relevant="additions">{messages.map((m,i)=><div key={`${category.id}-${i}`} className={`pa-message ${m.role} ${m.error?'error':''}`}><span className="pa-speaker">{m.role==='assistant'?(m.kind==='ai'?'AI 답변':'서버 안내'):'나'}</span><p>{m.text}</p></div>)}
          {loading&&<div className="pa-message assistant pa-loading"><span className="pa-speaker">AI 답변</span><p><Loader2 size={15} className="pa-spin"/> 서버가 후보·가격·호환을 확인하고 AI가 답을 쓰고 있어요…</p></div>}</div>
        {failed&&!loading&&<button type="button" className="pa-retry" onClick={()=>send(failed.question, failed.history)}><RotateCcw size={14}/> 다시 시도</button>}
        <div className="pa-starters" aria-label="조건 질문">{(choices.length?choices:(result?.followUps?.length?result.followUps:STARTERS[category.id]))?.map(q=><button type="button" key={q} disabled={loading} onClick={()=>ask(q)}>{q}</button>)}</div>
        <form className="pa-input" onSubmit={e=>{e.preventDefault();ask(input);}}><label htmlFor={`pa-question-${category.id}`}>추가 질문</label><div><input id={`pa-question-${category.id}`} maxLength={300} value={input} onChange={e=>setInput(e.target.value)} placeholder="예산이나 용도, 다른 후보와의 차이를 물어보세요"/><button type="submit" disabled={!input.trim()||loading} aria-label="추가 질문 보내기"><Send size={18}/></button></div></form>
        <p className="pa-example-note">질문은 AI 상담을 위해 서버로 보내요. 연락처·카드번호 같은 개인정보는 적지 마세요(적으면 가려서 보내요).</p></section>
      <section className="pa-recommendations" aria-label={`${category.name} 추천 후보`}><div className="pa-section-title"><SlidersHorizontal size={17}/><h3>지금 조건의 후보</h3><span>{ai?AI_LABEL[ai.status]||'서버 확인 후보':'확인 중'}</span></div>
        <div className="pa-budget"><span>다른 선택 부품 합계 <strong>{money(otherTotal)}</strong></span>
          {feas?.status==='over'&&<span className="pa-warn">고른 부품을 유지하면 {category.name}을 포함한 최소 구성 {money(feas.minTotal)} · 전체 예산보다 {money(feas.shortfall)} 부족</span>}
          {feas?.status==='feasible'&&<span>고른 부품 유지 시 최소 구성 {money(feas.minTotal)} · 전체 예산에서 {money(feas.headroom)} 여유</span>}
          {feas?.status==='no_budget'&&<span>전체 예산을 정하면 남은 금액을 함께 비교해요.</span>}
          {result?.restMin>0&&<small>아직 고르지 않은 다른 자리를 가장 싸게 채우면 {money(result.restMin)}이 더 들어요(서버 확인 후보 기준).</small>}</div>
        {ai&&ai.status!=='ok'&&ai.message&&<div className="pa-ai-note"><AlertCircle size={16}/><p>{ai.message}</p></div>}
        <div className="pa-card-list">{recs.map((p,i)=>card(p,i,true))}{others.slice(0,Math.max(0,3-recs.length)).map((p,i)=>card(p,i+recs.length,false))}</div>
        {result&&!recs.length&&!others.length&&<div className="pa-empty"><Info size={26}/><h4>지금 조건으로 제안할 후보가 없어요.</h4><p>{result.answer}</p>{(result.excluded||[]).length>0&&<p className="pa-excluded">담을 수 없는 상품: {result.excluded.map(x=>`${x.shortName}(${x.reason})`).join(', ')}</p>}<button type="button" onClick={resetConditions}><RotateCcw size={15}/>상담 조건만 초기화</button></div>}
        {(result?.feasibility?.relax||[]).length>0&&<div className="pa-relax"><strong>고정한 부품을 바꾸면</strong><ul>{result.feasibility.relax.slice(0,2).map(r=><li key={r.category}>{r.label} {r.current} → {r.replacement}: 최소 구성 {money(r.minTotal)}{r.fits?' (예산 안)':''}</li>)}</ul><small>바꿀지는 고객이 정해요. 자동으로 바꾸지 않아요.</small></div>}
        <div className="pa-followups" aria-label="추천 부품에 추가 질문"><span>현재 조건에 대해</span>{['더 저렴한 대안이 있나요?','지금 고른 부품과 맞나요?','예산이 부족하면 어떻게 하나요?'].map(q=><button type="button" key={q} disabled={loading} onClick={()=>ask(q)}>{q}</button>)}{(conditions.partBudget||conditions.totalBudget)&&<button type="button" disabled={loading} onClick={resetConditions}>상담 조건 초기화</button>}</div></section>
    </div><footer className="pa-footer"><Info size={15}/><p>서버가 DB 판매가·판매 상태·호환 규칙으로 확인한 후보 안에서 AI가 추천해요. 2026-10-23 조사 표본 32개 기준이며 실보유 수량·실시간 가격은 확인 전이에요. 조립·배송·OS 비용은 별도예요.</p></footer>
  </div>;
}
