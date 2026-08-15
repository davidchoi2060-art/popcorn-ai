"""상품 일괄 등록(ADM-CSV-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-product-bulk-import.html`(사장님 Claude Design 승인 원안,
2026-08-14 확정 — `id="1b"` 문장 보고서형 + 턴 2 `2a`~`2d` 상태 4장)을
`templates/admin/catalog_import.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-product-bulk-import.md`. 확정 근거: `docs/decisions/decision-log.md`
UX-21. 원안·데이터 계약·오류 상태 관례·원안과 다르게 만든 지점은 전부 템플릿 파일 상단
주석에 있다(중복 기록하지 않는다).

■ 데이터 API — 새로 만들지 않았다. 전부 이미 있는 것을 그대로 쓴다(읽기·쓰기 모두 수정 없음).
  · `POST /api/admin/catalog-import/dryrun` · `POST /api/admin/catalog-import/apply`
    (`api/admin_catalog_import.py`) — owner 전용(쓰기).
  · `GET /api/admin/import-jobs` · `GET /api/admin/import-jobs/{job_id}/rows`
    (`api/admin_imports.py`) — viewer 이상(조회).
  · `GET /api/admin/product-meta`(`api/admin_products.py`) — 드라이런 리포트의 "부품 종류별
    분포"에 쓰는 부품 라벨(코드→한글) 원천. `taxonomy.PART_LABELS`를 이 화면에 다시 옮겨
    적지 않으려고 이미 그 값을 읽어 내려주는 기존 엔드포인트를 재사용한다.

■ 권한 — `api/auth.py`의 `OWNER_WRITE_PREFIXES`에 `/api/admin/catalog-import`가 명시돼
  업로드·적용(쓰기)은 owner만, 이력·오류 조회(GET)는 viewer 이상이면 열린다(실측, 비대칭은
  의도된 설계 — decision-log UX-21). 화면은 역할이 owner 미만이면 업로드 영역 전체를
  "잠김" 안내로 바꾼다(원안 `2d`).

■ 좌측 메뉴(LNB) 참고 — `api/admin_nav.py`의 "상품관리" 그룹 "상품 일괄 등록" 항목은 이
  라우트가 만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그 파일은 이 작업의 담당
  범위 밖이라 고치지 않았다(지시서: "메뉴 링크는 내가 따로 붙인다"). href를
  `/admin2/catalog-import`로 올려야 LNB에서 이 화면으로 갈 수 있다(제작 보고서에 남김).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/catalog-import", response_class=HTMLResponse)
def catalog_import(request: Request) -> HTMLResponse:
    """상품 일괄 등록(ADM-CSV-010).

    가장 위험한 쓰기 화면 — 파일 하나가 정본 카탈로그 전체를 upsert로 덮을 수 있고
    적용 후 되돌리기가 없다. 업로드 → 드라이런(계획만, DB 미변경) → 확인 → 적용의 순서가
    강제되고, 같은 화면 안에서 과거 배치 이력·거부 행 원본을 이어서 조회한다(옛 3화면
    통합 — ADM-SYS-030/040·ADM-IMP-010·중복 ADM-PRD-040은 이 ID로 흡수·폐기).
    """
    return render(request, "admin/catalog_import.html.j2",
                  screen_id="ADM-CSV-010", domain="catalog_import",
                  crumb_group="상품관리", crumb_now="상품 일괄 등록")
