"""Actual database integration check, always rolled back; no real customer changes."""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from fastapi import HTTPException
from api.db import engine
from api.pc_quote_assembly import Action, Contact, Apply, record, contact, apply_change, load, unresolved


def check():
    passed=[]
    with engine.connect() as c:
        tx=c.begin()
        try:
            def sql(statement,**p): return c.execute(text(statement),p)
            def denied(name,fn):
                with c.begin_nested() as save:
                    try: fn()
                    except HTTPException as exc:
                        assert exc.status_code in (409,422);passed.append(name)
                    else: raise AssertionError(name+' unexpectedly accepted')
                    save.rollback()
            sid=sql('SELECT session_id FROM consult_sessions ORDER BY session_id LIMIT 1').scalar()
            cfg=sql('SELECT configuration_id FROM pc_configurations ORDER BY configuration_id LIMIT 1').scalar()
            assert sid and cfg
            q,s,k=uuid4(),uuid4(),uuid4(); actor=dict(operator_id=0,name='rollback-test')
            sql('''INSERT INTO pc_customer_quotes(quote_id,session_id,configuration_id,configuration_revision,origin_snapshot)
                 VALUES(:q,:sid,:cfg,1,'{"test_only": true}')''',q=str(q),sid=sid,cfg=cfg)
            sql('''INSERT INTO pc_quote_versions(quote_id,version,bom,bom_fingerprint,conditions,total_amount,assembly_fee_included,price_basis)
                 VALUES(:q,1,'[{"slot":"RAM","test_only": true}]',:fp,'{}',1000,true,'{"test_only": true}')''',q=str(q),fp='a'*64)
            sql('UPDATE pc_customer_quotes SET current_version=1 WHERE quote_id=:q',q=str(q))
            sql('INSERT INTO pc_quote_confirmations(confirmation_id,quote_id,version,confirmed_by) VALUES(:id,:q,1,\'rollback-test\')',id=str(uuid4()),q=str(q))
            sql('INSERT INTO pc_change_sets(change_set_id,quote_id,base_version,idempotency_key) VALUES(:s,:q,1,:k)',s=str(s),q=str(q),k=str(k))
            sql('''INSERT INTO pc_change_revisions(change_set_id,revision,request_summary,bom,bom_fingerprint,price_status,base_total,delta_amount,total_amount,price_basis)
                VALUES(:s,1,'rollback test','[{"slot":"RAM","test_only":"replacement"}]',:fp,'confirmed',1000,100,1100,'{"test_only": true}')''',s=str(s),fp='b'*64)
            sql('UPDATE pc_change_sets SET current_revision=1 WHERE change_set_id=:s',s=str(s))
            checkid=uuid4()
            sql('''INSERT INTO pc_change_validations(validation_id,change_set_id,revision,bom_fingerprint,compatibility,sale_status,pricing,intent_match,rule_version,inputs_hash,findings,expires_at)
                VALUES(:v,:s,1,:fp,'pass','pass','pass','pass','rollback-test',:h,'{"test_only": true}',now()+interval '10 minutes')''',v=str(checkid),s=str(s),fp='b'*64,h='c'*64)
            apply=Apply(version=1,change_set_id=s,revision=1,validation_id=checkid)
            denied('no_consent_no_apply',lambda:apply_change(c,q,apply,actor))
            args=dict(version=1,change_set_id=s,revision=1,contacted_at=datetime.now(timezone.utc)-timedelta(minutes=1),summary='테스트 전화 응답 내용 기록입니다',impacts='테스트 금액 차이와 사양 변경 영향입니다')
            contact(c,q,Contact(**args,decision='no_response'),actor)
            denied('no_response_no_apply',lambda:apply_change(c,q,apply,actor))
            denied('pending_change_blocks_verify',lambda:record(c,q,Action(version=1,action='verify',note='테스트 실제 검사 결과 기록입니다'),actor))
            record(c,q,Action(version=1,action='issue',note='테스트 조립 중 장착 문제가 발생했습니다'),actor)
            contact(c,q,Contact(**args,decision='agreed'),actor)
            denied('wrong_proposal_revision',lambda:apply_change(c,q,Apply(**(apply.model_dump()|dict(revision=2))),actor))
            apply_change(c,q,apply,actor)
            current,version,events=load(c,q)
            assert current['current_version']==2 and version['total_amount']==1100
            assert sql('SELECT total_amount FROM pc_quote_versions WHERE quote_id=:q AND version=1',q=str(q)).scalar()==1000
            passed.append('new_version_only_original_preserved')
            denied('issue_blocks_verify',lambda:record(c,q,Action(version=2,action='verify',note='테스트 실제 검사 결과 기록입니다'),actor))
            issue=unresolved(events)[0]
            record(c,q,Action(version=2,action='resolve',issue_id=issue['event_id'],note='테스트 대체 부품 장착과 재확인을 완료했습니다'),actor)
            record(c,q,Action(version=2,action='verify',note='테스트 부팅 인식 부하 온도 검사를 완료했습니다'),actor)
            passed.append('issue_resolution_then_reinspection')
            assert sql('SELECT count(*) FROM pc_quote_confirmations WHERE quote_id=:q',q=str(q)).scalar()==2
            passed.append('customer_confirmed_replacement_catalog_pending')
        finally: tx.rollback()
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM pc_customer_quotes WHERE quote_id=:q'),dict(q=str(q))).scalar()==0
    return dict(passed=passed,rolled_back=True)


if __name__=='__main__': print(json.dumps(check(),ensure_ascii=False))
