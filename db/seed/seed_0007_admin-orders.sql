-- seed_0007_admin-orders.sql — ADM-ORD-020 슬라이스: 시드 주문 1(ORD-84216) 라벨 백필 (2026-07-24)
-- 전제: seed.sql~0006 적용된 DB. 재실행 안전(멱등 UPDATE). 스키마 무변경.
-- 목적: order 1의 core 7행이 spec_snap NULL이라 상세 라벨이 전부 "구성"으로 렌더 →
--   목업의 부품별 라벨(CPU/GPU/…)을 재현하도록 part_type만 백필. 가격·이름 등 스냅샷 불변.

BEGIN;

UPDATE order_items SET spec_snap='{"part_type":"CPU"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE 'Intel Core%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"GPU"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%RTX 4070%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"MB"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%Z790%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"RAM"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%DDR5-5600%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"SSD"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%990 PRO%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"POWER"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%FOCUS GX%' AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"CASE"}'::jsonb
 WHERE order_id=1 AND item_kind='core_part' AND name_snap LIKE '%H5 Flow%' AND spec_snap IS NULL;

-- 주변기기 2행 (시드 INSERT에 spec_snap 컬럼 자체가 없었음 — "모니터(함께 구성)" 라벨 재현)
UPDATE order_items SET spec_snap='{"part_type":"MONITOR"}'::jsonb
 WHERE order_id=1 AND item_kind='peripheral' AND product_code=20487101 AND spec_snap IS NULL;
UPDATE order_items SET spec_snap='{"part_type":"MOUSE"}'::jsonb
 WHERE order_id=1 AND item_kind='peripheral' AND product_code=20487202 AND spec_snap IS NULL;

COMMIT;
