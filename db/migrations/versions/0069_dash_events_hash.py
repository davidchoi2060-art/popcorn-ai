# -*- coding: utf-8 -*-
"""dash_events 중복 거르기 — event_hash 유니크 인덱스 (2026-08-27 결함 수정)

■ 왜 필요한가
  `POST /api/admin/dash/push` 가 같은 사건을 두 번 받으면(감시자 재시작 · 실패 뒤
  재시도 · 여러 세션이 동시에 같은 사건을 밀어 올림) 지금까지는 매번 새 행이 쌓였다
  — 서버 쪽에 중복을 막는 장치가 «전무»했다(확인자 실측: 같은 사건을 두 번 보내면
  `inserted:1` 이 매번 나오고 행이 둘 생김). 이 프로젝트는 **세션을 시작할 때마다
  감시자를 새로 띄우라고 지시**하므로(`CLAUDE.md` §첫 세션 시작 ④), 정상적인 사용
  패턴 자체가 중복을 쌓는다 — 재시작마다 최근 60건을 다시 밀어 올린다.

■ 지문(event_hash) — 누가 만드나
  `api/dash._event_hash()` 가 `who`·`ev_ts`·`blocks`(가리기 전 원문)로 sha1 을 낸다.
  **서버가 받은 내용으로 스스로 계산한다** — 감시자가 보낸 값을 신뢰하지 않는다
  (감시자·서버가 서로 다른 리비전의 `api/dash.py` 를 도는 배포 시차가 있을 수
  있어서다 — 감시자는 재시작 전까지 옛 코드를 계속 물고 있다).

■ 왜 유니크 인덱스인가(애플리케이션 검사 대신)
  삽입 직전에 SELECT 로 존재를 먼저 확인하는 방식은 두 요청이 거의 동시에 들어오면
  경합(TOCTOU)이 생긴다 — 두 요청 다 "없음"을 보고 둘 다 INSERT 한다. 유니크
  인덱스 + `INSERT ... ON CONFLICT (event_hash) DO NOTHING` 은 DB 가 원자적으로
  막아 그 경합이 없다.

■ NULL 허용 — 옛 행을 소급하지 않는다
  `event_hash` 는 nullable 이다. 이 마이그레이션 이전에 쌓인 행은 값을 채우지
  않는다 — `dash_events` 는 원장이 아니라 표시용 캐시라(0068 마이그레이션 설명
  §원장이 아니다) 소급할 이유가 없고, 사흘 뒤엔 어차피 정리 대상이다(0068
  §보관). Postgres 유니크 인덱스는 NULL 끼리 서로 충돌하지 않으므로 옛 행들과
  공존한다 — 새로 들어오는 행은 항상 값이 있으므로 그때부터 실제로 거른다.

Revision ID: 0069
Revises: 0068
"""
import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dash_events", sa.Column("event_hash", sa.String(40), nullable=True))
    op.create_index("ux_dash_events_hash", "dash_events", ["event_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_dash_events_hash", table_name="dash_events")
    op.drop_column("dash_events", "event_hash")
