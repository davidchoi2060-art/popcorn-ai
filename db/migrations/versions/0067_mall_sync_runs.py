# -*- coding: utf-8 -*-
"""몰 공급처·가격 일일 자동 반영 — 실행 이력(mall_sync_runs).

■ 배경 (2026-08-27, 사장님 지시 — 몰 공급처·가격 자동 갱신)
  `tools/mall_daily_sync.py`(새벽 systemd timer)가 매일 새벽 한 번 ①추천 후보 목록
  ②몰에서 공급처·가격 수집 ③「가능」 최저가로 매입가·판매가 재계산 ④전 공급처
  품절 상품 후보 제외를 자동으로 돈다. 이 배치는 **배포 서버**에서 돌고, 그 결과를
  확인할 사람은 **관리자 대시보드**(`/admin2/`, admin.popcornai.co.kr)에서 본다 —
  작업 현황판(`api/dash.py`)은 하네스의 로컬 세션 전사본(`~/.claude/projects/...`)을
  읽는 화면이라 배포 서버에서 도는 배치의 결과가 거기까지 닿을 길이 없다(2026-08-27
  사장님 확인 — "알림 위치는 작업 현황판이 아니라 대시보드"). 그래서 실행 결과를
  **DB에 남기고 대시보드가 그것을 읽는다.**

■ 이 표가 답해야 하는 것 (지시서 그대로)
  언제 · 성공/실패 · 수집 건수 · 가격 변경 건수 · 보류 건수 · 후보 제외 건수 ·
  실패 사유. 대시보드는 "가장 최근 실행 한 건"만 보여주면 되므로 `admin_operator_
  activity_logs`(이력 스트림 — 여러 화면이 최근 3건 · 검색용으로 쓴다)에 얹기보다
  **실행 단위로 한 행**인 전용 표가 낫다고 판단했다(대시보드 코드가 `ORDER BY
  run_id DESC LIMIT 1` 하나로 끝난다 — activity_logs에서 매번 `action='...'`으로
  걸러 최신을 찾는 것보다 명확하고, 다른 화면들의 "최근 활동" 스트림에도 안 섞인다).

  다만 **개별 상품의 되돌리기 근거(before 스냅샷)는 이 표에 두지 않는다** —
  A-115·A-116과 같은 모양으로 `admin_operator_activity_logs`에 남긴다(그래야 기존
  되돌리기 절차·`activity-logs` 화면과 같은 방식으로 다뤄진다). `reprice_log_id`·
  `exclude_log_id`가 그 로그로 가는 다리다 — 이 표는 "그날 무슨 일이 있었나
  요약"만, 되돌릴 근거는 지금까지 하던 자리에 그대로 둔다(같은 것을 두 벌 두지
  않는다).

■ ok가 NULL일 수 있는 이유
  실행 시작 시점에 `started_at`만으로 한 행을 먼저 넣고(진행 중 상태를 남긴다),
  끝나면 그 행을 UPDATE한다. 프로세스가 도중에 죽으면(정전·OOM 등) `finished_at`·
  `ok`가 영원히 NULL로 남는데, 이것도 정보다 — 대시보드가 "started_at만 있고 오래
  지났다"를 "응답 없음"으로 보여줄 근거가 된다(모르는 것을 지어내지 않는다 —
  성공도 실패도 아니라고 참으로 말한다).

Revision ID: 0067
Revises: 0066
"""
from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS mall_sync_runs (
          run_id               BIGSERIAL PRIMARY KEY,
          started_at           TIMESTAMP NOT NULL DEFAULT now(),
          finished_at          TIMESTAMP,
          ok                   BOOLEAN,           -- NULL=진행 중(또는 응답 없이 죽음)
          fail_reason          VARCHAR(300),
          target_count         INTEGER,           -- 1단계: 추천 후보 수
          collected_count      INTEGER,           -- 2단계: 몰에서 실제로 읽은 상품 수
          price_changed_count  INTEGER,           -- 3단계: 매입가·판매가가 바뀐 상품 수
          held_count           INTEGER,           -- 3단계: 큰 변동이라 보류한 상품 수
          excluded_count       INTEGER,           -- 4단계: 전 공급처 품절이라 후보에서 뺀 수
          -- 개별 상품 before 스냅샷은 여기 두지 않는다(위 모듈 docstring 참조) —
          -- 아래 두 컬럼이 admin_operator_activity_logs 의 해당 행을 가리킨다.
          reprice_log_id       BIGINT REFERENCES admin_operator_activity_logs(log_id),
          exclude_log_id       BIGINT REFERENCES admin_operator_activity_logs(log_id),
          detail               JSONB              -- 보류 건 표본 등 요약이 못 담는 부가 정보
        )
    """)
    # 대시보드는 "가장 최근 한 건"만 본다 — 최신순 조회가 유일한 조회 패턴이라
    # 이 인덱스 하나로 충분하다(다른 정렬·필터가 없다).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mall_sync_runs_started_at"
        " ON mall_sync_runs (started_at DESC)")


def downgrade() -> None:
    # 이 표를 지우면 "그동안 몰 갱신이 언제 성공/실패했나"를 통째로 잃는다 —
    # 사양 항목 컬럼(0025 등)과 같은 규칙으로 downgrade는 no-op.
    pass
