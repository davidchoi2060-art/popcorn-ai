"""Evidence-bound administrative recommendation review, separate from publication."""
import copy
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import text

from .auth import current_operator
from .db import engine
from .pc_configuration_copy import digest, part_needs_review
from .pc_review_specs import specs_for_review
from .recommend import rule_verdict, rule_ref_value, _rule_applies
from .pc_review_policy import POLICY_VERSION, issue_stages, route_checks
from .pc_cooling_plan import cooling_plan

router = APIRouter()
MANUAL = {
    'copy': '변경 구성과 상품 설명 일치',
    'price': '가격 기준·조립 서비스 포함 조건 확인',
}


class Finding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: bool = False
    evidence: str = Field(default='', max_length=2000)


class ReviewEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: StrictInt = Field(gt=0)
    basis: str = Field(min_length=64, max_length=64)
    action: Literal['draft', 'approve', 'revoke']
    findings: dict[str, Finding] = Field(default_factory=dict, max_length=100)
    note: str = Field(default='', max_length=2000)


def basis_hash(config, parts, offers, rows, specs, rules):
    content = {k:v for k,v in config['content'].items() if k not in ('_review', '_admin_bom_edit')}
    # Workflow flags and approval timestamps are not source evidence.
    # List reads contain all families and SQL RowMappings; detail reads contain
    # one family and plain dicts. Canonicalize both to this BOM's exact evidence.
    codes={p['explanation_code'] for p in parts if not p['pseudo']}
    cooling = cooling_plan(parts, rows)
    policy = POLICY_VERSION + ':bundled-5500gt-v1' if cooling['verified_bundle'] and cooling['installed']=='bundled' else POLICY_VERSION
    return digest(dict(policy=policy,content=content,
        parts=sorted((dict(p) for p in parts),key=lambda p:p['ordinal']),
        offers=sorted((dict(o) for o in offers),key=lambda o:o['offer_id']),
        rows={k:dict(v) for k,v in rows.items() if k in codes},
        specs={k:dict(v) for k,v in specs.items() if k in codes},
        rules=sorted((dict(r) for r in rules),key=lambda r:(r.get('rule_id',0),r['rule_key']))))


def assess(config, parts, offers, rows, specs, rules):
    blockers = []
    assembly_checks = []
    customer_conditions = []
    real = [p for p in parts if not p['pseudo']]
    for p in real:
        e = rows.get(p['explanation_code'])
        if part_needs_review(p,e,stage='recommendation'):
            blockers.append(f"{p['slot']} · {p['source_code']}: 부품 설명·원문 확인 필요")
        if e:
            for issue in issue_stages(e):
                if issue['stage'] == 'assembly':
                    assembly_checks.append(dict(key=f"part:{p['ordinal']}:{len(assembly_checks)}",label=f"{p['slot']} · {p['source_code']}",detail=issue['issue'],state='unknown',stage='assembly'))
                    customer_conditions.extend(issue['customer_conditions'])
        if e and e.get('product_code') is not None and e.get('sale_status') != '판매중':
            blockers.append(f"{p['slot']} · {p['source_code']}: 판매중 부품 아님")
    if not real or not offers:
        blockers.append('구성 부품 또는 가격 기준 없음')
    if config['status'] == 'retired':
        blockers.append('보관된 제품군')
    content = config['content']
    if not content.get('title') or not content.get('intro'):
        blockers.append('상품명·소개 누락')
    for key in ('cpu','ram_gb','storage_gb'):
        if content.get('facts',{}).get(key) is None:
            blockers.append(f'추천용 사양 확인 필요: {key}')
    checks = []
    slots = {}
    for p in real:
        slots.setdefault(p['slot'], []).append(p)
    if not rules:
        blockers.append('활성 호환 규칙 없음')
    # Evaluate all registered active rules against the fixed BOM, not DFS traversal order.
    for rule in rules:
        left, right = slots.get(rule['slot'], []), slots.get(rule['ref_slot'], [])
        if not left or not right:
            checks.append(dict(key=rule['rule_key'],label=rule['label'],state='unknown',
                               detail='대상 부품 또는 비교 부품 없음 · 내장/기본 포함 여부 근거 확인'))
            continue
        for p in left:
            s = specs.get(p['explanation_code'], {})
            if s.get('part_type') and not _rule_applies(rule,s):
                continue
            for q in right:
                key = f"{rule['rule_key']}:{p['ordinal']}:{q['ordinal']}"
                ref = specs.get(q['explanation_code'], {})
                v, r = s.get(rule['field']), ref.get(rule['ref_field'])
                state = 'unknown'
                detail = f"{p['source_code']} {rule['field']}={v}; {q['source_code']} {rule['ref_field']}={r}"
                if v is not None and r is not None and s.get('part_type') and rule['op'] in ('eq','gte','lte','contains'):
                    try:
                        state = 'pass' if rule_verdict(rule,v,r) else 'fail'
                        detail = (rule.get('detail_fmt') or '{v} / {r}').replace('{v}',str(v)).replace('{r}',str(rule_ref_value(rule,r)))
                        if state == 'fail' and rule['op'] == 'contains':
                            detail = f"등록 지원 목록 {v} / 대상 {r} · 목록에 없음"
                        if rule['rule_key']=='power':
                            detail = f"파워 정격 {v}W / GPU {r}W + 규칙 여유 {rule.get('ref_offset') or 0}W"
                    except (TypeError, ValueError):
                        detail += ' · 사양 형식 확인 필요'
                checks.append(dict(key=key,label=rule['label'],state=state,detail=detail,
                                   missing_fields=[field for field,value in ((rule['field'],v),(rule['ref_field'],r)) if value is None]))
                if state == 'fail':
                    blockers.append(rule['label']+' · 현재 DB 사양 불일치')
    route_checks(checks,parts,specs,config,rows)
    cooling = cooling_plan(parts,rows)
    if cooling['installed']=='bundled':
        customer_conditions.append('cooling_usage')
    assembly_checks += [dict(x) for x in checks if x['stage']=='assembly']
    required = {x['key']:x['label']+' · 추천 전 근거 확인' for x in checks if x['state']=='unknown' and x['stage']=='recommendation'} | MANUAL
    critical_unknown = any(x['state']=='unknown' and x['stage']=='recommendation' for x in checks)
    recommendation = 'hold' if blockers or critical_unknown else 'conditional' if assembly_checks else 'ready'
    basis = basis_hash(config,parts,offers,rows,specs,rules)
    saved = content.get('_review',{})
    current = saved.get('basis') == basis
    approved = config['status'] == 'approved' and saved.get('state') == 'approved' and current and recommendation != 'hold'
    findings = saved.get('findings',{}) if current else {}
    return dict(configuration_id=config['configuration_id'],revision=config['revision'],basis=basis,
                checks=checks,blockers=list(dict.fromkeys(blockers)),required=required,
                findings=findings,note=saved.get('note',''),
                state='approved' if approved else ('stale' if saved and not current else ('pending' if saved.get('state')=='approved' else saved.get('state','pending'))),
                approved_by=saved.get('actor'),approved_at=saved.get('at'),
                eligible=approved,customer_publishable=False,
                policy_version=POLICY_VERSION,recommendation_state=recommendation,cooling_plan=cooling_plan(parts,rows,specs),
                assembly_state='not_started',assembly_checks=assembly_checks,
                assembly_checklist=['실제 부품·수량·장착·전원 연결','부팅·메모리·저장장치 인식','사용 조건별 부하·온도·안정성'],
                customer_conditions=sorted(set(customer_conditions)),
                prior_review=saved if saved and not current else None)


def load_review(c, identity, lock=False):
    if lock:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    config = c.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id'+(' FOR UPDATE' if lock else '')),
                       dict(id=identity)).mappings().first()
    if not config:
        raise HTTPException(404,'조립PC 구성 없음')
    parts = [dict(p) for p in c.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),dict(id=identity)).mappings()]
    offers = [dict(o) for o in c.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY offer_id'),dict(id=identity)).mappings()]
    codes = [p['explanation_code'] for p in parts if not p['pseudo']]
    rows = {r['source_product_code']:dict(r) for r in c.execute(text('''SELECT e.*,p.product_name,p.spec_source_text,
        p.status AS sale_status,p.sale_price FROM product_explanations e LEFT JOIN products p USING(product_code)
        WHERE e.source_product_code=ANY(:codes) ORDER BY e.source_product_code'''+(' FOR SHARE OF e' if lock else '')),dict(codes=codes)).mappings()}
    product_codes = [r['product_code'] for r in rows.values() if r['product_code'] is not None]
    if lock and product_codes:
        c.execute(text('SELECT product_code FROM products WHERE product_code=ANY(:codes) ORDER BY product_code FOR SHARE'),dict(codes=product_codes)).all()
        # Re-read after locks: no price/name race between verification and approval.
        rows = {r['source_product_code']:dict(r) for r in c.execute(text('''SELECT e.*,p.product_name,p.spec_source_text,
            p.status AS sale_status,p.sale_price FROM product_explanations e LEFT JOIN products p USING(product_code)
            WHERE e.source_product_code=ANY(:codes) ORDER BY e.source_product_code'''),dict(codes=codes)).mappings()}
    by_product = {r['product_code']:dict(r) for r in c.execute(text('SELECT * FROM product_specs WHERE product_code=ANY(:codes) ORDER BY product_code'+(' FOR SHARE' if lock else '')),dict(codes=product_codes)).mappings()}
    specs = specs_for_review(rows, by_product)
    rules = [dict(r) for r in c.execute(text('SELECT * FROM compat_rules WHERE active ORDER BY rule_id'+(' FOR SHARE' if lock else ''))).mappings()]
    return dict(config), parts, offers, assess(config,parts,offers,rows,specs,rules)


def review_allows(c, config):
    content = config['content']
    if '_review' not in content:
        return not content.get('_admin_bom_edit',{}).get('review_required')
    return load_review(c,config['configuration_id'])[3]['eligible']


def save_review(c, identity, body, actor):
    config,parts,offers,state = load_review(c,identity,lock=True)
    if config['revision'] != body.revision or state['basis'] != body.basis:
        raise HTTPException(409,'구성·설명·가격·검사 근거가 변경되었습니다. 최신 검토를 다시 열어 주세요.')
    if config['status'] == 'retired':
        raise HTTPException(409,'보관된 제품군은 검토할 수 없습니다.')
    if set(body.findings) - set(state['required']):
        raise HTTPException(422,'현재 검토 항목에 없는 입력입니다.')
    if body.action == 'approve':
        if state['blockers']:
            raise HTTPException(422,'승인 전 보완 필요: '+' / '.join(state['blockers']))
        if state['recommendation_state'] == 'hold':
            raise HTTPException(422,'추천 필수 규격은 근거 사양을 보완한 뒤 승인할 수 있습니다. 검토 메모만으로 통과 처리하지 않습니다.')
        if any(not body.findings.get(k) or not body.findings[k].confirmed or len(body.findings[k].evidence.strip())<10 for k in state['required']):
            raise HTTPException(422,'모든 확인 항목에 근거(10자 이상)와 확인 표시가 필요합니다.')
    if body.action == 'revoke' and not body.note.strip():
        raise HTTPException(422,'추천 제외 사유가 필요합니다.')
    content = copy.deepcopy(config['content'])
    content['_review'] = dict(state={'approve':'approved','draft':'pending','revoke':'revoked'}[body.action],
        basis=state['basis'],findings={k:v.model_dump() for k,v in body.findings.items()},note=body.note.strip(),
        actor=dict(operator_id=actor['operator_id'],name=actor.get('name','')),at=datetime.now(timezone.utc).isoformat(),
        checks=state['checks'],scope='admin_recommendation_review')
    if content.get('_admin_bom_edit'):
        content['_admin_bom_edit']['review_required'] = body.action != 'approve'
    snapshot = dict(config,parts=parts,offers=offers,edit=dict(kind='review',action=body.action,name=actor.get('name',''),operator_id=actor['operator_id']))
    c.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:rev,CAST(:s AS jsonb))'),
              dict(id=identity,rev=config['revision'],s=json.dumps(snapshot,ensure_ascii=False,default=str)))
    c.execute(text('''UPDATE pc_configurations SET content=CAST(:content AS jsonb),content_hash=:hash,
        copy_hash=:copy_hash,status=:status,revision=revision+1,updated_at=now() WHERE configuration_id=:id'''),
        dict(id=identity,content=json.dumps(content,ensure_ascii=False),hash=digest(dict(content=content,parts=parts,offers=offers)),
             copy_hash=digest(dict(content=content,parts=parts)),status='approved' if body.action=='approve' else 'review_required'))
    return load_review(c,identity)[3]


@router.get('/api/admin/pc-configurations/{identity}/review')
def get_review(identity: str):
    with engine.connect() as c:
        return load_review(c,identity)[3]


@router.put('/api/admin/pc-configurations/{identity}/review')
def put_review(identity: str, body: ReviewEdit, request: Request):
    actor = current_operator()
    if not actor or actor.get('role') not in ('operator','owner'):
        raise HTTPException(403,'검토 저장 권한이 없습니다.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403,'같은 관리자 화면에서 저장해 주세요.')
    with engine.begin() as c:
        return save_review(c,identity,body,actor)
