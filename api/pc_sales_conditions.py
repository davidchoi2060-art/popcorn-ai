"""Operator-confirmed, configuration-bound sales terms in the existing content/history."""
from datetime import date, datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import text
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter()
LABELS = {'os':'운영체제', 'keyboard':'키보드', 'mouse':'마우스', 'monitor':'모니터', 'warranty':'보증·AS'}


class Condition(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    state: Literal['unknown', 'included', 'excluded', 'verified'] = 'unknown'
    detail: str = Field(default='', max_length=200)
    evidence: str = Field(default='', max_length=1500)
    source: str = Field(default='', max_length=500)
    checked_date: date | None = None
    months: StrictInt | None = Field(default=None, ge=1, le=120)

    @model_validator(mode='after')
    def evidence_required(self):
        if self.state != 'unknown':
            if not self.evidence or not self.source or not self.checked_date:
                raise ValueError('확인한 내용·출처·확인일이 필요합니다')
            if self.checked_date > datetime.now(timezone(timedelta(hours=9))).date():
                raise ValueError('확인일은 미래일 수 없습니다')
            if self.state in ('included', 'verified') and not self.detail:
                raise ValueError('조건 상세가 필요합니다')
        return self


class SalesEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: StrictInt = Field(gt=0)
    source_basis: str = Field(pattern=r'^[a-f0-9]{64}$')
    key: Literal['os', 'keyboard', 'mouse', 'monitor', 'warranty']
    condition: Condition

    @model_validator(mode='after')
    def type_matches(self):
        c = self.condition
        if self.key == 'warranty':
            if c.state not in ('unknown', 'verified') or (c.state == 'verified' and c.months is None):
                raise ValueError('보증은 확인 상태와 보증기간을 입력해 주세요')
        elif c.state == 'verified' or c.months is not None:
            raise ValueError('포함 조건에 올바른 상태를 입력해 주세요')
        return self


def scope_basis(config, parts=None, offers=None):
    from .pc_configuration_copy import digest
    # Copy changes/approval must not invalidate terms; BOM and sale offer changes do.
    return digest(dict(configuration_id=config['configuration_id'], bom=config.get('bom_fingerprint'),
        parts=sorted(({k:p.get(k) for k in ('ordinal','slot','source_code','quantity','pseudo','explanation_hash')}
                      for p in (parts if parts is not None else config.get('parts', []))), key=lambda p:p['ordinal']),
        offers=sorted(({k:o.get(k) for k in ('offer_id','price_snapshot','payload')}
                       for o in (offers if offers is not None else config.get('offers', []))), key=lambda o:o['offer_id'])))


def customer_statement(key, item):
    if item['state'] == 'unknown':
        return f'{LABELS[key]} 포함 여부를 구매 전에 확인해 주세요.' if key != 'warranty' else '보증·AS 조건을 구매 전에 확인해 주세요.'
    if key == 'warranty':
        return f"보증·AS 기간은 {item['months']}개월입니다."
    # Use one fixed, inspectable claim rather than allowing any text mentioning a verified subject.
    return f"{LABELS[key]}는 {'포함됩니다' if item['state']=='included' else '미포함입니다'}."


def effective_conditions(config, parts=None, offers=None):
    basis = scope_basis(config, parts, offers)
    raw = config.get('content', {}).get('_sales_conditions', {})
    result = {}
    for key in LABELS:
        row = raw.get(key, {}) if isinstance(raw, dict) else {}
        item = dict(state='unknown', detail='', evidence='', source='', checked_date=None, months=None, stale=False)
        try:
            validated = Condition.model_validate({k:row[k] for k in Condition.model_fields if k in row})
            # Validate target-specific state as well as required evidence, even on reads.
            SalesEdit(revision=1, source_basis='a'*64, key=key, condition=validated)
            if row.get('scope_basis') == basis and row.get('operator_id') and row.get('confirmed_at'):
                item.update(validated.model_dump(mode='json'))
            elif validated.state != 'unknown':
                item.update(stale=True, previous=row)
        except (ValueError, TypeError, KeyError):
            item['stale'] = bool(row)
        item['customer_statement'] = customer_statement(key, item)
        result[key] = item
    return result


def ai_conditions(config):
    return {k:{f:v[f] for f in ('state','detail','months','customer_statement')} for k,v in effective_conditions(config).items()}


def customer_conditions(config, parts=None, offers=None):
    """Customer-safe terms contract; does not approve publication or recommendation."""
    terms = effective_conditions(config, parts, offers)
    return {key:dict(state=item['state'],
                    detail=item['detail'] if item['state'] != 'unknown' else '',
                    months=item['months'] if item['state'] == 'verified' else None,
                    needs_reconfirmation=item['stale'],
                    customer_statement=item['customer_statement'])
            for key,item in terms.items()}


def save_condition(conn, identity, body, actor):
    from .pc_configuration_review import load_review
    from .pc_configuration_edit import write_content
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    cfg, parts, offers, state = load_review(conn, identity, lock=True)
    if cfg['status'] == 'retired':
        raise HTTPException(409, '보관된 제품군의 판매조건은 수정할 수 없습니다.')
    if cfg['revision'] != body.revision or state['basis'] != body.source_basis:
        raise HTTPException(409, '상품 또는 근거가 변경되었습니다. 입력을 보존한 뒤 최신 내용을 다시 확인해 주세요.')
    before = effective_conditions(cfg, parts, offers)[body.key]
    payload = body.condition.model_dump(mode='json')
    if not before.get('stale') and all(before.get(k) == v for k,v in payload.items()):
        return dict(revision=cfg['revision'], changed=False)
    item = dict(payload, scope_basis=scope_basis(cfg, parts, offers), operator_id=actor['operator_id'],
                confirmed_at=iso(datetime.now(timezone.utc)))
    # An unknown state removes previous assertions but may retain operator notes for follow-up.
    terms = dict(cfg['content'].get('_sales_conditions') or {})
    terms[body.key] = item
    return write_content(conn, cfg, dict(cfg['content'], _sales_conditions=terms), actor,
                         'sales_conditions', [body.key])


@router.put('/api/admin/pc-configurations/{identity}/sales-conditions')
def update_sales(identity: str, body: SalesEdit, request: Request):
    actor = current_operator()
    if not actor or actor.get('role') not in ('operator','owner'):
        raise HTTPException(403, '판매조건을 저장할 권한이 없습니다.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '같은 관리자 화면에서 저장해 주세요.')
    with engine.begin() as conn:
        return save_condition(conn, identity, body, actor)
