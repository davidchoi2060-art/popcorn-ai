/* AI 패키지 도입 상담(ai-consult.html) 연결 — /mvp4 (2026-10-19).
 *
 * PAI.submitConsult(payload) 계약(ai.js)은 그대로 두고, 실제 접수는 구매 상담 신청 API 로 보낸다.
 *   GET  /api/mvp3/purchase-inquiries/form   주제·동의 문구(서버가 준 문장만 보인다)
 *   POST /api/mvp3/purchase-inquiries        {topic, name, phone|email, message, consent}
 * contactRequested(연락 요청 확인)와 개인정보 수집 동의는 다르다 — 서버 동의 문구로 따로 받는다.
 * 패키지·기능·문의 의도(intent=quote|adoption)는 문의 내용 앞머리에 적어 함께 저장한다.
 * 응답을 받지 못했으면 접수됐다고 하지 않는다(pending). 비밀값은 이 파일에 두지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var PACKAGES = { basic: '기본형', business: '업무형', advanced: '고급형' };
  var USES = { documents: '사내 문서 검색', meetings: '회의록 정리', replies: '고객 답변 초안' };

  function call(method, path, body) {
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 30000);
    return fetch(path, { method: method, credentials: 'same-origin', cache: 'no-store', headers: body ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.json().catch(function () { return null; }).then(function (d) { if (r.ok && d && d.ok === true) return d; var e = new Error('http'); e.status = r.status; e.detail = d && d.detail; throw e; }); },
        function () { clearTimeout(timer); var e = new Error('network'); e.status = 0; throw e; });
  }

  P.submitConsult = function (payload) {
    var privacy = document.getElementById('consult-privacy');
    if (!privacy || !privacy.checked) return Promise.resolve({ status: 'failed' });
    var intent = P.qs && P.qs.get('intent');
    var kind = intent === 'quote' ? '견적 문의' : intent === 'adoption' ? '도입 상담' : '도입 상담';
    var head = '[AI 패키지 ' + kind + '] ' + (PACKAGES[payload.packageId] || payload.packageId || '') + (USES[payload.use] ? ' · ' + USES[payload.use] : '') + (payload.company ? ' · ' + payload.company : '');
    var body = { topic: '기타', name: payload.name || null, message: (head + (payload.request ? '\n' + payload.request : '')).slice(0, 500), consent: true };
    if (payload.contactMethod === 'email') body.email = payload.contact; else body.phone = String(payload.contact || '').replace(/[\s()]/g, '');
    return call('POST', '/api/mvp3/purchase-inquiries', body).then(function (r) { return { status: 'accepted', requestId: r.inquiry_no }; },
      function (e) { return { status: e.status >= 400 && e.status < 500 ? 'failed' : 'pending' }; });
  };

  // 개인정보 수집 동의 칸 — 서버 문구를 그대로 싣는다. 체크하지 않으면 제출을 멈추고 알린다.
  function addPrivacy() {
    var form = document.getElementById('ai-consult-form'), box = form && form.querySelector('.consent-box');
    if (!box || document.getElementById('consult-privacy')) return;
    var wrap = document.createElement('div'); wrap.className = 'consent-box';
    wrap.innerHTML = '<label><input type="checkbox" id="consult-privacy" aria-describedby="privacy-error"> <span data-privacy-text>개인정보 수집·이용 안내를 불러오고 있어요.</span> <span class="required">필수</span></label><p class="error" id="privacy-error" hidden>개인정보 수집·이용에 동의해 주세요.</p>';
    box.parentNode.insertBefore(wrap, box.nextSibling);
    var cb = wrap.querySelector('input'), text = wrap.querySelector('[data-privacy-text]'), error = wrap.querySelector('#privacy-error');
    cb.disabled = true;
    call('GET', '/api/mvp3/purchase-inquiries/form').then(function (m) { text.textContent = m.consent_text; cb.disabled = false; },
      function () { text.textContent = '개인정보 수집·이용 안내를 불러오지 못했어요. 잠시 후 새로고침해 주세요.'; });
    document.addEventListener('submit', function (event) {
      if (event.target !== form) return;
      if (cb.checked) { error.hidden = true; cb.removeAttribute('aria-invalid'); return; }
      error.hidden = false; cb.setAttribute('aria-invalid', 'true');
      // 다른 칸 검사가 먼저 실패한 경우가 아니면 동의 칸으로 보낸다.
      setTimeout(function () { if (!form.querySelector('[aria-invalid="true"]:not(#consult-privacy)')) cb.focus(); }, 0);
      if (form.querySelector('[name=use]:checked') && document.getElementById('consult-consent').checked) { event.preventDefault(); event.stopImmediatePropagation(); }
    }, true);
  }
  // 화면은 boot.js 가 그린다 — 상담 칸이 생기면 한 번 붙인다.
  var watch = new MutationObserver(function () { if (document.getElementById('ai-consult-form')) { watch.disconnect(); addPrivacy(); } });
  watch.observe(document.documentElement, { childList: true, subtree: true });
  if (document.getElementById('ai-consult-form')) { watch.disconnect(); addPrivacy(); }
}());
