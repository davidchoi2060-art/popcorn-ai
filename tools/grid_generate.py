# -*- coding: utf-8 -*-
"""사전 생성 견적 격자 갱신 배치 — grid_cells 각 칸을 recommend 엔진으로 채운다.

배경: `docs/design/prebuilt-grid-benchmark-2026-09-07.md` §5. 새 조합 엔진을 만들지
않는다 — 기존 `POST /api/recommend`(고객 실시간 경로와 같은 엔진)를 그대로 호출해
칸마다 견적을 미리 만들어 둔다. 저장 구조는 `db/migrations/versions/0072_quote_grid.py`.

실행:
  .venv/Scripts/python tools/grid_generate.py --dry   (호출만 하고 DB에 쓰지 않는다)
  .venv/Scripts/python tools/grid_generate.py

■ 팝콘 X(budget_max NULL)의 예산 라벨 — 문서·지시는 "예산 라벨 생략"이라고 했지만
  `api/recommend.py`의 필수 라벨 검사(missing 목록에 "예산"이 없으면 무조건 400,
  1005~1008행)에는 예외가 없다 — 그대로 생략하면 팝콘 X 16칸이 전부 400으로
  실패한다. 대신 "{budget_min//10000}만원 이상"을 보낸다: `_budget_cap()`이 값에
  "이상"이 있으면 무조건 None(상한 없음)을 돌려주므로(api/candidates.py:228-229)
  팝콘 X가 뜻하는 "상한 없음"과 정확히 같은 효과를 내면서 필수 라벨 검사도 통과한다.
  실측하지 않고 문서 문구를 곧이곧대로 옮기면 생기는 확실한 실패를 피하기 위한
  의도적 이탈이다 — 근거는 이 주석과 실행 보고.

■ 원장 — UPDATE가 아니라 INSERT
  칸을 다시 채울 때 이전 is_current 행을 false로 내리고 새 행을 INSERT한다(견적
  이력 보존). 부분 유니크 인덱스가 "칸당 현재본 하나"를 강제한다.

■ 콘솔 출력은 ASCII만 — cp949 콘솔에서 한글이 깨지는 것 자체는 tools/_console.py가
  막아 주지만, 이 스크립트는 지시에 따라 진행 로그를 ASCII로 고정한다(플랫폼은
  intel/amd로, 티어·용도명은 cell_id로 대신한다 — 사람이 읽는 매핑은 grid_cells를
  직접 조회해서 본다).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                       # noqa: E402
from sqlalchemy import create_engine, text           # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = "http://127.0.0.1:8000/api/recommend"
PLATFORM_ASCII = {"인텔": "intel", "AMD": "amd"}


def _call_recommend(usage: str, budget_min: int, budget_max, platform: str) -> dict:
    constraints = [{"l": "용도", "v": usage}]
    if budget_max is not None:
        constraints.append({"l": "예산", "v": f"{budget_max // 10000}만원"})
    else:
        constraints.append({"l": "예산", "v": f"{budget_min // 10000}만원 이상"})
    constraints.append({"l": "플랫폼", "v": platform})
    body = {"mode": "guided", "constraints": constraints}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return {"ok": True, "status": resp.status, "json": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": e.code, "detail": detail}
    except urllib.error.URLError as e:
        return {"ok": False, "status": None, "detail": str(e.reason)}


def _next_batch_id(conn) -> str:
    today = date.today().strftime("%Y%m%d")
    n = conn.execute(text(
        "SELECT count(DISTINCT batch_id) FROM grid_quotes WHERE batch_id LIKE :p"),
        {"p": f"{today}-%"}).scalar()
    return f"{today}-{n + 1:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT cell_id, tier, usage, platform, budget_min, budget_max"
            " FROM grid_cells WHERE NOT intended_empty ORDER BY cell_id")).mappings().all()
        batch_id = _next_batch_id(conn)

    print(f"[grid_generate] target_cells={len(cells)} batch_id={batch_id} dry={int(args.dry)}")

    t0 = time.time()
    ok_n, warn_n, over_n, fail_n = 0, 0, 0, 0
    failures = []
    conn_fail_streak = 0

    for cell in cells:
        platform_ascii = PLATFORM_ASCII.get(cell["platform"], "unknown")
        res = _call_recommend(cell["usage"], cell["budget_min"], cell["budget_max"],
                               cell["platform"])

        if not res["ok"]:
            fail_n += 1
            if res["status"] is None:
                conn_fail_streak += 1
                reason = f"connection_error detail={res.get('detail', '')[:200]}"
            else:
                conn_fail_streak = 0
                reason = f"http_error status={res['status']} detail={res.get('detail', '')[:200]}"
            failures.append((cell["cell_id"], reason))
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> FAIL {reason}")
            if conn_fail_streak >= 3:
                print("[grid_generate] FATAL: 3 consecutive connection errors -- "
                      "aborting, is the API server up at 127.0.0.1:8000?")
                break
            continue
        conn_fail_streak = 0

        data = res["json"]
        build = (data.get("sets") or {}).get("recommend")
        if build is None:
            fail_n += 1
            exhausted = (data.get("search_exhausted") or {}).get("recommend")
            reason = f"recommend_tier_null exhausted={exhausted}"
            failures.append((cell["cell_id"], reason))
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> FAIL {reason}")
            continue

        total = build.get("total")
        budget = build.get("budget") or {}
        verdict = budget.get("verdict")
        status = "정상"
        notes = []
        if verdict == "over":
            status = "예산 상한 초과"
            notes.append(f"engine_over_by={budget.get('over_by')}")
        if cell["budget_min"] is not None and total is not None and total < cell["budget_min"]:
            notes.append(f"예산 미달 경고: 총액 {total}원 < 칸 하한 {cell['budget_min']}원")
        engine_note = " / ".join(notes) if notes else None

        if status == "정상":
            ok_n += 1
            if notes:
                warn_n += 1
        else:
            over_n += 1

        console_status = "OK" if status == "정상" else "OVER"
        print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
              f" -> {console_status} total={total} verdict={verdict}")

        if args.dry:
            continue

        with engine.begin() as wconn:
            wconn.execute(text(
                "UPDATE grid_quotes SET is_current=false"
                " WHERE cell_id=:cid AND is_current"), {"cid": cell["cell_id"]})
            wconn.execute(text(
                "INSERT INTO grid_quotes (cell_id, batch_id, generated_at, engine_note,"
                " total, verdict, status, payload, is_current)"
                " VALUES (:cid, :bid, now(), :note, :total, :verdict, :status,"
                " CAST(:payload AS JSONB), true)"),
                {"cid": cell["cell_id"], "bid": batch_id, "note": engine_note,
                 "total": total, "verdict": verdict, "status": status,
                 "payload": json.dumps(build, ensure_ascii=False)})

    elapsed = time.time() - t0
    print(f"[grid_generate] done in {elapsed:.1f}s ok={ok_n}(warn={warn_n}) "
          f"over_budget={over_n} fail={fail_n} batch_id={batch_id}")
    if failures:
        print("[grid_generate] failures:")
        for cid, reason in failures:
            print(f"  cell_id={cid} {reason}")
    if args.dry:
        print("[grid_generate] --dry mode -- no rows written to grid_quotes")


if __name__ == "__main__":
    main()
