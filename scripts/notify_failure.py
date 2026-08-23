#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""systemd OnFailure= 로 불려 "이 unit 이 실패했다"를 텔레그램으로 알린다.

결정 로그 U-57 해소(다나와 시세 재수집 타이머가 실패해도 journald 에만 남고
아무에게도 안 가던 문제 — A-111 근거). 호출 관례:

    ExecStart=.../notify_failure.py <unit-식별자>

<unit-식별자>는 실패한 unit 의 완전한 이름(%n)이 아닐 수 있다. 실패한 unit
자신이 이미 '@' 를 포함한 템플릿 인스턴스(예: popcorn-danawa-market@fast.service)
라면, systemd 유닛 이름의 인스턴스 부분(첫 '@' 뒤, 타입 접미사 앞)은 '@' 문자를
허용하지 않는다(systemd-escape 기준 안전 문자는 글자 · 숫자 · 콜론 · 밑줄 ·
마침표 · 하이픈뿐이고 그 밖은 16진수로 escape 된다). 그래서 실패한 unit 이름을
그대로 다시 '@' 로 이어붙이면(OnFailure=notify-failure@%n.service) '@' 가 두 번
들어가 무효한 이름이 되고, systemd 는 그 OnFailure= 의존성을 조용히 버린다 —
지금 고치려는 증상("실패해도 아무도 모른다")이 알림 배선 위에서 그대로
재발하는 셈이다. 그래서 호출부(deploy/systemd/popcorn-danawa-market@.service)는
'@' 가 생기지 않는 "prefix-instance" 형태(%p-%i)를 넘긴다.
resolve_unit_name() 이 그 형태를 다시 "prefix@instance.service" 로 복원한다 —
복원 규칙의 전제와 한계는 그 함수 docstring 참조. 전체 배선 근거는
deploy/systemd/popcorn-notify-failure@.service 머리말에도 있다(중복 서술하지
않는다).

텔레그램 전송은 scripts/notify_telegram.py 를 **그대로** 쓴다(다시 구현하지
않는다) — 여기서는 별도 프로세스로 불러 그 스크립트의 --stdin 입력을 쓴다.
자격증명이 "있는지 없는지"만 scripts/_tg_env.py 의 creds() 를 직접 불러 먼저
확인한다 — notify_telegram.py 를 그냥 불렀을 때 나오는 안내 문구("이 프로젝트의
.env 에 넣으십시오")가, 프로젝트 .env 파일이 아예 없는 배포 서버에서는 엉뚱한
위치를 가리키기 때문이다(서버에서 맞는 위치는 /etc/popcorn-ai.env). 이
스크립트가 서버(.env 없음, 환경변수만)에서 동작하는지에 대한 판정과 근거는
deploy/README.md 「실패 알림」 절에 있다.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import _tg_env  # noqa: E402  -- creds() 만 재사용한다(전송 로직은 손대지 않는다)

NOTIFY_TELEGRAM = os.path.join(_HERE, "notify_telegram.py")

JOURNAL_LINES = 20
JOURNAL_TIMEOUT_SEC = 15
SEND_TIMEOUT_SEC = 30

KNOWN_SUFFIXES = (".service", ".timer", ".socket", ".path", ".mount", ".target", ".device")


def resolve_unit_name(raw: str) -> str:
    """받은 식별자를 journalctl -u 에 쓸 실제 unit 이름으로 되돌린다.

    ① 이미 알려진 unit 타입 접미사로 끝나면 — 템플릿이 아닌 평범한 unit 이
       OnFailure=...@%n.service 로 자기 이름을 그대로 넘긴 경우다(평범한 unit
       이름에는 애초에 '@' 가 없어 이 문제가 안 생긴다). 그대로 쓴다.
    ② 아니면 — 템플릿 인스턴스가 %p-%i(하이픈 조인) 형태로 넘긴 것으로 보고
       **마지막** '-' 를 '@' 로 되돌리고 .service 를 붙인다.

    ②의 전제: 인스턴스 이름 자체에는 '-' 가 없어야 한다. 지금 이 저장소가 이
    알림에 실제로 연결한 인스턴스는 fast/slow 뿐이라(하이픈 없음) 문제가 없다.
    새 템플릿 unit 을 여기 연결하는데 그 인스턴스 이름에 하이픈이 들어가면
    이 함수부터 다시 봐야 한다 — 복원이 틀려도 fetch_last_logs() 는 예외를
    올리지 않고 "로그 없음"을 알리므로, 알림 자체가 조용히 사라지지는 않는다.
    """
    if raw.endswith(KNOWN_SUFFIXES):
        return raw
    if "-" in raw:
        prefix, _, instance = raw.rpartition("-")
        return f"{prefix}@{instance}.service"
    return raw + ".service"


def fetch_last_logs(unit: str, lines: int = JOURNAL_LINES) -> str:
    """journalctl -u <unit> 의 마지막 lines 줄. 못 가져와도 예외를 올리지 않는다
    — 로그를 못 읽었다는 이유로 알림 자체가 안 나가면 안 된다."""
    try:
        proc = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager",
             "--no-hostname", "--output=short-iso"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=JOURNAL_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return "(journalctl 실행 파일을 찾지 못했다)"
    except subprocess.TimeoutExpired:
        return f"(journalctl 응답 없음 - {JOURNAL_TIMEOUT_SEC}초 초과)"
    except OSError as e:
        return f"(journalctl 실행 실패: {e})"

    out = (proc.stdout or "").strip()
    if out:
        return out
    err = (proc.stderr or "").strip()
    if err:
        return f"(로그 없음, stderr: {err})"
    return "(로그 없음 - unit 이름 복원이 틀렸을 수 있다. 위 unit 값을 확인하라)"


def build_body(raw_id: str, unit: str, logs: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return "\n".join([
        f"[unit 실패] {unit}",
        f"시각: {now} UTC (원본 id: {raw_id})",
        "-" * 24,
        f"최근 로그 {JOURNAL_LINES}줄:",
        logs,
    ])


def send_via_notify_telegram(body: str) -> tuple[bool, str]:
    """scripts/notify_telegram.py --stdin 을 별도 프로세스로 불러 전송한다.

    전송 로직(HTTP 호출 · 4096자 자르기)은 전부 그 스크립트 것을 그대로
    쓴다 — 여기서 다시 구현하지 않는다."""
    try:
        proc = subprocess.run(
            [sys.executable, NOTIFY_TELEGRAM, "--stdin"],
            input=body, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=SEND_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, f"notify_telegram.py 응답 없음 - {SEND_TIMEOUT_SEC}초 초과"
    except OSError as e:
        return False, f"notify_telegram.py 실행 실패: {e}"

    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("[알림 실패] 실패한 unit 식별자를 인자로 받지 못했다 - "
              "OnFailure= 배선을 확인하라.", file=sys.stderr)
        return 1

    raw_id = sys.argv[1].strip()
    unit = resolve_unit_name(raw_id)

    # 자격증명이 없으면 로그를 뽑기 전에 먼저, 분명하게 알린다 - 어차피 못
    # 보낸다. notify_telegram.py 를 그냥 불렀을 때 나오는 안내("이 프로젝트의
    # .env 에 넣으십시오")는 프로젝트 .env 가 없는 배포 서버에서는 틀린
    # 위치를 가리키므로, 여기서는 creds() 의 "없다" 판정만 재사용하고 문구는
    # 직접 쓴다. 이 메시지가 이 스크립트에서 가장 중요한 줄이다 - 텔레그램이
    # 안 가는데 journald 에도 아무 흔적이 없으면 U-57 을 고친 것이 아니다.
    try:
        _tg_env.creds()
    except SystemExit:
        print(
            "[알림 실패] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없다 - "
            "/etc/popcorn-ai.env 에 두 줄을 추가해야 한다(권한 640 root:popcorn "
            "유지, 절차는 deploy/README.md 「실패 알림」 참조). "
            f"원인 unit={unit}",
            file=sys.stderr,
        )
        return 1

    logs = fetch_last_logs(unit)
    body = build_body(raw_id, unit, logs)

    ok, detail = send_via_notify_telegram(body)
    if not ok:
        print(f"[알림 실패] 텔레그램 발송 실패 (unit={unit}): {detail}", file=sys.stderr)
        return 1

    print(f"[알림] unit={unit} 실패를 텔레그램으로 통지했다. {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
