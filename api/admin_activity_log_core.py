"""Connection-injected legacy activity INSERT; transaction belongs to caller.

This module neither establishes actor authenticity/authorization nor adds a
receipt or commit/rollback guarantee. The injected actor lookup runs once before
the unchanged json.dumps(detail), at the original parameter-evaluation point.
No operational application modules or connection/engine factories are imported.
"""

import json

from sqlalchemy import text


def log_action(conn, action: str, target_id: str, detail: dict, kind: str = "order", *,
               operator_id) -> int:
    """Execute on conn and return scalar unchanged, including a supplied NULL."""
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, :k, :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": operator_id(), "a": action, "k": kind, "t": target_id,
         "d": json.dumps(detail)}).scalar()
