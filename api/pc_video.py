"""Private, operator-triggered video editing with immutable cloud versions."""
import hashlib
import json
import logging
import os
import re
from datetime import datetime,timezone
from pathlib import Path
from typing import Literal
from uuid import UUID,uuid4
from urllib.parse import quote
from fastapi import APIRouter,BackgroundTasks,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import text
from .db import engine
from .admin_pc_builder import permission
from . import pc_media as media
from .pc_configuration_copy import digest
from . import pc_video_render as renderer

router=APIRouter()
SPOOL=Path(os.environ.get('PC_VIDEO_SPOOL',str(Path(__file__).resolve().parents[1]/'.cache'/'pc-video-spool')))
LOCK=736229410
MUSIC_NAMES=('none','hyper-ultra','hyperflight')

class Generate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    basis:str=Field(min_length=64,max_length=64)
    music:Literal['none','hyper-ultra','hyperflight']='hyper-ultra'

def snapshot(c,identity,music,lock=False):
    s=media.snapshot(c,identity,lock=lock)
    cfg=c.execute(text('SELECT content FROM pc_configurations WHERE configuration_id=:id'),dict(id=identity)).scalar_one()
    image=c.execute(text("SELECT job_id,visual_basis,asset FROM pc_media_jobs WHERE configuration_id=:id AND status='ready' AND selected"),dict(id=identity)).mappings().first()
    errors=list(s['errors'])
    if not image or image['visual_basis']!=s['visual_basis']:errors.append('현재 구성의 대표 이미지 확정 필요')
    facts={k:cfg.get('facts',{}).get(k) for k in ('cpu','gpu','ram_gb','storage_gb')}
    if any(v is None for k,v in facts.items() if k!='gpu'):errors.append('영상 표기용 CPU·메모리·저장 용량 확인 필요')
    data=dict(configuration_id=identity,title=s['title'],facts=facts,cooling=s['snapshot']['cooling'].get('method_label','냉각 구성 확인'),music=music,template=renderer.VERSION,
        image_job_id=str(image['job_id']) if image else None,image_asset=image['asset'] if image else None,
        visual_basis=s['visual_basis'])
    basis=digest(dict(review=s['basis'],data=data))
    return dict(basis=basis,snapshot=data,errors=errors)

def directory(job):return SPOOL/str(UUID(str(job)))

def list_jobs(c,identity):
    result=[]
    for row in c.execute(text('SELECT job_id,status,phase,error,basis,snapshot,created_at,updated_at FROM pc_video_jobs WHERE configuration_id=:id ORDER BY created_at DESC LIMIT 20'),dict(id=identity)).mappings():
        r=dict(row);current=snapshot(c,identity,r['snapshot']['music'])
        r['current']=r['basis']==current['basis'] and not current['errors']
        r['music']=r.pop('snapshot')['music']
        r['url']=f"/api/admin/pc-video/{identity}/files/{r['job_id']}/intro.mp4"
        r['thumb_url']=f"/api/admin/pc-video/{identity}/files/{r['job_id']}/thumb.jpg"
        r['staged_available']=(directory(r['job_id'])/'intro.mp4').is_file() and (directory(r['job_id'])/'thumb.jpg').is_file()
        r['interrupted']=(datetime.now(timezone.utc)-r['updated_at']).total_seconds()>900 and r['status']=='running'
        result.append(r)
    return result

@router.get('/api/admin/pc-video/{identity}')
def state(identity:str):
    with engine.connect() as c:
        choices={m:snapshot(c,identity,m) for m in MUSIC_NAMES}
        rows=list_jobs(c,identity)
    tracks=[dict(id=t['id'],title=t['title'],author=t['author'],license=t['license'],source=t['source']) for t in renderer.TRACKS]
    return dict(choices=choices,jobs=rows,tracks=tracks,renderer_ready=renderer.ready(),cloud_ready=media.cloud_ready(),duration=10,width=1920,height=1080,template=renderer.VERSION)

@router.post('/api/admin/pc-video/{identity}/generate',status_code=202)
def start(identity:str,body:Generate,request:Request,background:BackgroundTasks):
    actor=permission(request)
    with engine.begin() as c:
        s=snapshot(c,identity,body.music,lock=True)
        old=c.execute(text('SELECT * FROM pc_video_jobs WHERE request_id=:r'),dict(r=body.request_id)).mappings().first()
        if old:
            if old['configuration_id']!=identity or old['basis']!=body.basis:raise HTTPException(409,'재요청 내용 불일치')
            return dict(job_id=old['job_id'],reused=True)
        if s['errors']:raise HTTPException(409,' · '.join(s['errors']))
        if s['basis']!=body.basis:raise HTTPException(409,'구성·대표 이미지·설명 변경. 최신 확인 필요')
        ready=c.execute(text("SELECT job_id FROM pc_video_jobs WHERE configuration_id=:id AND basis=:b AND status='ready' ORDER BY created_at DESC LIMIT 1"),dict(id=identity,b=body.basis)).scalar()
        if ready:return dict(job_id=ready,reused=True)
        if not renderer.ready():raise HTTPException(503,'영상 렌더러·한글 글꼴·음원 확인 필요')
        if not media.cloud_ready():raise HTTPException(503,'클라우드 저장 연결 확인 필요')
        # Transaction lock serializes new requests globally on the small VM.
        c.execute(text('SELECT pg_advisory_xact_lock(:k)'),dict(k=LOCK+1))
        if c.execute(text("SELECT 1 FROM pc_video_jobs WHERE status='running' AND updated_at>now()-interval '15 minutes' LIMIT 1")).scalar():raise HTTPException(409,'다른 영상 제작 진행 중 · 완료 후 실행')
        job=uuid4()
        c.execute(text("""INSERT INTO pc_video_jobs(job_id,configuration_id,request_id,image_job_id,basis,snapshot,actor,status)
        VALUES(:j,:id,:r,:image,:b,CAST(:s AS jsonb),:a,'running')"""),dict(j=job,id=identity,r=body.request_id,image=s['snapshot']['image_job_id'],b=body.basis,s=json.dumps(s['snapshot'],ensure_ascii=False),a=str(actor['operator_id'])))
    background.add_task(work,str(job))
    return dict(job_id=job,reused=False)

def read_source(asset,job):
    key=f'pc-configurations/{job}/representative.png'
    if asset.get('bucket')!=media.MEDIA_BUCKET or asset.get('key')!=key:raise ValueError('Image path mismatch')
    with media.cloud_session() as session:
        r=session.get(f'https://storage.googleapis.com/storage/v1/b/{media.MEDIA_BUCKET}/o/{quote(key,safe="")}?alt=media',timeout=(10,30));r.raise_for_status()
    if len(r.content)>20*1024*1024 or hashlib.sha256(r.content).hexdigest()!=asset['sha256']:raise ValueError('Image checksum')
    return r.content

def upload_file(job,name,path,mime):
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    key=f'pc-configurations/{job}/videos/{name}'
    with media.cloud_session() as session:
        r=session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{media.MEDIA_BUCKET}/o',params=dict(uploadType='media',name=key,ifGenerationMatch='0'),data=raw,headers={'Content-Type':mime},timeout=(10,90))
        if r.status_code!=412:r.raise_for_status()
        # Verify the actual object bytes before declaring completion (including retries).
        r=session.get(f'https://storage.googleapis.com/storage/v1/b/{media.MEDIA_BUCKET}/o/{quote(key,safe="")}?alt=media',timeout=(10,90));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=sha:raise ValueError('Video cloud checksum')
    return dict(bucket=media.MEDIA_BUCKET,key=key,sha256=sha,size=len(raw),mime=mime)

def work(job_id,storage_only=False):
    phase='storage' if storage_only else 'render';d=directory(job_id)
    with engine.connect() as guard:
        # A stale UI job must never create overlapping ffmpeg workers.
        locked=guard.execute(text('SELECT pg_try_advisory_lock(:k)'),dict(k=LOCK)).scalar();guard.commit()
        try:
            if not locked:raise RuntimeError('Renderer busy')
            with engine.connect() as c:job=dict(c.execute(text('SELECT * FROM pc_video_jobs WHERE job_id=:j'),dict(j=job_id)).mappings().one())
            if job['status']!='running':return
            if not storage_only:
                raw=read_source(job['snapshot']['image_asset'],job['snapshot']['image_job_id'])
                d.mkdir(parents=True,exist_ok=True,mode=0o700)
                renderer.render(job['snapshot'],raw,d)
            phase='storage'
            with engine.begin() as c:c.execute(text("UPDATE pc_video_jobs SET phase='storage',updated_at=now() WHERE job_id=:j"),dict(j=job_id))
            asset=dict(video=upload_file(job_id,'intro.mp4',d/'intro.mp4','video/mp4'),thumb=upload_file(job_id,'thumb.jpg',d/'thumb.jpg','image/jpeg'),duration=10,width=1920,height=1080,template=renderer.VERSION,music=job['snapshot']['music'])
            with engine.begin() as c:c.execute(text("UPDATE pc_video_jobs SET status='ready',phase='complete',error=NULL,asset=CAST(:a AS jsonb),updated_at=now() WHERE job_id=:j"),dict(j=job_id,a=json.dumps(asset)))
            # Only our exact UUID directory; successful cloud originals remain permanent.
            try:
                for p in d.iterdir():
                    if p.is_file():p.unlink()
                d.rmdir()
            except OSError:logging.getLogger(__name__).warning('PC video local cleanup pending')
        except Exception as exc:
            logging.getLogger(__name__).warning('PC video failure phase=%s type=%s',phase,type(exc).__name__)
            with engine.begin() as c:c.execute(text("UPDATE pc_video_jobs SET status='failed',phase=:p,error=:e,updated_at=now() WHERE job_id=:j"),dict(j=job_id,p=phase,e='클라우드 저장 실패 · 저장만 재시도 가능' if phase=='storage' else '영상 제작 실패 · 자동 재호출 없음'))
        finally:
            if locked:guard.execute(text('SELECT pg_advisory_unlock(:k)'),dict(k=LOCK));guard.commit()

@router.post('/api/admin/pc-video/{identity}/retry-storage/{job_id}',status_code=202)
def retry(identity:str,job_id:UUID,request:Request,background:BackgroundTasks):
    permission(request)
    with engine.begin() as c:
        row=c.execute(text('SELECT * FROM pc_video_jobs WHERE job_id=:j AND configuration_id=:id FOR UPDATE'),dict(j=job_id,id=identity)).mappings().first()
        if not row or row['status']!='failed' or row['phase']!='storage':raise HTTPException(409,'저장 재시도 대상 없음')
        if not all((directory(job_id)/n).is_file() for n in ('intro.mp4','thumb.jpg')):raise HTTPException(409,'렌더 원본 없음 · 신규 제작 필요')
        if not media.cloud_ready():raise HTTPException(503,'클라우드 연결 확인 필요')
        c.execute(text("UPDATE pc_video_jobs SET status='running',error=NULL,updated_at=now() WHERE job_id=:j"),dict(j=job_id))
    background.add_task(work,str(job_id),True)
    return dict(job_id=job_id)

def byte_range(header,size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or not any(match.groups()):raise HTTPException(416,'지원하지 않는 범위',headers={'Content-Range':f'bytes */{size}'})
    a,b=match.groups()
    start=int(a) if a else max(0,size-int(b));end=min(size-1,int(b)) if a and b else size-1
    if (not a and int(b)==0) or start>=size or start>end:raise HTTPException(416,'범위 초과',headers={'Content-Range':f'bytes */{size}'})
    return start,end,True

@router.get('/api/admin/pc-video/{identity}/files/{job_id}/{name}')
def file(identity:str,job_id:UUID,name:str,request:Request,download:bool=False):
    if name not in ('intro.mp4','thumb.jpg'):raise HTTPException(404,'영상 파일 없음')
    with engine.connect() as c:asset=c.execute(text("SELECT asset FROM pc_video_jobs WHERE configuration_id=:id AND job_id=:j AND status='ready'"),dict(id=identity,j=job_id)).scalar()
    if not asset:raise HTTPException(404,'완료 영상 없음')
    a=asset['video' if name=='intro.mp4' else 'thumb'];key=f'pc-configurations/{job_id}/videos/{name}'
    if a.get('bucket')!=media.MEDIA_BUCKET or a.get('key')!=key:raise HTTPException(404,'파일 경로 불일치')
    try:
        with media.cloud_session() as session:
            r=session.get(f'https://storage.googleapis.com/storage/v1/b/{media.MEDIA_BUCKET}/o/{quote(key,safe="")}?alt=media',timeout=(10,60));r.raise_for_status();raw=r.content
        if len(raw)>30*1024*1024 or len(raw)!=a['size'] or hashlib.sha256(raw).hexdigest()!=a['sha256']:raise ValueError('Checksum')
    except Exception as exc:raise HTTPException(503,'클라우드 영상 조회 실패') from exc
    start,end,partial=byte_range(request.headers.get('range'),len(raw))
    headers={'Cache-Control':'private, max-age=300','X-Content-Type-Options':'nosniff','Accept-Ranges':'bytes','Content-Length':str(end-start+1)}
    if partial:headers['Content-Range']=f'bytes {start}-{end}/{len(raw)}'
    if download:headers['Content-Disposition']=f'attachment; filename="pc-{job_id}.mp4"'
    return Response(raw[start:end+1],status_code=206 if partial else 200,media_type=a['mime'],headers=headers)

@router.get('/api/admin/pc-video-music/{track}')
def music(track:str):
    if track not in renderer.MUSIC:raise HTTPException(404,'음원 없음')
    return Response(renderer.MUSIC[track]['file'].read_bytes(),media_type='audio/mp4',headers={'Cache-Control':'private, max-age=3600'})
