"""Pure receipt comparison and conservative journal transitions.

Reprice uses this contract at its receipt boundary; the other actions remain pure contracts. The caller supplies
expected identity from a trusted server boundary, and supplies a candidate from
its own trusted transport. Matching data proves neither authentication nor
authorization, server authenticity, commit atomicity or business correctness.
Fingerprints and canonical versions are opaque: no hash, TTL, clock, ID creation,
database, driver, socket or application imports are used here.

Inputs are plain JSON dictionaries/lists with strict scalar types. Outputs are
fresh allowlisted projections; diagnostics never reflect input values or keys.
Identifier ranges and price/stock business rules are not introduced. UUID text
is case-normalized; other identity strings are compared exactly.
"""

import re


CONTRACT_VERSION = "admin_operation_v1"
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_IDENTITY_FIELDS = (
    "contract_version", "canonical_version", "operation_id", "actor_id",
    "environment", "action", "target", "request_fingerprint",
)
_TARGETS = {
    "reprice_apply": (("scope",), ()),
    "sourcing_request": (("product_code",), ()),
    "sourcing_reply": (("product_code", "quote_id"), ("batch_id", "supplier_id")),
    "sourcing_confirm": (("product_code", "quote_id"), ("batch_id", "supplier_id")),
    "stock_inbound": (("product_code",), ()),
    "stock_hold": (("product_code",), ()),
    "stock_hold_release": (("product_code", "hold_id"), ()),
    "stock_inbound_undo": (("product_code", "ref_log_id"), ()),
}
_RESULT_FIELDS = {
    "reprice_apply": {k: "int" for k in ("log_id", "changed", "up", "down", "locked", "dropped")},
    "sourcing_request": {"log_id": "int", "batch_id": "int", "quotes": "quotes"},
    "sourcing_reply": {"log_id": "int", "quote_id": "int", "price": "int"},
    "sourcing_confirm": {
        "log_id": "int", "quote_id": "int", "price": "int",
        "purchase_before": "nullable_int", "purchase_after": "nullable_int",
        "sale_before": "nullable_int", "sale_after": "nullable_int",
        "purchase_changed": "bool", "sale_changed": "bool", "sale_locked": "bool",
    },
    "stock_inbound": {
        "log_id": "int", "movement_id": "int", "stock_before": "int",
        "stock_after": "int", "status_changed": "bool", "pool_entered": "bool",
    },
    "stock_hold": {"log_id": "int", "hold_id": "int"},
    "stock_hold_release": {"log_id": "int", "hold_id": "int"},
    "stock_inbound_undo": {
        "log_id": "int", "ref_log_id": "int", "movement_id": "int",
        "stock_before": "int", "stock_after": "int",
    },
}
_UNKNOWN_STATES = {
    "unknown": "unconfirmed", "not_found": "not_found",
    "expired": "outside_retention", "outside_retention": "outside_retention",
    "accepted": "nonterminal", "in_progress": "nonterminal",
    "permission_denied": "permission_denied",
}
_EVENTS = frozenset((
    "prepare", "receipt", "reload", "current_read", "current_read_failed",
    "list_missing", "elapsed",
))


def _text(value):
    return type(value) is str and bool(value)


def _object(value):
    return type(value) is dict and all(type(key) is str for key in value)


def _identity(value):
    if not _object(value) or any(k not in value for k in _IDENTITY_FIELDS):
        return None
    if not _text(value["contract_version"]) or value["contract_version"] != CONTRACT_VERSION:
        return None
    for field in ("canonical_version", "environment", "request_fingerprint"):
        if not _text(value[field]):
            return None
    if type(value["actor_id"]) is not int:
        return None
    operation_id = value["operation_id"]
    if type(operation_id) is not str or _UUID.fullmatch(operation_id) is None:
        return None
    action = value["action"]
    if type(action) is not str or action not in _TARGETS:
        return None
    target = value["target"]
    required, optional = _TARGETS[action]
    if not _object(target) or not set(required).issubset(target):
        return None
    if not set(target).issubset(required + optional):
        return None
    if action == "reprice_apply":
        if type(target["scope"]) is not str or target["scope"] not in ("live", "selling", "all"):
            return None
    elif any(type(target[k]) is not int for k in target):
        return None
    result = {k: value[k] for k in _IDENTITY_FIELDS if k != "target"}
    result["operation_id"] = operation_id.lower()
    result["target"] = {k: target[k] for k in required + optional if k in target}
    return result


def _quotes(value):
    if type(value) is not list:
        return None
    result, seen = [], set()
    for quote in value:
        if not _object(quote):
            return None
        if any(k not in quote or type(quote[k]) is not int
               for k in ("quote_id", "supplier_id")):
            return None
        if quote["quote_id"] in seen:
            return None
        seen.add(quote["quote_id"])
        result.append({k: quote[k] for k in ("quote_id", "supplier_id")})
    return result


def _result(value, identity):
    if not _object(value):
        return None
    projected = {}
    for field, kind in _RESULT_FIELDS[identity["action"]].items():
        if field not in value:
            return None
        item = value[field]
        if kind == "quotes":
            item = _quotes(item)
            if item is None:
                return None
        elif kind == "int" and type(item) is not int:
            return None
        elif kind == "nullable_int" and item is not None and type(item) is not int:
            return None
        elif kind == "bool" and type(item) is not bool:
            return None
        projected[field] = item
    # Target IDs repeated inside a result must agree, even if optional here.
    for field, expected in identity["target"].items():
        if field in value:
            kind = str if identity["action"] == "reprice_apply" and field == "scope" else int
            if type(value[field]) is not kind or value[field] != expected:
                return None
            projected[field] = value[field]
    return projected


def _answer(state, reason, receipt=None):
    return {"state": state, "reason": reason, "receipt": receipt}


def validate_receipt(candidate, *, expected, transport_status=200):
    """Compare every identity field and project an applied/rejected receipt.

    ``expected`` has the eight identity fields listed in the module. Actor and
    environment must be established outside this function by the trusted caller.
    Targets have action-specific ID fields; extra target keys are invalid.
    Applied receipts require the action's typed result fields. Rejected receipts
    require a receipt_id and a result dictionary, whose contents are discarded:
    raw business messages, payload, memo, contacts and credentials are not exposed.

    None/404/410/401/403/other non-200 transport statuses never prove rejection or
    non-execution. A matched rejected receipt is a supplied terminal assertion,
    not a rollback proof created by this function. No retry decision is made.
    """
    identity = _identity(expected)
    if identity is None:
        return _answer("invalid", "invalid_expected")
    if transport_status is None:
        return _answer("unknown", "transport_failure")
    if type(transport_status) is not int or not 100 <= transport_status <= 599:
        return _answer("invalid", "invalid_transport_status")
    if transport_status == 404:
        return _answer("unknown", "not_found")
    if transport_status == 410:
        return _answer("unknown", "outside_retention")
    if transport_status in (401, 403):
        return _answer("unknown", "permission_denied")
    if transport_status != 200:
        return _answer("unknown", "unverified_http_status")
    supplied = _identity(candidate)
    if supplied is None:
        return _answer("invalid", "invalid_receipt")
    if supplied != identity:
        return _answer("invalid", "identity_mismatch")
    state = candidate.get("state")
    if type(state) is not str:
        return _answer("invalid", "invalid_state")
    if state in _UNKNOWN_STATES:
        return _answer("unknown", _UNKNOWN_STATES[state])
    if state not in ("applied", "rejected"):
        return _answer("invalid", "invalid_state")
    if not _text(candidate.get("receipt_id")):
        return _answer("invalid", "invalid_terminal_receipt")
    if state == "applied":
        result = _result(candidate.get("result"), identity)
    else:
        result = {} if _object(candidate.get("result")) else None
    if result is None:
        return _answer("invalid", "invalid_result")
    receipt = supplied | {"state": state, "receipt_id": candidate["receipt_id"],
                          "result": result}
    return _answer(state, "matched_" + state, receipt)


def transition_journal(current, *, expected, event, candidate=None, transport_status=200):
    """Return a new journal without resolving uncertainty from a product GET.

    Events: prepare, receipt, reload, current_read, current_read_failed,
    list_missing, elapsed. No event creates an ID, authorizes a write or requests
    a POST. A journal is bound to the full expected identity. A terminal ack is
    revalidated and preserved on lookup failures, foreign/late responses and
    conflicting terminal results. Ordinary GET contents and elapsed time have
    no authority over the operation outcome. Fresh context/authorization remain
    external requirements, including after applied or rejected.
    """
    identity = _identity(expected)
    output = {"phase": "invalid", "identity": identity, "receipt": None,
              "observation": "invalid", "reason": "invalid_journal",
              "automatic_post": False, "allows_new_operation": False,
              "requires_fresh_context": True}
    if identity is None:
        output["reason"] = "invalid_expected"
        return output
    if type(event) is not str or event not in _EVENTS:
        output["reason"] = "invalid_event"
        return output
    phase, saved = "writing", None
    if current is not None:
        if not _object(current) or _identity(current.get("identity")) != identity:
            return output
        phase = current.get("phase")
        if type(phase) is not str or phase not in ("writing", "uncertain", "applied", "rejected"):
            return output
        saved = current.get("receipt")
        if phase in ("applied", "rejected"):
            validated = validate_receipt(saved, expected=identity)
            if validated["state"] != phase:
                return output
            saved = validated["receipt"]
        elif saved is not None:
            return output
    elif event != "prepare":
        return output
    output.update(phase=phase, receipt=saved, observation="unknown", reason="unchanged")
    if event == "receipt":
        observed = validate_receipt(candidate, expected=identity,
                                    transport_status=transport_status)
        output.update(observation=observed["state"], reason=observed["reason"])
        if saved is not None:
            if observed["receipt"] is not None and observed["receipt"] != saved:
                output.update(observation="invalid", reason="terminal_receipt_conflict")
        elif observed["state"] in ("applied", "rejected"):
            output.update(phase=observed["state"], receipt=observed["receipt"])
        else:
            output["phase"] = "uncertain"
    elif event == "reload" and phase == "writing":
        output.update(phase="uncertain", reason="interrupted_write")
    elif event in ("current_read", "current_read_failed", "list_missing", "elapsed"):
        output["reason"] = "product_observation_does_not_resolve_operation"
    return output
