# -*- coding: utf-8 -*-
"""사전 생성 견적 격자 갱신 배치 — grid_cells 각 칸을 recommend 엔진으로 채운다.

0105 예산대 축 재설계(2026-09-20). 새 조합 엔진을 만들지 않는다 — 기존
`POST /api/recommend`(고객 실시간 경로와 같은 엔진)를 그대로 호출한다.
저장 구조는 `db/migrations/versions/0105_grid_budget_band_axis.py`.

실행:
  .venv/Scripts/python tools/grid_generate.py --dry
  .venv/Scripts/python tools/grid_generate.py

■ 무엇이 바뀌었나 — 실측으로 확인된 결함 둘을 고친다
  (A) **등급이 엔진에 도달하지 않았다.** 옛 `cell_spec_floor()` 는 `game_grade` 를
      tier 조회 키로만 쓰고 반환 dict 에서 버렸다. DB 에서 `E/1080p` 와 `L/1080p`
      가 같은 행(T1·override NULL)이라 두 칸이 엔진에 보내는 body 가 바이트 단위로
      같았다 — 18칸이 실제로는 5가지 하한이었다.
      → 이제 칸의 **예산대**(grid_budget_bands)가 함께 엔진으로 간다. 같은 T1
      하한이라도 예산대가 다르면 다른 가격이 나온다(아래 (B) 참조).
  (B) **하한이 가격을 정하지 못했다.** `api/recommend.py _order_of()` 는 숫자 예산이
      없으면 `"median"`(후보 풀 중앙값)을 준다 — 실측상 GPU 하한을 완전히 제거해도
      추천 총액이 2,229,400 으로 T1(2,199,300)과 거의 같았다. 하한이 아니라 **풀
      모양**이 가격을 만들고 있었다.
      → 이제 `{"l":"예산","v":band.budget_label}` 로 **숫자 예산**을 보낸다.
        `api/candidates.py _budget_cap()` 이 그 문자열에서 상한을 읽으면
        `has_cap=True` 가 되어 `_order_of` 가 `desc`+예산 가지치기로 바뀐다.
        실측: T1 하한 + "150만원" → 추천 1,499,900 (엔진은 원래 할 수 있었다).
      ⚠ **라벨 형식이 정확해야 한다.** `_budget_cap` 의 정규식은
        `(-)?\\s*(\\d{1,3}(?:,\\d{3})+|\\d+)\\s*만` 이고 "이상"이 들어 있으면 None 을
        준다. 형식을 벗어나면 엔진이 **조용히 무시**하고 median 으로 되돌아간다.
        그래서 이 배치는 라벨을 지어내지 않고 `grid_budget_bands.budget_label`
        컬럼(0105 가 그 형식에 맞춰 넣은 값)을 그대로 실어 보낸다.

■ 3종을 전부 살린다 — quote_low/quote_high 가 «관측 범위»다
  옛 판은 `budget_min = budget_max = 추천 총액` 이었다(단일 관측점). 그래서 같은
  칸의 가성비 구성(실측 921,100원)이 발행되지 않고 버려졌다.
  이제 `quote_low = 가성비 총액` · `quote_high = 고성능 총액` 으로 **실제 3종의
  범위**를 기록한다. 추천은 그 사이에 있고 grid_quotes 에 그대로 남는다.
  ⚠ 셋 중 일부만 성공하면 **있는 것만으로** 범위를 만든다(지어내지 않는다).
    전부 실패하면 둘 다 NULL.

■ 0110 — 구간이 «입력»이고 견적은 그 안에서 난다
  컬럼 이름이 바뀌었다: `budget_min/budget_max` -> `quote_low/quote_high`.
  뜻이 두 번 바뀌는 동안(입력 -> 관측점 -> 관측범위) 이름이 그대로라 «같은 NB_L2
  의 하한이 33만~171만»처럼 읽혔다. 이제 이름이 «견적 관측값»이라고 말한다.
  **예산 구간의 단일 원천은 `grid_budget_bands` 한 벌뿐**이고, 이 배치는 그 구간을
  «입력»으로 받아(`budget_label` 을 엔진에 실어 보낸다) 그 안에서 견적을 낸다.

■ 0110 — 어느 칸을 도는가: `handling_state = '취급함'` 만
  옛 `intended_empty`(boolean)는 «시장에도 없다»와 «표본이 없어 모른다»를 구분하지
  못했고, 134칸 전부 false 인 채 **쓰는 코드가 없었다**. 이제 4값이다 —
  취급함 / 일부러 비움 / 모름 / 채울 예정. 배치는 **취급함만** 돈다.
  나머지 셋은 견적이 «없는 것이 정상»이고, 화면이 사유를 그대로 말한다.

■ 0110 — 견적이 그 칸 구간 안에 드는지 배치가 스스로 본다
  구간을 먼저 고정한 이상 «가성비·추천이 구간 하한보다 낮다»는 것도 결함이다
  (구간 이름이 거짓이 된다). 옛 판정은 상한만 봤다 — `_band_fit()` 이 아래를 본다.

■ 스펙 하한을 어디서 읽나
  게임 칸: `game_grade_resolution_tiers` 의 (grade, resolution) → gpu_tier_key
    (+cpu_tier_key_override) → `spec_tiers`. 0092 와 같은 원천이다.
    ⚠ 예산대가 `gpu_required=false`(내장그래픽 구간)면 **gpu_watt_min 만 None 으로
      떨어뜨린다** — 그 구간에는 우리 풀의 외장 GPU(최저 297,700원)가 애초에
      들어갈 수 없기 때문이다. 나머지 하한(CPU·RAM·SSD)은 그대로 건다.
      gpu_watt_min 이 None 이고 용도에 GPU 하한이 없으면 엔진이 **이미 갖고 있는
      iGPU 전용 탐색 패스**(api/recommend.py, 사무용에 쓰는 그것)를 탄다 —
      여기서 새로 만들지 않는다.
  비게임 칸: **스펙 하한을 넘기지 않는다**(4개 전부 None). 비게임 용도의 하한은
    `usage_floors` 가 단일 원천으로 이미 갖고 있고, 엔진이 「용도」 라벨만 받으면
    그 하한을 스스로 건다. 0092 가 거기에 spec_tiers T0~T5 를 겹쳐 건 것이
    «사무·인강 × T5 = 1,344만원» 헛칸의 직접 원인이었다 — 축에서 뺐으니 하한도
    겹쳐 걸지 않는다.

■ 용도에 따라 **발행하지 않는 구성**이 있다 (0106)
  `grid_variant_omissions(usage, tier_variant)` 에 행이 있으면 그 용도는 그 구성을
  발행하지 않는다. 사무·주식의 「고성능」이 그것이다 — 200만원 위 실판매가 0벌이라
  사장님이 «그 카드를 만들지 않는다»로 확정했다(2026-09-20).
  · 그 표에 행이 없으면 지금까지처럼 3종 전부를 발행한다(기본값 = 현재 동작).
  · 제외된 구성은 **엔진 실패가 아니다.** 실패로 세지 않고, grid_quotes 에도
    쓰지 않는다. 사유는 그 표의 `reason_public` 이 들고 있고 화면이 그것을 읽는다.
  · 엔진은 여전히 한 번만 호출한다(응답에 3종이 함께 온다) — 제외는 «저장하지
    않는다»이지 «다르게 계산한다»가 아니다. 엔진 상수(HIGHEND_CAP_X)는 건드리지
    않았다.

■ 실패도 원장에 남긴다 · 원장은 UPDATE 가 아니라 INSERT (0072 이후 계승)
■ 콘솔 출력은 ASCII 만 (서버 stdout cp949)
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

STATUS_OK = "정상"
STATUS_OVER = "예산 상한 초과"
# 0110 — 「구간 하한 미달」은 「상한 초과」와 **다른 사실**이다. 한 이름으로 적으면
# 화면이 2,058,500원짜리 칸을 「예산 상한 초과」라고 말한다(거짓). 그래서 가른다.
STATUS_UNDER = "구간 하한 미달"
STATUS_FAIL = "생성 실패"

NOTE_MAX = 200                     # grid_quotes.engine_note String(200)

VARIANT_MAP = {"value": "가성비", "recommend": "추천", "highend": "고성능"}
# quote_low/quote_high 의 원천 variant — 견적 총액의 «관측 범위»다(0105 · 0110 개명).
BUDGET_MIN_VARIANT = "가성비"
BUDGET_MAX_VARIANT = "고성능"

# 0110 — 배치가 도는 칸. grid_cells.handling_state 4값 중 이것 하나뿐이다.
STATE_ACTIVE = "취급함"

GAME_USAGE = "게임"

CHECK_SPECS = (
    ("GPU", "required_power_watt", "gpu_watt_min", "W"),
    ("CPU", "cpu_cores", "cpu_cores_min", "코어"),
    ("RAM", "capacity_gb", "ram_min_gb", "GB"),
    ("SSD", "capacity_gb", "ssd_min_gb", "GB"),
)


def _load_spec_tiers(conn) -> dict:
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT tier_key, gpu_watt_min, cpu_cores_min, ram_min_gb, ssd_min_gb"
        " FROM spec_tiers")).mappings().all()
    return {r["tier_key"]: dict(r) for r in rows}


def _load_game_grade_tiers(conn) -> dict:
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT grade, resolution, gpu_tier_key, cpu_tier_key_override"
        " FROM game_grade_resolution_tiers")).mappings().all()
    return {(r["grade"], r["resolution"]): dict(r) for r in rows}


def _load_bands(conn) -> dict:
    """grid_budget_bands 전행 -> {band_key: row}. 예산 라벨·GPU 성립 여부의 단일 원천."""
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT band_key, axis, label, budget_min_won, budget_max_won, budget_label,"
        " gpu_required, engine_usage_label FROM grid_budget_bands")).mappings().all()
    return {r["band_key"]: dict(r) for r in rows}


# ⚠ 0110 — 격자 용도 라벨을 엔진에 **그대로** 보낸다(override 표를 두지 않았다).
#   usage_floors.match() 가 현행 11개 라벨을 전부 잡는 것을 실측 확인했다:
#   사무용 / 영상편집 / 디자인·조판 / 캐드·설계 / 주식·트레이딩 / 3D 렌더링 /
#   학습용 AI / 음악 작업 / 사무형 AI / 개발 / 게임.
#   용도 라벨을 바꾸면 이 대응이 **조용히** 깨진다 — 엔진이 못 알아들으면 실패가
#   아니라 «하한 없이 만든 견적»이 나온다. tests/regression.py 의
#   「격자 용도가 전부 usage_floors 에 걸린다」가 그 감시다.


def _load_omissions(conn) -> dict:
    """grid_variant_omissions -> {usage: {tier_variant, ...}} (0106).

    그 용도에서 **발행하지 않는** 구성 목록. 행이 없는 용도는 빈 집합이 되고,
    그러면 지금까지처럼 3종 전부를 발행한다 — 기본값이 현재 동작이라, 새 용도를
    추가하면서 이 표를 잊어도 카드가 조용히 사라지지 않는다.
    """
    from sqlalchemy import text
    out: dict = {}
    for r in conn.execute(text(
            "SELECT usage, tier_variant FROM grid_variant_omissions")).mappings().all():
        out.setdefault(r["usage"], set()).add(r["tier_variant"])
    return out


def cell_spec_floor(cell: dict, spec_tiers: dict, game_tiers: dict, bands: dict):
    """격자 칸 하나 -> (엔진에 보낼 것 전부, error|None).

    반환 dict:
      usage_label   「용도」 제약으로 보낼 문자열
      budget_label  「예산」 제약으로 보낼 문자열(grid_budget_bands 원문 — 지어내지 않는다)
      band_key/band_label/band_max  로그·판정용
      gpu_watt_min · cpu_cores_min · ram_min_gb · ssd_min_gb  스펙 하한(엔진 body 최상위)

    ⚠ 옛 판과 달리 **예산대가 반드시 함께 간다.** 이게 «등급이 엔진에 도달하지
      않는다»(결함 A)와 «하한이 가격을 정하지 못한다»(결함 B)를 동시에 푸는 자리다.
    """
    band = bands.get(cell["budget_band_key"])
    if band is None:
        return None, f"budget_band_key={cell['budget_band_key']!r}가 grid_budget_bands에 없습니다"

    common = {
        "budget_label": band["budget_label"],
        "band_key": band["band_key"], "band_label": band["label"],
        "band_min": band["budget_min_won"], "band_max": band["budget_max_won"],
    }

    if cell["usage"] != GAME_USAGE:
        # 비게임 — 스펙 하한은 usage_floors 가 단일 원천이다(위 헤더 참조).
        # 용도 라벨만 보내면 엔진이 그 표를 읽어 스스로 건다.
        common.update({
            "usage_label": band["engine_usage_label"] or cell["usage"],
            "gpu_watt_min": None, "cpu_cores_min": None,
            "ram_min_gb": None, "ssd_min_gb": None,
        })
        return common, None

    key = (cell["game_grade"], cell["game_resolution"])
    gt = game_tiers.get(key)
    if gt is None:
        return None, (f"(grade={cell['game_grade']!r}, resolution={cell['game_resolution']!r})가"
                      " game_grade_resolution_tiers에 없습니다")
    base = spec_tiers.get(gt["gpu_tier_key"])
    if base is None:
        return None, f"gpu_tier_key={gt['gpu_tier_key']!r}가 spec_tiers에 없습니다"
    cpu_tier = base
    if gt["cpu_tier_key_override"]:
        cpu_tier = spec_tiers.get(gt["cpu_tier_key_override"])
        if cpu_tier is None:
            return None, f"cpu_tier_key_override={gt['cpu_tier_key_override']!r}가 spec_tiers에 없습니다"

    # 내장그래픽 구간이면 GPU 하한만 떨군다 — 나머지 하한은 그대로 건다(위 헤더).
    gpu_watt_min = base["gpu_watt_min"] if band["gpu_required"] else None
    common.update({
        "usage_label": band["engine_usage_label"] or GAME_USAGE,
        "gpu_watt_min": gpu_watt_min, "cpu_cores_min": cpu_tier["cpu_cores_min"],
        "ram_min_gb": base["ram_min_gb"], "ssd_min_gb": base["ssd_min_gb"],
    })
    return common, None


def _mark_batch_session(wconn, res: dict) -> None:
    """배치 호출은 고객 상담이 아니다 — 방금 만들어진 consult_sessions 행을 'test' 로 표시."""
    sid = ((res.get("json") or {}).get("session_id")) if res.get("ok") else None
    if sid is None:
        return
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE consult_sessions SET data_origin='test' WHERE session_id=:sid AND data_origin='real'"
    ), {"sid": sid})


def _call_recommend(floor: dict, platform: str) -> dict:
    """엔진 호출 — 「용도」·「예산」·「플랫폼」 + 스펙 하한 4종.

    ⚠ 예산 문자열은 `grid_budget_bands.budget_label` 원문이다. 그 값이
    `api/candidates.py _budget_cap()` 이 읽는 형식이라야 `has_cap=True` 가 되고,
    그래야 `_order_of` 가 median(풀 중앙값)에서 desc(예산을 채우는 방향)로 바뀐다.
    여기서 문자열을 새로 만들지 않는다 — 만들면 형식이 갈라지고, 갈라지면 엔진이
    조용히 무시한다.
    """
    constraints = [
        {"l": "용도", "v": floor["usage_label"]},
        {"l": "예산", "v": floor["budget_label"]},
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            return {"ok": True, "status": resp.status, "json": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": e.code, "detail": detail}
    except urllib.error.URLError as e:
        return {"ok": False, "status": None, "detail": str(e.reason)}


def _spec_violations(build: dict, floor: dict) -> list:
    """엔진이 실제로 스펙 하한을 지켰는지 사후 검증(below_tier_min 패턴, 안전장치)."""
    items_by_slot = {it.get("part_type"): it for it in (build.get("items") or [])}
    out = []
    for slot, field, floor_key, unit in CHECK_SPECS:
        min_v = floor.get(floor_key)
        if min_v is None:
            continue   # 이 슬롯엔 하한이 없다 — 검증할 것이 없다
        item = items_by_slot.get(slot)
        if item is None:
            out.append(f"{slot} 슬롯 없음(하한 {min_v}{unit} 기대)")
            continue
        val = (item.get("spec") or {}).get(field)
        if val is None or val < min_v:
            out.append(f"{slot}.{field}={val} < {min_v}{unit}")
    return out


def _band_fit(total: int, floor: dict, eng_key: str) -> str | None:
    """견적 총액이 이 칸의 «구간 안»에 드는가 — 0110 에서 새로 본다.

    구간을 먼저 고정하고 그 안에서 견적을 내기로 했으므로(사장님 확정 ①),
    구간을 벗어난 총액은 **구간 이름을 거짓으로 만든다**. 옛 판정은 상한만 봤다.

    ⚠ 위아래 둘 다 예외가 있다 — 지어낸 관용이 아니라 엔진 설계에서 오는 것이다.
      · 고성능(highend)은 `api/recommend.py HIGHEND_CAP_X` 가 예산 상한을 1.5배로
        늘려 잡는 «위쪽 선택지»라 상한 초과가 정상 동작이다(0105 가 실측).
      · 가성비(value)는 «그 하한을 만족하는 가장 싼 구성»이라 구간 하한보다 낮을
        수 있다. 그게 이 티어의 존재 이유다.
      그래서 **아래로 새는지는 「추천」에서만** 본다 — 추천이 구간 하한보다 낮으면
      그 칸은 자기 구간 이름을 못 지킨다.
    반환: 위반 사유 문자열 또는 None(문제 없음).
    """
    lo, hi = floor.get("band_min"), floor.get("band_max")
    if hi is not None and total > hi and eng_key != "highend":
        return f"band_over total={total} band_max={hi}"
    if lo is not None and total < lo and eng_key == "recommend":
        return f"band_under total={total} band_min={lo}"
    return None


def judge_variant(eng_key: str, data: dict, floor: dict) -> dict:
    """엔진 응답 하나에서 티어 하나(value/recommend/highend)의 grid_quotes 행 판정.

    ⚠ 예산이 다시 입력이 됐으므로(0105) `verdict == "over"` 가 **실제로 나올 수
    있다** — 옛 판에서는 cap=None 이라 엔진이 항상 "none" 을 줬다.
      · 가성비·추천이 over 면 그 칸은 그 예산대에서 성립하지 않는다는 사실이다
        (STATUS_OVER 로 남긴다 — 지우지 않는다).
      · **고성능(highend)은 예외다**: `api/recommend.py` 의 고성능 티어는 설계상
        예산 상한을 HIGHEND_CAP_X 배로 늘려 잡는 «위쪽 선택지»라, over 가 뜨는 게
        정상 동작이다. 이걸 실패로 세면 모든 칸이 PARTIAL 이 된다.

    0110 — 엔진 verdict 말고 **구간 경계 자체**로도 본다(`_band_fit`). 엔진의
    verdict 는 «예산 라벨»(상한 하나)을 기준으로 나오는데, 격자 구간은 하한도
    갖고 있어서 엔진이 모르는 위반이 있다.
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
        return fail(f"total_missing {eng_key} build has no total")

    violations = _spec_violations(build, floor)
    if violations:
        return fail("below_tier_min " + "; ".join(violations))

    verdict = (build.get("budget") or {}).get("verdict")
    band_miss = _band_fit(total, floor, eng_key)
    over = (verdict == "over" and eng_key != "highend") or band_miss is not None
    status, reason = STATUS_OK, None
    if over:
        reason = band_miss or (f"budget_over total={total} band_max={floor['band_max']}")
        status = STATUS_UNDER if reason.startswith("band_under") else STATUS_OVER
    return {"status": status, "total": total, "verdict": verdict,
            "engine_note": reason[:NOTE_MAX] if reason else None, "payload": build,
            "kind": "ok" if not over else "over", "reason": reason}


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


def retire_omitted_current(wconn, cell_id: int, omit: set) -> None:
    """발행하지 않기로 한 구성의 옛 현재본을 내린다 — 삭제가 아니라 is_current=false.

    `grid_quotes` 는 원장이다(0072 이후). 행은 남기고 «현재본» 표시만 뗀다.
    이 함수가 있어서 `grid_variant_omissions` 에 행을 추가하고 배치만 다시 돌려도
    화면에서 그 카드가 사라진다 — 규칙을 바꿀 때마다 마이그레이션을 쓰지 않는다.
    """
    if not omit:
        return
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE grid_quotes SET is_current=false"
        " WHERE cell_id=:cid AND is_current AND tier_variant = ANY(:vs)"),
        {"cid": cell_id, "vs": sorted(omit)})


def write_budget_observed(wconn, cell_id: int, lo, hi) -> None:
    """quote_low/quote_high — 배치가 실제로 만든 견적 총액의 **관측 범위**(0110 개명).

    low=가성비 총액 · high=고성능 총액. 옛 판(min=max=추천 단일점)은 같은 칸의
    가성비 구성(실측 921,100원)을 발행하지 않고 버렸다 — 그게 롤 하는 고객에게
    219만원만 보여 주던 이유의 절반이다.
    일부만 성공하면 있는 것만으로 범위를 만든다. 둘 다 없으면 NULL — 지어내지 않는다.
    ⚠ 이 값은 **예산 구간이 아니다.** 구간의 단일 원천은 grid_budget_bands 다.
      0110 이 컬럼을 개명한 이유가 그것이다(뜻이 두 번 바뀌는 동안 이름이 그대로였다).
    """
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE grid_cells SET quote_low=:lo, quote_high=:hi WHERE cell_id=:cid"),
        {"lo": lo, "hi": hi, "cid": cell_id})


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
    ap.add_argument("--only", default=None,
                    help="comma-separated cell_id list (debug)")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    only = None
    if args.only:
        only = {int(x) for x in args.only.split(",") if x.strip()}

    with engine.connect() as conn:
        # 0110 — 「취급함」 칸만 돈다. 「일부러 비움 / 모름 / 채울 예정」은 견적이
        # 없는 것이 정상이고, 그 사유를 화면이 handling_note 로 그대로 말한다.
        cells = conn.execute(text(
            "SELECT cell_id, usage, budget_band_key, game_grade, game_resolution, platform"
            " FROM grid_cells WHERE handling_state = :st ORDER BY cell_id"),
            {"st": STATE_ACTIVE}).mappings().all()
        spec_tiers = _load_spec_tiers(conn)
        game_tiers = _load_game_grade_tiers(conn)
        bands = _load_bands(conn)
        omissions = _load_omissions(conn)
        batch_id = _next_batch_id(conn)

    if only is not None:
        cells = [c for c in cells if c["cell_id"] in only]

    omitted_n = sum(len(v) for v in omissions.values())
    print(f"[grid_generate] target_cells={len(cells)} bands={len(bands)}"
          f" omission_rules={omitted_n} batch_id={batch_id} dry={int(args.dry)}", flush=True)
    for u in sorted(omissions):
        print(f"[grid_generate] omit usage={u!r} variants={sorted(omissions[u])}"
              " (grid_variant_omissions -- not published, reason stored in DB)",
              flush=True)

    t0 = time.time()
    ok_n, over_n, fail_cell_n, fail_variant_n = 0, 0, 0, 0
    failures = []
    conn_fail_streak = 0

    for idx, cell in enumerate(cells, 1):
        platform_ascii = PLATFORM_ASCII.get(cell["platform"], "unknown")
        # 이 칸이 발행하는 구성 — 0106. 제외된 구성은 호출도 판정도 저장도 하지 않는다.
        omit = omissions.get(cell["usage"], set())
        pub = {ek: v for ek, v in VARIANT_MAP.items() if v not in omit}
        floor, err = cell_spec_floor(cell, spec_tiers, game_tiers, bands)
        if err:
            fail_cell_n += 1
            failures.append((cell["cell_id"], f"spec_floor_lookup_failed: {err}"))
            print(f"[grid_generate] ({idx}/{len(cells)}) cell_id={cell['cell_id']}"
                  f" platform={platform_ascii} -> FAIL spec_floor_lookup_failed: {err}", flush=True)
            if not args.dry:
                with engine.begin() as wconn:
                    for variant in pub.values():
                        write_quote_row(wconn, cell["cell_id"], variant, batch_id, {
                            "status": STATUS_FAIL, "total": None, "verdict": None,
                            "engine_note": err[:NOTE_MAX], "payload": None})
                    write_budget_observed(wconn, cell["cell_id"], None, None)
            continue

        res = _call_recommend(floor, cell["platform"])

        if not res["ok"]:
            fail_cell_n += 1
            reason = (f"connection_error detail={res.get('detail', '')[:150]}"
                      if res["status"] is None else
                      f"http_error status={res['status']} detail={res.get('detail', '')[:150]}")
            failures.append((cell["cell_id"], reason))
            print(f"[grid_generate] ({idx}/{len(cells)}) cell_id={cell['cell_id']}"
                  f" platform={platform_ascii} -> FAIL {reason}", flush=True)
            if not args.dry:
                with engine.begin() as wconn:
                    for variant in pub.values():
                        write_quote_row(wconn, cell["cell_id"], variant, batch_id, {
                            "status": STATUS_FAIL, "total": None, "verdict": None,
                            "engine_note": reason[:NOTE_MAX], "payload": None})
                    write_budget_observed(wconn, cell["cell_id"], None, None)
            conn_fail_streak = conn_fail_streak + 1 if res["status"] is None else 0
            if conn_fail_streak >= 3:
                print("[grid_generate] FATAL: 3 consecutive connection errors -- "
                      "aborting, is the API server up at 127.0.0.1:8000? "
                      "(remaining cells NOT recorded)", flush=True)
                break
            continue

        conn_fail_streak = 0
        data = res["json"] or {}
        judged_by_variant = {}
        cell_state = "OK"
        for eng_key, variant in pub.items():
            judged = judge_variant(eng_key, data, floor)
            judged_by_variant[variant] = judged
            if judged["kind"] == "ok":
                ok_n += 1
            elif judged["kind"] == "over":
                over_n += 1
                cell_state = "OVER"
                failures.append((cell["cell_id"], f"{variant}: {judged['reason']}"))
            else:
                fail_variant_n += 1
                cell_state = "PARTIAL"
                failures.append((cell["cell_id"], f"{variant}: {judged['reason']}"))

        # 관측 범위 — 0106 이후 «발행한 구성»만 본다. 고성능을 발행하지 않는 용도에서
        # budget_max 는 남은 구성의 최대값(추천)이다. 발행하지 않은 카드의 가격을
        # 범위 상한으로 말하지 않는다.
        lo = (judged_by_variant.get(BUDGET_MIN_VARIANT) or {}).get("total")
        hi = (judged_by_variant.get(BUDGET_MAX_VARIANT) or {}).get("total")
        if lo is None or hi is None:
            # 일부만 성공(또는 일부를 발행하지 않음) — 있는 것만으로 범위를 만든다
            got = sorted(j["total"] for j in judged_by_variant.values() if j["total"] is not None)
            lo = got[0] if got else None
            hi = got[-1] if got else None

        summary = " ".join(
            f"{v}={j['total'] if j['total'] is not None else 'FAIL'}"
            for v, j in judged_by_variant.items())
        if omit:
            summary += " omitted=" + ",".join(sorted(omit))
        print(f"[grid_generate] ({idx}/{len(cells)}) cell_id={cell['cell_id']}"
              f" platform={platform_ascii} usage={floor['usage_label']}"
              f" band={floor['band_key']} -> {cell_state} {summary}", flush=True)

        if not args.dry:
            with engine.begin() as wconn:
                for variant, judged in judged_by_variant.items():
                    write_quote_row(wconn, cell["cell_id"], variant, batch_id, judged)
                # 제외된 구성의 옛 현재본을 내린다(삭제가 아니다 — 원장은 남는다).
                # 이게 있어야 grid_variant_omissions 에 행을 새로 넣고 배치만 돌려도
                # 화면에서 그 카드가 사라진다(마이그레이션을 또 쓰지 않아도 된다).
                retire_omitted_current(wconn, cell["cell_id"], omit)
                write_budget_observed(wconn, cell["cell_id"], lo, hi)
                _mark_batch_session(wconn, res)

    elapsed = time.time() - t0
    print(f"[grid_generate] done in {elapsed:.1f}s ok_variants={ok_n} over_variants={over_n}"
          f" fail_cells={fail_cell_n} fail_variants={fail_variant_n} batch_id={batch_id}",
          flush=True)
    if failures:
        print("[grid_generate] non-ok variants (also recorded in grid_quotes"
              " unless --dry):")
        for cid, reason in failures:
            print(f"  cell_id={cid} {reason}")
    if args.dry:
        print("[grid_generate] --dry mode -- no rows written to grid_quotes/grid_cells")


if __name__ == "__main__":
    main()
