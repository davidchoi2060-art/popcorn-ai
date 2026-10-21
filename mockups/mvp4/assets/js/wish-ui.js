/* /mvp4 찜하기 버튼·찜목록 개수 (2026-10-21 대표 확정 1번 시안 「찜하기·찜목록」).
 *
 * 추천 카드·AI 답변 카드·PC 쇼핑 카드·상품 상세·AI 장비 상세가 모두 이 버튼 하나를 쓴다. 저장은 wish-store.js(이 브라우저).
 * 버튼은 data-wish-kind·data-wish-id 만 들고, 누르면 이 파일이 저장소를 바꾼 뒤 화면의 같은 상품 버튼과 개수를 함께 맞춘다.
 * 다른 탭에서 바뀌어도 같은 방식으로 맞춘다. 저장하지 못하면 바꾸지 않고 그 사실을 알린다.
 * 찜·찜 해제는 질문 대상·대화·입력 중인 문장·견적을 바꾸지 않고, 서버나 AI 를 부르지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var W = P.wishlist;
  if (!W) return;
  var HEART = '<svg class="wish-heart" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 20.5s-7.5-4.4-9.3-9.2C1.4 7.9 3.6 4.5 7 4.5c2 0 3.6 1.1 5 2.9 1.4-1.8 3-2.9 5-2.9 3.4 0 5.6 3.4 4.3 6.8-1.8 4.8-9.3 9.2-9.3 9.2z"/></svg>';
  function h(v) { return P.h ? P.h(v) : String(v == null ? '' : v); }
  // 찜목록 화면 주소. 고객 화면(/mvp4/?screen=…) 밖의 페이지(AI 장비 상세 등)에서도 같은 화면으로 간다.
  P.wishHref = function (params) {
    if (typeof P.designHref === 'function') return P.designHref('compare', 'normal', params || {});
    var q = new URLSearchParams({ screen: 'compare' }); Object.keys(params || {}).forEach(function (k) { if (params[k]) q.set(k, params[k]); });
    return './?' + q;
  };
  function label(on, b) { return on ? (b && b.on) || '찜한 상품' : (b && b.off) || '찜하기'; }
  // opts: {kind, id, name, cls, on, off}. 이름은 숨긴 접근성 글자로만 쓴다. on/off 는 문구를 바꿀 때(찜목록의 「찜 해제」).
  P.wishButton = function (opts) {
    var on = W.has(opts.kind, opts.id);
    return '<button type="button" class="wish-btn' + (opts.cls ? ' ' + h(opts.cls) : '') + (on ? ' is-on' : '') + '" data-wish-kind="' + h(opts.kind) + '" data-wish-id="' + h(opts.id) + '" data-wish-name="' + h(opts.name || '') + '"' + (opts.on ? ' data-wish-on="' + h(opts.on) + '"' : '') + (opts.off ? ' data-wish-off="' + h(opts.off) + '"' : '') + ' aria-pressed="' + on + '">' + HEART + '<span data-wish-label>' + label(on, opts) + '</span>' + (opts.name ? '<span class="visually-hidden"> · ' + h(opts.name) + '</span>' : '') + '</button>';
  };
  P.wishCount = function () { return W.count(); };
  // 「찜목록 보기 (N)」 링크. 개수는 저장소가 바뀌면 함께 바뀐다.
  P.wishLink = function (opts) {
    opts = opts || {};
    return '<a class="wish-link' + (opts.cls ? ' ' + h(opts.cls) : '') + '" href="' + h(P.wishHref(opts.params)) + '">' + HEART + '<span>' + h(opts.label || '찜목록 보기') + '</span><b class="wish-count" data-wish-count>' + W.count() + '</b></a>';
  };
  function sync() {
    var count = W.count();
    document.querySelectorAll('[data-wish-id][data-wish-kind]').forEach(function (b) {
      var on = W.has(b.dataset.wishKind, b.dataset.wishId);
      b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', String(on));   // 보이는 문구 + 숨긴 상품명이 접근성 이름, 상태는 눌림으로 알린다
      var t = b.querySelector('[data-wish-label]'); if (t) t.textContent = label(on, { on: b.dataset.wishOn, off: b.dataset.wishOff });
    });
    document.querySelectorAll('[data-wish-count]').forEach(function (n) { n.textContent = String(count); });
    document.querySelectorAll('[data-wish-has]').forEach(function (n) { n.hidden = count === 0; });
  }
  var toastTimer = null;
  // 알림: 찜 해제만 잠깐 「되돌리기」를 준다(영구 복구를 약속하지 않는다).
  P.wishToast = function (text, undo) {
    var box = document.querySelector('[data-wish-toast]');
    if (!box) { box = document.createElement('div'); box.className = 'wish-toast'; box.setAttribute('data-wish-toast', ''); box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
    box.innerHTML = '<span>' + h(text) + '</span>' + (undo ? '<button type="button" data-wish-undo>되돌리기</button>' : '');
    box.classList.add('is-shown');
    var btn = box.querySelector('[data-wish-undo]');
    if (btn) btn.addEventListener('click', function () { var r = W.add(undo.kind, undo.id); P.wishToast(r.ok ? '다시 찜했어요.' : '되돌리지 못했어요. 브라우저 저장 설정을 확인해 주세요.'); });
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { box.classList.remove('is-shown'); box.innerHTML = ''; }, undo ? 6000 : 3500);
  };
  document.addEventListener('click', function (event) {
    var b = event.target.closest && event.target.closest('button[data-wish-id][data-wish-kind]');
    if (!b || b.disabled) return;
    event.preventDefault();
    var kind = b.dataset.wishKind, id = b.dataset.wishId, name = b.dataset.wishName, r = W.toggle(kind, id);
    if (!r.ok) { P.wishToast(r.reason === 'invalid' ? '이 상품은 찜할 수 없어요.' : '찜을 저장하지 못했어요. 브라우저의 사이트 데이터 저장 설정을 확인해 주세요.'); sync(); return; }
    if (r.wished) P.wishToast((name ? name + ' · ' : '') + '찜했어요. 찜목록에서 골라 비교할 수 있어요.');
    else P.wishToast((name ? name + ' · ' : '') + '찜을 해제했어요.', { kind: kind, id: id });
  });
  W.onChange(sync);
  W.migrate();   // 예전 「비교에 담기」로 실제 담았던 상품만 한 번 옮긴다(추천·선택 상품은 옮기지 않는다)
  P.wishSync = sync;
}());
