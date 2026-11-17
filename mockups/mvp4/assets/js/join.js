(function () {
  'use strict';
  var P = window.PAI;
  if (!P || !P.authUI) return;
  P.pages.join = function () {
    return { html: '<div class="container"><section class="auth-join stack" data-join-root aria-live="polite"><p>화면을 불러오고 있습니다.</p></section></div>', mount: mount };
  };
  function mount() {
    try {
      var root = document.querySelector('[data-join-root]');
      if (!root) return;
      var api = P.authUI, required = ['terms', 'privacy', 'age14'];
      function unavailable(closed) {
        root.innerHTML = '<h1 class="section-title">' + (closed ? '지금은 회원가입을 받지 않습니다.' : '가입 대기 시간이 지났습니다. 다시 로그인해 주세요.') + '</h1><a class="btn btn-outline" href="/mvp4/">홈으로 이동</a>' + (closed ? '' : '<button class="btn btn-primary" data-restart>로그인 다시 시작</button>');
        var restart = root.querySelector('[data-restart]');
        if (restart) restart.onclick = function () { try { api.login(restart); } catch (ignore) {} };
      }
      // Closed/failed providers never reveal a join form or login button.
      api.request('/api/auth/providers').then(function (providers) {
        if (providers.enabled !== true) { unavailable(true); return; }
        return api.request('/api/auth/join/pending').then(function (pending) {
          if (required.some(function (key) { return !Array.isArray(pending.required) || pending.required.indexOf(key) < 0; })) { unavailable(false); return; }
          var names = { kakao: '카카오', naver: '네이버', google: 'Google' };
          root.innerHTML = '<h1 class="section-title">회원가입 동의</h1><div class="auth-identity"><p>' + (names[pending.provider] ? '<strong>' + P.h(names[pending.provider]) + '</strong> 계정으로 가입합니다.' : '간편로그인 계정으로 가입합니다.') + '</p><p class="auth-nickname">닉네임 ' + P.h(pending.nickname || '회원') + '</p></div><p>다른 로그인 방법으로 이미 가입하셨다면 그 방법으로 로그인해 주세요. 로그인 방법이 다르면 별도 회원으로 가입됩니다.</p><form class="stack" data-join-form><label class="auth-check"><input type="checkbox" data-all> 전체 동의</label><div class="auth-consents"><label class="auth-check"><input type="checkbox" name="terms"> [필수] 이용약관 <a class="text-link" href="terms.html" target="_blank" rel="noopener">본문</a></label><label class="auth-check"><input type="checkbox" name="privacy"> [필수] 개인정보 수집·이용 <a class="text-link" href="privacy.html" target="_blank" rel="noopener">본문</a></label><label class="auth-check"><input type="checkbox" name="age14"> [필수] 만 14세 이상</label></div><p class="error" role="alert" hidden></p><div class="button-row"><a class="btn btn-outline" href="/mvp4/">취소</a><button class="btn btn-primary" type="submit" disabled>가입</button></div></form>';
          var form = root.querySelector('form'), all = form.querySelector('[data-all]'), submit = form.querySelector('[type=submit]'), notice = form.querySelector('.error'), busy = false;
          function sync() {
            var count = required.filter(function (key) { return form.elements[key].checked; }).length;
            all.checked = count === 3; all.indeterminate = count > 0 && count < 3;
            submit.disabled = busy || count !== 3;
          }
          all.onchange = function () { required.forEach(function (key) { form.elements[key].checked = all.checked; }); sync(); };
          required.forEach(function (key) { form.elements[key].onchange = sync; });
          form.onsubmit = function (event) {
            event.preventDefault();
            if (busy || submit.disabled) return;
            busy = true; sync(); notice.hidden = true;
            var consents = {};
            required.forEach(function (key) { consents[key] = form.elements[key].checked; });
            api.request('/api/auth/join', { consents: consents }, true).then(function (data) {
              if (data.ok !== true) throw new Error('join');
              var path = data.return_path;
              window.location.href = typeof path === 'string' && path.indexOf('/mvp4/') === 0 && path.indexOf('//') < 0 && path.indexOf('\\') < 0 ? path : '/mvp4/';
            }).catch(function (e) {
              if (e.status === 409 && e.code === 'already_joined') { window.location.href = '/mvp4/'; return; }
              notice.textContent = e.status === 400 || (e.status === 422 && e.code === 'consent_required') ? '필수 동의 항목을 모두 선택해 주세요.' : '가입하지 못했습니다. 잠시 후 다시 시도해 주세요.';
              notice.hidden = false;
            }).then(function () { busy = false; sync(); });
          };
        }).catch(function (e) { unavailable(e.status === 503); });
      }).catch(function () { unavailable(true); });
    } catch (ignore) {}
  }
}());
