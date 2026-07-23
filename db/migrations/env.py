# 팝콘PC AI — Alembic 환경. 접속: 환경변수 DATABASE_URL (비밀번호는 절대 커밋 금지)
import os
from alembic import context
from sqlalchemy import create_engine

config = context.config


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 필요합니다. 예: "
            "postgresql+psycopg2://popcorn_app:<비번>@<HOST>:5432/popcorn_pc?sslmode=require"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
