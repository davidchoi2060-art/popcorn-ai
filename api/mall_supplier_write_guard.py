"""Caller-owned mall PSP write scope; no parsing, network or transaction creation."""
from sqlalchemy import text

from .pricing_write_guard_core import lock_products, ProductScopeChanged

_CONTACT_LOCK_SQL = (
    "SELECT supplier_id FROM suppliers WHERE supplier_id = ANY(:ids)"
    " ORDER BY supplier_id FOR NO KEY UPDATE"
)
_SUPPLIER_SCOPE_SQL = (
    "SELECT supplier_id FROM suppliers WHERE supplier_id = ANY(:ids)"
    " ORDER BY supplier_id"
)


class SupplierScopeChanged(RuntimeError):
    """Abort the caller transaction; never expand the selected supplier scope."""


def _ids(values):
    if type(values) not in (list, tuple) or any(type(sid) is not int or sid <= 0 for sid in values):
        raise SupplierScopeChanged("supplier_scope_changed")
    return tuple(sorted(set(values)))


def _same_ids(observed, expected):
    if (type(observed) is not list or any(type(sid) is not int or sid <= 0 for sid in observed)
            or tuple(observed) != expected):
        raise SupplierScopeChanged("supplier_scope_changed")


def lock_mall_write_scope(conn, product_code, supplier_ids, contact_supplier_ids):
    """Product first, contact targets ascending, then validate the fixed FK scope.

    NO KEY UPDATE is compatible with FK KEY SHARE; FOR UPDATE would also block
    unrelated PSP writers that only reference the supplier. Only contact targets
    acquire this protection. The caller retains the original PSP/contact order.
    This validates current numeric identities, not names, revisions or ABA.
    """
    lock_products(conn, [product_code])
    current = conn.execute(text(
        "SELECT product_code FROM products WHERE product_code=:pc"),
        {"pc": product_code}).scalar()
    if type(current) is not int or current != product_code:
        raise ProductScopeChanged("product_scope_changed")
    expected = _ids(supplier_ids)
    contacts = _ids(contact_supplier_ids)
    if not set(contacts).issubset(expected):
        raise SupplierScopeChanged("supplier_scope_changed")
    if contacts:
        observed = conn.execute(text(_CONTACT_LOCK_SQL), {"ids": list(contacts)}).scalars().all()
        _same_ids(observed, contacts)
    if expected:
        observed = conn.execute(text(_SUPPLIER_SCOPE_SQL), {"ids": list(expected)}).scalars().all()
        _same_ids(observed, expected)
    return expected
