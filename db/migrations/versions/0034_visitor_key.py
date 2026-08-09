"""방문자 키를 상담·주문에 붙인다 — 깔때기를 잇는 실 (2026-08-09).

■ 무엇이 문제였나 — 실측
  대시보드에 깔때기(접속 → 문의 → 성공 → S2 도달 → 장바구니 → 구매)를 넣으려 했더니
  **단계가 서로 이어지지 않았다.**

      상담 세션            3,885
      그중 회원이 붙은 것      1   (0.03%)
      주문                   10   (회원은 10/10, 상담은 6/10)
      promo_click_logs      235   그중 user_id 있는 것 0

  숫자는 있는데 **"이 3,885건 중 몇 명이 주문까지 갔나"** 를 답할 수 없다.
  깔때기는 각 단계가 앞 단계의 **부분집합**이어야 하는데, 지금은 모집단이 다른 수 여섯 개다.
  그걸 깔때기 모양으로 그리면 **화면이 있지도 않은 관계를 주장**하게 된다.

■ 구조는 이미 있었다 — 값이 안 들어갔을 뿐이다
  `users(user_id, anon_key)` 가 익명 방문자 표이고, 이미 **네 곳이 FK 로 참조**한다:
  `promo_click_logs` · `swap_event_logs` · `recommendations` · `members.user_id`.
  즉 **익명 → 회원 승격 경로까지 설계돼 있었다.** 그런데 키를 발급·유지하는 코드가
  없어서 `users` 는 1행이고 참조는 전부 NULL 이었다.

  그래서 새 축을 만들지 않는다. **없는 두 자리에만 같은 키를 붙인다.**

■ 왜 orders 에도 붙이나 — session_id 로 파생하면 안 되나
  `orders.session_id` 가 이미 있고 6/10 이 채워져 있다. 하지만 **상담 없이 들어온 주문**
  (쇼핑몰 인계·직접 주문)은 세션이 없다. 그때도 "누가" 는 남아야 하므로 주문에도
  방문자 키를 직접 둔다. 세션이 있으면 둘이 같은 사람을 가리키고, 없으면 주문 쪽만 남는다.

■ 과거는 못 잇는다 — 지어내지 않는다
  기존 상담 3,885건·주문 10건에는 키가 없다. 소급해서 그럴듯한 키를 만들면 **없던 관계를
  발명하는 것**이다. 재고 7,594건을 `inbound` 가 아니라 **기초 재고**(`opening`)로 기록한
  것과 같은 규칙이다. NULL 로 두고, **깔때기는 "오늘 이후 발생분"만 센다**는 사실을
  화면이 먼저 말한다.

■ NOT NULL 로 걸지 않는 이유
  방문자 키 발급이 실패해도 상담·주문은 진행돼야 한다. 집계용 축이 장사를 막으면 안 된다.
  (`clicks` 가 "실패해도 화면을 막지 않는다"고 한 것과 같은 판단.)
"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE consult_sessions
            ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(user_id)
    """)
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(user_id)
    """)
    # 깔때기 집계가 이 축으로 훑는다.
    op.execute("CREATE INDEX IF NOT EXISTS ix_consult_sessions_user ON consult_sessions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_user ON orders (user_id)")

    # 방문자 키는 고유해야 한다 — 같은 키가 둘이면 두 사람의 행동이 한 사람으로 합쳐진다.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_anon_key ON users (anon_key)")


def downgrade():
    # 컬럼을 지우면 "누가 무엇을 했나"가 함께 사라진다. 되돌릴 수 없는 손실이라
    # 인덱스만 걷는다 — 0033 과 같은 규칙이다.
    op.execute("DROP INDEX IF EXISTS ix_consult_sessions_user")
    op.execute("DROP INDEX IF EXISTS ix_orders_user")
