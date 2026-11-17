"""스케줄 가드 — 루프백 DB 에서는 «운영 프록시라고 스스로 밝힌 배포»만 스케줄을 켠다.

운영은 Cloud SQL Proxy(127.0.0.1:5432)로 붙는다. 예전 판정(루프백이면 무조건 끔)을 그대로
두면 운영에서 쇼핑몰 가격 자동 반영과 보존기간 파기가 조용히 멈춘다. 반대로 조건을 느슨하게
풀면 CI·개인 PC 가 쇼핑몰에 요청을 보낸다. 그래서 조건 하나가 빠질 때마다 꺼지는지를 본다.
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://ci:ci@127.0.0.1:1/ci")

from api import mall_price_auto as AUTO
from api import retention_purge as RP
from api.scheduler_guard import database_schedule_allowed

GUARD_KEYS = ("DATABASE_URL", "CLOUD_SQL_INSTANCE_CONNECTION_NAME", "POPCORN_EXPECTED_DATABASE",
              "POPCORN_CLOUD_SQL_PROXY_SCHEDULE_ENABLED", "POPCORN_ENVIRONMENT",
              "POPCORN_DEPLOYMENT_PHASE", "MALL_PRICE_AUTO_SCHEDULE", RP.SCHEDULE_ENV)

# 형식만 맞춘 가짜 값이다 — 실제 프로젝트·인스턴스·DB 이름이 아니다.
PROXY = {
    "DATABASE_URL": "postgresql+psycopg2://app:pw@127.0.0.1:5432/fixture_prod_db",
    "CLOUD_SQL_INSTANCE_CONNECTION_NAME": "fixture-project:asia-northeast3:fixture-db",
    "POPCORN_EXPECTED_DATABASE": "fixture_prod_db",
    "POPCORN_CLOUD_SQL_PROXY_SCHEDULE_ENABLED": "1",
    "POPCORN_ENVIRONMENT": "production",
    "POPCORN_DEPLOYMENT_PHASE": "production",
}


class SchedulerGuardTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in GUARD_KEYS:
            os.environ.pop(key, None)

    def use(self, **overrides):
        for key in PROXY:
            os.environ.pop(key, None)
        values = dict(PROXY, **overrides)
        os.environ.update({k: v for k, v in values.items() if v is not None})

    def test_remote_database_keeps_the_old_default(self):
        os.environ["DATABASE_URL"] = "postgresql+psycopg2://u:p@10.1.2.3:5432/db"
        self.assertTrue(database_schedule_allowed())
        os.environ["DATABASE_URL"] = "postgresql://u:p@db.example/x"
        self.assertTrue(database_schedule_allowed())

    def test_missing_or_malformed_url_is_off(self):
        self.assertFalse(database_schedule_allowed())
        for bad in ("", "not a url", "postgresql://"):
            with self.subTest(bad=bad):
                os.environ["DATABASE_URL"] = bad
                self.assertFalse(database_schedule_allowed())

    def test_plain_loopback_is_off(self):
        for host in ("127.0.0.1", "localhost", "[::1]"):
            with self.subTest(host=host):
                os.environ["DATABASE_URL"] = f"postgresql+psycopg2://ci:ci@{host}:5432/ci"
                self.assertFalse(database_schedule_allowed())

    def test_declared_production_proxy_is_on(self):
        self.use()
        self.assertTrue(database_schedule_allowed())

    def test_each_missing_or_wrong_declaration_turns_it_off(self):
        cases = {
            "switch missing": dict(POPCORN_CLOUD_SQL_PROXY_SCHEDULE_ENABLED=None),
            "switch not 1": dict(POPCORN_CLOUD_SQL_PROXY_SCHEDULE_ENABLED="true"),
            "environment": dict(POPCORN_ENVIRONMENT="development"),
            "environment missing": dict(POPCORN_ENVIRONMENT=None),
            "phase": dict(POPCORN_DEPLOYMENT_PHASE="preview"),
            "phase missing": dict(POPCORN_DEPLOYMENT_PHASE=None),
            "connection missing": dict(CLOUD_SQL_INSTANCE_CONNECTION_NAME=None),
            "connection shape": dict(CLOUD_SQL_INSTANCE_CONNECTION_NAME="fixture-project/fixture-db"),
            "connection uppercase": dict(CLOUD_SQL_INSTANCE_CONNECTION_NAME="Fixture:asia-northeast3:db"),
            "expected database missing": dict(POPCORN_EXPECTED_DATABASE=None),
            "expected database empty": dict(POPCORN_EXPECTED_DATABASE=""),
            "other database": dict(POPCORN_EXPECTED_DATABASE="another_db"),
            "other port": dict(DATABASE_URL="postgresql+psycopg2://app:pw@127.0.0.1:5433/fixture_prod_db"),
            "no port": dict(DATABASE_URL="postgresql+psycopg2://app:pw@127.0.0.1/fixture_prod_db"),
            "localhost name": dict(DATABASE_URL="postgresql+psycopg2://app:pw@localhost:5432/fixture_prod_db"),
            "ipv6 loopback": dict(DATABASE_URL="postgresql+psycopg2://app:pw@[::1]:5432/fixture_prod_db"),
            "other backend": dict(DATABASE_URL="mysql+pymysql://app:pw@127.0.0.1:5432/fixture_prod_db"),
        }
        for name, override in cases.items():
            with self.subTest(case=name):
                self.use(**override)
                self.assertFalse(database_schedule_allowed())

    def test_both_schedulers_follow_the_guard_and_their_own_switch(self):
        self.use()
        self.assertTrue(AUTO.scheduler_enabled())
        self.assertTrue(RP.scheduler_enabled())
        with patch.dict(os.environ, {"MALL_PRICE_AUTO_SCHEDULE": "off", RP.SCHEDULE_ENV: "off"}):
            self.assertFalse(AUTO.scheduler_enabled())
            self.assertFalse(RP.scheduler_enabled())
        self.use(POPCORN_DEPLOYMENT_PHASE="preview")
        self.assertFalse(AUTO.scheduler_enabled())
        self.assertFalse(RP.scheduler_enabled())


if __name__ == "__main__":
    unittest.main()
