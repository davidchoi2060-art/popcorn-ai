/* AI 패키지 견적 문의·도입 상담(ai-consult.html · v9 ai-inquiry.js) 실제 접수 — /mvp4 (2026-10-19).
 *
 * PAI.inquiryService = { submit(payload), lookup({clientRequestKey, requestId}) } (v9 계약).
 *   GET  /api/mvp3/purchase-inquiries/form              주제·동의 문구 + 이 브라우저의 방문자 연결(쿠키)
 *   POST /api/mvp3/purchase-inquiries                  {topic, name, phone|email, message, consent, client_key}
 *   GET  /api/mvp3/purchase-inquiries/by-key/{key}     같은 요청의 접수 여부(이 브라우저 것만)
 * - client_key(=clientRequestKey)로 같은 요청은 한 번만 접수된다. 응답을 받지 못했으면 접수됐다고 하지 않고(unknown),
 *   같은 키로만 결과를 확인한다. 「접수 안 됨」은 이 브라우저에서 그 키의 접수가 없다고 서버가 답했을 때만이다.
 * - 연락 요청 확인(contactRequested)과 개인정보 수집 동의(privacyConsent)는 다르다 — 동의 문구는 서버 문장만 보인다.
 * - 패키지·목적·기능·세부 조건과 문의 원문은 문의 내용에 함께 적는다(원문의 공백·줄바꿈은 그대로).
 * 비밀값은 이 파일에 두지 않는다. design-only/inquiry-fixtures.js 는 고객 화면에 싣지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var PACKAGES = { basic: '기본형', business: '업무형', advanced: '고급형' };
  var USES = { documents: '사내 문서 검색', meetings: '회의록 정리', replies: '고객 답변 초안', unsure: '아직 정하지 않음' };
  var SETUP = { bundle: 'PC와 함께 구성', existing: '보유 PC에 설치', unsure: '아직 정하지 않음' };
  var KEY_RE = /^[A-Za-z0-9_-]{6,64}$/;

  function call(method, path, body) {
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 30000);
    var headers = { Accept: 'application/json', 'X-Popcorn-Surface': 'mvp4' };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: method, credentials: 'same-origin', cache: 'no-store', headers: headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.json().catch(function () { return null; }).then(function (d) { if (r.ok && d && d.ok === true) return d; var e = new Error('http'); e.status = r.status; e.detail = d && d.detail; throw e; }); },
        function () { clearTimeout(timer); var e = new Error('network'); e.status = 0; throw e; });
  }
  // 방문자 연결과 동의 문구를 먼저 받는다 — 결과 확인이 같은 브라우저 기준으로만 이뤄지게.
  var form = null;
  function prime() { if (!form) form = call('GET', '/api/mvp3/purchase-inquiries/form').then(function (m) { P.inquiryConsentText = m.consent_text; showConsent(); return m; }, function (e) { form = null; throw e; }); return form; }
  function showConsent() {
    var box = document.querySelector('[name=privacyConsent]');
    if (!box || !P.inquiryConsentText) return;
    var span = box.parentNode.querySelector('span');
    if (!box.disabled && (!span || span.textContent.indexOf(P.inquiryConsentText) === 0)) return;   // 이미 반영됨(관찰 루프 방지)
    box.disabled = false; if (span) span.innerHTML = '';
    if (span) { span.appendChild(document.createTextNode(P.inquiryConsentText + ' ')); var b = document.createElement('b'); b.className = 'required'; b.textContent = '필수'; span.appendChild(b); }
  }
  function message(p) {
    var kind = p.intent === 'quote' ? '견적 문의' : '도입 상담';
    var lines = ['[AI 패키지 ' + kind + '] ' + (PACKAGES[p.packageId] || p.packageId || '')];
    var meta = [['관심 기능', USES[p.use] || p.use], ['구성 방식', p.intent === 'quote' ? SETUP[p.setup] || p.setup : ''], ['예산', p.budget], ['수량', p.quantity], ['사용 인원', p.people], ['환경', p.environment], ['회사', p.company]]
      .filter(function (x) { return x[1] && String(x[1]).trim(); }).map(function (x) { return x[0] + ': ' + String(x[1]).trim(); });
    if (meta.length) lines.push(meta.join(' / '));
    var head = lines.join('\n');
    return p.request ? (head + '\n' + p.request).slice(0, 500) : head;
  }
  function outcome(e) {
    if (e.status === 0 || e.status >= 500) return { status: 'unknown' };
    if (e.status === 429) return { status: 'rate-limit' };
    if (e.status === 403) return { status: 'forbidden' };
    if (e.status === 422 && /동의/.test(typeof e.detail === 'string' ? e.detail : '')) return { status: 'consent-expired' };
    return { status: 'failed' };
  }

  P.inquiryService = {
    submit: function (p) {
      if (p.privacyConsent !== true || p.contactRequested !== true) return Promise.resolve({ status: 'consent-expired' });
      if (!KEY_RE.test(String(p.clientRequestKey || ''))) return Promise.resolve({ status: 'failed' });
      var body = { topic: '기타', name: p.name ? String(p.name).trim().slice(0, 30) || null : null, message: message(p), consent: true, client_key: p.clientRequestKey };
      if (p.contactMethod === 'email') body.email = p.contact; else body.phone = String(p.contact || '').replace(/[\s()]/g, '');
      return prime().then(function () { return call('POST', '/api/mvp3/purchase-inquiries', body); }).then(function (r) { return { status: 'accepted', requestId: r.inquiry_no }; }, outcome);
    },
    lookup: function (q) {
      var key = q && q.clientRequestKey;
      if (!KEY_RE.test(String(key || ''))) return Promise.resolve({ status: 'unknown' });
      return call('GET', '/api/mvp3/purchase-inquiries/by-key/' + encodeURIComponent(key)).then(function (r) {
        return r.found ? { status: 'accepted', requestId: r.inquiry_no } : { status: 'failed' };
      }, function (e) { return e.status === 403 ? { status: 'forbidden' } : { status: 'unknown' }; });
    }
  };

  // 문의 화면이 열리면 동의 문구를 미리 받는다(화면은 boot.js 가 그린다).
  if (/ai-consult\.html$/.test(location.pathname)) {
    prime().catch(function () { /* 문구를 못 받으면 동의 칸이 잠긴 채 남는다 — 제출되지 않는다 */ });
    new MutationObserver(showConsent).observe(document.documentElement, { childList: true, subtree: true });
  }
}());
