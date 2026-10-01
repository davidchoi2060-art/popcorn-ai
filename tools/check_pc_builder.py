"""Live catalog integration checks; all writes roll back and never approve a product."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from fastapi import HTTPException
from api.db import engine
from api.admin_pc_builder import Build,prepare,save_build
from api.pc_configuration_copy import read_configuration,digest


def snapshot(c):
    return {t:digest([dict(r) for r in c.execute(text('SELECT * FROM '+t+' ORDER BY 1,2')).mappings()])
        for t in ('pc_configurations','pc_configuration_parts','pc_configuration_offers','pc_configuration_history')}


with engine.connect() as c:
    before=snapshot(c);c.rollback();tx=c.begin()
    try:
        base=read_configuration(c,'N07')
        selections=[dict(code=p['explanation_code'],quantity=p['quantity']) for p in base['parts'] if not p['pseudo']]
        body=Build(title='롤백 전용 신규 구성',parts=selections,request_id='rollback-builder-20261002')
        duplicate=prepare(c,body)[0];assert duplicate['duplicate_id']
        try:save_build(c,body,{'operator_id':0})
        except HTTPException as e:assert e.status_code==409
        else:raise AssertionError('duplicate accepted')
        for s in selections:
            if s['code']==128702:s['quantity']=3
        body=Build(title='롤백 전용 신규 구성',parts=selections,request_id='rollback-builder-20261002')
        preview=prepare(c,body)[0];assert preview['can_save'] and not preview['duplicate_id']
        body.preview_token=preview['preview_token'];out=save_build(c,body,{'operator_id':0,'name':'rollback-only'})
        d=read_configuration(c,out['configuration_id'])
        assert d['status']=='review_required' and not d['current_review']['eligible']
        assert d['content']['facts']['ram_gb']==32 and d['content']['facts']['storage_gb']==3000
        assert d['offers'][0]['price_snapshot']==preview['subtotal']+30000
        assert save_build(c,body,{'operator_id':0})['reused']
        # Price changes after preview must force another preview, even within the transaction.
        with c.begin_nested() as sp:
            altered=body.model_copy(deep=True);altered.parts[3].quantity=4
            altered.request_id='rollback-price-check-20261002';altered.preview_token=prepare(c,altered)[0]['preview_token']
            c.execute(text('UPDATE products SET sale_price=sale_price+1 WHERE product_code=128702'))
            try:save_build(c,altered,{'operator_id':0})
            except HTTPException as e:assert e.status_code==409
            else:raise AssertionError('stale price accepted')
            sp.rollback()
        print('Live rollback checks: duplicate blocked, new BOM saved pending, quantity/capacity/fee correct, retry idempotent, stale price blocked.')
    finally:tx.rollback()
    assert snapshot(c)==before,'Catalog changed after rollback'
    print('Catalog/parts/offers/history unchanged after rollback.')
