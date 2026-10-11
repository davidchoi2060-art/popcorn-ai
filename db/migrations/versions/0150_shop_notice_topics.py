"""판매 안내 자료 — 관리자가 직접 더하는 안내 주제 (2026-10-11 품질관리 · 개편 12번).

0137 의 주제 일곱 개(운영체제·주변기기·여러 대·결제·할인·A/S·배송)는 코드에 고정돼 있다.
「인텔이 좋아요 AMD가 좋아요?」「4060이면 됨?」 같은 질문은 어느 주제에도 걸리지 않아 AI 가
질문을 넘기고 용도만 되물었다(고객3 F11 · 고객1 기능 9). 관리자가 주제 이름 · 알아볼 낱말 ·
안내 문장을 직접 더하는 표다.

  · 낱말은 정규식이 아니라 «글자 그대로»다(공백·대소문자 무시). 관리자가 규칙 문법을 몰라도 된다.
  · 행을 지우지 않는다 — «미사용»으로 내리면 고객에게 나가지 않는다(0137 과 같은 규칙).
  · 시드 행은 넣지 않는다. 기존 표·데이터는 건드리지 않는다.
"""
from alembic import op

revision = '0150'
down_revision = '0145'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE shop_notice_topics (
      topic_id BIGSERIAL PRIMARY KEY,
      label VARCHAR(40) NOT NULL UNIQUE CHECK (length(btrim(label)) BETWEEN 1 AND 40),
      keywords JSONB NOT NULL CHECK (jsonb_typeof(keywords) = 'array'
                                     AND jsonb_array_length(keywords) BETWEEN 1 AND 20),
      body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 400),
      status VARCHAR(8) NOT NULL DEFAULT '미사용' CHECK (status IN ('사용','미사용')),
      created_by BIGINT,
      updated_by BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')


def downgrade():
    op.execute('''DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM shop_notice_topics) THEN
        RAISE EXCEPTION '0150 downgrade refused: shop_notice_topics has rows';
      END IF; END $$''')
    op.execute('DROP TABLE shop_notice_topics')
