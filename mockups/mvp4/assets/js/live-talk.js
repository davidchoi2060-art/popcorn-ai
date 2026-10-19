/* /mvp4 AI 상담 연결 (2026-10-19). mvp3 와 같은 서버 계약을 쓴다.
 *
 *   POST /api/talk/parse      {text, state, chat_flow, history[-6], display_context?}
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

  P.liveTalk = {
    /* convo: {talk, chatFlow, history:[{role,text}], pendingText} — 이 함수가 갱신한다. */
    send: function (convo, userText, displayContext, signal) {
      var body = { text: userText, state: convo.talk || null, chat_flow: convo.chatFlow || null, history: (convo.history || []).slice(-6), defer_answer: false };
      if (displayContext) body.display_context = displayContext;
      return post('/api/talk/parse', body, signal).then(function (res) {
        if (!res.state || typeof res.state !== 'object') { var e = new Error('shape'); e.kind = 'error'; throw e; }
        var before = JSON.stringify(convo.talk || null);
        convo.talk = res.state; convo.chatFlow = res.chat_flow && typeof res.chat_flow === 'object' ? res.chat_flow : null;
        convo.history = (convo.history || []).concat([{ role: 'user', text: userText.slice(0, 1000) }]);
        var reply = [text(res.answer), text(res.reply)].filter(Boolean).join('\n\n');
        if (reply) convo.history.push({ role: 'assistant', text: reply.slice(0, 300) });
        if (res.agent === true && text(res.shown_note)) convo.history.push({ role: 'assistant', text: res.shown_note.slice(0, 300) });
        convo.history = convo.history.slice(-6);
        var missing = Array.isArray(res.missing) ? res.missing : [];
        var out = { reply: res.silent ? '' : reply, missing: missing, products: null, handoff: res.handoff_offer === true };
        var keep = res.pc_related === false || res.fallback || res.explain_only === true || res.silent;
        if (keep || missing.length) { if (!keep && missing.length) convo.pendingText = ((convo.pendingText ? convo.pendingText + ' / ' : '') + userText).slice(-300); return out; }
        var recBody = { state: res.state };
        if (res.agent === true) { if (res.wants && typeof res.wants === 'object') recBody.wants = res.wants; if (res.nav === 'cheaper' || res.nav === 'better') recBody.nav = res.nav; }
        else recBody.text = ((convo.pendingText ? convo.pendingText + ' / ' : '') + userText).slice(-300);
        convo.pendingText = '';
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
