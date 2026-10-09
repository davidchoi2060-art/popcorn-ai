"""Clean up the 2026-10-09 data findings on the server DB as a migration.

Approved in the project thread on 2026-10-09 (KST 23:37 "허락..", 23:40
"막으면 그걸 풀어"; message ids cmsg_012k6fnspU3tgfYTTB56KTuDQBjRx7dbZSdUEDaVjHQA5r
and cmsg_012k6fnspU3tgfYTTB56KTuDKmFfwwH2KAv7BxovsXaL7i). Specs:
/mnt/project-files/handoff/auto-lock-20261009/unlock.sql, unlock-extra.sql and
/mnt/project-files/handoff/regression-cleanup-20261009/README.md.

1. Remove the 11 `specs.<field>` locks (7 products) that tools/enrich_pc_catalog_sources.py and
   tools/repair_pc_audit_evidence.py added on 2026-09-30 (fixed in PR #36).
   Spec values, spec_sources and reviews stay as they are. The owner's approval
   (docs/rights/pc-publication-approval-ledger.json, pc-publication-20261009-bundle)
   names "7개 상품 11개 항목"; the 3 in unlock-extra.sql (114723, 128080, 128085)
   are left for a separate approval, as the server owner's README says.
2. 94959: undo the regression product_edit that was never undone (sale price
   +1000, status 품절, both locked) exactly like POST /products/undo/{log_id}:
   price, status and locks back, a reverse price history row, and a
   product_edit_undo row with ref_log_id. Stock is not touched.
3. 105053: create the missing product_specs row and open 대기 reviews for
   rated_watt and form_factor.
4. 123034: review_required_yn=true and lock it, so loads stop putting it back
   into the candidate pool (CLAUDE.md, 123034 note).

Every target is checked against its expected current value first. A target
that already differs is skipped and counted, never forced. Each changed product
gets one ledger row in admin_operator_activity_logs; the counts go in one
migration_0135 row. On a DB without these products nothing is written.

downgrade() is a reverse transition, not a delete: it re-adds the removed
locks, re-applies the 94959 edit as a new product_edit row (undoable from the
admin screen), clears 123034 back to its recorded before-state, and moves the
105053 reviews it opened to 처리. Each reverse row points at the upgrade row
with ref_log_id. The 105053 specs row is kept (no values in it).
"""
import re
from alembic import op
from sqlalchemy import text

revision = '0135'
down_revision = '0134'
branch_labels = None
depends_on = None

# Expected values are what unlock.sql checks (to_jsonb(product_specs) -> field).
COMMON_SQL = r'''
CREATE TEMP TABLE m0135_unlock(product_code bigint, field text, expect jsonb) ON COMMIT DROP;
INSERT INTO m0135_unlock VALUES
  (120906,'cooler_tdp','280'),
  (121011,'cooler_tdp','280'),
  (114514,'cooler_tdp','290'),
  (128119,'cooler_tdp','200'),
  (129775,'mem_type','"DDR5"'),
  (129552,'gpu_max_mm','240'),
  (129552,'cooler_height_mm','75'),
  (129552,'form_factor_list','["m-ATX", "mini-ITX"]'),
  (129551,'gpu_max_mm','240'),
  (129551,'cooler_height_mm','75'),
  (129551,'form_factor_list','["m-ATX", "mini-ITX"]');
'''

UPGRADE_SQL = COMMON_SQL + r'''
DO $up$
DECLARE
  ev CONSTANT jsonb := '["cmsg_012k6fnspU3tgfYTTB56KTuDQBjRx7dbZSdUEDaVjHQA5r","cmsg_012k6fnspU3tgfYTTB56KTuDKmFfwwH2KAv7BxovsXaL7i"]';
  meta jsonb;
  r record; it record; tl_id bigint; tl_detail jsonb;
  v_sku text; lf jsonb; sj jsonb; locks text[]; d jsonb; chg jsonb;
  n_found int;
  u_applied int := 0; u_products int := 0; u_unlocked int := 0; u_changed int := 0; u_missing int := 0;
  s94959 text := 'skipped_missing'; s105053 text := 'skipped_missing'; s123034 text := 'skipped_missing';
  review_ids jsonb; rid bigint; specs_created boolean; pt text; rr boolean;
BEGIN
  meta := jsonb_build_object('migration','0135','phase','up','source','migration 0135','evidence',ev);
  SELECT count(*) INTO n_found FROM __S__.products
   WHERE product_code IN (SELECT product_code FROM m0135_unlock UNION SELECT unnest(ARRAY[94959,105053,123034]));
  IF n_found = 0 THEN
    RAISE NOTICE 'migration 0135: no target products in this DB, nothing written';
    RETURN;
  END IF;
  PERFORM 1 FROM __S__.products
   WHERE product_code IN (SELECT product_code FROM m0135_unlock UNION SELECT unnest(ARRAY[94959,105053,123034]))
   ORDER BY product_code FOR UPDATE;

  -- 1. unlock: only 'specs.<field>' entries whose value still equals the expected one
  FOR r IN SELECT product_code FROM m0135_unlock GROUP BY product_code ORDER BY product_code LOOP
    SELECT p.sku, COALESCE(p.locked_fields,'[]'::jsonb) INTO v_sku, lf
      FROM __S__.products p WHERE p.product_code = r.product_code;
    IF NOT FOUND THEN
      u_missing := u_missing + (SELECT count(*) FROM m0135_unlock WHERE product_code = r.product_code);
      CONTINUE;
    END IF;
    SELECT to_jsonb(s) INTO sj FROM __S__.product_specs s WHERE s.product_code = r.product_code;
    locks := ARRAY[]::text[];
    FOR it IN SELECT field, expect FROM m0135_unlock WHERE product_code = r.product_code ORDER BY field LOOP
      IF NOT lf ? ('specs.'||it.field) THEN
        u_unlocked := u_unlocked + 1;
      ELSIF sj IS NULL OR (sj -> it.field) IS DISTINCT FROM it.expect THEN
        u_changed := u_changed + 1;
      ELSE
        locks := locks || ('specs.'||it.field);
      END IF;
    END LOOP;
    CONTINUE WHEN cardinality(locks) = 0;
    UPDATE __S__.products SET locked_fields = lf - locks, updated_at = now()
     WHERE product_code = r.product_code;
    INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
    VALUES (NULL, 'product_edit', 'product', v_sku, meta || jsonb_build_object(
      'kind','unlock','product_code',r.product_code,'sku',v_sku,'changes','{}'::jsonb,
      'before',jsonb_build_object('locked_fields',lf),
      'after',jsonb_build_object('locked_fields',lf - locks),
      'unlocked',to_jsonb(locks),'locked',false));
    u_applied := u_applied + cardinality(locks);
    u_products := u_products + 1;
  END LOOP;

  -- 2. 94959: undo the latest product_edit nobody undid, if it is the regression edit
  SELECT l.log_id, l.detail INTO tl_id, tl_detail FROM __S__.admin_operator_activity_logs l
   WHERE l.action = 'product_edit' AND l.detail->>'product_code' = '94959'
     AND NOT EXISTS (SELECT 1 FROM __S__.admin_operator_activity_logs u
                      WHERE u.detail->>'ref_log_id' = l.log_id::text)
   ORDER BY l.log_id DESC LIMIT 1;
  SELECT p.sku, COALESCE(p.locked_fields,'[]'::jsonb), to_jsonb(p) INTO v_sku, lf, sj
    FROM __S__.products p WHERE p.product_code = 94959;
  IF NOT FOUND THEN
    s94959 := 'skipped_missing';
  ELSIF tl_id IS NULL THEN
    s94959 := 'skipped_no_open_edit';
  ELSE
    d := tl_detail; chg := d->'changes';
    IF jsonb_typeof(chg) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(chg) k) IS DISTINCT FROM ARRAY['sale_price','status']
       OR chg #> '{sale_price,from}' IS DISTINCT FROM '131400'::jsonb
       OR chg #> '{status,from}' IS DISTINCT FROM '"판매중"'::jsonb
       OR jsonb_typeof(chg #> '{sale_price,to}') IS DISTINCT FROM 'number'
       OR d #> '{before,locked_fields}' IS DISTINCT FROM '[]'::jsonb
       OR d->'locked' IS DISTINCT FROM 'true'::jsonb THEN
      s94959 := 'skipped_not_regression_edit';
    ELSIF sj->'sale_price' IS DISTINCT FROM chg #> '{sale_price,to}'
       OR sj->'status' IS DISTINCT FROM chg #> '{status,to}'
       OR NOT (lf @> '["sale_price","status"]'::jsonb AND '["sale_price","status"]'::jsonb @> lf) THEN
      s94959 := 'skipped_changed';
    ELSE
      UPDATE __S__.products SET sale_price = 131400, status = '판매중',
             locked_fields = '[]'::jsonb, updated_at = now()
       WHERE product_code = 94959;
      INSERT INTO __S__.product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)
      VALUES (94959, 'sale', (chg #>> '{sale_price,to}')::bigint, 131400, 'manual', tl_id, NULL);
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit_undo', 'product', v_sku, meta || jsonb_build_object(
        'kind','restore_94959','ref_log_id',tl_id,'product_code',94959,'sku',v_sku,
        'restored',jsonb_build_object('sale_price',131400,'status','판매중'),
        'before',jsonb_build_object('sale_price',sj->'sale_price','status',sj->'status','locked_fields',lf),
        'after',jsonb_build_object('locked_fields','[]'::jsonb)));
      s94959 := 'applied';
    END IF;
  END IF;

  -- 3. 105053: specs row + 대기 reviews for the two required power specs
  SELECT p.sku, p.part_type INTO v_sku, pt FROM __S__.products p WHERE p.product_code = 105053;
  IF FOUND THEN
    specs_created := false;
    SELECT to_jsonb(s) INTO sj FROM __S__.product_specs s WHERE s.product_code = 105053;
    IF sj IS NULL THEN
      INSERT INTO __S__.product_specs (product_code, part_type) VALUES (105053, pt);
      specs_created := true;
    END IF;
    review_ids := '[]'::jsonb;
    FOR it IN SELECT unnest(ARRAY['rated_watt','form_factor']) AS field LOOP
      CONTINUE WHEN sj IS NOT NULL AND (sj -> it.field) IS NOT NULL AND sj -> it.field <> 'null'::jsonb;
      CONTINUE WHEN EXISTS (SELECT 1 FROM __S__.product_reviews x
                             WHERE x.product_code = 105053 AND x.field_name = it.field
                               AND x.review_status = '대기');
      INSERT INTO __S__.product_reviews (product_code, review_type, field_name, review_status, detail)
      VALUES (105053, 'spec_missing', it.field, '대기', '필수 사양 미확인 - 사양 행 없음(마이그레이션 0135)')
      RETURNING review_id INTO rid;
      review_ids := review_ids || to_jsonb(rid);
    END LOOP;
    IF specs_created OR jsonb_array_length(review_ids) > 0 THEN
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', v_sku, meta || jsonb_build_object(
        'kind','specs_105053','product_code',105053,'sku',v_sku,'changes','{}'::jsonb,
        'specs_row_created',specs_created,'review_ids',review_ids,'locked',false));
      s105053 := 'applied';
    ELSE
      s105053 := 'skipped_already';
    END IF;
  END IF;

  -- 4. 123034: send to review and lock the flag
  SELECT p.sku, COALESCE(p.locked_fields,'[]'::jsonb), p.review_required_yn INTO v_sku, lf, rr
    FROM __S__.products p WHERE p.product_code = 123034;
  IF FOUND THEN
    IF rr IS TRUE AND lf ? 'review_required_yn' THEN
      s123034 := 'skipped_already';
    ELSE
      UPDATE __S__.products
         SET review_required_yn = true,
             locked_fields = CASE WHEN lf ? 'review_required_yn' THEN lf ELSE lf || '["review_required_yn"]'::jsonb END,
             updated_at = now()
       WHERE product_code = 123034;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', v_sku, meta || jsonb_build_object(
        'kind','review_123034','product_code',123034,'sku',v_sku,'changes','{}'::jsonb,
        'before',jsonb_build_object('review_required_yn',rr,'locked_fields',lf),
        'after',jsonb_build_object('review_required_yn',true,'locked_fields',
          CASE WHEN lf ? 'review_required_yn' THEN lf ELSE lf || '["review_required_yn"]'::jsonb END),
        'locked',true));
      s123034 := 'applied';
    END IF;
  END IF;

  INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
  VALUES (NULL, 'migration_0135', 'migration', '0135', meta || jsonb_build_object(
    'unlock',jsonb_build_object('fields_unlocked',u_applied,'products',u_products,
      'skipped_already_unlocked',u_unlocked,'skipped_value_changed',u_changed,'skipped_missing',u_missing),
    'p94959',s94959,'p105053',s105053,'p123034',s123034));
  RAISE NOTICE 'migration 0135 up: unlocked % fields on % products (skip: % already unlocked, % value changed, % missing); 94959 %; 105053 %; 123034 %',
    u_applied, u_products, u_unlocked, u_changed, u_missing, s94959, s105053, s123034;
END $up$;
'''

DOWNGRADE_SQL = r'''
DO $down$
DECLARE
  meta jsonb;
  r record; lf jsonb; sj jsonb; relock jsonb; d jsonb;
  n_relocked int := 0; n_skipped int := 0; n_reviews int := 0;
BEGIN
  meta := jsonb_build_object('migration','0135','phase','down','source','migration 0135 downgrade');
  PERFORM 1 FROM __S__.products
   WHERE product_code IN (SELECT (l.detail->>'product_code')::bigint FROM __S__.admin_operator_activity_logs l
                           WHERE l.detail->>'migration' = '0135' AND l.detail->>'phase' = 'up'
                             AND l.detail ? 'product_code')
   ORDER BY product_code FOR UPDATE;

  -- Up rows nobody has reversed yet, newest first.
  FOR r IN SELECT l.log_id, l.target_id, l.detail FROM __S__.admin_operator_activity_logs l
            WHERE l.detail->>'migration' = '0135' AND l.detail->>'phase' = 'up' AND l.detail ? 'kind'
              AND NOT EXISTS (SELECT 1 FROM __S__.admin_operator_activity_logs u
                               WHERE u.detail->>'ref_log_id' = l.log_id::text)
            ORDER BY l.log_id DESC LOOP
    d := r.detail;
    SELECT COALESCE(p.locked_fields,'[]'::jsonb), to_jsonb(p) INTO lf, sj
      FROM __S__.products p WHERE p.product_code = (d->>'product_code')::bigint;
    IF NOT FOUND THEN n_skipped := n_skipped + 1; CONTINUE; END IF;

    IF d->>'kind' = 'unlock' THEN
      -- re-add only the entries this migration removed and nobody re-added since
      SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) INTO relock
        FROM jsonb_array_elements_text(d->'unlocked') e WHERE NOT lf ? e;
      IF jsonb_array_length(relock) = 0 THEN n_skipped := n_skipped + 1; CONTINUE; END IF;
      UPDATE __S__.products SET locked_fields = lf || relock, updated_at = now()
       WHERE product_code = (d->>'product_code')::bigint;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', r.target_id, meta || jsonb_build_object(
        'ref_log_id',r.log_id,'product_code',d->'product_code','sku',d->'sku','changes','{}'::jsonb,
        'before',jsonb_build_object('locked_fields',lf),
        'after',jsonb_build_object('locked_fields',lf || relock),'relocked',relock,'locked',false));
      n_relocked := n_relocked + jsonb_array_length(relock);

    ELSIF d->>'kind' = 'restore_94959' THEN
      IF sj->'sale_price' IS DISTINCT FROM '131400'::jsonb OR sj->>'status' IS DISTINCT FROM '판매중'
         OR lf <> '[]'::jsonb THEN
        n_skipped := n_skipped + 1; CONTINUE;
      END IF;
      UPDATE __S__.products SET sale_price = (d #>> '{before,sale_price}')::bigint,
             status = d #>> '{before,status}', locked_fields = d #> '{before,locked_fields}', updated_at = now()
       WHERE product_code = 94959;
      INSERT INTO __S__.product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)
      VALUES (94959, 'sale', 131400, (d #>> '{before,sale_price}')::bigint, 'manual', r.log_id, NULL);
      -- Same shape as an admin product_edit, so the admin screen can undo it again.
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', r.target_id, meta || jsonb_build_object(
        'ref_log_id',r.log_id,'product_code',94959,'sku',d->'sku',
        'changes',jsonb_build_object(
          'sale_price',jsonb_build_object('from',131400,'to',d #> '{before,sale_price}'),
          'status',jsonb_build_object('from','판매중','to',d #> '{before,status}')),
        'before',jsonb_build_object('locked_fields','[]'::jsonb),'locked',true));

    ELSIF d->>'kind' = 'specs_105053' THEN
      UPDATE __S__.product_reviews SET review_status = '처리', reviewed_at = now()
       WHERE review_id IN (SELECT (e)::bigint FROM jsonb_array_elements_text(d->'review_ids') e)
         AND review_status = '대기';
      GET DIAGNOSTICS n_reviews = ROW_COUNT;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', r.target_id, meta || jsonb_build_object(
        'ref_log_id',r.log_id,'product_code',105053,'sku',d->'sku','changes','{}'::jsonb,
        'reviews_closed',n_reviews,'specs_row_kept',true,'locked',false));

    ELSIF d->>'kind' = 'review_123034' THEN
      IF sj->'review_required_yn' IS DISTINCT FROM 'true'::jsonb OR NOT lf ? 'review_required_yn' THEN
        n_skipped := n_skipped + 1; CONTINUE;
      END IF;
      UPDATE __S__.products
         SET review_required_yn = (d #>> '{before,review_required_yn}')::boolean,
             locked_fields = CASE WHEN (d #> '{before,locked_fields}') ? 'review_required_yn' THEN lf
                                  ELSE lf - 'review_required_yn' END,
             updated_at = now()
       WHERE product_code = 123034;
      INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
      VALUES (NULL, 'product_edit', 'product', r.target_id, meta || jsonb_build_object(
        'ref_log_id',r.log_id,'product_code',123034,'sku',d->'sku','changes','{}'::jsonb,
        'before',jsonb_build_object('review_required_yn',true,'locked_fields',lf),
        'restored',d->'before','locked',false));
    END IF;
  END LOOP;
  IF n_relocked + n_skipped > 0 OR EXISTS (SELECT 1 FROM __S__.admin_operator_activity_logs
                                             WHERE detail->>'migration' = '0135') THEN
    INSERT INTO __S__.admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)
    VALUES (NULL, 'migration_0135', 'migration', '0135', meta || jsonb_build_object(
      'fields_relocked',n_relocked,'skipped_changed',n_skipped));
  END IF;
  RAISE NOTICE 'migration 0135 down: re-locked % fields, skipped % rows', n_relocked, n_skipped;
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
