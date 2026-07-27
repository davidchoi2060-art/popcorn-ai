# -*- coding: utf-8 -*-
"""사양 재파싱 회수 — 원천에 있는데 놓친 값을 채운다 (슬라이스 42).

실행:
  .venv/Scripts/python tools/respec.py --dry     # 회수량만 계산(DB 무변경)
  .venv/Scripts/python tools/respec.py           # 실제 반영

**값을 지어내지 않는다.** 원천 '스펙' 문자열에 두 가지 표기 형식이 섞여 있었고
(A: 값 나열 / B: "키 : 값"), 적재 때 A만 읽었다. B를 읽어 **비어 있는 필드만** 채운다.

지키는 규칙:
  · 이미 값이 있는 필드는 건드리지 않는다 — 운영자가 검수로 넣은 값을 덮으면 노동이 무효가 된다.
  · `locked_fields`에 잠긴 필드도 건너뛴다(ERD §4.3).
  · 출처를 `spec_sources`에 'text_kv'로 남긴다 — 어디서 온 값인지 화면이 말할 수 있게.
  · 채워진 필드의 **검수 대기 행을 해소**하고(review_status='처리'), 필수 사양이 모두 차면
    4중 게이트 ②를 다시 판정한다(ai_candidate 승격 · review_required 해제).
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

from dotenv import load_dotenv                       # noqa: E402
from sqlalchemy import create_engine, text           # noqa: E402

from api.catalog_map import extract_from_text        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = {
    "CPU": ["socket", "tdp_watt"],
    "MB": ["socket", "chipset", "form_factor", "mem_type"],
    "RAM": ["mem_type", "capacity_gb", "clock_mhz"],
    "GPU": ["length_mm", "required_power_watt", "pcie_gen"],
    "SSD": ["form_factor", "interface", "capacity_gb"],
    "HDD": ["form_factor", "interface", "capacity_gb"],
    "POWER": ["rated_watt", "form_factor"],
    "CASE": ["form_factor_list", "gpu_max_mm", "cooler_height_mm"],
    "COOLER_CPU_AIR": ["socket_list", "cooler_height_mm", "cooler_tdp"],
    "COOLER_CPU_AIO": ["socket_list", "cooler_tdp"],
}
JSON_COLS = {"socket_list", "form_factor_list", "spec_sources"}
BATCH = 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="계산만 하고 DB를 바꾸지 않는다")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.product_code, p.part_type, p.product_name, p.spec_source_text,
                   p.locked_fields, p.status, p.stock_qty, to_jsonb(ps) AS specs,
                   ps.spec_sources
            FROM products p JOIN product_specs ps USING (product_code)
            WHERE p.category_group = 'core_part' AND p.spec_source_text IS NOT NULL
              AND (p.review_required_yn = true
                   -- 이미 승격된 케이스도 포함: 새 규칙(CASE.form_factor_list contains
                   -- MB.form_factor)이 목록을 요구하므로, 비어 있으면 견적에서 케이스가
                   -- 전부 탈락한다(슬라이스 43). 채우기만 하고 다른 값은 건드리지 않는다.
                   OR (p.part_type = 'CASE' AND ps.form_factor_list IS NULL))
        """)).mappings().all()
    print(f"검수 대기 상태의 핵심 부품 {len(rows):,}건을 재파싱합니다\n")

    updates, filled = [], Counter()
    gate_open, sale_open = 0, 0
    for r in rows:
        pt = r["part_type"]
        need = REQUIRED.get(pt)
        if not need:
            continue
        got, src = extract_from_text(pt, r["spec_source_text"], r["product_name"])
        if not got:
            continue
        specs = r["specs"] or {}
        locked = set(r["locked_fields"] or [])
        new_vals, new_src = {}, dict(r["spec_sources"] or {})
        for f, v in got.items():
            if specs.get(f) is not None:            # 이미 있는 값은 덮지 않는다
                continue
            if f in locked or f"specs.{f}" in locked:
                continue
            new_vals[f] = v
            new_src[f] = src[f]
            filled[f"{pt}.{f}"] += 1
        if not new_vals:
            continue
        merged = {**{k: specs.get(k) for k in need}, **new_vals}
        complete = all(merged.get(f) is not None for f in need)
        if complete:
            gate_open += 1
            if r["status"] == "판매중" and (r["stock_qty"] or 0) > 0:
                sale_open += 1
        updates.append({"pc": r["product_code"], "vals": new_vals,
                        "src": new_src, "complete": complete})

    print("=== 회수된 필드 (상위 15) ===")
    for k, v in filled.most_common(15):
        print(f"  {k:34s} {v:>5,}")
    print(f"\n필드 회수 합계 {sum(filled.values()):,}건 · 상품 {len(updates):,}건")
    print(f"필수 사양이 모두 차는 상품 {gate_open:,}건 (그중 판매중·재고>0 {sale_open:,}건)")

    if args.dry:
        print("\n--dry 모드 — DB를 바꾸지 않았습니다.")
        return

    if not updates:
        print("\n회수할 것이 없습니다.")
        return

    with engine.begin() as conn:
        for i in range(0, len(updates), BATCH):
            for u in updates[i:i + BATCH]:
                sets, params = [], {"pc": u["pc"]}
                for f, v in u["vals"].items():
                    if f in JSON_COLS:
                        sets.append(f"{f} = CAST(:{f} AS JSONB)")
                        params[f] = json.dumps(v)
                    else:
                        sets.append(f"{f} = :{f}")
                        params[f] = v
                sets.append("spec_sources = CAST(:src AS JSONB)")
                params["src"] = json.dumps(u["src"], ensure_ascii=False)
                sets.append("updated_at = now()")
                conn.execute(text(
                    f"UPDATE product_specs SET {', '.join(sets)} WHERE product_code = :pc"), params)

                # 채운 필드의 검수 대기 행 해소 — 삭제하지 않고 상태 전이(원장 원칙)
                conn.execute(text("""
                    UPDATE product_reviews SET review_status = '처리', reviewed_at = now(),
                           detail = detail || ' [재파싱 회수: 원천 형식 B에서 값 확인]'
                     WHERE product_code = :pc AND review_status = '대기'
                       AND field_name = ANY(:fields)
                """), {"pc": u["pc"], "fields": list(u["vals"].keys())})

                if u["complete"]:
                    # 4중 게이트 ② 재판정 — 남은 대기 검수가 없을 때만 승격한다
                    conn.execute(text("""
                        UPDATE products SET review_required_yn = false, ai_candidate_yn = true,
                               updated_at = now()
                         WHERE product_code = :pc
                           AND NOT EXISTS (SELECT 1 FROM product_reviews x
                                            WHERE x.product_code = :pc AND x.review_status = '대기')
                    """), {"pc": u["pc"]})
            print(f"  반영 {min(i + BATCH, len(updates)):,}/{len(updates):,}")

    with engine.connect() as c:
        q = {
            "pool": "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0",
            "review": "SELECT count(*) FROM product_reviews WHERE review_status = '대기'",
            "sale_review": ("SELECT count(*) FROM product_reviews r JOIN products p"
                            " USING (product_code) WHERE r.review_status = '대기'"
                            " AND p.status = '판매중' AND p.stock_qty > 0"),
        }
        got = {k: c.execute(text(s)).scalar_one() for k, s in q.items()}
    print(f"\n=== 반영 후 ===\n  추천 후보 {got['pool']:,}건"
          f"\n  검수 대기 {got['review']:,}건 (판매중 {got['sale_review']:,}건)")


if __name__ == "__main__":
    main()
