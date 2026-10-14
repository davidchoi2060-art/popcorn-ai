/* Render only server-supplied sold products. No demo price arithmetic. */
(function(root){'use strict';
  const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
  const text=v=>typeof v==='string'?v:'';
  const copy=v=>JSON.parse(JSON.stringify(v));
  const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
  function publicSpec(value){
    if(typeof value==='string')return value;
    if(!object(value))return null;
    const out={};
    for(const key of ['cpu','gpu','case','psu'])if(typeof value[key]==='string')out[key]=value[key];
    for(const key of ['ram_gb','ssd_gb','vram_gb'])if(Number.isFinite(value[key])&&value[key]>=0)out[key]=value[key];
    return Object.keys(out).length?out:null;
  }
  function specRows(spec){
    return object(spec)?[['CPU','cpu'],['GPU','gpu'],['메모리','ram_gb'],['저장장치','ssd_gb'],['GPU 메모리','vram_gb']]
      .filter(pair=>Object.prototype.hasOwnProperty.call(spec,pair[1]))
      .map(([label,key])=>[label,typeof spec[key]==='number'?spec[key]+'GB':spec[key]]):[];
  }
  // Results cards show the four rows of the approved R01 card, built only from
  // server spec fields (no inferred core counts or interface names).
  function storageLabel(gb){return gb>=1000&&gb%1000===0?gb/1000+'TB':gb>=1024&&gb%1024===0?gb/1024+'TB':gb+'GB';}
  function cardSpecRows(spec){
    if(!object(spec))return [];
    const NONE='정보 없음',val=key=>{const v=spec[key];return v===null||v===undefined||(typeof v==='string'&&!v.trim())?'':v;};
    const cpu=val('cpu'),gpu=val('gpu')?String(val('gpu')):'',vram=Number(val('vram_gb'))>0?val('vram_gb')+'GB':'',ram=val('ram_gb'),ssd=val('ssd_gb');
    return [
      ['CPU',cpu!==''?cpu:NONE],
      ['GPU',gpu&&vram&&!gpu.replace(/\s+/g,'').toUpperCase().includes(vram.toUpperCase())?gpu+' · '+vram:gpu||(vram?vram+' 그래픽카드':NONE)],
      ['RAM',ram!==''?ram+'GB':NONE],
      ['저장장치',ssd!==''?storageLabel(ssd)+' SSD':NONE],
      // 케이스·파워(2026-10-12 중헌 님 고객단 4번) -- 서버가 몰 구성 원문에서 읽은 이름만. 못 읽었으면 줄을 두지 않는다.
      ...[['케이스','case'],['파워','psu']].filter(([,key])=>val(key)!=='').map(([label,key])=>[label,String(val(key))])
    ];
  }
  // 2026-10-11: a card without an approved intro used to show the fit category name
  // ("게임 캐주얼 — 롤·발로란트…"). Say instead, in plain words, what changed from the card before it.
  function cardFallbackIntro(product,comparison){
    if(!object(product)||!object(comparison)||!object(product.spec)||!object(comparison.spec))return '';
    const NONE='정보 없음',mine=new Map(cardSpecRows(product.spec)),theirs=new Map(cardSpecRows(comparison.spec));
    const norm=v=>String(v||'').replace(/\s+/g,'').toUpperCase();
    const parts=[['CPU','CPU를'],['GPU','그래픽카드를'],['RAM','메모리를'],['저장장치','저장공간을']]
      .filter(([key])=>mine.get(key)&&mine.get(key)!==NONE&&theirs.get(key)!==NONE&&norm(mine.get(key))!==norm(theirs.get(key)))
      .slice(0,3).map(([key,word])=>word+' '+mine.get(key)+'로');
    if(!parts.length)return '';
    const from=text(comparison.tag)||'앞의 구성';
    return from+'에서 '+parts.join(', ')+(product.role==='premium'?' 바꿔 사양을 높인 구성이에요.':' 바꾼 구성이에요.');
  }
  // 부품을 바꾼 구성(build.changes)은 사양 줄도 바꾼 부품으로 보인다. 바꾼 부품의 용량·코어 수는 서버가 주지 않으므로
  // 지어내지 않고 부품 이름을 그대로 쓴다(2026-10-12 카드 검수 X1: SSD 1TB 로 바꿔도 「저장장치 500GB SSD」로 남았다).
  // 바꾼 부품 칸 -> 바꿔 쓸 사양 줄 이름(카드·상세 두 표기) · 더는 맞지 않아 뺄 줄.
  const CHANGE_ROWS={CPU:[['CPU'],[]],GPU:[['GPU'],['GPU 메모리']],RAM:[['RAM','메모리'],[]],SSD:[['저장장치'],[]],HDD:[['저장장치'],[]],CASE:[['케이스'],[]],POWER:[['파워'],[]]};
  function changedSpecRows(rows,build){
    const changes=object(build)&&Array.isArray(build.changes)?build.changes:[];
    const names=new Map(),drop=new Set();
    for(const c of changes){
      const rule=CHANGE_ROWS[String(c?.slot||'').toUpperCase()];
      if(!rule||!c.after?.name)continue;
      for(const label of rule[0])names.set(label,[...(names.get(label)||[]),c.after.name]);
      for(const label of rule[1])drop.add(label);
    }
    return rows.filter(([label])=>!drop.has(label)).map(([label,value])=>names.has(label)?[label,names.get(label).join(', ')+' (바꾼 부품)']:[label,value]);
  }
  // 상품 이름은 쇼핑몰의 기본 구성 이름이다. 부품을 바꿨으면 이름 아래에 무엇을 바꿨는지 밝힌다.
  function changedPartsNote(build){
    const changes=object(build)&&Array.isArray(build.changes)?build.changes:[];
    const list=changes.filter(c=>c?.after?.name).map(c=>(text(c.label)||c.slot)+' '+c.after.name);
    return list.length?'상품 이름은 기본 구성 기준이에요. 바꾼 부품: '+list.join(', '):'';
  }
  function specText(spec){return typeof spec==='string'?spec:specRows(spec).map(([label,value])=>label+' '+value).join('\n');}
  function safeUrl(value){
    if(typeof value!=='string')return null;
    try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}
  }
  // Approved registered photo of one BOM part. Only the exact server route for a
  // product code is accepted; anything else is shown as "no photo", not rejected.
  function partPhoto(part){
    const none={state:'none',url:null},photo=part.photo;
    if(part.pseudo||!object(photo)||photo.state!=='approved'||typeof photo.url!=='string')return none;
    const match=/^\/api\/product-images\/([1-9][0-9]{0,15})\/detail$/.exec(photo.url);
    return match&&Number.isSafeInteger(Number(match[1]))?{state:'approved',url:photo.url}:none;
  }
  function publicConfiguration(value,productCode){
    const nullable=v=>v===null||typeof v==='string',positive=v=>Number.isSafeInteger(v)&&v>0;
    if(!object(value)||!positive(productCode)||value.product_code!==productCode||value.offer_id!=='P'+productCode||
      !text(value.configuration_id).trim()||!positive(value.revision))return null;
    const d=value.description;
    if(!object(d)||!['title','intro','scene'].every(k=>nullable(d[k]))||
      !Array.isArray(d.benefits)||!d.benefits.every(x=>Array.isArray(x)&&x.length===2&&x.every(y=>typeof y==='string'))||
      !Array.isArray(d.checks)||!d.checks.every(x=>typeof x==='string')||
      !Array.isArray(d.faq)||!d.faq.every(x=>object(x)&&typeof x.question==='string'&&typeof x.answer==='string'))return null;
    if(!Array.isArray(value.parts)||!value.parts.length)return null;
    const ordinals=new Set(),parts=[];
    for(const p of value.parts){
      if(!object(p)||!Number.isSafeInteger(p.ordinal)||p.ordinal<0||ordinals.has(p.ordinal)||!text(p.slot).trim()||
        !positive(p.quantity)||typeof p.pseudo!=='boolean'||!nullable(p.name)||!nullable(p.description)||
        !Array.isArray(p.specs)||!p.specs.every(x=>object(x)&&typeof x.label==='string'&&typeof x.value==='string')||
        (p.pseudo&&(p.name!==null||p.description!==null||p.specs.length)))return null;
      ordinals.add(p.ordinal);
      parts.push({ordinal:p.ordinal,slot:p.slot,quantity:p.quantity,pseudo:p.pseudo,name:p.name,description:p.description,
        specs:p.specs.map(x=>({label:x.label,value:x.value})),photo:partPhoto(p),
        price:!p.pseudo&&positive(p.price)?p.price:null});
    }
    const price=value.price,stock=value.stock,c=value.compatibility,photo=value.photo,conditions={};
    if(!object(price)||!['confirmed','snapshot','estimated','needs_reconfirmation','unknown'].includes(price.state)||
      !nullable(price.checked_at)||!nullable(price.observed_date)||!([null,'bundle','new_parts_sum','derived_delta'].includes(price.model))||
      (['unknown','needs_reconfirmation'].includes(price.state)?price.amount!==null:!positive(price.amount))||
      (price.state==='confirmed'&&!text(price.checked_at).trim())||
      !object(stock)||!['available','unavailable','unknown'].includes(stock.state)||!nullable(stock.checked_at)||
      !object(c)||!['pass','fail','unknown'].includes(c.document_state)||!nullable(c.public_summary)||c.assembly_state!=='unknown'||
      !object(photo)||photo.state!=='unresolved'||photo.url!==null||!object(value.customer_conditions))return null;
    for(const key of ['os','keyboard','mouse','monitor','warranty']){
      const x=value.customer_conditions[key],states=key==='warranty'?['verified','unknown']:['included','excluded','unknown'];
      if(!object(x)||!states.includes(x.state)||typeof x.detail!=='string'||typeof x.customer_statement!=='string'||
        typeof x.needs_reconfirmation!=='boolean'||(x.months!==null&&(!positive(x.months)||x.months>120))||
        (key!=='warranty'&&x.months!==null)||(key==='warranty'&&x.state==='verified'&&(!positive(x.months)||!x.detail.trim()||x.needs_reconfirmation)))return null;
      conditions[key]={state:x.state,detail:x.detail,months:x.months,needs_reconfirmation:x.needs_reconfirmation,customer_statement:x.customer_statement};
    }
    return {product_code:productCode,configuration_id:value.configuration_id,revision:value.revision,offer_id:value.offer_id,
      description:{title:d.title,intro:d.intro,scene:d.scene,benefits:d.benefits.map(x=>[...x]),checks:[...d.checks],faq:d.faq.map(x=>({question:x.question,answer:x.answer}))},
      parts:parts.sort((a,b)=>a.ordinal-b.ordinal),customer_conditions:conditions,
      price:{state:price.state,amount:price.amount,checked_at:price.checked_at,observed_date:price.observed_date,model:price.model},
      stock:{state:stock.state,checked_at:stock.checked_at},compatibility:{document_state:c.document_state,public_summary:c.public_summary,assembly_state:c.assembly_state},
      photo:{state:'unresolved',url:null}};
  }
  // Card role (sold_reco: value · recommended · reference). Responses and saved
  // snapshots from before the role field carry only the badge text.
  // premium = 추천 구성 다음 「더 높은 사양」, chosen = 목록 밖에서 고객이 고른 카드를 보관한 것(2026-10-11).
  const legacyRoles={'추천 구성':'recommended','예산 안 최고 수준':'recommended','알뜰 구성':'value','가장 저렴한 선택':'value','예산을 넘는 최저가':'reference','더 높은 사양':'premium','고른 구성':'chosen'};
  function productRole(value){
    if(['value','recommended','reference','premium','chosen'].includes(value.role))return value.role;
    return value.role===undefined||value.role===null?legacyRoles[text(value.tag)]||'':'';
  }
  function product(value){
    if(!object(value)||!Number.isInteger(value.product_code)||value.product_code<=0||!text(value.name))return null;
    return {product_code:value.product_code,name:value.name,price:Number.isInteger(value.price)&&value.price>=0?value.price:null,
      price_src:text(value.price_src),spec:publicSpec(value.spec),reasons:Array.isArray(value.reasons)?value.reasons.filter(x=>typeof x==='string'):[],
      mall_url:safeUrl(value.mall_url),level:text(value.level),tag:text(value.tag),role:productRole(value),over_budget:value.over_budget===true,
      public_configuration:publicConfiguration(value.public_configuration,value.product_code),build:build(value.build),
      ...(Number.isSafeInteger(value.sets)&&value.sets>1&&value.sets<=10?{sets:value.sets}:{})};
  }
  // 부품 직접 바꾸기(api/mvp3_build): 같은 PC 의 구성표에서 바꾼 줄들. 금액·차액은 서버가 준 값만 쓴다.
  function buildPart(v){
    return object(v)&&Number.isSafeInteger(v.product_code)&&v.product_code>0&&typeof v.name==='string'&&Number.isSafeInteger(v.price)
      ?{product_code:v.product_code,name:v.name,price:v.price}:null;
  }
  function buildChanges(list){
    if(!Array.isArray(list))return null;
    const out=list.map(c=>{
      const before=buildPart(c?.before),after=buildPart(c?.after);
      if(!object(c)||!Number.isSafeInteger(c.ordinal)||c.ordinal<0||!text(c.slot)||!Number.isSafeInteger(c.delta)||!before||!after)return null;
      const quantity=Number.isSafeInteger(c.quantity)&&c.quantity>0?c.quantity:1;
      // base_quantity: 구성표 원래 수량(api/mvp3_quantity). 예전 견적에는 없어 바꾼 수량과 같다고 본다.
      return {ordinal:c.ordinal,slot:c.slot,label:text(c.label)||c.slot,quantity,base_quantity:Number.isSafeInteger(c.base_quantity)&&c.base_quantity>0?c.base_quantity:quantity,before,after,delta:c.delta};
    });
    return out.every(Boolean)?out:null;
  }
  // 받아들였지만 확인하지 못한 호환 안내(예: 구성표에 CPU 쿨러 줄이 없음). 서버 문구만 쓴다.
  function buildWarnings(list){return Array.isArray(list)?list.filter(x=>typeof x==='string'&&x.trim()):[];}
  function build(value){
    if(!object(value)||!Number.isSafeInteger(value.base_price)||value.base_price<0)return null;
    const changes=buildChanges(value.changes);
    return changes&&changes.length?{base_price:value.base_price,changes,warnings:buildWarnings(value.warnings)}:null;
  }
  function buildQuote(value,baseCode){
    const changes=buildChanges(value?.changes);
    if(!object(value)||value.ok!==true||value.base_code!==baseCode||!Number.isSafeInteger(value.base_price)||!Number.isSafeInteger(value.total)||!changes)
      throw new Error('바꾼 구성의 금액을 확인할 수 없어요.');
    return {base_price:value.base_price,total:value.total,changes,warnings:buildWarnings(value.warnings)};
  }
  function buildOptions(value,baseCode,ordinal){
    if(!object(value)||value.ok!==true||value.base_code!==baseCode||value.ordinal!==ordinal||!Number.isSafeInteger(value.total)||!Array.isArray(value.options))
      throw new Error('바꿀 부품 선택지를 확인할 수 없어요.');
    const options=value.options.map(o=>object(o)&&Number.isSafeInteger(o.product_code)&&o.product_code>0&&text(o.name).trim()&&
      Number.isSafeInteger(o.price)&&Number.isSafeInteger(o.price_diff)&&Number.isSafeInteger(o.total)
      ?{product_code:o.product_code,name:o.name,price:o.price,price_diff:o.price_diff,total:o.total}:null).filter(Boolean);
    // 메모리·저장장치 수량 범위(api/mvp3_quantity.limit_for). 서버가 준 범위만 쓴다 -- 없으면 수량을 바꾸지 않는다.
    const l=value.quantity_limit,q=value.quantity;
    const quantity=object(l)&&Number.isSafeInteger(q)&&Number.isSafeInteger(l.max)&&l.max>=q&&q>=1
      ?{current:q,min:1,max:l.max,basis:text(l.basis),known:l.known===true}:null;
    return {ordinal,label:text(value.label),current:buildPart(value.current),total:value.total,options,quantity,
      checked:Number.isSafeInteger(value.checked)?value.checked:0,untested:Number.isSafeInteger(value.untested)?value.untested:0,note:text(value.note),
      warnings:buildWarnings(value.warnings)};
  }
  function gameContext(value){
    if(!object(value)||!text(value.game_name).trim()||!object(value.source)||value.source.kind!=='game_customer_copy')return null;
    const out={};
    for(const key of ['game_name','spec_summary','why_this_pc','upgrade_hint','caution'])out[key]=text(value[key]);
    out.source={kind:'game_customer_copy',fields:Array.isArray(value.source.fields)?value.source.fields.filter(x=>typeof x==='string'):[],url:safeUrl(value.source.url)};
    return out;
  }
  // 새로 나온 PC(api/sold_reco.custom_items · 부품 상품화 5단계): 몰 상품번호가 없는 운영자 신규 조립PC.
  // 몰 카드(products)와 섞지 않는다 — 보관 견적·쇼핑몰 연결 대신 「새로 나온 PC」 화면으로 보낸다.
  function customItem(v){
    if(!object(v)||typeof v.configuration_id!=='string'||!/^A[0-9A-F]{16}$/.test(v.configuration_id)||!text(v.title).trim()||!Number.isSafeInteger(v.price)||v.price<=0)return null;
    const parts=Array.isArray(v.parts)?v.parts.filter(p=>object(p)&&text(p.slot_label)&&text(p.name)).map(p=>({slot_label:p.slot_label,name:p.name,quantity:Number.isSafeInteger(p.quantity)&&p.quantity>0?p.quantity:1})):[];
    return {configuration_id:v.configuration_id,title:v.title,price:v.price,price_note:text(v.price_note),fit:v.fit==='fit'?'fit':'unknown',
      level_text:text(v.level_text)||'정보 없음',parts,url:'new-pcs.html#'+v.configuration_id};
  }
  function recommendations(value){
    if(!object(value)||value.ok!==true||!Array.isArray(value.card_sets))throw new Error('추천 응답 형식을 확인할 수 없어요.');
    let index=0,unsupported=false;
    const groups=value.card_sets.map(set=>{
      if(!object(set))return null;
      if(set.kind!=='sold'){unsupported=true;return null;}
      return {usage:text(set.usage),usage_grid:text(set.usage_grid),empty_reason:text(set.empty_reason),empty_note:text(set.empty_note),
        min_level:text(set.min_level),min_level_work:text(set.min_level_work),game_context:set.usage_grid==='게임'?gameContext(set.game_context):null,
        products:(Array.isArray(set.items)?set.items:[]).map(product).filter(Boolean).map(p=>({...p,index:index++})),
        custom:(Array.isArray(set.custom_items)?set.custom_items:[]).map(customItem).filter(Boolean)};
    }).filter(Boolean);
    return {groups,unsupported,needs:Array.isArray(value.needs)?value.needs.filter(x=>typeof x==='string'):[],
      assumed:Array.isArray(value.assumed)?value.assumed.filter(x=>typeof x==='string'):[],aiEstimated:Array.isArray(value.ai_estimated)?value.ai_estimated:[],
      ...exploration(value)};
  }
  // Conversation follow-ups (api/reco_explore): sentences to say after the cards, quick
  // choices, the card they are measured from, and the extra conditions to send back next time.
  const CHOICE_IDS=['cheaper','better','change'];
  function exploration(value){
    const notes=Array.isArray(value.talk_notes)?value.talk_notes.filter(x=>typeof x==='string'&&x.trim()).slice(0,8):[];
    const choices=Array.isArray(value.choices)?value.choices.filter(c=>object(c)&&CHOICE_IDS.includes(c.id)&&text(c.label).trim())
      .map(c=>({id:c.id,label:c.label,enabled:c.enabled===true})):[];
    const anchorCode=Number.isSafeInteger(value.anchor_code)&&value.anchor_code>0?value.anchor_code:null;
    const wants=object(value.wants)&&JSON.stringify(value.wants).length<=2048?copy(value.wants):null;
    return {talkNotes:notes,choices,anchorCode,wants};
  }
  // 보관·구매 순간 쇼핑몰 현재가 확인 결과(api/mall_price_live.confirm). 문장은 서버가 준 것만 쓴다.
  function priceCheck(value){
    if(!object(value)||!['same','changed','unchecked'].includes(value.status))return null;
    const int=v=>Number.isInteger(v)?v:null;
    return {status:value.status,quoted:int(value.quoted),mall:int(value.mall),diff:int(value.diff),saved:value.saved===true,message:text(value.message),checked_at:text(value.checked_at)};
  }
  function quote(value){
    if(!object(value)||!uuid(value.id)||!object(value.state)||typeof value.saved_at!=='string'||!/^\d{4}-\d\d-\d\dT/.test(value.saved_at)||!Number.isFinite(Date.parse(value.saved_at)))return null;
    const p=product(value.product);if(!p||p.price===null)return null;
    const out={id:value.id,product:p,state:copy(value.state),saved_at:value.saved_at},check=priceCheck(value.product.price_check);
    if(check)out.price_check=check;
    return out;
  }
  // 부품 바꾸기 응답(api/mvp3_part_options): 그 부품만 다른 판매 PC 들. 상품은 추천 카드와 같은 판정을 거치고,
  // 차액·함께 바뀌는 것은 서버가 준 값만 쓴다(화면이 금액을 더하거나 빼지 않는다).
  const SWAP_SLOTS=['cpu','gpu','ram','ssd'];
  function partOptions(value,slot,baseCode){
    if(!object(value)||value.ok!==true||!SWAP_SLOTS.includes(slot)||value.slot!==slot||value.base_code!==baseCode||!Array.isArray(value.options))
      throw new Error('부품 선택지를 확인할 수 없어요.');
    const options=value.options.map(raw=>{
      const p=product(raw),s=raw?.swap;
      if(!p||p.price===null||p.product_code===baseCode||!object(s)||s.slot!==slot||!text(s.value).trim()||!Number.isSafeInteger(s.price_diff)||!Array.isArray(s.also))return null;
      const also=s.also.filter(x=>object(x)&&['label','from','to'].every(k=>typeof x[k]==='string')).map(x=>({label:x.label,from:x.from,to:x.to}));
      return {...p,swap:{value:s.value,price_diff:s.price_diff,also}};
    }).filter(Boolean);
    return {slot,label:text(value.label)||slot,current:text(value.current),options};
  }
  function sources(value){
    return Array.isArray(value)?value.filter(object).filter(x=>['own','web'].includes(x.kind)&&text(x.label))
      .map(x=>({kind:x.kind,label:x.label,url:safeUrl(x.url)})):[];
  }
  function conditions(state){
    if(!object(state))return [];
    const result=[];
    if(Array.isArray(state.usages)&&state.usages.length)result.push(state.usages.filter(x=>typeof x==='string').join(' · '));
    if(Number.isInteger(state.budget_won)&&state.budget_won>0)result.push('예산 '+state.budget_won.toLocaleString('ko-KR')+'원'+(state.budget_bound?' '+text(state.budget_bound):''));
    if(Array.isArray(state.game?.names)&&state.game.names.length)result.push(state.game.names.filter(x=>typeof x==='string').join(' · '));
    if(text(state.game?.resolution))result.push(state.game.resolution);
    if(text(state.platform))result.push(state.platform);
    return result;
  }
  // Condition chips for the results heading: what the server parsed, plus
  // assumptions it reported (shown as provisional, never as the customer's words).
  function conditionChips(state,assumed){
    const chips=[];
    if(object(state)){
      if(Array.isArray(state.game?.names))state.game.names.filter(x=>typeof x==='string'&&x.trim()).forEach(x=>chips.push({icon:'game-controller',label:x}));
      if(Number.isInteger(state.budget_won)&&state.budget_won>0)chips.push({icon:'tag',label:'예산 '+state.budget_won.toLocaleString('ko-KR')+'원'+(state.budget_bound?' '+text(state.budget_bound):'')});
      if(Array.isArray(state.usages)&&state.usages.length)chips.push({icon:'computer-tower',label:state.usages.filter(x=>typeof x==='string').join(' · ')});
      if(text(state.game?.resolution))chips.push({icon:'monitor',label:state.game.resolution});
      if(text(state.platform))chips.push({icon:'gear',label:state.platform});
    }
    if(Array.isArray(assumed)&&assumed.includes('game.resolution=1080p')&&!text(state?.game?.resolution))
      chips.push({icon:'monitor',label:'FHD · 임시 기준',assumed:true,note:'해상도를 정하지 않아 FHD(1080p)를 기준으로 조회했어요.'});
    return chips;
  }
  const CARD_PART_LABELS={CPU:'CPU',GPU:'그래픽카드',RAM:'메모리',SSD:'저장장치',HDD:'저장장치',MB:'메인보드',
    COOLER:'쿨러',POWER:'파워',PSU:'파워',CASE:'케이스'};
  // Card thumbnails: only parts the public configuration already approved. No placeholder for the rest.
  function cardPartPhotos(product){
    const parts=product?.public_configuration?.parts;
    if(!Array.isArray(parts))return [];
    return parts.filter(p=>!p.pseudo&&p.photo?.state==='approved'&&partPhoto(p).state==='approved')
      .map(p=>({ordinal:p.ordinal,label:CARD_PART_LABELS[p.slot]||p.slot,name:p.name||'',url:p.photo.url}));
  }
  const model={object,text,copy,uuid,safeUrl,publicSpec,partPhoto,publicConfiguration,specRows,cardSpecRows,changedSpecRows,changedPartsNote,cardFallbackIntro,cardPartPhotos,conditionChips,specText,product,gameContext,recommendations,customItem,partOptions,buildOptions,buildQuote,quote,sources,conditions};
  if(typeof module!=='undefined')module.exports=model;else root.MVP3LiveModel=model;
})(typeof window==='undefined'?globalThis:window);
