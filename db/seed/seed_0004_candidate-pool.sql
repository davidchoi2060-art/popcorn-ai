-- seed_0004_candidate-pool.sql — S1 후보 풀 카운터(엔진 v0) 슬라이스 시드 (2026-07-23)
-- 전제: seed.sql + 0002 + 0003 적용된 DB. 재실행 안전(전 구문 가드). 스키마 무변경.
--
-- 목적: v_recommendation_candidates ∧ stock_qty>0 통과가 2행뿐이라 필터 델타 시연 불가 →
--   P-2001 specs 보강 + 추천 가능 신규 6종(태그 포함)으로 total=9 구성.
--   기존 검수 서사 행(P-5140·P-4821·P-3390·P-7102·P-6012)은 절대 불변.
--
-- 부작용(의도됨): 상품 목록 13→19행(kpis ok 7→13), P-2001 사양 4/4, S1 카운터 total=9.
--   검수 큐(대기 5)·단가표 데모 무영향.

BEGIN;

-- 1) P-2001 specs 보강 (MB 필수 4필드 — 뷰 JOIN 탈락 해소)
INSERT INTO product_specs (product_code, part_type, socket, chipset, form_factor, mem_type, extract_source, confidence, verified_yn)
SELECT 20482001, 'MB', 'AM5', 'B650', 'M-ATX', 'DDR5', 'rule', 0.98, true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20482001);

-- 2) 추천 가능 신규 6종 (판매중·ai_candidate·비검수·재고 보유)
INSERT INTO products (product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty)
SELECT v.* FROM (VALUES
  (20484101,'P-4101','이엠텍 RTX 4060 Ti STORM X2','이엠텍','GPU','core_part','판매중',true,false,405000,428000,7),
  (20486101,'P-6101','솔리다임 P44 Pro 1TB','솔리다임','SSD','core_part','판매중',true,false,104000,115000,26),
  (20483401,'P-3401','시소닉 FOCUS GX-650','시소닉','POWER','core_part','판매중',true,false,86000,95000,14),
  (20488101,'P-8101','앱코 NCORE 화이트','앱코','CASE','core_part','판매중',true,false,47000,54000,21),
  (20488102,'P-8102','다크플래쉬 DK351 블랙','다크플래쉬','CASE','core_part','판매중',true,false,37000,43000,18),
  (20489101,'P-9101','딥쿨 AK400','딥쿨','COOLER_CPU_AIR','core_part','판매중',true,false,29000,35000,33)
 ) AS v(product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty)
WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_code=v.product_code);

-- 3) 신규 6종 specs (api 필수맵·ERD §5 양쪽 충족, 태그 명시 — v0 태그 필터 데모)
INSERT INTO product_specs (product_code, part_type, length_mm, required_power_watt, pcie_gen, tdp_watt, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20484101,'GPU',267,650,'4.0',160,false,false,false,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20484101);

INSERT INTO product_specs (product_code, part_type, form_factor, interface, capacity_gb, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20486101,'SSD','M.2 2280','NVMe',1000,false,false,false,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20486101);

INSERT INTO product_specs (product_code, part_type, rated_watt, form_factor, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20483401,'POWER',650,'ATX',false,false,true,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20483401);

INSERT INTO product_specs (product_code, part_type, form_factor, gpu_max_mm, cooler_height_mm, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20488101,'CASE','M-ATX',330,165,true,false,false,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20488101);

INSERT INTO product_specs (product_code, part_type, form_factor, gpu_max_mm, cooler_height_mm, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20488102,'CASE','M-ATX',335,168,false,false,true,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20488102);

INSERT INTO product_specs (product_code, part_type, socket, cooler_height_mm, cooler_tdp, tag_white, tag_rgb, tag_silent, extract_source, confidence, verified_yn)
SELECT 20489101,'COOLER_CPU_AIR','AM5',155,220,false,false,true,'rule',0.97,true
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20489101);

COMMIT;
