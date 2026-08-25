# -*- coding: utf-8 -*-
"""현황판 큐 감시 — 로컬 + 배포 서버 (2026-08-12 · 2026-08-25 상시화 개정)

■ 왜 다시 짰나 — 셸 카운터가 메시지를 삼켰다 (2026-08-12)
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
  [현황판·로컬] / [현황판·서버] 접두어로 어느 쪽에서 온 말인지 구분한다.

■ 2026-08-25 — 상시 기동(작업 스케줄러)과 세션 알림이 부딪히는 문제
  PC 로그온 시 이 스크립트를 작업 스케줄러로 띄우면 하트비트는 계속 켜진다. 그런데
  사장님 메시지를 **에이전트에게** 전하는 유일한 경로는 "stdout 한 줄 = Monitor 알림
  하나"뿐이다 — Monitor 는 **세션이 자기가 띄운 프로세스**의 출력만 받는다. 스케줄러가
  띄운 프로세스는 어떤 세션도 띄운 적이 없으므로, 그 프로세스가 아무리 메시지를
  찍어도 받을 Monitor 가 애초에 없다. 그래서 **역할을 가른다**(설계 선택 ㉠):

      --service (스케줄러 전용)   하트비트만. 큐는 «보되 소비하지 않는다»
                                  (watcher=1 핑만 보내고 `queued` 내용은 버린다)
      기본값(세션이 스스로 띄움)  기존과 동일한 전체 동작 + **읽음 처리 실제 구현**(㉢)

  **service 모드가 큐를 소비(읽음 처리)하면 안 되는 이유**: 그 순간 살아있는 세션이
  하나도 없어도 메시지는 "읽음"으로 굳어 버리고, 나중에 세션이 떠도 이미 읽음 처리된
  메시지는 다시 안 보인다 — 즉 **아무도 못 본 채로 사라진다.** 그래서 service 모드는
  절대 `queued` 의 내용을 들여다보지 않는다(`Server.ping()` — 응답을 받고 버린다).

  **중복 방지는 service 모드에만 건다**(PID 잠금, 아래 `acquire_service_lock`). 기본
  (notify) 모드는 잠그지 않는다 — 이 PC는 여러 VSCode 창이 동시에 세션을 가질 수 있고
  (전역 CLAUDE.md "세션은 공유하지 않는다"), 각 세션이 자기 Monitor 로 이 스크립트를
  기본 모드로 띄운다(실측: 2026-08-25 작업 중에도 다른 세션의 dash_watch.py 가 이미
  떠 있었다). 여기를 잠그면 두 번째 세션은 영영 알림을 못 받는다 — 그래서
  "사장님이 말을 걸어도 안 온다"는 사고가 스케줄러 쪽이 아니라 **이쪽**에서도 날 수
  있다. 대가: 여러 세션이 동시에 뜨면 각자 서버에 핑·로그인을 중복으로 보낸다(가벼운
  낭비, 정확성보다 싼 비용이라 감수한다).

  **한 문장 요약(사장님이 물으면 이렇게 답한다)**: 사장님이 대시보드에서 "말 걸기"를
  누르면 큐 파일(로컬) 또는 배포 서버 큐에 메시지가 쌓이고, **지금 열려 있는 Claude
  Code 세션이 자기 Monitor 로 띄운 이 스크립트(기본 모드)** 가 5초(로컬)~30초(서버)
  안에 그것을 발견해 stdout 에 한 줄 찍으면 그게 그 세션에 대한 알림이 된다 — 세션이
  하나도 안 떠 있으면 스케줄러의 하트비트 전용 프로세스는 그 메시지를 만지지 않고
  그대로 "안 읽음"으로 남겨 두므로, **다음에 세션이 뜨면 그때 놓치지 않고 알린다.**

■ 읽음 처리 실제 구현 (㉢ — 이 파일 옛 주석이 이미 의도했던 방향)
  `api/dash.py` 의 `POST /api/admin/dash/mark-read` 를 부른다(로컬은 127.0.0.1:8000,
  배포는 SERVER — 같은 라우트, 같은 응답 모양). **큐 파일을 여기서 직접 다시 쓰지
  않는다** — 이 프로세스와 API 서버가 동시에 같은 파일을 read-modify-write 하면 그
  사이 도착한 새 메시지를 덮어써 잃어버릴 수 있다. 쓰기는 항상 API 서버 하나만 하게
  두고, 이 스크립트는 그 API 를 부르기만 한다. 실패(로그인 안 됨·서버 다운)하면
  조용히 다음 주기에 다시 시도한다 — 읽음 처리가 한 번 실패해도 "다시 알린다"가
  "영영 못 본다"보다 안전하기 때문이다.
  남는 한계 하나: `mark-read` 는 "지금 안 읽은 것 전부"를 읽음으로 표시하는 API라(특정
  id 지정 불가 — `api/dash.py` 는 다른 제작자 담당이라 바꾸지 않았다), 알린 직후
  아주 좁은 순간(<1초)에 새 메시지가 도착하면 그 메시지는 출력 없이 읽음 처리될 수
  있다. 사람이 대시보드에 타이핑해 넣는 빈도(분 단위)를 감안하면 실질 위험은 낮다고
  보고 받아들였다 — 감춘 것이 아니라 여기 적어 둔다.
"""
import argparse
import atexit
import datetime
import io
import json
import os
import ssl
import subprocess
import sys
import time
import http.cookiejar
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_Q = os.path.join(ROOT, ".claude", "dash-queue.jsonl")
HEARTBEAT = os.path.join(ROOT, ".claude", "dash-watch.heartbeat")
LOCK_PATH = os.path.join(ROOT, ".claude", "dash-watch.service.lock")
SERVER = "https://admin.popcornai.co.kr"
LOCAL_BASE = "http://127.0.0.1:8000"
POLL_LOCAL_S = 5
POLL_SERVER_S = 30

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:                                              # noqa: BLE001
    # pythonw.exe(창 없음) 등 stdout 이 정상 스트림이 아닐 수 있는 환경 대비.
    # 이 환경(3.11.9)에서는 문제없음을 확인했지만(스케줄러는 창 없이 돈다),
    # 다른 배포·버전에서 stdout 이 None 이면 여기서 죽지 않게 막아 둔다.
    pass

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
    service·notify 두 모드 다 이 함수를 부른다 — 어느 쪽이 떠 있어도 하트비트는
    끊기지 않는다(덮어쓰기라 중복 호출은 해가 없다).
    """
    try:
        os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
        with io.open(HEARTBEAT, "w", encoding="utf-8") as f:
            f.write(now_iso())
    except Exception:                                        # noqa: BLE001
        pass


def say(src: str, ts: str, text: str) -> None:
    print("[현황판·%s %s] %s" % (src, ts or "?", (text or "").strip()[:400]))


def read_local(seen: set) -> int:
    """로컬 큐 파일을 **직접** 읽는다(로컬 API 서버가 죽어 있어도 새 메시지는 알린다).

    반환값 = 이번 호출에서 새로 알린 개수. 0 이면 호출부가 mark-read 를 부르지 않는다
    (안 읽은 게 없는데 매번 서버를 두드릴 이유가 없다).
    """
    if not os.path.exists(LOCAL_Q):
        return 0
    try:
        lines = io.open(LOCAL_Q, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return 0
    n = 0
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
        n += 1
    return n


class Server:
    """관리자 API 로그인 + 큐 폴링/핑/읽음 처리.

    `base_url` 만 다르면 로컬(127.0.0.1:8000)과 배포(admin.popcornai.co.kr) 양쪽에
    그대로 쓴다 — 같은 코드(api/dash.py)가 같은 모양의 라우트를 두 곳에서 서비스하고,
    두 DB 가 같은 Cloud SQL 이라 자격증명(.env 의 ADMIN_EMAIL/ADMIN_PW)도 같다.
    """

    def __init__(self, base_url: str, label: str):
        self.base = base_url
        self.label = label
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
                reason = ("서버 큐는 감시하지 않는다" if self.label == "서버"
                           else "읽음 처리를 못 한다(재시작하면 다시 알린다)")
                print("[현황판·%s] ADMIN_PW 없음 — %s" % (self.label, reason))
                self.warned = True
            return False
        try:
            req = urllib.request.Request(
                self.base + "/api/admin/auth/login",
                data=json.dumps({"email": self.creds[0], "password": self.creds[1]}).encode(),
                headers={"Content-Type": "application/json"})
            return self.op.open(req, timeout=20).status == 200
        except Exception:                                    # noqa: BLE001
            return False

    def mark_read(self) -> bool:
        """방금 알린 것을 서버에 읽음으로 표시한다 — 재시작해도 다시 알리지 않기 위해서다.

        큐 파일을 여기서 직접 고치지 않는다(머리 주석 "읽음 처리 실제 구현" 참고) —
        API 서버 하나만 쓰게 두어 read-modify-write 경합을 피한다.
        """
        try:
            req = urllib.request.Request(
                self.base + "/api/admin/dash/mark-read",
                data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            return self.op.open(req, timeout=20).status == 200
        except urllib.error.HTTPError as e:
            if e.code == 401 and self.login():
                return self.mark_read()
            return False
        except Exception:                                    # noqa: BLE001
            return False

    def ping(self) -> None:
        """service 모드 전용 — "살아있다"만 알린다. 응답의 `queued` 는 받아도 버린다.

        여기서 큐를 소비하면(읽고 읽음 처리하면) 세션이 하나도 안 떠 있을 때 메시지가
        말 없이 "읽음"으로 굳어버린다(머리 주석 참고) — 그래서 절대 손대지 않는다.
        """
        try:
            self.op.open(self.base + "/api/admin/dash/state?limit=1&watcher=1", timeout=20).read()
        except urllib.error.HTTPError as e:                  # 401 = 세션 만료 → 재로그인
            if e.code == 401 and self.login():
                self.ping()
        except Exception:                                    # noqa: BLE001
            pass

    def poll(self, seen: set) -> int:
        """notify 모드 전용 — 큐를 읽어 새것만 알리고, 알린 게 있으면 읽음 처리한다."""
        try:
            # watcher=1 — 배포 서버가 «감시자가 마지막으로 부른 시각»을 기록하게 한다
            # (배포 PC엔 로컬 하트비트 파일이 없으니 이 핑이 유일한 생존 신호다).
            r = self.op.open(self.base + "/api/admin/dash/state?limit=1&watcher=1", timeout=20)
            body = r.read()
        except urllib.error.HTTPError as e:                  # 401 = 세션 만료 → 재로그인
            if e.code == 401 and self.login():
                return self.poll(seen)
            return 0
        except Exception:                                    # noqa: BLE001
            return 0
        try:
            q = json.loads(body).get("queued") or []
        except Exception:                                    # noqa: BLE001
            return 0
        n = 0
        for d in q:
            key = ("S", d.get("ts"), d.get("text"))
            if key in seen:
                continue
            seen.add(key)
            say(self.label, d.get("ts", ""), d.get("text", ""))
            n += 1
        if n:
            self.mark_read()
        return n


# ── 중복 실행 방지 (service 모드 전용 — 머리 주석 "역할을 가른다" 참고) ──────────

def _proc_alive(pid: int) -> bool:
    """PID 가 실제로 살아 있는 프로세스인지 확인한다.

    PC 강제 종료 등으로 죽은 프로세스의 잠금 파일이 남을 수 있다 — 그 PID 를 산
    프로세스로 오인하면 다음 로그온 때 감시자가 영영 못 뜬다. `tasklist` 로 그 PID 가
    **지금** 존재하는지 직접 확인한다(파일 mtime 등 간접 신호를 쓰지 않는다).
    """
    if os.name == "nt":
        try:
            cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, errors="ignore",
                creationflags=cf)
            line = (out.stdout or "").strip()
            # 살아있으면 CSV 한 줄(`"이미지명","PID",...`), 없으면 "정보: ..." 류 안내문.
            return line.startswith('"') and ('"%d"' % pid) in line
        except Exception:                                    # noqa: BLE001
            return False
    try:                                                      # 개발·테스트용(비Windows)
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:                                        # noqa: BLE001
        return True


def acquire_service_lock() -> None:
    """service 모드 단일 실행을 보장한다.

    `O_CREAT|O_EXCL` 로 원자적으로 잠근다(두 프로세스가 같은 순간 시작해도 하나만
    성공 — TOCTOU 경합 없음). 이미 잠겨 있으면 그 PID 가 **지금 실제로** 살아있는지
    `_proc_alive` 로 확인한다:
      살아있다   조용히 죽지 않는다 — 어느 PID·언제 시작했는지 밝히고 종료한다(exit 1).
      죽어있다   강제 종료로 남은 잠금 파일이다 — 지우고 다시 잡는다.
    """
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "started": now_iso()}, f)
            atexit.register(release_service_lock)
            return
        except FileExistsError:
            info = {}
            try:
                info = json.load(io.open(LOCK_PATH, encoding="utf-8"))
            except Exception:                                # noqa: BLE001
                pass
            pid = info.get("pid")
            if isinstance(pid, int) and _proc_alive(pid):
                print("[현황판·서비스] 이미 실행 중이다 — PID %s (시작 %s). "
                      "이 인스턴스는 종료한다." % (pid, info.get("started", "?")))
                sys.exit(1)
            print("[현황판·서비스] 죽은 프로세스의 잠금 파일을 발견했다 — PID %s. "
                  "지우고 다시 잡는다." % (pid,))
            try:
                os.remove(LOCK_PATH)
            except OSError:
                pass
    print("[현황판·서비스] 잠금을 잡지 못했다 — 종료한다.")
    sys.exit(1)


def release_service_lock() -> None:
    """정상 종료 시 잠금을 지운다. 강제 종료(TerminateProcess)면 못 불린다 — 그건
    다음 시작의 `_proc_alive` 검사가 처리한다(위 `acquire_service_lock` 참고)."""
    try:
        info = json.load(io.open(LOCK_PATH, encoding="utf-8"))
        if info.get("pid") == os.getpid():
            os.remove(LOCK_PATH)
    except Exception:                                        # noqa: BLE001
        pass


# ── 두 모드 ──────────────────────────────────────────────────────────────

def service_loop() -> None:
    """하트비트 전용 — 큐를 절대 소비하지 않는다. 작업 스케줄러가 이 모드로 띄운다."""
    deploy = Server(SERVER, "서버")
    deploy.login()
    last_srv = 0.0
    while True:
        write_heartbeat()
        if time.time() - last_srv >= POLL_SERVER_S:
            last_srv = time.time()
            deploy.ping()
        time.sleep(POLL_LOCAL_S)


def notify_loop() -> None:
    """세션이 스스로 띄우는 모드 — 큐를 읽어 stdout 으로 알리고 실제로 읽음 처리한다.

    인자 없이 호출한다 — `CLAUDE.md` 시작 절차 ④가 그대로 부르는 명령이 이것이다
    (`Monitor(persistent): .venv/Scripts/python scripts/dash_watch.py`). 여기 시그니처를
    바꾸면 그 문서도 함께 고쳐야 하므로 기본 동작(인자 없음)은 그대로 둔다.
    잠그지 않는다 — 여러 세션이 동시에 이 모드를 띄울 수 있다(머리 주석 참고).
    """
    seen: set = set()
    # 시작 시점의 «안 읽음»도 찍는다 — 감시가 죽어 있던 사이에 온 것을 놓치지 않기 위해서다.
    local = Server(LOCAL_BASE, "로컬")
    local.login()
    deploy = Server(SERVER, "서버")
    deploy.login()
    last_srv = 0.0
    while True:
        write_heartbeat()
        if read_local(seen) > 0:
            local.mark_read()
        if time.time() - last_srv >= POLL_SERVER_S:
            last_srv = time.time()
            deploy.poll(seen)
        time.sleep(POLL_LOCAL_S)


def main() -> None:
    p = argparse.ArgumentParser(description="현황판 큐 감시자")
    p.add_argument("--service", action="store_true",
                    help="하트비트 전용 상시 모드(작업 스케줄러용) — 큐를 소비하지 않는다. "
                         "생략하면 기존과 같은 전체 모드(세션이 스스로 띄우는 용도)다.")
    args = p.parse_args()
    if args.service:
        acquire_service_lock()
        service_loop()
    else:
        notify_loop()


if __name__ == "__main__":
    main()
