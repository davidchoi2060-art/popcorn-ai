/* 가입 동의 (회원 로그인 시안 v1 ③, 2026-10-14 사장님 승인) -- POST /api/auth/join.
 * 필수 3개(이용약관 · 개인정보 수집·이용 · 만 14세 이상)만 받는다. 마케팅 수신은 오픈 범위에서 뺐다(설계 D8).
 * 동의 전 신원은 서버에만 있다(10분 · 한 번용 쿠키). 이 화면은 공급자 이름과 닉네임 기본값만 받는다.
 */
(function(){'use strict';
  const NAME = {google: 'Google', kakao: '카카오', naver: '네이버'};
  const ERR = {
    consent_required: '필수 항목에 모두 동의해 주세요.',
    join_expired: '시간이 지나 다시 로그인이 필요해요.',
    already_joined: '이미 가입된 계정이에요. 로그인해 주세요.',
    auth_unavailable: '지금은 로그인을 이용할 수 없어요. 비회원으로 계속 상담할 수 있어요.',
  };
  const ACCESS_KEY = 'popcorn-mvp3-guest-access-v1', KEY_RE = /^[A-Za-z0-9_-]{32,128}$/;
  const $ = id => document.getElementById(id);

  function codeOf(data){ const d = data && data.detail; return (d && typeof d === 'object' && d.code) || ''; }

  function expired(){ $('mb-join').hidden = true; $('mb-expired').hidden = false; $('mb-join-sub').hidden = true; }

  async function start(){
    const form = $('mb-join'), boxes = [...form.querySelectorAll('input[data-consent]')], all = $('mb-all');
    const submit = $('mb-submit'), error = $('mb-error');
    let info;
    try{
      const r = await fetch('/api/auth/join/pending', {credentials: 'same-origin', cache: 'no-store'});
      info = await r.json().catch(() => null);
      if(!r.ok){ if(codeOf(info) === 'auth_unavailable'){ $('mb-join-sub').textContent = ERR.auth_unavailable; return; } return expired(); }
    }catch{ return expired(); }
    if(NAME[info.provider]) $('mb-join-sub').textContent = NAME[info.provider] + ' 계정으로 가입해요. 아래 내용을 확인해 주세요.';
    if(typeof info.nickname === 'string') $('mb-nickname').value = info.nickname.slice(0, 100);
    form.hidden = false;
    const sync = () => {
      const n = boxes.filter(b => b.checked).length;
      all.checked = n === boxes.length; all.indeterminate = n > 0 && n < boxes.length;
      submit.disabled = n !== boxes.length;
    };
    all.addEventListener('change', () => { boxes.forEach(b => { b.checked = all.checked; }); sync(); });
    boxes.forEach(b => b.addEventListener('change', sync));
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if(submit.disabled) return;
      submit.disabled = true; error.hidden = true;
      const consents = Object.fromEntries(boxes.map(b => [b.dataset.consent, b.checked]));
      const headers = {'Content-Type': 'application/json'};
      try{ const k = localStorage.getItem(ACCESS_KEY); if(k && KEY_RE.test(k)) headers['X-Access-Key'] = k; }catch{}
      try{
        const r = await fetch('/api/auth/join', {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers,
          body: JSON.stringify({consents, nickname: $('mb-nickname').value.trim() || null})});
        const data = await r.json().catch(() => null);
        if(r.ok && data && data.ok){
          try{ sessionStorage.setItem('popcorn-mvp3-member-attached-v1', '1'); }catch{}
          location.replace(typeof data.return_path === 'string' && data.return_path.startsWith('/mvp3/') ? data.return_path : 'index.html');
          return;
        }
        const code = codeOf(data);
        if(code === 'join_expired') return expired();
        error.textContent = ERR[code] || '가입하지 못했어요. 잠시 후 다시 시도해 주세요.';
      }catch{ error.textContent = '가입하지 못했어요. 연결 상태를 확인해 주세요.'; }
      error.hidden = false; sync();
    });
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
