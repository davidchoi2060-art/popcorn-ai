"""엑셀 다운로드 관리(ADM-SYS-050) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

화면 자체는 `docs/design/dc-excel-export.html`(사장님 Claude Design 승인 원안)을
`templates/admin/excel_exports.html.j2`로 옮긴 것이다. 요구사항 정의서:
`docs/design/req/req-excel-export.md`(2026-08-13, "구화면 대응 없음 — 완전 신규").

■★ 데이터 API — **없다. 새로 만들지도 않았다**(지시서: "API 를 지어내지 마라").
  이 작업(제작 범위 = 템플릿 + UI 라우트만)에서 독립적으로 재확인한 실측(2026-08-14):

    코드 검색(api/ 전체, grep)
      celery|rq|arq|huey|BackgroundTasks 사용 0건
      Workbook(|StreamingResponse|FileResponse|Content-Disposition 검색 결과:
        StreamingResponse는 dash.py 1건뿐이고 SSE 실시간 스트림이라 파일 다운로드가
        아니다. FileResponse는 main.py 1건뿐이고 정적 mockup HTML을 돌려주는 용도라
        생성 파일과 무관하다. Workbook() 파일 쓰기 0건.
      api/*.py 파일명에 excel·export·download·queue·job이 들어간 모듈 0개
    DB 조회(information_schema.tables, 읽기 전용 SELECT 1회, 부작용 없음)
      테이블명에 export·download·queue·task·celery가 들어간 테이블 0개
      job이 들어간 테이블은 `csv_import_jobs` 1개뿐(실측 11행) — 컬럼이
      file_name/row_total/row_ok/row_error/row_review/status/created_by/created_at/
      data_origin/source로 **업로드(적재) 결과 기록용**이다. 방향이 반대(들여오기)이고
      비동기 워커가 채우는 방식도 아니다(요청이 끝난 뒤 동기로 기록됨) — 그대로
      재사용하면 "이름만 큐, 실제로는 동기"가 된다(요구사항 정의서 ④와 동일 결론).
    화면 검색(mockups/admin/*.html, templates/admin/*.html)
      "내보내기"·"다운로드"·"Export" 문구가 실제 동작(data-action·onclick)과 연결된
      곳 0건. 유일한 매치는 `_demo-products.html`(템플릿 잔재, 화면 아님)과
      `home.html.j2`의 Phoenix 데모 드롭다운(href="#!" 죽은 링크) — 둘 다 기능하는
      발신 버튼이 아니다.

  **결론: 비동기 큐는 이름만 있고 실체가 없다.** 큐 상태 테이블 · 조회 API · 요청
  생성 API · 파일 다운로드 API · 파일 생성 백그라운드 실행 수단, 다섯 다 0이다.
  이 화면(템플릿)은 그래서 **어떤 API도 호출하지 않는다** — 지어낸 엔드포인트를
  두느니 클라이언트 JS를 아예 넣지 않았다(순수 서버 렌더 정적 페이지, 상세 근거는
  템플릿 파일 상단 주석). 데이터 API가 필요해지면(사장님 결정 이후) 그때 별도로
  짓는다 — 이 라우트는 페이지 뼈대만 내려준다(다른 admin2 화면과 같은 관행).

■★ "미구현"을 "비어 있음"처럼 보이지 않게 — 화면은 값이 없을 때 "0"이 아니라
  "—"(집계 불가)를 쓰고, 목록 빈 상태 문구가 "요청 0건"과 "표 자체가 없음"을
  명시적으로 구분한다. 상세 근거는 템플릿 파일 상단 주석(§데이터, §미구현을
  비어있음처럼 보이지 않게).

■ 좌측 메뉴(LNB) 참고 — `api/admin_nav.py`의 "엑셀 다운로드 관리" 항목은 이 라우트가
  만들어진 시점에도 여전히 `href=None`(신설 예정)이다. 그 파일은 이 작업의 담당
  범위 밖이라 고치지 않았다(지시서: "메뉴 링크는 내가 따로 붙인다") — href를
  `/admin2/excel-exports`로 올려야 LNB에서 이 화면으로 갈 수 있다.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/excel-exports", response_class=HTMLResponse)
def excel_exports(request: Request) -> HTMLResponse:
    return render(
        request, "admin/excel_exports.html.j2",
        screen_id="ADM-SYS-050", domain="excel_exports",
        crumb_group="시스템", crumb_now="엑셀 다운로드 관리",
    )
