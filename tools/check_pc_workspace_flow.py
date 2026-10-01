"""Three real catalog products: live AI proposals, rollback-only persistence.

LLM usage logs remain; all catalog writes and test approvals roll back.
No real review finding is asserted by the simulated approval branch.
"""
import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from api import admin_pc_workspace as workspace
from api.db import engine
from api.pc_configuration_copy import read_configuration, catalog_rows, digest
from api.pc_configuration_edit import CopyEdit, EDITABLE, save_copy
from api.pc_configuration_review import ReviewEdit, load_review, save_review


def check(output):
    identities = ['AC11F5AEA43924DBA', 'N07', 'P119302']
    actor = dict(operator_id=0, role='operator', name='rollback-only-workspace-test')
    app = FastAPI()
    app.include_router(workspace.router)
    client = TestClient(app)
    proposals = {}
    with engine.connect() as c:
        baseline = {i: read_configuration(c, i) for i in identities}
        histories = {i: c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'), dict(id=i)).scalar() for i in identities}
    output.mkdir(parents=True, exist_ok=True)
    for identity in identities:
        mode = 'review' if identity == 'P119302' else 'copy'
        with patch.object(workspace, 'current_operator', return_value=actor):
            response = client.post(f'/api/admin/pc-configurations/{identity}/ai-proposals', json=dict(
                revision=baseline[identity]['revision'], mode=mode,
                instruction='상품 소개(intro) 한 항목만 쉽게 다듬어 주세요. 구성에 없는 기능과 성능 수치를 쓰지 마세요.' if mode == 'copy' else '등록된 쿨러 소켓 불일치 사유와 사람이 확인할 자료를 설명해주세요. 승인 판단은 하지 마세요.'))
            assert response.status_code == 200, response.text
            proposals[identity] = response.json()
            sources = client.post(f'/api/admin/pc-configurations/{identity}/ai-proposals', json=dict(revision=baseline[identity]['revision'], mode='sources'))
            assert sources.status_code == 200, sources.text
            assert len(sources.json()['sources']) == len([p for p in baseline[identity]['parts'] if not p['pseudo']])
        (output / f'{identity}-proposal.json').write_text(json.dumps(proposals[identity], ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(product=identity, mode=mode, fields=[p['field'] for p in proposals[identity]['changes']], log_id=proposals[identity].get('log_id')), ensure_ascii=False), flush=True)
    results = []
    with engine.connect() as c:
        tx = c.begin()
        try:
            c.execute(text("SET LOCAL lock_timeout='5s'"))
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext('pc_configuration_copy'))"))
            for identity in identities:
                with c.begin_nested() as sp:
                    before = read_configuration(c, identity)
                    assert digest(before) == digest(baseline[identity]), 'catalog changed during AI generation'
                    proposal = proposals[identity]
                    cfg, _, _, state = load_review(c, identity)
                    checks = ['proposal_did_not_write_catalog', 'registered_sources_complete']
                    if identity == 'P119302':
                        assert not proposal['changes']
                        assert state['recommendation_state'] == 'hold' and state['blockers']
                        try:
                            save_review(c, identity, ReviewEdit(revision=cfg['revision'], basis=state['basis'], action='approve'), actor)
                        except HTTPException as exc:
                            assert exc.status_code == 422
                        else:
                            raise AssertionError('incompatible product approved')
                        checks += ['review_ai_no_copy_patch', 'known_conflict_blocks_approval']
                    else:
                        assert proposal['changes'], 'live copy proposal empty'
                        edit = {k: cfg['content'][k] for k in EDITABLE}
                        # Any single checkbox can be saved independently.
                        first = proposal['changes'][0]
                        edit[first['field']] = first['value']
                        body = CopyEdit(revision=cfg['revision'], content=edit)
                        result = save_copy(c, identity, body, actor)
                        assert result['changed'], 'AI proposed identical copy'
                        after = read_configuration(c, identity)
                        assert after['revision'] == before['revision'] + 1
                        assert after['parts'] == before['parts'] and after['offers'] == before['offers']
                        assert after['content']['facts'] == before['content']['facts']
                        assert c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'),dict(id=identity)).scalar() == histories[identity] + 1
                        try:
                            save_copy(c, identity, body, actor)
                        except HTTPException as exc:
                            assert exc.status_code == 409
                        else:
                            raise AssertionError('stale revision accepted')
                        checks += ['selected_patch_saved', 'revision_incremented', 'history_recorded', 'bom_price_facts_unchanged', 'stale_save_rejected']
                        cfg, _, _, state = load_review(c, identity)
                        assert not state['eligible']
                        draft = save_review(c, identity, ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='draft',note='Rollback-only workflow check; not a real review.'), actor)
                        assert not draft['eligible']
                        checks.append('review_draft_not_approved')
                        cfg, _, _, state = load_review(c, identity)
                        if state['recommendation_state'] != 'hold':
                            findings = {k: dict(confirmed=True,evidence='흐름 시험용 가상 확인입니다. 실제 검수 근거가 아니며 전량 롤백합니다.') for k in state['required']}
                            assert save_review(c,identity,ReviewEdit(revision=cfg['revision'],basis=state['basis'],action='approve',findings=findings),actor)['eligible']
                            assert workspace.task_for(next(r for r in catalog_rows(c) if r['configuration_id']==identity)) is None
                            cfg, _, _, state = load_review(c,identity)
                            edit = {k:cfg['content'][k] for k in EDITABLE}
                            edit['intro'] += ' (rollback test)'
                            save_copy(c,identity,CopyEdit(revision=cfg['revision'],content=edit),actor)
                            current = load_review(c,identity)[3]
                            assert current['state']=='stale' and not current['eligible']
                            assert workspace.task_for(next(r for r in catalog_rows(c) if r['configuration_id']==identity))['task_kind']=='review'
                            checks += ['simulated_approval_removes_task', 'later_copy_change_invalidates_review_and_restores_task']
                    results.append(dict(configuration_id=identity,checks=checks,notes=proposal['notes'],log_id=proposal.get('log_id')))
                    sp.rollback()
        finally:
            tx.rollback()
    with engine.connect() as c:
        for identity in identities:
            assert digest(read_configuration(c,identity))==digest(baseline[identity])
            assert c.execute(text('SELECT count(*) FROM pc_configuration_history WHERE configuration_id=:id'),dict(id=identity)).scalar()==histories[identity]
    report=dict(products=results, live_llm_calls=3, catalog_mutations_retained=0, approval_mutations_retained=0, histories_unchanged=True, rolled_back=True, production_authenticated_ui='pending login')
    (output/'flow-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    check(parser.parse_args().output)
