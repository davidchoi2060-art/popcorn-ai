/* 오른쪽 패널을 운영자 작업 패널로 바꾼다 (슬라이스 61).
 *
 * 원래 이 자리는 Phoenix 템플릿의 Theme Customizer였다 — 31개 관리자 화면 중 30개에
 * 붙어 있으면서 내용은 Color Scheme·RTL(아랍어 문자 방향)·Navigation Type 4종·
 * Support Chat 토글이었다. 운영자가 얻는 건 없고 잘못 누르면 레이아웃이 바뀌어
 * "왜 이래요?" 문의만 만드는 자리였다. 게다가 전부 영문이라 한국어 UI 규약에도 어긋났다.
 *
 * 대시보드가 같은 것을 보여주긴 한다. 하지만 **보려면 대시보드로 돌아가야 한다.**
 * 이 패널의 값어치는 거기 있다 — 작업하던 화면을 떠나지 않고 확인하고 바로 이동한다.
 *
 * 숫자는 전부 서버(`/api/admin/worklist`)가 준 것만 쓴다. 화면이 세지 않는다.
 * 다크모드는 남긴다(야간 작업) — 한국어로 바꾸고, 레이아웃을 깨뜨리는 항목만 걷어낸다.
 */
(function () {
  var PANEL = 'settings-offcanvas';
  var SEEN_KEY = 'popcorn-admin-seen';   // 최근 본 상품 — 화면을 오갈 때 되돌아가기 쉽게
  var SEEN_MAX = 6;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[<>&"]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c];
    });
  }

  /* 지금 보고 있는 상품을 기록한다. 운영자는 검수 -> 상세 -> 재고를 오가는데
     그때마다 코드를 다시 찾아 들어가야 했다.
     **상품명은 나중에 채워진다**(서버 응답 후). 로드 시점에 읽으면 화면 제목
     ('상품 등록·수정')이 상품명 자리에 박힌다 — 잠시 뒤 다시 읽어 갱신한다. */
  function pname() {
    // 상품 상세는 #ptitle에 이름을 넣는다. 아무 h2나 잡으면 마크업에 남아 있던
    // 예시 상품명("이엠텍 RTX 4060 …")이 엉뚱한 코드에 붙어 저장된다(실제로 겪음).
    var el = document.getElementById('ptitle');
    if (!el) return '';
    var c = el.cloneNode(true);
    // 화면 ID 배지(ADM-PRD-030)는 상품명이 아니다
    [].forEach.call(c.querySelectorAll('.badge'), function (b) { b.remove(); });
    var s = String(c.textContent || '').replace(/\s+/g, ' ').trim();
    return s.length >= 4 ? s : '';
  }

  function remember(retry) {
    var m = location.search.match(/[?&]code=(\d+)/);
    if (!m) return;
    var code = m[1], name = pname();
    if (!name && retry !== false) {          // 아직 안 채워졌다 — 한 번만 기다렸다 다시
      setTimeout(function () { remember(false); }, 1200);
      return;
    }
    var list = [];
    try { list = JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'); } catch (e) { list = []; }
    list = list.filter(function (x) { return x && x.code !== code; });
    list.unshift({ code: code, name: name.slice(0, 40) });
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(list.slice(0, SEEN_MAX))); } catch (e) {}
  }

  function seenList() {
    try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'); } catch (e) { return []; }
  }

  function rel(href) {
    // 관리자 화면은 전부 mockups/admin/ 안에 있다 — 같은 폴더 기준 상대 경로면 된다
    return href;
  }

  function render(box, d) {
    var rows = (d.items || []).map(function (it) {
      var n = it.count || 0;
      var focus = (it.focus != null && it.focus !== n)
        ? '<div class="fs-10 text-body-tertiary mt-1">그중 ' + esc(it.focus_label) + ' <b>'
          + it.focus.toLocaleString() + '</b>건</div>' : '';
      // 0건은 회색으로 — 할 일이 없다는 것도 정보다
      var tone = n > 0 ? 'text-body-emphasis' : 'text-body-quaternary';
      return '<a href="' + rel(it.href) + '" class="d-block text-decoration-none border-bottom '
        + 'py-2 px-1 admin-wl-row">'
        + '<div class="d-flex justify-content-between align-items-baseline">'
        + '<span class="fs-9 fw-bold text-body-emphasis">' + esc(it.label) + '</span>'
        + '<span class="fs-7 fw-bolder ' + tone + '">' + n.toLocaleString() + '</span></div>'
        + '<div class="fs-10 text-body-tertiary">' + esc(it.hint) + '</div>'
        + focus + '</a>';
    }).join('');

    var seen = seenList();
    var seenHtml = seen.length
      ? seen.map(function (s) {
          return '<a href="product-edit.html?code=' + encodeURIComponent(s.code)
            + '" class="d-block text-decoration-none fs-10 py-1 text-body-secondary">'
            + '<span class="text-body-quaternary">' + esc(s.code) + '</span> '
            + esc(s.name) + '</a>';
        }).join('')
      : '<div class="fs-10 text-body-quaternary py-1">아직 연 상품이 없습니다</div>';

    box.innerHTML =
      '<div class="p-3 border-bottom">'
      + '<h5 class="mb-1 fs-8 fw-bolder text-body-emphasis">지금 할 일</h5>'
      + '<p class="mb-0 fs-10 text-body-tertiary">서버가 세는 실제 건수입니다 — '
      + '누르면 그 화면으로 갑니다.</p></div>'
      + '<div class="px-3 pt-2">' + rows + '</div>'
      + '<div class="p-3 border-top">'
      + '<h6 class="fs-9 fw-bold text-body-emphasis mb-2">빠른 이동</h6>'
      + '<div class="input-group input-group-sm mb-2">'
      + '<input id="wlGo" class="form-control form-control-sm" placeholder="상품코드 입력">'
      + '<button id="wlGoBtn" class="btn btn-sm btn-phoenix-primary">열기</button></div>'
      + '<div class="fs-10 text-body-quaternary mb-1">최근 본 상품</div>'
      + seenHtml + '</div>'
      + '<div class="p-3 border-top">'
      + '<h6 class="fs-9 fw-bold text-body-emphasis mb-2">화면 밝기</h6>'
      + '<div class="btn-group btn-group-sm w-100" role="group" id="wlTheme">'
      + '<button class="btn btn-phoenix-secondary" data-th="light">밝게</button>'
      + '<button class="btn btn-phoenix-secondary" data-th="dark">어둡게</button>'
      + '<button class="btn btn-phoenix-secondary" data-th="auto">자동</button>'
      + '</div></div>'
      + '<div class="px-3 pb-3 fs-10 text-body-quaternary">추천 가능 부품 '
      + (d.pool != null ? d.pool.toLocaleString() : '—') + '개</div>';

    var go = function () {
      var v = (document.getElementById('wlGo').value || '').trim();
      if (/^\d+$/.test(v)) location.href = 'product-edit.html?code=' + encodeURIComponent(v);
    };
    document.getElementById('wlGoBtn').onclick = go;
    document.getElementById('wlGo').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') go();
    });

    // 다크모드는 Phoenix가 쓰던 것과 같은 저장 키를 쓴다 — 우리가 새 규칙을 만들면
    // 템플릿의 나머지 코드와 어긋난다
    var cur = null;
    try { cur = localStorage.getItem('phoenixTheme'); } catch (e) {}
    [].forEach.call(box.querySelectorAll('#wlTheme button'), function (b) {
      if (b.getAttribute('data-th') === (cur || 'light')) b.classList.add('active');
      b.onclick = function () {
        var th = b.getAttribute('data-th');
        try { localStorage.setItem('phoenixTheme', th); } catch (e) {}
        document.documentElement.setAttribute('data-bs-theme',
          th === 'auto' ? (window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark' : 'light') : th);
        [].forEach.call(box.querySelectorAll('#wlTheme button'), function (x) {
          x.classList.toggle('active', x === b);
        });
      };
    });
  }

  /* 좌측 메뉴·상단 알림의 배지 숫자를 서버 값으로 갈아끼운다.
     마크업에는 상품 검수 9 · 가격 검토 5 · 단가표 15 · 재고 입고 3이 박혀 있었다.
     실제로는 5,162 · 0 · 1 · 15,261이다 — 메뉴가 대놓고 거짓말을 하고 있었다.
     href로 찾으므로 사이드바와 상단 드롭다운이 한 번에 맞춰진다. */
  function paintBadges(d) {
    var byHref = {};
    (d.items || []).forEach(function (i) { byHref[i.href] = i; });
    [].forEach.call(document.querySelectorAll('a[href]'), function (a) {
      var it = byHref[a.getAttribute('href')];
      var b = a.querySelector('.badge');
      if (!b) return;
      if (!it) {
        // 원천이 없는 배지는 지운다 — 지어낸 수를 남기느니 없는 편이 낫다
        if (/^\s*\d+\s*$/.test(b.textContent)) b.remove();
        return;
      }
      if (!it.count) { b.remove(); return; }      // 0건이면 배지 자체를 없앤다
      // '대기 9'처럼 접두어가 붙은 것은 접두어를 살린다
      var pre = (b.textContent || '').replace(/[\d,\s]+$/, '').trim();
      b.textContent = (pre ? pre + ' ' : '') + it.count.toLocaleString();
    });
  }

  /* 패널 머리말과 여는 버튼이 영문이었다("Theme Customizer" · "customize").
     한국어 UI 규약이기도 하고, 무엇보다 이제 테마 설정이 아니다. */
  function korean(panel) {
    var h = panel.querySelector('.offcanvas-header h5, .offcanvas-title');
    if (h) h.innerHTML = '<span class="fas fa-clipboard-list me-2 fs-8"></span>작업 패널';
    var p = panel.querySelector('.offcanvas-header p');
    if (p) p.textContent = '지금 처리할 일과 바로가기입니다';
    // 템플릿의 'Reset to default'는 테마 초기화 버튼이라 쓸 데가 없다
    [].forEach.call(panel.querySelectorAll('button, a'), function (b) {
      if (/reset to default/i.test((b.textContent || '').trim())) b.remove();
    });
    var tog = document.querySelector('.setting-toggle');
    if (tog) {
      [].forEach.call(tog.querySelectorAll('*'), function (e) {
        if (e.children.length === 0 && /customize/i.test(e.textContent || '')) {
          e.textContent = '할 일';
        }
      });
      tog.setAttribute('aria-label', '작업 패널 열기');
      tog.setAttribute('title', '작업 패널');
    }
  }

  function boot() {
    var panel = document.getElementById(PANEL);
    if (!panel) return;
    remember();
    // 템플릿이 심어둔 안내 말풍선(settings-popover)은 테마 설정을 가리키던 것이라 지운다
    var pop = document.querySelector('.settings-popover');
    if (pop && pop.parentNode) pop.parentNode.removeChild(pop);
    korean(panel);

    var body = panel.querySelector('.offcanvas-body') || panel;
    body.innerHTML = '<div class="p-3 fs-9 text-body-tertiary">작업 목록을 불러오는 중…</div>';

    function load(first) {
      return fetch('/api/admin/worklist')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) {
            // 서버가 없으면 지어내지 않는다 — 못 받았다고 말한다(목업 폴백).
            // 마크업의 더미 배지도 지운다: 서버에 못 닿았는데 '검수 9'가 남아 있으면
            // 그게 실제 값인 줄 안다.
            if (first) clearDummyBadges();
            body.innerHTML = '<div class="p-3 fs-9 text-body-tertiary">'
              + '작업 목록을 불러오지 못했습니다 — 서버에 연결되면 표시됩니다.</div>';
            return;
          }
          paintBadges(d);
          render(body, d);
        })
        .catch(function () {
          if (first) clearDummyBadges();
          body.innerHTML = '<div class="p-3 fs-9 text-body-tertiary">'
            + '작업 목록을 불러오지 못했습니다.</div>';
        });
    }

    load(true);
    /* 메뉴 숫자는 계속 따라가야 한다. 운영자가 검수를 처리해도 옆의 배지가 어제 값이면
       무엇이 남았는지 알 수 없다. 60초마다 갱신하고, 다른 탭에서 보고 있을 때는 쉰다. */
    setInterval(function () {
      if (document.visibilityState === 'visible') load(false);
    }, 60000);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') load(false);
    });
  }

  function clearDummyBadges() {
    [].forEach.call(document.querySelectorAll('.navbar-vertical a .badge, .dropdown-item .badge'),
      function (b) {
        if (/^\s*(\D*\s)?[\d,]+\s*$/.test(b.textContent || '')) b.remove();
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
