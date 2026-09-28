"""Admin-only BOM copy reads; no public recommendation or price authority."""
import hashlib
import json
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from .db import engine
from .part_explanations import is_current

router=APIRouter()

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def explanation_digest(row):
    return digest({k:row[k] for k in ('content','source_snapshot','source_fingerprint')})

def part_needs_review(part, row):
    if part['pseudo']:
        return False
    if not row or part['explanation_hash']!=explanation_digest(row):
        return True
    if row['content'].get('review_issues'):
        return True
    # Assembly-only identity is linked to the BOM, not to a fictitious retail product.
    if row.get('product_code') is None:
        return row['content'].get('availability_scope')!='assembly_only'
    return not is_current(row)

def read_configuration(conn, identity):
    r=conn.execute(text('SELECT * FROM pc_configurations WHERE configuration_id=:id'),{'id':identity}).mappings().first()
    if r is None: raise HTTPException(404,'조립PC 구성 없음')
    parts=[dict(p) for p in conn.execute(text('SELECT * FROM pc_configuration_parts WHERE configuration_id=:id ORDER BY ordinal'),{'id':identity}).mappings()]
    affected=[]
    for p in parts:
        row=None
        if not p['pseudo']:
            row=conn.execute(text('''SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status
              FROM product_explanations e LEFT JOIN products p ON p.product_code=e.product_code
              WHERE e.source_product_code=:code'''),{'code':p['explanation_code']}).mappings().one()
            p['explanation']=row['content']
            p['image_url']=f"/api/product-images/{p['explanation_code']}/detail"
            p['sale_status']=row['sale_status']
        if part_needs_review(p,row): affected.append(p['source_code'])
    offers=[dict(o) for o in conn.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY price_snapshot,offer_id'),{'id':identity}).mappings()]
    return dict(r,parts=parts,offers=offers,needs_review=bool(affected),affected_parts=affected,
                customer_publishable=False,price_is_snapshot=True)

@router.get('/api/admin/pc-configurations')
def list_configurations(offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=104)):
    with engine.connect() as c:
        total=c.execute(text('SELECT count(*) FROM pc_configurations')).scalar_one()
        rows=c.execute(text('''SELECT configuration_id,bom_fingerprint,revision,status,observed_date,
          content->>'title' AS title,content->>'intro' AS intro FROM pc_configurations
          ORDER BY configuration_id LIMIT :limit OFFSET :offset'''),{'limit':limit,'offset':offset}).mappings().all()
    return dict(total=total,items=[dict(r) for r in rows],customer_publishable=False)

@router.get('/api/admin/pc-configurations/{identity}')
def get_configuration(identity:str):
    with engine.connect() as c: return read_configuration(c,identity)
