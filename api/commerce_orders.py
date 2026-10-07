"""Owned stored order detail only. No order/payment writes or provider calls."""
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import commerce_contract as c
from . import commerce_owner as owner
from . import commerce_owner_contexts as owner_http
from . import commerce_writer as writer

router = APIRouter(prefix='/api/commerce', tags=['commerce'])
_HEADERS = {'Cache-Control': 'no-store'}
# Existing ORD identifiers and the writer's opaque ASCII identifiers fit the
# persisted VARCHAR(20). This endpoint does not invent an issuing convention.
_ORDER_NO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,19}\Z')


def _inputs(request, order_no):
    if type(order_no) is not str or not _ORDER_NO.fullmatch(order_no):
        raise owner.OwnerError(422, 'invalid_order_no')
    query = request.query_params
    values = query.getlist('expected_binding_id')
    if set(query.keys()) != {'expected_binding_id'} or len(values) != 1:
        raise owner.OwnerError(422, 'invalid_order_request')
    return owner.expected_binding(values[0])


def _scope_probe(conn, order_no, context):
    # Restrict ownership BEFORE loading financial bundles or validating their
    # proof/cardinality. Foreign and absent orders have the same public error.
    row = conn.execute(text('''/*commerce_http:scope_probe*/ SELECT 1
        FROM orders o JOIN commerce_order_details d USING(order_id)
        WHERE o.order_no=:order_no AND d.context_id=CAST(:context_id AS uuid)
          AND d.owner_scope=:owner_scope AND d.owner_identity=CAST(:identity AS jsonb)'''),
        dict(order_no=order_no, context_id=context.context_id, owner_scope=context.owner_scope,
             identity=json.dumps(context.owner_identity, sort_keys=True, separators=(',', ':')))).first()
    if row is None:
        raise owner.OwnerError(404, 'order_not_found')


def _stored_detail(engine, request, order_no, expected):
    with engine.connect() as conn:
        try:
            owner.ensure_ready(conn)
            now = owner.database_now(conn)
            context = owner.lookup_context(conn, request.cookies.get(owner.COOKIE),
                                           expected_binding_id=expected, now=now)
            if context is None:
                raise owner.OwnerError(401, 'owner_context_lost')
            _scope_probe(conn, order_no, context)
            stored = writer.read_committed_order(conn, order_no, context_id=context.context_id,
                                                  owner=context.owner_identity, now=now)
            # Read completion time, not a provider approval or sale-stock time.
            checked_at = owner.database_now(conn)
            permissions = {key: dict(allowed=False, reason='route_unavailable', expected_basis=None)
                           for key in c.CUSTOMER_ACTIONS}
            record = dict(row=stored['row'], basis=dict(state='unconfirmed', basis_id=None),
                          permissions=permissions,
                          balances=dict(approved=stored['approved'], refunded=stored['refunded']))
            return c.order_envelope([record], audience='customer', context=context.public(),
                                    checked_at=checked_at, detail=True)
        finally:
            conn.rollback()


@router.get('/orders/{order_no}')
def read_order_detail(order_no: str, request: Request):
    try:
        policy = owner_http.get_policy()
        owner_http._secure_request(request, policy)
        expected = _inputs(request, order_no)
        payload = _stored_detail(owner_http.get_engine(), request, order_no, expected)
        return JSONResponse(payload, headers=_HEADERS)
    except owner.OwnerError as error:
        return owner_http._error(error)
    except c.CommerceError as error:
        if error.code in ('order_not_found', 'owner_mismatch'):
            public = owner.OwnerError(404, 'order_not_found')
        elif error.code == 'owner_unconfirmed':
            public = owner.OwnerError(401, 'owner_context_lost')
        else:
            public = owner.OwnerError(503, 'order_detail_unavailable')
        return owner_http._error(public)
    except Exception:
        return owner_http._error(owner.OwnerError(503, 'order_detail_unavailable'))
