/* All products, prices, FPS and compatibility here are fictional UI fixtures. */
(function(root){
  'use strict';
  const data={origin:'demo',version:1,budget:1500000,baseTotal:1490000,
    gpus:[
      {id:'A',name:'그래픽카드 A · 8GB',price:500000,pubg:90,lol:220,power:550,length:240,compatible:true},
      {id:'B',name:'그래픽카드 B · 12GB',price:650000,pubg:120,lol:250,power:600,length:260,compatible:true},
      {id:'C',name:'그래픽카드 C · 8GB',price:430000,pubg:85,lol:210,power:500,length:230,compatible:true}],
    ssds:[{id:'1TB',name:'NVMe SSD 1TB',price:100000,games:8,read:5000},{id:'2TB',name:'NVMe SSD 2TB',price:170000,games:18,read:5000}],
    parts:[
      {key:'cpu',label:'CPU',name:'6코어 프로세서',price:250000,icon:'ms-memory',description:'게임과 여러 프로그램의 연산을 처리하는 부품이에요.',reason:'게임과 일반 작업을 함께 사용하는 상황을 고려했어요.',specs:[['코어 / 스레드','6코어 / 12스레드'],['용도','게임 · 일반 작업'],['소켓','실제 제품 확인 필요']]},
      {key:'gpu',label:'그래픽카드',icon:'ms-developer_board',description:'게임 화면을 그리는 부품이에요. 성능은 모델과 설정에 따라 달라요.',reason:'게임명과 해상도, 목표 프레임을 함께 비교해요.'},
      {key:'ram',label:'메모리',name:'32GB (16GB × 2)',price:120000,icon:'ms-memory_alt',description:'게임과 브라우저를 함께 사용할 여유를 고려했어요.',reason:'실행 중인 프로그램의 데이터를 잠시 보관해요.',specs:[['총 용량','32GB'],['구성','16GB × 2'],['규격 / 지원 여부','실제 제품과 메인보드 확인']]},
      {key:'ssd',label:'저장장치',icon:'ms-inventory',description:'게임과 파일을 저장해요. 설치할 게임의 용량을 확인해주세요.',reason:'용량 증가와 속도 향상은 따로 확인해야 해요.'},
      {key:'board',label:'메인보드',name:'예시 메인보드',price:180000,icon:'ms-developer_board',description:'CPU, 메모리, 그래픽카드 등을 연결하는 기반이에요.',reason:'정확한 제품 기준으로 부품 호환성을 확인해요.',specs:[['CPU 소켓','실제 제품 확인'],['메모리 규격','실제 제품 확인'],['저장장치 슬롯','M.2 지원 여부 확인'],['연결 단자','USB · LAN 등 확인']]},
      {key:'power',label:'파워',name:'650W 파워',price:100000,icon:'ms-inventory_2',description:'각 부품에 필요한 전력을 공급하는 부품이에요.',reason:'소비전력과 그래픽카드 전원 단자를 함께 확인해요.',specs:[['정격 출력','650W'],['형태','ATX (예시)'],['전원 커넥터 / 보증','실제 제품 확인']]},
      {key:'case',label:'케이스',name:'미들타워 케이스',price:140000,icon:'ms-desktop_windows',description:'부품을 담고 공기가 흐를 공간을 만드는 외장이에요.',reason:'부품 크기와 통풍, 설치 공간을 확인해요.',specs:[['형태','미들타워'],['GPU 장착 길이','최대 330mm (예시)'],['기본 팬 / 포트','실제 제품 확인']]},
      {key:'assembly',label:'조립 · 검수',name:'조립 · 검수 예시 금액',price:100000,icon:'ms-tune',description:'부품 조립과 기본 동작 확인을 위한 예시 항목이에요.',reason:'실조립 검수 완료와 문서상 호환 확인은 다른 상태예요.',specs:[['조립 범위','실제 판매조건 확인 필요'],['동작 확인','실검수 전'],['서비스 포함 여부','근거 확인 필요']]}],
    conditions:{os:{state:'unknown',detail:'',months:null,needs_reconfirmation:true,customer_statement:'운영체제 포함 여부는 구매 전 확인이 필요합니다.'},keyboard:{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'키보드 제공 여부는 미확인입니다.'},mouse:{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'마우스 제공 여부는 미확인입니다.'},monitor:{state:'unknown',detail:'',months:null,needs_reconfirmation:false,customer_statement:'모니터 제공 여부는 미확인입니다.'},warranty:{state:'unknown',detail:'',months:null,needs_reconfirmation:true,customer_statement:'보증 기간과 범위는 재확인이 필요합니다.'}}};
  if(typeof module!=='undefined')module.exports=data;else root.MVP3Fixtures=data;
})(typeof window==='undefined'?globalThis:window);
