"""AI 응답 기록(ADM-AI-060) API — `api/main.py`가 자동으로 싣는다(§discovery).

요구사항: `docs/design/req/req-ai-response-log.md`. 디자인 정본: `docs/design/dc-ai-
response-log.html`. 실측 근거: `ai-screens-datamap.md` §4.

■ 이 화면은 왜 API가 있는데도 항상 0건을 돌려주는가
  "AI가 무엇을 묻고 뭐라 답했나"를 담는 로그는 이 저장소 어디에도 없다(그레프
  실측 0건 — S1·S2 LLM 호출 경로 자체가 연동 보류로 없다). 잠재 원천 네 갈래
  (`api_cost_logs`·`spec_web_suggestions`·운영 도우미 대화·LLM 호출)가 전부 이
  목적에 못 쓰인다는 사실은 데이터맵과 요구사항 문서가 이미 실측했다 — 이 모듈은
  그중 **DB로 다시 잴 수 있는 두 가지**(`api_cost_logs`·`spec_web_suggestions`의
  행수)만 요청마다 실측해서 내려준다. 나머지 둘(운영 도우미 대화의 서버 미전송,
  LLM 호출 경로 없음)은 코드 구조 자체에 대한 사실이라 SQL로 다시 잴 수 없다 —
  그래서 "실측"이 아니라 "코드 확인"이라고 정직하게 구분해 표시한다.

■ 로그용 테이블을 일부러 만들지 않았다(제작 보고서에도 남김)
  실 LLM 연동이 재개되기 전에는 이 화면에 **영구히 0행**만 쌓인다 — 아무도 그 표에
  쓰지 않기 때문이다(쓰는 코드가 없다). 빈 표를 미리 만들어 두는 것(`cost_thresholds`
  ·`rate_limit_policies`처럼)과, 아예 만들지 않고 "없다"고 말하는 것 중 후자를
  골랐다 — 이 화면의 상세 서랍(입력·출력 전문·플래그)은 실제로 열릴 일이 "연동 후
  미리보기" 모드(클라이언트 전용 가상 데이터, 빨간 배너로 구분)에서만 발생하고,
  실측(measured) 모드는 행이 없어 서랍 자체가 열리지 않는다. 그래서 플래그 쓰기
  API도 만들지 않았다 — 대상이 하나도 없는 쓰기 엔드포인트는 항상 404만 돌려주는
  죽은 코드다. LLM 연동이 재개되어 실제로 로그가 쌓이기 시작하면 그때 테이블·
  플래그 API를 함께 신설한다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/admin", tags=["ai-response-log"])

# 작업 종류 4종(닫힌 목록) — 정본은 decision-log.md A-35(2026-08-13 사장님 확정)다.
# DB 테이블도 코드 상수도 아직 단일 원천이 없다(`ai-screens-datamap.md` §0-1 실측) —
# 여기서는 이 화면의 필터 표시용으로만 옮겨 적는다. AI 작업 설정(ADM-AI-030)이 같은
# 목록을 별도로 들고 있을 수 있다 — 두 화면이 갈라지면 합칠 자리가 필요하다(보고서 참조).
TASKS = [
    {"key": "task.s1_parse", "label": "입력 파싱"},
    {"key": "task.s2_explain", "label": "근거 설명"},
    {"key": "task.ops_assist", "label": "운영 도우미 질의"},
    {"key": "task.spec_fill", "label": "웹 사양 채움"},
]


@router.get("/ai-response-log")
def get_ai_response_log(task: str | None = None, model: str | None = None,
                         period: str | None = None, flagged: int = 0):
    """실측 0건 + "왜 0건인가"를 서버가 실측해 함께 내려준다.

    `task`·`model`·`period`·`flagged` 파라미터는 목록 화면 규약("필터를 바꾸면
    서버에 다시 요청")을 지키기 위해 받아 둔다 — 로그 원천 자체가 없어 결과(빈 목록)
    는 바뀌지 않지만, 그 사실을 감추지 않고 `note`에 명시한다.
    """
    with engine.connect() as conn:
        cost_rows = conn.execute(text("SELECT count(*) FROM api_cost_logs")).scalar() or 0
        web_rows = conn.execute(text("SELECT count(*) FROM spec_web_suggestions")).scalar() or 0

    reasons = [
        {
            "key": "api_cost_logs",
            "name": "api_cost_logs",
            "chip": "컬럼 없음",
            "measured": f"실측 {cost_rows}행 · provider·model·tokens_in/out·cost_usd",
            "why": ("비용 집계 전용 스키마입니다. 질문·답변 텍스트를 담을 컬럼이 아예 "
                    "없어 행이 쌓여도 감사에는 못 씁니다."),
        },
        {
            "key": "spec_web_suggestions",
            "name": "spec_web_suggestions",
            "chip": "결과만 남음",
            "measured": f"실측 {web_rows}행 · source_url·confidence·note",
            "why": ("최종 채택된 값 하나만 남깁니다. 무엇을 검색했고 어떤 후보를 "
                    "버렸는지는 기록되지 않아 \"무엇을 물었나\"를 복원할 수 없습니다."),
        },
        {
            "key": "ops_helper_chat",
            "name": "운영 도우미 대화",
            "chip": "서버 미전송",
            "measured": "코드 확인 · sessionStorage['popcorn-admin-helper']",
            "why": ("브라우저 세션에만 저장되고 서버로 보내지 않습니다(코드 주석에 "
                    "명시). 서버가 애초에 받지 않는 내용입니다."),
        },
        {
            "key": "llm_calls",
            "name": "S1·S2 LLM 호출",
            "chip": "호출 경로 없음",
            "measured": "코드 확인 · api/·tools/ 호출 경로 0건",
            "why": ("연동 보류(2026-07-21 결정)로 호출 코드 자체가 없습니다. 호출이 "
                    "없으니 남길 응답도 없습니다."),
        },
    ]

    return {
        "items": [],
        "total": 0,
        "tasks": TASKS,
        "filters_echo": {"task": task, "model": model, "period": period,
                          "flagged": bool(flagged)},
        "reasons": reasons,
        "note": ("기록이 0건인 것은 아직 아무도 안 써서가 아니라, 남기는 계측 지점이 "
                 "저장소 어디에도 없어서입니다. 선행 조건은 ① 실 LLM 연동 재개"
                 "(2026-07-21 보류, 별도 승인 필요) ② 운영 도우미 대화의 서버 전송 "
                 "시작(현재는 브라우저 저장 전용)입니다."),
    }
