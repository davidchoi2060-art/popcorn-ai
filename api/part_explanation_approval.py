"""Internal explanation approval history on the authenticated caller's TX.

No router, engine, implicit transaction, commit, rollback or seed actor. The
caller supplies one consistent snapshot and rolls back its ENTIRE transaction
on any exception, including SQL/UUID conflicts or failures after a pending
metadata update. Return values do not prove a caller COMMIT succeeded.

CAUTION before activation: the legacy part public GET consumes native approved
metadata and returns image URLs. This source/MOCK implementation is NOT PC,
individual product, or photo publication permission; those consumers/photo
gates and the authenticated caller need separate acceptance before wiring.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from .timeutil import iso

VERSION = 'part-explanation-approval-v1'
SCOPE = 'internal_part_description'
MAX_BIGINT = 2**63 - 1
EVENT_COLUMNS = ('source_product_code,event_seq,request_id,request_digest,action,'
                 'operator_id,recorded_at,note,approval_basis,snapshot,metadata_reset,write_txid')


def _fail(status, reason):
    raise HTTPException(status, reason)


def _integer(value, minimum=1, maximum=MAX_BIGINT):
    return type(value) is int and minimum <= value <= maximum


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _transaction(conn):
    if (conn.in_transaction() is not True or conn.in_nested_transaction()
            or conn.get_execution_options().get('isolation_level') == 'AUTOCOMMIT'):
        _fail(503, 'part_approval_caller_transaction_required')
    transaction = conn.get_transaction()
    if transaction is None:
        _fail(503, 'part_approval_caller_transaction_required')
    return transaction


def _sql(conn, tag, statement, **params):
    _transaction(conn)
    return conn.execute(text('/*part_approval:' + tag + '*/ ' + statement), params)


def _code(code):
    if not _integer(code):
        _fail(422, 'part_approval_code_invalid')


def _time(value):
    if type(value) is str:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            _fail(503, 'part_approval_time_invalid')
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _fail(503, 'part_approval_time_invalid')
    value = value.astimezone(timezone.utc)
    if value > datetime.now(timezone.utc):
        _fail(503, 'part_approval_time_invalid')
    return iso(value)


def _json(value):
    try:
        return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str,allow_nan=False)
    except (ValueError, TypeError):
        _fail(503, 'part_approval_source_invalid')


def _snapshot(row):
    result = dict(row)
    for key in ('approved_at','updated_at'):
        if result.get(key) is not None:
            result[key] = _time(result[key])
    return json.loads(_json(result))


def _digest(value):
    from .pc_configuration_copy import digest
    return digest(value)


def basis(row):
    """Exact source+native metadata binding; use the original digest algorithm."""
    return _digest(dict(version=VERSION, scope=SCOPE, row=_snapshot(row)))


def _read(conn, code, lock=False):
    from .part_explanations import SELECT
    if lock:
        _sql(conn,'catalog_lock',"SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))")
    row = _sql(conn,'row',SELECT+' WHERE e.source_product_code=:code'+(' FOR UPDATE OF e' if lock else ''),code=code).mappings().first()
    if not row:
        _fail(404, 'part_approval_explanation_missing')
    row = dict(row)
    if not _integer(row.get('source_product_code')) or row['source_product_code'] != code:
        _fail(503, 'part_approval_source_binding_invalid')
    linked = row.get('product_code')
    if lock and linked is not None:
        if not _integer(linked):
            _fail(503, 'part_approval_link_invalid')
        _sql(conn,'product_lock', 'SELECT product_code FROM products WHERE product_code=:code FOR SHARE',code=linked).all()
        # Keep the original e lock and re-read the joined current product AFTER locking.
        refreshed = _sql(conn,'row',SELECT+' WHERE e.source_product_code=:code',code=code).mappings().first()
        if not refreshed or refreshed['source_product_code'] != code or refreshed['product_code'] != linked:
            _fail(503, 'part_approval_source_binding_invalid')
        row = dict(refreshed)
    return row


def _actor(conn, actor):
    # A trusted caller authenticates this context; it MUST NOT come from a body.
    if (type(actor) is not dict or not _integer(actor.get('operator_id'))
            or actor.get('role') not in ('owner','operator') or actor.get('status') != '활성'):
        _fail(403, 'part_approval_actor_required')
    current = _sql(conn,'actor','''SELECT operator_id,role,status FROM admin_operators
        WHERE operator_id=:operator_id FOR SHARE''',operator_id=actor['operator_id']).mappings().first()
    if (not current or not _integer(current['operator_id']) or current['operator_id'] != actor['operator_id']
            or current['role'] != actor['role'] or current['status'] != '활성'):
        _fail(403, 'part_approval_actor_required')
    return actor['operator_id']


def _assembly_only(row):
    """BOM-only part with no retail product row. Spec facts may be unknown; that
    never blocks approval (unknown values are shown as unknown)."""
    content = row.get('content')
    return (row.get('product_code') is None and type(content) is dict
            and content.get('availability_scope') == 'assembly_only')


def _source_reason(row):
    from .part_explanations import is_current, fingerprint
    if row.get('status') == 'retired':
        return 'part_approval_retired'
    if row.get('status') not in ('draft','approved') or type(row.get('content')) is not dict:
        return 'part_approval_source_invalid'
    assembly = _assembly_only(row)
    if not assembly and not _integer(row.get('product_code')):
        return 'part_approval_unlinked'
    issues = row['content'].get('review_issues', [])
    if type(issues) is not list or issues:
        return 'part_approval_review_issues'
    source = row.get('source_snapshot')
    if (type(source) is not dict or not source or not _hash(row.get('source_fingerprint'))
            or row['source_fingerprint'] != fingerprint(source.get('name'),source.get('spec'))
            or (not assembly and (type(row.get('product_name')) is not str or not row['product_name'].strip()
                                  or type(row.get('spec_source_text')) is not str or not row['spec_source_text'].strip()
                                  or row.get('sale_status') != '판매중'))
            or not is_current(row)):
        return 'part_approval_source_stale'
    return None


def _event(row):
    if row is None:
        return None
    event = dict(row)
    try:
        event['request_id'] = str(UUID(str(event['request_id'])))
    except (KeyError, ValueError, TypeError):
        _fail(503, 'part_approval_event_invalid')
    snapshot = event.get('snapshot')
    if (not _integer(event.get('source_product_code')) or not _integer(event.get('event_seq'))
            or not _integer(event.get('operator_id')) or not _integer(event.get('write_txid'))
            or event.get('action') not in ('approve','revoke') or type(event.get('metadata_reset')) is not bool
            or (event['action']=='approve' and event['metadata_reset'])
            or type(event.get('note')) is not str or not event['note'].strip() or len(event['note'])>3000
            or not _hash(event.get('request_digest')) or not _hash(event.get('approval_basis'))
            or type(snapshot) is not dict or snapshot.get('source_product_code') != event['source_product_code']
            or not _integer(snapshot.get('source_product_code'))
            or not (_integer(snapshot.get('product_code')) or _assembly_only(snapshot))
            or snapshot.get('status') != 'approved' or not _integer(snapshot.get('approved_by'))
            or not _hash(snapshot.get('source_fingerprint')) or basis(snapshot) != event['approval_basis']):
        _fail(503, 'part_approval_event_invalid')
    event['recorded_at'] = _time(event.get('recorded_at'))
    approved_at = _time(snapshot.get('approved_at'))
    if event['action']=='approve' and (snapshot['approved_by'] != event['operator_id'] or approved_at != event['recorded_at']):
        _fail(503, 'part_approval_event_invalid')
    return deepcopy(event)


def _latest(conn, code):
    event = _event(_sql(conn,'latest','SELECT '+EVENT_COLUMNS+''' FROM part_explanation_approval_events
        WHERE source_product_code=:code ORDER BY event_seq DESC LIMIT 1''',code=code).mappings().first())
    if event and event['source_product_code'] != code:
        _fail(503, 'part_approval_event_binding_invalid')
    return event


def _current(row, latest):
    reason = _source_reason(row)
    state = 'unapproved'
    if latest:
        if latest['action']=='revoke':
            state = 'revoked'
        elif row.get('status')=='draft':
            state, reason = 'draft', 'part_approval_metadata_changed'
        elif reason:
            state = 'stale'
        elif row.get('status')!='approved' or basis(row) != latest['approval_basis']:
            state, reason = 'stale', 'part_approval_metadata_or_source_changed'
        else:
            state = 'approved'
    from .pc_configuration_copy import explanation_digest
    return dict(source_product_code=row['source_product_code'],scope=SCOPE,
        event_seq=latest['event_seq'] if latest else 0,state=state,allowed=state=='approved',
        basis=basis(row), approval_basis=latest['approval_basis'] if latest else None,
        explanation_hash=explanation_digest(row),reason=reason)


def read_current(conn, code):
    """Latest-only internal authority in the caller's consistent snapshot."""
    _transaction(conn)
    _code(code)
    row = _read(conn,code)
    return _current(row,_latest(conn,code))


def _request(code, action, expected_seq, request_id, note, operator_id, **binding):
    if (not _integer(expected_seq,0,MAX_BIGINT-1) or type(note) is not str
            or not note.strip() or len(note)>3000):
        _fail(422, 'part_approval_request_invalid')
    try:
        if type(request_id) is UUID:
            uid = str(request_id)
        elif type(request_id) is str and str(UUID(request_id)) == request_id:
            uid = request_id
        else:
            raise ValueError()
    except ValueError:
        _fail(422, 'part_approval_request_id_invalid')
    return uid,_digest(dict(version=VERSION,source_product_code=code,action=action,
                            expected_seq=expected_seq,request_id=uid,note=note,operator_id=operator_id,**binding))


def _replay(conn, code, action, operator_id, uid, digest):
    event = _event(_sql(conn,'request','SELECT '+EVENT_COLUMNS+
        ' FROM part_explanation_approval_events WHERE request_id=:uid',uid=uid).mappings().first())
    if event and (event['source_product_code'] != code or event['action'] != action
                  or event['operator_id'] != operator_id or event['request_digest'] != digest):
        _fail(409, 'part_approval_request_conflict')
    return event


def _approve_metadata(conn, code, operator_id, before):
    updated = _sql(conn,'approve_metadata', '''UPDATE product_explanations SET status='approved',
        approved_by=:operator_id,approved_at=now(),updated_at=now() WHERE source_product_code=:code
        RETURNING source_product_code''',code=code,operator_id=operator_id).mappings().one()
    if updated['source_product_code'] != code:
        _fail(503, 'part_approval_metadata_write_mismatch')
    after = _read(conn,code)
    protected = {k:v for k,v in before.items() if k not in ('status','approved_by','approved_at','updated_at')}
    if (any(_json(after.get(k)) != _json(v) for k,v in protected.items())
            or after.get('status') != 'approved' or type(after.get('approved_by')) is not int
            or after['approved_by'] != operator_id or _time(after.get('approved_at')) != _time(after.get('updated_at'))
            or _source_reason(after)):
        _fail(503, 'part_approval_metadata_write_mismatch')
    return after


def _owned_metadata(row, event):
    snapshot = event['snapshot']
    return (row.get('status')=='approved' and type(row.get('approved_by')) is int
            and row['approved_by']==snapshot['approved_by'] and row.get('approved_at') is not None
            and _time(row['approved_at'])==_time(snapshot['approved_at']))


def _reset_metadata(conn, code, before):
    updated = _sql(conn,'revoke_metadata', '''UPDATE product_explanations SET status='draft',
        approved_by=NULL,approved_at=NULL,updated_at=now() WHERE source_product_code=:code
        AND status='approved' AND approved_by=:old_actor AND approved_at=:old_at
        RETURNING source_product_code''',code=code,old_actor=before['approved_by'],old_at=before['approved_at']).mappings().one()
    if updated['source_product_code'] != code:
        _fail(503, 'part_approval_metadata_write_mismatch')
    after = _read(conn,code)
    protected = {k:v for k,v in before.items() if k not in ('status','approved_by','approved_at','updated_at')}
    if (any(_json(after.get(k)) != _json(v) for k,v in protected.items())
            or after.get('status') != 'draft' or after.get('approved_by') is not None or after.get('approved_at') is not None):
        _fail(503, 'part_approval_metadata_write_mismatch')
    return after


def _append(conn, code, seq, uid, digest, action, operator_id, note, snapshot, metadata_reset):
    row = _sql(conn,'append', '''INSERT INTO part_explanation_approval_events
        (source_product_code,event_seq,request_id,request_digest,action,operator_id,note,
         approval_basis,snapshot,metadata_reset)
        VALUES(:code,:seq,:uid,:request_digest,:action,:operator_id,:note,:basis,CAST(:snapshot AS jsonb),:reset)
        RETURNING '''+EVENT_COLUMNS,code=code,seq=seq,uid=uid,request_digest=digest,action=action,
        operator_id=operator_id,note=note.strip(),basis=basis(snapshot),snapshot=_json(snapshot),reset=metadata_reset).mappings().one()
    event = _event(row)
    if (event['source_product_code'] != code or event['event_seq'] != seq or event['request_id'] != uid
            or event['request_digest'] != digest or event['action'] != action or event['operator_id'] != operator_id
            or event['snapshot'] != snapshot or event['metadata_reset'] is not metadata_reset):
        _fail(503, 'part_approval_append_mismatch')
    return event


def _result(conn, code, event, replayed, transaction):
    current = read_current(conn,code)
    if _transaction(conn) is not transaction:
        _fail(503, 'part_approval_transaction_changed')
    return dict(event=event,replayed=replayed,current=current,committed=False)


def approve(conn, code, *, expected_seq, expected_basis, request_id, note, actor):
    transaction = _transaction(conn)
    _code(code)
    row = _read(conn,code,lock=True)
    operator_id = _actor(conn,actor)
    if not _hash(expected_basis):
        _fail(422, 'part_approval_basis_invalid')
    uid,digest = _request(code,'approve',expected_seq,request_id,note,operator_id,expected_basis=expected_basis)
    event = _replay(conn,code,'approve',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _latest(conn,code)
        if (latest['event_seq'] if latest else 0) != expected_seq:
            _fail(409, 'part_approval_sequence_changed')
        if basis(row) != expected_basis:
            _fail(409, 'part_approval_basis_changed')
        reason = _source_reason(row)
        if reason:
            _fail(422,reason)
        after = _approve_metadata(conn,code,operator_id,row)
        event = _append(conn,code,expected_seq+1,uid,digest,'approve',operator_id,note,_snapshot(after),False)
    return _result(conn,code,event,replayed,transaction)


def revoke(conn, code, *, expected_seq, request_id, note, actor):
    transaction = _transaction(conn)
    _code(code)
    row = _read(conn,code,lock=True)
    operator_id = _actor(conn,actor)
    uid,digest = _request(code,'revoke',expected_seq,request_id,note,operator_id)
    event = _replay(conn,code,'revoke',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _latest(conn,code)
        if not latest or latest['event_seq'] != expected_seq:
            _fail(409, 'part_approval_sequence_changed')
        if latest['action'] != 'approve':
            _fail(409, 'part_approval_already_revoked')
        reset = _owned_metadata(row,latest)
        if reset:
            _reset_metadata(conn,code,row)
        # No old content/source/product/status snapshot is restored. If metadata
        # belongs to an edit/other approval/retirement, leave EVERY native field alone.
        event = _append(conn,code,expected_seq+1,uid,digest,'revoke',operator_id,note,latest['snapshot'],reset)
    return _result(conn,code,event,replayed,transaction)
