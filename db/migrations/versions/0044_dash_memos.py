# -*- coding: utf-8 -*-
"""현황판 메모 — `dash_memos` (2026-08-12 사용자 요청)

■ 무엇에 쓰나
  작업 현황판의 진행 흐름에서 **남겨 둘 항목을 골라 저장**했다가, 나중에 찾아
  **다시 세션에 보낸다**(= 큐에 넣어 재실행). 진행 흐름은 전사본 꼬리라 흘러가 버리는데,
  «이건 이따 시켜야지» 하는 것을 붙잡아 두는 자리다.

■ 원장이 아니다
  개인 메모라 **삭제를 연다**(주문·재고 원장의 「삭제 금지 · 역방향 전이」 규칙과 다른 부류).
  다만 재실행 이력은 남긴다 — `used_at` · `used_count` 로 «언제 다시 시켰나»는 알 수 있게.

■ 원문 시각을 함께 둔다
  `event_ts` 는 전사본 사건의 시각이다. 메모만 보고 «그때 무슨 맥락이었나»를 찾아가려면
  전사본 어디쯤인지가 있어야 한다 — 내용만 남기면 못 찾는다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dash_memos",
        sa.Column("memo_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_ts", sa.String(40)),                  # 전사본 사건 시각 (UTC ISO)
        sa.Column("who", sa.String(16)),                       # user / claude / result
        sa.Column("content", sa.Text, nullable=False),         # 저장한 내용
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),      # 마지막 재실행 시각
        sa.Column("used_count", sa.Integer, server_default="0", nullable=False),
    )
    op.create_index("ix_dash_memos_created", "dash_memos", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_dash_memos_created", table_name="dash_memos")
    op.drop_table("dash_memos")
