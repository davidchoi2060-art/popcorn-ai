#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""텔레그램 연결 진단 — **어느 봇에 붙어 있는지**와 chat_id 를 찾는다.

토큰만 있으면 돌아간다(chat_id 는 없어도 된다 — 그걸 찾는 게 이 스크립트다).

  py scripts/tg_setup.py           진단만
  py scripts/tg_setup.py --write   찾은 chat_id 를 .env 에 기록

■ 이 스크립트가 있는 이유
  이 PC 의 전역 환경변수에는 **다른 프로젝트 봇** 토큰이 남아 있었다.
  그대로 쓰면 팝콘AI 알림이 엉뚱한 봇으로 나가는데, 발송은 성공하므로
  **아무도 알아채지 못한다.** 그래서 붙은 봇의 이름을 먼저 찍는다.

■ 토큰은 절대 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tg_env import ENV_FILE, _from_env_file, source_note          # noqa: E402

EXPECT_BOT = "popcornpc_ai_bot"      # 이 프로젝트가 쓰기로 한 봇


def _get(url: str, timeout: int = 20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="찾은 chat_id 를 .env 에 기록")
    a = ap.parse_args()

    token = (_from_env_file().get("TELEGRAM_BOT_TOKEN")
             or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN 이 없습니다.\n"
            f"  {ENV_FILE} 에 한 줄 넣으십시오:\n"
            "    TELEGRAM_BOT_TOKEN=<BotFather 토큰>\n"
            "  (setx 로 등록해도 됩니다. .env 가 우선입니다.)")

    print("자격증명 출처: %s" % source_note())
    try:
        me = _get("https://api.telegram.org/bot%s/getMe" % token).get("result", {})
    except urllib.error.HTTPError as e:
        raise SystemExit("getMe 실패 HTTP %s — 토큰이 잘못됐을 수 있습니다." % e.code) from None
    uname = me.get("username", "?")
    print("붙은 봇: @%s (%s)" % (uname, me.get("first_name", "")))
    if uname != EXPECT_BOT:
        print("  ⚠ 이 프로젝트가 쓰기로 한 봇은 @%s 입니다." % EXPECT_BOT)
        print("    지금 토큰은 **다른 봇**입니다 — 알림이 엉뚱한 곳으로 갑니다.")

    res = _get("https://api.telegram.org/bot%s/getUpdates" % token).get("result", [])
    chats = {}
    for u in res:
        m = u.get("message") or u.get("edited_message") or {}
        ch = m.get("chat") or {}
        if ch.get("id"):
            chats[str(ch["id"])] = "%s / %s" % (
                ch.get("type", "?"),
                ch.get("first_name") or ch.get("title") or ch.get("username") or "")
    print("\n대기 중인 업데이트 %d건 · 발신 대화 %d개" % (len(res), len(chats)))
    for cid, desc in chats.items():
        print("   chat_id=%s   %s" % (cid, desc))

    cur = _from_env_file().get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    if cur:
        print("\n현재 설정된 chat_id: %s%s" % (cur, "" if cur in chats else "  (이번 목록엔 없음)"))

    if not chats:
        print("\n→ 폰이나 PC 텔레그램에서 @%s 를 열고 **START** 를 누른 뒤" % EXPECT_BOT)
        print("  아무 메시지나 하나 보내고 다시 실행하십시오.")
        print("  (봇은 사용자가 먼저 말을 걸기 전에는 발송할 수 없습니다.)")
        return

    if a.write:
        if len(chats) > 1:
            raise SystemExit("\n대화가 여럿입니다 — 어느 것인지 사람이 골라야 합니다. "
                             "직접 .env 에 적으십시오.")
        cid = next(iter(chats))
        if cur == cid:
            print("\n이미 같은 값이 설정돼 있습니다. 바꿀 것 없음.")
            return
        with open(ENV_FILE, "a", encoding="utf-8") as f:
            f.write("\nTELEGRAM_CHAT_ID=%s\n" % cid)
        print("\n.env 에 TELEGRAM_CHAT_ID=%s 를 기록했습니다." % cid)
    elif not cur:
        print("\n→ `--write` 를 주면 이 chat_id 를 .env 에 기록합니다.")


if __name__ == "__main__":
    main()
