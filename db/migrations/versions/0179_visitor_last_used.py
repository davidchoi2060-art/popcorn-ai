"""방문자 식별값·보관 견적의 「마지막 이용」 시각 -- 1년 동안 쓰지 않으면 파기한다.

근거: 2026-11-18 사장님 승인, 개인정보처리방침(2026-11-23 시행) 「방문자 식별값·보관 견적은 마지막 이용 뒤
1년이 지나면 파기」. 파기 자체는 `api/retention_purge.py` 의 visitor_key · saved_quote 가 한다.

■ 왜 새 열인가
  두 표에는 «마지막 이용»을 판정할 열이 없었다.
      users                       user_id · anon_key · created_at          (0001 · 0034)
      mvp3_saved_recommendations  saved_at(처음 보관) · member_id · surface (0123 · 0156 · 0162)
  created_at·saved_at 은 «처음» 시각이라, 그것으로 자르면 어제도 쓴 방문자를 지운다.

■ 바꾸는 것
  users
    · last_used_at TIMESTAMPTZ NOT NULL DEFAULT now() -- 기존 행은 created_at 으로 채운다
      (created_at 은 시간대 없는 TIMESTAMP 라 세션 시간대로 읽힌다. 1년 기한에 몇 시간 차이는 무관하다)
    · anon_key_purged_at TIMESTAMPTZ -- 식별값을 비운 시각(기존 contact_purged_at 과 같은 규약)
    · anon_key 는 원래 NULL 을 허용한다(0001: `anon_key VARCHAR(64) UNIQUE`) -- 제약은 바꾸지 않는다.
  mvp3_saved_recommendations
    · last_used_at TIMESTAMPTZ NOT NULL DEFAULT now() -- 기존 행은 saved_at 으로 채운다
    · purged_at TIMESTAMPTZ -- 내용을 비운 시각
    · owner_key_hash · request_basis 의 NOT NULL 을 푼다 -- 파기가 이 둘을 NULL 로 비운다.
      대신 CHECK 로 「비우지 않은 행(purged_at IS NULL)은 둘 다 있어야 한다」를 지킨다(0158 과 같은 방식).
      product_snapshot · talk_state 는 NOT NULL·object CHECK 그대로 두고 파기 때 빈 객체('{}')로 바꾼다
      -- 읽는 곳이 모두 `or {}` 로 받는다(admin_mvp3_consults · mvp3_handoff · mvp3_quote_consult …).
  행은 지우지 않는다 -- users 는 여러 표가 FK 로 참조하고, 보관 견적은 상담 신청(purchase_inquiries.quote_id)이 참조한다.

■ downgrade
  파기된 행이 한 줄이라도 있으면 거절한다(NOT NULL 을 되돌릴 수 없고, 비운 기록을 잃는다 -- 0153 과 같은 원칙).
"""
from alembic import op

revision = '0179'
down_revision = '0178'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE users ADD COLUMN last_used_at TIMESTAMPTZ')
    op.execute('UPDATE users SET last_used_at = created_at')
    op.execute('ALTER TABLE users ALTER COLUMN last_used_at SET DEFAULT now()')
    op.execute('ALTER TABLE users ALTER COLUMN last_used_at SET NOT NULL')
    op.execute('ALTER TABLE users ADD COLUMN anon_key_purged_at TIMESTAMPTZ')
    op.execute('CREATE INDEX ix_users_last_used_live ON users (last_used_at) WHERE anon_key IS NOT NULL')

    t = 'mvp3_saved_recommendations'
    op.execute(f'ALTER TABLE {t} ADD COLUMN last_used_at TIMESTAMPTZ')
    op.execute(f'UPDATE {t} SET last_used_at = saved_at')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN last_used_at SET DEFAULT now()')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN last_used_at SET NOT NULL')
    op.execute(f'ALTER TABLE {t} ADD COLUMN purged_at TIMESTAMPTZ')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN owner_key_hash DROP NOT NULL')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN request_basis DROP NOT NULL')
    op.execute(f'ALTER TABLE {t} ADD CONSTRAINT ck_mvp3_saved_live_owner CHECK '
               '(purged_at IS NOT NULL OR (owner_key_hash IS NOT NULL AND request_basis IS NOT NULL))')
    op.execute(f'CREATE INDEX ix_mvp3_saved_last_used_live ON {t} (last_used_at) WHERE purged_at IS NULL')


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM mvp3_saved_recommendations WHERE purged_at IS NOT NULL LIMIT 1)
         OR EXISTS (SELECT 1 FROM users WHERE anon_key_purged_at IS NOT NULL LIMIT 1)
      THEN RAISE EXCEPTION 'purged visitor keys and saved quotes must be preserved'; END IF; END $$""")
    t = 'mvp3_saved_recommendations'
    op.execute('DROP INDEX IF EXISTS ix_mvp3_saved_last_used_live')
    op.execute(f'ALTER TABLE {t} DROP CONSTRAINT ck_mvp3_saved_live_owner')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN request_basis SET NOT NULL')
    op.execute(f'ALTER TABLE {t} ALTER COLUMN owner_key_hash SET NOT NULL')
    op.execute(f'ALTER TABLE {t} DROP COLUMN purged_at')
    op.execute(f'ALTER TABLE {t} DROP COLUMN last_used_at')
    op.execute('DROP INDEX IF EXISTS ix_users_last_used_live')
    op.execute('ALTER TABLE users DROP COLUMN anon_key_purged_at')
    op.execute('ALTER TABLE users DROP COLUMN last_used_at')
