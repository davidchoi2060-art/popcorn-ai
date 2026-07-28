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

  function boot() {
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
