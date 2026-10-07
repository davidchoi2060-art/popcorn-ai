"""Support-only caller connection adapter; no engine/commit/retry/savepoint.

The caller rolls back its ENTIRE transaction on exceptions. Successful writes
are pending until a fresh transaction reads and validates the immutable event.
"""
from copy import deepcopy
from functools import wraps
import hashlib
import json
from uuid import uuid4

from sqlalchemy import text

from . import commerce_contract as c
from . import commerce_owner as owner
from . import commerce_support_core as s

OPERATION_NAMESPACE = 1398100048  # ASCII SUPP; not POPC, POPR or hashtext(UUID),2.
CASE_COLUMNS = ('case_id,order_id,owner_scope,origin,state,admin_revision,public_revision,'
                'created_at,updated_at,public_updated_at,write_txid')
EVENT_COLUMNS = ('event_id,operation_id,case_id,order_id,owner_scope,actor,action,visible,'
                 'body,reply_event_id,request,request_hash,result,result_hash,admin_revision,'
                 'public_revision,recorded_at,write_txid,commit_id')


def _sql(conn, tag, statement, **params):
    return conn.execute(text('/*commerce_support:' + tag + '*/ ' + statement), params)


def _transaction(conn):
    if (not conn.in_transaction() or conn.in_nested_transaction()
            or conn.get_execution_options().get('isolation_level') == 'AUTOCOMMIT'):
        s.fail(503, 'support_caller_transaction_required')


def _txid(conn):
    return s.integer(_sql(conn, 'txid', 'SELECT txid_current()').scalar_one(), 1)


def _atomic(function):
    @wraps(function)
    def run(conn, *args, **kwargs):
        _transaction(conn)
        try:
            txid = _txid(conn)
            if txid != _txid(conn):
                s.fail(503, 'support_transaction_changed')
            result = function(conn, *args, **kwargs)
            if txid != _txid(conn):
                s.fail(503, 'support_transaction_changed')
            return result
        except Exception as error:
            try:
                _sql(conn, 'abort', 'SELECT 1/0 AS support_transaction_abort')
            except Exception:
                pass
            if isinstance(error, (s.SupportError, owner.OwnerError)):
                raise
            s.fail(503, 'support_store_unavailable')
    return run


def _json(value):
    c.fingerprint(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _grant(authorize, *, no, action, now, audience):
    if not callable(authorize):
        s.fail(403, 'support_authorization_required')
    grant = authorize(order_no=no, action=action, now=now)
    if (type(grant) is not dict or grant.get('allowed') is not True
            or grant.get('audience') != audience or grant.get('order_no') != no
            or type(grant.get('checked_at')) is not int or grant['checked_at'] != now
            or grant.get('permission') != 'commerce.support.' + action):
        s.fail(403, 'support_authorization_required')
    if audience == 'admin':
        if grant.get('source') != 'api.auth.current_operator':
            s.fail(403, 'support_authorization_required')
        principal = s.principal(grant.get('principal'), write=action != 'read')
        author = dict(kind='operator', operator_id=principal['operator_id'])
    elif audience == 'customer':
        context = grant.get('context')
        if (grant.get('source') != 'commerce_owner.lookup_context'
                or type(context) is not owner.OwnerContext or context.expires_at <= now):
            s.fail(401, 'owner_context_lost')
        identity = c.owner_identity(context.owner_identity)
        if identity['kind'] != 'guest':
            s.fail(401, 'verified_member_adapter_unready')
        if c.fingerprint(identity) != context.owner_scope:
            s.fail(503, 'support_owner_unavailable')
        s.uuid(context.context_id)
        author = dict(kind='customer', user_id=identity['user_id'], owner_scope=context.owner_scope)
    else:
        s.fail(403, 'support_authorization_required')
    return grant, s.actor(author)


def _again(authorize, grant, *, no, action, now, audience):
    current, author = _grant(authorize, no=no, action=action, now=now, audience=audience)
    if ({k: v for k, v in current.items() if k != 'permission'}
            != {k: v for k, v in grant.items() if k != 'permission'}):
        s.fail(403, 'support_authorization_changed')
    return author


def _scope(conn, no, grant, *, lock=False):
    # Ownership filter precedes any support body or operation lookup.
    params = dict(no=no)
    predicate = ''
    if grant['audience'] == 'customer':
        context = grant['context']
        predicate = (' AND d.context_id=CAST(:context AS uuid) AND d.owner_scope=:scope'
                     ' AND d.owner_identity=CAST(:identity AS jsonb)')
        params.update(context=context.context_id, scope=context.owner_scope,
                      identity=_json(context.owner_identity))
    row = _sql(conn, 'scope_lock' if lock else 'scope', '''SELECT o.order_no,d.order_id,
        d.context_id,d.owner_scope,d.owner_identity,d.write_txid AS order_write_txid
        FROM orders o JOIN commerce_order_details d USING(order_id)
        WHERE o.order_no=:no''' + predicate + (' FOR UPDATE OF d,o' if lock else ''),
               **params).mappings().first()
    if row is None:
        s.fail(404, 'order_not_found')
    row = dict(row)
    try:
        s.integer(row['order_id'], 1)
        if row['order_no'] != no or c.fingerprint(c.owner_identity(row['owner_identity'])) != row['owner_scope']:
            raise ValueError()
        s.uuid(str(row['context_id']))
        _committed(conn, row['order_write_txid'])
        if grant['audience'] == 'customer':
            ctx = grant['context']
            if (str(row['context_id']) != ctx.context_id or row['owner_scope'] != ctx.owner_scope
                    or row['owner_identity'] != ctx.owner_identity):
                s.fail(404, 'order_not_found')
    except s.SupportError as error:
        if error.status == 404:
            raise
        s.fail(503, 'support_order_unavailable')
    except (ValueError, KeyError, TypeError):
        s.fail(503, 'support_order_unavailable')
    return row


def _committed(conn, *write_txids):
    current = _txid(conn)
    for value in write_txids:
        if s.integer(value, 1) == current:
            s.fail(503, 'support_record_unconfirmed')


def _case_record(raw, scope):
    try:
        record = dict(raw)
        for key in ('case_id',):
            record[key] = s.uuid(str(record[key]))
        if (record['order_id'] != scope['order_id'] or record['owner_scope'] != scope['owner_scope']
                or record['origin'] not in ('customer', 'external_record')
                or record['state'] not in ('open', 'closed')):
            raise ValueError()
        s.integer(record['order_id'], 1)
        s.integer(record['admin_revision'], 1)
        s.integer(record['created_at']); s.integer(record['updated_at']); s.integer(record['write_txid'], 1)
        if record['updated_at'] < record['created_at']:
            raise ValueError()
        if record['origin'] == 'customer':
            if not 1 <= s.integer(record['public_revision'], 1) <= record['admin_revision']:
                raise ValueError()
            if not record['created_at'] <= s.integer(record['public_updated_at']) <= record['updated_at']:
                raise ValueError()
        elif record['public_revision'] is not None or record['public_updated_at'] is not None:
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError):
        s.fail(503, 'support_record_unavailable')


def _case(conn, scope, case_id, audience, *, lock=False):
    row = _sql(conn, 'case_lock' if lock else 'case', 'SELECT ' + CASE_COLUMNS +
               ' FROM commerce_support_cases WHERE order_id=:oid AND case_id=CAST(:case AS uuid)' +
               (" AND origin='customer'" if audience == 'customer' else '') +
               (' FOR UPDATE' if lock else ''), oid=scope['order_id'], case=case_id).mappings().first()
    if row is None:
        s.fail(404, 'support_case_not_found')
    return _case_record(row, scope)


def _event_record(raw, scope):
    try:
        record = dict(raw)
        for key in ('event_id', 'operation_id', 'case_id', 'commit_id'):
            record[key] = s.uuid(str(record[key]))
        if record['reply_event_id'] is not None:
            record['reply_event_id'] = s.uuid(str(record['reply_event_id']))
        s.integer(record['order_id'], 1); s.integer(record['write_txid'], 1)
        s.integer(record['admin_revision'], 1); s.integer(record['recorded_at'])
        if record['public_revision'] is not None:
            s.integer(record['public_revision'], 1)
        if (record['order_id'] != scope['order_id'] or record['owner_scope'] != scope['owner_scope']
                or type(record['visible']) is not bool or s.body_text(record['body']) != record['body']):
            raise ValueError()
        author = s.actor(record['actor'])
        audience = 'customer' if author['kind'] == 'customer' else 'admin'
        request = record['request']
        s.fields(request, ('version', 'order_id', 'order_no', 'owner_scope', 'actor', 'command'))
        cmd = s.command(request['command'], audience)
        expected = s.identity(cmd, order_id=scope['order_id'], no=scope['order_no'],
                              owner_scope=scope['owner_scope'], author=author)
        if (request != expected or record['request_hash'] != c.fingerprint(expected)
                or cmd['operation_id'] != record['operation_id'] or cmd['action'] != record['action']
                or (cmd['case_id'] is not None and cmd['case_id'] != record['case_id'])
                or (author['kind'] == 'customer' and author['owner_scope'] != scope['owner_scope'])
                or (record['action'] in s.PRIVATE_ACTIONS and record['visible'])
                or (author['kind'] == 'customer' and not record['visible'])
                or (record['visible'] and record['public_revision'] is None)
                or record['reply_event_id'] != cmd.get('reply_event_id')
                or (record['action'] != 'publish_customer_reply' and record['body'] != cmd['body'])):
            raise ValueError()
        result = record['result']
        s.fields(result, ('case_id', 'origin', 'state', 'revision', 'recorded_at', 'updated_at',
                          'event_id', 'action', 'event_body', 'visible', 'delivery'))
        if (result['case_id'] != record['case_id'] or result['event_id'] != record['event_id']
                or result['action'] != record['action'] or result['event_body'] != record['body']
                or result['visible'] is not record['visible'] or result['delivery'] != 'not_attempted'
                or result['origin'] not in ('customer', 'external_record')
                or result['state'] not in ('open', 'closed')
                or (record['visible'] and result['origin'] != 'customer')
                or result['revision'] != (record['public_revision'] if audience == 'customer' else record['admin_revision'])
                or result['updated_at'] != record['recorded_at']
                or record['result_hash'] != c.fingerprint(result)):
            raise ValueError()
        s.integer(result['revision'], 1); s.integer(result['recorded_at']); s.integer(result['updated_at'])
        if result['recorded_at'] > result['updated_at']:
            raise ValueError()
        if record['admin_revision'] != cmd['expected_revision'] + 1 and audience == 'admin':
            raise ValueError()
        if record['public_revision'] != cmd['expected_revision'] + 1 and audience == 'customer':
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError, c.CommerceError):
        s.fail(503, 'support_record_unavailable')


def _operation(conn, operation_id):
    return _sql(conn, 'operation', 'SELECT ' + EVENT_COLUMNS +
                ' FROM commerce_support_events WHERE operation_id=CAST(:op AS uuid)',
                op=operation_id).mappings().first()


def _case_proof(conn, case, scope, audience):
    # Customer proof uses ONLY the last public event, even after private notes.
    column = 'public_revision' if audience == 'customer' else 'admin_revision'
    row = _sql(conn, 'case_proof', 'SELECT ' + EVENT_COLUMNS +
        ' FROM commerce_support_events WHERE order_id=:oid AND case_id=CAST(:case AS uuid)'
        ' AND ' + column + '=:revision' + (' AND visible=true' if audience == 'customer' else ''),
        oid=scope['order_id'], case=case['case_id'], revision=case[column]).mappings().first()
    if row is None:
        s.fail(503, 'support_record_unavailable')
    event = _event_record(row, scope)
    timestamp = case['public_updated_at'] if audience == 'customer' else case['updated_at']
    if (event['case_id'] != case['case_id'] or event['result']['origin'] != case['origin']
            or event['result']['state'] != case['state'] or event['recorded_at'] != timestamp):
        s.fail(503, 'support_record_unavailable')
    _committed(conn, case['write_txid'], event['write_txid'])


def _receipt(record):
    # Exact immutable outcome. The caller separately reads current_case.
    return dict(operation_id=record['operation_id'], request_hash=record['request_hash'],
                commit_id=record['commit_id'], result=deepcopy(record['result']))


@_atomic
def apply(conn, no, command, *, audience, now, authorize):
    no, now = s.order_no(no), s.integer(now)
    cmd = s.command(command, audience)
    grant, author = _grant(authorize, no=no, action=cmd['action'], now=now, audience=audience)
    # Order scope before lock/UUID lookup; no products/payment/stock scope.
    scope = _scope(conn, no, grant)
    lock_key = int.from_bytes(hashlib.sha256(cmd['operation_id'].encode('ascii')).digest()[:4], 'big', signed=True)
    _sql(conn, 'operation_lock', 'SELECT pg_catalog.pg_advisory_xact_lock(:namespace,:key)',
         namespace=OPERATION_NAMESPACE, key=lock_key)
    scope = _scope(conn, no, grant, lock=True)
    request = s.identity(cmd, order_id=scope['order_id'], no=no, owner_scope=scope['owner_scope'], author=author)
    raw = _operation(conn, cmd['operation_id'])
    if raw is not None:
        # Different order/actor => value-free conflict, never expose that receipt.
        if (raw['order_id'] != scope['order_id'] or raw['actor'] != author
                or raw['request_hash'] != c.fingerprint(request)):
            s.fail(409, 'support_operation_conflict')
        record = _event_record(raw, scope)
        if record['request'] != request:
            s.fail(409, 'support_operation_conflict')
        _committed(conn, record['write_txid'])
        _again(authorize, grant, no=no, action=cmd['action'], now=now, audience=audience)
        return dict(state='pending_commit', replay=True, operation_id=cmd['operation_id'],
                    request_hash=record['request_hash'])
    old = None if cmd['case_id'] is None else _case(conn, scope, cmd['case_id'], audience, lock=True)
    case, visible = s.transition(old, cmd, audience, now=now)
    case_id = str(uuid4()) if old is None else old['case_id']
    case.pop('write_txid', None)
    case.update(case_id=case_id, order_id=scope['order_id'], owner_scope=scope['owner_scope'])
    body = cmd.get('body')
    if cmd['action'] == 'publish_customer_reply':
        draft = _sql(conn, 'draft', 'SELECT ' + EVENT_COLUMNS +
            ' FROM commerce_support_events WHERE order_id=:oid AND case_id=CAST(:case AS uuid)'
            ' AND event_id=CAST(:event AS uuid)', oid=scope['order_id'], case=case_id,
            event=cmd['reply_event_id']).mappings().first()
        if draft is None:
            s.fail(404, 'support_reply_not_found')
        draft = _event_record(draft, scope)
        if draft['action'] != 'record_reply' or draft['visible'] or draft['actor']['kind'] != 'operator':
            s.fail(409, 'support_publication_forbidden')
        _committed(conn, draft['write_txid'])
        body = draft['body']
    _again(authorize, grant, no=no, action=cmd['action'], now=now, audience=audience)
    txid = _txid(conn)
    if old is None:
        _sql(conn, 'insert_case', '''INSERT INTO commerce_support_cases
          (case_id,order_id,owner_scope,origin,state,admin_revision,public_revision,
           created_at,updated_at,public_updated_at,write_txid)
          VALUES(CAST(:case_id AS uuid),:order_id,:owner_scope,:origin,:state,:admin_revision,
                 :public_revision,:created_at,:updated_at,:public_updated_at,:write_txid)''',
             **case, write_txid=txid)
    else:
        changed = _sql(conn, 'update_case', '''UPDATE commerce_support_cases SET state=:state,
          admin_revision=:admin_revision,public_revision=:public_revision,updated_at=:updated_at,
          public_updated_at=:public_updated_at,write_txid=:write_txid
          WHERE order_id=:order_id AND case_id=CAST(:case_id AS uuid) AND admin_revision=:old_revision''',
                       **case, write_txid=txid, old_revision=old['admin_revision'])
        if changed.rowcount != 1:
            s.fail(409, 'support_revision_conflict')
    event_id = str(uuid4())
    result = s.case_view(case, audience)
    result.update(event_id=event_id, action=cmd['action'], event_body=body,
                  visible=visible, delivery='not_attempted')
    _sql(conn, 'insert_event', '''INSERT INTO commerce_support_events
      (event_id,operation_id,case_id,order_id,owner_scope,actor,action,visible,body,
       reply_event_id,request,request_hash,result,result_hash,admin_revision,public_revision,
       recorded_at,write_txid,commit_id,customer_user_id,operator_id)
      VALUES(CAST(:event AS uuid),CAST(:op AS uuid),CAST(:case AS uuid),:oid,:scope,
       CAST(:actor AS jsonb),:action,:visible,:body,CAST(:reply AS uuid),CAST(:request AS jsonb),
       :request_hash,CAST(:result AS jsonb),:result_hash,:admin_revision,:public_revision,
       :now,:txid,CAST(:commit AS uuid),:customer_user_id,:operator_id)''',
         event=event_id, op=cmd['operation_id'], case=case_id, oid=scope['order_id'], scope=scope['owner_scope'],
         actor=_json(author), action=cmd['action'], visible=visible, body=body,
         reply=cmd.get('reply_event_id'), request=_json(request), request_hash=c.fingerprint(request),
         result=_json(result), result_hash=c.fingerprint(result), admin_revision=case['admin_revision'],
         public_revision=case['public_revision'], now=now, txid=txid, commit=str(uuid4()),
         customer_user_id=author.get('user_id'), operator_id=author.get('operator_id'))
    _again(authorize, grant, no=no, action=cmd['action'], now=now, audience=audience)
    return dict(state='pending_commit', replay=False, operation_id=cmd['operation_id'],
                request_hash=c.fingerprint(request))


def read(conn, no, *, audience, now, authorize, case_id=None, operation_id=None,
         request_hash=None, limit=20, cursor=None, expected_command=None):
    _transaction(conn)
    no, now = s.order_no(no), s.integer(now)
    if case_id is not None and operation_id is not None:
        s.fail(422, 'invalid_support_mode')
    limit = s.integer(limit, 1)
    if limit > 50:
        s.fail(422, 'invalid_support_limit')
    grant, author = _grant(authorize, no=no, action='read', now=now, audience=audience)
    scope = _scope(conn, no, grant)
    if operation_id is not None:
        if cursor is not None or request_hash is None:
            s.fail(422, 'invalid_support_mode')
        op = s.uuid(operation_id)
        c.basis_text(request_hash)
        raw = _operation(conn, op)
        if raw is None or raw['order_id'] != scope['order_id'] or raw['actor'] != author:
            s.fail(404, 'support_operation_not_found')
        record = _event_record(raw, scope)
        if record['request_hash'] != request_hash:
            s.fail(409, 'support_operation_conflict')
        if expected_command is not None:
            cmd = s.command(expected_command, audience)
            expected = s.identity(cmd, order_id=scope['order_id'], no=no,
                                  owner_scope=scope['owner_scope'], author=author)
            if record['request'] != expected:
                s.fail(409, 'support_operation_conflict')
            _again(authorize, grant, no=no, action=cmd['action'], now=now, audience=audience)
        else:
            _again(authorize, grant, no=no, action=record['action'], now=now, audience=audience)
        _committed(conn, record['write_txid'])
        case = _case(conn, scope, record['case_id'], audience)
        _case_proof(conn, case, scope, audience)
        payload = dict(operation_result=_receipt(record), current_case=s.case_view(case, audience))
    else:
        if request_hash is not None or expected_command is not None:
            s.fail(422, 'invalid_support_mode')
        mode = 'cases' if case_id is None else 'events'
        target = None if case_id is None else s.uuid(case_id)
        cursor_scope = s.cursor_scope(no, audience, mode, target)
        upper, after = s.decode_cursor(cursor, cursor_scope) if cursor is not None else (None, None)
        customer = audience == 'customer'
        if mode == 'cases':
            # One bounded statement; anchor and page use the same statement snapshot.
            rows = _sql(conn, 'case_page', '''WITH visible_cases AS (
              SELECT * FROM commerce_support_cases WHERE order_id=:oid''' +
              (" AND origin='customer'" if customer else '') + '''), anchor AS (
              SELECT COALESCE(CAST(:upper AS uuid),max(case_id::text)::uuid) AS upper_id FROM visible_cases)
              SELECT ''' + ','.join('v.' + x for x in CASE_COLUMNS.split(',')) + ''',a.upper_id
              FROM visible_cases v CROSS JOIN anchor a WHERE v.case_id<=a.upper_id
              AND (CAST(:after AS uuid) IS NULL OR v.case_id>CAST(:after AS uuid))
              ORDER BY v.case_id LIMIT :bound''', oid=scope['order_id'], upper=upper, after=after,
                        bound=limit + 1).mappings().all()
            records = [_case_record(row, scope) for row in rows]
            ids = [case['case_id'] for case in records]
            anchors = [s.uuid(str(row['upper_id'])) for row in rows]
            if (len(records) > limit + 1 or ids != sorted(set(ids))
                    or (anchors and (len(set(anchors)) != 1
                        or (upper is not None and anchors[0] != upper)
                        or any(case_id > anchors[0] or (after is not None and case_id <= after) for case_id in ids)))
                    or (customer and any(case['origin'] != 'customer' for case in records))):
                s.fail(503, 'support_record_unavailable')
            for case in records:
                _case_proof(conn, case, scope, audience)
            page = [s.case_view(case, audience) for case in records[:limit]]
            next_cursor = (s.encode_cursor(cursor_scope, str(rows[0]['upper_id']), records[limit-1]['case_id'])
                           if len(records) > limit else None)
            payload = dict(cases=page, next_cursor=next_cursor)
        else:
            case = _case(conn, scope, target, audience)
            _case_proof(conn, case, scope, audience)
            revision_column = 'public_revision' if customer else 'admin_revision'
            upper = case[revision_column] if upper is None else upper
            rows = _sql(conn, 'event_page', 'SELECT ' + EVENT_COLUMNS +
                ' FROM commerce_support_events WHERE order_id=:oid AND case_id=CAST(:case AS uuid)' +
                (' AND visible=true' if customer else '') +
                ' AND ' + revision_column + '<=:upper AND (CAST(:after AS bigint) IS NULL OR ' + revision_column + '>CAST(:after AS bigint))'
                ' ORDER BY ' + revision_column + ' LIMIT :bound', oid=scope['order_id'], case=target,
                upper=upper, after=after, bound=limit + 1).mappings().all()
            records = [_event_record(row, scope) for row in rows]
            if len(records) > limit + 1 or any(event['case_id'] != target for event in records):
                s.fail(503, 'support_record_unavailable')
            for event in records:
                _committed(conn, event['write_txid'])
            revisions = [event[revision_column] for event in records]
            if (revisions != sorted(set(revisions)) or any(rev > upper or (after is not None and rev <= after) for rev in revisions)
                    or (customer and any(not event['visible'] for event in records))):
                s.fail(503, 'support_record_unavailable')
            page = [s.event_view(event, audience) for event in records[:limit]]
            next_cursor = (s.encode_cursor(cursor_scope, upper, records[limit-1][revision_column])
                           if len(records) > limit else None)
            payload = dict(current_case=s.case_view(case, audience), events=page, next_cursor=next_cursor)
    _again(authorize, grant, no=no, action='read', now=now, audience=audience)
    return dict(version=s.VERSION, state='confirmed', order_no=no, checked_at=now, **payload)
