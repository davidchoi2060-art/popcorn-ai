"""Pure contract for supplied handoff observations; no database or write policy.

The caller must supply the complete relevant input snapshot. ``created_at`` is
the handoff creation time, not an external measurement or commit timestamp.
Sorting identities orders candidates only: equal newest times remain ambiguous.
Freshness is display metadata, never permission to apply a price. This module
does not provide snapshot isolation, latest-at-commit, ABA protection or receipts.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone


OBS_KINDS = ("core_part", "peripheral")
_FIELDS = ("handoff_id", "line_no", "created_at", "price_mall", "mall_status")


def _aware_utc(value):
    if isinstance(value, str):
        # Only timestamps with an explicit offset are accepted; no local zone.
        if "T" not in value and " " not in value:
            raise ValueError("timestamp_required")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("aware_timestamp_required")
    return value.astimezone(timezone.utc)


def _freshness(at, now):
    if at < now - timedelta(days=30):
        return "stale"
    if at < now - timedelta(days=8):
        return "mid"
    return "fresh"


def normalize_observations(records, *, product_code, now):
    """Return selected/missing/ambiguous/invalid and whitelisted candidates.

    ``records`` is a sequence of mappings containing the native join fields:
    product_code, item_kind, handoff_id, line_no, created_at, price_mall and
    mall_status. A missing nullable field is invalid, explicit None is valid.
    Integer fields reject bool, strings and floats. Price range and status
    business rules are deliberately not introduced here.

    ``now`` must be an aware datetime or explicit-offset ISO timestamp. Providing
    it makes repeated calls deterministic. Out-of-scope products/kinds (including
    native NULL product codes) are ignored before payload validation. Bad routing
    fields or bad relevant records make the entire result invalid: valid older
    rows cannot conceal a possibly newer malformed observation. Duplicate native
    keys are invalid input, including identical copies; callers should supply
    one row per native key rather than a multiplied join.

    Errors expose only row index, field and code, never raw input or extra fields.
    No caller-owned mappings/lists are modified.
    """
    result = {"state": "invalid", "selected": None, "candidates": [],
              "latest_candidates": [], "errors": []}

    def error(index, field, code):
        result["errors"].append({"index": index, "field": field, "code": code})

    if type(product_code) is not int:
        error(None, "product_code", "strict_integer_required")
    try:
        reference = _aware_utc(now)
    except (ValueError, TypeError, OverflowError):
        error(None, "now", "aware_timestamp_required")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        error(None, "records", "sequence_required")
    if result["errors"]:
        return result

    normalized = []
    seen = set()
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            error(index, "record", "mapping_required")
            continue
        if "product_code" not in row:
            error(index, "product_code", "missing")
            continue
        pc = row["product_code"]
        if pc is None:
            continue
        if type(pc) is not int:
            error(index, "product_code", "strict_integer_required")
            continue
        if pc != product_code:
            continue
        if "item_kind" not in row:
            error(index, "item_kind", "missing")
            continue
        if type(row["item_kind"]) is not str:
            error(index, "item_kind", "string_required")
            continue
        if row["item_kind"] not in OBS_KINDS:
            continue
        missing = [field for field in _FIELDS if field not in row]
        for field in missing:
            error(index, field, "missing")
        if missing:
            continue
        before = len(result["errors"])
        for field in ("handoff_id", "line_no"):
            if type(row[field]) is not int:
                error(index, field, "strict_integer_required")
        if row["price_mall"] is not None and type(row["price_mall"]) is not int:
            error(index, "price_mall", "nullable_strict_integer_required")
        if row["mall_status"] is not None and type(row["mall_status"]) is not str:
            error(index, "mall_status", "nullable_string_required")
        try:
            at = _aware_utc(row["created_at"])
        except (ValueError, TypeError, OverflowError):
            error(index, "created_at", "aware_timestamp_required")
        if len(result["errors"]) != before:
            continue
        key = (row["handoff_id"], row["line_no"])
        if key in seen:
            error(index, "identity", "duplicate")
            continue
        seen.add(key)
        candidate = {"product_code": pc, "item_kind": row["item_kind"],
                     "handoff_id": key[0], "line_no": key[1],
                     "created_at": at.isoformat(), "price_mall": row["price_mall"],
                     "mall_status": row["mall_status"],
                     "freshness": _freshness(at, reference)}
        normalized.append((at, candidate))

    normalized.sort(key=lambda pair: (pair[0], pair[1]["handoff_id"],
                                      pair[1]["line_no"]), reverse=True)
    result["candidates"] = [candidate for _, candidate in normalized]
    if result["errors"]:
        return result
    if not normalized:
        result["state"] = "missing"
        return result
    newest = normalized[0][0]
    latest = [candidate for at, candidate in normalized if at == newest]
    result["latest_candidates"] = latest
    if len(latest) > 1:
        result["state"] = "ambiguous"
    else:
        result["state"] = "selected"
        result["selected"] = latest[0]
    return result
