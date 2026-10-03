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
  function product(value){
    if(!object(value)||!Number.isInteger(value.product_code)||value.product_code<=0||!text(value.name))return null;
    return {product_code:value.product_code,name:value.name,price:Number.isInteger(value.price)&&value.price>=0?value.price:null,
      price_src:text(value.price_src),spec:publicSpec(value.spec),reasons:Array.isArray(value.reasons)?value.reasons.filter(x=>typeof x==='string'):[],
      mall_url:safeUrl(value.mall_url),level:text(value.level),tag:text(value.tag),over_budget:value.over_budget===true};
  }
  function recommendations(value){
    if(!object(value)||value.ok!==true||!Array.isArray(value.card_sets))throw new Error('추천 응답 형식을 확인할 수 없어요.');
    let index=0,unsupported=false;
    const groups=value.card_sets.map(set=>{
      if(!object(set))return null;
      if(set.kind!=='sold'){unsupported=true;return null;}
      return {usage:text(set.usage),usage_grid:text(set.usage_grid),empty_reason:text(set.empty_reason),empty_note:text(set.empty_note),
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
  const model={object,text,copy,uuid,safeUrl,publicSpec,specRows,specText,product,recommendations,quote,sources,conditions};
  if(typeof module!=='undefined')module.exports=model;else root.MVP3LiveModel=model;
})(typeof window==='undefined'?globalThis:window);
