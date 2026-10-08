// 팝콘PC AI — 가입/로그인 모달 + 세션 + MY 플로팅 버튼 (A-10 회원 축)
//
// 서버 /me의 확인된 응답만 현재 화면의 회원 상태로 사용한다.
// localStorage, 입력 이메일, 통신 실패는 인증 증거가 아니다. 목업 로그인은 없다.
// 이 소비자는 본인 확인 발급기를 구현하지 않으며 guest 주문/견적 키를 사용하지 않는다.
(function(){
var KEY='popcorn-member';
var confirmed=null, phase='checking', availability='unknown', generation=0, modalVersion=0, loggingOut=false;
var listeners=[], notificationVersion=0, channel=null, suspended=false, exhausted=false, refreshAfterLogout=false;
var INVALIDATION_KEY='popcorn-auth-invalidation-v2', INVALIDATION_VALUE='invalidate-v2';
var READY='회원 본인 확인 기능을 준비 중입니다. 현재 로그인·가입을 이용할 수 없습니다. 상담·추천은 로그인 없이 이용할 수 있습니다.';
var FAILED='회원 상태를 확인하지 못했습니다. 다시 확인해 주세요. 상담·추천은 로그인 없이 이용할 수 있습니다.';
var notice='로그인 상태를 확인하고 있습니다.';
// Approved component typography. Keep this scoped to the existing auth UI.
var LEGIBILITY_CSS=
 '#pa-ov{font-size:16px;line-height:1.55;}\n'+
 '#pa-ov>div{max-height:calc(100vh - 32px);max-height:calc(100dvh - 32px);overflow-y:auto;overscroll-behavior:contain;}\n'+
 '#pa-ov p{font-size:14px!important;line-height:1.6!important;color:#625d54!important;word-break:keep-all;overflow-wrap:break-word;}\n'+
 '#pa-ov #pa-note{font-size:16px!important;line-height:1.55!important;color:#4e4b44!important;}\n'+
 '#pa-ov #pa-err{font-size:16px!important;color:#b31b25!important;}\n'+
 '#pa-ov button,#pa-ov input{font-size:16px!important;line-height:1.4;}\n'+
 '#pa-ov input:disabled{opacity:1;color:#625d54;-webkit-text-fill-color:#625d54;}\n'+
 '#pa-ov input::placeholder{color:#706b61;opacity:1;}\n'+
 '#pa-ov [data-social="네이버"]{color:#073c21!important;}\n'+
 '#pa-ov>div>div:nth-child(5){font-size:14px!important;color:#706b61!important;}\n'+
 '#pa-ov :is(button,input):focus-visible{outline:3px solid #446fd8;outline-offset:3px;}\n'+
 '#pa-fab{font-size:14px!important;}\n'+
 '#pa-toast{font-size:16px!important;line-height:1.55;max-width:calc(100vw - 32px);}\n';
if(!document.getElementById('pa-legibility')){
 var style=document.createElement('style');style.id='pa-legibility';style.textContent=LEGIBILITY_CSS;
 (document.head||document.documentElement).appendChild(style);
}
function object(v){return !!v&&typeof v==='object'&&!Array.isArray(v);}
function fields(v,names){
 return object(v)&&Object.keys(v).length===names.length&&names.every(function(k){return Object.prototype.hasOwnProperty.call(v,k);});
}
function text(v,max){return typeof v==='string'&&v.trim()&&v.length<=max&&!/[<>\x00-\x1f\x7f]/.test(v);}
function decimal(v){
 return typeof v==='string'&&/^[1-9][0-9]{0,18}$/.test(v)&&(v.length<19||v<='9223372036854775807');
}
function uuid(v){return typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);}
function identity(m,context){
 if(!fields(m,['member_id','nickname','email','via'])||!decimal(m.member_id)||!text(m.nickname,120)||
    !(m.email===null||(text(m.email,254)&&/^[^\s@]+@[^\s@]+$/.test(m.email)))||
    typeof m.via!=='string'||['kakao','naver','google','email'].indexOf(m.via)<0||
    !fields(context,['member_id','session_context_id','principal_revision'])||
    context.member_id!==m.member_id||!uuid(context.session_context_id)||!decimal(context.principal_revision))return null;
 return {id:m.member_id,nick:m.nickname,email:m.email,via:m.via,
  context:{member_id:context.member_id,session_context_id:context.session_context_id,principal_revision:context.principal_revision}};
}
function member(){return confirmed?{nick:confirmed.nick,email:confirmed.email,via:confirmed.via,live:true}:null;}
function clear(){confirmed=null;try{localStorage.removeItem(KEY);}catch(e){}}
function save(m){confirmed=m;try{localStorage.setItem(KEY,JSON.stringify(member()));}catch(e){}}
function getSnapshot(){
 var m=confirmed;
 return Object.freeze({epoch:generation,phase:phase,
  member:m?Object.freeze({member_id:m.id,nickname:m.nick,email:m.email,via:m.via}):null,
  auth_context:m?Object.freeze({member_id:m.context.member_id,session_context_id:m.context.session_context_id,
   principal_revision:m.context.principal_revision}):null});
}
function deliver(entry){
 if(!entry.active||entry.running)return;
 entry.running=true;
 try{entry.listener(getSnapshot());}catch(e){}finally{entry.running=false;}
}
function notify(){
 var version=++notificationVersion,list=listeners.slice();
 for(var i=0;i<list.length&&version===notificationVersion;i++)deliver(list[i]);
}
function subscribe(listener){
 if(typeof listener!=='function')throw new TypeError('listener must be a function');
 var entry={listener:listener,active:true,running:false};listeners.push(entry);deliver(entry);
 return function(){if(!entry.active)return;entry.active=false;var i=listeners.indexOf(entry);if(i>=0)listeners.splice(i,1);};
}
function unavailable(d){
 if(!object(d))return false;
 var detail=object(d.detail)?d.detail:null;
 return d.error==='auth_unavailable'||d.code==='auth_unavailable'||
  !!(detail&&(detail.error==='auth_unavailable'||detail.code==='auth_unavailable'))||
  (typeof d.note==='string'&&(d.note.indexOf('회원 본인 확인 기능을 준비 중')>-1||d.note.indexOf('현재 로그인·가입을 이용할 수 없습니다')>-1));
}
function update(next,message,m){
 clear();phase=next;notice=message;if(m)save(m);
 notify();
 // A subscriber may synchronously start another transition.
 refreshFab();var ov=document.getElementById('pa-ov');if(ov&&ov._paint)ov._paint();
}
function broadcast(){
 var sent=false;
 if(channel){try{channel.postMessage({type:'invalidate',auth_version:2});sent=true;}catch(e){}}
 if(!sent){try{localStorage.setItem(INVALIDATION_KEY,INVALIDATION_VALUE);localStorage.removeItem(INVALIDATION_KEY);}catch(e){}}
}
function begin(next,message,share){
 if(generation>=Number.MAX_SAFE_INTEGER){exhausted=true;update('error',FAILED);return null;}
 var turn=++generation;update(next,message);if(share)broadcast();return turn;
}
clear();
function toast(m){var t=document.getElementById('pa-toast');if(!t){t=document.createElement('div');t.id='pa-toast';t.style.cssText='position:fixed;bottom:76px;left:50%;transform:translateX(-50%);background:#17171b;color:#fff;font-size:13.5px;font-weight:700;padding:12px 20px;border-radius:12px;z-index:99999;opacity:0;transition:.25s;font-family:var(--font);box-shadow:0 10px 30px rgba(0,0,0,.3);';document.body.appendChild(t);}t.textContent=m;t.style.opacity='1';clearTimeout(t._x);t._x=setTimeout(function(){t.style.opacity='0';},2400);}

function request(url,options){
 return Promise.resolve().then(function(){return fetch(url,Object.assign({cache:'no-store',credentials:'same-origin'},options));}).then(function(r){
  if(!r||!Number.isInteger(r.status)||typeof r.json!=='function')return null;
  return Promise.resolve().then(function(){return r.json();}).then(function(d){return {ok:r.ok===true&&r.status===200,status:r.status,d:d};},function(){return null;});
 }).catch(function(){return null;});
}
function apiLogin(email,nick,provider){
 return request('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({email:email,nickname:nick||null,provider:provider||'dev'})});
}
function meResult(res){
 var error={phase:'error',notice:FAILED};
 if(!res)return error;
 if(res.status===503&&unavailable(res.d))return {phase:'unavailable',notice:READY};
 if(!res.ok||!object(res.d))return error;
 var d=res.d;
 if(d.auth_version===2){
  if(d.phase==='authenticated'&&d.authenticated===true&&
     fields(d,['auth_version','phase','authenticated','member','auth_context'])){
   var m=identity(d.member,d.auth_context);
   return m?{phase:'authenticated',notice:'현재 회원 상태를 확인했습니다.',member:m}:error;
  }
  if(d.authenticated===false&&d.member===null&&d.auth_context===null){
   if(d.phase==='signed-out'&&fields(d,['auth_version','phase','authenticated','member','auth_context']))
    return {phase:'signed-out',notice:'로그인되어 있지 않습니다. 상담·추천은 로그인 없이 이용할 수 있습니다.'};
   if(d.phase==='unavailable'&&d.reason==='auth_unavailable'&&
      fields(d,['auth_version','phase','authenticated','member','auth_context','reason']))
    return {phase:'unavailable',notice:READY};
  }
  return error;
 }
 // Preserve known deployed closed responses; v1 true never grants v2 membership.
 var legacy=fields(d,['authenticated','member'])||fields(d,['authenticated','member','note']);
 if(legacy&&d.authenticated===false&&d.member===null&&(d.note===undefined||typeof d.note==='string')){
  if(unavailable(d))return {phase:'unavailable',notice:READY};
  return {phase:'signed-out',notice:'로그인되어 있지 않습니다. 상담·추천은 로그인 없이 이용할 수 있습니다.'};
 }
 return error;
}
function applyMe(result){
 availability=result.phase==='unavailable'?'unavailable':result.phase==='error'?'unknown':'available';
 update(result.phase,result.notice,result.member);
}

function canFocus(el){
 if(!el||!el.isConnected||typeof el.focus!=='function'||el.tabIndex<0||el.disabled||el.matches(':disabled')||el.getAttribute('aria-disabled')==='true')return false;
 for(var p=el;p&&p.nodeType===1;p=p.parentElement){
  var s=window.getComputedStyle(p);
  if(p.hidden||p.getAttribute('aria-hidden')==='true'||s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||s.opacity==='0')return false;
 }
 return true;
}
function close(restore){
 var ov=document.getElementById('pa-ov');modalVersion++;
 if(ov){
  if(ov._cleanup){ov._cleanup();ov._cleanup=null;}
  if(ov._busy){begin('error',FAILED,true);}
  ov.remove();
  if(restore!==false&&canFocus(ov._opener))ov._opener.focus({preventScroll:true});
 }
}
function open(mode,after){
 var previous=document.getElementById('pa-ov'),active=document.activeElement;
 var opener=previous&&previous.contains(active)?previous._opener:active;
 close(false);mode=mode||'login';
 var version=modalVersion;
 var ov=document.createElement('div');ov.id='pa-ov';ov._opener=opener;
 ov.style.cssText='position:fixed;inset:0;z-index:99990;background:rgba(23,23,27,.55);backdrop-filter:blur(3px);display:flex;align-items:center;justify-content:center;font-family:var(--font);padding:16px;';
 ov.innerHTML=''
 +'<div id="pa-dialog" role="dialog" aria-modal="true" aria-label="로그인·회원가입 안내" aria-describedby="pa-note" tabindex="-1" style="width:min(400px,94vw);background:#fff;border-radius:22px;padding:28px 26px;box-shadow:0 24px 70px rgba(0,0,0,.35);box-sizing:border-box;">'
 +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
 +'<div style="font-size:17px;font-weight:900;color:#17171b;">팝콘PC <span style="color:#2b5fd9;">AI</span></div>'
 +'<button id="pa-x" type="button" aria-label="로그인 안내 닫기" style="border:none;background:#f4f2ec;width:30px;height:30px;border-radius:9px;cursor:pointer;font-weight:800;color:#6b6b73;">✕</button></div>'
 +'<p id="pa-note" role="status" style="margin:0 0 16px;font-size:12.5px;color:#8a8578;font-weight:600;line-height:1.5;"></p>'
 +'<div style="display:flex;background:#f4f2ec;border-radius:11px;padding:3px;margin-bottom:16px;">'
 +'<button data-tab="login" style="flex:1;padding:9px;border:none;border-radius:8px;font-size:13.5px;font-weight:800;cursor:pointer;font-family:inherit;">로그인</button>'
 +'<button data-tab="join" style="flex:1;padding:9px;border:none;border-radius:8px;font-size:13.5px;font-weight:800;cursor:pointer;font-family:inherit;">회원가입</button></div>'
 +'<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px;">'
 +'<button data-social="카카오" style="width:100%;padding:12px;border:none;background:#FEE500;border-radius:11px;font-size:13.5px;font-weight:800;color:#191919;cursor:pointer;font-family:inherit;">카카오 로그인 (준비 중)</button>'
 +'<button data-social="네이버" style="width:100%;padding:12px;border:none;background:#03C75A;border-radius:11px;font-size:13.5px;font-weight:800;color:#fff;cursor:pointer;font-family:inherit;">네이버 로그인 (준비 중)</button></div>'
 +'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;color:#c9c5bd;font-size:11.5px;font-weight:700;"><span style="flex:1;height:1px;background:#ece9e3;"></span>회원 정보<span style="flex:1;height:1px;background:#ece9e3;"></span></div>'
 +'<div id="pa-form" style="display:flex;flex-direction:column;gap:9px;">'
 +'<input id="pa-nick" aria-label="닉네임" placeholder="닉네임" style="display:none;padding:12px 14px;border:1.5px solid #e6e2da;border-radius:11px;font-size:14px;font-family:inherit;">'
 +'<input id="pa-email" aria-label="이메일" type="email" placeholder="이메일" style="padding:12px 14px;border:1.5px solid #e6e2da;border-radius:11px;font-size:14px;font-family:inherit;">'
 +'<p style="margin:0;font-size:11.5px;color:#a29d92;font-weight:700;line-height:1.5;">상담·추천은 로그인 없이 이용할 수 있습니다. 입력한 이메일만으로 회원 정보나 주문 내역을 조회할 수 없습니다.</p>'
 +'<p id="pa-err" role="alert" style="margin:0;font-size:12px;color:#b31b25;font-weight:700;min-height:14px;"></p>'
 +'<button id="pa-go" style="width:100%;padding:13px;border:none;background:#2b5fd9;border-radius:11px;font-size:14.5px;font-weight:800;color:#fff;cursor:pointer;font-family:inherit;">로그인</button>'
 +'<p id="pa-terms" style="display:none;margin:2px 0 0;font-size:11px;color:#a29d92;line-height:1.5;">회원가입은 본인 확인 기능을 이용할 수 있을 때 진행할 수 있습니다.</p>'
 +'</div></div>';
 document.body.appendChild(ov);
 var cur=mode;
 function currentModal(){return version===modalVersion&&document.getElementById('pa-ov')===ov;}
 function controls(){return Array.prototype.filter.call(ov.querySelectorAll('button,input,select,textarea,a[href],[tabindex]'),canFocus);}
 function focusInitial(){
  if(!currentModal())return;
  var preferred=ov.querySelector(cur==='join'?'#pa-nick':'#pa-email');
  (canFocus(preferred)?preferred:controls()[0]||ov.querySelector('#pa-dialog')).focus();
 }
 function keydown(e){
  if(!currentModal())return;
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();return;}
  if(e.key!=='Tab')return;
  var list=controls(),index=list.indexOf(document.activeElement);
  e.preventDefault();
  if(!list.length){ov.querySelector('#pa-dialog').focus();return;}
  var next=index<0?(e.shiftKey?list.length-1:0):(index+(e.shiftKey?-1:1)+list.length)%list.length;
  list[next].focus();
 }
 document.addEventListener('keydown',keydown,true);
 ov._cleanup=function(){document.removeEventListener('keydown',keydown,true);};
 function paint(){
  var focused=document.activeElement,inside=ov.contains(focused);
  ov.querySelectorAll('[data-tab]').forEach(function(b){var on=b.dataset.tab===cur;b.style.background=on?'#17171b':'transparent';b.style.color=on?'#fff':'#6b6b73';});
  ov.querySelector('#pa-nick').style.display=cur==='join'?'block':'none';
  ov.querySelector('#pa-terms').style.display=cur==='join'?'block':'none';
  var enabled=phase==='signed-out'&&!ov._busy&&!loggingOut;
  ov.querySelector('#pa-note').textContent=notice;
  ov.querySelector('#pa-nick').disabled=!enabled;ov.querySelector('#pa-email').disabled=!enabled;
  var go=ov.querySelector('#pa-go');
  go.textContent=phase==='unavailable'?'로그인·가입 준비 중':phase==='error'?'회원 상태 다시 확인':phase==='checking'?'회원 상태 확인 중':phase==='authenticated'?'회원 상태 확인됨':cur==='join'?'회원가입':'로그인';
  go.disabled=!!ov._busy||loggingOut||(phase!=='signed-out'&&phase!=='error');
  if(inside&&!canFocus(focused))focusInitial();
 }
 ov._paint=paint;
 ov.querySelectorAll('[data-tab]').forEach(function(b){b.onclick=function(){cur=b.dataset.tab;paint();};});

 ov.querySelectorAll('[data-social]').forEach(function(b){b.onclick=function(){
  var via=b.dataset.social;
  var err=ov.querySelector('#pa-err');
  err.textContent=via+' 로그인은 준비 중입니다. 상담·추천은 로그인 없이 이용할 수 있습니다.';
 };});

 ov.querySelector('#pa-go').onclick=function(){
  if(ov._busy||loggingOut||document.getElementById('pa-ov')!==ov)return;
  if(phase==='error'){ov.querySelector('#pa-err').textContent='';sync();return;}
  if(phase!=='signed-out'){paint();return;}
  var em=ov.querySelector('#pa-email').value.trim(),nk=ov.querySelector('#pa-nick').value.trim();
  var err=ov.querySelector('#pa-err');
  if(!em||em.indexOf('@')<0){err.textContent='이메일을 확인해 주세요.';return;}
  if(cur==='join'&&!nk){err.textContent='닉네임을 입력해 주세요.';return;}
  finish(em, cur==='join'?nk:(em.split('@')[0]), '이메일', err);
 };

 function finish(em,nick,via,err){
  ov._busy=true;var turn=begin('checking','로그인 상태를 확인하고 있습니다.',true);err.textContent='';
  function current(){return turn!==null&&!exhausted&&turn===generation&&version===modalVersion&&document.getElementById('pa-ov')===ov;}
  function fail(next,message){if(!current())return;ov._busy=false;availability=next==='unavailable'?'unavailable':next==='signed-out'?'available':'unknown';update(next,message);err.textContent=message;}
  if(!current())return;
  apiLogin(em,nick,via).then(function(res){
   if(!current())return;
   if(res&&unavailable(res.d)){fail('unavailable',READY);return;}
   if(res&&!res.ok&&res.status===400){fail('signed-out','이메일 등 입력 정보를 확인해 주세요.');return;}
   // Email issuance remains closed. No accepted v2 login receipt exists.
   // A legacy "active" response cannot invoke after(), publish identity or claim success.
   fail('error',FAILED);
  });
 }
 ov.querySelector('#pa-x').onclick=function(){if(currentModal())close();};
 ov.addEventListener('click',function(e){if(e.target===ov&&currentModal())close();});
 paint();focusInitial();
}

function logout(){
 if(loggingOut)return Promise.resolve(null);
 close();loggingOut=true;var turn=begin('checking','로그아웃하고 있습니다.',true);
 return request('/api/auth/logout',{method:'POST'}).then(function(res){
  loggingOut=false;
  if(turn===null||turn!==generation||exhausted){
   if(refreshAfterLogout&&!suspended){refreshAfterLogout=false;return syncInternal(false);}
   return null;
  }
  refreshAfterLogout=false;
  update(availability==='unavailable'?'unavailable':'error',availability==='unavailable'?READY:FAILED);
  toast(res&&res.ok&&object(res.d)&&res.d.ok===true?'로그아웃했습니다':'이 기기의 로그인 표시를 지웠습니다. 서버 로그아웃 상태는 확인하지 못했습니다.');
  if(location.pathname.indexOf('my-')>-1)location.href='main-landing.html';
  return null;
 });
}

function syncInternal(share){
 if(loggingOut){refreshAfterLogout=true;return Promise.resolve(null);}
 var ov=document.getElementById('pa-ov');if(ov)ov._busy=false;
 var turn=begin('checking','로그인 상태를 확인하고 있습니다.',share);
 if(turn===null||turn!==generation||exhausted||suspended)return Promise.resolve(null);
 return request('/api/auth/me').then(function(res){
  if(turn!==generation||exhausted||suspended)return null;
  var result;try{result=meResult(res);}catch(e){result={phase:'error',notice:FAILED};}
  applyMe(result);
  if(turn!==generation||exhausted||suspended)return null;
  return result.phase==='authenticated'?true:result.phase==='signed-out'||result.phase==='unavailable'?false:null;
 });
}
function sync(){return syncInternal(true);}

// MY 플로팅 버튼 (우하단 — 허브 FAB는 좌하단)
function refreshFab(){
 var f=document.getElementById('pa-fab');
 if(location.pathname.indexOf('my-page')>-1){if(f)f.remove();return;}
 if(!f){f=document.createElement('a');f.id='pa-fab';
  f.style.cssText='position:fixed;right:18px;bottom:18px;z-index:80;display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:999px;background:rgba(23,23,27,.82);color:#fff;font-size:12.5px;font-weight:800;text-decoration:none;font-family:var(--font);box-shadow:0 4px 16px rgba(0,0,0,.22);backdrop-filter:blur(4px);cursor:pointer;';
  document.body.appendChild(f);}
 var m=member();
 if(m){var avatar=document.createElement('span');avatar.style.cssText='width:20px;height:20px;border-radius:50%;background:#2b5fd9;display:inline-flex;align-items:center;justify-content:center;font-size:11px;';avatar.textContent=m.nick.charAt(0);f.textContent='';f.appendChild(avatar);f.appendChild(document.createTextNode('마이페이지'));f.href='my-page.html';f.onclick=null;}
 else{f.textContent=phase==='unavailable'?'로그인·가입 준비 중':phase==='signed-out'?'로그인 · 가입':'회원 상태 확인';f.href='#!';f.onclick=function(e){e.preventDefault();open('login');};}
}
// 401은 현재 표시를 지운다. 이용 불가한 로그인 모달을 반복해서 자동으로 열지 않는다.
function expired(){
 var ov=document.getElementById('pa-ov');if(ov)ov._busy=false;
 begin(availability==='unavailable'?'unavailable':'error',availability==='unavailable'?READY:FAILED,true);
 toast(notice);
}
function remoteInvalidation(){
 if(suspended){begin('checking','로그인 상태를 확인하고 있습니다.',false);return;}
 if(loggingOut){begin('checking','로그인 상태를 확인하고 있습니다.',false);refreshAfterLogout=true;return;}
 syncInternal(false);
}
function message(event){
 var d=event&&event.data;
 if(fields(d,['type','auth_version'])&&d.type==='invalidate'&&d.auth_version===2)remoteInvalidation();
}
function connectChannel(){
 if(channel||typeof window.BroadcastChannel!=='function')return;
 try{channel=new window.BroadcastChannel('popcorn-auth-invalidate-v2');channel.onmessage=message;}catch(e){channel=null;}
}
function disconnectChannel(){
 if(!channel)return;var old=channel;channel=null;old.onmessage=null;try{old.close();}catch(e){}
}
window.addEventListener('storage',function(e){
 if(e.key===INVALIDATION_KEY&&e.newValue===INVALIDATION_VALUE)remoteInvalidation();
});
window.addEventListener('pagehide',function(){
 suspended=true;close(false);begin('checking','로그인 상태를 확인하고 있습니다.',false);disconnectChannel();
});
window.addEventListener('pageshow',function(e){
 if(!suspended&&!e.persisted)return;suspended=false;connectChannel();syncInternal(true);
});
document.addEventListener('visibilitychange',function(){
 if(document.visibilityState==='hidden'){suspended=true;close(false);begin('checking','로그인 상태를 확인하고 있습니다.',false);}
 else if(document.visibilityState==='visible'){suspended=false;connectChannel();syncInternal(true);}
});
window.addEventListener('focus',function(e){
 if(e.target!==window||suspended)return;syncInternal(true);
});
window.popcornAuth={open:open,member:member,logout:logout,toast:toast,sync:sync,expired:expired,getSnapshot:getSnapshot,subscribe:subscribe};
connectChannel();
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){syncInternal(false);});else syncInternal(false);
})();
