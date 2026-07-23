-- 팝콘PC AI — 개발 시드 (목업 더미 데이터 이식, 2026-07-23)
-- 실행: psql "$DATABASE_URL" -f db/seed/seed.sql  (멱등 아님 — 빈 DB 전제)

BEGIN;

-- 운영자·익명 주체
INSERT INTO admin_operators (name, email, role) VALUES ('관리자', 'admin@popcornpc.local', 'owner');
INSERT INTO users (anon_key) VALUES ('seed-anon-1');

-- 운영 설정: 1단계 프리셋(전부 쇼핑몰 인계) — ops-settings 목업 기본값
INSERT INTO ops_settings (key, mode) VALUES
 ('member','own'), ('pay','mall'), ('settle','mall'), ('ship','mall'), ('refund','mall');
INSERT INTO ops_settings_history (changes, version, changed_by, reason)
 VALUES ('{"init":"1단계 전부 인계 프리셋"}', 1, 1, '초기 시드');

-- 가격 산정 파라미터 (카드수수료 2.2%는 예시값 — 실요율 확정 시 갱신)
INSERT INTO pricing_settings (card_fee_rate, margin_rate, effective_from, created_by)
 VALUES (0.0220, 0, now(), 1);

-- 공급처 + 프리셋 (실파일 2종 검증분)
INSERT INTO suppliers (name, platform, brands) VALUES
 ('MSI(웨이코스)', '윈윈', 'MSI'),
 ('클릭나라', NULL, 'GIGABYTE(PCD)');
INSERT INTO supplier_presets (supplier_id, rules) VALUES
 (1, '{"sheets":{"exclude":["Sheet3","가격지도"]},"header_rows":2,"carry_forward":["CHIPSET"],"price_cols":["판매가(윈윈,셀프로)","대형몰딜러가","카드노출가"],"cost_rule":"min_price","state_map":{"품절":"품절","가능":"가능","문의":"문의"}}'),
 (2, '{"sheets":{"exclude":[]},"header_rows":3,"carry_forward":["칩셋"],"price_cols":["공급가","현금/딜러몰","카드몰"],"cost_rule":"min_price","state_map":{"O":"가능","X":"품절"},"danawa_code_col":"다나와상품코드"}');

-- 상품 (관리자 상품 목록 데모 — product_code=자체상품번호, sku=P-xxxx)
INSERT INTO products (product_code, sku, product_name, maker, part_type, category_group, status, ai_candidate_yn, review_required_yn, purchase_price, sale_price, stock_qty, supplier) VALUES
 (20481001,'P-1001','AMD 라이젠5 7600 (정품)','AMD','CPU','core_part','판매중',true,false,215000,239000,12,'MSI(웨이코스)'),
 (20481002,'P-1002','AMD 라이젠7 7700 (정품)','AMD','CPU','core_part','품절',true,false,325000,359000,0,NULL),
 (20482001,'P-2001','ASUS PRIME B650M-A II','ASUS','MB','core_part','판매중',true,false,128000,142000,8,NULL),
 (20485140,'P-5140','ASRock B650M PG Lightning','ASRock','MB','core_part','판매중',false,true,115000,128000,15,NULL),
 (20483001,'P-3001','삼성 DDR5-5600 16GB','삼성','RAM','core_part','판매중',true,false,46000,52000,64,NULL),
 (20484821,'P-4821','이엠텍 RTX 4060 STORM X2 WHITE','이엠텍','GPU','core_part','판매중',false,true,360000,398000,6,NULL),
 (20486012,'P-6012','삼성 990 PRO 2TB','삼성','SSD','core_part','판매중',true,false,198000,219000,31,NULL),
 (20483390,'P-3390','마이크로닉스 Classic II 500W','마이크로닉스','POWER','core_part','판매중',false,true,44000,49000,18,NULL),
 (20487101,'P-7101','LG 울트라기어 27GS75Q QHD 180Hz','LG','MONITOR','peripheral','판매중',true,false,296000,329000,9,NULL),
 (20487102,'P-7102','삼성 오디세이 G5 G51C 32형','삼성','MONITOR','peripheral','판매중',false,true,322000,359000,5,NULL),
 (20487201,'P-7201','앱코 K660 축교환 기계식','앱코','KEYBOARD','peripheral','판매중',true,false,31000,39000,44,NULL),
 (20487202,'P-7202','로지텍 G102 LIGHTSYNC','로지텍','MOUSE','peripheral','판매중',true,false,18000,23000,120,NULL),
 (20487301,'P-7301','하이퍼엑스 Cloud III','하이퍼엑스','HEADSET','peripheral','판매중',true,false,99000,119000,17,NULL);

-- 사양 (일부 — 후보 뷰 검증용)
INSERT INTO product_specs (product_code, part_type, socket, tdp_watt, verified_yn, extract_source, confidence) VALUES
 (20481001,'CPU','AM5',65,true,'rule',0.98);
INSERT INTO product_specs (product_code, part_type, mem_type, capacity_gb, clock_mhz, verified_yn) VALUES
 (20483001,'RAM','DDR5',16,5600,true);
INSERT INTO product_specs (product_code, part_type, size_inch, resolution, refresh_hz, panel, ports, connection, verified_yn) VALUES
 (20487101,'MONITOR',27.0,'QHD',180,'IPS','{"dp":1,"hdmi":2}','유선',true),
 (20487102,'MONITOR',32.0,'QHD',NULL,'VA','{"dp":1,"hdmi":2}','유선',false);  -- 주사율 미확인 → 검수
INSERT INTO product_specs (product_code, part_type, switch_type, key_layout, connection, verified_yn) VALUES
 (20487201,'KEYBOARD','축교환','풀배열','유선',true);
INSERT INTO product_specs (product_code, part_type, connection, verified_yn) VALUES
 (20487202,'MOUSE','유선',true), (20487301,'HEADSET','유선',true);

-- 검수 큐 (모니터 주사율 케이스 포함)
INSERT INTO product_reviews (product_code, review_type, field_name, detail) VALUES
 (20485140,'spec_missing','mem_type','상세페이지에 메모리 규격 명시 없음 — 칩셋 기준 DDR5 추정(0.55)'),
 (20484821,'spec_conflict','length_mm','원문 272mm vs 지식 251mm — 케이스 호환 판정 필수 사양'),
 (20487102,'spec_missing','refresh_hz','주사율 미표기 — 함께 구성 GPU 매칭 근거(165Hz 시리즈 추정 0.62)');

-- 회원 (회원 관리 데모)
INSERT INTO members (user_id, email, nickname, joined_via, mall_member_id, created_at) VALUES
 (1,'mj.kim@example.com','김민준','email',NULL, now() - interval '13 days'),
 (NULL,'sy.lee@example.com','이서연','kakao','MALL-2201', now() - interval '33 days'),
 (NULL,'dy.park@example.com','박도윤','naver',NULL, now() - interval '29 days');

-- 주문 원장 (고객·관리자 화면 공통 데모 — ops_snapshot은 주문 시점 스위치)
INSERT INTO orders (order_no, member_id, channel, status, total_amount, ops_snapshot, created_at) VALUES
 ('ORD-84216',1,'own','조립중',2087000,'{"member":"own","pay":"own","settle":"own","ship":"own","refund":"mall"}', now()),
 ('ORD-84213',1,'own','배송중',812000,'{"member":"own","pay":"own","settle":"own","ship":"own","refund":"mall"}', now() - interval '9 days'),
 ('ORD-83907',2,'mall','완료',1284000,'{"member":"own","pay":"mall","settle":"mall","ship":"mall","refund":"mall"}', now() - interval '25 days'),
 ('ORD-83881',3,'mall','완료',452000,'{"member":"own","pay":"mall","settle":"mall","ship":"mall","refund":"mall"}', now() - interval '28 days');

INSERT INTO order_items (order_id, product_code, item_kind, name_snap, price_snap) VALUES
 (1,NULL,'core_part','Intel Core i7-14700K',580000),
 (1,NULL,'core_part','NVIDIA RTX 4070 Ti SUPER',420000),
 (1,NULL,'core_part','MSI MAG Z790 Tomahawk WiFi',250000),
 (1,NULL,'core_part','삼성 DDR5-5600 32GB (16×2)',120000),
 (1,NULL,'core_part','삼성 990 PRO 1TB NVMe',135000),
 (1,NULL,'core_part','시소닉 FOCUS GX-750 750W',110000),
 (1,NULL,'core_part','NZXT H5 Flow',90000),
 (1,NULL,'assembly_service','전문가 조립 · 선정리 · 24시간 검사',30000),
 (1,20487101,'peripheral','LG 울트라기어 27GS75Q',329000),
 (1,20487202,'peripheral','로지텍 G102 LIGHTSYNC',23000),
 (2,NULL,'core_part','라이젠5 7600 · RTX 4060 구성 (7종) + 조립·검수',812000),
 (3,NULL,'core_part','라이젠5 5600 · RTX 3060 구성 (7종) + 조립·검수',1284000),
 (4,NULL,'core_part','사무용 구성 (6종) + 조립·검수',452000);

INSERT INTO payments (order_id, pay_mode, method, pg_ref, amount, status, paid_at) VALUES
 (1,'own','신용카드','TX-88213',2087000,'승인', now()),
 (2,'own','신용카드','TX-87954',812000,'승인', now() - interval '9 days'),
 (3,'mall','쇼핑몰 결제',NULL,1284000,'승인', now() - interval '25 days'),
 (4,'mall','쇼핑몰 결제',NULL,452000,'승인', now() - interval '28 days');

INSERT INTO shipments (order_id, ship_mode, carrier, tracking_no, status, shipped_at) VALUES
 (2,'own','CJ대한통운','6482-1234-5678','배송중', now() - interval '2 days'),
 (3,'mall','CJ대한통운','6480-8821-3341','완료', now() - interval '22 days');

INSERT INTO refunds (order_id, refund_mode, reason_type, amount, status) VALUES
 (2,'mall','초기 불량',812000,'접수');

INSERT INTO stock_reservations (order_id, product_code, qty, status, expires_at) VALUES
 (1,20487101,1,'converted', now() + interval '1 day'),
 (1,20487202,1,'converted', now() + interval '1 day');

INSERT INTO stock_movements (product_code, movement_type, qty_delta, ref_kind, ref_id) VALUES
 (20487101,'own_sale',-1,'order',1),
 (20487202,'own_sale',-1,'order',1);

-- 후기 (구매 인증만 — order_item 연계)
INSERT INTO member_reviews (member_id, order_item_id, rating, body, status, cite_s2) VALUES
 (2,12,5,'조립 사진이랑 검사 리포트까지 같이 와서 놀랐어요. 왜 이 부품인지 설명해준 게 제일 좋았어요.','게시',true),
 (3,13,4,'사무용으로 조용하고 빠릅니다. 배송도 빨랐어요.','게시',false);

INSERT INTO member_favorites (member_id, product_code, price_alert) VALUES
 (1,20484821,true), (1,20487101,true), (2,20486012,false);

-- 상담 스냅샷 (팝콘톡 데모 — "그때 가격으로 다시 보기")
INSERT INTO consult_sessions (member_id, mode, constraints) VALUES
 (1,'talk','[{"l":"용도","v":"게임"},{"l":"예산","v":"100만원대"},{"l":"모니터","v":"32형 듀얼 보유"}]');
INSERT INTO quote_snapshots (session_id, quote_type, items, companion, total_amount) VALUES
 (1,'recommend','[{"slot":"CPU","name":"Ryzen 5 7500F","price":170000},{"slot":"GPU","name":"RTX 4060 8GB","price":398000}]',
  '[{"c":"모니터","n":"LG 울트라기어 27GS75Q","p":329000}]',1250000);

-- 공급처 가격 1:N (단가표 반영 데모)
INSERT INTO supplier_price_files (supplier_id, file_name, received_at, row_count, status) VALUES
 (1,'MSI_단가표0716MTF.xlsx', now() - interval '7 days', 174, '반영 완료'),
 (2,'GBT PCD VGA MB 단가표  0721클릭.xlsx', now() - interval '2 days', 246, '반영 완료');
INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state, src_file_id) VALUES
 (20481001,1,215000,'가능',1),
 (20484821,1,360000,'품절',1),
 (20487101,2,296000,'가능',2);

COMMIT;
