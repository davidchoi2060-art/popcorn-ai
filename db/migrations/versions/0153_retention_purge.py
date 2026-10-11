"""보관 기한이 지난 고객 개인정보를 지우는 일일 작업의 기록 (2026-10-11 코덱스 검수 #84 · #85).

고객 질문 원문(`talk_intent_hits.raw_purge_at`, 90일) · AI 답(`talk_reply_reviews.purge_at`) ·
구매 상담 연락처(`purchase_inquiries.purge_at`, 180일)는 보관 기한을 적어 두었지만 실제로 지우는
작업이 없었다. 화면은 기한이 지나면 가리기만 했다. 작업은 `api/retention_purge.py` 가 한다.

  · `retention_purge_runs`   실행 한 번에 한 줄. 미리보기(dry_run)인지, 표별로 몇 건을 지웠는지
                              (미리보기면 지울 대상 건수), 언제 시작·끝났는지 남긴다. 지우지 않는다.
  · `purchase_inquiries.contact_purged_at`
                              연락처를 지운 시각. 기존 CHECK(전화 또는 이메일 필수)는 연락처를 지운
                              행만 예외로 둔다 — 지운 행도 「언제 지웠는지」를 남긴다.

**기존 행의 값은 바꾸지 않는다.** 지우는 일은 작업이 설정(env)으로 켜졌을 때만 한다.
"""
from alembic import op

revision = '0153'
down_revision = '0142'
branch_labels = None
depends_on = None

_CONTACT_CHECK = 'purchase_inquiries_contact_check'


def upgrade():
    op.execute('''CREATE TABLE retention_purge_runs (
      run_id BIGSERIAL PRIMARY KEY,
      moment VARCHAR(8) NOT NULL CHECK (moment IN ('auto','manual')),
      dry_run BOOLEAN NOT NULL,
      counts JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts) = 'object'),
      error TEXT,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      finished_at TIMESTAMPTZ)''')
    op.execute('CREATE INDEX retention_purge_runs_started_idx ON retention_purge_runs(moment, started_at DESC)')
    op.execute('ALTER TABLE purchase_inquiries ADD COLUMN contact_purged_at TIMESTAMPTZ')
    # 0139 의 이름 없는 CHECK(전화 또는 이메일)를 찾아 바꾼다 — 이름은 Postgres 가 붙였다.
    op.execute("""DO $$
    DECLARE c text;
    BEGIN
      FOR c IN SELECT conname FROM pg_constraint
               WHERE conrelid = 'purchase_inquiries'::regclass AND contype = 'c'
                 AND pg_get_constraintdef(oid) LIKE '%contact_phone IS NOT NULL%contact_email IS NOT NULL%'
      LOOP
        EXECUTE format('ALTER TABLE purchase_inquiries DROP CONSTRAINT %I', c);
      END LOOP;
    END $$""")
    op.execute('ALTER TABLE purchase_inquiries ADD CONSTRAINT %s CHECK ('
               'contact_phone IS NOT NULL OR contact_email IS NOT NULL OR contact_purged_at IS NOT NULL)'
               % _CONTACT_CHECK)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM purchase_inquiries WHERE contact_purged_at IS NOT NULL LIMIT 1)
        THEN RAISE EXCEPTION 'Purged inquiry contacts cannot be restored'; END IF;
      IF EXISTS (SELECT 1 FROM retention_purge_runs LIMIT 1)
        THEN RAISE EXCEPTION 'Retention purge runs must be preserved'; END IF;
    END $$""")
    op.execute('ALTER TABLE purchase_inquiries DROP CONSTRAINT %s' % _CONTACT_CHECK)
    op.execute('ALTER TABLE purchase_inquiries ADD CHECK (contact_phone IS NOT NULL OR contact_email IS NOT NULL)')
    op.execute('ALTER TABLE purchase_inquiries DROP COLUMN contact_purged_at')
    op.execute('DROP TABLE retention_purge_runs')
