# -*- coding: utf-8 -*-
"""작업 현황판 「진행 흐름」을 배포 서버에서도 보이게 — `dash_events` (2026-08-27 사장님 확정)

■ 왜 필요한가
  `api/dash.py` 는 로컬 PC 의 세션 전사본(`~/.claude/projects/E--DEV/*.jsonl`)을 **읽기만**
  한다. 배포 서버에는 그 폴더 자체가 없다(사장님 PC 전용 경로) — 그래서 `/admin2/dash` 를
  배포 서버에서 열면 「진행 흐름」이 항상 빈다. 이 표는 그 간극을 메우는 **중계 저장소**다:
  로컬 감시자(`scripts/dash_watch.py`)가 화면에 이미 보이는 사건만 골라 여기로 밀어 올리고,
  배포 서버는 로컬 파일 대신 이 표를 읽는다(`api/dash._state_server`).

■ 원장이 아니다 — 표시용 캐시다
  주문·재고 원장과 달리 **삭제해도 되돌릴 근거를 잃지 않는다**. 원본은 여전히 로컬 PC의
  세션 전사본이고, 이 표는 그중 화면에 보여줄 일부를 옮겨 둔 사본이다. 그래서 보관 기간을
  두고 지운다(아래 「보관」) — `stock_movements` 류의 「삭제 금지·역방향 전이만」 규칙은
  여기 적용되지 않는다.

■ 무엇을 담나 — «화면에 보이는 모양» 그대로
  `api/dash._event()` 가 세션 전사본 한 줄에서 뽑아내는 사건과 **같은 모양**
  (who · ts · blocks[{kind,name,detail,text}] · tokens · agents)이다. 원문 줄을 통째로
  옮기지 않는다 — 이미 `_event()`/`_tool_detail()`/`_scan()` 이 걸러낸 결과만 받는다.

■ 비밀값 — 받기 전에 한 번 더 가린다
  전사본에는 DB 접속 문자열·쿠키·`ADMIN_PW` 식별자가 실제로 섞여 있었다(2026-08-26 조사자
  전수 검사: 접속 문자열 2건 · 쿠키·세션 토큰류 241건 · `ADMIN_PW` 식별자 143건). 감시자가
  보내기 **전에** `api/dash._redact_event()` 로 한 번 가리고, 이 표로 들어오는 쓰기 API
  (`POST /api/admin/dash/push`)가 **같은 필터로 다시** 가린다(감시자 버전이 낡아도 서버가
  마지막 방어선이다). 가려진 자리는 원문 대신 `[가림 — 비밀값으로 보여 전송 제외]` 문구가
  들어간다 — 빈 칸이 아니라 「가려졌다」는 사실 자체를 보여준다.

■ 보관 — 무한히 크지 않는다
  원장이 아니므로 오래된 것은 지운다. 쓰기 API 가 삽입할 때마다 함께 정리한다(별도 배치
  불필요): **사흘 지난 행** 그리고 **최신 5,000행을 넘는 행**을 지운다. 화면이 실제로
  보여주는 건 `limit`(기본 40~60)뿐이라 5,000행이면 충분히 여유 있다. 푸시 자체가 영영
  끊기면(감시자 정지) 그 시점 이후로는 새 행도 안 쌓이므로 무한히 자라는 방향의 위험은 없다
  — 다만 그 경우 마지막 배치가 정리되지 않은 채 사흘까지는 남을 수 있다(다음 정상 푸시가
  오면 그때 함께 정리된다).

Revision ID: 0068
Revises: 0067
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dash_events",
        sa.Column("event_id", sa.BigInteger, primary_key=True, autoincrement=True),
        # 어느 로컬 세션에서 왔나 — 전사본 파일명(확장자 제외). 원장 대조용이 아니라
        # 「이 사건 뭉치가 어디서 왔는지」 되짚는 실마리다.
        sa.Column("session_id", sa.String(80)),
        # 전사본 사건 원래 시각 — dash_memos.event_ts 와 같은 규약(UTC ISO 문자열, 40자).
        sa.Column("ev_ts", sa.String(40)),
        sa.Column("who", sa.String(16)),                        # user / claude / result
        sa.Column("blocks", postgresql.JSONB, nullable=False),  # 화면이 그대로 그리는 사건 내용
        sa.Column("agents", postgresql.JSONB),                  # 관련 팀원 태그(있으면 필터에 쓴다)
        sa.Column("tokens", sa.Integer),
        sa.Column("source", sa.String(40)),                     # 예: "dash_watch"
        sa.Column("received_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_dash_events_received", "dash_events", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_dash_events_received", table_name="dash_events")
    op.drop_table("dash_events")
