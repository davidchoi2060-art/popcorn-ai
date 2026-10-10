/* admin2 공통 셸 JS — 좌측 메뉴(LNB) 접기·그룹 아코디언 + 권한 표시(+선택적 토스트).
 * 단일 원천: `templates/admin/_admin2_shell.html.j2`가 이 파일 하나만 부른다.
 *
 * reviews.html.j2(2026-08-13 사장님 승인판)가 화면마다 따로 갖고 있던 initLnb/
 * toggleLnb/toggleLnbGroup/loadMe/renderRoleBox를 여기로 모았다 — 화면이 늘 때마다
 * 이 코드를 다시 베끼면 언젠가 갈라진다(`.claude/CANON.md` §1의 병).
 *
 * ■ 접기 상태를 화면별이 아니라 **전역 하나**로 저장한다(reviews.html.j2 원본은
 *   'admin2.reviews.lnbCollapsed'로 화면마다 따로였다) — 사이드바를 접고 다른 admin2
 *   화면으로 이동해도 접힌 채 유지되는 편이 셸 하나라는 이 작업의 취지에 맞는다.
 * ■ `data-keep="1"`인 LNB 밖 클릭으로 화면 자신의 선택 상태를 지우는 것은 각 화면의
 *   책임이다(무엇을 지울지는 화면마다 다르다) — 여기서는 `isKeepClick()` 헬퍼만 준다.
 */
(function () {
  'use strict';

  var ROLE_KO = { viewer: '조회', operator: '운영자', owner: '관리자' };
  var ROLE_RANK = { viewer: 1, operator: 2, owner: 3 };

  var LNB_COLLAPSE_KEY = 'admin2.lnb.collapsed';
  var LNB_CLOSED_KEY = 'admin2.lnb.closed';

  var lnb = document.getElementById('lnb');
  var collapsed = false;

  function applyCollapse() {
    if (!lnb) return;
    lnb.classList.toggle('collapsed', collapsed);
    var brand = document.getElementById('lnbBrand');
    if (brand) brand.textContent = collapsed ? '팝콘' : '팝콘 AI';
    var icon = document.getElementById('lnbToggleIcon');
    if (icon) icon.textContent = collapsed ? '»' : '«';
  }
  function toggleCollapse() {
    collapsed = !collapsed;
    try { sessionStorage.setItem(LNB_COLLAPSE_KEY, collapsed ? '1' : '0'); } catch (e) { /* 무시 */ }
    applyCollapse();
  }
  function readClosed() {
    try { return JSON.parse(sessionStorage.getItem(LNB_CLOSED_KEY)) || []; } catch (e) { return []; }
  }
  function initLnb() {
    if (!lnb) return;
    try { collapsed = sessionStorage.getItem(LNB_COLLAPSE_KEY) === '1'; } catch (e) { collapsed = false; }
    applyCollapse();
    var closed = readClosed();
    lnb.querySelectorAll('.a2-lnb-grp').forEach(function (g) {
      var key = g.getAttribute('data-grp');
      if (closed.indexOf(key) >= 0) {
        g.setAttribute('data-open', 'n');
        var b = g.querySelector('[data-action="lnb-group"]');
        if (b) b.setAttribute('aria-expanded', 'false');
      }
    });
  }
  function toggleGroup(btn) {
    var g = btn.closest('.a2-lnb-grp');
    if (!g) return;
    var key = g.getAttribute('data-grp');
    var open = g.getAttribute('data-open') === 'y';
    g.setAttribute('data-open', open ? 'n' : 'y');
    btn.setAttribute('aria-expanded', String(!open));
    var closed = readClosed();
    var i = closed.indexOf(key);
    if (open && i < 0) closed.push(key);
    if (!open && i >= 0) closed.splice(i, 1);
    try { sessionStorage.setItem(LNB_CLOSED_KEY, JSON.stringify(closed)); } catch (e) { /* 무시 */ }
    if (collapsed) { collapsed = false; applyCollapse(); }
  }

  // NEW mobile disclosure is RAM-only: desktop/group session keys keep their meaning.
  function initMobileLnb() {
    var button = document.getElementById('lnbMobileToggle');
    var menu = document.getElementById('lnbMenu');
    if (!lnb || !button || !menu || document.body.getAttribute('data-admin-mode') !== 'new') return;
    var media = window.matchMedia('(max-width:768px)');
    var mobileOpen = false;
    function applyMobile() {
      var active = document.activeElement;
      var closingFocus = media.matches && !mobileOpen && menu.contains(active);
      menu.hidden = media.matches && !mobileOpen;
      button.setAttribute('aria-expanded', String(media.matches && mobileOpen));
      button.setAttribute('aria-label', mobileOpen ? '메뉴 닫기' : '메뉴 열기');
      document.getElementById('lnbMobileLabel').textContent = mobileOpen ? '메뉴 닫기' : '메뉴 열기';
      lnb.setAttribute('data-mobile-open', String(media.matches && mobileOpen));
      if (media.matches) {
        lnb.classList.remove('collapsed');
        document.getElementById('lnbBrand').textContent = '팝콘 AI';
        if (closingFocus || active === document.getElementById('lnbToggle')) button.focus({ preventScroll: true });
      } else {
        applyCollapse();
        if (active === button) document.getElementById('lnbToggle').focus({ preventScroll: true });
      }
    }
    button.addEventListener('click', function () {
      if (!media.matches) return;
      mobileOpen = !mobileOpen;
      applyMobile();
    });
    lnb.addEventListener('keydown', function (ev) {
      if (!media.matches || !mobileOpen || ev.key !== 'Escape' || !lnb.contains(ev.target)) return;
      ev.preventDefault();
      ev.stopPropagation();
      mobileOpen = false;
      applyMobile();
    });
    function changeMobile() {
      mobileOpen = false;
      applyMobile();
    }
    if (media.addEventListener) media.addEventListener('change', changeMobile);
    else media.addListener(changeMobile);
    applyMobile();
  }

  if (lnb) {
    lnb.addEventListener('click', function (ev) {
      var toggle = ev.target.closest('[data-action="toggle-lnb"]');
      if (toggle) { toggleCollapse(); return; }
      var grp = ev.target.closest('[data-action="lnb-group"]');
      if (grp) { toggleGroup(grp); }
    });
    initLnb();
    initMobileLnb();
  }

  // ── 화면 머리말 바로가기 접기 (2026-10-11) — 셸이 그린 `.a2-intro` 만 다룬다.
  //    접힘 여부는 이 브라우저에만 기억한다(값이 없거나 저장소가 막혀도 펼친 채로 그린다).
  (function initIntro() {
    var intro = document.getElementById('a2Intro');
    var btn = document.getElementById('a2IntroToggle');
    if (!intro || !btn) return;
    var KEY = 'a2.introLinks.collapsed';
    function apply(collapsed) {
      intro.setAttribute('data-collapsed', collapsed ? 'y' : 'n');
      btn.setAttribute('aria-expanded', String(!collapsed));
      btn.textContent = collapsed ? '바로가기 펼치기' : '바로가기 접기';
    }
    var saved = false;
    try { saved = window.localStorage.getItem(KEY) === 'y'; } catch (e) { saved = false; }
    apply(saved);
    btn.addEventListener('click', function () {
      var next = intro.getAttribute('data-collapsed') !== 'y';
      apply(next);
      try { window.localStorage.setItem(KEY, next ? 'y' : 'n'); } catch (e) { /* 기억 못 해도 동작은 같다 */ }
    });
  })();

  // ── 권한 표시 — `/api/admin/auth/me`를 화면마다 다시 부르지 않는다 ──────────
  var me = null;
  var resolveReady;
  var meReady = new Promise(function (resolve) { resolveReady = resolve; });

  function renderRoleBox() {
    var box = document.getElementById('roleBox');
    if (!box) return;
    if (!me) { box.textContent = '로그인 필요'; return; }
    box.textContent = (me.name || me.email || '') + ' · ' + (ROLE_KO[me.role] || me.role);
  }
  fetch('/api/admin/auth/me', { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (j) { me = j.authenticated ? j.operator : null; })
    .catch(function () { me = null; })
    .then(function () { renderRoleBox(); resolveReady(me); });

  function canWrite(minRole) {
    minRole = minRole || 'operator';
    return !!(me && ROLE_RANK[me.role] >= ROLE_RANK[minRole]);
  }

  // ── 토스트(선택적 — 화면이 원하면 쓴다. reviews.html.j2는 기존 자체 구현을 그대로
  //    쓰고 있어 이 헬퍼로 옮기지 않았다: 승인/기각/되돌리기 흐름이 이미 검증된 코드라
  //    옮기는 위험이 이득보다 크다는 판단, 2026-08-13 제작자 판단 — 보고서 참조) ──
  var toastSeq = 0, toasts = [];
  function renderToasts() {
    var box = document.getElementById('toasts');
    if (!box) return;
    box.innerHTML = toasts.map(function (t) {
      var color = t.kind === 'err' ? 'var(--rv-red)' : (t.kind === 'warn' ? 'var(--rv-amber)' : 'var(--rv-green)');
      var mark = t.kind === 'err' ? '✕' : (t.kind === 'warn' ? '▲' : '✓');
      return '<div class="a2-toast" style="border-left-color:' + color + '" data-tid="' + t.id + '">'
        + '<span class="a2-toast-mark" style="color:' + color + '"></span>'
        + '<span class="a2-toast-msg"></span>'
        + (t.action ? '<button type="button" class="a2-toast-act" data-a2-toast-act="' + t.id + '"></button>' : '')
        + '<button type="button" class="a2-toast-x" data-a2-toast-close="' + t.id + '">✕</button></div>';
    }).join('');
    // 메시지는 textContent 로 채운다 — 전사본·사용자 입력이 그대로 innerHTML 에 들어가면 XSS
    toasts.forEach(function (t) {
      var row = box.querySelector('[data-tid="' + t.id + '"]');
      if (!row) return;
      row.querySelector('.a2-toast-mark').textContent = row.querySelector('.a2-toast-mark').textContent;
      row.querySelector('.a2-toast-msg').textContent = t.msg;
      var actBtn = row.querySelector('[data-a2-toast-act]');
      if (actBtn) actBtn.textContent = t.action;
    });
  }
  function toast(msg, kind, action, onAction) {
    var id = ++toastSeq;
    toasts.push({ id: id, msg: msg, kind: kind, action: action, onAction: onAction });
    renderToasts();
    setTimeout(function () {
      toasts = toasts.filter(function (t) { return t.id !== id; });
      renderToasts();
    }, 7000);
  }
  document.addEventListener('click', function (ev) {
    var x = ev.target.closest('[data-a2-toast-close]');
    if (x) {
      var xid = Number(x.getAttribute('data-a2-toast-close'));
      toasts = toasts.filter(function (t) { return t.id !== xid; });
      renderToasts();
      return;
    }
    var a = ev.target.closest('[data-a2-toast-act]');
    if (a) {
      var aid = Number(a.getAttribute('data-a2-toast-act'));
      var found = toasts.filter(function (t) { return t.id === aid; })[0];
      if (found && found.onAction) found.onAction();
      toasts = toasts.filter(function (t) { return t.id !== aid; });
      renderToasts();
    }
  });

  window.Admin2Shell = {
    meReady: meReady,
    getMe: function () { return me; },
    canWrite: canWrite,
    // 권한 등급 코드(viewer·operator·owner)를 화면 표시용 한국어로 바꾼다.
    // 서버 쪽 같은 표는 api/admin_labels.py ROLE_KO — 두 곳의 값을 같게 둔다.
    roleKo: function (code) { return code ? (ROLE_KO[code] || code) : '로그인 필요'; },
    isKeepClick: function (target) { return !!(target && target.closest && target.closest('[data-keep]')); },
    toast: toast
  };
})();
