# -*- coding: utf-8 -*-
"""PC 구성 질문에 일반 AI 처럼 먼저 답한다 -- 답변 경로 [B] 의 PC 갈래(2026-10-11 사장님 확정).

사장님 원문(2026-10-11):
  > "LLM에 먼저 API 연동해서 보내주고.. 그걸 기반으로 신뢰성있게.. 우리 제품도 같이 보여줘야..
  >  계속 되물어보면.. 너무 짜증남.. 일반 LLM이 저렇게 답변했다고 해서.. 저걸 또 검증한다고
  >  시간끌지말고.. 저 기준이 크게 어긋나지 않으면.. 우리가 제품을 보여주면 돼.. 아래 쪽에.."

■ 무엇을 하나
  [B] 는 원래 «게임 질문»에만 답했다(talk_answer.answer_path). 그래서 「개발자용 PC를 가장 저렴하게
  추천해줘」에는 위쪽 설명이 비고, 되묻기 한 줄과 카드만 나왔다. 이 모듈은 PC 구성 질문에
  «무엇이 중요하고 무엇은 아껴도 되는지, 왜 그런지»를 서너 문장으로 먼저 답한다. 화면은 이 답을
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

ADVICE_MAX_LEN = 420
ADVICE_MAX_TOKENS = 500
ADVICE_TIMEOUT_SEC = 10
TASK_KEY = "task.talk_answer"

_PC_WORD = re.compile(r"pc|피시|컴퓨터|컴\b|본체|데스크\s*[탑톱]|조립", re.I)
_REQUEST = re.compile(r"추천|맞춰|맞추|견적|사려|살려|살까|사고\s*싶|구매|구입|구성|뭐가\s*좋|어떤\s*게\s*좋|"
                      r"싸게|저렴|가성비|최저가|싼\s*(걸|거|것)|좋은\s*(걸|거|것)|최고\s*사양")
# 고객에게 보일 조건만 -- 램·SSD·그래픽 필요 여부. 지수·등급 같은 내부 기준은 빼고 옮긴다.
# 부품 질문(「SSD랑 메모리 차이가 뭐예요」)과 쓰던 PC 고민(「지금 쓰는 PC가 느려요」)도 설명을 먼저 한다
# (코덱스 담당의견-최소차이-v1 §3 -- 단순 설명 질문에 구매 절차를 강제로 시작하지 않는다).
# 모니터는 뺀다 -- 「모니터 추천」은 크기 구간을 바로 보여 주는 별도 흐름이 있다(talk.MONITOR_BANDS).
_PART = re.compile(r"ssd|hdd|하드|램|ram|메모리|그래픽\s*카드|글카|gpu|vga|cpu|씨피유|프로세서|파워|쿨러|메인\s*보드|케이스", re.I)
_ASKS = re.compile(r"차이|뭐|무엇|뭔가|어떤|어느|왜|필요|좋아|좋은|괜찮|비교|알려|궁금|역할|\?")
_UPGRADE = re.compile(r"느려|느리|버벅|끊겨|끊김|렉\b|렉이|업그레이드|교체|바꾸|바꿀|늘리|늘릴|증설|오래\s*된|쓰던")
TOPIC_BUILD, TOPIC_PART, TOPIC_UPGRADE = "build", "part", "upgrade"
_PUBLIC_COND = re.compile(r"램 \d+GB 이상|SSD \d+GB 이상|그래픽 메모리 \d+GB 이상|외장 그래픽 필요|엔비디아 그래픽 필요")
_QUESTION = re.compile(r"\?\s*$|까요\s*$|나요\s*$|세요\s*\?|신가요")


def mentions_pc(sentence: str) -> bool:
    return bool(_PC_WORD.search(sentence or ""))


def usage_hits(sentence: str, vocab) -> list[str]:
    """문장에 걸린 용도 라벨(용도 어휘의 매칭 낱말 기준). 없으면 []."""
    s = (sentence or "").lower()
    out: list[str] = []
    for label, terms in getattr(vocab, "usages", None) or []:
        if any(t and t.lower() in s for t in list(terms) + [label]) and label not in out:
            out.append(label)
    return out


def topic_of(sentence: str, vocab) -> str | None:
    """설명을 먼저 해 줄 문장인가 -> build | part | upgrade | None."""
    s = sentence or ""
    part, pc = bool(_PART.search(s)), bool(_PC_WORD.search(s))
    if _UPGRADE.search(s) and (pc or part):
        return TOPIC_UPGRADE
    if _REQUEST.search(s) and (usage_hits(s, vocab) or pc):
        return TOPIC_BUILD
    if part and _ASKS.search(s):
        return TOPIC_PART
    return None


def wants_advice(sentence: str, vocab, prev_state=None) -> list[str] | None:
    """PC 설명을 먼저 해 줄 문장인가 -> 설명에 쓸 용도 라벨 목록(빈 목록 가능). 아니면 None."""
    if topic_of(sentence, vocab) is None:
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
    TOPIC_BUILD: "이 용도에 무엇이 중요하고 무엇은 필요 없거나 아껴도 되는지, 그 이유를 서너 문장으로 쓴다."
                 " 고객이 싸게(최저가·가성비)를 말했으면 어디를 아끼고 어디는 지킬지, 좋은 것을 말했으면 어디에 더"
                 " 쓰면 체감이 큰지 말한다. 작업이 커지면(예: 도커·가상 머신 여러 개) 무엇이 더 필요해지는지도 한 문장 말해도 된다."
                 " 용도를 말하지 않았으면 용도에 따라 무엇이 달라지는지 짧게 설명한다.",
    TOPIC_PART: "고객이 물은 부품의 역할과 차이, 고르는 기준을 서너 문장으로 쉽게 설명한다."
                " 새 PC를 사라고 권하지 않는다.",
    TOPIC_UPGRADE: "쓰던 PC의 불편에서 흔한 원인과 먼저 살펴볼 부품(예: 저장장치·메모리)을 서너 문장으로 설명한다."
                   " 지금 PC 사양을 모르면 무엇을 확인하면 되는지 문장으로 알려 준다(질문 형태로 쓰지 않는다)."
                   " 특정 PC에 바로 장착된다고 단정하지 않는다.",
}


def build_prompt(sentence: str, basis: list[str], history: list | None = None,
                 topic: str = TOPIC_BUILD) -> str:
    hist = ["%s: %s" % ("고객" if r == "user" else "상담원", t) for r, t in (history or [])][-4:]
    lines = [
        "당신은 PC 판매점의 상담원이다. 고객이 PC 에 대해 물었다. 일반 AI 에게 물었을 때처럼 먼저 답한다.",
        "되묻기로 답을 미루지 않는다 - 고객은 이미 물었다.",
        "",
        "[쓸 것] " + _TOPIC_TASK.get(topic, _TOPIC_TASK[TOPIC_BUILD]),
        "[말투] 쉬운 한국어 존댓말(~요). 강조 기호(**)·목록 기호 없이 문장으로 쓴다. 감사 인사로 시작하지 않는다."
        " %d자 이내." % ADVICE_MAX_LEN,
        "",
        "[우리 추천 기준] 아래 추천 카드는 이 기준표를 따른다. 설명이 이 기준과 어긋나지 않게 한다"
        " (예: 최소 기준이 램 16GB 이면 16GB 로는 부족하다고 말하지 않는다). 기준표에 없는 내부 수치는 만들지 않는다.",
        *(basis or ["(기준표를 읽지 못했다 - 일반적인 설명만 한다)"]),
        "",
        "[쓰지 않는 것]",
        "- 가격·금액·예산 숫자(카드가 보여 준다).",
        "- 특정 부품 모델명(RTX 4060·i5-14400·라이젠 5 7600 같은 것). 부품 종류 이름(그래픽카드·램·SSD·CPU)은 된다.",
        "- 재고·배송·할인·설치.",
        "- 질문 문장. 마지막 안내는 서버가 붙인다.",
        "- 카드나 견적을 찾아 주겠다·맞춰 주겠다는 약속.",
        "",
    ]
    if hist:
        lines += ["[대화 이력 - 오래된 것부터]", *hist,
                  "이미 한 설명을 그대로 되풀이하지 않는다. 이번 문장이 더한 것만 짧게 보탠다.", ""]
    lines += ["[고객 문장]", sentence]
    return "\n".join(lines)


_PRICE_WORDS = re.compile(r"\d+\s*만|\d+\s*원|원대|가격대")


def clean(raw: str) -> tuple[str, list[dict]]:
    """AI 설명 -> (고객 문장, 걷은 문장[{before, reason}]). 가격·모델명·재고·질문 문장만 걷는다."""
    kept, dropped = [], []
    for s in TF.split_sentences((raw or "").replace("**", "")):
        if TF._RE_PRICE.search(s) or _PRICE_WORDS.search(s):
            dropped.append({"before": s, "reason": "price"})
        elif TF._RE_PART.search(s):
            dropped.append({"before": s, "reason": "part model"})
        elif any(w in s for w in TF._LEXICON_STOCK):
            dropped.append({"before": s, "reason": "stock"})
        elif _QUESTION.search(s):
            dropped.append({"before": s, "reason": "question"})
        else:
            kept.append(s.lstrip("-•* ").strip())
    body = " ".join(k for k in kept if k)
    if len(body) > ADVICE_MAX_LEN:
        cut = body[:ADVICE_MAX_LEN]
        body = cut[:cut.rfind(".") + 1] if "." in cut else cut
    return body, dropped


def advise(conn_factory, sentence: str, labels: list[str], res, *, history=None,
           timeout_sec: float = ADVICE_TIMEOUT_SEC, topic: str = TOPIC_BUILD):
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
        out = llm.call(build_prompt(sentence, basis, history, topic), task_key=TASK_KEY,
                       customer_facing=True, max_output_tokens=ADVICE_MAX_TOKENS,
                       timeout_sec=int(min(ADVICE_TIMEOUT_SEC, timeout_sec)))
        res.provider, res.model = out.provider, out.model
        res.cost_usd, res.tokens_in, res.tokens_out = out.cost_usd, out.tokens_in, out.tokens_out
        res.log_id = out.log_id
        body, dropped = clean(out.text)
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
