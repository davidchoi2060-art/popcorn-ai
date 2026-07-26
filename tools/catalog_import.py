# -*- coding: utf-8 -*-
"""카탈로그 적재(T0) — 실파일 24,303행을 products·product_specs·검수 큐로 (슬라이스 39).

실행:
  .venv/Scripts/python tools/catalog_import.py                 # 실데이터 전량
  .venv/Scripts/python tools/catalog_import.py --origin demo    # 데모로 적재(구분용)
  .venv/Scripts/python tools/catalog_import.py --limit 500      # 일부만(시험)

**왜 스크립트인가**: 12MB CSV 3본을 브라우저로 올리는 업로드 UI는 이 단계에서 과하다.
적재 이력은 `csv_import_jobs`에 남으므로 관리자 화면(ADM-SYS: 일괄 등록 이력)에서 보인다.
파일 업로드 UI는 이관.

**데모/실데이터 구분**(사용자 지시): `--origin demo|real`이 그대로 `products.data_origin`에
들어간다. 앞으로도 데모를 올려 테스트할 수 있고, 실운영 데이터와 섞이지 않는다.

**재실행 안전**: product_code(= 자체상품코드) 기준 upsert. 잠긴 필드(locked_fields)는
건드리지 않는다 — 운영자가 손으로 고친 값을 적재가 덮으면 검수 노동이 무효가 된다.
"""
import argparse
import csv
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv                      # noqa: E402
from sqlalchemy import create_engine, text          # noqa: E402

from api.catalog_map import extract_specs, map_part_type   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"E:\GDRIVE\0.신사업\2.AI 영업사원\2단계\산출물"
MASTER = os.path.join(SRC, "최종_정제완료_상품데이터.csv")
DB_PRODUCTS = os.path.join(SRC, "db_products.csv")
DB_SPECS = os.path.join(SRC, "db_product_specs.csv")

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
SPEC_COLS = ["socket", "socket_list", "chipset", "mem_type", "capacity_gb", "clock_mhz",
             "tdp_watt", "rated_watt", "required_power_watt", "length_mm", "gpu_max_mm",
             "cooler_height_mm", "cooler_tdp", "pcie_gen", "form_factor", "interface",
             "size_inch", "resolution", "refresh_hz", "panel"]
JSON_COLS = {"socket_list", "form_factor_list"}
# product_specs의 VARCHAR 길이(DB 실측) — 초과 값은 잘라 넣고 검수로 알린다
SPEC_MAXLEN = {"socket": 30, "chipset": 50, "mem_type": 10, "pcie_gen": 20,
               "form_factor": 50, "interface": 50, "resolution": 20, "panel": 20}
BATCH = 500


def _int(v):
    s = (v or "").strip().replace(",", "")
    return int(s) if s.isdigit() else None


def load_eav():
    pid_to_code = {}
    for r in csv.DictReader(io.open(DB_PRODUCTS, encoding="utf-8-sig", newline="")):
        pid_to_code[r["product_id"]] = (r["custom_product_code"] or "").strip()
    kvs, feats = defaultdict(dict), defaultdict(list)
    for r in csv.DictReader(io.open(DB_SPECS, encoding="utf-8-sig", newline="")):
        code = pid_to_code.get(r["product_id"])
        if not code:
            continue
        k, v = (r["spec_key"] or "").strip(), (r["spec_value"] or "").strip()
        if k == "특성":
            feats[code].append(v)
        elif k:
            kvs[code].setdefault(k, v)
    return kvs, feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", choices=["real", "demo"], default="real")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as c:
        gpu_ref = dict(c.execute(text(
            "SELECT chipset_key, recommended_watt FROM gpu_power_reference")).all())
        locked = {r[0]: (r[1] or []) for r in c.execute(text(
            "SELECT product_code, locked_fields FROM products"
            " WHERE jsonb_array_length(locked_fields) > 0")).all()}
        # danawa_code는 UNIQUE다(단가표 자동 매칭이 이 값으로 상품 하나를 특정한다).
        # 이미 다른 상품이 점유한 코드는 가져갈 수 없다.
        dan_owner = {r[0]: r[1] for r in c.execute(text(
            "SELECT danawa_code, product_code FROM products WHERE danawa_code IS NOT NULL")).all()}
    print(f"GPU 참조표 {len(gpu_ref)}종 · 잠금 보유 상품 {len(locked)}건")

    print("EAV 로드 중...")
    kvs, feats = load_eav()
    rows = list(csv.DictReader(io.open(MASTER, encoding="utf-8-sig", newline="")))
    if args.limit:
        rows = rows[:args.limit]
    print(f"마스터 {len(rows):,}행 · 사양 보유 {len(set(kvs) | set(feats)):,}코드\n")

    # 실측: 다나와No가 채워진 행 중 중복이 있다(같은 제품을 색상·패키지별 코드로 관리).
    # UNIQUE 제약을 지키려면 **대표 1건만** 코드를 갖고 나머지는 비워 검수로 보낸다.
    dan_rep, dan_dup = {}, 0
    for r in rows:
        d = (r["다나와No"] or "").strip()
        c0 = _int(r["자체상품코드"])
        if not d or c0 is None:
            continue
        sale0 = (r["상태값"] or "").strip() == "판매중"
        key = (0 if sale0 else 1, c0)          # 판매중 우선 → 코드 오름차순
        if d not in dan_rep or key < dan_rep[d][0]:
            dan_rep[d] = (key, c0)
    dan_rep = {d: v[1] for d, v in dan_rep.items()}

    prods, specs, reviews, errors = [], [], [], []
    skipped = defaultdict(int)
    for i, r in enumerate(rows, 1):
        code = _int(r["자체상품코드"])
        name = (r["상품명"] or "").strip()
        if code is None or not name:
            errors.append((i, r, "자체상품코드 또는 상품명 없음"))
            continue
        l1, l2, l3 = r["카테고리1"], r["카테고리2"], r["카테고리3"]
        pt, group, reason = map_part_type(l1, l2, l3, name)
        if reason:
            skipped[reason] += 1
            continue
        skey = (r["자체상품코드"] or "").strip()
        sale = (r["상태값"] or "").strip() == "판매중"
        sp, src = extract_specs(pt, kvs.get(skey, {}), feats.get(skey, []), name, l2, gpu_ref) \
            if pt else ({}, {})
        need = REQUIRED.get(pt, [])
        missing = [f for f in need if sp.get(f) is None]
        dan = (r["다나와No"] or "").strip()[:40] or None
        dan_use = dan
        if dan:
            owner = dan_owner.get(dan)
            if dan_rep.get(dan) != code or (owner is not None and owner != code):
                dan_use = None          # 대표가 아니거나 다른 상품이 점유 중
                dan_dup += 1
                reviews.append({"pc": code, "field": "danawa_code",
                                "detail": f"다나와코드 {dan} 중복 — 대표 상품이 이미 점유"
                                          " (단가표 자동 매칭 대상에서 제외됨)"})
        # 게이트 ②: 필수 사양 전부 충족 ∧ core_part만 추천 후보로 승격
        ok = bool(need) and not missing and group == "core_part"
        prods.append({
            "pc": code, "sku": skey, "name": name[:200],
            "maker": (r["제조사"] or "").strip()[:60] or None,
            "model": (r["모델명"] or "").strip()[:120] or None,
            # part_type은 NOT NULL이다 — 미매핑은 'ETC'(미분류)로 넣는다.
            # 추천 뷰는 part_type 10종만 받으므로 견적에는 영향이 없고,
            # 화면에는 '미분류'로 드러나 분류 작업이 남은 사실이 숨지 않는다.
            "pt": pt or "ETC", "grp": group or "etc",
            "status": "판매중" if sale else "품절",
            "ai": ok, "rev": (not ok) and group == "core_part",
            "pp": _int(r["매입가"]), "sp2": _int(r["일반회원"]), "mp": _int(r["시중가"]),
            "sup": (r["공급처"] or "").strip()[:80] or None,
            "dan": dan_use,
            # 재고 수량은 원천에 없다(사용자 결정 2026-07-26): 판매중=1, 품절=0.
            # 실제 수량은 입고 화면(ADM-SRC-020)에서 실사로 채운다.
            "stock": 1 if sale else 0,
            "spec_text": (r["스펙"] or "").strip()[:2000] or None,
            "origin": args.origin,
        })
        if pt:
            row = {"pc": code, "pt": pt, "sources": json.dumps(src, ensure_ascii=False)}
            for col in SPEC_COLS:
                v = sp.get(col)
                if col in JSON_COLS and v is not None:
                    v = json.dumps(v)
                elif isinstance(v, str) and col in SPEC_MAXLEN:
                    # 원천 문자열이 컬럼 길이를 넘는 경우가 있다(모니터 해상도·패널 원문 등).
                    # 잘라 넣되 잘렸다는 사실을 검수로 알린다 — 조용히 버리지 않는다.
                    if len(v) > SPEC_MAXLEN[col]:
                        reviews.append({"pc": code, "field": col,
                                        "detail": f"'{col}' 원천 값이 컬럼 한계({SPEC_MAXLEN[col]}자)를"
                                                  f" 넘어 잘림 — 원문: {v[:60]}"})
                        v = v[:SPEC_MAXLEN[col]]
                row[col] = v
            specs.append(row)
        for f in missing:
            reviews.append({"pc": code, "field": f,
                            "detail": f"{pt} 필수 사양 '{f}' 미확인 — 적재 원천에서 추출 실패"})

    print(f"적재 대상 {len(prods):,}건 · 사양 행 {len(specs):,}건 · 검수 회부 {len(reviews):,}건")
    print(f"제외 {dict(skipped)} · 오류 {len(errors)}건\n")

    with engine.begin() as conn:
        job_id = conn.execute(text(
            "INSERT INTO csv_import_jobs (file_name, row_total, row_ok, row_error, row_review,"
            " status, data_origin, source, created_by)"
            " VALUES (:f, :t, :ok, :er, :rv, '완료', :o, 'catalog_csv', 1) RETURNING job_id"),
            {"f": os.path.basename(MASTER), "t": len(rows), "ok": len(prods),
             "er": len(errors), "rv": len(reviews), "o": args.origin}).scalar()
        print(f"적재 배치 #{job_id} 기록")

        ins_p = text("""
            INSERT INTO products (product_code, sku, product_name, maker, model_name, part_type,
              category_group, status, ai_candidate_yn, review_required_yn, purchase_price,
              sale_price, market_price, supplier, danawa_code, stock_qty, spec_source_text,
              data_origin)
            VALUES (:pc, :sku, :name, :maker, :model, :pt, :grp, :status, :ai, :rev, :pp, :sp2,
              :mp, :sup, :dan, :stock, :spec_text, :origin)
            ON CONFLICT (product_code) DO UPDATE SET
              product_name = EXCLUDED.product_name, maker = EXCLUDED.maker,
              model_name = EXCLUDED.model_name, part_type = EXCLUDED.part_type,
              category_group = EXCLUDED.category_group, status = EXCLUDED.status,
              ai_candidate_yn = EXCLUDED.ai_candidate_yn,
              review_required_yn = EXCLUDED.review_required_yn,
              -- locked_fields는 JSONB 배열이다 — 요소 존재는 `?` 연산자로 본다.
              -- 운영자가 손으로 고친 값을 적재가 덮으면 검수 노동이 무효가 된다(ERD §4.3).
              purchase_price = CASE WHEN products.locked_fields ? 'purchase_price'
                                    THEN products.purchase_price ELSE EXCLUDED.purchase_price END,
              sale_price = CASE WHEN products.locked_fields ? 'sale_price'
                                THEN products.sale_price ELSE EXCLUDED.sale_price END,
              market_price = EXCLUDED.market_price, supplier = EXCLUDED.supplier,
              danawa_code = EXCLUDED.danawa_code, stock_qty = EXCLUDED.stock_qty,
              spec_source_text = EXCLUDED.spec_source_text, data_origin = EXCLUDED.data_origin,
              updated_at = now()
        """)
        for i in range(0, len(prods), BATCH):
            conn.execute(ins_p, prods[i:i + BATCH])
            if (i // BATCH) % 10 == 0:
                print(f"  products {min(i + BATCH, len(prods)):,}/{len(prods):,}")

        set_cols = ", ".join(f"{c} = EXCLUDED.{c}" for c in SPEC_COLS)
        ins_s = text(f"""
            INSERT INTO product_specs (product_code, part_type, {', '.join(SPEC_COLS)},
              spec_sources, extract_source, confidence)
            VALUES (:pc, :pt, {', '.join(':' + c for c in SPEC_COLS)},
              CAST(:sources AS JSONB), 'csv', 0.8)
            ON CONFLICT (product_code) DO UPDATE SET
              part_type = EXCLUDED.part_type, {set_cols},
              spec_sources = EXCLUDED.spec_sources, extract_source = 'csv', updated_at = now()
        """)
        for i in range(0, len(specs), BATCH):
            conn.execute(ins_s, specs[i:i + BATCH])
            if (i // BATCH) % 10 == 0:
                print(f"  product_specs {min(i + BATCH, len(specs)):,}/{len(specs):,}")

        # 검수 큐 — 같은 상품·같은 필드의 대기 행이 있으면 만들지 않는다(재실행 안전)
        ins_r = text("""
            INSERT INTO product_reviews (product_code, review_type, field_name, detail,
              review_status, confidence)
            SELECT :pc, 'spec_missing', :field, :detail, '대기', 0.8
             WHERE NOT EXISTS (SELECT 1 FROM product_reviews x
                                WHERE x.product_code = :pc AND x.field_name = :field
                                  AND x.review_status = '대기')
        """)
        for i in range(0, len(reviews), BATCH):
            conn.execute(ins_r, reviews[i:i + BATCH])
        print(f"  검수 큐 {len(reviews):,}건 회부")

        for row_no, raw, why in errors[:200]:
            conn.execute(text(
                "INSERT INTO csv_import_errors (job_id, row_no, raw_row, reason)"
                " VALUES (:j, :n, CAST(:r AS JSONB), :why)"),
                {"j": job_id, "n": row_no, "r": json.dumps(raw, ensure_ascii=False), "why": why})

    q = {
        "total": "SELECT count(*) FROM products",
        "real": "SELECT count(*) FROM products WHERE data_origin = 'real'",
        "demo": "SELECT count(*) FROM products WHERE data_origin = 'demo'",
        "pool": "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0",
        "review": "SELECT count(*) FROM product_reviews WHERE review_status = '대기'",
    }
    with engine.connect() as c:
        got = {k: c.execute(text(s)).scalar_one() for k, s in q.items()}
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
