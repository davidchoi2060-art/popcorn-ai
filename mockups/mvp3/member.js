/* 고객 회원 -- 상단 로그인/마이페이지 · 로그인 창 · 로그인 예외 안내 (회원 로그인 시안 v1 ①②④, 2026-10-14 사장님 승인).
 *
 * 서버가 로그인을 켜지 않았으면(GET /api/auth/providers → enabled:false) 아무것도 그리지 않는다 -- 버튼이 보였다가
 * 503 이 나는 일이 없게. 켜져 있으면 상단 메뉴 끝에 「로그인」(로그인 전) 또는 「마이페이지」(로그인 후)를 붙인다.
 * 로그인은 같은 사이트의 /api/auth/{공급자}/start 로 이동할 뿐이고, 공급자 키·토큰은 브라우저에 오지 않는다.
 * 문구는 설계 docs/design/customer-social-login-v1.md 와 시안 검수(Codex 2026-10-13) 정본을 따른다.
 */
(function(root){'use strict';
  const PROVIDER = {
    google: {label: 'Google로 계속하기', cls: 'mb-google', mark: 'G'},
    kakao: {label: '카카오로 계속하기', cls: 'mb-kakao', mark: 'K'},
    naver: {label: '네이버로 계속하기', cls: 'mb-naver', mark: 'N'},
  };
  const ORDER = ['google', 'kakao', 'naver'];
  const ACCESS_KEY = 'popcorn-mvp3-guest-access-v1', KEY_RE = /^[A-Za-z0-9_-]{32,128}$/;
  const ATTACHED = 'popcorn-mvp3-member-attached-v1';
  // 로그인 예외 안내(시안 ④). 원인을 단정하지 않는다(Codex 시안 검수 2026-10-13).
  const BLOCKED = new Set(['identity_revoked', 'member_inactive']);

  function el(tag, attrs, ...children){
    const n = document.createElement(tag);
    for(const [k, v] of Object.entries(attrs || {})){
      if(v === null || v === undefined || v === false) continue;
      if(k === 'class') n.className = v; else if(k === 'text') n.textContent = v; else n.setAttribute(k, v === true ? '' : v);
    }
    for(const c of children) if(c) n.append(c);
    return n;
  }

  async function getJSON(path){
    const r = await fetch(path, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
    let data = null; try{ data = await r.json(); }catch{}
    return {status: r.status, data};
  }

  function returnPath(){
    const p = location.pathname + location.search.replace(/([?&])login_error=[^&]*&?/, '$1').replace(/[?&]$/, '') + location.hash;
    return p.startsWith('/mvp3/') ? p : '/mvp3/';
  }

  function dialog(title, body, {closeLabel = '닫기'} = {}){
    const d = el('dialog', {class: 'mb-dialog', 'aria-labelledby': 'mb-dialog-title'});
    const close = el('button', {type: 'button', class: 'mb-close', 'aria-label': closeLabel, text: '×'});
    close.addEventListener('click', () => d.close());
    d.append(el('div', {class: 'mb-dialog-head'}, el('h2', {id: 'mb-dialog-title', text: title}), close), body);
    d.addEventListener('close', () => d.remove());
    document.body.append(d);
    d.showModal();
    return d;
  }

  function openLogin(providers){
    const list = el('div', {class: 'mb-providers'});
    for(const key of ORDER){
      if(!providers.includes(key)) continue;
      const p = PROVIDER[key];
      const a = el('a', {class: 'mb-provider ' + p.cls, href: '/api/auth/' + key + '/start?return=' + encodeURIComponent(returnPath())},
        el('span', {class: 'mb-mark', 'aria-hidden': 'true', text: p.mark}), el('span', {text: p.label}));
      list.append(a);
    }
    const guest = el('button', {type: 'button', class: 'mb-guest', text: '비회원으로 계속 상담하기 ›'});
    const body = el('div', {}, el('p', {class: 'mb-sub', text: '내 견적과 문의를 이어 보세요.'}), list,
      el('div', {class: 'mb-or'}, el('span', {text: '또는'})), guest);
    const d = dialog('로그인', body);
    guest.addEventListener('click', () => d.close());
  }

  function openNotice(code, providers){
    const blocked = BLOCKED.has(code);
    const cancelled = code === 'cancelled';
    const title = blocked ? '현재 로그인할 수 없어요' : cancelled ? '로그인이 취소됐어요' : '로그인하지 못했어요';
    const text = blocked ? '계정 이용이 제한되어 로그인할 수 없어요. 궁금한 점이 있다면 상담으로 문의해 주세요.'
      : cancelled ? '다시 시도해 주세요. 비회원으로도 계속 상담할 수 있어요.' : '잠시 후 다시 시도해 주세요. 비회원으로는 계속 상담할 수 있어요.';
    const action = el('button', {type: 'button', class: blocked ? 'outline mb-wide' : 'primary mb-wide', text: blocked ? '상담으로 들어가기' : '다시 시도'});
    const d = dialog(title, el('div', {class: 'mb-notice' + (blocked ? ' is-blocked' : '')}, el('p', {text}), action));
    action.addEventListener('click', () => { d.close(); if(!blocked) openLogin(providers); });
  }

  function openMember(member){
    const name = (member && member.nickname) || '회원';
    const out = el('button', {type: 'button', class: 'outline mb-wide', text: '로그아웃'});
    const body = el('div', {class: 'mb-member'},
      el('p', {class: 'mb-hello'}, el('strong', {text: name}), document.createTextNode('님, 안녕하세요!')),
      el('a', {class: 'mb-row', href: 'index.html#saved', text: '내 견적'}),
      el('p', {class: 'muted', text: '주문·결제·배송은 팝콘PC 쇼핑몰에서 확인해요.'}), out);
    const d = dialog('마이페이지', body);
    out.addEventListener('click', async () => {
      out.disabled = true;
      try{ await fetch('/api/auth/signout', {method: 'POST', credentials: 'same-origin', cache: 'no-store'}); }catch{}
      try{ sessionStorage.removeItem(ATTACHED); }catch{}
      d.close(); location.reload();
    });
  }

  // 로그인 뒤 이 브라우저에 보관한 견적을 회원 기록에 붙인다(서버가 이미 다른 회원 것인지 본다). 한 탭 세션에 한 번.
  async function attachGuest(){
    let key = null, done = false;
    try{ done = sessionStorage.getItem(ATTACHED) === '1'; key = localStorage.getItem(ACCESS_KEY); }catch{}
    if(done) return;
    const headers = {};
    if(key && KEY_RE.test(key)) headers['X-Access-Key'] = key;
    try{
      const r = await fetch('/api/auth/attach-guest', {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers});
      if(r.ok) sessionStorage.setItem(ATTACHED, '1');
    }catch{}
  }

  // 상단 메뉴(nav) 안이 아니라 머리줄 끝에 둔다 -- 처음 화면(index)의 휴대폰 메뉴는 이미 세 개로 꽉 찼다.
  // 휴대폰 폭에서는 로고 옆 첫 줄에 남고 메뉴가 둘째 줄로 내려간다(member.css).
  function navButton(label, onClick, cls){
    const bar = document.querySelector('.topbar');
    if(!bar) return null;
    const b = el('button', {type: 'button', class: 'mb-nav ' + cls, 'data-member': cls, text: label});
    b.addEventListener('click', onClick);
    bar.append(b);
    return b;
  }

  async function start(){
    let providers = [];
    try{
      const r = await getJSON('/api/auth/providers');
      if(r.status !== 200 || !r.data || r.data.enabled !== true || !Array.isArray(r.data.providers)) return;
      providers = r.data.providers.filter(p => ORDER.includes(p));
      if(!providers.length) return;
    }catch{ return; }
    const params = new URLSearchParams(location.search);
    const err = params.get('login_error');
    if(err){
      params.delete('login_error');
      const q = params.toString();
      history.replaceState(history.state, '', location.pathname + (q ? '?' + q : '') + location.hash);
    }
    let me = null;
    try{ me = await getJSON('/api/auth/me'); }catch{}
    if(me && me.status === 200 && me.data && me.data.authenticated === true){
      navButton('마이페이지', () => openMember(me.data.member), 'mb-mypage');
      attachGuest();
    }else{
      navButton('로그인', () => openLogin(providers), 'mb-login');
      if(err) openNotice(err, providers);
    }
  }

  root.PopcornMember = {start, returnPath, PROVIDER};
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})(window);
