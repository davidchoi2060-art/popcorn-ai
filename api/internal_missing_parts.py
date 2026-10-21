"""판매 PC 구성 부품 중 부품 설명이 없던 것 등록(tools/register_missing_parts.py)의 «연습·결과 조회» 내부 경로 — 임시 (2026-10-21).

러너(같은 VM)가 127.0.0.1:8000 으로 직접 부를 때만 연다(api/internal_remake25.py 와 같은 거름).
연습은 DB 쓰기를 모두 되돌린다(전용 저장소에 내용 주소 키로 올린 사진만 남는다). 실제 반영은 마이그레이션이 한다.
"""
import threading

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
_lock = threading.Lock()


@router.get('/api/internal/missing-parts')
def missing_parts(request: Request, mode: str = Query('report', pattern='^(report|dry)$')):
    host = request.client.host if request.client else ''
    if host != '127.0.0.1' or request.headers.get('x-forwarded-for') or request.headers.get('x-real-ip'):
        raise HTTPException(404, 'Not Found')
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, 'running')
    try:
        from tools import register_missing_parts as tool
        if mode == 'report':
            return tool.read_report()
        from api.db import engine
        return tool.run(engine, apply=False)
    finally:
        _lock.release()
