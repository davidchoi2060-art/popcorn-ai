#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""현황 한 눈에 — 텔레그램 「현황」 명령이 부르는 스크립트.

**폰 화면이라 짧아야 한다.** 표를 쓰지 않고 3~5줄로 끝낸다(`docs/telegram-rules.md` §4).

  py scripts/status.py                      # 화면에 출력
  py scripts/notify_telegram.py --title 현황 --run py scripts/status.py

`--run` 으로 감싸는 이유: PowerShell 파이프를 거치면 한글이 전부 '?' 가 된다.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _n(v) -> str:
    return format(int(v or 0), ",")


def main() -> None:
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        q = lambda s: c.execute(text(s)).scalar()          # noqa: E731
        pool = q("SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        review = q("SELECT COUNT(*) FROM product_reviews WHERE review_status='대기'")
        today = q("SELECT COUNT(*) FROM orders WHERE created_at::date = CURRENT_DATE")
        sess = q("SELECT COUNT(*) FROM consult_sessions WHERE created_at::date = CURRENT_DATE")
        std = q("SELECT COUNT(*) FROM std.part_specs")
        ven = q("SELECT COUNT(*) FROM std.part_specs WHERE source='vendor'")
        hum = q("SELECT COUNT(*) FROM std.part_specs WHERE source='human'")

    print(f"추천 후보 {_n(pool)} · 검수 대기 {_n(review)}")
    print(f"오늘 상담 {_n(sess)} · 주문 {_n(today)}")
    print(f"조립 표준 값 {_n(std)} (사람 {_n(hum)} · 제조사 {_n(ven)})")


if __name__ == "__main__":
    main()
