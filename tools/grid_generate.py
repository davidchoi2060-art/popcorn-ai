# -*- coding: utf-8 -*-
"""사전 생성 견적 격자 갱신 배치 — grid_cells 각 칸을 recommend 엔진으로 채운다.

배경: `docs/design/prebuilt-grid-benchmark-2026-09-07.md` §5. 새 조합 엔진을 만들지
않는다 — 기존 `POST /api/recommend`(고객 실시간 경로와 같은 엔진)를 그대로 호출해
칸마다 견적을 미리 만들어 둔다. 저장 구조는 `db/migrations/versions/0072_quote_grid.py`.

실행:
  .venv/Scripts/python tools/grid_generate.py --dry-run   (호출·판정만 하고 DB에 쓰지 않는다)
  .venv/Scripts/python tools/grid_generate.py

■ 티어 하한은 배치가 건다 — 엔진은 하한을 모른다 (2026-09-11 결함 A 수정)
  `api/candidates.py` `_budget_cap()`은 예산 라벨에서 **상한**만 읽는다("이상"이면
  None = 상한 없음, 하한은 어디에도 걸리지 않는다). 그래서 어느 칸이든 엔진이 낸
  총액이 칸의 budget_min 아래일 수 있다 — 배치 20260907-01 에서 팝콘 X 칸에 285~401만
  조합(팝콘 9 구간보다 싼 값)이 들어갔다. 엔진을 고치지 않고(고객 실시간 경로와
  같은 엔진이다 — 격자 사정으로 계약을 바꾸지 않는다) **배치가 응답을 보고 거른다**:
  `total < budget_min` 이면 그 칸은 실패(reason `below_tier_min total=X min=Y`).
  상한 쪽은 엔진이 verdict='over' 로 직접 말해 주므로 그대로 따른다.

■ 팝콘 X(budget_max NULL)의 예산 라벨 — «가상 상한» (2026-09-11)
  ① 필수 라벨 검사: `api/recommend.py` 는 "예산" 라벨이 없으면 무조건 400 이라
     라벨을 생략할 수 없다(이전 판 주석 그대로 유효).
  ② 이전 판은 "{budget_min}만원 이상"을 보냈다 — `_budget_cap()` 이 "이상"을 None 으로
     읽어 상한 없음이 되는 것까지는 의도대로였지만, 엔진은 **숫자 예산이 없으면
     추천 티어를 '중간 순위 우선'으로 고른다**(recommend.py 머리 주석 12행,
     `_order()` 267~270행). 즉 상한 없음 = 비싼 조합이 아니라 «중간 가격 조합» 이라
     하한 검사와 함께 쓰면 X 칸이 매번 떨어진다.
  ③ 그래서 X 칸에는 배치 내부에서만 쓰는 가상 상한 `budget_min × X_VIRTUAL_CAP_MULT`
     (기본 1.5) 를 "N만원" 라벨로 준다. 근거: 숫자 상한이 있으면 추천 티어는
     "예산 캡 풀 + 가격 내림차순 + 총액 가지치기"(같은 파일 9행·265행) 로 **상한
     근처의 첫 성립 조합**을 고른다 — 하한(=X 의 시작점) 위에 안착할 가능성이
     가장 큰 방식이다. 배수 1.5 는 recommend.py 의 HIGHEND_CAP_X(고성능 티어가
     예산을 넘어도 되는 배수)와 같은 값으로 맞췄다 — 엔진이 이미 "예산의 1.5배
     까지는 같은 고객의 견적"으로 취급하는 폭이다.
     한계:
       - 가상 상한은 **지어낸 값**이다. grid_cells.budget_max 는 NULL 그대로 두고
         이 스크립트 안에서만 쓴다(스키마·응답·payload 어디에도 박지 않는다 —
         payload 는 엔진 응답 그대로라 build.budget.cap 에는 가상 상한이 남는다.
         읽는 쪽은 그것을 티어 상한으로 오해하지 말 것: engine_note 에 표기해 둔다).
       - 내림차순 첫 성립이 반드시 하한 위라는 보장은 없다(재고 풀이 얇으면
         가지치기가 훨씬 아래에서 성립할 수 있다) — 그 경우 하한 검사로 정직하게
         실패 처리되고 grid_quotes 에 사유가 남는다. 배수를 키우면 안착 확률은
         오르지만 "팝콘 X 의 대표 견적"이 하한에서 점점 멀어진다 — 조정은 실측 후.
       - 상한 없음 티어의 대표 견적을 "하한×1.5 근처"로 «정의»한 것은 배치의
         결정이지 사장님 확정이 아니다(결정 이력에 없다). 다른 정의가 확정되면
         X_VIRTUAL_CAP_MULT 하나만 바꾸면 된다.

■ 실패도 원장에 남긴다 (2026-09-11 결함 B 수정)
  이전 판은 실패 칸을 stdout 에만 찍어 배치 20260907-01 의 14칸 실패 사유를
  되짚을 수 없었다. 이제 실패 칸도 grid_quotes 에 행을 INSERT 한다:
    status='생성 실패' · engine_note=사유(200자 절단) · payload=NULL · total=NULL ·
    verdict=NULL · is_current=true (이전 현재본은 false 로 내린다 — "이 칸의 현재
    상태는 실패"가 사실이다. 이전 견적을 현재본으로 남기면 화면이 «최신 배치가
    성공했다»는 거짓을 말한다).
  status 값 '생성 실패'는 0072 마이그레이션의 status 컬럼 주석("정상 / 예산 상한
  초과 / 재고 소진 슬롯 있음 / 생성 실패")을 따른 것이고, `api/admin_grid.py`
  `_cell_state()` 는 `"실패" in status` 로 판정하므로 그대로 fail 버킷에 들어간다.
  ⚠ 연결 오류(status None)로 3회 연속 실패해 중단(abort)하는 경우는 남은 칸을
  기록하지 않는다 — 서버가 죽은 것은 칸의 사실이 아니다. 중단 전에 시도한 칸의
  connection_error 는 기록한다.

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = "http://127.0.0.1:8000/api/recommend"
PLATFORM_ASCII = {"인텔": "intel", "AMD": "amd"}

# grid_quotes.status 값 — 0072 마이그레이션 status 컬럼 주석이 정본(이 파일이 판정)
STATUS_OK = "정상"
STATUS_OVER = "예산 상한 초과"
STATUS_FAIL = "생성 실패"

# 팝콘 X(budget_max NULL) 가상 상한 배수 — 파일 머리 주석 참조. 배치 내부 전용.
X_VIRTUAL_CAP_MULT = 1.5
NOTE_MAX = 200                     # grid_quotes.engine_note String(200)


def _effective_cap(budget_min: int, budget_max):
    """엔진에 보낼 상한(원). budget_max 가 있으면 그대로, NULL(팝콘 X)이면 가상 상한.
    두 번째 값은 가상 상한 여부."""
    if budget_max is not None:
        return budget_max, False
    return int(budget_min * X_VIRTUAL_CAP_MULT), True


def _budget_label(budget_min: int, budget_max) -> str:
    cap, _ = _effective_cap(budget_min, budget_max)
    return f"{cap // 10000}만원"


def _call_recommend(usage: str, budget_min: int, budget_max, platform: str) -> dict:
    constraints = [
        {"l": "용도", "v": usage},
        {"l": "예산", "v": _budget_label(budget_min, budget_max)},
        {"l": "플랫폼", "v": platform},
    ]
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


def judge(cell: dict, res: dict) -> dict:
    """엔진 응답 → grid_quotes 한 행의 판정. DB·네트워크 없음(단위 확인 가능).

    반환: {"status", "total", "verdict", "engine_note", "payload"(build dict|None),
           "reason"(실패 사유|None), "kind"("ok"|"over"|"fail"), "warn"(bool)}
    """
    def fail(reason: str) -> dict:
        return {"status": STATUS_FAIL, "total": None, "verdict": None,
                "engine_note": reason[:NOTE_MAX], "payload": None,
                "reason": reason, "kind": "fail", "warn": False}

    if not res["ok"]:
        if res["status"] is None:
            return fail(f"connection_error detail={res.get('detail', '')[:150]}")
        return fail(f"http_error status={res['status']} detail={res.get('detail', '')[:150]}")

    data = res["json"] or {}
    build = (data.get("sets") or {}).get("recommend")
    if build is None:
        exhausted = (data.get("search_exhausted") or {}).get("recommend")
        return fail(f"recommend_tier_null exhausted={exhausted}")

    total = build.get("total")
    budget_min = cell["budget_min"]
    # 하한 강제 — 엔진은 하한을 모른다(파일 머리 주석). total 이 None 이면 판정
    # 자체가 불가능하므로 그것도 실패다(지어내지 않는다).
    if total is None:
        return fail("total_missing recommend build has no total")
    if budget_min is not None and total < budget_min:
        return fail(f"below_tier_min total={total} min={budget_min}")

    budget = build.get("budget") or {}
    verdict = budget.get("verdict")
    status = STATUS_OK
    notes = []
    if verdict == "over":
        status = STATUS_OVER
        notes.append(f"engine_over_by={budget.get('over_by')}")
    cap, virtual = _effective_cap(budget_min, cell["budget_max"])
    if virtual:
        # payload.budget.cap 에 남는 값이 티어 상한이 아님을 읽는 쪽에 알린다
        notes.append(f"virtual_cap={cap} (budget_max NULL, x{X_VIRTUAL_CAP_MULT})")
    engine_note = (" / ".join(notes))[:NOTE_MAX] if notes else None
    return {"status": status, "total": total, "verdict": verdict,
            "engine_note": engine_note, "payload": build, "reason": None,
            "kind": "ok" if status == STATUS_OK else "over", "warn": False}


def write_row(wconn, cell_id: int, batch_id: str, judged: dict) -> None:
    """이전 현재본을 내리고 새 행 INSERT — 성공·실패 공통(실패는 payload/total NULL)."""
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE grid_quotes SET is_current=false"
        " WHERE cell_id=:cid AND is_current"), {"cid": cell_id})
    payload = judged["payload"]
    wconn.execute(text(
        "INSERT INTO grid_quotes (cell_id, batch_id, generated_at, engine_note,"
        " total, verdict, status, payload, is_current)"
        " VALUES (:cid, :bid, now(), :note, :total, :verdict, :status,"
        " CAST(:payload AS JSONB), true)"),
        {"cid": cell_id, "bid": batch_id, "note": judged["engine_note"],
         "total": judged["total"], "verdict": judged["verdict"],
         "status": judged["status"],
         "payload": json.dumps(payload, ensure_ascii=False) if payload is not None else None})


def _next_batch_id(conn) -> str:
    from sqlalchemy import text
    today = date.today().strftime("%Y%m%d")
    n = conn.execute(text(
        "SELECT count(DISTINCT batch_id) FROM grid_quotes WHERE batch_id LIKE :p"),
        {"p": f"{today}-%"}).scalar()
    return f"{today}-{n + 1:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                    help="engine calls + judgement only, no grid_quotes writes")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT cell_id, tier, usage, platform, budget_min, budget_max"
            " FROM grid_cells WHERE NOT intended_empty ORDER BY cell_id")).mappings().all()
        batch_id = _next_batch_id(conn)

    print(f"[grid_generate] target_cells={len(cells)} batch_id={batch_id} dry={int(args.dry)}"
          f" x_virtual_cap_mult={X_VIRTUAL_CAP_MULT}")

    t0 = time.time()
    ok_n, over_n, fail_n = 0, 0, 0
    failures = []
    conn_fail_streak = 0

    for cell in cells:
        platform_ascii = PLATFORM_ASCII.get(cell["platform"], "unknown")
        res = _call_recommend(cell["usage"], cell["budget_min"], cell["budget_max"],
                              cell["platform"])
        judged = judge(cell, res)

        if judged["kind"] == "fail":
            fail_n += 1
            failures.append((cell["cell_id"], judged["reason"]))
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> FAIL {judged['reason']}")
            conn_fail_streak = conn_fail_streak + 1 if (
                not res["ok"] and res["status"] is None) else 0
        else:
            conn_fail_streak = 0
            if judged["kind"] == "ok":
                ok_n += 1
            else:
                over_n += 1
            cap, virtual = _effective_cap(cell["budget_min"], cell["budget_max"])
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> {'OK' if judged['kind'] == 'ok' else 'OVER'} total={judged['total']}"
                  f" verdict={judged['verdict']} min={cell['budget_min']}"
                  f" cap={cap}{'(virtual)' if virtual else ''}")

        if not args.dry:
            with engine.begin() as wconn:
                write_row(wconn, cell["cell_id"], batch_id, judged)

        if conn_fail_streak >= 3:
            print("[grid_generate] FATAL: 3 consecutive connection errors -- "
                  "aborting, is the API server up at 127.0.0.1:8000? "
                  "(remaining cells NOT recorded)")
            break

    elapsed = time.time() - t0
    print(f"[grid_generate] done in {elapsed:.1f}s ok={ok_n} "
          f"over_budget={over_n} fail={fail_n} batch_id={batch_id}")
    if failures:
        print("[grid_generate] failures (also recorded in grid_quotes status='fail'"
              " unless --dry):")
        for cid, reason in failures:
            print(f"  cell_id={cid} {reason}")
    if args.dry:
        print("[grid_generate] --dry-run mode -- no rows written to grid_quotes")


if __name__ == "__main__":
    main()
