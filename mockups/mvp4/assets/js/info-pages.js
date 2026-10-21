/* /mvp4 회사정보 · 이용약관 · 개인정보처리방침 · 구매·배송·A/S 안내 (2026-10-21 대표 확정 디자인 05·06).
 *
 * 회사정보는 대표가 확정한 값만 쓴다(00-design-handoff.txt 「회사정보 원문 기준」). 대표번호는 착신 확인 전이라 전화 걸기 링크를
 * 걸지 않고 표기만 한다. 정책 세 문서는 v3 검토용 초안이라 공개 화면에 본문을 싣지 않는다 -- P.policyDocs 에 «확정된» 문서가
 * 들어오면 같은 읽기 틀(목차 + 본문)로 그린다. 확정 전 문서를 이 파일에 옮겨 적지 않는다.
 */
(function () {
  'use strict';
  var P = window.PAI = window.PAI || {};
  P.pages = P.pages || {};
  P.policyDocs = P.policyDocs || {};
  var h = function (v) { return P.h ? P.h(v) : String(v == null ? '' : v); };
  var icon = function (n, c) { return P.icon ? P.icon(n, c) : ''; };

  var TABS = [['company', '회사정보', 'company.html'], ['terms', '이용약관', 'terms.html'],
    ['privacy', '개인정보처리방침', 'privacy.html'], ['purchase-support', '구매·배송·A/S 안내', 'purchase-support.html']];

  var COMPANY = {
    name: '주식회사 팝콘컴퓨터',
    rows: [['대표자', '이미숙'], ['사업자등록번호', '794-81-00671'],
      ['주소', '서울특별시 용산구 원효로 188, 5층\n(원효로2가, JM빌딩)'], ['대표번호', '02)1644-0249'],
      ['팩스', '070-8610-0100'], ['웹팩스', '0303-3442-0249'], ['개인정보보호책임자', '이미숙']]
  };

  function tabs(active) {
    return '<nav class="ip-tabs" aria-label="회사정보와 정책">' + TABS.map(function (t) {
      return '<a href="' + t[2] + '"' + (t[0] === active ? ' aria-current="page"' : '') + '>' + h(t[1]) + '</a>';
    }).join('') + '</nav>';
  }

  function head(active, title, lead, extra) {
    return '<header class="ip-head"><div class="ip-title-row"><h1>' + h(title) + '</h1>' + (extra || '') + '</div>' +
      '<p class="ip-lead">' + h(lead) + '</p>' + tabs(active) + '</header>';
  }

  function page(inner) { return '<div class="ip-page"><div class="container ip-wrap">' + inner + '</div></div>'; }

  P.pages.company = function () {
    var rows = COMPANY.rows.map(function (r) {
      return '<div class="ip-row"><dt>' + h(r[0]) + '</dt><dd>' + h(r[1]).replace(/\n/g, '<br>') + '</dd></div>';
    }).join('');
    var roles = '<section class="ip-roles" aria-labelledby="ip-roles-title"><h2 id="ip-roles-title">팝콘AI와 팝콘PC몰의 역할</h2>' +
      '<ul><li><span class="ip-role-icon">' + icon('chat-circle') + '</span><div><strong>팝콘AI</strong><p>상품 탐색 · AI 추천 · 비교 · 견적 보관 · 상담 안내</p></div></li>' +
      '<li><span class="ip-role-icon">' + icon('package') + '</span><div><strong>제휴사 팝콘PC</strong><p>상품 판매 · 결제 · 배송 · 교환 · 반품 · 환급 · 제품 A/S · 회원관리</p></div></li></ul>' +
      '<p class="ip-note">' + icon('info') + '<span>팝콘AI와 팝콘PC는 별도 사업자입니다.</span></p>' +
      '<a class="ip-more" href="purchase-support.html">구매·배송·A/S 안내 보기 ' + icon('arrow-right') + '</a>' +
      // 착신 확인 전 -- 버튼 모양이지만 전화를 걸지 않는다(00-design-handoff.txt).
      '<p class="ip-phone">' + icon('phone') + '<span>대표번호 <strong>02)1644-0249</strong></span></p></section>';
    return { html: page(head('company', '회사정보', '팝콘AI를 운영하는 회사 정보를 안내합니다.') +
      '<div class="ip-card ip-company"><section class="ip-co" aria-labelledby="ip-co-name"><h2 id="ip-co-name">' + h(COMPANY.name) + '</h2>' +
      '<p class="ip-sub">팝콘AI 운영사</p><dl class="ip-rows">' + rows + '</dl></section>' + roles + '</div>') };
  };

  // ── 정책 문서 읽기 틀 (06) ──
  var CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩';
  function block(b) {
    if (b.t === 'h3') return '<h3>' + h(b.text) + '</h3>';
    if (b.t === 'ol') return '<ol class="ip-marked">' + b.items.map(function (it) {
      var n = CIRCLED.indexOf(it.mark);   // ①~⑩은 원 안의 숫자로 그린다(06). 글자는 원문 그대로 읽힌다.
      return '<li><span class="ip-mark' + (n >= 0 ? ' ip-circ' : '') + '" aria-label="' + h(it.mark) + '">' + h(n >= 0 ? String(n + 1) : it.mark) + '</span><span>' + h(it.text) + '</span></li>';
    }).join('') + '</ol>';
    if (b.t === 'table') return '<div class="ip-table">' + b.rows.map(function (r) {
      return '<dl class="ip-table-row">' + r.map(function (c, i) {
        return '<div><dt>' + h(b.head[i] || '') + '</dt><dd>' + h(c) + '</dd></div>';
      }).join('') + '</dl>';
    }).join('') + '</div>';
    return '<p>' + h(b.text) + '</p>';
  }

  P.policyDocRender = function (key, doc, title, lead) {
    var toc = doc.sections.map(function (s, i) {
      return '<li><a href="#' + h(s.id) + '"' + (i === 0 ? ' aria-current="true"' : '') + '>' + h(s.title) + '</a></li>';
    }).join('');
    var body = (doc.intro || []).map(block).join('') + doc.sections.map(function (s) {
      return '<section class="ip-sec" id="' + h(s.id) + '"><h2>' + h(s.title) + '</h2>' + s.blocks.map(block).join('') + '</section>';
    }).join('');
    var badge = doc.badge ? '<span class="ip-badge">' + h(doc.badge) + '</span>' : '';
    return page(head(key, title || doc.title, lead || doc.lead, badge) + (doc.meta ? '<p class="ip-meta">' + h(doc.meta) + '</p>' : '') +
      '<div class="ip-card ip-doc"><details class="ip-toc" open><summary>목차</summary><ol>' + toc + '</ol></details>' +
      '<article class="ip-body">' + body + '</article></div>' +
      '<a class="ip-top" href="#main-content">맨 위로 ' + icon('caret-down', 'ip-up') + '</a>');
  };

  function pending(key, title, lead, text) {
    return page(head(key, title, lead) + '<div class="ip-card ip-pending"><p>' + h(text) + '</p>' +
      '<p class="ip-sub">회사 정보는 <a class="text-link" href="company.html">회사정보</a>에서 확인할 수 있습니다.</p></div>');
  }

  function policyPage(key, title, lead, pendingText) {
    return function () {
      var doc = P.policyDocs[key];
      if (doc && Array.isArray(doc.sections)) {
        return { html: P.policyDocRender(key, doc, title, lead), mount: mountToc };
      }
      return { html: pending(key, title, lead, pendingText) };
    };
  }

  // 목차: 지금 읽는 조 표시 + 휴대폰에서 목차를 고르면 접는다.
  function mountToc() {
    var links = Array.prototype.slice.call(document.querySelectorAll('.ip-toc a'));
    var toc = document.querySelector('.ip-toc');
    if (window.matchMedia && window.matchMedia('(max-width: 860px)').matches && toc) toc.removeAttribute('open');
    links.forEach(function (a) { a.addEventListener('click', function () { if (toc && window.matchMedia('(max-width: 860px)').matches) toc.removeAttribute('open'); }); });
    if (!('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (a) { if (a.getAttribute('href') === '#' + e.target.id) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current'); });
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    document.querySelectorAll('.ip-sec').forEach(function (s) { io.observe(s); });
  }

  P.pages.terms = policyPage('terms', '이용약관', '팝콘AI 웹사이트의 이용과 관련한 권리, 의무 및 책임 사항을 안내합니다.',
    '이용약관은 검토 중입니다. 확정되면 이 자리에 게시합니다.');
  P.pages.privacy = policyPage('privacy', '개인정보처리방침', '팝콘AI가 처리하는 개인정보와 이용자의 권리를 안내합니다.',
    '개인정보처리방침은 검토 중입니다. 확정되면 이 자리에 게시합니다.');
  P.pages['purchase-support'] = policyPage('purchase-support', '구매·배송·A/S 안내', '팝콘AI에서 살펴보고, 팝콘PC몰에서 구매하세요.',
    '배송비와 출고 일정, 보증 및 반품·A/S 조건은 상품별로 다를 수 있습니다. 구매하실 판매 페이지의 안내를 확인해 주세요.');
}());
