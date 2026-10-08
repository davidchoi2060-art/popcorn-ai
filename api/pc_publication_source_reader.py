"""SERVER-only native approval reader for the unchanged publication callback.

No routes, connection factory, credentials, writes or approval generation.
One caller-owned REPEATABLE READ/SERIALIZABLE snapshot is required. This reader
also works inside the publication writer's transaction; it never changes its
read/write mode. Historical approval refs are re-bound to the actual config.
Native photo evidence is component evidence, never a whole-PC photo or sale.
"""
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text

from . import part_explanation_approval as part
from . import part_photo_approval as photo
from . import pc_customer_publication as publication


def _require(condition, reason, status=422):
    if not condition:
        raise publication._Unavailable(reason, status)


def _snapshot(conn, expected=None):
    transaction = part._transaction(conn)
    if expected is not None and transaction is not expected:
        raise HTTPException(503, 'publication_native_snapshot_changed')
    if conn.execute(text('SHOW transaction_isolation')).scalar_one() not in ('repeatable read','serializable'):
        raise HTTPException(503, 'publication_native_snapshot_required')
    if part._transaction(conn) is not transaction:
        raise HTTPException(503, 'publication_native_snapshot_changed')
    return transaction


def _utc(value):
    # The native event validators have already checked awareness and DB time.
    return datetime.fromisoformat(part._time(value)).astimezone(timezone.utc)


def _inputs(configuration, parts, offers, review, rows):
    _require(type(configuration) is dict and type(review) is dict and type(rows) is dict,
             'publication_native_input_invalid')
    identity, revision = configuration.get('configuration_id'), configuration.get('revision')
    _require(type(identity) is str and bool(identity.strip()) and part._integer(revision)
             and configuration.get('status')=='approved'
             and review.get('configuration_id')==identity and type(review.get('revision')) is int
             and review['revision']==revision and review.get('state')=='approved'
             and review.get('eligible') is True and review.get('customer_publishable') is False,
             'publication_native_configuration_invalid')
    _require(type(parts) in (list,tuple) and bool(parts) and type(offers) in (list,tuple)
             and all(type(o) is dict and o.get('configuration_id')==identity for o in offers),
             'publication_native_coverage_invalid')
    ordinals=set(); real=[]
    for p in parts:
        _require(type(p) is dict and p.get('configuration_id')==identity
                 and part._integer(p.get('ordinal'),minimum=0,maximum=2**31-1)
                 and p['ordinal'] not in ordinals and part._integer(p.get('quantity'),maximum=2**31-1)
                 and type(p.get('slot')) is str and bool(p['slot'].strip()) and type(p.get('pseudo')) is bool,
                 'publication_native_coverage_invalid')
        ordinals.add(p['ordinal'])
        if not p['pseudo']:
            _require(part._integer(p.get('explanation_code')) and part._hash(p.get('explanation_hash')),
                     'publication_native_part_identity_invalid')
            real.append(p)
    codes={p['explanation_code'] for p in real}
    _require(bool(real) and all(type(code) is int and type(row) is dict
                               and type(row.get('source_product_code')) is int
                               and row['source_product_code']==code for code,row in rows.items()) and set(rows)==codes,
             'publication_native_rows_invalid')
    return real, codes


def make_source_reader(*, image_reader=None, business_rights_reference=None):
    """Build an internal callback; image/rights inputs are registered SERVER ports.

    image_reader(asset, code, 'detail') follows product_images.read_image.
    The rights reference is the existing business attestation, not request data.
    Missing ports fail closed; SQL failures propagate for whole-caller rollback.
    Bytes are cached only within one invocation and one exact asset identity.
    """
    def source_reader(conn, *, configuration, parts, offers, review, rows):
        transaction=_snapshot(conn)
        configuration,parts,offers,review,rows=deepcopy((configuration,parts,offers,review,rows))
        real,codes=_inputs(configuration,parts,offers,review,rows)
        _require(callable(image_reader) and photo._reference(business_rights_reference,rights=True),
                 'publication_native_photo_ports_unconnected',503)
        native={}; cache={}
        for code in sorted(codes):
            try:
                row=part._read(conn,code)
                current=part.read_current(conn,code)
                event=part._latest(conn,code)
                _require(event is not None and event['action']=='approve' and current['allowed'] is True
                         and current['state']=='approved' and current['event_seq']==event['event_seq']
                         and current['source_product_code']==code and current['scope']==part.SCOPE
                         and current['basis']==event['approval_basis']==part.basis(row)
                         and current['explanation_hash']==part._current(row,event)['explanation_hash']
                         and part.basis(row)==part.basis(rows[code]),
                         'publication_native_part_not_current')
                photo_event=photo._latest(conn,code)
                _require(photo_event is not None and photo_event['action']=='approve',
                         'publication_native_photo_not_approved')

                def provenance(connection, *, row, expected_basis):
                    _require(connection is conn and row['source_product_code']==code
                             and expected_basis==photo_event['source_basis'],
                             'publication_native_photo_binding_invalid')
                    return photo.PhotoProvenance(**deepcopy(photo_event['snapshot']['provenance']))

                expected_asset=deepcopy(row['content'].get('image_asset'))

                def current_bytes(asset, source_code, variant):
                    _require(source_code==code and type(source_code) is int and variant=='detail'
                             and asset==expected_asset, 'publication_native_asset_binding_invalid')
                    key=(code,part._digest(asset))
                    if key not in cache:
                        cache[key]=image_reader(deepcopy(asset),code,variant)
                    if part._transaction(conn) is not transaction:
                        raise HTTPException(503,'publication_native_snapshot_changed')
                    return cache[key]

                photo_current=photo.read_current(conn,code,provenance_reader=provenance,image_reader=current_bytes,
                                                business_rights_reference=business_rights_reference)
                # SQL outside the storage exception boundary must propagate.
                _snapshot(conn,transaction)
                _require(photo_current['allowed'] is True and photo_current['state']=='approved'
                         and photo_current['event_seq']==photo_event['event_seq']
                         and photo_current['approval_basis']==photo_event['approval_basis']
                         and photo_current['basis']==photo_event['source_basis']==photo.basis(row)
                         and photo_current['operator_id']==photo_event['operator_id']
                         and photo_current['approved_at']==photo_event['recorded_at'],
                         'publication_native_photo_not_current',503 if photo_current['state']=='unknown' else 422)
                # Native description may be withdrawn while the bytes port runs.
                refreshed=part._read(conn,code)
                _require(part.basis(refreshed)==part.basis(row) and part._latest(conn,code)==event
                         and photo._latest(conn,code)==photo_event,
                         'publication_native_evidence_changed')
                _snapshot(conn,transaction)
                native[code]=(row,current,event,photo_event,photo_current,cache[(code,part._digest(expected_asset))])
            except HTTPException as error:
                _snapshot(conn,transaction)
                raise publication._Unavailable('publication_native_history_unavailable',error.status_code) from None
        part_proofs=[]; photo_proofs=[]
        for p in sorted(real,key=lambda p:p['ordinal']):
            row,current,event,photo_event,photo_current,data=native[p['explanation_code']]
            _require(p['explanation_hash']==current['explanation_hash'], 'publication_native_bom_hash_changed')
            part_proofs.append(publication.PartApproval(p['ordinal'],p['explanation_code'],
                publication.component_basis(configuration,p,row),
                f'part-explanation-approval:{p["explanation_code"]}:{event["event_seq"]}:{event["approval_basis"]}',
                event['operator_id'],_utc(event['recorded_at'])))
            proof=photo_event['snapshot']['provenance']
            photo_proofs.append(publication.PhotoApproval(p['ordinal'],p['explanation_code'],
                publication.photo_basis(configuration,p,row),photo_current['reference'],photo_event['operator_id'],
                _utc(photo_event['recorded_at']),proof['kind'],proof['source_reference'],proof['rights_reference'],data))
        _snapshot(conn,transaction)
        return publication.PublicationSources(publication.SOURCE_POLICY,tuple(part_proofs),tuple(photo_proofs))
    return source_reader
