# -*- coding: utf-8 -*-
"""spec_fill_runs — 웹 사양 채움 실행 원장 (ADM-AI-020 1a안, 스키마만 · 적용 보류).

■ 왜 필요한가
  사장님 확정(2026-08-15, `docs/design/spec-spec-fill.md`) 셋 중 하나가
  **"사람 없이 도는 실행"**이다 — 사람이 화면을 지켜보지 않는 동안 채움 담당(specfiller)이
  돈다는 뜻이다. 그런데 지금은 **"몇 번 돌았는지"조차 아무도 모른다** — 실측(2026-08-15):
  `spec_web_suggestions`에는 실행 단위 식별자가 없어 9시간짜리 수집 구간이 1회인지
  여러 번인지 시각 군집으로 짐작만 한다. 사람이 지켜보지 않는 실행일수록 "언제·누가
  요청·몇 건 찾음·몇 건 못 찾음"이 구조화돼 남아야 한다 — 그게 이 표다.

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 — DB에 적용하지 않는다
  하네스 권한 분류기가 지금 `alembic upgrade` 실행을 막고 있다(마이그레이션 0051도
  같은 이유로 파일만 있고 미적용). 우회하지 않는다.

  그래서 `api/admin_spec_fill.py`는 `api/auth.py`의 `_schema_ready()`와 같은 방식으로
  이 테이블의 존재 여부를 매 요청 확인하고, 없으면 "0건"이 아니라 **"실행 원장 신설
  필요"**를 돌려준다(화면이 스키마 없이도 죽지 않게). 이 마이그레이션이 실제로
  적용되기 전까지 그 상태가 계속된다 — 그 자체가 이 화면의 정직한 현재 상태다.

■ 실제로 이 표에 쓰는 코드는 아직 없다
  이 화면(admin_spec_fill.py)은 **읽기만** 한다(계약대로 정본·실행 로직을 갖지 않는다).
  실행 트리거는 여전히 기존 대시보드 큐(`POST /api/admin/dash/say`, `api/dash.py`,
  이 작업 담당 밖)이고, 그 큐를 읽어 채움 담당을 실제로 부르는 것은 사람(하네스 세션)이다
  — `api/dash.py`의 `say()` docstring이 이미 이 한계를 적어 뒀다("세션에 직접 밀어
  넣지 않는다 … 도중에는 못 읽는다"). 즉 "요청됨" 이후 "찾음/못찾음/완료"를 이 표에
  채우는 쓰기 경로는 **이번 작업 범위 밖**이고, 별도로 지어야 한다(요구사항 정의서
  §① "채움 담당을 API로 부를 수 있는 독립 경로 — 지금은 없다"). 그래서 지금 이
  테이블은 스키마만 있고(적용도 아직 안 됐고) 채워지는 행도 없다 — **거짓 "진행중"
  행을 만드느니 아예 만들지 않는 편**을 택했다(빈 스키마는 정직하지만, 아무도 못
  끝내는 "진행중" 행은 거짓말이 된다).

■ 컬럼
  · `field_name`     — 대상 필드. `spec_web_suggestions.field_name`과 같은 규약으로
    FK를 걸지 않는다(그 표도 마찬가지 — 사양 항목 정의는 삭제를 열지 않지만, 원장이
    정의 테이블에 종속되면 정의 쪽 사정으로 원장 조회가 막힐 수 있다).
  · `requested_by`   — `admin_operators.operator_id` 참조(nullable — 사람 없이 트리거되는
    경로가 나중에 생기면 NULL일 수 있다). 표시 이름은 조회 시 JOIN으로 구한다(스냅샷을
    또 두면 개명·탈퇴 시 둘이 갈린다).
  · `found_count`/`not_found_count` — NULL = "아직 모른다"(진행 중이거나, 완료 보고를
    못 받음). 0을 기본값으로 두지 않는다 — 0건 찾음과 "모름"은 다른 사실이다.
  · `status`         — '진행중'은 아직 못 끝난 실행. '응답없음'은 8초 내 전달 확인조차
    못 받은 경우(화면의 실행 상태 셋 중 하나, 정본은 화면 쪽 문구).

Revision ID: 0052
Revises: 0051
"""
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE spec_fill_runs (
          run_id           BIGSERIAL PRIMARY KEY,
          field_name       VARCHAR(50) NOT NULL,
          requested_count  INTEGER NOT NULL CHECK (requested_count BETWEEN 1 AND 500),
          requested_by     BIGINT REFERENCES admin_operators(operator_id),
          status           VARCHAR(20) NOT NULL DEFAULT '진행중'
                             CHECK (status IN ('진행중', '완료', '실패', '응답없음')),
          found_count      INTEGER,
          not_found_count  INTEGER,
          started_at       TIMESTAMP NOT NULL DEFAULT now(),
          finished_at      TIMESTAMP,
          note             TEXT,
          created_at       TIMESTAMP NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_spec_fill_runs_started ON spec_fill_runs (started_at DESC);
        CREATE INDEX idx_spec_fill_runs_field ON spec_fill_runs (field_name);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spec_fill_runs")
