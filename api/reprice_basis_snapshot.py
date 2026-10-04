"""One statement pricing basis read, with caller-owned transaction and policy guard.

The caller must already hold the shared (or exclusive) pricing policy guard and
use the migrated application schema/search_path. This helper owns no connection,
locks or transaction. Revision tokens do not freeze unselected rows/phantoms.
"""
from decimal import Decimal
import json
import math

from sqlalchemy import text
from sqlalchemy.exc import NoResultFound

from .pricing import resolve_margins


class InvalidRepriceBasisSnapshot(ValueError):
    """The same-statement basis is missing or malformed; never invent tokens."""


_RAW_FIELDS = ("product_code", "product_name", "part_type", "purchase_price", "sale_price",
               "status", "stock_qty", "locked_fields", "category_id")
_SCOPES = {"live": "p.status = '판매중' AND p.stock_qty > 0",
           "selling": "p.status = '판매중'", "all": "TRUE"}
_SQL = """
WITH scoped_products AS (
  SELECT p.product_code,p.product_name,p.part_type,p.purchase_price,p.sale_price,
         p.status,p.stock_qty,p.locked_fields,p.category_id,p.pricing_basis_revision
  FROM products p
  WHERE p.purchase_price IS NOT NULL AND p.purchase_price > 0 AND {scope_condition}
), latest_settings AS (
  SELECT card_fee_rate,margin_rate FROM pricing_settings
  ORDER BY effective_from DESC LIMIT 1
)
SELECT jsonb_build_object(
  'products',COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.product_code) FROM scoped_products p),'[]'::jsonb),
  'settings',(SELECT to_jsonb(s) FROM latest_settings s),
  'nodes',COALESCE((SELECT jsonb_agg(jsonb_build_array(category_id,parent_id) ORDER BY category_id) FROM categories),'[]'::jsonb),
  'margins',COALESCE((SELECT jsonb_agg(jsonb_build_array(category_id,margin_rate) ORDER BY category_id) FROM category_margin_policies),'[]'::jsonb),
  'policy_tokens',COALESCE((SELECT jsonb_agg(jsonb_build_object('singleton',singleton,'revision',revision) ORDER BY singleton)
                           FROM pricing_basis_policy_revision),'[]'::jsonb)
)::text AS basis
"""


def _invalid():
    raise InvalidRepriceBasisSnapshot("missing_or_invalid_pricing_basis")


def _positive_int(value):
    return type(value) is int and 0 < value <= 9223372036854775807


def _number(value):
    if type(value) not in (int, Decimal) or (type(value) is Decimal and not value.is_finite()):
        _invalid()
    return value


def _pairs_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def read_basis(conn, scope):
    """Return raw9 rows, product_revisions, policy_revision, fee, margin and mmap.

    SQL errors propagate unchanged. Missing pricing_settings retains the original
    _settings().one() NoResultFound failure, unlike a valid empty product/tree set.
    """
    if type(scope) is not str or scope not in _SCOPES:
        raise InvalidRepriceBasisSnapshot("invalid_scope")
    raw = conn.execute(text(_SQL.format(scope_condition=_SCOPES[scope]))).scalar_one()
    if type(raw) is not str:
        _invalid()
    try:
        payload = json.loads(raw, parse_float=Decimal,
                             parse_constant=lambda value: _invalid(), object_pairs_hook=_pairs_object)
    except (TypeError, ValueError):
        _invalid()
    if type(payload) is not dict or set(payload) != {"products", "settings", "nodes", "margins", "policy_tokens"}:
        _invalid()
    tokens = payload["policy_tokens"]
    if (type(tokens) is not list or len(tokens) != 1 or type(tokens[0]) is not dict
            or set(tokens[0]) != {"singleton", "revision"} or type(tokens[0]["singleton"]) is not int
            or tokens[0]["singleton"] != 1 or not _positive_int(tokens[0]["revision"])):
        _invalid()
    settings = payload["settings"]
    if settings is None:
        raise NoResultFound("No row was found when one was required")
    if type(settings) is not dict or set(settings) != {"card_fee_rate", "margin_rate"}:
        _invalid()
    fee, margin = float(_number(settings["card_fee_rate"])), float(_number(settings["margin_rate"]))
    if not math.isfinite(fee) or not math.isfinite(margin):
        _invalid()
    products = payload["products"]
    if type(products) is not list:
        _invalid()
    rows, revisions, last_code = [], {}, None
    for row in products:
        if type(row) is not dict or set(row) != set(_RAW_FIELDS) | {"pricing_basis_revision"}:
            _invalid()
        code = row["product_code"]
        if (type(code) is not int or code <= 0 or (last_code is not None and code <= last_code)
                or not _positive_int(row["pricing_basis_revision"])):
            _invalid()
        for field in ("product_name", "part_type", "status"):
            if row[field] is not None and type(row[field]) is not str:
                _invalid()
        for field in ("stock_qty", "category_id"):
            if row[field] is not None and type(row[field]) is not int:
                _invalid()
        for field in ("purchase_price", "sale_price"):
            if row[field] is not None:
                _number(row[field])
        if row["purchase_price"] is None or row["purchase_price"] <= 0:
            _invalid()
        if scope == "selling" and row["status"] != "판매중":
            _invalid()
        if scope == "live" and (row["status"] != "판매중" or row["stock_qty"] is None or row["stock_qty"] <= 0):
            _invalid()
        locks = row["locked_fields"]
        if locks is not None and (type(locks) is not list or any(type(v) is not str for v in locks)):
            _invalid()
        rows.append({field: row[field] for field in _RAW_FIELDS})
        revisions[code] = row["pricing_basis_revision"]
        last_code = code
    nodes, own = [], {}
    for name in ("nodes", "margins"):
        pairs = payload[name]
        if type(pairs) is not list:
            _invalid()
        last_id = None
        for pair in pairs:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not int:
                _invalid()
            cid, value = pair
            if last_id is not None and cid <= last_id:
                _invalid()
            if name == "nodes":
                if value is not None and type(value) is not int:
                    _invalid()
                nodes.append((cid, value))
            else:
                rate = float(_number(value))
                if not math.isfinite(rate):
                    _invalid()
                own[cid] = rate
            last_id = cid
    mmap = {cid: rate for cid, (rate, source) in resolve_margins(nodes, own, margin).items()}
    return {"rows": rows, "product_revisions": revisions, "policy_revision": tokens[0]["revision"],
            "fee": fee, "margin": margin, "mmap": mmap}
