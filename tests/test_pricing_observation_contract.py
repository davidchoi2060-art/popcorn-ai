import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "api" / "pricing_observation_contract.py"
spec = importlib.util.spec_from_file_location("observation_contract_test", MODULE)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


def row(**changes):
    return dict(product_code=101, item_kind="core_part", handoff_id=1, line_no=1,
                created_at=NOW, price_mall=100, mall_status="ok") | changes


def select(records, **options):
    return contract.normalize_observations(records, product_code=options.get("product_code", 101),
                                           now=options.get("now", NOW))


class ObservationContractTests(unittest.TestCase):
    def test_empty_and_filtered_inputs_are_missing(self):
        for records in ([], [row(product_code=102, price_mall="bad")],
                        [row(item_kind="assembly_fee", price_mall="bad")],
                        [row(product_code=None)], [row(item_kind="other")]):
            with self.subTest(records=records):
                self.assertEqual(select(records)["state"], "missing")

    def test_native_kinds_and_whitelist(self):
        for kind in contract.OBS_KINDS:
            result = select([row(item_kind=kind, member_id=7, note="private", session_id=9)])
            self.assertEqual(result["state"], "selected")
            self.assertEqual(set(result["selected"]), {"product_code", "item_kind", "handoff_id",
                             "line_no", "created_at", "price_mall", "mall_status", "freshness"})

    def test_latest_null_does_not_fall_back(self):
        result = select([row(handoff_id=2, price_mall=None, mall_status=None),
                         row(created_at=NOW-timedelta(days=1))])
        self.assertEqual(result["state"], "selected")
        self.assertIsNone(result["selected"]["price_mall"])
        self.assertEqual(result["selected"]["handoff_id"], 2)

    def test_nullable_fields_must_be_present(self):
        for field in ("price_mall", "mall_status"):
            record = row(); del record[field]
            result = select([record])
            self.assertEqual(result["state"], "invalid")
            self.assertIn({"index": 0, "field": field, "code": "missing"}, result["errors"])

    def test_all_required_fields_and_bad_routing(self):
        for field in row():
            record = row(); del record[field]
            with self.subTest(field=field):
                self.assertEqual(select([record])["state"], "invalid")
        for record in (None, row(item_kind=None), row(product_code=True)):
            self.assertEqual(select([record])["state"], "invalid")

    def test_strict_integer_fields(self):
        for field in ("product_code", "handoff_id", "line_no", "price_mall"):
            for value in (True, "1", 1.0):
                with self.subTest(field=field, value=value):
                    self.assertEqual(select([row(**{field: value})])["state"], "invalid")
        for value in (True, "101", 101.0, None):
            self.assertEqual(select([], product_code=value)["state"], "invalid")

    def test_no_new_business_price_or_status_policy(self):
        for price in (0, -1, 10**20, None):
            self.assertEqual(select([row(price_mall=price, mall_status="unrecognized")])["state"],
                             "selected")
        for status in (True, 1, []):
            self.assertEqual(select([row(mall_status=status)])["state"], "invalid")

    def test_timezone_normalization_and_tie_across_offsets(self):
        other = NOW.astimezone(timezone(timedelta(hours=9)))
        result = select([row(handoff_id=2, created_at=other.isoformat()), row()])
        self.assertEqual(result["state"], "ambiguous")
        self.assertEqual({r["created_at"] for r in result["latest_candidates"]}, {NOW.isoformat()})
        self.assertEqual(select([row(created_at="2026-10-03T12:00:00Z")])["state"], "selected")

    def test_invalid_timestamps_fail_closed(self):
        for value in (None, "bad", "2026-10-03", "2026-10-03T12:00:00", NOW.replace(tzinfo=None),
                      True, 100):
            with self.subTest(value=value):
                result = select([row(handoff_id=2, created_at=value),
                                 row(created_at=NOW-timedelta(days=1))])
                self.assertEqual(result["state"], "invalid")
                self.assertIsNone(result["selected"])
                self.assertEqual(result["latest_candidates"], [])
                self.assertEqual(select([], now=value)["state"], "invalid")

    def test_equal_amount_and_time_are_still_ambiguous(self):
        records = [row(handoff_id=2, line_no=1), row(handoff_id=1, line_no=2), row()]
        result = select(records)
        self.assertEqual(result["state"], "ambiguous")
        self.assertIsNone(result["selected"])
        self.assertEqual([(r["handoff_id"], r["line_no"]) for r in result["latest_candidates"]],
                         [(2, 1), (1, 2), (1, 1)])
        self.assertEqual(result, select(list(reversed(records))))

    def test_older_ties_do_not_make_unique_latest_ambiguous(self):
        records = [row(handoff_id=3), row(created_at=NOW-timedelta(days=1)),
                   row(handoff_id=2, created_at=NOW-timedelta(days=1))]
        result = select(records)
        self.assertEqual(result["state"], "selected")
        self.assertEqual(len(result["candidates"]), 3)
        self.assertEqual(len(result["latest_candidates"]), 1)

    def test_duplicate_identity_is_invalid(self):
        for second in (row(), row(price_mall=110), row(created_at=NOW-timedelta(days=1))):
            result = select([row(), second])
            self.assertEqual(result["state"], "invalid")
            self.assertEqual(result["errors"][-1]["code"], "duplicate")

    def test_freshness_exact_boundaries_are_display_only(self):
        cases = [(8, 0, "fresh"), (8, 1, "mid"), (30, 0, "mid"), (30, 1, "stale"),
                 (31, 0, "stale"), (-1, 0, "fresh")]
        for days, seconds, expected in cases:
            result = select([row(created_at=NOW-timedelta(days=days, seconds=seconds))])
            self.assertEqual(result["state"], "selected")
            self.assertEqual(result["selected"]["freshness"], expected)

    def test_input_unchanged_and_repeated_calls_stable(self):
        records = [row(private={"secret": [1]}), row(handoff_id=2, created_at=NOW-timedelta(days=31))]
        original = copy.deepcopy(records)
        self.assertEqual(select(records), select(records))
        self.assertEqual(records, original)
        result = select(records); result["selected"]["price_mall"] = 999
        self.assertEqual(records, original)

    def test_invalid_container_and_errors_do_not_echo_private_data(self):
        for value in (None, "secret", {}, 1, (r for r in [])):
            self.assertEqual(select(value)["state"], "invalid")
        result = select([row(price_mall="private-password", note="sensitive")])
        self.assertNotIn("private-password", repr(result))
        self.assertNotIn("sensitive", repr(result))

    def test_isolated_import_has_no_application_modules_or_router(self):
        code = """import sys
from api import pricing_observation_contract as module
assert not hasattr(module, 'router')
assert not any(n.startswith(('sqlalchemy', 'fastapi', 'psycopg', 'api.db', 'api.main')) for n in sys.modules)
assert {n for n in sys.modules if n.startswith('api.')} == {'api.pricing_observation_contract'}
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, " +
                                repr(str(ROOT)) + ");\n" + code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
