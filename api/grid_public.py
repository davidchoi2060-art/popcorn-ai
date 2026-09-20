# -*- coding: utf-8 -*-
"""고객용 격자 추천 API — `POST /api/grid/recommend` (A-135 스펙축 재설계, 2026-09-16).

■ 무엇을 하나
  talk.py 가 낸 **격자 좌표 state**(api/talk_schema.TalkState — 용도·예산·플랫폼·
  게임 등급/해상도 …)를 받아 사전 생성 견적 격자(grid_cells × grid_quotes.is_current,
  0092)에서 칸을 찾아 **용도별 카드 묶음(card_sets)** 으로 돌려준다.
  실시간 recommend 엔진을 돌리지 않는다 — 격자가 추천 원천이다(A-126·A-128).

■ 입력 계약 전환(2026-09-16 오후, docs/design/talk-grid-guide-redesign-2026-09-16.md §7·§8)
  · 정본 입력은 `state`(TalkState dict). 검증은 talk_schema.validate_state 로 매 요청
    DB 어휘와 대조한다 — AI/화면이 낸 값을 그대로 믿지 않는다(어휘 밖은 null 로 접고
    notes 에 남기며, 같은 dropped[] 를 응답에도 실어 화면이 '반영 못 한 조건'을 말할 수
    있게 한다). 400/422 를 내지 않는 방침은 그대로다.
  · 하위호환으로 옛 `constraints[{l,v}]` 도 받는다(mvp1 이 아직 옛 모양을 쓸 수 있다).
    둘 다 오면 state 우선. constraints 만 오면 _pick/_usage_grid_of/_platform_of/
    parse_budget 로 state 를 만든 뒤 같은 길을 탄다 — 단, 게임명 탐색은 더 이상 하지
    않으므로(아래) 옛 모양의 게임 용도는 needs=["game.grade"] 로 끝난다.
  · 게임명·등급은 AI 가 좌표(state.game.grade)로 준다 — 이 파일이 '요청'·'선호' 값에서
    games.name 을 뒤지던 _find_game_name/GAME_NAME_LABEL_PRIORITY 는 삭제했다.
  · 사장님 확정 정책 3항목(설계서 §6)을 이 파일이 구현한다:
      ① 용도가 둘 이상 → usages[] 마다 격자 조회, card_sets[] 로 전부 돌려준다.
        게임 계열 용도가 여럿(게임+고사양 게임)이면 게임 카드는 한 벌만.
      ② 목록 밖 게임(grade_src="ai_estimate") → 추정 등급으로 바로 카드 + 응답
        ai_estimated[] 로 화면 배지. 그 시점에 talk_game_estimates(0093) 에 한 행.
      ③ 해상도 null → 1080p 로 카드를 내고 assumed:["game.resolution=1080p"].
  · `notes[]` 는 서버 내부 사유(로그·디버그용)다. 화면은 이것을 고객 말풍선에 싣지
    않는다(되묻기는 AI 의 reply 만) — 옛 화면이 실수로 못 쓰게 필드명을 `note`(문자열)
    에서 `notes`(배열)로 바꿨다.

■ 스키마 대전환(0091·0092, 이 재작성의 배경 — A-135)
  옛 판(0072~0082): grid_cells.tier 는 브랜드명 문자열이고 budget_min/max 가
  칸을 정의하는 **입력**(가격 구간을 먼저 정함)이었다. 이 파일은 그 판을 SELECT
  했고(`tier AS name`), 0092 마이그레이션이 grid_cells 를 스펙 축으로 갈아엎으며
  `tier` 컬럼 자체가 없어져 500 이 났다(실측: `column "tier" does not exist`).

  새 판(0091·0092):
    · 비게임 칸 = tier_key(FK→spec_tiers T0~T5, 팝콘1~5·X) + usage(6종 문자열:
      AI 작업/영상편집/디자인/사무·인강/주식·트레이딩/3D 그래픽 — 아래 USAGE_TO_GRID
      주석의 실측 SQL 참고).
    · 게임 칸 = usage='게임' 고정 + game_grade(FK→game_load_grades E/A/B/C/S/L)
      + game_resolution(1080p/1440p/4K). tier_key 는 게임 칸에서 항상 NULL —
      스펙은 game_grade_resolution_tiers 조인으로 구한다(admin_grid.py 와 같은 원천).
    · budget_min/budget_max 는 이제 **입력이 아니라 배치가 실제로 만든 추천
      (recommend) variant 총액의 관측값**이다(nullable — 배치 미실행 시 NULL,
      tools/grid_generate.py write_budget_observed 참고). min==max 로 저장된다
      (셋을 다르게 만들 근거가 없어 지어내지 않는다는 게 그 배치의 판단).
    · grid_quotes 가 칸 하나당 최대 3개 현재본을 가진다(tier_variant =
      가성비/추천/고성능, 부분 유니크 uq_grid_quotes_current_per_cell_variant).

■ 인증 게이트 밖이다 (실측 그대로 유지, 스키마와 무관)
  `api/auth.py` `_is_gated()` 는 `/api/admin/` 만 본다 → `/api/grid/` 는 대상이
  아니다. `api/customer_auth.py` 는 `/api/my/` 만 401 을 낸다 → 게스트도 통과.

■ 읽기 전용에 예외 하나 — talk_game_estimates(0093) INSERT
  SELECT 만 하던 파일이다. 예외는 §6 ② 의 추정 기록 한 행뿐이며 별도 트랜잭션으로
  쓰고, 실패해도 카드 응답은 버리지 않고 로그(log.exception)+notes 로만 남긴다
  (api/llm.py 의 cost_logged 판단과 같은 결). 세션·다른 원장은 쓰지 않는다.

■ 지어내지 않는 것
  · `reasons`·`omitted` 는 payload 그대로(재작성 금지).
  · 카드 이름은 payload.label 을 쓰지 않는다 — 조사자 실측(2026-09-11)으로 70건
    전부 '추천형 견적' 동일이라 정보가 없다. 티어/등급 + 용도로 합성한다.
  · `in_stock` 은 `products.stock_qty` 를 그 자리에서 다시 읽은 값이다.
  · budget_min/max 가 NULL(배치 미실행)이면 그대로 null 을 내보낸다 — 만든 숫자를
    채우지 않는다.

■ 사장님 확정 없이 이 파일이 직접 판단한 것(보고서에 명시)
  ① DEFAULT_TIER_KEY = "T1"(팝콘2, 입문급) — 예산도 tier_key 힌트도 없을 때 중심
     티어. 지시서 원문이 "미정이면 T1로 가정"이라 명시해 그대로 따른다.
  ② `tier_index_for` 의 예산 매칭 규칙을 반열림 구간 비교에서 "관측 가격점 중
     가장 가까운 티어" 규칙으로 바꿨다 — budget_min==budget_max(단일 관측점)라
     옛 [min,max) 구간 비교가 사실상 항상 실패하기 때문이다(아래 함수 docstring
     참고). 새 가격을 지어내지 않고 실측 점들만 재료로 쓰지만, 이 대체 규칙
     자체는 사장님 확정 사항이 아니다.
  ③ (해소, 2026-09-16 오후) 게임명 탐색·해상도 고정은 사라졌다 — 둘 다 AI 가
     state.game 좌표로 준다. 해상도 null 은 설계서 §6 ③ 대로 1080p 가정.
  ④ 비게임 tier_key 힌트와 예산이 **둘 다** 있으면 예산을 중심으로 쓴다(설계서
     §11 "이번엔 예산 우선 유지"). 힌트와 예산이 고른 칸이 다르면 notes 에 남긴다.
     힌트만 있으면 그 칸을 중심으로 한다.
"""
import json
import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine
from .talk_schema import (DEFAULT_RESOLUTION, TalkState, is_game_usage, load_vocab,
                          missing_for, validate_state)
from .taxonomy import SLOT_LABELS
from .timeutil import iso as _iso

log = logging.getLogger("grid_public")

router = APIRouter(prefix="/api/grid", tags=["grid-public"])

# ── 상수 ────────────────────────────────────────────────────────────────
DEFAULT_TIER_KEY = "T1"          # 예산 없을 때 중심 tier_key — 위 ① 참고(가정값)
TIERS_UP = 2                     # 중심 + 위 2개(0072 이래 정책 유지, 이번 변경 범위 밖)
DEFAULT_PLATFORM = "인텔"        # 사장님 확정(2026-09-11), 스키마와 무관
# 플랫폼 어휘는 talk_schema.PLATFORM_VALUES 하나만 쓴다(validate_state 가 거른다) — 여기
# 따로 두지 않는다(단일 원천). 옛 PLATFORMS 상수는 미참조라 지웠다(2026-09-16 확인자 G-2).
GAME_USAGE = "게임"              # grid_cells.usage 의 게임 축 리터럴(0092)
# 해상도 기본값은 talk_schema.DEFAULT_RESOLUTION(1080p) 하나만 쓴다 — 여기 따로 두지
# 않는다(단일 원천). null 이면 그 값으로 카드를 내고 assumed 에 표시한다(§6 ③).
ASSUMED_RESOLUTION = f"game.resolution={DEFAULT_RESOLUTION}"

# ── 용도 매핑 — 파서 9종 → grid_cells.usage 6종(비게임) + '게임'(게임 3종 합류) ──
# 비게임 6종은 2026-09-16 실측 SQL 로 확인한 값 그대로다:
#   SELECT DISTINCT usage FROM grid_cells WHERE usage <> '게임'
#   → {'AI 작업','디자인','영상편집','사무·인강','주식·트레이딩','3D 그래픽'}
# 이 6종은 `usage_floors.usage_label`(ai/design/video/office/trading/video_3d)과
# **1:1로 이미 같은 문자열**이다(0090·0092 가 같은 어휘를 썼다) — 그래서 옛 판처럼
# 여러 파서 용도를 하나로 접는 매핑표가 필요 없다. 게임 계열 3종(게임·캐주얼 게임·
# 고사양 게임)만 GAME_USAGE 로 합류시킨다 — 세부(등급·해상도)는 tier_key 가 아니라
# game_grade+game_resolution 이 결정한다(아래 _game_card_set).
# 이 매핑의 키는 usage_floors.usage_label 9종과 같다 — talk_schema.load_vocab 이 매
# 요청 DB 에서 읽는 그 어휘다. state.usages 는 validate_state 가 이미 그 어휘로
# 걸러 주므로 여기서는 값→격자 용도 변환만 한다.
USAGE_TO_GRID = {
    "AI 작업": "AI 작업",
    "디자인": "디자인",
    "영상편집": "영상편집",
    # 2026-09-18 (0102) — `office` 가 «단순 사무용»·«복합 사무용» 둘로 갈렸다.
    #   `usage_floors.usage_label` 이 두 값으로 바뀌었으므로 여기 키도 둘이 된다.
    #   ⚠ 값(격자 용도)은 **둘 다 '사무·인강'** 이다 — `grid_cells.usage` 축은
    #     0092 가 만든 «가격 격자»의 축이고 12행 실측이 그 문자열 하나다. 격자를
    #     쪼개려면 카드를 다시 생성해야 하는데(tools/grid_generate.py) 그건 이
    #     작업 범위 밖이다. 하한(usage_floors)은 갈렸고 격자는 아직 안 갈렸다 —
    #     즉 두 용도가 «같은 가격대 카드»를 보되 견적 엔진의 하한은 서로 다르다.
    #     격자까지 가르는 것은 후속 작업이다(설계 문서 §미해결).
    #   ⚠ '사무·인강' 키도 남긴다 — grid_cells.usage 리터럴이자 옛 세션·문서가
    #     쓰던 값이라 지우면 그 입력이 통째로 needs=['usages'] 로 떨어진다.
    "단순 사무용": "사무·인강",
    "복합 사무용": "사무·인강",
    "사무·인강": "사무·인강",
    "주식·트레이딩": "주식·트레이딩",
    # 2026-09-19 (0104) — `video_3d`(3D 그래픽) 가 «캐드·설계»·«3D 렌더링» 둘로 갈렸다.
    #   `usage_floors.usage_label` 이 두 값으로 바뀌었으므로 여기 키도 둘이 된다.
    #   ⚠ 값(격자 용도)은 **둘 다 '3D 그래픽'** 이다 — 0102 의 사무 분할과 같은 상황이다.
    #     `grid_cells.usage` 축은 0092 가 만든 «가격 격자»의 축이고 12행 실측이 그
    #     문자열 하나다. 격자를 쪼개려면 카드를 다시 생성해야 하는데
    #     (tools/grid_generate.py) 그건 이 작업 범위 밖이다. 하한(usage_floors)과
    #     겨냥(usage_tier_rules)은 갈렸고 격자는 아직 안 갈렸다 — 즉 두 용도가
    #     «같은 가격대 카드»를 보되 견적 엔진의 하한·상한은 서로 다르다.
    #   ⚠ '3D 그래픽' 키도 남긴다 — grid_cells.usage 리터럴(12행)이자
    #     consult_sessions 60건·grid_quotes.payload 72건이 들고 있는 값이라
    #     지우면 그 입력이 통째로 needs=['usages'] 로 떨어진다.
    "캐드·설계": "3D 그래픽",
    "3D 렌더링": "3D 그래픽",
    "3D 그래픽": "3D 그래픽",
    "게임": GAME_USAGE,
    "캐주얼 게임": GAME_USAGE,
    "고사양 게임": GAME_USAGE,
}

# grid_quotes.tier_variant(한글) → 응답 키(카드 3종 구조, 지시 6번 예시 그대로)
VARIANT_KEY_MAP = {"가성비": "value", "추천": "reco", "고성능": "perf"}
REPRESENTATIVE_VARIANT = "추천"   # 하위호환 최상위 필드가 참조하는 대표 variant


# ── 부품 순서·라벨 — 화면(mockups/mvp2/app.js makeQuotes) 순서, 스키마와 무관 ──
PART_ORDER = ("CPU", "MB", "RAM", "GPU", "SSD", "CASE", "COOLER", "POWER")
DISPLAY_OVERRIDE = {"SSD": "저장장치", "COOLER": "쿨러"}


def _cat_label(slot: str) -> str:
    return DISPLAY_OVERRIDE.get(slot) or SLOT_LABELS.get(slot, slot)


# ── 입력 ────────────────────────────────────────────────────────────────
class Constraint(BaseModel):
    """옛 모양(mvp1) — 하위호환으로만 받는다."""
    l: str | None = None
    v: str | None = None


class RecommendBody(BaseModel):
    state: dict | None = None            # 정본 — talk_schema.TalkState 모양의 dict
    constraints: list[Constraint] = []   # 하위호환(옛 모양). state 가 있으면 무시
    history_note: str | None = None     # 받기만 한다 — 이 단계에선 판정에 쓰지 않는다


# ── 예산 문자열 → 원 ───────────────────────────────────────────────────────
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_budget(s: str | None) -> tuple[int | None, str | None]:
    """'1,500만원' · '150만원 이하' · '130만' · '1300000원' → (원, bound).

    bound ∈ {'이상','이하',None}. 콤마를 떼고 첫 숫자를 읽는다. '만' 이 있으면 ×10000,
    없고 값이 10000 미만이면 만원 단위로 간주해 ×10000, 그 밖은 원 그대로.
    못 읽으면 (None, None) — 지어내지 않는다.

    (스키마 변경과 무관한 순수 문자열 파서 — 0092 재작성에서 손대지 않았다.)
    """
    if not s:
        return None, None
    raw = s.replace(",", "").strip()
    m = _NUM.search(raw)
    if not m:
        return None, None
    n = float(m.group(1))
    tail = raw[m.end():]
    if "만" in tail or ("만" not in raw and n < 10000):
        won = int(round(n * 10000))
    else:
        won = int(round(n))
    bound = "이상" if "이상" in raw else ("이하" if "이하" in raw else None)
    return won, bound


def _load_tiers(conn, usage_grid: str | None, platform: str) -> list[dict]:
    """spec_tiers(T0~T5)를 정본 순서로 싣고, 있으면 그 usage×platform 의 관측
    가격(grid_cells.budget_min/max)을 붙인다.

    ⚠ 관측 가격은 usage 마다 다르다(같은 T2 라도 '사무·인강'은 310만원대,
    'AI 작업'은 346만원대 — 2026-09-16 실측). 그래서 옛 판처럼 usage 를 무시하고
    "티어 하나의 가격"을 구할 수 없다 — 반드시 usage_grid+platform 을 함께
    받는다. usage_grid 가 없거나(용도 미정) 게임(GAME_USAGE, tier_key 축이 아님)
    이면 관측 가격을 조회하지 않고 전부 None 으로 둔다(지어내지 않는다) —
    이 경우 `tier_index_for`는 비교 재료가 없어 DEFAULT_TIER_KEY 로 떨어진다.
    """
    tier_rows = conn.execute(text(
        "SELECT tier_key, popcorn_name FROM spec_tiers ORDER BY sort_order"
    )).mappings().all()
    tiers = [{"tier_key": r["tier_key"], "name": r["popcorn_name"],
              "budget_min": None, "budget_max": None} for r in tier_rows]

    if usage_grid and usage_grid != GAME_USAGE:
        obs = conn.execute(text(
            "SELECT tier_key, budget_min, budget_max FROM grid_cells"
            " WHERE usage = :u AND platform = :p"),
            {"u": usage_grid, "p": platform}).mappings().all()
        obs_by_tier = {o["tier_key"]: o for o in obs}
        for t in tiers:
            o = obs_by_tier.get(t["tier_key"])
            if o is not None:
                t["budget_min"] = o["budget_min"]
                t["budget_max"] = o["budget_max"]
    return tiers


def tier_index_for(tiers: list[dict], won: int | None, bound: str | None) -> int:
    """예산 값으로 중심 티어 인덱스를 고른다.

    ⚠ 스키마 대전제가 바뀌었다(0092) — budget_min/budget_max 는 더 이상 "이
    티어가 커버하는 가격 구간"이 아니라 "배치가 실제로 만든 추천(recommend)
    견적 총액" **단일 관측점**이다(min==max로 저장됨, tools/grid_generate.py
    write_budget_observed — "셋을 각각 다른 값으로 만들 근거가 없어 지어내지
    않는다"). 옛 알고리즘의 반열림 구간 [budget_min, budget_max) 비교는 폭이
    0인 구간을 비교하는 것과 같아 예산이 그 값과 정확히 일치할 때만 맞는다 —
    실사용에서는 사실상 항상 실패한다.

    그래서 이 함수는 "관측된 가격 점들 중 예산 조건에 맞는 가장 가까운 티어"를
    고르는 규칙으로 대체한다(새 가격을 지어내지 않고, 실측된 점만 비교 재료로
    쓴다 — 위 헤더 ② 항목, 사장님 확정 아님·이번 작업 판단):
      · bound 없음 또는 '이하'(둘 다 상한 취급, 옛 로직과 같은 전제) — 예산
        이하인 관측 가격 중 **가장 비싼** 티어(예산을 최대한 채운다).
        전부 예산을 넘으면 그나마 **가장 싼** 티어(가장 가까운 선택지).
      · '이상'(하한) — 예산 이상인 관측 가격 중 **가장 싼** 티어.
        전부 예산에 못 미치면 **가장 비싼** 티어.

    관측값이 없는 티어(budget_min이 NULL — 배치 미실행이거나 이 usage×platform
    조합이 아직 없음)는 비교에서 제외한다(지어내지 않는다). **예산이 없거나
    비교할 관측값이 하나도 없으면** DEFAULT_TIER_KEY 로 폴백한다.
    """
    priced = [(i, t) for i, t in enumerate(tiers) if t["budget_min"] is not None]
    if won is None or not priced:
        for i, t in enumerate(tiers):
            if t["tier_key"] == DEFAULT_TIER_KEY:
                return i
        return 0
    if bound == "이상":
        ge = [(i, t) for i, t in priced if t["budget_min"] >= won]
        if ge:
            return min(ge, key=lambda it: it[1]["budget_min"])[0]
        return max(priced, key=lambda it: it[1]["budget_min"])[0]
    # '이하' 또는 bound 없음
    le = [(i, t) for i, t in priced if t["budget_min"] <= won]
    if le:
        return max(le, key=lambda it: it[1]["budget_min"])[0]
    return min(priced, key=lambda it: it[1]["budget_min"])[0]


# ── 제약 읽기 ───────────────────────────────────────────────────────────
def _pick(constraints: list[Constraint], label: str) -> str | None:
    for c in constraints:
        if (c.l or "").strip() == label and (c.v or "").strip():
            return c.v.strip()
    return None


def _platform_of(constraints: list[Constraint]) -> str:
    """'플랫폼' 라벨이 정본. 없으면 '선호' 값에 AMD/라이젠·인텔이 명시돼 있을 때만 그것,
    그 밖은 인텔(사장님 확정)."""
    v = _pick(constraints, "플랫폼")
    cands = [v] if v else [c.v for c in constraints if (c.l or "").strip() == "선호" and c.v]
    for s in cands:
        u = (s or "").upper()
        if "AMD" in u or "라이젠" in u or "RYZEN" in u:
            return "AMD"
        if "인텔" in u or "INTEL" in u:
            return "인텔"
    return DEFAULT_PLATFORM


def _usage_grid_of(constraints: list[Constraint]) -> tuple[str | None, str | None]:
    """(격자 용도 또는 GAME_USAGE, 파서 원문 용도). 파서 값이 정확히 같지 않아도
    라벨이 값에 포함되면 받는다(긴 라벨 우선 — '고사양 게임' 이 '게임' 보다 먼저)."""
    v = _pick(constraints, "용도")
    if not v:
        return None, None
    if v in USAGE_TO_GRID:
        return USAGE_TO_GRID[v], v
    for lab in sorted(USAGE_TO_GRID, key=len, reverse=True):
        if lab in v:
            return USAGE_TO_GRID[lab], v
    return None, v


def _state_from_constraints(cons: list[Constraint]) -> tuple[TalkState, list[str]]:
    """옛 모양(constraints[{l,v}]) → TalkState. 하위호환 전용(mvp1).

    옛 로직(_pick/_usage_grid_of/_platform_of/parse_budget) 그대로 읽어 좌표로 옮긴다.
    게임명·등급은 넣지 않는다 — 옛 모양엔 그 좌표가 없고 이 파일은 더 이상 게임명을
    뒤지지 않는다(AI 가 state.game 을 준다). 그래서 옛 모양의 게임 용도는 아래
    본체에서 needs=["game.grade"] 로 끝난다. 반환 (state, notes)."""
    notes: list[str] = []
    budget_won, bound = parse_budget(_pick(cons, "예산"))
    usage_grid, usage_raw = _usage_grid_of(cons)
    usages: list[str] = []
    if usage_grid is not None:
        # USAGE_TO_GRID 의 키(파서 라벨) 중 usage_raw 가 가리키는 것을 usages 로. 게임
        # 계열은 격자 용도가 같아도 라벨을 보존한다(is_game_usage 가 라벨을 본다).
        label = usage_raw if usage_raw in USAGE_TO_GRID else next(
            (lab for lab in sorted(USAGE_TO_GRID, key=len, reverse=True) if lab in (usage_raw or "")),
            None)
        if label:
            usages.append(label)
    elif usage_raw:
        notes.append(f"legacy constraints: usage '{usage_raw}' not in USAGE_TO_GRID")
    state = TalkState(usages=usages, budget_won=budget_won, budget_bound=bound,
                      platform=_platform_of(cons))
    return state, notes


def _record_estimate(state: TalkState) -> tuple[bool, str | None]:
    """§6 ② — ai_estimate 로 카드를 낸 시점에 talk_game_estimates(0093) 한 행.

    별도 트랜잭션. 실패해도 예외를 올리지 않는다 — 카드 응답은 이미 만들어졌고 기록
    누락은 로그(log.exception)와 notes 로만 드러낸다(api/llm.py cost_logged 와 같은
    판단: 이미 낸 답을 버리지 않되 누락을 조용히 감추지도 않는다).
    반환 (logged, error_text)."""
    g = state.game
    names = list(g.names) if g else []
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO talk_game_estimates (game_name_raw, names_all, grade)"
                " VALUES (:raw, CAST(:names AS jsonb), :grade)"),
                {"raw": names[0] if names else "", "names": json.dumps(names, ensure_ascii=False),
                 "grade": g.grade})
        return True, None
    except Exception as e:      # noqa: BLE001 — 기록 실패는 카드를 막지 않는다(헤더 참고)
        log.exception("[grid_public] talk_game_estimates insert failed (grade=%s names=%r)",
                      g.grade if g else None, names)
        return False, f"{type(e).__name__}: {e}"


# ── 견적 카드 조립 ──────────────────────────────────────────────────────
def _stock_by_code(conn, rows) -> dict:
    """행 목록(payload 포함) 전부의 product_code 를 한 번에 조회 — 지금 재고."""
    codes: set = set()
    for r in rows:
        if r is None or r.get("quote_id") is None:
            continue
        for it in ((r.get("payload") or {}).get("items") or []):
            if it.get("product_code") is not None:
                codes.add(it["product_code"])
    if not codes:
        return {}
    return {s["product_code"]: s["stock_qty"] for s in conn.execute(text(
        "SELECT product_code, stock_qty FROM products"
        " WHERE product_code = ANY(:c)"), {"c": list(codes)}).mappings().all()}


def _variant_payload(row, budget_won: int | None, bound: str | None, stock_by_code: dict) -> dict:
    """grid_quotes 행 하나(variant 하나) → 카드가 쓰는 모양. `over_budget` 은
    이 variant 자신의 total 로만 계산한다(지시 9번 — variant 마다 total 이 다르다)."""
    payload = row["payload"] or {}
    by_slot = {it.get("part_type"): it for it in (payload.get("items") or [])}
    parts = []
    for slot in PART_ORDER:
        it = by_slot.get(slot)
        if it is None:
            continue      # 그 자리가 없으면(예: 기본 쿨러 생략) 빈 항목을 지어내지 않는다
        parts.append({
            "cat": _cat_label(slot),
            "name": it.get("name"),
            "price": it.get("price"),
            "product_code": it.get("product_code"),
            "in_stock": stock_by_code.get(it.get("product_code"), 0) > 0,
        })
    total = row["total"] if row["total"] is not None else payload.get("total")
    # '이상' 은 하한이라 「예산 초과」 판정이 성립하지 않는다(기존 방침 유지).
    over_budget = bool(bound != "이상" and budget_won is not None
                        and total is not None and total > budget_won)
    return {
        "quote_id": row["quote_id"], "total": total, "over_budget": over_budget,
        "status": row["status"], "parts": parts,
        "reasons": list(payload.get("reasons") or []),
        "omitted": list(payload.get("omitted") or []),
        "generated_at": _iso(row["generated_at"]),
    }


def _build_card(cell_id: int, variants: dict, name: str, kind: str,
                 tier_key: str | None, tier_name: str | None,
                 usage: str, platform: str, tier_range: dict,
                 game_grade: str | None, game_resolution: str | None, game_name: str | None,
                 budget_won: int | None, bound: str | None, stock_by_code: dict) -> dict:
    """칸 하나 → 카드 하나. `quotes.{value,reco,perf}` 에 3종을 전부 담고(지시
    6번 핵심 변화), 하위호환을 위해 대표(추천) variant 값을 최상위에도 그대로
    얹는다. 없는 variant 는 None — 지어내지 않는다(admin_grid.py 와 같은 관행)."""
    quotes: dict = {}
    for kr_label, out_key in VARIANT_KEY_MAP.items():
        row = variants.get(kr_label)
        quotes[out_key] = (_variant_payload(row, budget_won, bound, stock_by_code)
                            if row is not None else None)

    rep = quotes.get(VARIANT_KEY_MAP[REPRESENTATIVE_VARIANT])   # "reco"
    return {
        "cell_id": cell_id, "kind": kind,               # kind: "nongame" | "game"
        "tier_key": tier_key, "tier": tier_name,
        "usage": usage, "platform": platform, "tier_range": tier_range,
        "game_grade": game_grade, "game_resolution": game_resolution, "game_name": game_name,
        "name": name,
        "quotes": quotes,
        # ── 하위호환 — 화면이 아직 quotes.* 로 안 옮겼어도 깨지지 않게(지시 6번) ──
        "quote_id": rep["quote_id"] if rep else None,
        "total": rep["total"] if rep else None,
        "over_budget": rep["over_budget"] if rep else False,
        "status": rep["status"] if rep else None,
        "parts": rep["parts"] if rep else [],
        "reasons": rep["reasons"] if rep else [],
        "omitted": rep["omitted"] if rep else [],
        "generated_at": rep["generated_at"] if rep else None,
    }


def _build_nongame_cards(conn, considered: list[dict], usage_grid: str, platform: str,
                          budget_won: int | None, bound: str | None) -> tuple[list, list]:
    """지시 5번 — WHERE 절을 tier_key 로 건다(비게임 축)."""
    cards: list = []
    empty_cells: list = []
    tier_keys = [t["tier_key"] for t in considered]
    rows = conn.execute(text(
        "SELECT c.cell_id, c.tier_key, c.budget_min, c.budget_max, c.intended_empty,"
        " q.tier_variant, q.quote_id, q.generated_at, q.total, q.status, q.payload"
        " FROM grid_cells c"
        " LEFT JOIN grid_quotes q ON q.cell_id = c.cell_id AND q.is_current"
        " WHERE c.usage = :u AND c.platform = :p AND c.tier_key = ANY(:tks)"),
        {"u": usage_grid, "p": platform, "tks": tier_keys}).mappings().all()

    by_tier: dict = {}
    for r in rows:
        slot = by_tier.setdefault(r["tier_key"], {
            "cell_id": r["cell_id"], "intended_empty": r["intended_empty"],
            "budget_min": r["budget_min"], "budget_max": r["budget_max"], "variants": {},
        })
        if r["quote_id"] is not None:
            slot["variants"][r["tier_variant"]] = r

    stock_by_code = _stock_by_code(conn, rows)

    for tier in considered:
        info = by_tier.get(tier["tier_key"])
        tier_range = {"min": tier["budget_min"], "max": tier["budget_max"]}
        if info is None:
            # 108칸 전량 시드(0092)라 정상적으로는 일어나지 않는다 — 방어적 분기.
            empty_cells.append({
                "cell_id": None, "tier_key": tier["tier_key"], "tier": tier["name"],
                "usage": usage_grid, "tier_range": tier_range,
                "reason": "격자에 이 칸이 없습니다(데이터 정합 확인 필요)"})
            continue
        if info["intended_empty"]:
            empty_cells.append({
                "cell_id": info["cell_id"], "tier_key": tier["tier_key"], "tier": tier["name"],
                "usage": usage_grid, "tier_range": tier_range,
                "reason": "의도적으로 비운 칸 — 이 티어×용도 조합은 격자가 만들지 않는다"})
            continue
        if not info["variants"]:
            empty_cells.append({
                "cell_id": info["cell_id"], "tier_key": tier["tier_key"], "tier": tier["name"],
                "usage": usage_grid, "tier_range": tier_range,
                "reason": "현재본 견적 없음"})
            continue
        name = f"{tier['name']} · {usage_grid}"     # 예: "팝콘3 · 디자인"(지시 7번)
        cards.append(_build_card(
            info["cell_id"], info["variants"], name, "nongame",
            tier["tier_key"], tier["name"], usage_grid, platform, tier_range,
            None, None, None, budget_won, bound, stock_by_code))
    return cards, empty_cells


def _build_game_cards(conn, grade: str, resolution: str, game_name: str | None,
                       platform: str, budget_won: int | None, bound: str | None) -> tuple[list, list]:
    """지시 5번 — WHERE 절을 game_grade+game_resolution 으로 건다(게임 축).
    (grade, resolution, platform) 은 uq_grid_cells_game_coord 로 유일하므로
    칸은 최대 1개다 — 비게임처럼 인접 등급을 함께 보여주는 정책은 지시서에
    없어 만들지 않는다(카드 최대 1장)."""
    cards: list = []
    empty_cells: list = []
    cell = conn.execute(text(
        "SELECT cell_id, budget_min, budget_max, intended_empty FROM grid_cells"
        " WHERE usage = :g_usage AND game_grade = :g AND game_resolution = :r AND platform = :p"),
        {"g_usage": GAME_USAGE, "g": grade, "r": resolution, "p": platform}).mappings().first()
    tier_range = {"min": cell["budget_min"], "max": cell["budget_max"]} if cell else {"min": None, "max": None}
    if cell is None:
        empty_cells.append({
            "cell_id": None, "game_grade": grade, "game_resolution": resolution,
            "game_name": game_name, "usage": GAME_USAGE, "tier_range": tier_range,
            "reason": "격자에 이 등급·해상도 칸이 없습니다(데이터 정합 확인 필요)"})
        return cards, empty_cells
    if cell["intended_empty"]:
        empty_cells.append({
            "cell_id": cell["cell_id"], "game_grade": grade, "game_resolution": resolution,
            "game_name": game_name, "usage": GAME_USAGE, "tier_range": tier_range,
            "reason": "의도적으로 비운 칸"})
        return cards, empty_cells

    q_rows = conn.execute(text(
        "SELECT tier_variant, quote_id, generated_at, total, status, payload"
        " FROM grid_quotes WHERE cell_id = :id AND is_current"),
        {"id": cell["cell_id"]}).mappings().all()
    variants = {r["tier_variant"]: r for r in q_rows}
    if not variants:
        empty_cells.append({
            "cell_id": cell["cell_id"], "game_grade": grade, "game_resolution": resolution,
            "game_name": game_name, "usage": GAME_USAGE, "tier_range": tier_range,
            "reason": "현재본 견적 없음"})
        return cards, empty_cells

    stock_by_code = _stock_by_code(conn, list(variants.values()))
    name = f"{grade}등급 · {resolution}"        # 예: "E등급 · 1080p"(지시 7번)
    cards.append(_build_card(
        cell["cell_id"], variants, name, "game", None, None, GAME_USAGE, platform,
        tier_range, grade, resolution, game_name, budget_won, bound, stock_by_code))
    return cards, empty_cells


# ── 용도별 카드 묶음(card_set) ────────────────────────────────────────────
def _nongame_card_set(conn, usage: str, state: TalkState, platform: str,
                      notes: list[str]) -> dict:
    """비게임 용도 하나 → card_set. tier_key 힌트가 있으면 그 칸 중심, 없으면 예산으로
    tier_index_for. 둘 다 있으면 예산 우선(헤더 ④·설계서 §11)."""
    usage_grid = USAGE_TO_GRID[usage]
    tiers = _load_tiers(conn, usage_grid, platform)
    ci = tier_index_for(tiers, state.budget_won, state.budget_bound)
    hint_i = next((i for i, t in enumerate(tiers) if t["tier_key"] == state.tier_key), None)
    if state.tier_key is not None:
        if state.budget_won is None:
            ci = hint_i if hint_i is not None else ci
            if hint_i is None:
                notes.append(f"{usage}: tier_key hint {state.tier_key} not in spec_tiers - ignored")
        elif hint_i is not None and hint_i != ci:
            notes.append(f"{usage}: tier_key hint {state.tier_key} != budget pick"
                         f" {tiers[ci]['tier_key']} - budget wins")
    elif state.budget_won is None:
        notes.append(f"{usage}: no budget, no tier_key hint - center {DEFAULT_TIER_KEY}")
    considered = tiers[ci: ci + 1 + TIERS_UP]
    cards, empty_cells = _build_nongame_cards(
        conn, considered, usage_grid, platform, state.budget_won, state.budget_bound)
    if not cards:
        notes.append(f"{usage}: no cards in considered tiers {[t['tier_key'] for t in considered]}")
    return {
        "usage": usage, "usage_grid": usage_grid, "kind": "nongame",
        "cards": cards, "empty_cells": empty_cells,
        "center_tier": tiers[ci]["name"], "center_tier_key": tiers[ci]["tier_key"],
        "tiers_considered": [t["tier_key"] for t in considered],
    }


def _game_card_set(conn, usage: str, state: TalkState, platform: str,
                   notes: list[str]) -> dict:
    """게임 계열 용도 → card_set 하나(칸 최대 1개). grade 는 이미 있다고 전제(호출부가
    needs 로 거른다). 해상도 null 이면 DEFAULT_RESOLUTION — assumed 는 호출부가 단다."""
    g = state.game
    resolution = g.resolution or DEFAULT_RESOLUTION
    game_name = g.names[0] if g.names else None
    cards, empty_cells = _build_game_cards(
        conn, g.grade, resolution, game_name, platform, state.budget_won, state.budget_bound)
    if not cards:
        notes.append(f"{usage}: no cards at grade={g.grade} resolution={resolution} platform={platform}")
    return {
        "usage": usage, "usage_grid": GAME_USAGE, "kind": "game",
        "cards": cards, "empty_cells": empty_cells,
        "center_tier": None, "center_tier_key": None, "tiers_considered": [],
    }


# ── 본체 ────────────────────────────────────────────────────────────────
@router.post("/recommend")
def recommend(body: RecommendBody):
    """state(TalkState) → 용도별 격자 카드 묶음. 400 을 내지 않는다 — 부족한 것은
    `needs` 로 말하고 카드 0장(되묻는 문장은 AI 의 reply 가 맡는다, 이 응답의
    notes 는 화면에 싣지 않는다).

    응답 {ok,
          card_sets: [{usage, usage_grid, kind("nongame"|"game"), cards[], empty_cells[],
                       center_tier, center_tier_key, tiers_considered[]}],
          cards[]          ← 하위호환: card_sets[0].cards 그대로(없으면 []),
          assumed[]        예: ["game.resolution=1080p"]  (§6 ③),
          ai_estimated[]   예: [{game_names:[...], grade:"C"}]  (§6 ② 화면 배지),
          needs[]          "usages" | "game.grade"  (talk_schema.missing_for — talk.py 와 같은 함수),
          dropped[]        validate_state 가 접은 값 [{field, value, reason}] 그대로 — 화면이
                           '반영하지 못한 조건'(예: resolution=8K → 1080p)을 고객에게 말할 수
                           있게 싣는다(parse 응답의 dropped 와 같은 모양). legacy 경로는 [],
          notes[]          서버 내부 사유(로그·디버그) — 고객 문구 아님,
          platform, budget_won, budget_bound, game_grade, game_resolution, game_name}

      cards[].quotes = {value, reco, perf} — 칸 하나의 3종 구성. 각 안에 {quote_id,
      total, over_budget, status, parts, reasons, omitted, generated_at}. 카드
      최상위에도 대표(추천) variant 값을 그대로 얹는다(하위호환).
      empty_cells  고려한 칸 중 카드가 안 나온 것의 사유 — intended_empty 면 그
                   사실, 현재본 견적이 없으면 '현재본 없음'.
    """
    notes: list[str] = []
    dropped: list[dict] = []

    with engine.connect() as conn:
        # ── 입력 → TalkState ─────────────────────────────────────────
        vocab = load_vocab(conn)     # validate_state · missing_for 둘 다 쓴다(legacy 경로 포함)
        if body.state is not None:
            state, dropped = validate_state(body.state, vocab)
            for d in dropped:
                notes.append(f"dropped {d['field']}={d['value']!r}: {d['reason']}")
        else:
            state, legacy_notes = _state_from_constraints(body.constraints or [])
            notes.extend(legacy_notes)
            if body.constraints:
                notes.append("input=legacy constraints (no state)")

        platform = state.platform or DEFAULT_PLATFORM
        game_usages = [u for u in state.usages if is_game_usage(u)]
        nongame_usages = [u for u in state.usages if not is_game_usage(u)
                          and u in USAGE_TO_GRID]
        for u in state.usages:
            if not is_game_usage(u) and u not in USAGE_TO_GRID:
                notes.append(f"usage '{u}' not in USAGE_TO_GRID - skipped")

        # ── needs — 카드를 막는 좌표. talk.py 의 missing 과 같은 함수(단일 원천) ──
        needs = missing_for(state, vocab)
        game_grade = state.game.grade if (game_usages and state.game) else None

        # ── usages[] 마다 card_set ───────────────────────────────────
        card_sets: list[dict] = []
        assumed: list[str] = []
        ai_estimated: list[dict] = []
        game_resolution = game_name = None
        for u in nongame_usages:
            card_sets.append(_nongame_card_set(conn, u, state, platform, notes))
        if game_usages and game_grade is not None:
            # 게임 계열 용도가 여럿(게임+고사양 게임)이어도 격자 칸은 같다 — 한 벌만.
            # usage 라벨은 가장 먼저 온 게임 계열 용도를 쓴다.
            if len(game_usages) > 1:
                notes.append(f"game usages {game_usages} merged into one card set")
            cs = _game_card_set(conn, game_usages[0], state, platform, notes)
            card_sets.append(cs)
            game_resolution = state.game.resolution or DEFAULT_RESOLUTION
            game_name = state.game.names[0] if state.game.names else None
            if state.game.resolution is None:
                assumed.append(ASSUMED_RESOLUTION)
            if state.game.grade_src == "ai_estimate":
                ai_estimated.append({"game_names": list(state.game.names), "grade": game_grade})

    # ── §6 ② 추정 기록 — 카드를 낸 시점, 별도 트랜잭션, 실패해도 응답은 그대로 ──
    # ⚠ G-5 (2026-09-16 사장님 확정): **게임명이 빈 추정은 기록하지 않는다.**
    #   "요즘 대작 다 돌리고 싶어요" 처럼 이름 없이 등급만 추정된 경우 원장에 남겨도
    #   사람이 확정할 대상(어느 게임인가)이 없어 `game_name_raw=''` 행만 쌓인다.
    #   카드는 그대로 내고 배지도 띄우되(ai_estimated 는 채운다) 표에는 안 넣는다.
    if ai_estimated and state.game is not None and state.game.names:
        logged, err = _record_estimate(state)
        if not logged:
            notes.append(f"talk_game_estimates insert failed: {err}")
    elif ai_estimated:
        notes.append("ai_estimate without game names - not recorded (G-5)")

    return {
        "ok": True,
        "card_sets": card_sets,
        "cards": card_sets[0]["cards"] if card_sets else [],     # 하위호환
        "assumed": assumed,
        "ai_estimated": ai_estimated,
        "needs": needs,
        "dropped": dropped,
        "notes": notes,
        "platform": platform,
        "budget_won": state.budget_won,
        "budget_bound": state.budget_bound,
        "game_grade": game_grade,
        "game_resolution": game_resolution,
        "game_name": game_name,
    }
