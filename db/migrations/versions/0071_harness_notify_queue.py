# -*- coding: utf-8 -*-
"""하네스 알림 큐(DB) — say() 의 로컬 파일 큐가 배포 서버에서 못 쓰는 문제를 우회한다
(요청 · 승인 결함⑦, 2026-08-27)

■ 왜 필요한가 — say() 의 파일 큐는 배포 서버에서 쓰기가 막혀 있다
  `api/dash.py`의 `say()`(`POST /api/admin/dash/say`)는 `ROOT/.claude/dash-queue.jsonl`
  (`QUEUE`)에 append 한다. 그런데 배포 서버의 systemd 유닛(`deploy/popcorn-api.service`)은
  `ProtectSystem=strict` + `ReadWritePaths=/srv/popcorn-ai/.cache` — **쓸 수 있는 경로가
  `.cache` 한 곳뿐**이고 `QUEUE`가 가리키는 `.claude/` 는 그 목록에 없다(2026-08-27 실측,
  파일을 직접 열어 확인함). 배포 서버에서 `say()`를 부르면 파일 쓰기가 막혀 실패한다 —
  화면은 "알렸다"고 말하는데 아무도 못 받는 사고가 난다(A-112 의 같은 병: 알림 장치는
  실패했을 때 «누가 아는가»를 함께 물어야 한다).

■ 이미 같은 제약을 두 번 우회했다 — 이번이 세 번째
  ① 캡처 · 프로필 사진 → Postgres BYTEA (`api/admin_profile_photo.py`,
     `admin_request_captures` — 디스크 대신 DB)
  ② 「진행 흐름」 표시 → `dash_events` 표(0068) — 로컬 감시자가 **로컬 → 배포**로 미는
     방향이라 이번과는 반대 방향이지만, "디스크 대신 DB" 라는 같은 판단이다.
  ③ (이 표) 하네스 알림 → **배포 서버 자신이 쓰는 큐를 DB로** — say() 의 파일 큐와
     나란히 두는 «짝»이다. 파일 큐를 대체하지 않는다 — 로컬 개발 서버는 지금도
     `say()`/파일 큐를 그대로 쓴다(관례를 안 깬다, `spec_fill.html.j2` 의 [실행] 단추가
     이미 그 경로를 쓰고 있다). 이 표는 **파일을 못 쓰는 프로세스**(배포 서버의
     `create_request()` 등)가 쓰는 자리다.

■ 읽는 쪽은 이미 있다 — 새로 만들 필요가 없다
  `scripts/dash_watch.py`의 `Server.poll()`이 30초마다 `GET /api/admin/dash/state?watcher=1`
  을 불러 응답의 `queued` 배열을 본다. `api/dash._queue_pending()`이 그 배열을 만드는데,
  **파일과 이 표를 합쳐서** 돌려주도록 고쳤다(같은 커밋) — `poll()`은 원소가 어디서
  왔는지 모른다(`{"ts":..., "text":...}` 모양만 본다), 그래서 `dash_watch.py`는 **한 글자도
  안 고쳤다.**

■ 원장이 아니다 — 읽히면(=하네스가 봤으면) 지운다고 보지 않고 «표시»만 한다
  `read_at IS NULL` 이 미읽음이다. `mark_read()`가 파일 큐와 이 표를 **한 번에** 마크한다
  (블랭킷 UPDATE — 파일 쪽의 기존 동작과 같은 정책: "지금 미읽음 전부"를 한꺼번에 읽음
  처리한다. 그 사이 새로 쓰인 것이 함께 읽음 처리되는 경합은 파일 큐도 이미 갖고 있던
  한계라 새로 만드는 위험이 아니다).

■ 보관 — 표시 캐시이지 원장이 아니므로 오래된 «읽은» 행만 지운다
  `dash_events`(사흘·5,000행)보다 느슨하게 잡았다 — 이 표는 쓰기 빈도가 훨씬 낮다
  (요청 하나당 한 행). 미읽음 행은 절대 안 지운다(감시자가 오래 꺼져 있어도 알림이
  사라지면 안 된다) — 삭제는 `notify_harness()`(api/dash.py)가 쓸 때마다
  "읽은 지 30일 지난 행"만 지운다.

Revision ID: 0071
Revises: 0070
"""
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS harness_notify_queue (
            notify_id  BIGSERIAL PRIMARY KEY,
            text       VARCHAR(2000) NOT NULL,
            source     VARCHAR(40),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at    TIMESTAMPTZ
        );
        CREATE INDEX idx_harness_notify_queue_unread
            ON harness_notify_queue (notify_id) WHERE read_at IS NULL;

        COMMENT ON TABLE harness_notify_queue IS
            '하네스 알림 큐(DB) — api/dash.py say()/QUEUE 파일 큐의 짝. 배포 서버가 systemd ProtectSystem=strict 로 .claude/ 에 못 쓰기 때문에 생겼다(요청·승인 결함⑦). 원장이 아니라 표시 캐시 — 읽은 지 30일 지난 행만 지운다';
        COMMENT ON COLUMN harness_notify_queue.source IS
            '무엇이 이 알림을 냈는지 — 예: work_request. 필터링용, 지금은 화면이 안 쓴다';
        COMMENT ON COLUMN harness_notify_queue.read_at IS
            'NULL = 미읽음. api/dash.py mark_read() 가 파일 큐와 함께 한 번에 마크한다(블랭킷 UPDATE)';
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_harness_notify_queue_unread;
        DROP TABLE IF EXISTS harness_notify_queue;
    """)
