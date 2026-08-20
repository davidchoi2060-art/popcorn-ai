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
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

# 세션 조회 술어(「어느 세션을 포함하는가」) 단일 원천 — U-34 대응, api/session_scope.py 참조.
from api.session_scope import session_scope_where                 # noqa: E402
# 「오늘」= KST 달력일. DB(naive)는 UTC라 CURRENT_DATE를 그대로 쓰면 09:00 KST 이전에는
# 「오늘」이 KST 어제와 섞인다(api/timeutil.py 규약). api/admin_ai_usage.py:_period_bounds ·
# api/llm.py:_today_kst_lo 와 같은 패턴 — 새로 만들지 않고 그대로 따른다.
from api.timeutil import KST, iso, kst_day_range                  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _n(v) -> str:
    return format(int(v or 0), ",")


def main() -> None:
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        q = lambda s: c.execute(text(s)).scalar()          # noqa: E731
        qp = lambda s, p: c.execute(text(s), p).scalar()   # noqa: E731
        pool = q("SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")
        review = q("SELECT COUNT(*) FROM product_reviews WHERE review_status='대기'")

        # KST 오늘 하루 -> UTC naive 반개구간 [lo, hi) (timeutil.kst_day_range 단일 원천).
        today_kst = datetime.now(KST).date()
        lo, hi = kst_day_range(iso(today_kst), iso(today_kst))
        params = {"lo": lo, "hi": hi}
        today = qp("SELECT COUNT(*) FROM orders WHERE created_at >= :lo AND created_at < :hi",
                    params)
        sess = qp(f"SELECT COUNT(*) FROM consult_sessions s WHERE {session_scope_where()}"
                  " AND created_at >= :lo AND created_at < :hi", params)

        std = q("SELECT COUNT(*) FROM std.part_specs")
        ven = q("SELECT COUNT(*) FROM std.part_specs WHERE source='vendor'")
        hum = q("SELECT COUNT(*) FROM std.part_specs WHERE source='human'")

    print(f"추천 후보 {_n(pool)} · 검수 대기 {_n(review)}")
    print(f"오늘 상담 {_n(sess)} · 주문 {_n(today)}")
    print(f"조립 표준 값 {_n(std)} (사람 {_n(hum)} · 제조사 {_n(ven)})")


if __name__ == "__main__":
    main()
