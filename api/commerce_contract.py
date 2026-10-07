"""Pure commerce DTO checks and projections; no authentication or I/O.

Owners, sale basis, policy and persisted rows must come from trusted server
adapters. Matching supplied dictionaries does not prove their authenticity,
current stock, a committed transaction, or a real payment. No router is exposed.
Limits below are PostgreSQL integer representation limits, not sales policy.
"""
from copy import deepcopy
import hashlib
import json
import re

VERSION = 'commerce_v1'
MAX_INTEGER = 2**63 - 1
MAX_QUANTITY = 2**31 - 1
CHECKOUT_STATES = ('draft', 'processing', 'unknown', 'paid', 'expired', 'cancelled')
PAYMENT_STATES = ('unpaid', 'prepared', 'processing', 'unknown', 'confirmed', 'declined')
ALLOCATION_STATES = ('unreserved', 'held', 'protected', 'allocated', 'blocked', 'released')
REFUND_STATES = ('none', 'requested', 'processing', 'unknown', 'partial', 'refunded')
ORDER_STATES = ('접수', '결제완료', '조립중', '출고', '배송중', '완료', '취소')
CAPABILITY_KEYS = ('approve', 'cancel', 'partial_cancel', 'guest_checkout')
_UUID = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


class CommerceError(ValueError):
    """Stable, value-free diagnostic; never reflect PII or provider secrets."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code):
    raise CommerceError(code)


def object_fields(value, required, optional=()):
    if (type(value) is not dict or any(type(k) is not str for k in value)
            or not set(required).issubset(value)
            or not set(value).issubset(set(required) | set(optional))):
        fail('invalid_fields')
    return value


def text(value):
    if type(value) is not str or not value.strip():
        fail('invalid_text')
    return value


def integer(value, minimum=0, maximum=MAX_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        fail('invalid_integer')
    return value


def uuid_text(value):
    if type(value) is not str or _UUID.fullmatch(value) is None:
        fail('invalid_uuid')
    return value.lower()


def basis_text(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        fail('invalid_basis')
    return value


def enum(value, choices):
    if type(value) is not str or value not in choices:
        fail('invalid_state')
    return value


def _json(value):
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        if not -MAX_INTEGER - 1 <= value <= MAX_INTEGER:
            fail('invalid_integer')
        return value
    if type(value) is list:
        return [_json(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _json(v) for k, v in value.items()}
    fail('invalid_json')


def fingerprint(payload):
    """Equality evidence only; a hash is not authorization or a signature."""
    try:
        raw = json.dumps(_json(payload), sort_keys=True, ensure_ascii=False,
                         separators=(',', ':')).encode('utf-8')
    except (UnicodeError, RecursionError):
        fail('invalid_json')
    return hashlib.sha256(raw).hexdigest()


def owner_identity(owner):
    if type(owner) is not dict:
        fail('owner_required')
    kind = enum(owner.get('kind'), ('guest', 'member'))
    if kind == 'guest':
        object_fields(owner, ('kind', 'user_id', 'owner_hash'))
        return dict(kind=kind, user_id=integer(owner['user_id'], 1),
                    owner_hash=basis_text(owner['owner_hash']))
    # auth_subject is supplied by a verified authentication adapter. Email,
    # provider label, and a client "verified": true do not meet this shape.
    object_fields(owner, ('kind', 'member_id', 'auth_subject'))
    return dict(kind=kind, member_id=integer(owner['member_id'], 1),
                auth_subject=text(owner['auth_subject']))


def require_owner(expected, supplied):
    if owner_identity(expected) != owner_identity(supplied):
        fail('owner_mismatch')
    return owner_identity(expected)


def request_identity(request_id, payload, owner):
    return dict(commerce_version=VERSION, request_id=uuid_text(request_id),
                request_basis=fingerprint(payload), owner=owner_identity(owner))


def replay_request(identity, existing):
    """existing is a trusted stored result; serialization/uniqueness is external."""
    object_fields(identity, ('commerce_version', 'request_id', 'request_basis', 'owner'))
    if identity['commerce_version'] != VERSION:
        fail('contract_mismatch')
    uuid_text(identity['request_id'])
    basis_text(identity['request_basis'])
    owner_identity(identity['owner'])
    if existing is None:
        return {'state': 'new'}
    object_fields(existing, ('identity', 'result'))
    previous = existing['identity']
    object_fields(previous, ('commerce_version', 'request_id', 'request_basis', 'owner'))
    require_owner(previous['owner'], identity['owner'])
    if (previous['commerce_version'] != VERSION
            or uuid_text(previous['request_id']) != uuid_text(identity['request_id'])):
        fail('request_scope_mismatch')
    if basis_text(previous['request_basis']) != identity['request_basis']:
        fail('request_conflict')
    return {'state': 'replay', 'result': deepcopy(existing['result'])}


def capabilities(value):
    object_fields(value, CAPABILITY_KEYS)
    if any(type(value[k]) is not bool for k in CAPABILITY_KEYS):
        fail('invalid_capabilities')
    return dict(value)


def confirmed_policy(policy):
    object_fields(policy, ('policy_id', 'policy_basis', 'state', 'currency', 'capabilities'),
                  ('max_quantity',))
    if policy['state'] != 'confirmed':
        fail('policy_unconfirmed')
    if policy['currency'] != 'KRW':
        fail('currency_mismatch')
    result = dict(policy_id=text(policy['policy_id']), policy_basis=basis_text(policy['policy_basis']),
                  state='confirmed', currency='KRW', capabilities=capabilities(policy['capabilities']))
    # Optional, explicitly supplied business limit. No default commercial cap.
    if 'max_quantity' in policy:
        result['max_quantity'] = integer(policy['max_quantity'], 1, MAX_QUANTITY)
    return result


def source_reference(source):
    object_fields(source, ('kind', 'id', 'version'))
    # An opaque server source kind preserves future SKU/BOM scope. It does not
    # allow a client to select or invent an adapter/source interpretation.
    return {k: text(source[k]) for k in ('kind', 'id', 'version')}


def validate_sale_basis(basis, *, expected_basis, policy, now):
    """Return a detached immutable-intent snapshot, never a sales approval."""
    object_fields(basis, ('basis_id', 'source', 'state', 'currency', 'lines', 'charges',
                         'total', 'expires_at', 'price_basis', 'stock_basis', 'terms_basis',
                         'policy_id', 'policy_basis'))
    policy = confirmed_policy(policy)
    if basis['state'] != 'confirmed':
        fail('sale_unconfirmed')
    if basis_text(basis['basis_id']) != basis_text(expected_basis):
        fail('sale_basis_changed')
    if basis['currency'] != 'KRW':
        fail('currency_mismatch')
    if (basis['policy_id'] != policy['policy_id']
            or basis['policy_basis'] != policy['policy_basis']):
        fail('policy_basis_changed')
    if integer(basis['expires_at']) <= integer(now):
        fail('sale_basis_expired')
    for field in ('price_basis', 'stock_basis', 'terms_basis'):
        basis_text(basis[field])
    if type(basis['lines']) is not list or not basis['lines']:
        fail('lines_required')
    lines, line_ids, stock, need, total = [], set(), {}, {}, 0
    for line in basis['lines']:
        object_fields(line, ('line_id', 'product_code', 'name', 'qty', 'unit_amount', 'stock_available'))
        line_id = text(line['line_id'])
        if line_id in line_ids:
            fail('duplicate_line')
        line_ids.add(line_id)
        code = integer(line['product_code'], 1)
        qty = integer(line['qty'], 1, MAX_QUANTITY)
        if 'max_quantity' in policy and qty > policy['max_quantity']:
            fail('quantity_policy_exceeded')
        available = integer(line['stock_available'])
        if code in stock and stock[code] != available:
            fail('stock_basis_inconsistent')
        stock[code] = available
        need[code] = integer(need.get(code, 0) + qty, 1, MAX_QUANTITY)
        total = integer(total + integer(line['unit_amount']) * qty)
        lines.append(dict(line_id=line_id, product_code=code, name=text(line['name']),
                          qty=qty, unit_amount=line['unit_amount'], stock_available=available))
    if any(need[code] > stock[code] for code in need):
        fail('stock_insufficient')
    if type(basis['charges']) is not list:
        fail('invalid_charges')
    charges, charge_ids = [], set()
    for charge in basis['charges']:
        object_fields(charge, ('code', 'amount'))
        code = text(charge['code'])
        if code in charge_ids:
            fail('duplicate_charge')
        charge_ids.add(code)
        total = integer(total + integer(charge['amount']))
        charges.append(dict(code=code, amount=charge['amount']))
    if integer(basis['total']) != total:
        fail('total_mismatch')
    return dict(commerce_version=VERSION, basis_id=basis['basis_id'],
                source=source_reference(basis['source']), currency='KRW', lines=lines,
                charges=charges, total=total, expires_at=basis['expires_at'],
                price_basis=basis['price_basis'], stock_basis=basis['stock_basis'],
                terms_basis=basis['terms_basis'], policy_id=policy['policy_id'],
                policy_basis=policy['policy_basis'])


def draft_contract(body, *, owner, sale_basis, policy, now):
    object_fields(body, ('request_id', 'source', 'expected_basis', 'shipping'))
    object_fields(body['shipping'], ('name', 'phone', 'address'), ('contact_email',))
    shipping = {k: text(v) for k, v in body['shipping'].items()}
    snapshot = validate_sale_basis(sale_basis, expected_basis=body['expected_basis'],
                                   policy=policy, now=now)
    if source_reference(body['source']) != snapshot['source']:
        fail('source_mismatch')
    principal = owner_identity(owner)
    if principal['kind'] == 'guest' and not confirmed_policy(policy)['capabilities']['guest_checkout']:
        fail('guest_checkout_unavailable')
    payload = dict(source=snapshot['source'], expected_basis=snapshot['basis_id'], shipping=shipping)
    identity = request_identity(body['request_id'], payload, principal)
    # Internal DTO contains PII for the existing shipping_snap writer. It must
    # not be returned as a public order projection or journal diagnostic.
    return dict(identity=identity, snapshot=snapshot, shipping=shipping,
                checkout_state='draft', payment_state='unpaid', allocation_state='held', refund_state='none')


def order_detail(row):
    """Allowlisted DTO from a trusted stored row, not from checkout browser data.

    The caller must authorize access before loading it. Confirmed/paid states
    require a structured persisted result reference, never verified=True.
    This projection does not resolve or authenticate that persisted reference.
    """
    required = ('order_no', 'order_state', 'checkout_state', 'payment_state', 'allocation_state',
                'refund_state', 'total', 'currency', 'expires_at', 'lines', 'reason_codes', 'capabilities')
    # Extra server fields are deliberately not exposed (owner, PII, PG tokens,
    # merchant/environment, administrative receipts from other workflows).
    if type(row) is not dict or not set(required).issubset(row):
        fail('invalid_order_detail')
    result = dict(commerce_version=VERSION, order_no=text(row['order_no']),
                  order_state=enum(row['order_state'], ORDER_STATES),
                  checkout_state=enum(row['checkout_state'], CHECKOUT_STATES),
                  payment_state=enum(row['payment_state'], PAYMENT_STATES),
                  allocation_state=enum(row['allocation_state'], ALLOCATION_STATES),
                  refund_state=enum(row['refund_state'], REFUND_STATES), total=integer(row['total']),
                  currency=enum(row['currency'], ('KRW',)), expires_at=integer(row['expires_at']))
    if result['checkout_state'] == 'paid' and result['payment_state'] != 'confirmed':
        fail('state_inconsistent')
    if result['allocation_state'] == 'allocated' and result['payment_state'] != 'confirmed':
        fail('state_inconsistent')
    if result['order_state'] in ('결제완료', '조립중', '출고', '배송중', '완료') and result['payment_state'] != 'confirmed':
        fail('state_inconsistent')
    if result['order_state'] in ('결제완료', '조립중', '출고', '배송중') and result['allocation_state'] != 'allocated':
        fail('state_inconsistent')
    if result['payment_state'] == 'confirmed':
        proof = row.get('committed_payment')
        object_fields(proof, ('operation_id', 'request_basis', 'commit_id', 'payment_id',
                             'order_no', 'amount', 'currency', 'status'))
        uuid_text(proof['operation_id'])
        basis_text(proof['request_basis'])
        text(proof['commit_id'])
        integer(proof['payment_id'], 1)
        if (proof['order_no'] != result['order_no'] or integer(proof['amount']) != result['total']
                or proof['currency'] != 'KRW' or proof['status'] != 'approved'):
            fail('committed_payment_mismatch')
    if type(row['lines']) is not list or not row['lines']:
        fail('lines_required')
    result['lines'] = []
    for line in row['lines']:
        if type(line) is not dict or not {'line_id', 'name', 'qty', 'unit_amount'}.issubset(line):
            fail('invalid_line')
        result['lines'].append(dict(line_id=text(line['line_id']), name=text(line['name']),
                                   qty=integer(line['qty'], 1, MAX_QUANTITY), unit_amount=integer(line['unit_amount'])))
    if (type(row['reason_codes']) is not list or any(type(v) is not str or not v for v in row['reason_codes'])
            or len(set(row['reason_codes'])) != len(row['reason_codes'])):
        fail('invalid_reasons')
    result['reason_codes'] = list(row['reason_codes'])
    available = capabilities(row['capabilities'])
    available['approve'] = (available['approve'] and result['checkout_state'] == 'draft'
                            and result['payment_state'] in ('unpaid', 'prepared')
                            and result['allocation_state'] == 'held')
    available['cancel'] = (available['cancel'] and result['payment_state'] == 'confirmed'
                           and result['refund_state'] not in ('processing', 'unknown', 'refunded'))
    available['partial_cancel'] = available['partial_cancel'] and available['cancel']
    result['capabilities'] = available
    # PostgreSQL BIGINT exceeds JavaScript's exact Number range. Public money
    # is always decimal text; internal comparisons/ledger plans remain integers.
    result['total'] = str(result['total'])
    for line in result['lines']:
        line['unit_amount'] = str(line['unit_amount'])
    return result


CUSTOMER_ACTIONS = ('confirm', 'cancel_draft', 'request_refund', 'reconcile')
ADMIN_ACTIONS = ('reconcile', 'cancel_payment', 'advance_fulfillment', 'return_stock')


def public_context(context):
    """Shape of caller-verified scope; public binding is never authentication."""
    object_fields(context, ('state', 'binding_id'))
    state = enum(context['state'], ('confirmed', 'unconfirmed'))
    binding = uuid_text(context['binding_id']) if state == 'confirmed' else None
    if state == 'unconfirmed' and context['binding_id'] is not None:
        fail('context_unconfirmed')
    return dict(state=state, binding_id=binding)


def _public_basis(basis):
    object_fields(basis, ('state', 'basis_id'))
    state = enum(basis['state'], ('confirmed', 'unconfirmed', 'stale'))
    identity = basis_text(basis['basis_id']) if basis['basis_id'] is not None else None
    if (state == 'confirmed' and identity is None) or (state == 'unconfirmed' and identity is not None):
        fail('basis_unconfirmed')
    return dict(state=state, basis_id=identity)


def _actions(keys, permissions, basis, eligible):
    """Permissions are complete server action decisions, not role/capability bools.

    The caller must include route support, source policy, CSRF, actor permission,
    and (for stock return) physical quantity evidence in that decision.
    """
    if permissions is not None:
        object_fields(permissions, keys)
    result = {}
    for key in keys:
        permission = permissions[key] if permissions is not None else dict(
            allowed=False, reason='permission_unconfirmed', expected_basis=None)
        object_fields(permission, ('allowed', 'reason', 'expected_basis'))
        if type(permission['allowed']) is not bool:
            fail('invalid_action_permission')
        expected = basis_text(permission['expected_basis']) if permission['expected_basis'] is not None else None
        reason = text(permission['reason']) if permission['reason'] is not None else None
        if permission['allowed'] and (reason is not None or expected is None):
            fail('invalid_action_permission')
        if not permission['allowed'] and reason is None:
            fail('invalid_action_permission')
        allowed = permission['allowed']
        if allowed and basis['state'] != 'confirmed':
            allowed, reason = False, 'basis_changed' if basis['state'] == 'stale' else 'basis_unconfirmed'
        elif allowed and expected != basis['basis_id']:
            allowed, reason = False, 'basis_changed'
        elif allowed and not eligible[key]:
            allowed, reason = False, 'state_blocked'
        result[key] = dict(allowed=allowed, reason=reason,
                           expected_basis=basis['basis_id'] if basis['state'] == 'confirmed' else None)
    return result


def _balances(value, item):
    object_fields(value, ('approved', 'refunded'))
    approved, refunded = integer(value['approved']), integer(value['refunded'])
    if refunded > approved or approved > int(item['total']):
        fail('invalid_payment_balance')
    if (item['payment_state'] == 'confirmed' and approved != int(item['total'])) or (
            item['payment_state'] != 'confirmed' and approved != 0):
        fail('committed_payment_mismatch')
    return dict(approved_amount=str(approved), refunded_amount=str(refunded), refundable_amount=str(approved-refunded))


def _recoverable(item):
    return (item['payment_state'] in ('processing', 'unknown') or
            item['refund_state'] in ('processing', 'unknown') or item['allocation_state'] == 'blocked')


def customer_order_detail(row, *, context, checked_at, basis, permissions, balances):
    context = public_context(context)
    if context['state'] != 'confirmed':
        fail('owner_unconfirmed')
    if uuid_text(row.get('owner_binding_id')) != context['binding_id']:
        fail('owner_binding_mismatch')
    item = order_detail(row)
    basis = _public_basis(basis)
    money = _balances(balances, item)
    eligible = dict(confirm=item['capabilities']['approve'],
      cancel_draft=item['checkout_state']=='draft' and item['payment_state'] in ('unpaid','prepared')
                   and item['allocation_state']=='held',
      request_refund=item['capabilities']['cancel'] and item['refund_state'] in ('none','partial')
                     and int(money['refundable_amount'])>0,
      reconcile=_recoverable(item))
    return dict(item, checked_at=integer(checked_at), basis_id=basis['basis_id'], basis_state=basis['state'],
                owner_binding_id=context['binding_id'], actions=_actions(CUSTOMER_ACTIONS, permissions, basis, eligible), **money)


def admin_order_detail(row, *, context, checked_at, basis, permissions, balances, provider):
    context = public_context(context)
    if context['state'] != 'confirmed':
        fail('permission_unconfirmed')
    item = order_detail(row)
    basis = _public_basis(basis)
    money = _balances(balances, item)
    object_fields(provider, ('provider_environment', 'verification_state', 'provider_checked_at'))
    environment = enum(provider['provider_environment'], ('test', 'live', 'unknown'))
    verification = enum(provider['verification_state'], ('unknown', 'pending', 'confirmed', 'failed'))
    observed = integer(provider['provider_checked_at']) if provider['provider_checked_at'] is not None else None
    if (verification == 'confirmed' and (environment == 'unknown' or observed is None)) or (
            observed is not None and observed > integer(checked_at)):
        fail('provider_unconfirmed')
    eligible = dict(reconcile=_recoverable(item) and environment!='unknown',
      cancel_payment=item['capabilities']['cancel'] and int(money['refundable_amount'])>0 and environment!='unknown',
      advance_fulfillment=item['payment_state']=='confirmed' and item['allocation_state']=='allocated'
        and item['refund_state'] not in ('processing','unknown','refunded'),
      # This exact phase has no physical return writer; keep this closed even
      # if a caller confuses cash permission with received/resellable goods.
      return_stock=False)
    return dict(item, checked_at=integer(checked_at), basis_id=basis['basis_id'], basis_state=basis['state'],
      actions=_actions(ADMIN_ACTIONS, permissions, basis, eligible), provider_environment=environment,
      verification_state=verification, provider_checked_at=observed, **money)


def order_envelope(records, *, audience, context, checked_at, next_cursor=None, detail=False):
    """records contain explicit internal row/basis/permission/balance inputs.

    Unconfirmed scope has no records. No keys, credentials, merchant identity,
    raw evidence or opaque workflow commit receipts pass through the envelope.
    """
    context = public_context(context)
    enum(audience, ('customer', 'admin'))
    integer(checked_at)
    if type(records) is not list or type(detail) is not bool:
        fail('invalid_envelope')
    if context['state'] != 'confirmed' and records:
        fail('context_unconfirmed')
    if next_cursor is not None:
        text(next_cursor)
    if detail and (len(records)>1 or next_cursor is not None):
        fail('invalid_envelope')
    items, seen = [], set()
    for record in records:
        keys = ('row','basis','permissions','balances') + (('provider',) if audience=='admin' else ())
        object_fields(record, keys)
        function = customer_order_detail if audience=='customer' else admin_order_detail
        item = function(**record, context=context, checked_at=checked_at)
        if item['order_no'] in seen:
            fail('duplicate_order')
        seen.add(item['order_no'])
        items.append(item)
    result = dict(commerce_version=VERSION, checked_at=checked_at, context=context)
    if detail:
        result['item'] = items[0] if items else None
    else:
        result.update(items=items, next_cursor=next_cursor)
    return result
