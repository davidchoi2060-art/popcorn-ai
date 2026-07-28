"""라디에이터 규칙 활성화 — 값을 채운 뒤에 켠다 (슬라이스 82-B).

0022가 필드·규칙을 만들되 규칙은 꺼 둔 채로 두었다. 값이 없는 상태에서 켜면 수랭이
통째로 탈락하기 때문이다(0021이 고친 것과 같은 전멸을 다른 이유로 반복하게 된다).

백필 후 실측(2026-07-29, 판매중·재고 기준):

    수랭 후보    49 · 라디에이터 열 있음  47
    케이스 후보 801 · 수랭 최대 열 있음  599

    (수랭 x 케이스) 39,249 조합
      통과            24,445  62%
      값 없어 불통과   11,096  28%   모르면 통과시키지 않는다(NULL 불통과)
      실제로 안 들어감  3,708   9%   규칙이 잡아내는 것 - 지금까지는 그냥 나갔다

    수랭이 하나라도 붙는 케이스 596/801 · 케이스가 있는 수랭 47/49

전멸하지 않는다. 켠다.

빠지는 수랭 2개는 라디에이터 크기를 원문에서 확인할 수 없는 것들이다(팬 6개 푸시풀 —
팬개수와 라디에이터 열을 구분할 수 없다). 값을 지어내는 대신 비워 뒀고, 상품 상세에서
사람이 넣으면 바로 살아난다.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE compat_rules SET active = true WHERE rule_key = 'radiator'")


def downgrade() -> None:
    op.execute("UPDATE compat_rules SET active = false WHERE rule_key = 'radiator'")
