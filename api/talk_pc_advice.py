# -*- coding: utf-8 -*-
"""PC 구성 질문에 일반 AI 처럼 먼저 답한다 -- 답변 경로 [B] 의 PC 갈래(2026-10-11 사장님 확정).

사장님 원문(2026-10-11):
  > "LLM에 먼저 API 연동해서 보내주고.. 그걸 기반으로 신뢰성있게.. 우리 제품도 같이 보여줘야..
  >  계속 되물어보면.. 너무 짜증남.. 일반 LLM이 저렇게 답변했다고 해서.. 저걸 또 검증한다고
  >  시간끌지말고.. 저 기준이 크게 어긋나지 않으면.. 우리가 제품을 보여주면 돼.. 아래 쪽에.."

■ 무엇을 하나
  [B] 는 원래 «게임 질문»에만 답했다(talk_answer.answer_path). 그래서 「개발자용 PC를 가장 저렴하게
  추천해줘」에는 위쪽 설명이 비고, 되묻기 한 줄과 카드만 나왔다. 이 모듈은 PC 구성 질문에
  «무엇이 중요하고 무엇은 아껴도 되는지, 왜 그런지»를 네다섯 문장으로 먼저 답한다. 화면은 이 답을
  말풍선 위쪽에, 가정 한 줄(api/talk_defaults)을 그 끝에, 추천 카드를 그 아래에 둔다.

■ 설명과 카드가 어긋나지 않게
  · 추천 카드가 실제로 따르는 기준표(product_fit_levels)의 작업 설명과 램·SSD·그래픽 조건을 프롬프트에
    싣는다. 내부 지수(CPU 멀티 지수 등)는 싣지 않는다(협업 6번).
  · 가격·금액, 특정 부품 모델명, 재고·배송, 질문 문장은 걷는다 -- 가격과 부품은 카드가 말하고,
    질문은 서버가 끝에 한 번만 붙인다. 다시 검증하는 두 번째 AI 호출은 두지 않는다(사장님 「시간끌지말고」).
"""
from __future__ import annotations

import logging
import re
import time

from sqlalchemy import bindparam, text

from . import llm
from . import talk_filter as TF

log = logging.getLogger(__name__)

# 480자로는 일반 AI 대비 「설명이 얕다」가 네 번 연속 나왔다(2026-10-12 비교 네 번째 86개 -- 추천 질문 31개 중 28개).
ADVICE_MAX_LEN = 700
# 한국어는 글자당 토큰이 많다 -- 500 이면 설명이 「CPU는 높은 프」에서 끊겼다(2026-10-11 일반 AI 비교 R05·R23).
ADVICE_MAX_TOKENS = 1300
ADVICE_TIMEOUT_SEC = 12      # [B] 경로 전체 상한(talk_answer.PATH_B_TIMEOUT_SEC = 13) 안
TASK_KEY = "task.talk_answer"

_PC_WORD = re.compile(r"pc|피시|컴퓨터|컴\b|본체|데스크\s*[탑톱]|조립", re.I)
_REQUEST = re.compile(r"추천|맞춰|맞추|견적|사려|살려|살까|사고\s*싶|구매|구입|구성|뭐가\s*좋|어떤\s*게\s*좋|짜\s*줘|짜\s*주|"
                      r"어떤\s*(pc|피시|컴퓨터|컴|본체|사양)\S{0,2}\s*(좋|괜찮|필요|돼|되)|"
                      r"싸게|저렴|가성비|최저가|싼\s*(걸|거|것)|좋은\s*(걸|거|것)|최고\s*사양|"
                      # 「예산 얼마나 잡아야」·「배그 돌아가는 컴퓨터」(2026-10-11 일반 AI 비교 R09·E13)
                      r"얼마\S{0,2}\s*(잡|들|필요|있어야|정도|면\s*돼|면\s*되)|돌아가는|돌릴|돌리려|"
                      # 「사무용 컴퓨터 50만원으로 맞출 수 있어요?」·「회계 사무실 PC 5대 필요해요」·「4K 편집이랑 3D 렌더링
                      # 같이 하려면?」·「공부용이랑 마인크래프트용 컴퓨터요」(2026-10-11 개발 서버 -- 설명 없이 되묻기만 했다)
                      r"맞출|용\s*(pc|피시|컴퓨터|본체|데스크)", re.I)
# 「~하려면」「~필요해요」는 용도·게임·PC 를 말했을 때만 새 PC 질문이다. 부품을 말했으면(「PC 램 몇 기가 필요해요?」)
# 부품 설명으로 둔다 -- 새 PC 용도를 되묻지 않게.
_NEED = re.compile(r"하려면|쓰려면|필요해|필요한가|필요할까|뭐가\s*필요")
# 「화이트 감성으로 100만원 PC」처럼 예산 금액과 PC 를 함께 말했으면 새 PC 질문이다(2026-10-12 개발 서버 -- 설명 없이 되묻기만 했다).
_AMOUNT = re.compile(r"\d+\s*만\s*원|\d+\s*만\s*(원\s*)?대|\d{2,3}\s*만(?!\s*(시간|명|개|건))")
# 고객에게 보일 조건만 -- 램·SSD·그래픽 필요 여부. 지수·등급 같은 내부 기준은 빼고 옮긴다.
# 부품 질문(「SSD랑 메모리 차이가 뭐예요」)과 쓰던 PC 고민(「지금 쓰는 PC가 느려요」)도 설명을 먼저 한다
# (코덱스 담당의견-최소차이-v1 §3 -- 단순 설명 질문에 구매 절차를 강제로 시작하지 않는다).
# 모니터도 넣는다(2026-10-12) -- 크기 구간 흐름(talk.MONITOR_BANDS)은 백업 화면(mvp1)만 부르고 지금 화면(mvp3)은
# 부르지 않아, 「모니터 어떤 거 사야 돼요?」에 본체 가격 안내만 나갔다.
# 그래픽카드·CPU 모델명도 부품이다 -- 「RTX 5060이랑 RTX 5060 Ti 차이가 뭐예요?」가 「판단할 수 없어요」로 끝났다(2026-10-11).
_PART = re.compile(r"ssd|hdd|하드|램|ram|메모리|그래픽\s*카드|글카|gpu|vga|cpu|씨피유|프로세서|파워|쿨러|메인\s*보드|케이스|모니터|"
                   r"(?<![a-z])(rtx|gtx|rx)\s*\d{3,4}|지포스|라데온|라이젠|ryzen", re.I)
_ASKS = re.compile(r"차이|뭐|무엇|뭔가|어떤|어느|왜|필요|좋아|좋은|괜찮|비교|알려|궁금|역할|\?")
_UPGRADE = re.compile(r"느려|느리|버벅|끊겨|끊김|렉\b|렉이|업그레이드|교체|바꾸|바꿀|늘리|늘릴|증설|오래\s*된|쓰던")
TOPIC_BUILD, TOPIC_PART, TOPIC_UPGRADE, TOPIC_GENERAL = "build", "part", "upgrade", "general"
TOPIC_LAPTOP = "laptop"
# 상담 중 고객이 이어서 한 말(환경·용도 설명 등) -- 위 규칙 낱말에 안 걸려도 AI 가 대화 전체를 읽고 답한다
# (2026-10-12 사장님 캡처: 「업무·학교·개인 용도로 두루두루, 모니터가 4대 임」에 AI 설명 없이 고정 안내만 나갔다.
#  사장님 「고객 소통채널은 LLM 이 되어야 함 · 말귀를 못 알아듣고 우리 하고 싶은 말만 한다」).
TOPIC_FOLLOW = "follow"
# 「이 가격이면 그냥 노트북 사는 게 낫지 않아요?」 -- 노트북을 팔지 않아도 데스크톱과 무엇이 다른지는 답할 수 있다
# (2026-10-11 일반 AI 비교 R27: 「노트북은 판매하지 않습니다」와 되묻기만 나갔다).
_LAPTOP_COMPARE = re.compile(r"(노트북|랩탑|랩톱|laptop|notebook).{0,20}(낫|나아|나을|나은|비교|차이|대신|vs|말고)|"
                             r"(낫|나아|나을|나은|비교|차이|대신|vs|말고).{0,20}(노트북|랩탑|랩톱|laptop|notebook)", re.I)
# 윈도우·배송·설치·환불·취소·보증·결제처럼 «일반 기준»은 말할 수 있는 구매 절차 질문(2026-10-11 일반 AI 비교
# R12·R13·E42·E44: 「확인이 어렵다」로만 넘겨 손님에게 남는 것이 없었다). 우리 가게 조건은 아래 안내(reply)가 말한다.
_GENERAL = re.compile(r"윈도우?|운영\s*체제|배송|택배|출고|도착|설치|환불|취소|반품|교환|보증|(?<![a-z])a\s*/?\s*s(?![a-z])|"
                      r"에이에스|무상\s*수리|할부|결제|영수증|세금\s*계산서|중고|"
                      # 다른 쇼핑몰과 비교·업체 신뢰도 비교 요령과 확인 방법은 일반 기준으로 답할 수 있다(2026-10-12 일반 AI 비교
                      # E31·E32·E33: 「다나와가 더 싸요?」·「A업체 사기인가요?」에 확인 방법조차 주지 않았다).
                      r"다나와|쿠팡|11번가|지마켓|g마켓|옥션|컴퓨존|네이버\s*쇼핑|가격\s*비교|"
                      r"다른\s*(쇼핑몰|업체|곳|가게|사이트)|타\s*(업체|사이트)|사기", re.I)
_PUBLIC_COND = re.compile(r"램 \d+GB 이상|SSD \d+GB 이상|그래픽 메모리 \d+GB 이상|외장 그래픽 필요|엔비디아 그래픽 필요")
_QUESTION = re.compile(r"\?\s*$|까요\s*$|나요\s*$|세요\s*\?|신가요")


def mentions_pc(sentence: str) -> bool:
    return bool(_PC_WORD.search(sentence or ""))


def asks_for_pc(sentence: str, vocab) -> bool:
    """PC 낱말이 없어도 PC 를 묻는 문장인가 -- 「~하려면 뭐가 필요해요?」이거나 게임 밖 용도(방송·편집)를 함께 말했다.
    2026-10-12 개발 서버 「유튜브 방송하면서 게임도 하려면 뭐가 필요해요?」에 인기 게임 목록이 나갔다."""
    from . import talk_schema as TS
    s = sentence or ""
    return bool(_NEED.search(s)) or any(not TS.is_game_usage(lb) for lb in usage_hits(s, vocab))


def usage_hits(sentence: str, vocab) -> list[str]:
    """문장에 걸린 용도 라벨(용도 어휘의 매칭 낱말 기준). 없으면 []."""
    s = (sentence or "").lower()
    out: list[str] = []
    for label, terms in getattr(vocab, "usages", None) or []:
        if any(t and t.lower() in s for t in list(terms) + [label]) and label not in out:
            out.append(label)
    return out


# 게임 이름이 든 문장이 «PC 이야기»인가 -- PC·부품 낱말, 예산 숫자, 구성·사양·견적 낱말(「롤 같은 게임 추천해줘」는
# 게임 이야기라 아니다). 2026-10-11 일반 AI 비교 R01·R23: 「120만원 롤·오버워치·로아 구성 짜줘」에 게임 소개와
# 「PC 구성은 답변하지 않습니다」가 나갔다.
_PC_INTENT = re.compile(r"\d+\s*만\s*원?|예산|구성|사양|견적|맞추|맞춰|짜\s*줘|짜\s*주|프레임|fps|옵션", re.I)


def pc_intent(sentence: str) -> bool:
    s = sentence or ""
    return bool(_PC_WORD.search(s) or _PART.search(s) or _PC_INTENT.search(s))


# 부품을 이해하려는 질문(「PC 메모리 구성과 SSD 차이가 뭐예요?」) -- 「구성」이 요청 낱말에 걸려도 사려는 말이
# 없으면 새 PC 추천이 아니라 부품 설명이다(코덱스 PR157 검수 v1 P2-1).
_EXPLAIN = re.compile(r"차이|역할|왜|무슨\s*(뜻|의미|역할)|뭐예요|뭔가요|뭐야|뭐에요|뭐죠|뭐지|설명")
_BUY = re.compile(r"추천|사려|살려|살까|사고\s*싶|구매|구입|견적|맞춰|맞추|짜\s*줘|짜\s*주|\d+\s*만\s*원?|예산", re.I)


def topic_of(sentence: str, vocab, game: bool = False) -> str | None:
    """설명을 먼저 해 줄 문장인가 -> build | part | upgrade | general | None. game=True 면 게임 이름을 용도로 친다."""
    s = sentence or ""
    part, pc = bool(_PART.search(s)), bool(_PC_WORD.search(s))
    if _LAPTOP_COMPARE.search(s) and not part:        # 「노트북 램 차이」는 부품 이야기다
        return TOPIC_LAPTOP
    explain_part = part and bool(_EXPLAIN.search(s)) and not _BUY.search(s)
    uses = bool(usage_hits(s, vocab)) or game
    build = bool((_REQUEST.search(s) and (uses or pc))
                 or (_NEED.search(s) and (uses or (pc and not part)))
                 # 「100만원 PC 환불 언제 들어와?」의 금액은 새 PC 예산이 아니라 주문 금액이다(코덱스 #177~#181 검수 P2-4).
                 or (pc and not part and _AMOUNT.search(s) and not _GENERAL.search(s))
                 # 「사무용 80만원」 -- PC 낱말·요청 낱말 없이 용도와 예산만 말해도 새 PC 이야기다. 설명 없이
                 # 「문서 작업 중심인가요?」 질문만 나갔다(2026-10-12 Claude 복귀 뒤 점검).
                 or (uses and not part and _AMOUNT.search(s) and not _GENERAL.search(s))) and not explain_part
    if _GENERAL.search(s) and not build:
        return TOPIC_GENERAL
    if _UPGRADE.search(s) and (pc or part):
        return TOPIC_UPGRADE
    if build:
        return TOPIC_BUILD
    if part and (_ASKS.search(s) or _REQUEST.search(s)):     # 「모니터 추천해줘」·「램 추천해줘」
        return TOPIC_PART
    return None


# 인사·맞장구만 한 말은 이어 답하지 않는다 -- 「감사합니다」에 PC 설명을 붙이지 않게.
_ACK_ONLY = re.compile(r"^\W*(감사|고마|고맙|ㅋ|ㅎ|ㄳ|안녕|수고|좋아요|네\b|넵|예\b|오케이|ok|알겠|잘\s*봤)", re.I)


def _in_consult(prev_state, history) -> bool:
    """이미 PC 상담이 진행 중인가 -- 앞 턴에 용도·예산을 읽었거나, 상담원이 한 번이라도 답했다."""
    if prev_state is not None and (getattr(prev_state, "usages", None) or getattr(prev_state, "budget_won", None)):
        return True
    return any(r == "assistant" for r, _t in (history or []))


def topic_in_context(sentence: str, vocab, prev_state=None, history=None) -> str | None:
    """topic_of 에 대화 맥락을 더한다 -- 규칙 낱말에 안 걸려도 상담 중 고객이 이어 말했으면 TOPIC_FOLLOW.

    규칙(topic_of)은 «어떤 설명을 할지» 고르는 데만 쓴다. «설명을 할지 말지»를 규칙이 막지 않는다
    -- 막으면 손님 말에 AI 답 없이 고정 안내만 나간다. 잡담이면 [A] 판정(pc=false)이 이 답을 화면에서 뺀다
    (talk.parse_talk 「answer = ""」 갈래)."""
    t = topic_of(sentence, vocab)
    if t is not None:
        return t
    s = (sentence or "").strip()
    if not s or (len(s) <= 12 and _ACK_ONLY.match(s)):
        return None
    if usage_hits(s, vocab) or pc_intent(s) or _in_consult(prev_state, history):
        return TOPIC_FOLLOW
    return None


def wants_advice(sentence: str, vocab, prev_state=None, history=None) -> list[str] | None:
    """PC 설명을 먼저 해 줄 문장인가 -> 설명에 쓸 용도 라벨 목록(빈 목록 가능). 아니면 None."""
    if topic_in_context(sentence, vocab, prev_state, history) is None:
        return None
    prev = list(getattr(prev_state, "usages", None) or []) if prev_state is not None else []
    return usage_hits(sentence, vocab) or prev


def _fit_of(label: str) -> str | None:
    from .sold_reco import fit_usage           # DB 적재 모듈을 끌어오므로 쓸 때만 읽는다
    return fit_usage(label)


def basis_lines(conn, labels: list[str]) -> list[str]:
    """추천 기준표의 용도별 단계 -> 고객에게 보일 기준 줄. 못 읽으면 []."""
    fits = [f for f in dict.fromkeys(_fit_of(lb) for lb in labels) if f]
    if not fits:
        return []
    rows = conn.execute(text(
        "SELECT usage, level, level_rank, work, conditions FROM product_fit_levels"
        " WHERE usage IN :u ORDER BY usage, level_rank").bindparams(
            bindparam("u", expanding=True)), {"u": fits}).mappings().all()
    out = []
    for r in rows:
        conds = " · ".join(_PUBLIC_COND.findall(r["conditions"] or ""))
        tail = f" ({conds})" if conds else ""
        mark = " <- 추천 카드의 최소 기준" if r["level_rank"] == 1 else ""
        out.append(f"- {r['usage']} {r['level']}: {r['work']}{tail}{mark}")
    return out


_TOPIC_TASK = {
    TOPIC_BUILD: "이 용도에 맞는 구성을 구체적으로 네다섯 문장 쓴다 -- CPU와 그래픽카드는 등급과 급 예시를 둘 다"
                 " (「중급형, 라이젠 5급·RTX 5060급」처럼), 램과 SSD 는 용량, 그리고 시중 예상 가격대를 「시중에서는 보통"
                 " ○○만원대」처럼 일반 시세로 말한다. 무엇은 아껴도 되는지와 그 이유도 말한다."
                 " 고객이 해상도·주사율·프레임(FHD·QHD·4K·144Hz·240fps)이나 AI·영상·3D 작업을 말했으면 그 기준에 맞는"
                 " 숫자(그래픽카드 VRAM ○GB 이상, 램 ○GB, 파워 ○W급)를 한 문장 넣는다."
                 " 고객이 싸게(최저가·가성비)를 말했으면 어디를 아끼고 어디는 지킬지, 좋은 것을 말했으면 어디에 더"
                 " 쓰면 체감이 큰지 말한다. 작업이 커지면(예: 도커·가상 머신 여러 개) 무엇이 더 필요해지는지도 한 문장 말해도 된다."
                 " 용도를 말하지 않았으면 용도에 따라 무엇이 달라지는지 짧게 설명한다.",
    TOPIC_PART: "고객이 물은 부품의 역할과 차이, 고르는 기준을 네다섯 문장으로 쉽게 설명한다. 기준은 숫자로 말한다"
                " (VRAM ○GB·램 ○GB·파워 ○W·코어 수처럼). 하나를 골라 달라고 하면 용도별로 「RTX 5060급」·「라이젠 5급」처럼"
                " 급 예시를 들어 어느 쪽이 맞는지 말한다."
                " 새 PC를 사라고 권하지 않는다.",
    TOPIC_UPGRADE: "쓰던 PC의 불편에서 흔한 원인과 먼저 살펴볼 부품(예: 저장장치·메모리)을 서너 문장으로 설명한다."
                   " 지금 PC 사양을 모르면 무엇을 확인하면 되는지 문장으로 알려 준다(질문 형태로 쓰지 않는다)."
                   " 특정 PC에 바로 장착된다고 단정하지 않는다.",
    TOPIC_LAPTOP: "데스크톱(조립 PC)과 노트북을 이동·성능·발열과 소음·업그레이드·같은 돈으로 얻는 성능 기준으로"
                  " 서너 문장 비교하고, 어떤 사람에게 어느 쪽이 맞는지 말한다. 우리 가게는 노트북을 팔지 않지만"
                  " 노트북을 깎아내리지 않는다.",
    TOPIC_GENERAL: "고객이 물은 구매 절차(운영체제 설치·배송·설치·결제·환불·취소·보증 등)를 국내 조립 PC 쇼핑몰의"
                   " «일반적인» 기준으로 네다섯 문장 설명한다. 흔한 기간·조건은 숫자로 말한다(예: 조립 PC 출고는 보통 ○~○영업일,"
                   " 카드 결제 취소 환불은 보통 ○~○영업일, 단순 변심 청약철회는 전자상거래법상 받은 날부터 7일 이내,"
                   " 부품 보증은 제조사 기준 보통 ○~○년). 「보통」·「일반적으로」·「쇼핑몰마다 다르지만」처럼 말하고,"
                   " 우리 가게가 해 준다·가능하다고 약속하지 않는다. 고객이 직접 확인할 곳(상품 페이지·주문 내역·카드사)을"
                   " 한 문장 알려 준다. 카드번호·주민번호 같은 정보는 상담 창에 적지 않아도 된다는 점은 필요할 때만 말한다."
                   " 다른 쇼핑몰·가격비교 사이트와 비교를 물으면 같은 부품 모델인지, 조립비·운영체제·배송·A/S 포함 여부를 맞춰"
                   " 비교하는 요령을 말한다. 업체를 믿을 수 있는지 물으면 사업자 정보·통신판매업 신고·안전결제·후기처럼 확인할"
                   " 방법을 말하고, 어느 업체도 좋다·나쁘다·사기다 단정하지 않는다.",
    TOPIC_FOLLOW: "대화 이력과 이번 문장을 함께 읽고, 고객이 이번에 한 말에 바로 답한다. 고객이 쓰는 환경(모니터 대수·해상도,"
                  " 설치 공간, 소음, 함께 쓰는 장비)이나 용도를 말했으면 그 조건 때문에 PC에서 무엇이 필요해지는지"
                  " 숫자로 서너 문장 설명한다(예: 모니터 여러 대면 그래픽 출력 단자 수와 외장 그래픽카드가 필요한지)."
                  " 고객 말을 다른 뜻으로 바꿔 읽지 않는다 -- 예를 들어 「모니터가 4대」는 PC를 4대 산다는 말이 아니라"
                  " 모니터 4대를 연결해 쓴다는 말이다. 앞서 한 설명은 되풀이하지 않는다.",
}
# 구성 추천과 배송·환불을 함께 물으면(「배그PC 추천하고 배송일과 환불도 알려줘」) 구성 설명 뒤에 일반 기준 한 문장.
_BUILD_WITH_GENERAL = (" 고객이 배송·설치·환불·운영체제 같은 구매 절차도 물었으면 마지막에 국내 쇼핑몰의 일반적인 기준을"
                       " 한 문장 덧붙인다(우리 가게 약속은 하지 않는다).")


# 「배송은 얼마나 걸려요?」에 운영체제·환불·보증까지 다 나열하고 정작 배송 기간은 말하지 않았다(2026-10-12 일반 AI 비교 R13).
_GENERAL_FOCUS = (" 고객이 물은 항목만 답한다 -- 배송을 물으면 배송, 환불을 물으면 환불. 첫 문장에서 그 질문에 바로 답하고"
                  " (예: 「조립 PC는 보통 결제 뒤 ○~○영업일 안에 출고돼요」), 묻지 않은 절차를 늘어놓지 않는다.")


def build_prompt(sentence: str, basis: list[str], history: list | None = None,
                 topic: str = TOPIC_BUILD, games: list[str] | None = None) -> str:
    hist = ["%s: %s" % ("고객" if r == "user" else "상담원", t) for r, t in (history or [])][-4:]
    lines = [
        "당신은 PC 판매점의 상담원이다. 고객이 PC 에 대해 물었다. 일반 AI 에게 물었을 때처럼 먼저 답한다.",
        "되묻기로 답을 미루지 않는다 - 고객은 이미 물었다.",
        "",
        "[쓸 것] " + _TOPIC_TASK.get(topic, _TOPIC_TASK[TOPIC_BUILD])
        + (_BUILD_WITH_GENERAL if topic == TOPIC_BUILD and _GENERAL.search(sentence or "") else "")
        + (_GENERAL_FOCUS if topic == TOPIC_GENERAL else ""),
        *(["[고객이 말한 게임] " + ", ".join(games) + " -- 게임 소개·역사·장르·인기 설명은 쓰지 않는다."
            " 이 게임들이 가벼운지 무거운지, 그래서 그래픽카드·CPU·램 중 무엇이 체감을 좌우하는지와 그에 맞는 등급을 말한다."]
          if games else []),
        "[말투] 쉬운 한국어 존댓말(~요). 강조 기호(**)·목록 기호 없이 문장으로 쓴다. 감사 인사로 시작하지 않는다."
        " %d자 이내." % ADVICE_MAX_LEN,
        "",
        "[우리 추천 기준] 아래 추천 카드는 이 기준표를 따른다. 설명이 이 기준과 어긋나지 않게 한다"
        " (예: 최소 기준이 램 16GB 이면 16GB 로는 부족하다고 말하지 않는다). 기준표에 없는 내부 수치는 만들지 않는다."
        # 2026-10-12 카드 검수 B5: 사무용에 「램 16GB 권장」이라 했는데 카드 두 장은 8GB(기준표 사무용 기본 = 램 8GB 이상),
        # 영상에 「램 64GB·SSD 2TB」라 했는데 카드는 32GB·1TB 였다. 권하는 용량을 카드가 따르는 기준표 숫자에 맞춘다.
        " 램·SSD 용량은 기준표 숫자로 말한다 -- 「추천 카드의 최소 기준」 단계 숫자로 되는 작업을 먼저 말하고,"
        " 윗단계 숫자는 그 단계의 작업(예: 대용량 엑셀)을 할 때로 나눠 말한다. 기준표보다 큰 용량은 권장처럼 말하지 않고"
        " 「더 여유를 원하면」처럼 선택으로만 말한다.",
        *(basis or ["(기준표를 읽지 못했다 - 일반적인 설명만 한다)"]),
        "",
        "[쓰지 않는 것]",
        ("- 시중 시세를 넘는 가격 이야기 -- 가격은 「시중에서는 보통 ○○만원대」 한 문장으로만 쓰고, 우리 가게 가격·할인처럼"
         " 말하지 않는다(우리 가격은 아래 카드가 보여 준다)." if topic == TOPIC_BUILD
         else "- 가격·금액·예산 숫자(카드가 보여 준다)."),
        "- 특정 부품 모델명을 단정하는 말(「RTX 4060을 사세요」). 등급 예시는 「RTX 5060급」처럼 급·정도·이상을 붙여서만 쓴다."
        + (" 고객이 직접 말한 모델명(%s)은 그대로 써서 비교해도 된다." % ", ".join(_models(sentence))
           if _models(sentence) else ""),
        ("- 재고·할인·특정 기간을 우리 가게 약속처럼 단정하는 말." if topic == TOPIC_GENERAL
         or _GENERAL.search(sentence or "") else "- 재고·배송·할인·설치."),
        "- 질문 문장. 마지막 안내는 서버가 붙인다.",
        "- 카드나 견적을 찾아 주겠다·맞춰 주겠다는 약속.",
        "- 우리 가게가 그 조건(저소음·화이트·브랜드 등)을 맞출 수 있다·가능하다는 답(「가능해요」). 그런 구성을 고르는"
        " 요령만 말한다 -- 맞출 수 있는지는 아래 카드와 안내가 말한다.",
        "",
    ]
    if hist:
        lines += ["[대화 이력 - 오래된 것부터]", *hist,
                  "이미 한 설명을 그대로 되풀이하지 않는다. 이번 문장이 더한 것만 짧게 보탠다.", ""]
    lines += ["[고객 문장]", sentence]
    return "\n".join(lines)


NOTE_MARKET = "시중 가격은 일반 시세이고, 아래 카드는 지금 판매 중인 PC의 실제 가격이라 다를 수 있어요."
# 「소음 적은 구성 가능해요?」에 「가능해요.」로 시작한 뒤 카드 안내가 「저소음 조건은 지금 못 맞춥니다」라 했다(R10).
_BARE_YES = re.compile(r"^\s*(네[,.]?\s*)?(물론\s*)?(가능(해요|합니다)|돼요|됩니다|할\s*수\s*있어요)[.!]?\s*$")
_PRICE_WORDS = re.compile(r"\d+\s*만|\d+\s*원|원대|가격대")


# 일반 기준 설명에서는 배송·할인 낱말이 곧 질문의 주제라 걷지 않는다 -- 재고 이야기만 걷는다.
_STOCK_ONLY = ("재고", "품절", "입고")


_TIER_AFTER = re.compile(r"\s*(급|정도|이상|수준|대\b|계열)")
_ENDED = re.compile(r"[.!?。…]\s*$|[요다죠네](\s*[)」』\]])?\s*$")


def _norm(m: str) -> str:
    return re.sub(r"\s+", "", m).lower()


# 모델명 대조용 -- talk_filter._RE_PART 와 같되 라이젠은 4자리 모델 번호까지 잡는다. 「라이젠 5」 까지만 보면
# 고객이 「라이젠 5 7600」을 물었는데 「라이젠 5 9600」 문장이 남는다(2026-10-12 검수 9595 P2-1).
_RE_MODEL = re.compile(
    r"(?:RTX|GTX|RX|GT)\s?\d{3,4}\s?(?:Ti|TI|SUPER|XT)?|i[3579][-\s]?\d{4,5}"
    r"|(?:라이젠|Ryzen)\s?\d(?:\s?\d{4}[A-Z0-9]*)?", re.IGNORECASE)
_STORE_PRICE = re.compile(r"저희|우리(?!나라)|당사|팝콘|이\s*가게")
_SERIES_ONLY = re.compile(r"^(라이젠|ryzen)\d$")


def _models(sentence: str) -> list[str]:
    """고객 문장에 나온 부품 모델명(「RTX 5060」·「RTX 5060 Ti」) -- 고객이 직접 물은 모델은 설명에 남긴다."""
    out: list[str] = []
    for m in _RE_MODEL.finditer(sentence or ""):
        if m.group(0).strip() not in out:
            out.append(m.group(0).strip())
    return out


def clean(raw: str, topic: str | None = None, sentence: str = "") -> tuple[str, list[dict]]:
    """AI 설명 -> (고객 문장, 걷은 문장[{before, reason}]). 가격·모델명·재고·질문 문장만 걷는다.
    일반 기준 설명(TOPIC_GENERAL)은 우리 가게가 해 주겠다는 약속 문장도 걷는다(talk_rules 약속 표시와 같은 틀)."""
    from .talk_rules import PROMISE_PATTERNS        # talk_rules 가 이 모듈을 읽지 않으므로 순환은 없다
    general, build = topic == TOPIC_GENERAL, topic in (None, TOPIC_BUILD)
    # 본체 구성과 구매 절차(배송·설치 등)를 함께 물었으면 절차 설명 문장도 남긴다 -- 대신 가게 약속은 걷는다
    # (2026-10-12 검수 9da2 P2-1 「배송」 한 단어로 배송 기준 문장이 통째로 걷혔다).
    mixed = build and bool(_GENERAL.search(sentence or ""))
    stock = _STOCK_ONLY if general or mixed else TF._LEXICON_STOCK
    asked = {_norm(m) for m in _models(sentence)}
    kept, dropped = [], []
    sents = TF.split_sentences((raw or "").replace("**", ""))
    if sents and not _ENDED.search(sents[-1]):
        # 토큰이 다해 끊긴 끝 문장(「CPU는 높은 프」)은 내지 않는다.
        dropped.append({"before": sents.pop(), "reason": "cut"})
    for s in sents:
        # 고객이 직접 말한 모델명만 든 문장은 남긴다(2026-10-11 「RTX 5060이랑 5060 Ti 차이가 뭐예요?」에 비교 문장이
        # 전부 걷혀 「판단할 수 없어요」만 남았다). 고객이 말하지 않은 모델명이 하나라도 있으면 걷는다.
        # 「RTX 5060급」「i5 정도」처럼 등급 예시로 든 모델명은 남긴다(2026-10-12 -- 설명이 등급을 구체적으로 말하게).
        # 고객이 말한 라이젠 모델의 시리즈(「라이젠 5 7600」을 물었을 때 「라이젠 5」)도 고객이 말한 것으로 본다.
        foreign_model = any(_norm(m.group(0)) not in asked
                            and not (_SERIES_ONLY.match(_norm(m.group(0)))
                                     and any(a.startswith(_norm(m.group(0))) for a in asked))
                            and not _TIER_AFTER.match(s, m.end())
                            for m in _RE_MODEL.finditer(s))
        # 「시중」 가격 문장은 남기되 같은 문장에 가게 가격(「저희 가격은 140만원」)이 섞이면 걷는다(2026-10-12 검수 9595 P2-3).
        market_price = (build and "시중" in s and not _STORE_PRICE.search(s)
                        and not any(p.search(s) for _label, p in PROMISE_PATTERNS))
        if (TF._RE_PRICE.search(s) or _PRICE_WORDS.search(s)) and not market_price:
            dropped.append({"before": s, "reason": "price"})
        elif foreign_model:
            dropped.append({"before": s, "reason": "part model"})
        elif any(w in s for w in stock):
            dropped.append({"before": s, "reason": "stock"})
        elif (general or mixed) and any(p.search(s) for _label, p in PROMISE_PATTERNS):
            dropped.append({"before": s, "reason": "promise"})
        elif _BARE_YES.match(s):
            dropped.append({"before": s, "reason": "promise"})
        elif _QUESTION.search(s):
            dropped.append({"before": s, "reason": "question"})
        else:
            kept.append(s.lstrip("-•* ").strip())
    # 길이는 문장 단위로 줄인다 -- 글자 수로 자르면 문장 중간에서 끊긴다(2026-10-11 R23 「기본형을 선택」).
    body = ""
    for k in (k for k in kept if k):
        if body and len(body) + 1 + len(k) > ADVICE_MAX_LEN:
            dropped.append({"before": k, "reason": "length"})
            continue
        body = (body + " " + k).strip()
    # 시중 시세 문장이 남았으면 아래 카드(우리 판매가)와 다를 수 있다고 한 줄 밝힌다 -- 설명은 50~70만원대인데
    # 카드는 89만원이라 어긋나 보였다(2026-10-12 일반 AI 비교 R02·R11).
    if body and any("시중" in k for k in kept if k and k in body) and NOTE_MARKET not in body:
        body = (body + " " + NOTE_MARKET).strip()
    return body, dropped


def advise(conn_factory, sentence: str, labels: list[str], res, *, history=None,
           timeout_sec: float = ADVICE_TIMEOUT_SEC, topic: str = TOPIC_BUILD, games: list[str] | None = None):
    """[B] 의 PC 갈래 -- res(AnswerResult)를 채워 돌려준다. 예외를 올리지 않는다."""
    t0 = time.time()
    res.kind = "pc_advice"
    res.topic = topic
    try:
        try:
            with conn_factory() as conn:
                basis = basis_lines(conn, labels)
        except Exception as e:  # noqa: BLE001 - 기준표를 못 읽어도 일반 설명은 낸다
            log.warning("[talk-advice] fit levels unavailable: %s", type(e).__name__)
            basis = []
        out = llm.call(build_prompt(sentence, basis, history, topic, games), task_key=TASK_KEY,
                       customer_facing=True, max_output_tokens=ADVICE_MAX_TOKENS,
                       timeout_sec=int(min(ADVICE_TIMEOUT_SEC, timeout_sec)))
        res.provider, res.model = out.provider, out.model
        res.cost_usd, res.tokens_in, res.tokens_out = out.cost_usd, out.tokens_in, out.tokens_out
        res.log_id = out.log_id
        body, dropped = clean(out.text, topic, sentence)
        res.answer = body
        res.filter_report = {"kept": len(TF.split_sentences(body)), "replaced": [],
                             "dropped": dropped, "gate_hit": False}
        log.info("[talk-advice] done: basis=%d chars=%d dropped=%d", len(basis), len(body), len(dropped))
    except llm.LLMBlockedError as e:
        res.error = "llm blocked: %s/%s" % (e.kind, e.provider)
    except llm.LLMNotConfiguredError:
        res.error = "llm not configured"
    except (llm.LLMAllProvidersFailedError, llm.LLMProviderError) as e:
        res.error = "llm failed: %s" % type(e).__name__
    except Exception as e:  # noqa: BLE001
        res.error = "advice path error: %s" % type(e).__name__
        log.warning("[talk-advice] path failed: %s", type(e).__name__)
    res.elapsed_sec = round(time.time() - t0, 3)
    return res
