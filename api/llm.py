"""LLM 호출 래퍼 -- 모든 프로바이더 호출이 지나는 단일 자리.

■ 이번 범위 (2026-08-16 사장님 승인 -- "일단 제미나이부터", 같은 날 3사로 확장)
  이 모듈은 **호출하는 자리를 만드는 것까지**다. 신설 당시(2026-08-16, 이 파일이 생긴
  그날)는 어디에 쓸지(팝콘톡 S1 파싱 / S2 근거 설명)가 다음 단계라 이 파일은 어떤
  화면·엔드포인트에서도 불려오지 않았다(import하는 곳 0곳 -- `api/main.py`의 라우터
  자동 탐색이 이 모듈을 실어 보긴 하지만, module-level `router`가 없어
  `_DISCOVERED_ROUTERS`에는 안 잡힌다).

  ⚠ **이 "0곳"은 그날 하루짜리 사실이었다 -- 지금은 낡았다.** 바로 다음 날
  (2026-08-17) 세 슬라이스가 실제 호출부를 붙였고(`git blame` 확인 -- 커밋
  `4cf376c`가 talk.py·recommend.py 둘을, `6408529`가 admin_ops_assistant.py를
  붙였다), 이 문단은 그 뒤로 갱신되지 않은 채 8일(2026-08-25 재확인 기준) 동안
  "0곳"을 지금 사실인 것처럼 말하고 있었다 -- 문서가 스스로 낡았다고 말해 주지
  않는다는 이 저장소의 흔한 병(`CLAUDE.md` 참고)이 이 파일 docstring에도 났다.
  **지금(2026-08-25, `grep -rn "llm\.call(\|task_key=" api/*.py` + `git blame`로
  직접 재확인) 실제 호출부는 셋이다**:

      api/talk.py:535                    task.s1_parse    (팝콘톡 자유입력 파싱)
      api/recommend.py:1546              task.s2_explain  (견적 근거 설명)
      api/admin_ops_assistant.py:690     task.ops_assist  (운영 도우미)

  (task.spec_fill은 아래 TASK_DEFAULTS에 배정만 있고 호출부는 아직 없다 -- 위 셋과
  헷갈리지 않도록 밝혀 둔다.) `api_cost_logs`에 쌓인 행이 그 증거다. 재확인은 위
  grep 한 줄이면 된다 -- 이 파일 자신과 `admin_ai_tasks.py`의 카탈로그 정의(호출이
  아니라 목록)는 걸러서 읽는다.

  ⚠ **"호출하는 곳"과 "import만 하는 곳"은 다른 사실이라 갈라 적는다** (2026-08-25,
  같은 날 발견된 두 번째 낡음 -- 다른 제작자가 찾아 넘겼다). 위 셋은 실제로
  `llm.call()`을 부른다(프로바이더에 요청이 나가고 비용이 발생할 수 있다). 그런데
  `api/admin_ai_logs.py:42`가 오늘 `from .llm import PROVIDERS`를 추가했다 -- AI
  응답 기록 화면의 "모델" 필터가 폐기된 모델명(`claude-opus-4-8`·`gemini-2.5-pro`·
  `gpt-5-codex`, 클라이언트 미리보기용 예시 배열의 잔재)을 쓰던 결함을 고치면서
  목록을 다시 베껴 적지 않고 이 파일의 `PROVIDERS[...].pricing` 키(실제 호출에
  쓰는 모델 문자열의 단일 원천)를 그대로 읽게 했다(그 파일 docstring "「모델」
  필터도 이 정본에서 읽는다(2026-08-25 정정)" 참고). **`call()`은 부르지 않는다**
  -- 프로바이더 호출도 비용도 없고 `PROVIDERS` 딕셔너리를 데이터로만 읽는다. 그래서
  위 "실제 호출부는 셋이다"라는 문장은 여전히 참이지만, "이 모듈을 import하는 곳"
  으로 범위를 넓히면 지금은 넷이다. **이 파일이 `PROVIDERS`의 모델 문자열을 늘리거나
  줄이면 AI 응답 기록 화면의 필터 목록도 그만큼 바뀐다** -- 그 화면을 고치는 다음
  사람이 알아야 할 결합이다.

  같은 날 두 번째 지시로 Claude·Codex(OpenAI)를 마저 등록하고 폴백을 실제로 지었다
  (아래 "다음 프로바이더를 더할 때" 문단 및 `_is_fallback_eligible`/`_resolve_fallback_order`
  참고). 사장님이 실사용 경험으로 배정을 확정했다(2026-08-16): 입력 파싱(task.s1_parse)
  = Claude(Haiku) · 근거 설명(task.s2_explain) = GPT · 웹 사양 채움(task.spec_fill) =
  Claude(Opus) · 운영 도우미(task.ops_assist) = Gemini. 처음엔 이 배정을 **PROVIDERS의
  default_model 선택에만**(프로바이더당 하나) 반영하고 task_key -> provider 자동
  라우팅은 짓지 않았다 -- 그런데 s1_parse·spec_fill이 **같은 프로바이더(Claude)인데
  등급이 다르다**는 사실이 "프로바이더당 default_model 하나" 구조로는 표현되지 않는다는
  게 곧바로 드러났다.

  그래서 같은 날 세 번째 지시로 이 층을 짓는다: `TASK_DEFAULTS`(task_key -> provider+model
  코드 기본값, `PROVIDERS` 바로 아래) + `_resolve_task_default()`(DB `ai_task_assignments`
  우선ㆍ코드 기본값 폴백 -- 아래 "■ task_key 기반 자동 라우팅" 참고)가 그것이다.
  `call(prompt, task_key=...)`만 넘기면 이제 provider·model이 자동으로 정해지고,
  `provider=`/`model=`을 명시하면 여전히 그게 이긴다(하위 호환 -- `call()` 문서 참고).

■ 지키는 결정
  - A-03 (decision-log.md): "LLM의 역할은 입력 파싱 + 근거 설명뿐. 견적을 생성하지
    않는다." -- 이 모듈에는 견적 계산 코드가 없다. 프롬프트를 넣고 텍스트를 받는
    범용 호출기일 뿐이고, 프롬프트를 무엇으로 채울지는 호출부(다음 단계)의 책임이다.
  - 2026-07-21 보류 결정: "비용 캡ㆍ요청 제한ㆍ접근 게이트 필수" -- ③ 아래에서 구현.
  - A-35: Codex/Claude/Gemini 3사 역할분담 + 폴백이 최종 방향이다. 지금은 Gemini
    하나뿐이지만, PROVIDERS 레지스트리 하나에 프로바이더를 더 등록하는 형태로 설계했다
    (아래 "다음 프로바이더를 더할 때" 참고). 폴백 사슬 자체(여러 프로바이더를 순서대로
    시도하는 루프)는 프로바이더가 하나뿐인 지금은 만들지 않았다 -- 쓸 데가 없는 추상을
    미리 넣지 않는다는 지시를 따른 것이고, 자리는 `_decide_cost_cap`의 `has_alt_provider`
    분기와 `PROVIDERS` 딕셔너리 자체가 이미 마련해 둔다.

■ 모델 선정 근거 (2026-08-16 실측 -- 넘겨짚지 않고 확인했다)
  SDK: `google-generativeai`는 PyPI 설명 첫 줄이 "[Deprecated]"다(공식 레포가 스스로
  "legacy"라 표기, 최근 릴리스 2025-12-16로 8개월 정체). 후속 `google-genai`가 최근
  릴리스 2026-08-13(오늘 기준 사흘 전)으로 활발히 유지되는 공식 후계 SDK다
  (PyPI JSON API로 두 패키지의 latest release 날짜를 직접 비교해 확인).

  모델: `https://ai.google.dev/gemini-api/docs/models`를 오늘 실제로 열어 "Stable"과
  "Preview" 절을 대조했다. Gemini 3 세대의 Stable 절에는 Pro 등급 텍스트 모델이 아직
  없다(Gemini 3.1 Pro는 여전히 Preview) -- Stable 중 가장 강력한 범용 모델은
  `gemini-3.7-flash`("Our latest and most capable Flash model")다. Preview 모델은
  예고 없이 바뀌거나 사라질 수 있어 인프라 기본값으로 부적절하다고 판단해 Stable을
  택했다. 단가는 `https://ai.google.dev/gemini-api/docs/pricing`에서 같은 날 확인
  (아래 PROVIDERS의 price_source 참고).

  ⚠ 이 판단에는 유효기간이 있다 -- Gemini 3.1 Pro가 Stable로 승격되거나 3.8/4 세대가
  나오면 다시 확인해야 한다. 짐작하지 않기 위해 코드가 아니라 이 순간의 실측을 근거로
  남긴다(재확인 방법: 위 두 URL을 다시 열어 Stable 절을 본다).

■ 다음 프로바이더(넷째)를 더할 때 -- 늘어나는 자리는 딱 여기 둘이다 (Claude/Codex를
  실제로 추가하며 검증됨 -- 아래 _call_claude/_call_openai가 그 실례다)
  ① `_call_<vendor>(model, prompt, system, max_output_tokens, timeout_sec)` 함수 하나
     (이 파일 안, `_call_gemini` 옆에). `genai_errors.APIError`처럼 프로바이더 SDK의
     상태코드로 `LLMProviderError(transient=...)`를 판정하는 부분이 유일한 벤더별 로직이다.
  ② `PROVIDERS` 딕셔너리에 `ProviderSpec` 항목 하나(pricing 딕셔너리는 실제로 쓰는
     모델만 채운다 -- 카탈로그 전체를 미리 채우지 않는다)
  `call()`ㆍ`_check_caps()`ㆍ`_call_one()`ㆍ`LLMResult`ㆍ예외 계층ㆍ폴백 로직은 프로바이더
  수와 무관하게 그대로다 -- 호출부(`llm.call(provider="claude", ...)`)도 바뀌지 않는다.

  ■ task_key 기반 자동 라우팅 (2026-08-16 세 번째 지시로 구현 -- 아래는 왜 처음엔
    미뤘고 왜 다시 필요해졌는지의 기록이다. 지우지 않는다: 같은 판단을 "지금 안 쓸
    추상을 미리 짓지 마세요" 원칙만 보고 다음에 또 되풀이하지 않기 위해서다)

    처음엔(같은 날 두 번째 지시 시점) `call(task_key="task.s1_parse")`가 "그럼 자동으로
    claude를 쓴다"처럼 스스로 provider를 고르게 하지 않았다 -- 그건 `ai_task_assignments`
    (0046, ADM-AI-030)가 저장하는 값을 "누가 실제로 쓸지" 정하는 오케스트레이션이고,
    이 파일의 책임(프로바이더+모델이 정해진 뒤 한 번 부르는 것, 캡ㆍ폴백)보다 한 층
    위라고 판단했다. 그래서 fallback_order만 예외로 `ai_task_assignments`를 읽었다
    (`_resolve_fallback_order`) -- "주 프로바이더가 막히면 다음은 뭘 쓸까"는 이미 이
    파일의 책임(③) 범위 안이라서였다. 지금 호출부는 `provider=`를 직접 명시해야 했다
    (이번 세션의 비교 벤치마크가 실제로 그렇게 했다).

    그런데 s1_parse(Claude Haiku)ㆍspec_fill(Claude Opus)처럼 **같은 프로바이더인데
    모델 등급이 다른** 배정이 나오면서 "호출부가 provider=만 골라 주면 된다"는 전제가
    깨졌다 -- provider="claude" 하나로는 두 작업을 구분할 수 없다. 그래서 세 번째
    지시로 "task_key 하나 -> provider+model 하나"를 정하는 층(`TASK_DEFAULTS` +
    `_resolve_task_default`)을 이 파일 안에 새로 만들었다. **오케스트레이션이라는
    판단 자체는 안 바뀌었다** -- `ai_task_assignments`가 여전히 정본이고 이 함수는 그
    값을 읽어 번역할 뿐이다. 다만 그 오케스트레이션이 "프로바이더 하나를 고르는 수준"이
    아니라 "그 프로바이더 안에서 어느 등급을 쓸지까지" 필요하다는 게 이번에 드러났고,
    그 폭은 이 파일(프로바이더+모델을 실제로 부르는 자리, `PROVIDERS[...].pricing`의
    키 = 유효한 모델 문자열을 이미 쥐고 있는 자리)이 가장 잘 안다고 판단했다.

    ⚠ **여전히 짓지 않은 것**: `ai_task_assignments.mode='concurrent'`(여러 프로바이더를
    동시에 불러 결과를 수렴하는 것)는 이번에도 만들지 않는다 -- `_resolve_task_default`는
    그 작업의 `providers` 배열에서 역할이 `'주'`인 항목 하나만 골라 **단일 호출**한다
    (concurrent로 저장된 행이 있어도 이 층은 그중 하나만 쓴다. `role='주'`가 없으면
    배열의 첫 항목). "여러 프로바이더를 동시에 불러 비교/수렴한다"는 `call()` 한 번의
    책임보다 위이고(이번 세션의 비교 벤치마크가 여러 번 호출해 손으로 비교한 것과 같은
    수준 -- 그 반복을 자동화하는 것은 다음 단계다), 화면·엔드포인트를 새로 만들지
    않는다는 이번 지시 범위 밖이기도 하다.

■ 캡(③) -- cost_thresholds/rate_limit_policies를 "읽고 실제로 막는다"
  두 표 모두 지금 0행이다(실측). "한도가 설정돼 있지 않으면 무제한"은 사고를 부른다는
  지시를 따라, 코드 기본값(DEFAULT_*)을 안전망으로 둔다 -- DB에 값이 있으면 항상 DB가
  이긴다. DEFAULT_DAILY_CAP_USD=$2.00의 근거: gemini-3.7-flash 표준가로 입력 500토큰+
  출력 500토큰짜리 호출이라면 1건당 약 $0.00225 -- $2.00이면 하루 약 888건까지 여유를
  주면서도 사고(무한 루프 등)는 반나절 안에 막는다. DEFAULT_PER_MINUTE=10,
  DEFAULT_PER_DAY=500도 같은 "테스트는 막지 않되 폭주는 막는다" 기준으로 정했다.

  `cost_thresholds.action`(warn/batch_defer/fallback/stop -- 정본은
  `api/admin_ai_integration.py`의 ACTIONS, 이 파일은 그 문자열을 그대로 읽기만 하고
  다시 정의하지 않는다)에 따라 초과 시 동작이 갈린다 -- `_decide_cost_cap` 참고.
  action이 비어 있으면(첫 저장 시 흔함) 가장 안전한 'stop'으로 취급한다.

  ⚠ 알려진 한계(보고서에도 남김): `cost_thresholds`의 작업별 부분 한도
  (`key=f"{provider}:{task_key}"`)는 저장은 되지만 강제하지 못한다 -- `api_cost_logs`에
  작업 종류 컬럼이 없어(스키마 없음, `api/admin_ai_usage.py`가 이미 같은 사실을 관측
  화면에서 밝히고 있다) 작업별 실사용을 다시 잴 수 없기 때문이다. 상위(프로바이더 전체)
  한도만 실제로 강제된다 -- `_check_caps`가 이 사실을 매 호출 로그에 남긴다.

■ 실패를 삼키지 않는다
  - 키가 없거나 빈 문자열이면 `LLMNotConfiguredError` -- 조용히 빈 텍스트를 돌려주지
    않는다(화면이 "AI가 답했다"처럼 보이는 게 제일 나쁘다는 지시 그대로).
  - 캡을 넘으면 호출 자체를 하지 않고 `LLMBlockedError` -- 호출하고 나서 기록만 하는
    건 캡이 아니라는 지시 그대로. 무엇이 막혔는지(`kind`: "cost"/"rate_minute"/
    "rate_day")와 왜 막혔는지(메시지)를 호출부가 그대로 받는다.
  - 프로바이더가 오류를 던지면(네트워크ㆍ잘못된 모델명ㆍ빈 응답 등) `LLMProviderError`로
    감싸 올린다 -- 여기서 삼키지 않는다.
  - `api_cost_logs` 기록 자체가 실패하면(DB 순단 등) -- 이미 호출은 성공해 비용이
    실제로 발생한 뒤이므로, 응답을 버리지 않고 `cost_logged=False`로 표시해 돌려준다.
    대신 서버 로그(logging.exception)에 크게 남긴다. "이미 산 답을 버리는 것"과 "기록
    누락을 조용히 감추는 것" 중 후자만 피하고 전자는 감수한 판단이다 -- 보고서에 남김.

■ 비용 계산 근거(단가)를 코드 상수로 둔 이유와 그 대가
  프로바이더 하나ㆍ모델 하나뿐인 지금 단계에서 별도 가격 테이블(새 DB 스키마)을 만드는
  것은 "지금 안 쓸 추상을 미리 짓지 마세요" 지시에 어긋난다고 판단했다. 대신
  `ProviderSpec.price_valid_until`(오늘 확인한 단가가 유효한 마지막 날 -- Google
  공식 문서가 명시한 인상일 전날)을 넘기면 호출마다 경고 로그를 남기도록 해 "낡은 채
  조용히 계속 쓰는" 상태를 막는다. 프로바이더가 늘고 단가 개정이 잦아지면 그때
  DB 테이블로 옮기는 편이 맞다 -- 지금은 그 문턱을 넘지 않았다고 판단했다(보고서에
  판단 근거로 남김, DBA/사장님 재검토 대상).

■ 개발/운영 축 (④) -- 이번 슬라이스에서는 만들지 않음 (2026-08-16 사장님 지시로 우선순위
  하향, 판단과 근거만 남긴다)
  로컬 PC와 배포 서버가 같은 Cloud SQL을 쓴다(CLAUDE.md #작업 흐름) -- 이 래퍼가
  호출될 때마다 `api_cost_logs`에 쌓이는 행은 "개발자가 시험 삼아 부른 것"과 "실제
  고객 요청"을 구분할 길이 없다. `products.data_origin`(real/demo)과 같은 어휘를
  재사용하는 안을 검토했다: 그 컬럼이 이미 "지금부터 만드는 것만 구분한다"는 철학으로
  존재하고(`0033_demo_data_axis.py`), 다른 표에서도 같은 이름을 쓰면 정리 SQL을 표마다
  새로 짜지 않아도 된다. 판정 축은 **환경변수**를 추천한다(예: `APP_ENV=dev|prod`,
  `.env`(로컬) vs 서버 `/etc/popcorn-ai.env`가 이미 그렇게 갈라져 있다 -- `UI_CHECK_
  DEV_LOGIN`과 같은 선례) -- 호출 시 인자로 넘기게 하면 호출부마다 깜빡하고 안 넘기는
  실수가 조용히 쌓인다(사람이 매번 기억해야 하는 것은 결국 안 지켜진다). ⚠ 중요한 구분:
  이 축은 "관측 필터"이지 "캡 면제"가 아니어야 한다 -- 실제로 쓰는 돈은 개발/운영과
  무관하게 진짜 돈이라, 캡(③)은 이 축과 상관없이 항상 전체 합계로 계산해야 한다(그렇지
  않으면 개발 중 반복 호출로 실제 과금 한도를 캡이 모르는 채 넘길 수 있다). 이번
  슬라이스는 이 판단만 남기고 마이그레이션 파일은 만들지 않았다(사장님 지시).
"""
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import inspect as sa_inspect, text

from .db import engine
from .timeutil import KST, iso, kst_day_range

log = logging.getLogger("llm")


# ============================================================================
# 예외 -- 호출부는 이 넷만 알면 된다 (프로바이더별 SDK 예외 타입은 몰라도 된다)
# ============================================================================
class LLMError(Exception):
    """이 모듈이 던지는 모든 오류의 공통 조상."""


class LLMNotConfiguredError(LLMError):
    """키가 없거나(env에 항목 자체가 없음) 비어 있다(선언만 되고 값이 없음).

    `api/admin_ai_integration.py`의 3분류(미설정/설정됨/확인 실패)와 같은 판정이다 --
    이 예외는 그 둘("미설정"과 "확인 실패") 모두를 같은 방식으로 막는다. 여기서는
    화면처럼 3분류를 구분해 보여줄 필요가 없다 -- 둘 다 "호출 불가"라는 결론은 같다.
    """


class LLMBlockedError(LLMError):
    """cost_thresholds/rate_limit_policies 한도를 넘어 호출 자체를 막았다 -- 프로바이더에
    네트워크 요청을 보내기 전에 발생한다(호출 자체를 안 한다).

    kind은 지금 셋: "cost"(프로바이더별 일일 한도) · "rate_minute" · "rate_day". **셋 다
    프로바이더 단위 한도**라 폴백 대상이다(_is_fallback_eligible 참고 -- 이 프로바이더만
    막혔을 뿐 다른 프로바이더는 자기 한도가 남아 있을 수 있다).

    ⚠ 넷째 kind "cost_global"(전체 합산 한도)은 **예약만 해 둔다 -- 아직 아무도 안
    던진다.** 지금 스키마(cost_thresholds)에는 "프로바이더 전체를 합산한 한도" 같은 키
    개념이 없다(키가 provider 또는 provider:task_key뿐). 2026-08-16 사장님 지시:
    "전체 비용 한도 초과는 폴백하면 안 된다"(다른 프로바이더로 넘겨도 어차피 같은
    지갑에서 돈이 나가므로 우회가 안 된다) -- 그런 한도가 나중에 생기면 kind="cost_global"
    로 던지고, _is_fallback_eligible이 그 kind만 예외로 차단하면 된다. 지금은 만들지 않고
    자리만 남긴다(지금 안 쓸 추상을 미리 짓지 않는다는 지시).
    """

    def __init__(self, message: str, *, kind: str, provider: str):
        super().__init__(message)
        self.kind = kind          # "cost" | "rate_minute" | "rate_day" | ("cost_global" 예약)
        self.provider = provider


class LLMAllProvidersFailedError(LLMError):
    """폴백 사슬(주 프로바이더 + fallback_order)을 전부 시도했는데 전부 막혔거나
    실패했다. `.attempts`에 (provider_key, 예외) 목록이 순서대로 남는다 -- 어디서부터
    막혔는지 되짚을 수 있다."""

    def __init__(self, message: str, attempts: list[tuple[str, Exception]]):
        super().__init__(message)
        self.attempts = attempts


class LLMProviderError(LLMError):
    """프로바이더 SDK/네트워크가 던진 오류를 감싼다 -- 호출부가 SDK별 예외 타입을
    몰라도 되게 한다(다음 프로바이더를 추가해도 호출부 except 절이 안 바뀐다).

    transient: 폴백 자격 판정에 쓴다(_is_fallback_eligible). 각 _call_<vendor>가 정한다.
      True  = "이 프로바이더가 지금 일시적으로 문제다"(네트워크·타임아웃·5xx·상대측
              레이트리밋) -- 다른 프로바이더로 넘기면 실제로 도움이 될 가능성이 있다.
      False = "우리가 이 프로바이더를 잘못 불렀다"(401/403 키 거부·400 잘못된 요청·404
              모델명 오타) -- 설정 실수라 다른 프로바이더로 넘겨도 원인이 안 없어지고,
              오히려 실수를 조용히 감춘다(무엇이 왜 실패했는지 아무도 모르게 된다).
              사장님 지시("잘못된 키는 넘겨도 소용없다")를 그대로 코드화한 것.
    """

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


# ============================================================================
# 결과
# ============================================================================
@dataclass
class LLMResult:
    provider: str
    model: str
    text: str
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    elapsed_sec: float
    log_id: int | None     # api_cost_logs.log_id -- 기록 실패 시 None (cost_logged 참고)
    cost_logged: bool      # False면 이미 비용은 발생했으나 api_cost_logs에 못 남겼다는 뜻


# ============================================================================
# 캡 -- 순수 판정 함수(_decide_cost_cap)와 DB 조회(_check_caps)를 분리했다.
# 순수 함수는 DB/네트워크 없이 값만 넣어 시험할 수 있다(확인자 몫 -- 지시서 확인 ②).
# ============================================================================
DEFAULT_DAILY_CAP_USD = 2.0
DEFAULT_ACTION = "stop"
DEFAULT_PER_MINUTE = 10
DEFAULT_PER_DAY = 500


def _decide_cost_cap(*, spent: float, limit: float, action: str,
                      customer_facing: bool, has_alt_provider: bool) -> tuple[bool, str]:
    """오늘 누계(spent)ㆍ한도(limit)ㆍ동작(action)만으로 호출 허용 여부를 정하는 순수
    함수 -- DB나 네트워크에 닿지 않는다. 반환: (허용?, 사유 문구).

    action 어휘는 `api/admin_ai_integration.py`의 ACTIONS가 정본이다(이 함수는 그
    문자열을 그대로 읽을 뿐 다시 정의하지 않는다): batch_defer/stop/fallback/warn.
    """
    if spent < limit:
        return True, f"limit ok (spent ${spent:.4f} / limit ${limit:.4f})"

    over_msg = f"today spent ${spent:.4f} >= limit ${limit:.4f}"

    if action == "warn":
        return True, f"{over_msg} - action=warn, continuing with warning only"

    if action == "batch_defer":
        if customer_facing:
            return True, f"{over_msg} - action=batch_defer but customer_facing=True, continuing"
        return False, f"{over_msg} - action=batch_defer, non-customer-facing call blocked"

    if action == "fallback":
        if has_alt_provider:
            return False, (f"{over_msg} - action=fallback (switching provider is the caller's"
                            f" job; this provider is blocked here)")
        return False, f"{over_msg} - action=fallback but no alternate provider is registered"

    # "stop" 또는 알 수 없는 값 -> 가장 안전한 기본: 차단
    suffix = "" if action == "stop" else f" (unknown action={action}, defaulting to stop)"
    return False, over_msg + suffix


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today_kst_lo() -> datetime:
    """오늘(서울 자정) 시작 시각 -- api_cost_logs.created_at(naive UTC)과 비교 가능한
    naive UTC로 돌려준다. timeutil.kst_day_range를 그대로 쓴다(날짜 경계 계산을
    여기서 다시 만들지 않는다)."""
    d = datetime.now(KST).date()
    lo, _hi = kst_day_range(iso(d), iso(d))
    return lo


def _check_caps(conn, provider_key: str, task_key: str | None, customer_facing: bool,
                 has_alt_provider: bool) -> None:
    """DB에서 정책ㆍ실사용을 읽어 `_decide_cost_cap`(+ 호출 빈도)으로 판정한다.
    막히면 `LLMBlockedError`를 던진다 -- 이 함수가 예외 없이 반환하면 호출해도 된다."""
    # ---- 호출 빈도 (rate_limit_policies) -- action 구분이 없어 초과 시 항상 차단 ----
    rl = conn.execute(text(
        "SELECT per_minute, per_day FROM rate_limit_policies WHERE key = :k"),
        {"k": provider_key}).mappings().first()
    rl_default = rl is None
    # is not None으로 명시 비교한다 -- 0을 "값 없음"으로 오독하는 or-폴백 함정을 피한다.
    # (지금은 api/admin_ai_integration.py의 쓰기 검증이 0 이하를 거부해 도달 불가능한
    # 경로지만, 이 파일이 그 보장에 암묵적으로 기대지 않도록 방어적으로 짰다.)
    per_minute = rl["per_minute"] if (rl and rl["per_minute"] is not None) else DEFAULT_PER_MINUTE
    per_day = rl["per_day"] if (rl and rl["per_day"] is not None) else DEFAULT_PER_DAY
    default_note = " (rate_limit_policies not set - using code default)" if rl_default else ""

    now = _naive_utcnow()
    n_minute = conn.execute(text(
        "SELECT COUNT(*) FROM api_cost_logs WHERE provider = :p AND created_at >= :since"),
        {"p": provider_key, "since": now - timedelta(minutes=1)}).scalar_one()
    if n_minute >= per_minute:
        raise LLMBlockedError(
            f"[{provider_key}] per-minute call limit exceeded: {n_minute} in last 1 min"
            f" >= {per_minute}{default_note}",
            kind="rate_minute", provider=provider_key)

    lo_day = _today_kst_lo()
    n_day = conn.execute(text(
        "SELECT COUNT(*) FROM api_cost_logs WHERE provider = :p AND created_at >= :lo"),
        {"p": provider_key, "lo": lo_day}).scalar_one()
    if n_day >= per_day:
        raise LLMBlockedError(
            f"[{provider_key}] daily call limit exceeded: {n_day} today >= {per_day}"
            f"{default_note}",
            kind="rate_day", provider=provider_key)

    # ---- 비용 상한 (cost_thresholds) ----
    thr = conn.execute(text(
        "SELECT daily_usd, action FROM cost_thresholds WHERE key = :k"),
        {"k": provider_key}).mappings().first()
    thr_default = thr is None or thr["daily_usd"] is None
    limit = float(thr["daily_usd"]) if (thr and thr["daily_usd"] is not None) \
        else DEFAULT_DAILY_CAP_USD
    action = thr["action"] if (thr and thr["action"] is not None) else DEFAULT_ACTION

    spent_row = conn.execute(text(
        "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM api_cost_logs"
        " WHERE provider = :p AND created_at >= :lo"),
        {"p": provider_key, "lo": lo_day}).mappings().first()
    spent = float(spent_row["c"])

    allowed, reason = _decide_cost_cap(
        spent=spent, limit=limit, action=action,
        customer_facing=customer_facing, has_alt_provider=has_alt_provider)
    if thr_default:
        reason += " (cost_thresholds not set - using code default)"

    if not allowed:
        raise LLMBlockedError(f"[{provider_key}] {reason}", kind="cost", provider=provider_key)
    if spent >= limit:
        # 막지는 않았지만(warn 또는 batch_defer+customer_facing) 넘은 사실은 남긴다.
        log.warning("[llm] %s: %s", provider_key, reason)

    if task_key:
        sub = conn.execute(text("SELECT daily_usd FROM cost_thresholds WHERE key = :k"),
                            {"k": f"{provider_key}:{task_key}"}).mappings().first()
        if sub and sub["daily_usd"] is not None:
            log.info(
                "[llm] %s:%s has a sub-limit ($%.2f) but api_cost_logs has no task-key"
                " column yet - only the provider-level limit is actually enforced",
                provider_key, task_key, float(sub["daily_usd"]))


# ============================================================================
# 프로바이더 레지스트리 -- 다음 프로바이더를 더할 때 늘어나는 자리는 여기와
# 아래 _call_<vendor> 함수뿐이다. call()은 프로바이더 수와 무관하게 그대로다.
#
# ■ 2026-08-16 3사로 확장하며 가격을 프로바이더당 1개에서 "모델별"로 바꿨다
#   (ModelPricing.pricing: dict[model, ModelPricing]) -- 이유: 같은 벤더 안에서도
#   등급마다(Opus/Sonnet/Haiku, Sol/Terra/Luna) 단가가 몇 배씩 다르다. 호출부가
#   `call(model=...)`로 default_model이 아닌 다른 등급을 넘기면(이번 세션의 비교
#   벤치마크가 실제로 그렇게 함) 프로바이더 단일 단가로 계산한 비용은 **틀린 값을
#   맞는 값처럼** 보여준다 -- "모르면 None"이 "잘못 알면서 확신하는 것"보다 낫다.
# ============================================================================
@dataclass(frozen=True)
class ModelPricing:
    price_in_per_1m: float   # USD / 1M input tokens
    price_out_per_1m: float  # USD / 1M output tokens (사고 토큰 등 프로바이더별 청구 기준 포함)
    valid_until: date | None   # 이 날짜가 지나면 _cost_usd가 경고 로그를 남긴다
    source: str               # 확인한 URL + 확인일 + 조건 (감사 근거)


@dataclass(frozen=True)
class ProviderSpec:
    key: str                # cost_thresholds/rate_limit_policies.key, api_cost_logs.provider
    vendor: str              # 표시용 (admin_ai_integration.PROVIDERS의 vendor와 같은 값 -- fallback_order 번역에도 씀)
    env_key: str             # .env 키 이름
    default_model: str       # call()에서 model= 생략 시 쓰는 값. pricing에 반드시 있어야 한다
    pricing: dict[str, ModelPricing]   # 이 세션에서 실제로 쓴 모델만 채운다(카탈로그 전체 아님)
    caller: Callable[[str, str, str | None, int, int], tuple[str, int | None, int | None]]


def _call_gemini(model: str, prompt: str, system: str | None,
                  max_output_tokens: int, timeout_sec: int) -> tuple[str, int | None, int | None]:
    """Gemini Developer API 호출 1회. 반환: (텍스트, 입력 토큰, 출력 토큰[thinking 포함]).

    SDK: google-genai (google-generativeai는 폐기 -- 모듈 docstring 근거 참고).
    """
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    client = genai.Client(api_key=api_key,
                           http_options=genai_types.HttpOptions(timeout=timeout_sec * 1000))
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_output_tokens,
    )
    try:
        resp = client.models.generate_content(model=model, contents=prompt, config=config)
    except genai_errors.APIError as e:
        # 4xx = 우리가 이 호출을 잘못 구성했다(키·모델명·요청 형식) -- 폴백 대상 아님.
        # 5xx/429 = 프로바이더 쪽 일시적 문제 -- 폴백 대상.
        transient = e.code is None or e.code >= 500 or e.code == 429
        raise LLMProviderError(
            f"Gemini API error {e.code} {e.status}: {e.message}", transient=transient) from e
    except Exception as e:  # httpx 타임아웃/연결 실패 등 APIError로 안 감싸지는 것들 -- 전부 일시적
        raise LLMProviderError(f"Gemini call failed ({type(e).__name__}): {e}", transient=True) from e

    usage = resp.usage_metadata
    tokens_in = usage.prompt_token_count if usage else None
    tokens_out = None
    if usage is not None:
        tokens_out = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)

    text_out = resp.text
    if text_out is None:
        # 응답은 왔는데 텍스트가 없다(예: 안전 필터 차단) -- 빈 문자열을 성공으로
        # 포장하지 않는다. finish_reason을 근거로 남긴다.
        reasons = [str(c.finish_reason) for c in (resp.candidates or [])
                   if getattr(c, "finish_reason", None)]
        raise LLMProviderError(
            "Gemini returned no text"
            + (f" (finish_reason={', '.join(reasons)})" if reasons else ""),
            transient=True)  # 안전 필터 등 -- 다른 벤더는 통과시킬 수도 있어 폴백 가치가 있다
    return text_out, tokens_in, tokens_out


def _call_claude(model: str, prompt: str, system: str | None,
                  max_output_tokens: int, timeout_sec: int) -> tuple[str, int | None, int | None]:
    """Anthropic Messages API 호출 1회. 반환: (텍스트, 입력 토큰, 출력 토큰)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    client = anthropic.Anthropic(api_key=api_key, timeout=float(timeout_sec), max_retries=0)
    kwargs = {"model": model, "max_tokens": max_output_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.APIStatusError as e:
        # 4xx(401/403/404/400/422/413) = 우리 쪽 설정 실수 -- 폴백 대상 아님.
        # 5xx/429/529(overloaded) = 일시적 -- 폴백 대상.
        transient = e.status_code >= 500 or e.status_code == 429
        raise LLMProviderError(
            f"Claude API error {e.status_code}: {e.message}", transient=transient) from e
    except Exception as e:  # 연결/타임아웃 등 APIStatusError가 아닌 것들 -- 전부 일시적
        raise LLMProviderError(f"Claude call failed ({type(e).__name__}): {e}", transient=True) from e

    tokens_in = resp.usage.input_tokens if resp.usage else None
    tokens_out = resp.usage.output_tokens if resp.usage else None
    text_out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    if not text_out:
        raise LLMProviderError(
            f"Claude returned no text (stop_reason={resp.stop_reason})", transient=True)
    return text_out, tokens_in, tokens_out


def _call_openai(model: str, prompt: str, system: str | None,
                  max_output_tokens: int, timeout_sec: int) -> tuple[str, int | None, int | None]:
    """OpenAI Responses API 호출 1회(공식 문서가 권하는 현행 엔드포인트 -- 구 Chat Completions
    아님). 반환: (텍스트, 입력 토큰, 출력 토큰)."""
    import openai

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    client = openai.OpenAI(api_key=api_key, timeout=float(timeout_sec), max_retries=0)
    kwargs = {"model": model, "input": prompt, "max_output_tokens": max_output_tokens}
    if system:
        kwargs["instructions"] = system
    try:
        resp = client.responses.create(**kwargs)
    except openai.APIStatusError as e:
        transient = e.status_code >= 500 or e.status_code == 429
        raise LLMProviderError(
            f"OpenAI API error {e.status_code}: {e.message}", transient=transient) from e
    except Exception as e:
        raise LLMProviderError(f"OpenAI call failed ({type(e).__name__}): {e}", transient=True) from e

    tokens_in = resp.usage.input_tokens if resp.usage else None
    tokens_out = resp.usage.output_tokens if resp.usage else None
    text_out = resp.output_text
    if not text_out:
        raise LLMProviderError(
            f"OpenAI returned no text (status={resp.status})", transient=True)
    return text_out, tokens_in, tokens_out


# ── 가격 확인 방법론(감사 근거) ─────────────────────────────────────────────
# Gemini: https://ai.google.dev/gemini-api/docs/pricing 페이지를 실제로 열어 "Standard
#   tier" 표를 그대로 읽었다.
# Claude: https://claude.com/pricing 페이지의 각 모델 카드(Input/Output, $/MTok)를 그대로
#   읽었다. Fable 5는 이 표에 없다(구독제 전용 -- "Max 플랜의 주간 한도 50%, Pro는 크레딧"
#   문구뿐, 개발자 API용 $/MTok가 없어 이 레지스트리에 넣지 않았다).
# OpenAI: https://platform.openai.com/docs/pricing의 JSON 임베디드 표를 파싱했다. 표는
#   모델당 4열이었는데 문자 그대로의 열 제목(<thead>)을 못 찾았다 -- 대신 값의 패턴으로
#   추론했다: 2열 값이 항상 1열의 ~10%(캐시 입력 할인, 업계 공통 관행과 일치) · 3열은
#   최신 세대(5.6)에만 있고 구세대는 전부 "-"(그 페이지의 "Priority processing was
#   renamed Fast mode" 각주와 일치 -- 최신 모델만 지원) · 4열은 1열의 5~6배(출력이 입력보다
#   비싼 통상 비율과 일치). 그래서 [입력, 캐시 입력, Fast모드 입력, 출력]으로 읽었고 이
#   레지스트리는 표준(비-Fast) 가격인 1·4열만 쓴다. ⚠ 열 제목 텍스트를 직접 못 읽었다는
#   점은 보고서에 명시한다 -- 패턴 추론이지 원문 확인이 아니다.
_CHECKED = date(2026, 8, 16)

PROVIDERS: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        key="gemini", vendor="Gemini", env_key="GEMINI_API_KEY",
        default_model="gemini-3.7-flash",   # 배정: 운영 도우미(ops_assist) - "이 정도로 충분"(사장님)
        pricing={
            "gemini-3.7-flash": ModelPricing(
                price_in_per_1m=0.75, price_out_per_1m=3.75, valid_until=date(2026, 12, 31),
                source="https://ai.google.dev/gemini-api/docs/pricing (Standard) - "
                       "checked 2026-08-16, incl. thinking tokens in output. "
                       "Rises to $1.50/$7.50 on 2027-01-01."),
        },
        caller=_call_gemini,
    ),
    "claude": ProviderSpec(
        key="claude", vendor="Claude", env_key="ANTHROPIC_API_KEY",
        default_model="claude-opus-5",   # provider 단위 폴백(task_key로 못 갈릴 때만 씀) +
                                          # 배정: 웹 사양 채움(spec_fill) - "정확도"(사장님).
                                          # s1_parse는 TASK_DEFAULTS에서 claude-haiku-4-5로
                                          # 따로 갈린다 -- 이 필드(프로바이더당 1개)로는 같은
                                          # 프로바이더 안의 등급 차이를 못 담아 TASK_DEFAULTS를
                                          # 새로 만들었다(모듈 docstring "task_key 기반 자동
                                          # 라우팅" 참고).
        pricing={
            "claude-opus-5": ModelPricing(
                price_in_per_1m=5.0, price_out_per_1m=25.0, valid_until=_CHECKED,
                source="https://claude.com/pricing - checked 2026-08-16, "
                       "\"Ideal for complex agentic coding and enterprise work\", "
                       "Anthropic's own \"if unsure, start here\" default (docs.claude.com)."),
            "claude-sonnet-5": ModelPricing(
                price_in_per_1m=2.0, price_out_per_1m=10.0, valid_until=_CHECKED,
                source="https://claude.com/pricing - checked 2026-08-16, "
                       "\"High-performance model for coding and agents\"."),
            "claude-haiku-4-5-20251001": ModelPricing(
                price_in_per_1m=1.0, price_out_per_1m=5.0, valid_until=_CHECKED,
                source="https://claude.com/pricing - checked 2026-08-16, "
                       "\"Fastest, most cost-efficient model\" - no Haiku-5 exists yet "
                       "(verified via GET /v1/models on 2026-08-16, latest Haiku is still 4.5)."),
        },
        caller=_call_claude,
    ),
    "codex": ProviderSpec(
        key="codex", vendor="Codex", env_key="OPENAI_API_KEY",
        default_model="gpt-5.6-sol",   # 배정: 근거 설명(s2_explain) - "고객이 읽는 글, 한국어 답변 품질"(사장님)
        pricing={
            "gpt-5.6-sol": ModelPricing(
                price_in_per_1m=5.0, price_out_per_1m=30.0, valid_until=_CHECKED,
                source="https://platform.openai.com/docs/pricing - checked 2026-08-16, "
                       "official guidance: \"our flagship model for complex reasoning "
                       "and coding\" (platform.openai.com/docs/models)."),
            "gpt-5.6-terra": ModelPricing(
                price_in_per_1m=2.0, price_out_per_1m=12.0, valid_until=_CHECKED,
                source="https://platform.openai.com/docs/pricing - checked 2026-08-16, "
                       "official guidance: \"balance intelligence and cost\"."),
            "gpt-5.6-luna": ModelPricing(
                price_in_per_1m=0.2, price_out_per_1m=1.2, valid_until=_CHECKED,
                source="https://platform.openai.com/docs/pricing - checked 2026-08-16, "
                       "official guidance: \"cost-sensitive, high-volume workloads\"."),
        },
        caller=_call_openai,
    ),
    # A-35의 3사가 이제 전부 등록됐다. 넷째 프로바이더가 생기면 이 딕셔너리에 항목 하나 +
    # 위에 _call_<vendor> 함수 하나만 추가한다 -- call()/_check_caps/폴백 로직은 그대로다.
}


# ============================================================================
# task_key -> (provider_key, model) 코드 기본값 -- 사장님 실사용 배정(2026-08-16).
# `ai_task_assignments`(0046)가 정본이고, 이 딕셔너리는 그 표가 비어 있거나(0행 --
# 2026-08-16 실측) 아직 마이그레이션 미적용일 때만 쓰는 폴백이다(_resolve_task_default).
#
# ■ `api/admin_ai_tasks.py`의 `DEFAULT_PROVIDERS`와 두 벌이 아닌 이유 (읽기만 했음 --
#   그 파일은 담당 밖이라 고치지 않았다)
#   그 상수는 **작업별로 갈라지지 않는 단일 값**이다 -- `POST /ai-task-settings/tasks`가
#   어느 task_key로 불려도 항상 같은
#   `[{"vendor":"Claude","model":"claude-opus-5","role":"주"}]`를 새 행에 넣는다(그 파일
#   자신의 주석: "이 상수 자체엔 task_key별 분기가 없다" · "정확한 작업별 모델은 배정
#   직후 이 화면(PATCH)에서 운영자가 골라야 한다"). 즉 s1_parse=Haiku·spec_fill=Opus처럼
#   **작업마다 다른 값**을 그 상수는 애초에 표현할 수 없다 -- "+ 작업 추가" 버튼을 누른
#   직후 화면에 뭐라도 채워 두는 임시 씨앗값일 뿐, 실제 호출 라우팅의 기본값으로 쓰인
#   적이 없다(ADM-AI-030 화면은 아직 "휴면" -- 그 파일 모듈 docstring). 그래서 이
#   딕셔너리는 그 상수를 대체하는 게 아니라, 그 상수가 애초에 다루지 않는 "작업별" 차원을
#   새로 채운다 -- 두 값이 같은 걸 두 번 정의하는 게 아니라 서로 다른 질문에 답한다
#   ("새 행을 만들 때 화면에 뭘 채워 둘까" vs "실제로 어느 모델을 부를까").
#
#   모델 문자열의 정본은 여전히 하나다 -- 아래 값은 전부 위 `PROVIDERS[...].pricing`의
#   기존 키를 그대로 가리킨다(새 모델을 여기서 지어내지 않는다). 모듈 로드 시
#   assert로 이 사실을 스스로 검증한다 -- "부르기 전에 있는지 본다"(CANON §5).
# ============================================================================
TASK_DEFAULTS: dict[str, tuple[str, str]] = {
    "task.s1_parse":   ("claude", "claude-haiku-4-5-20251001"),  # 입력 파싱 - 속도
    "task.s2_explain": ("codex",  "gpt-5.6-sol"),                # 근거 설명 - 한국어 품질
    "task.ops_assist": ("gemini", "gemini-3.7-flash"),           # 운영 도우미 - "이 정도로 충분"
    "task.spec_fill":  ("claude", "claude-opus-5"),              # 웹 사양 채움 - 정확도
}
for _tk, (_pk, _md) in TASK_DEFAULTS.items():
    assert _pk in PROVIDERS, f"TASK_DEFAULTS[{_tk}]: unknown provider {_pk!r}"
    assert _md in PROVIDERS[_pk].pricing, (
        f"TASK_DEFAULTS[{_tk}]: {_pk}/{_md} has no ModelPricing entry in"
        f" PROVIDERS[{_pk!r}].pricing")
del _tk, _pk, _md


def _cost_usd(spec: ProviderSpec, model: str,
              tokens_in: int | None, tokens_out: int | None) -> float | None:
    """모델별 단가로 계산한다. **이 모델의 가격을 모르면 None을 돌려준다** -- default_model의
    가격을 대신 쓰지 않는다(다른 등급을 mode=로 넘겼을 때 틀린 값을 맞는 값처럼 보여주는
    것을 막는다 -- ProviderSpec.pricing 필드 주석 참고)."""
    if tokens_in is None or tokens_out is None:
        return None
    p = spec.pricing.get(model)
    if p is None:
        log.warning(
            "[llm] %s/%s has no price entry - cost unknown (not estimated from another model)",
            spec.key, model)
        return None
    if p.valid_until and date.today() > p.valid_until:
        log.warning("[llm] %s/%s price valid_until(%s) has passed - re-check pricing at: %s",
                    spec.key, model, p.valid_until, p.source)
    return round(tokens_in / 1_000_000 * p.price_in_per_1m
                 + tokens_out / 1_000_000 * p.price_out_per_1m, 6)


def _is_fallback_eligible(exc: Exception) -> bool:
    """이 실패가 "다른 프로바이더로 넘기면 실제로 도움이 되는" 종류인가.

    True로 잡는 것:
      - LLMBlockedError(kind in cost/rate_minute/rate_day) -- **프로바이더 단위** 한도라
        다른 프로바이더는 자기 한도가 남아 있을 수 있다(사장님 지시: "한도 초과는 그
        프로바이더만 넘기는 게 맞다"). kind="cost_global"(예약, 아직 아무도 안 던짐)은
        **일부러 여기 넣지 않는다** -- 전체 합산 한도라 프로바이더를 바꿔도 같은 지갑에서
        돈이 나가 우회가 안 된다(사장님 지시: "전체 비용 한도 초과는 폴백하면 안 된다").
      - LLMProviderError(transient=True) -- 네트워크·타임아웃·5xx·상대측 레이트리밋.

    False로 잡는 것(원인이 안 없어지므로 다른 벤더로 넘겨도 소용없다 -- 오히려 설정
    실수를 조용히 감춘다):
      - LLMNotConfiguredError -- 이 프로바이더 키 자체가 없다/비어 있다.
      - LLMProviderError(transient=False) -- 401/403 키 거부·400 잘못된 요청·404 모델명 오타.
      - ValueError 등 그 외 -- 호출부 실수.
    """
    if isinstance(exc, LLMBlockedError):
        return exc.kind in ("cost", "rate_minute", "rate_day")
    if isinstance(exc, LLMProviderError):
        return exc.transient
    return False


def _load_task_assignment(conn, task_key: str) -> dict | None:
    """`ai_task_assignments`(0046)에서 task_key 행을 읽는다 -- provider/model 자동 라우팅
    (`_resolve_task_default`)과 폴백 순서(`_resolve_fallback_order`)가 공유하는 단일 조회
    지점이다(둘이 각자 SELECT를 따로 짜면 "같은 표를 읽는 같은 목적의 쿼리"가 두 벌 된다).

    테이블이 없으면(마이그레이션 0046 미적용) `None` -- 500을 내지 않는다. 이 파일이
    `api/admin_ai_tasks.py`의 `_ready()`(`sa_inspect(conn).has_table(...)`)와 **같은 판단을
    같은 방식으로** 여기 다시 짠다 -- 그 함수를 import하지 않는 이유는, 그 파일이
    admin API 라우터(상위 계층)이고 이 파일은 그 라우터가 저장한 값을 읽기만 하는 하위
    계층이라 반대 방향 의존은 계층을 거꾸로 만들기 때문이다(그리고 그 함수 이름 자체가
    `_`로 시작해 모듈 밖에서 부르지 말라는 신호다).
    """
    if not sa_inspect(conn).has_table("ai_task_assignments"):
        return None
    return conn.execute(text(
        "SELECT providers, fallback_order FROM ai_task_assignments WHERE task_key = :k"),
        {"k": task_key}).mappings().first()


def _resolve_fallback_order(primary_key: str, task_key: str | None) -> list[str]:
    """폴백 순서를 정한다. 우선순위:
      ① task_key가 있고 `ai_task_assignments`(0046)에 그 작업의 행이 있으면 그 행의
         `fallback_order`(벤더 표시명 배열, 예: ["Claude","Codex"])를 읽어 PROVIDERS 키로
         번역한다 -- 이 값이 **단일 원천**이다(ADM-AI-030 화면이 저장하는 바로 그 값,
         CANON "같은 것을 두 벌 두지 않는다"). 테이블이 아직 비적용/0행이면(2026-08-16
         실측) 조용히 다음 순위로 내려간다 -- 500을 내지 않는다(admin_ai_tasks.py의
         `_ready()` 패턴과 동일).
      ② 없으면 코드 기본값: PROVIDERS에 등록된 순서(딕셔너리 순서)에서 primary만 뺀 나머지.
    """
    if task_key:
        try:
            with engine.connect() as conn:
                row = _load_task_assignment(conn, task_key)
                if row and row["fallback_order"]:
                    vendor_to_key = {s.vendor: s.key for s in PROVIDERS.values()}
                    order = [vendor_to_key[v] for v in row["fallback_order"]
                             if v in vendor_to_key and vendor_to_key[v] != primary_key]
                    if order:
                        return order
        except Exception:
            log.exception(
                "[llm] failed to read ai_task_assignments.fallback_order for %s -"
                " falling back to code default order", task_key)
    return [k for k in PROVIDERS if k != primary_key]


def _resolve_task_default(task_key: str) -> tuple[str | None, str | None, str]:
    """task_key로 (provider_key, model)을 정한다. 반환: (provider_key|None, model|None,
    reason) -- reason은 "왜 이 값을 골랐는지"(DB 사용/코드 기본값 사용/근거 없음)를 사람이
    읽을 수 있게 적은 문장이다(호출부가 로그로 남긴다 -- 요구사항 ①의 "왜 코드 기본값을
    썼는지 알 수 있어야" 항목).

    우선순위:
      ① `ai_task_assignments`(0046)에 그 task_key 행이 있고 `providers`(JSONB 배열,
         `[{"vendor":..,"model":..,"role":..}, ...]`) 안에 역할이 `'주'`인 항목이 있으면
         그 vendor/model을 쓴다(벤더 표시명 -> PROVIDERS 키 번역) -- **이 표가 정본이다**
         (ADM-AI-030 화면이 저장하는 바로 그 값, 운영자가 화면에서 바꾸면 그게 이긴다).
         역할 `'주'`가 없으면 배열의 첫 항목을 쓴다(providers는 최소 1개 --
         `admin_ai_tasks._validate_update`가 이미 그렇게 강제한다. `mode='concurrent'`로
         여러 항목이 있어도 이 함수는 하나만 골라 단일 호출한다 -- 모듈 docstring
         "task_key 기반 자동 라우팅" 참고).
         테이블이 없거나(미적용)/행이 없거나(0행, 2026-08-16 실측)/벤더·모델을 PROVIDERS가
         모르면(오타·아직 등록 안 된 모델 문자열) 조용히 ②로 내려간다 -- 500을 내지 않는다.
      ② 코드 기본값 `TASK_DEFAULTS`(사장님 실사용 배정, 2026-08-16).
      ③ task_key가 `TASK_DEFAULTS`에도 없으면(닫힌 4종 밖의 값) `(None, None, reason)`을
         돌려준다 -- `call()`은 이걸 "이 task_key에는 아무 근거가 없다"로 해석해 원래
         하드코딩 기본값("gemini")으로 떨어진다.
    """
    reason = ""
    try:
        with engine.connect() as conn:
            row = _load_task_assignment(conn, task_key)
            providers = (row or {}).get("providers") or []
            if providers:
                primary = next((p for p in providers if p.get("role") == "주"), providers[0])
                vendor_to_key = {s.vendor: s.key for s in PROVIDERS.values()}
                pk = vendor_to_key.get(primary.get("vendor"))
                pm = primary.get("model")
                if pk and pm:
                    return (pk, pm,
                            f"ai_task_assignments row (vendor={primary.get('vendor')!r},"
                            f" role={primary.get('role')!r})")
                reason = (f"ai_task_assignments row has an unrecognized vendor/model"
                          f" ({primary.get('vendor')!r}/{primary.get('model')!r}) -"
                          f" falling back to TASK_DEFAULTS")
            else:
                reason = ("ai_task_assignments has no usable row for this task_key"
                          " (table missing, 0 rows, or empty providers) -"
                          " falling back to TASK_DEFAULTS")
    except Exception:
        log.exception(
            "[llm] failed to read ai_task_assignments.providers for %s -"
            " falling back to TASK_DEFAULTS", task_key)
        reason = "ai_task_assignments read failed (see server log) - falling back to TASK_DEFAULTS"

    default = TASK_DEFAULTS.get(task_key)
    if default:
        return default[0], default[1], (reason or "TASK_DEFAULTS code default")
    return None, None, (reason + "; task_key is also unknown to TASK_DEFAULTS" if reason
                         else f"unknown task_key {task_key!r} - not in ai_task_assignments"
                              f" or TASK_DEFAULTS")


def _call_one(prompt: str, provider: str, task_key: str | None, model: str | None,
              system: str | None, customer_facing: bool, max_output_tokens: int,
              timeout_sec: int, caller_key: int | None = None) -> LLMResult:
    """딱 한 프로바이더에게 한 번 건다 -- 캡 확인 -> 호출 -> 비용 기록. 폴백은 여기서
    하지 않는다(call()이 이 함수를 여러 프로바이더에 대해 순서대로 부른다).

    caller_key: 호출자 식별자(익명 방문자 `users.user_id` -- `api/visitor.py` 참고).
      ⚠ **자리만 있다 -- 아직 아무것도 하지 않는다.** `_check_caps`에도 넘기지 않고
      (사용자별 캡은 이번 범위 밖 -- 모듈 docstring ④), `api_cost_logs`에도 쓰지 않는다
      (그 표에 호출자 컬럼 자체가 없다 -- 마이그레이션 없이는 쓸 칸이 없다). 지금은
      디버그 로그 한 줄로만 흔적을 남긴다 -- 팝콘톡(3단계)에서 사용자별 제한을 실제로
      구현할 때 `api_cost_logs` 스키마와 함께 이 값을 마저 배선하면 된다(그때 이 함수
      시그니처를 또 바꾸지 않아도 되는 것이 이번에 자리를 만드는 목적).
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError(f"unknown provider: {provider} (registered: {', '.join(PROVIDERS)})")

    api_key = os.environ.get(spec.env_key, "")
    if not api_key.strip():
        raise LLMNotConfiguredError(
            f"{spec.env_key} is not set - add a value in .env before calling {spec.vendor}"
            f" (the key name itself is missing, or present but empty)")

    used_model = model or spec.default_model
    has_alt_provider = len(PROVIDERS) > 1
    log.debug("[llm] calling provider=%s model=%s task_key=%s caller_key=%s",
              spec.key, used_model, task_key, caller_key)

    with engine.connect() as conn:
        _check_caps(conn, spec.key, task_key, customer_facing, has_alt_provider)

    t0 = time.monotonic()
    text_out, tokens_in, tokens_out = spec.caller(
        used_model, prompt, system, max_output_tokens, timeout_sec)
    elapsed = time.monotonic() - t0

    cost_usd = _cost_usd(spec, used_model, tokens_in, tokens_out)

    log_id = None
    cost_logged = False
    try:
        with engine.begin() as conn:
            log_id = conn.execute(text(
                "INSERT INTO api_cost_logs (provider, model, tokens_in, tokens_out, cost_usd)"
                " VALUES (:p, :m, :ti, :to, :c) RETURNING log_id"),
                {"p": spec.key, "m": used_model, "ti": tokens_in, "to": tokens_out,
                 "c": cost_usd}).scalar_one()
        cost_logged = True
    except Exception:
        # 이미 호출은 성공해 비용이 발생했다 -- 기록 실패를 이유로 응답을 버리지
        # 않는다(위 모듈 docstring #실패를 삼키지 않는다 참고). 대신 크게 남긴다.
        log.exception(
            "[llm] failed to write api_cost_logs (response is still returned,"
            " cost_logged=False) provider=%s model=%s tokens_in=%s tokens_out=%s cost_usd=%s",
            spec.key, used_model, tokens_in, tokens_out, cost_usd)

    return LLMResult(
        provider=spec.key, model=used_model, text=text_out,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd,
        elapsed_sec=round(elapsed, 3), log_id=log_id, cost_logged=cost_logged)


# ============================================================================
# 공개 진입점 -- 모든 호출이 지나는 단일 자리
# ============================================================================
def call(prompt: str, *, provider: str | None = None, task_key: str | None = None,
         model: str | None = None, system: str | None = None,
         customer_facing: bool = False, max_output_tokens: int = 2048,
         timeout_sec: int = 30, fallback_order: list[str] | None = None,
         caller_key: int | None = None) -> LLMResult:
    """LLM을 한 번 부른다(필요하면 폴백까지). 이 함수 밖에서 프로바이더 SDK를 직접
    부르지 않는다.

    Args:
        prompt: 사용자/작업 프롬프트. 비어 있으면 ValueError(호출 자체를 안 하므로
            캡ㆍ비용에 영향이 없다).
        provider: **주(primary)** 프로바이더 -- PROVIDERS의 키. **생략(None, 기본값)
            하면 task_key로 자동으로 정해진다**(`_resolve_task_default` -- 아래 참고).
            task_key도 없거나 그 작업에 아무 근거가 없으면 옛 하드코딩 기본값 "gemini"로
            떨어진다(하위 호환 -- provider·task_key 둘 다 생략한 옛 호출부는 동작이
            바뀌지 않는다). **명시하면 이 값이 항상 이긴다**(task_key가 있어도
            무시하지 않는다 -- 시험ㆍ특수 호출을 위해).
        task_key: A-35의 4종 작업 키(task.s1_parse 등). **provider=를 생략했을 때
            provider·model을 자동으로 정하는 데 쓰인다**(① `ai_task_assignments`
            우선 ② 없으면 `TASK_DEFAULTS` 코드 기본값). 그 밖에 ③ 작업별 부분 한도
            조회(`_check_caps`) ④ fallback_order 미지정 시 `_resolve_fallback_order`
            에도 쓰인다. 필수 아님 -- 생략하면 이 넷 다 그냥 건너뛴다(옛 동작 그대로).
        model: 생략하면 provider·task_key로 정해진다 -- (명시했든 task_key로 자동
            선택했든) 최종 provider와 task_key의 배정이 **같은 프로바이더를 가리킬
            때만** task 기본 모델을 쓰고, 아니면 `PROVIDERS[provider].default_model`
            (프로바이더당 1개, 옛 동작)로 떨어진다. **명시하면 이 값이 항상 이긴다.**
        system: system instruction(선택).
        customer_facing: action=batch_defer일 때만 의미가 있다 -- 고객이 기다리는
            호출이면 True로 넘겨 한도 초과여도 계속하게 한다. 기본 False(더 안전한
            쪽 -- 무엇인지 모르면 배치로 취급해 막는다).
        max_output_tokens: 단일 호출의 최악 비용을 미리 제한한다(한 번의 거대한
            호출이 캡을 단번에 넘기는 것을 막는 2차 방어선).
        timeout_sec: 프로바이더 HTTP 타임아웃(초). 팝콘톡처럼 고객이 기다리는 자리에
            붙일 때는 짧게 넘기는 것을 권장(확인 결과는 보고서 참고).
        fallback_order: 명시하면 이 순서를 그대로 쓴다(PROVIDERS 키 목록). 생략하면
            `_resolve_fallback_order`가 task_key -> ai_task_assignments -> 코드 기본값
            순으로 정한다. **빈 리스트 `[]`를 넘기면 폴백을 아예 끈다**(주 프로바이더만
            시도) -- model= 를 명시적으로 override한 비교/시험 호출처럼 "정확히 이
            프로바이더·이 모델의 결과만 보고 싶다"는 의도를 표현하는 자리.
        caller_key: 호출자 식별자 -- 익명 방문자 `users.user_id`(`api/visitor.py`의
            `visitor.resolve()`가 돌려주는 바로 그 정수값, 회원 승격 후에도 같은 값이
            이어진다). ⚠ **이번 범위에서는 받아서 로그에 남기기만 한다** -- 사용자별
            캡ㆍ`api_cost_logs` 기록에는 아직 안 쓴다(그 표에 호출자 컬럼이 없다).
            팝콘톡(3단계)에서 사용자별 제한을 실제로 구현할 때 이 값을 마저 배선한다
            -- 지금 자리를 만들어 두면 그때 이 함수의 시그니처를 또 바꾸지 않아도 된다.

    Raises:
        ValueError: prompt가 비어 있거나 (명시했든 task_key로 정해졌든) 최종 provider가
            PROVIDERS에 등록되지 않음.
        LLMNotConfiguredError: **주 프로바이더**부터 키가 없거나 비어 있고(폴백 대상
            아님) 폴백 후보도 전부 같은 이유로 막히면, 마지막 시도의 이 예외가 그대로
            올라온다(아래 LLMAllProvidersFailedError와 달리 "설정 자체가 안 됨"은 굳이
            감싸지 않는다 -- 원인이 한눈에 보이는 편이 낫다는 판단, 판단 근거는 보고서).
        LLMBlockedError: 폴백이 없거나(fallback_order=[]) 전부 실패했을 때, 마지막
            시도의 원인이 이 예외뿐이면 그대로 올라온다.
        LLMProviderError: 위와 같은 경우 마지막 시도가 이 예외뿐이면 그대로 올라온다.
        LLMAllProvidersFailedError: **둘 이상**을 시도했고 전부 실패했을 때 -- 원인이
            섞여 있어(예: 1번은 캡 초과, 2번은 네트워크 오류) 단일 예외 타입으로
            뭉뚱그리면 정보 손실이라 이 전용 예외로 모든 시도를 함께 올린다.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")

    # ── ① task_key -> provider/model 자동 해석 (2026-08-16 세 번째 지시) ─────────
    # provider=·model=을 이미 둘 다 명시했으면 task_key를 몰라도 되므로 DB를 안 읽는다
    # (기존처럼 명시 호출만 하는 호출부는 이 층이 생겨도 DB 왕복이 늘지 않는다).
    task_provider = task_model = None
    task_reason = ""
    if task_key and (provider is None or model is None):
        task_provider, task_model, task_reason = _resolve_task_default(task_key)

    resolved_provider = provider if provider is not None else (task_provider or "gemini")
    if resolved_provider not in PROVIDERS:
        raise ValueError(
            f"unknown provider: {resolved_provider} (registered: {', '.join(PROVIDERS)})")

    # task 기본 모델은 "실제로 쓰기로 한 프로바이더"와 벤더가 같을 때만 적용한다 --
    # 예: task_key의 배정은 claude인데 provider="gemini"를 명시로 넘기면, claude 모델
    # 문자열을 gemini API에 보낼 수 없으므로 gemini의 default_model로 그대로 둔다.
    resolved_model = model
    if resolved_model is None and task_model and task_provider == resolved_provider:
        resolved_model = task_model
    if task_key and (provider is None or model is None):
        # 무엇을 요청했고(requested) task_key가 무엇을 배정했고(assigned) 최종
        # 무엇으로 정했는지(using)를 한 줄로 남긴다 -- 0행/미적용/명시 충돌 어느
        # 경우든 이 로그 한 줄로 "왜 이 값을 썼는지"를 되짚을 수 있다(요구사항 ①).
        log.info(
            "[llm] task_key=%s resolution: requested(provider=%s, model=%s)"
            " assigned(provider=%s, model=%s, %s) -> using(provider=%s, model=%s)",
            task_key, provider, model, task_provider, task_model, task_reason,
            resolved_provider, resolved_model or "(default_model)")

    order = ([resolved_provider] if fallback_order == []
              else [resolved_provider] + [p for p in (fallback_order or
                                          _resolve_fallback_order(resolved_provider, task_key))
                                  if p in PROVIDERS and p != resolved_provider])

    attempts: list[tuple[str, Exception]] = []
    for i, prov in enumerate(order):
        try:
            return _call_one(prompt, prov, task_key,
                              resolved_model if prov == resolved_provider else None,
                              system, customer_facing, max_output_tokens, timeout_sec,
                              caller_key=caller_key)
        except Exception as e:
            attempts.append((prov, e))
            is_last = (i == len(order) - 1)
            if is_last or not _is_fallback_eligible(e):
                if len(attempts) == 1:
                    raise  # 시도가 하나뿐이면 그 예외를 그대로 -- 불필요하게 감싸지 않는다
                summary = "; ".join(f"{p}: {type(exc).__name__}: {exc}" for p, exc in attempts)
                raise LLMAllProvidersFailedError(
                    f"all {len(attempts)} provider(s) failed - {summary}", attempts) from e
            log.warning("[llm] %s failed (%s: %s) - falling back to %s",
                        prov, type(e).__name__, e, order[i + 1])
    raise AssertionError("unreachable - order is never empty")
