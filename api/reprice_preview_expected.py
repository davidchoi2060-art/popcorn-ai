"""Value-only preview identity; no revision/ABA, auth, receipt or TX ownership.

v1 normalizes finite int/float/Decimal numbers by exact decimal value (float
uses str), including signed zero, without rounding or Decimal-context changes.
Null, bool, text and ordered lists remain distinct. Object keys are sorted;
numeric policy/margin keys are represented as sorted pairs. Row/lock and actual
up+down plan order are retained. All scoped rows and effective margins count,
including unchanged/locked and cap-excluded products, so drift is conservative.
"""
from collections.abc import Mapping
from decimal import Decimal
import hashlib
import json


EXPECTED_VERSION = "reprice_basis_v1"
_SCOPES = ("live", "selling", "all")
_ROW_FIELDS = (
    "product_code", "product_name", "part_type", "purchase_price", "sale_price",
    "status", "stock_qty", "locked_fields", "category_id",
)
_CLASS_FIELDS = {"up", "down", "same", "locked", "outlier", "negative", "margins_used"}


class InvalidPreviewBasis(ValueError):
    """The basis cannot be represented by this closed canonical contract."""


def _number(value):
    if type(value) not in (int, float, Decimal):
        raise InvalidPreviewBasis("invalid_number")
    number = Decimal(str(value)) if type(value) is not Decimal else value
    if not number.is_finite():
        raise InvalidPreviewBasis("nonfinite_number")
    sign, digits, exponent = number.as_tuple()
    if not any(digits):
        return ["number", 0, "0", 0]
    digits = "".join(str(d) for d in digits)
    trimmed = digits.rstrip("0")
    return ["number", sign, trimmed, exponent + len(digits) - len(trimmed)]


def _canonical(value):
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) in (int, float, Decimal):
        return _number(value)
    if type(value) is str:
        return ["text", value]
    if type(value) in (list, tuple):
        return ["list", [_canonical(v) for v in value]]
    if isinstance(value, Mapping) and all(type(k) is str for k in value):
        return ["object", [[k, _canonical(value[k])] for k in sorted(value)]]
    raise InvalidPreviewBasis("unsupported_value")


def canonical_basis(*, scope, rows, fee, margin, mmap, max_apply):
    """Validate raw inputs BEFORE classification and retain every raw field."""
    if type(scope) is not str or scope not in _SCOPES:
        raise InvalidPreviewBasis("invalid_scope")
    if type(max_apply) is not int or max_apply <= 0:
        raise InvalidPreviewBasis("invalid_cap")
    _number(fee)
    _number(margin)
    if not isinstance(mmap, Mapping) or any(type(k) is not int for k in mmap):
        raise InvalidPreviewBasis("invalid_margin_map")
    policies = [[k, mmap[k]] for k in sorted(mmap)]
    for _, rate in policies:
        _number(rate)
    projected = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(_ROW_FIELDS):
            raise InvalidPreviewBasis("invalid_row_fields")
        if type(row["product_code"]) is not int:
            raise InvalidPreviewBasis("invalid_product_code")
        for field in ("stock_qty", "category_id"):
            if row[field] is not None and type(row[field]) is not int:
                raise InvalidPreviewBasis("invalid_integer_field")
        for field in ("product_name", "part_type", "status"):
            if row[field] is not None and type(row[field]) is not str:
                raise InvalidPreviewBasis("invalid_text_field")
        for field in ("purchase_price", "sale_price"):
            if row[field] is not None:
                _number(row[field])
        locks = row["locked_fields"]
        if locks is not None and (type(locks) is not list or any(type(v) is not str for v in locks)):
            raise InvalidPreviewBasis("invalid_locks")
        projected.append({field: row[field] for field in _ROW_FIELDS})
    return _canonical({"scope": scope, "rows": projected, "fee": fee,
                       "margin": margin, "mmap": policies, "max_apply": max_apply})


def make_expected(basis, classification, *, scope, max_apply):
    """Hash full classification plus the existing ordered and capped plan."""
    if set(classification) != _CLASS_FIELDS:
        raise InvalidPreviewBasis("invalid_classification")
    calculation = dict(classification)
    calculation["margins_used"] = [[k, v] for k, v in sorted(classification["margins_used"].items())]
    targets = classification["up"] + classification["down"]
    plan = {"changed": len(targets), "selected_codes": [t["product_code"] for t in targets[:max_apply]],
            "dropped": max(0, len(targets) - max_apply)}
    payload = {"version": EXPECTED_VERSION, "basis": basis,
               "classification": _canonical(calculation), "plan": _canonical(plan)}
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    return {"version": EXPECTED_VERSION, "scope": scope,
            "fingerprint": hashlib.sha256(encoded).hexdigest()}


EXPECTED_VERSION_V2 = "reprice_basis_v2"


def canonical_basis_v2(*, scope, rows, fee, margin, mmap, max_apply,
                       product_revisions, policy_revision):
    """Retain v1's whole basis, plus exact native BIGINT generation evidence."""
    basis = canonical_basis(scope=scope, rows=rows, fee=fee, margin=margin,
                            mmap=mmap, max_apply=max_apply)
    def token(value):
        return type(value) is int and 0 < value <= 9223372036854775807
    codes = [row["product_code"] for row in rows]
    if (any(type(code) is not int or code <= 0 for code in codes) or len(set(codes)) != len(codes)
            or not isinstance(product_revisions, Mapping)
            or any(type(code) is not int or code <= 0 for code in product_revisions)
            or set(product_revisions) != set(codes) or not token(policy_revision)
            or any(not token(value) for value in product_revisions.values())):
        raise InvalidPreviewBasis("invalid_revision_evidence")
    revisions = {"product_revisions": [[code, product_revisions[code]] for code in sorted(codes)],
                 "policy_revision": policy_revision}
    return [EXPECTED_VERSION_V2, basis, _canonical(revisions)]


def make_expected_v2(basis, classification, *, scope, max_apply):
    """Domain-separate v2, reusing the unchanged full classification/plan hash."""
    if type(basis) is not list or len(basis) != 3 or basis[0] != EXPECTED_VERSION_V2:
        raise InvalidPreviewBasis("invalid_v2_basis")
    previous = make_expected(basis, classification, scope=scope, max_apply=max_apply)
    encoded = json.dumps([EXPECTED_VERSION_V2, previous], ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode("ascii")
    return {"version": EXPECTED_VERSION_V2, "scope": scope,
            "fingerprint": hashlib.sha256(encoded).hexdigest()}
