"""ADM-SRC-010 매입 견적(용산) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

계약: `docs/design/spec-sourcing.md`(사장님 확정 2026-08-15 · 1a 안 — 목록 + 우측 작업
패널) · 요구사항 `docs/design/req/req-sourcing-quote.md`. 데이터는 이미 있는 API를
그대로 쓴다(`api/admin_sourcing.py` — 서버 페이지네이션·검색·부품종류 필터·요청·회신·
확정이 전부 실데이터로 이미 동작한다). 이 파일은 `admin_ui_price_review.py`와 같은
패턴으로 페이지 껍데기만 서버 렌더하고, 목록·작업 흐름은 템플릿
(`templates/admin/sourcing.html.j2`)의 클라이언트 스크립트가 그 API를 불러 채운다.

■ 제작 전에 잰 것 (MAKER-CHECKLIST §8 — 하네스 말이 아니라 코드·DB를 읽었다)
  ① 서버 페이지네이션은 **이미 된다**(슬라이스 86에서 이미 고쳐짐) — 실측:
     `GET /api/admin/sourcing`(size=50) 응답 13,699바이트 · 50건만(전체 15,338건 중).
     예전 "15,261건·3.6MB 통째 전송" 사고는 재발하지 않는다.
  ② 확정 응답은 `purchase_changed`·`sale_changed`·`sale_locked`를 **이미 준다.**
     다만 계약 ㉰가 요구하는 "148,000 → 142,000" 같은 실제 전·후 값은 없어서
     `admin_sourcing.py`의 `confirm_quote()`에 `purchase_before/after`·
     `sale_before/after`를 추가했다(아래 ③).
  ③ `sourcing_batches`(총 6건 — 진행 5·완료 1)·`product_sourcing_quotes`(총 12건 —
     요청 9·회신 1·확정 1·취소 1)는 이미 스키마에 있다(ERD §3.10, 0006 마이그레이션).
     안전재고는 `products.safety_stock`(0004) — API가 이미 읽는다.
  ④ 대기 모집단 **15,338건**(2026-08-15 재측정 — req 문서의 08-13 스냅샷과 동일).
     활성 공급처 **4곳**(전체 5곳 중 1곳 '중지') — 0곳 안내 분기는 지금은 실제로
     타지 않지만 계약이 명시한 경계라 구현한다.

■ `admin_sourcing.py`에 더한 것 — 상세 사유는 그 파일의 주석 참조
  · `GET /sourcing`의 `suppliers`를 활성(`status='활성'`)만 + `brands` 포함으로 좁혔다
    (다른 소비자 없음 — 실측: 이 화면과 회귀뿐이고 회귀는 `suppliers` 필드를 안 읽는다).
  · `GET /sourcing`에 `in_progress_total`을 더했다 — "대기 {N}건 중 진행 중인 견적이
    있는 상품은 {n}건"(계약 §② 배너)은 **전체 모집단** 기준이라 페이지 단위로는 못 센다.
  · `POST /sourcing/quotes/{id}/confirm`에 `purchase_before/after`·`sale_before/after`.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(tags=["admin-ui"])


@router.get("/admin2/sourcing", response_class=HTMLResponse)
def sourcing_page(request: Request) -> HTMLResponse:
    """ADM-SRC-010 매입 견적(용산) — 1a: 좌 목록(서버 페이지네이션 50건) + 우 작업 패널.

    실데이터는 클라이언트가 `GET /api/admin/sourcing`(대기 목록 + 진행중 견적 + 최근
    확정 이력) + `GET /api/admin/product-meta`(부품 종류 필터 선택지) +
    `POST /api/admin/sourcing/request|quotes/{id}/reply|quotes/{id}/confirm`
    (견적 요청 기록·회신 대행 입력·매입 확정)을 불러 채운다. 화면이 숫자를 스스로
    세지 않는다 — 배너의 대기 건수·진행 중 건수·오늘 확정 건수는 전부 서버 응답값이다.
    """
    return render(request, "admin/sourcing.html.j2",
                  screen_id="ADM-SRC-010", domain="sourcing",
                  crumb_group="매입 · 소싱", crumb_now="매입 견적(용산)")
