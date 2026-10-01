"""Grouped copy work and selective saves. Reuses product history/review; no DDL."""
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .auth import current_operator
from .db import engine
from .product_name import display_name
from .pc_configuration_copy import catalog_rows
from .pc_configuration_edit import CopyEdit, EDITABLE, save_copy
from .pc_configuration_review import load_review
from .admin_pc_workspace import ProposedChange

router = APIRouter()
MAX_BATCH = 10


class SelectedCopy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    configuration_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(gt=0)
    source_basis: str = Field(pattern=r'^[a-f0-9]{64}$')
    changes: list[ProposedChange] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def unique_fields(self):
        if len({c.field for c in self.changes}) != len(self.changes):
            raise ValueError('동일 항목을 두 번 적용할 수 없습니다.')
        return self


class BatchSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[SelectedCopy] = Field(min_length=1, max_length=MAX_BATCH)

    @model_validator(mode='after')
    def unique_products(self):
        if len({p.configuration_id for p in self.items}) != len(self.items):
            raise ValueError('같은 제품은 한 번만 저장할 수 있습니다.')
        return self


def grouped(rows):
    parts, reasons, names = defaultdict(set), defaultdict(set), {}
    active = [r for r in rows if r['status'] != 'retired']
    for r in active:
        identity = r['configuration_id']
        for p in r['search_parts']:
            parts[str(p['code'])].add(identity)
            names[str(p['code'])] = display_name(p['name'])
        for reason in r.get('review_reasons') or []:
            reasons[reason].add(identity)
    groups = [dict(key='part:'+code, kind='part', code=code, title=names[code], ids=sorted(ids), count=len(ids))
              for code, ids in parts.items() if len(ids)>1]
    groups += [dict(key='reason:'+reason, kind='reason', title=reason, ids=sorted(ids), count=len(ids)) for reason,ids in reasons.items()]
    groups.sort(key=lambda g:(g['kind']!='part', -g['count'], g['key']))
    return dict(catalog_total=len(rows),items=active,groups=groups,max_batch=MAX_BATCH)


def save_selected(conn, body, actor):
    results=[]
    for item in body.items:
        try:
            with conn.begin_nested():
                cfg, _, _, state = load_review(conn, item.configuration_id, lock=True)
                if cfg['revision'] != item.revision or state['basis'] != item.source_basis:
                    raise HTTPException(409,'제품 또는 근거가 변경되었습니다. 최신 정보로 제안을 다시 생성해 주세요.')
                edit={k:cfg['content'].get(k) for k in EDITABLE}
                for change in item.changes:
                    edit[change.field]=change.value
                # Server schema validation is authoritative, never trust the client preview.
                try:
                    request=CopyEdit(revision=item.revision,content=edit)
                except ValueError:
                    raise HTTPException(422,'선택한 설명 형식이 올바르지 않습니다.')
                result=save_copy(conn,item.configuration_id,request,actor)
                results.append(dict(configuration_id=item.configuration_id,status='saved' if result['changed'] else 'unchanged',
                                    revision=result['revision'],changed=result['changed'],
                                    message='설명 저장 · 검토 필요' if result['changed'] else '동일 내용 · 변경 없음'))
        except HTTPException as exc:
            results.append(dict(configuration_id=item.configuration_id,status='conflict' if exc.status_code==409 else 'failed',
                                message=exc.detail,http_status=exc.status_code))
    return dict(items=results,counts={k:sum(r['status']==k for r in results) for k in ('saved','unchanged','conflict','failed')})


@router.get('/api/admin/pc-workspace/groups')
def groups():
    with engine.connect() as conn:
        return grouped(catalog_rows(conn))


@router.post('/api/admin/pc-workspace/batch-description')
def apply_selected(body:BatchSave,request:Request):
    actor=current_operator()
    if not actor or actor.get('role') not in ('operator','owner'):
        raise HTTPException(403,'설명을 저장할 권한이 없습니다.')
    if request.headers.get('sec-fetch-site')=='cross-site':
        raise HTTPException(403,'같은 관리자 화면에서 저장해 주세요.')
    with engine.begin() as conn:
        return save_selected(conn,body,actor)
