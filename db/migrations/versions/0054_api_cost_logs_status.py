# -*- coding: utf-8 -*-
"""api_cost_logs.status/error_message -- 실패 호출도 남길 자리 (LLM 호출 래퍼 대비, 스키마만 · 적용 보류).

■ 왜 필요한가
  api/llm.py(LLM 호출 래퍼)가 프로바이더 호출 실패(네트워크 오류·프로바이더 4xx/5xx·
  안전 필터로 빈 응답 등)를 CLAUDE.md "실패를 삼키지 않는다" 원칙대로 예외로 올린다.
  그런데 지금 api_cost_logs(0001_initial_schema.py)는 log_id·provider·model·
  tokens_in·tokens_out·cost_usd·created_at 일곱 컬럼뿐이라 성공한 호출만 담을 수
  있다 -- 실패는 예외가 호출부까지 전파되고 나면 흔적이 서버 로그(stdout)에만 남고
  DB에는 전혀 남지 않는다. "오늘 비용이 왜 이렇게 낮지?"에 "성공이 적어서"인지
  "실패가 많아서"인지를 이 표만 보고는 답할 수 없다.

■ 지금 당장 쓰지 않는 이유
  api/llm.py는 이번 슬라이스에서 실패를 이 표에 쓰지 않는다 -- 컬럼이 없어서다.
  실패는 Python logging(서버 stdout)으로만 남긴다. 이 마이그레이션이 적용되면
  api/llm.py의 실패 경로에 status='error' INSERT를 추가하는 게 다음 단계다(그 변경은
  이 마이그레이션과 분리해서 낸다 -- 스키마가 없는데 코드가 먼저 그 컬럼을 쓰면 배포
  순서에 따라 500이 난다. 0052 계열이 겪은 것과 같은 종류의 문제).

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 -- DB에 적용하지 않는다 (DBA 소관)
  0051~0053과 같은 이유(하네스 권한 분류기가 alembic upgrade 실행을 막는다) +
  이번 작업 지시서가 "마이그레이션은 파일만, 적용 금지"를 명시했다.

■ 컬럼
  · `status` -- NOT NULL DEFAULT 'ok'. 기존 0행이라 백필 문제는 없다. 지금 코드가
    성공 기록만 쓰기 때문에 기본값을 'ok'로 둔다.
  · `error_message` -- nullable TEXT. 성공 행은 항상 NULL. 실패 사유 문자열은 예외
    메시지를 담되, 프로바이더 원문에 요청 정보(키 등)가 섞이지 않도록 호출부
    (api/llm.py)가 이미 정제한 메시지만 넘겨야 한다 -- 이 컬럼 자체는 그 정제를
    강제하지 않는다(스키마가 아니라 호출부 책임).
  · CHECK (status IN ('ok','error')) -- 닫힌 두 값. "차단됨"(캡 초과로 호출 자체를
    안 함)은 비용이 0이고 프로바이더를 부르지도 않아 이 표(비용 원장)의 대상이
    아니라고 판단했다 -- 차단 이력이 따로 필요해지면 별도 판단(다른 표 또는 다른
    축)이 필요하다. 이 마이그레이션의 범위 밖으로 남긴다(보고서 참고).

Revision ID: 0054
Revises: 0053
"""
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE api_cost_logs
          ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'ok'
            CHECK (status IN ('ok', 'error')),
          ADD COLUMN error_message TEXT;
    """)


def downgrade() -> None:
    # 원장성 표라 컬럼을 지우면 "그날 무엇이 실패했는지"가 함께 사라진다 -- 재고
    # 원장·사양 항목에서 이미 지킨 것과 같은 규칙(삭제는 열지 않는다). downgrade는
    # CHECK만 걷고 컬럼은 남긴다.
    op.execute("""
        ALTER TABLE api_cost_logs DROP CONSTRAINT IF EXISTS api_cost_logs_status_check;
    """)
