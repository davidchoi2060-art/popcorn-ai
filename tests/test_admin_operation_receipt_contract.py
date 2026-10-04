"""Pure supplied-data tests; no server, authorization or DB atomicity proof."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


MODULE = Path(__file__).resolve().parents[1] / "api" / "admin_operation_receipt_contract.py"
SPEC = importlib.util.spec_from_file_location("receipt_contract_test", MODULE)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
OPERATION = "a51b8342-62c8-4ac9-bbef-54e3386049d8"
OTHER_OPERATION = "ab4b8342-62c8-4ac9-bbef-54e3386049d8"
ACTIONS = (
    "sourcing_request", "sourcing_reply", "sourcing_confirm", "stock_inbound",
    "stock_hold", "stock_hold_release", "stock_inbound_undo",
)


def identity(action="stock_inbound", **changes):
    target = {"product_code": 101}
    if action in ("sourcing_reply", "sourcing_confirm"):
        target.update(quote_id=301, batch_id=201, supplier_id=401)
    if action == "stock_hold_release":
        target["hold_id"] = 501
    if action == "stock_inbound_undo":
        target["ref_log_id"] = 601
    return dict(contract_version=contract.CONTRACT_VERSION, canonical_version="test-canon-v0",
                operation_id=OPERATION, actor_id=11, environment="isolated-fixture",
                action=action, target=target, request_fingerprint="opaque-fixture-value") | changes


def applied_result(action):
    common = {"log_id": 701}
    return common | {
        "sourcing_request": {"batch_id": 201, "quotes": [{"quote_id": 301, "supplier_id": 401}]},
        "sourcing_reply": {"quote_id": 301, "price": 142000},
        "sourcing_confirm": {
            "quote_id": 301, "price": 142000,
            "purchase_before": None, "purchase_after": 142000,
            "sale_before": 160000, "sale_after": 160000,
            "purchase_changed": True, "sale_changed": False, "sale_locked": True,
        },
        "stock_inbound": {"movement_id": 801, "stock_before": 0, "stock_after": 5,
                          "status_changed": True, "pool_entered": False},
        "stock_hold": {"hold_id": 501},
        "stock_hold_release": {"hold_id": 501},
        "stock_inbound_undo": {"ref_log_id": 601, "movement_id": 802,
                               "stock_before": 5, "stock_after": 0},
    }[action]


def receipt(expected=None, *, state="applied", **changes):
    expected = copy.deepcopy(expected or identity())
    result = applied_result(expected["action"]) if state == "applied" else {}
    return expected | {"state": state, "receipt_id": "receipt-fixture-1", "result": result} | changes


def prepare(expected=None):
    return contract.transition_journal(None, expected=expected or identity(), event="prepare")


def receive(current, candidate, expected=None, status=200):
    return contract.transition_journal(current, expected=expected or identity(), event="receipt",
                                       candidate=candidate, transport_status=status)


class ReceiptContractTests(unittest.TestCase):
    def test_seven_actions_have_separate_typed_projections(self):
        for action in ACTIONS:
            expected = identity(action)
            candidate = receipt(expected)
            candidate.update(token="DO_NOT_EXPOSE", memo="DO_NOT_EXPOSE")
            candidate["result"].update(password="DO_NOT_EXPOSE", contact_raw="DO_NOT_EXPOSE",
                                       memo="DO_NOT_EXPOSE", reason="DO_NOT_EXPOSE")
            with self.subTest(action=action):
                output = contract.validate_receipt(candidate, expected=expected)
                self.assertEqual(output["state"], "applied")
                self.assertEqual(output["receipt"]["result"], applied_result(action))
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_each_required_identity_field_is_checked(self):
        expected = identity()
        for field in expected:
            for remove_from in ("expected", "candidate"):
                e, c = copy.deepcopy(expected), receipt(expected)
                del (e if remove_from == "expected" else c)[field]
                with self.subTest(field=field, remove_from=remove_from):
                    self.assertEqual(contract.validate_receipt(c, expected=e)["state"], "invalid")

    def test_all_identity_mismatches_are_invalid_without_reflection(self):
        expected = identity("sourcing_confirm")
        changes = {
            "contract_version": "DO_NOT_EXPOSE", "canonical_version": "DO_NOT_EXPOSE",
            "operation_id": OTHER_OPERATION, "actor_id": 12, "environment": "DO_NOT_EXPOSE",
            "action": "sourcing_reply", "request_fingerprint": "DO_NOT_EXPOSE",
        }
        for field, value in changes.items():
            candidate = receipt(expected, **{field: value}, private="DO_NOT_EXPOSE")
            with self.subTest(field=field):
                output = contract.validate_receipt(candidate, expected=expected)
                self.assertEqual(output["state"], "invalid")
                self.assertIsNone(output["receipt"])
                self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_exact_target_fields_and_optional_identity(self):
        expected = identity("sourcing_confirm")
        for field in expected["target"]:
            candidate = receipt(expected)
            candidate["target"][field] += 1
            self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")
        for target in ({"product_code": 101}, expected["target"] | {"secret": "DO_NOT_EXPOSE"},
                       {k: v for k, v in expected["target"].items() if k != "supplier_id"}):
            output = contract.validate_receipt(receipt(expected, target=target), expected=expected)
            self.assertEqual(output["state"], "invalid")
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_result_target_ids_must_match(self):
        for action, field in (("sourcing_reply", "quote_id"), ("stock_hold_release", "hold_id"),
                              ("stock_inbound_undo", "ref_log_id"), ("stock_inbound", "product_code")):
            expected = identity(action)
            candidate = receipt(expected)
            candidate["result"][field] = expected["target"][field] + 1
            with self.subTest(action=action):
                self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")

    def test_uuid_syntax_and_case_are_explicit(self):
        expected = identity(operation_id=OPERATION.upper())
        output = contract.validate_receipt(receipt(identity()), expected=expected)
        self.assertEqual(output["state"], "applied")
        self.assertEqual(output["receipt"]["operation_id"], OPERATION)
        for value in (None, 1, True, OPERATION.replace("-", ""), " " + OPERATION, "DO_NOT_EXPOSE"):
            self.assertEqual(contract.validate_receipt(receipt(), expected=identity(operation_id=value))["state"],
                             "invalid")

    def test_fingerprint_and_canonical_version_are_opaque_exact_values(self):
        expected = identity(canonical_version="caller-defined-variant", request_fingerprint="not-a-hash")
        self.assertEqual(contract.validate_receipt(receipt(expected), expected=expected)["state"], "applied")
        for field in ("canonical_version", "request_fingerprint", "environment"):
            for bad in (None, 1, True, ""):
                self.assertEqual(contract.validate_receipt(receipt(), expected=identity(**{field: bad}))["state"],
                                 "invalid")
            candidate = receipt(expected, **{field: expected[field] + " "})
            self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")

    def test_strict_integer_identity_rejects_bool_string_float(self):
        for action in ACTIONS:
            for bad in (True, False, "101", 101.0):
                expected = identity(action, actor_id=bad)
                self.assertEqual(contract.validate_receipt(receipt(identity(action)), expected=expected)["state"],
                                 "invalid")
                for field in identity(action)["target"]:
                    expected = identity(action)
                    expected["target"][field] = bad
                    self.assertEqual(contract.validate_receipt(receipt(identity(action)), expected=expected)
                                     ["state"], "invalid")

    def test_required_result_fields_and_strict_types_for_all_actions(self):
        for action in ACTIONS:
            expected = identity(action)
            for field, value in applied_result(action).items():
                candidate = receipt(expected)
                del candidate["result"][field]
                with self.subTest(action=action, missing=field):
                    self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")
                if type(value) is int:
                    bad_values = (True, str(value), float(value))
                elif type(value) is bool:
                    bad_values = (1, "true", None)
                elif value is None:
                    bad_values = (True, "0", 0.0)
                else:
                    bad_values = (None, {}, "DO_NOT_EXPOSE")
                for bad in bad_values:
                    candidate = receipt(expected)
                    candidate["result"][field] = bad
                    self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")

    def test_nullable_prices_and_no_new_business_range_policy(self):
        expected = identity("sourcing_confirm")
        for value in (None, 0, -1, 10**30):
            candidate = receipt(expected)
            for field in ("purchase_before", "purchase_after", "sale_before", "sale_after"):
                candidate["result"][field] = value
            self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "applied")

    def test_request_quotes_projection_and_duplicate_keys(self):
        expected = identity("sourcing_request")
        candidate = receipt(expected)
        candidate["result"]["quotes"][0]["contact_raw"] = "DO_NOT_EXPOSE"
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(contract.validate_receipt(candidate, expected=expected)))
        for quotes in ([{"quote_id": 301, "supplier_id": True}], [{"quote_id": 301}],
                       [{"quote_id": 301, "supplier_id": 401}] * 2, [None]):
            candidate = receipt(expected)
            candidate["result"]["quotes"] = quotes
            self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "invalid")

    def test_rejected_receipt_is_distinct_and_raw_reason_is_dropped(self):
        for action in ACTIONS:
            expected = identity(action)
            candidate = receipt(expected, state="rejected", result={"detail": "DO_NOT_EXPOSE",
                                                                     "email": "DO_NOT_EXPOSE"})
            output = contract.validate_receipt(candidate, expected=expected)
            self.assertEqual(output["state"], "rejected")
            self.assertEqual(output["receipt"]["result"], {})
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_terminal_receipts_need_id_and_object_result(self):
        for state in ("applied", "rejected"):
            for changes in ({"receipt_id": None}, {"receipt_id": ""}, {"result": None}, {"result": []}):
                self.assertEqual(contract.validate_receipt(receipt(state=state, **changes), expected=identity())
                                 ["state"], "invalid")

    def test_404_expiry_permission_and_transport_failure_never_become_rejected(self):
        reasons = {404: "not_found", 410: "outside_retention", 401: "permission_denied",
                   403: "permission_denied", None: "transport_failure", 500: "unverified_http_status",
                   409: "unverified_http_status", 422: "unverified_http_status", 202: "unverified_http_status"}
        for status, reason in reasons.items():
            output = contract.validate_receipt({"detail": "DO_NOT_EXPOSE"}, expected=identity(),
                                               transport_status=status)
            self.assertEqual((output["state"], output["reason"]), ("unknown", reason))
            self.assertIsNone(output["receipt"])
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_nonterminal_body_states_and_unknown_states(self):
        for state in ("unknown", "not_found", "expired", "outside_retention", "accepted",
                      "in_progress", "permission_denied"):
            self.assertEqual(contract.validate_receipt(receipt(state=state), expected=identity())["state"],
                             "unknown")
        for state in ("DO_NOT_EXPOSE", True, None, [], {}):
            output = contract.validate_receipt(receipt(state=state), expected=identity())
            self.assertEqual(output["state"], "invalid")
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))

    def test_invalid_shapes_and_hostile_non_json_values_are_not_reflected(self):
        class Private:
            def __repr__(self):
                raise AssertionError("DO_NOT_EXPOSE")

            def __eq__(self, other):
                raise AssertionError("DO_NOT_EXPOSE")

        for candidate in (None, [], "DO_NOT_EXPOSE", Private(), {"private": Private()}):
            self.assertEqual(contract.validate_receipt(candidate, expected=identity())["state"], "invalid")
        candidate = receipt(contract_version=Private())
        self.assertEqual(contract.validate_receipt(candidate, expected=identity())["state"], "invalid")
        for bad in (True, "200", 200.0, 99, 600, Private()):
            self.assertEqual(contract.validate_receipt(receipt(), expected=identity(), transport_status=bad)
                             ["state"], "invalid")
        candidate = receipt(extra=Private())
        self.assertEqual(contract.validate_receipt(candidate, expected=identity())["state"], "applied")

    def test_inputs_remain_unchanged_and_outputs_do_not_alias(self):
        expected = identity("sourcing_request")
        candidate = receipt(expected)
        original = copy.deepcopy((expected, candidate))
        first = contract.validate_receipt(candidate, expected=expected)
        self.assertEqual(first, contract.validate_receipt(candidate, expected=expected))
        first["receipt"]["target"]["product_code"] = 999
        first["receipt"]["result"]["quotes"][0]["quote_id"] = 999
        self.assertEqual((expected, candidate), original)
        self.assertEqual(contract.validate_receipt(candidate, expected=expected)["state"], "applied")

    def test_plain_json_key_types_only(self):
        for expected in (identity() | {7: "private"}, identity(target={"product_code": 101, 7: "private"})):
            self.assertEqual(contract.validate_receipt(receipt(), expected=expected)["state"], "invalid")


class JournalTransitionTests(unittest.TestCase):
    def test_prepare_is_bound_and_never_authorizes_post(self):
        state = prepare()
        self.assertEqual(state["phase"], "writing")
        self.assertEqual(state["identity"], identity())
        self.assertFalse(state["automatic_post"])
        self.assertFalse(state["allows_new_operation"])

    def test_reload_changes_writing_to_uncertain_without_retry(self):
        state = contract.transition_journal(prepare(), expected=identity(), event="reload")
        self.assertEqual(state["phase"], "uncertain")
        self.assertIsNone(state["receipt"])
        self.assertFalse(state["automatic_post"])

    def test_lost_response_then_matched_receipt_recovers_seven_actions(self):
        for action in ACTIONS:
            expected = identity(action)
            state = receive(prepare(expected), None, expected, None)
            self.assertEqual(state["phase"], "uncertain")
            recovered = receive(state, receipt(expected), expected)
            self.assertEqual(recovered["phase"], "applied")
            self.assertTrue(recovered["requires_fresh_context"])
            self.assertFalse(recovered["allows_new_operation"])

    def test_known_ack_survives_every_lookup_failure_and_foreign_late_reply(self):
        state = receive(prepare(), receipt())
        before = copy.deepcopy(state)
        for candidate, status in ((None, None), ({}, 404), ({}, 410), ({}, 401), ({}, 403), ({}, 500),
                                  (None, 200), (receipt(operation_id=OTHER_OPERATION), 200),
                                  (receipt(actor_id=12, private="DO_NOT_EXPOSE"), 200),
                                  (receipt(target={"product_code": 102}), 200)):
            output = receive(state, candidate, status=status)
            self.assertEqual(output["phase"], "applied")
            self.assertEqual(output["receipt"], state["receipt"])
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))
        self.assertEqual(state, before)

    def test_rejected_ack_remains_rejected_after_lookup_failure(self):
        state = receive(prepare(), receipt(state="rejected"))
        output = receive(state, {}, status=404)
        self.assertEqual(output["phase"], "rejected")
        self.assertEqual(output["receipt"], state["receipt"])
        self.assertEqual(output["observation"], "unknown")

    def test_lost_response_recovery_then_failed_current_read(self):
        uncertain = receive(prepare(), None, status=None)
        known = receive(uncertain, receipt())
        observed = contract.transition_journal(known, expected=identity(), event="current_read_failed")
        self.assertEqual(observed["phase"], "applied")
        self.assertEqual(observed["receipt"], known["receipt"])
        self.assertFalse(observed["automatic_post"])
        self.assertTrue(observed["requires_fresh_context"])

    def test_rejected_receipt_cannot_turn_applied_after_conditions_change(self):
        rejected = receive(prepare(), receipt(state="rejected"))
        observed = receive(rejected, receipt())
        self.assertEqual(observed["phase"], "rejected")
        self.assertEqual(observed["receipt"], rejected["receipt"])
        self.assertEqual(observed["reason"], "terminal_receipt_conflict")

    def test_conflicting_terminal_receipt_never_replaces_known_result(self):
        state = receive(prepare(), receipt())
        alternatives = [receipt(state="rejected"), receipt(receipt_id="different-receipt")]
        changed = receipt()
        changed["result"]["stock_after"] = 10
        alternatives.append(changed)
        for candidate in alternatives:
            output = receive(state, candidate)
            self.assertEqual(output["phase"], "applied")
            self.assertEqual(output["receipt"], state["receipt"])
            self.assertEqual((output["observation"], output["reason"]),
                             ("invalid", "terminal_receipt_conflict"))

    def test_identical_receipt_replay_is_stable(self):
        state = receive(prepare(), receipt())
        self.assertEqual(receive(state, receipt()), state)

    def test_product_same_value_list_exit_and_time_do_not_resolve_uncertainty(self):
        state = receive(prepare(), None, status=None)
        for event in ("current_read", "current_read_failed", "list_missing", "elapsed", "prepare"):
            output = contract.transition_journal(state, expected=identity(), event=event,
                                                 candidate={"product_code": 101, "stock_after": 5})
            self.assertEqual(output["phase"], "uncertain")
            self.assertIsNone(output["receipt"])
            self.assertFalse(output["automatic_post"])

    def test_current_read_failure_after_ack_preserves_ack(self):
        state = receive(prepare(), receipt())
        for event in ("current_read_failed", "current_read", "list_missing", "elapsed", "reload", "prepare"):
            output = contract.transition_journal(state, expected=identity(), event=event)
            self.assertEqual(output["receipt"], state["receipt"])
            self.assertEqual(output["phase"], "applied")
            self.assertTrue(output["requires_fresh_context"])

    def test_404_does_not_prove_no_later_commit(self):
        state = receive(prepare(), {}, status=404)
        self.assertEqual(state["phase"], "uncertain")
        self.assertEqual(receive(state, receipt())["phase"], "applied")

    def test_old_v1_or_corrupted_journal_cannot_be_promoted(self):
        old = {"mode": "stock", "code": 101, "phase": "uncertain", "body": {"qty": 5}}
        for state in (old, {"identity": identity(), "phase": "saved"}, [], "DO_NOT_EXPOSE", None):
            output = contract.transition_journal(state, expected=identity(), event="reload")
            self.assertEqual(output["phase"], "invalid")
            self.assertIsNone(output["receipt"])
            self.assertFalse(output["automatic_post"])

    def test_other_account_environment_new_id_cannot_reuse_journal(self):
        state = receive(prepare(), receipt())
        for changed in (identity(actor_id=12), identity(environment="other-env"),
                        identity(operation_id=OTHER_OPERATION)):
            output = contract.transition_journal(state, expected=changed, event="reload")
            self.assertEqual(output["phase"], "invalid")
            self.assertIsNone(output["receipt"])

    def test_saved_ack_and_phase_must_agree(self):
        state = receive(prepare(), receipt())
        for changes in ({"phase": "rejected"}, {"phase": "uncertain"},
                        {"receipt": receipt(actor_id=12)}, {"receipt": None}):
            output = contract.transition_journal(state | changes, expected=identity(), event="reload")
            self.assertEqual(output["phase"], "invalid")

    def test_journal_input_immutability_and_repeated_observations(self):
        state = receive(prepare(), receipt())
        original = copy.deepcopy(state)
        first = contract.transition_journal(state, expected=identity(), event="current_read_failed")
        self.assertEqual(first, contract.transition_journal(first, expected=identity(), event="current_read_failed"))
        first["receipt"]["result"]["stock_after"] = 999
        first["identity"]["target"]["product_code"] = 999
        self.assertEqual(state, original)

    def test_invalid_event_and_expected_fail_closed(self):
        for event in (None, True, [], "DO_NOT_EXPOSE"):
            output = contract.transition_journal(prepare(), expected=identity(), event=event)
            self.assertEqual(output["phase"], "invalid")
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(output))
        output = contract.transition_journal(prepare(), expected={}, event="reload")
        self.assertEqual(output["phase"], "invalid")


class IndependentImportTests(unittest.TestCase):
    def test_module_import_does_not_import_application_network_or_database(self):
        source = """
import builtins, importlib.util, sys
original = builtins.__import__
blocked = {'api', 'main', 'socket', 'sqlite3', 'psycopg', 'psycopg2', 'sqlalchemy',
           'asyncpg', 'requests', 'http', 'urllib'}
def checked(name, *args, **kwargs):
    if name.split('.')[0] in blocked:
        raise AssertionError('forbidden import')
    return original(name, *args, **kwargs)
builtins.__import__ = checked
spec = importlib.util.spec_from_file_location('isolated_contract', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('independent import passed')
"""
        output = subprocess.run([sys.executable, "-I", "-B", "-c", source, str(MODULE)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(output.stdout.strip(), "independent import passed")


if __name__ == "__main__":
    unittest.main()
