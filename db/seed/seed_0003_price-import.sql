-- seed_0003_price-import.sql — ADM-PRC-040 단가표 일일 반영 슬라이스 시드 (2026-07-23)
-- 전제: seed.sql + seed_0002 적용된 DB에 실행. 재실행 안전(전 구문 가드).
-- 스키마 무변경(마이그레이션 불요). file_id는 시리얼 가정 금지 — supplier_id+file_name 자연키로 조회.
--
-- 부작용(의도됨): P-4821 공급처 수 1→2, P-2001 danawa_code 채움.
--   반영 데모 실행 시 P-1001 sale 239000→214000, P-4821 398000→360000으로 바뀜(undo로 복원 가능).
-- 한계(의도됨): model_key = 모델명 원문(정규화는 파싱 슬라이스 소관).

BEGIN;

-- 1) 오늘 수신 파일 2건 ('대기')
INSERT INTO supplier_price_files (supplier_id, file_name, received_at, row_count, status)
SELECT 1, 'MSI_단가표0723MTF.xlsx', now(), 4, '대기'
 WHERE NOT EXISTS (SELECT 1 FROM supplier_price_files WHERE supplier_id=1 AND file_name='MSI_단가표0723MTF.xlsx');
INSERT INTO supplier_price_files (supplier_id, file_name, received_at, row_count, status)
SELECT 2, 'GBT PCD VGA MB 단가표 0723클릭.xlsx', now(), 8, '대기'
 WHERE NOT EXISTS (SELECT 1 FROM supplier_price_files WHERE supplier_id=2 AND file_name='GBT PCD VGA MB 단가표 0723클릭.xlsx');

-- 2) baseline rows — 기존 파일(f1 MSI 7일 전 / f2 GBT 2일 전, seed.sql의 '반영 완료' 파일)
--    ※ f2 파일명에 공백 2개 있음 — 원문 그대로.
INSERT INTO supplier_price_rows (file_id, model_name, danawa_code, prices, cost_price, supply_state, memo)
SELECT f.file_id, v.mn, v.dc, v.pr::jsonb, v.cp, v.st, v.mm
FROM (SELECT file_id FROM supplier_price_files WHERE supplier_id=1 AND file_name='MSI_단가표0716MTF.xlsx') f,
 (VALUES
   ('AMD 라이젠5 7600 (정품)', NULL, '{"판매가(윈윈,셀프로)":215000}', 215000, '가능', NULL),
   ('이엠텍 RTX 4060 STORM X2 WHITE', NULL, '{"판매가(윈윈,셀프로)":360000}', 360000, '품절', NULL),
   ('MSI MAG B850 토마호크 맥스 WIFI', NULL, '{"판매가(윈윈,셀프로)":312000}', 312000, '가능', NULL)
 ) AS v(mn, dc, pr, cp, st, mm)
WHERE NOT EXISTS (SELECT 1 FROM supplier_price_rows r WHERE r.file_id=f.file_id AND r.model_name=v.mn);

INSERT INTO supplier_price_rows (file_id, model_name, danawa_code, prices, cost_price, supply_state, memo)
SELECT f.file_id, v.mn, v.dc, v.pr::jsonb, v.cp, v.st, v.mm
FROM (SELECT file_id FROM supplier_price_files WHERE supplier_id=2 AND file_name='GBT PCD VGA MB 단가표  0721클릭.xlsx') f,
 (VALUES
   ('LG 울트라기어 27GS75Q QHD 180Hz', NULL, '{"공급가":296000,"현금/딜러몰":301000}', 296000, '가능', NULL),
   ('이엠텍 RTX 4060 STORM X2 WHITE', NULL, '{"공급가":365000,"현금/딜러몰":369000}', 365000, '품절', NULL),
   ('GA-B860M AORUS ELITE', NULL, '{"공급가":224000,"현금/딜러몰":228000}', 224000, '가능', NULL),
   ('GA-Z790 AORUS ELITE AX', NULL, '{"공급가":359000,"현금/딜러몰":364000}', 359000, '가능', NULL),
   ('GIGABYTE UD850GM PG5', NULL, '{"공급가":109000,"현금/딜러몰":112000}', 109000, '가능', NULL)
 ) AS v(mn, dc, pr, cp, st, mm)
WHERE NOT EXISTS (SELECT 1 FROM supplier_price_rows r WHERE r.file_id=f.file_id AND r.model_name=v.mn);

-- 3) 오늘 rows — f4 MSI: chg 2 · stat 1 · nw 1(none) · same 1
INSERT INTO supplier_price_rows (file_id, model_name, danawa_code, prices, cost_price, supply_state, memo)
SELECT f.file_id, v.mn, v.dc, v.pr::jsonb, v.cp, v.st, v.mm
FROM (SELECT file_id FROM supplier_price_files WHERE supplier_id=1 AND file_name='MSI_단가표0723MTF.xlsx') f,
 (VALUES
   ('AMD 라이젠5 7600 (정품)', NULL, '{"판매가(윈윈,셀프로)":209000}', 209000, '가능', '0723 가격변동'),
   ('이엠텍 RTX 4060 STORM X2 WHITE', NULL, '{"판매가(윈윈,셀프로)":352000}', 352000, '가능', '재입고'),
   ('MSI MAG B850 토마호크 맥스 WIFI', NULL, '{"판매가(윈윈,셀프로)":312000}', 312000, '가능', NULL),
   ('PRO H810M-E', NULL, '{"판매가(윈윈,셀프로)":111000}', 111000, '가능', '신규')
 ) AS v(mn, dc, pr, cp, st, mm)
WHERE NOT EXISTS (SELECT 1 FROM supplier_price_rows r WHERE r.file_id=f.file_id AND r.model_name=v.mn);

-- 4) 오늘 rows — f3 GBT: chg 3(P-7101 / P-4821 alt / UD850GM sub·미매칭) · stat 2 · nw 3(code/sim/none) · same 1
INSERT INTO supplier_price_rows (file_id, model_name, danawa_code, prices, cost_price, supply_state, memo)
SELECT f.file_id, v.mn, v.dc, v.pr::jsonb, v.cp, v.st, v.mm
FROM (SELECT file_id FROM supplier_price_files WHERE supplier_id=2 AND file_name='GBT PCD VGA MB 단가표 0723클릭.xlsx') f,
 (VALUES
   ('LG 울트라기어 27GS75Q QHD 180Hz', NULL, '{"공급가":289000,"현금/딜러몰":294000}', 289000, '가능', '0723 인하'),
   ('이엠텍 RTX 4060 STORM X2 WHITE', NULL, '{"공급가":362000,"현금/딜러몰":366000}', 362000, '가능', '재입고'),
   ('GA-B860M AORUS ELITE', NULL, '{"공급가":224000,"현금/딜러몰":228000}', 224000, '가능', NULL),
   ('GA-Z790 AORUS ELITE AX', NULL, '{"공급가":359000,"현금/딜러몰":364000}', 359000, '품절', '인상 품절'),
   ('GIGABYTE UD850GM PG5', NULL, '{"공급가":null,"현금/딜러몰":105000}', 105000, '가능', '공급가 결측'),
   ('GA-Z890I AORUS ULTRA', '69699695', '{"공급가":469000,"현금/딜러몰":475000}', 469000, '가능', '신규'),
   ('삼성 오디세이 G5 G51C 32인치', NULL, '{"공급가":318000,"현금/딜러몰":323000}', 318000, '가능', '신규'),
   ('W790 AI TOP', NULL, '{"공급가":1407000,"현금/딜러몰":1420000}', 1407000, '가능', '신규')
 ) AS v(mn, dc, pr, cp, st, mm)
WHERE NOT EXISTS (SELECT 1 FROM supplier_price_rows r WHERE r.file_id=f.file_id AND r.model_name=v.mn);

-- 5) 기억된 모델↔SKU 매핑 (1회 확정 후 매일 자동 — ERD §11 매칭 1순위)
INSERT INTO supplier_product_map (supplier_id, model_key, product_code, match_method, confirmed_by, confirmed_at)
SELECT v.s, v.mk, v.pc, 'manual', 1, now()
FROM (VALUES
   (1, 'AMD 라이젠5 7600 (정품)', 20481001),
   (1, '이엠텍 RTX 4060 STORM X2 WHITE', 20484821),
   (2, 'LG 울트라기어 27GS75Q QHD 180Hz', 20487101),
   (2, '이엠텍 RTX 4060 STORM X2 WHITE', 20484821)
 ) AS v(s, mk, pc)
WHERE NOT EXISTS (SELECT 1 FROM supplier_product_map m WHERE m.supplier_id=v.s AND m.model_key=v.mk);

-- 6) P-4821 타 공급처 가격 (alt 데모) — 불변식 유지: '가능' 없음 → 전체 최저 360000 = 기존 purchase_price
INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state, src_file_id)
SELECT 20484821, 2, 365000, '품절',
       (SELECT file_id FROM supplier_price_files WHERE supplier_id=2 AND file_name='GBT PCD VGA MB 단가표  0721클릭.xlsx')
 WHERE NOT EXISTS (SELECT 1 FROM product_supplier_prices WHERE product_code=20484821 AND supplier_id=2);

-- 7) 다나와 코드 교차 매칭 키 (nw 'code' 데모 — 목업의 P-2101은 시드에 없어 P-2001로 대체)
UPDATE products SET danawa_code='69699695', updated_at=now()
 WHERE product_code=20482001 AND danawa_code IS NULL;

COMMIT;
