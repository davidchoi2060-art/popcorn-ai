-- seed_0011: 슬라이스 24 — 사양 행 부재 상품(P-1002)의 사양 검수 유입 (재실행 안전)
-- 배경: 슬라이스 23 검증에서 P-1002가 검수·가격·재고·품절 해제를 다 갖춰도 추천 풀에
-- 미진입함을 발견 — 원인은 product_specs 행 자체의 부재(추천 뷰가 specs를 조인).
-- 시드 데이터 유래 예외이며(신규 등록 API는 specs 행을 함께 만든다), 이 시드가 그 공백을 메운다.
--
-- 정직 설계: specs 행을 값 NULL로 만들되 products.review_required_yn=true로 올려
-- **검수 완료 전까지 풀에서 제외**한다(ERD §3.5 "검수 대상 필드는 확정 전 NULL 유지" +
-- §7.2 게이트). 값이 비어 있는 사양으로 호환 판정에 쓰이는 일을 막는 것이 목적.
-- CPU 필수 사양 = socket, tdp_watt (api REQUIRED_SPEC_FIELDS). 지식 추정값은 실측이 아니라
-- 대조 후보이며 confidence로 표기한다(라이젠7 7700 = AM5 / 65W).

INSERT INTO product_specs (product_code, part_type, extract_source, confidence, verified_yn)
SELECT 20481002, 'CPU', 'ai_text', 0.70, false
 WHERE NOT EXISTS (SELECT 1 FROM product_specs WHERE product_code = 20481002);

UPDATE products SET review_required_yn = true, updated_at = now()
 WHERE product_code = 20481002
   AND EXISTS (SELECT 1 FROM product_specs WHERE product_code = 20481002 AND socket IS NULL);

INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20481002, 'spec_missing', 'socket',
       '사양 행 부재 상품 — 원문 사양 없음. 지식 대조 추정 AM5(라이젠 7000 시리즈 기준) — CPU·보드 호환 판정의 기준 필수 사양',
       NULL, 'AM5', 0.74, now()
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code = 20481002 AND review_type = 'spec_missing' AND field_name = 'socket');

INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20481002, 'spec_missing', 'tdp_watt',
       '사양 행 부재 상품 — 원문 사양 없음. 지식 대조 추정 65W(비X 모델 기준) — 쿨러·파워 여유 계산 필수 사양',
       NULL, '65', 0.71, now()
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code = 20481002 AND review_type = 'spec_missing' AND field_name = 'tdp_watt');
