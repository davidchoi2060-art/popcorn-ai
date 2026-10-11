// 품질관리 고객2(사무용) 일회용 — 개발 서버 공개 고객 API 를 화면(mvp3)과 같은 순서로 부른다.
// 상담: /api/talk/parse -> (missing 없고 pc_related!==false 이고 silent 아님) -> /api/grid/recommend
// 카드마다: /api/customer/pc-offers/{code} · 대표 사진 URL · 부품 사진 URL(앞 3개) 을 GET 으로만 확인.
// 견적 보관(POST saved-quotes)·주문·결제는 부르지 않는다. 비밀값·DB 접속·서버 변경 없음.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const BASE='https://popcornai.co.kr', OUT=process.env.OUT||'out';
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'cases.json'),'utf8'));
fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let cookie='', vid='', lastParse=0, parseCount=0, parseByVisitor=0;
async function call(method,p,body,extra={},binary=false){
  const h={'Accept':binary?'*/*':'application/json','Origin':BASE,'User-Agent':'Mozilla/5.0 popcorn-qa-office-check',...extra};
  if(body)h['Content-Type']='application/json';
  if(cookie)h['Cookie']=cookie;
  const t0=Date.now();let res,text='',buf=null,err=null;
  try{res=await fetch(BASE+p,{method,headers:h,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(120000)});
    if(binary){buf=Buffer.from(await res.arrayBuffer());}else{text=await res.text();}}
  catch(e){err=String(e&&e.message||e);}
  const sec=(Date.now()-t0)/1000;
  if(binary)return {status:res?res.status:0,sec,type:res?res.headers.get('content-type'):null,bytes:buf?buf.length:0,png:buf?buf.slice(0,4).toString('hex')==='89504e47':false,error:err};
  let json=null;try{json=JSON.parse(text);}catch{}
  return {status:res?res.status:0,sec,json,raw:json?undefined:text.slice(0,2000),error:err,setCookie:res?res.headers.get('set-cookie'):null};
}
async function getVisitor(){
  const key=crypto.randomBytes(24).toString('base64url');
  cookie='';
  const r=await call('GET','/api/mvp3/saved-quotes?limit=1',null,{'X-Access-Key':key});
  const m=(r.setCookie||'').match(/pc_vid=([^;]+)/);
  vid=m?m[1].slice(0,8):'';
  return m?'pc_vid='+m[1]:'';
}
async function parse(body){
  // 방문자 한도(분당 5회, 하루 40회)를 넘지 않게 13초 간격, 방문자당 9회까지만 쓴다.
  const wait=lastParse+13000-Date.now();if(wait>0)await sleep(wait);
  let r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;parseByVisitor++;
  if(r.status===429){await sleep(65000);r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;r.retried_after_429=true;}
  return r;
}
const offerCache={};
async function checkCard(item){
  const code=item.product_code;
  if(offerCache[code])return offerCache[code];
  const out={code};
  out.offer=await call('GET','/api/customer/pc-offers/'+code);
  if(item.photo&&item.photo.url){out.photo=await call('GET',item.photo.url.replace(BASE,''),null,{},true);}
  const oj=out.offer.json||{};const parts=oj.parts||(oj.public_configuration&&oj.public_configuration.parts)||(item.public_configuration&&item.public_configuration.parts)||[];
  out.part_photos=[];
  for(const p of parts.filter(p=>p&&p.photo&&p.photo.state==='approved'&&typeof p.photo.url==='string').slice(0,3)){
    out.part_photos.push({slot:p.slot,url:p.photo.url,res:await call('GET',p.photo.url,null,{},true)});
  }
  offerCache[code]=out;return out;
}
(async()=>{
  const summary=[];
  const page=await call('GET','/mvp3/');
  const ops=await call('GET','/api/ops');fs.writeFileSync(path.join(OUT,'ops.json'),JSON.stringify(ops,null,2));
  fs.writeFileSync(path.join(OUT,'page.json'),JSON.stringify({status:page.status,len:(page.raw||'').length,head:(page.raw||'').slice(0,600)},null,2));
  for(const c of cases){
    const needed=c.turns.length;
    if(!cookie||parseByVisitor+needed>9){cookie=await getVisitor();parseByVisitor=0;}
    let talk=null,chatFlow=null,history=[];const turns=[];
    for(const text of c.turns){
      const p=await parse({text,state:talk,chat_flow:chatFlow,history:history.slice(-6)});
      const turn={text,sent_at:new Date(lastParse).toISOString(),visitor_key_prefix:vid,parse:p,recommend:null,cards:[]};
      const j=p.json;
      if(p.status===200&&j&&j.ok===true&&j.state){
        talk=j.state;chatFlow=j.chat_flow||null;history.push({role:'user',text});
        if(!j.silent){for(const k of ['answer','reply']){const v=typeof j[k]==='string'?j[k]:'';if(v.trim())history.push({role:'assistant',text:v.slice(0,300)});}}
        history=history.slice(-6);
        const missing=Array.isArray(j.missing)?j.missing:[];
        if(!(missing.length||j.pc_related===false||j.silent)){
          turn.recommend=await call('POST','/api/grid/recommend',{state:talk});
          const sets=(turn.recommend.json&&turn.recommend.json.card_sets)||[];
          for(const s of sets){if(s&&s.kind==='sold')for(const it of (s.items||[]))turn.cards.push(await checkCard(it));}
        }
      }
      turns.push(turn);
    }
    const rec={id:c.id,kind:c.kind,visitor_key_prefix:vid,turns,at:new Date().toISOString()};
    fs.writeFileSync(path.join(OUT,String(c.id).padStart(2,'0')+'.json'),JSON.stringify(rec,null,2));
    const last=turns[turns.length-1];
    summary.push({id:c.id,parse:turns.map(t=>t.parse.status+'/'+t.parse.sec.toFixed(1)+'s'),rec:last.recommend?last.recommend.status+'/'+last.recommend.sec.toFixed(1)+'s':'-',cards:last.cards.map(x=>x.code+':'+x.offer.status+'/photo '+(x.photo?x.photo.status:'-'))});
    console.log(JSON.stringify(summary[summary.length-1]));
  }
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),parse_calls:parseCount,summary},null,2));
})();
