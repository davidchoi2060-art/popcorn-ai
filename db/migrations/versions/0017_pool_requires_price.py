"""추천 후보 뷰에 가격 게이트를 넣는다 — 판매가 없는 상품이 견적에 들어가 API를 죽였다.

'4중 게이트(사양·검수·가격·재고)'라고 문서에 적어 두고 **뷰는 가격을 보지 않았다.**
status='판매중' · ai_candidate_yn · review_required_yn=false · core_part만 검사했다.

그래서 판매가가 NULL인 상품(P-9106)이 후보 풀에 들어왔고, 예산 필터가
`sale_price <= int(cap * 배분율)`을 계산하다 TypeError로 **견적 API 전체가 500**이 됐다.
후보 수도 3,308 -> 3,309로 늘어 회귀가 함께 잡았다.

값을 손으로 고치지 않고 게이트를 고친다 — 그 상품 하나를 바로잡아도 다음에 또 생긴다.
가격이 없으면 팔 수 없고, 팔 수 없으면 견적에 넣을 수 없다.

**WHERE 절만 바꾼다**(컬럼 목록은 그대로). CREATE OR REPLACE VIEW는 컬럼 변경은
거부하지만 조건 변경은 허용한다.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

VIEW = "v_recommendation_candidates"
COND = "p.sale_price IS NOT NULL"


def _rewrite(conn, add: bool):
    ddl = conn.execute(sa.text(f"SELECT pg_get_viewdef('{VIEW}', true)")).scalar()
    if add:
        if COND in ddl:
            return
        # WHERE 바로 뒤에 조건을 끼운다 — 나머지 정의는 손대지 않는다
        i = ddl.upper().find("WHERE")
        if i < 0:
            raise RuntimeError("뷰에 WHERE 절이 없습니다 — 수동 확인 필요")
        ddl = ddl[:i + 5] + f" {COND} AND" + ddl[i + 5:]
    else:
        ddl = ddl.replace(f" {COND} AND", "", 1)
    conn.execute(sa.text(f"CREATE OR REPLACE VIEW {VIEW} AS {ddl}"))


def upgrade():
    _rewrite(op.get_bind(), True)


def downgrade():
    _rewrite(op.get_bind(), False)
