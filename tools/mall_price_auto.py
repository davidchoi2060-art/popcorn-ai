# -*- coding: utf-8 -*-
"""쇼핑몰 가격 자동 갱신을 손으로 한 번 돌리기 (매일 06:00 · 13:00 KST 정기 실행은 API 안 스케줄러가 한다).

    python tools/mall_price_auto.py            # 수집 -> 비교 -> 판매가 반영 -> 실행 기록
    python tools/mall_price_auto.py --check    # 설정 이름과 «있는지»만 본다(값은 안 보인다, 요청 없음)

하는 일은 전부 `api/mall_price_auto.run()` 이 한다. 관리자 화면 「지금 실행」과 같은 함수다.
실행 기록(mall_price_runs.moment)에는 «manual» 로 남는다 — 정기 실행(auto)과 구분하고,
손으로 돌린 것이 그 시각의 정기 실행을 대신 채우지 않게 한다(2026-10-11 코덱스 검수 반영).
출력은 ASCII 만 쓴다(서버 stdout 이 cp949 — 슬라이스 40). 실패하면 종료 코드 1.
실패 사유 원문(한국어)은 관리자 화면 · mall_price_runs 에 남는다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()                   # 개발 PC 용. 서버는 EnvironmentFile=/etc/popcorn-ai.env 로 이미 들어와 있다

from api import mall_price_auto as AUTO  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mall price auto update (one run)")
    ap.add_argument("--check", action="store_true", help="show which settings exist; no request, no write")
    a = ap.parse_args(argv)
    cfg = AUTO.settings()
    if a.check:
        print("login=%s export_url=%s -> source=%s" % (
            cfg["login"], cfg["export_url"], "export" if cfg["login"] and cfg["export_url"] else "pages"))
        print("names: " + " ".join(cfg["names"]))
        return 0
    res = AUTO.run("manual")
    print(json.dumps(res, ensure_ascii=True))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
