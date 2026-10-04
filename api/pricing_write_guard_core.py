"""Acquire one caller transaction's complete product set before child locks."""
from sqlalchemy import text

_LOCK_PRODUCTS_SQL = (
    "SELECT product_code FROM products WHERE product_code = ANY(:codes)"
    " ORDER BY product_code FOR UPDATE"
)


class ProductScopeChanged(RuntimeError):
    """The caller must abort this transaction; no retry or late scope expansion."""


def lock_products(conn, product_codes):
    """Lock sorted unique native positive integer IDs; never own a transaction."""
    if type(product_codes) not in (list, tuple) or any(
        type(code) is not int or code <= 0 for code in product_codes
    ):
        raise ProductScopeChanged("product_scope_changed")
    expected = tuple(sorted(set(product_codes)))
    if not expected:
        return ()
    observed = conn.execute(text(_LOCK_PRODUCTS_SQL), {"codes": list(expected)}).scalars().all()
    if type(observed) is not list or any(
        type(code) is not int or code <= 0 for code in observed
    ) or tuple(observed) != expected:
        raise ProductScopeChanged("product_scope_changed")
    return expected
