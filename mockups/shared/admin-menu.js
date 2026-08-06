/* 좌측 메뉴를 기본으로 모두 펼치고, 운영자가 접은 것은 접힌 채로 둔다 (슬라이스 63).
 *
 * 원래 마크업은 `data-bs-parent="#navbarVerticalCollapse"`가 붙은 **아코디언**이었다.
 * 하나를 열면 나머지가 닫히므로 "상품"을 보다가 "가격"을 열면 상품이 접혔다.
 * 운영자는 여러 그룹을 오가며 일하는데, 매번 다시 펼쳐야 했다.
 *
 * 그래서 두 가지를 한다:
 *   ① 아코디언 해제 — 그룹끼리 서로 닫지 않는다
 *   ② 접힘/펼침 상태를 기억 — 저장된 게 없으면 **펼침이 기본**
 *
 * 기본을 펼침으로 두는 이유: 관리자 화면이 31개다. 접혀 있으면 무엇이 있는지 모른다.
 */
(function () {
  var KEY = 'popcorn-admin-menu';   // { 그룹id: true(펼침) | false(접힘) }

  function state() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; }
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }

  function toggleOf(id) {
    return document.querySelector('[data-bs-toggle="collapse"][href="#' + id + '"]')
      || document.querySelector('[data-bs-toggle="collapse"][data-bs-target="#' + id + '"]');
  }

  /* ── 메뉴를 **데이터에서 그린다** (2026-08-05) ──────────────────────
   *
   * 예전에는 이 마크업이 36화면에 각각 박혀 있었다(672KB). 손으로 맞추다 보니
   * 이미 갈라져서, `ai-cost` 에는 '운영 전환 설정'이 · `policy-weights` 에는
   * '용도 하한'이 **빠져 있었다** — 그 화면에서는 갈 길이 아예 없었다.
   * 이제 `admin-menu-data.js` 한 곳이 원천이고 여기서 그린다.
   *
   * 마크업은 Phoenix 규약 그대로다(클래스·collapse id·화살표 아이콘). 바꾸면
   * 테마 CSS 와 어긋나므로 **모양을 바꾸지 않는다** — 옮기기만 한다.
   */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function here() {
    var f = (location.pathname.split('/').pop() || 'index.html');
    return f || 'index.html';
  }

  function itemHTML(it, cur) {
    var on = (it.href === cur) ? ' active' : '';
    return '<li class="nav-item"><a class="nav-link' + on + '" href="' + esc(it.href) + '">'
      + '<div class="d-flex align-items-center">'
      + '<span class="nav-link-icon me-2" style="width:16px;height:16px;display:inline-flex;">'
      + '<span data-feather="' + esc(it.icon) + '" style="width:16px;height:16px;"></span></span>'
      + '<span class="nav-link-text">' + esc(it.label) + '</span>'
      + (it.badge ? '<span class="badge badge-phoenix badge-phoenix-warning ms-2">'
                    + esc(it.badge) + '</span>' : '')
      + '</div></a></li>';
  }

  function render() {
    var root = document.getElementById('navbarVerticalNav');
    var data = window.POPCORN_ADMIN_MENU;
    // 이미 마크업이 있으면(옛 화면) 손대지 않는다 — 섞어서 두 벌이 되는 게 최악이다
    if (!root || !data || root.children.length) return;

    var cur = here(), out = [];
    data.forEach(function (g) {
      if (g.section) {
        out.push('<li class="nav-item"><p class="navbar-vertical-label">' + esc(g.section)
                 + '</p><hr class="navbar-vertical-line"/></li>');
        return;
      }
      if (!g.items) {                                   // 단독 항목
        var on = (g.href === cur) ? ' active' : '';
        out.push('<li class="nav-item"><div class="nav-item-wrapper">'
          + '<a class="nav-link label-1' + on + '" href="' + esc(g.href) + '">'
          + '<div class="d-flex align-items-center"><span class="nav-link-icon">'
          + '<span data-feather="' + esc(g.icon) + '"></span></span>'
          + '<span class="nav-link-text">' + esc(g.label) + '</span></div></a></div></li>');
        return;
      }
      var mine = g.items.some(function (i) { return i.href === cur; });
      out.push('<li class="nav-item"><div class="nav-item-wrapper">'
        + '<a class="nav-link dropdown-indicator label-1' + (mine ? ' active' : '')
        + '" href="#' + esc(g.id) + '" role="button" data-bs-toggle="collapse"'
        + ' aria-expanded="' + (mine ? 'true' : 'false') + '" aria-controls="' + esc(g.id) + '">'
        + '<div class="d-flex align-items-center">'
        + '<div class="dropdown-indicator-icon-wrapper">'
        + '<span class="fas fa-caret-right dropdown-indicator-icon"></span></div>'
        + '<span class="nav-link-icon"><span data-feather="' + esc(g.icon) + '"></span></span>'
        + '<span class="nav-link-text">' + esc(g.label) + '</span></div></a>'
        + '<div class="parent-wrapper label-1">'
        + '<ul class="nav collapse parent' + (mine ? ' show' : '') + '" id="' + esc(g.id) + '">'
        + g.items.map(function (i) { return itemHTML(i, cur); }).join('')
        + '</ul></div></div></li>');
    });
    root.innerHTML = out.join('');
  }

  function boot() {
    render();
    var groups = document.querySelectorAll('.navbar-vertical .collapse.parent[id]');
    if (!groups.length) return;
    var s = state();

    [].forEach.call(groups, function (el) {
      // ① 아코디언 해제. 이게 남아 있으면 아래에서 아무리 펼쳐도 하나만 남는다.
      el.removeAttribute('data-bs-parent');

      // ② 저장된 상태가 있으면 그대로, 없으면 펼침
      var open = Object.prototype.hasOwnProperty.call(s, el.id) ? !!s[el.id] : true;
      el.classList.toggle('show', open);

      var tog = toggleOf(el.id);
      if (tog) {
        // 화살표 아이콘과 스타일이 이 두 가지를 본다 — 클래스만 바꾸면 아이콘이 어긋난다
        tog.setAttribute('aria-expanded', open ? 'true' : 'false');
        tog.classList.toggle('collapsed', !open);
      }

      // 운영자가 직접 접거나 편 것은 그대로 기억한다(다음 화면·다음 접속에도 유지)
      el.addEventListener('shown.bs.collapse', function () {
        var x = state(); x[el.id] = true; save(x);
      });
      el.addEventListener('hidden.bs.collapse', function () {
        var x = state(); x[el.id] = false; save(x);
      });
    });
  }

  /* 그리는 시점이 중요하다.
   *
   * 이 파일은 문서 끝에서 로드되므로 `#navbarVerticalNav` 는 **이미 파싱돼 있다.**
   * 그래서 DOMContentLoaded 를 기다리지 않고 **지금 바로** 그린다 —
   * `feather.replace()`(phoenix docReady)와 `su-icons`(그 뒤)는 아직 돌지 않았고,
   * 우리가 넣은 `data-feather` 스팬을 그들이 이어서 아이콘으로 바꿔 준다.
   * 기다렸다가 그리면 **아이콘이 하나도 안 붙는다**(빈 스팬만 남는다).
   *
   * 혹시 이 스크립트가 <head> 로 옮겨져 노드가 아직 없다면 그때는 문서 완료 후에 그린다.
   */
  render();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
