"""Real DB rollback, simulated provider/cloud: zero generation spend or catalog mutation."""
import io,json,sys,tempfile
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import BackgroundTasks,HTTPException
from starlette.requests import Request
from sqlalchemy import text
from PIL import Image
from api import pc_media as m
from api.db import engine
from api.pc_configuration_copy import catalog_rows,read_configuration

class Bound:
    def __init__(self,c):self.c=c
    @contextmanager
    def begin(self):yield self.c
    @contextmanager
    def connect(self):yield self.c

raw=io.BytesIO();Image.new('RGB',(8,8),'white').save(raw,'PNG');raw=raw.getvalue()
request=Request({'type':'http','headers':[(b'sec-fetch-site',b'same-origin')]})
with engine.connect() as c:
    transaction=c.begin()
    try:
        before=c.execute(text("SELECT md5(string_agg(row_to_json(x)::text,'' ORDER BY configuration_id)) FROM pc_configurations x")).scalar()
        count=c.execute(text('SELECT count(*) FROM pc_media_jobs')).scalar()
        with tempfile.TemporaryDirectory() as temp,patch.object(m,'engine',Bound(c)),patch.object(m,'permission',return_value={'operator_id':1}),patch.object(m,'cloud_ready',return_value=True),patch.object(m,'SPOOL',Path(temp)),patch.object(m,'generate_image',return_value=raw) as generate,patch.object(m,'upload',side_effect=lambda job,data:dict(bucket=m.MEDIA_BUCKET,key=f"pc-configurations/{job['job_id']}/representative.png",sha256=m.hashlib.sha256(data).hexdigest(),notice=m.NOTICE)) as upload:
            s=m.state('N07');assert not s['errors'],s['errors']
            body=m.Generate(request_id=uuid4(),basis=s['basis']);bg=BackgroundTasks()
            started=m.start('N07',body,request,bg);job=str(started['job_id'])
            assert m.start('N07',body,request,BackgroundTasks())['reused']
            try:m.start('N07',m.Generate(request_id=uuid4(),basis=s['basis']),request,BackgroundTasks());raise AssertionError('Concurrent cost allowed')
            except HTTPException as e:assert e.status_code==409
            m.work(job);assert generate.call_count==1 and upload.call_count==1
            m.select('N07',m.Choose(job_id=job,visual_basis=s['visual_basis']),request)
            assert m.state('N07')['jobs'][0]['selected']
            assert read_configuration(c,'N07')['representative_image_url']
            assert next(r for r in catalog_rows(c) if r['configuration_id']=='N07')['image_caption']=='AI 조립 예시 이미지'
            assert c.execute(text("SELECT md5(string_agg(row_to_json(x)::text,'' ORDER BY configuration_id)) FROM pc_configurations x")).scalar()==before
            second=m.start('N07',m.Generate(request_id=uuid4(),basis=s['basis']),request,BackgroundTasks())
            second_id=str(second['job_id'])
            with patch.object(m,'upload',side_effect=RuntimeError('storage offline')):m.work(second_id)
            staged=c.execute(text('SELECT status,staged_png FROM pc_media_jobs WHERE job_id=:j'),dict(j=second_id)).mappings().one()
            assert staged['status']=='failed' and bytes(staged['staged_png'])==raw
            generated_count=generate.call_count
            m.retry_storage('N07',second['job_id'],request,BackgroundTasks())
            m.work(second_id,True)
            assert generate.call_count==generated_count
            ready=c.execute(text('SELECT status,staged_png FROM pc_media_jobs WHERE job_id=:j'),dict(j=second_id)).mappings().one()
            assert ready['status']=='ready' and ready['staged_png'] is None
            print('PASS durable bytes: upload failure keeps DB original; storage retry never invokes generator')
            c.execute(text("UPDATE pc_configuration_parts SET quantity=2 WHERE configuration_id='N07' AND slot='SSD'"))
            assert not m.state('N07')['jobs'][0]['current']
            assert not read_configuration(c,'N07')['representative_image_url']
            try:m.select('N07',m.Choose(job_id=job,visual_basis=s['visual_basis']),request);raise AssertionError('Stale selection')
            except HTTPException as e:assert e.status_code==409
            print('PASS real DB: idempotence, concurrency, job ready, representative selection/list/detail, stale blocking; provider/cloud mocked')
    finally:transaction.rollback()
    assert c.execute(text('SELECT count(*) FROM pc_media_jobs')).scalar()==count
    assert c.execute(text("SELECT md5(string_agg(row_to_json(x)::text,'' ORDER BY configuration_id)) FROM pc_configurations x")).scalar()==before
    print('PASS rollback: catalog and jobs unchanged; zero paid API calls')
