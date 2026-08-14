"""상품 분류 관리(ADM-CAT-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-product-category.html`(사장님 Claude Design 승인 원안)을
`templates/admin/product_category.html.j2`로 옮긴 것이다.

■ 데이터 API 정정(2026-08-13) — **처음 받은 지시서의 `/api/admin/product-category/*`
  경로는 존재하지 않는 것이었다.** 실측 결과 카테고리 백엔드는 이미 전부 구현돼
  있고(구화면 `mockups/admin/categories.html`이 지금도 쓰고 있다), 정본은
  `api/admin_categories.py`의 **`/api/admin/categories`**(단수형 경로, 복수 세그먼트
  아님)다. 이 템플릿은 그 기존 API를 그대로 소비한다 — 새 API를 요구하지 않는다.
  표는 `categories`(트리) + `category_margin_policies`(1:1 마진, `products` 아님).

  **카테고리 트리 편집(추가·수정·삭제·마진)에는 되돌리기 API가 없다**(실측 0건 —
  `admin_operator_activity_logs`에 로그는 남지만 역방향 전이 엔드포인트가 없다).
  화면은 이 사실을 "미구현"으로 정직하게 표시한다(꺼짐·변경없음처럼 보이지 않게).
  참고로 "상품 분류 매핑"(다른 화면 소관)의 `POST /api/admin/category-mapping/undo`는
  **상품 이동 되돌리기**이고 이것과는 다른 기능이다 — 혼동하지 않는다.

  변경 이력 표시는 카테고리 전용 조회 API가 없어 범용 `GET /api/admin/activity-logs`
  (`api/admin_activity_logs.py`, 최근 500건 · 전 도메인 혼합)를 불러 `kind==='category'`
  로 **화면에서** 걸러 쓴다 — 500건 밖에 있는 과거 카테고리 이력은 이 화면에 안 보일
  수 있다는 뜻이라, 빈 목록 문구도 "이력이 없다"가 아니라 "최근 500건 안에는 없다"로
  적었다.

요구사항 정의서: `docs/design/req/req-product-category.md`(단, ④의 API 표는 위 정정
이전 스냅샷이라 API 경로 자체는 이 파일의 실측이 우선한다 — 나머지 운영 전제·기능
서술은 여전히 유효).

■ 좌측 메뉴(LNB) 참고 — `api/admin_nav.py`의 "상품관리" 그룹 1번째 항목("상품 분류
  관리")은 이 라우트가 만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그
  파일은 이 작업의 담당 범위 밖이라 고치지 않았다 — href를 `/admin2/categories`로
  올려야 LNB에서 이 화면으로 갈 수 있다(제작 보고서에 남김).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/categories", response_class=HTMLResponse)
def product_category(request: Request) -> HTMLResponse:
    """상품 분류 관리(ADM-CAT-010).

    구화면 `mockups/admin/categories.html`(같은 화면 ID, 백업용 동결 — P-09)과 **같은
    API**(`/api/admin/categories`, `api/admin_categories.py`)를 쓴다 — 다만 이 화면은
    admin2 셸(`_admin2_shell.html.j2`)을 상속하고, 실제 로그인 등급(`Admin2Shell.
    canWrite('owner')`)만으로 쓰기를 가른다(구화면의 역할 스위처 같은 장치 없음).

    평소엔 조용한 화면이다: 트리는 거의 안 바뀌고, 여는 계기는 상단 지표(허용 종류
    위반 · 미배정 상품)가 늘었을 때뿐이라는 것이 요구사항 정의서 ①의 운영 전제다.
    """
    return render(request, "admin/product_category.html.j2",
                  screen_id="ADM-CAT-010", domain="product_category",
                  crumb_group="상품관리", crumb_now="상품 분류 관리")
