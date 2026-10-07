"""Current public BOM in a caller-owned, read-only database snapshot.

No route, connection factory, sale approval, price allocation or image serving.
source_reader is a trusted SERVER producer for the unchanged publication core.
The caller must open a fresh READ ONLY REPEATABLE READ/SERIALIZABLE transaction;
an old snapshot cannot report a withdrawal committed after its snapshot began.
"""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import text


def _deny():
    return {'status': 404, 'error': 'not_public'}


def _snapshot(conn, expected=None):
    if (conn.in_transaction() is not True or conn.in_nested_transaction()
            or conn.get_execution_options().get('isolation_level') == 'AUTOCOMMIT'):
        raise HTTPException(503, 'customer_snapshot_required')
    transaction = conn.get_transaction()
    if transaction is None or (expected is not None and transaction is not expected):
        raise HTTPException(503, 'customer_snapshot_changed')
    isolation = conn.execute(text('SHOW transaction_isolation')).scalar_one()
    readonly = conn.execute(text('SHOW transaction_read_only')).scalar_one()
    if isolation not in ('repeatable read', 'serializable') or readonly != 'on':
        raise HTTPException(503, 'customer_readonly_snapshot_required')
    if conn.get_transaction() is not transaction or conn.in_transaction() is not True:
        raise HTTPException(503, 'customer_snapshot_changed')
    return transaction


def _same_source(bound, captured, permission):
    config, parts, offers, review, rows = (captured[key] for key in
                                         ('configuration', 'parts', 'offers', 'review', 'rows'))
    detail = bound['detail']
    identity, revision = bound['configuration_id'], bound['revision']
    if (bound['customer_publishable'] is not False or detail['customer_publishable'] is not False
            or bound['price_is_snapshot'] is not True or detail['price_is_snapshot'] is not True
            or any(detail.get(key) != value for key, value in config.items())
            or sorted(offers, key=lambda o: o['offer_id']) != sorted(detail['offers'], key=lambda o: o['offer_id'])
            or review != detail['current_review']
            or permission.get('configuration_id') != identity
            or type(permission.get('revision')) is not int or permission['revision'] != revision
            or permission.get('basis') != review['basis']
            or permission.get('allowed') is not True or permission.get('state') != 'approved'
            or permission.get('source_state') != 'current'
            or not isinstance(permission.get('publication_basis'), str)
            or permission['publication_basis'] != permission.get('event_publication_basis')):
        return False
    raw = {p['ordinal']: p for p in parts}
    private = {p['ordinal']: p for p in detail['parts']}
    if len(raw) != len(parts) or len(private) != len(detail['parts']) or set(raw) != set(private):
        return False
    for ordinal, part in raw.items():
        other = private[ordinal]
        if any(other.get(key) != value for key, value in part.items()):
            return False
        if not part['pseudo']:
            row = rows.get(part['explanation_code'])
            if not row or other.get('explanation') != row['content']:
                return False
    return True


def _public_parts(parts, rows):
    result = []
    for part in parts:
        # Pseudo rows carry no fictitious SKU, product copy or invented facts.
        content = {} if part['pseudo'] else rows[part['explanation_code']]['content']
        name = content.get('name')
        role = content.get('role')
        facts = content.get('facts')
        result.append(dict(ordinal=part['ordinal'], name=name if isinstance(name, str) else None,
                           description=role if isinstance(role, str) else None,
                           specs=[dict(label=f['label'], value=f['value']) for f in facts
                                  if isinstance(f, dict) and isinstance(f.get('label'), str)
                                  and isinstance(f.get('value'), str)] if isinstance(facts, list) else []))
    return result


def read_customer_sold_offer(conn, product_code, *, source_reader=None):
    """Return the public allowlist or an indistinguishable not_public response.

    Consumes the actual registered offer resolver and publication.read_current,
    without changing either private DTO's False flag. Permission applies only to
    this snapshot. No guessed whole-PC/part photo URL, current price/stock, FPS,
    source IDs, approval actor, raw basis, private content or history exits.
    """
    if type(product_code) is not int or not 0 < product_code <= 2**63 - 1:
        raise HTTPException(422, 'customer_product_code_invalid')
    transaction = _snapshot(conn)
    if not callable(source_reader):
        return _deny()
    from .pc_configuration_copy import read_sold_offer_configuration
    from .pc_customer_publication import read_current
    from .pc_sales_conditions import customer_conditions
    from .customer_pc_projection import project_configuration

    captured = None

    def observe(connection, **inputs):
        nonlocal captured
        if connection is not conn or captured is not None:
            raise HTTPException(503, 'customer_source_reader_binding_invalid')
        _snapshot(conn, transaction)
        captured = deepcopy(inputs)
        proofs = source_reader(connection, **deepcopy(inputs))
        _snapshot(conn, transaction)
        return proofs

    try:
        sold = conn.execute(text('SELECT product_code,status FROM products WHERE product_code=:code'),
                            {'code': product_code}).mappings().first()
        if (not sold or type(sold.get('product_code')) is not int
                or sold['product_code'] != product_code or sold.get('status') != '판매중'):
            return _deny()
        bound = read_sold_offer_configuration(conn, product_code)
        _snapshot(conn, transaction)
        permission = read_current(conn, bound['configuration_id'], source_reader=observe)
        _snapshot(conn, transaction)
        if captured is None or not _same_source(bound, captured, permission):
            return _deny()
        config, parts, offers, review, rows = (captured[key] for key in
                                             ('configuration', 'parts', 'offers', 'review', 'rows'))
        binding = dict(configuration_id=bound['configuration_id'], revision=bound['revision'],
                       basis=review['basis'])
        # This detached public envelope is derived from current permission;
        # neither original config, private review nor resolver DTO is mutated.
        public_review = dict(review, customer_publishable=permission['allowed'])
        details = dict(binding, offer_id=bound['offer_id'], description=config['content'],
                       parts=_public_parts(parts, rows))
        terms = dict(binding, values=customer_conditions(config, parts, offers))
        projected = project_configuration(config, parts, public_review, publication=permission,
                                          details=details, terms=terms)
        _snapshot(conn, transaction)
        if projected['status'] != 200:
            return _deny()
        projected['data']['product_code'] = product_code
        # Component proofs in PublicationSources do not establish a PC photo.
        projected['data']['photo'] = {'state': 'unresolved', 'url': None}
        return projected
    except HTTPException as error:
        _snapshot(conn, transaction)
        if error.status_code in (404, 409):
            return _deny()
        raise
    except (KeyError, TypeError, ValueError):
        _snapshot(conn, transaction)
        return _deny()
