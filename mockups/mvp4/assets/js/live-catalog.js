/* /mvp4 실제 상품 원천 (2026-10-19). catalog-snapshot.js(10/18 관찰 자료)를 대신한다.
 *
 * 목록   GET /api/customer/pc-catalog              판매 중인 완제품 PC 전체(추천과 같은 원천)
 * 상세   GET /api/customer/pc-offers/{code}         공개 승인된 부품 구성 + 대표 사진(404 = 공개 아님)
 * 사진   /api/customer/products/{code}/representative-image[?size=card]  (404 이면 사진 없음으로)
 *
 * 화면 모듈(design-*.js)이 읽는 상품 모양으로 바꿔 PAI.catalogProducts 에 넣는다. 서버가 주지 않은 값은
 * 지어내지 않는다 — 가격이 없으면 null, 구성이 공개되지 않았으면 부품 표가 비고 「구성 확인 필요」로 보인다.
 * 부품 개별 단가는 받지 않는다(공개 구성의 price 는 버린다).
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var CATALOG = '/api/customer/pc-catalog';
  var OFFER = '/api/customer/pc-offers/';
  var REGISTERED = '/api/customer/pc-registered/';
  // 승인 대표 사진이 없으면 팝콘PC 몰에 올린 그 상품의 대표 사진을 쓴다(2026-10-20 대표 「이미지도 만들어」).
  function mallImage(code) { var n = Number(code); return Number.isSafeInteger(n) && n > 0 ? 'https://www.popcornpc.co.kr/data/pimg/' + Math.floor(n / 1000) + '/' + n + '_600.jpg' : null; }
  // 새 판매 PC 대표 사진(AI 조립 예시, 2026-10-21 대표 「이미지 작업은 좀 멋지게」) — 저장소 자산 assets/images/products/{상품번호}.webp.
  // 서버 승인 사진이 없을 때 몰 사진보다 먼저 쓴다. 번호 목록은 여기 하나(출처·해시 = 그 폴더 SOURCES.json).
  var LOCAL_PHOTOS = { 130569: 1, 130570: 1, 130571: 1, 130572: 1, 130573: 1, 130574: 1, 130575: 1, 130576: 1, 130577: 1, 130578: 1, 130579: 1, 130580: 1, 130581: 1, 130582: 1, 130583: 1, 130584: 1, 130585: 1, 130586: 1, 130587: 1, 130588: 1, 130589: 1, 130590: 1, 130591: 1, 130592: 1, 130593: 1, 130594: 1, 130595: 1, 130596: 1, 130597: 1, 130598: 1, 130599: 1, 130600: 1, 130601: 1, 130602: 1, 130603: 1, 130604: 1, 130605: 1, 130606: 1, 130607: 1, 130608: 1, 130609: 1, 130610: 1, 130611: 1, 130612: 1, 130613: 1, 130614: 1, 130615: 1, 130616: 1, 130617: 1, 130618: 1, 130619: 1, 130620: 1, 130621: 1, 130622: 1, 130623: 1, 130624: 1, 130625: 1, 130626: 1, 130627: 1, 130628: 1, 130629: 1, 130630: 1, 130631: 1, 130632: 1, 130633: 1, 130634: 1, 130635: 1, 130636: 1, 130637: 1, 130638: 1, 130639: 1, 130640: 1, 130641: 1, 130642: 1, 130643: 1, 130644: 1, 130645: 1, 130646: 1, 130647: 1, 130648: 1, 130649: 1, 130650: 1, 130651: 1, 130652: 1, 130653: 1, 130654: 1, 130655: 1, 130656: 1, 130657: 1, 130658: 1, 130659: 1, 130660: 1, 130661: 1, 130662: 1, 130663: 1, 130664: 1, 130665: 1, 130666: 1, 130667: 1, 130668: 1, 130669: 1, 130670: 1, 130671: 1, 130672: 1, 130673: 1, 130674: 1, 130675: 1, 130676: 1, 130677: 1, 130678: 1, 130679: 1 };  // 111장(2026-10-21) — 나머지는 몰 사진 그대로
  var LOCAL_NOTICE = 'AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음';
  function localImage(code) { return LOCAL_PHOTOS[String(code)] === 1 ? 'assets/images/products/' + Number(code) + '.webp' : null; }
  // 몰은 일부 상품 대표 사진을 .gif 로만 둔다(2026-10-20 실측 122081·122083·121112·121114·121115 — _600.jpg 404, _600.gif 있음).
  // 다른 사진 대체(아이콘·「사진 준비 중」)보다 먼저 받아 .gif 로 한 번 더 읽는다. .gif 도 없으면 원래 대체가 그대로 돈다.
  window.addEventListener('error', function (event) {
    var img = event.target;
    if (!img || img.tagName !== 'IMG' || img.dataset.mallGif) return;
    var m = /^(https:\/\/www\.popcornpc\.co\.kr\/data\/pimg\/\d+\/\d+_600)\.jpg$/.exec(img.getAttribute('src') || '');
    if (!m) return;
    img.dataset.mallGif = '1';
    event.stopImmediatePropagation();
    img.src = m[1] + '.gif';
  }, true);
  // 2026-10-20 승인 「구매 경로 분리」 -- 일반 완제품(이 PC 카탈로그 상품)은 팝콘PC몰 그 상품 페이지에서 구매한다.
  // 같은 상품번호(pd_no)의 몰 상품 주소일 때만 쓴다. 몰 홈·검색·다른 상품으로 대체하지 않고, 없으면 빈 값(확인 필요)이다.
  // 주소 검사·가격 안내는 mall-buy-guide.js 한곳에 있다(2026-10-21 구매 1번 승인 — 몰 이동 전 가격 변동 안내).
  P.mallBuyUrl = function (p) { return p && P.mallUrlFor ? P.mallUrlFor(p.id, p.mallUrl) : ''; };
  P.mallBuyLink = function (p, cls, label) {
    if (!p || !P.mallBuyAnchor) return '';
    var price = typeof p.price === 'number' && isFinite(p.price) && p.price > 0 ? p.price : null;
    return P.mallBuyAnchor({ id: p.id, url: p.mallUrl, name: p.name, price: price, image: P.catalogImage ? P.catalogImage(p) : null, cls: cls, label: label || '팝콘PC몰에서 구매하기' });
  };
  var SLOT = { CPU: 'CPU', GPU: '그래픽카드', RAM: '메모리', SSD: '저장장치', HDD: '저장장치', MB: '메인보드', POWER: '파워', PSU: '파워', CASE: '케이스', COOLER: 'CPU 쿨러', OS: '운영체제' };

  function get(url) {
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 20000) : null;
    return fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().catch(function () { return null; }).then(function (body) { return { status: r.status, body: body }; });
      }, function (err) { if (timer) clearTimeout(timer); throw err; });
  }

  function gb(v) { return typeof v === 'number' && v > 0 ? (v >= 1000 && v % 1000 === 0 ? v / 1000 + 'TB' : v + (v >= 1000 ? 'GB' : 'GB')) : ''; }

  function summarySpecs(spec) {
    var rows = [];
    if (spec.cpu) rows.push({ label: 'CPU', value: spec.cpu, slot: 'CPU' });
    if (spec.ram_gb) rows.push({ label: '메모리', value: gb(spec.ram_gb), slot: 'RAM' });
    if (spec.ssd_gb) rows.push({ label: '저장장치', value: gb(spec.ssd_gb), slot: 'SSD' });
    if (spec.gpu) rows.push({ label: '그래픽카드', value: spec.gpu, slot: 'GPU' });
    return rows;
  }

  function toProduct(it) {
    var spec = it.spec && typeof it.spec === 'object' ? it.spec : {};
    var summary = summarySpecs(spec);
    return {
      id: String(it.product_code), productCode: it.product_code, name: it.name, officialName: typeof it.official_name === 'string' && it.official_name.trim() ? it.official_name.trim() : it.name,
      price: typeof it.price === 'number' && it.price > 0 ? it.price : null, priceBasis: it.price_basis || '',
      image: it.photo_hint ? it.image_url : localImage(it.product_code) || mallImage(it.product_code),
      mediaStatus: it.photo_hint || localImage(it.product_code) ? 'ready' : 'mall',
      photoNotice: !it.photo_hint && localImage(it.product_code) ? LOCAL_NOTICE : '',
      summary: summary.map(function (s) { return s.value; }).join(' · '), summarySpecs: summary,
      specs: [], status: it.sale_status, saleStatus: it.sale_status, isSelling: it.sale_status === '판매중',
      recommendable: it.sale_status === '판매중', reviewRequired: false, purchasable: it.sale_status === '판매중',
      category: it.category || '', fit: it.fit || {}, mallUrl: it.mall_url || null,
      configurationPublic: it.configuration_public === true,
      configurationId: null, bomStatus: it.configuration_public ? 'unloaded' : 'missing',
      source: { kind: 'live', bomBasis: 'customer-public-configuration' }, optionGroups: [], liveDetail: 'pending'
    };
  }

  // 상세 = 공개 구성. 404 not_public 은 «상품 없음»이 아니라 «구성 비공개»다.
  function applyOffer(p, body) {
    var conf = body && body.public_configuration;
    var parts = conf && Array.isArray(conf.parts) ? conf.parts : [];
    p.configurationId = conf && conf.configuration_id || null;
    p.specs = parts.filter(function (x) { return x && !x.pseudo && x.name; }).map(function (x) {
      var facts = (Array.isArray(x.specs) ? x.specs : []).filter(function (f) { return f && f.label && f.value; }).map(function (f) { return { label: String(f.label), value: String(f.value) }; });
      return { label: SLOT[String(x.slot || '').toUpperCase()] || String(x.slot || '부품'), value: x.name, slot: String(x.slot || '').toUpperCase(),
        quantity: Number.isInteger(x.quantity) && x.quantity > 0 ? x.quantity : null, partId: x.ordinal, partIdKind: 'ordinal',
        role: x.description || '', facts: facts, detail: facts.map(function (f) { return f.label + ': ' + f.value; }).join(' · '),
        assemblyOnly: x.assembly_only === true,
        // 부품 사진: 서버가 이 부품 설명 코드로 공개 승인한 사진만(parts[].photo, state=approved). 이름으로 찾지 않는다.
        image: x.photo && x.photo.state === 'approved' && typeof x.photo.url === 'string' && /^\/api\/product-images\/\d+\/detail$/.test(x.photo.url) ? x.photo.url : '' };
    });
    // 기존 /mvp3 상세가 보여 주던 소개·구매 전 확인 사항도 함께 둔다(빠뜨리지 않게).
    p.description = conf && conf.description && typeof conf.description === 'object' ? conf.description : null;
    p.customerConditions = conf && conf.customer_conditions && typeof conf.customer_conditions === 'object' ? conf.customer_conditions : null;
    p.bomStatus = p.specs.length ? 'configuration-only' : 'missing';
    var photo = body && body.photo;
    if (photo && photo.state === 'available' && typeof photo.url === 'string' && photo.url.indexOf('/api/customer/products/' + p.id + '/') === 0) {
      p.image = photo.url; p.mediaStatus = 'ready'; p.photoNotice = photo.notice || '';
    } else if (localImage(p.id)) {
      p.image = localImage(p.id); p.mediaStatus = 'ready'; p.photoNotice = LOCAL_NOTICE;
    } else { p.image = mallImage(p.id); p.mediaStatus = 'mall'; }
    p.liveDetail = 'public';
  }

  // 승인 구성이 없는 판매 PC: 몰에 등록된 구성으로 부품 표를 채운다(2026-10-20 대표 「부품표도 채워서 넣어」).
  // 같은 몰 옵션 문구로 승인 구성에서 확인된 부품이면 그 사진·역할 설명이 붙는다. 최종 구성은 상담 시 확정.
  function applyRegistered(p, body) {
    var parts = body && Array.isArray(body.parts) ? body.parts : [];
    p.specs = parts.filter(function (x) { return x && x.name; }).map(function (x, i) {
      var slot = String(x.slot || '').toUpperCase();
      return { label: SLOT[slot] || slot || '부품', value: String(x.name).replace(/^\[([^\]]{1,20})\]\s*/, '$1 '), slot: slot, registered: true, ordinal: i,
        quantity: Number.isInteger(x.quantity) && x.quantity > 0 ? x.quantity : 1, role: x.role || '', facts: [],
        image: typeof x.photo === 'string' && (/^\/api\/product-images\/\d+\/detail$/.test(x.photo) || /^https:\/\/www\.popcornpc\.co\.kr\/data\/pimg\/\d+\/\d+_600\.jpg$/.test(x.photo) || /^assets\/images\/parts\/[a-z0-9-]+\.(jpg|png|webp)$/.test(x.photo)) ? x.photo : '' };
    });
    p.service = body && typeof body.service === 'string' ? body.service : '';
    p.bomStatus = p.specs.length ? 'registered' : 'missing';
    p.liveDetail = 'registered';
  }

  P.live = {
    state: 'loading', error: null,
    loadCatalog: function () {
      return get(CATALOG).then(function (res) {
        if (res.status !== 200 || !res.body || !Array.isArray(res.body.items)) throw new Error('catalog_' + res.status);
        P.catalogProducts = res.body.items.map(toProduct);
        P.live.state = P.catalogProducts.length ? 'ready' : 'empty';
        return P.catalogProducts;
      }).catch(function (err) { P.catalogProducts = []; P.live.state = 'error'; P.live.error = err; throw err; });
    },
    // 같은 상품을 이미 읽는 중이면 그 요청을 함께 기다린다(목록 카드·상세·대화가 같은 상품을 동시에 부를 때 한 번만 받는다).
    // 끝난 결과는 쌓아 두지 않는다 — 공개 구성은 매번 서버 판정(no-store)을 따른다.
    loadDetail: function (id) {
      var p = P.getCatalogProduct(id);
      if (!p) return Promise.resolve(null);
      var key = String(p.id);
      if (inflight[key]) return inflight[key];
      var done = function (v) { delete inflight[key]; return v; };
      return (inflight[key] = readDetail(p).then(done, function (err) { delete inflight[key]; throw err; }));
    }
  };
  var inflight = Object.create(null);
  function readDetail(p) {
    return get(OFFER + encodeURIComponent(p.id)).then(function (res) {
      if (res.status === 200 && res.body && res.body.ok) applyOffer(p, res.body);
      else if (res.status === 404) {
        p.specs = []; p.bomStatus = 'missing'; p.liveDetail = 'not_public';
        return get(REGISTERED + encodeURIComponent(p.id)).then(function (r2) { if (r2.status === 200 && r2.body && r2.body.ok) applyRegistered(p, r2.body); return p; }, function () { return p; });
      }
      else { p.liveDetail = 'error'; }
      return p;
    }, function () { p.liveDetail = 'error'; return p; });
  }

  // 실제 라우트: /mvp4/?screen=…  (상태는 응답이 정하므로 대화 시작 방식만 싣는다)
  P.designHref = function (screen, state, params) {
    var q = new URLSearchParams();
    if (screen && screen !== 'home') q.set('screen', screen);
    if (screen === 'chat' && state && state !== 'welcome') q.set('state', state);
    Object.keys(params || {}).forEach(function (k) { if (params[k] != null && params[k] !== '' && k !== 'dataset' && k !== 'state') q.set(k, String(params[k])); });
    // 검수용 예시 화면(review-flows.html)은 자기 주소와 예시 조건을 유지한다. 고객 화면은 ./ 하나.
    (P.routeKeep || []).forEach(function (k) { var v = P.qs.get(k); if (v && !q.has(k)) q.set(k, v); });
    var s = q.toString();
    return (P.routeBase || './') + (s ? '?' + s : '');
  };

  P.getCatalogProduct = function (id) {
    return (P.catalogProducts || []).find(function (p) { return String(p.id) === String(id); }) || null;
  };
  // 사진은 상대 자산 · 이 상품의 고객 공개 사진 · 팝콘PC 몰에 올린 이 상품의 대표 사진만 받는다.
  P.catalogImage = function (p) {
    if (!p || !p.image) return null;
    return /^assets\//.test(p.image) || p.image.indexOf('/api/customer/products/' + p.id + '/representative-image') === 0 || p.image === mallImage(p.id) ? p.image : null;
  };
}());
