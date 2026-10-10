# -*- coding: utf-8 -*-
"""팝콘톡 문장 해석의 «결정론 보정» — AI 가 낸 state 를 고객 문장 원문으로 한 번 더 바로잡는다.

2026-10-10 상담 품질 점검(customer-screens/상담품질-20261010/결과.md) 높음 4건에서 나왔다.
AI 는 대체로 잘 읽지만, 아래 넷은 같은 실수를 반복했다. 그래서 규칙으로 고정한다.

  ① 「발로 백만원」 -> 예산 1,000만원 (근거 줄에는 「백만원 = 1000000원」이라 적고 값은 10배)
     -> `budget_from_text` 가 문장에서 금액을 직접 읽어 AI 값과 다르면 덮어쓴다.
  ② 「발로」 같은 줄임말 게임을 game.names 에 안 넣음
     -> `games_from_text` 가 문장에서 우리 목록의 게임을 찾아 채운다(부정 표현이 있으면 손대지 않는다).
  ③ 게임 이름 없이 「게임용 250만원」 -> 되묻기만 하고 카드 없음 · 같은 질문 반복
     -> `release_unnamed_game` 이 «예산이 있거나 이미 한 번 물었으면» FHD 기준으로 넘긴다.
  ④ 「노트북 추천해줘」 -> 판다/안 판다 말 없이 상담을 이어 감
     -> `mentions_laptop` + `LAPTOP_NOTICE` 로 한 줄 알린다.

이 모듈은 DB 를 읽지 않는다(순수 함수). 어휘는 호출부가 넘기는 `Vocab` 에서 온다.
라우터가 없으므로 `api/main` 자동 등록에는 잡히지 않는다(잡혀도 무해).
"""
from __future__ import annotations

import re

# ── 게임 줄임말 (코드 쪽 보충) ─────────────────────────────────────────────
# 정본은 `talk_game_aliases` 표(0113)다. 이 표는 그 표에 «없는» 줄임말만 채운다 —
# 표에 같은 별칭이 있으면 표가 이긴다(`talk_schema.load_vocab`). 가리키는 게임이
# `games` 에 실재할 때만 쓴다(없으면 조용히 건너뛴다 — 지어낸 게임을 가리키지 않는다).
# 2026-10-10 지시로 DB 를 바꾸지 않고 코드로 둔다. 운영자가 표에 넣으면 그쪽이 정본이 된다.
EXTRA_GAME_ALIASES: dict[str, str] = {
    "발로": "발로란트",
    "발로란": "발로란트",
    "롤": "리그 오브 레전드",
    "lol": "리그 오브 레전드",
    "리그오브레전드": "리그 오브 레전드",
    "배그": "배틀그라운드",
    "배틀그라운드": "배틀그라운드",
    "펍지": "배틀그라운드",
    "pubg": "배틀그라운드",
    "옵치": "오버워치2",
    "오버워치": "오버워치2",
    "로아": "로스트아크",
    "던파": "던전앤파이터",
    "메이플": "메이플스토리",
    "서든": "서든어택",
    "피파": "FC온라인",
    "피파온라인": "FC온라인",
    "fc": "FC온라인",
    "디아": "디아블로4",
    "디아4": "디아블로4",
    "마크": "마인크래프트",
    "마겜": "마인크래프트",
    "사펑": "사이버펑크2077",
    "몬헌": "몬스터헌터 와일즈",
    "몬헌와일즈": "몬스터헌터 와일즈",
    "오공": "검은신화 오공",
    "콜옵": "콜 오브 듀티",
    "헬다": "헬다이버즈2",
    "패오엑": "패스 오브 엑자일2",
    "poe": "패스 오브 엑자일2",
    "로블": "로블록스",
}


def merged_game_aliases(db_aliases: dict[str, str], all_game_names, norm) -> dict[str, str]:
    """DB 별칭 + 코드 보충 별칭. DB 키가 이긴다. 대상 게임이 없으면 넣지 않는다."""
    names = set(all_game_names or [])
    out = dict(db_aliases or {})
    for alias, name in EXTRA_GAME_ALIASES.items():
        key = norm(alias)
        if key and key not in out and name in names:
            out[key] = name
    return out


# ── ① 예산 ───────────────────────────────────────────────────────────────
_HAN_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_HAN_UNIT = {"십": 10, "백": 100, "천": 1000}
_NUM_CHARS = "0-9일이삼사오육칠팔구십백천"

# 「150만원」「백만원」「2백만」「천오백만」「150마넌」「1,500만」 — 숫자 덩어리 + 만
# 아라비아 숫자로 시작하면 앞 글자를 가리지 않는다(「롤150만원」). 한글 숫자로 시작하면 앞이
# 한글이 아니어야 한다(「예산이백만원」의 조사 「이」를 숫자로 읽지 않게 — 그 경우는 AI 에 맡긴다).
_MAN = re.compile(r"(?:(?<![0-9,.])([0-9][0-9,]*(?:\.[0-9]+)?[" + _NUM_CHARS + r"]*)"
                  r"|(?<![가-힣A-Za-z])([" + _NUM_CHARS + r"]+))\s*(?:만|마넌)")
# 「1억」「1억5천」 — 억 단위(뒤의 천만 단위는 «만» 없이 쓰기도 한다)
_EOK = re.compile(r"(?<![가-힣A-Za-z0-9])([0-9]+|[일이삼사오육칠팔구]?)\s*억\s*([" + _NUM_CHARS + r"]*)\s*(만)?")
# 「1500000원」 — 원 단위로 바로 쓴 금액(다섯 자리 이상만 — 「5070원」 같은 오독을 막는다)
_WON = re.compile(r"(?<![0-9,])([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,})\s*원")
# 「백오십」「이백」「천오백」 — «만»을 생략한 한글 금액. 백/천이 들어간 2자 이상 낱말만.
_BARE_HAN = re.compile(
    r"(?<![가-힣])([일이삼사오육칠팔구]?[백천](?:[일이삼사오육칠팔구]?[백십])*[일이삼사오육칠팔구]?)"
    r"(?=$|\s|[.,!?]|으로|로|에|정도|쯤|짜리|이요|요|까지|이하|이내|선|대)")


def _han_number(s: str) -> int | None:
    """「백오십」->150 · 「천오백」->1500 · 「2백50」->250 · 「150」->150. 못 읽으면 None."""
    s = s.replace(",", "")
    if not s:
        return None
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", s):
        v = float(s)
        return int(v) if v == int(v) else None
    total, cur = 0, None
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            if cur is not None:
                return None
            cur = int(s[i:j])
            i = j
            continue
        if ch in _HAN_DIGIT:
            if cur is not None:
                return None
            cur = _HAN_DIGIT[ch]
        elif ch in _HAN_UNIT:
            total += (1 if cur is None else cur) * _HAN_UNIT[ch]
            cur = None
        else:
            return None
        i += 1
    if cur is not None:
        total += cur
    return total or None


def budget_from_text(text: str) -> int | None:
    """문장에 적힌 예산(원). 금액이 없거나 서로 다른 금액이 둘 이상이면 None(AI 판단에 맡긴다).

    「100-150만원」처럼 범위면 뒤 숫자만 «만»에 붙으므로 그 값 하나가 나온다(옛 동작과 같다).
    음수(「-500만원」)는 읽지 않는다 — 부호 처리는 기존 검증층 몫이다.
    """
    if not text:
        return None
    s = str(text)
    found: list[int] = []
    for m in _EOK.finditer(s):
        head = _han_number(m.group(1)) if m.group(1) else 1
        if head is None:
            continue
        tail = _han_number(m.group(2)) if m.group(2) else 0
        found.append(head * 100_000_000 + (tail or 0) * 10_000)
    rest = _EOK.sub(" ", s)
    for m in _MAN.finditer(rest):
        grp = 1 if m.group(1) else 2
        start = m.start(grp)
        if start > 0 and rest[start - 1] == "-" and (start < 2 or not rest[start - 2].isdigit()):
            continue
        n = _han_number(m.group(grp))
        if n:
            found.append(n * 10_000)
    rest = _MAN.sub(" ", rest)
    for m in _WON.finditer(rest):
        found.append(int(m.group(1).replace(",", "")))
    rest = _WON.sub(" ", rest)
    for m in _BARE_HAN.finditer(rest):
        if len(m.group(1)) < 2:          # 「천」「백」 한 글자는 금액인지 알 수 없다
            continue
        n = _han_number(m.group(1))
        if n:
            found.append(n * 10_000)
    vals = set(found)
    return found[0] if len(vals) == 1 else None


# ── ② 게임 이름 ───────────────────────────────────────────────────────────
# 「배그는 안 하고」처럼 빼는 말이 있으면 문장에서 게임을 줍지 않는다 — AI 가 문맥을 본다.
_NEGATION = re.compile(r"안\s*해|안\s*하|않|말고|빼고|제외|싫|별로")


def games_from_text(text: str, vocab, match_game) -> list[str]:
    """문장에서 우리 목록에 있는 게임(games.name)을 찾는다. 부정 표현이 있으면 빈 목록."""
    if not text or _NEGATION.search(text):
        return []
    out: list[str] = []
    for name in getattr(vocab, "all_game_names", []) or []:
        if name and name in text and name not in out:
            out.append(name)
    for raw in re.split(r"[\s,·?!.~/]+", text.strip()):
        if not raw or re.search(r"[0-9]", raw):
            continue
        # 원문 그대로 먼저 본다 — 「발로」의 「로」를 조사로 떼면 「발」만 남는다.
        bare = re.sub(r"(으로|로|이랑|랑|하고|이요|요|은|는|이|가|을|를|와|과|만|도|용)$", "", raw)
        m = match_game(raw, vocab) or (match_game(bare, vocab) if bare and bare != raw else None)
        if m and m not in out:
            out.append(m)
    return out


# ── ③ 게임 이름 없는 게임 질문 ─────────────────────────────────────────────
UNNAMED_GAME_REPLY = ("게임 이름이 없어서 보통 모니터(FHD) 기준으로 골라 봤어요. "
                      "하시는 게임을 알려 주시면 더 맞춰 드릴게요.")


def unnamed_game(state) -> bool:
    """게임 계열 용도인데 게임 이름이 하나도 없는가."""
    g = getattr(state, "game", None)
    return g is None or not g.names


def release_unnamed_game(missing: list[str], state, prev_state, is_game_usage,
                         missing_game_grade: str) -> bool:
    """게임 이름 없는 게임 질문을 되묻기에서 풀어 줄지.

    푼다: 막는 이유가 게임 등급 «하나뿐»이고, 게임 이름이 없고, 아래 중 하나일 때
      · 예산을 말했다(「게임용 250만원」 — 바로 카드)
      · 이전 턴도 이름 없는 게임 질문이었다(= 이미 한 번 물었다 — 같은 질문을 또 하지 않는다)
    안 푼다: 게임 이름이 «있는데» 등급이 없는 경우(목록 밖 게임 · 확정 전 보류) — 그건 기존대로.
    """
    if missing != [missing_game_grade] or not unnamed_game(state):
        return False
    if state.budget_won:
        return True
    if prev_state is not None and any(is_game_usage(u) for u in (prev_state.usages or [])):
        return unnamed_game(prev_state)
    return False


# ── ④ 노트북 ─────────────────────────────────────────────────────────────
LAPTOP_NOTICE = "노트북은 팔지 않아요. 데스크톱(조립 PC)으로 안내해 드릴게요."
_LAPTOP = re.compile(r"노트북|랩탑|랩톱|laptop|notebook", re.I)
# 「노트북 램」처럼 부품 이야기면 안내하지 않는다.
_LAPTOP_PART = re.compile(r"(노트북|랩탑)\s*(용\s*)?(램|메모리|ssd|SSD|충전기|어댑터|거치대|가방)")


def mentions_laptop(text: str) -> bool:
    return bool(text and _LAPTOP.search(text) and not _LAPTOP_PART.search(text))


def with_laptop_notice(reply: str) -> str:
    """안내 한 줄을 앞에 붙인다. 이미 붙어 있으면 그대로."""
    reply = (reply or "").strip()
    if LAPTOP_NOTICE in reply:
        return reply
    return (LAPTOP_NOTICE + " " + reply).strip()
