"""compat_rules.op 어휘 확장 — 'contains' 수용 (슬라이스 39).

`op`이 VARCHAR(4)로 잡혀 있어 eq/gte/lte만 들어간다. 쿨러는 소켓을 평균 5~6개 지원하므로
(실측: 6개 180건·5개 73건·7개 43건) `COOLER.socket_list contains CPU.socket` 규칙이 필요하고,
그 연산자 이름이 4자를 넘는다. 어휘를 늘릴 자리를 만드는 최소 개정이다.

**op 어휘(성문화)**: eq · gte · lte · contains(참조값이 배열 안에 있는가).
NULL 불통과 원칙은 그대로 — 배열이 없거나 비면 통과하지 않는다.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE compat_rules ALTER COLUMN op TYPE VARCHAR(12);")


def downgrade() -> None:
    # 되돌리기 전에 4자 초과 값을 남겨두면 실패한다 — 쿨러 규칙을 단일값 비교로 환원한다.
    op.execute("""
        UPDATE compat_rules SET field='socket', op='eq', detail_fmt='{v} = {r}'
         WHERE rule_key='cooler_socket';
        ALTER TABLE compat_rules ALTER COLUMN op TYPE VARCHAR(4);
    """)
