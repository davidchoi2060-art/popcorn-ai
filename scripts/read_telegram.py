#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""텔레그램 새 메시지를 읽는다 (폰 → PC). `notify_telegram.py` 의 짝.

핵심 두 가지:

  1. **오프셋을 파일에 남긴다.** `getUpdates` 는 확인 처리(`offset=마지막+1`)를 안 하면
     같은 메시지를 계속 준다. 폴링에서 빠뜨리면 한 번 보낸 지시를 1분마다 다시 읽어
     **같은 작업을 반복 실행**한다.

  2. **등록된 chat_id 외에는 전부 버린다.** 봇 username 은 공개라 아무나 찾아 말을 걸 수
     있다. 읽기를 여는 순간 그것이 실제 주입 통로가 되므로, 낯선 발신자는 **내용을 출력조차
     하지 않는다** — 로그에 남기는 것 자체가 통로다.

사용:
  py scripts/read_telegram.py            # 새 메시지 출력 + 확인 처리
  py scripts/read_telegram.py --peek     # 확인 처리 없이 들여다보기
  py scripts/read_telegram.py --json     # 기계 판독용
  py scripts/read_telegram.py --mark-reply   # 답장 직후 호출(유휴 시계 리셋)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tg_env import creds                                          # noqa: E402

API = "https://api.telegram.org/bot{token}/getUpdates"
# 오프셋 파일 — **반드시 gitignore 한다.** 여러 PC 가 저장소를 공유하면 남의 오프셋이
# 딸려 와 메시지를 건너뛰거나 다시 읽는다.
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "references", "telegram_offset.json")


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_offset() -> int:
    try:
        return int(load_state().get("offset", 0))
    except Exception:
        return 0


def _write(st: dict) -> None:
    st["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def save_offset(offset: int, *, got_message: bool) -> None:
    """오프셋과 '마지막으로 사용자 메시지를 받은 시각'을 남긴다.

    메시지가 없던 실행은 시각을 건드리지 않는다 — 그래야 유휴가 누적된다.
    """
    st = load_state()
    st["offset"] = offset
    if got_message:
        st["last_message_at"] = time.time()
    _write(st)


def mark_reply() -> None:
    """답장을 보낸 시각을 남긴다 — **유휴 시계의 기준점**.

    사용자 메시지 시각만 기준으로 잡으면 내가 답하는 데 걸린 시간까지 유휴로 계산돼
    답하자마자 유휴가 4분이 되어 있다. 규칙은 「내가 답한 뒤 5분 안에 응답 없으면 종료」다.
    """
    st = load_state()
    st["last_reply_at"] = time.time()
    _write(st)


def idle_minutes():
    """유휴(분). 기준 = 사용자 메시지와 내 답장 중 **나중 것**.

    답장을 빼면 내가 오래 걸려 답한 만큼 유휴가 부풀어 루프가 일찍 죽는다.
    답장만 쓰면 내가 먼저 보낸 알림이 시계를 되돌려 필요 이상으로 오래 산다.
    """
    st = load_state()
    ts = [float(st[k]) for k in ("last_message_at", "last_reply_at") if st.get(k)]
    return None if not ts else (time.time() - max(ts)) / 60.0


def fetch(token: str, offset: int, timeout: int = 20) -> list:
    q = urllib.parse.urlencode({"offset": offset, "timeout": 0})
    try:
        with urllib.request.urlopen(f"{API.format(token=token)}?{q}", timeout=timeout) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"수신 실패 HTTP {e.code}") from None   # 토큰은 찍지 않는다
    except urllib.error.URLError as e:
        raise SystemExit(f"수신 실패 (네트워크): {e.reason}") from None
    if not body.get("ok"):
        raise SystemExit(f"수신 실패: {body}")
    return body.get("result", [])


STOP_WORDS = ("텔레그램 종료", "텔레그램종료", "루프 종료", "루프종료", "폴링 종료", "폴링종료")


def stop_requested(msgs: list) -> bool:
    """종료 지시가 있는가. 띄어쓰기 흔들림까지 받되 **너무 넓게 잡지 않는다** —
    "종료"만으로 판정하면 "배치 종료됐어?" 같은 평범한 문장이 루프를 죽인다."""
    return any(any(w in (m.get("text") or "") for w in STOP_WORDS) for m in msgs)


def main() -> None:
    p = argparse.ArgumentParser(description="텔레그램 새 메시지 읽기")
    p.add_argument("--peek", action="store_true", help="확인 처리하지 않는다")
    p.add_argument("--json", action="store_true", help="기계 판독용 출력")
    p.add_argument("--mark-reply", action="store_true",
                   help="답장 직후에 호출 — 유휴 시계를 지금부터 다시 센다")
    a = p.parse_args()

    if a.mark_reply:
        mark_reply()
        print("[답장기록] 유휴 시계를 지금부터 다시 셉니다.")
        return

    token, chat_id = creds()
    updates = fetch(token, load_offset())

    msgs, last, dropped = [], 0, 0
    for u in updates:
        last = max(last, u.get("update_id", 0))
        m = u.get("message") or u.get("edited_message")
        if not m or "text" not in m:
            continue
        if str(m.get("chat", {}).get("id")) != chat_id:
            dropped += 1            # 낯선 발신자 — 내용은 보지도 않는다
            continue
        msgs.append({"at": time.strftime("%H:%M", time.localtime(m.get("date", 0))),
                     "text": m["text"]})

    if last and not a.peek:
        save_offset(last + 1, got_message=bool(msgs))   # +1 이 확인 처리다

    idle = idle_minutes()

    if a.json:
        print(json.dumps({"messages": msgs, "dropped": dropped,
                          "stop_requested": stop_requested(msgs),
                          "idle_min": None if idle is None else round(idle, 1)},
                         ensure_ascii=False, indent=2))
        return

    for m in msgs:
        print(f"[{m['at']}] {m['text']}")
    # 종료 지시는 놓치면 안 되므로 **스크립트가 직접 집어내 전용 줄로 알린다.**
    # 루프가 목록을 읽고 알아채게 두면 다른 지시에 섞이거나 목록이 길 때 놓친다.
    # 폰에서 끈 사람은 꺼진 줄 알고 자리를 뜨는데 루프가 계속 도는 것이 가장 나쁘다.
    if stop_requested(msgs):
        print("\n[종료요청] 「텔레그램 종료」를 받았다 — 즉시 루프를 끝낼 것. "
              "종료 인사를 보낸 뒤 ScheduleWakeup(stop=true).")
    if dropped:
        print(f"\n※ 등록되지 않은 발신자의 메시지 {dropped}건을 버렸다 (내용은 읽지 않음).")
    if not msgs:
        mark = "" if idle is None or idle < 5 else "  ← 5분 경과, 종료할 것"
        print(f"[유휴] 새 메시지 없음 · 마지막 주고받음으로부터 "
              f"{'기록 없음' if idle is None else f'{idle:.0f}분'}{mark}")


if __name__ == "__main__":
    main()
