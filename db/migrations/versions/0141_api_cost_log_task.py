"""AI 비용 기록에 작업 종류와 고객 문의 번호를 남긴다 (2026-10-11 품질관리 · F6·F18).

`api_cost_logs` 는 업체·모델·토큰·비용만 남겼다. 그래서 관리자 「AI 사용량 · 비용」 화면의
작업 종류별 분해는 「항목 없음」으로 고정돼 있었고, 비용이 어느 고객 문의에서 났는지도
되짚을 수 없었다.

  task_key   `llm.call(task_key=...)` 로 받은 작업 종류. 새 기록부터 채운다
  hit_id     팝콘톡 문의 원장(`talk_intent_hits.hit_id`). 그 문의에서 부른 AI 기록에만 채운다

두 칸 다 NULL 허용이다. **이미 있는 행은 바꾸지 않는다** — 옛 기록은 「작업 종류 미기록」으로
보인다. hit_id 에 외래 키를 걸지 않는다: 비용 기록은 문의 원장보다 오래 남아야 한다.
"""
from alembic import op

revision = '0141'
down_revision = '0140'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE api_cost_logs ADD COLUMN task_key VARCHAR(48)')
    op.execute('ALTER TABLE api_cost_logs ADD COLUMN hit_id BIGINT')
    op.execute('CREATE INDEX api_cost_logs_task_idx ON api_cost_logs(task_key, created_at)')
    op.execute('CREATE INDEX api_cost_logs_hit_idx ON api_cost_logs(hit_id) WHERE hit_id IS NOT NULL')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM api_cost_logs
      WHERE task_key IS NOT NULL OR hit_id IS NOT NULL LIMIT 1)
      THEN RAISE EXCEPTION 'AI cost task records must be preserved'; END IF; END $$""")
    op.execute('DROP INDEX IF EXISTS api_cost_logs_hit_idx')
    op.execute('DROP INDEX IF EXISTS api_cost_logs_task_idx')
    op.execute('ALTER TABLE api_cost_logs DROP COLUMN hit_id')
    op.execute('ALTER TABLE api_cost_logs DROP COLUMN task_key')
