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
import re
from urllib.parse import parse_qsl, quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .admin_price_review import PENDING
from .admin_products import STATUS_OK
from .db import engine

router = APIRouter(tags=["admin-ui"])


# ---- ADM-H1-20261027: 상품 관리에서 «선택 상품 하나»를 들고 들어오고, 원래 목록으로 돌아간다 ----
# 계약 원문: outputs/office-admin-h1-20261027/claude/contract.json (A·D·E절).
# ⚠ admin 템플릿(.html.j2)은 Jinja 자동 이스케이프가 꺼져 있다 — jinja2.select_autoescape() 가
#   '.html.j2' 를 대상으로 보지 않는다(2026-10-27 실측). 그래서 URL 원문을 템플릿에 되돌려
#   주지 않는다: code 는 정수 또는 '형식 틀림' 플래그로만, 복귀 주소는 허용 키만 다시
#   인코딩한 문자열로만 넘긴다(인코딩 결과에는 따옴표·꺾쇠가 남지 않는다).
PRODUCTS_PATH = "/admin2/products"
_CODE_RE = re.compile(r"[1-9][0-9]{0,18}")
_INT_MAX = 2 ** 63 - 1                      # products.product_code BIGINT 범위


def parse_target_code(raw: str | None) -> tuple[int | None, bool]:
    """URL 의 code → (product_code 또는 None, 형식이 틀렸는가). 빈 값은 '대상 없음'(틀림 아님)."""
    s = (raw or "").strip()
    if not s:
        return None, False
    if _CODE_RE.fullmatch(s) and int(s) <= _INT_MAX:
        return int(s), False
    return None, True


def _pos_int(limit_digits: int):
    rx = re.compile(r"[1-9][0-9]{0,%d}" % (limit_digits - 1))
    return lambda v: v if rx.fullmatch(v) else None


def _one_of(*allowed):
    return lambda v: v if v in allowed else None


def _text_upto(n: int):
    return lambda v: v if 0 < len(v) <= n else None


def _sale_status(v: str):
    picked = []
    for part in v.split(","):
        part = part.strip()
        if part in STATUS_OK and part not in picked:
            picked.append(part)
    return ",".join(picked) or None


# 상품 관리 화면이 자기 URL 에 쓰는 상태 키(계약 D.products_url_state_keys) — 순서 그대로 다시 쓴다.
# (키, 디코딩된 값의 최대 글자 수, 검사) — 최대 글자 수는 검사가 받아 주는 가장 긴 값과 같다.
_RET_RULES = (
    ("q", 200, _text_upto(200)),
    ("tab", 6, _one_of("all", "ok", "review", "oos", "price")),
    ("part_type", 40, lambda v: v if re.fullmatch(r"[A-Za-z0-9_]{1,40}", v) else None),
    ("maker", 100, _text_upto(100)),
    ("visible", 3, _one_of("on", "off")),
    ("sale_status", len(",".join(STATUS_OK)), _sale_status),
    ("category_id", 10, _pos_int(10)),
    ("include_desc", 1, _one_of("0", "1")),
    ("page", 6, _pos_int(6)),
    ("size", 3, _one_of("50", "100", "200", "500")),
    ("sort", 6, _one_of("name", "cat", "spec", "stock", "price", "status")),
    ("dir", 4, _one_of("asc", "desc")),
    ("sel", 19, lambda v: v if parse_target_code(v)[0] is not None else None),
)
# 총 길이 상한은 «유효한 값의 최악의 인코딩»에서 계산한다(ADM-H1-SRV-001). 옛 상한 2,000자는
# 한글 q 200자 + maker 100자(각자 허용 범위 안)만으로 2,727자가 되어 page·sel 까지 통째로 버렸다.
# 한 글자는 퍼센트 인코딩으로 최대 12자(UTF-8 4바이트 × %XX)다. 그래서 키마다
# 「키 + '=' + '&' + 최대 글자 수 × 12」를 더한 값이면 유효한 상태는 항상 들어가고, 그보다 긴 입력은
# 처음부터 유효할 수 없으니 읽지 않고 버린다(입력 크기 방어 유지 — 지금 규칙으로 5,047자).
_PCT_MAX_PER_CHAR = 12
_RET_MAX_LEN = sum(len(key) + 2 + _PCT_MAX_PER_CHAR * n for key, n, _ in _RET_RULES)


def products_return_href(ret: str | None) -> str:
    """복귀 주소. 경로는 항상 /admin2/products 로 고정하고, ret(상품 관리의 query string)에서
    허용 키·허용 값만 골라 다시 인코딩한다 — 외부 주소·다른 경로로는 갈 수 없다."""
    if not ret or len(ret) > _RET_MAX_LEN:
        return PRODUCTS_PATH
    try:
        pairs = parse_qsl(ret, keep_blank_values=False, max_num_fields=60)
    except ValueError:                       # 필드 수 초과 — 통째로 버리고 기본 목록으로
        return PRODUCTS_PATH
    first = {}
    for k, v in pairs:
        first.setdefault(k, v.strip())       # 같은 키가 여러 번이면 첫 값만
    kept = []
    for key, _max_chars, check in _RET_RULES:
        v = first.get(key)
        if v is None:
            continue
        ok = check(v)
        if ok is not None:
            kept.append((key, ok))
    if not any(k == "category_id" for k, _ in kept):
        kept = [(k, v) for k, v in kept if k != "include_desc"]   # category_id 없이 뜻이 없다
    return PRODUCTS_PATH + ("?" + urlencode(kept, quote_via=quote) if kept else "")


@router.get("/admin2/price-review", response_class=HTMLResponse)
def price_review_page(request: Request, code: str | None = None, ret: str | None = None) -> HTMLResponse:
    """ADM-PRC-010 가격 검토 대기.

    승인 디자인은 두 상태를 가진 한 화면이다 — 1b(대상이 있을 때: KPI 4장 + 표 7열 +
    판정 서랍) 골격을 그대로 짓되, 1a(빈 큐 — 실측상 지금 실제로 뜨는 화면)를 표 헤더는
    남기고 본문 자리에 정성껏 그린다. 실데이터는 클라이언트가
    `GET /api/admin/price-review`(목록) +
    `GET /api/admin/price-review/empty-breakdown`(빈 이유 3종, 아래)을 불러 채운다.

    ADM-H1(2026-10-27): 상품 관리에서 들어오면 `?code=<product_code>&ret=<목록 query>`가 붙는다.
    code·ret 은 여기서 정제해 넘기고(pr_target_code · pr_target_invalid · pr_return_href),
    대상 판정은 화면이 `GET /api/admin/price-review/target/{code}` 로 매번 새로 받는다.
    둘 다 없으면 지금까지와 같은 화면이다.
    """
    target, invalid = parse_target_code(code)
    return render(request, "admin/price_review.html.j2",
                  screen_id="ADM-PRC-010", domain="price-review",
                  crumb_group="판매가", crumb_now="가격 검토 대기",
                  pr_target_code=target, pr_target_invalid=invalid,
                  pr_return_href=products_return_href(ret))


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
