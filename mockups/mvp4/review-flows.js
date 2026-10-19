/* /mvp4 검수용 예시 화면 (2026-10-19). review-flows.html 에서만 읽는다 — 고객 화면(index.html)은 이 파일을 싣지 않는다.
   서버에 아무것도 보내지 않는다: 모든 /api 요청을 이 파일의 예시 응답으로 바꾸고, 목록에 없는 /api 요청은 503 으로 막는다.
   브라우저 보관함(localStorage·sessionStorage)도 이 탭 메모리로만 쓴다(같은 주소의 실제 보관 기록을 건드리지 않는다).
   상품·금액·번호·이름은 전부 예시다. 자동 입력은 010-0000-0000(존재하지 않는 예시 번호)만 쓴다.

   주소 매개변수(나머지 screen·id·quote 등은 고객 화면과 같다)
     has      1                 연락처가 이미 등록된 고객(다른 견적 보관 = 재사용)
     save     ok(기본) | fail | unknown | price
              fail = 확정 실패 422 · unknown = 응답 불명 503(같은 요청으로 결과 확인 → 두 번째는 성공) · price = 가격 변경 409
     consult  ok(기본) | fail | already | unknown
     talk     ok(기본) | fail | slow
     catalog  ok(기본) | fail | empty
     fill     1                 보관·상담 칸에 예시 연락처를 채운다
     ask      문장              대화 화면이 이 문장을 바로 보낸다(메인 입력 전달과 같은 경로)
*/
(function () {
  'use strict';
  // 화면 이동이 이 검수 주소와 예시 조건을 유지하게 한다(live-catalog.js designHref).
  window.PAI = window.PAI || {}; window.PAI.routeBase = 'review-flows.html'; window.PAI.routeKeep = ['has', 'save', 'consult', 'talk', 'catalog', 'fill'];
  var q = new URLSearchParams(location.search), HAS = q.get('has') === '1';
  var SAVE = q.get('save') || 'ok', CONSULT = q.get('consult') || 'ok', TALK = q.get('talk') || 'ok', CATALOG = q.get('catalog') || 'ok';
  function memStore() { var m = new Map(); return { getItem: function (k) { return m.has(k) ? m.get(k) : null; }, setItem: function (k, v) { m.set(k, String(v)); }, removeItem: function (k) { m.delete(k); }, clear: function () { m.clear(); }, key: function (i) { return Array.from(m.keys())[i] || null; }, get length() { return m.size; } }; }
  ['localStorage', 'sessionStorage'].forEach(function (name) { try { Object.defineProperty(window, name, { value: memStore(), configurable: true }); } catch (e) { /* 막히면 실제 보관함 — 예시 키만 쓴다 */ } });

  // ask=문장 이면 메인 입력에서 넘어온 것처럼 대화 화면이 그 문장을 바로 보낸다(예시 응답).
  if (q.get('ask')) try { window.sessionStorage.setItem('pai-design-question', q.get('ask')); } catch (e) { /* 메모리 보관함 */ }
  var PRODUCTS = [
    { product_code: 900001, name: '예시 게이밍 PC [14400F/16G/1TB/RTX5060]', price: 1917300, cat: '게이밍 PC', spec: { cpu: 'i5-14400F', gpu: 'RTX 5060', ram_gb: 16, ssd_gb: 1000 } },
    { product_code: 900002, name: '예시 사무용 PC [14100/16G/500GB/UHD 730]', price: 880300, cat: '사무·업무용', spec: { cpu: 'i3-14100', gpu: '인텔 UHD(내장)', ram_gb: 16, ssd_gb: 500 } },
    { product_code: 900003, name: '예시 영상편집 PC [7700/32G/1TB/RTX5070]', price: 2412000, cat: '디자인·영상', spec: { cpu: '라이젠7 7700', gpu: 'RTX 5070', ram_gb: 32, ssd_gb: 1000 } }
  ];
  var MALL = 'https://www.popcornpc.co.kr/shop/system_detail.html?pd_no=';
  var contact = HAS ? { has_contact: true, masked_phone: '010-****-0000', name: '예시' } : { has_contact: false, masked_phone: null, name: null };
  var CONSENT = '[예시 문구] 견적 보관과 고객님이 신청한 구매 상담 연락을 위해 전화번호(필수)와 이름·이메일(선택)을 받습니다. 상담을 신청하기 전에는 먼저 연락드리지 않습니다.';
  var quotes = [], saveTries = 0, consultTries = 0, inquirySeq = 1000, keys = {};

  // has=1 이면 이미 보관한 예시 견적 하나가 있다(다른 견적 재사용·내 견적·견적 상담 확인용).
  if (HAS) quotes.push({ id: '00000000-0000-4000-8000-000000000001', request_id: 'seed', product: { product_code: 900002, name: '예시 사무용 PC [14100/16G/500GB/UHD 730]', price: 880300, mall_url: MALL + 900002 }, saved_at: '2026-10-19T01:00:00Z' });
  function item(p) { return { product_code: p.product_code, name: p.name, price: p.price, price_basis: '예시 가격 · 구매할 때 확정', sale_status: '판매중', mall_url: MALL + p.product_code, spec: p.spec, fit: {}, category: p.cat, configuration_public: true, photo_hint: false, image_url: '/api/customer/products/' + p.product_code + '/representative-image?size=card' }; }
  function offer(code) {
    var p = PRODUCTS.find(function (x) { return x.product_code === code; });
    if (!p) return null;
    var parts = [['CPU', p.spec.cpu], ['GPU', p.spec.gpu], ['RAM', '예시 메모리 ' + p.spec.ram_gb + 'GB'], ['SSD', '예시 NVMe SSD ' + (p.spec.ssd_gb >= 1000 ? p.spec.ssd_gb / 1000 + 'TB' : p.spec.ssd_gb + 'GB')], ['MB', '예시 메인보드'], ['POWER', '예시 파워 600W'], ['CASE', '예시 케이스']];
    return { ok: true, product_code: code, photo: { state: 'unavailable', url: null }, public_configuration: { configuration_id: 'P' + code, parts: parts.map(function (x, i) { return { ordinal: i, slot: x[0], quantity: 1, pseudo: false, name: x[1], description: '예시 부품 설명입니다.', specs: [{ label: '예시', value: '검수용 값' }], price: null, assembly_only: false }; }) } };
  }
  function reply(status, body) { return Promise.resolve(new Response(JSON.stringify(body), { status: status, headers: { 'Content-Type': 'application/json' } })); }
  function later(ms, v) { return new Promise(function (r) { setTimeout(function () { r(v); }, ms); }); }
  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var url = new URL(typeof input === 'string' ? input : input.url, location.href), path = url.pathname, method = (init && init.method || 'GET').toUpperCase();
    var body = init && init.body ? JSON.parse(init.body) : null;
    if (url.origin !== location.origin || path.indexOf('/api/') !== 0) return realFetch(input, init);
    if (path === '/api/customer/pc-catalog') return CATALOG === 'fail' ? reply(503, { detail: 'example' }) : reply(200, { ok: true, items: CATALOG === 'empty' ? [] : PRODUCTS.map(item) });
    var m = path.match(/^\/api\/customer\/pc-offers\/(\d+)$/); if (m) { var o = offer(Number(m[1])); return o ? reply(200, o) : reply(404, { detail: { error: 'not_public' } }); }
    if (path === '/api/talk/parse') {
      if (TALK === 'fail') return reply(502, { detail: 'example' });
      return later(TALK === 'slow' ? 4000 : 600).then(function () { return reply(200, { ok: true, state: { usages: ['게임', '영상편집'], budget_won: 1500000, budget_bound: '이하' }, missing: [], reply: '[예시 답변] 말씀하신 게임과 영상 편집 기준으로 판매 중인 PC를 골라 봤어요. 아래 카드에서 구성과 가격을 확인해 보세요.', chat_flow: { turns: 1 } }); });
    }
    if (path === '/api/grid/recommend') return reply(200, { ok: true, card_sets: [{ kind: 'sold', items: PRODUCTS.map(function (p) { return { product_code: p.product_code, over_budget: p.price > 1500000 }; }) }] });
    if (path === '/api/mvp3/saved-quotes' && method === 'GET') return reply(200, { ok: true, quotes: quotes.slice(), has_more: false });
    if (path === '/api/mvp3/contact' && method === 'GET') return reply(200, Object.assign({ ok: true, consent_text: CONSENT }, contact));
    if (path === '/api/mvp3/contact' && method === 'PUT') { contact = { has_contact: true, masked_phone: '010-****-0000', name: body && body.name }; return reply(200, Object.assign({ ok: true }, contact)); }
    if (path === '/api/mvp3/saved-quotes' && method === 'POST') {
      saveTries++;
      if (!contact.has_contact && !body.contact) return reply(422, { detail: { error: 'contact_required', detail: '견적을 보관하려면 전화번호를 입력하고 개인정보 수집·이용에 동의해 주세요.', consent_text: CONSENT } });
      if (SAVE === 'fail') return reply(422, { detail: '[예시] 전화번호 형식을 확인해 주세요. 예: 010-1234-5678' });
      if (SAVE === 'unknown' && saveTries === 1) return reply(503, null);
      if (SAVE === 'price' && saveTries === 1) return reply(409, { detail: '상품 가격이 변경되었습니다. 다시 조회한 가격을 확인해 주세요.' });
      var p = PRODUCTS.find(function (x) { return x.product_code === body.product_code; });
      var existing = quotes.find(function (x) { return x.request_id === body.request_id; });
      if (!existing) { if (body.contact) contact = { has_contact: true, masked_phone: '010-****-0000', name: body.contact.name }; existing = { id: '00000000-0000-4000-8000-00000000000' + (quotes.length + 1), request_id: body.request_id, product: { product_code: p.product_code, name: p.name, price: p.price, sets: body.sets > 1 ? body.sets : undefined, mall_url: MALL + p.product_code }, saved_at: new Date().toISOString() }; quotes.unshift(existing); }
      return reply(200, { ok: true, quote: existing, contact: contact });
    }
    if (path === '/api/mvp3/purchase-inquiries/form') return reply(200, { ok: true, topics: ['여러 대 구매', '할인', '세금계산서·영수증', '주문 희망', '기타'], consent_text: '[예시 문구] 구매 상담 연락을 위해 이름·연락처·문의 내용을 받습니다.' });
    var bk = path.match(/^\/api\/mvp3\/purchase-inquiries\/by-key\/([A-Za-z0-9_-]{6,64})$/);
    if (bk) return reply(200, { ok: true, found: !!keys[bk[1]], inquiry_no: keys[bk[1]] || null });
    if (path === '/api/mvp3/purchase-inquiries/from-quote' || path === '/api/mvp3/purchase-inquiries') {
      consultTries++;
      if (body && body.client_key && keys[body.client_key]) return reply(200, { ok: true, already: true, inquiry_no: keys[body.client_key] });
      if (CONSULT === 'fail') return reply(422, { detail: '[예시] 문의 주제를 골라 주세요.' });
      // unknown = 첫 요청은 서버에 접수됐는데 응답을 잃은 경우(결과 확인 → 접수됨).
      if (CONSULT === 'unknown' && consultTries === 1) { if (body && body.client_key) keys[body.client_key] = 'PI-' + (inquirySeq + 1); return reply(503, null); }
      if (path.slice(-10) === 'from-quote' && !contact.has_contact) return reply(409, { detail: { error: 'contact_required', detail: '상담 연락을 받을 전화번호를 먼저 등록해 주세요.' } });
      if (body && body.client_key) keys[body.client_key] = 'PI-' + (inquirySeq + 1);
      return reply(200, { ok: true, already: CONSULT === 'already' || (CONSULT === 'unknown' && consultTries > 1), inquiry_no: 'PI-' + (inquirySeq + 1), quote_id: body.quote_id, masked_phone: contact.masked_phone, note: '예시' });
    }
    return reply(503, { detail: 'review fixture: blocked' });
  };
  // 예시 연락처 자동 입력(fill=1) — 실제 번호를 쓰지 않는다.
  if (q.get('fill') === '1') new MutationObserver(function () {
    var ph = document.getElementById('ds-phone'); if (ph && !ph.value) { ph.value = '010-0000-0000'; var c = ph.form && ph.form.querySelector('[name=consent]'); if (c) c.checked = true; }
  }).observe(document.documentElement, { childList: true, subtree: true });
}());
