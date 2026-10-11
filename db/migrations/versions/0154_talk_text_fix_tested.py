"""상담 해석 바로잡기 — 시험한 값만 «사용»으로 올린다 (2026-10-11 코덱스 검수 #111 · 사장님 「고치기」).

화면은 «미사용으로 저장 → 시험 → 사용»을 안내했지만 API 는 처음부터 «사용»으로 만들 수 있었다.
이제 서버가 그 순서를 지킨다. 저장된 규칙을 시험해 그 규칙이 실제로 문장에 맞았을 때만
그 값의 지문을 남기고(`tested_sig`), «사용»으로 올릴 때 지금 값의 지문과 같아야 한다.

  · `tested_sig`  시험한 값의 지문(표현 · 종류 · 예산 · 경계 · 해상도). 메모는 넣지 않는다.
  · `tested_at` · `tested_by`  언제 · 누가 시험했나.

**기존 행은 바꾸지 않는다.** 이미 «사용»인 규칙은 값이 그대로면 그대로 저장할 수 있다.
"""
from alembic import op

revision = '0154'
down_revision = '0153'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE talk_text_fixes ADD COLUMN tested_sig VARCHAR(120),'
               ' ADD COLUMN tested_at TIMESTAMPTZ, ADD COLUMN tested_by BIGINT')


def downgrade():
    op.execute('ALTER TABLE talk_text_fixes DROP COLUMN tested_by, DROP COLUMN tested_at, DROP COLUMN tested_sig')
