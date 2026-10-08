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
    for(const key of ['cpu','gpu'])if(typeof value[key]==='string')out[key]=value[key];
    for(const key of ['ram_gb','ssd_gb','vram_gb'])if(Number.isFinite(value[key])&&value[key]>=0)out[key]=value[key];
    return Object.keys(out).length?out:null;
  }
  function specRows(spec){
    return object(spec)?[['CPU','cpu'],['GPU','gpu'],['메모리','ram_gb'],['저장장치','ssd_gb'],['GPU 메모리','vram_gb']]
      .filter(pair=>Object.prototype.hasOwnProperty.call(spec,pair[1]))
      .map(([label,key])=>[label,typeof spec[key]==='number'?spec[key]+'GB':spec[key]]):[];
  }
  function specText(spec){return typeof spec==='string'?spec:specRows(spec).map(([label,value])=>label+' '+value).join('\n');}
  function safeUrl(value){
    if(typeof value!=='string')return null;
    try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}
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
        specs:p.specs.map(x=>({label:x.label,value:x.value}))});
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
  function product(value){
    if(!object(value)||!Number.isInteger(value.product_code)||value.product_code<=0||!text(value.name))return null;
    return {product_code:value.product_code,name:value.name,price:Number.isInteger(value.price)&&value.price>=0?value.price:null,
      price_src:text(value.price_src),spec:publicSpec(value.spec),reasons:Array.isArray(value.reasons)?value.reasons.filter(x=>typeof x==='string'):[],
      mall_url:safeUrl(value.mall_url),level:text(value.level),tag:text(value.tag),over_budget:value.over_budget===true,
      public_configuration:publicConfiguration(value.public_configuration,value.product_code)};
  }
  function gameContext(value){
    if(!object(value)||!text(value.game_name).trim()||!object(value.source)||value.source.kind!=='game_customer_copy')return null;
    const out={};
    for(const key of ['game_name','spec_summary','why_this_pc','upgrade_hint','caution'])out[key]=text(value[key]);
    out.source={kind:'game_customer_copy',fields:Array.isArray(value.source.fields)?value.source.fields.filter(x=>typeof x==='string'):[],url:safeUrl(value.source.url)};
    return out;
  }
  function recommendations(value){
    if(!object(value)||value.ok!==true||!Array.isArray(value.card_sets))throw new Error('추천 응답 형식을 확인할 수 없어요.');
    let index=0,unsupported=false;
    const groups=value.card_sets.map(set=>{
      if(!object(set))return null;
      if(set.kind!=='sold'){unsupported=true;return null;}
      return {usage:text(set.usage),usage_grid:text(set.usage_grid),empty_reason:text(set.empty_reason),empty_note:text(set.empty_note),
        min_level:text(set.min_level),min_level_work:text(set.min_level_work),game_context:set.usage_grid==='게임'?gameContext(set.game_context):null,
        products:(Array.isArray(set.items)?set.items:[]).map(product).filter(Boolean).map(p=>({...p,index:index++}))};
    }).filter(Boolean);
    return {groups,unsupported,needs:Array.isArray(value.needs)?value.needs.filter(x=>typeof x==='string'):[],
      assumed:Array.isArray(value.assumed)?value.assumed.filter(x=>typeof x==='string'):[],aiEstimated:Array.isArray(value.ai_estimated)?value.ai_estimated:[]};
  }
  function quote(value){
    if(!object(value)||!uuid(value.id)||!object(value.state)||typeof value.saved_at!=='string'||!/^\d{4}-\d\d-\d\dT/.test(value.saved_at)||!Number.isFinite(Date.parse(value.saved_at)))return null;
    const p=product(value.product);return p&&p.price!==null?{id:value.id,product:p,state:copy(value.state),saved_at:value.saved_at}:null;
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
  const model={object,text,copy,uuid,safeUrl,publicSpec,publicConfiguration,specRows,specText,product,gameContext,recommendations,quote,sources,conditions};
  if(typeof module!=='undefined')module.exports=model;else root.MVP3LiveModel=model;
})(typeof window==='undefined'?globalThis:window);
