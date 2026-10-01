"""Representative review -> recommendation verification; all mutations roll back.
No provider calls or production approvals are retained.
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from fastapi import HTTPException
from api.db import engine
from api.pc_configuration_copy import catalog_rows, read_configuration, digest
from api.pc_configuration_edit import CopyEdit, EDITABLE, save_copy
from api.pc_configuration_review import ReviewEdit, load_review, save_review
from api.configuration_consultation import load_catalog, load_rules, Conditions, Use, match


def scenario_profile(s):
    return Conditions(uses=[Use(scenario_id=s['id'],description=s['title'],
        resolution=s.get('resolution'),target_fps=s.get('target_fps'),monitor_count=s.get('monitors'))],
        budget_won=100000000,budget_scope='body',extra_limit_won=100000000)


def check():
    actor=dict(operator_id=0,name='rollback-flow-test')
    with engine.connect() as c:
        tx=c.begin()
        try:
            c.execute(text("SET LOCAL lock_timeout='5s'"))
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
            rows=catalog_rows(c); rules=load_rules(c); baseline_catalog=load_catalog(c)
            by={r['configuration_id']:r for r in rows}
            x3d=next(r['configuration_id'] for r in rows if r['cooling_plan'].get('cpu_model')=='9800X3D')
            identities=list(dict.fromkeys(['N07','N02','P113193','N14','P112769',x3d,'P119302']))
            baseline={i:digest(read_configuration(c,i)) for i in identities}
            history=c.execute(text('SELECT count(*) FROM pc_configuration_history')).scalar()
            results=[]
            for identity in identities:
                with c.begin_nested() as sp:
                    cfg,parts,offers,state=load_review(c,identity)
                    detail=read_configuration(c,identity)
                    assert detail['current_review']['basis']==state['basis']
                    assert detail['content'].get('intro')
                    assert all(p['pseudo'] or p['explanation'].get('role') for p in detail['parts'])
                    body=ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='approve',
                        findings={k:dict(confirmed=True,evidence='흐름 검사 전용 가상 확인이며 전체 변경은 롤백됩니다.') for k in state['required']})
                    item=dict(configuration_id=identity,method=by[identity]['cooling_plan']['method'],classification=by[identity]['management_state'],required=state['required'],assembly_checks=state['assembly_checks'])
                    if state['recommendation_state']=='hold':
                        try: save_review(c,identity,body,actor)
                        except HTTPException as exc: assert exc.status_code==422
                        else: raise AssertionError('blocked configuration approved')
                        assert identity not in {p['id'] for p in load_catalog(c)}
                        item['checks']=['blocked_approval_rejected','excluded_from_recommendation']
                    else:
                        incomplete=body.model_copy(update=dict(findings={}))
                        try: save_review(c,identity,incomplete,actor)
                        except HTTPException as exc: assert exc.status_code==422
                        else: raise AssertionError('approval without evidence accepted')
                        assert save_review(c,identity,body,actor)['eligible']
                        pc=next(p for p in load_catalog(c) if p['id']==identity)
                        assert not pc['stale_parts']
                        matches=[]
                        for sid,s in rules.items():
                            outcome=match(scenario_profile(s),rules,[pc])
                            for card in outcome['candidates']:
                                assert card['configuration_id']==identity
                                offer=next(o for o in pc['offers'] if o['id']==card['offer_id'])
                                assert card['price_snapshot']==offer['price']
                                assert card['bom_fingerprint']==cfg['bom_fingerprint']
                                assert not outcome['customer_publishable']
                            if outcome['candidates']: matches.append(sid)
                        assert matches, 'no scenario matched representative '+identity
                        item['matching_scenarios']=matches
                        cfg,_,_,state=load_review(c,identity)
                        save_review(c,identity,ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='draft'),actor)
                        assert identity not in {p['id'] for p in load_catalog(c)}
                        cfg,_,_,state=load_review(c,identity)
                        save_review(c,identity,ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='approve',findings=body.findings),actor)
                        cfg,_,_,_=load_review(c,identity)
                        edit={k:cfg['content'][k] for k in EDITABLE}; edit['intro']+=' (롤백 검사)'
                        save_copy(c,identity,CopyEdit(revision=cfg['revision'],content=edit),actor)
                        assert load_review(c,identity)[3]['state']=='stale'
                        assert identity not in {p['id'] for p in load_catalog(c)}
                        item['checks']=['missing_evidence_rejected','approved_catalog_loaded','scenario_price_bom_grounded','draft_excluded','changed_copy_stales_and_excludes']
                    results.append(item)
                    sp.rollback()
            scenarios=[]
            for sid,s in rules.items():
                outcome=match(scenario_profile(s),rules,baseline_catalog)
                scenarios.append(dict(scenario_id=sid,title=s['title'],state=outcome['state'],candidates=outcome['candidates']))
            report=dict(catalog_total=len(rows),classification=dict(Counter(r['management_state'] for r in rows)),
                approval_states=dict(Counter(r.get('review_state') or 'legacy_unreviewed' for r in rows)),
                legacy_compare_catalog=len(baseline_catalog),representatives=results,scenarios=scenarios,
                scenario_states=dict(Counter(s['state'] for s in scenarios)),
                manual_groups={k:[r['configuration_id'] for r in rows if r['management_state']==k] for k in ('ready','conditional','excluded')},
                retained_approvals=0,llm_calls=0)
        finally:
            tx.rollback()
    with engine.connect() as c:
        assert all(digest(read_configuration(c,i))==baseline[i] for i in identities)
        assert c.execute(text('SELECT count(*) FROM pc_configuration_history')).scalar()==history
    report['rolled_back']=True
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=check()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('representatives','scenarios','manual_groups')},ensure_ascii=False))
