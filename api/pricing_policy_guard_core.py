"""Caller-TX policy guard for participating pricing/tree writers and reprice.

One two-int key (ASCII POPC, pricing-policy 1), distinct from bigint keys.
Acquire policy before product/child locks; choose shared OR exclusive at entry,
never upgrade. Missing policy rows still use this same key. Only participating
callers are protected: no revision, preview ABA, actor or receipt guarantee.
"""
from sqlalchemy import text

_POLICY_LOCK_PARAMS = {"namespace": 1347375171, "key": 1}
_SHARED_SQL = "SELECT pg_catalog.pg_advisory_xact_lock_shared(:namespace,:key)"
_EXCLUSIVE_SQL = "SELECT pg_catalog.pg_advisory_xact_lock(:namespace,:key)"


def lock_pricing_policy_shared(conn):
    """Hold shared policy guard until the caller transaction ends."""
    conn.execute(text(_SHARED_SQL), _POLICY_LOCK_PARAMS.copy())


def lock_pricing_policy_exclusive(conn):
    """Hold exclusive policy guard until the caller transaction ends."""
    conn.execute(text(_EXCLUSIVE_SQL), _POLICY_LOCK_PARAMS.copy())
