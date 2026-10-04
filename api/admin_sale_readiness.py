"""Read-only readiness evidence for the existing authenticated admin shell."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from .sale_readiness_parts import detail_part, list_parts


router = APIRouter(prefix='/api/admin/sale-readiness')
Scope = Literal['parts', 'configurations']
STATES = ('needs_work', 'needs_check', 'basis_met', 'excluded')
NOTE = '현재 확인된 근거와 보완 사유입니다. 추천 자격과 주문·결제 가능 여부는 구분합니다.'


def connection():
    # Import only when the authenticated handler runs; pure tests never load api.db.
    from .db import engine
    return engine.connect()


def readers(scope):
    if scope == 'parts':
        return list_parts, detail_part
    from .sale_readiness_configurations import list_configurations, detail_configuration
    return list_configurations, detail_configuration


def page_result(scope, items, q, offset, limit):
    needle = q.strip().casefold()
    if needle:
        items = [item for item in items if needle in ' '.join(
            [item['id'], item['name'], item['code']]
            + [str(reason[field]) for reason in item['reasons'] for field in ('label', 'detail')]
        ).casefold()]
    counts = {state: sum(item['state'] == state for item in items) for state in STATES}
    return dict(scope=scope, items=items[offset:offset + limit], counts=counts,
                total=len(items), offset=offset, limit=limit, note=NOTE)


@router.get('')
def sale_readiness(response: Response, scope: Scope = 'parts', q: str = Query('', max_length=100),
                   offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    load, _ = readers(scope)
    with connection() as conn:
        items = load(conn)
    return page_result(scope, items, q, offset, limit)


@router.get('/{scope}/{identity}')
def sale_readiness_detail(scope: Scope, identity: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    _, load = readers(scope)
    try:
        with connection() as conn:
            item = load(conn, identity)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), 'Cache-Control': 'no-store'}
        raise
    if item is None:
        raise HTTPException(404, '대상을 찾을 수 없습니다', headers={'Cache-Control': 'no-store'})
    return item
