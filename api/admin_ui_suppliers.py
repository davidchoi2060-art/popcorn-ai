"""공급처(ADM-SRC-030) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/suppliers", response_class=HTMLResponse)
def suppliers_page(request: Request) -> HTMLResponse:
    """공급처(ADM-SRC-030) — **신설**. 계약: `docs/design/spec-suppliers.md`(1b 안,
    사장님 확정 2026-08-15). 정의서: `docs/design/req/req-suppliers.md`.

    ⚠ admin2 «신규» 구축이다 — 구화면(`mockups/admin/suppliers.html`)은 백업용
    동결(P-09), 옮기지 않고 새로 지었다.

    데이터는 기존 API를 그대로 쓴다(`api/admin_suppliers.py`) — 이 화면 작업으로
    아래 세 가지를 그 파일에 보강했다(이 라우트 파일은 렌더만 한다, 로직 없음):
      GET   /api/admin/suppliers              목록. **보강**: 행마다 `preset_count`
                                                (supplier_presets 건수 — 원래 없었다,
                                                파서 프리셋 열의 원천), 응답 최상위에
                                                `inactive`·`no_preset_count` 추가.
      POST  /api/admin/suppliers               등록. **보강**: 409 중복 응답에
                                                `platform`·`brands`를 추가로 실어
                                                보낸다 — "되살리기" 버튼이 PATCH로
                                                되살릴 때 이 값이 없으면 전체 덮어쓰기
                                                의미상 NULL로 지워버리기 때문이다.
      PATCH /api/admin/suppliers/{id}          수정. **보강**: 이름 중복 409를
                                                문자열 하나에서 등록과 같은 구조화된
                                                딕셔너리로 바꿨다(정의서 §⑦ "등록·수정
                                                공통" 요구를 실제로 채움).
      GET   /api/admin/suppliers/{id}/impact   중지 전 영향 미리보기 — **이미 있었다**
                                                (계약이 "없을 가능성이 크다"고 적었지만
                                                실측 결과 이미 구현돼 있었다). 연결된
                                                매입가·단가표 파일·"유일한 매입처인
                                                상품 수"를 전부 준다. 신설하지 않았다.

    ⚠ 기본키는 목록·등록·수정 응답 전부 `id`다(`supplier_id`가 아니다) — 이 저장소가
    정확히 이 화면에서 그 혼동으로 사고를 낸 전례(2026-08-05)가 있어 화면 마크업에도
    `id {{ }}`를 그대로 보이게 둔다. 다만 `.../impact` 응답 하나만 최상위 키가
    `supplier_id`다(다른 세 응답과 다른 모양 — 클라이언트 스크립트가 이 차이를
    알고 읽는다, 새로 통일하지 않았다: `admin_suppliers.py`는 담당 파일이 아니라
    "필요하면 연다"는 지시 범위 안에서 위 세 가지만 최소로 보강했다).

    좌측 메뉴(LNB) 연결은 이 작업의 소관이 아니다(`api/admin_nav.py`는 정본 —
    기록자가 검증 통과 후 연다). 지금은 `href=None`으로 "매입 · 소싱" 그룹에 이미
    항목만 있고, 주소를 직접 입력해 들어간다: `/admin2/suppliers`.
    """
    return render(request, "admin/suppliers.html.j2",
                  screen_id="ADM-SRC-030", domain="suppliers",
                  crumb_group="매입 · 소싱", crumb_now="공급처")
