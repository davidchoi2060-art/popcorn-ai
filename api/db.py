"""DB 엔진 — 접속 정보는 루트 .env(커밋 금지)의 DATABASE_URL만 사용한다."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 환경변수가 필요합니다. 예: "
        "postgresql+psycopg2://popcorn_app:***@HOST:5432/popcorn_pc?sslmode=require"
    )

# Cloud SQL 공개 IP 경유 — 유휴 연결이 끊기므로 pre_ping + recycle 필수
#
# statement_timeout=15초 (2026-08-15 추가) — 실사고 근거: admin_dashboard.quote_quality()의
# 상관 서브쿼리 하나가 단독 11~14초, 경합 상태에서 18.6초→30초(타임아웃)→40초(타임아웃)
# →60초 무응답까지 악화됐다(EXPLAIN ANALYZE로 원인 확정 — loops=22840짜리 SubPlan).
# 그 쿼리 자체는 별도로 재작성해 20ms대로 고쳤다(admin_dashboard.py stock_drift) —
# 이 타임아웃은 「그 쿼리의 수정」이 아니라 **같은 부류의 다음 버그에 대한 안전망**이다.
# 실측 없이 걸면 정당한 작업을 끊을 수 있어 값을 정하기 전에 확인했다:
#   · 이 engine을 쓰는 라이브 요청 경로에서 가장 느린 정상 동작 = 견적 생성 2.1초
#     (CLAUDE.md 실측). 대량 쓰기(카테고리 일괄 이동 등)도 500~2,000행 단위로 쪼개
#     실행해 statement 하나가 초 단위를 넘지 않는다(admin_category_mapping.MAX_MOVE 등).
#   · **정말 오래 걸리는 배치**(tools/catalog_import.py·respec.py·reclassify.py·
#     backfill_tags.py·tests/regression.py)는 전부 이 engine을 쓰지 않고 **자체
#     create_engine()을 따로 연다**(코드 확인 — 여기서 타임아웃을 걸어도 그 경로는
#     영향받지 않는다).
# 15초는 정상 동작(2.1초)의 약 7배 여유를 두면서, 관측된 붕괴 구간(30·40·60초)보다
# 훨씬 앞에서 끊는다 — 무한 대기 대신 **에러로 실패**하게 만드는 것이 목적이다
# (실패를 삼키지 않는다는 원칙과 같다 — 지금은 60초 무응답이라는 형태로 실패를
# 삼키고 있다). psycopg2 connect_args로 검증: SELECT pg_sleep(20) 이 정확히 15.0초에
# QueryCanceled 로 끊기는 것을 확인했다.
#
# connect_timeout=10초 — 새 "연결 수립" 자체가 걸리는 경우를 막는다(공개 IP 경유라
# 네트워크 문제 시 libpq 기본값은 무제한 대기다). pre_ping은 이미 열린 연결이 죽었는지만
# 확인하고, 새로 연결을 여는 시간 자체는 별도로 방어해야 한다.
#
# pool_timeout=30초 — SQLAlchemy QueuePool의 기본값과 동일한 값이다(원래도 이 값으로
# 동작하고 있었다 — 여기 적은 것은 새 제약이 아니라 암묵적 기본값을 코드에 드러낸 것).
#
# ⚠ idle_in_transaction_session_timeout은 실측으로 0(무제한)임을 확인했지만 이번 판단
# 범위(statement_timeout·pool_timeout·connect_timeout) 밖이라 여기서는 건드리지 않는다.
# 이 저장소는 트랜잭션을 전부 `with engine.connect()`로 여닫아 예외가 나도 연결이
# 반환되므로 지금 당장의 위험은 낮다고 판단했다 — 필요하면 별도로 판단할 사안이다.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=15000",
    },
)
