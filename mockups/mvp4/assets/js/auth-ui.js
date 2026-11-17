/* Optional customer authentication, isolated from the existing shell. */
(function () {
  'use strict';
  var P = window.PAI;
  if (!P || P.authUI) return;
  var state = null, loading = false, attached = false, errorShown = false;
  var errors = {
    cancelled: '로그인을 취소했습니다.',
    state_mismatch: '로그인 시간이 지났습니다. 다시 시도해 주세요.',
    attempt_expired: '로그인 시간이 지났습니다. 다시 시도해 주세요.',
    identity_revoked: '탈퇴한 로그인 정보입니다. 고객지원으로 문의해 주세요.',
    member_inactive: '이용이 제한된 회원입니다. 고객지원으로 문의해 주세요.',
    provider_failed: '로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.'
  };
  function request(path, body, guest) {
    try {
      var headers = { Accept: 'application/json' };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (guest) {
        try {
          // Same existing guest key as saved-quotes-client.js; never write member data.
          var key = window.localStorage.getItem('popcorn-mvp3-guest-access-v1');
          if (key && /^[A-Za-z0-9_-]{32,128}$/.test(key)) headers['X-Access-Key'] = key;
        } catch (ignore) {}
      }
      return window.fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: headers, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
        return r.json().catch(function () { return null; }).then(function (data) {
          if (!r.ok || !data) { var e = new Error('auth'); e.status = r.status; e.code = data && data.detail && data.detail.code; throw e; }
          return data;
        });
      });
    } catch (e) { return Promise.reject(e); }
  }
  function returnPath() {
    var q = new URLSearchParams(window.location.search);
    q.delete('login_error');
    var path = window.location.pathname + (q.toString() ? '?' + q.toString() : '');
    return path.indexOf('/mvp4/') === 0 && path.length <= 300 && path.indexOf('//') < 0 && path.indexOf('\\') < 0 ? path : '/mvp4/';
  }
  function start(provider) { window.location.href = '/api/auth/' + provider + '/start?return=' + encodeURIComponent(returnPath()); }
  function close(d) {
    if (!d) return;
    if (typeof d.close === 'function') d.close(); else d.removeAttribute('open');
    document.documentElement.classList.remove('dialog-is-open');
    if (d.returnFocus && document.contains(d.returnFocus)) d.returnFocus.focus();
  }
  function dialog(title, html, trigger) {
    var old = document.getElementById('auth-dialog');
    if (old) { close(old); old.remove(); }
    var menu = document.getElementById('site-menu');
    if (menu && menu.open) close(menu);
    var d = document.createElement('dialog');
    d.id = 'auth-dialog'; d.className = 'site-dialog auth-dialog';
    d.setAttribute('aria-labelledby', 'auth-title');
    d.innerHTML = '<div class="dialog-content stack"><div class="dialog-heading"><h2 id="auth-title">' + title + '</h2><button type="button" class="icon-button" data-auth-close aria-label="닫기">' + P.icon('x') + '</button></div>' + html + '</div>';
    document.body.appendChild(d); d.returnFocus = trigger;
    d.querySelector('[data-auth-close]').onclick = function () { close(d); };
    d.addEventListener('close', function () { document.documentElement.classList.remove('dialog-is-open'); if (trigger && document.contains(trigger)) trigger.focus(); });
    d.addEventListener('click', function (e) { if (e.target === d) close(d); });
    d.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); close(d); }
      if (e.key === 'Tab' && typeof d.showModal !== 'function') {
        var items = d.querySelectorAll('button:not(:disabled),a,input'), first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
    document.documentElement.classList.add('dialog-is-open');
    d.querySelector('button').focus(); return d;
  }
  function login(trigger) {
    if (!state) return;
    var labels = { kakao: '카카오 로그인', naver: '네이버 로그인', google: 'Google 계정으로 로그인' };
    var html = '<p>처음이시면 로그인 뒤 가입 동의 화면으로 이동합니다.</p><div class="auth-providers">';
    ['kakao', 'naver', 'google'].forEach(function (name) {
      if (state.providers.indexOf(name) >= 0) html += '<button type="button" class="btn auth-provider auth-' + name + '" data-provider="' + name + '"><img src="/mvp4/assets/icons/auth-' + name + '.svg" width="20" height="20" alt="">' + labels[name] + '</button>';
    });
    var d = dialog('간편로그인', html + '</div><p class="auth-policy"><a class="text-link" href="/mvp4/terms.html" target="_blank" rel="noopener">이용약관</a> · <a class="text-link" href="/mvp4/privacy.html" target="_blank" rel="noopener">개인정보처리방침</a></p>', trigger);
    d.querySelectorAll('[data-provider]').forEach(function (b) { b.onclick = function () { try { start(b.dataset.provider); } catch (ignore) {} }; });
  }
  function withdraw(trigger) {
    var d = dialog('회원 탈퇴', '<p>탈퇴하면 로그인 정보가 삭제되고 되돌릴 수 없습니다. 같은 방법으로 다시 가입하면 새 회원이 되며 이전 기록은 이어지지 않습니다.</p><label class="auth-check"><input type="checkbox"> 안내를 확인했습니다</label><p class="error" role="alert" hidden></p><div class="button-row"><button class="btn btn-outline" data-cancel>취소</button><button class="btn btn-primary" data-withdraw disabled>탈퇴</button></div>', trigger);
    var box = d.querySelector('input'), submit = d.querySelector('[data-withdraw]'), notice = d.querySelector('.error'), busy = false;
    box.onchange = function () { submit.disabled = busy || !box.checked; };
    d.querySelector('[data-cancel]').onclick = function () { close(d); };
    submit.onclick = function () {
      if (busy || !box.checked) return; busy = true; submit.disabled = true; notice.hidden = true;
      request('/api/auth/withdraw', {}).then(function (data) {
        if (data.ok !== true) throw new Error('withdraw');
        var done = dialog('회원 탈퇴', '<p role="status">탈퇴했습니다.</p><div class="button-row"><button type="button" class="btn btn-primary" data-home>확인</button></div>', null);
        var home = function () { window.location.href = '/mvp4/'; };
        done.querySelector('[data-home]').onclick = home;
        done.addEventListener('close', home);
      }).catch(function (e) {
        if (e.status === 401) { window.location.reload(); return; }
        notice.textContent = '탈퇴를 처리하지 못했습니다. 고객지원으로 문의해 주세요.'; notice.hidden = false;
      }).then(function () { busy = false; submit.disabled = !box.checked; });
    };
  }
  function account(trigger) {
    if (!state.me.authenticated) { login(trigger); return; }
    var d = dialog(P.h(state.me.member && state.me.member.nickname || '회원'), '<div class="button-row"><button type="button" class="btn btn-outline" data-signout>로그아웃</button></div><p class="error" role="alert" hidden></p><button type="button" class="auth-leave" data-leave>회원 탈퇴</button>', trigger);
    d.querySelector('[data-leave]').onclick = function () { withdraw(trigger); };
    var b = d.querySelector('[data-signout]');
    b.onclick = function () {
      b.disabled = true;
      request('/api/auth/signout', {}).then(function (data) {
        if (data.ok !== true) throw new Error('signout');
        try { window.sessionStorage.removeItem('pai-auth-attached'); } catch (ignore) {}
        window.location.reload();
      }).catch(function () { var n = d.querySelector('.error'); n.textContent = '로그아웃하지 못했습니다. 잠시 후 다시 시도해 주세요.'; n.hidden = false; b.disabled = false; });
    };
  }
  function render() {
    if (!state) return;
    var targets = [document.querySelector('.nh-tools') || document.querySelector('.header-actions'), document.querySelector('#site-menu .nh-menu-content') || document.querySelector('#site-menu .dialog-content')];
    targets.forEach(function (target, i) {
      if (!target || target.querySelector('[data-auth-entry]')) return;
      var b = document.createElement('button'); b.type = 'button'; b.className = i ? 'btn btn-outline auth-menu-entry' : 'icon-button auth-entry';
      b.setAttribute('data-auth-entry', ''); b.setAttribute('aria-haspopup', 'dialog');
      var name = state.me.authenticated ? (state.me.member && state.me.member.nickname || '회원') : '로그인';
      b.setAttribute('aria-label', name); b.title = name;
      b.innerHTML = i ? P.h(name) : P.icon('user') + '<span class="auth-entry-label">' + P.h(name) + '</span>';
      b.onclick = function () { try { account(b); } catch (ignore) {} };
      if (i) target.appendChild(b); else target.insertBefore(b, target.lastElementChild);
    });
  }
  function init() {
    try {
      if (state) { render(); return; }
      if (loading) return; loading = true;
      request('/api/auth/providers').then(function (data) {
        if (data.enabled !== true || !Array.isArray(data.providers)) return null;
        var providers = data.providers.filter(function (p) { return ['kakao', 'naver', 'google'].indexOf(p) >= 0; });
        if (!providers.length) return null;
        return request('/api/auth/me').then(function (me) {
          if (typeof me.authenticated !== 'boolean') return null;
          state = { providers: providers, me: me }; render();
          if (!me.authenticated) { try { window.sessionStorage.removeItem('pai-auth-attached'); } catch (ignore) {} }
          if (me.authenticated && !attached) {
            attached = true;
            try {
              var marker = me.auth_context && me.auth_context.session_context_id;
              if (typeof marker !== 'string' || !marker) throw new Error('missing context');
              if (window.sessionStorage.getItem('pai-auth-attached') === marker) return state;
              window.sessionStorage.setItem('pai-auth-attached', marker);
            } catch (ignore) {}
            request('/api/auth/attach-guest', {}, true).catch(function () {});
          }
          return state;
        });
      }).then(function () {
        if (!state || errorShown) return;
        var q = new URLSearchParams(window.location.search), code = q.get('login_error');
        if (!q.has('login_error')) return; errorShown = true; q.delete('login_error');
        window.history.replaceState(window.history.state, '', window.location.pathname + (q.toString() ? '?' + q.toString() : '') + window.location.hash);
        dialog('간편로그인', '<p role="alert">' + (Object.prototype.hasOwnProperty.call(errors, code) ? errors[code] : errors.provider_failed) + '</p>', document.querySelector('[data-auth-entry]'));
      }).catch(function () { state = null; });
    } catch (ignore) {}
  }
  P.authUI = { request: request, login: login, init: init, returnPath: returnPath };
  var bind = P.bindShell;
  P.bindShell = function () { var result = bind.apply(this, arguments); init(); return result; };
}());
