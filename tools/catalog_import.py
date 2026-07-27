# -*- coding: utf-8 -*-
"""실카탈로그 적재 CLI (슬라이스 39 · 슬라이스 50에서 로직 분리).

실행:
  .venv/Scripts/python tools/catalog_import.py --dry
  .venv/Scripts/python tools/catalog_import.py --origin real
  .venv/Scripts/python tools/catalog_import.py --origin demo --limit 30

**적재 로직은 여기에 없다.** `api/catalog_ingest`가 단일 원천이고, 관리자 업로드 화면도
같은 함수를 부른다 — 스크립트와 화면이 다른 결과를 내면 "왜 이 상품이 안 올라왔지?"에
답할 수 없기 때문이다(슬라이스 50). 이 파일은 파일을 읽어 넘기고 결과를 보여줄 뿐이다.

적재 이력은 `csv_import_jobs`에 남으므로 관리자 화면(ADM-SYS: 일괄 등록 이력)에서 보인다.
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

from api.catalog_ingest import (                    # noqa: E402
    apply_plan, build_plan, load_eav, plan_summary, read_master,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"E:\GDRIVE\0.신사업\2.AI 영업사원\2단계\산출물"
MASTER = os.path.join(SRC, "최종_정제완료_상품데이터.csv")
DB_PRODUCTS = os.path.join(SRC, "db_products.csv")
DB_SPECS = os.path.join(SRC, "db_product_specs.csv")


def _read(path):
    with io.open(path, "rb") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", choices=["real", "demo"], default="real")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="계획만 보고 DB를 바꾸지 않는다")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    print("EAV 로드 중...")
    kvs, feats = load_eav(_read(DB_PRODUCTS), _read(DB_SPECS))
    rows = read_master(_read(MASTER))
    if args.limit:
        rows = rows[:args.limit]
    print(f"마스터 {len(rows):,}행 · 사양 보유 {len(set(kvs) | set(feats)):,}코드\n")

    with engine.connect() as c:
        from api.catalog_ingest import read_refs
        refs = read_refs(c)
    print(f"GPU 참조표 {len(refs['gpu_ref'])}종 · 잠금 보유 상품 {len(refs['locked'])}건")

    plan = build_plan(rows, kvs, feats, refs, args.origin)
    s = plan_summary(plan)
    print(f"적재 대상 {s['ok']:,}건 · 사양 행 {s['spec_rows']:,}건"
          f" · 검수 회부 {s['review']:,}건")
    print(f"제외 {s['skipped']} · 오류 {s['error']}건\n")

    if args.dry:
        print("--dry 모드 — DB를 바꾸지 않았습니다.")
        return

    with engine.begin() as conn:
        job_id = apply_plan(conn, plan, os.path.basename(MASTER), args.origin, operator_id=1)
    print(f"적재 배치 #{job_id} 완료")

    q = {
        "total": "SELECT count(*) FROM products",
        "real": "SELECT count(*) FROM products WHERE data_origin = 'real'",
        "demo": "SELECT count(*) FROM products WHERE data_origin = 'demo'",
        "pool": "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0",
        "review": "SELECT count(*) FROM product_reviews WHERE review_status = '대기'",
    }
    with engine.connect() as c:
        got = {k: c.execute(text(v)).scalar_one() for k, v in q.items()}
        print("\n=== 적재 후 실측 ===")
        print(f"  products {got['total']:,} (real {got['real']:,} · demo {got['demo']:,})")
        print(f"  추천 후보(뷰 ∧ 재고>0): {got['pool']:,}")
        print(f"  검수 대기: {got['review']:,}")
        for r in c.execute(text(
                "SELECT part_type, count(*) n, count(*) FILTER (WHERE ai_candidate_yn) ok"
                " FROM products WHERE category_group = 'core_part' GROUP BY part_type"
                " ORDER BY part_type")):
            print(f"    {r[0]:16s} {r[1]:>6,}건 · 추천 승격 {r[2]:>5,}")


if __name__ == "__main__":
    main()
