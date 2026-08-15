# -*- coding: utf-8 -*-
"""product_sourcing_quotes.confirmed_at — 매입 확정 시각 (ADM-SRC-010, 스키마만 · 적용 보류).

■ 왜 필요한가
  화면 헤더 「오늘 확정 {n}건」(docs/design/spec-sourcing.md)이 `created_at`(견적을
  처음 "요청"한 날짜)으로 세고 있었다 — 확인자 실측(2026-08-15): 상품 39948·45551을
  당일 확정했는데도(활동 로그 sourcing_confirm 2건, 07:09·07:22) done_today가 세 번
  조회 모두 0이었다. 요청 → 회신 대기 → 확정까지 며칠 걸리는 것이 이 화면의 **정상
  흐름**이라 이 어긋남은 예외가 아니라 거의 항상 벌어지는 경우다.
  `confirm_quote()`(api/admin_sourcing.py)는 상태만 UPDATE하고 어떤 타임스탬프도
  남기지 않는다 — `replied_at`은 "회신을 적은 시각"이라 대안이 못 된다(같은 날
  회신·다음 날 확정이면 또 어긋난다). "확정한 시각" 자체를 남기는 컬럼이 필요하다.

■ ⚠⚠ 이 마이그레이션은 파일만 만든다 — DB에 적용하지 않는다
  하네스 권한 분류기가 `alembic upgrade` 실행을 막고 있다(마이그레이션 0051·0052도
  같은 이유로 파일만 있고 미적용). 우회하지 않는다.

  그래서 `api/admin_sourcing.py`는 `api/auth.py`의 `_schema_ready()`와 같은 방식으로
  이 컬럼의 존재 여부를 매 요청 확인한다(`_confirmed_at_ready()`) — 없으면 "오늘
  확정 0건"을 자신 있게 말하지 않고 `done_today: null` + 이유 문구
  (`done_today_reason`)를 돌려준다. 이 마이그레이션이 실제로 적용되기 전까지 그
  상태가 계속된다 — 그 자체가 이 화면의 정직한 현재 상태다.

■ 컬럼
  · `confirmed_at` — nullable TIMESTAMP. 이 마이그레이션이 적용되기 «전에» 이미
    '확정' 상태였던 행(예: quote_id 2·6·8)은 정확히 언제 확정됐는지 우리가 모른다 —
    지어내지 않고 NULL로 남는다(CLAUDE.md "모르는 과거는 지어내지 않는다 — 기초
    재고로 기록한다"와 같은 원칙: 모르는 과거를 그럴듯한 값으로 채우지 않는다).
    적용 이후 `confirm_quote()`가 새로 확정하는 건부터 실제 시각이 찍힌다.
  · 부분 인덱스(`WHERE confirmed_at IS NOT NULL`) — "오늘 확정 {n}건"이 매 목록
    조회마다 도는 COUNT라 `status='확정'` 행 대다수(과거 확정 전량)가 앞으로도
    NULL로 남을 것을 감안했다. status 조건은 함께 못 걸었다(status는 인덱스
    후보 컬럼이 아니라 상수 리터럴 '확정'이라 부분 인덱스 조건에 넣어도 실제
    쿼리(WHERE status='확정' AND confirmed_at::date=...)가 그대로 이 인덱스를
    탈 수 있다 — Postgres는 조건이 인덱스 조건을 포함(imply)하면 부분 인덱스를
    쓴다).

Revision ID: 0053
Revises: 0052
"""
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE product_sourcing_quotes
          ADD COLUMN confirmed_at TIMESTAMP;

        CREATE INDEX idx_sourcing_quotes_confirmed_at
          ON product_sourcing_quotes (confirmed_at)
          WHERE confirmed_at IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_sourcing_quotes_confirmed_at;
        ALTER TABLE product_sourcing_quotes DROP COLUMN IF EXISTS confirmed_at;
    """)
