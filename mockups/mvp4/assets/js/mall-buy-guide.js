/* /mvp4 팝콘PC몰 구매 전 가격 안내 (2026-10-21 구매·견적·AI 비교 1번 승인).
 *
 * 「팝콘PC몰에서 구매」 링크(data-mall-buy)를 누르면 바로 몰로 가지 않고, 고른 상품·모델·수량과 가격 변동 안내를 먼저 보인다.
 *   돌아가기 = 안내만 닫고 누른 버튼으로 초점을 돌린다(선택·수량·스크롤 유지).
 *   팝콘PC몰로 이동 = 같은 상품번호의 몰 상세를 새 창으로 연다.
 * 동의 체크·연락처·저장·상담을 구매 앞에 두지 않는다. 몰에 수량을 넘기지 못하므로 수량이 있으면 몰에서 다시 확인하라고 알린다.
 * 링크 주소는 P.mallUrlFor 하나로 검사한다 — https · www.popcornpc.co.kr · 몰 상품 상세 경로 · pd_no 가 그 상품번호일 때만.
 * 몰 홈·검색·다른 상품번호면 빈 값이고, 버튼은 「구매 링크 확인 필요」로 남는다(조용한 대체 이동 없음).
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  var PATHS = ['/shop/system_detail.html', '/shop/product_detail.html'];
  function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  P.mallUrlFor = function (id, url) {
    if (typeof url !== 'string' || !/^\d{1,18}$/.test(String(id))) return '';
    var u; try { u = new URL(url); } catch (e) { return ''; }
    return u.protocol === 'https:' && u.hostname === 'www.popcornpc.co.kr' && PATHS.indexOf(u.pathname) >= 0 && u.searchParams.get('pd_no') === String(id) && !u.hash && u.username === '' && u.password === '' ? u.href : '';
  };
  // 구매 링크 한 개. o = {id, url, name, model, quantity, price(1대 값|null), image, cls, label}
  P.mallBuyAnchor = function (o) {
    var href = P.mallUrlFor(o.id, o.url);
    if (!href) return '';
    var attrs = ' data-mall-buy="' + esc(o.id) + '" data-mall-name="' + esc(o.name || '') + '"' + (o.model ? ' data-mall-model="' + esc(o.model) + '"' : '') +
      (o.quantity ? ' data-mall-qty="' + esc(o.quantity) + '"' : '') + (typeof o.price === 'number' && o.price > 0 ? ' data-mall-price="' + esc(o.price) + '"' : '') + (o.image ? ' data-mall-img="' + esc(o.image) + '"' : '');
    return '<a class="' + esc(o.cls || 'btn btn-primary') + '" href="' + esc(href) + '" target="_blank" rel="noopener"' + attrs + '>' + esc(o.label || '팝콘PC몰에서 바로 구매') + ' <span aria-hidden="true">↗</span></a>';
  };
  function money(n) { return Number(n).toLocaleString('ko-KR') + '원'; }
  var dialog = null, opener = null;
  function close() { if (!dialog) return; if (dialog.open) dialog.close(); }
  function open(a) {
    var href = P.mallUrlFor(a.dataset.mallBuy, a.href);
    if (!href) return false;
    opener = a;
    var qty = parseInt(a.dataset.mallQty || '', 10), unit = Number(a.dataset.mallPrice), hasPrice = isFinite(unit) && unit > 0;
    var name = a.dataset.mallName || '', model = a.dataset.mallModel || '', img = a.dataset.mallImg || '';
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'mb-guide';
      dialog.setAttribute('aria-labelledby', 'mb-title');
      dialog.setAttribute('aria-describedby', 'mb-desc');
      document.body.appendChild(dialog);
      dialog.addEventListener('close', function () { document.documentElement.classList.remove('mb-open'); if (opener && document.contains(opener)) opener.focus({ preventScroll: true }); });
      dialog.addEventListener('click', function (e) {
        if (e.target === dialog || e.target.closest('[data-mb-close]')) { e.preventDefault(); close(); return; }
        if (e.target.closest('[data-mb-go]')) setTimeout(close, 0);   // 새 창은 링크가 연다. 안내만 닫는다.
      });
    }
    var total = hasPrice ? unit * (qty > 0 ? qty : 1) : null;
    dialog.innerHTML = '<div class="mb-box"><header class="mb-head"><h2 id="mb-title">팝콘PC몰에서 구매를 이어갑니다.</h2><button type="button" class="mb-x" data-mb-close aria-label="안내 닫기">×</button></header>' +
      '<div class="mb-product">' + (img ? '<img src="' + esc(img) + '" alt="" width="96" height="64">' : '') + '<div><strong>' + esc(name) + (model && name.indexOf(model) < 0 ? ' · ' + esc(model) : '') + '</strong><small>상품번호 ' + esc(a.dataset.mallBuy) + (qty > 0 ? ' · 수량 ' + qty + '대' : '') + '</small></div>' +
      '<div class="mb-price">' + (hasPrice ? '<b>' + esc(money(total)) + '</b><small>팝콘AI 표시 금액' + (qty > 1 ? ' · ' + qty + '대' : '') + '</small>' : '<b class="mb-unknown">가격 확인 필요</b><small>최종 가격은 팝콘PC몰에서 확인</small>') + '</div></div>' +
      '<div class="mb-warn" id="mb-desc" role="note"><span class="mb-warn-mark" aria-hidden="true">!</span><p><strong>부품 가격이 수시로 변경되어 표시 금액과 실제 판매 금액이 다를 수 있습니다.</strong> 구매 전 팝콘PC몰에서 최종 가격과 구성을 확인해 주세요.</p></div>' +
      (qty > 0 ? '<p class="mb-qty">구매 수량은 팝콘PC몰에서 다시 확인해 주세요.</p>' : '') +
      '<div class="mb-actions"><button type="button" class="btn btn-outline" data-mb-close>돌아가기</button><a class="btn mb-go" data-mb-go href="' + esc(href) + '" target="_blank" rel="noopener">팝콘PC몰로 이동 <span aria-hidden="true">↗</span></a></div></div>';
    document.documentElement.classList.add('mb-open');
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
    var back = dialog.querySelector('.mb-actions [data-mb-close]'); if (back) back.focus();
    return true;
  }
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[data-mall-buy]');
    if (!a || (dialog && dialog.contains(a))) return;
    if (open(a)) e.preventDefault();
  });
  P.mallBuyGuide = { open: open, close: close };
}());
