// 고객 화면 공용: 서버가 준 대표 이미지(AI 조립 예시)만 받아들이는 규칙. 1차(app.js)와 2차 대화 화면(talk.js)이
// 같은 규칙을 쓰도록 한 곳에 둔다. 불러오면 MVP3LiveModel 의 추천·부품·보관 정리에 사진을 덧붙인다.
(function(root){'use strict';
const M=root.MVP3LiveModel;
const assemblyNotice='AI 조립 예시 이미지 · 실제 출고 외형과 다를 수 있음';
function customerPhoto(value,code){
  const unavailable={state:'unavailable',url:null};
  if(!M.object(value))return unavailable;
  if(value.state==='temporarily_unavailable')return {state:value.state,url:null};
  if(value.state!=='available'||value.kind!=='ai_assembly_example'||value.notice!==assemblyNotice||!Number.isSafeInteger(code)||code<=0)return unavailable;
  const expected='/api/customer/products/'+code+'/representative-image';
  // Accept only the exact server URL for this SKU, never infer an image URL.
  if(value.url!==expected&&value.url!==root.location.origin+expected)return unavailable;
  return {state:'available',kind:value.kind,url:value.url,notice:value.notice};
}
// The existing model drops additive media. Extend only the UI normalization
// results; keep its original product selection, ordering and quote validation.
const normalizeRecommendations=M.recommendations,normalizeQuote=M.quote;
M.recommendations=value=>{
  const result=normalizeRecommendations(value);
  const source=value.card_sets.filter(set=>M.object(set)&&set.kind==='sold');
  result.groups.forEach((group,index)=>{
    const items=(Array.isArray(source[index].items)?source[index].items:[]).filter(item=>M.product(item));
    group.products.forEach((product,n)=>{product.photo=customerPhoto(items[n].photo,product.product_code);});
  });
  return result;
};
const normalizePartOptions=M.partOptions;
M.partOptions=(value,slot,base)=>{
  const result=normalizePartOptions(value,slot,base);
  result.options.forEach(product=>{const raw=value.options.find(x=>M.object(x)&&x.product_code===product.product_code);product.photo=customerPhoto(raw?.photo,product.product_code);});
  return result;
};
M.quote=value=>{
  const result=normalizeQuote(value);
  if(result)result.product.photo=customerPhoto(value.product.photo,result.product.product_code);
  return result;
};
root.MVP3LivePhoto={customerPhoto,assemblyNotice};
})(window);
