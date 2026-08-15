"""상품 사양 정의(ADM-PRD-050) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

**정본 이름 확정(기록자, 2026-08-14) — decision-log UX-27**: 이 화면은 「상품 스펙 관리」·
「사양 항목 정의」·「상품 사양 정의」세 이름으로 불려 왔다. 화면 라벨·경로·문구는
**「상품 사양 정의」**로 통일한다(충돌이 아니라 한 화면의 이름이 셋이었을 뿐).

**이 화면이 다루는 저장소** — `spec_field_defs`(메타) · `product_specs`(실제 값 컬럼).
`std.spec_defs`(조립 사양 표준, `/admin2/spec-standard`)와는 **다른 저장소**다: 그쪽은
사람이 조립 경험으로 넓혀가는 실험 표준(EAV)이고, 아직 견적 엔진이 읽지 않는다. 여기는
**엔진이 실제로 읽는 살아 있는 스키마**다. 조립 사양 표준의 「정본 승격」이 도착하는
자리가 여기다(아직 승격 API는 없다 — `spec_standard.html.j2` 담당자 실측 갭 참조).

승인 디자인 `docs/design/dc-spec-field-defs-2안.html`의 **1a(항목 축)만 정본**이다
(UX-27, 2026-08-14 사장님 확정). 1b(부품 축)는 탈락 — 구조를 가져오지 않았다. 다만
1b가 시연하던 **건강 상태 배너(정상/위험)의 셋**(상시 경고 배너 + 항목 위험 표시 +
조치 지시문)은 공통 확정 사항이라 1a 쪽으로 옮겨 구현했다(`spec_field_defs.html.j2`
JS `renderHealth()` 참조).

데이터 API(`api/admin_spec_fields.py`)는 이 작업의 담당 밖이라 고치지 않았다 — 실측
결과는 이 라우트의 docstring이 아니라 제작 보고서에 남긴다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/spec-field-defs", response_class=HTMLResponse)
def spec_field_defs(request: Request) -> HTMLResponse:
    """상품 사양 정의(ADM-PRD-050) — 사양 항목(31개, 실측 2026-08-14)을 항목 축으로 본다.

    열람은 등급 무관(viewer 이상) · 항목 추가는 owner 전용(`auth.OWNER_WRITE_PREFIXES`가
    `/api/admin/spec-fields` POST를 이미 막는다 — 이 라우트·템플릿은 그 사실을
    화면에 반영만 한다). 값 입력·검수는 이 화면 소관이 아니다(요구사항 정의서 §비범위).
    """
    return render(request, "admin/spec_field_defs.html.j2",
                  screen_id="ADM-PRD-050", domain="spec-field-defs",
                  crumb_group="상품사양관리", crumb_now="상품 사양 정의")
