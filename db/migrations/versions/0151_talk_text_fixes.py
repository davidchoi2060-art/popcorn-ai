"""상담 해석 바로잡기 — 관리자가 등록하는 표현 규칙 (2026-10-11 품질관리 · 개편 14번 · R8 나머지).

「롤 120」「100만원대」는 코드로 바로잡았지만(#88), 다음에 잘못 읽힌 표현은 다시 개발이
필요했다. 관리자가 «표현 → 바로잡을 값»(예산 · 해상도)을 등록하면 상담이 AI 가 읽은 값보다
먼저 이 값을 쓴다.

  · 표현은 정규식이 아니라 «글자 그대로»다(공백·대소문자 무시). `phrase_norm` 이 그 비교 열이고 고유하다.
  · 종류 «예산»은 `budget_won`(원) 과 `budget_bound`(이하·이상·없음), «해상도»는 `resolution` 만 쓴다.
  · 행을 지우지 않는다 — «미사용»으로 내린다. 시드 행 없음. 기존 표·데이터는 건드리지 않는다.
"""
from alembic import op

revision = '0151'
down_revision = '0150'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE talk_text_fixes (
      fix_id BIGSERIAL PRIMARY KEY,
      phrase VARCHAR(30) NOT NULL CHECK (length(btrim(phrase)) BETWEEN 2 AND 30),
      phrase_norm VARCHAR(30) NOT NULL UNIQUE CHECK (length(phrase_norm) >= 2),
      kind VARCHAR(8) NOT NULL CHECK (kind IN ('예산','해상도')),
      budget_won INTEGER CHECK (budget_won IS NULL OR budget_won BETWEEN 100000 AND 50000000),
      budget_bound VARCHAR(4) CHECK (budget_bound IS NULL OR budget_bound IN ('이하','이상')),
      resolution VARCHAR(8) CHECK (resolution IS NULL OR resolution IN ('1080p','1440p','4K')),
      memo VARCHAR(200),
      status VARCHAR(8) NOT NULL DEFAULT '미사용' CHECK (status IN ('사용','미사용')),
      created_by BIGINT,
      updated_by BIGINT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK ((kind = '예산' AND budget_won IS NOT NULL AND resolution IS NULL)
          OR (kind = '해상도' AND resolution IS NOT NULL AND budget_won IS NULL AND budget_bound IS NULL)))''')


def downgrade():
    op.execute('''DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM talk_text_fixes) THEN
        RAISE EXCEPTION '0151 downgrade refused: talk_text_fixes has rows';
      END IF; END $$''')
    op.execute('DROP TABLE talk_text_fixes')
