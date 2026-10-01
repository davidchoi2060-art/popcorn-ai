"""Read-only DB integration and stub-provider API checks. Never calls external LLM."""
import sys
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from api import admin_pc_workspace as workspace
from api.pc_configuration_copy import read_configuration, catalog_rows
from api.pc_configuration_edit import EDITABLE
from api.db import engine


def check():
    with engine.connect() as conn:
        conn.execute(text('SET TRANSACTION READ ONLY'))
        before = read_configuration(conn, 'AC11F5AEA43924DBA')
        rows = catalog_rows(conn)
        conn.rollback()
    assert next(r for r in rows if r['configuration_id']==before['configuration_id'])['description_ready']
    assert workspace.task_for(next(r for r in rows if r['configuration_id']==before['configuration_id']))['task_kind']=='review'
    app=FastAPI(); app.include_router(workspace.router)
    client=TestClient(app)
    actor=dict(operator_id=0, role='operator', name='test-only')
    request=dict(revision=before['revision'],mode='copy',instruction='설명을 쉽게 작성')
    endpoint='/api/admin/pc-configurations/'+before['configuration_id']+'/ai-proposals'
    fake=SimpleNamespace(text=json.dumps(dict(changes=[dict(field='intro',value='프로그램과 편집 소스를 두 SSD로 나눠 저장할 수 있습니다.',reason='실제 SSD 수량2 기준')],notes=['실제 성능은 별도 측정 필요']),ensure_ascii=False),provider='test-stub',model='test-stub',log_id=None)
    with patch.object(workspace,'current_operator',return_value=actor), patch.object(workspace.llm,'call',return_value=fake) as call:
        result=client.post(endpoint,json=request)
        assert result.status_code==200,result.text
        assert result.json()['revision']==before['revision']
        assert len(result.json()['changes'])==1
        source=client.post(endpoint,json=dict(request,mode='sources'))
        assert source.status_code==200,source.text
        assert call.call_count==1
        assert client.post(endpoint,json=dict(request,revision=999999)).status_code==409
        assert client.post(endpoint,json=request,headers={'sec-fetch-site':'cross-site'}).status_code==403
        call.return_value=SimpleNamespace(text='not JSON')
        assert client.post(endpoint,json=request).status_code==502
        with patch.object(workspace,'current_operator',return_value=dict(role='viewer')):
            assert client.post(endpoint,json=request).status_code==403
    with engine.connect() as conn:
        after=read_configuration(conn,before['configuration_id'])
    assert before['revision']==after['revision'] and before['content']==after['content']
    return dict(catalog_total=len(rows),tasks=len([r for r in rows if workspace.task_for(r)]),
        dual_ssd_description_ready=True,dual_ssd_task='review',
        checks=['source-only no LLM call','valid proposal','revision conflict','cross-site rejection','invalid JSON','viewer rejection','product unchanged'],
        external_llm_calls=0, writes=0)


if __name__=='__main__':
    result=check()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if len(sys.argv)>1:
        p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
