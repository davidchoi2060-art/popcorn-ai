"""Per-customer assembly and phone decisions, bound to immutable quote revisions."""
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, AwareDatetime
from typing import Literal
from sqlalchemy import text
from .db import engine
from .auth import current_operator
from .pc_configuration_copy import digest

router = APIRouter(prefix='/api/admin/pc-quote-assembly')


def operator(request=None, write=False):
    actor = current_operator()
    if not actor or (write and actor.get('role') not in ('operator','owner')):
        raise HTTPException(403,'관리자 권한 확인 필요')
    if write and request and request.headers.get('sec-fetch-site')=='cross-site':
        raise HTTPException(403,'같은 관리자 화면에서 저장해 주세요.')
    return actor


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(gt=0)
    action: Literal['issue','resolve','verify']
    note: str = Field(min_length=10,max_length=2000)
    issue_id: UUID | None = None


class Contact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(gt=0)
    change_set_id: UUID
    revision: StrictInt = Field(gt=0)
    decision: Literal['agreed','declined','no_response']
    contacted_at: AwareDatetime
    summary: str = Field(min_length=10,max_length=2000)
    impacts: str = Field(min_length=10,max_length=2000)


class Apply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(gt=0)
    change_set_id: UUID
    revision: StrictInt = Field(gt=0)
    validation_id: UUID


def load(c, quote_id, version=None, lock=False):
    q = c.execute(text('SELECT * FROM pc_customer_quotes WHERE quote_id=:q'+(' FOR UPDATE' if lock else '')),dict(q=str(quote_id))).mappings().first()
    if not q: raise HTTPException(404,'고객 견적 없음')
    if version is not None and (q['status']!='active' or q['current_version']!=version):
        raise HTTPException(409,'견적 버전 변경 또는 보관 상태 · 다시 확인 필요')
    v = c.execute(text('SELECT * FROM pc_quote_versions WHERE quote_id=:q AND version=:v'),dict(q=str(quote_id),v=q['current_version'])).mappings().first()
    if not v: raise HTTPException(409,'견적 구성 미등록')
    events = [dict(x) for x in c.execute(text('SELECT * FROM pc_quote_events WHERE quote_id=:q ORDER BY created_at,event_id'),dict(q=str(quote_id))).mappings()]
    return dict(q),dict(v),events


def unresolved(events):
    closed = {e['payload'].get('issue_id') for e in events if e['action']=='assembly_resolve'}
    return [e for e in events if e['action']=='assembly_issue' and str(e['event_id']) not in closed]


def assembly_verified(events, version, fingerprint):
    relevant=[e for e in events if e['action'].startswith('assembly_') or e['action']=='phone_change_applied']
    return bool(relevant and relevant[-1]['action']=='assembly_verify'
                and relevant[-1]['payload'].get('version')==version
                and relevant[-1]['payload'].get('bom_fingerprint')==fingerprint)


def event(c,q,actor,action,payload,change=None):
    c.execute(text('''INSERT INTO pc_quote_events(event_id,quote_id,change_set_id,actor_kind,actor_ref,action,payload,created_at)
      VALUES(:id,:q,:change,'admin',:actor,:action,CAST(:payload AS jsonb),clock_timestamp())'''),
      dict(id=str(uuid4()),q=str(q),change=str(change) if change else None,actor=str(actor['operator_id']),action=action,payload=json.dumps(payload,ensure_ascii=False,default=str)))


def proposal(c,quote_id,body):
    s = c.execute(text('SELECT * FROM pc_change_sets WHERE change_set_id=:s FOR UPDATE'),dict(s=str(body.change_set_id))).mappings().first()
    if not s or str(s['quote_id'])!=str(quote_id) or s['status']!='draft' or s['base_version']!=body.version or s['current_revision']!=body.revision:
        raise HTTPException(409,'변경안이 갱신되었거나 현재 견적과 다릅니다.')
    r = c.execute(text('SELECT * FROM pc_change_revisions WHERE change_set_id=:s AND revision=:r'),dict(s=str(body.change_set_id),r=body.revision)).mappings().one()
    return dict(s),dict(r)


def proposal_basis(row):
    return digest({k:row[k] for k in ('change_set_id','revision','bom','bom_fingerprint','base_total','delta_amount','total_amount','price_status','price_basis')})


def valid_agreement(events, change_id, revision, basis):
    contacts = [e for e in events if e['action']=='phone_decision' and str(e.get('change_set_id'))==str(change_id)]
    if not contacts: return False
    last = contacts[-1]['payload']
    return last.get('decision')=='agreed' and last.get('revision')==revision and last.get('proposal_basis')==basis


def record(c,quote_id,body,actor):
    _,v,events = load(c,quote_id,body.version,True)
    if len(body.note.strip())<10: raise HTTPException(422,'확인 내용을 10자 이상 기록해 주세요.')
    open_issues = unresolved(events)
    if body.action=='resolve' and str(body.issue_id) not in {str(e['event_id']) for e in open_issues}:
        raise HTTPException(409,'해결할 열린 조립 이슈가 없습니다.')
    if body.action=='verify':
        pending = c.execute(text("SELECT 1 FROM pc_change_sets WHERE quote_id=:q AND status='draft'"),dict(q=str(quote_id))).first()
        confirmed = c.execute(text('SELECT 1 FROM pc_quote_confirmations WHERE quote_id=:q AND version=:v'),dict(q=str(quote_id),v=body.version)).first()
        if open_issues or pending or not confirmed:
            raise HTTPException(409,'미해결 이슈·미확정 변경안을 정리하고 고객 확정 후 검수해 주세요.')
    event(c,quote_id,actor,'assembly_'+body.action,dict(version=body.version,bom_fingerprint=v['bom_fingerprint'],note=body.note.strip(),issue_id=str(body.issue_id) if body.issue_id else None))


def contact(c,quote_id,body,actor):
    load(c,quote_id,body.version,True)
    _,r=proposal(c,quote_id,body)
    if body.contacted_at>datetime.now(timezone.utc) or len(body.summary.strip())<10 or len(body.impacts.strip())<10:
        raise HTTPException(422,'실제 연락 시각과 변경 영향·동의 내용을 확인해 주세요.')
    if body.decision=='agreed' and (r['price_status']!='confirmed' or r['total_amount'] is None):
        raise HTTPException(409,'변경 금액 확정 후 고객 동의를 기록해 주세요.')
    event(c,quote_id,actor,'phone_decision',dict(body.model_dump(mode='json'),proposal_basis=proposal_basis(r),base_total=r['base_total'],total_amount=r['total_amount'],delta_amount=r['delta_amount']),body.change_set_id)


def apply_change(c,quote_id,body,actor):
    _,v,events=load(c,quote_id,body.version,True)
    _,r=proposal(c,quote_id,body)
    if not valid_agreement(events,body.change_set_id,body.revision,proposal_basis(r)):
        raise HTTPException(409,'현재 변경안에 대한 고객 동의가 없습니다.')
    validation=c.execute(text('SELECT * FROM pc_change_validations WHERE validation_id=:v'),dict(v=str(body.validation_id))).mappings().first()
    if (not validation or str(validation['change_set_id'])!=str(body.change_set_id) or validation['revision']!=body.revision
            or validation['bom_fingerprint']!=r['bom_fingerprint'] or validation['expires_at']<=datetime.now(timezone.utc)
            or any(validation[k]!='pass' for k in ('compatibility','sale_status','pricing','intent_match'))):
        raise HTTPException(409,'현재 변경안의 유효한 호환성·판매·가격·고객 조건 검증이 필요합니다.')
    new_version=body.version+1
    c.execute(text('''INSERT INTO pc_quote_versions(quote_id,version,bom,bom_fingerprint,conditions,total_amount,assembly_fee_included,price_basis)
      VALUES(:q,:v,CAST(:bom AS jsonb),:fp,CAST(:cond AS jsonb),:total,:fee,CAST(:price AS jsonb))'''),dict(q=str(quote_id),v=new_version,bom=json.dumps(r['bom'],ensure_ascii=False),fp=r['bom_fingerprint'],cond=json.dumps(v['conditions'],ensure_ascii=False),total=r['total_amount'],fee=v['assembly_fee_included'],price=json.dumps(r['price_basis'],ensure_ascii=False)))
    c.execute(text("UPDATE pc_change_sets SET status='applied',applied_version=:v,validation_id=:check WHERE change_set_id=:s"),dict(v=new_version,check=str(body.validation_id),s=str(body.change_set_id)))
    # Existing DB trigger moves current_version and preserves the original version.
    c.execute(text('INSERT INTO pc_quote_confirmations(confirmation_id,quote_id,version,confirmed_by) VALUES(:id,:q,:v,:by)'),dict(id=str(uuid4()),q=str(quote_id),v=new_version,by='phone-record:'+str(actor['operator_id'])))
    event(c,quote_id,actor,'phone_change_applied',dict(base_version=body.version,version=new_version,revision=body.revision,proposal_basis=proposal_basis(r)),body.change_set_id)


@router.get('')
def quotes(configuration_id:str=Query(max_length=100)):
    operator()
    with engine.connect() as c:
        items=[dict(r) for r in c.execute(text('''SELECT quote_id,current_version,status,updated_at FROM pc_customer_quotes
            WHERE configuration_id=:id ORDER BY updated_at DESC LIMIT 50'''),dict(id=configuration_id)).mappings()]
    return dict(items=items,limit=50)


@router.get('/{quote_id}')
def detail(quote_id:UUID):
    operator()
    with engine.connect() as c:
        q,v,events=load(c,quote_id)
        drafts=[dict(r) for r in c.execute(text('''SELECT r.* FROM pc_change_sets s JOIN pc_change_revisions r
            ON r.change_set_id=s.change_set_id AND r.revision=s.current_revision WHERE s.quote_id=:q AND s.status='draft' '''),dict(q=str(quote_id))).mappings()]
        verified=assembly_verified(events,q['current_version'],v['bom_fingerprint'])
        open_issues=unresolved(events)
        validations=[dict(r) for r in c.execute(text('''SELECT v.* FROM pc_change_validations v JOIN pc_change_sets s
          ON s.change_set_id=v.change_set_id AND s.current_revision=v.revision
          WHERE s.quote_id=:q AND s.status='draft' AND v.expires_at>now() ORDER BY checked_at DESC'''),dict(q=str(quote_id))).mappings()]
        return dict(quote=q,version=v,events=events,open_issues=open_issues,drafts=drafts,validations=validations,
                    assembly_state='issue' if open_issues else 'pending_change' if drafts else 'verified' if verified else 'not_verified')


@router.post('/{quote_id}/assembly')
def save_action(quote_id:UUID,body:Action,request:Request):
    actor=operator(request,True)
    with engine.begin() as c: record(c,quote_id,body,actor)
    return detail(quote_id)


@router.post('/{quote_id}/contact')
def save_contact(quote_id:UUID,body:Contact,request:Request):
    actor=operator(request,True)
    with engine.begin() as c: contact(c,quote_id,body,actor)
    return detail(quote_id)


@router.post('/{quote_id}/apply')
def save_apply(quote_id:UUID,body:Apply,request:Request):
    actor=operator(request,True)
    with engine.begin() as c: apply_change(c,quote_id,body,actor)
    return detail(quote_id)
