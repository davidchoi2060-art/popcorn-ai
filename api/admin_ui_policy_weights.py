"""추천 기준 보기(ADM-ENG-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

**조회 전용.** 계약 `docs/design/spec-policy-weights.md`(1a "티어 3열 대조" 확정,
2026-08-14) + 정의서 `docs/design/req/req-policy-weights.md`.

`GET /api/admin/engine-rules`(`api/admin_engine_rules.py`) 응답 중 **`tiers`·`budget`만**
쓴다. 같은 응답에 실려 오는 `compat`(「조립 호환 규칙」소관)·`pricing`(「판매가」소관)은
이 화면이 표시도 편집도 하지 않는다 — 두 화면이 같은 값을 다르게 고치면 아무도 못 믿는다
(계약 §여기서 다루지 않는 것). `weights`(policy_weights 원본, 실측 0행)는 예외적으로
"이 표가 비어 있다"는 사실 자체를 보여주는 용도로만 읽는다(행 수만 — 값을 편집하지 않는다).

화면 이름: 디자인이 "추천 기준 설정" -> "추천 기준 보기"로 바꿀 것을 제안했다(근거 — 지금
이 화면에서 바꿀 수 있는 값이 하나도 없다, 전부 코드 상수). **사장님 확정 전**이므로 화면
안에서는 제안된 "추천 기준 보기"를 쓰되, `api/admin_nav.py`의 메뉴 라벨(정본 — 하네스 몫)은
건드리지 않는다. crumb_group="상품사양관리"는 admin_nav.py를 직접 읽지 않고, 같은 그룹을
쓰는 형제 화면 세 곳(`admin_ui_build_map.py`·`admin_ui_reviews.py`·`admin_ui_spec_standard.py`)
의 실제 라우트 인자를 대조해 확인했다.

부품 라벨(그래픽카드·메인보드·CPU쿨러(공랭) 등)은 이 화면이 다시 정의하지 않는다 —
`taxonomy.PART_LABELS`(단일 원천, `.claude/CANON.md` §1)를 그대로 읽어 렌더 시점에
JSON으로 실어 보낸다. 예산 배분율(BUDGET_ALLOC)·태그 스코프 API 응답은 `part_type` 코드
(GPU·MB·COOLER_CPU_AIR 등)만 주므로, 화면 쪽 JS가 이 맵으로만 한글 라벨을 붙인다.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render
from .taxonomy import PART_LABELS

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/policy-weights", response_class=HTMLResponse)
def policy_weights(request: Request) -> HTMLResponse:
    """추천 기준 보기(ADM-ENG-020) — 신설. `api/admin_nav.py` "상품사양관리" 그룹,
    "부품 등급 관리" 다음(정본은 admin_nav.py — 이 라우트는 라벨을 다시 정의하지 않는다).
    """
    return render(request, "admin/policy_weights.html.j2",
                  screen_id="ADM-ENG-020", domain="policy-weights",
                  crumb_group="상품사양관리", crumb_now="추천 기준 보기",
                  part_labels_json=json.dumps(PART_LABELS, ensure_ascii=False))
