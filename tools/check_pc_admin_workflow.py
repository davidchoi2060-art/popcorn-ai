"""Exercise real admin persistence inside a rollback-only transaction."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from fastapi import HTTPException
from api.db import engine
from api.pc_configuration_copy import read_configuration, catalog_rows, digest
from api.pc_configuration_edit import CopyEdit, EDITABLE, save_copy
from api.pc_configuration_parts_edit import PartsEdit, prepare, save_parts
from api.pc_configuration_review import ReviewEdit, load_review, save_review


def check():
    passed=[]; identity='N07'; actor=dict(operator_id=0,name='rollback-admin-test')
    with engine.connect() as c:
        tx=c.begin()
        try:
            c.execute(text("SET LOCAL lock_timeout='5s'"))
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
            before=read_configuration(c,identity)
            baseline=digest(before)
            history_before=c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'),dict(id=identity)).scalar()
            cfg,parts,offers,state=load_review(c,identity)
            assert state['recommendation_state']!='hold'
            approval=ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='approve',
                findings={k:dict(confirmed=True,evidence='통합 테스트 전용 근거이며 전체 변경은 롤백됩니다.') for k in state['required']})
            assert save_review(c,identity,approval,actor)['eligible']
            assert next(r for r in catalog_rows(c) if r['configuration_id']==identity)['review_state']=='approved'
            passed.append('evidence_bound_approval')
            cfg,parts,offers,state=load_review(c,identity)
            edit={k:cfg['content'][k] for k in EDITABLE};edit['intro']+=' (롤백 검사)'
            save_copy(c,identity,CopyEdit(revision=cfg['revision'],content=edit),actor)
            assert load_review(c,identity)[3]['state']=='stale'
            try: save_copy(c,identity,CopyEdit(revision=cfg['revision'],content=edit),actor)
            except HTTPException as e: assert e.status_code==409
            else: raise AssertionError('stale write accepted')
            passed.append('description_edit_stales_approval_and_rejects_conflict')
            cfg,parts,offers,state=load_review(c,identity)
            ram=next(p for p in parts if p['slot']=='RAM' and not p['pseudo'])
            body=PartsEdit(revision=cfg['revision'],offer_id=offers[0]['offer_id'],
                replacements=[dict(ordinal=ram['ordinal'],code=ram['explanation_code'],quantity=ram['quantity']+1)])
            preview=prepare(c,identity,body)[3]
            assert preview['total']==preview['base_price']+preview['delta']
            body.preview_token=preview['preview_token']
            with c.begin_nested() as save:
                result=save_parts(c,identity,body.model_copy(update=dict(mode='new')),actor)
                assert result['configuration_id']!=identity
                assert result['detail']['status']=='review_required'
                assert not result['detail']['customer_publishable']
                save.rollback()
            result=save_parts(c,identity,body,actor)
            assert result['detail']['status']=='review_required'
            assert not result['detail']['current_review']['eligible']
            passed.append('parts_preview_update_and_new_family_require_review')
            cfg,parts,offers,state=load_review(c,identity)
            save_review(c,identity,ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='draft',note='롤백 검사'),actor)
            assert c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'),dict(id=identity)).scalar()==history_before+4
            passed.append('description_parts_review_history_preserved')
            # A price update must stale an already-open review and surface on the list.
            cfg,parts,offers,state=load_review(c,identity)
            code=c.execute(text('SELECT product_code FROM product_explanations WHERE source_product_code=:code'),dict(code=ram['explanation_code'])).scalar()
            old=c.execute(text('SELECT sale_price FROM products WHERE product_code=:code'),dict(code=code)).scalar()
            c.execute(text('UPDATE products SET sale_price=sale_price+1000 WHERE product_code=:code'),dict(code=code))
            c.execute(text("""INSERT INTO product_price_history(product_code,field,old_price,new_price,reason)
                VALUES(:code,'sale',:old,:new,'admin_rollback_test')"""),dict(code=code,old=old,new=old+1000))
            assert load_review(c,identity)[3]['basis']!=state['basis']
            listed=next(r for r in catalog_rows(c) if r['configuration_id']==identity)
            assert any(a['kind']=='price_history' for a in listed['market_alerts'])
            assert listed['needs_review']
            c.execute(text("UPDATE products SET status='품절' WHERE product_code=:code"),dict(code=code))
            listed=next(r for r in catalog_rows(c) if r['configuration_id']==identity)
            assert listed['management_state']=='excluded'
            assert any(a['kind']=='sale' for a in listed['market_alerts'])
            passed.append('price_and_sale_change_alerts_and_stale_review')
        finally:
            tx.rollback()
    with engine.connect() as c:
        assert digest(read_configuration(c,identity))==baseline
        assert c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'),dict(id=identity)).scalar()==history_before
    return dict(passed=passed,rolled_back=True)


if __name__=='__main__': print(json.dumps(check(),ensure_ascii=False))
