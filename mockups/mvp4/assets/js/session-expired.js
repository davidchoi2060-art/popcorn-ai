/* 운영 미리보기 로그인 만료 안내 (2026-10-29 사장님 「응 고쳐줘」).
 *
 * 출시 전 운영 서버는 관리자로 로그인한 사람만 admin.popcornai.co.kr 의 /mvp4·/api 를 쓴다(nginx auth_request).
 * 관리자 로그인은 8시간이면 끝나는데(api/auth.py ABSOLUTE_HOURS), 끝나면 /api 요청이 「오픈 준비 중」 503 HTML 로
 * 바뀌어 상담 AI 가 아무 말 없이 응답을 멈춘 것처럼 보였다(10-29 18:00~18:09, 미리보기 인증 401 15회).
 * 미리보기 주소에서만 fetch 를 지켜보다가 /api 요청이 503 HTML 로 돌아오면 화면 위에 다시 로그인 안내를 한 번 띄운다.
 * 응답은 그대로 넘긴다 -- 각 화면의 실패 처리는 바뀌지 않는다. 다른 주소(개발 서버·출시 뒤 고객)에서는 아무것도 하지 않는다.
 */
(function () {
  'use strict';
  var HOST = 'admin.popcornai.co.kr', LOGIN = '/__preview/';
  if (location.hostname !== HOST || typeof window.fetch !== 'function' || window.__popcornSessionNotice) return;
  window.__popcornSessionNotice = true;
  var original = window.fetch, shown = false;
  function isApi(input) {
    var url = typeof input === 'string' ? input : input && input.url;
    try { return new URL(url, location.href).pathname.indexOf('/api/') === 0; } catch (e) { return false; }
  }
  function notice() {
    if (shown || !document.body) return;
    shown = true;
    var box = document.createElement('div');
    box.setAttribute('role', 'alert');
    box.setAttribute('data-preview-expired', '');
    box.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483001;display:flex;gap:12px;align-items:center;' +
      'width:max-content;max-width:calc(100% - 24px);padding:12px 16px;border-radius:12px;background:#152e48;color:#fff;font:600 14px/1.5 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25)';
    var text = document.createElement('span');
    text.textContent = '미리보기 로그인이 만료되었습니다. 다시 로그인하면 이어서 쓸 수 있습니다.';
    var link = document.createElement('a');
    link.href = LOGIN;
    link.textContent = '다시 로그인';
    link.style.cssText = 'flex-shrink:0;padding:6px 12px;border-radius:8px;background:#ffdf42;color:#141414;text-decoration:none;font-weight:800';
    box.appendChild(text);
    box.appendChild(link);
    document.body.appendChild(box);
  }
  window.fetch = function (input) {
    var api = isApi(input);
    return original.apply(this, arguments).then(function (res) {
      if (api && res && res.status === 503 && /^text\/html/i.test((res.headers && res.headers.get('content-type')) || '')) notice();
      return res;
    });
  };
}());
