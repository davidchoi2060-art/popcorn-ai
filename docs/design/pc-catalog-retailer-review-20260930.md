# 보완 항목 판매처 대조 — 2026-09-30

다나와·컴퓨존·오마이PC의 상품 자료로 현재 보완 항목을 채울 수 있는지 조사했다. 기존 보완 대상 부품 9종과 기본 쿨러 식별을 위한 CPU 1종을 대상으로 했다. 104개 완제품 전체의 재고·출고를 세 판매처에서 확인한 조사는 아니다.

**결론: 입력할 근거를 새로 확보한 항목, 버전을 구분해야 하는 항목, 판매처끼리 충돌하는 항목이 함께 있다.** DN-240의 290W는 새로 확보한 판매처 사양이다. 보드 영상 단자와 SSD 용량별 속도는 정정 근거가 강화됐다. 반면 PALADIN 400은 사양 변경 이력, A13은 소켓 지원 변경, SF 360은 치수 불일치가 있어 일괄 복사하면 오류가 재발한다.

이번 산출물은 조사·반영 판단 문서다. DB 사양·검토 승인·추천 상태는 변경하지 않았다. 마지막 DB 재점검은 **2026-09-30 14:38 KST: 51 추천 가능 후보 / 52 보완 필요 / 1 우선 제외 대상**이며 현재 실시간 재집계값으로 해석하지 않는다.

## 확인 결과와 반영 판단

| 부품번호 / 모델 | 다나와 | 컴퓨존 | 오마이PC | 판단 |
|---|---|---|---|---|
| 113685 · GIGABYTE H610M H V2 D4 | DDR4, HDMI·D-SUB | 동일 모델 DDR4, HDMI·D-SUB | 같은 DDR4 모델, HDMI·D-SUB | 기존 DVI 포함 표기를 정정할 모델 수준 근거 확보. DDR5 이름 유사 제품은 제외. 출고 리비전·BIOS 확인은 별도 |
| 110899 · Samsung PM9A1 256GB | 순차 읽기 6,400 / 쓰기 2,700 MB/s | 찾은 동일 용량 상품은 중고 | 사이트 검색에서 해당 모델 미확보 | 256GB 기준 속도 정정 근거 확보. 다른 용량 수치, 중고 상품 가격·보증은 가져오지 않음. 실제 공급 P/N 확인은 남음 |
| 111403 · PCCOOLER PALADIN 400 | 현재 235W, 2025년 7월 200→235W 변경 안내 | 현재 235W | 사이트 검색에서 해당 모델 미확보 | 235W를 현행 판매 사양으로 기록 가능. 기존 팝콘PC 공급 버전 확인 없이 모든 제품에 소급 적용하지 않음 |
| 114514 · darkFlash NEBULA DN-240 ARGB 블랙 | TDP 수치 미표기 | **TDP 290W** | DN-240 사양표에 TDP 수치 미표기 | **판매처 출처를 명시해 보완 가능한 신규 수치.** 다른 곳의 미표기는 반대 근거가 아님. 실측 냉각 성능·소음 보증과 구분 |
| 114723 · Thermalright Peerless Assassin 120 SE WHITE ARGB | 155mm, AM4·AM5, TDP 수치 미표기 | 155mm, AM5 표기, TDP 수치 미표기 | 동일 모델명 사양표는 AM4만 표기, 유통사 미기재 | 오마이PC 표가 최신 지원 목록을 충분히 반영하지 못함. 숫자 TDP 대신 제조사 CPU 지원·부하 검증 근거 필요 |
| 123603 · MSI MAG CORELIQUID A13 360 블랙 | 2025년 4월부터 115x·1200 미지원 안내 | 현재 요약에 1851·1700 | 사양표에 1200·115x도 포함 | 공급 시점/브래킷 조건 구분 필요. 기존 DB의 구형 소켓 목록을 현행 모델 지원으로 단정하면 안 됨 |
| 128953 · 3RSYS 라니 SF 360 ARGB 블랙 | 라디에이터 길이 397mm | 394mm | SF 360 ARGB 공통 모델 394mm | 색상·세부 모델을 식별하고 실제 도면 대조. 3mm 차이도 케이스 장착 판단에서 임의로 합치지 않음. TDP 수치 미확보 |
| 128954 · 3RSYS 라니 SF 360 ARGB 화이트 | 라디에이터 길이 397mm | 394mm | 위 공통 모델 자료 | 블랙과 같은 충돌. SF 360N PWM 및 SE·NY 등 유사 제품 자료를 섞지 않음 |
| 123395 · ABKO 자이로스 120X4 FRGB 블랙 | 210W·150mm, LGA1851 포함 | 검색에 노출된 상품 요약에는 LGA1851 없음 | 사이트 검색에서 해당 모델 미확보 | 소켓 지원 충돌. 컴퓨존 상세 실시간 재열람은 실패해 검색 노출 근거로만 취급. 동봉 브래킷/포장 지원표 확인 전 P119302를 자동 통과시키지 않음 |
| 121359 · Ryzen 5 5500GT / 기본 쿨러 식별 | 멀티팩 Wraith Stealth 포함 | 해당 멀티팩 Wraith Stealth 포함 | 5500GT 완제품 구성에 Wraith Stealth를 별도 명시 | 기본 쿨러 모델 후보 확보. 팝콘PC의 실제 CPU 패키지와 출고 구성 확인 후 연결. 공용 기본쿨러 코드 전체를 이 모델로 바꾸면 안 됨 |

검색 미확보는 판매하지 않는다는 확정이 아니다. 다나와·컴퓨존은 공개 상품 페이지와 검색을 이용했고, 오마이PC는 검색 및 실제 상세 사양표를 읽었다. 컴퓨존 DN-240은 일반 웹 추출의 문자 인코딩 문제 때문에 실제 브라우저 페이지에서도 290W 표시를 확인했다.

## 출처별 근거

### 메인보드와 SSD

- H610M H V2 D4: [다나와 · 피씨디렉트](https://prod.danawa.com/info/?pcode=20119583), [컴퓨존 · 1028527](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1028527), [오마이PC · 1238](https://www.omypc.co.kr/products/1238). 세 곳의 HDMI·D-SUB 표기는 [GIGABYTE DDR4 rev.1.0 사양](https://www.gigabyte.com/pk/Motherboard/H610M-H-V2-DDR4-rev-10/sp)과도 일치한다. 제품명에서 D4/DDR4를 반드시 구분한다.
- PM9A1 256GB: [다나와 · 13550969](https://prod.danawa.com/info/?pcode=13550969), [컴퓨존 중고 · 1354252](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1354252), [삼성 용량별 사양표](https://download.semiconductor.samsung.com/resources/brochure/Product%20Overviews%20PM9A1%20SSD%20Storage%20for%20the%20Next-Generation%20PC.pdf). 다나와 256GB 순차 속도 6,400/2,700 MB/s와 500K/600K IOPS는 기존 원문의 다른 용량 수치를 정정하는 근거다. 컴퓨존 중고 상품의 존재가 팝콘PC 공급품도 중고라는 뜻은 아니다.

### 쿨러

- PALADIN 400: [다나와](https://prod.danawa.com/info/?pcode=14110475), [컴퓨존](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=793267). 현재 235W 표기는 일치하지만 다나와는 변경 이력을 제공한다. 팬 및 보증 세부 표기도 서로 다르므로 TDP 숫자만으로 동일 공급 버전을 확정할 수 없다.
- DN-240 ARGB: [다나와](https://prod.danawa.com/info/?pcode=28485527), [컴퓨존 블랙 · 1077304](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1077304), [오마이PC · 4033](https://www.omypc.co.kr/products/4033). 컴퓨존 제품 요약의 290W는 **판매처 게시 사양**으로 수집한다. 제조사 확인이나 실측 시험으로 출처 등급을 높여 표시하지 않는다.
- Peerless Assassin 120 SE WHITE ARGB: [다나와](https://prod.danawa.com/info/?pcode=16852175), [컴퓨존](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=901025), [오마이PC](https://www.omypc.co.kr/products/2659), [제조사](https://www.thermalright.com/product/peerless-assassin-120-se-white-argb/). 다나와에는 AM5 추가 이력이 있다. 오마이PC의 구형 소켓 표를 최신 제조사 목록보다 우선하지 않는다. 커뮤니티 글의 TDP를 공식 수치로 가져오지 않는다.
- MSI A13 360: [다나와](https://prod.danawa.com/info/?pcode=76512596), [컴퓨존](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1215437), [오마이PC](https://www.omypc.co.kr/products/5697), [MSI 사양](https://www.msi.com/Liquid-Cooling/MAG-CORELIQUID-A13-360/Specification). LGA1200/115x 지원 차이는 기록해야 한다. 현재 연관 구성 P128594의 CPU는 LGA1851이므로 구형 소켓 표기 차이가 이 구성의 직접적인 장착 실패를 뜻하지는 않는다.
- SF 360 ARGB 블랙: [다나와](https://prod.danawa.com/info/?pcode=106721621), [컴퓨존](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1325835). 화이트: [다나와](https://prod.danawa.com/info/?pcode=106721630), [컴퓨존](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1325836). [오마이PC 공통 모델](https://www.omypc.co.kr/products/6615). 확인한 표의 397/394mm 차이는 미해결이다. 모델명의 360은 360W 냉각 능력을 뜻하지 않는다.
- ABKO 120X4: [다나와](https://prod.danawa.com/info/?pcode=65914526), [컴퓨존 상품 링크](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1174747). 컴퓨존 측 소켓 정보는 이번 상세 페이지 재열람 실패로 검색 노출 수준의 근거다. P119302는 등록된 소켓 목록 기준 우선 제외 상태이나 물리적 비호환 확정으로 고객에게 설명하지 않는다.

### 기본 포함 쿨러

- [다나와 5500GT 멀티팩](https://prod.danawa.com/info/?pcode=54218171), [컴퓨존 5500GT 멀티팩](https://www.compuzone.co.kr/product/product_detail.htm?ProductNo=1146524), [오마이PC 5500GT 완제품 구성](https://www.omypc.co.kr/products/1597). Wraith Stealth라는 구체적인 식별 후보를 얻었다. 실제 팝콘PC BOM은 아직 ‘기본 포함’ 자리여서, P113193·P113334·P113838·P113843·P120220의 공급 패키지를 확인해야 한다.

## 기존 조사에서 달라진 점

[직전 공식 자료 조사](pc-catalog-enrichment-20260930.md)의 ‘숫자형 쿨러 TDP 미확인 6종 / 13개 구성’은 당시 조사 범위의 결과다. 이번에는 DN-240 290W와 PALADIN 400 현행 235W를 판매처에서 찾았다. 따라서 6종 모두를 ‘어디서도 자료를 구할 수 없음’으로 해석하면 안 된다.

- DN-240은 P90622 한 구성의 보완 근거로 사용할 수 있다.
- PALADIN 400은 P112854 한 구성과 관련되지만 공급 버전 대조가 남는다.
- 나머지 4종(화이트/블랙 SF 각각 포함)은 확인한 판매 사양표에서 숫자 TDP를 확보하지 못했다. 11개 관련 구성에 다른 냉각 검증 근거가 필요하다.
- 메인보드 27개 구성, SSD 16개 구성의 정정 근거가 강화됐다. 합집합은 31개이며 위 수와 단순 합산하지 않는다.
- 외장 GPU가 없는 19개 구성의 길이·전력 unknown은 판매처 자료 부족과 별개인 규칙 적용 문제다. 그중 4개(N02~N05)는 이 사유만 남아 있다.

위 수는 기존 스냅샷의 연관 관계다. 새 자료를 DB에 반영한 뒤 재평가하기 전에는 해소 개수로 보고하지 않는다.

## 권장 반영 순서

1. DN-240 290W를 판매처 출처·조회일·정확한 모델과 함께 보완한다. 기존 값이 비었는지 확인하고 백업·변경 이력·제품군 설명 동기화 후 재평가한다.
2. 보드의 DVI 오류와 SSD의 용량별 속도 오류는 모델 수준의 정정으로 처리한다. 실제 리비전/P/N 확인 과제를 사양 오류와 구분해 남긴다. 모든 설명을 통째로 ‘보완 필요’로 묶는 대신 해당 단자/속도가 고객 조건에 필요한지도 검토한다.
3. PALADIN 버전, ABKO 브래킷, SF 360 치수, 기본 쿨러 모델은 공급품 사진·포장·발주 기록과 대조한다. MSI 구형 소켓은 현행 지원과 분리한다.
4. 숫자 TDP를 공개하지 않는 쿨러는 제조사 CPU 지원 또는 조건이 명시된 부하 시험으로 검토할 수 있게 근거 종류를 확장한다. 누락값을 0이나 임의의 높은 값으로 채우지 않는다.
5. 내장그래픽 구성에는 외장 GPU 전용 검사 적용 여부를 먼저 판정하도록 개선한다. 전원 용량 검토 자체를 없애지는 않는다.

판매처의 가격·재고·보증은 이 조사로 팝콘PC의 판매 조건에 덮어쓰지 않는다. 고객에게는 읽기 쉬운 제품 설명을 제공하고, 상세 출처·충돌·조회일은 관리자가 확인할 근거로 보관한다.
