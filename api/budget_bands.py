# -*- coding: utf-8 -*-
"""GET /api/budget-bands — 예산 구간·고객 예산 칩의 단일 원천 (0110, 2026-09-21).

■ 왜 있는가
  `mockups/mvp1/s1-session.html` 의 `Q_BUDGET` 이 칩 다섯 개(70/100/150/200만+)를
  **화면 안에 하드코딩**하고 있었다. 「200만원 이상」 하나에 시장 정화 표본 782벌의
  **62.5%(489벌)**가 뭉친다 — 사실상 «그 이상은 안 묻는다»와 같다.
  `api/usage_floors.py:135` 의 `GET /api/usages` 주석이 이미 같은 원칙을 적어 뒀다:
  «화면이 목록을 갖는 한 표가 바뀌는 날 반드시 갈라진다. 그래서 받아 쓰게 한다.»
  **용도는 그렇게 고쳤고 예산은 안 고쳤다.** 이 파일이 그것을 고친다.

■ ⚠ 고객 칩과 격자 구간은 **같지 않다** — 같아야 할 이유가 없다
  둘은 서로 다른 것을 잰다:

      | 무엇인가      | 고객 칩            | 격자 구간              |
      | 값의 성격     | 「150만원 이하」= **상한 하나** | 「110~150만」= **하한+상한** |
      | 누가 정하나   | 고객이 고른다       | 우리가 배치로 만든다     |
      | 적정 개수     | 4~7개(한눈에 읽힌다) | 필요한 만큼(15개여도 된다) |

  결정적 차이: 칩 값은 `api/candidates.py _budget_cap()` 이 **상한 하나**로 쓴다
  (`parts <= cap x pct`). 고객이 「150만원 이하」라고 말한 것은 «90만짜리도 본다»는
  뜻이지 «150만 구간의 상품만 본다»가 아니다. 칩을 격자 구간과 1:1 로 만들면
  (게임 7 + 비게임 8 = 15개) 그 차이가 지워지고, 모바일에서 3~4줄이 되어
  «고른다»가 아니라 «읽는다»가 된다.

  그래서 이 API 는 **둘 다** 준다:
    `bands`  격자 구간 전수(15개) — 관리자 화면·검증·설명용
    `chips`  고객이 고르는 칩(6개) — S1 화면이 그리는 것
  화면은 `chips` 만 그린다. 둘의 단일 원천이 서버라는 것이 요점이지,
  둘이 같은 값이라는 뜻이 아니다.

■ 칩 6개를 어떻게 골랐나 — 지어낸 경계가 하나도 없다
  전부 `grid_budget_bands` 의 **실제 구간 경계**에서 가져왔다(아래 CHIP_EDGES).
  고른 규칙: 비게임 축의 경계(W0~W7)를 «상한»으로 읽되, 시장 표본이 한 칩에
  과반으로 뭉치지 않도록 782벌 분포에서 고른다. 결과 분포(비게임 361벌 기준):

      ~90만    74벌(20.5%)      ~150만  81벌(22.4%)
      ~220만   54벌(15.0%)      ~280만  28벌( 7.8%)
      ~460만   45벌(12.5%)      460만+  79벌(21.9%)

  최대 칩이 22.4% 다 — 옛 「200만+」 한 칩의 **62.5%** 에서 내려왔다. 그게 이
  설계의 전부다. 칩을 13~15개로 늘리지 않았고, 대신 **뭉침을 깼다.**
  ⚠ 최상위를 「460만원 이상」 하나로 둔 것은 판단이다: W6(460~780만) 44벌과
    W7(780만~) 35벌은 워크스테이션·AI 학습기·서버라, 이런 고객이 칩을 눌러
    들어오지 않는다(상담에서 갈린다). 근거는 표본 성격이지 측정이 아니다 —
    그 사실을 감추지 않는다.

■ ⚠ `constraint_value` 형식 제약 — 벗어나면 엔진이 **조용히 무시**한다
  `api/candidates.py _budget_cap()` 의 정규식은
    `(-)?\\s*(\\d{1,3}(?:,\\d{3})+|\\d+)\\s*만`
  이고 「이상」이 들어 있으면 None(상한 없음)을 준다. 형식을 벗어나면 엔진이
  median(후보 풀 중앙값) 동작으로 되돌아가 **실패 없이 틀린 값**을 준다.
  그래서 이 모듈은 응답을 만들 때 **자기 값을 스스로 검사한다**(`_check_cap`) —
  형식이 깨지면 500 을 내고 조용히 틀리지 않는다. 같은 검사가
  `tests/regression.py` 에도 있다.

■ 인증 없음 · 읽기 전용. `GET /api/usages` 와 같은 자리다.
"""
import re

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api", tags=["budget"])

# api/candidates.py _budget_cap() 의 정규식 원문. **베껴 온 것이므로 갈라질 수
# 있다** — 그래서 아래 _check_cap 이 «이 정규식이 통과하는가»가 아니라 «실제
# _budget_cap 이 숫자를 주는가»를 본다(가져다 쓴다, 다시 짜지 않는다).
_MAN = re.compile(r"(-)?\s*(\d{1,3}(?:,\d{3})+|\d+)\s*만")

# ── 고객 칩 — 값은 전부 grid_budget_bands 의 실제 경계다 ────────────────
# (band_key 가 그 경계를 들고 있는 구간, chip_text, 상한 표현)
# ⚠ band_key 를 함께 두는 것이 중요하다 — 경계를 여기 숫자로 적으면 구간이
#   바뀌는 날 또 갈라진다. 숫자는 **DB 에서 읽는다**(아래 list_budget_bands).
CHIP_EDGES = [
    ("W0", "~90만", "이하"),      # W0 상한 = 900,000
    ("W2", "~150만", "이하"),     # W2 상한 = 1,500,000
    ("W3", "~220만", "이하"),     # W3 상한 = 2,200,000
    ("W4", "~280만", "이하"),     # W4 상한 = 2,800,000
    ("W5", "~460만", "이하"),     # W5 상한 = 4,600,000
    ("W6", "460만+", "이상"),     # W6 하한 = 4,600,000 — 열린 칩
]
# 칩마다 «왜 이 칩인가»(시장 표본). 화면 why 자리에 그대로 나간다 —
# 화면이 이유를 지어내지 않는다.
CHIP_SAMPLE = {
    "W0": "시장 표본 74벌", "W2": "시장 표본 81벌", "W3": "시장 표본 54벌",
    "W4": "시장 표본 28벌", "W5": "시장 표본 45벌", "W6": "시장 표본 79벌",
}
# 「잘 모르겠어요」 — 숫자가 없는 선택지. 엔진은 상한 없이 median 으로 간다.
# 이 값은 화면이 예전부터 쓰던 리터럴 그대로다(원장 호환 — 바꾸면 옛 세션과 갈린다).
CHIP_UNSURE = {"key": "unsure", "chip_text": "잘 모르겠어요(추천 받을래요)",
               "constraint_value": "AI 추천 예산", "max_won": None,
               "why": "가성비 최적 구간으로 압축"}


def _check_cap(value: str, expect_capped: bool) -> None:
    """이 문자열을 엔진이 실제로 읽는지 **서버가 스스로 확인한다**.

    형식이 어긋나면 엔진은 예외를 내지 않고 조용히 median 으로 되돌아간다 —
    화면은 멀쩡하고 값만 틀린다. 오늘 고친 결함 다섯이 전부 그 모양이었다.
    그래서 여기서 터뜨린다.
    """
    from .candidates import _budget_cap
    cap = _budget_cap(value)
    if expect_capped and cap is None:
        raise HTTPException(500, f"예산 칩 값 '{value}'을 견적 엔진이 상한으로 읽지"
                                 " 못합니다(형식 불일치)")
    if not expect_capped and cap is not None:
        raise HTTPException(500, f"예산 칩 값 '{value}'은 상한 없는 칩인데 엔진이"
                                 f" 상한 {cap}으로 읽습니다")


@router.get("/budget-bands")
def list_budget_bands():
    """예산 구간 전수 + 고객 예산 칩. 읽기 전용·인증 없음.

    응답
      {ok, axes:[{axis, label, bands:[{key,label,min_won,max_won,budget_label,
                                       sample_n,source}]}],
       chips:[{key, chip_text, constraint_value, max_won, why}]}

      bands[].budget_label  **배치가 엔진에 보내는** 예산 라벨(격자 생성용).
                            고객 칩 값이 아니다 — 둘을 섞지 않는다.
      chips[].constraint_value  **고객이 고르면 서버로 되돌아오는** 값.
                            `_budget_cap` 이 반드시 파싱할 수 있는 형식이고,
                            그것을 이 함수가 매 응답마다 검사한다.
      chips[].max_won       그 칩의 상한(원). 열린 칩은 null — 화면이 예산 막대
                            위치를 스스로 계산하지 않고 이 값을 쓴다.
    """
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT band_key, axis, label, budget_min_won, budget_max_won,"
            " budget_label, sample_n, source, sort_order"
            " FROM grid_budget_bands ORDER BY sort_order")).mappings().all()

    by_key = {r["band_key"]: r for r in rows}
    axes: list = []
    for axis, label in (("game", "게임"), ("nongame", "비게임")):
        bands = [{
            "key": r["band_key"], "label": r["label"],
            "min_won": r["budget_min_won"], "max_won": r["budget_max_won"],
            "budget_label": r["budget_label"], "sample_n": r["sample_n"],
            "source": r["source"],
        } for r in rows if r["axis"] == axis]
        if bands:
            axes.append({"axis": axis, "label": label, "bands": bands})

    chips: list = []
    for band_key, chip_text, bound in CHIP_EDGES:
        b = by_key.get(band_key)
        if b is None:                 # 구간이 사라졌다 — 칩을 지어내지 않는다
            continue
        if bound == "이하":
            won = b["budget_max_won"]
            if won is None:
                continue              # 열린 구간을 「이하」 칩으로 쓸 수 없다
            value = f"{won // 10000:,}만원 이하"
        else:
            won = b["budget_min_won"]
            value = f"{won // 10000:,}만원 이상"
        _check_cap(value, expect_capped=(bound == "이하"))
        chips.append({"key": band_key, "chip_text": chip_text,
                      "constraint_value": value,
                      "max_won": won if bound == "이하" else None,
                      "why": CHIP_SAMPLE.get(band_key, "")})
    chips.append(CHIP_UNSURE)

    return {"ok": True, "axes": axes, "chips": chips}
