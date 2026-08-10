#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""텔레그램 자격증명 읽기 — **프로젝트별로 다른 봇**을 쓸 수 있게 한다.

■ 왜 환경변수만으로는 안 되나 (2026-08-10 실제로 걸린 것)
  핸드오프 문서는 `setx` 로 등록한 환경변수를 전제로 했다. 그런데 이 PC 에는 이미
  **다른 프로젝트의 봇 토큰**이 들어 있었다(`@sola_pipeline_bot` — 설교영상 계기판).
  환경변수는 PC 에 하나뿐이라 그대로 쓰면 **팝콘AI 알림이 설교영상 봇으로 간다.**

  그래서 읽는 순서를 정한다:

      ① 프로젝트 `.env`  ← 이 프로젝트의 봇. 여기 있으면 이걸 쓴다
      ② 환경변수         ← 없을 때만

  `.env` 를 **먼저** 보는 이유: 전역 환경변수가 남아 있어도 프로젝트 값이 이긴다.
  반대로 두면 다른 프로젝트 봇으로 조용히 나가고, 그건 알아채기 어렵다.

■ `.env` 는 이미 `.gitignore` 에 있다(DATABASE_URL 이 거기 있다).
  **토큰을 리포·문서·메모리에 적지 않는다**(전역 규약).

■ 표준 라이브러리만 쓴다 — 핸드오프의 "설치할 것이 없다"를 지킨다.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")

KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def _from_env_file() -> dict:
    """`.env` 를 아주 단순하게 읽는다 — `KEY=값` 만 본다.

    따옴표와 `export ` 접두는 벗긴다. `#` 로 시작하는 줄은 건너뛴다.
    값 안의 `#` 는 주석으로 보지 않는다 — 토큰에 들어갈 수 있다.
    """
    out = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith("export "):
                    k = k[7:].strip()
                if k in KEYS:
                    out[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def creds() -> tuple[str, str]:
    """(토큰, chat_id). 없으면 **무엇이 없는지** 말하고 끝낸다."""
    fromfile = _from_env_file()
    token = (fromfile.get("TELEGRAM_BOT_TOKEN")
             or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    chat = (fromfile.get("TELEGRAM_CHAT_ID")
            or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    missing = [n for n, v in zip(KEYS, (token, chat)) if not v]
    if missing:
        raise SystemExit(
            "텔레그램 자격증명 없음: %s\n"
            "  이 프로젝트의 .env 에 넣으십시오 (환경변수보다 우선합니다):\n"
            "    TELEGRAM_BOT_TOKEN=...\n"
            "    TELEGRAM_CHAT_ID=...\n"
            "  ※ .env 는 gitignore 돼 있습니다. 토큰을 리포에 적지 마십시오."
            % ", ".join(missing)
        )
    return token, chat


def source_note() -> str:
    """어느 쪽에서 읽었는지 — **다른 프로젝트 봇으로 잘못 나가는 것**을 알아채는 줄."""
    f = _from_env_file()
    return ".env" if f.get("TELEGRAM_BOT_TOKEN") else "환경변수(전역)"
