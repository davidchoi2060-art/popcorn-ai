-- seed_0012: 슬라이스 33 — 안전재고 기준 설정 + 기존 매입가 이력의 공급처 백필 (재실행 안전)
-- 그동안 "안전재고 미달"은 화면 연출이었다(stock-inbound 배지·sourcing 자동 등록 문구).
-- 마이그레이션 0004로 products.safety_stock이 생겼으므로 기준을 넣어 실판정으로 전환한다.
--
-- 기준 산정(운영 정책이 아니라 dev 시연용 초기값 — 실 운영 시 카테고리·회전율로 재산정):
--   GPU·POWER = 6  (견적 병목 부품 — 품절이 곧 견적 실패로 이어지므로 여유를 크게)
--   그 외 핵심 부품 = 3   · 주변기기 = 2   · 서비스·조립 등 = 미설정(NULL)
-- 미설정(NULL)은 "미달 판정 대상 아님" — 서비스 라인처럼 재고 개념이 없는 항목을 위한 값.
-- 차등 근거: candidate-pool의 얇은 카테고리 경고가 GPU·파워에 걸린다(전력·장착 제약의 병목).

UPDATE products SET safety_stock = 6, updated_at = now()
 WHERE category_group = 'core_part'
   AND part_type IN ('GPU','POWER')
   AND status NOT IN ('단종','삭제대기')
   AND (safety_stock IS NULL OR safety_stock = 3);

UPDATE products SET safety_stock = 3, updated_at = now()
 WHERE category_group = 'core_part'
   AND part_type NOT IN ('GPU','POWER')
   AND status NOT IN ('단종','삭제대기')
   AND safety_stock IS NULL;

UPDATE products SET safety_stock = 2, updated_at = now()
 WHERE category_group = 'peripheral'
   AND status NOT IN ('단종','삭제대기')
   AND safety_stock IS NULL;

-- 기존 매입가 이력에 공급처 백필 — 그 시점 그 상품의 공급처를 남긴다.
-- product_supplier_prices에 단일 공급처만 있는 상품은 그 공급처로 확정할 수 있다.
-- 복수 공급처 상품은 추정이 되므로 건드리지 않는다(NULL 유지 = "출처 미기록" 정직).
UPDATE product_price_history h SET supplier_id = sole.supplier_id
  FROM (SELECT product_code, MIN(supplier_id) AS supplier_id
          FROM product_supplier_prices
         GROUP BY product_code
        HAVING COUNT(*) = 1) sole
 WHERE h.product_code = sole.product_code
   AND h.field = 'purchase'
   AND h.supplier_id IS NULL;
