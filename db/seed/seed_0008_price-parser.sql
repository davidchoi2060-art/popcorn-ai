-- seed_0008: 슬라이스 14 — 단가표 엑셀 실파일 파싱용 프리셋 rules 확장 (재실행 안전 UPDATE)
-- 실파일 구조 실측(GBT 0721클릭·MSI 0716MTF) 기반. 스키마 무개정 — rules(JSONB)만 갱신.
-- 신규 키: file_pattern(공급처 인식)·model_col(+fallback)·state_col·memo_col.
-- MSI sheets.exclude에 저장장치·파워-쿨러 추가(이질 레이아웃 — v2 이관, 응답에 정직 표기).
-- MSI price_cols는 실파일 헤더 정규화 키(공백·개행 제거)와 정합하도록 교정.

UPDATE supplier_presets SET rules = rules || '{
  "file_pattern": "MSI_단가표",
  "model_col": "다나와 상품명",
  "model_col_fallback": "MKT NAME",
  "state_col": "비고",
  "memo_col": "비고",
  "sheets": {"exclude": ["Sheet3", "가격지도", "저장장치", "파워-쿨러"]},
  "price_cols": ["판매가(윈윈,셀프로)", "대형몰딜러가/비노출카드할인가", "카드노출가"]
}'::jsonb
WHERE supplier_id = 1;

UPDATE supplier_presets SET rules = rules || '{
  "file_pattern": "GBT",
  "model_col": "모델명",
  "state_col": "재고현황",
  "memo_col": "비고"
}'::jsonb
WHERE supplier_id = 2;
