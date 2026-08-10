# -*- coding: utf-8 -*-
"""기존 사양 값 이관 — `public.product_specs` → `std.part_specs` (2026-08-10)

■ 무엇을 옮기나
  `std.spec_defs` 46항목 중 **`public.product_specs` 에 같은 이름의 컬럼이 있는 20개**.
  나머지 26개는 신설 항목이라 원천이 없다(재파싱·사람 입력으로 채운다).

■ **출처를 지어내지 않는다** — 이게 이 도구의 요점이다
  같은 값이라도 어떻게 얻었는지가 다르면 신뢰도가 다르다.

    · `products.locked_fields` 에 `specs.<필드>` 가 있으면 → **`human`**, `locked=true`
      사람이 손으로 고친 값이다(388건). 잠그지 않으면 다음 재파싱이 덮어써
      **어제 고친 값이 오늘 되돌아간다**(A-16 의 짝).
    · 그 밖에는 → `parsed`. 근거는 `product_specs.spec_sources` 의 추출 방법
      (`text_kv` · `text_tokens` 등)을 그대로 남긴다.

■ 기존 행을 덮어쓰지 않는다
  재파싱(`std_parse.py`)이 이미 넣은 값과는 **겹치지 않는다** — 그쪽은 전부 신설 항목이고
  유일한 동명 필드 `length_mm` 은 재파싱이 POWER, 여기가 GPU 라 상품이 다르다.
  그래도 `ON CONFLICT DO NOTHING` 으로 막는다. 나중에 규칙이 바뀌어 겹치면
  **조용히 덮어쓰는 것보다 안 쓰는 쪽이 낫다** — 드라이런이 충돌 건수를 보고한다.

■ `public` 은 읽기만 한다. 쓰기 대상은 `std.part_specs` 뿐이다.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv                                    # noqa: E402
from sqlalchemy import create_engine, text                        # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
ENGINE = create_engine(os.environ["DATABASE_URL"])

# `public.product_specs` 컬럼 → std 필드 (이름이 같다). 값 변환이 필요한 것만 표시.
NUM_COLS = ["tdp_watt", "rated_watt", "required_power_watt", "length_mm", "gpu_max_mm",
            "cooler_height_mm", "cooler_tdp", "radiator_rows", "radiator_max_rows",
            "capacity_gb", "clock_mhz", "size_inch"]
TEXT_COLS = ["socket", "chipset", "mem_type", "form_factor", "interface"]
LIST_COLS = ["socket_list", "form_factor_list"]
INT_FROM_TEXT = ["pcie_gen"]        # '4.0' · 'PCIe5.0' 처럼 문자열로 저장돼 있다
ALL_COLS = NUM_COLS + TEXT_COLS + LIST_COLS + INT_FROM_TEXT


def _gen(v):
    """`'4.0'` · `'PCIe5.0'` → 4 · 5. 읽을 수 없으면 None(넣지 않는다)."""
    m = re.search(r"(\d)\s*\.\s*0", str(v)) or re.search(r"(\d)", str(v))
    return int(m.group(1)) if m else None


def run(apply_it):
    with ENGINE.connect() as c:
        defs = {r[0]: list(r[1]) for r in c.execute(text(
            "SELECT field_key, part_types FROM std.spec_defs")).all()}
        have = {(r[0], r[1]) for r in c.execute(text(
            "SELECT product_code, field_key FROM std.part_specs")).all()}
        cols = [x for x in ALL_COLS if x in defs]
        missing_def = [x for x in ALL_COLS if x not in defs]

        sel = ", ".join("ps." + x for x in cols)
        rows = c.execute(text(
            f"SELECT p.product_code, p.part_type, p.locked_fields, ps.spec_sources, {sel}"
            " FROM products p JOIN product_specs ps USING (product_code)"
            " WHERE p.category_group = 'core_part'")).mappings().all()

    plan, stats, conflict, skipped_type, unreadable = [], {}, 0, 0, 0
    for r in rows:
        pt = r["part_type"]
        locked = {str(x).replace("specs.", "") for x in (r["locked_fields"] or [])}
        srcs = r["spec_sources"] or {}
        for col in cols:
            v = r[col]
            if v is None:
                continue
            if pt not in defs[col]:            # 표준이 이 부품에 쓰지 않는 항목
                skipped_type += 1
                continue
            if (r["product_code"], col) in have:
                conflict += 1
                continue
            if col in INT_FROM_TEXT:
                g = _gen(v)
                if g is None:
                    unreadable += 1
                    continue
                v = g
            is_human = col in locked
            ref = ("사람 검수(잠김)" if is_human
                   else "원천 추출: %s" % (srcs.get(col) or "미상"))
            plan.append((r["product_code"], col, pt, v, is_human, ref))
            k = (col, "human" if is_human else "parsed")
            stats[k] = stats.get(k, 0) + 1

    print("=" * 74)
    print("기존 사양 이관 — %s" % ("적용" if apply_it else "드라이런(쓰지 않음)"))
    print("=" * 74)
    if missing_def:
        print("⚠ std.spec_defs 에 없어 건너뛴 컬럼: %s" % missing_def)
    print("대상 상품(core_part) %d건 · 옮길 항목 %d종\n" % (len(rows), len(cols)))
    print("  %-22s %8s %8s" % ("항목", "parsed", "human"))
    for col in cols:
        p, h = stats.get((col, "parsed"), 0), stats.get((col, "human"), 0)
        if p or h:
            print("  %-22s %8d %8d%s" % (col, p, h, "  ← 잠금" if h else ""))
    print("\n  적용 대상 밖이라 건너뜀 %d · 이미 std 에 있어 건너뜀 %d · 값을 못 읽음 %d"
          % (skipped_type, conflict, unreadable))
    print("\n총 %d건을 쓸 예정" % len(plan))
    if not apply_it:
        print("적용하려면 --apply")
        return 0

    with ENGINE.begin() as c:
        for pc, col, pt, v, is_human, ref in plan:
            vt = vn = vj = None
            if col in LIST_COLS:
                vj = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            elif col in TEXT_COLS:
                vt = str(v)[:200]
            else:
                vn = v
            c.execute(text(
                "INSERT INTO std.part_specs"
                " (product_code, field_key, value_text, value_num, value_json,"
                "  source, source_ref, confidence, locked, updated_at)"
                " VALUES (:pc, :f, :vt, :vn, CAST(:vj AS JSONB), :src, :ref, :cf, :lk, now())"
                " ON CONFLICT (product_code, field_key) DO NOTHING"),
                {"pc": pc, "f": col, "vt": vt, "vn": vn, "vj": vj,
                 "src": "human" if is_human else "parsed", "ref": ref[:200],
                 "cf": 1.00 if is_human else 0.85, "lk": is_human})
    print("적용 완료 — %d건" % len(plan))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(기본은 드라이런)")
    sys.exit(run(ap.parse_args().apply))
