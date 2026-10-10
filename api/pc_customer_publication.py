"""Caller-TX publication events; no routes, engine, commits or sale authority.

The caller supplies an authenticated actor and a consistent DB snapshot, and
rolls back its entire transaction on ANY exception (including SQL conflicts).
Write results are pending: only a fresh read after the caller commits confirms
durable state. read_current never falls back to an older approval.

source_reader is a SERVER callable, never request data. It must read accepted,
immutable component/photo approval records and CURRENT photo bytes, using this
conn for DB evidence. No such production producer is connected here: None
denies approval. Typed mock proofs are test inputs, not production approval.
Assembly-only NULL links require a future accepted source-current producer;
this implementation rejects them rather than inventing retail/current facts.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from .timeutil import iso

VERSION = 'pc-customer-publication-v1'
SOURCE_POLICY = 'pc-publication-source-v1'
MAX_BIGINT = 2**63 - 1
EVENT_COLUMNS = ('configuration_id,event_seq,request_id,request_digest,action,'
                 'operator_id,recorded_at,note,configuration_revision,'
                 'review_basis,publication_basis,evidence')


@dataclass(frozen=True)
class PartApproval:
    ordinal: int
    explanation_code: int
    basis: str
    reference: str
    operator_id: int
    approved_at: datetime


@dataclass(frozen=True)
class PhotoApproval:
    ordinal: int
    explanation_code: int
    basis: str
    reference: str
    operator_id: int
    approved_at: datetime
    kind: str
    source_reference: str
    rights_reference: str
    detail_bytes: bytes


@dataclass(frozen=True)
class PublicationSources:
    policy_version: str
    parts: tuple[PartApproval, ...]
    photos: tuple[PhotoApproval, ...]


class _Unavailable(Exception):
    def __init__(self, reason, status=422):
        self.reason, self.status = reason, status


def _fail(status, reason):
    raise HTTPException(status, reason)


def _integer(value, minimum=1, maximum=MAX_BIGINT):
    return type(value) is int and minimum <= value <= maximum


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _string(value, maximum=2000):
    return type(value) is str and 0 < len(value.strip()) <= maximum


def _digest(value):
    # Reuse the canonical source algorithm; do not redefine content/copy hashes.
    from .pc_configuration_copy import digest
    return digest(value)


def _sql(conn, tag, statement, **params):
    _transaction(conn)
    return conn.execute(text('/*pc_publication:' + tag + '*/ ' + statement), params)


def _transaction(conn):
    if (conn.in_transaction() is not True or conn.in_nested_transaction()
            or conn.get_execution_options().get('isolation_level') == 'AUTOCOMMIT'):
        _fail(503, 'publication_caller_transaction_required')
    transaction = conn.get_transaction()
    if transaction is None:
        _fail(503, 'publication_caller_transaction_required')
    return transaction


def _load(conn, identity, lock=False):
    _transaction(conn)
    from .pc_configuration_review import load_review
    return load_review(conn, identity, lock=lock)


def _identity(identity):
    if not _string(identity, 200) or identity != identity.strip():
        _fail(422, 'publication_configuration_id_invalid')


def _actor(conn, actor):
    # actor MUST come from the caller's authenticated context, never a body ID.
    if (type(actor) is not dict or not _integer(actor.get('operator_id'))
            or actor.get('role') not in ('owner', 'operator')
            or actor.get('status') != '활성'):
        _fail(403, 'publication_actor_required')
    row = _sql(conn, 'actor', '''SELECT operator_id,role,status FROM admin_operators
        WHERE operator_id=:operator_id FOR SHARE''', operator_id=actor['operator_id']).mappings().first()
    if (not row or not _integer(row['operator_id']) or row['operator_id'] != actor['operator_id']
            or row['role'] != actor['role'] or row['status'] != '활성'):
        _fail(403, 'publication_actor_required')
    return actor['operator_id']


def _latest(conn, identity):
    return _sql(conn, 'latest', 'SELECT ' + EVENT_COLUMNS + ''' FROM pc_customer_publication_events
        WHERE configuration_id=:identity ORDER BY event_seq DESC LIMIT 1''', identity=identity).mappings().first()


def _event(row):
    if not row:
        return None
    e = dict(row)
    try:
        e['request_id'] = str(UUID(str(e['request_id'])))
        e['recorded_at'] = _stamp(e['recorded_at'])
    except (ValueError, TypeError, KeyError, _Unavailable):
        _fail(503, 'publication_event_invalid')
    if (not _string(e.get('configuration_id'), 200) or not _integer(e.get('event_seq'))
            or not _integer(e.get('operator_id')) or not _integer(e.get('configuration_revision'), maximum=2**31-1)
            or e.get('action') not in ('approve', 'revoke')
            or type(e.get('note')) is not str or len(e['note']) > 2000
            or (e['action'] == 'revoke' and not e['note'].strip())
            or any(not _hash(e.get(k)) for k in ('request_digest','review_basis','publication_basis'))
            or type(e.get('evidence')) is not dict or e['evidence'].get('version') != VERSION
            or _digest(e['evidence']) != e['publication_basis']):
        _fail(503, 'publication_event_invalid')
    binding = e['evidence'].get('binding', {})
    if (type(binding) is not dict or binding.get('configuration_id') != e['configuration_id']
            or type(binding.get('revision')) is not int or binding['revision'] != e['configuration_revision']
            or e['evidence'].get('review_basis') != e['review_basis']):
        _fail(503, 'publication_event_invalid')
    return deepcopy(e)


def _stamp(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _Unavailable('publication_approval_time_invalid')
    value = value.astimezone(timezone.utc)
    if value > datetime.now(timezone.utc):
        raise _Unavailable('publication_approval_time_invalid')
    return iso(value)


def _proof(proof, part, expected_basis, cls):
    if (type(proof) is not cls or not _integer(proof.ordinal, 0, 2**31-1)
            or proof.ordinal != part['ordinal'] or not _integer(proof.explanation_code)
            or proof.explanation_code != part['explanation_code'] or not _hash(proof.basis)
            or proof.basis != expected_basis or not _string(proof.reference, 500)
            or not _integer(proof.operator_id)):
        raise _Unavailable('publication_component_proof_invalid')
    return dict(reference=proof.reference, operator_id=proof.operator_id,
                approved_at=_stamp(proof.approved_at))


def component_basis(config, part, row):
    """Binding a future server producer must record; not an approval operation."""
    return _digest(dict(configuration_id=config['configuration_id'], revision=config['revision'],
                        part=dict(part), explanation=dict(row)))


def photo_basis(config, part, row):
    return _digest(dict(component_basis=component_basis(config, part, row),
                        asset=row['content'].get('image_asset'),
                        merchant_source=row['content'].get('image_url')))


def _evidence(conn, config, parts, offers, review, source_reader):
    from .pc_configuration_copy import explanation_digest
    from .part_explanations import is_current
    from .pc_sales_conditions import scope_basis, customer_conditions
    from .pc_copy_claims import claim_issues
    if not callable(source_reader):
        raise _Unavailable('publication_source_reader_unconnected', 503)
    identity, revision = config.get('configuration_id'), config.get('revision')
    if (not _string(identity, 200) or not _integer(revision, maximum=2**31-1)
            or config.get('status') != 'approved' or type(config.get('content')) is not dict
            or any(not _hash(config.get(k)) for k in ('bom_fingerprint','content_hash','copy_hash'))
            or type(review.get('revision')) is not int or review['revision'] != revision
            or review.get('configuration_id') != identity or not _hash(review.get('basis'))
            or review.get('state') != 'approved' or review.get('eligible') is not True
            or review.get('customer_publishable') is not False):
        raise _Unavailable('publication_recommendation_not_current')
    saved = config['content'].get('_review', {})
    if (type(saved) is not dict or saved.get('state') != 'approved' or saved.get('basis') != review['basis']
            or type(saved.get('actor')) is not dict or not _integer(saved['actor'].get('operator_id'))
            or not _string(saved.get('at'), 100)):
        raise _Unavailable('publication_recommendation_not_current')
    try:
        _stamp(datetime.fromisoformat(saved['at']))
    except ValueError:
        raise _Unavailable('publication_approval_time_invalid') from None
    terms = customer_conditions(config,parts,offers)
    # Legacy recommendation approval is not proof of unknown sale conditions.
    if any(claim_issues(config['content'].get(key, []),key,terms)
           for key in ('title','intro','benefits','scene','checks','faq')):
        raise _Unavailable('publication_copy_claim_not_supported')
    if (not isinstance(parts, (list, tuple)) or not parts or not isinstance(offers, (list, tuple))
            or any(type(p) is not dict or p.get('configuration_id') != identity
                   or not _integer(p.get('ordinal'), 0, 2**31-1) or not _integer(p.get('quantity'), maximum=2**31-1)
                   or type(p.get('pseudo')) is not bool or not _string(p.get('slot'), 100)
                   or not _string(p.get('source_code'), 200) for p in parts)
            or len({p['ordinal'] for p in parts}) != len(parts)
            or any(type(o) is not dict or o.get('configuration_id') != identity for o in offers)):
        raise _Unavailable('publication_configuration_binding_invalid')
    real = [p for p in parts if not p['pseudo']]
    if not real or any(not _integer(p.get('explanation_code')) or not _hash(p.get('explanation_hash')) for p in real):
        raise _Unavailable('publication_part_missing')
    rows = {r['source_product_code']:dict(r) for r in _sql(conn, 'sources', '''SELECT e.*,p.product_name,
        p.spec_source_text,p.status AS sale_status,p.sale_price FROM product_explanations e
        LEFT JOIN products p USING(product_code) WHERE e.source_product_code=ANY(:codes)
        ORDER BY e.source_product_code''', codes=[p['explanation_code'] for p in real]).mappings()}
    for p in real:
        row = rows.get(p['explanation_code'])
        # Assembly-only parts are sold only inside the PC: no retail product/sale status.
        assembly = (row is not None and row.get('product_code') is None and type(row.get('content')) is dict
                    and row['content'].get('availability_scope') == 'assembly_only')
        if (not row or type(row.get('content')) is not dict
                or not (assembly or _integer(row.get('product_code')))
                or row.get('status') != 'approved' or not _integer(row.get('approved_by'))
                or row.get('approved_at') is None or (not assembly and row.get('sale_status') != '판매중')
                or row['content'].get('review_issues') or not is_current(row)
                or p['explanation_hash'] != explanation_digest(row)):
            raise _Unavailable('publication_part_not_current')
        _stamp(row['approved_at'])
    # Copies protect the locked source snapshot from an accidental callback mutation.
    transaction = _transaction(conn)
    proofs = source_reader(conn, configuration=deepcopy(config), parts=deepcopy(parts),
                           offers=deepcopy(offers), review=deepcopy(review), rows=deepcopy(rows))
    if _transaction(conn) is not transaction:
        _fail(503, 'publication_caller_transaction_changed')
    if (type(proofs) is not PublicationSources or proofs.policy_version != SOURCE_POLICY
            or type(proofs.parts) is not tuple or type(proofs.photos) is not tuple
            or any(type(p) is not PartApproval for p in proofs.parts)
            or any(type(p) is not PhotoApproval for p in proofs.photos)):
        raise _Unavailable('publication_source_proofs_invalid')
    by_part = {p.ordinal:p for p in proofs.parts}
    by_photo = {p.ordinal:p for p in proofs.photos}
    ordinals = {p['ordinal'] for p in real}
    if (len(by_part) != len(proofs.parts) or len(by_photo) != len(proofs.photos)
            or set(by_part) != ordinals or set(by_photo) != ordinals):
        raise _Unavailable('publication_component_coverage_invalid')
    from .product_images import MEDIA_BUCKET
    components = []
    for p in sorted(real, key=lambda p:p['ordinal']):
        row, photo = rows[p['explanation_code']], by_photo[p['ordinal']]
        part_proof = _proof(by_part[p['ordinal']], p, component_basis(config,p,row), PartApproval)
        if (part_proof['operator_id'] != row['approved_by']
                or part_proof['approved_at'] != _stamp(row['approved_at'])):
            raise _Unavailable('publication_part_approval_mismatch')
        photo_proof = _proof(photo, p, photo_basis(config,p,row), PhotoApproval)
        asset = row['content'].get('image_asset')
        if (type(asset) is not dict or asset.get('bucket') != MEDIA_BUCKET
                or type(asset.get('detail_key')) is not str
                or re.fullmatch(r'products/'+str(p['explanation_code'])+r'/[a-f0-9]{16}/detail\.png',asset['detail_key']) is None
                or not _hash(asset.get('detail_sha256')) or photo.kind != 'registered_product_photo'
                or not _string(photo.source_reference, 500) or not _string(photo.rights_reference, 500)
                or type(photo.detail_bytes) is not bytes or not 8 < len(photo.detail_bytes) <= 10*1024*1024
                or not photo.detail_bytes.startswith(b'\x89PNG\r\n\x1a\n')
                or hashlib.sha256(photo.detail_bytes).hexdigest() != asset['detail_sha256']):
            raise _Unavailable('publication_photo_not_verified')
        components.append(dict(ordinal=p['ordinal'], explanation_code=p['explanation_code'],
            component_basis=component_basis(config,p,row), part_approval=part_proof,
            photo_basis=photo_basis(config,p,row), photo_approval=photo_proof,
            photo_kind=photo.kind, source_reference=photo.source_reference,
            rights_reference=photo.rights_reference, detail_sha256=asset['detail_sha256']))
    return dict(version=VERSION, source_policy_version=SOURCE_POLICY,
        binding=dict(configuration_id=identity, revision=revision,
                     **{k:config[k] for k in ('bom_fingerprint','content_hash','copy_hash')}),
        configuration_digest=_digest(dict(content=config['content'],parts=sorted(parts,key=lambda p:p['ordinal']),
            offers=sorted(offers,key=lambda o:o['offer_id']),observed_date=config.get('observed_date'))),
        review_basis=review['basis'], review_digest=_digest(dict(basis=review['basis'],saved=saved,
            policy_version=review.get('policy_version'))), terms_scope_basis=scope_basis(config,parts,offers),
        terms_digest=_digest(terms), components=components)


def read_current(conn, identity, *, source_reader=None):
    """One caller snapshot. None/unavailable evidence always yields allowed=False."""
    _transaction(conn)
    _identity(identity)
    latest = _event(_latest(conn, identity))
    config, parts, offers, review = _load(conn, identity)
    if (config.get('configuration_id') != identity or review.get('configuration_id') != identity
            or (latest and latest['configuration_id'] != identity)):
        _fail(503, 'publication_read_binding_invalid')
    evidence, reason = None, None
    try:
        evidence = _evidence(conn, config, parts, offers, review, source_reader)
    except _Unavailable as error:
        reason = error.reason
    basis = _digest(evidence) if evidence is not None else None
    state = 'unapproved' if latest is None else ('revoked' if latest['action']=='revoke' else 'stale')
    if latest and latest['action']=='approve' and evidence is not None and latest['publication_basis']==basis:
        state = 'approved'
    return dict(configuration_id=identity, revision=config['revision'], basis=review['basis'],
        event_seq=latest['event_seq'] if latest else 0, state=state, allowed=state=='approved',
        publication_basis=basis, event_publication_basis=latest['publication_basis'] if latest else None,
        source_state='current' if evidence is not None else 'unknown', reason=reason or
            ('publication_basis_changed' if state=='stale' else None))


def _request(identity, action, expected_seq, request_id, note, operator_id, **binding):
    if not _integer(expected_seq, 0, MAX_BIGINT-1) or type(note) is not str or len(note)>2000:
        _fail(422, 'publication_request_invalid')
    try:
        if type(request_id) is UUID:
            uid = str(request_id)
        elif type(request_id) is str and str(UUID(request_id)) == request_id:
            uid = request_id
        else:
            raise ValueError()
    except ValueError:
        _fail(422, 'publication_request_id_invalid')
    return uid, _digest(dict(configuration_id=identity, action=action, operator_id=operator_id,
                            expected_seq=expected_seq, request_id=uid, note=note, **binding))


def _replay(conn, identity, action, operator_id, uid, digest):
    row = _sql(conn, 'request', 'SELECT '+EVENT_COLUMNS+
               ' FROM pc_customer_publication_events WHERE request_id=:request_id', request_id=uid).mappings().first()
    event = _event(row)
    if event and (event['configuration_id'] != identity or event['action'] != action
                  or event['operator_id'] != operator_id or event['request_digest'] != digest):
        _fail(409, 'publication_request_conflict')
    return event


def _append(conn, identity, seq, uid, request_digest, action, operator_id, note, evidence):
    row = _sql(conn, 'append', '''INSERT INTO pc_customer_publication_events
        (configuration_id,event_seq,request_id,request_digest,action,operator_id,note,
         configuration_revision,review_basis,publication_basis,evidence)
        VALUES(:identity,:seq,:uid,:request_digest,:action,:operator_id,:note,
         :revision,:review_basis,:publication_basis,CAST(:evidence AS jsonb)) RETURNING '''+EVENT_COLUMNS,
        identity=identity,seq=seq,uid=uid,request_digest=request_digest,action=action,operator_id=operator_id,
        note=note.strip(), revision=evidence['binding']['revision'],review_basis=evidence['review_basis'],
        publication_basis=_digest(evidence),evidence=json.dumps(evidence,ensure_ascii=False,sort_keys=True,
                                                              separators=(',',':'),allow_nan=False)).mappings().one()
    event = _event(row)
    if (event['configuration_id'] != identity or event['event_seq'] != seq or event['request_id'] != uid
            or event['request_digest'] != request_digest or event['action'] != action
            or event['operator_id'] != operator_id or event['evidence'] != evidence):
        _fail(503, 'publication_append_mismatch')
    return event


def approve(conn, identity, *, expected_seq, revision, review_basis, publication_basis,
            request_id, note='', actor, source_reader=None):
    _transaction(conn)
    _identity(identity)
    # Original lock order is owned by load_review, not copied/redefined here.
    config, parts, offers, review = _load(conn, identity, lock=True)
    operator_id = _actor(conn, actor)
    if not _integer(revision, maximum=2**31-1) or not _hash(review_basis) or not _hash(publication_basis):
        _fail(422, 'publication_binding_invalid')
    uid, digest = _request(identity,'approve',expected_seq,request_id,note,operator_id,
                           revision=revision,review_basis=review_basis,publication_basis=publication_basis)
    event = _replay(conn,identity,'approve',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _event(_latest(conn,identity))
        if (latest['event_seq'] if latest else 0) != expected_seq:
            _fail(409, 'publication_sequence_changed')
        if config['revision'] != revision or review['basis'] != review_basis:
            _fail(409, 'publication_basis_changed')
        try:
            evidence = _evidence(conn,config,parts,offers,review,source_reader)
        except _Unavailable as error:
            _fail(error.status,error.reason)
        if _digest(evidence) != publication_basis:
            _fail(409, 'publication_basis_changed')
        event = _append(conn,identity,expected_seq+1,uid,digest,'approve',operator_id,note,evidence)
    return dict(event=event,replayed=replayed,committed=False,
                current=read_current(conn,identity,source_reader=source_reader))


def revoke(conn, identity, *, expected_seq, request_id, reason, actor):
    _transaction(conn)
    _identity(identity)
    _load(conn, identity, lock=True)  # Stale recommendation/source evidence is NOT a revoke blocker.
    operator_id = _actor(conn, actor)
    if not _string(reason):
        _fail(422, 'publication_revoke_reason_required')
    uid, digest = _request(identity,'revoke',expected_seq,request_id,reason,operator_id)
    event = _replay(conn,identity,'revoke',operator_id,uid,digest)
    replayed = event is not None
    if not replayed:
        latest = _event(_latest(conn,identity))
        if not latest or latest['event_seq'] != expected_seq:
            _fail(409, 'publication_sequence_changed')
        if latest['action'] != 'approve':
            _fail(409, 'publication_already_revoked')
        event = _append(conn,identity,expected_seq+1,uid,digest,'revoke',operator_id,reason,latest['evidence'])
    return dict(event=event,replayed=replayed,committed=False,current=read_current(conn,identity))
