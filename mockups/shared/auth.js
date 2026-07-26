// 팝콘PC AI — 가입/로그인 모달 + 세션 + MY 플로팅 버튼 (A-10 회원 축)
//
// 슬라이스 38(LIVE): 세션의 원천은 **서버**다. `/api/auth/login`이 HttpOnly 쿠키를 주고
// `/api/my/*`는 그 세션으로만 열린다. localStorage는 화면 표시용 캐시일 뿐이며,
// **서버가 "세션 없다"고 하면 캐시를 지운다**(로그인처럼 보이는데 API는 401인 상태를 만들지 않는다).
// API가 아예 없으면(목업 단독 열람) 기존 로컬 mock 동작을 유지한다.
//
// **비밀번호를 저장하지 않는다** — 신원은 소셜 제공자가 확인한다(관리자 인증과 같은 원칙).
// 지금은 dev 어댑터라 입력한 이메일을 신원으로 신뢰한다 — **로컬 전용·공개 배포 차단 사유.**
(function(){
var KEY='popcorn-member';
function member(){try{return JSON.parse(localStorage.getItem(KEY)||'null');}catch(e){return null;}}
function save(m){localStorage.setItem(KEY,JSON.stringify(m));}
function clear(){localStorage.removeItem(KEY);}
function toast(m){var t=document.getElementById('pa-toast');if(!t){t=document.createElement('div');t.id='pa-toast';t.style.cssText='position:fixed;bottom:76px;left:50%;transform:translateX(-50%);background:#17171b;color:#fff;font-size:13.5px;font-weight:700;padding:12px 20px;border-radius:12px;z-index:99999;opacity:0;transition:.25s;font-family:Pretendard,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.3);';document.body.appendChild(t);}t.textContent=m;t.style.opacity='1';clearTimeout(t._x);t._x=setTimeout(function(){t.style.opacity='0';},2400);}

// 서버 로그인 — 성공 시 캐시 동기화. API 부재는 null을 돌려 로컬 mock으로 폴백시킨다.
function apiLogin(email,nick,provider){
 return fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({email:email,nickname:nick||null,provider:provider||'dev'})})
  .then(function(r){return r.json().then(function(d){return {ok:r.ok,d:d};});})
  .catch(function(){return null;});
}

function close(){var ov=document.getElementById('pa-ov');if(ov)ov.remove();}
function open(mode,after){
 close();mode=mode||'login';
 var ov=document.createElement('div');ov.id='pa-ov';
 ov.style.cssText='position:fixed;inset:0;z-index:99990;background:rgba(23,23,27,.55);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;font-family:Pretendard,-apple-system,sans-serif;padding:16px;';
 ov.innerHTML=''
 +'<div style="width:min(400px,94vw);background:#fff;border-radius:22px;padding:28px 26px;box-shadow:0 24px 70px rgba(0,0,0,.35);box-sizing:border-box;">'
 +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
 +'<div style="font-size:17px;font-weight:900;color:#17171b;">팝콘PC <span style="color:#2b5fd9;">AI</span></div>'
 +'<button id="pa-x" style="border:none;background:#f4f2ec;width:30px;height:30px;border-radius:9px;cursor:pointer;font-weight:800;color:#6b6b73;">✕</button></div>'
 +'<p style="margin:0 0 16px;font-size:12.5px;color:#8a8578;font-weight:600;line-height:1.5;">가입하면 <b style="color:#3a3a40;">상담 내역·관심 부품·견적</b>이 저장되고, 그때 가격 그대로 다시 볼 수 있어요.</p>'
 +'<div style="display:flex;background:#f4f2ec;border-radius:11px;padding:3px;margin-bottom:16px;">'
 +'<button data-tab="login" style="flex:1;padding:9px;border:none;border-radius:8px;font-size:13.5px;font-weight:800;cursor:pointer;font-family:inherit;">로그인</button>'
 +'<button data-tab="join" style="flex:1;padding:9px;border:none;border-radius:8px;font-size:13.5px;font-weight:800;cursor:pointer;font-family:inherit;">회원가입</button></div>'
 +'<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px;">'
 +'<button data-social="카카오" style="width:100%;padding:12px;border:none;background:#FEE500;border-radius:11px;font-size:13.5px;font-weight:800;color:#191919;cursor:pointer;font-family:inherit;">카카오로 3초 만에 시작</button>'
 +'<button data-social="네이버" style="width:100%;padding:12px;border:none;background:#03C75A;border-radius:11px;font-size:13.5px;font-weight:800;color:#fff;cursor:pointer;font-family:inherit;">네이버로 시작</button></div>'
 +'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;color:#c9c5bd;font-size:11.5px;font-weight:700;"><span style="flex:1;height:1px;background:#ece9e3;"></span>또는 이메일로<span style="flex:1;height:1px;background:#ece9e3;"></span></div>'
 +'<div id="pa-form" style="display:flex;flex-direction:column;gap:9px;">'
 +'<input id="pa-nick" placeholder="닉네임" style="display:none;padding:12px 14px;border:1.5px solid #e6e2da;border-radius:11px;font-size:14px;font-family:inherit;outline:none;">'
 +'<input id="pa-email" type="email" placeholder="이메일" style="padding:12px 14px;border:1.5px solid #e6e2da;border-radius:11px;font-size:14px;font-family:inherit;outline:none;">'
 +'<p style="margin:0;font-size:11.5px;color:#a29d92;font-weight:700;line-height:1.5;">비밀번호를 만들지 않습니다 — 본인 확인은 <b style="color:#8a8578;">카카오·네이버 계정</b>이 합니다.</p>'
 +'<p id="pa-err" style="margin:0;font-size:12px;color:#b31b25;font-weight:700;min-height:14px;"></p>'
 +'<button id="pa-go" style="width:100%;padding:13px;border:none;background:#2b5fd9;border-radius:11px;font-size:14.5px;font-weight:800;color:#fff;cursor:pointer;font-family:inherit;">로그인</button>'
 +'<p id="pa-terms" style="display:none;margin:2px 0 0;font-size:11px;color:#a29d92;line-height:1.5;">가입 시 <a href="#!" style="color:#8a8578;">이용약관</a>·<a href="#!" style="color:#8a8578;">개인정보 처리방침</a>에 동의합니다. 결제·배송 정보는 주문 시점에만 수집합니다.</p>'
 +'</div></div>';
 document.body.appendChild(ov);
 var cur=mode;
 function paint(){
  ov.querySelectorAll('[data-tab]').forEach(function(b){var on=b.dataset.tab===cur;b.style.background=on?'#17171b':'transparent';b.style.color=on?'#fff':'#6b6b73';});
  ov.querySelector('#pa-nick').style.display=cur==='join'?'block':'none';
  ov.querySelector('#pa-terms').style.display=cur==='join'?'block':'none';
  ov.querySelector('#pa-go').textContent=cur==='join'?'가입하고 시작하기':'로그인';
 }
 ov.querySelectorAll('[data-tab]').forEach(function(b){b.onclick=function(){cur=b.dataset.tab;paint();};});

 // 소셜 — 앱 등록 전이라 신원 확인을 이메일로 대체한다(같은 흐름을 검증하기 위해).
 ov.querySelectorAll('[data-social]').forEach(function(b){b.onclick=function(){
  var via=b.dataset.social, em=ov.querySelector('#pa-email').value.trim();
  var err=ov.querySelector('#pa-err');
  if(!em||em.indexOf('@')<0){
   err.textContent=via+' 로그인은 앱 등록 후 동작합니다 — 지금은 이메일로 같은 흐름을 확인합니다.';
   ov.querySelector('#pa-email').focus();return;
  }
  finish(em, ov.querySelector('#pa-nick').value.trim()||(via+' 사용자'), via, err);
 };});

 ov.querySelector('#pa-go').onclick=function(){
  var em=ov.querySelector('#pa-email').value.trim(),nk=ov.querySelector('#pa-nick').value.trim();
  var err=ov.querySelector('#pa-err');
  if(!em||em.indexOf('@')<0){err.textContent='이메일을 확인해 주세요.';return;}
  if(cur==='join'&&!nk){err.textContent='닉네임을 입력해 주세요.';return;}
  finish(em, cur==='join'?nk:(em.split('@')[0]), '이메일', err);
 };

 function finish(em,nick,via,err){
  apiLogin(em,nick,via).then(function(res){
   if(res && !res.ok){ err.textContent=res.d.detail||'로그인할 수 없습니다.'; return; }
   if(res){    // 서버 세션 확정 — 캐시는 서버가 준 값으로
    var m=res.d.member;
    save({nick:m.nickname,email:m.email,via:via,live:true});
    close();toast(res.d.message||'환영해요!');refreshFab();if(after)after(member());
   } else {    // API 부재 = 목업 단독 열람 — 기존 로컬 mock 유지
    save({nick:nick,email:em,via:via,live:false});
    close();toast(via+' 계정으로 시작합니다 (목업)');refreshFab();if(after)after(member());
   }
  });
 }
 ov.querySelector('#pa-x').onclick=close;
 ov.addEventListener('click',function(e){if(e.target===ov)close();});
 paint();ov.querySelector(cur==='join'?'#pa-nick':'#pa-email').focus();
}

function logout(){
 fetch('/api/auth/logout',{method:'POST'}).catch(function(){})
  .then(function(){clear();toast('로그아웃했습니다');refreshFab();
   if(location.pathname.indexOf('my-')>-1)location.href='main-landing.html';});
}

// 서버 세션과 캐시를 맞춘다 — 로그인처럼 보이는데 API는 401인 상태를 만들지 않는다.
function sync(){
 return fetch('/api/auth/me').then(function(r){return r.json();}).then(function(d){
  if(d.authenticated){
   var m=d.member;save({nick:m.nickname,email:m.email,via:m.via,live:true});
  } else if(member()){
   clear();      // 서버가 세션 없다고 한다 — 만료·로그아웃. 표시도 로그아웃으로 맞춘다.
  }
  refreshFab();
  // MY 화면은 로그인이 전제다 — 미로그인으로 들어왔으면 더미를 실데이터처럼 두지 않고
  // 로그인부터 요구한다(서버가 명시적으로 "세션 없음"이라고 답한 경우에만).
  if(!d.authenticated && location.pathname.indexOf('/my-')>-1) expired();
  return d.authenticated;
 }).catch(function(){refreshFab();return null;});   // API 부재 — 캐시 그대로(목업 단독)
}

// MY 플로팅 버튼 (우하단 — 허브 FAB는 좌하단)
function refreshFab(){
 var f=document.getElementById('pa-fab');
 if(location.pathname.indexOf('my-page')>-1){if(f)f.remove();return;}
 if(!f){f=document.createElement('a');f.id='pa-fab';
  f.style.cssText='position:fixed;right:18px;bottom:18px;z-index:80;display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:999px;background:rgba(23,23,27,.82);color:#fff;font-size:12.5px;font-weight:800;text-decoration:none;font-family:Pretendard,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.22);backdrop-filter:blur(4px);cursor:pointer;';
  document.body.appendChild(f);}
 var m=member();
 if(m){f.innerHTML='<span style="width:20px;height:20px;border-radius:50%;background:#2b5fd9;display:inline-flex;align-items:center;justify-content:center;font-size:11px;">'+(m.nick||'?').charAt(0)+'</span>마이페이지';f.href='my-page.html';f.onclick=null;}
 else{f.textContent='로그인 · 가입';f.href='#!';f.onclick=function(e){e.preventDefault();open('login');};}
}
// 세션 만료·미로그인으로 회원 API가 401을 준 경우 — 더미를 실데이터처럼 두지 않고
// 캐시를 지우고 로그인 모달을 띄운다(화면은 "로그인 필요" 상태로 정직하게 되돌아간다).
function expired(){
 var had=member();clear();refreshFab();
 toast(had?'로그인이 만료됐습니다 — 다시 로그인해 주세요':'로그인이 필요합니다');
 setTimeout(function(){open('login',function(){location.reload();});},600);
}

window.popcornAuth={open:open,member:member,logout:logout,toast:toast,sync:sync,expired:expired};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sync);else sync();
})();
