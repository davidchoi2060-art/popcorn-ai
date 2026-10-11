// 고객 품질관리(영상 편집자) — 개발 서버 고객 API 를 mvp3 화면과 같은 순서로 부른다. 비밀값 없음.
// /api/talk/parse -> (missing 없고 pc_related!==false 이고 silent 아님) -> /api/grid/recommend
// 카드마다 대표 사진·부품 사진·공개 구성 확인, save 표시 문의는 견적 보관(mvp3 마지막 단계)까지.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const BASE='https://popcornai.co.kr', OUT=process.env.OUT||'out';
const TAG=process.env.TAG||'';
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'cases.json'),'utf8')).map(c=>({...c,turns:c.turns.map(t=>TAG+t)}));
fs.mkdirSync(OUT,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let cookie='', accessKey='', lastParse=0, parseCount=0;
async function call(method,p,body,extra={},binary=false){
  const h={'Content-Type':'application/json','Accept':binary?'image/*':'application/json','Origin':BASE,'User-Agent':'Mozilla/5.0 popcorn-qa-video-editor',...extra};
  if(cookie)h['Cookie']=cookie;
  const t0=Date.now();let res,text='',err=null,bytes=0,ctype=null;
  try{res=await fetch(BASE+p,{method,headers:h,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(120000)});
    ctype=res.headers.get('content-type');
    if(binary){const b=Buffer.from(await res.arrayBuffer());bytes=b.length;text=ctype&&ctype.includes('json')?b.toString('utf8'):'';}
    else text=await res.text();}
  catch(e){err=String(e&&e.message||e);}
  const sec=(Date.now()-t0)/1000;let json=null;try{json=JSON.parse(text);}catch{}
  const out={status:res?res.status:0,sec,error:err,ctype,setCookie:res?res.headers.get('set-cookie'):null};
  if(binary){out.bytes=bytes;if(json)out.json=json;}else{out.json=json;if(!json)out.raw=text.slice(0,2000);}
  return out;
}
async function newVisitor(){
  cookie='';accessKey=crypto.randomBytes(24).toString('base64url');
  const r=await call('GET','/api/mvp3/saved-quotes?limit=1',null,{'X-Access-Key':accessKey});
  const m=(r.setCookie||'').match(/pc_vid=([^;]+)/);
  cookie=m?'pc_vid='+m[1]:'';
  return r;
}
async function parse(body){
  const wait=lastParse+13000-Date.now();if(wait>0)await sleep(wait);
  let r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;
  if(r.status===429){await sleep(65000);r=await call('POST','/api/talk/parse',body);lastParse=Date.now();parseCount++;r.retried_after_429=true;}
  return r;
}
function soldItems(rec){
  const j=rec&&rec.json;if(!j||!Array.isArray(j.card_sets))return [];
  return j.card_sets.filter(g=>g&&g.kind==='sold').flatMap(g=>Array.isArray(g.items)?g.items:[]);
}
async function checkCards(items){
  const out=[];
  for(const it of items.slice(0,4)){
    const c={product_code:it.product_code,price:it.price,photo:it.photo||null};
    if(it.photo&&it.photo.state==='available'&&typeof it.photo.url==='string'){
      const r=await call('GET',it.photo.url,null,{},true);c.rep_image={status:r.status,bytes:r.bytes,ctype:r.ctype};
    }
    const parts=(it.public_configuration&&Array.isArray(it.public_configuration.parts))?it.public_configuration.parts:[];
    const ph=parts.filter(p=>p&&p.photo&&p.photo.state==='approved'&&typeof p.photo.url==='string');
    c.parts_total=parts.length;c.parts_with_photo=ph.length;
    if(ph.length){const r=await call('GET',ph[0].photo.url,null,{},true);c.part_image_first={url:ph[0].photo.url,status:r.status,bytes:r.bytes};}
    const o=await call('GET','/api/customer/pc-offers/'+it.product_code);
    c.offer={status:o.status,keys:o.json?Object.keys(o.json):null};
    out.push(c);
  }
  return out;
}
(async()=>{
  const summary=[];
  const ops=await call('GET','/api/ops');
  fs.writeFileSync(path.join(OUT,'ops.json'),JSON.stringify(ops,null,2));
  let turnsSinceVisitor=99;
  for(const c of cases){
    if(turnsSinceVisitor+c.turns.length>12){await newVisitor();turnsSinceVisitor=0;}
    turnsSinceVisitor+=c.turns.length;
    let talk=null,chatFlow=null,history=[];const turns=[];
    for(const text of c.turns){
      const wait0=lastParse+13000-Date.now();if(wait0>0)await sleep(wait0);
      const sentAt=new Date().toISOString();
      const p=await parse({text,state:talk,chat_flow:chatFlow,history:history.slice(-6)});
      const turn={text,sent_at:sentAt,parse:p,recommend:null,cards:null};
      const j=p.json;
      if(p.status===200&&j&&j.ok===true&&j.state){
        talk=j.state;chatFlow=j.chat_flow||null;history.push({role:'user',text});
        if(!j.silent){for(const k of ['answer','reply']){const v=typeof j[k]==='string'?j[k]:'';if(v.trim())history.push({role:'assistant',text:v.slice(0,300)});}}
        history=history.slice(-6);
        const missing=Array.isArray(j.missing)?j.missing:[];
        if(!(missing.length||j.pc_related===false||j.silent)){
          turn.recommend=await call('POST','/api/grid/recommend',{state:talk});
          turn.cards=await checkCards(soldItems(turn.recommend));
        }
      }
      turns.push(turn);
    }
    const rec={id:c.id,kind:c.kind,turns,visitor:cookie||'ip',access_key_sha256:crypto.createHash('sha256').update(accessKey).digest('hex'),at:new Date().toISOString()};
    const last=turns[turns.length-1];
    if(c.save){
      const items=soldItems(last.recommend);
      if(items.length&&talk){
        const it=items[0];
        const body={request_id:crypto.randomUUID(),product_code:it.product_code,expected_price:it.price,state:talk};
        rec.save={request:{product_code:it.product_code,expected_price:it.price},
          post:await call('POST','/api/mvp3/saved-quotes',body,{'X-Access-Key':accessKey})};
        rec.save.list=await call('GET','/api/mvp3/saved-quotes?limit=5',null,{'X-Access-Key':accessKey});
      } else rec.save={skipped:'no sold card'};
    }
    fs.writeFileSync(path.join(OUT,String(c.id).padStart(2,'0')+'.json'),JSON.stringify(rec,null,2));
    summary.push({id:c.id,parse:turns.map(t=>t.parse.status+'/'+t.parse.sec.toFixed(1)+'s'),rec:last.recommend?last.recommend.status+'/'+last.recommend.sec.toFixed(1)+'s':'-',cards:(last.cards||[]).map(x=>x.product_code),save:rec.save?(rec.save.post?rec.save.post.status:rec.save.skipped):undefined});
    console.log(JSON.stringify(summary[summary.length-1]));
  }
  // 결제 경로 확인: 자체 결제 주문 생성은 가짜 상담 번호로 한 번만 두드린다(쓰기 전 단계에서 거절되는지).
  const order=await call('POST','/api/orders',{session_id:999999999,tier:'recommend',periph:[],member:{nick:'qa',email:'qa-test@example.invalid',via:'email'},shipping:{name:'테스트',phone:'000',addr:'테스트'},method:'카드'});
  fs.writeFileSync(path.join(OUT,'order-probe.json'),JSON.stringify(order,null,2));
  fs.writeFileSync(path.join(OUT,'summary.json'),JSON.stringify({base:BASE,taken_at:new Date().toISOString(),parse_calls:parseCount,summary},null,2));
})();
