# -*- coding: utf-8 -*-
"""배포 전 사전 점검 — 서버에서 돌려 "지금 올려도 되는가"를 확인한다.

실행(서버):  sudo -u popcorn /srv/popcorn-ai/.venv/bin/python deploy/preflight.py
실행(로컬):  .venv/Scripts/python deploy/preflight.py

**통과 못 하는 항목이 있으면 배포하지 않는다.** 특히 Basic Auth와 바인드 주소는 지금
유일한 실질 방벽이다(로그인이 dev 어댑터이므로).
"""
import io
import os
import socket
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails, warns = [], []


def check(name, ok, detail=""):
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def warn(name, detail):
    print(f"  [WARN] {name} - {detail}")
    warns.append(name)


print("=" * 70)
print("팝콘PC AI 배포 사전 점검")
print("=" * 70)

# ── 1. 환경변수 ────────────────────────────────────────────────
print("\n[1] 환경변수")
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass
db_url = os.environ.get("DATABASE_URL", "")
check("DATABASE_URL 설정", bool(db_url))
boot = os.environ.get("ADMIN_BOOTSTRAP_EMAILS", "").strip()
check("ADMIN_BOOTSTRAP_EMAILS 설정", bool(boot),
      "첫 관리자가 없으면 아무도 승인할 수 없다")
if boot and len([e for e in boot.split(",") if e.strip()]) > 1:
    warn("부트스트랩 이메일이 여러 개", "자동 owner가 되는 계정은 최소로 두는 편이 안전하다")
secure = os.environ.get("COOKIE_SECURE", "").strip() in ("1", "true", "True", "yes")
print(f"  [INFO] COOKIE_SECURE = {'켜짐(HTTPS 전용)' if secure else '꺼짐(HTTP 운영)'}")

# ── 2. DB ─────────────────────────────────────────────────────
print("\n[2] 데이터베이스")
if db_url:
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine(db_url)
        with eng.connect() as c:
            ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            check("마이그레이션 최신(0011)", ver == "0011", f"현재 {ver}")
            n_prod = c.execute(text("SELECT count(*) FROM products")).scalar_one()
            check("상품 적재됨", n_prod > 1000, f"{n_prod:,}건")
            n_real = c.execute(text(
                "SELECT count(*) FROM products WHERE data_origin='real'")).scalar_one()
            n_demo = n_prod - n_real
            print(f"  [INFO] real {n_real:,} · demo {n_demo:,}")
            pool = c.execute(text(
                "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty>0")).scalar_one()
            check("추천 후보 존재", pool > 0, f"{pool:,}건")
            rev = c.execute(text(
                "SELECT count(*) FROM product_reviews WHERE review_status='대기'")).scalar_one()
            print(f"  [INFO] 검수 대기 {rev:,}건 (직원이 처리할 실제 작업량)")
            ops = c.execute(text(
                "SELECT count(*) FROM admin_operators WHERE role='owner' AND status='활성'")).scalar_one()
            check("활성 관리자 1명 이상", ops >= 1, f"{ops}명")
    except Exception as e:
        check("DB 접속", False, f"{type(e).__name__}: {e}"[:140])
else:
    check("DB 접속", False, "DATABASE_URL 없음")

# ── 3. 앱 로드 ─────────────────────────────────────────────────
print("\n[3] 앱")
try:
    from api.main import app
    routes = len(app.routes)
    check("FastAPI 앱 로드", routes > 20, f"라우트 {routes}개")
except Exception as e:
    check("FastAPI 앱 로드", False, f"{type(e).__name__}: {e}"[:140])

# ── 4. 배포 산출물 ─────────────────────────────────────────────
print("\n[4] 배포 산출물")
for rel in ("deploy/popcorn-api.service", "deploy/nginx-popcorn.conf", "deploy/README.md"):
    check(rel, os.path.exists(os.path.join(ROOT, rel)))

# ── 5. 노출 점검(서버에서만 의미 있음) ──────────────────────────
print("\n[5] 노출 점검")


def listening(host, port):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


if os.name != "nt":
    ht = "/etc/nginx/.htpasswd-popcorn"
    check("Basic Auth 파일 존재", os.path.exists(ht),
          "없으면 사이트가 무방비로 열린다")
    check("nginx 설정 링크", os.path.exists("/etc/nginx/sites-enabled/popcorn"))
    if os.path.exists("/etc/nginx/sites-enabled/default"):
        warn("nginx default 사이트가 살아 있음", "봉쇄되지 않은 경로가 생길 수 있다 — 제거 권장")
    envf = "/etc/popcorn-ai.env"
    if os.path.exists(envf):
        mode = oct(os.stat(envf).st_mode)[-3:]
        check("환경변수 파일 권한 600", mode == "600", f"현재 {mode}")
    else:
        check("환경변수 파일 존재", False, envf)
else:
    print("  [SKIP] 서버 전용 점검(로컬 Windows)")

print("\n" + "=" * 70)
if fails:
    print(f"실패 {len(fails)}건 — 배포하지 않는다: {', '.join(fails)}")
elif warns:
    print(f"통과(경고 {len(warns)}건): {', '.join(warns)}")
else:
    print("전 항목 통과 — 배포 가능")
print("=" * 70)
sys.exit(1 if fails else 0)
