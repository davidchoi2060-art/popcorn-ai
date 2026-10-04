"""Reprice-only terminal receipts; SQL uses the caller's connection/transaction.

No pending row or independent transaction is created. A full rollback therefore
also removes the UUID/payload binding; an absent lookup cannot prove rejection.
"""
import hashlib
import json
import os
import re
from uuid import uuid4

from sqlalchemy import text

from .admin_operation_receipt_contract import CONTRACT_VERSION, validate_receipt

CANONICAL_VERSION = "reprice_request_v1"
ACTION = "reprice_apply"
SCOPES = ("live", "selling", "all")
MAX_SAFE_INTEGER = 9007199254740991
OPERATION_NAMESPACE = 1347375186  # ASCII POPR, separate from policy POPC.
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_UUID = re.compile(UUID_PATTERN)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
RESULT_FIELDS = ("log_id", "changed", "up", "down", "locked", "dropped")
OPERATION_LOCK_SQL = "SELECT pg_catalog.pg_advisory_xact_lock(:namespace,:key)"
_COLUMNS = ("environment, operation_id, receipt_id, actor_id, action, contract_version, "
            "canonical_version, scope, request_fingerprint, state, result, response_body, "
            "original_http_status, log_id")
LOOKUP_SQL = ("SELECT " + _COLUMNS + " FROM admin_operation_receipts "
              "WHERE environment=:environment AND operation_id=:operation_id")
OWN_LOOKUP_SQL = LOOKUP_SQL + " AND actor_id=:actor_id AND action=:action"
INSERT_SQL = ("INSERT INTO admin_operation_receipts "
              "(environment,operation_id,receipt_id,actor_id,action,contract_version,"
              "canonical_version,scope,request_fingerprint,state,result,response_body,"
              "original_http_status,log_id) VALUES "
              "(:environment,:operation_id,:receipt_id,:actor_id,:action,:contract_version,"
              ":canonical_version,:scope,:request_fingerprint,:state,CAST(:result AS jsonb),"
              "CAST(:response_body AS jsonb),:original_http_status,:log_id)")


class ReceiptUnavailable(ValueError):
    pass


class OperationConflict(ValueError):
    pass


class PrewriteRejected(Exception):
    """Only explicitly identified domain checks before any mutation create this."""
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail
        super().__init__(detail)


def _uuid(value):
    return type(value) is str and len(value) == 36 and _UUID.fullmatch(value) is not None


def _safe_int(value, *, positive=False):
    return type(value) is int and (1 if positive else 0) <= value <= MAX_SAFE_INTEGER


def configured_environment():
    # Validate on invocation: a missing setting must not break module discovery.
    value = os.environ.get("ADMIN_OPERATION_ENVIRONMENT")
    if not _uuid(value):
        raise ReceiptUnavailable("재산정 요청 확인 환경이 설정되지 않았습니다")
    return value


def operation_context(operator):
    if (type(operator) is not dict or operator.get("role") != "owner"
            or not _safe_int(operator.get("operator_id"), positive=True)):
        raise OperationConflict("재산정 요청의 권한을 확인할 수 없습니다")
    return {"contract_version": CONTRACT_VERSION, "canonical_version": CANONICAL_VERSION,
            "actor_id": operator["operator_id"], "environment": configured_environment(),
            "action": ACTION}


def request_fingerprint(payload):
    """Versioned validated command, not raw HTTP JSON whitespace/key order."""
    if type(payload) is not dict:
        raise OperationConflict("재산정 요청을 확인할 수 없습니다")
    scope, count, expected, note = (payload.get(k) for k in
                                    ("scope", "expect_changed", "expected", "note"))
    if (scope not in SCOPES or not _safe_int(count) or type(expected) is not dict
            or set(expected) != {"version", "scope", "fingerprint"}
            or expected["version"] not in ("reprice_basis_v1", "reprice_basis_v2") or expected["scope"] not in SCOPES
            or type(expected["fingerprint"]) is not str
            or _SHA.fullmatch(expected["fingerprint"]) is None or type(note) is not str):
        raise OperationConflict("재산정 요청을 확인할 수 없습니다")
    command = [CANONICAL_VERSION, ACTION, scope, str(count),
               [expected["version"], expected["scope"], expected["fingerprint"]], note]
    try:
        raw = json.dumps(command, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except UnicodeError:
        raise OperationConflict("재산정 요청을 확인할 수 없습니다") from None
    return hashlib.sha256(raw).hexdigest()


def prepare_reprice_operation(body, operator):
    context = operation_context(operator)
    if body.operation_context.model_dump() != context or not _uuid(body.operation_id):
        raise OperationConflict("재산정 요청 정보가 다릅니다")
    fingerprint = request_fingerprint(body.model_dump())
    if fingerprint != body.request_fingerprint:
        raise OperationConflict("재산정 요청 정보가 다릅니다")
    return context | {"operation_id": body.operation_id, "target": {"scope": body.scope},
                      "request_fingerprint": fingerprint}


def operation_lock_params(identity):
    if not _uuid(identity.get("environment")) or not _uuid(identity.get("operation_id")):
        raise OperationConflict("재산정 요청 정보가 다릅니다")
    raw = (identity["environment"] + "|" + identity["operation_id"]).encode("ascii")
    return {"namespace": OPERATION_NAMESPACE,
            "key": int.from_bytes(hashlib.sha256(raw).digest()[:4], "big", signed=True)}


def lock_operation(conn, identity):
    conn.execute(text(OPERATION_LOCK_SQL), operation_lock_params(identity))


def lookup_operation(conn, identity, *, owned=False):
    params = {k: identity[k] for k in ("environment", "operation_id")}
    if owned:
        params.update(actor_id=identity["actor_id"], action=ACTION)
    return conn.execute(text(OWN_LOOKUP_SQL if owned else LOOKUP_SQL), params).mappings().first()


def operation_record(row, *, expected=None):
    """Validate stored identity, proof projection and exact original response."""
    identity = {k: row[k] for k in ("contract_version", "canonical_version", "actor_id",
                                    "action", "request_fingerprint")}
    identity.update(environment=str(row["environment"]), operation_id=str(row["operation_id"]),
                    target={"scope": row["scope"]})
    if expected is not None and identity != expected:
        raise OperationConflict("재산정 요청 정보가 다릅니다")
    receipt = identity | {"receipt_id": str(row["receipt_id"]), "state": row["state"],
                          "result": row["result"]}
    checked = validate_receipt(receipt, expected=identity)
    response, status = row["response_body"], row["original_http_status"]
    if (checked["state"] not in ("applied", "rejected")
            or identity["canonical_version"] != CANONICAL_VERSION
            or not _uuid(identity["environment"]) or not _uuid(receipt["receipt_id"])
            or not _safe_int(identity["actor_id"], positive=True) or type(response) is not dict
            or type(status) is not int):
        raise RuntimeError("Invalid stored reprice receipt")
    if checked["state"] == "applied":
        if (status != 200 or set(response) != set(RESULT_FIELDS) | {"verdict"}
                or type(response["verdict"]) is not str
                or any(not _safe_int(response.get(k), positive=(k == "log_id"))
                       or response[k] != checked["receipt"]["result"][k] for k in RESULT_FIELDS)
                or row["log_id"] != response["log_id"]):
            raise RuntimeError("Invalid stored reprice result")
    elif (status not in (400, 409) or row["log_id"] is not None or row["result"] != {}
          or set(response) != {"detail"} or type(response["detail"]) is not str):
        raise RuntimeError("Invalid stored reprice rejection")
    return {"receipt": checked["receipt"], "response_body": dict(response), "http_status": status}


def store_operation(conn, identity, response, *, status=200):
    state = "applied" if status == 200 else "rejected"
    result = {k: response[k] for k in RESULT_FIELDS} if state == "applied" else {}
    row = identity | {"scope": identity["target"]["scope"], "receipt_id": str(uuid4()),
                      "state": state, "result": result, "response_body": response,
                      "original_http_status": status, "log_id": result.get("log_id")}
    record = operation_record(row, expected=identity)
    params = {k: row[k] for k in ("environment", "operation_id", "receipt_id", "actor_id",
              "action", "contract_version", "canonical_version", "scope", "request_fingerprint",
              "state", "original_http_status", "log_id")}
    params.update(result=json.dumps(result, ensure_ascii=False),
                  response_body=json.dumps(response, ensure_ascii=False))
    # A unique collision MUST roll back preceding business writes, never skip this INSERT.
    conn.execute(text(INSERT_SQL), params)
    return record
