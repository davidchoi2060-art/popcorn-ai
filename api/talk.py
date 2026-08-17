"""S1 자유입력 파싱(POST /api/talk/parse) — 문장을 «조건»으로만 바꾼다.

`api/main.py`가 자동으로 싣는다(pkgutil 1단계 스캔 — 등록 코드 없음).

■ 무엇을 하는 자리인가
  고객이 S1에서 자연어로 말한 문장을 화면이 이미 쓰는 제약 형태(`{l, v}` —
  정본은 `api/candidates.Constraint`)로 바꾼다. **그것 하나만 한다.**

■ 지키는 결정
  - A-01·A-02·A-03: **LLM은 견적을 만들지 않는다.** 이 모듈은 부품·가격·후보 수를
    한 글자도 말하지 않는다. 구조적으로도 못 한다 — 응답 스키마가 라벨 3종
    (예산·용도·선호)과 **미리 정해진 값 집합**뿐이라 부품명이 들어올 칸이 없다.
    후보 수는 여전히 `/api/candidates/count`만이 답한다.
  - **정규식 먼저, 못 읽은 문장만 AI**(2026-08-17 사장님 확정). 이 엔드포인트는
    화면의 `liveParse`가 **아무것도 못 뽑았을 때만** 불린다 — 하나라도 뽑았으면
    부르지 않는다(비용 0 · 기존 동작 보존). 그 판단은 화면이 한다
    (`mockups/mvp1/s1-session.html`의 `srvParse` 호출 지점 주석 참고).

■ 어휘를 여기서 새로 정의하지 않는다 (CANON §1 — 정본을 복제하지 않는다)
  ① 용도 값 = `api/usage_floors`의 `usage_label` 집합. **요청마다 읽는다** —
     운영자가 `usage_floors`를 고치면 다음 요청부터 반영된다. 여기에 목록을 박아
     두면 표가 늘어난 날 화면만 옛 어휘로 말한다.
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

■ 대화 원문을 저장하지 않는다
  선례 = `api/admin_ops_assistant.py`. 이 모듈도 고객 문장을 어떤 표에도 적재하지
  않는다. `llm.py`가 남기는 것은 `api_cost_logs`의 프로바이더·모델·토큰·비용뿐이고,
  이 파일은 그 표에 아무것도 더 쓰지 않는다. 서버 로그에도 **문장을 찍지 않는다**
  (길이만 남긴다).

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

from . import access_gate   # 방문자별 호출 횟수 제한의 단일 원천
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
_BUDGET_NUM = re.compile(r"(\d{2,4})\s*만")
_BUDGET_BOUND = re.compile(r"(이상|이하)")

LABELS = ("예산", "용도", "선호")


class ParseBody(BaseModel):
    text: str


def _usage_values() -> list:
    """지금 서버가 실제로 하한을 갖고 있는 용도 라벨(중복 제거, 정렬 순서 유지)."""
    out = []
    for r in UF._rows():
        lab = r.get("usage_label")
        if lab and lab not in out:
            out.append(lab)
    return out


def _build_prompt(text: str, usages: list) -> str:
    """매 요청마다 접는다 -- 용도 어휘가 DB에서 바뀌면 다음 요청부터 반영된다."""
    usage_line = " / ".join(usages) if usages else "(지금 정의된 용도가 없다)"
    return "\n".join([
        "당신은 PC 견적 상담의 «입력 파서»다. 고객 문장을 구조화 조건으로 바꾸는 일만 한다.",
        "",
        "[절대 금지]",
        "- 부품 이름·가격·후보 수·견적을 말하지 않는다. 그것은 다른 시스템이 한다.",
        "- 문장에 없는 예산·용도·선호를 만들지 않는다. 없으면 그 항목을 아예 빼라.",
        "- 문장이 모순되어도(예: 예산은 낮은데 최고 사양 요구) 한쪽을 지우지 않는다."
        " 읽히는 대로 둘 다 넣는다.",
        "- 추측·보완·친절한 해석을 하지 않는다. 적힌 것만 옮긴다.",
        "",
        "[출력 형식] JSON 하나만 출력한다. 설명·코드블록·앞뒤 문장을 붙이지 않는다.",
        '{"constraints":[{"l":"라벨","v":"값"}]}',
        "읽을 것이 하나도 없으면 정확히 이렇게 출력한다: {\"constraints\":[]}",
        "",
        "[쓸 수 있는 라벨과 값 -- 이 목록 밖의 값은 쓰지 않는다]",
        '1. l="예산"  v: "숫자만원" 형식. 예 "150만원".',
        '   "이상"·"이하"는 고객이 실제로 그렇게 말했을 때만 붙인다'
        '("150만원 이상", "100만원 이하").',
        '   "쯤"·"정도"·"안팎"처럼 대략을 뜻하는 말은 경계가 아니다 -- 그냥 "150만원"으로 적는다.',
        "   금액이 문장에 없으면 이 항목을 넣지 않는다.",
        f'2. l="용도"  v: 다음 중에서만 고른다 -- {usage_line}',
        "   둘 이상이면 \" · \" 로 잇는다. 목록에 없는 용도는 넣지 않는다.",
        f'3. l="선호"  v: 다음 중에서만 고른다 -- {" / ".join(PREF_VALUES)}',
        "   둘 다면 \"저소음 · 화이트\". 그 밖의 선호(성능·크기·브랜드 등)는 넣지 않는다.",
        "",
        "[고객 문장]",
        text,
    ])


def _norm_budget(v: str):
    """예산 값 정규화 -- (값, None) 또는 (None, 사유)."""
    m = _BUDGET_NUM.search(v)
    if not m:
        return None, "금액을 읽을 수 없는 예산 표기입니다"
    b = _BUDGET_BOUND.search(v)
    return m.group(1) + "만원" + (" " + b.group(1) if b else ""), None


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
    """고객 문장 -> 조건 목록. 부품·가격·후보 수는 말하지 않는다(A-01·A-02).

    화면은 정규식 파서가 0건일 때만 이 경로를 부른다. 실패는 502로 올라가고
    화면은 "조건으로 못 읽었다"고 밝힌다 -- 조건을 지어내지 않는다.

    ■ 방문자별 호출 횟수 제한 (2026-08-17 사장님 확정 -- 세 구멍 중 ②)
      이 경로는 인증 요구가 0 이라 **한 사람이 프로바이더 하루치(기본 일 500 · $2)를
      혼자 태울 수 있었다.** 축·한도·근거는 `api/access_gate` 에 한 벌로 있다
      (여기서 다시 정의하지 않는다 -- CANON §1).
      소유자 개념이 없는 자리라 403 은 없고 **429 만** 난다.

    응답 규약(추가분)
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

    usages = _usage_values()
    prompt = _build_prompt(text, usages)
    # 문장 자체는 로그에 남기지 않는다(원문 비적재 규약) -- 길이만 남긴다.
    log.info("[talk] parse request: chars=%d usages=%d", len(text), len(usages))

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
    log.info("[talk] parse done: provider=%s kept=%d dropped=%d elapsed=%.2fs",
             result.provider, len(kept), len(dropped), result.elapsed_sec)

    return {
        "ok": True,
        "constraints": kept,
        "dropped": dropped,
        "note": ("조건으로 읽을 수 있는 내용이 없습니다." if not kept else None),
        "provider": result.provider, "model": result.model,
        "elapsed_sec": result.elapsed_sec, "cost_usd": result.cost_usd,
        "stored": False,   # 대화 원문은 어디에도 저장하지 않는다
    }
