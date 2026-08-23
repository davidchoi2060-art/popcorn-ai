"""ADM-PRD-020 검수 큐 — 읽기 + 첫 쓰기 이음새 (처리/되돌리기/일괄 확정).

승인 전이(ERD §8 T2): specs 값 반영 → (잔여 0건이면) verified → locked_fields 등록
→ review_required 재산정(필수 충족 ∧ 잔여 0) → true→false 전이 시에만 ai_candidate 승격.
"""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .timeutil import iso
from .admin_products import PART_TYPE_LABELS, required_fields
from .db import engine

router = APIRouter(prefix="/api/admin")

# 작업 기록 주체 = 세션 운영자(슬라이스 37). 세션 없는 경로는 시드 운영자(1)로 폴백.
from .auth import current_operator_id


# ERD §7.3 호환성 치명 필드 (목업 CRIT_CONFLICT와 다름 — ERD 우선 채택, 의도된 차이)
CRITICAL_FIELDS = {"length_mm", "gpu_max_mm", "rated_watt", "socket"}

# 검수 처리 가능한 specs 컬럼 화이트리스트 + SQL 캐스트 타입.
# 컬럼명은 이 딕셔너리를 통해서만 SQL에 삽입된다(ports JSONB는 제외 — 구조 편집은 별도 화면).
FIELD_CAST = {
    **{f: "INTEGER" for f in (
        "length_mm", "rated_watt", "refresh_hz", "capacity_gb", "clock_mhz",
        "tdp_watt", "required_power_watt", "gpu_max_mm", "cooler_height_mm", "cooler_tdp")},
    "size_inch": "NUMERIC(4,1)",
    **{f: "VARCHAR" for f in (
        "socket", "chipset", "mem_type", "form_factor", "interface", "pcie_gen",
        "resolution", "panel", "switch_type", "key_layout", "connection")},
    # 목록형 사양(JSONB). 승인 대상에서 빠져 있어 케이스 규격·쿨러 소켓을 확정할 수
    # 없었다 — 검수 제안의 41%가 이 두 필드다(슬라이스 51).
    **{f: "JSONB" for f in ("form_factor_list", "socket_list")},
}
# JSONB 필드는 값이 JSON 배열 문자열이어야 한다 — 화면·수집기가 보내는 표기를 맞춘다
JSON_FIELDS = {"form_factor_list", "socket_list"}

# 검수 처리 가능한 **products 컬럼** 화이트리스트(위 FIELD_CAST는 product_specs 컬럼 —
# 대상 테이블이 다르다). market_price 하나뿐이다(㉠ 시장가 제안 승인 — A-103·A-104,
# 2026-08-23 사장님 확정): 다나와 최저가는 이 검수 큐로 «제안»까지만 오고, 사람이 이
# 화면에서 승인해야만 products.market_price에 들어간다(A-18 "다나와는 제안까지만"을
# 가격에도 그대로 확장). 잠금 표기는 `specs.{field}` 접두어가 아니라 **맨 컬럼명**이다
# — `api/catalog_ingest.py`의 UPSERT가 `locked_fields ? 'market_price'`(접두어 없음,
# purchase_price·sale_price와 같은 표기)로 읽기 때문에, 여기서 접두어를 붙이면 잠가도
# 다음 CSV 적재가 그대로 되돌린다.
PRODUCT_FIELD_CAST = {"market_price": "BIGINT"}

# products 갈래 «가격» 필드의 범위 검증 — PRODUCT_FIELD_CAST 전체가 가격 컬럼이라는
# 전제로 여기 한 자리에 둔다(지금은 market_price 하나뿐이지만, purchase_price·
# sale_price류가 이 화이트리스트에 더해지면 같은 상한을 그대로 받는다). **가격이
# 아닌 컬럼을 PRODUCT_FIELD_CAST에 추가할 때는 이 상수를 그대로 쓸 수 있는지부터
# 다시 판단해야 한다** — product_specs 갈래(FIELD_CAST·위 _approve)는 이 상수와
# 무관하게 그대로 동작한다(대상 테이블도 화이트리스트도 다르다).
#
# 하한(확인자 결함 2026-08-23 재현: review 신규 생성 -> action=manual value='-5000'
# -> 기존 코드는 int('-5000') 캐스팅에 성공해 200을 내고 products.market_price=
# -5000 · locked_fields=['market_price']로 저장했다). 가격은 0이거나 음수일 수
# 없다 — products.market_price는 이미 «리터럴 0»으로 채워진 행이 다수이고 그 0은
# "값이 없다"는 뜻이다(decision-log.md A-103 "2026-08-23 보완": 시장가 실측
# 양수 467건 · 0 22,649건 · NULL 35건, 2026-08-23 재실측 동일). 0을 승인된 «값»
# 으로 받아 주면 그 구분이 무너진다.
PRODUCT_PRICE_MIN = 1

# 상한(실측, 2026-08-23): `SELECT max(sale_price) FROM products` -> 900,000,000.
# 수를 지어내지 않고 이 실측값을 그대로 상한으로 쓴다. 같은 실측에서
# max(market_price)=259,280,000으로 이 상한의 3분의 1이 안 된다 — 지금 이미
# 저장돼 있는 어떤 market_price 값도 이 상한에 걸리지 않는다(기존 데이터
# 무영향 확인, 재확인법: `SELECT count(*) FROM products WHERE market_price >
# 900000000` -> 0).
PRODUCT_PRICE_MAX = 900_000_000

# 시세(market_price) 자동 승인 임계값(A-108, 2026-08-23 사장님 확정 — A-103 개정).
# 사장님 원문: "승인: 변동폭이 작은 건(예: 5% 미만)은 자동 승인하고, 큰 것만 사람이
# 본다. A-103 을 그렇게 개정해라." A-103(다나와 시세는 제안 큐 경유 · 전량 사람 승인)은
# 폐기가 아니라 개정이다 — "제안 큐를 거친다"(다나와가 정본에 직접 쓰지 않는다, A-18
# 그대로)와 "큰 변동은 사람이 본다"는 그대로 남고, 바뀌는 것은 "얼마나 작아야 사람 없이
# 넘어가는가" 하나뿐이다.
#
# 근거(조사자 실측 — 27일 표본 120건 실제 재수집): 변동 없음 31.4% · 변동률 중앙값
# 0.62% · |변동률| > 5%는 20.3%뿐. 오늘 하루 3,520건을 사람이 초당 9~19건으로 훑었다 —
# 그 속도로는 작은 변동도 큰 변동도 똑같이 "훑기"만 할 뿐 판단이 실리지 않는다(비용만
# 있고 판단이 없다). 임계 미만을 자동으로 넘기고 사람의 눈을 나머지 20.3%(변동이 큰
# 축)에 모으는 편이 지금(전량 훑기)보다 오히려 더 안전하다 — A-18의 근거("남의 값이
# 그대로 견적 근거가 되면 정체성이 무너진다")를 버리는 게 아니라 지키는 길이다: 위험이
# 큰 변동은 여전히 전량 사람이 본다.
#
# 이 값을 바꾸면 무엇이 달라지는가: 낮추면(예 3.0) 자동 승인 범위가 좁아져 사람이 더
# 많이 보고, 높이면(예 10.0) 더 많은 변동이 사람 없이 넘어간다. 위 실측 분포에서 5.0은
# 상위 20.3%(변동이 큰 쪽)만 사람에게 남기는 지점이다. 0으로 두면 사실상 전량 사람
# 승인(개정 전 A-103)으로 되돌아간다.
MARKET_AUTO_APPROVE_PCT = 5.0  # 이 미만의 |변동률(%)|은 자동 승인


def market_auto_approve_decision(current, new_val: int) -> tuple[bool, float | None, str]:
    """market_price 자동 승인 판정 — **한 자리**(단일 원천, A-108). 같은 판정을 다른
    곳에 다시 적지 않는다 — 재사용자(예: tools/danawa_fetch.py)는 이 함수를 그대로
    import해서 쓴다.

    규칙(사장님 확정 2026-08-23):
      · 새 값이 API 범위(PRODUCT_PRICE_MIN~PRODUCT_PRICE_MAX) 밖이거나 0 이하
        -> 자동 승인하지 않는다. 기존 `_approve_product_field()` 가드(아래)를
        느슨하게 하는 것이 아니다 — 그 가드보다 **앞에서** 한 번 더 본다(이 판정이
        막아도, 사람이 화면에서 그대로 승인을 시도하면 그 가드가 다시 막는다 —
        기존 가드는 그대로 살아 있다).
      · 현재 값(`current` — products.market_price)이 없거나(NULL) 0 이하
        -> 사람이 본다. 비교 기준이 없다(첫 값은 사람이 확인한다).
      · |변동률| < MARKET_AUTO_APPROVE_PCT -> 자동 승인.
      · 그 이상 -> 대기(사람이 본다).

    인자: current(현재 products.market_price, int | None) · new_val(제안값, int).
    반환: (auto_approved, pct_change, reason). pct_change는 비교 기준이 없거나
    새 값이 범위 밖이면 None. reason은 사람이 읽는 문장이다 — 콘솔에 그대로
    출력될 수 있어 ASCII 기호만 쓴다(화살표·줄표 대신 "->"·"-", 서버 stdout이 cp949).
    """
    if new_val is None or new_val <= 0 or new_val < PRODUCT_PRICE_MIN or new_val > PRODUCT_PRICE_MAX:
        return False, None, (
            f"제안값이 허용 범위 밖입니다(허용 {PRODUCT_PRICE_MIN:,}~{PRODUCT_PRICE_MAX:,})."
            " 자동 승인하지 않습니다.")
    if current is None or current <= 0:
        return False, None, (
            "현재 시세 값이 없거나 0입니다. 비교 기준이 없어 사람이 확인합니다(첫 값 검수).")
    pct = (new_val - current) / current * 100.0
    if abs(pct) < MARKET_AUTO_APPROVE_PCT:
        return True, pct, (
            f"변동률 {pct:+.2f}% - 임계값 {MARKET_AUTO_APPROVE_PCT}% 미만이라 자동 승인합니다.")
    return False, pct, (
        f"변동률 {pct:+.2f}% - 임계값 {MARKET_AUTO_APPROVE_PCT}% 이상이라 사람이 확인합니다.")


def _risk(review_type: str, field: str | None) -> str:
    if review_type == "spec_conflict" and field in CRITICAL_FIELDS:
        return "치명"
    if review_type in ("spec_conflict", "spec_missing"):
        return "주의"
    return "경미"


def _crit(part_type: str, target_field: str | None, review_type: str, specs: dict | None):
    out = []
    for f in required_fields(part_type):
        if f == target_field:
            out.append({"field": f, "value": "불일치" if review_type == "spec_conflict" else "미확인", "ok": False})
        else:
            v = specs.get(f) if specs else None
            out.append({"field": f, "value": "미확인" if v is None else str(v), "ok": True if v is not None else None})
    return out


@router.get("/reviews")
def list_reviews(page: int = 1, size: int = 100, part_type: str = "", origin: str = "",
                 sellable: int = 0, suggested: int = 0, field: str = "",
                 keyword: str = "", status: str = "대기"):
    """검수 큐 — 실데이터 적재 후 대기 건수가 수천이 되므로 서버 페이지네이션이 필수다(슬라이스 39).

    admin2 상품 사양 검수(ADM-PRD-020) 신설에 맞춰 최소 추가한 필터 셋(2026-08-13):
      `suggested=-1` 제안이 **없는** 것만("B·값 없음" 묶음 — 기존 0=필터없음/1=있음과 구분).
      `keyword=`      상품명·product_code·사양 필드명을 함께 훑는 검색.
      `status=`       검수 상태를 바꿔 본다(기본 '대기' — 기존 호출과 동일해 하위호환).
                      집계(`queue`·`by_field`·`by_type`)는 상태와 무관하게 **항상 대기 큐**를
                      설명한다 — "지금 무엇을 할 수 있는지"는 지금 보는 상태와 별개다.

    단가표發 편입 대기(sourcing_hold)는 **파생 목록**이라 페이지네이션 밖이다 —
    항목 수가 공급처 최신 파일 규모(수백)로 제한되므로 1페이지에만 덧붙인다.

    `suggested=1`이면 **외부 제안이 붙은 것만** — 승인/기각 판단만 하면 되는 목록이다.
    제안이 몇십 건인데 큐가 수천 건이면 화면에서 찾을 방법이 없다(슬라이스 52).

    `sellable=1`이면 **판매중 ∧ 재고>0** 상품만 — 지금 매출에 영향을 주는 것부터 본다
    (슬라이스 49: 6,490건 중 1,720건. 나머지는 팔 수도 없는 상품이라 급하지 않다).

    `field=cooler_tdp`처럼 **한 사양만** 볼 수 있다(슬라이스 85). 화면은 종류별 집계를
    이미 보여주면서 그걸로 좁힐 방법이 없었다 — 큐가 5,000건인데 "쿨러 발열 한도 350건을
    오늘 끝내겠다"는 작업을 시작할 수가 없었다. 같은 사양을 연달아 보면 판단 기준이
    유지되고, 자료를 한 번 펼쳐 놓고 처리할 수 있다.
    """
    size = max(1, min(size, 500))
    page = max(1, page)
    keyword = keyword.strip()
    status = status.strip() or "대기"
    # 허용 범위 밖 값은 "필터 없음"으로 되돌린다 — SQL의 (:suggested=-1 OR :suggested=1 OR ...)
    # 어느 쪽도 안 맞으면 조건이 통째로 거짓이 돼 **전 행이 조용히 사라진다**(예전 코드의
    # `1 if suggested else 0` 관용을 유지 + -1 신설).
    suggested = 1 if suggested > 0 else (-1 if suggested < 0 else 0)
    q = text("""
        SELECT r.review_id, r.product_code, r.review_type, r.field_name, r.detail,
               r.origin_value, r.suggested_value, r.confidence, r.created_at,
               p.sku, p.product_name, p.part_type, to_jsonb(ps) AS specs,
               sw.confidence AS web_confidence, sw.note AS web_note,
               sw.source_url AS web_source_url, sw.source_name AS web_source_name
        FROM product_reviews r
        JOIN products p USING (product_code)          -- product_code NULL(csv_error류)은 자연 제외
        LEFT JOIN product_specs ps USING (product_code)
        -- 진짜 신뢰 신호는 spec_web_suggestions에만 있다 — product_reviews.confidence는
        -- 최초 등록 시점 값이라 웹 제안 38건이 전부 0.8로 뭉뚱그려 보였다(admin2 상품
        -- 사양 검수 요구사항 §신뢰도 취급, 2026-08-13). 재수집돼 값이 여럿이면 최신만.
        LEFT JOIN LATERAL (
            SELECT confidence, note, source_url, source_name
            FROM spec_web_suggestions sw0
            WHERE sw0.product_code = r.product_code AND sw0.field_name = r.field_name
            ORDER BY sw0.fetched_at DESC LIMIT 1
        ) sw ON true
        WHERE r.review_status = :status
          AND (:part_type = '' OR p.part_type = :part_type)
          AND (:origin = '' OR p.data_origin = :origin)
          AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
          AND (:suggested = 0 OR (:suggested = 1 AND r.suggested_value IS NOT NULL)
                              OR (:suggested = -1 AND r.suggested_value IS NULL))
          AND (:field = '' OR r.field_name = :field)
          AND (:keyword = '' OR p.product_name ILIKE '%%' || :keyword || '%%'
                             OR CAST(p.product_code AS TEXT) ILIKE '%%' || :keyword || '%%'
                             OR r.field_name ILIKE '%%' || :keyword || '%%')
        ORDER BY r.created_at, r.review_id
        LIMIT :size OFFSET :offset
    """)
    qc = text("""
        SELECT count(*) FROM product_reviews r JOIN products p USING (product_code)
         WHERE r.review_status = :status
           AND (:part_type = '' OR p.part_type = :part_type)
           AND (:origin = '' OR p.data_origin = :origin)
           AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
           AND (:suggested = 0 OR (:suggested = 1 AND r.suggested_value IS NOT NULL)
                               OR (:suggested = -1 AND r.suggested_value IS NULL))
           AND (:field = '' OR r.field_name = :field)
           AND (:keyword = '' OR p.product_name ILIKE '%%' || :keyword || '%%'
                              OR CAST(p.product_code AS TEXT) ILIKE '%%' || :keyword || '%%'
                              OR r.field_name ILIKE '%%' || :keyword || '%%')
    """)
    # 종류별 집계는 **지금 보고 있는 범위**를 따른다. 필터를 켰는데 전체 분포를 보여주면
    # 화면의 숫자와 배너의 숫자가 다른 말을 한다(슬라이스 49). part_type 필터만 제외한다 —
    # 자기 자신으로 거르면 한 종류만 남아 집계의 뜻이 없어진다.
    qg = text("""
        SELECT p.part_type, count(*) n FROM product_reviews r JOIN products p USING (product_code)
         WHERE r.review_status = '대기'
           AND (:origin = '' OR p.data_origin = :origin)
           AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
           AND (:suggested = 0 OR (:suggested = 1 AND r.suggested_value IS NOT NULL)
                               OR (:suggested = -1 AND r.suggested_value IS NULL))
           AND (:keyword = '' OR p.product_name ILIKE '%%' || :keyword || '%%'
                              OR CAST(p.product_code AS TEXT) ILIKE '%%' || :keyword || '%%'
                              OR r.field_name ILIKE '%%' || :keyword || '%%')
         GROUP BY 1 ORDER BY 2 DESC
    """)
    # 큐 구성 — "6,490건"만 보여주면 운영자는 언젠가 처리하면 줄어들 줄 안다.
    # 실제로는 대부분이 **원문에 값 자체가 없어** 일괄 확정이 불가능한 항목이다(슬라이스 49).
    # 무엇이 손댈 수 있는 일이고 무엇이 사람 손이 필요한 일인지 화면이 구분해 말해야 한다.
    # bulkable은 **일괄 확정 API가 실제로 처리하는 조건과 같아야 한다**
    # (bulk_confirm: review_type='low_confidence' ∧ origin_value IS NOT NULL).
    # '값이 있는 것' 전부를 세면 버튼이 처리하지 못하는 수를 약속하게 된다.
    qs = text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE r.origin_value IS NOT NULL
                                  AND r.review_type = 'low_confidence') AS bulkable,
               count(*) FILTER (WHERE r.origin_value IS NOT NULL
                                  AND r.review_type <> 'low_confidence') AS single,
               count(*) FILTER (WHERE r.origin_value IS NULL) AS manual,
               count(*) FILTER (WHERE p.status = '판매중' AND p.stock_qty > 0) AS sellable,
               -- 외부 제안이 붙어 승인/기각 판단만 하면 되는 것(슬라이스 52)
               count(*) FILTER (WHERE r.suggested_value IS NOT NULL) AS suggested,
               -- 사양이 아니라 분류·코드 정체성이 틀린 것 — 이 화면의 승인 경로로 못 닫는다
               -- (admin2 상품 사양 검수 요구사항 §⑤ 덩어리 C, 2026-08-13). 기각(보류)만 된다.
               count(*) FILTER (WHERE (r.review_type = 'spec_conflict' AND r.field_name = 'danawa_code')
                                   OR r.review_type = 'name_invalid') AS identity_conflict
        FROM product_reviews r JOIN products p USING (product_code)
        WHERE r.review_status = '대기'
    """)
    # 필드별 대기도 **지금 보고 있는 범위**를 따른다(qg와 같은 이유, 2026-08-13 추가) —
    # field 자기 자신만 제외한다. LIMIT은 12→24(실측 상위 15개 전부를 담기 위함).
    qf = text("""
        SELECT r.field_name, count(*) n,
               count(*) FILTER (WHERE p.status = '판매중' AND p.stock_qty > 0) sell
        FROM product_reviews r JOIN products p USING (product_code)
        WHERE r.review_status = '대기' AND r.field_name IS NOT NULL
          AND (:part_type = '' OR p.part_type = :part_type)
          AND (:origin = '' OR p.data_origin = :origin)
          AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
          AND (:suggested = 0 OR (:suggested = 1 AND r.suggested_value IS NOT NULL)
                              OR (:suggested = -1 AND r.suggested_value IS NULL))
          AND (:keyword = '' OR p.product_name ILIKE '%%' || :keyword || '%%'
                             OR CAST(p.product_code AS TEXT) ILIKE '%%' || :keyword || '%%'
                             OR r.field_name ILIKE '%%' || :keyword || '%%')
        GROUP BY 1 ORDER BY n DESC LIMIT 24
    """)
    # 상태별 건수 — admin2 「처리 상태」 필터 드롭다운의 실측 카운트(2026-08-13 추가).
    qsc = text("SELECT review_status, count(*) FROM product_reviews GROUP BY 1")
    p = {"part_type": part_type.strip(), "origin": origin.strip(),
         "field": field.strip(), "keyword": keyword, "status": status,
         "sellable": 1 if sellable else 0, "suggested": suggested,
         "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        rows = conn.execute(q, p).mappings().all()
        total = conn.execute(qc, p).scalar_one()
        by_type = [{"part_type": r[0], "label": PART_TYPE_LABELS.get(r[0], r[0]), "n": r[1]}
                   for r in conn.execute(qg, p).all()]
        s = conn.execute(qs).mappings().first()
        by_field = [{"field": r[0], "n": r[1], "sellable": r[2]}
                    for r in conn.execute(qf, p).all()]
        status_counts = dict(conn.execute(qsc).all())
    items = []
    for r in rows:
        detail_text = r["detail"] or ""
        # 제안값의 출처를 밝힌다 — 다나와에서 온 값을 'AI 지식'이라 부르면 거짓이다
        # (슬라이스 51). 스키마 무개정이라 detail의 표기에서 파생한다.
        # "웹 제안" 분기(2026-08-13, B안 부수 수정) — `tools/spec_fill_apply.py`가 남기는
        # 표기(`[웹 제안: ... · 출처 ... — 확인 후 승인하세요]`)가 없으면 웹 제안이
        # "다나와"가 아니라는 이유만으로 "ai"(AI 지식)로 오표시되고 있었다.
        is_danawa = "다나와 제안" in detail_text
        is_web = "웹 제안" in detail_text
        suggest_source = ("danawa" if is_danawa else
                          ("web" if is_web else
                          ("ai" if r["suggested_value"] is not None else None)))
        # 진짜 신뢰 신호(admin2 상품 사양 검수 §신뢰도 취급, 2026-08-13). 웹 제안은
        # spec_web_suggestions 실측값 — 다나와는 유사도가 product_reviews.confidence
        # 자리에 이미 있다(별도 표 없음). **없으면 만들지 않고 null로 둔다.**
        if r["web_source_url"] is not None:
            signal = {"confidence": float(r["web_confidence"]) if r["web_confidence"] is not None else None,
                      "note": r["web_note"], "source_name": r["web_source_name"],
                      "source_url": r["web_source_url"], "kind": "web"}
        elif is_danawa:
            signal = {"confidence": float(r["confidence"]) if r["confidence"] is not None else None,
                      "note": None, "source_name": "다나와 유사도", "source_url": None, "kind": "danawa"}
        else:
            signal = None
        items.append({
            "review_id": r["review_id"],
            "product_code": r["product_code"],
            "sku": r["sku"],
            "name": r["product_name"],
            "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
            "part_type": r["part_type"],
            "type": r["review_type"],
            "field": r["field_name"],
            "detail": r["detail"],
            "origin_value": r["origin_value"],
            "suggested_value": r["suggested_value"],
            "suggest_source": suggest_source,
            "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
            "created_at": iso(r["created_at"]),
            "risk": _risk(r["review_type"], r["field_name"]),
            "crit": _crit(r["part_type"], r["field_name"], r["review_type"], r["specs"]),
            "signal": signal,
        })
    if (page == 1 and not part_type and not sellable and not suggested and not field
            and not keyword and status == "대기"):
        items.extend(_sourcing_items())
    # 오늘 내가 처리한 건수 — **서버가 센다**(슬라이스 96).
    # 화면은 `let done = 0`이라는 JS 변수로 세고 있었다. 새로고침하면 0이 되므로
    # 하루 종일 검수하다 F5를 누르면 성과가 사라졌고, 무엇보다 라벨이 '오늘 처리'인데
    # 실제로는 '이 페이지를 연 뒤 처리'였다 — 화면이 사실과 다른 것을 말하고 있었다.
    #
    # **'오늘'은 서울 기준이다.** DB는 UTC로 돌고 `reviewed_at`은 naive UTC다.
    # `date_trunc('day', now())`를 그대로 쓰면 UTC 자정(= 09:00 KST)이 경계가 되어,
    # 오전 8시에 출근한 운영자는 어제 저녁 작업이 '오늘'로 잡히고 9시가 되기 전까지
    # 자기 오전 작업은 안 잡힌다. 사람에게 보여주는 '오늘'은 그 사람의 오늘이어야 한다.
    #   now() AT TIME ZONE 'Asia/Seoul'        -> 서울 벽시계
    #   date_trunc('day', ...)                 -> 서울 자정(naive)
    #   ... AT TIME ZONE 'Asia/Seoul'          -> 그 순간의 절대시각
    #   ... AT TIME ZONE 'UTC'                 -> naive UTC (reviewed_at과 같은 축)
    with engine.connect() as conn:
        me = current_operator_id()
        my_today = conn.execute(text(
            "SELECT count(*) FROM product_reviews"
            " WHERE reviewed_by = :me AND reviewed_at >="
            "   (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')"
            "      AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'"),
            {"me": me}).scalar_one() if me else 0

    return {"items": items, "page": page, "size": size, "total": total,
            "pages": (total + size - 1) // size, "by_type": by_type,
            # 지금 걸린 필터에서 남은 수. 화면의 큰 숫자가 이걸 써야 한다 —
            # 예전에는 현재 페이지 길이(최대 100)를 '남은 N건'으로 띄웠다.
            "remaining": total,
            "my_today": my_today,
            "field": field.strip(),        # 화면이 지금 무엇으로 좁혔는지 되돌려 말한다
            "keyword": keyword,
            "status": status,
            "status_counts": status_counts,  # {review_status: n} — 상태 필터 드롭다운 실측 카운트
            "queue": {
                "total": s["total"],
                "bulkable": s["bulkable"],      # 일괄 확정 버튼이 실제로 처리하는 수
                "single": s["single"],          # 값은 있지만 단건 검수 강제(치명·주의)
                "manual": s["manual"],          # 원문에 값이 없다 — 사람이 찾아 넣어야 한다
                "sellable": s["sellable"],      # 판매중 ∧ 재고>0 — 지금 매출에 영향
                "suggested": s["suggested"],    # 외부 제안 대기 — 승인/기각만 하면 된다
                "identity_conflict": s["identity_conflict"],  # 사양이 아니라 정체성 문제(덩어리 C)
                "by_field": by_field,
                "verdict": (
                    f"대기 {s['total']:,}건 중 일괄 확정으로 끝낼 수 있는 건 {s['bulkable']:,}건, "
                    f"값은 있지만 단건 검수가 필요한 건 {s['single']:,}건입니다. "
                    f"나머지 {s['manual']:,}건은 원문에 값이 없어 사람이 사양을 찾아 넣어야 합니다"
                    f" — 재파싱(respec)으로는 더 회수되지 않습니다. "
                    f"지금 매출에 영향을 주는 건 판매중·재고 있는 {s['sellable']:,}건입니다."
                ),
            },
            "note": ("검수 대기는 서버에서 나눠 보냅니다 — by_type·by_field·queue는 상태와"
                     " 무관하게 항상 대기 큐 전체 집계입니다(부품 종류·사양 필드는 자기 자신을"
                     " 제외한 다른 필터를 반영합니다). 단가표發 편입 대기는 파생 목록이라"
                     " 기본 조회(1페이지·필터 없음·대기)에만 붙습니다."
                     " sellable=1이면 판매중·재고>0만, suggested=1이면 외부 제안이 붙은 것만,"
                     " suggested=-1이면 제안이 없는 것만, keyword는 상품명·product_code·사양"
                     " 필드명을 함께 봅니다.")}


# ---- 슬라이스 16: 단가표 신규(sourcing_hold) — 저장 없는 파생 큐 ----
# 공급처별 최신 파일의 미매칭 행(map 무 ∧ danawa 불일치)을 편입 대기 항목으로 파생.
# 연결·등록이 supplier_product_map을 쓰면 파생 조건에서 자연 소멸(상태 테이블 불필요·멱등).
# 시트·칩셋은 스냅샷에 미저장(스키마 무개정) — 화면 '—' 정직 표시, 컬럼화·페이지네이션 이관.
SIM_THRESHOLD = 0.3  # admin_price_import._file_diff와 동일 규칙


def _sourcing_items():
    q = text("""
        SELECT r.row_id, r.model_name, r.danawa_code, r.cost_price, r.supply_state, r.memo,
               f.supplier_id, f.file_name, f.received_at, s.name AS sup_name,
               c.sku AS cand_sku, c.product_name AS cand_name, c.sim AS cand_sim
        FROM (SELECT DISTINCT ON (supplier_id) file_id, supplier_id, file_name, received_at
              FROM supplier_price_files ORDER BY supplier_id, received_at DESC) f
        JOIN suppliers s USING (supplier_id)
        JOIN supplier_price_rows r USING (file_id)
        LEFT JOIN supplier_product_map m
               ON m.supplier_id = f.supplier_id AND m.model_key = r.model_name
        LEFT JOIN LATERAL (
          -- similarity(a,b) > th 형태는 trgm GIN 인덱스를 타지 못한다
          -- (24,303행 × 단가표 308행 = 이 화면 1페이지가 247초 걸렸다 — 슬라이스 39 실측).
          -- trgm 유사도 연산자는 인덱스를 쓴다. 임계값은 위 set_limit()으로 명시한다.
          SELECT p.sku, p.product_name, similarity(r.model_name, p.product_name) AS sim
          FROM products p WHERE p.product_name % r.model_name
          ORDER BY sim DESC LIMIT 1
        ) c ON true
        WHERE m.map_id IS NULL
          AND (r.danawa_code IS NULL
               OR NOT EXISTS (SELECT 1 FROM products p2 WHERE p2.danawa_code = r.danawa_code))
        ORDER BY f.supplier_id, r.row_id
    """)
    with engine.connect() as conn:
        # 유사도 임계값을 세션에 고정 — `%` 연산자가 이 값을 쓴다(코드와 DB 판정을 일치시킨다).
        # SET 문은 파라미터를 받지 않으므로 pg_trgm의 set_limit() 함수를 쓴다.
        conn.execute(text("SELECT set_limit(:th)"), {"th": SIM_THRESHOLD})
        rows = conn.execute(q, {"th": SIM_THRESHOLD}).mappings().all()
    return [{
        "review_id": None, "sku": None, "type": "sourcing_hold",
        "src_row_id": r["row_id"], "supplier_id": r["supplier_id"],
        # cat: 이 행은 아직 카탈로그에 상품이 없는 원시 단가표 줄이라 부품 종류
        # 자체가 없다("값이 없다") — ETC(part_type이 정해져 "기타(ETC)"로 뜨는 것,
        # "값이 있다")와는 다른 사실이라 같은 글자를 쓰지 않는다. taxonomy.part_label(None)이
        # 이미 "값 없음"을 '—'로 표기하는 관례이고(part_type도 바로 아래 None),
        # reviews.html.j2도 이 필드를 `r.cat || '—'`로 그린다(r.src.sup과 같은 패턴) —
        # 그래서 falsy만 넘기면 화면쪽 수정 없이 '—'로 뜬다.
        "name": r["model_name"], "cat": None, "part_type": None,
        "field": None, "origin_value": None, "suggested_value": None, "confidence": None,
        "created_at": iso(r["received_at"]), "risk": "경미", "crit": [],
        "detail": ("단가표 신규 행 — 카탈로그에 같은 모델이 없습니다. 이름 유사 후보가 있어 연결 검토가 우선입니다."
                   if r["cand_sku"] else
                   "단가표 신규 행 — 유사 후보 없음. 취급하려면 신규 상품으로 등록하고 검수를 거칩니다."),
        "src": {"sup": r["sup_name"], "file": r["file_name"], "cost": r["cost_price"],
                "state": r["supply_state"], "memo": r["memo"],
                "danawa_code": r["danawa_code"]},
        "cand": ({"sku": r["cand_sku"], "name": r["cand_name"], "sim": float(r["cand_sim"])}
                 if r["cand_sku"] else None),
    } for r in rows]


class LinkBody(BaseModel):
    row_id: int
    sku: str
    via: str = "manual"  # candidate(유사 후보 채택 → similarity) | manual(SKU 직접 입력)


@router.post("/reviews/sourcing/link")
def sourcing_link(body: LinkBody):
    """편입 ①: 기존 상품에 연결 — map 등록만(psp·가격 무변경 — '다음 단가표부터 자동 매칭')."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT r.row_id, r.model_name, f.supplier_id FROM supplier_price_rows r"
            " JOIN supplier_price_files f USING (file_id) WHERE r.row_id=:i"),
            {"i": body.row_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "단가표 행이 없습니다")
        prod = conn.execute(text(
            "SELECT product_code, sku FROM products WHERE sku=:s"), {"s": body.sku.strip()}).mappings().first()
        if prod is None:
            raise HTTPException(404, f"상품이 없습니다: {body.sku}")
        method = "similarity" if body.via == "candidate" else "manual"
        map_id = conn.execute(text(
            "INSERT INTO supplier_product_map (supplier_id, model_key, product_code, match_method, confirmed_by, confirmed_at)"
            " VALUES (:s, :k, :pc, :m, :op, now())"
            " ON CONFLICT (supplier_id, model_key) DO NOTHING RETURNING map_id"),
            {"s": row["supplier_id"], "k": row["model_name"], "pc": prod["product_code"],
             "m": method, "op": current_operator_id()}).scalar()
        if map_id is None:
            raise HTTPException(409, "이미 연결된 모델입니다")
        log_id = _log(conn, "sourcing_link", row["model_name"][:100],
                      {"map_id": map_id, "row_id": row["row_id"], "supplier_id": row["supplier_id"],
                       "model_key": row["model_name"], "product_code": prod["product_code"],
                       "sku": prod["sku"], "method": method})
        return {"ok": True, "undo_id": log_id, "sku": prod["sku"]}


@router.post("/reviews/sourcing/unlink/{log_id}")
def sourcing_unlink(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "sourcing_link":
            raise HTTPException(404, "되돌릴 연결 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='sourcing_unlink' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 연결입니다")
        d = log["detail"]
        m = conn.execute(text(
            "SELECT product_code, match_method FROM supplier_product_map WHERE map_id=:m FOR UPDATE"),
            {"m": d["map_id"]}).first()
        if m is None or m[0] != d["product_code"] or m[1] != d["method"]:
            raise HTTPException(409, "연결 이후 매핑이 변경되어 되돌릴 수 없습니다")
        conn.execute(text("DELETE FROM supplier_product_map WHERE map_id=:m"), {"m": d["map_id"]})
        _log(conn, "sourcing_unlink", str(log_id), {"ref_log_id": log_id, "model_key": d["model_key"]})
        return {"ok": True}


class ProcessBody(BaseModel):
    action: str  # origin | suggested | manual | reject
    value: str | None = None
    # 같은 모델의 변형에 같은 값을 함께 넣는다(슬라이스 85). **화면이 고른 것만** —
    # 서버가 알아서 확장하지 않는다. 목록은 /reviews/{id}/siblings가 제안한다.
    also: list[int] = []


def _approve(conn, review, value, new_status: str) -> tuple[dict, int]:
    """승인 전이 공용 헬퍼(단건·일괄 공유). before 스냅샷과 pool_added를 반환."""
    field = review["field_name"]
    if field in PRODUCT_FIELD_CAST:
        # products 컬럼 갈래(market_price) — 아래 사양 갈래와 대상 테이블·게이트가
        # 다르므로 별도 함수로 완전히 가른다(§보고: FIELD_CAST 분기가 product_specs
        # 전용이라 market_price를 못 받는 실측 근거).
        return _approve_product_field(conn, review, value, new_status)
    if field not in FIELD_CAST:
        raise HTTPException(400, f"처리할 수 없는 필드: {field}")
    pc = review["product_code"]

    prod = conn.execute(text(
        "SELECT part_type, review_required_yn, ai_candidate_yn, locked_fields"
        " FROM products WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()
    spec = conn.execute(text(
        "SELECT to_jsonb(ps) AS specs FROM product_specs ps WHERE product_code=:pc FOR UPDATE"),
        {"pc": pc}).mappings().first()
    specs_before = spec["specs"] if spec else None

    before = {
        "spec_value": (specs_before or {}).get(field),
        "verified_yn": (specs_before or {}).get("verified_yn", False),
        "review_required_yn": prod["review_required_yn"],
        "ai_candidate_yn": prod["ai_candidate_yn"],
        "locked_fields": prod["locked_fields"],
        "review_status": review["review_status"],
    }

    try:
        conn.execute(text(f"""
            INSERT INTO product_specs (product_code, part_type, {field})
            VALUES (:pc, :pt, CAST(:v AS {FIELD_CAST[field]}))
            ON CONFLICT (product_code)
            DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = now()
        """), {"pc": pc, "pt": prod["part_type"], "v": value})
    except DBAPIError:
        raise HTTPException(400, f"값 형식 오류: {value!r} → {field}")

    remaining = conn.execute(text(
        "SELECT COUNT(*) FROM product_reviews WHERE product_code=:pc"
        " AND review_status IN ('대기','검수중') AND review_id<>:rid"),
        {"pc": pc, "rid": review["review_id"]}).scalar()
    if remaining == 0:
        conn.execute(text(
            "UPDATE product_specs SET verified_yn=true, updated_at=now() WHERE product_code=:pc"),
            {"pc": pc})

    specs_now = conn.execute(text(
        "SELECT to_jsonb(ps) AS s FROM product_specs ps WHERE product_code=:pc"),
        {"pc": pc}).scalar()
    required = required_fields(prod["part_type"])
    all_filled = all((specs_now or {}).get(f) is not None for f in required)
    new_review_required = not (all_filled and remaining == 0)

    pool_added = 0
    if prod["review_required_yn"] and not new_review_required:
        # 게이트 해제 전이 — 이 순간에만 ai_candidate 승격 (ERD §8 T2)
        conn.execute(text(
            "UPDATE products SET review_required_yn=false, ai_candidate_yn=true,"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})
        pool_added = 1
    else:
        conn.execute(text(
            "UPDATE products SET"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})

    conn.execute(text(
        "UPDATE product_reviews SET review_status=:st, reviewed_by=:op, reviewed_at=now()"
        " WHERE review_id=:rid"),
        {"st": new_status, "op": current_operator_id(), "rid": review["review_id"]})
    return before, pool_added


def _approve_product_field(conn, review, value, new_status: str, *, auto: bool = False) -> tuple[dict, int]:
    """승인 전이 — **products 컬럼** 갈래(market_price 전용, A-103·A-104 2026-08-23).

    위 `_approve()`와 나란한 함수이지 그 내부 분기가 아니다 — 대상 테이블도
    (`product_specs`가 아니라 `products`) 게이트도 다르다:
      · market_price는 `spec_field_defs`에 없다 — 추천 후보 게이트(필수 사양 충족
        판정)의 대상이 아니므로 `review_required_yn`·`ai_candidate_yn`을 건드리지
        않는다(그래서 pool_added는 항상 0).
      · 잠금 키는 `specs.{field}` 접두어가 아니라 **맨 컬럼명**이다 — 이래야
        `api/catalog_ingest.py`의 UPSERT(`locked_fields ? 'market_price'`, A-104)가
        같은 문자열로 이 잠금을 읽는다.
      · 값이 바뀌면 `product_price_history`에 한 행을 남긴다(reason='market_observe').
        field 값은 'market_price'가 아니라 **'market'**이다 — 이 표가 이미 쓰고 있는
        표기(`FIELD_KO = {"sale":..., "purchase":...}`, `api/admin_price_history.py`)와
        DB 컬럼 코멘트("field VARCHAR(20) -- purchase / sale / market")를 따른다.
        값이 같으면(승인값이 이미 반영된 값과 동일) 이력을 남기지 않는다 — 이 저장소의
        기존 규약(admin_price_import.py 등 "값이 같으면 원장에 안 남긴다")과 같다.

    auto=True(A-108, 2026-08-23 사장님 확정 — 변동폭이 작은 시세 제안 자동 승인):
        `reviewed_by`·`product_price_history.changed_by`에 operator_id 대신
        **NULL**을 남긴다 — 사람이 아니라 시스템이 승인했다는 사실 자체가 값이다
        (이 함수 밖 `auto_approve_market_price()`가 `new_status`로 '자동승인'을
        넘겨 같은 사실을 review_status 축에도 이중으로 남긴다 — 두 컬럼이 같은
        말을 한다). 승인 로직 자체(값 반영 · 잠금 · 이력 · 상태 전이)는 auto
        여부와 무관하게 완전히 같다 — 바뀌는 것은 "누가 했다고 적을 것인가" 그
        한 값뿐이다. 기본값 False는 기존 호출부(`_approve()`)와 완전히 같은
        동작을 유지한다(하위 호환 무변경 — operator_id는 지금까지처럼
        current_operator_id()가 들어간다).
    """
    field = review["field_name"]
    pc = review["product_code"]
    cast = PRODUCT_FIELD_CAST[field]
    op = None if auto else current_operator_id()

    prod = conn.execute(text(
        f"SELECT {field} AS v, locked_fields FROM products"
        " WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()

    before = {
        "product_value": prod["v"],
        "locked_fields": prod["locked_fields"],
        "review_status": review["review_status"],
    }

    # 빈 값은 조용히 NULL 확정으로 빠지지 않는다 — 값 형식 오류와 같은 값으로 취급해 400
    # (확인자 결함 2026-08-23: 제품 20481003, action=manual value="" 재현 —
    #  기존 코드는 여기서 new_val=None 을 만들어 market_price 를 조용히 지웠다).
    # 사양(product_specs) 갈래(위 _approve, CAST 실패 시 400)와 같은 동작으로 맞춘다.
    stripped = str(value).strip() if value is not None else ""
    if stripped == "":
        raise HTTPException(400, f"값 형식 오류: {value!r} → {field}")
    try:
        new_val = int(stripped)
    except (TypeError, ValueError):
        raise HTTPException(400, f"값 형식 오류: {value!r} → {field}")

    # 범위 검증(위 PRODUCT_PRICE_MIN·PRODUCT_PRICE_MAX 주석 참조) — 형식은 맞아도
    # 값이 말이 안 되는 경우(음수·0·자릿수 오타)를 여기서 400으로 막는다. 화면
    # 쪽 숫자 검사가 이 필드에서 빠져 있어도(별도 결함, 화면 담당 제작자 작업 중)
    # 서버가 스스로 막아야 한다 — ASCII 기호만 쓴다(서버 stdout이 cp949).
    if new_val < PRODUCT_PRICE_MIN or new_val > PRODUCT_PRICE_MAX:
        raise HTTPException(400,
            f"값 범위 오류: {new_val:,} -> {field}"
            f" (허용 범위 {PRODUCT_PRICE_MIN:,}~{PRODUCT_PRICE_MAX:,})")

    conn.execute(text(
        f"UPDATE products SET {field} = CAST(:v AS {cast}),"
        " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
        " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at = now()"
        " WHERE product_code = :pc"),
        {"v": new_val, "lf": field, "pc": pc})

    if before["product_value"] != new_val:
        conn.execute(text(
            "INSERT INTO product_price_history"
            " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, 'market', :o, :n, 'market_observe', :ref, :op)"),
            {"pc": pc, "o": before["product_value"], "n": new_val,
             "ref": review["review_id"], "op": op})

    conn.execute(text(
        "UPDATE product_reviews SET review_status=:st, reviewed_by=:op, reviewed_at=now()"
        " WHERE review_id=:rid"),
        {"st": new_status, "op": op, "rid": review["review_id"]})
    return before, 0


def _log(conn, action: str, target_id: str, detail: dict, *, auto: bool = False) -> int:
    """작업 기록. auto=True면 operator_id에 NULL을 남긴다 — 사람이 아니라 시스템이
    한 일이라는 뜻이다(자동 승인 전용, A-108). 기존 호출부는 전부 auto를 생략하므로
    지금까지와 완전히 같게 current_operator_id()가 들어간다(하위 호환 무변경)."""
    import json
    op = None if auto else current_operator_id()
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'product_review', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": op, "a": action, "t": target_id, "d": json.dumps(detail)}).scalar()


def _lock_waiting_review(conn, review_id: int):
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": review_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "검수 항목이 없습니다")
    if r["review_status"] != "대기":
        raise HTTPException(409, "이미 처리된 항목입니다")
    return r


def auto_approve_market_price(review_id: int) -> dict:
    """A-108(2026-08-23 사장님 확정 — A-103 개정) 재사용 가능한 승인 진입점.

    외부 시세 수집기(tools/danawa_fetch.py 등)가 field_name='market_price' 검수행을
    만든 뒤, review_id 하나씩 이 함수를 불러 변동폭이 작은 건을 사람 손 없이
    정리한다. 판정은 market_auto_approve_decision() 한 곳에서만 한다(위) — 여기서
    다시 %를 계산하지 않는다.

    **승인 로직은 새로 만들지 않는다.** 실제 반영(값 쓰기 · locked_fields 잠금 ·
    product_price_history 이력 · 검수행 상태 전이)은 사람이 화면에서 [확인]을 누를
    때와 완전히 같은 코드(`_approve_product_field()`)가 한다. 이 함수가 보태는 일은
    ① 자동 승인 대상인지 판정 ② `_approve_product_field(auto=True)` 호출 ③ 원장에
    "시스템이 왜 했는지"를 남기는 것, 셋뿐이다.

    **원장에서 자동/사람 승인을 구분하는 방법(기존 스키마 그대로 — 새 컬럼 없음)**:
      review_status   기존에도 승인 "방식"에 따라 갈렸다(원문 그대로 승인 = '승인',
                       직접 입력 = '수정' — process_review()의 기존 관례). 같은
                       축에 **'자동승인'**을 더한다. review_status만 봐도 사람이
                       버튼을 눌렀는지(승인/수정) 시스템이 넘겼는지(자동승인) 답이
                       나온다.
      reviewed_by      사람 승인은 항상 operator_id가 들어간다. 자동 승인은
                       **NULL**로 남긴다 — undo()가 '대기'로 되돌릴 때 이미 NULL을
                       쓰고 있어(아래 `_revert_one()` 참조), 이 컬럼이 "사람 아님"을
                       표현하는 값으로 NULL을 쓰는 것은 이 파일의 기존 관례다.
                       '대기'(미처리)와는 review_status가 다르므로 헷갈리지 않는다
                       (대기+NULL = 미처리, 자동승인+NULL = 시스템 처리).
      product_price_history.changed_by  같은 이유로 NULL(위 `_approve_product_field`의
                       auto 파라미터가 이 컬럼도 함께 처리한다).
      activity log     `admin_operator_activity_logs.action='review_auto_approve'`
                       (사람 처리는 'review_process') · `operator_id`=NULL ·
                       `detail`에 `pct_change`·`threshold_pct`·`before`(반영 전
                       값·잠금 스냅샷)를 남긴다 — "누가"뿐 아니라 "왜"까지 이
                       로그 하나로 답할 수 있다.

    되돌리기: `POST /reviews/undo/{log_id}`가 이 함수의 반환값 `undo_id`를 그대로
    받는다 — `undo()`의 허용 action 목록에 'review_auto_approve'를 추가했다(아래
    `undo()` 참조). `detail`의 `mode`는 (action 이름과는 별개로) 'approve'로
    남긴다 — `_revert_one()`이 `entry["mode"]`만 보고 반영 전 값으로 되돌리는
    기존 코드를 그대로 타게 하기 위해서다(되돌리기 로직도 새로 만들지 않는다).
    되돌리면 값 · 잠금 · 이력이 전부 역행하고 검수행은 다시 '대기'가 된다 — 사람
    승인을 되돌릴 때와 똑같다.

    반환(dict):
      review_id       int
      auto_approved   bool  — 자동 승인했는가
      left_to_human   bool  — 대기 상태 그대로 사람 몫으로 남겼는가. 이미 처리돼
                              있던 항목이면 "남긴" 것이 아니라 "이미 끝나 있었다"는
                              뜻이라 False다(auto_approved·left_to_human이 둘 다
                              False인 경우가 있다는 뜻).
      reason          str   — 판정 근거(사람이 읽는 문장, ASCII 기호만)
      pct_change      float | None  — 변동률(%). 비교 기준이 없거나 파싱 실패면 None
      old_value       int | None    — 비교 기준이 된 현재 products.market_price
      new_value       int | None    — 제안값(파싱 성공 시)
      undo_id         int | None    — 자동 승인했을 때만 log_id, 아니면 None

    field_name이 'market_price'가 아니거나 review_id 자체가 없으면 HTTPException을
    올린다(호출측 계약 위반 — 정상적인 "사람에게 남긴다" 결과가 아니다). 이미 처리된
    항목(대기 상태가 아님)은 예외를 올리지 않고 조용히(auto_approved=False,
    left_to_human=False) 돌려준다 — 같은 제안을 두 번 넘겨도 호출자가 매번 예외
    처리를 하지 않아도 되게 하기 위해서다.
    """
    with engine.begin() as conn:
        try:
            review = _lock_waiting_review(conn, review_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise
            # 409 = 이미 대기 상태가 아니다 — 이미 끝난 일이니 자동 승인 대상도
            # 새로 사람에게 남기는 것도 아니다.
            return {"review_id": review_id, "auto_approved": False, "left_to_human": False,
                    "reason": "이미 처리된 항목입니다(대기 상태가 아닙니다).",
                    "pct_change": None, "old_value": None, "new_value": None, "undo_id": None}

        if review["field_name"] != "market_price":
            raise HTTPException(400,
                f"market_price 전용 진입점입니다(field_name={review['field_name']!r}).")

        if review["suggested_value"] is None:
            return {"review_id": review_id, "auto_approved": False, "left_to_human": True,
                    "reason": "제안값이 없습니다.", "pct_change": None,
                    "old_value": None, "new_value": None, "undo_id": None}
        try:
            new_val = int(str(review["suggested_value"]).strip())
        except (TypeError, ValueError):
            return {"review_id": review_id, "auto_approved": False, "left_to_human": True,
                    "reason": f"제안값 형식 오류입니다: {review['suggested_value']!r}",
                    "pct_change": None, "old_value": None, "new_value": None, "undo_id": None}

        current = conn.execute(text(
            "SELECT market_price FROM products WHERE product_code=:pc"),
            {"pc": review["product_code"]}).scalar()

        ok, pct, reason = market_auto_approve_decision(current, new_val)
        if not ok:
            return {"review_id": review_id, "auto_approved": False, "left_to_human": True,
                    "reason": reason, "pct_change": pct, "old_value": current,
                    "new_value": new_val, "undo_id": None}

        before, _pool_added = _approve_product_field(
            conn, review, str(new_val), "자동승인", auto=True)
        log_id = _log(conn, "review_auto_approve", str(review_id),
                      {"mode": "approve", "auto": True, "review_id": review_id,
                       "field": "market_price", "value": str(new_val),
                       "pct_change": round(pct, 4) if pct is not None else None,
                       "threshold_pct": MARKET_AUTO_APPROVE_PCT, "before": before},
                      auto=True)
        return {"review_id": review_id, "auto_approved": True, "left_to_human": False,
                "reason": reason, "pct_change": pct, "old_value": current,
                "new_value": new_val, "undo_id": log_id}


# 같은 모델의 색상·패키지 변형 — 사양이 같은데 검수만 따로 해야 했다.
# 실측: cooler_tdp 대기 307건이 서로 다른 모델로는 232개뿐이다(75건이 변형).
# **자동으로 채우지 않는다.** 후보를 찾아 보여주고, 사람이 골라서 함께 적용한다 —
# 이름이 닮았다는 것만으로 사양이 같다고 단정하면 지어낸 값과 다를 게 없다.
_VARIANT = re.compile(r"\(([^)]*)\)")
_COLOR = re.compile(r"(블랙|화이트|블루|레드|핑크|그레이|실버|골드|투명|"
                    r"BLACK|WHITE|BLUE|RED|PINK|GRAY|GREY|SILVER|GOLD)", re.I)


def _model_key(name: str) -> str:
    """색상·괄호 표기를 지운 모델 이름. 보수적으로 — 괄호 밖 단어는 건드리지 않는다
    (`AS500`과 `AS500 PLUS`는 다른 제품이므로 묶이면 안 된다)."""
    s = _VARIANT.sub(" ", name or "")
    s = _COLOR.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


@router.get("/reviews/{review_id}/siblings")
def review_siblings(review_id: int):
    """이 검수 건과 **같은 모델로 보이는** 대기 건들 — 함께 처리할 후보.

    조건을 좁게 둔다: 같은 제조사 · 같은 부품 종류 · 같은 사양 필드 · 대기 상태 ·
    색상 표기를 지운 이름이 같을 것. 하나라도 어긋나면 후보에서 뺀다.
    """
    with engine.connect() as conn:
        me = conn.execute(text(
            "SELECT r.review_id, r.product_code, r.field_name, p.product_name, p.maker,"
            " p.part_type FROM product_reviews r JOIN products p USING (product_code)"
            " WHERE r.review_id=:rid"), {"rid": review_id}).mappings().first()
        if me is None:
            raise HTTPException(404, "검수 항목이 없습니다")
        rows = conn.execute(text(
            "SELECT r.review_id, r.product_code, p.product_name, p.status, p.stock_qty"
            " FROM product_reviews r JOIN products p USING (product_code)"
            " WHERE r.review_status='대기' AND r.field_name=:f AND p.part_type=:pt"
            "   AND coalesce(p.maker,'')=coalesce(:mk,'') AND r.review_id <> :rid"
            " ORDER BY p.product_name"),
            {"f": me["field_name"], "pt": me["part_type"], "mk": me["maker"],
             "rid": review_id}).mappings().all()
    key = _model_key(me["product_name"])
    sibs = [{"review_id": r["review_id"], "product_code": r["product_code"],
             "name": r["product_name"],
             "sellable": bool(r["status"] == "판매중" and (r["stock_qty"] or 0) > 0)}
            for r in rows if _model_key(r["product_name"]) == key]
    return {"review_id": review_id, "field": me["field_name"],
            "name": me["product_name"], "model_key": key, "siblings": sibs,
            "note": ("같은 제조사·같은 부품 종류에서 색상 표기만 다른 대기 건입니다."
                     " 사양이 같은지는 **사람이 확인**해야 합니다 —"
                     " 이름이 닮았다는 것만으로 값을 옮기지 않습니다."
                     if sibs else "함께 처리할 만한 같은 모델 대기 건이 없습니다.")}


@router.post("/reviews/{review_id}/process")
def process_review(review_id: int, body: ProcessBody):
    if body.action not in ("origin", "suggested", "manual", "reject"):
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    with engine.begin() as conn:
        review = _lock_waiting_review(conn, review_id)

        if body.action == "reject":
            conn.execute(text(
                "UPDATE product_reviews SET review_status='보류', reviewed_by=:op, reviewed_at=now()"
                " WHERE review_id=:rid"), {"op": current_operator_id(), "rid": review_id})
            log_id = _log(conn, "review_process", str(review_id),
                          {"mode": "reject", "review_id": review_id,
                           "before": {"review_status": "대기"}})
            return {"ok": True, "undo_id": log_id, "pool_added": 0}

        value = {"origin": review["origin_value"], "suggested": review["suggested_value"],
                 "manual": body.value}[body.action]
        if value is None:
            raise HTTPException(400, "확정할 값이 없습니다")
        new_status = "수정" if body.action == "manual" else "승인"
        before, pool_added = _approve(conn, review, value, new_status)
        detail = {"mode": "approve", "review_id": review_id,
                  "field": review["field_name"], "value": str(value), "before": before}

        # 함께 적용 — 화면이 지정한 대기 건에만 같은 값을 넣는다.
        # 같은 사양 필드가 아니면 거부한다: 다른 필드에 같은 숫자를 넣는 건 사고다.
        extra = []
        for rid in dict.fromkeys(body.also or []):
            if rid == review_id:
                continue
            sib = _lock_waiting_review(conn, rid)
            if sib["field_name"] != review["field_name"]:
                raise HTTPException(400, "다른 사양 항목은 함께 처리할 수 없습니다")
            sb, sadd = _approve(conn, sib, value, new_status)
            pool_added += sadd
            extra.append({"review_id": rid, "product_code": sib["product_code"],
                          "before": sb})
        if extra:
            # 한 로그에 함께 담는다 — 되돌리면 전부 함께 되돌아간다(부분 원복 금지).
            detail["also"] = extra
        log_id = _log(conn, "review_process", str(review_id), detail)
        return {"ok": True, "undo_id": log_id, "pool_added": pool_added,
                "applied": 1 + len(extra),
                "note": (f"{1 + len(extra)}건에 같은 값을 넣었습니다 — 되돌리면 함께 돌아갑니다."
                         if extra else None)}


@router.post("/reviews/bulk-confirm")
def bulk_confirm():
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT * FROM product_reviews WHERE review_type='low_confidence'"
            " AND review_status='대기' ORDER BY review_id FOR UPDATE")).mappings().all()
        entries, skipped, pool_total = [], 0, 0
        for r in rows:
            if r["origin_value"] is None:
                skipped += 1
                continue
            before, pool_added = _approve(conn, r, r["origin_value"], "승인")
            pool_total += pool_added
            entries.append({"mode": "approve", "review_id": r["review_id"],
                            "field": r["field_name"], "value": r["origin_value"], "before": before})
        if not entries:
            raise HTTPException(400, "일괄 확정 대상이 없습니다")
        log_id = _log(conn, "review_bulk_confirm", f"{len(entries)}건", {"items": entries})
        return {"count": len(entries), "skipped": skipped, "undo_id": log_id, "pool_added": pool_total}


def _revert_one(conn, entry: dict):
    rid = entry["review_id"]
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": rid}).mappings().first()
    if r is None:
        raise HTTPException(404, f"검수 항목이 없습니다: {rid}")
    if r["review_status"] == "대기":
        raise HTTPException(409, "이미 대기 상태입니다")  # 이중 undo·경합 방어의 전부
    before = entry["before"]
    if entry["mode"] == "approve":
        field, pc = entry["field"], r["product_code"]
        import json
        if field in PRODUCT_FIELD_CAST:
            # products 컬럼 갈래(market_price) — 값·잠금·이력을 전부 역행한다
            # (원장 규약: 되돌림은 삭제가 아니라 역방향 전이다). _approve_product_field와
            # 짝을 이루는 되돌리기이지 위 사양 갈래의 분기가 아니다.
            cast = PRODUCT_FIELD_CAST[field]
            cur = conn.execute(text(
                f"SELECT {field} AS v FROM products WHERE product_code=:pc FOR UPDATE"),
                {"pc": pc}).scalar()
            conn.execute(text(
                f"UPDATE products SET {field} = CAST(:v AS {cast}),"
                " locked_fields = CAST(:lf AS JSONB), updated_at = now()"
                " WHERE product_code = :pc"),
                {"v": before["product_value"],
                 "lf": json.dumps(before["locked_fields"]), "pc": pc})
            if cur != before["product_value"]:
                # 역방향 이력 행 — 원래 행을 지우지 않고 반대 방향으로 새 행을 남긴다
                # (margin_policy/margin_policy_undo와 같은 원장 패턴).
                conn.execute(text(
                    "INSERT INTO product_price_history"
                    " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                    " VALUES (:pc, 'market', :o, :n, 'market_observe_undo', :ref, :op)"),
                    {"pc": pc, "o": cur, "n": before["product_value"],
                     "ref": rid, "op": current_operator_id()})
        else:
            conn.execute(text(f"""
                UPDATE product_specs SET {field} = CAST(:v AS {FIELD_CAST[field]}),
                       verified_yn = :vy, updated_at = now() WHERE product_code = :pc
            """), {"v": before["spec_value"], "vy": before["verified_yn"], "pc": pc})
            conn.execute(text(
                "UPDATE products SET review_required_yn=:rr, ai_candidate_yn=:ac,"
                " locked_fields=CAST(:lf AS JSONB), updated_at=now() WHERE product_code=:pc"),
                {"rr": before["review_required_yn"], "ac": before["ai_candidate_yn"],
                 "lf": json.dumps(before["locked_fields"]), "pc": pc})
    conn.execute(text(
        "UPDATE product_reviews SET review_status='대기', reviewed_by=NULL, reviewed_at=NULL"
        " WHERE review_id=:rid"), {"rid": rid})


@router.post("/reviews/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:id"),
            {"id": log_id}).mappings().first()
        if log is None or log["action"] not in (
                "review_process", "review_bulk_confirm", "review_auto_approve"):
            raise HTTPException(404, "되돌릴 작업 기록이 없습니다")
        detail = log["detail"]
        if log["action"] == "review_bulk_confirm":
            entries = detail["items"]
        else:
            # 함께 적용분(also)도 같은 로그에 담겨 있다 — **부분 원복은 없다**.
            # 하나만 되돌리면 같은 모델의 형제끼리 값이 갈려 어느 쪽이 맞는지 알 수 없다.
            # review_auto_approve 로그도 여기로 온다 — also가 없어(자동 승인은 항상
            # 단건) 아래 리스트 컴프리헨션이 빈 목록을 더해 entries=[detail] 하나가
            # 된다. detail의 모양(mode·field·review_id·before)은 review_process와
            # 같다(auto_approve_market_price() 참조) — _revert_one()을 그대로 탄다.
            entries = [detail] + [
                {"mode": detail.get("mode"), "field": detail.get("field"),
                 "review_id": a["review_id"], "before": a["before"]}
                for a in (detail.get("also") or [])]
        for e in entries:
            _revert_one(conn, e)
        _log(conn, "review_undo", str(log_id), {"ref_log_id": log_id, "count": len(entries)})
        return {"ok": True, "restored": len(entries)}
