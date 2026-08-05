/* 관리자 인증 가드 (슬라이스 37) — 전 관리자 화면 공통.
 *
 * 화면마다 fetch 실패 시 처신이 다르다 — 더미로 폴백하는 화면(배지 '더미 데이터')이 있고,
 * 더미를 걷어내고 '—'만 남기는 화면(배지 '연결 안 됨')이 있다. 인증이 붙은 뒤로는 미로그인도
 * 그 경로에 걸리므로, **왜 값이 없는지**를 이 스크립트가 상단 띠로 밝히고(미로그인 /
 * 승인 대기 / 권한 부족) 로그인 화면으로 안내한다.
 * 로그인 상태면 우측 상단 프로필을 실제 운영자로 바꾸고 로그아웃을 연결한다.
 *
 * 단, **폴백을 걷어낸 화면에는 더미가 없다.** 그런 화면에서 "수치는 더미입니다"라고 말하면
 * 이 띠가 거짓말이 된다 — 사람 4명이 박혀 있던 표를 지운 operators.html이 첫 사례고,
 * 정적 행 5개를 걷어낸 대시보드(index.html · 슬라이스 101)가 그다음이다.
 * 그런 화면은 `<body data-dummy-fallback="none">`으로 표시하고, 여기서 문구를 바꾼다.
 * 표시가 없으면 예전 문구 그대로다(아직 더미로 폴백하는 화면이 다수 남아 있다).
 * **폴백을 걷어낼 때 이 표시를 함께 붙이지 않으면 띠만 거짓말로 남는다.**
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
      var noDummy = document.body.getAttribute('data-dummy-fallback') === 'none';
      banner('로그인하지 않은 상태입니다 — ' +
        (noDummy ? '이 화면은 <b>아무 값도 보여주지 않습니다</b>(더미로 채우지 않습니다). '
                 : '화면의 수치는 <b>실데이터가 아니라 더미</b>입니다. ') +
        '<a href="login.html" style="color:#fff;text-decoration:underline;">관리자 로그인</a>');
    })
    .catch(function () {
      // API 서버 자체가 없으면 목업 단독 열람 — 원래 설계된 더미 폴백이므로 조용히 둔다.
    });
})();
