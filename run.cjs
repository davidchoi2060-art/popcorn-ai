// 고객1(게임용 대학생) 품질 점검 — 개발 서버 고객 API 를 mvp3 화면과 같은 순서로 부른다.
// 읽기만 한다: talk/parse, grid/recommend, 대표 사진·부품 사진 GET, pc-offers GET, saved-quotes GET.
// 견적 보관(POST saved-quotes)은 DB 쓰기라 부르지 않는다. 비밀값 없음.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const BASE='https://popcornai.co.kr', OUT=process.env.OUT||'out', TAG=process.env.TAG||'';
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'cases.json'),'utf8'));
fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let cookie='', lastParse=0, parseCount=0;
async function call(method,p,body,extra={},binary=false){
  const h={'Accept':binary?'*/*':'application/json','Origin':BASE,'User-Agent':'Mozilla/5.0 popcorn-qa-customer1',...extra};
  if(body)h['Content-Type']='application/json';
  if(cookie)h['Cookie']=cookie;
  const t0=Date.now();let res,text='',err=null,bytes=0,ctype=null;
  try{res=await fetch(BASE+p,{method,headers:h,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(120000)});
    if(binary){const b=Buffer.from(await res.arrayBuffer());bytes=b.length;ctype=res.headers.get('content-type');}else text=await res.text();}
  catch(e){err=String(e&&e.message||e);}
  const sec=(Date.now()-t0)/1000;let json=null;if(!binary){try{json=JSON.parse(text);}catch{}}
  return {status:res?res.status:0,sec,json,raw:(binary||json)?undefined:text.slice(0,2000),bytes,ctype,error:err,setCookie:res?res.headers.get('set-cookie'):null};
}
async function getVisitor(){
  const key=crypto.randomBytes(24).toString('base64url');
  const r=await call('GET','/api/mvp3/saved-quotes?limit=1',null,{'X-Access-Key':key});
  const m=(r.setCookie||'').match(/pc_vid=([^;]+)/);
  return {cookie:m?'pc_vid='+m[1]:'',saved:{status:r.status,json:r.json}};
}
async function parse(body){
  const wait=lastParse+13000-Date.now();if(wait>0)await sleep(wait);
  let r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;
  if(r.status===429){await sleep(65000);r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;r.retried_after_429=true;}
  return r;
}
function products(rec){
  const out=[];const j=rec&&rec.json;if(!j||!Array.isArray(j.card_sets))return out;
  for(const s of j.card_sets){for(const key of ['items','products','cards']){if(Array.isArray(s[key]))for(const it of s[key])out.push(it);}}
  return out;
}
const checkedImg={};
async function checkMedia(rec){
  const res=[];
  for(const it of products(rec)){
    const code=it.product_code;const m={product_code:code};
    const ph=it.photo;m.photo_state=ph&&ph.state;m.photo_url=ph&&ph.url;
    if(ph&&ph.url&&!checkedImg[ph.url]){const r=await call('GET',ph.url,null,{},true);checkedImg[ph.url]={status:r.status,bytes:r.bytes,ctype:r.ctype};}
    if(ph&&ph.url)m.photo_get=checkedImg[ph.url];
    const parts=(it.public_configuration&&it.public_configuration.parts)||[];
    m.parts_total=parts.length;m.parts_photo=[];
    for(const p of parts){if(p.photo&&p.photo.url){const u=p.photo.url;if(!checkedImg[u]){const r=await call('GET',u,null,{},true);checkedImg[u]={status:r.status,bytes:r.bytes,ctype:r.ctype};}m.parts_photo.push({u,...checkedImg[u]});}}
    if(code&&!checkedImg['offer'+code]){const r=await call('GET','/api/customer/pc-offers/'+code);checkedImg['offer'+code]={status:r.status,json:r.json};}
    m.offer=code?checkedImg['offer'+code]:null;
    res.push(m);
  }
  return res;
}
(async()=>{
  const summary=[];let v=null;const ops=await call('GET','/api/ops');fs.writeFileSync(path.join(OUT,'ops.json'),JSON.stringify(ops,null,2));
  for(const c of cases){
    if(c.id===1||c.id===9||c.id===17){cookie='';v=await getVisitor();cookie=v.cookie;}
    let talk=null,chatFlow=null,history=[];const turns=[];
    for(const text of c.turns){
      const sent=new Date();const p=await parse({text:TAG+text,state:talk,chat_flow:chatFlow,history:history.slice(-6)});
      const turn={text:TAG+text,sent_at_utc:sent.toISOString(),sent_at_kst:new Date(sent.getTime()+9*3600e3).toISOString().replace('Z','+09:00'),pc_vid:cookie.replace('pc_vid=',''),parse:p,recommend:null,media:null};
      const j=p.json;
      if(p.status===200&&j&&j.ok===true&&j.state){
        talk=j.state;chatFlow=j.chat_flow||null;history.push({role:'user',text});
        if(!j.silent){for(const k of ['answer','reply']){const val=typeof j[k]==='string'?j[k]:'';if(val.trim())history.push({role:'assistant',text:val.slice(0,300)});}}
        history=history.slice(-6);
        const missing=Array.isArray(j.missing)?j.missing:[];
        if(!(missing.length||j.pc_related===false||j.silent)){turn.recommend=await call('POST','/api/grid/recommend',{state:talk});turn.media=await checkMedia(turn.recommend);}
      }
      turns.push(turn);
    }
    const rec={id:c.id,kind:c.kind,turns,visitor:cookie?'cookie':'ip',visitor_probe:v&&v.saved,at:new Date().toISOString()};
    fs.writeFileSync(path.join(OUT,String(c.id).padStart(2,'0')+'.json'),JSON.stringify(rec,null,2));
    const last=turns[turns.length-1];
    summary.push({id:c.id,parse:turns.map(t=>t.parse.status+'/'+t.parse.sec.toFixed(1)+'s'),rec:last.recommend?last.recommend.status+'/'+last.recommend.sec.toFixed(1)+'s':'-'});
    console.log(JSON.stringify(summary[summary.length-1]));
  }
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),parse_calls:parseCount,summary},null,2));
})();
