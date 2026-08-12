"""ADM-ENG-030 추천 가능 재고 현황 — 4중 게이트별 제외 사유 집계 (읽기 전용).

게이트 정본(슬라이스 23·24에서 확정, ERD §3.6 뷰 정의 기준):
  ① 사양 행 존재(product_specs — 뷰가 조인) ② 검수 통과(review_required=false ∧ ai_candidate)
  ③ 판매가 산정(sale_price) ④ 재고>0 ∧ status='판매중'
버킷은 **배타**(우선순위 순 1개 소속) — admin_products.derive_status와 같은 사고이나 사양 행·
승격 여부를 별도 사유로 분리해 "왜 추천에 못 쓰이는지"를 사유별로 셀 수 있게 한다.
S1 후보 카운터(v_recommendation_candidates ∧ stock>0)와 'ok' 합계가 일치해야 정합.
얇은 카테고리: 후보 수 임계 이하 + 제약 결합 실측 2종(화이트 케이스·750W 이상 파워 —
목업의 두 경고 항목을 실데이터로 계산). 규칙·정책 버전 표기는 미모델링이라 정직 표기.
이관: 규칙/정책 버전 관리, 카테고리별 목표 재고, 주변기기(peripheral) 풀 집계.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .admin_products import PART_TYPE_LABELS
from .db import engine
from .taxonomy import CORE_TYPES   # 단일 원천(슬라이스 A)

router = APIRouter(prefix="/api/admin")

THIN_THRESHOLD = 3   # 후보 N개 이하 = 견적 실패 위험(현 dev 재고 규모 기준 — 운영 시 재조정)
REASONS = [("no_specs", "사양 미등록(행 없음)", "products.html"),
           ("need_review", "검수 대기", "review-queue.html"),
           ("not_candidate", "후보 미승격", "review-queue.html"),
           ("no_price", "가격 검토 대기", "price-review.html"),
           ("oos", "재고 없음 · 매입", "stock-inbound.html")]

# **시연용(`data_origin='demo'`)은 모집단에서 뺀다 — 버킷이 아니다.**
#   0043 이 추천 뷰에서 demo 를 막았는데(몰에 없는 가짜 상품이 견적에 들어가고 있었다),
#   이 쿼리는 뷰를 쓰지 않고 `products` 를 직접 읽어 게이트를 파이썬으로 다시 구현한다.
#   그래서 뷰만 고치자 `ok_total`(여기) 과 `pool_total`(뷰) 이 3,219 대 3,242 로 갈라졌다.
#   demo 를 사유 버킷으로 만들지 않는 이유: 사유는 «왜 추천에 못 쓰이는지»를 운영자에게
#   보여 고치게 하는 목록인데, demo 는 **고칠 것이 아니라 우리 상품이 아니다.**
_Q = """
    SELECT p.product_code, p.sku, p.product_name, p.part_type, p.status, p.stock_qty,
           p.sale_price, p.review_required_yn, p.ai_candidate_yn,
           s.product_code IS NOT NULL AS has_specs,
           s.tag_white, s.rated_watt
    FROM products p LEFT JOIN product_specs s USING (product_code)
    WHERE p.category_group = 'core_part' AND p.part_type = ANY(:types)
      AND p.data_origin IS DISTINCT FROM 'demo'
"""


def _bucket(r) -> str:
    """배타 버킷 — 게이트 순서대로 첫 미충족 사유가 그 상품의 사유."""
    if not r["has_specs"]:
        return "no_specs"
    if r["review_required_yn"]:
        return "need_review"
    if not r["ai_candidate_yn"]:
        return "not_candidate"
    if r["sale_price"] is None:
        return "no_price"
    if r["stock_qty"] == 0 or r["status"] != "판매중":
        return "oos"
    return "ok"


@router.get("/candidate-pool")
def candidate_pool():
    with engine.connect() as conn:
        rows = conn.execute(text(_Q), {"types": list(CORE_TYPES)}).mappings().all()
        pool_total = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates WHERE stock_qty>0")).scalar_one()
        white_cases = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates"
            " WHERE stock_qty>0 AND part_type='CASE' AND tag_white")).scalar_one()
        big_psu = conn.execute(text(
            "SELECT COUNT(*) FROM v_recommendation_candidates"
            " WHERE stock_qty>0 AND part_type='POWER' AND rated_watt>=750")).scalar_one()

    cats, reasons = {}, {k: 0 for k, _l, _h in REASONS}
    for r in rows:
        label = PART_TYPE_LABELS.get(r["part_type"], r["part_type"])
        c = cats.setdefault(label, {"name": label, "total": 0, "ok": 0,
                                    **{k: 0 for k, _l, _h in REASONS}})
        b = _bucket(r)
        c["total"] += 1
        c[b] += 1
        if b != "ok":
            reasons[b] += 1
    cat_list = sorted(cats.values(), key=lambda c: -c["total"])
    ok_total = sum(c["ok"] for c in cat_list)

    thin = [{"name": c["name"], "count": c["ok"],
             "why": "후보가 적어 제약이 겹치면 견적이 실패할 수 있습니다",
             "link": "stock-inbound.html"}
            for c in cat_list if c["ok"] <= THIN_THRESHOLD]
    thin += [{"name": "케이스(화이트 태그)", "count": white_cases,
              "why": "\"화이트 감성\" 제약 결합 시 견적 실패 위험", "link": "stock-inbound.html"},
             {"name": "750W 이상 파워", "count": big_psu,
              "why": "고성능 GPU 견적의 전력 병목", "link": "stock-inbound.html"}]

    return {
        "pool_total": pool_total, "core_total": len(rows), "ok_total": ok_total,
        "rate": round(ok_total / len(rows) * 100, 1) if rows else 0.0,
        "categories": cat_list,
        "reasons": [{"key": k, "label": l, "link": h, "count": reasons[k]}
                    for k, l, h in REASONS],
        "reason_total": sum(reasons.values()),
        "thin": thin, "thin_threshold": THIN_THRESHOLD,
        "note": ("S1 후보 카운터와 같은 집합(추천 뷰 ∧ 재고>0)입니다 · 규칙·정책 버전 표기는"
                 " 버전 관리 도입 후 실값으로 바뀝니다 · 주변기기 풀은 별도 집계(준비 중)."),
    }
