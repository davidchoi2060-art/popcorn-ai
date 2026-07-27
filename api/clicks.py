"""근거 클릭 수집 (슬라이스 49).

**왜 이게 필요한가.** 정체성이 "모든 견적에는 이유가 있습니다"인데, 정작 고객이 *어떤 부품의
이유를 확인하려 했는지*를 우리가 모르면 근거를 개선할 근거가 없다. 자주 눌리는 부품 =
설명만으로는 납득이 안 되는 부품이다. 그게 추천 기준을 손볼 지점이다.

`promo_click_logs`는 스키마에 이미 있었지만 **0행이었고 쌓이는 경로가 없었다**
(admin_swap_logs가 `empty=true`로 '원천 준비 중'을 표기해 온 이유). 이 라우터가 그 경로다.

기록하는 것은 `product_code`와 (로그인했다면) `member_id`뿐이다 — 스키마 무개정.
게스트도 기록한다: 로그인은 견적을 보는 조건이 아니고, 로그인 전 행동이 오히려 많다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .customer_auth import current_member
from .db import engine

router = APIRouter(prefix="/api")


class ClickBody(BaseModel):
    product_code: int


@router.post("/promo-click")
def promo_click(body: ClickBody):
    """근거를 확인하려고 부품을 누른 사실 1건. 실패해도 화면을 막지 않는다(집계용).

    `user_id`는 **회원 ID가 아니다.** FK가 `users`(익명 방문자 테이블)를 가리키고
    `members.user_id`가 그것을 참조하는 구조다. member_id를 넣으면 FK 위반으로
    조용히 롤백된다 — 실제로 그렇게 첫 두 건을 잃었다(슬라이스 49).
    로그인 회원이라도 방문자 키가 없으면(현재 대부분) 식별 없이 기록한다.
    """
    m = current_member() or {}
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM products WHERE product_code=:p"),
                        {"p": body.product_code}).first() is None:
            raise HTTPException(404, "없는 상품입니다")
        uid = None
        if m.get("member_id"):
            uid = conn.execute(text("SELECT user_id FROM members WHERE member_id=:m"),
                               {"m": m["member_id"]}).scalar()
        log_id = conn.execute(text(
            "INSERT INTO promo_click_logs (product_code, user_id) VALUES (:p, :u)"
            " RETURNING log_id"), {"p": body.product_code, "u": uid}).scalar_one()
    return {"ok": True, "log_id": log_id, "identified": uid is not None}
