"""Clean up the 2026-10-09 data findings on the dev server DB as a migration.

Approved in the project thread on 2026-10-09 (KST 23:37 "허락..", 23:40
"막으면 그걸 풀어"; message ids cmsg_012k6fnspU3tgfYTTB56KTuDQBjRx7dbZSdUEDaVjHQA5r
and cmsg_012k6fnspU3tgfYTTB56KTuDKmFfwwH2KAv7BxovsXaL7i).

This is the server owner's bundle moved into the deploy path. The originals are
pinned in /mnt/project-files/handoff/regression-cleanup-20261009/:
  apply_bundle_20261009.py  10613 B  sha256 05caa7b43885585a9f3e4eef34608e662c825dbae1ee03286b5f6687153ede75
  undo_bundle_20261009.sql   5637 B  sha256 b8895737b2d7cf21979154b2b2ebf5b6e889639ad90bd9ce27c35f6042e6d26c
upgrade() makes the same checks and the same writes as apply_bundle_20261009.py
(same values, ledger actions, details and notes, so undo_bundle_20261009.sql also
works on its result); downgrade() follows undo_bundle_20261009.sql.

  1. 94959    undo regression log 22137 (sale 132400 -> 131400, 품절 -> 판매중, locks
               cleared), reverse price history row, product_edit_undo row (ref_log_id)
  2. 105053   empty product_specs row, rated_watt/form_factor spec_missing reviews,
               review_required_yn=true
  3. (B)      reviews 631, 637, 2544, 7164, 8614 must still be 대기 (read only)
  4. unlock   the 11 `specs.<field>` locks the 2026-09-30 spec-fill tools added on
               7 products (values and reviews untouched). The 3 in unlock-extra.sql
               are not in the owner's approval ("7개 상품 11개 항목") and not here.
  5. 123034   review_required_yn=true and lock it (review 8193 pending)

Differences from the originals, on purpose:
  - A failed check does not raise. Like the original, nothing at all is written
    (all-or-nothing), but the migration still completes and one migration_0135
    ledger row records which check failed. A raise would stop every later deploy
    until someone fixed the server by hand. On a DB without these products
    nothing is written at all.
  - Ledger rows carry "migration": "0135" so downgrade finds exactly its own rows.
  - Operator: the original writes operator 1 (and 22137's operator for 94959);
    here operator 1 is used only if it exists, else NULL (other DBs).
  - Downgrade re-locks a product only while its lock list and its spec values
    are still what the upgrade left; a changed product is skipped and recorded.
"""
import re
from alembic import op
from sqlalchemy import text

revision = '0135'
down_revision = '0134'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
DO $up$
DECLARE
  ev CONSTANT jsonb := '["cmsg_012k6fnspU3tgfYTTB56KTuDQBjRx7dbZSdUEDaVjHQA5r","cmsg_012k6fnspU3tgfYTTB56KTuDKmFfwwH2KAv7BxovsXaL7i"]';
  note CONSTANT text := 'regression cleanup 2026-10-09';
  mark jsonb;
  op1 bigint; src record; p record; r record; n int; v jsonb; why text := NULL;
  lid bigint; logs jsonb := '{}'::jsonb;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM __S__.products
                  WHERE product_code IN (94959,105053,123034,120906,121011,114514,128119,129552,129551,129775)) THEN
    RAISE NOTICE 'migration 0135: no target products in this DB, nothing written';
    RETURN;
  END IF;
  mark := jsonb_build_object('migration','0135','phase','up','evidence',ev);
  SELECT operator_id INTO op1 FROM __S__.admin_operators WHERE operator_id = 1;
  PERFORM 1 FROM __S__.products
   WHERE product_code IN (94959,105053,123034,120906,121011,114514,128119,129552,129551,129775)
   ORDER BY product_code FOR UPDATE;

  CREATE TEMP TABLE m0135_values(product_code bigint, field text, expect jsonb) ON COMMIT DROP;
  INSERT INTO m0135_values VALUES
    (120906,'cooler_tdp','280'), (121011,'cooler_tdp','280'), (114514,'cooler_tdp','290'),
    (128119,'cooler_tdp','200'), (129775,'mem_type','"DDR5"'),
    (129552,'gpu_max_mm','240'), (129552,'cooler_height_mm','75'), (129552,'form_factor_list','["m-ATX", "mini-ITX"]'),
    (129551,'gpu_max_mm','240'), (129551,'cooler_height_mm','75'), (129551,'form_factor_list','["m-ATX", "mini-ITX"]');
  -- (product, lock list now -- must match exactly, entries to drop)
  CREATE TEMP TABLE m0135_unlock(ord int, product_code bigint, before jsonb, drop_ text[]) ON COMMIT DROP;
  INSERT INTO m0135_unlock VALUES
    (1,120906,'["market_price", "specs.cooler_height_mm", "specs.cooler_tdp", "specs.socket_list"]',ARRAY['specs.cooler_tdp']),
    (2,121011,'["market_price", "specs.cooler_height_mm", "specs.cooler_tdp", "specs.socket_list"]',ARRAY['specs.cooler_tdp']),
    (3,114514,'["market_price", "specs.cooler_tdp"]',ARRAY['specs.cooler_tdp']),
    (4,128119,'["market_price", "specs.cooler_tdp"]',ARRAY['specs.cooler_tdp']),
    (5,129552,'["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"]',
            ARRAY['specs.cooler_height_mm','specs.form_factor_list','specs.gpu_max_mm']),
    (6,129551,'["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"]',
            ARRAY['specs.cooler_height_mm','specs.form_factor_list','specs.gpu_max_mm']),
    (7,129775,'["specs.mem_type"]',ARRAY['specs.mem_type']);

  -- ---- checks first; any failure writes nothing (original: Abort -> rollback)
  SELECT operator_id, target_id, detail INTO src FROM __S__.admin_operator_activity_logs
   WHERE log_id = 22137 AND action = 'product_edit';
  IF NOT FOUND OR src.detail->'product_code' IS DISTINCT FROM '94959'::jsonb THEN
    why := '94959: source log 22137 mismatch';
  ELSIF EXISTS (SELECT 1 FROM __S__.admin_operator_activity_logs WHERE action = 'product_edit_undo'
                 AND (detail->>'ref_log_id')::bigint = 22137) THEN
    why := '94959: undo row for 22137 already exists';
  END IF;
  IF why IS NULL THEN
    SELECT sale_price, status, locked_fields INTO p FROM __S__.products WHERE product_code = 94959;
    IF NOT FOUND OR p.sale_price IS DISTINCT FROM 132400 OR p.status IS DISTINCT FROM '품절'
       OR p.locked_fields IS DISTINCT FROM '["sale_price", "status"]'::jsonb THEN
      why := '94959: current values differ';
    END IF;
  END IF;
  IF why IS NULL THEN
    SELECT part_type, category_group, review_required_yn, locked_fields INTO p
      FROM __S__.products WHERE product_code = 105053;
    IF NOT FOUND OR p.part_type IS DISTINCT FROM 'POWER' OR p.category_group IS DISTINCT FROM 'core_part'
       OR p.review_required_yn IS DISTINCT FROM false THEN
      why := '105053: current values differ';
    ELSIF EXISTS (SELECT 1 FROM __S__.product_specs WHERE product_code = 105053) THEN
      why := '105053: product_specs row already exists';
    ELSIF EXISTS (SELECT 1 FROM __S__.product_reviews WHERE product_code = 105053) THEN
      why := '105053: review rows already exist';
    END IF;
  END IF;
  IF why IS NULL THEN
    SELECT count(*) INTO n FROM __S__.product_reviews
     WHERE review_id IN (631,637,2544,7164,8614) AND review_status = '대기';
    IF n <> 5 THEN why := '(B): pending reviews are not 5 (' || n || ')'; END IF;
  END IF;
  IF why IS NULL THEN
    FOR r IN SELECT t.product_code, t.field, t.expect, to_jsonb(s) -> t.field AS got
               FROM m0135_values t LEFT JOIN __S__.product_specs s USING (product_code) LOOP
      IF r.got IS DISTINCT FROM r.expect THEN
        why := r.product_code || '.' || r.field || ': value differs'; EXIT;
      END IF;
    END LOOP;
  END IF;
  IF why IS NULL THEN
    FOR r IN SELECT u.product_code, u.before, p2.locked_fields AS cur
               FROM m0135_unlock u LEFT JOIN __S__.products p2 USING (product_code) LOOP
      IF r.cur IS DISTINCT FROM r.before THEN
        why := r.product_code || ': lock list differs'; EXIT;
      END IF;
    END LOOP;
  END IF;
  IF why IS NULL THEN
    SELECT review_required_yn, ai_candidate_yn, locked_fields, status INTO p
      FROM __S__.products WHERE product_code = 123034;
    IF NOT FOUND OR p.review_required_yn IS DISTINCT FROM false OR p.ai_candidate_yn IS DISTINCT FROM true
       OR p.locked_fields IS DISTINCT FROM '[]'::jsonb OR p.status IS DISTINCT FROM '판매중' THEN
      why := '123034: current values differ';
    ELSIF (SELECT review_status FROM __S__.product_reviews WHERE review_id = 8193) IS DISTINCT FROM '대기' THEN
      why := '123034: review 8193 is not pending';
    END IF;
  END IF;

  IF why IS NOT NULL THEN
    INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
    VALUES (NULL, 'migration_0135', 'migration', '0135',
            mark || jsonb_build_object('applied', false, 'skipped_reason', why, 'note', note));
    RAISE NOTICE 'migration 0135: check failed, nothing applied: %', why;
    RETURN;
  END IF;

  -- ---- 1) 94959 restore (log 22137, its undo returned 409)
  UPDATE __S__.products SET sale_price = 131400, status = '판매중', locked_fields = '[]'::jsonb, updated_at = now()
   WHERE product_code = 94959;
  INSERT INTO __S__.product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)
  VALUES (94959, 'sale', 132400, 131400, 'manual', 22137, src.operator_id);
  INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
  VALUES (src.operator_id, 'product_edit_undo', 'product', src.target_id, mark || jsonb_build_object(
    'ref_log_id', 22137, 'product_code', 94959, 'restored', jsonb_build_object('status','판매중','sale_price',131400),
    'note', 'regression cleanup 2026-10-09 (undo 409)')) RETURNING log_id INTO lid;
  logs := logs || jsonb_build_object('94959', lid);

  -- ---- 2) (A) 105053 ZM700-TX power: empty specs row + required spec reviews
  SELECT locked_fields INTO v FROM __S__.products WHERE product_code = 105053;
  INSERT INTO __S__.product_specs (product_code, part_type) VALUES (105053, 'POWER');
  INSERT INTO __S__.product_reviews (product_code, review_type, field_name, detail, confidence) VALUES
    (105053, 'spec_missing', 'rated_watt', 'POWER 필수 사양 ''rated_watt'' 미확인 — 사양 행 누락으로 회부(' || note || ')', 0.80),
    (105053, 'spec_missing', 'form_factor', 'POWER 필수 사양 ''form_factor'' 미확인 — 사양 행 누락으로 회부(' || note || ')', 0.80);
  UPDATE __S__.products SET review_required_yn = true, updated_at = now() WHERE product_code = 105053;
  INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
  VALUES (op1, 'product_edit', 'product', '105053', mark || jsonb_build_object(
    'sku', '105053', 'product_code', 105053, 'locked', false, 'before', jsonb_build_object('locked_fields', v),
    'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from', false, 'to', true),
               'product_specs', jsonb_build_object('from', NULL, 'to', 'row created (part_type POWER, values empty)')),
    'note', note || ' - core_part POWER had no product_specs row. Created empty row and referred required '
            'specs (rated_watt, form_factor) to review; no values invented. NOTE: not in EDITABLE -- '
            'the generic undo button will NOT revert this log.')) RETURNING log_id INTO lid;
  logs := logs || jsonb_build_object('105053', lid);

  -- ---- 3) (B) checked above, nothing written
  -- ---- 4) unlock the 11 fields the 2026-09-30 tools locked (values and reviews unchanged)
  FOR r IN SELECT product_code, before, drop_ FROM m0135_unlock ORDER BY ord LOOP
    v := r.before - r.drop_;
    UPDATE __S__.products SET locked_fields = v, updated_at = now() WHERE product_code = r.product_code;
    INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
    VALUES (op1, 'product_edit', 'product', r.product_code::text, mark || jsonb_build_object(
      'sku', r.product_code::text, 'product_code', r.product_code, 'locked', false,
      'before', jsonb_build_object('locked_fields', r.before),
      'changes', jsonb_build_object('locked_fields', jsonb_build_object('from', r.before, 'to', v)),
      'note', note || ' - unlock spec fields locked by the 2026-09-30 spec-fill tool (not operator-verified, '
              'verified_yn=false, pending spec_missing reviews kept). Values unchanged. NOTE: not in EDITABLE -- '
              'the generic undo button will NOT revert this log.')) RETURNING log_id INTO lid;
    logs := logs || jsonb_build_object(r.product_code::text, lid);
  END LOOP;
  SELECT count(*) INTO n FROM m0135_values t JOIN __S__.products p2 USING (product_code)
   WHERE p2.locked_fields ? ('specs.' || t.field);
  IF n <> 0 THEN
    RAISE EXCEPTION 'migration 0135: % target locks left after unlock (must be 0)', n;
  END IF;

  -- ---- 5) 123034 name is a sales-condition phrase: review flag + lock
  UPDATE __S__.products SET review_required_yn = true, locked_fields = '["review_required_yn"]'::jsonb, updated_at = now()
   WHERE product_code = 123034;
  INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
  VALUES (op1, 'product_edit', 'product', '123034', mark || jsonb_build_object(
    'sku', '123034', 'product_code', 123034, 'locked', true, 'before', jsonb_build_object('locked_fields', '[]'::jsonb),
    'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from', false, 'to', true)),
    'note', note || ' - name is a sales-condition phrase (review 8193 pending); flag for review and lock so '
            'the next import does not clear it. NOTE: not in EDITABLE -- the generic undo button will NOT revert this log.'))
  RETURNING log_id INTO lid;
  logs := logs || jsonb_build_object('123034', lid);

  INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
  VALUES (NULL, 'migration_0135', 'migration', '0135',
          mark || jsonb_build_object('applied', true, 'log_ids', logs, 'note', note));
  RAISE NOTICE 'migration 0135: applied (94959, 105053, 7 unlocks, 123034)';
END $up$;
'''

DOWNGRADE_SQL = r'''
DO $down$
DECLARE
  note CONSTANT text := 'revert of regression cleanup 2026-10-09';
  mark jsonb;
  op1 bigint; r record; p record; n int; done jsonb := '[]'::jsonb; skipped jsonb := '[]'::jsonb;
BEGIN
  mark := jsonb_build_object('migration','0135','phase','down');
  SELECT operator_id INTO op1 FROM __S__.admin_operators WHERE operator_id = 1;
  PERFORM 1 FROM __S__.products
   WHERE product_code IN (SELECT (l.detail->>'product_code')::bigint FROM __S__.admin_operator_activity_logs l
                           WHERE l.detail->>'migration' = '0135' AND l.detail->>'phase' = 'up'
                             AND l.detail ? 'product_code')
   ORDER BY product_code FOR UPDATE;

  -- This migration's up rows that nothing has reversed yet; each item independent
  FOR r IN SELECT l.log_id, l.operator_id, l.target_id, l.detail FROM __S__.admin_operator_activity_logs l
            WHERE l.detail->>'migration' = '0135' AND l.detail->>'phase' = 'up' AND l.detail ? 'product_code'
              AND NOT EXISTS (SELECT 1 FROM __S__.admin_operator_activity_logs u
                               WHERE u.detail->>'ref_log_id' = l.log_id::text)
            -- same order as undo_bundle_20261009.sql blocks (1) (2) (3) (4)
            ORDER BY CASE l.detail->>'product_code' WHEN '94959' THEN 1 WHEN '105053' THEN 2
                                                    WHEN '123034' THEN 3 ELSE 4 END, l.log_id LOOP
    IF r.detail->>'product_code' = '94959' THEN
      -- (1) back to the regression test values (normally never needed)
      UPDATE __S__.products SET sale_price = 132400, status = '품절',
             locked_fields = '["sale_price","status"]'::jsonb, updated_at = now()
       WHERE product_code = 94959 AND sale_price = 131400 AND status = '판매중' AND locked_fields = '[]'::jsonb;
      GET DIAGNOSTICS n = ROW_COUNT;
      IF n = 0 THEN skipped := skipped || '"94959"'::jsonb; CONTINUE; END IF;
      INSERT INTO __S__.product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)
      VALUES (94959, 'sale', 131400, 132400, 'manual', 22137, op1);
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (op1, 'product_edit', 'product', '94959', mark || jsonb_build_object(
        'sku', '94959', 'product_code', 94959, 'locked', true, 'before', jsonb_build_object('locked_fields', '[]'::jsonb),
        'changes', jsonb_build_object('status', jsonb_build_object('from','판매중','to','품절'),
                                      'sale_price', jsonb_build_object('from',131400,'to',132400)),
        'ref_log_id', r.log_id, 'note', note || ' (undo 409)'));

    ELSIF r.detail->>'product_code' = '105053' THEN
      -- (2) close the reviews (not deleted), drop the still-empty specs row, clear the flag
      UPDATE __S__.product_reviews SET review_status = '처리', reviewed_at = now(),
             detail = detail || ' [되돌림: regression cleanup 2026-10-09 사양 행 생성 취소]'
       WHERE product_code = 105053 AND review_type = 'spec_missing' AND review_status = '대기'
         AND field_name IN ('rated_watt','form_factor') AND detail LIKE '%regression cleanup 2026-10-09%';
      DELETE FROM __S__.product_specs WHERE product_code = 105053 AND part_type = 'POWER'
         AND rated_watt IS NULL AND form_factor IS NULL AND verified_yn = false;
      UPDATE __S__.products SET review_required_yn = false, updated_at = now() WHERE product_code = 105053;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (op1, 'product_edit', 'product', '105053', mark || jsonb_build_object(
        'sku', '105053', 'product_code', 105053, 'locked', false, 'before', r.detail->'before',
        'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from', true, 'to', false),
                   'product_specs', jsonb_build_object('from', 'row created (part_type POWER, values empty)', 'to', NULL)),
        'ref_log_id', r.log_id, 'note', note || ' (105053 spec row)'));

    ELSIF r.detail->>'product_code' = '123034' THEN
      -- (3) review flag + lock
      UPDATE __S__.products SET review_required_yn = false, locked_fields = '[]'::jsonb, updated_at = now()
       WHERE product_code = 123034 AND locked_fields = '["review_required_yn"]'::jsonb;
      GET DIAGNOSTICS n = ROW_COUNT;
      IF n = 0 THEN skipped := skipped || '"123034"'::jsonb; CONTINUE; END IF;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (op1, 'product_edit', 'product', '123034', mark || jsonb_build_object(
        'sku', '123034', 'product_code', 123034, 'locked', false,
        'before', jsonb_build_object('locked_fields', '["review_required_yn"]'::jsonb),
        'changes', jsonb_build_object('review_required_yn', jsonb_build_object('from', true, 'to', false),
                   'locked_fields', jsonb_build_object('from', '["review_required_yn"]'::jsonb, 'to', '[]'::jsonb)),
        'ref_log_id', r.log_id, 'note', note || ' (123034 review flag)'));

    ELSIF r.detail #> '{changes,locked_fields}' IS NOT NULL THEN
      -- (4) re-lock: only while the lock list is what the upgrade left and the
      -- unlocked spec values are still the 2026-09-30 tool values
      SELECT locked_fields INTO p FROM __S__.products WHERE product_code = (r.detail->>'product_code')::bigint;
      IF p.locked_fields IS DISTINCT FROM r.detail #> '{changes,locked_fields,to}' OR EXISTS (
           SELECT 1 FROM (VALUES
             (120906,'cooler_tdp','280'::jsonb), (121011,'cooler_tdp','280'), (114514,'cooler_tdp','290'),
             (128119,'cooler_tdp','200'), (129775,'mem_type','"DDR5"'),
             (129552,'gpu_max_mm','240'), (129552,'cooler_height_mm','75'), (129552,'form_factor_list','["m-ATX", "mini-ITX"]'),
             (129551,'gpu_max_mm','240'), (129551,'cooler_height_mm','75'), (129551,'form_factor_list','["m-ATX", "mini-ITX"]')
           ) t(product_code, field, expect)
           LEFT JOIN __S__.product_specs s ON s.product_code = t.product_code
           WHERE t.product_code = (r.detail->>'product_code')::bigint
             AND (to_jsonb(s) -> t.field) IS DISTINCT FROM t.expect) THEN
        skipped := skipped || to_jsonb(r.detail->>'product_code'); CONTINUE;
      END IF;
      UPDATE __S__.products SET locked_fields = r.detail #> '{before,locked_fields}', updated_at = now()
       WHERE product_code = (r.detail->>'product_code')::bigint;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (op1, 'product_edit', 'product', r.target_id, mark || jsonb_build_object(
        'sku', r.target_id, 'product_code', (r.detail->>'product_code')::bigint, 'locked', true,
        'before', jsonb_build_object('locked_fields', r.detail #> '{changes,locked_fields,to}'),
        'changes', jsonb_build_object('locked_fields', jsonb_build_object(
            'from', r.detail #> '{changes,locked_fields,to}', 'to', r.detail #> '{changes,locked_fields,from}')),
        'ref_log_id', r.log_id, 'note', note || ' (re-lock 2026-09-30 tool fields)'));
    ELSE
      CONTINUE;
    END IF;
    done := done || to_jsonb(r.detail->>'product_code');
  END LOOP;

  IF jsonb_array_length(done) + jsonb_array_length(skipped) > 0 THEN
    INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
    VALUES (NULL, 'migration_0135', 'migration', '0135',
            mark || jsonb_build_object('reverted', done, 'skipped_changed', skipped));
  END IF;
  RAISE NOTICE 'migration 0135 down: reverted %, skipped (changed since upgrade) %', done, skipped;
END $down$;
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Schema unavailable')
    return '"' + value + '"'


def upgrade():
    # Data only; runs in the caller's Alembic transaction.
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    bind = op.get_bind()
    op.execute(DOWNGRADE_SQL.replace('__S__', _schema(bind)))
