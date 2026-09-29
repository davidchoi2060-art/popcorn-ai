"""Exercise 0119 constraints in a rolled-back transaction; no test quotes persist."""
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from alembic.migration import MigrationContext
from alembic.operations import Operations
from api.db import engine


def check():
    spec = importlib.util.spec_from_file_location('schema_0119', ROOT / 'db/migrations/versions/0119_pc_quote_changes.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    passed = []
    with engine.connect() as c:
        tx = c.begin()
        try:
            if not c.execute(text("SELECT to_regclass('public.pc_customer_quotes')")).scalar():
                with Operations.context(MigrationContext.configure(c)):
                    migration.upgrade()

            def sql(statement, **params):
                return c.execute(text(statement), params)

            def rejected(name, statement, **params):
                save = c.begin_nested()
                try:
                    sql(statement, **params)
                except DBAPIError:
                    save.rollback()
                    passed.append(name)
                else:
                    save.rollback()
                    raise AssertionError(name + ': unexpectedly accepted')

            sid = sql('SELECT session_id FROM consult_sessions ORDER BY session_id LIMIT 1').scalar()
            cfg = sql('SELECT configuration_id FROM pc_configurations ORDER BY configuration_id LIMIT 1').scalar()
            assert sid is not None and cfg is not None, 'Existing session/catalog required; test will not create a real customer'
            q, change, validation, confirm = [str(uuid4()) for _ in range(4)]
            before = json.dumps([{'line_key': 'RAM', 'slot': 'RAM', 'source_code': 'schema-test', 'quantity': 1}])
            after = json.dumps([{'line_key': 'RAM', 'slot': 'RAM', 'source_code': 'schema-test', 'quantity': 2}])
            origin = '{"test_only":true}'
            basis = '{"method":"schema-test","source_ref":"rollback-only"}'
            sql('''INSERT INTO pc_customer_quotes(quote_id,session_id,configuration_id,configuration_revision,origin_snapshot)
                VALUES(:q,:sid,:cfg,1,CAST(:origin AS jsonb))''', q=q,sid=sid,cfg=cfg,origin=origin)
            version_insert = '''INSERT INTO pc_quote_versions(quote_id,version,bom,bom_fingerprint,conditions,total_amount,assembly_fee_included,price_basis)
                VALUES(:q,:v,CAST(:bom AS jsonb),:fp,'{}',:total,true,CAST(:basis AS jsonb))'''
            sql(version_insert,q=q,v=1,bom=before,fp='a'*64,total=1000,basis=basis)
            sql('UPDATE pc_customer_quotes SET current_version=1 WHERE quote_id=:q',q=q)
            set_insert = '''INSERT INTO pc_change_sets(change_set_id,quote_id,base_version,idempotency_key) VALUES(:s,:q,1,:k)'''
            sql(set_insert,s=change,q=q,k=str(uuid4()))
            rejected('one_active_draft',set_insert,s=str(uuid4()),q=q,k=str(uuid4()))
            revision_insert = '''INSERT INTO pc_change_revisions(change_set_id,revision,request_summary,bom,bom_fingerprint,price_status,base_total,delta_amount,total_amount,price_basis)
                VALUES(:s,:r,'schema test',CAST(:bom AS jsonb),:fp,'confirmed',1000,100,:total,CAST(:basis AS jsonb))'''
            rejected('total_must_match_delta',revision_insert,s=change,r=1,bom=after,fp='b'*64,total=1200,basis=basis)
            sql(revision_insert,s=change,r=1,bom=after,fp='b'*64,total=1100,basis=basis)
            item_insert = '''INSERT INTO pc_change_items(change_set_id,revision,line_key,slot,operation,before_parts,after_parts,reason)
                VALUES(:s,1,:key,:slot,'replace',CAST(:old AS jsonb),CAST(:new AS jsonb),'schema test')'''
            rejected('replacement_needs_both_sides',item_insert,s=change,key='RAM',slot='RAM',old='[]',new=after)
            sql(item_insert,s=change,key='RAM',slot='RAM',old=before,new=after)
            sql(item_insert,s=change,key='SSD',slot='SSD',old=before,new=after)
            sql('UPDATE pc_change_sets SET current_revision=1 WHERE change_set_id=:s',s=change)
            rejected('no_late_item_in_published_revision',item_insert,s=change,key='GPU',slot='GPU',old=before,new=after)
            rejected('immutable_quote_version','UPDATE pc_quote_versions SET total_amount=5 WHERE quote_id=:q',q=q)
            rejected('immutable_preview','UPDATE pc_change_revisions SET total_amount=5 WHERE change_set_id=:s',s=change)
            # A new revision can remove just one requested change; revision 1 stays intact.
            sql(revision_insert,s=change,r=2,bom=after,fp='b'*64,total=1100,basis=basis)
            sql(item_insert.replace(':s,1,', ':s,2,'),s=change,key='SSD',slot='SSD',old=before,new=after)
            sql('UPDATE pc_change_sets SET current_revision=2 WHERE change_set_id=:s',s=change)
            counts = sql('SELECT revision,count(*) FROM pc_change_items WHERE change_set_id=:s GROUP BY revision ORDER BY revision',s=change).all()
            assert counts == [(1,2),(2,1)]
            passed.append('individual_cancel_preserves_previous_revision')
            sql(version_insert,q=q,v=2,bom=after,fp='b'*64,total=1100,basis=basis)
            validation_insert = '''INSERT INTO pc_change_validations(validation_id,change_set_id,revision,bom_fingerprint,compatibility,sale_status,pricing,intent_match,rule_version,inputs_hash,findings,checked_at,expires_at)
                VALUES(:v,:s,:r,:fp,:compat,'pass','pass','pass','test',:hash,'{}',now()-interval '2 hours',now()+CAST(:expiry AS interval))'''
            apply = '''UPDATE pc_change_sets SET status='applied',applied_version=2,validation_id=:v WHERE change_set_id=:s'''
            for name, rev, compatibility, expiry, fingerprint in [
                ('old_revision_rejected',1,'pass','1 hour','b'*64),
                ('unknown_compatibility_rejected',2,'unknown','1 hour','b'*64),
                ('expired_checks_rejected',2,'pass','-1 hour','b'*64),
                ('different_bom_rejected',2,'pass','1 hour','c'*64),
            ]:
                v = str(uuid4())
                sql(validation_insert,v=v,s=change,r=rev,fp=fingerprint,compat=compatibility,hash='d'*64,expiry=expiry)
                rejected(name,apply,s=change,v=v)
            sql(validation_insert,v=validation,s=change,r=2,fp='b'*64,compat='pass',hash='d'*64,expiry='1 hour')
            sql(apply,s=change,v=validation)
            assert sql('SELECT current_version FROM pc_customer_quotes WHERE quote_id=:q',q=q).scalar() == 2
            passed.append('atomic_apply_moves_current_version')
            rejected('terminal_change_immutable','UPDATE pc_change_sets SET status=\'draft\' WHERE change_set_id=:s',s=change)
            assert sql('SELECT count(*) FROM pc_catalog_submissions WHERE confirmation_id=:id',id=confirm).scalar() == 0
            passed.append('change_application_is_not_quote_confirmation')
            confirmation_insert = '''INSERT INTO pc_quote_confirmations(confirmation_id,quote_id,version,confirmed_by) VALUES(:id,:q,:v,'rollback-test')'''
            rejected('old_quote_cannot_be_confirmed',confirmation_insert,id=str(uuid4()),q=q,v=1)
            sql(confirmation_insert,id=confirm,q=q,v=2)
            submission = sql('SELECT status,bom_fingerprint FROM pc_catalog_submissions WHERE confirmation_id=:id',id=confirm).one()
            assert submission == ('pending','b'*64)
            passed.append('final_confirmation_enqueues_catalog_registration')
            rejected('cannot_link_unrelated_catalog_bom',
                "UPDATE pc_catalog_submissions SET status='linked',configuration_id=:cfg WHERE confirmation_id=:id",cfg=cfg,id=confirm)
            rejected('confirmation_is_idempotent_per_version',confirmation_insert,id=str(uuid4()),q=q,v=2)
            rejected('confirmation_history_immutable','DELETE FROM pc_quote_confirmations WHERE confirmation_id=:id',id=confirm)
        finally:
            tx.rollback()
    return {'passed': passed, 'count':len(passed), 'test_data':'rolled_back'}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
