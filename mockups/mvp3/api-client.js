/* Same-origin customer APIs. Provider credentials never enter the browser. */
(function(root){'use strict';
  class ApiError extends Error {
    constructor(message,status=0,code='network',retryAfter=0){super(message);this.name='ApiError';this.status=status;this.code=code;this.retryAfter=retryAfter;}
  }
  const KEY='popcorn-mvp3-guest-access-v1', KEY_RE=/^[A-Za-z0-9_-]{32,128}$/;
  function errorMessage(status,data){
    const detail=data&&data.detail, value=typeof detail==='object'&&detail?detail:data;
    const code=typeof value?.error==='string'?value.error:'';
    if(status===429)return '요청이 많아 잠시 기다려야 해요. 잠시 후 다시 시도해주세요.';
    if(status===409)return '상품 가격이나 추천 조건이 달라졌어요. 최신 추천을 다시 확인해주세요.';
    if(status===401||status===403)return '이 브라우저의 보관 기록에 접근할 수 없어요. 보관 키와 브라우저 설정을 확인해주세요.';
    if(status===404)return '요청한 자료를 찾지 못했어요. 연결 상태를 확인한 뒤 다시 시도해주세요.';
    if(status===502||status===503)return '상담 또는 서버 연결을 확인할 수 없어요. 잠시 후 다시 시도해주세요.';
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
    async function request(method,path,body,options={}){
      const allowed=(method==='POST'&&['/api/talk/parse','/api/grid/recommend','/api/mvp3/saved-quotes'].includes(path))
        ||(method==='GET'&&/^\/api\/mvp3\/saved-quotes(?:\?limit=(?:1|20))?$/.test(path));
      if(!allowed)throw new ApiError('지원하지 않는 고객 요청입니다.',0,'unsupported');
      if(!fetchImpl)throw new ApiError('서버 연결을 사용할 수 없어요.',0,'network');
      const controller=new AbortController(), signal=options.signal;
      const abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
      if(signal?.aborted)controller.abort();
      let timedOut=false;const timer=setTimeout(()=>{timedOut=true;controller.abort();},options.timeoutMs||60000);
      try{
        const headers=body?{'Content-Type':'application/json'}:{};
        if(path.startsWith('/api/mvp3/saved-quotes'))headers['X-Access-Key']=guestKey(options.existingKeyOnly===true);
        const response=await fetchImpl(path,{method,headers,credentials:'same-origin',cache:'no-store',signal:controller.signal,...(body?{body:JSON.stringify(body)}:{})});
        let data;try{data=await response.json();}catch{throw new ApiError('서버 응답을 확인할 수 없어요. 다시 시도해주세요.',response.status||502,'invalid_response');}
        if(!response.ok){
          const value=typeof data?.detail==='object'&&data.detail?data.detail:data;
          const rawRetry=response.headers?.get('Retry-After');
          const retry=Number(rawRetry)||Math.max(0,(Date.parse(rawRetry)-Date.now())/1000)||Number(value?.retry_after_sec)||0;
          throw new ApiError(errorMessage(response.status,data),response.status,typeof value?.error==='string'?value.error:'http_error',Math.ceil(retry));
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
      recommend:(state,options)=>request('POST','/api/grid/recommend',{state},options),listSaved,saveQuote,prepareSave};
  }
  const exported={ApiError,createClient,errorMessage,KEY};
  if(typeof module!=='undefined')module.exports=exported;else root.MVP3Api={...exported,...createClient()};
})(typeof window==='undefined'?globalThis:window);
