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

  if (lnb) {
    lnb.addEventListener('click', function (ev) {
      var toggle = ev.target.closest('[data-action="toggle-lnb"]');
      if (toggle) { toggleCollapse(); return; }
      var grp = ev.target.closest('[data-action="lnb-group"]');
      if (grp) { toggleGroup(grp); }
    });
    initLnb();
  }

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
    isKeepClick: function (target) { return !!(target && target.closest && target.closest('[data-keep]')); },
    toast: toast
  };
})();
