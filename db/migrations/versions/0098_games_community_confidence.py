# -*- coding: utf-8 -*-
"""games.community_confidence - 커뮤니티 보강분의 신뢰도를 따로 기록한다.

왜 기존 games.confidence 를 쓰지 않는가:
  games.confidence(varchar 120) 는 **공식 사양표 출처의 신뢰도**를 적는 칸이고
  86종 전부 값이 차 있다("확인", "사양=미확보", "통칭/사양 산정 불가" 등).
  이번에 들어오는 값은 **커뮤니티 실사용 보강분의 신뢰도**로 의미가 다르다.
  같은 칸에 덮어쓰면 공식 사양 출처 정보가 사라진다(기존 사고와 같은 유형).
  그래서 칸을 새로 판다.

값: '확인' | '추정'
  확인 = 복수 출처 / 재현된 보고
  추정 = 단일 출처 · 개별 사례 기반. 조사자가 "병합 전 재확인 권고"라고 명시했다.
  견적 엔진은 '확인' 만 골라 쓸 수 있다.

Revision ID: 0098
Revises: 0097
"""
from alembic import op
import sqlalchemy as sa

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("community_confidence", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("games", "community_confidence")
