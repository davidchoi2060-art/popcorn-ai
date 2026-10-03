(function(root){'use strict';
  const f=typeof module!=='undefined'?require('./fixtures.js'):root.MVP3Fixtures;
  function selection(gpu='A',ssd='1TB'){if(!f.gpus.some(x=>x.id===gpu)||!f.ssds.some(x=>x.id===ssd))throw new Error('선택한 예시 제품을 찾을 수 없어요.');return {gpu,ssd};}
  function quote(s){const picks=selection(s.gpu,s.ssd),gpu=f.gpus.find(x=>x.id===picks.gpu),ssd=f.ssds.find(x=>x.id===picks.ssd);const gpuDelta=gpu.price-f.gpus[0].price,ssdDelta=ssd.price-f.ssds[0].price;return {gpu,ssd,gpuDelta,ssdDelta,total:f.baseTotal+gpuDelta+ssdDelta};}
  function change(s,key,value){if(!['gpu','ssd'].includes(key))throw new Error('지원하지 않는 변경 항목이에요.');return selection(key==='gpu'?value:s.gpu,key==='ssd'?value:s.ssd);}
  function budgetText(total){const gap=f.budget-total;return gap>0?`예산보다 ${gap.toLocaleString('ko-KR')}원 낮아요`:gap<0?`예산보다 ${(-gap).toLocaleString('ko-KR')}원 높아요`:'예산과 같아요';}
  function savedPayload(s){const p=selection(s.gpu,s.ssd);return {origin:'demo',version:1,gpu:p.gpu,ssd:p.ssd};}
  function loadSaved(raw){const x=JSON.parse(raw);if(!x||x.origin!=='demo'||x.version!==1)throw new Error('저장된 데모 견적 형식이 맞지 않아요.');return selection(x.gpu,x.ssd);}
  const model={selection,quote,change,budgetText,savedPayload,loadSaved};if(typeof module!=='undefined')module.exports=model;else root.MVP3Model=model;
})(typeof window==='undefined'?globalThis:window);
