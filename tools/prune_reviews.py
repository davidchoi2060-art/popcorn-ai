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
"""
import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.catalog_ingest import SPEC_COLS            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# product_specs에 실제로 있는 사양 컬럼 전부(JSONB 배열 컬럼 포함)
FIELDS = sorted(set(SPEC_COLS) | {"form_factor_list"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        before = c.execute(text(
            "SELECT count(*) FROM product_reviews WHERE review_status='대기'")).scalar()
        found = {}
        for col in FIELDS:
            n = c.execute(text(f"""
                SELECT count(*) FROM product_reviews r JOIN product_specs s USING (product_code)
                 WHERE r.review_status='대기' AND r.review_type='spec_missing'
                   AND r.field_name = :f AND s.{col} IS NOT NULL"""), {"f": col}).scalar()
            if n:
                found[col] = n
    print(f"대기 {before:,}건 중 이미 채워진 항목 {sum(found.values()):,}건")
    for k in sorted(found, key=lambda x: -found[x]):
        print(f"  {k:22s} {found[k]:>5,}")

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
                       detail = detail || ' [정합 정리: 다른 경로로 값이 채워져 해소]'
                 WHERE r.review_status='대기' AND r.review_type='spec_missing'
                   AND r.field_name = :f
                   AND EXISTS (SELECT 1 FROM product_specs s
                                WHERE s.product_code = r.product_code AND s.{col} IS NOT NULL)
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
