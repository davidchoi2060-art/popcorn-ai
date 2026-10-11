"""판매 안내 자료 — 관리자가 적고 고객 상담 AI 가 그대로 쓰는 주제별 안내 (2026-10-11).

품질관리(2026-10-11) 고객 역할 셋에서 AI 가 「윈도우 깔아서 배송」「5대 주문 확인」처럼
근거 없는 약속을 했다. 운영체제·배송·A/S·세금계산서·할인 안내를 관리자가 적을 곳이 없었다.

주제 목록과 기본 안내는 코드(`api/talk_rules.PURCHASE_TOPICS`)에 있다. 이 표에는 관리자가
적은 안내만 담는다 — 행이 없거나 '미사용'이면 기본 안내가 나간다. 시드 행은 넣지 않는다.
"""
from alembic import op

revision = '0137'
down_revision = '0136'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE shop_notices (
      topic_key VARCHAR(32) PRIMARY KEY,
      body TEXT,
      status VARCHAR(8) NOT NULL DEFAULT '미사용' CHECK(status IN ('사용','미사용')),
      updated_by BIGINT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK(body IS NULL OR length(body) BETWEEN 1 AND 400),
      CHECK(status <> '사용' OR body IS NOT NULL))''')


def downgrade():
    op.execute('DROP TABLE shop_notices')
