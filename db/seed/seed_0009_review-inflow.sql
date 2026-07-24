-- seed_0009: 슬라이스 18 — 편입산 신규 상품(P-9102)의 검수 유입 재현 (재실행 안전)
-- 단가표發 등록 상품은 사양이 전부 NULL(§3.5) — 검수 유입의 정식 주체(CSV/AI 사양 파이프라인,
-- ERD §8 T0·T1)는 미구현이라 유입만 시드로 재현한다. 값은 지식 대조 '추정치'(실측 아님 —
-- confidence 0.6대·출고 시 실측 리포트 서사)이며 origin_value NULL = 단가표에는 사양이 없음(정직).
-- GPU 필수 필드 = api REQUIRED_SPEC_FIELDS 기준 3종(length_mm·required_power_watt·pcie_gen).

INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20489102,'spec_missing','length_mm',
       '단가표發 신규 등록 — 원문 사양 없음. 지식 대조 추정 272mm(동급 AERO OC 시리즈 기준) — 케이스 호환 판정 필수 사양',
       NULL,'272',0.62, now()
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code=20489102 AND review_type='spec_missing' AND field_name='length_mm');

INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20489102,'spec_missing','required_power_watt',
       '단가표發 신규 등록 — 원문 사양 없음. 지식 대조 추정 450W(제조사 권장 시스템 파워) — 전력 여유 계산 필수 사양',
       NULL,'450',0.66, now()
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code=20489102 AND review_type='spec_missing' AND field_name='required_power_watt');

INSERT INTO product_reviews (product_code, review_type, field_name, detail, origin_value, suggested_value, confidence, created_at)
SELECT 20489102,'spec_missing','pcie_gen',
       '단가표發 신규 등록 — 원문 사양 없음. 지식 대조 추정 PCIe 5.0 x8(RTX 5060 Ti 세대 기준) — 보드 호환 참고 사양',
       NULL,'PCIe 5.0',0.68, now()
 WHERE NOT EXISTS (SELECT 1 FROM product_reviews
                    WHERE product_code=20489102 AND review_type='spec_missing' AND field_name='pcie_gen');
