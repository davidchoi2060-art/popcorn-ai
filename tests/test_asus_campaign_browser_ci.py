"""ASUS 기획전 브라우저 끝단 검증을 CI 단위 작업에서 돌린다 (2026-11-06).

POPCORN_CI=1 일 때만 돈다. CI 일회용 Postgres 안에 전용 DB(asus_e2e_*)를 새로 만들어 `alembic upgrade head` 를 적용하고,
실제 앱 + Chrome 으로 tests/scenarios/asus_campaign_browser.cjs 를 돌린 뒤 그 DB 를 지운다.
개발 PC 에서는 건너뛴다(Postgres 가 없고, 실제 DB 에 닿지 않게 하려는 것이다).
결과 전문은 GITHUB_STEP_SUMMARY 와 ASUS_E2E_OUT 폴더(기본 임시 폴더)에 남는다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_URL = "postgresql+psycopg2://ci:ci@127.0.0.1:5432/ci"
RUN = os.environ.get("POPCORN_CI") == "1" and os.environ.get("DATABASE_URL") == CI_URL


@unittest.skipUnless(RUN, "CI 일회용 Postgres 에서만 실행")
class AsusCampaignBrowser(unittest.TestCase):
    def test_admin_edit_save_reread_customer_at_1440_and_390(self):
        from sqlalchemy import create_engine, text

        if not (shutil.which("google-chrome") or os.environ.get("CHROME_BIN")):
            self.fail("Chrome 이 없습니다")
        name = "asus_e2e_" + uuid.uuid4().hex[:12]
        admin = create_engine(CI_URL, isolation_level="AUTOCOMMIT")
        out = Path(os.environ.get("ASUS_E2E_OUT") or tempfile.mkdtemp(prefix="asus-e2e-out-"))
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            env = dict(os.environ, DATABASE_URL=CI_URL.rsplit("/", 1)[0] + "/" + name, SCENARIO_E2E_DB="1")
            mig = subprocess.run(["alembic", "upgrade", "head"], cwd=ROOT / "db", env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(mig.returncode, 0, mig.stderr[-2000:])
            # 다시 적용해도 그대로(현재 리비전 유지)
            run = subprocess.run([sys.executable, "tests/scenarios/run_asus_campaign_browser.py", "--out", str(out)],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
            results_file = out / "results.json"
            results = json.loads(results_file.read_text(encoding="utf-8"))["results"] if results_file.exists() else []
            lines = [("PASS " if r["ok"] else "FAIL ") + "[" + r["kind"] + "] " + r["name"] for r in results]
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with open(summary, "a", encoding="utf-8") as f:
                    f.write("\n### ASUS 기획전 브라우저 끝단 검증\n```\n" + "\n".join(lines) + "\n" + run.stdout[-1500:] + "\n```\n")
            failed = [r for r in results if not r["ok"]]
            self.assertTrue(results, run.stdout[-1500:] + run.stderr[-1500:])
            self.assertEqual(failed, [], "\n--- runner stdout ---\n" + run.stdout[-6000:] + "\n--- runner stderr ---\n" + run.stderr[-800:])
            self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-800:])
        finally:
            with admin.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            admin.dispose()


if __name__ == "__main__":
    unittest.main()
