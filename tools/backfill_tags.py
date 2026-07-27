# -*- coding: utf-8 -*-
"""선호 태그 백필 — 화이트·저소음 (슬라이스 48).

실행:
  .venv/Scripts/python tools/backfill_tags.py --dry
  .venv/Scripts/python tools/backfill_tags.py

**왜 respec과 분리했나**: respec은 "비어 있는 필드만 채운다"는 규칙으로 돌고, 태그 컬럼은
DB 기본값이 `false`다. respec에게는 false가 '이미 있는 값'으로 보여 영원히 건너뛴다.
태그에서는 **false = 아직 판정하지 않음**이므로 규칙이 다르다. 규칙이 다른 일은 도구를 나눈다.

**명시된 표현만 태그로 인정한다**(catalog_map.extract_tags): '무소음'·'저소음'처럼 제조사가
쓴 말이 근거다. "팬이 크니 조용할 것"처럼 추론하지 않는다 — 지어낸 태그는 고객이
"조용하게"라고 말한 이유를 배신한다. `locked_fields`로 잠긴 것은 건드리지 않는다.
"""
import argparse
import io
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.catalog_map import extract_tags            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.product_code, p.part_type, p.product_name, p.spec_source_text,
                   p.locked_fields, p.status, p.stock_qty,
                   ps.tag_white, ps.tag_silent, ps.spec_sources
            FROM products p JOIN product_specs ps USING (product_code)
            WHERE p.category_group = 'core_part'
        """)).mappings().all()
    print(f"핵심 부품 {len(rows):,}건 스캔\n")

    updates, hit = [], Counter()
    sale_hit = Counter()
    for r in rows:
        tags, src = extract_tags(r["part_type"], r["product_name"], r["spec_source_text"])
        if not tags:
            continue
        locked = set(r["locked_fields"] or [])
        new = {}
        for f, v in tags.items():
            if r[f]:                       # 이미 true — 다시 쓰지 않는다
                continue
            if f in locked or f"specs.{f}" in locked:
                continue
            new[f] = v
            hit[f"{r['part_type']}.{f}"] += 1
            if r["status"] == "판매중" and (r["stock_qty"] or 0) > 0:
                sale_hit[f"{r['part_type']}.{f}"] += 1
        if new:
            merged = dict(r["spec_sources"] or {})
            merged.update({f: src[f] for f in new})
            updates.append({"pc": r["product_code"], "vals": new, "src": merged})

    print("=== 붙일 태그 (판매중·재고>0 기준 괄호) ===")
    for k in sorted(hit, key=lambda x: -hit[x]):
        print(f"  {k:34s} {hit[k]:>5,}  ({sale_hit.get(k, 0):,})")
    print(f"\n합계 {sum(hit.values()):,}건 · 상품 {len(updates):,}건")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return
    if not updates:
        print("\n붙일 태그가 없습니다.")
        return

    with engine.begin() as conn:
        for i in range(0, len(updates), BATCH):
            for u in updates[i:i + BATCH]:
                sets = [f"{f} = :{f}" for f in u["vals"]]
                sets.append("spec_sources = CAST(:src AS JSONB)")
                sets.append("updated_at = now()")
                p = {"pc": u["pc"], "src": json.dumps(u["src"], ensure_ascii=False)}
                p.update(u["vals"])
                conn.execute(text(
                    f"UPDATE product_specs SET {', '.join(sets)} WHERE product_code = :pc"), p)
            print(f"  반영 {min(i + BATCH, len(updates)):,}/{len(updates):,}")

    # 반영 후: 저소음·화이트 조건에서 각 슬롯에 후보가 남는지 — 견적 성립의 전제다
    with engine.connect() as c:
        print("\n=== 조건 적용 시 슬롯별 잔존(추천 후보·재고>0) ===")
        for label, cond in (("저소음", "tag_silent OR part_type NOT IN "
                                       "('GPU','POWER','CASE','COOLER_CPU_AIR','COOLER_CPU_AIO')"),
                            ("화이트", "tag_white OR part_type <> 'CASE'")):
            rows2 = c.execute(text(f"""
                SELECT part_type, count(*) FILTER (WHERE {cond}) kept
                FROM v_recommendation_candidates WHERE stock_qty > 0
                GROUP BY part_type ORDER BY part_type""")).all()
            empty = [r[0] for r in rows2 if r[1] == 0]
            print(f"  [{label}] " + " · ".join(f"{r[0]} {r[1]:,}" for r in rows2))
            print(f"      빈 슬롯: {empty or '없음'}"
                  + ("  ← 이 조건에서는 견적이 불성립한다" if empty else ""))


if __name__ == "__main__":
    main()
