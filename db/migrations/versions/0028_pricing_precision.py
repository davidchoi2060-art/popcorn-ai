"""가격 정책 비율의 자릿수를 넓힌다 — 2.585%가 2.59%로 조용히 반올림됐다 (슬라이스 E).

■ 무엇이 일어났나
사용자가 카드수수료를 **2.585%**(기존 임대 관리자의 운영값)로 확정해 저장했는데,
`pricing_settings.card_fee_rate`가 `NUMERIC(5,4)`라 소수 넷째 자리까지만 담긴다.

    입력 0.02585  ->  저장 0.0259  ->  화면 "2.59%"

**아무도 오류를 보지 못했다.** API는 200을 돌려줬고 화면은 저장됐다고 말했다.
사용자가 정한 값이 시스템 안에서 다른 값이 된 채로 남았다.

■ 왜 중요한가
이 비율은 **모든 상품의 판매가를 만드는 수**다. 매입가 100만원이면 25,900원 대 25,850원으로
건당 50원 차이지만, 문제는 금액이 아니라 **결정이 말없이 바뀌었다는 것**이다.
"모든 견적에는 이유가 있습니다"라고 말하는 시스템에서 근거값이 몰래 반올림되면 안 된다.

■ 얼마나 넓히나
`NUMERIC(7,6)` — 소수 여섯째 자리(0.000001 = 0.0001%)까지. 비율은 API가 0 이상 1 미만으로
막고 있으므로 정수부 1자리면 충분하고, 여섯 자리면 실무에서 쓰는 어떤 수수료율도 담긴다
(2.585% · 3.3% · 2.9% 등).

■ 되돌리기
downgrade는 `NUMERIC(5,4)`로 되돌린다 — **그 순간 자릿수가 다시 잘린다.** 이미 저장된
2.585%는 2.59%가 된다. 되돌릴 일이 있으면 그 사실을 알고 해야 한다.

■ 회귀가 지킨다
`[36]`이 "저장한 값이 그대로 돌아온다"를 검사한다 — 반올림으로 값이 바뀌면 실패한다.
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pricing_settings"
               " ALTER COLUMN card_fee_rate TYPE NUMERIC(7,6)")
    op.execute("ALTER TABLE pricing_settings"
               " ALTER COLUMN margin_rate  TYPE NUMERIC(7,6)")
    # 카테고리별 마진도 같은 표기를 쓴다 — 한쪽만 넓히면 두 경로가 다른 값을 만든다.
    op.execute("ALTER TABLE category_margin_policies"
               " ALTER COLUMN margin_rate TYPE NUMERIC(7,6)")


def downgrade() -> None:
    # 자릿수가 잘린다(2.585% -> 2.59%). 알고 되돌려야 한다.
    op.execute("ALTER TABLE category_margin_policies"
               " ALTER COLUMN margin_rate TYPE NUMERIC(5,4)")
    op.execute("ALTER TABLE pricing_settings"
               " ALTER COLUMN margin_rate  TYPE NUMERIC(5,4)")
    op.execute("ALTER TABLE pricing_settings"
               " ALTER COLUMN card_fee_rate TYPE NUMERIC(5,4)")
