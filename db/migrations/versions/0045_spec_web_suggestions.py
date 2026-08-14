# -*- coding: utf-8 -*-
"""spec_web_suggestions — 웹 검색으로 채운 사양 제안 (제안 전용, product_specs 불가침).

■ 왜 필요한가
  다나와 수집(danawa_fetch.py)이 못 채우는 필드가 있다 — `cooler_tdp`는 다나와 상세
  페이지에도 없다(판매중·재고 있는 대기 중 최다 덩어리, 307건). 이 필드들은 제조사
  공식 자료·기타 웹 자료를 사람 대신 팀원(specfiller)이 검색해 채워야 한다.

  danawa_fetch.py는 출처가 다나와 한 곳이라 `product_reviews.detail` 문자열에 출처를
  녹여 넣는 것으로 충분했다. 웹 검색은 출처가 매번 다르므로(제조사 사이트·리테일러·
  리뷰 등) **출처를 구조화된 컬럼으로 남겨야** 다음 사람이 되짚을 수 있다 — CANON의
  crosschecker 규칙("근거 URL을 반드시 붙인다")과 같은 이유다.

■ 계약 (danawa_fetch.py와 동일선상)
  이 테이블에 쓴다고 정본이 되지 않는다. `product_reviews.suggested_value`에도 함께
  올려야 검수 화면(ADM-PRD-020)에 보이고, 승인 액션이 그제서야 `product_specs`에 쓴다.
  **이 마이그레이션은 테이블만 만든다 — product_reviews.suggested_value를 채우는 것은
  tools/spec_fill_apply.py 소관이다.**

  `applied_review_id`는 이 제안이 실제로 어느 검수 행의 suggested_value를 채웠는지
  가리킨다(nullable — 기록만 하고 아직 검수 행에 반영 못 한 경우가 있을 수 있어서다.
  예: 그 사이 검수 행이 다른 경로로 이미 처리된 경우).

Revision ID: 0045
Revises: 0044
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE spec_web_suggestions (
          id                 BIGSERIAL PRIMARY KEY,
          product_code       BIGINT NOT NULL REFERENCES products(product_code),
          field_name         VARCHAR(50) NOT NULL,
          suggested_value    VARCHAR(255) NOT NULL,   -- 표기 규약은 product_reviews와 동일
                                                       -- (JSONB 대상 필드는 JSON 배열 문자열)
          source_url         TEXT NOT NULL,           -- 근거 없는 제안은 없다
          source_name        VARCHAR(100),            -- '제조사 공식' / '다나와' 등 출처 종류
          confidence         NUMERIC(4,2),
          note               TEXT,
          fetched_at         TIMESTAMP NOT NULL DEFAULT now(),
          applied_review_id  BIGINT REFERENCES product_reviews(review_id),
          created_at         TIMESTAMP NOT NULL DEFAULT now()
        );

        CREATE INDEX idx_spec_web_suggestions_product
          ON spec_web_suggestions (product_code, field_name);
        CREATE INDEX idx_spec_web_suggestions_applied
          ON spec_web_suggestions (applied_review_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spec_web_suggestions")
