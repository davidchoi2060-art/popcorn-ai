"""Automatic source fills must not lock fields (2026-10-09).

The 2026-09-30 runs of tools/enrich_pc_catalog_sources.py and
tools/repair_pc_audit_evidence.py added manufacturer, merchant and audit values
to products.locked_fields. A lock means "a person entered this" to the
review-queue checks, so those unconfirmed values looked confirmed. Only the
admin spec-entry path may lock. These tests run each tool's apply() on a
recording fake connection and check that specs are written and locks are not.
They also check that both tools refuse a field locked as `field` or
`specs.field` before writing anything (repair had no such check until
2026-10-09), and the spec_sources value each tool stores.
"""
import copy
import json
import unittest
from unittest.mock import patch

from api.part_explanations import fingerprint
import tools.enrich_pc_catalog_sources as enrich
import tools.repair_pc_audit_evidence as repair


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def one(self):
        assert len(self._rows) == 1, self._rows
        return self._rows[0]

    def __iter__(self):
        return iter(self._rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class FakeConn:
    """Answers the SELECTs the tools issue and records every statement."""

    def __init__(self, explanation, product, spec):
        self.explanation, self.product, self.spec = explanation, product, spec
        self.sql = []

    def execute(self, stmt, params=None):
        q = " ".join(str(stmt).split())
        self.sql.append((q, params or {}))
        if q.startswith("SELECT * FROM product_explanations"):
            return _Result([copy.deepcopy(self.explanation)])
        if q.startswith("SELECT * FROM product_specs"):
            return _Result([copy.deepcopy(self.spec)])
        if q.startswith("SELECT") and "FROM products" in q:
            return _Result([copy.deepcopy(self.product)])
        if q.startswith("SELECT DISTINCT configuration_id"):
            return _Result([])
        return _Result([])

    def writes(self, table):
        return [(q, p) for q, p in self.sql if q.startswith("UPDATE %s " % table)]


LOCKED_MSG = r"^Locked field requires review$"


def updates(conn):
    return [q for q, _ in conn.sql if q.startswith(("UPDATE", "INSERT", "DELETE"))]


def _fixture(code, spec):
    name, src = "Exact model", "spec text"
    explanation = dict(source_product_code=code, product_code=code, status="draft",
                       source_fingerprint=fingerprint(name, src), source_snapshot={},
                       content=dict(slot="COOLER", sources=[], facts=[]))
    product = dict(product_code=code, product_name=name, spec_source_text=src,
                   locked_fields=["cost_price"], status="판매중")
    snapshot = dict(rows=[dict(explanation, product_name=name, spec_source_text=src,
                               sale_status="판매중")],
                    specs=[spec], configs=[])
    return explanation, product, snapshot


class NoAutoLockTests(unittest.TestCase):
    @staticmethod
    def saved_sources(conn):
        saved = [p["v"] for q, p in conn.writes("product_specs") if "SET spec_sources=" in q]
        assert len(saved) == 1, saved
        return json.loads(saved[0])

    def assert_no_lock(self, conn):
        locks = [q for q, _ in conn.sql if "locked_fields" in q and not q.startswith("SELECT")]
        self.assertEqual(locks, [], "automatic source fill wrote locked_fields")

    def test_enrich_fills_spec_without_lock(self):
        spec = dict(product_code=120906, cooler_tdp=None, gpu_power_draw_watt=None, spec_sources={})
        explanation, product, snapshot = _fixture(120906, spec)
        item = dict(code=120906, specs=dict(cooler_tdp=280), facts=[], note="n",
                    source=dict(id="mfr", kind="manufacturer", url="https://example.com/c"))
        conn = FakeConn(explanation, product, spec)
        enrich.apply(conn, snapshot, [item])
        filled = [p for q, p in conn.writes("product_specs") if "SET cooler_tdp=" in q]
        self.assertEqual(filled, [dict(code=120906, value=280)])
        self.assertEqual(self.saved_sources(conn),
                         {"cooler_tdp": "manufacturer:2026-09-30:https://example.com/c"})
        self.assert_no_lock(conn)

    def test_enrich_still_refuses_human_locked_field(self):
        spec = dict(product_code=120906, cooler_tdp=None, gpu_power_draw_watt=None, spec_sources={})
        explanation, product, snapshot = _fixture(120906, spec)
        product["locked_fields"] = ["specs.cooler_tdp"]
        item = dict(code=120906, specs=dict(cooler_tdp=280), facts=[], note="n",
                    source=dict(id="mfr", kind="manufacturer", url="https://example.com/c"))
        conn = FakeConn(explanation, product, spec)
        with self.assertRaisesRegex(AssertionError, LOCKED_MSG):
            enrich.apply(conn, snapshot, [item])
        self.assertEqual(updates(conn), [])

    def test_repair_fills_spec_without_lock(self):
        spec = dict(product_code=129775, mem_type=None, spec_sources={})
        explanation, product, snapshot = _fixture(129775, spec)
        conn = FakeConn(explanation, product, spec)
        with patch.object(repair, "FACT_CODES", set()), \
             patch.object(repair, "SPEC_REPAIRS", {129775: dict(mem_type="DDR5")}):
            repair.apply(conn, snapshot)
        filled = [p for q, p in conn.writes("product_specs") if "SET mem_type=" in q]
        self.assertEqual(filled, [dict(code=129775, v="DDR5")])
        self.assertEqual(self.saved_sources(conn), {
            "mem_type": "audit:2026-09-30:https://www.popcornpc.co.kr/shop/product_detail.html?pd_no=129775"})
        self.assert_no_lock(conn)

    def repair_114723(self, locked_fields, sources=None):
        # The real 114723 entry: socket_list already has a value and is overwritten when unlocked.
        old = ["AM4", "AM5"]
        spec = dict(product_code=114723, socket_list=old, spec_sources=dict(sources or {}))
        explanation, product, snapshot = _fixture(114723, spec)
        product["locked_fields"] = locked_fields
        return FakeConn(explanation, product, spec), snapshot

    def run_repair_114723(self, conn, snapshot):
        with patch.object(repair, "FACT_CODES", set()), \
             patch.object(repair, "SPEC_REPAIRS", {114723: repair.SPEC_REPAIRS[114723]}):
            repair.apply(conn, snapshot)

    def test_repair_overwrites_unlocked_114723_with_audit_source(self):
        conn, snapshot = self.repair_114723(["cost_price"])
        self.run_repair_114723(conn, snapshot)
        filled = [json.loads(p["v"]) for q, p in conn.writes("product_specs") if "SET socket_list=" in q]
        self.assertEqual(filled, [repair.SPEC_REPAIRS[114723]["socket_list"]])
        self.assertEqual(self.saved_sources(conn), {"socket_list": "audit:2026-09-30:" + repair.THERMAL})
        self.assert_no_lock(conn)

    def test_existing_spec_sources_keys_are_kept(self):
        # Writing one field's source must not drop other fields' sources.
        other = {"socket": "manual:2026-08-01:admin", "cooler_height_mm": "danawa:x"}
        conn, snapshot = self.repair_114723(["cost_price"], sources=other)
        self.run_repair_114723(conn, snapshot)
        self.assertEqual(self.saved_sources(conn),
                         dict(other, socket_list="audit:2026-09-30:" + repair.THERMAL))

        spec = dict(product_code=120906, cooler_tdp=None, gpu_power_draw_watt=None,
                    spec_sources=dict(other))
        explanation, product, snapshot = _fixture(120906, spec)
        item = dict(code=120906, specs=dict(cooler_tdp=280), facts=[], note="n",
                    source=dict(id="mfr", kind="manufacturer", url="https://example.com/c"))
        conn = FakeConn(explanation, product, spec)
        enrich.apply(conn, snapshot, [item])
        self.assertEqual(self.saved_sources(conn),
                         dict(other, cooler_tdp="manufacturer:2026-09-30:https://example.com/c"))

    def test_repair_refuses_locked_field_in_either_spelling_and_writes_nothing(self):
        for locks in (["specs.socket_list"], ["socket_list"]):
            with self.subTest(locks=locks):
                conn, snapshot = self.repair_114723(locks)
                with self.assertRaisesRegex(AssertionError, LOCKED_MSG):
                    self.run_repair_114723(conn, snapshot)
                self.assertEqual(updates(conn), [])
        # Same for a NULL-fill target, checked on the connection itself.
        for locks in (["specs.mem_type"], ["mem_type"]):
            with self.subTest(locks=locks):
                spec = dict(product_code=129775, mem_type=None, spec_sources={})
                explanation, product, snapshot = _fixture(129775, spec)
                product["locked_fields"] = locks
                conn = FakeConn(explanation, product, spec)
                with patch.object(repair, "FACT_CODES", set()), \
                     patch.object(repair, "SPEC_REPAIRS", {129775: dict(mem_type="DDR5")}):
                    with self.assertRaisesRegex(AssertionError, LOCKED_MSG):
                        repair.apply(conn, snapshot)
                self.assertEqual(updates(conn), [])

    def test_enrich_refuses_bare_field_lock_too(self):
        spec = dict(product_code=120906, cooler_tdp=None, gpu_power_draw_watt=None, spec_sources={})
        explanation, product, snapshot = _fixture(120906, spec)
        product["locked_fields"] = ["cooler_tdp"]
        item = dict(code=120906, specs=dict(cooler_tdp=280), facts=[], note="n",
                    source=dict(id="mfr", kind="manufacturer", url="https://example.com/c"))
        conn = FakeConn(explanation, product, spec)
        with self.assertRaisesRegex(AssertionError, LOCKED_MSG):
            enrich.apply(conn, snapshot, [item])
        self.assertEqual(updates(conn), [])


if __name__ == "__main__":
    unittest.main()
