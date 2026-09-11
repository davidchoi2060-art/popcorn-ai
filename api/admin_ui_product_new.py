# -*- coding: utf-8 -*-
"""상품 등록·수정(ADM-PRD-011 가칭) — admin2 페이지 라우트. `api/main.py`가 자동으로 싣는다.

■ 계약 — `docs/design/req/req-product-new.md`(요구사항 정의서, ④ ○ 판정 11항목) ·
  `docs/design/spec-product-unified.md`(§4 사장님 확정 4건, ①「상품등록/수정」신설을
  `/admin2/product-new` 로 확정) · `docs/decisions/decision-log.md` A-127.
  원안(`docs/design/incoming/dc-product-unified-admin.html` isProduct 블록,
  247~526행 근처)은 참고용 — 정의서가 상위다(지시서 그대로).

■ 이 파일은 «페이지 라우트만» 갖는다 — 데이터 API 는 전부 `api/admin_products.py` 에
  이미 있다(담당 밖·수정하지 않는다). 정의서 ④가 전수 적은 그대로 쓴다:
      GET   /api/admin/product-meta            선택지(분류·제조사·판매상태)
      GET   /api/admin/product-similar         등록 전 중복 판정(dedupe.SIMILAR_THRESHOLD)
      POST  /api/admin/products                신규 등록
      GET   /api/admin/products/{code}         수정 모드 초기값
      PATCH /api/admin/products/{code}         단건 수정(EDITABLE 필드만)
      PATCH /api/admin/products/{code}/specs   (이 화면 밖 — 링크만 남길 수 있음, 미사용)
      POST  /api/admin/products/{code}/suppliers (이 화면 밖 — 미사용)
  새 API를 짓지 않았다.

■ ⚠ 자기검증으로 발견한 사실(코드 실측, `api/admin_products.py` 직접 읽음) — 정의서
  ④ ○ 판정 11항목(상품명·SKU·제조사·브랜드·모델명·분류·판매상태·카테고리·판매가·
  매입가·재고수량)은 "현행 스키마 컬럼이 있다"는 판정이지 "현재 등록/수정 API가
  그 값을 받는다"는 뜻이 아니다. 실측 결과:
    - `RegisterBody`(POST /products) 필드: name·part_type·part_label·supplier_id·
      model_name·cost_price·danawa_code·maker·supplier·confirm_similar — **브랜드·
      카테고리·판매가·재고수량·판매상태 필드 자체가 없다.**
    - INSERT 문 리터럴: `status='판매중'`·`stock_qty=0` **고정**. `sale_price`·
      `category_id`·`brand`·`model_name`(products 컬럼 자체)은 그 INSERT 목록에
      아예 없다 — model_name 은 `supplier_id` 가 있을 때만 `supplier_product_map`
      매칭에 쓰이고 `products.model_name` 에는 저장되지 않는다.
    - `EDITABLE`(PATCH /products/{code} 허용 필드, 실측):
      `danawa_code·maker·market_price·model_name·name·purchase_price·sale_price·
      status·stock_qty·supplier` — **브랜드·카테고리·분류(part_type) 는 없다.**
    - `GET /products/{code}` 의 SELECT 목록에도 **brand·category_id 컬럼 자체가
      없다** — 조회 응답에 값이 실리지 않는다.
  화면(`templates/admin/product_new.html.j2`)은 이 사실을 근거로, 11항목을 전부
  화면에 "그대로" 두되(지시서 요구) 서버가 실제로 받지 않는 자리는 **비활성 +
  사유 병기**로 처리한다 — 입력하면 저장되는 것처럼 가장하지 않는다(CANON §2-1,
  MAKER-CHECKLIST "if(!res.ok) return; 금지"와 같은 정신 — 조용한 거짓을 만들지
  않는다). 상세는 템플릿 파일 머리말 주석 참조.

■ 권한 — 별도 코드 없이 이미 만족된다(`api/auth.py` 패턴, stock_inbound 라우트와 동일).
  `/api/admin/*` 전역 규칙(`required_role`)이 GET=viewer · 그 외(POST/PATCH)=operator다.
  `/api/admin/products*` 는 `OWNER_WRITE_PREFIXES` 에 없다 — owner 전용이 아니다.
  이 페이지 라우트 자체는 GET 하나뿐이라 viewer 이상이면 연다(공용 미들웨어가 처리).

■ 라우트 = `/admin2/product-new`. 화면 ID = `ADM-PRD-011`(가칭 — 확정 전, 지시서 그대로).
  `?code={product_code}` 유무로 등록/수정 모드를 가른다 — 모드 판정 자체는 서버가
  아니라 **화면(JS)** 이 `location.search` 로 한다(다른 admin2 화면과 같은 방식 —
  페이지 라우트는 쿼리스트링을 몰라도 되는 정적 셸이다). 다만 상단 breadcrumb 문구는
  `?code=` 유무를 여기서 미리 읽어 등록/수정으로 갈라 보여준다(첫 페인트부터 맞는
  라벨을 보여주기 위함 — 화면 JS 가 다시 한번 같은 판정을 하여 본문을 그린다. 서버
  쪽 판정은 오직 문구 표시용이고 데이터 조회·저장 로직에는 관여하지 않는다).

■ admin_nav.py 등재 — 하지 않는다(지시서 명시, 기록자 몫).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/product-new", response_class=HTMLResponse)
def product_new_page(request: Request) -> HTMLResponse:
    """상품 등록·수정(ADM-PRD-011 가칭) — 등록/수정 겸용 단일 화면.

    데이터는 전부 `api/admin_products.py` 기존 API 를 화면(JS)이 직접 호출해 채운다
    (이 라우트는 셸만 그린다 — `admin_ui_stock_inbound.py`·`admin_ui_products.py` 와
    같은 패턴, 확인법: `grep -n \"def stock_inbound_page\" api/admin_ui_stock_inbound.py`).
    """
    code = (request.query_params.get("code") or "").strip()
    mode = "edit" if code else "register"
    crumb_now = "상품 수정" if code else "상품 등록"
    # mode/code 는 SSR 초기 <title>·H1 표시용 힌트일 뿐이다 — 실제 데이터 흐름(무엇을
    # 조회·저장할지)은 화면(JS)이 `location.search` 를 직접 읽어 독립적으로 판단한다
    # (다른 admin2 화면의 쿼리스트링 처리와 같은 방식 — 서버 렌더와 클라이언트 판단이
    # 어긋나도 클라이언트 쪽이 항상 진실이 되도록 이중 판정을 둔다).
    return render(request, "admin/product_new.html.j2",
                  screen_id="ADM-PRD-011", domain="product_new",
                  crumb_group="상품관리", crumb_now=crumb_now,
                  mode=mode, code=code)
