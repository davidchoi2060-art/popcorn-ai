"""관리자 비밀번호 인증 — nginx Basic Auth를 걷어내기 위한 전제.

지금 앱 로그인은 **입력한 이메일을 그대로 신뢰한다**(dev 어댑터). 승인된 관리자
이메일을 아는 사람은 누구나 들어올 수 있어서, nginx Basic Auth가 그 앞을 막고 있었다.
그런데 그 팝업이 모바일에서 불편하고 이메일을 넣게 되는 혼동을 만든다(실제로
"kck@popcornpc.co.kr was not found in .htpasswd-popcorn" 에러가 반복됐다).

그래서 앱이 직접 비밀번호를 검증하게 한다. **원문은 저장하지 않는다** — scrypt 해시만
둔다(표준 라이브러리, 새 의존성 없음). 해시는 되돌릴 수 없으므로 DB가 새도
비밀번호가 새지 않는다.

`password_hash IS NULL`이면 **로그인할 수 없다**. 기존 계정 11개가 그 상태로 시작하고,
owner가 임시 비밀번호를 발급하거나 서버에서 직접 설정해야 한다 — 마이그레이션이
자동으로 비밀번호를 만들어 주면 그게 곧 뒷문이 된다.

fail2ban이 없으므로 잠금을 앱에서 한다: 연속 실패가 쌓이면 일정 시간 막는다.

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_operators",
                  sa.Column("password_hash", sa.String(255)))
    op.add_column("admin_operators",
                  sa.Column("password_set_at", sa.DateTime))
    # 비밀번호를 발급받았지만 아직 본인이 바꾸지 않은 상태 — 최초 로그인에서 변경을 요구한다
    op.add_column("admin_operators",
                  sa.Column("must_change_password", sa.Boolean,
                            nullable=False, server_default=sa.false()))
    op.add_column("admin_operators",
                  sa.Column("login_fail_count", sa.Integer,
                            nullable=False, server_default="0"))
    op.add_column("admin_operators",
                  sa.Column("locked_until", sa.DateTime))


def downgrade():
    for c in ("locked_until", "login_fail_count", "must_change_password",
              "password_set_at", "password_hash"):
        op.drop_column("admin_operators", c)
