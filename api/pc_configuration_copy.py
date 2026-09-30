"""Admin-only BOM copy reads; no public recommendation or price authority."""
import hashlib
import json
from io import BytesIO
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from .db import engine
from .part_explanations import is_current
from .taxonomy import SLOT_LABELS
from .pc_catalog_review_snapshot import review_snapshot

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
            row=conn.execute(text('''SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status,p.sale_price
              FROM product_explanations e LEFT JOIN products p ON p.product_code=e.product_code
              WHERE e.source_product_code=:code'''),{'code':p['explanation_code']}).mappings().first()
            p['explanation']=row['content'] if row else {}
            p['image_url']=f"/api/product-images/{p['explanation_code']}/detail"
            p['sale_status']=row['sale_status'] if row else None
            p['current_unit_price']=row['sale_price'] if row else None
        p['slot_label']=SLOT_LABELS.get(p['slot'],p['slot'])
        p['needs_review']=part_needs_review(p,row)
        if part_needs_review(p,row): affected.append(p['source_code'])
    offers=[dict(o) for o in conn.execute(text('SELECT * FROM pc_configuration_offers WHERE configuration_id=:id ORDER BY price_snapshot,offer_id'),{'id':identity}).mappings()]
    from .pc_configuration_review import load_review
    workflow=load_review(conn,identity)[3] if r['content'].get('_review') else None
    return dict(r,review_workflow=workflow,parts=parts,offers=offers,needs_review=(bool(workflow) and not workflow['eligible']) or bool(affected) or bool(r['content'].get('_admin_bom_edit',{}).get('review_required')),affected_parts=affected,
                compatibility_display=review_snapshot(identity,parts),
                customer_publishable=False,price_is_snapshot=True)

def catalog_rows(conn):
    """Bulk read once; evaluate the same source-review rule used by detail reads."""
    rows=conn.execute(text('SELECT * FROM pc_configurations ORDER BY configuration_id')).mappings().all()
    parts=conn.execute(text('SELECT * FROM pc_configuration_parts ORDER BY configuration_id,ordinal')).mappings().all()
    explanations={r['source_product_code']:r for r in conn.execute(text('''
      SELECT e.*,p.product_name,p.spec_source_text,p.status AS sale_status
      FROM product_explanations e LEFT JOIN products p ON p.product_code=e.product_code
      WHERE EXISTS (SELECT 1 FROM pc_configuration_parts b WHERE b.explanation_code=e.source_product_code)
    ''')).mappings()}
    offers={}
    for o in conn.execute(text('SELECT * FROM pc_configuration_offers ORDER BY price_snapshot,offer_id')).mappings():
        offers.setdefault(o['configuration_id'],[]).append(dict(o))
    by_pc={}
    for p in parts: by_pc.setdefault(p['configuration_id'],[]).append(p)
    result=[]
    for r in rows:
        content=r['content']; bom=by_pc.get(r['configuration_id'],[])
        from .pc_configuration_review import load_review
        workflow=load_review(conn,r['configuration_id'])[3] if content.get('_review') else None
        affected=[p['source_code'] for p in bom if part_needs_review(p,explanations.get(p['explanation_code']))]
        case=next((p for p in bom if p['slot']=='CASE' and not p['pseudo']),None)
        offer_list=offers.get(r['configuration_id'],[])
        offer=offer_list[0] if offer_list else None
        description_ready=not content.get('_admin_bom_edit',{}).get('review_required') and bool(content.get('title') and content.get('intro') and bom) and all(
            p['pseudo'] or bool(explanations.get(p['explanation_code'],{}).get('content',{}).get('role')) for p in bom)
        result.append(dict(configuration_id=r['configuration_id'],bom_fingerprint=r['bom_fingerprint'],
            revision=r['revision'],status=r['status'],observed_date=r['observed_date'],
            title=content.get('title',''),intro=content.get('intro',''),facts=content.get('facts',{}),
            source=content.get('source',''),price=offer['price_snapshot'] if offer else None,
            price_note=offer['payload'].get('price_note','') if offer else '',offer_count=len(offer_list),
            image_url=f"/api/product-images/{case['explanation_code']}/detail" if case else None,
            image_caption='케이스 이미지',part_count=len(bom),description_ready=description_ready,
            review_state=workflow['state'] if workflow else None,
            needs_review=bool(affected) or not description_ready or (bool(workflow) and not workflow['eligible']),affected_parts=affected,
            customer_publishable=False,price_is_snapshot=True))
    return result


def filter_rows(rows,q='',source='',review='',visibility=''):
    needle=q.strip().casefold()
    return [r for r in rows if
        (not needle or needle in ' '.join([r['configuration_id'],r['title'],
          *[str(v) for v in r['facts'].values()]]).casefold())
        and (not source or r['source']==source)
        and (not review or r['needs_review']==(review=='needs_review'))
        and (not visibility or r['customer_publishable']==(visibility=='public'))]


@router.get('/api/admin/pc-configurations')
def list_configurations(offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=104),
        q:str=Query('',max_length=100),source:str=Query('',pattern='^(|신규|기존)$'),
        review:str=Query('',pattern='^(|needs_review|ready)$'),visibility:str=Query('',pattern='^(|public|private)$')):
    with engine.connect() as c: all_rows=catalog_rows(c)
    rows=filter_rows(all_rows,q,source,review,visibility)
    return dict(total=len(rows),catalog_total=len(all_rows),offset=offset,limit=limit,
                items=rows[offset:offset+limit],customer_publishable=False)


def export_workbook(rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb=Workbook(); ws=wb.active; ws.title='조립PC 제품군'
    ws.append(['구성 ID','상품명','등록 출처','CPU','GPU','메모리(GB)','저장장치(GB)',
               '기준 가격(원)','가격 기준일','가격 안내','상품 설명','정보 검토','고객 공개'])
    for r in rows:
        f=r['facts']
        values=[r['configuration_id'],r['title'],r['source'],f.get('cpu'),f.get('gpu'),
                f.get('ram_gb'),f.get('storage_gb'),r['price'],str(r['observed_date']),r['price_note'],
                '설명 등록' if r['description_ready'] else '설명 보완 필요',
                '확인 필요' if r['needs_review'] else '정보 변경 없음','비공개']
        ws.append(values)
        # Catalog text is untrusted. Never let a name turn into an Excel formula.
        for cell in ws[ws.max_row]:
            if isinstance(cell.value,str): cell.data_type='s'
    ws.freeze_panes='C2'; ws.auto_filter.ref=ws.dimensions
    for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='186953')
    for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=min(60,max(16,max(len(str(c.value or '')) for c in col)+2))
    for row in ws.iter_rows(min_row=2,min_col=8,max_col=8): row[0].number_format='#,##0'
    buffer=BytesIO(); wb.save(buffer); return buffer.getvalue()


@router.get('/api/admin/pc-configurations/export.xlsx')
def export_configurations(q:str=Query('',max_length=100),source:str=Query('',pattern='^(|신규|기존)$'),
        review:str=Query('',pattern='^(|needs_review|ready)$'),visibility:str=Query('',pattern='^(|public|private)$')):
    with engine.connect() as c: rows=filter_rows(catalog_rows(c),q,source,review,visibility)
    return Response(export_workbook(rows),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':'attachment; filename="pc-configurations.xlsx"','Cache-Control':'no-store'})

@router.get('/api/admin/pc-configurations/{identity}')
def get_configuration(identity:str):
    with engine.connect() as c: return read_configuration(c,identity)
