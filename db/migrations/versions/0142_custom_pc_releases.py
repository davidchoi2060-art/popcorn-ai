"""신규 조립PC 고객 공개 기록 (2026-10-11 부품 상품화 4단계).

관리자 「신규 조립PC 생성」으로 만든 구성(`pc_configurations` · 오퍼 `ADMIN-…`)은 쇼핑몰 상품번호가
없어 고객 화면에 낼 길이 없었다. 이 표는 운영자의 「고객 공개」·「공개 중지」를 한 줄씩 쌓는다.

  action           release(공개) · withdraw(공개 중지). 되돌림은 지우지 않고 withdraw 한 줄을 더한다
  ref_event_id     withdraw 가 내리는 release 줄
  revision ·       공개할 때의 구성 판과 부품 지문. 그 뒤 구성표가 바뀌면 고객 화면은 그 공개를
  bom_fingerprint  인정하지 않는다(다시 공개해야 한다)
  price_at_release 공개할 때의 부품 판매가 합 + 조립비. 기록용이다 — 고객 가격은 늘 현재 판매가로 다시 센다

`purchase_inquiries.configuration_id` 는 고객이 그 PC 로 남긴 구매 상담 신청을 잇는다(NULL 허용).
**이미 있는 행은 바꾸지 않는다.**
"""
from alembic import op

revision = '0142'
down_revision = '0152'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE custom_pc_release_events (
      event_id BIGSERIAL PRIMARY KEY,
      configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      action VARCHAR(8) NOT NULL CHECK(action IN ('release','withdraw')),
      revision INTEGER NOT NULL CHECK(revision > 0),
      bom_fingerprint VARCHAR(64) NOT NULL,
      price_at_release INTEGER CHECK(price_at_release IS NULL OR price_at_release > 0),
      ref_event_id BIGINT REFERENCES custom_pc_release_events(event_id),
      note TEXT CHECK(note IS NULL OR length(note) <= 500),
      operator_id BIGINT NOT NULL REFERENCES admin_operators(operator_id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK((action = 'release' AND ref_event_id IS NULL AND price_at_release IS NOT NULL)
         OR (action = 'withdraw' AND ref_event_id IS NOT NULL)))''')
    op.execute('CREATE INDEX custom_pc_release_events_cfg_idx ON custom_pc_release_events(configuration_id, event_id DESC)')
    op.execute('ALTER TABLE purchase_inquiries ADD COLUMN configuration_id TEXT REFERENCES pc_configurations(configuration_id)')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM custom_pc_release_events LIMIT 1)
      OR EXISTS (SELECT 1 FROM purchase_inquiries WHERE configuration_id IS NOT NULL LIMIT 1)
      THEN RAISE EXCEPTION 'custom PC release records must be preserved'; END IF; END $$""")
    op.execute('ALTER TABLE purchase_inquiries DROP COLUMN configuration_id')
    op.execute('DROP TABLE custom_pc_release_events')
