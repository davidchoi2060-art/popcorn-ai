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
      AI 작업/영상편집/디자인/사무·인강/주식·트레이딩/3D 그래픽 — 아래 usage_map()
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
# 0105 — `DEFAULT_TIER_KEY`/`TIERS_UP` 은 사라졌다. 비게임 축에서 tier_key 가
# 빠졌고, 예산대 목록 자체가 이미 그 용도에 맞게 좁아서(격자에 있는 칸만) 중심을
# 가정값으로 찍을 필요가 없다 — 예산이 없으면 그 용도의 가장 싼 구간이 중심이다.
BANDS_UP = 2                     # 중심 + 위 2개(0072 이래 «위쪽도 보여준다» 정책 유지)
DEFAULT_PLATFORM = "인텔"        # 사장님 확정(2026-09-11), 스키마와 무관
# 플랫폼 어휘는 talk_schema.PLATFORM_VALUES 하나만 쓴다(validate_state 가 거른다) — 여기
# 따로 두지 않는다(단일 원천). 옛 PLATFORMS 상수는 미참조라 지웠다(2026-09-16 확인자 G-2).
GAME_USAGE = "게임"              # grid_cells.usage 의 게임 축 리터럴(0092)
# 해상도 기본값은 talk_schema.DEFAULT_RESOLUTION(1080p) 하나만 쓴다 — 여기 따로 두지
# 않는다(단일 원천). null 이면 그 값으로 카드를 내고 assumed 에 표시한다(§6 ③).
ASSUMED_RESOLUTION = f"game.resolution={DEFAULT_RESOLUTION}"

# ── 용도 매핑 — 파서 14종 → grid_cells.usage(비게임 11종) + '게임' ──────────
# 2026-09-20 (0105) — **접는 매핑이 사라졌다.** 0105 격자가 `usage_floors.usage_label`
# 을 그대로 `grid_cells.usage` 축으로 쓰므로 비게임은 전부 **항등 매핑**이다.
#   옛 판(0092~0104)은 격자 용도가 6종뿐이라 «단순 사무용»·«복합 사무용»을 둘 다
#   '사무·인강' 으로, «캐드·설계»·«3D 렌더링» 을 둘 다 '3D 그래픽' 으로 접었다 —
#   하한(usage_floors)은 갈렸는데 격자는 안 갈려서 «두 용도가 같은 카드를 보되
#   엔진 하한은 서로 다른» 상태였다(0102·0104 주석이 "후속 작업"이라고 남긴 것).
#   0105 가 그 후속 작업이다: 격자가 14종 용도를 직접 안다.
# ⚠ 옛 리터럴('사무·인강'·'3D 그래픽')은 **키로만** 남긴다 — consult_sessions·
#   grid_quotes.payload 가 그 값을 들고 있어 지우면 그 입력이 통째로
#   needs=['usages'] 로 떨어진다. 값은 새 격자 용도로 옮긴다.
# ⚠ 0110 — 이 표를 **손으로 적지 않는다.** DB 두 곳이 정본이다:
#     정규 이름 = `grid_cells.usage` 의 DISTINCT (격자가 실제로 가진 용도)
#     옛 이름   = `usage_label_map` (legacy_label -> canonical_label)
#   손으로 적던 시절 0102(사무 분할) 때 새 키를 빠뜨려 격자 카드가 0장이 될 뻔했고,
#   0108(디자인 분할) 주석이 그 사고를 "분할 마이그레이션과 한 묶음으로 고친다"고
#   남겼다 — 즉 **표가 사람 손에 있는 한 다음 분할에서 또 빠진다.** 0110 이 용도를
#   다시 재편하면서(합치기 3 + AI 분할) 그 구조를 끝낸다.
#   여기 없는 용도는 카드가 «조용히» 사라진다(KeyError 가 아니라 needs=['usages']).
#
# `usage_label_map.canonical_label` 이 NULL 이면 «대응을 모른다»는 뜻이라 매핑에
# 넣지 않는다 — 지어내 잇지 않는다(그 입력은 needs 로 떨어지고, 그게 정직한 결과다).
_USAGE_MAP_CACHE: dict | None = None


def _load_usage_map(conn) -> dict:
    out: dict = {}
    for (u,) in conn.execute(text("SELECT DISTINCT usage FROM grid_cells")):
        out[u] = u                     # 격자가 가진 이름은 항등 매핑
    for r in conn.execute(text(
            "SELECT legacy_label, canonical_label FROM usage_label_map"
            " WHERE canonical_label IS NOT NULL")).mappings():
        # 격자에 실제로 있는 이름으로만 잇는다. 매핑표가 격자보다 앞서 갈 수 있다.
        if r["canonical_label"] in out:
            out.setdefault(r["legacy_label"], r["canonical_label"])
    return out


def usage_map() -> dict:
    """파서·원장 용도 라벨 -> grid_cells.usage. DB 가 정본이고 프로세스 수명 캐시."""
    global _USAGE_MAP_CACHE
    if _USAGE_MAP_CACHE is None:
        try:
            with engine.connect() as conn:
                _USAGE_MAP_CACHE = _load_usage_map(conn)
        except Exception as e:      # DB 를 못 읽으면 매핑 없이 — 카드가 안 나올 뿐
            print(f"[grid_public] usage_map load failed: {e}")
            _USAGE_MAP_CACHE = {}
    return _USAGE_MAP_CACHE


def reload_usage_map() -> int:
    global _USAGE_MAP_CACHE
    _USAGE_MAP_CACHE = None
    return len(usage_map())


# grid_quotes.tier_variant(한글) → 응답 키(카드 3종 구조, 지시 6번 예시 그대로)
VARIANT_KEY_MAP = {"가성비": "value", "추천": "reco", "고성능": "perf"}
REPRESENTATIVE_VARIANT = "추천"   # 하위호환 최상위 필드가 참조하는 대표 variant

# ── 칸 취급 상태 (0110 · 사장님 확정 ⑥) ────────────────────────────────
# 옛 `intended_empty`(boolean)는 「시장에도 없다」와 「표본이 없어 모른다」를
# 구분하지 못했고, 고객에게는 둘 다 「의도적으로 비운 칸」으로 나갔다.
# 문구는 CLAUDE.md §어휘 — 고객에게 «비움»·«모름» 같은 내부 말을 쓰지 않는다.
STATE_ACTIVE = "취급함"
HANDLING_REASON = {
    "일부러 비움": "취급하지 않는 가격대입니다",
    "모름": "이 가격대는 아직 확인되지 않았습니다",
    "채울 예정": "준비 중인 가격대입니다",
}


def _load_omissions(conn, usage: str) -> list[dict]:
    """이 용도가 «발행하지 않는» 구성과 그 사유(0106).

    화면이 「왜 여긴 세 개인데 여긴 두 개지」를 묻지 않게 하는 자리다. 카드가
    조용히 사라지면 고객은 이유를 지어내 생각한다 — 우리 정체성은 「모든 견적에는
    이유가 있습니다」이므로, 없는 것에도 사유를 붙여 내려준다.
    사유 문구는 `grid_variant_omissions.reason_public` 원문이다 — 여기서 새로
    만들지 않는다(§단일 원천). 그 컬럼은 NOT NULL 이라 사유 없는 제외가 없다.
    """
    rows = conn.execute(text(
        "SELECT tier_variant, reason_public FROM grid_variant_omissions"
        " WHERE usage = :u"), {"u": usage}).mappings().all()
    return [{"variant": r["tier_variant"],
             "key": VARIANT_KEY_MAP.get(r["tier_variant"]),
             "reason": r["reason_public"]} for r in rows]


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


def _load_bands(conn, axis: str, usage_grid: str | None, platform: str,
                game_grade: str | None = None,
                game_resolution: str | None = None) -> list[dict]:
    """이 (용도[×등급×해상도] × 플랫폼)에 **실제로 칸이 있는** 예산대만 정본 순서로.

    ⚠ 0105 대전환 — 옛 판(`_load_tiers`)은 `spec_tiers` T0~T5 **전부**를 싣고 그
    티어의 관측 가격을 붙였다. 그 축이 «사무·인강 × T5 = 1,344만원» 같은 헛칸을
    만들었다. 새 판은 그 반대로 간다: **격자에 존재하는 칸만** 예산대 목록이
    된다. 어떤 용도에 어떤 예산대를 둘지는 0105 마이그레이션이 실판매 표본으로
    정했고(각 칸의 `band_note` 에 근거가 적혀 있다), 이 함수는 그것을 읽기만 한다.

    구간 경계(`budget_min_won`/`budget_max_won`)는 `grid_budget_bands`의 **정의**고,
    `budget_min`/`budget_max`는 배치가 실제로 만든 **관측 범위**(가성비~고성능)다.
    둘을 섞지 않는다 — 앞은 입력, 뒤는 출력이다.
    """
    where = " AND c.usage = :u"
    params: dict = {"axis": axis, "p": platform, "u": usage_grid}
    if axis == "game":
        where += " AND c.game_grade = :g AND c.game_resolution = :r"
        params.update({"u": GAME_USAGE, "g": game_grade, "r": game_resolution})
    rows = conn.execute(text(
        "SELECT b.band_key, b.label, b.budget_min_won, b.budget_max_won, b.sample_n,"
        " b.gpu_required, c.cell_id, c.quote_low, c.quote_high, c.band_note,"
        " c.handling_state, c.handling_note"
        " FROM grid_budget_bands b"
        " JOIN grid_cells c ON c.budget_band_key = b.band_key AND c.platform = :p"
        + where +
        " WHERE b.axis = :axis ORDER BY b.sort_order"), params).mappings().all()
    return [dict(r) for r in rows]


def band_index_for(bands: list[dict], won: int | None, bound: str | None) -> int:
    """예산 값으로 중심 예산대 인덱스를 고른다.

    ⚠ 0105 로 비교 재료가 «점»에서 «구간»으로 돌아왔다. 옛 판(`tier_index_for`)은
    budget_min==budget_max(단일 관측점)라 반열림 구간 비교가 사실상 항상 실패해서
    "가장 가까운 관측점" 규칙으로 대체해야 했다. 이제 `grid_budget_bands`가 실판매
    분포에서 뽑은 **진짜 구간**을 들고 있으므로 구간 비교로 돌아간다.

      · bound 없음 또는 '이하'(상한 취급) — 예산이 들어가는 구간. 없으면 예산
        이하인 구간 중 가장 비싼 것(예산을 최대한 채운다), 그것도 없으면 가장 싼 것.
      · '이상'(하한) — 예산 이상을 커버하는 구간 중 가장 싼 것. 없으면 가장 비싼 것.
    예산이 없거나 구간이 하나도 없으면 0(가장 싼 구간)이다 — 옛 DEFAULT_TIER_KEY
    같은 가정값을 새로 만들지 않는다(구간 목록 자체가 이미 그 용도에 맞게 좁다).
    """
    if not bands:
        return 0
    if won is None:
        return 0
    if bound == "이상":
        ge = [i for i, b in enumerate(bands)
              if b["budget_max_won"] is None or b["budget_max_won"] >= won]
        return ge[0] if ge else len(bands) - 1
    inside = [i for i, b in enumerate(bands)
              if b["budget_min_won"] <= won
              and (b["budget_max_won"] is None or won <= b["budget_max_won"])]
    if inside:
        return inside[0]
    le = [i for i, b in enumerate(bands) if b["budget_min_won"] <= won]
    if le:
        return le[-1]
    return 0


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
    umap = usage_map()
    if v in umap:
        return umap[v], v
    for lab in sorted(umap, key=len, reverse=True):
        if lab in v:
            return umap[lab], v
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
        # usage_map() 의 키(파서 라벨) 중 usage_raw 가 가리키는 것을 usages 로. 게임
        # 계열은 격자 용도가 같아도 라벨을 보존한다(is_game_usage 가 라벨을 본다).
        umap = usage_map()
        label = usage_raw if usage_raw in umap else next(
            (lab for lab in sorted(umap, key=len, reverse=True) if lab in (usage_raw or "")),
            None)
        if label:
            usages.append(label)
    elif usage_raw:
        notes.append(f"legacy constraints: usage '{usage_raw}' not in usage_map()")
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
                 band: dict, usage: str, platform: str,
                 game_grade: str | None, game_resolution: str | None, game_name: str | None,
                 budget_won: int | None, bound: str | None, stock_by_code: dict,
                 omissions: list[dict] | None = None) -> dict:
    """칸 하나 → 카드 하나. `quotes.{value,reco,perf}` 에 3종을 전부 담고, 하위호환을
    위해 대표(추천) variant 값을 최상위에도 그대로 얹는다. 없는 variant 는 None.

    ⚠ `tier_range`(0105) — 옛 판은 `{min: budget_min, max: budget_max}` 였고 그 둘이
    같은 값(추천 단일점)이었다. 이제 min=가성비·max=고성능 **실제 범위**다.
    구간 «정의»(band_min/band_max)는 별도 필드로 따로 싣는다 — 정의와 관측을
    한 필드에 겹쳐 담지 않는다.
    `tier_key`/`tier` 는 0105 로 비게임 축에서 사라졌다 — 화면 하위호환을 위해
    키는 남기되 항상 None 이다(없는 값을 지어내 채우지 않는다).
    """
    quotes: dict = {}
    for kr_label, out_key in VARIANT_KEY_MAP.items():
        row = variants.get(kr_label)
        quotes[out_key] = (_variant_payload(row, budget_won, bound, stock_by_code)
                            if row is not None else None)

    rep = quotes.get(VARIANT_KEY_MAP[REPRESENTATIVE_VARIANT])   # "reco"
    om = list(omissions or [])
    return {
        "cell_id": cell_id, "kind": kind,               # kind: "nongame" | "game"
        "tier_key": None, "tier": None,                 # 0105 로 축에서 사라짐(하위호환 키)
        "band_key": band["band_key"], "band": band["label"],
        "band_range": {"min": band["budget_min_won"], "max": band["budget_max_won"]},
        "band_sample_n": band["sample_n"], "band_note": band["band_note"],
        "gpu_required": band["gpu_required"],
        "usage": usage, "platform": platform,
        # ── 0106: «없는 카드»의 사유. 화면은 탭을 비활성으로 두고 이 문구를 쓴다 ──
        # `quotes[key] is None` 만으로는 «아직 안 만들어진 것»과 «만들지 않기로 한
        # 것»을 구분할 수 없다. 그 둘은 고객에게 전혀 다른 말이라 필드를 가른다.
        "omitted_variants": om,
        "omitted_variant_keys": [o["key"] for o in om if o.get("key")],
        # 관측 범위 — 가성비~고성능. 옛 이름을 유지해 화면이 안 깨지게 한다.
        "tier_range": {"min": band["quote_low"], "max": band["quote_high"]},
        "game_grade": game_grade, "game_resolution": game_resolution, "game_name": game_name,
        "name": name,
        "quotes": quotes,
        # ── 하위호환 — 화면이 아직 quotes.* 로 안 옮겼어도 깨지지 않게 ──
        "quote_id": rep["quote_id"] if rep else None,
        "total": rep["total"] if rep else None,
        "over_budget": rep["over_budget"] if rep else False,
        "status": rep["status"] if rep else None,
        "parts": rep["parts"] if rep else [],
        "reasons": rep["reasons"] if rep else [],
        "omitted": rep["omitted"] if rep else [],
        "generated_at": rep["generated_at"] if rep else None,
    }


def _build_cards(conn, considered: list[dict], usage_grid: str, platform: str,
                 kind: str, budget_won: int | None, bound: str | None,
                 game_grade: str | None = None, game_resolution: str | None = None,
                 game_name: str | None = None) -> tuple[list, list]:
    """고려한 예산대 칸들 → 카드 + 빈칸 사유. 게임·비게임 공통(0105).

    0092 판은 축이 달라 `_build_nongame_cards`/`_build_game_cards` 둘로 갈려
    있었다. 0105 에서는 둘 다 «칸 = 예산대» 라 조회가 같아져 하나로 합친다
    (같은 판정을 두 벌 두지 않는다 · §단일 원천). 다른 것은 카드 이름과
    game_* 필드뿐이다.
    """
    cards: list = []
    empty_cells: list = []
    if not considered:
        return cards, empty_cells

    cell_ids = [b["cell_id"] for b in considered]
    # 이 용도가 발행하지 않는 구성 + 사유(0106) — 칸마다 같으므로 한 번만 읽는다.
    omissions = _load_omissions(conn, usage_grid)
    rows = conn.execute(text(
        "SELECT cell_id, tier_variant, quote_id, generated_at, total, status, payload"
        " FROM grid_quotes WHERE cell_id = ANY(:ids) AND is_current"),
        {"ids": cell_ids}).mappings().all()
    by_cell: dict = {}
    for r in rows:
        by_cell.setdefault(r["cell_id"], {})[r["tier_variant"]] = r
    stock_by_code = _stock_by_code(conn, rows)

    for band in considered:
        info = {"cell_id": band["cell_id"], "band_key": band["band_key"],
                "band": band["label"], "usage": usage_grid,
                "band_range": {"min": band["budget_min_won"], "max": band["budget_max_won"]},
                "tier_range": {"min": band["quote_low"], "max": band["quote_high"]},
                "handling_state": band["handling_state"]}
        # 0110 — 「취급함」이 아닌 칸의 사유를 셋으로 갈라 말한다(사장님 확정 ⑥).
        # 옛 boolean 은 셋을 「의도적으로 비운 칸」 한 문구로 뭉갰다.
        if band["handling_state"] != STATE_ACTIVE:
            empty_cells.append({**info,
                                "reason": HANDLING_REASON[band["handling_state"]],
                                "reason_detail": band["handling_note"]})
            continue
        variants = by_cell.get(band["cell_id"]) or {}
        if not variants:
            empty_cells.append({**info, "reason": "현재본 견적 없음"})
            continue
        if kind == "game":
            name = f"{game_grade}등급 · {game_resolution} · {band['label']}"
        else:
            name = f"{usage_grid} · {band['label']}"
        cards.append(_build_card(
            band["cell_id"], variants, name, kind, band, usage_grid, platform,
            game_grade, game_resolution, game_name, budget_won, bound, stock_by_code,
            omissions))
    return cards, empty_cells


# ── 용도별 카드 묶음(card_set) ────────────────────────────────────────────
def _nongame_card_set(conn, usage: str, state: TalkState, platform: str,
                      notes: list[str]) -> dict:
    """비게임 용도 하나 → card_set. 예산으로 중심 예산대를 고르고 그 위 BANDS_UP 개까지.

    ⚠ 0105 — `tier_key` 힌트는 더 이상 비게임 축이 아니다(축에서 사라졌다).
    state.tier_key 가 와도 무시하고 notes 에 그 사실을 남긴다 — 조용히 삼키면
    화면이 "반영됐다"고 착각한다.
    """
    usage_grid = usage_map()[usage]
    bands = _load_bands(conn, "nongame", usage_grid, platform)
    if not bands:
        notes.append(f"{usage}: no bands in grid for platform={platform}")
        return {"usage": usage, "usage_grid": usage_grid, "kind": "nongame",
                "cards": [], "empty_cells": [], "omitted_variants": [],
                "center_band": None,
                "center_band_key": None, "bands_considered": [],
                "center_tier": None, "center_tier_key": None, "tiers_considered": []}
    ci = band_index_for(bands, state.budget_won, state.budget_bound)
    if state.tier_key is not None:
        notes.append(f"{usage}: tier_key hint {state.tier_key} ignored"
                     " - 0105 removed tier_key from the non-game axis")
    if state.budget_won is None:
        notes.append(f"{usage}: no budget - center = cheapest band {bands[0]['band_key']}")
    considered = bands[ci: ci + 1 + BANDS_UP]
    cards, empty_cells = _build_cards(
        conn, considered, usage_grid, platform, "nongame",
        state.budget_won, state.budget_bound)
    if not cards:
        notes.append(f"{usage}: no cards in considered bands"
                     f" {[b['band_key'] for b in considered]}")
    return {
        "usage": usage, "usage_grid": usage_grid, "kind": "nongame",
        "cards": cards, "empty_cells": empty_cells,
        # 용도 단위의 «없는 구성» 사유(0106) — 카드마다 같은 문장이라, 화면이 묶음
        # 머리에 한 번만 쓰고 싶을 때 여기를 읽는다(카드 안에도 같은 값이 있다).
        "omitted_variants": _load_omissions(conn, usage_grid),
        "center_band": bands[ci]["label"], "center_band_key": bands[ci]["band_key"],
        "bands_considered": [b["band_key"] for b in considered],
        # 하위호환 키 — 0105 로 tier 축이 사라져 항상 None/[] 이다(지어내지 않는다)
        "center_tier": None, "center_tier_key": None, "tiers_considered": [],
    }


def _game_card_set(conn, usage: str, state: TalkState, platform: str,
                   notes: list[str]) -> dict:
    """게임 계열 용도 → card_set. 0105 로 **칸이 여럿이다**(등급×해상도 하나에
    예산대가 1~3개) — 옛 판은 칸이 최대 1개라 카드도 1장뿐이었고, 그래서 롤 하는
    고객이 219만원짜리 카드 한 장만 봤다. 이제 예산대마다 카드가 나온다."""
    g = state.game
    resolution = g.resolution or DEFAULT_RESOLUTION
    game_name = g.names[0] if g.names else None
    bands = _load_bands(conn, "game", GAME_USAGE, platform, g.grade, resolution)
    if not bands:
        notes.append(f"{usage}: no bands at grade={g.grade} resolution={resolution}"
                     f" platform={platform}")
        return {"usage": usage, "usage_grid": GAME_USAGE, "kind": "game",
                "cards": [], "empty_cells": [], "omitted_variants": [],
                "center_band": None,
                "center_band_key": None, "bands_considered": [],
                "center_tier": None, "center_tier_key": None, "tiers_considered": []}
    ci = band_index_for(bands, state.budget_won, state.budget_bound)
    considered = bands[ci: ci + 1 + BANDS_UP]
    cards, empty_cells = _build_cards(
        conn, considered, GAME_USAGE, platform, "game",
        state.budget_won, state.budget_bound, g.grade, resolution, game_name)
    if not cards:
        notes.append(f"{usage}: no cards at grade={g.grade} resolution={resolution}"
                     f" platform={platform}")
    return {
        "usage": usage, "usage_grid": GAME_USAGE, "kind": "game",
        "cards": cards, "empty_cells": empty_cells,
        "omitted_variants": _load_omissions(conn, GAME_USAGE),
        "center_band": bands[ci]["label"], "center_band_key": bands[ci]["band_key"],
        "bands_considered": [b["band_key"] for b in considered],
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
      empty_cells  고려한 칸 중 카드가 안 나온 것의 사유. handling_state 가
                   「취급함」이 아니면 그 상태별 문구(0110 — 취급하지 않는 구간 /
                   시장 표본이 없어 확인되지 않은 구간 / 준비 중인 구간)와
                   handling_note 원문을 reason_detail 에 싣고, 그 밖이면
                   '현재본 견적 없음'.
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
                          and u in usage_map()]
        for u in state.usages:
            if not is_game_usage(u) and u not in usage_map():
                notes.append(f"usage '{u}' not in usage_map() - skipped")

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
