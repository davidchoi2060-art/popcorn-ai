# -*- coding: utf-8 -*-
"""보관 기한이 지난 고객 개인정보 지우기를 손으로 한 번 돌리기 (정기 실행은 API 안 스케줄러가 한다).

    python tools/retention_purge.py            # 미리보기: 지울 대상 건수만 기록한다
    python tools/retention_purge.py --apply    # 실제로 지운다

하는 일은 전부 `api/retention_purge.purge()` 가 한다. 실행 기록(retention_purge_runs.moment)에는
«manual» 로 남는다 — 정기 실행(auto)과 구분하고, 그 시각의 정기 실행을 대신 채우지 않는다.
출력은 ASCII 만 쓴다(서버 stdout 이 cp949 — 슬라이스 40). 실패하면 종료 코드 1.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from api import retention_purge as RP  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="purge customer data past its retention date (one run)")
    ap.add_argument("--apply", action="store_true", help="really clear the values (default: dry run)")
    a = ap.parse_args(argv)
    try:
        res = RP.purge("manual", apply=a.apply)
    except Exception as e:                                          # noqa: BLE001
        print("[retention-purge] failed: %s" % type(e).__name__)
        return 1
    print(json.dumps(res, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
