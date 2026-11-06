"""ASUS 기획전 끝단 검증 실행기 — CI 일회용 DB 전용 (2026-11-06).

CI 일회용 PostgreSQL 안의 전용 DB(asus_e2e_*)에서만 돈다. SCENARIO_E2E_DB=1 이고 DATABASE_URL 이 그 주소가
아니면 아무것도 하지 않고 멈춘다. 합성 운영자 두 명(operator · viewer)을 만들고, 실제 앱(uvicorn)을 띄워
tests/scenarios/asus_campaign_browser.cjs 로 Chrome 을 돌린다. 끝난 뒤 DB 를 다시 읽어 감사 · 상품 불변을 대조한다.
산출물: --out 폴더의 캡처 · results.json · db-check.json. 세션값은 파일로만 넘기고 끝나면 지운다.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

URL_RE = re.compile(r"postgresql\+psycopg2://ci:ci@127\.0\.0\.1:5432/asus_e2e_[0-9a-f]{12}")
PORT = 8765
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if os.environ.get("SCENARIO_E2E_DB") != "1" or not URL_RE.fullmatch(os.environ.get("DATABASE_URL") or ""):
        print("refused: not the disposable CI database", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import text

    from api import auth
    from api.db import engine

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with engine.begin() as c:
        ids = {}
        for role in ("operator", "viewer"):
            ids[role] = c.execute(text(
                "INSERT INTO admin_operators (name, email, role, status) VALUES (:n, :e, :r, '활성')"
                " RETURNING operator_id"),
                {"n": f"E2E {role}", "e": f"asus-e2e-{role}@ci.popcorn.invalid", "r": role}).scalar()
        cookies = {role: auth._new_session(c, oid, "asus-e2e", None) for role, oid in ids.items()}
        before = products_fingerprint(c, text)
        seed = {r["model_id"]: r["version"] for r in c.execute(text(
            "SELECT model_id, version FROM asus_campaign_models")).mappings()}
    secret = out.parent / "asus-e2e-sessions.json"
    secret.write_text(json.dumps({"cookie": auth.COOKIE, **cookies}), encoding="utf-8")

    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                              cwd=ROOT, stdout=(out / "server.log").open("wb"), stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{PORT}"
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/customer/asus-campaign", timeout=2).read()
                break
            except Exception:                           # noqa: BLE001
                time.sleep(1)
        else:
            print("server did not start", file=sys.stderr)
            return 1
        code = subprocess.call(["node", str(ROOT / "tests/scenarios/asus_campaign_browser.cjs"), base, str(secret), str(out)])
    finally:
        server.terminate()
        server.wait(timeout=20)
        secret.unlink(missing_ok=True)

    with engine.connect() as c:
        after = products_fingerprint(c, text)
        logs = c.execute(text("SELECT count(*) AS n, count(DISTINCT operator_id) AS who FROM admin_operator_activity_logs"
                              " WHERE target_kind='asus_campaign'")).mappings().one()
        rows = list(c.execute(text("SELECT model_id, version, origin, plan_review_price, updated_by"
                                   " FROM asus_campaign_models ORDER BY model_id")).mappings())
        inquiries = c.execute(text("SELECT count(*) FROM purchase_inquiries")).scalar()
    check = {"products_unchanged": before == after, "products": after, "audit_rows": logs["n"], "audit_operators": logs["who"],
             "operator_id": ids["operator"], "seed_versions": seed, "rows": [dict(r) for r in rows],
             "purchase_inquiries_after": inquiries}
    (out / "db-check.json").write_text(json.dumps(check, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(check, ensure_ascii=False, default=str))
    ok = check["products_unchanged"] and logs["n"] > 0 and logs["who"] == 1 and all(
        r["updated_by"] in (None, ids["operator"]) for r in rows)
    shutil.rmtree(out / "chrome-profile", ignore_errors=True)
    return code if code else (0 if ok else 1)


def products_fingerprint(conn, text):
    return dict(conn.execute(text(
        "SELECT count(*) AS n, COALESCE(sum(sale_price), 0)::text AS sale, COALESCE(sum(stock_qty), 0)::text AS stock,"
        " md5(COALESCE(string_agg(product_code::text || ':' || COALESCE(sale_price::text, '') || ':'"
        " || COALESCE(stock_qty::text, ''), ',' ORDER BY product_code), '')) AS digest FROM products")).mappings().one())


if __name__ == "__main__":
    raise SystemExit(main())
