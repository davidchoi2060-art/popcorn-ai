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


def _mark_batch_session(wconn, res: dict) -> int | None:
    """배치 호출은 고객 상담이 아니다 — 방금 만들어진 consult_sessions 행을 'test' 로 표시.

    ■ 왜 `X-Popcorn-Test` 헤더«만»으로는 안 되는가 (2026-09-22 확인)
      헤더는 `_call_recommend()` 가 실제로 보낸다(그 함수 주석 참조). 다만 그것만
      믿을 수 없다 — 이중 게이트 중 하나가 `.env` 의 `POPCORN_TEST_HEADER_ENABLED`
      인데 **서버 env 에는 그 이름이 나타나면 안 된다**(`deploy/README.md` — 확인법이
      `grep -c` -> 0). 서버 안에서 loopback 으로 API 를 두드리는 내부 프로세스가
      실고객 세션을 'test' 로 감추는 경로가 열리기 때문이다. 그래서 **서버에서는
      헤더가 조용히 무시되고**, 실제로 표식을 남기는 것은 이 함수다. 사장님 PC 에서는
      반대로 헤더가 듣는다 — 그때는 행이 처음부터 'test' 로 태어나고 이 UPDATE 가
      아무것도 바꾸지 않는다(`AND data_origin='real'` 조건이 그것을 보장한다).
      그 조건은 남의 행이나 이미 표시된 행을 건드리지 않기 위한 것이기도 하다.
      이 배치는 DATABASE_URL 을 이미 쥐고 있으므로 **자기가 만든 행만** 표시한다.

    ■ 실패 호출에는 세션이 없다
      `res["ok"]` 가 거짓이면 엔진이 행을 만들기 전에 끊긴 것이라 표시할 대상이 없다.

    ■ 표시한 session_id 를 돌려준다
      배치가 끝난 뒤 «정말 다 표시됐는지»를 되물을 수 있어야 한다(main 의 사후 대조).
      UPDATE 가 성공을 반환한다고 해서 원장이 그 상태로 남아 있다는 뜻은 아니다 --
      다른 경로가 같은 행을 되돌릴 수도 있고, 여기서 예외가 나 커밋이 말려도
      루프는 다음 칸으로 간다. 그래서 «했다»가 아니라 «남아 있다»를 확인한다.
    """
    sid = ((res.get("json") or {}).get("session_id")) if res.get("ok") else None
    if sid is None:
        return None
    from sqlalchemy import text
    wconn.execute(text(
        "UPDATE consult_sessions SET data_origin='test' WHERE session_id=:sid AND data_origin='real'"
    ), {"sid": sid})
    return sid


def audit_batch_sessions(conn, sids: list) -> tuple:
    """이 배치가 만든 상담 행이 전부 'test' 로 남아 있는지 되센다.

    ■ 왜 「오늘 real 이 늘었나」로 세지 않는가
      이 DB 는 배포 서버와 공유다(CLAUDE.md). 배치가 도는 22분 사이에 실고객이
      들어오면 오늘의 real 은 «정상적으로» 는다 -- 그걸 오염으로 읽으면 다음부터
      아무도 경고를 안 믿는다. 그래서 **우리가 만든 session_id 만** 되센다.
      거짓 경보가 없으므로 0 이 아니면 그건 진짜 고칠 것이다.

    ■ 못 세는 구멍
      호출이 실패(`res["ok"]` false)하면 session_id 를 못 받는다. 엔진이 행을 만든
      뒤에 끊긴 경우가 있으면 그 행은 이 목록에 없고 여기서도 안 잡힌다.
      지금은 fail_cells=0 이라 해당 없지만, 실패가 생기면 이 한계를 같이 읽어야 한다.
    """
    if not sids:
        return 0, 0
    from sqlalchemy import text
    row = conn.execute(text(
        "SELECT count(*) AS n FROM consult_sessions"
        " WHERE session_id = ANY(:sids) AND data_origin <> 'test'"),
        {"sids": sids}).mappings().one()
    return len(sids), int(row["n"])


PROBE_FILE = os.path.join(ROOT, "tools", "grid_probe.txt")


def _load_probe_list() -> list:
    """`tools/grid_probe.txt` -> [(usage, band_key, platform), ...] (없으면 빈 목록).

    ■ 무엇을 재는 도구인가
      격자 칸은 «용도 x 구간»이고, 구간이 정하는 것은 **예산 상한 하나**다
      (`cell_spec_floor` -- 비게임 칸은 스펙 하한을 보내지 않고 usage_floors 가
      단일 원천이다). 그래서 **구간을 바꾸면 견적 총액도 따라 바뀐다.**
      「이 칸이 188만을 만들었으니 188만이 드는 구간으로 옮기면 되겠다」가
      **틀리는 이유가 이것이다** -- 옮기는 순간 상한이 달라져 총액이 다시 움직인다.

      그래서 옮기기 «전»에, 아직 칸이 없는 (용도, 구간) 조합에서 엔진이 얼마를
      만드는지 재 본다. 이 파일이 그 목록이고, 이 함수가 그것을 읽는다.

    ■ 형식 -- 한 줄에 하나, `용도|구간키|플랫폼` 또는 `용도|구간키|플랫폼|GPU하한W`.
        디자인·조판|W0|인텔
        디자인·조판|W3|인텔|300      <- 그래픽카드 하한 300W 를 «가정»하고 잰다

      4번째 칸은 엔진 body 의 `gpu_watt_min` 으로 그대로 들어간다. 이 값이 있으면
      `api/recommend.py` 의 `allow_igpu_omit` 이 꺼져 **GPU 를 생략하지 못한다**
      (1845-1850). 즉 usage_floors 에 GPU 하한을 «넣었다면 얼마가 되는가»를
      DB 를 고치지 않고 미리 재는 자리다. `-` 또는 비우면 하한 없음.

    ■ 이 목록은 임시다. 다 재고 나면 파일을 지운다 -- 남겨 두면 다음 사람이
      「이게 정본 목록인가」를 묻게 된다.
    """
    if not os.path.exists(PROBE_FILE):
        return []
    out = []
    with open(PROBE_FILE, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) not in (3, 4):
                print(f"[probe] SKIP malformed line: {raw.rstrip()!r}", flush=True)
                continue
            gpu_w = None
            if len(parts) == 4 and parts[3] not in ("", "-"):
                if not parts[3].isdigit():
                    print(f"[probe] SKIP bad gpu_watt_min: {raw.rstrip()!r}", flush=True)
                    continue
                gpu_w = int(parts[3])
            out.append((parts[0], parts[1], parts[2], gpu_w))
    return out


def band_of(total: int, bands: dict, axis: str) -> str | None:
    """이 총액이 «실제로» 드는 구간. 없으면 None(지어내지 않는다)."""
    # `_load_bands` 는 sort_order 를 싣지 않는다 -- 하한으로 정렬하면 같은 순서가 된다
    # (구간은 겹치지 않고 하한이 단조다). 없는 컬럼을 참조하지 않는다.
    for key, b in sorted(bands.items(), key=lambda kv: kv[1]["budget_min_won"]):
        if b["axis"] != axis:
            continue
        lo, hi = b["budget_min_won"], b["budget_max_won"]
        if total >= lo and (hi is None or total <= hi):
            return key
    return None


def run_probe(engine, probes: list, spec_tiers: dict, game_tiers: dict,
              bands: dict, batch_sids: list) -> None:
    """후보 (용도, 구간) 조합에서 «추천» 총액이 어디에 떨어지는지 재서 표로 낸다.

    **아무것도 쓰지 않는다** -- grid_cells 도 grid_quotes 도 건드리지 않는다.
    유일한 쓰기는 자기가 만든 상담 행에 'test' 표식을 남기는 것뿐이다
    (`_mark_batch_session` -- 안 하면 원장에 표식 없는 상담이 쌓인다, A-75).
    """
    print(f"[probe] {len(probes)} combos -- grid_cells/grid_quotes 에 쓰지 않는다",
          flush=True)
    gpu_census(engine)
    for usage, band_key, platform, gpu_w in probes:
        cell = {"usage": usage, "budget_band_key": band_key,
                "game_grade": None, "game_resolution": None, "platform": platform}
        floor, err = cell_spec_floor(cell, spec_tiers, game_tiers, bands)
        if err:
            print(f"[probe] usage={usage} band={band_key} SKIP {err}", flush=True)
            continue
        # 가정한 GPU 하한을 «여기서만» 얹는다 -- usage_floors 는 건드리지 않는다.
        if gpu_w is not None:
            floor = dict(floor)
            floor["gpu_watt_min"] = gpu_w
        gtag = f"gpu>={gpu_w}W" if gpu_w is not None else "gpu-none"
        head = f"[probe] {usage} {band_key} {PLATFORM_ASCII.get(platform, '?')} {gtag}"
        res = _call_recommend(floor, platform)
        with engine.begin() as wconn:
            sid = _mark_batch_session(wconn, res)
        if sid:
            batch_sids.append(sid)
        if not res["ok"]:
            print(f"{head} CALL FAILED status={res['status']}", flush=True)
            continue
        data = res["json"] or {}
        cols = []
        for eng_key in ("value", "recommend", "highend"):
            judged = judge_variant(eng_key, data, floor)
            total = judged.get("total")
            if total is None:
                cols.append(f"{eng_key}=NULL({judged.get('reason')})")
                continue
            extra = ""
            if eng_key == "recommend":
                lands = band_of(total, bands, "nongame") or "-"
                extra = f"(lands={lands} {_band_fit(total, floor, eng_key) or 'in band'})"
            cols.append(f"{eng_key}={total}{extra} {_gpu_of(judged.get('payload'))}")
        print(f"{head} cap={floor['band_min']}~{floor['band_max']} | "
              + " | ".join(cols), flush=True)


def _gpu_of(build) -> str:
    """그 구성이 «실제로» 고른 그래픽카드 -- 없으면 GPU:none(생략됐다는 사실)."""
    if not build:
        return "GPU:?"
    for it in (build.get("items") or []):
        if it.get("part_type") == "GPU":
            spec = it.get("spec") or {}
            return (f"GPU:{it.get('product_name', '')[:28]}"
                    f"/{it.get('sale_price')}원/{spec.get('required_power_watt')}W")
    return "GPU:none"


def gpu_census(engine) -> None:
    """후보 풀의 그래픽카드를 required_power_watt 등급별로 «세어» 둔다.

    기획이 「300W 급이면 얼마」라고 말하려면 그 수가 어디서 왔는지가 있어야 한다.
    CLAUDE.md 에 적힌 등급별 가격대는 슬라이스 58(2026-08) 값이라 지금 값이 아니다.
    읽기 전용 -- 세기만 한다.
    """
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT required_power_watt AS w, count(*) AS n,"
                " min(sale_price) AS lo, max(sale_price) AS hi,"
                " percentile_disc(0.5) WITHIN GROUP (ORDER BY sale_price) AS mid"
                " FROM v_recommendation_candidates"
                " WHERE part_type='GPU' AND stock_qty > 0 AND sale_price IS NOT NULL"
                " GROUP BY 1 ORDER BY 1 NULLS FIRST")).mappings().all()
        print("[probe][gpu] required_power_watt | 건수 | 최저 | 중앙 | 최고", flush=True)
        for r in rows:
            print(f"[probe][gpu] {r['w']} | {r['n']} | {r['lo']} | {r['mid']} | {r['hi']}",
                  flush=True)
    except Exception as e:
        print(f"[probe][gpu] census FAILED: {e}", flush=True)


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
    # 표식을 «두 겹»으로 건다 -- 어느 한쪽만으로는 구멍이 남는다(2026-09-22).
    #   ① 이 헤더: 서버 `.env` 에 POPCORN_TEST_HEADER_ENABLED 가 켜져 있으면 행이
    #      **처음부터** data_origin='test' 로 태어난다. 꺼져 있으면 조용히 무시된다
    #      (자기 신고라 아무나 못 쓰게 이중 게이트 -- api/recommend.py TEST_HEADER 주석).
    #      이름과 값은 tests/regression.py `_headers()` 와 같은 것을 쓴다.
    #   ② `_mark_batch_session()`: 그 스위치가 꺼져 있어도 배치가 자기 행을 직접 표시한다.
    # ①만 믿으면 스위치가 없는 서버에서 표식이 통째로 사라지고, ②만 믿으면 INSERT 와
    # UPDATE 사이에 'real' 인 찰나가 남는다. 둘 다 건다.
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Popcorn-Test": "1"}, method="POST")
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

    batch_sids: list = []   # consult_sessions.session_id 는 BIGSERIAL 이라 정수다
    t0 = time.time()

    # ── 후보 구간 재기 (tools/grid_probe.txt 가 있을 때만) ──────────────────
    # **`--dry` 에서만 돈다.** 실배치에서 같이 돌리면 22분짜리 작업 앞에 재기가
    # 붙어 배포가 늦어지고, 무엇보다 «재기 목록이 배치를 대신했나»를 로그에서
    # 구분하기 어려워진다. 실배치에서 파일을 발견하면 무시했다고 **말한다** --
    # 조용히 건너뛰면 다음 사람이 재기 결과를 기다리다 만다.
    probes = _load_probe_list()
    if probes and not args.dry:
        print(f"[grid_generate] NOTE: tools/grid_probe.txt ({len(probes)} combos)"
              " ignored -- 재기는 --dry 에서만 돈다", flush=True)
    elif probes:
        run_probe(engine, probes, spec_tiers, game_tiers, bands, batch_sids)
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
                sid = _mark_batch_session(wconn, res)
            if sid:
                batch_sids.append(sid)
        else:
            # ⚠ --dry 는 «격자 표에 쓰지 않는다»는 뜻이지 «아무것도 안 만든다»가 아니다.
            #   엔진 호출은 그대로 하므로 consult_sessions 행은 실제로 생긴다(2026-09-22
            #   지적받아 확인). 표시를 여기서 빼면 드라이런이 돌 때마다 표식 없는 상담이
            #   원장에 쌓인다 — 「검증이 흔적을 남긴다」(슬라이스 78)가 정확히 이 모양이었다.
            #   그래서 드라이런에서도 «자기가 만든 행»만 표시한다. 이건 격자를 바꾸는
            #   쓰기가 아니라 자기 흔적을 치우는 쓰기다.
            with engine.begin() as wconn:
                sid = _mark_batch_session(wconn, res)
            if sid:
                batch_sids.append(sid)

    elapsed = time.time() - t0
    print(f"[grid_generate] done in {elapsed:.1f}s ok_variants={ok_n} over_variants={over_n}"
          f" fail_cells={fail_cell_n} fail_variants={fail_variant_n} batch_id={batch_id}",
          flush=True)
    if failures:
        print("[grid_generate] non-ok variants (also recorded in grid_quotes"
              " unless --dry):")
        for cid, reason in failures:
            print(f"  cell_id={cid} {reason}")

    # 사후 대조 -- 「표시했다」가 아니라 「표시된 채 남아 있다」를 확인한다.
    # 감시 장치가 감시 대상을 깨뜨리면 안 된다: 22분치 결과를 다 쓴 뒤에 도는
    # 검사라, 여기서 예외가 나도 배치 보고를 트레이스백으로 덮지 않는다.
    try:
        with engine.connect() as conn:
            made_n, unmarked_n = audit_batch_sessions(conn, batch_sids)
    except Exception as exc:                      # noqa: BLE001 -- 안전망이 본류를 막지 않는다
        print(f"[grid_generate] ledger audit FAILED to run: {exc!r}"
              f" (sessions={len(batch_sids)} -- 표시 여부를 확인하지 못했다)", flush=True)
        made_n = unmarked_n = None
    if unmarked_n:
        print(f"[grid_generate] LEDGER WARN: sessions={made_n} unmarked={unmarked_n}"
              " -- 이 배치가 만든 상담 행이 원장에 'real' 로 남아 있다."
              " tools/grid_generate.py _mark_batch_session 을 확인한다.", flush=True)
    elif unmarked_n == 0:
        print(f"[grid_generate] ledger ok: sessions={made_n} all marked data_origin='test'"
              " (실고객 행은 세지 않는다 -- 이 배치가 만든 session_id 만 대조)", flush=True)

    if args.dry:
        print("[grid_generate] --dry mode -- no rows written to grid_quotes/grid_cells")


if __name__ == "__main__":
    main()
