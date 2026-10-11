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


# ①-2 (2026-10-11 품질관리 R8) 「100만원대」 — 그 자릿수 구간 전체로 읽는다.
#   지금까지는 「100만」만 읽혀 상한 100만원이 됐다. 「N만원대」는 N 에서 시작하는 그 자릿수
#   구간이다(100만원대 = 100~199만원 · 150만원대 = 150~159만원 · 50만원대 = 50~59만원).
#   그래서 «구간의 끝까지(이하)»로 읽고, 그렇게 읽었다고 답에 밝힌다(`budget_band_note`).
_BAND = re.compile(r"(?<![0-9,.])([0-9]{1,4})\s*만\s*원?\s*대(?:(?![가-힣])|(?=[로에의요쯤정면이는도가를]))")


def budget_band_from_text(text: str) -> tuple[int, int] | None:
    """「100만원대」 -> (구간 시작 원, 구간 끝 원) = (1_000_000, 1_990_000). 하나일 때만."""
    if not text:
        return None
    found = {m.group(1) for m in _BAND.finditer(str(text))}
    if len(found) != 1:
        return None
    n = int(found.pop())
    if n <= 0:
        return None
    zeros = len(str(n)) - len(str(n).rstrip("0"))
    width = 10 ** min(zeros, len(str(n)) - 1)
    return n * 10_000, (n + width - 1) * 10_000


def budget_band_note(text: str) -> str | None:
    band = budget_band_from_text(text)
    if not band:
        return None
    lo, hi = band
    return "「%d만원대」는 %d만원부터 %d만원까지로 보고 찾았어요." % (lo // 10_000, lo // 10_000, hi // 10_000)


# ①-3 (2026-10-11 품질관리 R8) 「롤 120」「오버워치 할 컴 120」 — 단위 없는 맨 숫자 예산.
#   문장 끝에(또는 「정도·쯤·선·까지·이하·이내·으로·요」 앞에) 혼자 있는 30~999 를 만원으로
#   읽는다. 그래픽카드 번호(4060)·주사율(144hz)·크기(27인치)·대수(5대)는 단위나 글자가
#   붙거나 범위 밖이라 걸리지 않는다. 금액이 따로 적혀 있으면 이 규칙은 쓰지 않는다.
_BARE_NUM = re.compile(r"(?<![0-9A-Za-z.,\-])([0-9]{2,3})(?=(?:\s*(?:정도|쯤|선|까지|이하|이내|으로|로|이요|요))*\s*[.!?~]*\s*$)")


def bare_budget_from_text(text: str) -> int | None:
    """단위 없는 맨 숫자 예산(만원). 하나뿐이고 30~999 일 때만. 금액 표기가 있으면 None."""
    if not text or budget_from_text(text) is not None:
        return None
    s = str(text).strip()
    nums = [int(m.group(1)) for m in _BARE_NUM.finditer(s)]
    # 「롤 120 배그 150」처럼 맨 숫자가 둘 이상이면 어느 것이 예산인지 알 수 없다 — AI 에 맡긴다.
    if len(re.findall(r"(?<![0-9A-Za-z.,\-])[0-9]{2,3}(?![0-9A-Za-z가-힣])", s)) > 1:
        return None
    if len(nums) != 1 or not 30 <= nums[0] <= 999:
        return None
    return nums[0] * 10_000


# ── ② 게임 이름 ───────────────────────────────────────────────────────────
# 「배그는 안 하고」처럼 빼는 말이 있으면 문장에서 게임을 줍지 않는다 — AI 가 문맥을 본다.
_NEGATION = re.compile(r"안\s*해|안\s*하|않|말고|빼고|제외|싫|별로")


# 게임이 아닌 작업 프로그램 — 영상·사진·3D·설계·문서. 게임 이름 찾기 전에 문장에서 지운다.
SOFTWARE_RE = re.compile(
    r"(?:어도비\s*)?(?:프리미어(?:\s*프로)?|애프터\s*이펙트|포토샵|라이트룸|일러스트레이터|일러스트"
    r"|인디자인|다빈치(?:\s*리졸브)?|리졸브|파이널\s*컷(?:\s*프로)?|베가스(?:\s*프로)?|캡컷|블렌더"
    r"|시네마\s*4d|3ds\s*맥스|스케치업|오토\s*캐드|캐드|솔리드\s*웍스|레빗|라이노|줌|엑셀|파워\s*포인트)",
    re.IGNORECASE)


def games_from_text(text: str, vocab, match_game) -> list[str]:
    """문장에서 우리 목록에 있는 게임(games.name)을 찾는다. 부정 표현이 있으면 빈 목록."""
    if not text or _NEGATION.search(text):
        return []
    # 작업 프로그램 이름은 게임 이름 찾기에서 뺀다 — 「프리미어 프로」의 「프로」가
    # 「프로젝트 좀보이드」에 부분 일치해 없는 게임을 지어냈다(2026-10-11 고객3 3번).
    text = SOFTWARE_RE.sub(" ", text)
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
UNNAMED_GAME_REPLY = ("즐겨 하시는 게임을 알려 주시면 "
                      "용도와 예산에 맞춰 안내하겠습니다.")


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
LAPTOP_NOTICE = "노트북은 판매하지 않습니다. 조립 PC를 안내해 드릴게요."
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


# ── ⑤ 근거 없는 약속 막기 (2026-10-11 품질관리 고객 역할 3곳 공통) ─────────────
# AI 의 reply 가 「네, 윈도우를 깔아서 배송해드립니다」「모니터 포함 가능」「5대 주문
# 확인했습니다」「결제 담당팀에 확인해 드릴게요」「램 64GB로 맞춰드리겠습니다」처럼
# **우리가 하지 않는 일, 추천이 반영하지 않는 조건**을 약속했다(품질관리-20261011
# 고객1·2·3 결과.md). 카드 자료는 운영체제·주변기기·보증을 「구매 전 확인」으로 정직하게
# 말하는데 말풍선만 어긋났다.
#
# 그래서 이 주제가 문장에 있으면 **서버가 안내 문장으로 말풍선을 바꾼다**(노트북 안내와
# 같은 방식). 판정은 고객 문장 원문(정규식)과 검증된 state 만 본다 — AI 출력은 보지 않는다.
#
# 안내 문장의 정본은 관리자 「판매 안내 자료」(표 `shop_notices`, `api/shop_notices.py`)다.
# 관리자가 그 주제를 적고 «사용»으로 두면 그 문장이 나가고, 아니면 아래 기본 안내가 나간다.
# 기본 안내는 «사실»만 말한다: 이 화면은 주문·결제를 받지 않는다 · 추천은 한 대 · 본체 가격
# 기준이다 · 상품마다 다른 것은 상품 페이지에서 확인한다. 연락처·일정을 지어내지 않는다.

# (주제 키, 관리자 화면 이름, 고객 문장 판정, 기본 안내)
PURCHASE_TOPICS: tuple[tuple[str, str, re.Pattern, str], ...] = (
    ("os", "운영체제(윈도우) 설치", re.compile(r"윈도우?|운영\s*체제|\bos\b|윈\s*1[01]", re.I),
     "윈도우(운영체제) 설치 여부는 상품마다 달라 지금 자료로는 확인되지 않았어요."
     " 구매 전에 팝콘PC 쇼핑몰 상품 페이지에서 확인해 주세요."),
    ("peripheral", "모니터·주변기기 포함", re.compile(
        r"(모니터|키보드|마우스|웹캠|캠|스피커|헤드셋)\S{0,3}\s*(도|랑|이랑|까지)?\s*"
        r"(같이|함께|포함|딸려|따로|사야|구성품|오나요|와요|주나요|오는|사면)"),
     "추천 가격은 본체 기준이에요. 모니터·키보드·마우스 같은 주변기기는 포함되지 않거나"
     " 상품마다 달라요. 모니터 값을 뺀 본체 예산을 알려 주시면 그 금액으로 다시 찾아 드릴게요."),
    ("quantity", "여러 대 구매", re.compile(
        r"(?<!모니터)(?<!모니터 )(?<![0-9])([2-9]|[1-9][0-9]{1,2}|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*대"
        r"(?!\s*(연결|까지 연결|를 연결|모니터))"),
     "추천과 가격은 한 대 기준이에요. 여러 대 구매와 수량 할인은 팝콘PC 쇼핑몰에서 주문할 때 확인해 주세요."),
    ("payment", "주문·결제·영수증·세금계산서", re.compile(r"결제|법인\s*카드|영수증|세금\s*계산서|계산서|할부|주문|구매\s*(하|할|방법)|사려면|입금"),
     "이 상담 화면에서는 주문과 결제를 받지 않아요. 마음에 드는 PC를 보관하면 팝콘PC 쇼핑몰"
     " 상품 페이지로 이어서 주문할 수 있어요. 결제·영수증·세금계산서는 쇼핑몰에서 진행돼요."),
    ("discount", "할인", re.compile(r"할인|에누리|네고|깎아"),
     "할인과 가격 조정은 이 상담에서 정할 수 없어요. 쇼핑몰 가격을 기준으로 확인해 주세요."),
    ("warranty", "A/S·보증", re.compile(r"a\s*/?\s*s|에이에스|보증|무상\s*수리|수리\s*(기간|받|해)", re.I),
     "보증 기간과 A/S 조건은 상품마다 달라 지금 자료로는 확인되지 않았어요."
     " 구매 전에 팝콘PC 쇼핑몰 상품 페이지에서 확인해 주세요."),
    ("delivery", "배송·설치", re.compile(r"배송|택배|출고|언제\s*(와|받|도착)|방문\s*설치|설치\s*기사|설치(도|까지)?\s*해\s*주"),
     "배송과 설치 안내는 팝콘PC 쇼핑몰에서 해요. 구매 전에 쇼핑몰 상품 페이지에서 확인해 주세요."),
)

# talk_intent_hits.matched_terms 에 남기는 꼬리표 머리 — 관리자 화면이 이 머리로 알아본다.
TOPIC_TAG = "주제:"
UNAPPLIED_TAG = "미반영:"


def topic_label(key: str) -> str | None:
    return next((label for k, label, _p, _d in PURCHASE_TOPICS if k == key), None)


# 고객이 말한 부품·외형 조건. 2026-10-11(상담 주고받기)부터 램·저장공간·그래픽카드 모델·
# 흰색 케이스·저소음은 추천(api/reco_explore)이 판매 PC 를 실제로 거르고, 못 거르면 카드와 함께
# 「못 맞춥니다」라고 말한다. CPU 와 모델 없는 그래픽카드(「지포스」)는 여전히 쓰지 않는다.
_RAM = re.compile(r"(?:램|메모리|ram)\s*(\d{1,3})\s*(?:gb|기가|g)(?![a-z])|(\d{1,3})\s*(?:gb|기가|g)\s*(?:램|메모리|ram)", re.I)
_STORAGE = re.compile(r"(\d{1,2})\s*(?:tb|테라)|(?:ssd|저장\s*공간|하드)\s*(\d{3,4})\s*(?:gb|기가)", re.I)
_GPU = re.compile(r"\b(rtx|gtx|rx)\s*-?\s*(\d{3,4})\s*(ti|super|xt)?(?![0-9a-z])|지포스|라데온", re.I)
_CPU = re.compile(r"\b(i[3579])\s*-?\s*\d{0,5}|\b라이젠\s*\d|\bryzen\s*\d", re.I)
PREF_LABEL = {"화이트": "흰색 케이스", "저소음": "조용한 PC(저소음)"}
# 2026-10-11 품질관리 M6: 「4K 편집」「최고사양」은 추천이 거르지 않는데 AI 가 「맞춰 드릴게요」라
# 답했다. 4K 는 게임 칸(state.game.resolution)에서만 추천에 쓰인다 — 비게임 tier_key 힌트는
# 0105 로 축에서 사라졌다(api/grid_public). 「최고사양」은 어느 축에도 없다.
_UHD = re.compile(r"(?<![0-9])4\s*k(?![a-z])|uhd|2160\s*p|4\s*케이", re.I)
_TOP = re.compile(r"최고\s*(사양|옵션?|성능|급)|최상\s*(급|사양)|풀\s*옵|끝판|하이\s*엔드", re.I)


def purchase_topics(text: str) -> list[str]:
    """문장에 들어 있는 구매·사후 주제 키 — 순서는 PURCHASE_TOPICS 순서."""
    t = text or ""
    return [key for key, _label, pat, _ in PURCHASE_TOPICS if pat.search(t)]


# 추천이 거르는 조건의 이름표 머리(unsupported_conditions 가 만드는 문자열과 같은 틀).
_APPLIED_HEADS = ("메모리 ", "저장공간 ", "흰색 케이스", "조용한 PC")


def _applied_by_recommend(cond: str) -> bool:
    if cond.startswith(_APPLIED_HEADS):
        return True
    return bool(re.match(r"그래픽카드 (RTX|GTX|RX) \d{4}", cond))


def requested_conditions(text: str, state, prev_state=None) -> tuple[list[str], list[str]]:
    """고객이 말한 조건 -> (추천이 거르는 것, 추천이 쓰지 않는 것)."""
    conds = unsupported_conditions(text, state, prev_state, _all=True)
    return ([c for c in conds if _applied_by_recommend(c)],
            [c for c in conds if not _applied_by_recommend(c)])


def unsupported_conditions(text: str, state, prev_state=None, _all: bool = False) -> list[str]:
    """추천이 반영하지 않는 조건 — 고객 문장과 검증된 state 에서만 읽는다.
    (_all=True 면 추천이 거르는 조건까지 모두 — requested_conditions 가 나눈다.)

    state.prefs 는 누적이라, 이전 턴에 이미 있던 선호는 다시 말하지 않는다(매 턴 같은
    안내가 되풀이되면 AI 답이 영영 안 보인다).
    """
    t = text or ""
    out = []
    m = _GPU.search(t)
    if m:
        out.append("그래픽카드 " + (" ".join(x for x in m.groups() if x).upper() if m.group(1) else m.group(0)))
    m = _CPU.search(t)
    if m:
        out.append("CPU " + m.group(0).strip())
    m = _RAM.search(t)
    if m:
        out.append("메모리 %sGB" % (m.group(1) or m.group(2)))
    m = _STORAGE.search(t)
    if m:
        out.append("저장공간 " + ("%sTB" % m.group(1) if m.group(1) else "%sGB" % m.group(2)))
    g = getattr(state, "game", None)
    # 「4K 모니터」는 모니터 상품 이야기다(모니터 크기 구간이 답한다) — PC 조건으로 세지 않는다.
    if _UHD.search(t) and "모니터" not in t and getattr(g, "resolution", None) != "4K":
        out.append("4K 해상도")
    if _TOP.search(t):
        out.append("최고 사양")
    before = set(getattr(prev_state, "prefs", None) or [])
    for p in (getattr(state, "prefs", None) or []):
        if p in before:
            continue
        label = PREF_LABEL.get(p, p)
        if label not in out:
            out.append(label)
    return out if _all else [c for c in out if not _applied_by_recommend(c)]


def honest_notices(text: str, state, written: dict | None = None, prev_state=None) -> list[str]:
    """말풍선을 바꿀 안내 문장들. 비어 있으면 AI reply 를 그대로 쓴다.

    `written` = 관리자가 적고 «사용»으로 둔 안내 {주제 키: 문장}. 있으면 기본 안내 대신 쓴다.
    """
    written = written or {}
    hit = purchase_topics(text)
    notes = [written.get(key) or msg for key, _label, _pat, msg in PURCHASE_TOPICS if key in hit]
    applied, conds = requested_conditions(text, state, prev_state)
    if applied:
        notes.append("말씀하신 " + " · ".join(applied) + " 조건으로 판매 중인 PC를 골라 볼게요."
                     " 맞추지 못하는 조건은 추천 카드와 함께 알려 드려요.")
    if conds:
        notes.append("말씀하신 " + " · ".join(conds) + " 조건은 아직 추천에 반영하지 못해요."
                     " 추천 카드는 용도와 예산 기준이니, 카드의 사양에서 직접 확인해 주세요.")
    return notes


def honest_reply(notes: list[str], has_usage: bool, missing: list[str]) -> str:
    """고정 안내 + (카드를 못 내는 턴이면) 다음에 알려 줄 것 한 줄."""
    out = " ".join(notes)
    if missing:
        out += (" 용도와 예산을 알려 주시면 맞는 PC를 찾아 드릴게요." if not has_usage
                else " 예산이나 게임 같은 조건을 조금 더 알려 주시면 카드로 보여 드릴게요.")
    return out.strip()


# ── ⑥ 약속하는 말 표시 (2026-10-11 관리자 AI 답 점검 · R2) ─────────────────────────
# 관리자 「AI 답 점검」 화면이 문의마다 붙이는 자동 표시. 판정은 «AI 가 낸 말»(서버가 바꾸기
# 전 reply 와 답변 [B])만 본다 — 고객 문장은 보지 않는다. 표시는 점검 대상을 고르는 단서이지
# 결함 판정이 아니다(「포함」은 「본체만 포함」일 수도 있다). 최종 판정은 사람이 한다.
PROMISE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    # 「찾아 드릴게요」(되묻기)는 약속이 아니므로 동사를 좁힌다
    ("해 드린다는 약속", re.compile(r"(해|깔아|맞춰|보내|넣어|챙겨)\s*드(리겠|릴|립니다|려요)")),
    ("확인했다는 말", re.compile(r"확인(했|하였)습니다|확인\s*됐|접수(했|됐|되었)")),
    ("가능하다는 단정", re.compile(r"(포함|설치|배송|할인|발행|결제)[^.?!]{0,8}가능(합니다|해요)")),
    ("담당자·다른 단계로 미룸", re.compile(r"담당\s*(팀|자|부서)|다른\s*(부서|시스템)|(구매|주문|결제|상품\s*확정)\s*(단계|후)에?서?\s*(안내|확인)")),
)


def promise_flags(*texts: str) -> list[str]:
    """AI 가 낸 말에서 약속하는 말의 종류 — PROMISE_PATTERNS 순서, 중복 없이."""
    joined = " ".join(t for t in texts if t)
    return [label for label, pat in PROMISE_PATTERNS if pat.search(joined)]


_QA_LABEL = re.compile(r"^\s*QA-\S*\s*", re.I)
_NON_WORD = re.compile(r"[\s\W_]+")


def question_key(masked_text: str) -> str | None:
    """같은 질문을 묶는 키 — 품질관리 이름표·공백·문장부호를 걷고 소문자로 맞춘 sha256.

    원문 대신 이 키만 저장한다. 마스킹된 문장에서 만든다(개인정보 조각은 이미 치환됨).
    """
    import hashlib
    t = _NON_WORD.sub("", _QA_LABEL.sub("", masked_text or "")).lower()
    return hashlib.sha256(t.encode("utf-8")).hexdigest() if t else None


# ── ⑦ 고객에게 내기 전 손질 (2026-10-11 개발 서버 「배그와 롤 150만원」 캡처) ─────────────
# 모델 문장에 한국어가 아닌 문자(힌디어 「उपलब्ध한」)가 섞여 낱자모처럼 깨져 보였다. 글자 수로
# 자르는 곳(REPLY_MAX_LEN 등)은 파이썬 문자 단위라 한글을 깨지 않는다 -- 원인은 모델 출력이다.
# 한글·영문·숫자·한자 밖의 문자(그리스 문자는 단위 기호로 남긴다)가 든 낱말을 통째로 걷는다.
_FOREIGN_CHARS = ("\u0400-\u052F\u0530-\u058F\u0590-\u05FF\u0600-\u06FF\u0750-\u077F"
                  "\u08A0-\u08FF\u0900-\u109F\u10A0-\u10FF\u1200-\u139F\u1780-\u17FF"
                  "\u3040-\u30FF")
_FOREIGN_WORD = re.compile(r"[^\s.,!?]*[" + _FOREIGN_CHARS + r"][^\s.,!?]*")
# 고객이 「150만원」이라 했는데 「150만원대」로 받는 것 -- 「대」는 고객이 붙였을 때만 쓴다.
# 「대」 뒤 조사는 받침 있는 「원」에 맞게 바꾼다(「150만원대로」 -> 「150만원으로」).
_AFTER_WON = {"로": "으로", "가": "이", "는": "은", "를": "을", "라": "이라", "야": "이야",
              "예요": "이에요", "여서": "이어서"}
_SAID_MAN = re.compile(r"(?<![0-9])([0-9][0-9,]*)\s*만\s*원?(?!\s*대)")


def tidy_customer_text(s: str, customer_text: str = "") -> str:
    """AI 가 낸 고객용 문장 손질 -- 외국 문자 낱말 걷기 · 고객이 안 붙인 「만원대」의 「대」 떼기."""
    if not s:
        return s
    out = s
    if _FOREIGN_WORD.search(out):
        out = _FOREIGN_WORD.sub("", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r" +([.,!?])", r"\1", out).strip()
    said = {int(n.replace(",", "")) for n in _SAID_MAN.findall(customer_text or "") if n.replace(",", "")}
    bare = bare_budget_from_text(customer_text) if customer_text else None
    if bare:
        said.add(bare // 10_000)
    for n in said:
        if not re.search(r"(?<![0-9])%d\s*만\s*원?\s*대" % n, customer_text or ""):
            out = re.sub(r"(?<![0-9,])(?:%s|%d)\s*만\s*원\s*대(로|가|는|를|라|야|예요|여서)?" % (f"{n:,}", n),
                         lambda m, n=n: "%d만원" % n + _AFTER_WON.get(m.group(1) or "", m.group(1) or ""), out)
    return out
