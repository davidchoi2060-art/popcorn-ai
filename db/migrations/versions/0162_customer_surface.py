"""상담 신청·견적 보관에 고객 화면 출처(mvp3/mvp4)를 남긴다 (2026-10-19 사장님 확정 — 서버·관리자단은 한 벌, 고객 화면만 둘).

`purchase_inquiries.surface` · `mvp3_saved_recommendations.surface` — 'mvp3' | 'mvp4' | NULL(알 수 없음).
값은 `api/customer_surface.surface_of()` 가 화면이 싣는 X-Popcorn-Surface 머리글로 정한다. 표시용 구분이다.

  · 기존 행은 건드리지 않는다(NULL = 출처를 남기기 전 기록). NULL 허용 칸과 CHECK 하나씩뿐이다.
"""
from alembic import op

revision = '0162'
down_revision = '0161'
branch_labels = None
depends_on = None

TABLES = ('purchase_inquiries', 'mvp3_saved_recommendations')


def upgrade():
    for t in TABLES:
        op.execute(f'ALTER TABLE {t} ADD COLUMN surface TEXT')
        op.execute(f"ALTER TABLE {t} ADD CONSTRAINT {t}_surface_chk CHECK (surface IN ('mvp3', 'mvp4'))")


def downgrade():
    for t in TABLES:
        op.execute(f'ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {t}_surface_chk')
        op.execute(f'ALTER TABLE {t} DROP COLUMN IF EXISTS surface')
