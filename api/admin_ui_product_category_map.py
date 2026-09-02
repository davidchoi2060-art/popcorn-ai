"""상품 분류 매핑(ADM-CAT-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-product-category-map.html`(사장님 Claude Design 승인 원안)을
`templates/admin/product_category_map.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-product-category-map.md`.

■ 데이터 API — 새로 만들지 않았다. 이미 구현·실사용 중이던 것을 그대로 소비한다.
  `GET /api/admin/category-mapping` · `POST /api/admin/category-mapping/move` ·
  `POST /api/admin/category-mapping/undo` (전부 `api/admin_category_mapping.py`, 읽기만
  — 수정하지 않았다). 트리(좌측 패널·이동 대상 선택지)는 그 응답의 `categories[]`가
  아니라 **`GET /api/admin/categories`**(읽기 전용)에서 온다 — 그쪽이 `allowed_labels`
  (표시용으로 이미 접힌 라벨)·`violations`(허용 종류 위반 수) · `in_stock_count`까지
  주는데, `/category-mapping`의 `categories[]`는 `allowed_part_types`(원시 코드)만 주고
  이 두 필드가 없다. 같은 트리를 두 벌 만들지 않으려고 더 풍부한 쪽 하나만 쓴다.

■ "상품 분류 관리"(ADM-CAT-010)와 다른 경계 — 이 화면은 **상품을 옮기기만** 한다.
  분류의 이름·구조·허용 부품 종류·마진은 그 화면 소관이라 여기서는 트리를 읽기 전용으로만
  쓴다. 쓰기는 이동/되돌리기(`POST .../move`, `POST .../undo`) 둘뿐이고 **operator
  이상**이면 된다(카테고리 관리 화면은 owner 전용 — 다르다, `api/admin_category_mapping.
  py`의 `_operator()` 실측).

■ 좌측 메뉴(LNB) 참고(2026-09-02 기록자 정정 — 요청 #32 검증 발견) — `api/admin_nav.py`의
  "상품관리" 그룹 "상품 분류 매핑" 항목은 이 라우트가 만들어진 시점(커밋 `df264fc`,
  2026-08-14 18:41:08)에 이미 `href="/admin2/category-mapping"`로 연결돼 있었다
  (커밋 `bd087b0`, 같은 날 18:40:01 — 1분 먼저 admin2 셸 정본화 물결이 IA 전체의 href를
  올렸다). 정의서(`docs/design/req/req-product-category-map.md`, 2026-08-13 작성)
  시점엔 실제로 `href=None`이었는데, 그 서술이 다음 날 이 주석에 그대로 옮겨져 낡은 채
  남아 있었다. **왜 고쳤나**: 옛 서술을 사실로 읽으면 "LNB 연결이 안 됐다"고 오판해
  이미 끝난 href 연결을 다시 하려 들 수 있다 — 실측: `grep -n "상품 분류 매핑"
  api/admin_nav.py`(href 값 확인) · `git log -1 --format=%ai bd087b0`·`df264fc`
  (시각 비교).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/category-mapping", response_class=HTMLResponse)
def product_category_map(request: Request) -> HTMLResponse:
    """상품 분류 매핑(ADM-CAT-020).

    대량 처리 화면 — 카테고리가 없는 상품(미매핑) · 허용 종류를 어기는 매핑(위반) ·
    부품 종류를 못 정한 상품(미분류, `part_type='ETC'`)을 범위로 골라 여러 건을 한
    카테고리로 한 번에 옮긴다. 서버가 우선순위(미매핑 > 위반 > 미분류 > 전체)로 계산한
    `open_at`으로 처음 범위가 열린다 — "할 일이 있는 곳"이 기본으로 보인다.
    """
    return render(request, "admin/product_category_map.html.j2",
                  screen_id="ADM-CAT-020", domain="category_mapping",
                  crumb_group="상품관리", crumb_now="상품 분류 매핑")
