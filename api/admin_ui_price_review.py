"""가격 검토 대기(ADM-PRC-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

계약: `docs/design/spec-price-review.md`(승인 디자인 1a·1b 요약). 데이터는 이미 있는
API를 그대로 쓴다(`api/admin_price_review.py` — `GET/POST /api/admin/price-review*`,
목록·승인·직접입력·유지 전부 실데이터로 이미 동작한다). 이 파일은 `admin_ui_reviews.py`·
`admin_ui_spec_fill.py`와 같은 패턴으로 **페이지 껍데기만** 서버 렌더하고, 실제 목록·
판정 흐름은 템플릿(`templates/admin/price_review.html.j2`)의 클라이언트 스크립트가
그 API를 불러 채운다.

■ 이 파일이 하나 더 얹는 이유(왜 `admin_price_review.py`를 고치지 않았는가)
큐가 비어 있을 때(1a — 2026-08-15 실측 기준 실제로 뜨는 화면) "왜 비어 있는가"를
사람 말로 풀려면 세 갈래 건수(판매가 미정 전체 · 그중 검수 대기 · 그중 잠금)가 필요한데,
기존 `GET /api/admin/price-review`는 큐(대상 0건)만 돌려주고 그 갈래는 세지 않는다.
이 작업의 담당 파일이 이 둘(`admin_ui_price_review.py` · `price_review.html.j2`)로
한정돼 있어 `admin_price_review.py`는 건드리지 않고, 대신 **큐를 정의하는 조건
(`PENDING`)을 그대로 가져다 쓴다** — 조건을 두 곳에 다시 적으면 언젠가 갈라진다
(`.claude/CANON.md` §1 「같은 것을 두 벌 두지 않는다」).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .admin_price_review import PENDING
from .db import engine

router = APIRouter(tags=["admin-ui"])


@router.get("/admin2/price-review", response_class=HTMLResponse)
def price_review_page(request: Request) -> HTMLResponse:
    """ADM-PRC-010 가격 검토 대기.

    승인 디자인은 두 상태를 가진 한 화면이다 — 1b(대상이 있을 때: KPI 4장 + 표 7열 +
    판정 서랍) 골격을 그대로 짓되, 1a(빈 큐 — 실측상 지금 실제로 뜨는 화면)를 표 헤더는
    남기고 본문 자리에 정성껏 그린다. 실데이터는 클라이언트가
    `GET /api/admin/price-review`(목록) +
    `GET /api/admin/price-review/empty-breakdown`(빈 이유 3종, 아래)을 불러 채운다.
    """
    return render(request, "admin/price_review.html.j2",
                  screen_id="ADM-PRC-010", domain="price-review",
                  crumb_group="판매가", crumb_now="가격 검토 대기")


@router.get("/api/admin/price-review/empty-breakdown")
def price_review_empty_breakdown():
    """빈 큐(1a) "왜 비어 있는가" 박스가 쓰는 건수 — sale_price가 없는 상품을
    세 갈래(+ 큐 자체)로 가른다. 조건은 `admin_price_review.PENDING`을 그대로
    재사용해 큐 정의가 두 곳에서 갈라지지 않게 한다(단일 원천).

    review_pending + locked_out + queue == null_total이 항상 성립한다(배타적·전수
    분기 — 세 조건이 sale_price IS NULL을 정확히 셋으로 나눈다). 2026-08-15 실측:
    5 / 5 / 0 / 0(전부 검수 대기라 큐가 비었다).

    `category_margin_policy_count`는 1b KPI 카드("적용 마진")의 부연에 쓴다 —
    지금은 0건이라 이 화면의 마진은 분류별 정책이 아니라 전역값(`pricing_settings`)
    하나다.
    """
    with engine.connect() as conn:
        row = conn.execute(text(f"""
            SELECT
              COUNT(*) FILTER (WHERE p.sale_price IS NULL) AS null_total,
              COUNT(*) FILTER (WHERE p.sale_price IS NULL
                                 AND p.review_required_yn = true)  AS review_pending,
              COUNT(*) FILTER (WHERE p.sale_price IS NULL
                                 AND p.review_required_yn = false
                                 AND (p.locked_fields @> '["sale_price"]'::jsonb)) AS locked_out,
              COUNT(*) FILTER (WHERE {PENDING}) AS queue
            FROM products p
        """)).mappings().one()
        policy_count = conn.execute(text(
            "SELECT count(*) FROM category_margin_policies")).scalar()
    return {
        "null_total": row["null_total"], "review_pending": row["review_pending"],
        "locked_out": row["locked_out"], "queue": row["queue"],
        "category_margin_policy_count": policy_count,
    }
