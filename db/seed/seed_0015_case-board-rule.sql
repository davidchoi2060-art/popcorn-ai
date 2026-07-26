-- seed_0015: 슬라이스 43 — 8번째 호환 규칙: 케이스가 보드 규격을 수용하는가 (재실행 안전)
--
-- 왜 추가하는가(사용자 결정 2026-07-26, 선택 ②): `CASE.form_factor`가 **필수 사양인데
-- 호환 규칙이 쓰지 않는** 상태였다. 규칙이 쓰지 않는 필드를 게이트로 요구하면 근거 없이
-- 추천을 막는다. 두 갈래(필수에서 빼기 / 규칙 추가) 중 **규칙 추가**를 택했다 —
-- "보드가 케이스에 들어가는가"는 조립에 실제로 필요한 검증이기 때문이다.
--
-- 단일값이 아니라 목록으로 비교한다: 케이스는 규격을 여러 개 지원한다(실측 3개 1,110건).
-- 쿨러 소켓과 같은 형태 — `contains`.
-- ref_slot(MB)은 탐색 순서(CPU→MB→RAM→GPU→CASE→COOLER→POWER→SSD)에서 CASE보다 앞이다.

INSERT INTO compat_rules (rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, sort_order)
SELECT * FROM (VALUES
  ('case_board', 'CASE', 'form_factor_list', 'contains', 'MB', 'form_factor',
   '메인보드 규격 수용', '{r} 지원', 35)
) AS v(rule_key, slot, field, op, ref_slot, ref_field, label, detail_fmt, sort_order)
WHERE NOT EXISTS (SELECT 1 FROM compat_rules c WHERE c.rule_key = v.rule_key);

-- 이미 있으면 정의를 현행화(재실행 안전)
UPDATE compat_rules
   SET slot = 'CASE', field = 'form_factor_list', op = 'contains',
       ref_slot = 'MB', ref_field = 'form_factor',
       label = '메인보드 규격 수용', detail_fmt = '{r} 지원', active = true
 WHERE rule_key = 'case_board';

-- 필수 사양 정의가 form_factor -> form_factor_list로 바뀌었으므로 **대기 중인 검수 항목도
-- 그 이름을 따라간다**(같은 것을 기다리는 행이 두 이름으로 갈리면 화면 집계가 어긋난다).
UPDATE product_reviews r
   SET field_name = 'form_factor_list',
       detail = replace(detail, '''form_factor''', '''form_factor_list''')
  FROM products p
 WHERE r.product_code = p.product_code AND p.part_type = 'CASE'
   AND r.review_status = '대기' AND r.field_name = 'form_factor';
