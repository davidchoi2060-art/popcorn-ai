# -*- coding: utf-8 -*-
"""지금 상태 — **문서를 읽지 않고 전부 잰다** (2026-08-12)

■ 왜 만드나 — 사용자 지적
  *"컨텍스트가 날아가면 압축돼서 과거 이력을 제대로 파악 못 하고, 서버 구성이나 PC 구성도
  현행화가 안 돼 있어서 같은 일을 반복하고, 일주일 지나면 다시 처음부터 하는 느낌이 든다."*

  이 프로젝트는 이미 그 병을 여러 번 앓았다:
      HANDOFF.md 가 20커밋 뒤처진 채 **범위를 정반대로** 말하고 있었다
      감사 문서의 「고칠 것 셋」이 셋 다 이미 고쳐져 있었고, 그걸 믿고 고치다 결함을 하나 만들었다
      CLAUDE.md 가 폐기된 색 `#005ab3` 을 들고 있었다
      지금 이 순간도 CLAUDE.md 는 products 22,838 · 후보 3,087 이라 적혀 있는데 실제와 다르다

  **원인은 «안 적어서»가 아니라 «적어서»다.** 상태를 문서에 적는 순간 그것은 낡기 시작하고,
  다음 세션은 낡은 것을 사실로 읽는다. 그리고 문서는 자기가 낡았다고 말해 주지 않는다.

■ 그래서 규칙은 하나다
      **낡는 것(수·상태)은 적지 말고 잴 수 있게 만든다.**
      **안 낡는 것(결정·이유·사고 경위)만 적는다.**

  이 스크립트가 앞의 절반을 맡는다. 새 세션은 문서를 믿는 대신 이걸 돌린다.
  뒤의 절반은 `docs/decisions/decision-log.md`(결정) 와 커밋 메시지(왜)가 맡는다.

■ 두 가지를 코드로 강제한다 (오늘 둘 다 당했다)
  ① **쿼리마다 새 연결** — 하나가 실패하면 트랜잭션이 죽어 나머지가 전부 «실패»로 보인다
  ② **못 잰 것은 「못 쟀다」고 말한다** — 0 과 측정 실패는 다르다. 조용히 넘기지 않는다

■ 쓰는 법
      .venv/Scripts/python scripts/state.py
      .venv/Scripts/python scripts/state.py --no-net     # 망 없이 (DB·로컬만)
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# `python scripts/state.py` 로 부르면 sys.path[0] 이 scripts/ 라 `api.db` 를 못 찾는다.
# 그러면 전부 「못 쟀음」이 되는데, 그건 **DB 가 죽은 것과 구분되지 않는다** — 여기서 막는다.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
LOCAL = "http://127.0.0.1:8000"
SERVER = "https://admin.popcornai.co.kr"
MISS = "못 쟀음"


def sh(*a: str) -> str:
    try:
        return subprocess.run(a, cwd=ROOT, capture_output=True,
                              timeout=20).stdout.decode("utf-8", "ignore").strip()
    except Exception:                                        # noqa: BLE001
        return ""


def get(url: str, timeout: int = 12):
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:                                        # noqa: BLE001
        return 0, b""


def one(sql: str):
    """쿼리 하나 = 연결 하나. 실패해도 다음 쿼리가 산다 — 오늘 여기서 당했다."""
    try:
        from sqlalchemy import text
        from api.db import engine
        with engine.connect() as c:
            return c.execute(text(sql)).scalar()
    except Exception as e:                                   # noqa: BLE001
        return "%s (%s)" % (MISS, type(e).__name__)


def head(t: str) -> None:
    print()
    print("■ " + t)


def row(k: str, v) -> None:
    print("   %-16s %s" % (k, v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true")
    a = ap.parse_args()
    net = not a.no_net

    print("=" * 72)
    print("지금 상태 — 전부 방금 잰 값이다 (문서에서 읽지 않았다)")
    print("=" * 72)

    # ── 코드 ────────────────────────────────────────────────────────
    head("코드")
    row("HEAD", sh("git", "log", "-1", "--format=%h %ad %s", "--date=short")[:66] or MISS)
    dirty = [x for x in sh("git", "status", "--porcelain").splitlines() if x.strip()]
    row("미커밋", "%d개 %s" % (len(dirty), " ".join(x[3:][:24] for x in dirty[:3])) if dirty else "없음")
    ahead = sh("git", "rev-list", "--count", "origin/main..HEAD")
    row("미푸시", (ahead + "커밋") if ahead and ahead != "0" else "없음")

    # ── 붙어 있는 곳 ────────────────────────────────────────────────
    head("붙어 있는 곳")
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
        u = urlparse(os.environ.get("DATABASE_URL", ""))
        shared = u.hostname not in ("127.0.0.1", "localhost", "::1", None)
        row("DB", "%s / %s%s" % (u.hostname, (u.path or "").lstrip("/"),
                                 "   ← **로컬·서버 공유**" if shared else "  (로컬 전용)"))
    except Exception as e:                                   # noqa: BLE001
        row("DB", "%s (%s)" % (MISS, type(e).__name__))
    row("마이그레이션", one("SELECT version_num FROM alembic_version"))
    if net:
        st, _ = get(LOCAL + "/api/ops", 5)
        row("로컬 API", "%s  %s" % (LOCAL, "떠 있음" if st == 200 else "안 뜸(%s)" % (st or "연결 실패")))
        st, _ = get(SERVER + "/api/ops")
        row("배포 서버", "%s  %s" % (SERVER, "200" if st == 200 else str(st or "연결 실패")))

    # ── 배포가 닿았나 ───────────────────────────────────────────────
    if net:
        head("배포 — 로컬 파일이 서버에도 있나")
        import hashlib
        pairs = [("mockups/mvp1/s4-cart.html", "/mvp1/s4-cart.html"),
                 ("mockups/mvp1/s5-complete.html", "/mvp1/s5-complete.html"),
                 ("design-system/tokens.css", "/design-system/tokens.css")]
        for f, url in pairs:
            try:
                lb = io.open(os.path.join(ROOT, f), "rb").read()
            except OSError:
                row(os.path.basename(f), MISS + " (로컬에 없음)")
                continue
            st, sb = get(SERVER + url)
            if st != 200:
                row(os.path.basename(f), "%s (서버 %s)" % (MISS, st or "연결 실패"))
                continue
            d = lambda b: hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()[:10]
            row(os.path.basename(f), "같음" if d(lb) == d(sb) else "**다름 — 배포 안 됨**")
        print("   (전수 대조는 scripts/verify_deploy.py)")

    # ── 운영 스위치 ─────────────────────────────────────────────────
    head("운영 스위치 — 고객 흐름을 실제로 가른다")
    if net:
        st, b = get(SERVER + "/api/ops")
        if st == 200:
            try:
                m = json.loads(b)
                row("서버", " · ".join("%s=%s" % (k, m[k]) for k in sorted(m)))
                own = [k for k in m if m[k] == "own"]
                row("자체 처리", ", ".join(own) if own else "없음 (전부 몰 인계)")
            except Exception:                                # noqa: BLE001
                row("서버", MISS + " (응답을 못 읽음)")
        else:
            row("서버", "%s (%s)" % (MISS, st or "연결 실패"))
    else:
        row("서버", "건너뜀 (--no-net)")

    # ── 데이터 ──────────────────────────────────────────────────────
    head("데이터 — 이 수를 문서에 옮겨 적지 마라")
    row("products", one("SELECT COUNT(*) FROM products"))
    row("  real/demo", "%s / %s" % (
        one("SELECT COUNT(*) FROM products WHERE data_origin IS DISTINCT FROM 'demo'"),
        one("SELECT COUNT(*) FROM products WHERE data_origin = 'demo'")))
    row("추천 후보", one("SELECT COUNT(*) FROM v_recommendation_candidates"))
    row("검수 대기", one("SELECT COUNT(*) FROM product_reviews WHERE review_status = '대기'"))
    row("호환 규칙(활성)", one("SELECT COUNT(*) FROM compat_rules WHERE active"))
    row("사양 항목", one("SELECT COUNT(*) FROM spec_field_defs"))
    row("용도 하한", one("SELECT COUNT(*) FROM usage_floors"))
    row("인계 원장", one("SELECT COUNT(*) FROM handoffs"))
    row("주문 원장", one("SELECT COUNT(*) FROM orders"))

    # ── 화면 ────────────────────────────────────────────────────────
    head("화면")
    cust = glob.glob(os.path.join(ROOT, "mockups", "mvp1", "*.html"))
    adm = [p for p in glob.glob(os.path.join(ROOT, "mockups", "admin", "*.html"))
           if "data-screen-id" in io.open(p, encoding="utf-8", errors="ignore").read()]
    row("고객 목업", "%d개" % len(cust))
    row("관리자 목업", "%d개" % len(adm))
    try:
        from api.admin_nav import counts
        c = counts()
        row("LNB", "%d그룹 %d항목 — 재구축 %d · 신설예정 %d"
            % (c["groups"], c["total"], c["new"], c["todo"]))
    except Exception as e:                                   # noqa: BLE001
        row("LNB", "%s (%s)" % (MISS, type(e).__name__))

    # ── 문서가 낡았는지 ─────────────────────────────────────────────
    head("문서 신선도 — 낡았으면 믿지 마라")
    for doc in ("HANDOFF.md", "CLAUDE.md", "docs/design/screen-flow.md"):
        last = sh("git", "log", "-1", "--format=%h", "--", doc)
        n = sh("git", "rev-list", "--count", "%s..HEAD" % last) if last else ""
        when = sh("git", "log", "-1", "--format=%ad", "--date=short", "--", doc)
        mark = "  ← 의심" if (n.isdigit() and int(n) >= 10) else ""
        row(doc, "%s · 그 뒤 %s커밋%s" % (when or MISS, n or "?", mark))

    print()
    print("-" * 72)
    print("이 값들은 **지금 잰 것**이다. 문서로 옮기면 그 순간부터 낡는다 —")
    print("적어야 할 것은 수가 아니라 **결정과 그 이유**다(docs/decisions/decision-log.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
