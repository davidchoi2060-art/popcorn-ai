#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""텔레그램으로 알림을 보낸다 (PC → 폰).

표준 라이브러리만 쓴다 — 설치할 것이 없다.
자격증명은 `_tg_env.creds()` 가 **프로젝트 `.env` 를 먼저** 보고 없으면 환경변수를 본다
(이 PC 에는 다른 프로젝트 봇 토큰이 전역에 남아 있어서 그렇게 한다).

사용:
  py scripts/notify_telegram.py "재고 반영 완료 — 22,840건"
  py scripts/notify_telegram.py --test
  py scripts/notify_telegram.py --title "회귀" --run .venv/Scripts/python tests/regression.py

배치 끝에 붙일 때는 `--run` 을 쓴다(아래 참조).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
# cp949 콘솔에서 --stdin 본문이 깨져 텔레그램이 400(strings must be UTF-8)을 냈다(2026-08-23).
# read_telegram.py 와 같은 처방 — 표준입출력을 UTF-8 로 고정한다.
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tg_env import creds, source_note                            # noqa: E402

API = "https://api.telegram.org/bot{token}/sendMessage"

# 텔레그램 한도는 4096자다. 넘으면 400 을 받고 **알림이 통째로 사라진다**.
# 조용히 잘라 보낸다 — 안 오는 것보다 잘린 게 낫다.
MAX_LEN = 4096
TRUNC_MARK = "\n…(잘림)"


def send(text: str, *, silent: bool = False, timeout: int = 15) -> None:
    token, chat_id = creds()
    if len(text) > MAX_LEN:
        text = text[: MAX_LEN - len(TRUNC_MARK)] + TRUNC_MARK
    payload = json.dumps({"chat_id": chat_id, "text": text,
                          "disable_notification": silent}).encode("utf-8")
    req = urllib.request.Request(API.format(token=token), data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        # 토큰은 절대 찍지 않는다 — 로그에 남으면 그대로 유출이다.
        raise SystemExit(f"발송 실패 HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise SystemExit(f"발송 실패 (네트워크): {e.reason}") from None
    if not body.get("ok"):
        raise SystemExit(f"발송 실패: {body}")


def notify_safe(text: str, title: str = "") -> bool:
    """다른 스크립트가 부르는 진입점 — **절대 예외를 올리지 않는다.**

    알림은 부수 기능이다. 텔레그램이 죽었거나 키가 없다는 이유로 30분짜리 배치의
    마지막 줄에서 터지면 본말전도다. 실패는 한 줄만 남기고 삼킨다.
    """
    try:
        send(f"[{title}]\n{text}" if title else text)
        return True
    except BaseException as e:      # SystemExit(자격증명 없음)까지 삼킨다
        print(f"[알림] 텔레그램 발송 건너뜀: {e}", flush=True)
        return False


def run_and_capture(cmd: list[str]) -> tuple[str, int]:
    """명령을 직접 실행해 출력을 UTF-8 로 받는다.

    **PowerShell 파이프를 거치지 않는 것이 핵심이다** — PS 5.1 은 프로그램 사이
    텍스트를 기본 ASCII 로 넘겨서 한글이 전부 '?' 가 된다. `PYTHONUTF8=1` 은
    파이썬 안쪽만 고치므로 그 구간에 효과가 없다. 파이썬이 자식을 직접 띄우면
    셸이 낄 자리가 사라진다.
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = list(cmd)
    # Windows 는 `.venv/Scripts/python` 같은 **상대 경로 + 슬래시**를 못 찾는다
    # (`FileNotFoundError [WinError 2]`). 셸이 없으니 아무도 대신 풀어 주지 않는다 —
    # 여기서 흡수한다. 안 그러면 배치마다 절대 경로를 적어야 한다.
    exe = cmd[0]
    if not os.path.isabs(exe):
        cand = os.path.abspath(exe.replace("/", os.sep))
        for c in (cand, cand + ".exe"):
            if os.path.isfile(c):
                cmd[0] = c
                break
    try:
        proc = subprocess.run(cmd, capture_output=True, env=env,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"실행 파일을 찾을 수 없습니다: {cmd[0]}", 127
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.rstrip(), proc.returncode


def main() -> None:
    p = argparse.ArgumentParser(description="텔레그램 알림 발송")
    p.add_argument("text", nargs="*", help="보낼 메시지")
    p.add_argument("--stdin", action="store_true", help="표준입력을 본문으로 쓴다")
    p.add_argument("--title", default="", help="본문 앞에 붙일 제목 줄")
    p.add_argument("--silent", action="store_true", help="소리 없이 보낸다")
    p.add_argument("--test", action="store_true", help="연결 확인용 메시지")
    p.add_argument("--run", nargs=argparse.REMAINDER,
                   help="이 뒤의 명령을 실행하고 그 출력을 보낸다. **항상 맨 끝**")
    a = p.parse_args()

    rc = 0
    if a.run:
        body, rc = run_and_capture(a.run)
        if not a.title:
            base = os.path.basename(a.run[-1] if len(a.run) > 1 else a.run[0])
            a.title = base + ("" if rc == 0 else f" (실패 rc={rc})")
        body = body or "(출력 없음)"
    elif a.test:
        body = "연결 확인 완료 — 팝콘AI 계기판이 살아 있습니다. (자격증명 출처: %s)" % source_note()
    elif a.stdin:
        body = sys.stdin.read().rstrip()
    else:
        body = " ".join(a.text).strip()

    if not body:
        raise SystemExit("보낼 내용이 없습니다. 텍스트를 주거나 --stdin 을 쓰십시오.")
    if a.title:
        body = f"[{a.title}]\n{body}"

    send(body, silent=a.silent)
    print("보냄")
    # `--run` 으로 감싼 명령이 실패했으면 그 종료코드를 그대로 물려준다.
    # 알림을 보냈다는 이유로 실패가 성공으로 둔갑하면 배치에서 조용히 지나간다.
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
