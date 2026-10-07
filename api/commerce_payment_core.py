"""Provider-independent plans for caller-owned durable payment operations.

No plan sends a payment, commits a ledger, authenticates a provider, reserves
stock, or guarantees concurrency. Adapters must verify provider evidence and
atomically apply CAS revisions, uniqueness and monetary/stock invariants.
Structured verification/commit receipts are supplied by trusted server adapters;
client booleans and callbacks are not receipts. Plans are never factual UI results.
"""
from copy import deepcopy

from . import commerce_contract as c

OPERATION_STATES = ('prepared', 'processing', 'unknown', 'confirmed', 'declined', 'expired')
_SPEC_FIELDS = ('operation_id', 'request_id', 'order_no', 'owner', 'kind', 'adapter_id',
                'provider', 'environment', 'merchant_id', 'provider_order_id', 'currency',
                'amount', 'order_total', 'approved_amount', 'refunded_amount', 'order_basis',
                'allocation_lines', 'reservation_expires_at', 'original_operation_id',
                'original_provider_ref', 'capabilities')
_EXPECTED_FIELDS = ('provider', 'environment', 'merchant_id', 'provider_order_id', 'currency', 'amount')
_EVIDENCE_FIELDS = ('provider', 'environment', 'merchant_id', 'provider_order_id', 'currency',
                    'amount', 'operation_id', 'status', 'provider_ref', 'original_provider_ref', 'observed_at')
_VERIFY_FIELDS = ('contract', 'adapter_id', 'verification_id', 'operation_id', 'request_basis',
                  'evidence_basis', 'source')
_CAS_REQUIREMENTS = ('operation_revision_cas', 'order_lock', 'active_operation_unique',
                     'payment_operation_unique', 'amount_cap_recheck', 'stock_effect_unique', 'atomic_commit')


def _spec(value):
    c.object_fields(value, _SPEC_FIELDS)
    result = deepcopy(value)
    for key in ('operation_id', 'request_id'):
        result[key] = c.uuid_text(value[key])
    result['owner'] = c.owner_identity(value['owner'])
    c.enum(value['kind'], ('approve', 'cancel'))
    for key in ('order_no', 'adapter_id', 'provider', 'merchant_id', 'provider_order_id'):
        c.text(value[key])
    c.enum(value['environment'], ('test', 'live'))
    c.enum(value['currency'], ('KRW',))
    for key in ('amount', 'order_total', 'approved_amount', 'refunded_amount', 'reservation_expires_at'):
        c.integer(value[key])
    c.basis_text(value['order_basis'])
    result['capabilities'] = c.capabilities(value['capabilities'])
    if value['refunded_amount'] > value['approved_amount'] or value['approved_amount'] > value['order_total']:
        c.fail('invalid_payment_balance')
    if type(value['allocation_lines']) is not list or not value['allocation_lines']:
        c.fail('allocation_lines_required')
    seen = set()
    for line in value['allocation_lines']:
        c.object_fields(line, ('line_id', 'product_code', 'qty'))
        c.text(line['line_id'])
        c.integer(line['product_code'], 1)
        c.integer(line['qty'], 1, c.MAX_QUANTITY)
        if line['line_id'] in seen:
            c.fail('duplicate_line')
        seen.add(line['line_id'])
    if value['kind'] == 'approve':
        if not result['capabilities']['approve']:
            c.fail('approval_unavailable')
        if (value['amount'] != value['order_total'] or value['approved_amount'] != 0
                or value['original_operation_id'] is not None or value['original_provider_ref'] is not None):
            c.fail('approval_amount_mismatch')
    else:
        if not result['capabilities']['cancel']:
            c.fail('cancel_unavailable')
        result['original_operation_id'] = c.uuid_text(value['original_operation_id'])
        if result['original_operation_id'] == result['operation_id']:
            c.fail('original_operation_mismatch')
        c.text(value['original_provider_ref'])
        remaining = value['approved_amount'] - value['refunded_amount']
        if not 0 < value['amount'] <= remaining:
            c.fail('cancel_amount_exceeded')
        if value['amount'] != remaining and not result['capabilities']['partial_cancel']:
            c.fail('partial_cancel_unavailable')
    if (value['kind'] == 'approve' and result['owner']['kind'] == 'guest'
            and not result['capabilities']['guest_checkout']):
        c.fail('guest_checkout_unavailable')
    return result


def _operation(value):
    c.object_fields(value, ('commerce_version', 'spec', 'request_basis', 'state', 'revision',
                            'prepared_at', 'lease_expires_at', 'prepared_commit', 'final_commit', 'provider_result'))
    if value['commerce_version'] != c.VERSION:
        c.fail('contract_mismatch')
    spec = _spec(value['spec'])
    if c.fingerprint(spec) != c.basis_text(value['request_basis']):
        c.fail('operation_basis_mismatch')
    c.enum(value['state'], OPERATION_STATES)
    c.integer(value['revision'], 1)
    c.integer(value['prepared_at'])
    if value['lease_expires_at'] is not None:
        c.integer(value['lease_expires_at'])
    if value['prepared_commit'] is not None:
        _prepared_receipt(value, value['prepared_commit'])
    if value['state'] in ('processing', 'unknown', 'confirmed', 'declined') and value['prepared_commit'] is None:
        c.fail('prepared_commit_required')
    if value['state'] in ('confirmed', 'declined'):
        _terminal_commit(value)
    return deepcopy(value)


def _terminal_commit(operation):
    receipt, evidence, spec = operation['final_commit'], operation['provider_result'], operation['spec']
    if receipt is None:
        c.fail('final_commit_required')
    c.object_fields(receipt, ('commerce_version', 'operation_id', 'request_basis', 'plan_basis',
                             'commit_id', 'payment_id', 'effect_keys'))
    c.object_fields(evidence, _EVIDENCE_FIELDS)
    if (receipt['commerce_version'] != c.VERSION or c.uuid_text(receipt['operation_id']) != spec['operation_id']
            or c.basis_text(receipt['request_basis']) != operation['request_basis']
            or c.uuid_text(evidence['operation_id']) != spec['operation_id']):
        c.fail('final_commit_mismatch')
    c.basis_text(receipt['plan_basis'])
    c.text(receipt['commit_id'])
    if (type(receipt['effect_keys']) is not list
            or any(type(k) is not str or not k for k in receipt['effect_keys'])
            or len(set(receipt['effect_keys'])) != len(receipt['effect_keys'])):
        c.fail('final_effects_mismatch')
    for key in _EXPECTED_FIELDS:
        if key == 'amount':
            c.integer(evidence[key])
        if evidence[key] != spec[key]:
            c.fail('provider_identity_mismatch')
    if evidence['original_provider_ref'] != spec['original_provider_ref']:
        c.fail('provider_original_mismatch')
    if c.integer(evidence['observed_at']) < operation['prepared_at']:
        c.fail('provider_time_mismatch')
    status = ('approved' if spec['kind'] == 'approve' else 'cancelled') if operation['state'] == 'confirmed' else 'declined'
    if evidence['status'] != status:
        c.fail('terminal_result_conflict')
    if operation['state'] == 'confirmed':
        c.text(evidence['provider_ref'])
        c.integer(receipt['payment_id'], 1)
        if spec['operation_id'] + ':payment' not in receipt['effect_keys']:
            c.fail('final_effects_mismatch')
    elif receipt['payment_id'] is not None:
        c.fail('final_payment_mismatch')


def _prepared_receipt(operation, receipt):
    c.object_fields(receipt, ('commerce_version', 'operation_id', 'request_basis', 'prepared_revision', 'commit_id'))
    if (receipt['commerce_version'] != c.VERSION
            or c.uuid_text(receipt['operation_id']) != operation['spec']['operation_id']
            or c.basis_text(receipt['request_basis']) != operation['request_basis']
            or c.integer(receipt['prepared_revision'], 1) != 1):
        c.fail('prepared_commit_mismatch')
    c.text(receipt['commit_id'])


def prepare_operation(spec, *, now, active=None):
    spec = _spec(spec)
    c.integer(now)
    basis = c.fingerprint(spec)
    if active is not None:
        active = _operation(active)
        previous = active['spec']
        c.require_owner(previous['owner'], spec['owner'])
        if previous['order_no'] != spec['order_no'] or previous['kind'] != spec['kind']:
            c.fail('operation_scope_mismatch')
        if previous['request_id'] == spec['request_id']:
            if active['request_basis'] != basis:
                c.fail('request_conflict')
            return {'action': 'replay', 'operation': active}
        if active['state'] not in ('declined', 'expired'):
            c.fail('active_operation_conflict')
    if spec['kind'] == 'approve' and now >= spec['reservation_expires_at']:
        c.fail('reservation_expired')
    operation = dict(commerce_version=c.VERSION, spec=spec, request_basis=basis,
                     state='prepared', revision=1, prepared_at=now, lease_expires_at=None,
                     prepared_commit=None, final_commit=None, provider_result=None)
    return {'action': 'prepare', 'operation': operation, 'requires': list(_CAS_REQUIREMENTS)}


def attach_prepared_commit(operation, receipt):
    operation = _operation(operation)
    _prepared_receipt(operation, receipt)
    if operation['prepared_commit'] is not None:
        if operation['prepared_commit'] != receipt:
            c.fail('prepared_commit_conflict')
        return operation
    if operation['state'] != 'prepared':
        c.fail('invalid_transition')
    operation['prepared_commit'] = deepcopy(receipt)
    return operation


def _plan(operation, action, *, next_operation=None, effects=()):
    plan = dict(commerce_version=c.VERSION, action=action,
                operation_id=operation['spec']['operation_id'], request_basis=operation['request_basis'],
                expected_revision=operation['revision'], next_operation=deepcopy(next_operation or operation),
                effects=deepcopy(list(effects)), requires=list(_CAS_REQUIREMENTS))
    plan['plan_basis'] = c.fingerprint(plan)
    return plan


def plan_dispatch(operation, *, now, lease_expires_at):
    operation = _operation(operation)
    c.integer(now)
    c.integer(lease_expires_at)
    if operation['state'] in ('processing', 'unknown'):
        return _plan(operation, 'query_required')
    if operation['state'] in ('confirmed', 'declined', 'expired'):
        return _plan(operation, 'read_result')
    if operation['prepared_commit'] is None:
        c.fail('prepared_commit_required')
    if now < operation['prepared_at'] or lease_expires_at <= now:
        c.fail('invalid_time')
    if operation['spec']['kind'] == 'approve' and now >= operation['spec']['reservation_expires_at']:
        c.fail('reservation_expired')
    changed = deepcopy(operation)
    changed.update(state='processing', revision=operation['revision'] + 1, lease_expires_at=lease_expires_at)
    # The adapter MUST commit this CAS change before sending the external
    # request, not merely call this function or attach a boolean durable flag.
    plan = _plan(operation, 'dispatch_after_commit', next_operation=changed)
    plan['external_identity'] = dict(operation_id=operation['spec']['operation_id'],
                                    idempotency_key=operation['spec']['operation_id'],
                                    **{k: operation['spec'][k] for k in _EXPECTED_FIELDS})
    plan['requires_commit_before_external'] = True
    plan['plan_basis'] = c.fingerprint({k: v for k, v in plan.items() if k != 'plan_basis'})
    return plan


def plan_unresolved(operation, *, reason, now):
    operation = _operation(operation)
    c.integer(now)
    c.enum(reason, ('transport_lost', 'process_lost', 'provider_pending', 'provider_not_found'))
    if operation['state'] in ('confirmed', 'declined', 'expired'):
        return _plan(operation, 'read_result')
    if operation['state'] not in ('processing', 'unknown'):
        c.fail('invalid_transition')
    changed = deepcopy(operation)
    if operation['state'] != 'unknown':
        changed.update(state='unknown', revision=operation['revision'] + 1)
    return _plan(operation, 'query_required', next_operation=changed)


def validate_provider_evidence(operation, evidence, verification, *, now):
    """Compare independently supplied server-verifier attestation and result.

    Verification of transport/authentication/signatures is exclusively the
    selected adapter's responsibility. This function cannot prove it happened.
    Attestation includes the complete evidence digest and operation identity;
    verified=True or browser callback status alone is deliberately insufficient.
    """
    operation = _operation(operation)
    c.object_fields(evidence, _EVIDENCE_FIELDS)
    c.object_fields(verification, _VERIFY_FIELDS)
    spec = operation['spec']
    if (verification['contract'] != 'commerce_provider_verification_v1'
            or verification['adapter_id'] != spec['adapter_id']
            or c.uuid_text(verification['operation_id']) != spec['operation_id']
            or c.basis_text(verification['request_basis']) != operation['request_basis']
            or c.basis_text(verification['evidence_basis']) != c.fingerprint(evidence)):
        c.fail('provider_verification_mismatch')
    c.text(verification['verification_id'])
    allowed = ('server_approval', 'server_query') if spec['kind'] == 'approve' else ('server_cancel', 'server_query')
    c.enum(verification['source'], allowed)
    if c.uuid_text(evidence['operation_id']) != spec['operation_id']:
        c.fail('provider_operation_mismatch')
    for field in _EXPECTED_FIELDS:
        if field == 'amount':
            c.integer(evidence[field])
        else:
            c.text(evidence[field])
        if evidence[field] != spec[field]:
            c.fail('provider_identity_mismatch')
    if evidence['original_provider_ref'] != spec['original_provider_ref']:
        c.fail('provider_original_mismatch')
    status = c.enum(evidence['status'], ('approved', 'cancelled', 'declined', 'pending', 'not_found'))
    if (spec['kind'] == 'approve' and status == 'cancelled') or (spec['kind'] == 'cancel' and status == 'approved'):
        c.fail('provider_status_mismatch')
    if status in ('approved', 'cancelled'):
        c.text(evidence['provider_ref'])
    elif evidence['provider_ref'] is not None:
        c.text(evidence['provider_ref'])
    if not operation['prepared_at'] <= c.integer(evidence['observed_at']) <= c.integer(now):
        c.fail('provider_time_mismatch')
    return deepcopy(evidence)


def plan_provider_result(operation, evidence, verification, *, now, allocation_state):
    operation = _operation(operation)
    c.enum(allocation_state, c.ALLOCATION_STATES)
    evidence = validate_provider_evidence(operation, evidence, verification, now=now)
    if operation['state'] in ('confirmed', 'declined'):
        previous = operation['provider_result']
        if type(previous) is not dict or any(previous[k] != evidence[k] for k in _EVIDENCE_FIELDS if k != 'observed_at'):
            c.fail('terminal_result_conflict')
        return _plan(operation, 'read_result')
    if operation['state'] not in ('processing', 'unknown'):
        c.fail('invalid_transition')
    if evidence['status'] in ('pending', 'not_found'):
        return plan_unresolved(operation, reason='provider_' + evidence['status'], now=now)
    spec, effects = operation['spec'], []
    successful = evidence['status'] in ('approved', 'cancelled')
    proposed = deepcopy(operation)
    proposed.update(state='confirmed' if successful else 'declined',
                    revision=operation['revision'] + 1, provider_result=evidence)
    operation_id = spec['operation_id']
    target_allocation = allocation_state
    if successful:
        effects.append(dict(kind='payment_approval' if spec['kind'] == 'approve' else 'payment_cancel',
                            dedup_key=operation_id + ':payment', amount=spec['amount'] if spec['kind'] == 'approve' else -spec['amount']))
        if spec['kind'] == 'approve':
            if allocation_state not in ('held', 'protected', 'blocked', 'released'):
                c.fail('allocation_state_conflict')
            if allocation_state in ('held', 'protected'):
                target_allocation = 'allocated'
                for line in spec['allocation_lines']:
                    effects.append(dict(kind='allocate', dedup_key=operation_id + ':allocate:' + line['line_id'],
                                        line_id=line['line_id'], product_code=line['product_code'], qty_delta=-line['qty']))
            else:
                # Money success is preserved; fulfillment needs reconciliation.
                target_allocation = 'blocked'
    elif spec['kind'] == 'approve' and allocation_state in ('held', 'protected', 'blocked'):
        # A stopped product can block allocation while our real reservation is
        # still protected. Authoritative decline releases only our claim; it
        # neither restores sold stock nor touches another order's reservation.
        target_allocation = 'released'
        effects.append(dict(kind='release_reservation', dedup_key=operation_id + ':release'))
    # Cancel never implies returned goods or automatic stock restoration.
    plan = _plan(operation, 'finalize_after_commit', next_operation=proposed, effects=effects)
    plan['verification'] = deepcopy(verification)
    plan['input_allocation_state'] = allocation_state
    plan['proposed_states'] = dict(payment_state='confirmed' if spec['kind'] == 'cancel' or successful else 'declined',
                                   allocation_state=target_allocation,
                                   refund_state=('refunded' if spec['refunded_amount'] + spec['amount'] == spec['approved_amount'] else 'partial')
                                   if spec['kind'] == 'cancel' and successful else 'unchanged',
                                   checkout_state='paid' if successful and spec['kind'] == 'approve' else 'unchanged')
    plan['plan_basis'] = c.fingerprint({k: v for k, v in plan.items() if k != 'plan_basis'})
    return plan


def apply_finalization_receipt(operation, plan, receipt):
    """Reflect a caller-verified atomic commit, not perform or prove that commit."""
    operation = _operation(operation)
    c.object_fields(receipt, ('commerce_version', 'operation_id', 'request_basis', 'plan_basis',
                             'commit_id', 'payment_id', 'effect_keys'))
    if (type(plan) is not dict or plan.get('action') != 'finalize_after_commit'
            or c.fingerprint({k: v for k, v in plan.items() if k != 'plan_basis'}) != plan.get('plan_basis')):
        c.fail('invalid_finalization_plan')
    if (receipt['commerce_version'] != c.VERSION or c.uuid_text(receipt['operation_id']) != operation['spec']['operation_id']
            or c.basis_text(receipt['request_basis']) != operation['request_basis']
            or receipt['plan_basis'] != plan['plan_basis'] or plan['operation_id'] != operation['spec']['operation_id']
            or plan['request_basis'] != operation['request_basis']):
        c.fail('final_commit_mismatch')
    c.text(receipt['commit_id'])
    keys = [e['dedup_key'] for e in plan['effects']]
    if type(receipt['effect_keys']) is not list or receipt['effect_keys'] != keys:
        c.fail('final_effects_mismatch')
    has_payment = any(e['kind'] in ('payment_approval', 'payment_cancel') for e in plan['effects'])
    if has_payment:
        c.integer(receipt['payment_id'], 1)
    elif receipt['payment_id'] is not None:
        c.fail('final_payment_mismatch')
    if operation['state'] in ('confirmed', 'declined'):
        if operation['final_commit'] != receipt:
            c.fail('final_commit_conflict')
        return operation
    # A self-consistent hash is not authority: reconstruct semantic effects
    # from the checked evidence and reject altered quantities/status/effects.
    if type(plan.get('next_operation')) is not dict:
        c.fail('invalid_finalization_plan')
    evidence = plan['next_operation'].get('provider_result')
    if type(evidence) is not dict:
        c.fail('invalid_finalization_plan')
    rebuilt = plan_provider_result(operation, evidence, plan.get('verification'),
                                   now=evidence.get('observed_at'),
                                   allocation_state=plan.get('input_allocation_state'))
    if rebuilt != plan:
        c.fail('finalization_plan_mismatch')
    if plan['expected_revision'] != operation['revision']:
        c.fail('operation_revision_conflict')
    proposed = deepcopy(plan['next_operation'])
    if proposed['spec'] != operation['spec'] or proposed['revision'] != operation['revision'] + 1:
        c.fail('operation_revision_conflict')
    proposed['final_commit'] = deepcopy(receipt)
    return _operation(proposed)


def plan_expiry(*, order_no, checkout_state, allocation_state, expires_at, now, active=None):
    c.text(order_no)
    c.enum(checkout_state, c.CHECKOUT_STATES)
    c.enum(allocation_state, c.ALLOCATION_STATES)
    c.integer(expires_at)
    c.integer(now)
    operation = _operation(active) if active is not None else None
    if operation is not None and operation['spec']['order_no'] != order_no:
        c.fail('operation_scope_mismatch')
    if checkout_state in ('processing', 'unknown') or (operation is not None and operation['state'] in ('processing', 'unknown')):
        return dict(action='query_required', effects=[], reservation_action='protect')
    if (checkout_state != 'draft' or now < expires_at
            or allocation_state not in ('held', 'protected')
            or (operation is not None and operation['state'] == 'confirmed')):
        return dict(action='none', effects=[], reservation_action='unchanged')
    result = dict(action='expire_draft_after_commit', reservation_action='release',
                  effects=[dict(kind='release_reservation', dedup_key=order_no + ':draft-expiry')],
                  requires=['order_revision_cas', 'no_dispatched_approval', 'atomic_commit'])
    if operation is not None and operation['state'] == 'prepared':
        changed = deepcopy(operation)
        changed.update(state='expired', revision=operation['revision'] + 1)
        result.update(expected_operation_revision=operation['revision'], next_operation=changed)
    return result
