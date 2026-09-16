# -*- coding: utf-8 -*-
"""고객용 격자 추천 API — `POST /api/grid/recommend` (A-135 스펙축 재설계, 2026-09-16).

■ 무엇을 하나
  talk.py 가 낸 constraints(예산·용도·플랫폼 …)를 받아 사전 생성 견적 격자
  (grid_cells × grid_quotes.is_current, 0092)에서 칸을 찾아 카드로 돌려준다.
  실시간 recommend 엔진을 돌리지 않는다 — 격자가 추천 원천이다(A-126·A-128).

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

■ 읽기 전용이다 — SELECT 만. 세션도 원장도 쓰지 않는다.

■ 지어내지 않는 것
  · `reasons`·`omitted` 는 payload 그대로(재작성 금지).
  · 카드 이름은 payload.label 을 쓰지 않는다 — 조사자 실측(2026-09-11)으로 70건
    전부 '추천형 견적' 동일이라 정보가 없다. 티어/등급 + 용도로 합성한다.
  · `in_stock` 은 `products.stock_qty` 를 그 자리에서 다시 읽은 값이다.
  · budget_min/max 가 NULL(배치 미실행)이면 그대로 null 을 내보낸다 — 만든 숫자를
    채우지 않는다.

■ 이번 재작성에서 사장님 확정 없이 이 파일이 직접 판단한 것 셋(보고서에 명시)
  ① DEFAULT_TIER_KEY = "T1"(팝콘2, 입문급) — 예산 없을 때 중심 티어. 지시서
     원문이 "미정이면 T1로 가정"이라 명시해 그대로 따른다.
  ② `tier_index_for` 의 예산 매칭 규칙을 반열림 구간 비교에서 "관측 가격점 중
     가장 가까운 티어" 규칙으로 바꿨다 — budget_min==budget_max(단일 관측점)라
     옛 [min,max) 구간 비교가 사실상 항상 실패하기 때문이다(아래 함수 docstring
     참고). 새 가격을 지어내지 않고 실측 점들만 재료로 쓰지만, 이 대체 규칙
     자체는 사장님 확정 사항이 아니다.
  ③ 게임 용도의 "게임명"을 파서가 아직 전용 라벨로 주지 않는다(2026-09-16 실측
     — api/talk.py LABELS 에 '게임명' 없음). '요청'(원문 보관)·'선호' 값 안에서
     games.name 부분일치를 시도하되, 못 찾으면 needs=["게임명"]으로 되묻는다.
"""
import re

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine
from .taxonomy import SLOT_LABELS
from .timeutil import iso as _iso

router = APIRouter(prefix="/api/grid", tags=["grid-public"])

# ── 상수 ────────────────────────────────────────────────────────────────
DEFAULT_TIER_KEY = "T1"          # 예산 없을 때 중심 tier_key — 위 ① 참고(가정값)
TIERS_UP = 2                     # 중심 + 위 2개(0072 이래 정책 유지, 이번 변경 범위 밖)
DEFAULT_PLATFORM = "인텔"        # 사장님 확정(2026-09-11), 스키마와 무관
PLATFORMS = ("인텔", "AMD")      # grid_cells.platform 이 정본
GAME_USAGE = "게임"              # grid_cells.usage 의 게임 축 리터럴(0092)
DEFAULT_GAME_RESOLUTION = "1080p"
# ⚠ 파서(api/talk.py)가 아직 해상도를 묻는 입력을 받지 않는다 — 항상 1080p로
# 고정한다(지시 4번, 위 헤더 ③번과 같은 결의 미정 사항). 화면이 해상도 선택
# UI 를 붙이는 날 이 상수 사용처(_resolve_game)만 고치면 된다.

# ── 용도 매핑 — 파서 9종 → grid_cells.usage 6종(비게임) + '게임'(게임 3종 합류) ──
# 비게임 6종은 2026-09-16 실측 SQL 로 확인한 값 그대로다:
#   SELECT DISTINCT usage FROM grid_cells WHERE usage <> '게임'
#   → {'AI 작업','디자인','영상편집','사무·인강','주식·트레이딩','3D 그래픽'}
# 이 6종은 `usage_floors.usage_label`(ai/design/video/office/trading/video_3d)과
# **1:1로 이미 같은 문자열**이다(0090·0092 가 같은 어휘를 썼다) — 그래서 옛 판처럼
# 여러 파서 용도를 하나로 접는 매핑표가 필요 없다. 게임 계열 3종(게임·캐주얼 게임·
# 고사양 게임)만 GAME_USAGE 로 합류시킨다 — 세부(등급·해상도)는 tier_key 가 아니라
# game_grade+game_resolution 이 결정한다(아래 _resolve_game).
USAGE_TO_GRID = {
    "AI 작업": "AI 작업",
    "디자인": "디자인",
    "영상편집": "영상편집",
    "사무·인강": "사무·인강",
    "주식·트레이딩": "주식·트레이딩",
    "3D 그래픽": "3D 그래픽",
    "게임": GAME_USAGE,
    "캐주얼 게임": GAME_USAGE,
    "고사양 게임": GAME_USAGE,
}

# 게임명을 찾을 때 뒤질 라벨과 그 순서 — '게임명' 은 파서가 아직 안 내지만(위 ③)
# 낼 날을 대비해 최우선으로 본다. '요청'은 고객 원문을 그대로 보관하는 자리
# (api/talk.py VERBATIM_LABELS), '선호'는 자유 태그 자리 — 둘 다 games.name 이
# 우연히 들어 있을 수 있는 유일한 통로다(용도 값 자체는 `_norm_usage`가 표준
# 라벨 하나로 접어버려 게임 제목이 못 들어온다, api/talk.py:472-507).
GAME_NAME_LABEL_PRIORITY = ("게임명", "요청", "선호")

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
    l: str | None = None
    v: str | None = None


class RecommendBody(BaseModel):
    constraints: list[Constraint] = []
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


def _find_game_name(conn, constraints: list[Constraint]) -> str | None:
    """'게임명'·'요청'·'선호' 라벨 값 안에서 games.name 부분일치를 찾는다(우선순위
    순서 그대로). 여러 이름이 후보로 걸리면 긴 이름부터 검사해 짧은 이름이 긴
    이름의 부분 문자열로 오매칭되는 위험을 줄인다. 못 찾으면 None — 지어내지 않는다."""
    names = conn.execute(text("SELECT name FROM games")).scalars().all()
    names_sorted = sorted((n for n in names if n), key=len, reverse=True)
    for lab in GAME_NAME_LABEL_PRIORITY:
        for c in constraints:
            if (c.l or "").strip() != lab or not (c.v or "").strip():
                continue
            v = c.v.strip()
            for g in names_sorted:
                if g in v:
                    return g
    return None


def _resolve_game(conn, constraints: list[Constraint]) -> dict:
    """게임 용도일 때 game_grade·game_resolution·game_name 판정.

    반환 {grade, resolution, game_name, needs[], note}.
    해상도는 DEFAULT_GAME_RESOLUTION 고정(위 헤더·상수 주석 참고 — 파서 미지원).
    """
    resolution = DEFAULT_GAME_RESOLUTION
    name = _find_game_name(conn, constraints)
    if name is None:
        return {"grade": None, "resolution": resolution, "game_name": None,
                "needs": ["게임명"],
                "note": "게임 용도인데 게임명을 알 수 없어 등급을 정할 수 없습니다"
                        "('요청'·'선호' 값에서 게임명을 찾지 못했습니다 — 파서가"
                        " 아직 게임명을 전용 라벨로 넘기지 않습니다)"}
    row = conn.execute(text(
        "SELECT grade FROM game_grade_assignments a"
        " JOIN games g ON g.game_id = a.game_id WHERE g.name = :n"),
        {"n": name}).mappings().first()
    grade = row["grade"] if row else None
    if grade is None:
        # 게임은 특정됐지만 등급이 없다(예: GTA — 재고값 없음+버전 특정 불가로
        # 미배정, 0091 마이그레이션 주석 그대로). 이미 이름을 아니 '게임명'을
        # 다시 물어도 소용없다 — needs 를 채우지 않고 사실만 note 로 남긴다.
        return {"grade": None, "resolution": resolution, "game_name": name,
                "needs": [],
                "note": f"게임 '{name}'은(는) 아직 부하 등급이 확정되지 않아"
                        " 카드를 만들 수 없습니다"}
    return {"grade": grade, "resolution": resolution, "game_name": name,
            "needs": [], "note": None}


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


# ── 본체 ────────────────────────────────────────────────────────────────
@router.post("/recommend")
def recommend(body: RecommendBody):
    """constraints → 격자 카드. 400 을 내지 않는다 — 부족한 것은 `needs` 로
    말하고 카드 0장(화면/LLM 이 되묻는다).

    응답 {ok, cards[], center_tier, center_tier_key, tiers_considered[],
          usage_grid, usage_kind, game_grade, game_resolution, game_name,
          platform, budget_won, budget_bound, needs[], note, empty_cells[]}

      cards[].quotes = {value, reco, perf} — 칸 하나의 3종 구성(지시 6번 핵심
      변화). 각 안에 {quote_id, total, over_budget, status, parts, reasons,
      omitted, generated_at}. 카드 최상위에도 대표(추천) variant 값을 그대로
      얹는다(하위호환) — 화면 제작자가 quotes.reco 대신 top-level 필드를 계속
      써도 동작한다.
      kind: "nongame"(tier_key 축) | "game"(game_grade+game_resolution 축).
      empty_cells  고려한 칸 중 카드가 안 나온 것의 사유 — intended_empty 면 그
                   사실, 현재본 견적이 없으면 '현재본 없음'.
    """
    cons = body.constraints or []
    budget_won, bound = parse_budget(_pick(cons, "예산"))
    usage_grid, usage_raw = _usage_grid_of(cons)
    platform = _platform_of(cons)

    needs: list[str] = []
    notes: list[str] = []
    if usage_grid is None:
        needs.append("용도")
        if usage_raw:
            notes.append(f"용도 '{usage_raw}' 는 격자 용도로 대응되지 않음")
    if budget_won is None:
        # T1(팝콘2) — 사장님 미정 시 가정값(위 헤더 ① 참고, 보고서에 명시).
        notes.append("예산 없음 — T1(팝콘2) 중심")

    cards: list[dict] = []
    empty_cells: list[dict] = []
    center_tier_name = None
    center_tier_key = None
    tiers_considered_keys: list[str] = []
    game_grade = game_resolution = game_name = None

    with engine.connect() as conn:
        if usage_grid == GAME_USAGE:
            g = _resolve_game(conn, cons)
            game_grade, game_resolution, game_name = g["grade"], g["resolution"], g["game_name"]
            needs.extend(g["needs"])
            if g["note"]:
                notes.append(g["note"])
            if game_grade is not None:
                cards, empty_cells = _build_game_cards(
                    conn, game_grade, game_resolution, game_name, platform, budget_won, bound)
        elif usage_grid is not None:
            tiers = _load_tiers(conn, usage_grid, platform)
            ci = tier_index_for(tiers, budget_won, bound)
            considered = tiers[ci: ci + 1 + TIERS_UP]
            center_tier_name = tiers[ci]["name"]
            center_tier_key = tiers[ci]["tier_key"]
            tiers_considered_keys = [t["tier_key"] for t in considered]
            cards, empty_cells = _build_nongame_cards(
                conn, considered, usage_grid, platform, budget_won, bound)
        else:
            # 용도 미정 — 카드는 안 만들지만(아래 needs=["용도"]) 참고용 중심
            # 티어는 계산해 보고한다. usage 를 모르니 관측 가격도 없다 —
            # tier_index_for 는 비교 재료가 없어 DEFAULT_TIER_KEY 로 떨어진다.
            tiers = _load_tiers(conn, None, platform)
            ci = tier_index_for(tiers, budget_won, bound)
            considered = tiers[ci: ci + 1 + TIERS_UP]
            center_tier_name = tiers[ci]["name"]
            center_tier_key = tiers[ci]["tier_key"]
            tiers_considered_keys = [t["tier_key"] for t in considered]

    if usage_grid is not None and usage_grid != GAME_USAGE and not cards:
        notes.append("고려한 티어에 카드 없음")
    if usage_grid == GAME_USAGE and game_grade is not None and not cards:
        notes.append("해당 등급·해상도 칸에 카드 없음")

    return {
        "ok": True,
        "cards": cards,
        "center_tier": center_tier_name,
        "center_tier_key": center_tier_key,
        "tiers_considered": tiers_considered_keys,
        "usage_grid": usage_grid,
        "usage_kind": ("game" if usage_grid == GAME_USAGE
                       else ("nongame" if usage_grid else None)),
        "game_grade": game_grade,
        "game_resolution": game_resolution,
        "game_name": game_name,
        "platform": platform,
        "budget_won": budget_won,
        "budget_bound": bound,
        "needs": needs,
        "note": " · ".join(notes),
        "empty_cells": empty_cells,
    }
