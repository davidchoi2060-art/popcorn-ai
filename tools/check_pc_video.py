"""Real DB rollback: gating, reuse, stale image, durable storage retry, no catalog mutation."""
import json,sys,tempfile
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from starlette.requests import Request
from fastapi import BackgroundTasks,HTTPException
from api import pc_video as v
from api.db import engine
class Bound:
    def __init__(self,c):self.c=c
    @contextmanager
    def connect(self):yield self.c
    @contextmanager
    def begin(self):yield self.c
request=Request({'type':'http','headers':[(b'sec-fetch-site',b'same-origin')]})
with engine.connect() as c:
    tx=c.begin()
    try:
        before=c.execute(text("SELECT md5(string_agg(row_to_json(x)::text,'' ORDER BY configuration_id)) FROM pc_configurations x")).scalar()
        with patch.object(v,'engine',Bound(c)),patch.object(v,'permission',return_value={'operator_id':1}),patch.object(v.media,'cloud_ready',return_value=True),patch.object(v.renderer,'ready',return_value=True),tempfile.TemporaryDirectory() as temp,patch.object(v,'SPOOL',Path(temp)):
            s=v.snapshot(c,'N07','none');assert not s['errors'],s['errors']
            b=v.Generate(request_id=uuid4(),basis=s['basis'],music='none')
            job=v.start('N07',b,request,BackgroundTasks());assert v.start('N07',b,request,BackgroundTasks())['reused']
            try:v.start('N07',v.Generate(request_id=uuid4(),basis=s['basis'],music='none'),request,BackgroundTasks());raise AssertionError('Concurrent render')
            except HTTPException as e:assert e.status_code==409
            # Simulated upload failure retains filesystem originals; retry has no render call.
            d=v.directory(job['job_id']);d.mkdir();(d/'intro.mp4').write_bytes(b'video');(d/'thumb.jpg').write_bytes(b'thumb')
            c.execute(text("UPDATE pc_video_jobs SET status='failed',phase='storage' WHERE job_id=:j"),dict(j=job['job_id']))
            bg=BackgroundTasks();v.retry('N07',job['job_id'],request,bg);assert len(bg.tasks)==1 and bg.tasks[0].args[1] is True
            c.execute(text("UPDATE pc_video_jobs SET status='ready',phase='complete',asset=CAST(:a AS jsonb) WHERE job_id=:j"),dict(j=job['job_id'],a=json.dumps({'duration':10})))
            assert v.start('N07',v.Generate(request_id=uuid4(),basis=s['basis'],music='none'),request,BackgroundTasks())['reused']
            c.execute(text("UPDATE pc_configurations SET content=jsonb_set(content,'{title}',to_jsonb('changed'::text)) WHERE configuration_id='N07'"))
            assert not v.list_jobs(c,'N07')[0]['current']
            c.execute(text("UPDATE pc_configurations SET content=jsonb_set(content,'{title}',to_jsonb(:title::text)) WHERE configuration_id='N07'".replace(':title::text','CAST(:title AS text)')),dict(title=s['snapshot']['title']))
            c.execute(text("UPDATE pc_media_jobs SET selected=false WHERE configuration_id='N07' AND selected"))
            assert '현재 구성의 대표 이미지 확정 필요' in v.snapshot(c,'N07','none')['errors']
            assert c.execute(text("SELECT md5(string_agg(row_to_json(x)::text,'' ORDER BY configuration_id)) FROM pc_configurations x")).scalar()==before
            print('PASS real DB rollback: gate, idempotency, concurrent block, reusable render, storage-only retry, stale text/image, unchanged catalog')
    finally:tx.rollback()
