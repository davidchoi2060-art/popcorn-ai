# -*- coding: utf-8 -*-
"""사전 생성 견적 격자 갱신 배치 — grid_cells 각 칸을 recommend 엔진으로 채운다.

A-135 재설계 최종 단계(2026-09-16) — "가격 구간 먼저"에서 "용도·스펙이 먼저,
가격은 결과"로 전환. 새 조합 엔진을 만들지 않는다 — 기존 `POST /api/recommend`
(고객 실시간 경로와 같은 엔진)를 그대로 호출한다. 스펙 하한은 이제 엔진이 직접
받는다(`api/recommend.py` RecommendBody.gpu_watt_min 등, 이번 물결 신설) — 배치는
그 값을 spec_tiers/game_grade_resolution_tiers에서 읽어 넘기기만 한다. 저장 구조는
`db/migrations/versions/0092_grid_spec_axis.py`(비게임 칸 = tier_key+usage 6종,
게임 칸 = game_grade+game_resolution, grid_quotes.tier_variant 3종).

실행:
  .venv/Scripts/python tools/grid_generate.py --dry   (호출·판정만 하고 DB에 쓰지 않는다)
  .venv/Scripts/python tools/grid_generate.py

■ 스펙 하한은 엔진이 직접 건다 — 배치는 그 값을 「전달」만 한다(2026-09-16 재설계)
  옛 판(0072~0082 가격축)은 엔진에 스펙 하한 개념이 없어 배치가 사후에 "총액이
  칸의 budget_min 아래인가"만 봤다(`below_tier_min` 판정, 근사치). 지금은 엔진
  (`api/recommend.py` `_spec_floor_filter`)이 **후보 풀 단계에서** gpu_watt_min·
  cpu_cores_min·ram_min_gb·ssd_min_gb로 직접 거른다 — 예산과 무관한 독립 축이다.
  배치는 각 칸의 tier_key(비게임) 또는 (game_grade, game_resolution)의 스펙(게임)을
  spec_tiers/game_grade_resolution_tiers에서 읽어 그대로 넘기고, **예산은 넘기지
  않는다**(가격은 결과이지 입력이 아니다 — 아래 "예산 없음" 참조). 그래도 이 배치는
  엔진 응답의 items[].spec을 다시 읽어 실제로 하한을 만족하는지 사후 검증한다
  (below_tier_min — 엔진이 필터링을 제대로 했다면 항상 통과해야 하는 안전장치).

■ 예산 없음("AI 추천 예산") — 엔진의 기존 동작을 그대로 쓴다
  `api/recommend.py`는 "예산" 라벨을 필수로 요구하지만(400 회피), 숫자 예산이
  없으면(`_budget_cap`이 None을 줌) 추천 티어는 "중간 순위 우선"(`_order_of`
  머리 주석)으로, 고성능 티어는 그 자체로 가격 내림차순 + 상한 없음(단, 이제는
  스펙 하한이 후보를 좁혀 두므로 예전처럼 "가장 비싼 부품 아무거나"로 폭주하지
  않는다 — 스펙 하한이 이미 램·SSD를 합리적 범위로 제한한다)으로 동작한다.
  옛 "가상 상한"(X_VIRTUAL_CAP_MULT, budget_min×1.5를 라벨로 위장해 보내던 편법)은
  **폐기한다** — 예산 자체가 입력이 아니게 됐으니 위장할 하한도 없다.

■ 카드 3종(가성비/추천/고성능) — 한 번의 호출로 전부 받는다
  `/api/recommend` 응답의 `sets.value`·`sets.recommend`·`sets.highend`가 이미
  한 호출에 동시에 들어 있다(기존 옛 판 `judge()`가 `sets.recommend`만 쓰고
  나머지 둘을 버리고 있었다) — 이제 셋 다 grid_quotes에 tier_variant별로 INSERT.

■ budget_min/budget_max — 이제 입력이 아니라 관측값이다(0092 스키마 주석 그대로)
  배치가 실제로 만든 **추천(recommend) variant**의 총액을 grid_cells.budget_min/
  budget_max에 UPDATE한다(지시서 원문 그대로 — "배치가 실제 만든 추천 가격을
  budget_min/max에 UPDATE"). 셋을 각각 다른 값으로 만들 근거(가성비~고성능 범위 등)는
  지시서에 없어 지어내지 않는다 — min=max=추천 총액. 추천이 실패하면 NULL로 둔다
  (다른 variant가 성공해도 지어내지 않는다 — 지시서가 특정한 것은 recommend뿐).

■ 실패도 원장에 남긴다 (0072 이후 계승)
  실패 칸도 grid_quotes에 행을 INSERT한다: status='생성 실패' · engine_note=사유
  (200자 절단) · payload=NULL · total=NULL · verdict=NULL · is_current=true.
  ⚠ 연결 오류(status None)로 3회 연속 실패해 중단(abort)하는 경우는 남은 칸을
  기록하지 않는다 — 서버가 죽은 것은 칸의 사실이 아니다.

■ 원장 — UPDATE가 아니라 INSERT
  칸×variant를 다시 채울 때 이전 is_current 행을 false로 내리고 새 행을 INSERT한다
  (견적 이력 보존). 부분 유니크 인덱스(cell_id, tier_variant WHERE is_current)가
  "칸×variant당 현재본 하나"를 강제한다.

■ 콘솔 출력은 ASCII만 — cp949 콘솔에서 한글이 깨지는 것 자체는 tools/_console.py가
  막아 주지만, 이 스크립트는 지시에 따라 진행 로그를 ASCII로 고정한다.
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

# grid_quotes.status 값 — 0072 마이그레이션 status 컬럼 주석이 정본(이 파일이 판정).
# 예산 상한 개념이 없어졌으므로(스펙 하한만 남음) 성공 판정은 이제 STATUS_OK 하나뿐
# 이다 — verdict는 cap=None이면 엔진이 항상 "none"을 주므로 "over"가 나올 일이
# 없다(recommend.py `_build_set`: `verdict = "none" if cap is None else ...`). 그래도
# 상수 자체는 남긴다 — 0072 스키마 주석의 값 어휘(정상/예산 상한 초과/생성 실패)를
# 이 파일이 계속 참조하고, 언젠가 엔진이 다시 예산을 받는 날 이 분기가 되살아난다.
STATUS_OK = "정상"
STATUS_OVER = "예산 상한 초과"
STATUS_FAIL = "생성 실패"

NOTE_MAX = 200                     # grid_quotes.engine_note String(200)

# 엔진 티어 키 -> grid_quotes.tier_variant 값(0092 CHECK 제약: 가성비/추천/고성능)
VARIANT_MAP = {"value": "가성비", "recommend": "추천", "highend": "고성능"}
BUDGET_OBSERVE_VARIANT = "recommend"   # budget_min/max 관측값의 원천 variant(지시서 원문)

# 스펙 하한 사후 검증(below_tier_min 패턴) — (slot=part_type, spec 필드, floor 딕셔너리 키, 단위)
# recommend.py의 SPEC_FLOOR_SPECS와 같은 4슬롯이다 — 이 배치는 엔진이 이미 건 필터를
# 다시 구현하지 않고, 엔진 응답(items[].spec)이 실제로 그 하한을 만족하는지만 잰다.
CHECK_SPECS = (
    ("GPU", "required_power_watt", "gpu_watt_min", "W"),
    ("CPU", "cpu_cores", "cpu_cores_min", "코어"),
    ("RAM", "capacity_gb", "ram_min_gb", "GB"),
    ("SSD", "capacity_gb", "ssd_min_gb", "GB"),
)


def _load_spec_tiers(conn) -> dict:
    """spec_tiers 전행 -> {tier_key: {gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb}}."""
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT tier_key, gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb"
        " FROM spec_tiers")).mappings().all()
    return {r["tier_key"]: dict(r) for r in rows}


def _load_game_grade_tiers(conn) -> dict:
    """game_grade_resolution_tiers 전행 -> {(grade, resolution): {gpu_tier_key, cpu_tier_key_override}}."""
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT grade, resolution, gpu_tier_key, cpu_tier_key_override"
        " FROM game_grade_resolution_tiers")).mappings().all()
    return {(r["grade"], r["resolution"]): dict(r) for r in rows}


def cell_spec_floor(cell: dict, spec_tiers: dict, game_tiers: dict) -> dict:
    """격자 칸 하나 -> ({usage_label, gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb}, error|None).

    비게임 칸: spec_tiers[cell.tier_key]를 그대로 스펙 하한으로 쓴다. 용도(usage)는
    grid_cells.usage 컬럼 값을 그대로 「용도」 제약으로 보낸다 — 0092 마이그레이션
    자신의 주석대로 이 값은 이미 usage_floors.usage_label과 같은 어휘다(대화 파서와
    같은 라벨, 새로 매핑하지 않는다).

    게임 칸: game_grade_resolution_tiers에서 (grade, resolution)의 gpu_tier_key
    (+cpu_tier_key_override)를 찾는다. GPU watt 하한·RAM·SSD 하한은 **기본(gpu) tier**
    값을, CPU 코어 하한은 override가 있으면 **override tier** 값을 쓴다(S등급 GPU/CPU
    비대칭 — 원본 game_grade_resolution_tiers.note "GPU T2급/CPU T4급 비대칭" 그대로).
    override가 없으면 기본 tier 값을 그대로 쓴다(둘이 같은 tier가 된다). usage는
    "게임"으로 고정 — 대화 파서(usage_floors game/game_casual/gaming_high)가 이미
    쓰는 라벨과 같다(usage_floors.match()가 부분일치로 이 라벨을 그대로 받는다).

    FK 무결성이 이미 DB가 지키므로(0091·0092 ForeignKey) tier_key/grade/resolution이
    맵에 없는 경우는 데이터 정합이 깨진 것 — 지어내지 않고 error 문자열을 돌려준다.
    """
    if cell["usage"] != "게임":
        tier = spec_tiers.get(cell["tier_key"])
        if tier is None:
            return None, f"tier_key={cell['tier_key']!r}가 spec_tiers에 없습니다"
        return {
            "usage_label": cell["usage"],
            "gpu_watt_min": tier["gpu_watt_min"], "cpu_cores_min": tier["cpu_cores_min"],
            "ram_min_gb": tier["ram_min_gb"], "ssd_min_gb": tier["ssd_min_gb"],
        }, None

    key = (cell["game_grade"], cell["game_resolution"])
    gt = game_tiers.get(key)
    if gt is None:
        return None, f"(grade={cell['game_grade']!r}, resolution={cell['game_resolution']!r})가" \
                     " game_grade_resolution_tiers에 없습니다"
    base = spec_tiers.get(gt["gpu_tier_key"])
    if base is None:
        return None, f"gpu_tier_key={gt['gpu_tier_key']!r}가 spec_tiers에 없습니다"
    cpu_tier = base
    if gt["cpu_tier_key_override"]:
        cpu_tier = spec_tiers.get(gt["cpu_tier_key_override"])
        if cpu_tier is None:
            return None, f"cpu_tier_key_override={gt['cpu_tier_key_override']!r}가 spec_tiers에 없습니다"
    return {
        "usage_label": "게임",
        "gpu_watt_min": base["gpu_watt_min"], "cpu_cores_min": cpu_tier["cpu_cores_min"],
        "ram_min_gb": base["ram_min_gb"], "ssd_min_gb": base["ssd_min_gb"],
    }, None


def _mark_batch_session(wconn, res: dict) -> None:
    """배치 호출은 고객 상담이 아니다 — 방금 만들어진 consult_sessions 행을 'test' 로 표시.

    2026-09-14 실사고: 배치 6회가 real 상담 485행을 남겨 «오늘 상담 수»류 지표를 왜곡했다.
    X-Popcorn-Test 헤더는 .env 스위치가 켜져야 먹고(서버는 꺼져 있다) 그 스위치를
    켜 두면 회귀가 거짓 통과한다(CLAUDE.md §회귀). 그래서 헤더 대신 응답의 session_id 로
    바로 되짚어 표시한다 — 지우지 않는다(원장). 사장님 지시 "지워" 의 적용.
    """
    sid = ((res.get("json") or {}).get("session_id")) if res.get("ok") else None
    if sid is None:
        return
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE consult_sessions SET data_origin='test' WHERE session_id=:sid AND data_origin='real'"
    ), {"sid": sid})


def _call_recommend(usage_label: str, floor: dict, platform: str) -> dict:
    """엔진 호출 — 예산은 넘기지 않는다("AI 추천 예산", 숫자 상한 없음). 스펙 하한
    4종은 body 최상위 필드로 직접 넘긴다(constraints가 아니다 — RecommendBody 신설
    필드, api/recommend.py 참조). "예산" 라벨 자체는 여전히 필수(400 회피용 형식
    요건)이지만 그 값이 후보를 거르지는 않는다(_budget_cap이 "이상"/무숫자를 None
    으로 읽는 기존 동작 그대로 — 옛 "가상 상한" 편법 없이).
    """
    constraints = [
        {"l": "용도", "v": usage_label},
        {"l": "예산", "v": "AI 추천 예산"},
        {"l": "플랫폼", "v": platform},
    ]
    body = {
        "mode": "guided", "constraints": constraints,
        "gpu_watt_min": floor["gpu_watt_min"], "cpu_cores_min": floor["cpu_cores_min"],
        "ram_min_gb": floor["ram_min_gb"], "ssd_min_gb": floor["ssd_min_gb"],
    }
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


def _spec_violations(build: dict, floor: dict) -> list:
    """엔진이 실제로 스펙 하한을 지켰는지 사후 검증(below_tier_min 패턴, 안전장치).

    엔진(`_spec_floor_filter`)이 후보 풀 단계에서 이미 걸렀으므로 정상적으로는
    빈 목록이어야 한다 — 그런데도 남기는 이유는 "필터가 실제로 적용됐다"를
    지어내지 않고 확인하기 위해서다. 위반이 있으면 그 사실(슬롯·기대값·실제값)을
    그대로 문자열로 남긴다(지어내지 않는다 원칙).
    """
    items_by_slot = {it.get("part_type"): it for it in (build.get("items") or [])}
    out = []
    for slot, field, floor_key, unit in CHECK_SPECS:
        min_v = floor.get(floor_key)
        if min_v is None:
            continue   # 이 슬롯엔 하한이 없다 — 검증할 것이 없다
        item = items_by_slot.get(slot)
        if item is None:
            # GPU가 iGPU 생략으로 빠졌을 수 있다 — 그런데 하한이 있으면(min_v is not
            # None) 엔진이 allow_igpu_omit을 False로 처리해 생략하지 않아야 정상이다
            # (recommend.py: `body.gpu_watt_min is None` 조건). 슬롯 자체가 없으면
            # 하한을 만족하는지 확인할 수 없으므로 위반으로 남긴다(모르는 것을
            # 통과로 지어내지 않는다).
            out.append(f"{slot} 슬롯 없음(하한 {min_v}{unit} 기대)")
            continue
        val = (item.get("spec") or {}).get(field)
        if val is None or val < min_v:
            out.append(f"{slot}.{field}={val} < {min_v}{unit}")
    return out


def judge_variant(cell_id: int, eng_key: str, data: dict, floor: dict) -> dict:
    """엔진 응답 하나에서 티어 하나(value/recommend/highend)의 grid_quotes 행 판정.

    반환: {"status", "total", "verdict", "engine_note", "payload"(build|None), "kind"}
    kind: "ok" | "fail" — 예산 상한 개념이 사라져 "over"는 이제 이론상 나오지
    않는다(verdict는 cap=None이면 항상 "none").
    """
    def fail(reason: str) -> dict:
        return {"status": STATUS_FAIL, "total": None, "verdict": None,
                "engine_note": reason[:NOTE_MAX], "payload": None, "kind": "fail", "reason": reason}

    build = (data.get("sets") or {}).get(eng_key)
    if build is None:
        exhausted = (data.get("search_exhausted") or {}).get(eng_key)
        return fail(f"{eng_key}_tier_null exhausted={exhausted}")

    total = build.get("total")
    if total is None:
        return fail("total_missing recommend build has no total")

    violations = _spec_violations(build, floor)
    if violations:
        return fail("below_tier_min " + "; ".join(violations))

    verdict = (build.get("budget") or {}).get("verdict")
    status = STATUS_OVER if verdict == "over" else STATUS_OK
    return {"status": status, "total": total, "verdict": verdict,
            "engine_note": None, "payload": build, "kind": "ok" if status == STATUS_OK else "fail",
            "reason": None}


def write_quote_row(wconn, cell_id: int, variant: str, batch_id: str, judged: dict) -> None:
    """칸×variant의 이전 현재본을 내리고 새 행 INSERT — 성공·실패 공통."""
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE grid_quotes SET is_current=false"
        " WHERE cell_id=:cid AND tier_variant=:tv AND is_current"),
        {"cid": cell_id, "tv": variant})
    payload = judged["payload"]
    wconn.execute(text(
        "INSERT INTO grid_quotes (cell_id, tier_variant, batch_id, generated_at, engine_note,"
        " total, verdict, status, payload, is_current)"
        " VALUES (:cid, :tv, :bid, now(), :note, :total, :verdict, :status,"
        " CAST(:payload AS JSONB), true)"),
        {"cid": cell_id, "tv": variant, "bid": batch_id, "note": judged["engine_note"],
         "total": judged["total"], "verdict": judged["verdict"], "status": judged["status"],
         "payload": json.dumps(payload, ensure_ascii=False) if payload is not None else None})


def write_budget_observed(wconn, cell_id: int, recommend_total) -> None:
    """budget_min/budget_max — 입력이 아니라 관측값(0092 스키마 주석). 배치가 실제로
    만든 **추천(recommend) variant** 가격을 그대로 UPDATE한다(지시서 원문). 추천이
    실패했으면(recommend_total is None) NULL로 둔다 — 다른 variant가 성공했어도
    지어내지 않는다(지시서가 특정한 원천은 recommend 하나뿐이다)."""
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE grid_cells SET budget_min=:v, budget_max=:v WHERE cell_id=:cid"),
        {"v": recommend_total, "cid": cell_id})


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
                    help="engine calls + judgement only, no grid_quotes/grid_cells writes")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        cells = conn.execute(text(
            "SELECT cell_id, tier_key, usage, game_grade, game_resolution, platform"
            " FROM grid_cells WHERE NOT intended_empty ORDER BY cell_id")).mappings().all()
        spec_tiers = _load_spec_tiers(conn)
        game_tiers = _load_game_grade_tiers(conn)
        batch_id = _next_batch_id(conn)

    print(f"[grid_generate] target_cells={len(cells)} batch_id={batch_id} dry={int(args.dry)}")

    t0 = time.time()
    ok_n, fail_cell_n, fail_variant_n = 0, 0, 0
    failures = []
    conn_fail_streak = 0

    for cell in cells:
        platform_ascii = PLATFORM_ASCII.get(cell["platform"], "unknown")
        floor, err = cell_spec_floor(cell, spec_tiers, game_tiers)
        if err:
            # 데이터 정합 자체가 깨진 경우 — 엔진 호출 없이 3 variant 모두 실패로
            # 남긴다(견적 불가 판정, 어느 슬롯이 왜 비었는지 사유를 남긴다 원칙).
            fail_cell_n += 1
            failures.append((cell["cell_id"], f"spec_floor_lookup_failed: {err}"))
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> FAIL spec_floor_lookup_failed: {err}")
            if not args.dry:
                with engine.begin() as wconn:
                    for variant in VARIANT_MAP.values():
                        write_quote_row(wconn, cell["cell_id"], variant, batch_id, {
                            "status": STATUS_FAIL, "total": None, "verdict": None,
                            "engine_note": err[:NOTE_MAX], "payload": None})
                    write_budget_observed(wconn, cell["cell_id"], None)
            continue

        res = _call_recommend(floor["usage_label"], floor, cell["platform"])

        if not res["ok"]:
            fail_cell_n += 1
            reason = (f"connection_error detail={res.get('detail', '')[:150]}"
                      if res["status"] is None else
                      f"http_error status={res['status']} detail={res.get('detail', '')[:150]}")
            failures.append((cell["cell_id"], reason))
            print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
                  f" -> FAIL {reason}")
            if not args.dry:
                with engine.begin() as wconn:
                    for variant in VARIANT_MAP.values():
                        write_quote_row(wconn, cell["cell_id"], variant, batch_id, {
                            "status": STATUS_FAIL, "total": None, "verdict": None,
                            "engine_note": reason[:NOTE_MAX], "payload": None})
                    write_budget_observed(wconn, cell["cell_id"], None)
            conn_fail_streak = conn_fail_streak + 1 if res["status"] is None else 0
            if conn_fail_streak >= 3:
                print("[grid_generate] FATAL: 3 consecutive connection errors -- "
                      "aborting, is the API server up at 127.0.0.1:8000? "
                      "(remaining cells NOT recorded)")
                break
            continue

        conn_fail_streak = 0
        data = res["json"] or {}
        judged_by_variant = {}
        cell_ok = True
        for eng_key, variant in VARIANT_MAP.items():
            judged = judge_variant(cell["cell_id"], eng_key, data, floor)
            judged_by_variant[variant] = judged
            if judged["kind"] == "ok":
                ok_n += 1
            else:
                fail_variant_n += 1
                cell_ok = False
                failures.append((cell["cell_id"], f"{variant}: {judged['reason']}"))

        recommend_total = judged_by_variant[VARIANT_MAP["recommend"]]["total"]
        summary = " ".join(
            f"{v}={j['total'] if j['total'] is not None else 'FAIL'}"
            for v, j in judged_by_variant.items())
        print(f"[grid_generate] cell_id={cell['cell_id']} platform={platform_ascii}"
              f" usage={floor['usage_label']} -> {'OK' if cell_ok else 'PARTIAL'} {summary}")

        if not args.dry:
            with engine.begin() as wconn:
                for variant, judged in judged_by_variant.items():
                    write_quote_row(wconn, cell["cell_id"], variant, batch_id, judged)
                write_budget_observed(wconn, cell["cell_id"], recommend_total)
                _mark_batch_session(wconn, res)

    elapsed = time.time() - t0
    print(f"[grid_generate] done in {elapsed:.1f}s ok_variants={ok_n} "
          f"fail_cells={fail_cell_n} fail_variants={fail_variant_n} batch_id={batch_id}")
    if failures:
        print("[grid_generate] failures (also recorded in grid_quotes status='fail'"
              " unless --dry):")
        for cid, reason in failures:
            print(f"  cell_id={cid} {reason}")
    if args.dry:
        print("[grid_generate] --dry mode -- no rows written to grid_quotes/grid_cells")


if __name__ == "__main__":
    main()
