/* Same-origin customer APIs. Provider credentials never enter the browser. */
(function(root){'use strict';
  class ApiError extends Error {
    constructor(message,status=0,code='network',retryAfter=0){super(message);this.name='ApiError';this.status=status;this.code=code;this.retryAfter=retryAfter;}
  }
  const KEY='popcorn-mvp3-guest-access-v1', KEY_RE=/^[A-Za-z0-9_-]{32,128}$/;
  function errorMessage(status,data,path=''){
    const detail=data&&data.detail, value=typeof detail==='object'&&detail?detail:data;
    const code=typeof value?.error==='string'?value.error:'';
    // 부품 직접 바꾸기는 서버가 고객에게 보일 이유(호환 실패 · 구성 비공개 · 판매 중 아님)를 문장으로 준다.
    if(path.startsWith('/api/mvp3/build/')&&[404,409,422].includes(status)&&typeof detail==='string'&&detail.length<=200)return detail;
    // 연락처·상담 신청 접수는 서버가 고객에게 보일 이유를 문장으로 준다(연락처 없음 · 형식 · 견적을 찾지 못함).
    const sentence=typeof detail==='string'?detail:typeof detail?.detail==='string'?detail.detail:'';
    if(/^\/api\/mvp3\/(contact|purchase-inquiries\/from-quote)$/.test(path)&&[404,409,422,429].includes(status)&&sentence&&sentence.length<=200)return sentence;
    if(status===422&&sentence&&sentence.length<=200)return sentence;
    if(status===429)return '요청이 많아 잠시 기다려야 해요. 잠시 후 다시 시도해주세요.';
    if(status===409)return '상품 가격이나 추천 조건이 달라졌어요. 최신 추천을 다시 확인해주세요.';
    if(status===401||status===403)return '이 브라우저의 보관 기록에 접근할 수 없어요. 보관 키와 브라우저 설정을 확인해주세요.';
    if(status===404)return '요청한 자료를 찾지 못했어요. 연결 상태를 확인한 뒤 다시 시도해주세요.';
    if(status===502||status===503||status===504)return '상담 또는 서버 연결을 확인할 수 없어요. 잠시 후 다시 시도해주세요.';
    return '요청을 처리하지 못했어요. 입력과 연결 상태를 확인해주세요.';
  }
  function createClient(options={}){
    const fetchImpl=options.fetchImpl||root.fetch?.bind(root), cryptoImpl=options.cryptoImpl||root.crypto;
    let storage=options.storage, storageResolved=Object.prototype.hasOwnProperty.call(options,'storage'), accessKey, primed=false;
    function guestKey(existingOnly=false){
      if(existingOnly){
        try{
          if(!storageResolved){storage=root.localStorage;storageResolved=true;}
          const existing=storage?.getItem(KEY);
          if(!existing||!KEY_RE.test(existing)||(accessKey&&existing!==accessKey))throw new Error('changed');
          accessKey=existing;return existing;
        }catch{throw new ApiError('이전 보관 요청의 접근 키를 확인할 수 없어요. 새 키로 다시 보관하지 않고 현재 요청을 유지합니다.',0,'owner_changed');}
      }
      if(accessKey)return accessKey;
      try{
        if(!storageResolved){storage=root.localStorage;storageResolved=true;}
        const existing=storage?.getItem(KEY);
        if(existing&&KEY_RE.test(existing)){accessKey=existing;return accessKey;}
        if(!storage||!cryptoImpl?.getRandomValues)throw new Error('storage');
        const bytes=new Uint8Array(32);cryptoImpl.getRandomValues(bytes);
        const generated=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
        storage.setItem(KEY,generated);
        if(storage.getItem(KEY)!==generated)throw new Error('storage');
        accessKey=generated;return accessKey;
      }catch{throw new ApiError('브라우저에 보관 접근 키를 저장할 수 없어 견적 보관을 사용할 수 없어요. 상담은 계속할 수 있어요.',0,'storage_unavailable');}
    }
    const HANDOFF_RE=/^\/api\/mvp3\/saved-quotes\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/handoff$/;
    async function request(method,path,body,options={}){
      const allowed=(method==='POST'&&(['/api/talk/parse','/api/talk/answer','/api/grid/recommend','/api/mvp3/saved-quotes','/api/mvp3/purchase-inquiries','/api/mvp3/purchase-inquiries/from-quote','/api/mvp3/part-options','/api/mvp3/build/options','/api/mvp3/build/quote'].includes(path)||HANDOFF_RE.test(path)))
        ||(method==='GET'&&(/^\/api\/mvp3\/saved-quotes(?:\?limit=(?:1|20))?$/.test(path)||path==='/api/mvp3/purchase-inquiries/form'||path==='/api/mvp3/contact'))
        ||(method==='PUT'&&path==='/api/mvp3/contact');
      if(!allowed)throw new ApiError('지원하지 않는 고객 요청입니다.',0,'unsupported');
      if(!fetchImpl)throw new ApiError('서버 연결을 사용할 수 없어요.',0,'network');
      const controller=new AbortController(), signal=options.signal;
      const abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
      if(signal?.aborted)controller.abort();
      let timedOut=false;const timer=setTimeout(()=>{timedOut=true;controller.abort();},options.timeoutMs||60000);
      try{
        const headers=body?{'Content-Type':'application/json'}:{};
        // 보관 견적·연락처·견적으로 상담 신청 접수는 같은 보관 키로 이 브라우저의 것임을 서버가 확인한다.
        if(path.startsWith('/api/mvp3/saved-quotes')||path==='/api/mvp3/contact'||path==='/api/mvp3/purchase-inquiries/from-quote')headers['X-Access-Key']=guestKey(options.existingKeyOnly===true);
        const response=await fetchImpl(path,{method,headers,credentials:'same-origin',cache:'no-store',signal:controller.signal,...(body?{body:JSON.stringify(body)}:{})});
        const retryOf=value=>{const rawRetry=response.headers?.get('Retry-After');return Number(rawRetry)||Math.max(0,(Date.parse(rawRetry)-Date.now())/1000)||Number(value?.retry_after_sec)||0;};
        let data;try{data=await response.json();}catch(error){
          // 본문을 읽다가 취소·시간 초과로 끊겼으면 아래 catch 가 그 사실대로 말한다(「응답 형식」 탓으로 돌리지 않는다).
          if(controller.signal.aborted)throw error;
          // JSON 이 아닌 5xx 는 서버 앞단(nginx)이 낸 오류 화면이다 -- API 가 재시작하는 몇 초 동안 502 HTML 이 온다
          // (2026-10-15 오픈테스트 C04: main 반영·배포 재시작 25초 뒤 첫 답변의 추천이 「서버 응답을 확인할 수 없어요」로 실패).
          // 응답 형식 문제가 아니라 일시적 연결 실패로 구분해 흐름이 다시 묻게 한다(live-flow TRANSIENT).
          if(!response.ok&&response.status>=500)throw new ApiError(errorMessage(response.status,null,path),response.status,'gateway_error',Math.ceil(retryOf(null)));
          throw new ApiError('서버 응답을 확인할 수 없어요. 다시 시도해주세요.',response.status||502,'invalid_response');
        }
        if(!response.ok){
          const value=typeof data?.detail==='object'&&data.detail?data.detail:data;
          const retry=retryOf(value);
          throw new ApiError(errorMessage(response.status,data,path),response.status,typeof value?.error==='string'?value.error:'http_error',Math.ceil(retry));
        }
        return data;
      }catch(error){
        if(error instanceof ApiError)throw error;
        if(controller.signal.aborted){const e=new ApiError(timedOut?'응답이 늦어 결과를 확인하지 못했어요. 잠시 후 다시 시도해주세요.':'요청을 취소했어요.',0,timedOut?'timeout':'aborted');throw e;}
        throw new ApiError('서버에 연결하지 못했어요. 연결 상태를 확인하고 다시 시도해주세요.',0,'network');
      }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
    }
    function validList(result){
      if(result?.ok!==true||!Array.isArray(result.quotes))throw new ApiError('보관 목록 응답을 확인할 수 없어요.',502,'invalid_response');
      return result;
    }
    async function prepareSave(options={}){
      const key=guestKey(options.existingKeyOnly===true);
      if(!cryptoImpl?.subtle)throw new ApiError('안전한 보관 요청 복구를 사용할 수 없어요. 상담은 계속할 수 있어요.',0,'storage_unavailable');
      const digest=await cryptoImpl.subtle.digest('SHA-256',new TextEncoder().encode(key));
      return Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
    }
    async function listSaved(options={}){
      const result=validList(await request('GET','/api/mvp3/saved-quotes?limit=20',null,options));primed=true;return result;
    }
    async function saveQuote(payload,options={}){
      if(!primed){validList(await request('GET','/api/mvp3/saved-quotes?limit=1',null,options));primed=true;}
      return request('POST','/api/mvp3/saved-quotes',payload,options);
    }
    return {request,parse:(payload,options)=>request('POST','/api/talk/parse',payload,options),
      answer:(payload,options)=>request('POST','/api/talk/answer',payload,options),
      // extra: this turn's text, the wants the server returned last time, a quick-choice
      // direction and the card it is measured from. Nothing else is forwarded.
      recommend:(state,options,extra={})=>{const body={state};
        if(typeof extra.text==='string'&&extra.text.trim())body.text=extra.text.slice(0,300);
        if(extra.wants&&typeof extra.wants==='object'&&!Array.isArray(extra.wants))body.wants=extra.wants;
        if(['cheaper','better'].includes(extra.nav))body.nav=extra.nav;
        if(Number.isSafeInteger(extra.anchor_code)&&extra.anchor_code>0)body.anchor_code=extra.anchor_code;
        return request('POST','/api/grid/recommend',body,options);},listSaved,saveQuote,prepareSave,
      // 보관 견적을 팝콘PC 쇼핑몰로 넘긴다(api/mvp3_handoff.py). 결제는 쇼핑몰이 한다.
      handoff:async(quoteId,options={})=>{if(!primed){validList(await request('GET','/api/mvp3/saved-quotes?limit=1',null,options));primed=true;}
        return request('POST','/api/mvp3/saved-quotes/'+String(quoteId).toLowerCase()+'/handoff',null,{...options,existingKeyOnly:true});},
      // 부품 바꾸기(api/mvp3_part_options.py): 고른 판매 PC 에서 그 부품만 다른 판매 PC 목록. 읽기만 한다.
      partOptions:(state,productCode,slot,options)=>request('POST','/api/mvp3/part-options',{state,product_code:productCode,slot},options),
      // 부품 직접 바꾸기(api/mvp3_build.py): 같은 PC 의 부품 한 줄을 호환되는 판매 부품으로. 읽기만 한다.
      buildOptions:(state,productCode,changes,ordinal,options)=>request('POST','/api/mvp3/build/options',{state,product_code:productCode,changes,ordinal},options),
      buildQuote:(state,productCode,changes,options)=>request('POST','/api/mvp3/build/quote',{state,product_code:productCode,changes},options),
      // 구매 상담 신청(api/mvp3_purchase_inquiry.py). 연락처를 남길 뿐 주문·결제는 하지 않는다.
      inquiryForm:options=>request('GET','/api/mvp3/purchase-inquiries/form',null,options),
      inquiry:(payload,options)=>request('POST','/api/mvp3/purchase-inquiries',payload,options),
      // 연락처(api/mvp3_quote_consult): 처음 보관할 때 한 번만 받는다. 응답에는 가린 번호만 온다.
      contact:options=>request('GET','/api/mvp3/contact',null,options),
      saveContact:(payload,options)=>request('PUT','/api/mvp3/contact',payload,{...options,existingKeyOnly:true}),
      // 보관 견적 + 등록 연락처로 상담 신청 접수. 같은 견적은 서버가 한 건만 만든다. 주제는 서버 TOPICS 중 하나(없으면 서버 기본값).
      consultFromQuote:(quoteId,message,options,topic)=>request('POST','/api/mvp3/purchase-inquiries/from-quote',{quote_id:String(quoteId).toLowerCase(),...(message?{message}:{}),...(topic?{topic}:{})},{...options,existingKeyOnly:true})};
  }
  const exported={ApiError,createClient,errorMessage,KEY};
  if(typeof module!=='undefined')module.exports=exported;else root.MVP3Api={...exported,...createClient()};
})(typeof window==='undefined'?globalThis:window);
