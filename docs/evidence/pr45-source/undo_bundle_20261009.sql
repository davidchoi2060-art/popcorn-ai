-- 묶음 「상품 94959 복원, 데이터 정리」(2026-10-09) 되돌리기. apply_bundle_20261009.py 가 커밋된 뒤에만 쓴다.
-- 저장소 규약: 되돌림은 삭제가 아니라 역방향 행이다. 원장(admin_operator_activity_logs·product_price_history)은
-- 지우지 않고 역방향 기록을 새로 남긴다. ref_log_id 는 적용 때 남긴 기록(note 'regression cleanup 2026-10-09%')이다.
-- 항목별로 독립 실행 가능. 각 블록은 한 트랜잭션.

-- ① 94959 복원 되돌리기(시험값 상태로 돌아감 — 보통은 쓸 일 없음)
BEGIN;
UPDATE products SET sale_price=132400, status='품절', locked_fields='["sale_price","status"]'::jsonb, updated_at=now()
 WHERE product_code=94959 AND sale_price=131400 AND status='판매중' AND locked_fields='[]'::jsonb;
INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)
VALUES (94959, 'sale', 131400, 132400, 'manual', 22137, 1);
INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
SELECT 1, 'product_edit', 'product', '94959', jsonb_build_object(
  'sku', '94959', 'product_code', 94959, 'locked', true, 'before', jsonb_build_object('locked_fields', '[]'::jsonb),
  'changes', jsonb_build_object('status', jsonb_build_object('from','판매중','to','품절'),
                                'sale_price', jsonb_build_object('from',131400,'to',132400)),
  'ref_log_id', l.log_id, 'note', 'revert of regression cleanup 2026-10-09 (undo 409)')
  FROM admin_operator_activity_logs l
 WHERE l.action='product_edit_undo' AND (l.detail->>'ref_log_id')::int=22137
   AND l.detail->>'note' LIKE 'regression cleanup 2026-10-09%';
COMMIT;

-- ② 105053 사양 행 생성 되돌리기 — 검수 행은 지우지 않고 '처리'로 닫는다(사유 기록)
BEGIN;
UPDATE product_reviews SET review_status='처리', reviewed_at=now(),
       detail = detail || ' [되돌림: regression cleanup 2026-10-09 사양 행 생성 취소]'
 WHERE product_code=105053 AND review_type='spec_missing' AND review_status='대기'
   AND field_name IN ('rated_watt','form_factor') AND detail LIKE '%regression cleanup 2026-10-09%';
DELETE FROM product_specs WHERE product_code=105053 AND part_type='POWER'
   AND rated_watt IS NULL AND form_factor IS NULL AND verified_yn=false;
UPDATE products SET review_required_yn=false, updated_at=now() WHERE product_code=105053;
INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
SELECT 1, 'product_edit', 'product', '105053', jsonb_build_object(
  'sku', '105053', 'product_code', 105053, 'locked', false, 'before', l.detail->'before',
  'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from',true,'to',false),
                                'product_specs', jsonb_build_object('from','row created (part_type POWER, values empty)','to',null)),
  'ref_log_id', l.log_id, 'note', 'revert of regression cleanup 2026-10-09 (105053 spec row)')
  FROM admin_operator_activity_logs l
 WHERE l.action='product_edit' AND l.target_id='105053' AND l.detail->>'note' LIKE 'regression cleanup 2026-10-09%';
COMMIT;

-- ③ 123034 검수 표시+잠금 되돌리기
BEGIN;
UPDATE products SET review_required_yn=false, locked_fields='[]'::jsonb, updated_at=now()
 WHERE product_code=123034 AND locked_fields='["review_required_yn"]'::jsonb;
INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
SELECT 1, 'product_edit', 'product', '123034', jsonb_build_object(
  'sku', '123034', 'product_code', 123034, 'locked', false,
  'before', jsonb_build_object('locked_fields', '["review_required_yn"]'::jsonb),
  'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from',true,'to',false),
                                'locked_fields', jsonb_build_object('from','["review_required_yn"]'::jsonb,'to','[]'::jsonb)),
  'ref_log_id', l.log_id, 'note', 'revert of regression cleanup 2026-10-09 (123034 review flag)')
  FROM admin_operator_activity_logs l
 WHERE l.action='product_edit' AND l.target_id='123034' AND l.detail->>'note' LIKE 'regression cleanup 2026-10-09%';
COMMIT;

-- ④ 9/30 도구 잠금 해제 되돌리기 — 적용 때 기록한 before 잠금 목록을 그대로 다시 쓰고 역방향 기록을 남긴다
BEGIN;
UPDATE products p SET locked_fields = l.detail->'before'->'locked_fields', updated_at=now()
  FROM admin_operator_activity_logs l
 WHERE l.action='product_edit' AND l.target_id = p.product_code::text
   AND l.target_id IN ('120906','121011','114514','128119','129552','129551','129775')
   AND l.detail->>'note' LIKE 'regression cleanup 2026-10-09%'
   AND p.locked_fields = l.detail->'changes'->'locked_fields'->'to';
INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
SELECT 1, 'product_edit', 'product', l.target_id, jsonb_build_object(
  'sku', l.target_id, 'product_code', (l.detail->>'product_code')::bigint, 'locked', true,
  'before', jsonb_build_object('locked_fields', l.detail->'changes'->'locked_fields'->'to'),
  'changes', jsonb_build_object('locked_fields', jsonb_build_object(
      'from', l.detail->'changes'->'locked_fields'->'to', 'to', l.detail->'changes'->'locked_fields'->'from')),
  'ref_log_id', l.log_id, 'note', 'revert of regression cleanup 2026-10-09 (re-lock 2026-09-30 tool fields)')
  FROM admin_operator_activity_logs l
 WHERE l.action='product_edit'
   AND l.target_id IN ('120906','121011','114514','128119','129552','129551','129775')
   AND l.detail->>'note' LIKE 'regression cleanup 2026-10-09%';
COMMIT;
