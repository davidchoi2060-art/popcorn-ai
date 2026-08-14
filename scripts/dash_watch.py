# -*- coding: utf-8 -*-
"""현황판 큐 감시 — 로컬 + 배포 서버 (2026-08-12)

■ 왜 다시 짰나 — 셸 카운터가 메시지를 삼켰다
  전에는 Monitor 에 셸 한 줄을 넣었다: `grep -c '"read": false'` 로 안 읽은 수를 세고
  늘어난 만큼 `tail -n` 으로 찍는 방식. 두 군데서 깨졌다:
    ① 큐가 전부 읽음이면 grep 이 «0 + 종료코드 1» 을 내고, `|| echo 0` 이 붙어
       N 이 "0\\n0" 이 됐다 → 수 비교가 조용히 실패 → 기준값이 안 내려감
    ② 그 상태에서 새 메시지가 오면 «1 > 1 = 거짓» — **22:29 메시지가 그렇게 사라졌다**
  수를 세지 말고 **본 것을 기억**한다: (ts, text) 를 집합에 담고 새것만 찍는다.

■ 서버 큐도 본다
  현황판은 배포 서버에도 떠 있다(https://admin.popcornai.co.kr/admin2/dash).
  거기서 보낸 메시지는 **서버 디스크의 큐 파일**에 쌓인다 — 로컬 파일만 보면 영영 모른다.
  `.env` 의 ADMIN_EMAIL/ADMIN_PW 로 로그인해 `/api/admin/dash/state` 의 `queued` 를 읽는다.
  (비밀값은 출력하지 않는다. 로그인 실패는 한 번만 알리고 계속 재시도한다.)

■ 출력 한 줄 = 알림 한 번 (Monitor 계약)
  [현황판·로컬] / [현황판·서버] 접두어로 어느 쪽에서 온 말인지 구분한다 —
  읽음 처리를 그쪽에 해야 하기 때문이다(로컬은 로컬 API, 서버는 서버 API).
"""
import datetime
import io
import json
import os
import ssl
import sys
import time
import http.cookiejar
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_Q = os.path.join(ROOT, ".claude", "dash-queue.jsonl")
HEARTBEAT = os.path.join(ROOT, ".claude", "dash-watch.heartbeat")
SERVER = "https://admin.popcornai.co.kr"
POLL_LOCAL_S = 5
POLL_SERVER_S = 30

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# 하트비트 파일에 적는 시각도 `api/timeutil.now_iso()` 와 같은 표기여야 한다 — `_watcher()`
# (api/dash.py)가 이 문자열을 그대로 화면에 내보내는데, 타임존 없는 isoformat 은 배포
# 서버(UTC)에서 브라우저가 로컬 시각으로 오독한다(슬라이스 62와 같은 함정). 이 스크립트는
# `api` 패키지 밖에서 단독 실행되므로 ROOT 를 sys.path 에 넣어 정본을 그대로 쓰되,
# 경로 문제로 실패하면 **같은 규칙(타임존 UTC 명시)** 의 자체 구현으로 물러난다.
try:
    sys.path.insert(0, ROOT)
    from api.timeutil import now_iso
except Exception:                                              # noqa: BLE001
    def now_iso() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_heartbeat() -> None:
    """감시자 생존 신호 — 매 반복 덮어쓴다. 실패해도 감시는 계속돼야 하니 조용히 넘어간다.

    출력 계약(머리 주석 참고: 출력 한 줄 = 알림 한 번)을 어기지 않으려면 여기서
    **절대 print 하지 않는다** — 서버(api/dash.py)가 파일 mtime/15초로 생존을 판정한다.
    """
    try:
        os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
        with io.open(HEARTBEAT, "w", encoding="utf-8") as f:
            f.write(now_iso())
    except Exception:                                        # noqa: BLE001
        pass


def say(src: str, ts: str, text: str) -> None:
    print("[현황판·%s %s] %s" % (src, ts or "?", (text or "").strip()[:400]))


def read_local(seen: set) -> None:
    if not os.path.exists(LOCAL_Q):
        return
    try:
        lines = io.open(LOCAL_Q, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:                                    # noqa: BLE001
            continue
        key = ("L", d.get("ts"), d.get("text"))
        if d.get("read") or key in seen:
            continue
        seen.add(key)
        say("로컬", d.get("ts", ""), d.get("text", ""))


class Server:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.creds = None
        self.warned = False
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(ROOT, ".env"))
        except Exception:                                    # noqa: BLE001
            pass
        email = os.environ.get("ADMIN_EMAIL", "admin@popcornpc.local")
        pw = os.environ.get("ADMIN_PW", "")
        if pw:
            self.creds = (email, pw)

    def login(self) -> bool:
        if not self.creds:
            if not self.warned:
                print("[현황판·서버] ADMIN_PW 없음 — 서버 큐는 감시하지 않는다")
                self.warned = True
            return False
        try:
            req = urllib.request.Request(
                SERVER + "/api/admin/auth/login",
                data=json.dumps({"email": self.creds[0], "password": self.creds[1]}).encode(),
                headers={"Content-Type": "application/json"})
            return self.op.open(req, timeout=20).status == 200
        except Exception:                                    # noqa: BLE001
            return False

    def poll(self, seen: set) -> None:
        try:
            # watcher=1 — 배포 서버가 «감시자가 마지막으로 부른 시각」을 기록하게 한다
            # (배포 PC엔 로컬 하트비트 파일이 없으니 이 핑이 유일한 생존 신호다).
            r = self.op.open(SERVER + "/api/admin/dash/state?limit=1&watcher=1", timeout=20)
            body = r.read()
        except urllib.error.HTTPError as e:                  # 401 = 세션 만료 → 재로그인
            if e.code == 401 and self.login():
                return self.poll(seen)
            return
        except Exception:                                    # noqa: BLE001
            return
        try:
            q = json.loads(body).get("queued") or []
        except Exception:                                    # noqa: BLE001
            return
        for d in q:
            key = ("S", d.get("ts"), d.get("text"))
            if key in seen:
                continue
            seen.add(key)
            say("서버", d.get("ts", ""), d.get("text", ""))


def main() -> None:
    seen: set = set()
    # 시작 시점의 «안 읽음»도 찍는다 — 감시가 죽어 있던 사이에 온 것을 놓치지 않기 위해서다.
    srv = Server()
    srv.login()
    last_srv = 0.0
    while True:
        write_heartbeat()
        read_local(seen)
        if time.time() - last_srv >= POLL_SERVER_S:
            last_srv = time.time()
            srv.poll(seen)
        time.sleep(POLL_LOCAL_S)


if __name__ == "__main__":
    main()
