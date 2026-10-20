"""Serve only catalog-linked display images from the private product media bucket."""
import hashlib
import re
import threading
from collections import OrderedDict
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import AuthorizedSession
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from .db import engine

router=APIRouter()
_sessions=threading.local()
MEDIA_BUCKET='popcorn-ai-product-media-045e861b'
# 저장소에서 받은 표시용 사진 바이트(키 -> bytes). 키에 버전 폴더(16자리 해시)가 들어 있어 사진을 바꾸면 키가 바뀐다 --
# 같은 키는 같은 내용이다. 공개 여부는 여기 묶지 않는다: 요청마다 product_explanations 를 다시 읽고 나서만 캐시를 본다.
_bytes_cache=OrderedDict()
_bytes_cache_lock=threading.Lock()
_bytes_cache_size=0
BYTES_CACHE_LIMIT=32*1024*1024


def _session():
    if not hasattr(_sessions,'value'):
        credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_only'])
        _sessions.value=AuthorizedSession(credentials,refresh_timeout=10)
    return _sessions.value


def image_key(asset, code, variant):
    key=asset.get('detail_key' if variant=='detail' else 'thumbnail_key','')
    suffix='detail.png' if variant=='detail' else 'thumb.webp'
    if asset.get('bucket')!=MEDIA_BUCKET or not re.fullmatch(r'products/'+str(code)+r'/[a-f0-9]{16}/'+re.escape(suffix),key):
        raise HTTPException(404,'등록된 표시용 이미지가 없습니다.')
    return key


def known_etag(asset, key, variant):
    """저장소를 읽기 전에 정할 수 있는 ETag. detail 은 기록된 원본 해시(내려보낸 바이트의 sha256 과 같다 -- read_image 가
    확인한다), 썸네일은 버전 키와 그 해시로 만든다(같은 키는 같은 파일이다). 기록이 없으면 None -- 받은 바이트로 계산한다."""
    sha=asset.get('detail_sha256')
    if not (isinstance(sha,str) and re.fullmatch(r'[a-f0-9]{64}',sha)):return None
    return '"'+(sha if variant=='detail' else hashlib.sha256((key+'\n'+sha).encode()).hexdigest())+'"'


def _cached(key):
    with _bytes_cache_lock:
        data=_bytes_cache.get(key)
        if data is not None:_bytes_cache.move_to_end(key)
        return data


def _remember(key, data):
    global _bytes_cache_size
    if len(data)>BYTES_CACHE_LIMIT//4:return
    with _bytes_cache_lock:
        if key in _bytes_cache:return
        _bytes_cache[key]=data;_bytes_cache_size+=len(data)
        while _bytes_cache_size>BYTES_CACHE_LIMIT and _bytes_cache:
            _,old=_bytes_cache.popitem(last=False);_bytes_cache_size-=len(old)


def read_image(asset, code, variant):
    key=image_key(asset,code,variant)
    data=_cached(key)
    if data is not None:return data
    data=_fetch(asset,key,variant)
    _remember(key,data)
    return data


def _fetch(asset, key, variant):
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
    # 공개 판정(위 조회)은 매 요청 한다. 재검증(304)은 ETag 를 미리 알 수 있으면 저장소를 읽지 않고 답한다.
    etag=known_etag(asset,image_key(asset,code,variant),variant)
    headers={'Cache-Control':'public, max-age=3600','X-Content-Type-Options':'nosniff'}
    if etag and request.headers.get('if-none-match')==etag:return Response(status_code=304,headers={**headers,'ETag':etag})
    data=read_image(asset,code,variant)
    headers['ETag']=etag or '"'+hashlib.sha256(data).hexdigest()+'"'
    if request.headers.get('if-none-match')==headers['ETag']:return Response(status_code=304,headers=headers)
    return Response(data,media_type='image/png' if variant=='detail' else 'image/webp',headers=headers)
