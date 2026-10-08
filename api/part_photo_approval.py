"""Internal immutable registered-photo evidence on the caller's transaction.

The trusted caller supplies authenticated actor, registered provenance and the
existing business photo-rights attestation reference. These are SERVER inputs,
never browser claims. image_reader(asset, code, 'detail') follows read_image's
contract; no credentials, storage client, route or connection is created here.
Every exception requires rollback of the ENTIRE caller transaction. Pending
events/current.allowed are not a COMMIT receipt or public/whole-PC permission.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import re
from uuid import UUID

from fastapi import HTTPException

from . import part_explanation_approval as original

VERSION = 'part-photo-approval-v1'
SCOPE = 'registered_product_photo'
EVENT_COLUMNS = ('source_product_code,event_seq,request_id,request_digest,action,operator_id,'
                 'recorded_at,note,source_basis,approval_basis,snapshot,write_txid')


@dataclass(frozen=True)
class PhotoProvenance:
    source_product_code: int
    product_code: int
    basis: str
    kind: str
    source_reference: str
    rights_reference: str


class _Unavailable(Exception):
    def __init__(self, reason, status=503):
        self.reason, self.status = reason, status


def _sql(conn, tag, statement, **params):
    original._transaction(conn)
    from sqlalchemy import text
    return conn.execute(text('/*part_photo:' + tag + '*/ ' + statement), params)


def _model(row):
    content = row.get('content') if type(row.get('content')) is dict else {}
    return dict(source_product_code=row.get('source_product_code'), product_code=row.get('product_code'),
                source_snapshot=deepcopy(row.get('source_snapshot')), source_fingerprint=row.get('source_fingerprint'),
                product_name=row.get('product_name'), spec_source_text=row.get('spec_source_text'),
                sale_status=row.get('sale_status'), image_url=content.get('image_url'),
                image_asset=deepcopy(content.get('image_asset')))


def basis(row):
    """Photo/model evidence, independent of editable description/native approval."""
    return original._digest(dict(version=VERSION, scope=SCOPE, model=_model(row)))


def _model_reason(row):
    from .part_explanations import fingerprint, is_current
    if row.get('status') not in ('draft', 'approved'):
        return 'photo_model_retired_or_invalid'
    source = row.get('source_snapshot')
    if (not original._integer(row.get('product_code')) or type(source) is not dict or not source
            or not original._hash(row.get('source_fingerprint'))
            or row['source_fingerprint'] != fingerprint(source.get('name'), source.get('spec'))
            or not isinstance(row.get('product_name'), str) or not row['product_name'].strip()
            or not isinstance(row.get('spec_source_text'), str) or not row['spec_source_text'].strip()
            or row.get('sale_status') != '판매중' or not is_current(row)):
        return 'photo_model_missing_or_stale'
    return None


def _asset_reason(asset, code):
    from .product_images import MEDIA_BUCKET
    if (type(asset) is not dict or asset.get('bucket') != MEDIA_BUCKET
            or not original._hash(asset.get('sha256')) or not original._hash(asset.get('detail_sha256'))):
        return 'photo_asset_missing_or_invalid'
    prefix = f'products/{code}/{asset["sha256"][:16]}/'
    if (asset.get('detail_key') != prefix + 'detail.png'
            or asset.get('thumbnail_key') != prefix + 'thumb.webp'
            or asset.get('original_key') not in tuple(prefix + 'original.' + ext for ext in ('jpg','png','webp','gif'))):
        return 'photo_asset_key_invalid'
    original_size, detail_size, box = (asset.get(k) for k in ('original_size','detail_size','crop_box'))
    if (type(original_size) is not list or len(original_size) != 2
            or type(detail_size) is not list or len(detail_size) != 2
            or type(box) is not list or len(box) != 4
            or any(not original._integer(v, maximum=2**31-1) for v in original_size + detail_size)
            or any(not original._integer(v, minimum=0, maximum=2**31-1) for v in box)
            or not 0 <= box[0] < box[2] <= original_size[0]
            or not 0 <= box[1] < box[3] <= original_size[1]
            or detail_size != [box[2]-box[0], box[3]-box[1]]
            or asset.get('crop_mode') not in ('uniform_margin','transparent_margin','no_outer_margin')):
        return 'photo_asset_processing_invalid'
    try:
        original._time(asset.get('prepared_at'))
    except HTTPException:
        return 'photo_asset_prepared_time_invalid'
    return None


def _reference(value, rights=False):
    if type(value) is not str or not 0 < len(value) <= 500 or any(c.isspace() for c in value):
        return False
    if rights:
        return re.fullmatch(r'workroom:.+@v[1-9][0-9]*:[a-f0-9]{64}', value) is not None
    return (re.fullmatch(r'[A-Za-z][A-Za-z0-9_.+-]*:.+', value) is not None
            and value.split(':',1)[0].lower() not in ('http','https','data','javascript'))


def _verify(conn, row, provenance_reader, image_reader, business_rights_reference):
    reason = _model_reason(row) or _asset_reason(_model(row)['image_asset'], row['source_product_code'])
    if reason:
        raise _Unavailable(reason, 422)
    if (not callable(provenance_reader) or not callable(image_reader)
            or not _reference(business_rights_reference, rights=True)):
        raise _Unavailable('photo_server_evidence_unconnected')
    transaction = original._transaction(conn)
    try:
        proof = provenance_reader(conn, row=deepcopy(row), expected_basis=basis(row))
    except Exception:
        if original._transaction(conn) is not transaction:
            original._fail(503, 'photo_transaction_changed')
        raise _Unavailable('photo_provenance_unavailable') from None
    if original._transaction(conn) is not transaction:
        original._fail(503, 'photo_transaction_changed')
    if (type(proof) is not PhotoProvenance or not original._integer(proof.source_product_code)
            or not original._integer(proof.product_code) or proof.source_product_code != row['source_product_code']
            or proof.product_code != row['product_code'] or proof.basis != basis(row)
            or proof.kind != SCOPE or not _reference(proof.source_reference)
            or proof.rights_reference != business_rights_reference):
        raise _Unavailable('photo_provenance_binding_invalid', 422)
    asset = deepcopy(row['content']['image_asset'])
    try:
        data = image_reader(deepcopy(asset), row['source_product_code'], 'detail')
    except Exception:
        if original._transaction(conn) is not transaction:
            original._fail(503, 'photo_transaction_changed')
        raise _Unavailable('photo_current_bytes_unavailable') from None
    if original._transaction(conn) is not transaction:
        original._fail(503, 'photo_transaction_changed')
    if (type(data) is not bytes or not 8 < len(data) <= 10*1024*1024
            or not data.startswith(b'\x89PNG\r\n\x1a\n')
            or hashlib.sha256(data).hexdigest() != asset['detail_sha256']):
        raise _Unavailable('photo_current_bytes_invalid', 422)
    # A callback must not replace the current model/asset even within this TX.
    refreshed = original._read(conn, row['source_product_code'])
    if _model_reason(refreshed) or basis(refreshed) != basis(row):
        raise _Unavailable('photo_source_changed', 409)
    return dict(version=VERSION, scope=SCOPE, model=_model(row), provenance=asdict(proof))


def _event(row):
    if row is None:
        return None
    event = dict(row)
    try:
        event['request_id'] = str(UUID(str(event['request_id'])))
        event['recorded_at'] = original._time(event['recorded_at'])
        snapshot = event['snapshot']; model = snapshot['model']; proof = snapshot['provenance']
        if (not original._integer(event.get('source_product_code')) or not original._integer(event.get('event_seq'))
                or not original._integer(event.get('operator_id')) or not original._integer(event.get('write_txid'))
                or event.get('action') not in ('approve','revoke') or type(event.get('note')) is not str
                or not event['note'].strip() or len(event['note']) > 3000
                or not original._hash(event.get('request_digest')) or not original._hash(event.get('source_basis'))
                or not original._hash(event.get('approval_basis')) or snapshot['version'] != VERSION
                or snapshot['scope'] != SCOPE or type(model) is not dict or type(proof) is not dict
                or not original._integer(model['source_product_code'])
                or model['source_product_code'] != event['source_product_code']
                or not original._integer(model['product_code'])
                or proof['source_product_code'] != model['source_product_code']
                or type(proof['source_product_code']) is not int or proof['product_code'] != model['product_code']
                or type(proof['product_code']) is not int or proof['basis'] != event['source_basis']
                or proof['kind'] != SCOPE or not _reference(proof['source_reference'])
                or not _reference(proof['rights_reference'], rights=True)
                or original._digest(dict(version=VERSION,scope=SCOPE,model=model)) != event['source_basis']
                or original._digest(snapshot) != event['approval_basis']):
            raise ValueError()
    except (KeyError, TypeError, ValueError, HTTPException):
        original._fail(503, 'photo_event_invalid')
    return deepcopy(event)


def _latest(conn, code):
    event = _event(_sql(conn,'latest','SELECT '+EVENT_COLUMNS+''' FROM part_photo_approval_events
        WHERE source_product_code=:code ORDER BY event_seq DESC LIMIT 1''', code=code).mappings().first())
    if event and event['source_product_code'] != code:
        original._fail(503, 'photo_event_binding_invalid')
    return event


def read_current(conn, code, *, provenance_reader=None, image_reader=None, business_rights_reference=None):
    transaction = original._transaction(conn)
    original._code(code)
    row = original._read(conn, code)
    latest = _latest(conn, code)
    state, reason = 'unapproved', None
    if latest:
        if latest['action'] == 'revoke':
            state = 'revoked'
        elif basis(row) != latest['source_basis']:
            state, reason = 'stale', 'photo_model_or_asset_changed'
        else:
            try:
                snapshot = _verify(conn,row,provenance_reader,image_reader,business_rights_reference)
                state = 'approved' if snapshot == latest['snapshot'] else 'stale'
                if state == 'stale': reason = 'photo_provenance_changed'
            except _Unavailable as error:
                state, reason = 'unknown' if error.status == 503 else 'stale', error.reason
    # A consistent caller snapshot remains required. In particular, never keep
    # an observed old approval if bytes/provenance work crosses a latest change.
    final_latest = _latest(conn, code)
    if final_latest != latest:
        latest = final_latest
        state = 'revoked' if latest and latest['action']=='revoke' else 'stale'
        reason = 'photo_approval_changed_during_read'
    if original._transaction(conn) is not transaction:
        original._fail(503, 'photo_transaction_changed')
    return dict(source_product_code=code, scope=SCOPE, event_seq=latest['event_seq'] if latest else 0,
                state=state, allowed=state=='approved', basis=basis(row),
                approval_basis=latest['approval_basis'] if latest else None,
                reference=f'part-photo-approval:{code}:{latest["event_seq"]}:{latest["approval_basis"]}'
                          if latest and state=='approved' else None,
                operator_id=latest['operator_id'] if latest and state=='approved' else None,
                approved_at=latest['recorded_at'] if latest and state=='approved' else None,
                reason=reason)


def _request(code, action, expected_seq, request_id, note, operator_id, **binding):
    if (not original._integer(expected_seq,minimum=0,maximum=original.MAX_BIGINT-1)
            or type(note) is not str or not note.strip() or len(note)>3000):
        original._fail(422, 'photo_request_invalid')
    try:
        uid = str(request_id) if type(request_id) is UUID else request_id
        if type(uid) is not str or str(UUID(uid)) != uid: raise ValueError()
    except (ValueError, TypeError):
        original._fail(422, 'photo_request_id_invalid')
    return uid,original._digest(dict(version=VERSION,source_product_code=code,action=action,
        expected_seq=expected_seq,request_id=uid,note=note,operator_id=operator_id,**binding))


def _replay(conn, code, action, operator_id, uid, digest):
    event = _event(_sql(conn,'request','SELECT '+EVENT_COLUMNS+' FROM part_photo_approval_events WHERE request_id=:uid',
                        uid=uid).mappings().first())
    if event and (event['source_product_code'] != code or event['action'] != action
                  or event['operator_id'] != operator_id or event['request_digest'] != digest):
        original._fail(409, 'photo_request_conflict')
    return event


def _append(conn, code, seq, uid, digest, action, operator_id, note, snapshot):
    source_basis = original._digest(dict(version=VERSION,scope=SCOPE,model=snapshot['model']))
    row = _sql(conn,'append','''INSERT INTO part_photo_approval_events
        (source_product_code,event_seq,request_id,request_digest,action,operator_id,note,source_basis,approval_basis,snapshot)
        VALUES(:code,:seq,:uid,:digest,:action,:actor,:note,:source_basis,:basis,CAST(:snapshot AS jsonb))
        RETURNING '''+EVENT_COLUMNS,code=code,seq=seq,uid=uid,digest=digest,action=action,actor=operator_id,
        note=note.strip(),source_basis=source_basis,basis=original._digest(snapshot),snapshot=original._json(snapshot)).mappings().one()
    event = _event(row)
    if (event['source_product_code'] != code or event['event_seq'] != seq or event['request_id'] != uid
            or event['request_digest'] != digest or event['action'] != action or event['operator_id'] != operator_id
            or event['snapshot'] != snapshot):
        original._fail(503, 'photo_append_mismatch')
    return event


def approve(conn, code, *, expected_seq, expected_basis, request_id, note, actor,
            provenance_reader=None, image_reader=None, business_rights_reference=None):
    transaction = original._transaction(conn)
    original._code(code)
    row = original._read(conn,code,lock=True)
    operator_id = original._actor(conn,actor)
    if not original._hash(expected_basis): original._fail(422, 'photo_basis_invalid')
    uid,digest = _request(code,'approve',expected_seq,request_id,note,operator_id,
                          expected_basis=expected_basis,business_rights_reference=business_rights_reference)
    event = _replay(conn,code,'approve',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _latest(conn,code)
        if (latest['event_seq'] if latest else 0) != expected_seq: original._fail(409, 'photo_sequence_changed')
        if basis(row) != expected_basis: original._fail(409, 'photo_basis_changed')
        try:
            snapshot = _verify(conn,row,provenance_reader,image_reader,business_rights_reference)
        except _Unavailable as error:
            original._fail(error.status,error.reason)
        event = _append(conn,code,expected_seq+1,uid,digest,'approve',operator_id,note,snapshot)
    current = read_current(conn,code,provenance_reader=provenance_reader,image_reader=image_reader,
                           business_rights_reference=business_rights_reference)
    if original._transaction(conn) is not transaction: original._fail(503, 'photo_transaction_changed')
    return dict(event=event,replayed=replayed,current=current,committed=False)


def revoke(conn, code, *, expected_seq, request_id, note, actor):
    transaction = original._transaction(conn)
    original._code(code)
    original._read(conn,code,lock=True)
    operator_id = original._actor(conn,actor)
    uid,digest = _request(code,'revoke',expected_seq,request_id,note,operator_id)
    event = _replay(conn,code,'revoke',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _latest(conn,code)
        if not latest or latest['event_seq'] != expected_seq: original._fail(409, 'photo_sequence_changed')
        if latest['action'] != 'approve': original._fail(409, 'photo_already_revoked')
        event = _append(conn,code,expected_seq+1,uid,digest,'revoke',operator_id,note,latest['snapshot'])
    current = read_current(conn,code)
    if original._transaction(conn) is not transaction: original._fail(503, 'photo_transaction_changed')
    return dict(event=event,replayed=replayed,current=current,committed=False)
