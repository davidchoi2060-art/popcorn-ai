# -*- coding: utf-8 -*-
"""배포 확인 — **로컬과 서버가 같은 말을 하는지** 대조한다 (2026-08-12)

■ 왜 만드나 — 오늘 실제로 당한 것
  운영 스위치를 로컬에서 바꿨는데 `.env` 의 DATABASE_URL 이 Cloud SQL 이라
  **배포 서버까지 바뀌었다.** 코드는 배포 전이라 서버에는 옛 화면이 떠 있었고,
  그래서 서버는 「인계 모드인데 인계를 못 하는」 상태가 됐다.

      서버가 보는 스위치   pay: mall     <- 로컬에서 바꾼 것이 여기까지 갔다
      서버가 서빙한 코드   handoff 0곳    <- 아직 옛 화면

  **두 줄을 나란히 놓기만 했으면 즉시 보였다.** 그런데 아무도 나란히 놓지 않았다 —
  고친 사람과 확인한 사람이 같았기 때문이다(`.claude/TEAM.md` §1).

■ 이 스크립트가 하는 일 — 읽기만 한다
  ① 바뀐 파일을 **서버에서 받아 로컬과 해시 비교** (배포가 실제로 닿았나)
  ② `/api/ops` 를 로컬·서버에서 각각 받아 대조 (같은 DB 를 보는가 · 값이 같은가)
  ③ 핵심 화면·API 의 상태코드
  **쓰기 요청을 보내지 않는다.** 확인이 흔적을 남기면 안 된다(슬라이스 78 전례).

■ 쓰는 법
      .venv/Scripts/python scripts/verify_deploy.py                  # 마지막 커밋의 파일만
      .venv/Scripts/python scripts/verify_deploy.py --since HEAD~5   # 최근 5커밋
      .venv/Scripts/python scripts/verify_deploy.py --all            # 서빙되는 전부

  **무엇을 훑었는지 항상 밝힌다** — 「이상 없음」과 「아무것도 안 봤다」는 다르다.
"""
import argparse
import hashlib
import io
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

# Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게 stdout·stderr 를 UTF-8로 고정한다.
# 이 스크립트는 첫 print() 에서 UnicodeEncodeError 로 죽고 있었다(em-dash '—' 가 cp949 밖.
# 2026-08-16). tests/regression.py(stdout만)·tools/_console.py(ensure_utf8_console, stdout+
# stderr)와 같은 처방 — ASCII 로 바꾸지 않고 스트림 인코딩을 맞추는 쪽을 골랐다. 이유는
# tools/_console.py 모듈 docstring에 이미 적혀 있다: CLAUDE.md §데이터의 "로그 문자열은
# ASCII 기호만"(슬라이스 40)은 **상시 구동 API 서버**가 요청 처리 중 내는 로그 얘기고,
# 이 스크립트는 운영자가 터미널에서 직접 실행해 눈으로 읽는 1회성 CLI 보고문이라 범위가
# 다르다. ⚠ tools/_console.py 와 정의가 두 벌(중복)이지만 지금은 합치지 않는다 — 그러려면
# tools/*.py(15개, 남의 담당)의 import 문까지 함께 고쳐야 한다. 제안은 보고 참조.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace",
                                   line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = "http://127.0.0.1:8000"
SERVER = "https://admin.popcornai.co.kr"

# 로컬 경로 -> 서버 URL. `api/main.py` 의 mount 와 같아야 한다:
#   app.mount("/design-system", ...)  ·  app.mount("/", MOCKUPS_DIR)
MOUNTS = [("mockups/", "/"), ("design-system/", "/design-system/")]

# 서버 렌더라 파일로 못 받는 것. 라우트 상태코드로만 본다(관리자는 401 이 정상)
ROUTES = [("/mvp1/s4-cart.html", 200), ("/mvp1/s5-complete.html", 200),
          ("/mvp1/s1-session.html", 200), ("/api/ops", 200),
          ("/admin2/dash", None), ("/admin2/build-map", None)]


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True).stdout.decode("utf-8", "ignore").strip()


def url_for(path: str) -> str | None:
    """리포 경로 -> 서버 URL. 서빙되지 않는 것은 None."""
    p = path.replace("\\", "/")
    for pre, mount in MOUNTS:
        if p.startswith(pre):
            return mount + p[len(pre):]
    return None


def digest(b: bytes) -> str:
    """줄바꿈을 맞춰서 센다 — 윈도우 작업본이 CRLF 라 그냥 비교하면 전부 다르다고 나온다."""
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()[:12]


def get(url: str, timeout: int = 20) -> tuple[int, bytes]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache",
                                               "User-Agent": "popcorn-verify/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:                                    # noqa: BLE001
        return 0, str(e).encode("utf-8", "ignore")


def targets(args) -> tuple[list[str], str]:
    """검사 대상 파일과 «어떻게 골랐는지»를 함께 돌려준다."""
    if args.all:
        out = []
        for pre, _m in MOUNTS:
            for root, _d, files in os.walk(os.path.join(ROOT, pre.rstrip("/"))):
                for f in files:
                    if f.rsplit(".", 1)[-1].lower() in ("html", "css", "js"):
                        out.append(os.path.relpath(os.path.join(root, f), ROOT))
        return sorted(out), "서빙되는 파일 전부"
    ref = args.since or "HEAD~1"
    changed = [x for x in sh("git", "diff", "--name-only", ref, "HEAD").splitlines() if x.strip()]
    return changed, "%s..HEAD 에서 바뀐 파일" % ref


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--local", default=LOCAL)
    ap.add_argument("--since", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    bad = 0
    print("=" * 74)
    print("배포 확인 — 로컬 %s  ↔  서버 %s" % (args.local, args.server))
    print("=" * 74)

    # ── ① 코드가 실제로 닿았나 ───────────────────────────────────────
    files, how = targets(args)
    servable = [(f, url_for(f)) for f in files]
    skipped = [f for f, u in servable if u is None]
    servable = [(f, u) for f, u in servable if u]
    print()
    print("[1] 코드 대조 — %s" % how)
    print("    대상 %d개 중 서버에서 받을 수 있는 것 %d개" % (len(files), len(servable)))
    if skipped:
        print("    파일로 못 받는 것 %d개(서버 렌더·비웹 자산): %s"
              % (len(skipped), ", ".join(skipped[:4]) + (" …" if len(skipped) > 4 else "")))
    if not servable:
        print("    → 대조할 것이 없다. **이건 «통과»가 아니다**")
    for f, u in servable:
        try:
            local_b = io.open(os.path.join(ROOT, f), "rb").read()
        except OSError:
            print("    ? %-46s 로컬에 없음(삭제된 파일)" % f)
            continue
        st, body = get(args.server + u)
        if st != 200:
            print("    X %-46s 서버 응답 %s" % (f, st or "연결 실패"))
            bad += 1
            continue
        same = digest(local_b) == digest(body)
        print("    %s %-46s %s" % ("O" if same else "X", f,
                                   "같음" if same else "**다름** 로컬 %s / 서버 %s"
                                   % (digest(local_b), digest(body))))
        if not same:
            bad += 1

    # ── ② 운영 스위치 — 오늘 놓친 자리 ────────────────────────────────
    print()
    print("[2] 운영 스위치 대조 — /api/ops")
    sl, bl = get(args.local + "/api/ops", timeout=8)
    ss, bs = get(args.server + "/api/ops")
    ol = json.loads(bl) if sl == 200 else None
    os_ = json.loads(bs) if ss == 200 else None
    if ol is None or os_ is None:
        print("    로컬 %s · 서버 %s — 한쪽을 못 읽어 대조하지 못했다(통과가 아니다)"
              % (sl or "연결 실패", ss or "연결 실패"))
        bad += 1
    else:
        for k in sorted(set(ol) | set(os_)):
            a, b = ol.get(k), os_.get(k)
            print("    %s %-8s 로컬 %-5s 서버 %-5s" % ("O" if a == b else "X", k, a, b))
            if a != b:
                bad += 1
        if ol == os_:
            print("    → 같다. 둘이 같은 DB 를 본다는 뜻이기도 하다 — "
                  "**로컬에서 스위치를 바꾸면 서버도 바뀐다**")

    # ── ③ 살아 있나 ─────────────────────────────────────────────────
    print()
    print("[3] 핵심 경로 상태코드")
    for path, want in ROUTES:
        st, _ = get(args.server + path)
        if want is None:
            ok = st in (200, 401)
            note = "(401 = 로그인 필요 · 정상)" if st == 401 else ""
        else:
            ok = st == want
            note = ""
        print("    %s %-28s %s %s" % ("O" if ok else "X", path, st or "연결 실패", note))
        if not ok:
            bad += 1

    print()
    print("-" * 74)
    print("어긋난 것 %d건" % bad if bad else "어긋난 것 없음")
    print("훑은 범위: 코드 %d개 · 스위치 5종 · 경로 %d개" % (len(servable), len(ROUTES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
