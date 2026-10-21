"""기존 승인 25개 쿨러 교체(tools/remake25_cooler.py)의 «드라이런·상태 조회» 내부 경로 — 임시 (2026-10-21 사장님 「허락..」).

러너(같은 VM)가 127.0.0.1:8000 으로 직접 부를 때만 연다. nginx 를 거친 요청은 uvicorn --proxy-headers 가
client.host 를 실제 접속 IP 로 바꾸고, 전달 헤더도 붙어 오므로 둘 다 거른다.
드라이런은 모든 쓰기를 되돌린다(전용 저장소에 내용 주소 키로 올린 사진만 남는다). 실제 반영은 이 경로가 하지 않는다 —
마이그레이션이 배포 때 한 번 한다. 25개 반영이 끝나면 이 파일을 지운다.
"""
import threading

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
_lock = threading.Lock()


@router.get('/api/internal/remake25')
def remake25(request: Request, mode: str = Query('status', pattern='^(status|dry)$')):
    host = request.client.host if request.client else ''
    if host != '127.0.0.1' or request.headers.get('x-forwarded-for') or request.headers.get('x-real-ip'):
        raise HTTPException(404, 'Not Found')
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, 'running')
    try:
        from api.db import engine
        from tools import remake25_cooler as tool
        if mode == 'status':
            return tool.status(engine)
        return tool.run(engine, apply=False)
    finally:
        _lock.release()
