"""카탈로그 적재 로직 — CLI와 업로드 API의 **단일 원천** (슬라이스 50).

이전에는 적재가 `tools/catalog_import.py` 하나뿐이었고 파일 경로가 하드코딩이었다.
업로드 화면을 열면서 같은 일을 두 번 구현하면 **스크립트와 화면이 다른 결과를 낸다** —
그 순간 "왜 이 상품이 안 올라왔지?"에 답할 수 없게 된다. 그래서 계획 수립(build_plan)과
반영(apply_plan)을 여기로 옮기고, CLI도 API도 이 함수만 부른다.

경계:
  · build_plan은 **DB를 건드리지 않는다** — 순수 계산이라 드라이런이 곧 미리보기다.
  · apply_plan은 한 트랜잭션이다 — 중간에 실패하면 통째로 없던 일이 된다.
  · 적재는 product_code 기준 upsert이고 **삭제가 없다**. 올린다고 기존 상품이 사라지지 않는다.
  · `locked_fields`로 잠근 값은 덮지 않는다(운영자가 손으로 고친 값 보호 — ERD §4.3).
"""
import csv
import io
import json
import os
from collections import defaultdict

from sqlalchemy import text

from .catalog_map import extract_specs, map_part_type

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
             "size_inch", "resolution", "refresh_hz", "panel",
             "radiator_rows", "radiator_max_rows"]
JSON_COLS = {"socket_list", "form_factor_list"}
# product_specs의 VARCHAR 길이(DB 실측) — 초과 값은 잘라 넣고 검수로 알린다
SPEC_MAXLEN = {"socket": 30, "chipset": 50, "mem_type": 10, "pcie_gen": 20,
               "form_factor": 50, "interface": 50, "resolution": 20, "panel": 20}
BATCH = 500

# 마스터 CSV가 반드시 가져야 하는 컬럼. 없으면 적재가 아니라 **거부**다 —
# 컬럼이 어긋난 파일을 받아 절반만 넣으면 나중에 무엇이 틀렸는지 알 수 없다.
MASTER_REQUIRED_COLS = ["자체상품코드", "상품명", "카테고리1", "카테고리2", "카테고리3",
                        "상태값", "매입가", "일반회원", "시중가", "공급처", "스펙",
                        "제조사", "모델명", "다나와No"]


def _int(v):
    s = (v or "").strip().replace(",", "")
    return int(s) if s.isdigit() else None


def read_master(raw: bytes) -> list[dict]:
    """마스터 CSV 바이트 → 행 목록. 컬럼이 모자라면 ValueError."""
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    if not rows:
        raise ValueError("빈 파일입니다")
    missing = [c for c in MASTER_REQUIRED_COLS if c not in rows[0]]
    if missing:
        raise ValueError("필수 컬럼이 없습니다: " + ", ".join(missing))
    return rows


def load_eav(products_raw: bytes | None, specs_raw: bytes | None):
    """사양 EAV(선택) — 없으면 빈 값. 그 경우 사양은 상품명·스펙 원문에서만 뽑힌다."""
    if not products_raw or not specs_raw:
        return {}, {}
    pid_to_code = {}
    for r in csv.DictReader(io.StringIO(products_raw.decode("utf-8-sig"), newline="")):
        pid_to_code[r.get("product_id")] = (r.get("custom_product_code") or "").strip()
    kvs, feats = defaultdict(dict), defaultdict(list)
    for r in csv.DictReader(io.StringIO(specs_raw.decode("utf-8-sig"), newline="")):
        code = pid_to_code.get(r.get("product_id"))
        if not code:
            continue
        k, v = (r.get("spec_key") or "").strip(), (r.get("spec_value") or "").strip()
        if k == "특성":
            feats[code].append(v)
        elif k:
            kvs[code].setdefault(k, v)
    return dict(kvs), dict(feats)


# 필수 사양 판정에 쓰이는 필드 전부(REQUIRED의 합집합). 기존 값을 함께 봐야
# "이 적재 후 이 상품의 사양이 완전한가"를 정직하게 판단할 수 있다.
GATE_FIELDS = sorted({f for fs in REQUIRED.values() for f in fs})


def read_refs(conn) -> dict:
    """계획 수립에 필요한 현재 DB 상태(잠금·다나와 점유·GPU 참조표·기존 사양)."""
    gpu_ref = dict(conn.execute(text(
        "SELECT chipset_key, recommended_watt FROM gpu_power_reference")).all())
    locked = {r[0]: (r[1] or []) for r in conn.execute(text(
        "SELECT product_code, locked_fields FROM products"
        " WHERE jsonb_array_length(locked_fields) > 0")).all()}
    # danawa_code는 UNIQUE다(단가표 자동 매칭이 이 값으로 상품 하나를 특정한다).
    dan_owner = {r[0]: r[1] for r in conn.execute(text(
        "SELECT danawa_code, product_code FROM products WHERE danawa_code IS NOT NULL")).all()}
    # 이미 확인된 사양. **이걸 모르면 EAV 없이 올린 파일이 기존 사양을 지운 것으로 계산되어
    # 멀쩡한 추천 후보를 검수로 떨어뜨린다** — 실제로 그런 일이 있었다(슬라이스 50).
    existing = {r[0]: {k: v for k, v in zip(GATE_FIELDS, r[1:]) if v is not None}
                for r in conn.execute(text(
                    f"SELECT product_code, {', '.join(GATE_FIELDS)} FROM product_specs")).all()}
    return {"gpu_ref": gpu_ref, "locked": locked, "dan_owner": dan_owner,
            "existing": existing}


def build_plan(rows: list[dict], kvs: dict, feats: dict, refs: dict, origin: str) -> dict:
    """행 목록 → 적재 계획. **DB를 바꾸지 않는다** — 이 결과가 곧 드라이런 리포트다."""
    gpu_ref, dan_owner = refs["gpu_ref"], refs["dan_owner"]
    existing = refs.get("existing") or {}

    # 실측: 다나와No가 채워진 행 중 중복이 있다(같은 제품을 색상·패키지별 코드로 관리).
    # UNIQUE 제약을 지키려면 **대표 1건만** 코드를 갖고 나머지는 비워 검수로 보낸다.
    dan_rep = {}
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
        # 스펙 원문을 함께 넘긴다 — 원천이 액세서리로 분류한 것을 부품으로 올리지 않는다
        pt, group, reason = map_part_type(l1, l2, l3, name, (r["스펙"] or "").strip())
        if reason:
            skipped[reason] += 1
            continue
        skey = (r["자체상품코드"] or "").strip()
        sale = (r["상태값"] or "").strip() == "판매중"
        sp, src = extract_specs(pt, kvs.get(skey, {}), feats.get(skey, []), name, l2, gpu_ref) \
            if pt else ({}, {})
        need = REQUIRED.get(pt, [])
        # 적재는 채우기만 하고 지우지 않는다(apply_plan의 COALESCE) — 따라서 '없는 사양'은
        # 새로 뽑은 값과 **이미 있는 값을 합쳐서** 판정해야 한다. 새 값만 보면 EAV를 안 올린
        # 파일이 멀쩡한 후보를 전부 검수로 떨어뜨린다(슬라이스 50 실측: 후보 -1 · 검수 +169).
        have = existing.get(code) or {}
        missing = [f for f in need if sp.get(f) is None and have.get(f) is None]
        dan = (r["다나와No"] or "").strip()[:40] or None
        dan_use = dan
        if dan:
            owner = dan_owner.get(dan)
            if dan_rep.get(dan) != code or (owner is not None and owner != code):
                dan_use = None          # 대표가 아니거나 다른 상품이 점유 중
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
            "pt": pt or "ETC", "grp": group or "etc",
            "status": "판매중" if sale else "품절",
            "ai": ok, "rev": (not ok) and group == "core_part",
            "pp": _int(r["매입가"]), "sp2": _int(r["일반회원"]), "mp": _int(r["시중가"]),
            "sup": (r["공급처"] or "").strip()[:80] or None,
            "dan": dan_use,
            # 재고 수량은 원천에 없다(사용자 결정 2026-07-26): 판매중=1, 품절=0.
            "stock": 1 if sale else 0,
            "spec_text": (r["스펙"] or "").strip()[:2000] or None,
            "origin": origin,
        })
        if pt:
            row = {"pc": code, "pt": pt, "sources": json.dumps(src, ensure_ascii=False)}
            for col in SPEC_COLS:
                v = sp.get(col)
                if col in JSON_COLS and v is not None:
                    v = json.dumps(v)
                elif isinstance(v, str) and col in SPEC_MAXLEN:
                    # 잘라 넣되 잘렸다는 사실을 검수로 알린다 — 조용히 버리지 않는다.
                    if len(v) > SPEC_MAXLEN[col]:
                        reviews.append({"pc": code, "field": col,
                                        "detail": f"'{col}' 원천 값이 컬럼 한계"
                                                  f"({SPEC_MAXLEN[col]}자)를 넘어 잘림"
                                                  f" — 원문: {v[:60]}"})
                        v = v[:SPEC_MAXLEN[col]]
                row[col] = v
            specs.append(row)
        for f in missing:
            reviews.append({"pc": code, "field": f,
                            "detail": f"{pt} 필수 사양 '{f}' 미확인 — 적재 원천에서 추출 실패"})

    return {"prods": prods, "specs": specs, "reviews": reviews, "errors": errors,
            "skipped": dict(skipped), "row_total": len(rows)}


def plan_impact(conn, plan: dict) -> dict:
    """이 적재가 **무엇을 바꾸는가** — 신규/갱신, 추천 후보 진입/이탈.

    건수만 보여주면 "몇 건 들어간다"만 알고 "무엇이 무너지는가"는 모른다.
    슬라이스 50에서 EAV 없이 올린 파일이 후보를 떨어뜨렸는데 리포트에는 안 보였다.
    """
    codes = [p["pc"] for p in plan["prods"]]
    if not codes:
        return {"new": 0, "update": 0, "pool_in": 0, "pool_out": 0}
    known = {r[0] for r in conn.execute(
        text("SELECT product_code FROM products WHERE product_code = ANY(:c)"),
        {"c": codes}).all()}
    # 지금 후보에 있는 상품 중 이번 적재 대상
    pool_now = {r[0] for r in conn.execute(
        text("SELECT product_code FROM v_recommendation_candidates"
             " WHERE stock_qty > 0 AND product_code = ANY(:c)"), {"c": codes}).all()}
    # 적재 후 후보가 될 상품 = 게이트 ②(ai) ∧ 재고>0 ∧ core_part
    will = {p["pc"] for p in plan["prods"]
            if p["ai"] and p["stock"] > 0 and p["grp"] == "core_part"}
    # 검수 회부는 (상품, 필드)로 중복을 막으므로 계획 수(len(reviews))가 곧 증가분이 아니다.
    # "198건 회부"라고 말했는데 실제 증가가 0이면 화면이 헛수를 말한 것이다(슬라이스 50).
    pending = {(r[0], r[1]) for r in conn.execute(text(
        "SELECT product_code, field_name FROM product_reviews"
        " WHERE review_status = '대기' AND product_code = ANY(:c)"), {"c": codes}).all()}
    review_new = len({(r["pc"], r["field"]) for r in plan["reviews"]} - pending)
    return {
        "new": sum(1 for c in codes if c not in known),
        "update": sum(1 for c in codes if c in known),
        "pool_in": len(will - pool_now),
        "pool_out": len(pool_now - will),
        "review_new": review_new,
        "review_planned": len(plan["reviews"]),
    }


def plan_summary(plan: dict) -> dict:
    """드라이런 리포트 — 화면이 그대로 쓰는 수치. 추정이 아니라 계획의 실측이다."""
    prods = plan["prods"]
    by_type: dict[str, dict] = {}
    for p in prods:
        b = by_type.setdefault(p["pt"], {"n": 0, "promote": 0})
        b["n"] += 1
        if p["ai"]:
            b["promote"] += 1
    return {
        "row_total": plan["row_total"],
        "ok": len(prods),
        "spec_rows": len(plan["specs"]),
        "review": len(plan["reviews"]),
        "error": len(plan["errors"]),
        "promote": sum(1 for p in prods if p["ai"]),
        "skipped": plan["skipped"],
        "skipped_total": sum(plan["skipped"].values()),
        "by_type": sorted(
            ({"part_type": k, **v} for k, v in by_type.items()),
            key=lambda x: -x["n"]),
        "error_samples": [{"row_no": n, "reason": why} for n, _, why in plan["errors"][:20]],
    }


def apply_plan(conn, plan: dict, file_name: str, origin: str, operator_id: int) -> int:
    """계획을 한 트랜잭션으로 반영하고 배치 번호를 돌려준다. 호출자가 트랜잭션을 연다."""
    prods, specs, reviews, errors = (plan["prods"], plan["specs"],
                                     plan["reviews"], plan["errors"])
    job_id = conn.execute(text(
        "INSERT INTO csv_import_jobs (file_name, row_total, row_ok, row_error, row_review,"
        " status, data_origin, source, created_by)"
        " VALUES (:f, :t, :ok, :er, :rv, '완료', :o, 'catalog_csv', :by) RETURNING job_id"),
        {"f": file_name[:200], "t": plan["row_total"], "ok": len(prods),
         "er": len(errors), "rv": len(reviews), "o": origin, "by": operator_id}).scalar()

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

    # **적재는 채우기만 하고 지우지 않는다.** 새 파일에서 못 뽑은 필드가 기존 값을 NULL로
    # 덮으면, EAV를 빼고 마스터만 올린 한 번의 적재가 추천 후보를 통째로 무너뜨린다
    # (슬라이스 50에서 실제로 겪었다). 잘못된 사양을 비우는 일은 검수 화면 소관이다.
    set_cols = ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, product_specs.{c})" for c in SPEC_COLS)
    ins_s = text(f"""
        INSERT INTO product_specs (product_code, part_type, {', '.join(SPEC_COLS)},
          spec_sources, extract_source, confidence)
        VALUES (:pc, :pt, {', '.join(':' + c for c in SPEC_COLS)},
          CAST(:sources AS JSONB), 'csv', 0.8)
        ON CONFLICT (product_code) DO UPDATE SET
          part_type = EXCLUDED.part_type, {set_cols},
          -- 출처도 덮지 않고 합친다(새 출처가 우선) — 어디서 온 값인지 잃지 않는다
          spec_sources = COALESCE(product_specs.spec_sources, '{{}}'::jsonb)
                         || COALESCE(EXCLUDED.spec_sources, '{{}}'::jsonb),
          extract_source = 'csv', updated_at = now()
    """)
    for i in range(0, len(specs), BATCH):
        conn.execute(ins_s, specs[i:i + BATCH])

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

    for row_no, raw, why in errors[:200]:
        conn.execute(text(
            "INSERT INTO csv_import_errors (job_id, row_no, raw_row, reason)"
            " VALUES (:j, :n, CAST(:r AS JSONB), :why)"),
            {"j": job_id, "n": row_no, "r": json.dumps(raw, ensure_ascii=False), "why": why})
    return job_id


def read_file(path: str) -> bytes:
    with io.open(path, "rb") as f:
        return f.read()


def basename(path: str) -> str:
    return os.path.basename(path)
