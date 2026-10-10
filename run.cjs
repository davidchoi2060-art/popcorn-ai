// 고객 상담 품질 점검 — 개발 서버 고객 API 를 화면과 같은 순서로 부른다(읽기만, 비밀값 없음).
// /api/talk/parse -> (missing 없고 pc_related!==false 이고 silent 아님) -> /api/grid/recommend
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const BASE='https://popcornai.co.kr', OUT=process.env.OUT||'out';
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'cases.json'),'utf8'));
fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let cookie='', lastParse=0, parseCount=0;
async function call(method,p,body,extra={}){
  const h={'Content-Type':'application/json','Accept':'application/json','Origin':BASE,'User-Agent':'Mozilla/5.0 popcorn-talk-quality-check',...extra};
  if(cookie)h['Cookie']=cookie;
  const t0=Date.now();let res,text='',err=null;
  try{res=await fetch(BASE+p,{method,headers:h,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(120000)});text=await res.text();}
  catch(e){err=String(e&&e.message||e);}
  const sec=(Date.now()-t0)/1000;let json=null;try{json=JSON.parse(text);}catch{}
  return {status:res?res.status:0,sec,json,raw:json?undefined:text.slice(0,2000),error:err,setCookie:res?res.headers.get('set-cookie'):null};
}
async function getVisitor(){
  const key=crypto.randomBytes(24).toString('base64url');
  const r=await call('GET','/api/mvp3/saved-quotes?limit=1',null,{'X-Access-Key':key});
  const m=(r.setCookie||'').match(/pc_vid=([^;]+)/);
  return m?'pc_vid='+m[1]:'';
}
async function parse(body){
  // 방문자 한도(기본 분당 5회)를 넘지 않게 13초 간격을 둔다.
  const wait=lastParse+13000-Date.now();if(wait>0)await sleep(wait);
  let r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;
  if(r.status===429){await sleep(65000);r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;r.retried_after_429=true;}
  return r;
}
(async()=>{
  const summary=[];
  for(const c of cases){
    if(c.id===1||c.id===16){cookie='';cookie=await getVisitor();}   // 방문자 둘로 나눠 일 한도를 나눈다
    let talk=null,chatFlow=null,history=[];const turns=[];
    for(const text of c.turns){
      const p=await parse({text,state:talk,chat_flow:chatFlow,history:history.slice(-6)});
      const turn={text,parse:p,recommend:null};
      const j=p.json;
      if(p.status===200&&j&&j.ok===true&&j.state){
        talk=j.state;chatFlow=j.chat_flow||null;history.push({role:'user',text});
        if(!j.silent){for(const k of ['answer','reply']){const v=typeof j[k]==='string'?j[k]:'';if(v.trim())history.push({role:'assistant',text:v.slice(0,300)});}}
        history=history.slice(-6);
        const missing=Array.isArray(j.missing)?j.missing:[];
        if(!(missing.length||j.pc_related===false||j.silent)){turn.recommend=await call('POST','/api/grid/recommend',{state:talk});}
      }
      turns.push(turn);
    }
    const rec={id:c.id,kind:c.kind,turns,visitor:cookie?'cookie':'ip',at:new Date().toISOString()};
    fs.writeFileSync(path.join(OUT,String(c.id).padStart(2,'0')+'.json'),JSON.stringify(rec,null,2));
    const last=turns[turns.length-1];
    summary.push({id:c.id,parse:turns.map(t=>t.parse.status+'/'+t.parse.sec.toFixed(1)+'s'),rec:last.recommend?last.recommend.status+'/'+last.recommend.sec.toFixed(1)+'s':'-'});
    console.log(JSON.stringify(summary[summary.length-1]));
  }
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),parse_calls:parseCount,summary},null,2));
})();
