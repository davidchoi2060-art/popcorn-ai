"""S1 자유입력 파싱(POST /api/talk/parse) — 문장을 «조건»으로 바꾸고, «PC 상담인지»를 판정한다.

`api/main.py`가 자동으로 싣는다(pkgutil 1단계 스캔 — 등록 코드 없음).

■ 무엇을 하는 자리인가
  고객이 S1에서 자연어로 말한 문장을 화면이 이미 쓰는 제약 형태(`{l, v}` —
  정본은 `api/candidates.Constraint`)로 바꾼다. **그리고 그 문장이 PC 상담인지도
  여기서 판정한다**(`pc_related`) — 같은 한 번의 호출로.

■ 「PC 상담이 아니다」도 AI 가 판정한다 (2026-08-17 사장님 확정 — 「관문을 걷는다」)
  아침 결정은 「관문(어휘 목록)을 그대로 둔다」였다. 그때 그 문이 막던 것은 «보조
  파서»였다. 같은 날 「문장은 항상 AI 가 본다」로 바뀌면서 **그 문이 본 파서를 막게
  됐다** — 전제가 무너져 결정이 바뀌었다. 실측된 피해(확인자, 2026-08-17):

      「겜만 할래요」           '겜' 이 화면 어휘 목록(PCWORDS)에 없다   -> AI 호출 0건 · 반송
      「본체 하나 맞춰주세요」   '본체' 없음 · '맞춰' 는 원형 '맞추' 와 문자열 불일치 -> 반송

  둘 다 정상적인 PC 문의인데 상담 자체가 차단됐다. 원형만 담은 리터럴 목록은
  **활용형을 영영 못 잡는다** — 오늘 이 파일이 없앤 병(리터럴 어휘로 판정)과
  같은 원인이다. 그래서 그 목록을 지우고, 판정을 이 프롬프트로 옮겼다.

  ⚠ **`pc_related` 는 bool 이 아니면 `None`(모름)이다.** 모델이 필드를 빼먹거나
  형식을 어긴 것을 `false` 로 접으면 **정상 문의가 반송된다** — 실패를 「PC 아님」
  으로 오해시키지 않는다(아래 §실패를 삼키지 않는다와 같은 원칙). LLM 이 아예
  실패하면 502 라 `pc_related` 자체가 없고, 화면은 그때 반송하지 않는다.

  ⚠ **판정은 여기서만 한다.** 화면이 어휘로 다시 거르면 같은 병이 돌아온다
  (`mockups/mvp1/s1-session.html` 의 `talkParse` 주석이 그 규약을 들고 있다).

■ 지키는 결정
  - A-01·A-02·A-03: **LLM은 견적을 만들지 않는다.** 이 모듈은 부품·가격·후보 수를
    한 글자도 말하지 않는다. 구조적으로도 못 한다 — 응답 스키마가 라벨 3종
    (예산·용도·선호)과 **미리 정해진 값 집합**뿐이라 부품명이 들어올 칸이 없다.
    후보 수는 여전히 `/api/candidates/count`만이 답한다.
  - **문장은 항상 AI가 본다**(2026-08-17 사장님 확정 — 같은 날 아침의 「정규식 먼저,
    못 읽은 문장만 AI」를 뒤집은 결정). 옛 규칙은 「못 읽은 문장」을 문장 단위가 아니라
    «우연히 걸린 토큰 하나»로 판정하고 있었다 — 실측 「겜하려고요ㅋㅋ 백오십만언쯤
    조용한걸루요」에서 화면 정규식이 '조용한' 하나만 잡아 이 엔드포인트를 **한 번도
    부르지 않았고**, 예산 150만원과 용도 게임이 통째로 사라졌다. 같은 문장을 이 경로에
    넣으면 셋을 다 읽는다(2026-08-17 실측 2.4초 · claude-haiku).
    이제 화면은 **모든 문장**을 여기로 보내고, 정규식 결과는 **AI가 실패했을 때의 몫**과
    **AI가 만들지 못하는 라벨**(상황·모니터·관심 부품 — 아래 LABELS 밖)로만 남는다.
    합치는 규칙은 화면이 갖는다(`mockups/mvp1/s1-session.html`의 `parseAll` 주석):
    합집합 · 라벨이 겹치면 AI 우선 · 선호는 토큰 합집합.
    ⚠ 그래서 **한 사람이 태우는 호출 수가 대화 길이만큼 늘었다** — 방문자 한도
    (`api/access_gate.DEFAULT_PER_MINUTE`·`DEFAULT_PER_DAY`)의 근거였던 「한 사이클
    최대 4회」는 더 이상 성립하지 않는다. 조절 자리는 `rate_limit_policies` 행이다.

■ 어휘를 여기서 새로 정의하지 않는다 (CANON §1 — 정본을 복제하지 않는다)
  ① 용도 값 = `api/usage_floors`의 `usage_label` **과 `match_terms`**. 둘 다
     **요청마다 읽는다** — 운영자가 `usage_floors`를 고치면 다음 요청부터 반영된다.
     여기에 목록을 박아 두면 표가 늘어난 날 화면만 옛 어휘로 말한다.

     ⚠ **라벨만 주면 모델이 추론한다**(2026-08-17 실측으로 신설). 이 프롬프트는
     오래 «용도 이름 8개»만 줬고 「어떤 말이 그 용도인가」는 주지 않았다. 그래서
     정본이 답을 갖고 있는데도(`gaming_high.match_terms` = 고사양 게임 · 고사양게임 ·
     **배그** · AAA) 모델이 스스로 넓은 쪽을 골랐다:

         「배그 하고 싶어요」  이 경로 -> 용도 «게임»       (GPU 하한 450W)
                               정본     -> «고사양 게임»    (GPU 하한 550W)

     사장님 확정(2026-08-17)은 「배그 = 고사양 게임」이라 **이 경로가 정본을 배신하고
     있었다.** 화면이 그동안 «용도만 DB 어휘로 접어 AI 결과보다 우선»하는 임시 분기로
     메우고 있었다(`mockups/mvp1/s1-session.html` 의 `aiCons`). 그 임시 조치의 해소가
     여기다 — **정본 어휘를 프롬프트에 함께 싣는다.**

  ①-1 충돌 판정 — **모델이 이긴다. 서버가 원문을 다시 접지 않는다.**
     「모델이 고른 용도」와 「원문을 `UF.match()` 로 접은 용도」가 다를 때 무엇을 쓰는가는
     정하고 넘어가야 하는 문제다. 여기서는 **서버가 원문을 다시 접는 층을 두지 않는다.**

         근거 ① `UF.match()` 는 **부분일치**라 문맥을 못 본다. 「배그는 안 하고 롤만
                해요」에도 '배그'가 걸려 «고사양 게임»을 준다 — 고객이 안 한다고 말한
                것을 용도로 잡는 것이라, 그 값으로 건 하한(GPU 550W)은 근거가 거짓이 된다.
         근거 ② 정본을 프롬프트에 실은 뒤로 **어휘 때문에 갈리는 일은 사라진다.**
                남는 차이는 부정·제외·비교 같은 **문맥**뿐이고, 그건 모델만 읽을 수 있다.
                실측(2026-08-17, claude-haiku): 「배그 하고 싶어요」 -> 고사양 게임 ·
                「배그는 안 하고 롤만 해요」 -> 게임. 둘 다 정본과 문맥을 함께 지켰다.
         근거 ③ **정본은 여전히 강제된다.** 값은 `_norm_from_set` 이 `usage_label`
                집합 밖이면 버리고, 어휘 자체가 매 요청 DB에서 온다. 모델이 이기는 것은
                「어느 용도인가」의 판단뿐이고 「어떤 용도가 있는가」는 계속 표가 정한다.

     ⚠ 뒤집는다면(=서버가 원문 판정으로 덮어쓴다면) **부정문을 먼저 재라.** 그 층은
     「배그는 안 하고」를 «고사양 게임»으로 만든다.
  ② 선호 값 = 저소음 · 화이트 둘뿐. 근거는 `api/candidates._apply_one`이 **실제로
     거르는 태그가 그 둘뿐**이라는 것이다(`SILENT_SCOPE`·`WHITE_SCOPE`). 셋째를
     지어내면 화면이 "조건으로 잡았다"고 말하는데 후보 수는 안 변한다 —
     §화면 정직성이 금지하는 상태다.
  ③ 예산 값 = `api/candidates._budget_cap`이 읽는 모양(`N만`, '이상'은 상한 없음).
     그 함수가 못 읽는 표기를 내보내면 화면은 조건이 잡혔다고 하는데 서버는
     "영향 없음"을 돌려준다.

■ 지어내지 않는다 · 조용히 지우지 않는다
  프롬프트가 "문장에 없는 것을 만들지 말라"고 먼저 막고, 그 뒤 **검증층이 화이트
  리스트 밖의 값을 거른다.** 다만 거른 것을 **삼키지 않는다** — `dropped[]`에
  값과 사유를 그대로 실어 돌려준다(무엇이 왜 반영되지 않았는지 화면이 말할 수
  있어야 한다).
  모순되는 조건은 **둘 다 남긴다**(A-53 실측: "예산 50만원인데 4K 최고옵"은
  예산과 용도가 서로 다른 라벨이라 함께 산다). 어느 쪽이 이기는지는 이 층이
  정하지 않는다 — 엔진이 `budget.verdict`로 정직하게 말한다.

■ 대화 원문 — **2026-08-22 A-95 로 규약이 뒤집혔다**
  오래 이 자리는 「고객 문장을 어떤 표에도 적재하지 않는다」였다. 사장님이 뒤집었다
  (`docs/decisions/decision-log.md` **A-95**) — 질문을 쌓아 답변 패턴으로 재사용하기
  위해서다. 저장 자리는 `talk_intent_hits.raw_text` 이고, 설계는
  `docs/design/req/req-talk-patterns.md`.

  ⚠ **이 파일 자체는 아직 아무것도 저장하지 않는다** — 표가 없다(미구현).
  구현할 때 §0-1 의 장치 넷을 «함께» 세워야 한다: 저장 전 마스킹 · 보관 기간 뒤 삭제 ·
  owner 전용 읽기 · 고객 고지. 넷 없이 원문만 넣는 경로를 만들지 않는다.

  ⚠ **뒤집히지 않은 것 둘**:
    · 서버 로그에는 **여전히 문장을 찍지 않는다**(길이만) — 아래 `log.info` 참고.
      바뀐 것은 «표에 남기는 것»이지 «로그에 찍는 것»이 아니다.
    · `llm.py` 가 남기는 것은 `api_cost_logs` 의 프로바이더·모델·토큰·비용뿐이고,
      이 파일은 그 표에 아무것도 더 쓰지 않는다.

■ 실패를 삼키지 않는다
  LLM이 막히거나(캡) 전 프로바이더가 실패하면 **502로 올리고 detail에 사유를
  그대로 싣는다**(사장님 지시 2026-08-17). 조건을 지어내 성공한 척하지 않는다 —
  화면은 그때 "조건으로 못 읽었다"고 밝힌다.
  ⚠ 로그 문자열은 ASCII 기호만 쓴다 — 서버 stdout이 cp949라 em-dash·화살표가
  요청을 500으로 만든다(슬라이스 40 전례).
"""
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from sqlalchemy import text   # /monitor-bands 가 집계 쿼리를 돈다

from . import access_gate   # 방문자별 호출 횟수 제한의 단일 원천
from . import visitor      # 방문자 키 — 자동 승격의 「서로 다른 사람」 판정에 쓴다
# 회귀 표식 판정의 단일 원천. 언더스코어 함수를 다른 모듈이 가져다 쓰는 것은 이 저장소의
# 기존 관례다 — `api/expert.py` 가 같은 함수를 그렇게 쓴다(그 파일 상단 주석 참조).
from .recommend import _resolve_data_origin
from . import llm
from . import usage_floors as UF
from .db import engine

router = APIRouter(prefix="/api/talk", tags=["talk"])

log = logging.getLogger(__name__)

MAX_TEXT_LEN = 300
# 한 번의 파싱에 이 이상이 필요한 문장은 없다(라벨이 3종뿐이다). 모델이 목록을
# 길게 뱉어도 여기서 끊는다 -- 화면 조건 칩이 무한히 늘어나는 것을 막는 상한.
MAX_CONSTRAINTS = 6
LLM_TIMEOUT_SEC = 12          # 고객이 기다리는 자리다. 길게 잡지 않는다.
LLM_MAX_OUTPUT_TOKENS = 256   # JSON 한 덩어리면 충분하다(최악 비용 상한).

# 선호 어휘 -- `api/candidates.py`의 `_apply_one`이 실제로 거르는 태그 둘.
# 여기서 늘리려면 그 파일이 먼저 늘어야 한다(늘리지 않고 여기만 늘리면 화면이
# 조건을 잡았다고 말하는데 후보 수가 그대로다).
PREF_VALUES = ("저소음", "화이트")

# 예산 표기 -- `api/candidates._budget_cap`이 읽는 모양.
# ⚠ 2026-08-22 수정: 옛 정규식 `\d{2,4}`는 자릿수를 2~4자리로 못박아 다섯 자리 이상
# 예산을 서버에서 잘랐다(`api/candidates.py` `_budget_cap`이 같은 날 고친 것과 같은
# 결함 — 그 커밋이 이 파일을 「남은 구멍」으로 명시했다). 이 값은 LLM이 프롬프트
# 규격("숫자만원", `_build_prompt`의 라벨 1)대로 뽑아낸 **이미 라벨링된** 단일 값이라
# `mockups/mvp1/s1-session.html`의 `budgetSaid`·`talkBudget`과 같은 처지다(자유 문장을
# 통째로 훑는 `liveParse`가 아니다) — 그래서 그 둘과 같게 자릿수 하한도 두지 않는다.
# `api/candidates.py`와 같은 패턴으로 자릿수 상한을 없애고 콤마 구분 표기도 받는다.
_BUDGET_NUM = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*만")
_BUDGET_BOUND = re.compile(r"(이상|이하)")

LABELS = ("예산", "용도", "선호")


class ParseBody(BaseModel):
    text: str


def _usage_rows() -> list:
    """용도 정본 -> [(라벨, 그 용도를 가리키는 말들)]. 중복 제거 · 정렬 순서 유지.

    ⚠ **여기서 어휘를 만들지 않는다.** 라벨도 어휘도 전부 `usage_floors` 행에서 온다
    (`usage_label` · `match_terms`). 한 usage_key 에 하한 행이 여럿이라 같은 라벨이
    여러 번 나오는데, 어휘는 행마다 같으므로 **처음 만난 행의 것만** 쓴다.
    순서는 `UF._rows()`(sort_order, floor_id) 그대로다 -- 그 순서가 곧 우선순위이고
    ('고사양 게임'이 '게임'보다 앞), 프롬프트도 같은 순서로 보여야 모델이 좁은 쪽을
    먼저 본다(`api/usage_floors.list_usages` 의 §순서가 곧 우선순위와 같은 규약).
    """
    out: list = []
    seen: set = set()
    for r in UF._rows():
        lab = r.get("usage_label")
        if lab and lab not in seen:
            seen.add(lab)
            out.append((lab, [t for t in (r.get("match_terms") or []) if t]))
    return out


def _build_prompt(text: str, usage_rows: list) -> str:
    """매 요청마다 접는다 -- 용도 어휘가 DB에서 바뀌면 다음 요청부터 반영된다."""
    # 라벨만 주면 모델은 '배그'가 어느 용도인지 알 방법이 없어 **추론한다**(실측:
    # 「배그 하고 싶어요」 -> 용도 «게임», 정본은 «고사양 게임»). 정본이 이미 그 답을
    # 갖고 있으므로(`match_terms`) 라벨과 함께 넘긴다 -- 여기 목록을 박지 않는다.
    usage_line = " / ".join(
        "%s(%s)" % (lab, ", ".join(terms)) if terms else lab for lab, terms in usage_rows
    ) if usage_rows else "(지금 정의된 용도가 없다)"
    # 예시도 표에서 뽑는다 -- '배그 -> 고사양 게임' 을 문자열로 박으면 표에서 그 말이
    # 빠진 날 프롬프트만 옛 어휘로 가르친다(이 파일이 오늘 고친 병과 같은 모양이다).
    # 고를 때는 «이름과 안 닮은» 말을 먼저 본다(글자가 하나도 안 겹치는 것) --
    # '고사양게임 -> 고사양 게임' 처럼 띄어쓰기만 다른 예시는 아무것도 안 가르친다.
    pairs = [(lab, t) for lab, terms in usage_rows for t in terms if t != lab]
    ex = next((p for p in pairs if not (set(p[1]) & set(p[0]))), None) or (
        pairs[0] if pairs else None)
    ex_line = ('   예: 문장에 "%s" 가 있으면 값은 "%s" 로 적는다.' % (ex[1], ex[0])) if ex else None
    # 표에 어휘가 하나도 없으면 예시가 없다 -- 그 줄만 빠진다(문단 사이 빈 줄 ""은 남긴다).
    return "\n".join(ln for ln in [
        "당신은 PC 견적 상담의 «입력 파서»다. 고객 문장을 두 가지로만 바꾼다 --",
        "① 이 문장이 PC 상담인가(pc) ② 문장에서 읽히는 구조화 조건(constraints).",
        "",
        "[절대 금지]",
        "- 부품 이름·가격·후보 수·견적을 말하지 않는다. 그것은 다른 시스템이 한다.",
        "- 문장에 없는 예산·용도·선호를 만들지 않는다. 없으면 그 항목을 아예 빼라.",
        "- 문장이 모순되어도(예: 예산은 낮은데 최고 사양 요구) 한쪽을 지우지 않는다."
        " 읽히는 대로 둘 다 넣는다.",
        "- 추측·보완·친절한 해석을 하지 않는다. 적힌 것만 옮긴다.",
        "",
        "[출력 형식] JSON 하나만 출력한다. 설명·코드블록·앞뒤 문장을 붙이지 않는다.",
        '{"pc":true,"constraints":[{"l":"라벨","v":"값"}]}',
        "두 항목은 **언제나 함께** 넣는다. pc 는 true/false 중 하나이며 문자열이 아니다.",
        "조건으로 읽을 것이 없으면 constraints 를 빈 목록으로 두되 pc 는 그대로 판정한다.",
        "",
        "[pc -- 이 문장이 PC 상담인가]",
        "여기는 PC(컴퓨터) 견적 상담 창구다. 고객은 컴퓨터를 사거나 고치러 온 사람이다.",
        "- true: 컴퓨터·부품·게임·용도·예산·구매·조립·업그레이드·호환·재고·배송·가격·A/S 중"
        " 하나라도 걸리는 문장.",
        "  **모니터·키보드·마우스·헤드셋·스피커 같은 주변기기 문의도 true 다** -- 우리는 그것도"
        " 판다(견적서의 「함께 쓰면 좋은 구성」). 실측 2026-08-22: 「모니터 추천해줘」가"
        " false 로 판정돼 상담이 끊겼다.",
        "  **무엇을 살지 밝히지 않은 막연한 요청도 true 다** -- 예: \"그냥 좋은 거"
        " 추천해주세요\", \"본체 하나 맞춰주세요\", \"겜만 할래요\", \"모르겠어요\".",
        "  구어·줄임말·오타여도 뜻이 PC 상담이면 true 다(겜 = 게임, 컴 = 컴퓨터, 본체 = PC).",
        "- false: PC 와 **분명히** 무관한 주제일 때만이다 -- 날씨·요리·연애·정치·건강·"
        "여행·번역·일반 지식 질문 등.",
        "- 애매하면 true 다. false 는 상담을 그 자리에서 끊는 판정이라 확실할 때만 쓴다.",
        "",
        "[쓸 수 있는 라벨과 값 -- 이 목록 밖의 값은 쓰지 않는다]",
        '1. l="예산"  v: "숫자만원" 형식. 예 "150만원".',
        '   "이상"·"이하"는 고객이 실제로 그렇게 말했을 때만 붙인다'
        '("150만원 이상", "100만원 이하").',
        '   "쯤"·"정도"·"안팎"처럼 대략을 뜻하는 말은 경계가 아니다 -- 그냥 "150만원"으로 적는다.',
        "   금액이 문장에 없으면 이 항목을 넣지 않는다.",
        f'2. l="용도"  v: 다음 중에서만 고른다 -- {usage_line}',
        "   **괄호 안은 그 용도를 가리키는 말이다**(서버 정본). 문장에 그 말이 있으면"
        " 괄호가 아니라 **앞의 이름**을 값으로 적는다.",
        ex_line,
        "   여러 이름의 말이 함께 있으면 **문장이 실제로 하겠다는 쪽**을 적는다 --"
        " 부정·제외된 말(\"~는 안 하고\" · \"~ 말고\")은 그 용도로 세지 않는다.",
        "   둘 이상이면 \" · \" 로 잇는다. 목록에 없는 용도는 넣지 않는다.",
        f'3. l="선호"  v: 다음 중에서만 고른다 -- {" / ".join(PREF_VALUES)}',
        "   둘 다면 \"저소음 · 화이트\". 그 밖의 선호(성능·크기·브랜드 등)는 넣지 않는다.",
        "",
        "[고객 문장]",
        text,
    ] if ln is not None)


def _norm_budget(v: str):
    """예산 값 정규화 -- (값, None) 또는 (None, 사유)."""
    m = _BUDGET_NUM.search(v)
    if not m:
        return None, "금액을 읽을 수 없는 예산 표기입니다"
    b = _BUDGET_BOUND.search(v)
    # 천단위 콤마로 «표시»한다(2026-08-22 사장님 지시) -- "1500만원"이 아니라 "1,500만원".
    # 이 값은 조건 칩으로 고객에게 그대로 보이면서 동시에 파서 입력이기도 한데, 소비처
    # 둘 다 콤마를 이미 받는다(실측): api/candidates._budget_cap 은 `\d{1,3}(?:,\d{3})+|\d+`
    # 로 읽고 int 변환 전에 콤마를 지우고, 화면 budgetSaid()(s1-session.html)도 같은 패턴에
    # `replace(/,/g,'')` 다. 그래서 표시를 바꿔도 상한 계산·범위 마커가 깨지지 않는다.
    # 일단 콤마를 지워 int 로 만든 뒤 다시 넣는다 -- 입력이 "1,500"이든 "1500"이든 같은 표기가
    # 나와야 한다(입력 표기가 화면에 새어 나가면 같은 예산이 두 모양으로 보인다).
    n = int(m.group(1).replace(",", ""))
    return format(n, ",") + "만원" + (" " + b.group(1) if b else ""), None


def _norm_from_set(v: str, allowed: list, kind: str):
    """' · '로 이어진 값에서 허용 목록에 있는 것만 남긴다 -- (값, 사유).

    ⚠ 넓은 값이 좁은 값의 부분문자열인 경우('게임' ⊂ '고사양 게임') 넓은 쪽을
    버린다. 화면의 `liveParse`가 같은 처리를 하고(s1-session.html:846), 서버
    `usage_floors.match`도 **먼저 맞는 usage_key 하나만** 쓴다 -- 둘 다 남기면
    조건 칩만 "고사양 게임 · 게임"으로 지저분해지고 실제 하한은 하나뿐이라
    화면과 서버가 다른 말을 하는 꼴이 된다.
    """
    if not allowed:
        return None, f"서버에 정의된 {kind} 어휘가 없습니다"
    picked = [a for a in allowed if a in v]
    picked = [a for a in picked if not any(a != b and a in b for b in picked)]
    if not picked:
        return None, f"서버가 아는 {kind} 어휘가 아닙니다"
    return " · ".join(picked), None


def _extract_json(raw: str) -> dict:
    """모델 응답에서 JSON 한 덩어리를 꺼낸다. 못 꺼내면 ValueError."""
    s = (raw or "").strip()
    if s.startswith("```"):                       # ```json ... ``` 울타리 제거
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object in response")
    obj = json.loads(s[i:j + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON root is not an object")
    return obj


def _pc_verdict(obj: dict):
    """모델이 말한 「PC 상담인가」 -> True · False · **None(모름)**.

    ⚠ **bool 이 아니면 None 이다.** 필드가 없거나 형식이 틀린 것을 `False` 로 접으면
    정상 문의가 반송된다 -- 「모델이 «PC 아님»이라 답한 것만 반송한다」(사장님 지시
    2026-08-17)를 코드로 지키는 자리가 여기다. 문자열 "true"/"false" 는 모델이 흔히
    내는 형태라 받아 주되, 그 밖은 전부 모름이다.
    """
    v = obj.get("pc")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().strip('"').lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
    return None


def _validate(raw_items, usages: list) -> tuple:
    """모델이 준 목록 -> (반영할 제약, 버린 것 + 사유).

    **버린 것을 삼키지 않는다** -- 사유와 함께 돌려줘 화면이 말할 수 있게 한다.
    """
    kept: list = []
    dropped: list = []
    seen: set = set()
    if not isinstance(raw_items, list):
        return kept, [{"l": None, "v": None, "reason": "응답의 constraints가 목록이 아닙니다"}]
    for it in raw_items[:MAX_CONSTRAINTS * 2]:
        if not isinstance(it, dict):
            dropped.append({"l": None, "v": None, "reason": "항목 형식이 올바르지 않습니다"})
            continue
        lab = str(it.get("l") or "").strip()
        val = str(it.get("v") or "").strip()
        if not lab or not val:
            dropped.append({"l": lab or None, "v": val or None, "reason": "라벨 또는 값이 비었습니다"})
            continue
        if lab not in LABELS:
            dropped.append({"l": lab, "v": val,
                            "reason": "서버가 조건으로 다루지 않는 항목입니다"})
            continue
        if lab in seen:
            dropped.append({"l": lab, "v": val,
                            "reason": "같은 항목이 두 번 나와 첫 값만 반영했습니다"})
            continue
        if lab == "예산":
            norm, why = _norm_budget(val)
        elif lab == "용도":
            norm, why = _norm_from_set(val, usages, "용도")
        else:
            norm, why = _norm_from_set(val, list(PREF_VALUES), "선호")
        if norm is None:
            dropped.append({"l": lab, "v": val, "reason": why})
            continue
        seen.add(lab)
        kept.append({"l": lab, "v": norm})
        if len(kept) >= MAX_CONSTRAINTS:
            break
    return kept, dropped


@router.post("/parse")
def parse_talk(body: ParseBody, request: Request):
    """고객 문장 -> (PC 상담인가) + 조건 목록. 부품·가격·후보 수는 말하지 않는다(A-01·A-02).

    화면은 **모든 문장**을 이 경로로 보낸다(2026-08-17 결정 뒤집기 -- 모듈 docstring).
    실패는 502로 올라가고 화면은 "AI가 조건으로 못 읽었다"고 밝히며 정규식 결과만
    반영한다 -- 조건을 지어내지 않는다.

    ■ 응답이 «반송해야 하는 문장»과 «조건이 없는 문장»을 가른다
      `pc_related` 가 **`false` 일 때만** 화면이 「PC 상담 전용」 안내로 반송한다.
      `true` 이고 `constraints` 가 비었으면 그것은 「PC 얘기지만 조건이 없다」이고
      (예: "그냥 좋은 거 추천해주세요") 화면은 무엇을 말해 주면 되는지 안내한다.
      `null` 은 **모름**이다 -- 반송하지 않는다. 502(전 프로바이더 실패·한도·키 없음)
      도 마찬가지로 판정이 아니다. 이 셋을 한 응답으로 뭉개면 정상 문의가 끊긴다.

    ■ 방문자별 호출 횟수 제한 (2026-08-17 사장님 확정 -- 세 구멍 중 ②)
      이 경로는 인증 요구가 0 이라 **한 사람이 프로바이더 하루치(기본 일 500 · $2)를
      혼자 태울 수 있었다.** 축·한도·근거는 `api/access_gate` 에 한 벌로 있다
      (여기서 다시 정의하지 않는다 -- CANON §1).
      소유자 개념이 없는 자리라 403 은 없고 **429 만** 난다.

    응답 규약(추가분)
      200 {ok, constraints[], dropped[], pc_related: true|false|null, note, ...}
      429 {error:"rate_limited", scope:"visitor", window:"minute"|"day",
           used, limit, retry_after_sec, detail}  + `Retry-After` 헤더
    """
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "문장이 비었습니다")
    if len(text) > MAX_TEXT_LEN:
        raise HTTPException(400, f"문장이 너무 깁니다(최대 {MAX_TEXT_LEN}자)")

    # 입력 검사 뒤 · LLM 호출 앞. 형식이 틀린 요청(400)은 비용이 없어 세지 않는다.
    with engine.connect() as conn:
        access_gate.check_rate(conn, request, what="talk.parse")

    usage_rows = _usage_rows()
    usages = [lab for lab, _terms in usage_rows]
    prompt = _build_prompt(text, usage_rows)
    # 문장 자체는 로그에 남기지 않는다(원문 비적재 규약) -- 길이만 남긴다.
    # terms 는 프롬프트에 실린 정본 어휘 수다 -- 표가 늘면 프롬프트도 길어지므로
    # (비용) 여기서 세어 둔다. 어휘 자체는 찍지 않는다(로그는 ASCII 기호만).
    log.info("[talk] parse request: chars=%d usages=%d terms=%d", len(text), len(usages),
             sum(len(t) for _lab, t in usage_rows))

    try:
        result = llm.call(prompt, task_key="task.s1_parse", customer_facing=True,
                          max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                          timeout_sec=LLM_TIMEOUT_SEC)
    except llm.LLMBlockedError as e:
        raise HTTPException(502, f"AI 파싱이 한도에 걸렸습니다({e.kind}/{e.provider}) - {e}")
    except llm.LLMAllProvidersFailedError as e:
        raise HTTPException(502, f"AI 파싱에 실패했습니다 - 연동된 프로바이더가 모두 실패: {e}")
    except llm.LLMNotConfiguredError as e:
        raise HTTPException(502, f"AI 연동이 설정되지 않았습니다 - {e}")
    except llm.LLMProviderError as e:
        raise HTTPException(502, f"AI 파싱에 실패했습니다 - {e}")

    try:
        obj = _extract_json(result.text)
    except Exception as e:
        # 모델이 형식을 어긴 것도 실패다 -- 빈 조건으로 뭉개면 "못 읽었다"와
        # "AI가 깨졌다"를 화면이 구분하지 못한다.
        log.warning("[talk] non-JSON response from %s/%s: %s",
                    result.provider, result.model, e)
        raise HTTPException(502, f"AI 응답을 조건으로 읽지 못했습니다 - {e}")

    kept, dropped = _validate(obj.get("constraints"), usages)
    pc = _pc_verdict(obj)
    log.info("[talk] parse done: provider=%s pc=%s kept=%d dropped=%d elapsed=%.2fs",
             result.provider, "none" if pc is None else ("yes" if pc else "no"),
             len(kept), len(dropped), result.elapsed_sec)
    if pc is None:
        # 삼키지 않는다 -- 판정을 못 얻은 것도 사실이므로 로그에 남긴다. 화면은 이때
        # 반송하지 않고 「조건이 없다」쪽으로만 안내한다(정상 문의를 끊지 않는다).
        log.warning("[talk] no pc verdict in response from %s/%s - treated as unknown",
                    result.provider, result.model)

    # 「PC 아님」과 「PC 얘기지만 조건이 없다」는 **다른 사실**이라 다른 문장을 준다.
    # 이 note 는 화면 상단 진행 바가 그대로 읽어 쓴다(shared/ui-progress.js okText).
    if pc is False and not kept:
        note = "PC 상담 문장이 아니라고 판정했습니다."
    elif not kept:
        note = "조건으로 읽을 수 있는 내용이 없습니다."
    else:
        note = None

    # 질문을 원장에 남긴다(A-95). 실패해도 상담을 끊지 않는다 -- `_record_hit` 주석.
    # 지금은 `talk_intents` 가 비어 있어 intent_key 가 NULL 로 들어간다 -- 그것이
    # 「우리가 아직 답을 못 만든 질문」이고 이 표의 존재 이유다.
    with engine.begin() as conn:
        _record_hit(conn, request=request, text_raw=text, matched=[l for l, _v in
                    [(c["l"], c["v"]) for c in kept]], unmatched_n=len(dropped),
                    intent_key=None, answer_kind="constraint_parse", llm_called=True)

    return {
        "ok": True,
        "constraints": kept,
        "dropped": dropped,
        # true | false | null(모름). null 을 false 로 읽지 않는 것이 규약이다.
        "pc_related": pc,
        "note": note,
        "provider": result.provider, "model": result.model,
        "elapsed_sec": result.elapsed_sec, "cost_usd": result.cost_usd,
        # A-95 로 «표에는» 남긴다(talk_intent_hits · 마스킹 후). 이 필드가 뜻하는 것은
        # 여전히 「이 응답이 상담 원장(consult_sessions)을 만들지 않았다」이다.
        "stored": False,
    }


# ── 모니터 크기 구간 ────────────────────────────────────────────────────────────
# 2026-08-22 사장님 지시: 「모니터 추천해줘」에 되묻지 말고 24 / 27 / 32인치를 사양과 함께
# 바로 보여준다. 그전에는 AI 가 이 문장을 **「PC 상담이 아니다」로 반송**했다(실측 응답
# `pc_related:false`) — 프롬프트가 "애매하면 true" 라고 시켜 놨는데도 그랬다.
#
# ⚠ 수를 화면이 세지 않는다(CLAUDE.md §화면 정직성). 구간·건수·가격대·대표 해상도를 전부
# 여기서 계산해 내려보낸다. 화면은 받은 것만 그린다.
#
# ⚠ 구간 경계는 **반올림**이다 — 23.8형은 시장에서 「24인치」로 판다. 저장은 원문 그대로의
# 정확한 값(23.8)이고 묶을 때만 반올림한다.
#
# ⚠ 하한을 0 으로 두면 23인치 이하가 24인치 구간에도 들어가고 `excluded` 에도 들어가
# **이중으로 세어진다**(실측: 24인치가 129 가 아니라 174 로 나왔다 — 45 가 겹쳤다).
# 구간과 제외는 겹치지 않아야 하고, 셋의 합 + excluded = 재고 모니터 전체여야 한다.
MONITOR_BANDS = (
    ("24", "24인치", 24, 25),       # 23.8·24.5 는 반올림으로 여기 묶인다
    ("27", "27인치", 26, 29),
    ("32", "32인치 이상", 30, 999),
)


@router.get("/monitor-bands")
def monitor_bands():
    """모니터를 크기 구간으로 묶어 돌려준다 — 되묻지 않고 바로 보여주기 위한 것.

    ■ 무엇을 세나
      재고가 있는 것만(`stock_qty > 0`). 화면이 「지금 살 수 있는 것」을 말해야 하기 때문이다.

    ■ 없는 값은 지어내지 않는다
      해상도·주사율이 비어 있으면 **그 항목을 빼고** 센다(2026-08-22 사장님 확정:
      *"해상도가 없으면 해당 항목은 빼도 됩니다"*). 몇 건이 비었는지는 `res_unknown` 으로
      함께 내려보내 화면이 「전부 안다」고 말하지 않게 한다.

    ■ 23인치 이하는 구간에서 뺀다
      재고가 있지만 대부분 CCTV·산업용 소형이고(15·17·19형), 고객이 「모니터 추천」으로
      기대하는 물건이 아니다. 빼되 **`excluded` 로 그 수를 밝힌다** — 조용히 감추지 않는다.
    """
    out = []
    with engine.connect() as conn:
        for key, label, lo, hi in MONITOR_BANDS:
            row = conn.execute(text("""
                SELECT COUNT(*) AS n,
                       MIN(sale_price) AS lo, MAX(sale_price) AS hi,
                       COUNT(resolution) AS res_known,
                       MAX(refresh_hz) AS hz_max,
                       SUM(CASE WHEN refresh_hz >= 144 THEN 1 ELSE 0 END) AS hz144
                  FROM v_companion_candidates
                 WHERE part_type = 'MONITOR' AND stock_qty > 0
                   AND size_inch IS NOT NULL
                   AND ROUND(size_inch) BETWEEN :lo AND :hi
            """), {"lo": lo, "hi": hi}).mappings().first()
            if not row or not row["n"]:
                continue
            # 대표 해상도 — 그 구간에서 가장 흔한 것 둘. 비어 있는 것은 세지 않는다.
            tops = conn.execute(text("""
                SELECT resolution AS v, COUNT(*) AS n
                  FROM v_companion_candidates
                 WHERE part_type = 'MONITOR' AND stock_qty > 0
                   AND size_inch IS NOT NULL AND resolution IS NOT NULL
                   AND ROUND(size_inch) BETWEEN :lo AND :hi
                 GROUP BY 1 ORDER BY 2 DESC LIMIT 2
            """), {"lo": lo, "hi": hi}).mappings().all()
            out.append({
                "key": key, "label": label,
                "count": int(row["n"]),
                "price_min": int(row["lo"]) if row["lo"] is not None else None,
                "price_max": int(row["hi"]) if row["hi"] is not None else None,
                "resolutions": [{"v": t["v"], "n": int(t["n"])} for t in tops],
                "res_unknown": int(row["n"]) - int(row["res_known"]),
                "hz_max": int(row["hz_max"]) if row["hz_max"] is not None else None,
                "hz144": int(row["hz144"] or 0),
            })
        excluded = conn.execute(text("""
            SELECT COUNT(*) FROM v_companion_candidates
             WHERE part_type = 'MONITOR' AND stock_qty > 0
               AND (size_inch IS NULL OR ROUND(size_inch) <= 23)
        """)).scalar()
    return {"ok": True, "bands": out, "excluded": int(excluded or 0)}


# ── 질문 이력 기록 (A-95·A-96 · 0061) ──────────────────────────────────────────
# 정의서 `docs/design/req/req-talk-patterns.md` · 표 `talk_intent_hits`.
#
# 사장님 확정값 둘을 **여기가 든다** — 표에 박지 않는다(표에 적으면 바꿀 때
# 마이그레이션이 필요해진다).
RAW_KEEP_DAYS = 90            # 원문 보관 기간(A-95 §0-1 ㉯)
AUTO_PROMOTE_VISITORS = 5     # 자동 승격 임계 — «서로 다른» 방문자 수(A-96 §0-2 ㉯)

# ■ 마스킹 — 저장 «전»에 지운다 (A-95 §0-1 ㉮)
#   지어내는 것이 아니라 «지우는» 것이라 A-02(재현성)와 무관하다.
#   ⚠ 계좌는 «하이픈이 있는 것만» 본다. `\d{10,16}` 같은 순수 숫자 패턴을 쓰면
#     「12000000원」 같은 예산 표기를 계좌로 오인해 고객이 말한 조건을 지운다.
#     못 지우는 계좌가 남는 것보다 «조건을 지우는» 쪽이 더 나쁜 결함이라 보수적으로 잡는다.
_MASKS = (
    (re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"), "[주민번호]"),
    (re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}"), "[전화번호]"),
    (re.compile(r"0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}"), "[전화번호]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "[이메일]"),
    (re.compile(r"\d{2,6}-\d{2,6}-\d{2,7}"), "[계좌번호]"),
)


def mask_pii(s: str) -> str:
    """개인정보로 보이는 조각을 치환한다. 실패하지 않는다 — 못 지우면 그대로 둔다.

    ⚠ 이 함수가 예외를 던지면 `_record_hit` 이 원문을 통째로 버린다(아래).
    「마스킹 없는 원문을 넣는 경로를 만들지 않는다」가 DB CHECK(`ck_talk_hits_masked`)
    로도 걸려 있어, 여기가 뚫려도 표에는 못 들어간다.
    """
    out = s or ""
    for pat, rep in _MASKS:
        out = pat.sub(rep, out)
    return out


def _record_hit(conn, *, request, text_raw, matched, unmatched_n,
                intent_key, answer_kind, llm_called, session_id=None):
    """질문 한 건을 원장에 남긴다. **실패해도 상담을 끊지 않는다.**

    이 기록은 부가 기능이다 — 여기서 예외가 나 고객 응답이 500 이 되면 본말이 전도된다.
    그래서 전부 삼키고 로그만 남긴다(로그에도 문장은 안 찍는다 — 길이만).

    ■ intent_key 는 지금 거의 항상 NULL 이다
      `talk_intents` 가 아직 비어 있기 때문이다(TALKS 20종 이관 = 다음 단계).
      **그것이 정상이고, 그 행이 이 표의 존재 이유다** — 「우리가 아직 답을 못 만든 질문」.
    """
    try:
        origin = _resolve_data_origin(request)
        try:
            uid = visitor.resolve(conn, request, None)   # response 미전달 = 쿠키 안 심는다
        except Exception:                                # noqa: BLE001
            uid = None
        raw = None
        try:
            raw = mask_pii(text_raw) if text_raw else None
        except Exception:                                # noqa: BLE001
            raw = None                                   # 마스킹이 실패하면 원문을 버린다
        conn.execute(text("""
            INSERT INTO talk_intent_hits
                (session_id, intent_key, matched_terms, unmatched_n,
                 raw_text, raw_masked_yn, raw_purge_at,
                 visitor_key, answer_kind, llm_called, data_origin)
            VALUES (:sid, :ik, CAST(:mt AS JSONB), :un,
                    :raw, :masked, :purge,
                    :vk, :ak, :llm, :origin)
        """), {
            "sid": session_id, "ik": intent_key,
            "mt": json.dumps(matched or [], ensure_ascii=False),
            "un": int(unmatched_n or 0),
            "raw": raw,
            "masked": raw is not None,
            # 원문이 있으면 삭제 예정 시각이 «반드시» 있어야 한다(ck_talk_hits_purge).
            "purge": None if raw is None else _purge_at(),
            "vk": None if uid is None else str(uid),
            "ak": answer_kind, "llm": bool(llm_called), "origin": origin,
        })
    except Exception as e:                               # noqa: BLE001
        log.warning("[talk] hit record failed (chars=%d): %s",
                    len(text_raw or ""), type(e).__name__)


def _purge_at():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=RAW_KEEP_DAYS)).replace(tzinfo=None)


class HitBody(BaseModel):
    text: str
    intent_key: str | None = None
    answer_kind: str | None = None


@router.post("/hit")
def record_hit(body: HitBody, request: Request):
    """화면이 «서버를 안 거치고» 답한 질문을 알린다 — 그것도 원장에 남기기 위해서다.

    ■ 왜 필요한가
      모니터 구간(`monitorBands`)·인사말처럼 화면이 조기 처리하는 경로는 `/parse` 를
      부르지 않는다. 그대로 두면 **가장 잘 답한 질문이 기록에서 빠진다** — 「무엇을
      묻는지」를 모으는 표인데 정작 답이 있는 질문만 사라지는 셈이다.

    ■ 이 경로는 LLM 을 태우지 않는다
      그래서 `access_gate` 의 AI 한도를 쓰지 않는다. 다만 아무나 부를 수 있는 자리라
      원문 길이 상한(`MAX_TEXT_LEN`)은 그대로 건다.
    """
    t = (body.text or "").strip()
    if not t:
        raise HTTPException(400, "문장이 비었습니다")
    if len(t) > MAX_TEXT_LEN:
        raise HTTPException(400, f"문장이 너무 깁니다(최대 {MAX_TEXT_LEN}자)")
    with engine.begin() as conn:
        _record_hit(conn, request=request, text_raw=t, matched=[], unmatched_n=0,
                    intent_key=body.intent_key, answer_kind=body.answer_kind,
                    llm_called=False)
    return {"ok": True}
