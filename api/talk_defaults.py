# -*- coding: utf-8 -*-
"""답 먼저, 되묻기는 끝에 한 번 -- 상담 답의 «기본 가정» 사전(2026-10-11 사장님 비교 지적).

■ 왜
  「개발자용 PC를 가장 저렴하게 추천해줘」에 일반 AI 는 바로 구성을 내놓는데, 우리 상담은 첫 턴에
  예산을 묻고 둘째 턴(「웹 개발, 예산은 최대한 싸게」)에도 「찾아드리겠습니다」만 했다. 카드는 두 턴
  모두 나왔지만 말이 카드를 따라가지 못했다. 그래서 다음을 서버가 정한다.
    1. 합리적으로 가정할 수 있으면 묻지 않는다 -- 무엇을 가정했는지 한 줄로 밝히고 카드를 낸다.
    2. 「최대한 싸게 / 제일 좋은 걸로 / 적당히 / 상관없어」는 예산 질문을 건너뛴다(가장 싼 쪽 / 높은
       사양 쪽 / 가격대를 넓게).
    3. 카드를 막는 되묻기는 연속 두 번 하지 않는다 -- 앞 턴에 물었으면 이번 턴은 가정을 밝히고 답한다.
    4. 용도별 문구는 이 파일 한곳에 둔다(문구만 바꾸려면 USAGE_AFTER · PREF_LINE 을 고친다).

■ 지어내지 않는 것
  · 「무엇을 기준으로 골랐나」는 추천이 실제로 쓰는 기준표(product_fit_levels 의 1단계 작업 설명)를
    그대로 읽는다. 표를 못 읽으면 기준 문장을 빼고 말한다(만들어 넣지 않는다).
  · 끝 문장은 질문이 아니라 «이런 작업이면 구성이 달라진다»는 안내다. 카드 뒤에 추천이 이미
    「아래에서 골라 주세요」를 묻기 때문에, 질문은 그 하나로 끝난다.
"""
import logging
import re

from sqlalchemy import text

from . import reco_explore as X
from .db import engine

log = logging.getLogger("talk_defaults")

PREF_CHEAPEST, PREF_TOP, PREF_WIDE = "cheapest", "top", "wide"

# 「적당히 · 상관없어」 -- 가격 방향이 없다는 말. 싸게·좋게는 추천 쪽(reco_explore)과 같은 규칙을 쓴다
# (같은 말을 두 곳에서 다르게 읽으면 답 문장과 카드가 갈린다).
_WIDE = re.compile(r"적당(히|한|하게)|무난(한|하게)|중간|상관\s*(없|x)|아무거나|알아서|대충")

# 예산을 되묻는 AI 문장(「예산은 어느 정도 생각하세요?」 · 「예산을 알려 주세요」).
_ASKS_BUDGET = re.compile(r"예산.{0,20}(\?|알려|말씀|생각하세요|생각하시|정해|어느\s*정도|얼마)")

# 예산이 없을 때 가격을 어떻게 잡았나.
PREF_LINE = {
    PREF_CHEAPEST: "예산은 말씀대로 가장 싼 쪽으로 봤어요.",
    PREF_TOP: "예산은 말씀대로 높은 사양 쪽으로 봤어요.",
    PREF_WIDE: "예산을 정하지 않으셔서 가격대를 넓게 봤어요.",
}

# 용도(추천 기준표의 용도 이름) -> 끝 안내 한 줄. «이런 작업까지 하면 구성이 달라진다».
# 근거는 같은 기준표의 2단계 이상 조건이다(product_fit_levels) -- 수치를 새로 만들지 않는다.
USAGE_AFTER = {
    "개발": "AI 학습이나 게임 개발까지 하시면 그래픽카드가 필요해 구성이 달라져요.",
    "사무용": "큰 엑셀 파일이나 모니터 두 대를 쓰시면 한 단계 위 구성이 맞아요.",
    "주식·트레이딩": "모니터를 4대 이상 쓰시면 그래픽카드가 필요해 구성이 달라져요.",
    "영상편집": "4K 편집이나 색보정까지 하시면 사양이 달라져요.",
    "디자인·조판": "큰 PSD나 RAW 사진을 많이 다루시면 사양이 달라져요.",
    "3D 렌더링": "실무 장면을 그래픽카드로 렌더하시면 사양이 달라져요.",
    "캐드·설계": "3D 모델링까지 하시면 그래픽카드가 필요해 구성이 달라져요.",
    "음악 작업": "샘플 라이브러리를 많이 쓰시는 큰 작업이면 램이 더 필요해요.",
    "방송·스트리밍": "QHD 게임을 송출하시면 사양이 달라져요.",
    "로컬 AI": "13B 이상 큰 모델을 돌리시면 그래픽 메모리가 더 큰 구성이 필요해요.",
    "게임": "주로 하는 게임을 알려 주시면 그 게임 기준으로 다시 볼 수 있어요.",
}

# 게임은 기준표의 «게임 수준»이 해상도로 정해진다. 해상도를 말하지 않았으면 FHD 로 본다(talk 와 같은 기본).
GAME_BASIS = "게임은 FHD(1080p) 화면 기준"

# 용도를 두 번 물어도 못 들었을 때 -- 일반 용도(사무용)를 가정하고 그 사실을 밝힌다.
DEFAULT_USAGE_FIT = "사무용"
NO_USAGE_LEAD = "하실 일을 아직 몰라서 일반 용도를 가정했어요."
NO_USAGE_AFTER = "하실 일을 알려 주시면 그에 맞춰 다시 볼 수 있어요."


def price_pref(raw: str | None) -> str | None:
    """고객 문장의 가격 방향 -> cheapest | top | wide | None. 숫자 예산이 있으면 None 이다."""
    nav = X.extract(raw).get("nav")
    if nav == X.CHEAPER:
        return PREF_CHEAPEST
    if nav == X.BETTER:
        return PREF_TOP
    s = (raw or "")[:X.MAX_TEXT]
    if _WIDE.search(s) and not re.search(r"\d{2,}", s):
        return PREF_WIDE
    return None


def asks_budget(reply: str | None) -> bool:
    return bool(_ASKS_BUDGET.search(reply or ""))


def _fit_usage(label: str) -> str | None:
    from .sold_reco import fit_usage       # sold_reco 가 DB 적재 모듈을 끌어오므로 쓸 때만 읽는다
    return fit_usage(label)


def basis_work(fit: str, level: str | None = None) -> str | None:
    """추천 기준표에서 그 용도 1단계(level 을 주면 그 단계)의 작업 설명. 못 읽으면 None(문장을 만들지 않는다)."""
    try:
        with engine.connect() as conn:
            if level:
                row = conn.execute(text(
                    "SELECT work FROM product_fit_levels WHERE usage = :u AND level = :l LIMIT 1"),
                    {"u": fit, "l": level}).first()
            else:
                row = conn.execute(text(
                    "SELECT work FROM product_fit_levels WHERE usage = :u ORDER BY level_rank LIMIT 1"),
                    {"u": fit}).first()
    except Exception:  # noqa: BLE001 - 기준 문장 하나 때문에 상담을 막지 않는다
        log.exception("[talk_defaults] fit level unavailable - basis omitted")
        return None
    return row[0] if row and row[0] else None


def _usage_name(label: str) -> str:
    return label[:-1] if label.endswith("용") else label


def answer_first(state, pref: str | None, *, is_game_usage, work_of=None, heavy=None) -> str:
    """카드를 내는 턴의 답 -- 「무엇을 기준으로 봤나」 한 줄 + 예산 가정 + 끝 안내 한 줄.

    heavy = reco_explore.heavy_levels(고객 문장). 고객이 한 단계 위 작업을 말했으면 카드도 그 단계부터 고르므로
    (sold_reco._heavy_rank) 기준 줄도 그 단계로 쓰고, 「…하시면 한 단계 위」 끝 안내는 붙이지 않는다."""
    work_of = work_of or basis_work
    usages = list(getattr(state, "usages", None) or [])
    label = next((u for u in usages if not is_game_usage(u)), None)
    lines: list[str] = []
    after = None
    if label is not None:
        fit = _fit_usage(label)
        level = (heavy or {}).get(fit or "")
        work = (work_of(fit, level) if level else work_of(fit)) if fit else None
        if work:
            lines.append(f"{_usage_name(label)}용은 {work} 기준으로 봤어요.")
        after = None if level else USAGE_AFTER.get(fit or "")
    elif usages:
        g = getattr(state, "game", None)
        if g is None or not g.resolution:
            lines.append(GAME_BASIS + "으로 봤어요.")
        if g is None or not g.names:
            after = USAGE_AFTER["게임"]
    if getattr(state, "budget_won", None) is None:
        lines.append(PREF_LINE.get(pref or PREF_WIDE, PREF_LINE[PREF_WIDE]))
    if after:
        lines.append(after)
    return " ".join(lines)


def default_usage_label(vocab) -> str | None:
    """용도 어휘 중 일반 용도(사무용)로 읽히는 라벨. 없으면 None(가정하지 않는다)."""
    for label, _terms in getattr(vocab, "usages", None) or []:
        if "AI" not in label and _fit_usage(label) == DEFAULT_USAGE_FIT:
            return label
    return None


def no_usage_reply(work: str | None) -> str:
    lead = f"하실 일을 아직 몰라서 {work} 같은 일반 용도를 가정했어요." if work else NO_USAGE_LEAD
    return f"{lead} {NO_USAGE_AFTER}"
