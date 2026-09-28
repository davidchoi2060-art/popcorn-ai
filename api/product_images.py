"""Serve only catalog-linked display images from the private product media bucket."""
import hashlib
import re
import threading
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import AuthorizedSession
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from .db import engine

router=APIRouter()
_sessions=threading.local()
MEDIA_BUCKET='popcorn-ai-product-media-045e861b'


def _session():
    if not hasattr(_sessions,'value'):
        credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_only'])
        _sessions.value=AuthorizedSession(credentials,refresh_timeout=10)
    return _sessions.value


def read_image(asset, code, variant):
    key=asset.get('detail_key' if variant=='detail' else 'thumbnail_key','')
    suffix='detail.png' if variant=='detail' else 'thumb.webp'
    if asset.get('bucket')!=MEDIA_BUCKET or not re.fullmatch(r'products/'+str(code)+r'/[a-f0-9]{16}/'+re.escape(suffix),key):
        raise HTTPException(404,'등록된 표시용 이미지가 없습니다.')
    try:
        url=f'https://storage.googleapis.com/storage/v1/b/{MEDIA_BUCKET}/o/{quote(key,safe="")}?alt=media'
        with _session().get(url,timeout=(5,15),stream=True,allow_redirects=False) as response:
            if response.status_code==404:raise HTTPException(404,'이미지 파일을 찾지 못했습니다.')
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('Unexpected storage response')
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>10*1024*1024:raise ValueError('Image size limit')
                chunks.append(chunk)
            data=b''.join(chunks)
            if variant=='detail' and hashlib.sha256(data).hexdigest()!=asset.get('detail_sha256'):
                raise ValueError('Image checksum mismatch')
            return data
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(503,'이미지 저장소 연결을 확인해주세요.') from exc


@router.get('/api/product-images/{code}/{variant}')
def product_image(code:int,variant:str,request:Request):
    if variant not in ('detail','thumbnail'):raise HTTPException(404,'지원하지 않는 이미지 종류입니다.')
    with engine.connect() as conn:
        asset=conn.execute(text("SELECT content->'image_asset' FROM product_explanations WHERE source_product_code=:code"),{'code':code}).scalar()
    if not asset:raise HTTPException(404,'등록된 이미지가 없습니다.')
    data=read_image(asset,code,variant)
    etag='"'+hashlib.sha256(data).hexdigest()+'"'
    headers={'Cache-Control':'public, max-age=3600','ETag':etag,'X-Content-Type-Options':'nosniff'}
    if request.headers.get('if-none-match')==etag:return Response(status_code=304,headers=headers)
    return Response(data,media_type='image/png' if variant=='detail' else 'image/webp',headers=headers)
