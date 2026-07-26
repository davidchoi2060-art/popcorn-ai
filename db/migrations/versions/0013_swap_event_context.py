"""부품 교체 기록에 맥락 3컬럼 — swap_event_logs (슬라이스 46).

`swap_event_logs`는 스키마만 있고 **0행이었다**(swap API가 기록을 남기지 않았다).
기록을 시작하면서, 화면(ADM-ANL-020 부품 교체 기록)이 쓸 수 있는 최소 맥락을 더한다.

기존 컬럼(from_product·to_product·user_id)만으로는 "무엇을 무엇으로 바꿨나"까지만 말할 수
있다. 화면은 **어느 상담에서 · 어느 슬롯을 · 얼마 차이로** 바꿨는지를 묻는다:

  · `session_id`  — 상담 기록(consult_sessions)과 이어진다. 교체가 어느 대화에서 나왔는지.
  · `slot`        — 어느 슬롯을 바꿨나(GPU를 자주 바꾸는지, POWER를 자주 바꾸는지).
  · `price_delta` — 가격이 얼마 오르내렸나(비싸게 갈아타는 신호 vs 아끼는 신호).

`user_id`는 그대로 두고 채우지 않는다 — 스왑은 게스트도 하고(로그인 강요 없음), 회원
주체는 세션에서 파생할 수 있다. 지어낸 주체를 남기지 않는다.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE swap_event_logs
          ADD COLUMN session_id  BIGINT REFERENCES consult_sessions(session_id),
          ADD COLUMN slot        VARCHAR(20),
          ADD COLUMN price_delta INTEGER;

        CREATE INDEX idx_swap_events_pair ON swap_event_logs (from_product, to_product);
        CREATE INDEX idx_swap_events_at ON swap_event_logs (created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_swap_events_at;
        DROP INDEX IF EXISTS idx_swap_events_pair;
        ALTER TABLE swap_event_logs
          DROP COLUMN IF EXISTS price_delta,
          DROP COLUMN IF EXISTS slot,
          DROP COLUMN IF EXISTS session_id;
    """)
