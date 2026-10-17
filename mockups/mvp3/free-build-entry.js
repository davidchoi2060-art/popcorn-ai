/* One-use, same-tab handoff. Customer text never enters the URL or localStorage. */
(function(root){'use strict';
 const KEY='popcorn-mvp3-free-build-handoff-v1',TTL=10*60*1000;
 const object=x=>x&&typeof x==='object'&&!Array.isArray(x);
 function validConditions(c){return object(c)&&Object.keys(c).every(k=>['cpu','gpu','ram_gb','ssd_gb','platform'].includes(k))&&Object.entries(c).every(([k,v])=>['cpu','gpu'].includes(k)?typeof v==='string'&&v.trim()&&v.length<=40:k==='platform'?['인텔','AMD'].includes(v):Number.isSafeInteger(v)&&v>=(k==='ram_gb'?4:120)&&v<=(k==='ram_gb'?256:16000));}
 function validAction(a,text){return object(a)&&a.type==='open_free_build'&&a.conditions_source==='request_text'&&typeof a.request_text==='string'&&a.request_text.trim()&&a.request_text.length<=2000&&a.request_text===text&&validConditions(a.conditions);}
 function create(options={}){const store=()=>options.storage||root.sessionStorage;return {
  put(a,now=Date.now()){try{const s=store();s.removeItem(KEY);if(!validAction(a,a?.request_text))return false;const raw=JSON.stringify({version:1,saved_at:now,text:a.request_text,conditions:a.conditions});s.setItem(KEY,raw);return s.getItem(KEY)===raw;}catch{return false;}},
  take(now=Date.now()){try{const s=store(),raw=s.getItem(KEY);s.removeItem(KEY);if(!raw)return null;const a=JSON.parse(raw);return a?.version===1&&Number.isFinite(a.saved_at)&&now>=a.saved_at&&now-a.saved_at<=TTL&&validAction({type:'open_free_build',conditions_source:'request_text',request_text:a.text,conditions:a.conditions},a.text)?{text:a.text,conditions:a.conditions}:null;}catch{return null;}}
 };}
 function open(a,win=root){if(!create().put(a))return false;win.location.assign('free-build.html');return true;}
 const api={KEY,TTL,validAction,validConditions,create,open};if(typeof module!=='undefined')module.exports=api;else root.MVP3FreeBuildEntry=api;
})(typeof window==='undefined'?globalThis:window);
