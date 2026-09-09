"""상품 분류 관리 신규 화면(ADM-CAT-011 가칭) — `api/main.py`가 자동으로 싣는다.

■★ 정본 확정(2026-09-09 사장님 지시) — LNB("상품관리" > "상품 분류 관리")가
  이제 이 화면(`/admin2/categories-v2`)을 가리킨다. 구 `/admin2/categories`
  (ADM-CAT-010, `api/admin_ui_product_category.py`)는 P-09 동결 — 그대로
  남지만 수정·신규 링크 금지. 두 화면은 **같은 백엔드**를 공유한다 —
  `api/admin_categories.py`에 새 API를 추가하지 않았다.

■ 참고한 승인 디자인 — `docs/design/incoming/dc-product-unified-admin.html`의
  `isCategory` 블록(카테고리 관리 부분만). 그 파일의 DEMO 데이터(의류·식품)는
  무시하고 실데이터로 간다. LEVELS 4단 고정 + 컬럼별 [+ 생성]/이름 입력/노출
  체크박스/하위 보기 버튼 + [변경 저장]/[전체 저장] 패턴을 그대로 옮겼다.

■ 우리 데이터는 지금 최대 2단이다 — LEVELS는 고정 4개를 유지하되(하드코딩된 깊이
  제한이 아니라 "선택된 부모 사슬" 기반 재귀 계산이라, 트리가 깊어져도 화면을
  다시 지을 필요가 없다), 3·4번째 컬럼은 실사용에서 항상 잠김(locked) 상태로
  보인다("OO를 먼저 선택하세요"). `api/admin_categories.py` 자체가 "고정 깊이
  없음"이라 서버는 더 깊은 트리도 그대로 받는다.

■ 신규 화면의 범위 — ADM-CAT-010(마진 설정·활동 이력·위반 집계 포함)과 달리,
  이 화면은 "생성·이름수정·삭제·노출토글·계층 탐색"에 집중한다. 마진 UI는 뺐다
  (승인 디자인 자체에도 마진 UI가 없다 — `margin_rate` 등은 API 응답에 있어도
  화면이 그리지 않는다).

■ 권한 — **지시서 원문은 "쓰기는 owner만"이라 적었지만, 실제 서버는 그렇지
  않다.** `api/admin_categories.py`의 `_operator()`는 owner·operator 둘 다 통과시
  키고(2026-08-13 사장님 결정, 독스트링에 그대로 적혀 있다), 실제로 요청을
  먼저 가로채는 `api/auth.py`의 `required_role()`도 `/api/admin/categories`를
  `OWNER_WRITE_PREFIXES`에 넣지 않아 쓰기 최소 등급이 **operator**다(코드 실측,
  두 곳 다 읽음 — 고치지 않았다). 이미 살아 있는 옆 화면(ADM-CAT-010,
  `templates/admin/product_category.html.j2`)도 이 사실을 따라
  `canWrite('operator')`로 문턱을 잡고 있다. **화면이 서버보다 더 엄격한 문턱을
  지어내면(오너만 된다고 말하면) 실제로는 쓸 수 있는 operator 운영자에게
  거짓을 말하는 것**이라 판단해, 이 화면도 실제 문턱(operator 이상)과 서버가
  실제로 돌려주는 403 문구를 그대로 쓴다. 이 판단은 보고서에도 남긴다 —
  다르게 정할 사장님 몫이면 되돌리기는 이 파일 한 곳만 고치면 된다.

■ 조회는 viewer 이상이면 통과한다(같은 근거, `required_role`이 GET엔 viewer를
  요구).

■ 좌측 메뉴(LNB) — 이번 작업 범위에서 연결하지 않는다(지시서 원문). 검증 통과
  후 하네스가 `api/admin_nav.py`를 별도로 고친다(이 파일 담당 밖).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/categories-v2", response_class=HTMLResponse)
def product_category_v2(request: Request) -> HTMLResponse:
    """상품 분류 관리 — 신규 4단 컬럼 시안(ADM-CAT-011 가칭).

    기존 `/admin2/categories`(ADM-CAT-010)와 **같은 API**(`/api/admin/categories`,
    `api/admin_categories.py`)를 쓴다 — 새 API를 만들지 않았다. 두 화면은 검증이
    끝날 때까지 나란히 존재한다.
    """
    return render(request, "admin/product_category_v2.html.j2",
                  screen_id="ADM-CAT-011", domain="product_category_v2",
                  crumb_group="상품관리", crumb_now="상품 분류 관리(신규)")
