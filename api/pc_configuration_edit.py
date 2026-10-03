"""Version-checked admin copy edits. BOM, offers and publication are never edited here."""
import json
from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import text
from .auth import current_operator
from .db import engine
from .pc_copy_claims import claim_issues, LABELS

router = APIRouter()
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Paragraph = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
EDITABLE = ('title', 'intro', 'benefits', 'scene', 'checks', 'faq', 'recommendation_policy')


class FAQ(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: Short
    answer: Paragraph


class Description(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Short
    intro: Paragraph
    benefits: list[tuple[Short, Paragraph]] = Field(min_length=1, max_length=12)
    scene: Paragraph
    checks: list[Paragraph] = Field(max_length=30)
    faq: list[FAQ] = Field(max_length=30)
    recommendation_policy: dict[Short, Paragraph] = Field(max_length=8)


class CopyEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(gt=0)
    content: Description
    source_basis: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')



def description_complete(content):
    if not content.get('title') or not content.get('intro'):
        return False
    if not content.get('_admin_creation'):
        return True # Keep the established legacy catalog review contract.
    try:
        Description.model_validate({k:content.get(k,{} if k=='recommendation_policy' else [] if k in ('benefits','checks','faq') else '') for k in EDITABLE})
        return True
    except ValidationError:
        return False


def save_copy(conn, identity, body, actor):
    from .pc_configuration_copy import digest
    # Coordinate with the existing importer; row lock + revision prevent lost updates.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
    prior = conn.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id FOR UPDATE'), {'id': identity}).mappings().first()
    if not prior:
        raise HTTPException(404, '조립PC 구성 없음')
    if prior['revision'] != body.revision:
        raise HTTPException(409, '다른 변경이 먼저 저장되었습니다. 입력한 내용은 유지됩니다. 최신 내용을 확인한 후 다시 편집해 주세요.')
    if prior['status'] == 'retired':
        raise HTTPException(409, '보관된 제품군의 설명은 수정할 수 없습니다.')
    if body.source_basis is not None:
        from .pc_configuration_review import load_review
        if load_review(conn,identity)[3]['basis'] != body.source_basis:
            raise HTTPException(409,'상품 구성·가격·부품 근거가 변경되었습니다. 최신 자료에서 설명을 다시 확인해 주세요.')
    edit = body.content.model_dump(mode='json')
    if set(edit['recommendation_policy']) != set(prior['content'].get('recommendation_policy', {})):
        raise HTTPException(422, '추천 기준의 항목 이름은 변경할 수 없습니다.')
    content = dict(prior['content'], **edit)
    for field in EDITABLE:
        # Preserve legacy text on unrelated edits; inspect every newly changed field.
        if edit[field] != prior['content'].get(field):
            from .pc_configuration_copy import read_configuration
            from .pc_sales_conditions import effective_conditions
            # Load only if a claim needs evidence. Existing no-claim edits keep their read contract.
            initial = claim_issues(edit[field], field)
            issues = (claim_issues(edit[field], field, effective_conditions(read_configuration(conn, identity)))
                      if initial and prior['content'].get('_sales_conditions') else initial)
            if issues:
                labels = '·'.join(LABELS[key] for key in issues)
                raise HTTPException(422, f'설명 근거 확인 필요: {field} ({labels}). 포함 여부 확인 안내 또는 확인된 부품 사양으로 수정해 주세요.')
    if content == prior['content']:
        return dict(revision=prior['revision'], updated_at=prior['updated_at'], content=content, changed=False)
    return write_content(conn, prior, content, actor, 'description',
                         [k for k in EDITABLE if prior['content'].get(k) != edit[k]])


def write_content(conn, prior, content, actor, kind, fields):
    from .pc_configuration_copy import digest
    identity = prior['configuration_id']
    snapshot = dict(prior)
    for key, table in [('parts', 'pc_configuration_parts'), ('offers', 'pc_configuration_offers')]:
        snapshot[key] = [dict(r) for r in conn.execute(text(f'SELECT * FROM {table} WHERE configuration_id=:id ORDER BY '+('ordinal' if key=='parts' else 'offer_id')), {'id': identity}).mappings()]
    snapshot['edit'] = dict(kind=kind, operator_id=actor['operator_id'], name=actor.get('name', ''), fields=fields)
    conn.execute(text('INSERT INTO pc_configuration_history(configuration_id,revision,snapshot) VALUES(:id,:revision,CAST(:snapshot AS jsonb))'),
                 dict(id=identity, revision=prior['revision'], snapshot=json.dumps(snapshot, ensure_ascii=False, default=str)))
    parts = [{k: v for k, v in p.items() if k != 'configuration_id'} for p in snapshot['parts']]
    basis = dict(content={k: v for k,v in content.items() if k!='evidence'}, parts=parts, bom_fingerprint=prior['bom_fingerprint'])
    payload = dict(content=content, parts=parts, offers=[o['payload'] for o in snapshot['offers']],
                   observed_date=prior['observed_date'], bom_fingerprint=prior['bom_fingerprint'])
    row = conn.execute(text('''UPDATE pc_configurations SET content=CAST(:content AS jsonb),
      content_hash=:hash, copy_hash=:copy_hash, revision=revision+1, updated_at=now()
      WHERE configuration_id=:id RETURNING revision, updated_at'''),
      dict(id=identity, content=json.dumps(content, ensure_ascii=False), hash=digest(payload), copy_hash=digest(basis))).mappings().one()
    return dict(row, content=content, changed=True)


@router.put('/api/admin/pc-configurations/{identity}/description')
def update_description(identity: str, body: CopyEdit, request: Request):
    actor = current_operator()
    if not actor or actor.get('role') not in ('operator', 'owner'):
        raise HTTPException(403, '설명을 저장할 권한이 없습니다.')
    # JSON PUT cannot be submitted by a cross-site HTML form. Also reject cross-site fetches.
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '같은 관리자 화면에서 저장해 주세요.')
    with engine.begin() as conn:
        return save_copy(conn, identity, body, actor)


@router.get('/api/admin/pc-configurations/{identity}/description-history')
def description_history(identity: str, offset: int=Query(0, ge=0), limit: int=Query(10, ge=1, le=30)):
    with engine.connect() as conn:
        if not conn.execute(text('SELECT 1 FROM pc_configurations WHERE configuration_id=:id'), {'id':identity}).scalar():
            raise HTTPException(404, '조립PC 구성 없음')
        total = conn.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'), {'id':identity}).scalar()
        rows = conn.execute(text('''SELECT revision, archived_at, snapshot FROM pc_configuration_history
            WHERE configuration_id=:id ORDER BY revision DESC LIMIT :limit OFFSET :offset'''),
            dict(id=identity, offset=offset, limit=limit)).mappings()
        items = [dict(revision=r['revision'], archived_at=r['archived_at'], edit=r['snapshot'].get('edit'),
                      content={k:r['snapshot'].get('content',{}).get(k) for k in (*EDITABLE, '_sales_conditions')}) for r in rows]
    return dict(total=total, offset=offset, items=items)
