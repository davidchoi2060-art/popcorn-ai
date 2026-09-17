"""팝콘톡 「격자 좌표」 계약 — talk.py · grid_public.py · 회귀가 함께 import 하는 단일 원천.

설계: docs/design/talk-grid-guide-redesign-2026-09-16.md (§4 스키마 · §5 검증 · §6 missing ·
§9 프롬프트 [격자] 문단). 배경: docs/design/flow-mvp2-talk-to-grid-2026-09-16.md.

여기 담긴 것 넷 — 어느 것도 다른 파일에 다시 적지 않는다:
  1. pydantic 모델           GameState · TalkState · ParseResult          (§4)
  2. 어휘 로더               load_vocab(conn) -> Vocab                    (§3 「정본은 DB」)
  3. 검증                    validate_state(raw, vocab) -> (TalkState, dropped)   (§5)
                             missing_for(state, vocab) -> list[str]       (§6)
                             is_game_usage(label) -> bool
                             match_game(raw_name, vocab) -> str | None
  4. 프롬프트 [격자] 문단    vocab_prompt_block(vocab) -> str             (§9)

규약
  · 어휘는 코드에 박지 않는다. 티어·등급·확정 게임·용도는 **매 요청** DB 에서 읽는다.
    상수로 둔 것은 스키마 수준 고정값뿐이며 각 상수 위에 그 근거를 적었다.
  · AI 출력을 그대로 믿지 않는다. 어휘 밖 값은 null 로 접고 `dropped` 에 사유와 함께
    돌려준다 — 삼키지 않는다.
  · 등급의 정본은 DB 다. 게임명이 확정 목록에 있으면 AI 가 뭐라 했든 DB 등급으로 덮어쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text

from . import usage_floors as UF   # 용도 어휘의 정본 로더 — 다시 짜지 않는다

# ── 스키마 수준 고정값 (DB 에서 읽지 않는 유일한 어휘) ────────────────────────
# RESOLUTION_VALUES: grid_cells.game_resolution 의 실값 DISTINCT(2026-09-16 실측 —
#   1080p/1440p/4K/NULL). game_grade_resolution_tiers.resolution 도 같은 세 값. 배치
#   (tools/grid_generate.py)가 이 세 해상도로 칸을 만들므로 스키마 수준 고정값이다.
RESOLUTION_VALUES: tuple[str, ...] = ("1080p", "1440p", "4K")
# DEFAULT_RESOLUTION: §6 ③ — AI 가 null 로 두면 서버가 이 값으로 카드를 내고
#   assumed:["resolution=1080p"] 로 표시한다. missing 에는 넣지 않는다.
DEFAULT_RESOLUTION = "1080p"
# PLATFORM_VALUES / PREF_VALUES / EXCLUDE_VALUES: api/talk.py 의 상수를 한 글자씩 옮긴 것
#   (2026-09-16). talk.py 는 이 파일에서 import 하도록 바뀔 예정(다른 제작자 담당).
#   · 플랫폼: grid_cells.platform 실값 DISTINCT = 인텔/AMD. `api/candidates._apply_one`
#     의 PLATFORM_LABELS 분기가 받는 리터럴 둘과 같아야 한다.
#   · 선호: `api/candidates._apply_one` 이 실제로 거르는 태그 둘.
#   · 제외: 후보를 거르는 조건이 아니라 견적에서 뺄 항목 표시 — 소비처는 격자 조회·화면.
PLATFORM_VALUES: tuple[str, ...] = ("인텔", "AMD")
PREF_VALUES: tuple[str, ...] = ("저소음", "화이트")
EXCLUDE_VALUES: tuple[str, ...] = ("모니터 보유", "OS 제외", "본체만")
# BUDGET_BOUND_VALUES: §4 budget_bound 의 두 값. api/talk.py `_BUDGET_BOUND` 정규식과 같다.
BUDGET_BOUND_VALUES: tuple[str, ...] = ("이상", "이하")
# GRADE_SRC_VALUES: §4 game.grade_src.
GRADE_SRC_VALUES: tuple[str, ...] = ("catalog", "ai_estimate")

# missing 좌표 이름 — talk.py · grid_public.py · 화면이 같은 문자열을 본다.
MISSING_USAGES = "usages"
MISSING_GAME_GRADE = "game.grade"

# 게임 계열 용도 판정 술어의 기준 문자열 — usage_floors.usage_label 중
# 게임 / 고사양 게임 / 캐주얼 게임 이 전부 이 글자를 품는다(2026-09-16 실측).
_GAME_USAGE_TOKEN = "게임"


# ── 1. pydantic 모델 (§4) ──────────────────────────────────────────────────
class GameState(BaseModel):
    names: list[str] = []                                   # 고객이 말한 게임명 원문 0~N
    grade: str | None = None                                # game_load_grades.grade
    grade_src: Literal["catalog", "ai_estimate"] | None = None
    resolution: str | None = None                           # RESOLUTION_VALUES | None


class TalkState(BaseModel):
    usages: list[str] = []                                  # usage_floors.usage_label 0~N
    budget_won: int | None = None                           # 원 단위 정수, 0 초과
    budget_bound: str | None = None                         # "이상" | "이하"
    platform: str | None = None                             # PLATFORM_VALUES
    tier_key: str | None = None                             # spec_tiers.tier_key (비게임 힌트)
    game: GameState | None = None                           # 게임 계열 용도일 때만
    exclude: list[str] = []                                 # EXCLUDE_VALUES
    prefs: list[str] = []                                   # PREF_VALUES


class ParseResult(BaseModel):
    """POST /api/talk/parse 가 돌려주는 것(§7 ⑥). talk.py 가 만든다."""
    state: TalkState
    missing: list[str] = []
    dropped: list[dict] = []          # [{field, value, reason}]
    evidence: list[str] = []
    reply: str = ""
    assumed: list[str] = []           # 예: ["resolution=1080p"]
    pc_related: bool | None = None


# ── 1-b. 잡담 흐름 카운터 (2026-09-17 사장님 확정 「폭을 넓힌다」) ──────────────
# ■ 왜 TalkState 가 아닌가 — **별도 축이다**
#   TalkState 는 «격자 좌표» 계약이다(usages · budget_won · game …). 저기 담긴 값은
#   전부 「고객이 어떤 PC 를 원하는가」를 가리키는 좌표이고, 그대로 grid_public 으로
#   넘어가 카드를 고른다. 「잡담을 몇 번 했는가」는 **격자의 좌표가 아니다** — 그 수로는
#   어떤 칸도 가리킬 수 없고, 격자 조회가 읽을 일도 없다. TalkState 에 끼워 넣으면
#   ① validate_state 가 «어휘 밖 값» 판정을 할 수 없는 필드가 하나 섞이고
#   ② /api/grid/recommend 가 받는 state 에도 따라 들어가 두 API 의 계약이 함께 늘고
#   ③ 화면이 state 를 그대로 되돌려 보내는 규약(「화면은 state 를 고치지 않는다」)과
#      충돌한다 — 카운터는 화면이 매 턴 «바뀐 값으로» 갈아 끼워야 하는 값이다.
#   그래서 요청·응답의 **최상위 형제 필드**(`chat_flow`)로 둔다. 좌표와 흐름을 섞지 않는다.
#
# ■ history 문자열로 세지 않는다
#   「직전 답변이 REPLY_NOT_PC 였는가」를 문자열 비교로 판정하는 방식은 표기가 바뀌는
#   날 조용히 빠져나간다(CLAUDE.md §회귀 세트 — 이름·문자열 모양으로 동작을 추정하는
#   검사). 명시적인 **수**로 왕복시키고, 전이는 아래 순수함수 하나가 한다.
#
# ■ 화면이 조작할 수 있다 — 그래도 새 방어를 만들지 않는다
#   카운터를 화면이 들고 있으므로 매 요청 0 으로 보내면 잡담을 무한히 할 수 있다.
#   그것을 막는 것은 **`rate_limit_policies` 의 `visitor.ai` 행**이다(분당 8 · 하루 120,
#   2026-09-17 실측). 잡담 한 번도 LLM 호출 한 번이라 그 한도를 그대로 먹는다 —
#   여기에 서버측 세션 저장소를 새로 만들지 않는다(consult_sessions 를 안 쓰는 규약도 그대로).
#
# 단계 이름 — talk.py · app.js · 회귀가 같은 문자열을 본다.
STAGE_PC = "pc"          # 이번 문장이 PC 관련(또는 첫 문장) — 카운터 0
STAGE_OPEN = "open"      # 잡담 1~3회차 — 자연스럽게 받아준다
STAGE_GUIDE = "guide"    # 잡담 4회차 — 역할을 알리고 방향을 튼다(안내 1회)
STAGE_SILENT = "silent"  # 잡담 5회차부터 — 답변 문장을 내지 않는다
# 사장님 확정 경계(2026-09-17). 「3회 허용 -> 4회 안내 -> 5회부터 침묵」.
SMALLTALK_ALLOW_MAX = 3      # 이 수까지는 그대로 받아준다
SMALLTALK_GUIDE_AT = 4       # 이 수에서 역할 안내 1회
SMALLTALK_SILENT_FROM = 5    # 이 수부터 침묵. 카운터는 여기서 멈춘다(정수 무한 증가 방지)


class ChatFlow(BaseModel):
    """대화 흐름 카운터 — TalkState 와 **형제**이고 부분집합이 아니다(위 근거).

    `smalltalk_turns` 는 «PC 와 무관하다고 판정된 문장이 연속으로 몇 번 나왔는가».
    PC 질문이 오면 0 으로 리셋한다 — 고객이 돌아왔으니 다시 3회 여유를 준다(④⑤).
    """
    smalltalk_turns: int = 0


def stage_for(turns: int) -> str:
    """카운터 -> 단계 이름. 전이와 표시가 같은 경계를 보게 하는 단일 원천."""
    if turns <= 0:
        return STAGE_PC
    if turns <= SMALLTALK_ALLOW_MAX:
        return STAGE_OPEN
    if turns == SMALLTALK_GUIDE_AT:
        return STAGE_GUIDE
    return STAGE_SILENT


def clamp_turns(raw) -> int:
    """화면이 보낸 카운터 -> 0 .. SMALLTALK_SILENT_FROM 의 정수.

    화면 값을 믿지 않는다 — 형식이 틀리거나 범위 밖이면 접는다(음수·문자열·bool·None).
    ⚠ bool 은 int 의 하위형이라 먼저 걸러야 한다(True 가 1 로 새어 들어간다).
    """
    if isinstance(raw, bool) or not isinstance(raw, int):
        try:
            raw = int(str(raw).strip())
        except (TypeError, ValueError):
            return 0
    if raw < 0:
        return 0
    return min(raw, SMALLTALK_SILENT_FROM)


def advance_smalltalk(prev_turns, pc_related: bool | None) -> tuple[int, str]:
    """(직전 카운터, 이번 문장의 pc 판정) -> (새 카운터, 단계).

    **순수함수다** — DB·LLM·시각을 보지 않는다. 회귀가 이 함수만으로 전이 전체를
    검사할 수 있게(= LLM 을 부르지 않고) 이 모양으로 뽑았다.

      pc_related is True  -> (0, "pc")        PC 질문 -> 리셋(⑤). 고객이 돌아왔다.
      pc_related is None  -> (그대로, 단계)   **모름은 잡담이 아니다.** 카운터를 올리지
                                              않는다 — 모르는 것을 잡담으로 단정하면
                                              진짜 고객이 입을 닫는다(모듈 docstring
                                              「pc_related 는 bool 이 아니면 None」과 같은 원칙).
      pc_related is False -> (직전+1, 단계)   1~3 받아줌 · 4 안내 · 5부터 침묵.
                                              SMALLTALK_SILENT_FROM 에서 멈춘다.
    """
    prev = clamp_turns(prev_turns)
    if pc_related is True:
        return 0, STAGE_PC
    if pc_related is None:
        return prev, stage_for(prev)
    nxt = min(prev + 1, SMALLTALK_SILENT_FROM)
    return nxt, stage_for(nxt)


# ── 2. 어휘 로더 (§3 「정본은 DB」) ──────────────────────────────────────────
@dataclass
class Vocab:
    tiers: list[dict] = field(default_factory=list)            # spec_tiers 전행, sort_order 순
    grades: list[dict] = field(default_factory=list)           # game_load_grades 전행, sort_order 순
    confirmed_games: dict[str, str] = field(default_factory=dict)   # name -> grade (grade NOT NULL 만)
    all_game_names: list[str] = field(default_factory=list)    # games.name 전부(등급 미배정 포함)
    usages: list[tuple[str, list[str]]] = field(default_factory=list)   # [(usage_label, match_terms)]
    # 등급 무게 — 확정 게임이 여럿일 때 「가장 무거운 등급」을 고르는 축. 설계서에 없는 규칙이라
    # 아래 _load_grade_weight 에 근거를 적었다. grade -> int (클수록 무겁다).
    grade_weight: dict[str, int] = field(default_factory=dict)
    resolutions: tuple[str, ...] = RESOLUTION_VALUES
    platforms: tuple[str, ...] = PLATFORM_VALUES
    prefs: tuple[str, ...] = PREF_VALUES
    excludes: tuple[str, ...] = EXCLUDE_VALUES

    # 편의 접근자 — 검증이 쓰는 키 집합. 로더가 채운 목록에서 파생(따로 들지 않는다).
    @property
    def tier_keys(self) -> list[str]:
        return [t["tier_key"] for t in self.tiers]

    @property
    def grade_keys(self) -> list[str]:
        return [g["grade"] for g in self.grades]

    @property
    def usage_labels(self) -> list[str]:
        return [u[0] for u in self.usages]


def _load_grade_weight(conn, grades: list[dict]) -> dict[str, int]:
    """등급 -> 무게. game_load_grades.sort_order 는 무게 축이 아니다(L=6 이 가장 가볍다).

    그래서 game_grade_resolution_tiers 의 **1080p(서버 기본 해상도) 행이 요구하는 티어**
    (gpu_tier_key, 있으면 cpu_tier_key_override 중 큰 쪽)의 spec_tiers.sort_order 를 무게로
    쓴다 — 격자가 실제로 배정하는 스펙이 곧 부하다. 동률이면 grade sort_order 가 앞선 쪽.
    표에 없는 등급은 무게 -1 (없다고 죽지 않는다 — 그 등급은 여전히 grade_keys 에 있다).
    """
    tier_order = {r["tier_key"]: r["sort_order"] for r in conn.execute(text(
        "SELECT tier_key, sort_order FROM spec_tiers")).mappings().all()}
    rows = conn.execute(text(
        "SELECT grade, gpu_tier_key, cpu_tier_key_override FROM game_grade_resolution_tiers"
        " WHERE resolution = :res"), {"res": DEFAULT_RESOLUTION}).mappings().all()
    req: dict[str, int] = {}
    for r in rows:
        w = max(tier_order.get(r["gpu_tier_key"], -1),
                tier_order.get(r["cpu_tier_key_override"], -1))
        req[r["grade"]] = max(req.get(r["grade"], -1), w)
    # 동률 깨기: (티어 무게, -sort_order) 를 정수 하나로 접는다 — sort_order 작은 쪽이 크게.
    n = len(grades) + 1
    return {g["grade"]: req.get(g["grade"], -1) * n + (n - g["sort_order"]) for g in grades}


def load_vocab(conn) -> Vocab:
    """매 요청 DB 에서 어휘를 읽는다. `conn` 은 SQLAlchemy Connection(`engine.connect()`).

    용도만은 api/usage_floors.list_usages() 를 부른다 — 그 모듈이 정본이고 자체 캐시
    (관리자가 고치면 reload()) 정책을 갖는다. 여기서 다시 SELECT 하면 두 벌이 된다.
    """
    tiers = [dict(r) for r in conn.execute(text(
        "SELECT tier_key, popcorn_name, label, gpu_vram_min_gb, gpu_watt_min,"
        " cpu_cores_min, ram_min_gb, ssd_min_gb, sort_order, note"
        " FROM spec_tiers ORDER BY sort_order")).mappings().all()]
    grades = [dict(r) for r in conn.execute(text(
        "SELECT grade, label, example_titles, note, sort_order"
        " FROM game_load_grades ORDER BY sort_order")).mappings().all()]
    confirmed = {r["name"]: r["grade"] for r in conn.execute(text(
        "SELECT g.name, a.grade FROM game_grade_assignments a"
        " JOIN games g ON g.game_id = a.game_id"
        " WHERE a.grade IS NOT NULL ORDER BY g.name")).mappings().all()}
    all_names = [n for n in conn.execute(text(
        "SELECT name FROM games ORDER BY name")).scalars().all() if n]
    usages = [(u["label"], list(u["terms"])) for u in UF.list_usages()["usages"]]
    return Vocab(tiers=tiers, grades=grades, confirmed_games=confirmed,
                 all_game_names=all_names, usages=usages,
                 grade_weight=_load_grade_weight(conn, grades))


# ── 3. 검증 (§5) ──────────────────────────────────────────────────────────
def is_game_usage(label: str | None) -> bool:
    """usage_label 이 게임 계열인가(게임 / 고사양 게임 / 캐주얼 게임). 다른 파일이 다시 적지 않는다."""
    return bool(label) and _GAME_USAGE_TOKEN in label


def _norm_name(s: str) -> str:
    """게임명 비교용 정규화 — 공백·구분 기호 제거 + casefold. 값 자체는 바꾸지 않는다."""
    return "".join(ch for ch in s if ch not in " \t·:-_.,()[]'\"").casefold()


def match_game(raw_name: str, vocab: Vocab) -> str | None:
    """고객이 말한 게임명 원문 -> games.name (없으면 None).

    정확 일치 우선, 그다음 정규화 후 포함 관계(양방향, 짧은 쪽이 2자 이상). 예:
    "오버워치" -> "오버워치2", "gta5" -> "GTA", "사이버펑크 2077" -> "사이버펑크2077".
    후보가 여럿이면 긴 이름을 고른다(더 특정한 쪽).
    """
    if not raw_name or not isinstance(raw_name, str):
        return None
    raw = raw_name.strip()
    if raw in vocab.all_game_names:
        return raw
    q = _norm_name(raw)
    if len(q) < 2:
        return None
    hits = []
    for name in vocab.all_game_names:
        n = _norm_name(name)
        if len(n) < 2:
            continue
        if q == n or (q in n) or (n in q):
            hits.append(name)
    return max(hits, key=len) if hits else None


def _drop(dropped: list[dict], field_name: str, value, reason: str) -> None:
    dropped.append({"field": field_name, "value": value, "reason": reason})


def _pick_list(raw, field_name: str, allowed: list | tuple, dropped: list[dict],
               what: str) -> list[str]:
    """배열 필드 — 어휘 안의 값만 남기고(중복 제거·순서 유지) 밖의 값은 dropped."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        _drop(dropped, field_name, raw, f"{what}: 배열이 아님")
        return []
    out: list[str] = []
    for v in raw:
        if not isinstance(v, str) or v.strip() not in allowed:
            _drop(dropped, field_name, v, f"{what} 어휘 밖")
            continue
        v = v.strip()
        if v not in out:
            out.append(v)
    return out


def _pick_one(raw, field_name: str, allowed, dropped: list[dict], what: str) -> str | None:
    """단일 값 필드 — 어휘 안이면 그 값, 아니면 null + dropped."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip() in allowed:
        return raw.strip()
    _drop(dropped, field_name, raw, f"{what} 어휘 밖")
    return None


def _pick_budget(raw, dropped: list[dict]) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        _drop(dropped, "budget_won", raw, "정수가 아님")
        return None
    try:
        n = int(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        _drop(dropped, "budget_won", raw, "정수가 아님")
        return None
    if n <= 0:
        _drop(dropped, "budget_won", raw, "0 초과여야 함")
        return None
    return n


def _heaviest(grades: list[str], vocab: Vocab) -> str:
    return max(grades, key=lambda g: vocab.grade_weight.get(g, -1))


def _validate_game(raw, vocab: Vocab, dropped: list[dict]) -> GameState | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _drop(dropped, "game", raw, "객체가 아님")
        return None
    for k in raw:
        if k not in GameState.model_fields:
            _drop(dropped, f"game.{k}", raw[k], "스키마 밖 필드")

    names_raw = raw.get("names")
    names: list[str] = []
    if names_raw is not None:
        if not isinstance(names_raw, (list, tuple)):
            _drop(dropped, "game.names", names_raw, "배열이 아님")
        else:
            for v in names_raw:
                if not isinstance(v, str) or not v.strip():
                    _drop(dropped, "game.names", v, "빈 값 또는 문자열이 아님")
                    continue
                if v.strip() not in names:
                    names.append(v.strip())

    grade = _pick_one(raw.get("grade"), "game.grade", vocab.grade_keys, dropped,
                      "game_load_grades.grade")
    grade_src = _pick_one(raw.get("grade_src"), "game.grade_src", GRADE_SRC_VALUES, dropped,
                          "grade_src")
    resolution = _pick_one(raw.get("resolution"), "game.resolution", vocab.resolutions,
                           dropped, "해상도")

    # §5 grade_src 행 — 등급의 정본은 DB. names 를 목록과 대조해 세 갈래로 나눈다.
    matched = {n: match_game(n, vocab) for n in names}
    confirmed = [vocab.confirmed_games[m] for m in matched.values()
                 if m and m in vocab.confirmed_games]
    listed_unconfirmed = [m for m in matched.values() if m and m not in vocab.confirmed_games]
    unlisted = [n for n, m in matched.items() if not m]

    if confirmed:
        db_grade = _heaviest(confirmed, vocab)
        if grade is not None and grade != db_grade:
            _drop(dropped, "game.grade", grade,
                  f"확정 목록 등급({db_grade})으로 덮어씀 — AI 추정은 목록 밖 게임에만 허용")
        if grade_src is not None and grade_src != "catalog":
            _drop(dropped, "game.grade_src", grade_src, "확정 목록에 있는 게임 — catalog 로 덮어씀")
        grade, grade_src = db_grade, "catalog"
    elif listed_unconfirmed and not unlisted:
        # 목록에는 있으나 game_grade_assignments 에 등급이 없다(GTA 같은 경우) — 추정 불허.
        if grade is not None:
            _drop(dropped, "game.grade", grade,
                  f"등급 미확정 — {', '.join(listed_unconfirmed)} 은(는) 목록에 있으나 등급이 아직 없음")
        if grade_src is not None:
            _drop(dropped, "game.grade_src", grade_src, "등급 미확정")
        grade, grade_src = None, None
    elif grade is not None:
        # 목록 밖 게임(또는 게임명 없이 "대작 다") — AI 추정을 인정한다(§6 ②).
        #
        # ⚠ G-5 (2026-09-16 사장님 확정): **grade_src 를 명시하지 않으면 승격하지 않는다.**
        #   `/api/grid/recommend` 는 공개 경로라, 예전엔 누구나 `game.grade` 만 실어 보내면
        #   서버가 ai_estimate 로 얹어 `talk_game_estimates` 에 행을 남겼다 — 게임명이 빈
        #   행이 무한히 쌓이는 길이었다(확인자 검증만으로 12행 적재). 추정을 «주장한 쪽»이
        #   grade_src 로 밝히게 하고, 안 밝히면 카드만 내고 원장에는 남기지 않는다.
        #   talk.py 경로는 프롬프트가 grade_src 를 내게 하므로 영향이 없다.
        if grade_src == "catalog":
            _drop(dropped, "game.grade_src", grade_src, "목록에 없는 게임 — catalog 로 볼 수 없음")
            grade_src = None
        elif grade_src is None:
            _drop(dropped, "game.grade_src", None,
                  "추정 등급인데 grade_src 가 없음 — 카드는 내되 추정으로 기록하지 않음")
    else:
        if grade_src is not None:
            _drop(dropped, "game.grade_src", grade_src, "grade 가 없는데 grade_src 만 있음")
        grade_src = None

    return GameState(names=names, grade=grade, grade_src=grade_src, resolution=resolution)


def validate_state(raw: dict, vocab: Vocab) -> tuple[TalkState, list[dict]]:
    """AI 가 낸 state(dict) -> (정규화된 TalkState, dropped[{field, value, reason}]).

    §5 표 그대로. 어휘 밖 값은 null(배열은 제외)로 접고 dropped 에 남긴다 — 삼키지 않는다.
    """
    dropped: list[dict] = []
    if not isinstance(raw, dict):
        _drop(dropped, "state", raw, "객체가 아님")
        return TalkState(), dropped
    for k in raw:
        if k not in TalkState.model_fields:
            _drop(dropped, k, raw[k], "스키마 밖 필드")

    usages = _pick_list(raw.get("usages"), "usages", vocab.usage_labels, dropped,
                        "usage_floors.usage_label")
    budget_won = _pick_budget(raw.get("budget_won"), dropped)
    budget_bound = _pick_one(raw.get("budget_bound"), "budget_bound", BUDGET_BOUND_VALUES,
                             dropped, "예산 경계")
    platform = _pick_one(raw.get("platform"), "platform", vocab.platforms, dropped, "플랫폼")
    tier_key = _pick_one(raw.get("tier_key"), "tier_key", vocab.tier_keys, dropped,
                         "spec_tiers.tier_key")
    game = _validate_game(raw.get("game"), vocab, dropped)
    exclude = _pick_list(raw.get("exclude"), "exclude", vocab.excludes, dropped, "제외")
    prefs = _pick_list(raw.get("prefs"), "prefs", vocab.prefs, dropped, "선호")

    state = TalkState(usages=usages, budget_won=budget_won, budget_bound=budget_bound,
                      platform=platform, tier_key=tier_key, game=game,
                      exclude=exclude, prefs=prefs)
    return state, dropped


def missing_for(state: TalkState, vocab: Vocab) -> list[str]:
    """카드를 내기 위해 아직 비어 있는 좌표(§6). 해상도는 넣지 않는다 — 서버가 1080p 를 가정한다."""
    if not state.usages:
        return [MISSING_USAGES]
    out: list[str] = []
    if any(is_game_usage(u) for u in state.usages):
        if state.game is None or state.game.grade is None:
            out.append(MISSING_GAME_GRADE)
    return out


# ── 4. 프롬프트 [격자] 문단 (§9) ──────────────────────────────────────────
def _tier_line(t: dict) -> str:
    if t.get("gpu_vram_min_gb") is None and t.get("gpu_watt_min") is None:
        gpu = "GPU 하한 없음(내장그래픽)"
    else:
        gpu = f"GPU VRAM {t['gpu_vram_min_gb']}GB 이상·파워 {t['gpu_watt_min']}W 이상"
    return (f"- {t['popcorn_name']}({t['tier_key']}) {t['label']}: {gpu} · "
            f"CPU {t['cpu_cores_min']}코어 이상 · RAM {t['ram_min_gb']}GB 이상 · "
            f"SSD {t['ssd_min_gb']}GB 이상")


def vocab_prompt_block(vocab: Vocab) -> str:
    """§9 의 [격자] 네 문단 — 티어 · 등급+example_titles · 확정 게임 목록 · 용도.

    talk.py 가 프롬프트에 그대로 끼워 넣는다. 어휘는 전부 vocab(DB) 에서 온다.
    """
    lines: list[str] = []
    lines.append("[격자 — 성능 티어]  tier_key 는 다음 중 하나만 쓴다(비게임 용도의 힌트)")
    lines.extend(_tier_line(t) for t in vocab.tiers)
    lines.append("")
    lines.append("[격자 — 게임 부하 등급]  grade 는 다음 중 하나만 쓴다")
    for g in vocab.grades:
        ex = g.get("example_titles") or ""
        lines.append(f"- {g['grade']} {g['label']}" + (f" (예: {ex})" if ex else ""))
    lines.append("")
    by_grade: dict[str, list[str]] = {}
    for name, grade in vocab.confirmed_games.items():
        by_grade.setdefault(grade, []).append(name)
    order = {g["grade"]: g["sort_order"] for g in vocab.grades}
    pairs = []
    for grade in sorted(by_grade, key=lambda g: order.get(g, 999)):
        pairs.extend(f"{n}={grade}" for n in sorted(by_grade[grade]))
    lines.append(f"[우리가 등급을 확정한 게임]  ({len(pairs)}종)")
    lines.append(", ".join(pairs))
    unconfirmed = sorted(n for n in vocab.all_game_names if n not in vocab.confirmed_games)
    if unconfirmed:
        lines.append(f"목록에 있으나 등급 미확정: {', '.join(unconfirmed)}"
                     " — 이 게임은 등급을 추정하지 말고 grade=null 로 둔다.")
    lines.append('위 목록의 게임이면 그 등급을 쓰고 grade_src="catalog". 목록에 없는 게임은'
                 ' 위 등급 설명으로 추정하고 grade_src="ai_estimate" 로 표시한다.')
    lines.append("")
    lines.append("[용도]  usages 는 다음 라벨만 쓴다(괄호는 고객이 흔히 쓰는 말)")
    for label, terms in vocab.usages:
        extra = [t for t in terms if t != label]
        lines.append(f"- {label}" + (f" ({' / '.join(extra)})" if extra else ""))
    return "\n".join(lines)
