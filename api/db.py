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
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
