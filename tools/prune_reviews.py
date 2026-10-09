# -*- coding: utf-8 -*-
"""검수 큐 정합 정리 — 이미 값이 채워진 대기 행을 해소한다 (슬라이스 50).

실행:
  .venv/Scripts/python tools/prune_reviews.py --dry
  .venv/Scripts/python tools/prune_reviews.py

**왜 필요한가.** 적재는 "필수 사양이 없다"고 판단하면 검수 행을 만든다. 그런데 이후 다른
경로(EAV 재적재·respec·운영자 입력)로 그 값이 채워지면 대기 행만 남는다. 운영자가 열어보면
"값이 이미 있는데 왜 검수?"가 되고, 큐 규모가 실제 할 일보다 부풀어 보인다.
슬라이스 50에서 117건이 그 상태였다.

**삭제하지 않는다.** 원장 원칙대로 `review_status='처리'`로 전이하고 사유를 detail에 남긴다 —
왜 사라졌는지 나중에 추적할 수 있어야 한다.

이 정리가 필요 없는 상태를 회귀가 지킨다("대기 검수에 이미 채워진 필드가 없다").

**사람이 확인한 값만 해소한다 (2026-10-09 개정).** 값이 채워졌다는 것만으로는 검수가
끝났다고 볼 수 없다 — 웹 제안·자동 추출로 들어온 값은 사람이 아직 안 봤다. 회귀 run #5
에서 그런 행 5건을 이 도구가 '처리'로 넘길 뻔했다(당시 11건을 잡았다). 그래서 해소 대상은
그 필드가 `products.locked_fields` 에 잠긴 행, 즉 운영자가 상품 상세에서 직접 넣은 값만이다
(잠금 표기는 `field` 또는 `specs.field` 둘 다 — `tools/std_import_public.py` 의 `human`
판정과 같은 기준). 나머지는 «값 검수 대기»로 남기고 건수만 알린다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools._console import ensure_utf8_console       # noqa: E402
ensure_utf8_console()

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.catalog_ingest import SPEC_COLS            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# product_specs에 실제로 있는 사양 컬럼 전부(JSONB 배열 컬럼 포함)
FIELDS = sorted(set(SPEC_COLS) | {"form_factor_list"})
# 사람이 확인한 값 = 그 필드가 products.locked_fields 에 잠겨 있다(상품 상세 사양 입력이 잠근다).
# 별칭 r(product_reviews)·p(products)를 전제로 한다.
HUMAN_LOCKED = ("(COALESCE(p.locked_fields, '[]'::jsonb) ? r.field_name"
                " OR COALESCE(p.locked_fields, '[]'::jsonb) ? ('specs.' || r.field_name))")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        before = c.execute(text(
            "SELECT count(*) FROM product_reviews WHERE review_status='대기'")).scalar()
        found, unconfirmed = {}, {}
        for col in FIELDS:
            row = c.execute(text(f"""
                SELECT count(*) FILTER (WHERE {HUMAN_LOCKED}),
                       count(*) FILTER (WHERE NOT {HUMAN_LOCKED})
                  FROM product_reviews r JOIN product_specs s USING (product_code)
                  JOIN products p USING (product_code)
                 WHERE r.review_status='대기' AND r.review_type='spec_missing'
                   AND r.field_name = :f AND s.{col} IS NOT NULL"""), {"f": col}).one()
            if row[0]:
                found[col] = row[0]
            if row[1]:
                unconfirmed[col] = row[1]
    print(f"대기 {before:,}건 중 사람이 확인한 값으로 채워진 항목 {sum(found.values()):,}건")
    for k in sorted(found, key=lambda x: -found[x]):
        print(f"  {k:22s} {found[k]:>5,}")
    if unconfirmed:
        print(f"값은 있으나 사람 확인 전이라 남기는 항목 {sum(unconfirmed.values()):,}건 (값 검수 대상)")
        for k in sorted(unconfirmed, key=lambda x: -unconfirmed[x]):
            print(f"  {k:22s} {unconfirmed[k]:>5,}")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return
    if not found:
        print("\n정리할 항목이 없습니다.")
        return

    total = 0
    with engine.begin() as conn:
        for col in found:
            r = conn.execute(text(f"""
                UPDATE product_reviews r SET review_status='처리', reviewed_at=now(),
                       detail = detail || ' [정합 정리: 사람이 확인한(잠긴) 값으로 해소]'
                 WHERE r.review_status='대기' AND r.review_type='spec_missing'
                   AND r.field_name = :f
                   AND EXISTS (SELECT 1 FROM product_specs s JOIN products p USING (product_code)
                                WHERE s.product_code = r.product_code AND s.{col} IS NOT NULL
                                  AND {HUMAN_LOCKED})
            """), {"f": col})
            total += r.rowcount
        # 필수 사양이 모두 찬 상품은 검수 플래그를 내리고 추천 후보로 올린다(게이트 ②)
        conn.execute(text("""
            UPDATE products p SET review_required_yn = false, ai_candidate_yn = true,
                                 updated_at = now()
             WHERE p.review_required_yn
               AND p.category_group = 'core_part'
               AND NOT EXISTS (SELECT 1 FROM product_reviews x
                                WHERE x.product_code = p.product_code
                                  AND x.review_status = '대기')
        """))
    with engine.connect() as c:
        after = c.execute(text(
            "SELECT count(*) FROM product_reviews WHERE review_status='대기'")).scalar()
        pool = c.execute(text("SELECT count(*) FROM v_recommendation_candidates"
                              " WHERE stock_qty > 0")).scalar()
    print(f"\n해소 {total:,}건 · 대기 {before:,} -> {after:,} · 추천 후보 {pool:,}")


if __name__ == "__main__":
    main()
