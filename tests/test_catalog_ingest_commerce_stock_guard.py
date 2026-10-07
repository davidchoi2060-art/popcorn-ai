"""Real ingest/shared locks, caller-transaction doubles; no native PostgreSQL proof."""
from copy import deepcopy
from unittest.mock import patch
import sys
import unittest

from tests import test_catalog_ingest_write_lock_order as legacy
from api import catalog_ingest as ci
from api.pricing_write_guard_core import _LOCK_PRODUCTS_SQL


class CommerceConnection(legacy.Connection):
    def execute(self, statement, params=None):
        q, d = str(statement), self.db
        if q in (ci._COMMERCE_CATALOG_SQL, ci._COMMERCE_STOCK_CODES_SQL):
            d.calls.append((q, deepcopy(params or {})))
            self.assert_locked()
            if getattr(d, 'probe_error', None):
                raise d.probe_error
            if q == ci._COMMERCE_CATALOG_SQL:
                return legacy.Result([getattr(d, 'commerce_present', False)])
            if getattr(d, 'membership_error', None):
                raise d.membership_error
            if getattr(d, 'membership_override', None) is not None:
                return legacy.Result(d.membership_override)
            codes = set(params['c'])
            protected = {pc for pc, order, state in d.reservations
                         if order in d.commerce_orders and pc in codes}
            protected.update(pc for pc, kind, operation, effect in d.movements
                             if pc in codes and kind == 'own_sale'
                             and operation is not None and effect is not None)
            return legacy.Result(sorted(protected))
        return super().execute(statement, params)


class StockGuardTests(unittest.TestCase):
    def setUp(self):
        self.connection_patch = patch.object(legacy, 'Connection', CommerceConnection)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)

    def db(self, state='held', stock=7):
        db = legacy.Database()
        db.commerce_present = True
        db.commerce_orders = {501}
        db.reservations = [(101, 501, state)]
        db.movements = []
        db.products[101]['stock'] = stock
        return db

    def apply(self, db, prods):
        value = legacy.plan(prods, db)
        with db.begin() as conn:
            return ci.apply_plan(conn, value, '원본.csv', 'real', 31)

    def denied(self, db, prods, exception=ci.CatalogConflict):
        before = deepcopy(db.products)
        with self.assertRaises(exception):
            self.apply(db, prods)
        self.assertEqual(db.products, before)
        self.assertEqual(db.writes, [])
        self.assertEqual((db.commits, db.rollbacks), (0, 1))
        self.assertFalse(any('INSERT' in q for q, _ in db.calls))

    def test_every_reservation_state_blocks_up_and_down_before_first_write(self):
        for state in ('held', 'protected', 'converted', 'released'):
            for stock in (6, 8):
                with self.subTest(state=state, stock=stock):
                    self.denied(self.db(state), [legacy.product(101, stock)])

    def test_own_sale_after_conversion_cannot_be_restored_by_stale_csv(self):
        db = self.db('converted', stock=9)
        db.reservations = []
        db.movements = [(101, 'own_sale', 'real-operation', 'real-effect')]
        self.denied(db, [legacy.product(101, 10)])

    def test_protection_includes_reservation_created_before_postlock_snapshot(self):
        db = self.db()
        db.reservations = []
        db.before_read = lambda d: d.reservations.append((101, 501, 'released'))
        self.denied(db, [legacy.product(101, 8)])

    def test_membership_sql_uses_real_link_and_markers_without_active_claim_filter(self):
        sql = ci._COMMERCE_STOCK_CODES_SQL
        self.assertIn('d.order_id = r.commerce_order_id', sql)
        self.assertIn("m.movement_type = 'own_sale'", sql)
        self.assertIn('m.commerce_operation_id IS NOT NULL', sql)
        self.assertIn('m.commerce_effect_key IS NOT NULL', sql)
        self.assertNotIn('expires_at', sql)
        self.assertNotIn('r.status', sql)
        self.assertEqual(sql.count('ANY(:c)'), 2)

    def test_mixed_same_protected_stock_and_legacy_change_keep_original_order(self):
        db = self.db()
        db.products[102] = dict(stock=4, pp=100, sp2=200, locked=[])
        self.apply(db, [legacy.product(102, 2), legacy.product(101, 7)])
        self.assertEqual([p['pc'] for q, rows in db.writes if q == 'products' for p in rows], [102, 101])
        moves = [r for q, rows in db.writes if 'stock_movements' in q for r in rows]
        self.assertEqual([(r['pc'], r['q']) for r in moves], [(102, -2)])

    def test_same_stock_keeps_price_metadata_raw_log_and_no_stock_delta(self):
        db = self.db()
        first = legacy.product(101, 7, 150, 250)
        second = legacy.product(101, 7, None, 300)
        original = deepcopy([first, second])
        self.apply(db, [first, second])
        self.assertEqual([first, second], original)
        self.assertEqual(db.products[101]['stock'], 7)
        self.assertEqual(db.products[101]['sp2'], 300)
        self.assertFalse(any('INSERT INTO stock_movements' in q for q, _ in db.writes))
        history = [r for q, rows in db.writes if 'product_price_history' in q for r in rows]
        self.assertEqual([(r['old'], r['new']) for r in history], [(100, 150), (200, 250), (250, 300)])
        self.assertEqual(len([r for q, rows in db.writes if 'product_imports' in q for r in rows]), 2)

    def test_unrelated_legacy_reservation_and_unmarked_ledger_do_not_invent_protection(self):
        db = self.db()
        db.reservations = [(101, None, 'held'), (101, 999, 'protected')]
        db.movements = [(101, 'own_sale', None, None), (101, 'adjust', 'op', 'key')]
        self.apply(db, [legacy.product(101, 3)])
        self.assertEqual(db.products[101]['stock'], 3)
        moves = [r for q, rows in db.writes if 'stock_movements' in q for r in rows]
        self.assertEqual([r['q'] for r in moves], [-4])

    def test_mixed_last_row_drift_after_batch_boundary_has_zero_business_writes(self):
        db = self.db()
        db.products[102] = dict(stock=4, pp=100, sp2=200, locked=[])
        prods = [legacy.product(102, 3) for _ in range(500)] + [legacy.product(101, 8)]
        self.denied(db, prods)
        self.assertEqual(db.locks, (101, 102))

    def test_duplicate_out_and_back_cannot_hide_intermediate_change(self):
        for stocks in ((8, 7), (7, 6), (7, 8, 7)):
            self.denied(self.db(), [legacy.product(101, stock) for stock in stocks])

    def test_lock_wait_observation_is_used_not_prelock_inventory(self):
        db = self.db()
        db.after_lock = lambda d: d.products[101].update(stock=9)
        self.denied_after_wait(db, 7)

    def denied_after_wait(self, db, stock):
        with self.assertRaises(ci.CatalogConflict):
            self.apply(db, [legacy.product(101, stock)])
        self.assertEqual(db.products[101]['stock'], 9)
        self.assertEqual(db.writes, [])
        queries = [q for q, _ in db.calls]
        self.assertLess(queries.index(_LOCK_PRODUCTS_SQL), queries.index(ci._COMMERCE_CATALOG_SQL))
        self.assertLess(next(i for i, q in enumerate(queries) if q.startswith('SELECT product_code, stock_qty')),
                        queries.index(ci._COMMERCE_STOCK_CODES_SQL))

    def test_after_wait_identical_stock_is_allowed(self):
        db = self.db()
        db.after_lock = lambda d: d.products[101].update(stock=9)
        self.apply(db, [legacy.product(101, 9)])
        self.assertEqual(db.commits, 1)

    def test_native_stock_types_are_not_coerced_or_defaulted_for_protected_rows(self):
        for stock in (True, None, '7', 7.0):
            self.denied(self.db(), [legacy.product(101, stock)])
        for actual in (None, True, '7', 7.0):
            self.denied(self.db(stock=actual), [legacy.product(101, 7)])

    def test_zero_stock_same_value_remains_zero(self):
        db = self.db('released', stock=0)
        self.apply(db, [legacy.product(101, 0)])
        self.assertEqual(db.products[101]['stock'], 0)

    def test_catalog_absence_keeps_legacy_duplicates_order_and_delta(self):
        db = self.db()
        db.commerce_present = False
        self.apply(db, [legacy.product(101, 2), legacy.product(101, 4)])
        moves = [r for q, rows in db.writes if 'stock_movements' in q for r in rows]
        self.assertEqual([r['q'] for r in moves], [-5, 2])
        self.assertFalse(any(q == ci._COMMERCE_STOCK_CODES_SQL for q, _ in db.calls))

    def test_probe_is_catalog_query_and_never_cached_across_transactions(self):
        db = self.db()
        db.commerce_present = False
        self.apply(db, [legacy.product(101, 7)])
        db.commerce_present = True
        with self.assertRaises(ci.CatalogConflict):
            self.apply(db, [legacy.product(101, 8)])
        self.assertEqual(sum(q == ci._COMMERCE_CATALOG_SQL for q, _ in db.calls), 2)
        self.assertIn('pg_catalog.to_regclass', ci._COMMERCE_CATALOG_SQL)

    def test_query_schema_or_column_error_propagates_before_business_write(self):
        for field in ('probe_error', 'membership_error'):
            db = self.db()
            setattr(db, field, RuntimeError('undefined table/column/schema'))
            self.denied(db, [legacy.product(101, 7)], RuntimeError)

    def test_invalid_catalog_boolean_or_membership_types_fail_closed(self):
        for observed in (None, 0, 1, 'false'):
            db = self.db()
            db.commerce_present = observed
            self.denied(db, [legacy.product(101, 7)])
        for observed in ([True], ['101'], [999]):
            db = self.db()
            db.membership_override = observed
            self.denied(db, [legacy.product(101, 7)])

    def test_basis_drift_still_precedes_commerce_check(self):
        db = self.db()
        db.after_lock = lambda d: d.products[101]['locked'].append('sale_price')
        with self.assertRaises(ci.CatalogConflict):
            self.apply(db, [legacy.product(101, 7)])
        self.assertEqual(db.products[101]['locked'], ['sale_price'])
        self.assertEqual(db.writes, [])
        self.assertEqual((db.commits, db.rollbacks), (0, 1))
        self.assertFalse(any(q == ci._COMMERCE_CATALOG_SQL for q, _ in db.calls))

    def test_new_late_insert_remains_insert_only_and_rolls_back_prior_work(self):
        db = self.db()
        external = dict(stock=42, pp=777, sp2=888, locked=[])
        db.before_read = lambda d: d.products.update({102: deepcopy(external)})
        with self.assertRaises(ci.CatalogConflict):
            self.apply(db, [legacy.product(101, 7), legacy.product(102, 1)])
        self.assertEqual(db.products[102], external)
        self.assertEqual(db.writes, [])
        inserts = [q for q, _ in db.calls if 'INSERT INTO products (' in q]
        self.assertNotIn('ON CONFLICT', inserts[-1])
        lookup = [p for q, p in db.calls if q == ci._COMMERCE_STOCK_CODES_SQL]
        self.assertEqual(lookup, [{'c': [101]}])

    def test_whole_batch_order_500_and_protected_same_stock_preserved(self):
        db = self.db()
        prods = [legacy.product(101, 7, sp=200 + i) for i in range(501)]
        self.apply(db, prods)
        batches = [rows for q, rows in db.writes if q == 'products']
        self.assertEqual([len(rows) for rows in batches], [500, 1])
        self.assertEqual([p['sp2'] for rows in batches for p in rows], list(range(200, 701)))

    def test_real_modules_do_not_import_database_or_application(self):
        self.assertNotIn('api.db', sys.modules)
        self.assertNotIn('api.main', sys.modules)


if __name__ == '__main__':
    unittest.main()
