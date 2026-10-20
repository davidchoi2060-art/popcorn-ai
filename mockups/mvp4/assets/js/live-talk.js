/* /mvp4 AI 상담 연결 (2026-10-19). mvp3 와 같은 서버 계약을 쓴다.
 *
 *   POST /api/talk/parse      {text, state, chat_flow, history[-6], display_context?, reply_format}
 *   POST /api/grid/recommend  {state, text?, wants?, nav?}   (조건이 다 모였을 때만)
 *
 * 서버는 대화를 저장하지 않는다 — 조건(state)·흐름(chat_flow)·최근 대화(history)는 이 화면이 들고 있다가
 * 매번 보낸다. 추천 PC 는 서버가 준 상품번호만 쓰고, 목록(/api/customer/pc-catalog)에 없는 번호는 버린다.
 * 실패는 지어낸 답으로 덮지 않는다: offline · timeout · rate_limited · error 로 돌려주고 입력은 화면이 지킨다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var TIMEOUT_MS = 60000;

  function post(path, body, signal) {
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null, timedOut = false;
    var timer = ctrl ? setTimeout(function () { timedOut = true; ctrl.abort(); }, TIMEOUT_MS) : null;
    if (signal && ctrl) signal.addEventListener('abort', function () { ctrl.abort(); }, { once: true });
    return fetch(path, { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body), signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (data) {
          if (r.ok && data && data.ok === true) return data;
          var e = new Error('http_' + r.status); e.kind = r.status === 429 ? 'rate_limited' : 'error'; e.status = r.status;
          e.retryAfter = data && data.retry_after_sec; throw e;
        });
      }, function (err) {
        if (timer) clearTimeout(timer);
        var e = new Error('network'); e.kind = signal && signal.aborted ? 'aborted' : timedOut ? 'timeout' : navigator.onLine === false ? 'offline' : 'offline'; e.cause = err; throw e;
      });
  }

  function text(v) { return typeof v === 'string' ? v.trim() : ''; }

  // 추천 응답의 판매 PC 번호(순서 유지·중복 제거). 목록에 없는 번호는 화면에 내지 않는다.
  function soldCodes(rec) {
    var seen = Object.create(null), out = [];
    (rec && Array.isArray(rec.card_sets) ? rec.card_sets : []).forEach(function (cs) {
      if (!cs || cs.kind !== 'sold') return;
      (Array.isArray(cs.items) ? cs.items : []).forEach(function (it) {
        var code = it && it.product_code; if (!Number.isSafeInteger(code) || seen[code]) return;
        seen[code] = true; if (P.getCatalogProduct(String(code))) out.push({ id: String(code), overBudget: it.over_budget === true });
      });
    });
    return out;
  }

  // 상담 AI 가 보여 준 PC(서버가 확인한 상품번호). 목록(/api/customer/pc-catalog)에 없는 번호는 오른쪽 카드에 내지 않는다
  // -- 본문은 그 상품을 「확인할 수 없음」으로 표시한다(chat-answer.js).
  function agentPicks(agentCards) {
    var picked = [], seen = Object.create(null);
    (Array.isArray(agentCards) ? agentCards : []).forEach(function (c) {
      var code = c && c.product_code; if (!Number.isSafeInteger(code) || seen[code]) return;
      seen[code] = true; if (P.getCatalogProduct(String(code))) picked.push({ id: String(code), overBudget: c.over_budget === true });
    });
    return picked;
  }

  function strip(s) { return P.chatAnswer ? P.chatAnswer.strip(s) : s; }

  P.liveTalk = {
    /* convo: {talk, chatFlow, history:[{role,text}], pendingText}.
     * 2026-10-20: 이 함수는 convo 를 바로 바꾸지 않는다. 결과의 commit() 을 화면이 «답을 실제로 그린 뒤에만» 부른다 --
     * 늦게 온 답·중단된 답·추천 조회가 실패한 답이 다음 질문의 이력이 되지 않게(C08·C09). */
    send: function (convo, userText, displayContext, signal) {
      var body = { text: userText, state: convo.talk || null, chat_flow: convo.chatFlow || null, history: (convo.history || []).slice(-6), defer_answer: false, reply_format: 'marked' };
      if (displayContext) body.display_context = displayContext;
      return post('/api/talk/parse', body, signal).then(function (res) {
        if (!res.state || typeof res.state !== 'object') { var e = new Error('shape'); e.kind = 'error'; throw e; }
        var before = JSON.stringify(convo.talk || null);
        var answer = text(res.answer), said = text(res.reply);
        var reply = [answer, said !== answer ? said : ''].filter(Boolean).join('\n\n');
        // 이력은 표시한 답 그대로(강조 표시만 뺀다). 앞 300자만 남기던 것을 600자로 -- 상품 참조는 이력 글이 아니라 답변 묶음(answer_sets)이 맡는다.
        var history = (convo.history || []).concat([{ role: 'user', text: userText.slice(0, 1000) }]);
        if (reply) history.push({ role: 'assistant', text: strip(reply).slice(0, 600) });
        if (res.agent === true && text(res.shown_note)) history.push({ role: 'assistant', text: res.shown_note.slice(0, 600) });
        var next = { talk: res.state, chatFlow: res.chat_flow && typeof res.chat_flow === 'object' ? res.chat_flow : null, history: history.slice(-6), pendingText: convo.pendingText || '' };
        var missing = Array.isArray(res.missing) ? res.missing : [];
        var out = { reply: res.silent ? '' : reply, missing: missing, products: null, handoff: res.handoff_offer === true, agentCards: res.agent === true ? res.agent_cards : null,
          commit: function () { convo.talk = next.talk; convo.chatFlow = next.chatFlow; convo.history = next.history; convo.pendingText = next.pendingText; } };
        var keep = res.pc_related === false || res.fallback || res.explain_only === true || res.silent;
        if (keep || missing.length) { if (!keep && missing.length) next.pendingText = ((next.pendingText ? next.pendingText + ' / ' : '') + userText).slice(-300); return out; }
        // 2026-10-20 대표 신고(P1 「답변과 추천 상품이 달라」): AI 가 PC 를 보여 준 턴은 그 PC 들이 곧 이 답변의 추천 묶음이다.
        // 예전에는 조건으로 추천을 다시 받아 AI 의 PC 가 그 안에 다 있으면 조건 추천 순서를 그대로 썼고, 화면이 앞 3대만 보여
        // 본문 2·3번과 오른쪽 2·3번이 다른 상품이 됐다. 이제 본문·오른쪽 카드·상세·비교·「위 N번째」가 같은 상품번호 목록을 쓴다.
        var picks = res.agent === true ? agentPicks(res.agent_cards) : [];
        if (picks.length || (res.agent === true && Array.isArray(res.agent_cards) && res.agent_cards.length)) {
          next.pendingText = ''; out.products = picks; out.changed = JSON.stringify(res.state) !== before; return out;
        }
        var recBody = { state: res.state };
        if (res.agent === true) { if (res.wants && typeof res.wants === 'object') recBody.wants = res.wants; if (res.nav === 'cheaper' || res.nav === 'better') recBody.nav = res.nav; }
        else recBody.text = ((next.pendingText ? next.pendingText + ' / ' : '') + userText).slice(-300);
        next.pendingText = '';
        return post('/api/grid/recommend', recBody, signal).then(function (rec) {
          out.products = soldCodes(rec);
          out.changed = JSON.stringify(res.state) !== before;
          return out;
        });
      });
    },
    budgetText: function (talk) {
      var won = talk && talk.budget_won;
      if (!Number.isSafeInteger(won) || won <= 0) return '';
      var man = won / 10000;
      return (Number.isInteger(man) ? man.toLocaleString('ko-KR') + '만 원' : won.toLocaleString('ko-KR') + '원') + (talk.budget_bound === '이상' ? ' 이상' : talk.budget_bound === '이하' ? ' 이하' : '');
    }
  };
}());
