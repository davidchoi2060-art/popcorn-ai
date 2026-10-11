"""MVP3 부품 바꾸기 — 고른 판매 PC 에서 한 부품만 다른 판매 PC 를 보여 준다 (2026-10-11).

■ 왜 «다른 판매 PC» 인가
  고객 화면(mvp3)이 권하는 것은 몰의 완제품 한 대(pd_no)다. 부품 하나만 바꾼 구성은 몰에 상품이
  없어 쇼핑몰로 넘길 수 없고, 그 값을 우리가 매기면 새 가격 계산이 된다. 기존 `/api/swap/*`
  는 부품 조립 견적(quote_snapshots)용이라 완제품을 다루지 못한다. 그래서 이 경로는 «바꾸려는
  부품만 다르고 핵심 부품은 같은 다른 판매 PC» 를 찾는다(규칙 원천 `api/sold_reco.part_options`).

      호환     몰이 조립해 파는 구성이다 — 맞지 않는 조합은 애초에 후보가 아니다
      가격     그 상품의 현재 판매가(추천 카드와 같은 원천) — 차액은 두 판매가의 차이일 뿐이다
      보관     고른 상품번호로 지금 「견적 보관하기」를 그대로 탄다(api/mvp3_saved_quotes 가
               같은 판정 eligible_sold_item 으로 다시 확인한다)
      구매     보관한 상품번호로 지금 「쇼핑몰에서 구매하기」를 그대로 탄다(api/mvp3_handoff)

■ 읽기만 한다 — 원장·가격·부품 데이터에 쓰지 않는다.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from . import grid_public

router = APIRouter(prefix='/api/mvp3', tags=['mvp3'])


class PartOptionsBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: dict
    product_code: StrictInt = Field(gt=0)
    slot: Literal['cpu', 'gpu', 'ram', 'ssd']


@router.post('/part-options')
def part_options(body: PartOptionsBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    res = grid_public.sold_part_options(body.state, body.product_code, body.slot)
    if res is None:
        raise HTTPException(409, '지금 판매 중인 추천 상품이 아니에요. 추천을 다시 조회해 주세요.')
    return {'ok': True, **res}
