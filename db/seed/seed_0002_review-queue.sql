-- seed_0002_review-queue.sql — ADM-PRD-020 검수 큐 슬라이스 시드 패치 (2026-07-23)
-- 전제: 0002 마이그레이션 적용 후, seed.sql이 들어간 DB에 1회 실행. 재실행 안전(가드 포함).
--
-- 원칙(ERD §7.2): 검수 대상 필드는 확정 전 product_specs에서 NULL 유지.
--   값은 큐행 origin/suggested에만 존재하고, 확정 액션이 비로소 specs에 쓴다.
--   spec_missing은 origin_value=NULL(원문에 없음이 정의), low_confidence는 suggested_value=NULL.
--
-- 부작용(의도됨): 검수 대기 5건. P-6012가 검수 대상으로 전환되어
--   상품 목록(ADM-PRD-010) kpis가 review 4→5 / ok 8→7, P-6012 사양 2/3로 바뀐다.

BEGIN;

-- 1) 기존 큐 3행에 값 컬럼 채움 (자연키 매칭 — review_id 시리얼 가정 금지)
UPDATE product_reviews SET suggested_value='DDR5', confidence=0.55,
  created_at=now()-interval '2 hours'
 WHERE product_code=20485140 AND review_type='spec_missing' AND field_name='mem_type';

UPDATE product_reviews SET origin_value='272', suggested_value='251', confidence=0.93,
  created_at=now()-interval '12 minutes'
 WHERE product_code=20484821 AND review_type='spec_conflict' AND field_name='length_mm';

UPDATE product_reviews SET suggested_value='165', confidence=0.62,
  created_at=now()-interval '38 minutes'
 WHERE product_code=20487102 AND review_type='spec_missing' AND field_name='refresh_hz';

-- 2) 신규 큐행 2건
--    P-3390: 목업 서사 유지 — 제목 500W vs 사양표 400W
INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20483390,'spec_conflict','rated_watt','제목 500W vs 상세 사양표 400W — 요구 전력 계산의 기준 필수 사양',
       '500','400',0.78, now()-interval '26 minutes'
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code=20483390 AND review_type='spec_conflict' AND field_name='rated_watt');

--    P-6012: 저신뢰 1건 (일괄 확정 데모용)
INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20486012,'low_confidence','capacity_gb','원문 표기 모호("2TB급") — 추출값 2000GB 신뢰도 0.71',
       '2000',NULL,0.71, now()-interval '55 minutes'
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code=20486012 AND review_type='low_confidence' AND field_name='capacity_gb');

-- 3) specs 보강 — 검수 대상 필드는 NULL 유지, 나머지 필수 필드는 채움
--    (api REQUIRED_SPEC_FIELDS와 ERD §5 매트릭스 양쪽을 만족하도록)
INSERT INTO product_specs (product_code, part_type, socket, chipset, form_factor, mem_type, extract_source, confidence, verified_yn)
SELECT 20485140,'MB','AM5','B650','M-ATX',NULL,'ai_text',0.55,false
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20485140);

INSERT INTO product_specs (product_code, part_type, tdp_watt, required_power_watt, pcie_gen, length_mm, extract_source, confidence, verified_yn)
SELECT 20484821,'GPU',115,550,'4.0',NULL,'ai_text',0.93,false
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20484821);

INSERT INTO product_specs (product_code, part_type, form_factor, rated_watt, extract_source, confidence, verified_yn)
SELECT 20483390,'POWER','ATX',NULL,'ai_text',0.78,false
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20483390);

INSERT INTO product_specs (product_code, part_type, form_factor, interface, capacity_gb, extract_source, confidence, verified_yn)
SELECT 20486012,'SSD','M.2 2280','NVMe',NULL,'ai_text',0.71,false
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code=20486012);

-- 4) P-6012 검수 대상 전환 (저신뢰 재검 — 추천 풀에서 임시 제외)
UPDATE products SET review_required_yn=true, ai_candidate_yn=false, updated_at=now()
 WHERE product_code=20486012;

COMMIT;
