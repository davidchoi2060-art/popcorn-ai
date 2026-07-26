/* 관리자 인증 가드 (슬라이스 37) — 전 관리자 화면 공통.
 *
 * 관리자 화면들은 각자 fetch 실패 시 더미로 폴백한다(배지 '더미 데이터'). 인증이 붙은 뒤로는
 * 미로그인도 그 폴백에 걸리므로, **왜 더미인지**를 화면 스스로 말해야 한다 — 이 스크립트가
 * 상단 띠로 사유(미로그인 / 승인 대기 / 권한 부족)를 밝히고 로그인 화면으로 안내한다.
 * 로그인 상태면 우측 상단 프로필을 실제 운영자로 바꾸고 로그아웃을 연결한다.
 */
(function () {
  if (location.pathname.indexOf('/admin/login.html') >= 0) return;

  var ROLE_KO = { viewer: '조회', operator: '운영자', owner: '관리자' };

  function banner(html, tone) {
    var el = document.createElement('div');
    el.id = '__authBanner';
    el.setAttribute('role', 'status');
    el.style.cssText =
      'position:fixed;top:0;left:0;right:0;z-index:2000;padding:9px 16px;font-size:13px;' +
      'font-weight:600;text-align:center;color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.18);' +
      'background:' + (tone === 'warn' ? '#8a5b00' : '#b31b25') + ';';
    el.innerHTML = html;
    document.body.appendChild(el);
    document.body.style.paddingTop = '38px';
  }

  function fillProfile(op) {
    document.querySelectorAll('.dropdown-profile h6').forEach(function (h) {
      h.textContent = op.name + ' · ' + (ROLE_KO[op.role] || op.role);
    });
    document.querySelectorAll('.dropdown-profile a').forEach(function (a) {
      if ((a.textContent || '').indexOf('로그아웃') >= 0) {
        a.setAttribute('href', '#');
        a.addEventListener('click', function (e) {
          e.preventDefault();
          fetch('/api/admin/auth/logout', { method: 'POST' })
            .then(function () { location.href = 'login.html'; })
            .catch(function () { location.href = 'login.html'; });
        });
      }
    });
    // 권한이 낮으면 쓰기 화면에서 403이 난다 — 미리 알린다(색 대신 텍스트로 명시).
    if (op.role === 'viewer') {
      banner('조회 권한입니다 — 확정·승인·발행 같은 <b>쓰기 작업은 거부</b>됩니다(권한 상향은 관리자에게 요청).', 'warn');
    }
  }

  fetch('/api/admin/auth/me')
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.authenticated) { fillProfile(d.operator); return; }
      banner('로그인하지 않은 상태입니다 — 화면의 수치는 <b>실데이터가 아니라 더미</b>입니다. ' +
        '<a href="login.html" style="color:#fff;text-decoration:underline;">관리자 로그인</a>');
    })
    .catch(function () {
      // API 서버 자체가 없으면 목업 단독 열람 — 원래 설계된 더미 폴백이므로 조용히 둔다.
    });
})();
