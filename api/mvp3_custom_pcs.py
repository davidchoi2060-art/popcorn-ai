"""MVP3 「새로 나온 PC」 — 운영자가 부품을 골라 만든 조립PC 중 고객 공개된 것 (2026-10-11 부품 상품화 4단계).

판정은 `api/custom_pc.py` 한 곳이다. 쇼핑몰 상품번호가 없으므로 구매는 「구매 상담 신청」
(`api/mvp3_purchase_inquiry.py`, configuration_id 로 잇는다)으로 받는다. 주문·결제는 하지 않는다.
가격은 요청마다 지금 부품 판매가로 다시 센다.
"""
import logging

from fastapi import APIRouter, Response

from . import custom_pc
from .db import engine

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])
log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)


@router.get('/custom-pcs')
def custom_pcs(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with engine.connect() as conn:
        items = custom_pc.customer_list(conn)
    return {'ok': True, 'items': items, 'purchase': 'inquiry',
            'note': '팝콘PC가 부품을 골라 새로 만든 조립PC예요. 쇼핑몰 상품 페이지가 아직 없어 구매 상담 신청으로 주문을 도와드려요.'}
