-- seed_0005_quote-engine.sql — S2 견적 생성 엔진 v1 슬라이스 시드 (2026-07-23)
-- 전제: seed.sql + 0002~0004 적용된 DB. 재실행 안전(전 구문 가드). 스키마 무변경.
--
-- 목적: 3구성(가성비/추천/고성능) 차별화 — CPU·GPU·RAM·SSD·POWER 티어 부품 확충.
--   전부 AM5/DDR5 정합. 4070 SUPER(요구 700W)를 위해 750W 파워 필수.
--   기존 검수·품절 서사 행 절대 불변 (P-1004는 '7700X' — P-1002 '7700' 품절 서사와 이름 충돌 회피).
--
-- 부작용(의도됨): 상품 목록 19→28행(kpis ok 13→22 — 신규 8종+SSD 상위 1종), S1 카운터 total 9→18
--   (슬라이스 4 기대값 매트릭스 수치 갱신됨). 검수 큐(대기 5)·단가표 데모 무영향.

BEGIN;

-- 1) 신규 8종
INSERT INTO products (product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty)
SELECT v.* FROM (VALUES
  (20481003,'P-1003','AMD 라이젠5 7500F (정품)','AMD','CPU','core_part','판매중',true,false,172000,191000,15),
  (20481004,'P-1004','AMD 라이젠7 7700X (정품)','AMD','CPU','core_part','판매중',true,false,306000,339000,9),
  (20483002,'P-3002','삼성 DDR5-5600 8GB','삼성','RAM','core_part','판매중',true,false,25000,29000,80),
  (20483003,'P-3003','삼성 DDR5-5600 32GB','삼성','RAM','core_part','판매중',true,false,86000,95000,40),
  (20484102,'P-4102','갤럭시 GALAX RTX 4060 2X','갤럭시','GPU','core_part','판매중',true,false,322000,355000,11),
  (20484103,'P-4103','MSI RTX 4070 SUPER 벤투스 2X','MSI','GPU','core_part','판매중',true,false,552000,610000,5),
  (20486102,'P-6102','WD Blue SN580 500GB','WD','SSD','core_part','판매중',true,false,48000,55000,35),
  (20483402,'P-3402','시소닉 FOCUS GX-750','시소닉','POWER','core_part','판매중',true,false,126000,139000,12)
 ) AS v(product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty)
WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_code=v.product_code);

-- 2) 신규 8종 specs (필수 필드 전부, verified)
INSERT INTO product_specs (product_code, part_type, socket, tdp_watt, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20481003,'CPU','AM5',65,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20481003);
INSERT INTO product_specs (product_code, part_type, socket, tdp_watt, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20481004,'CPU','AM5',105,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20481004);

INSERT INTO product_specs (product_code, part_type, mem_type, capacity_gb, clock_mhz, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20483002,'RAM','DDR5',8,5600,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20483002);
INSERT INTO product_specs (product_code, part_type, mem_type, capacity_gb, clock_mhz, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20483003,'RAM','DDR5',32,5600,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20483003);

INSERT INTO product_specs (product_code, part_type, length_mm, required_power_watt, pcie_gen, tdp_watt, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20484102,'GPU',250,550,'4.0',115,false,false,true,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20484102);
INSERT INTO product_specs (product_code, part_type, length_mm, required_power_watt, pcie_gen, tdp_watt, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20484103,'GPU',242,700,'4.0',220,false,false,false,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20484103);

INSERT INTO product_specs (product_code, part_type, form_factor, interface, capacity_gb, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20486102,'SSD','M.2 2280','NVMe',500,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20486102);

INSERT INTO product_specs (product_code, part_type, rated_watt, form_factor, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20483402,'POWER',750,'ATX',false,false,true,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20483402);

-- 3) SSD 상위 티어 — 신규 상품으로 추가.
--    (계획 초안의 "P-6012 specs 보강"은 오류: P-6012는 seed_0002에서 검수 대상(review_required)으로
--     전환된 상품이라 뷰 편입 불가·편입 시 검수 큐 데모 파괴 — 동일 가격의 별도 상품으로 대체)
INSERT INTO products (product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty)
SELECT 20486103,'P-6103','SK하이닉스 Platinum P41 2TB','SK하이닉스','SSD','core_part','판매중',true,false,197000,219000,13
 WHERE NOT EXISTS (SELECT 1 FROM products WHERE product_code=20486103);
INSERT INTO product_specs (product_code, part_type, form_factor, interface, capacity_gb, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20486103,'SSD','M.2 2280','NVMe',2000,false,false,false,'rule',0.98,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20486103);

COMMIT;
