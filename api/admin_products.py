"""ADM-PRD-010 관리자 상품 목록 — 읽기 1본.

응답 계약(목업 products.html과 합의):
  { items: [{product_code, sku, name, cat, maker, spec_done, spec_total,
             stock, supplier_count, sale_price, status_key}],
    kpis: {total, ok, review, oos, price} }   # 상호배타 버킷 합 (목업의 독립 카운트와 다름)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/admin")

# part_type 코드 → 화면 분류 라벨. 미등록 코드는 원문 폴백.
PART_TYPE_LABELS = {
    "CPU": "CPU", "MB": "메인보드", "RAM": "메모리", "GPU": "그래픽카드",
    "SSD": "SSD", "HDD": "HDD", "POWER": "파워", "CASE": "케이스",
    # 공랭·수냉은 견적에서 한 슬롯이지만 **상품 분류로는 다른 것**이다.
    # 같은 라벨을 쓰면 집계에 'CPU쿨러'가 두 줄로 나와 운영자가 어느 쪽인지 알 수 없고,
    # 라벨→코드 역매핑도 한쪽으로 뭉개진다(슬라이스 49).
    "COOLER_CPU_AIR": "CPU쿨러(공랭)", "COOLER_CPU_AIO": "CPU쿨러(수냉)",
    "MONITOR": "모니터", "KEYBOARD": "키보드", "MOUSE": "마우스",
    "HEADSET": "헤드셋", "SPEAKER": "스피커", "WEBCAM": "웹캠",
    "ETC": "미분류",   # 적재 시 부품 종류를 정하지 못한 상품(슬라이스 39) — 추천 대상 아님
}

# part_type별 필수 사양 필드(ERD 4.0 필수 사양 매트릭스). 미등록 타입은 0/0 → 화면 "—".
# verified_yn은 이번 집계에 미반영(전 필드 채움+미검증 케이스는 다음 슬라이스).
REQUIRED_SPEC_FIELDS = {
    "CPU": ["socket", "tdp_watt"],
    "MB": ["socket", "chipset", "form_factor", "mem_type"],
    "RAM": ["mem_type", "capacity_gb", "clock_mhz"],
    "GPU": ["length_mm", "required_power_watt", "pcie_gen"],
    "SSD": ["form_factor", "interface", "capacity_gb"],
    "HDD": ["form_factor", "interface", "capacity_gb"],
    "POWER": ["rated_watt", "form_factor"],
    "CASE": ["form_factor_list", "gpu_max_mm", "cooler_height_mm"],
    "COOLER_CPU_AIR": ["socket", "cooler_height_mm", "cooler_tdp"],
    "COOLER_CPU_AIO": ["socket", "cooler_tdp"],
    "MONITOR": ["size_inch", "resolution", "refresh_hz", "panel"],
    "KEYBOARD": ["switch_type", "key_layout", "connection"],
    "MOUSE": ["connection"],
    "HEADSET": ["connection"],
    "SPEAKER": ["connection"],
    "WEBCAM": ["connection"],
}

# 실데이터 24,303행이 들어온 뒤로 전 행 반환·전 행 순회 KPI는 불가능하다(슬라이스 39).
# 목록은 서버에서 필터·페이지네이션하고, KPI는 SQL 집계로 전체를 센다.
# status_key 파생 로직(derive_status)과 아래 CASE는 **같은 판정을 두 곳에 쓴다** —
# 성능 때문에 감수한 중복이므로 한쪽을 바꾸면 반드시 다른 쪽도 바꿔야 한다.
_STATUS_CASE = """
    CASE WHEN p.review_required_yn THEN 'review'
         WHEN p.stock_qty = 0 OR p.status = '품절' THEN 'oos'
         WHEN p.sale_price IS NULL THEN 'price'
         WHEN p.status = '판매중' THEN 'ok'
         ELSE 'review' END
"""

_WHERE = """
    WHERE (:q = '' OR p.product_name ILIKE '%%' || :q || '%%' OR p.sku ILIKE '%%' || :q || '%%'
           OR p.maker ILIKE '%%' || :q || '%%')
      AND (:part_type = '' OR p.part_type = :part_type)
      AND (:origin = '' OR p.data_origin = :origin)
"""

_QUERY = text(f"""
    SELECT p.product_code, p.sku, p.product_name, p.maker, p.part_type,
           p.status, p.review_required_yn, p.sale_price, p.stock_qty, p.data_origin,
           COALESCE(sp.cnt, 0) AS supplier_count,
           to_jsonb(ps) AS specs
    FROM products p
    LEFT JOIN product_specs ps USING (product_code)
    LEFT JOIN (SELECT product_code, COUNT(*) AS cnt
               FROM product_supplier_prices GROUP BY product_code) sp USING (product_code)
    {_WHERE}
      AND (:status = '' OR {_STATUS_CASE.strip()} = :status)
    ORDER BY p.product_code
    LIMIT :size OFFSET :offset
""")

_COUNT = text(f"""
    SELECT count(*) FROM products p
    {_WHERE}
      AND (:status = '' OR {_STATUS_CASE.strip()} = :status)
""")

_KPI = text(f"""
    SELECT {_STATUS_CASE.strip()} AS k, count(*) AS n FROM products p
    {_WHERE}
    GROUP BY 1
""")


def derive_status(row) -> str:
    """화면 상태 4종 파생. 우선순위 순 — 한 상품은 정확히 한 버킷.

    한계(주석으로 명시): sale_price=0은 NULL이 아니라 ok로 흐른다.
    """
    if row.review_required_yn:
        return "review"
    if row.stock_qty == 0 or row.status == "품절":
        return "oos"
    if row.sale_price is None:
        return "price"
    if row.status == "판매중":
        return "ok"
    return "review"  # 단종·삭제대기 안전망 — 행을 숨기지 않고 운영자 확인 대상으로


def spec_progress(part_type: str, specs: dict | None) -> tuple[int, int]:
    fields = REQUIRED_SPEC_FIELDS.get(part_type)
    if not fields:
        return 0, 0
    if specs is None:
        return 0, len(fields)
    done = sum(1 for f in fields if specs.get(f) is not None)
    return done, len(fields)


@router.get("/products")
def list_products(q: str = "", part_type: str = "", status: str = "", origin: str = "",
                  page: int = 1, size: int = 100):
    # def(비동기 아님) — psycopg2 동기 드라이버, FastAPI 스레드풀 실행
    size = max(1, min(size, 500))     # 상한 — 브라우저가 버티는 범위
    page = max(1, page)
    p = {"q": q.strip(), "part_type": part_type.strip(), "status": status.strip(),
         "origin": origin.strip(), "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        rows = conn.execute(_QUERY, p).all()
        total_count = conn.execute(_COUNT, p).scalar_one()
        kpi_rows = dict(conn.execute(_KPI, p).all())

    items = []
    kpis = {"total": sum(kpi_rows.values()), "ok": kpi_rows.get("ok", 0),
            "review": kpi_rows.get("review", 0), "oos": kpi_rows.get("oos", 0),
            "price": kpi_rows.get("price", 0)}
    for r in rows:
        status_key = derive_status(r)
        done, total = spec_progress(r.part_type, r.specs)
        items.append({
            "product_code": r.product_code,
            "sku": r.sku,
            "name": r.product_name,
            "cat": PART_TYPE_LABELS.get(r.part_type, r.part_type),
            "maker": r.maker,
            "spec_done": done,
            "spec_total": total,
            # 사양 행 자체가 없는 상품 — 값 미확인(0/N)과 구분해야 한다.
            # 추천 뷰가 product_specs를 조인하므로 이 상품은 재고·가격이 채워져도 미진입(슬라이스 23 발견).
            "spec_row_missing": r.specs is None,
            "stock": r.stock_qty,
            "supplier_count": r.supplier_count,
            "sale_price": r.sale_price,
            "status_key": status_key,
            "origin": r.data_origin,
        })
    return {"items": items, "kpis": kpis,
            "page": page, "size": size, "total": total_count,
            "pages": (total_count + size - 1) // size,
            "note": ("실데이터 24,303행 규모 — 목록은 서버에서 필터·페이지네이션됩니다."
                     " KPI는 필터 조건 전체 집계입니다(현재 페이지 합이 아닙니다).")}


# ---- 슬라이스 16: 신규 상품 등록 (단가표發 편입 ②) ----
# 풀 안전 2중 방어: ai_candidate=false(추천 풀 제외) + review_required=true(주변기기 뷰까지 제외)
# — 등록이 S1 카운터·S2 추천 기검증 수치를 절대 바꾸지 않는다. sale_price는 NULL 유지
# (판매가 산정은 검수·가격정책 통과 후 — ERD §6). 등록 undo 없음(목업 스펙 부재).
# SKU 발번 = MAX+1(dev 단독 수용 — 동시 발번은 주문 advisory lock 전례로 이관).
class RegisterBody(BaseModel):
    name: str
    part_label: str            # 화면 분류 라벨(그래픽카드 등) — PART_TYPE_LABELS 역매핑
    # 아래 셋은 **단가표發 등록일 때만** 온다(슬라이스 54에서 선택으로 완화).
    # 상품 관리에서 직접 등록하면 공급처가 정해지지 않은 상태이고, 없는 사실을
    # 매핑·매입가 원장에 적을 수는 없다.
    supplier_id: int | None = None
    model_name: str | None = None      # 단가표 행 원문 — map model_key(상품명 입력과 별도)
    cost_price: int | None = None
    danawa_code: str | None = None
    maker: str | None = None


@router.post("/products")
def register_product(body: RegisterBody):
    from .admin_orders import _log  # kind 파라미터형 공용 로거
    # 라벨은 이제 1:1이다(공랭/수냉 분리) — setdefault로 뭉갤 중복이 없다.
    rev = {v: k for k, v in PART_TYPE_LABELS.items()}
    lab = body.part_label.strip()
    # 뭉뚱그린 옛 라벨('CPU쿨러')을 보내는 화면이 남아 있을 수 있어 공랭으로 받아준다.
    pt = rev.get(lab) or ("COOLER_CPU_AIR" if lab == "CPU쿨러" else None)
    if pt is None:
        raise HTTPException(400, f"알 수 없는 분류: {body.part_label}")
    if not body.name.strip():
        raise HTTPException(400, "상품명이 비어 있습니다")
    if body.supplier_id is not None and (body.model_name is None or body.cost_price is None):
        raise HTTPException(400, "공급처를 지정하면 모델명과 매입가가 함께 있어야 합니다")
    with engine.begin() as conn:
        if body.supplier_id is not None and conn.execute(
                text("SELECT 1 FROM suppliers WHERE supplier_id=:s"),
                {"s": body.supplier_id}).first() is None:
            raise HTTPException(404, "공급처가 없습니다")
        if body.danawa_code:
            dup = conn.execute(text(
                "SELECT sku FROM products WHERE danawa_code=:d"), {"d": body.danawa_code}).scalar()
            if dup:
                raise HTTPException(400, f"다나와 코드 중복 — 기존 상품 {dup}에 연결하세요")
        num = conn.execute(text(
            r"SELECT COALESCE(MAX(CAST(SUBSTRING(sku FROM 3) AS INTEGER)), 0) + 1"
            r" FROM products WHERE sku ~ '^P-[0-9]+$'")).scalar()
        sku, pc = f"P-{num}", int(f"2048{num}")
        conn.execute(text(
            "INSERT INTO products (product_code, sku, product_name, part_type, category_group,"
            " status, ai_candidate_yn, review_required_yn, purchase_price, stock_qty, danawa_code)"
            " VALUES (:pc, :sku, :n, :pt, 'core_part', '판매중', false, true, :cost, 0, :d)"),
            {"pc": pc, "sku": sku, "n": body.name.strip(), "pt": pt,
             "cost": body.cost_price, "d": body.danawa_code})
        if body.maker and body.maker.strip():
            conn.execute(text("UPDATE products SET maker=:m WHERE product_code=:pc"),
                         {"m": body.maker.strip()[:60], "pc": pc})
        conn.execute(text(
            "INSERT INTO product_specs (product_code, part_type) VALUES (:pc, :pt)"),
            {"pc": pc, "pt": pt})  # 검수 대상 필드는 확정 전 NULL 유지(ERD §3.5)
        if body.supplier_id is None:
            # 공급처 없는 직접 등록 — 매핑·매입가 원장은 만들지 않는다(없는 사실을 적지 않는다)
            _log(conn, "product_register", sku,
                 {"product_code": pc, "sku": sku, "part_type": pt,
                  "supplier_id": None, "source": "manual"}, kind="product")
            return {"ok": True, "sku": sku, "product_code": pc,
                    "note": ("등록됐습니다 — 검수 대기 상태이고 추천 풀에는 들어가지 않습니다."
                             " 사양 검수와 판매가 산정을 통과해야 추천에 쓰입니다.")}
        map_id = conn.execute(text(
            "INSERT INTO supplier_product_map (supplier_id, model_key, product_code, match_method, confirmed_by, confirmed_at)"
            " VALUES (:s, :k, :pc, 'manual', :op, now())"
            " ON CONFLICT (supplier_id, model_key) DO NOTHING RETURNING map_id"),
            {"s": body.supplier_id, "k": body.model_name, "pc": pc, "op": 1}).scalar()
        if map_id is None:
            raise HTTPException(409, "이미 연결된 단가표 모델입니다")
        srow = conn.execute(text(
            "SELECT r.supply_state, f.file_id FROM supplier_price_rows r"
            " JOIN supplier_price_files f USING (file_id)"
            " WHERE f.supplier_id=:s AND r.model_name=:k"
            " ORDER BY f.received_at DESC LIMIT 1"),
            {"s": body.supplier_id, "k": body.model_name}).first()
        conn.execute(text(
            "INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state, src_file_id)"
            " VALUES (:pc, :s, :c, :st, :f)"),  # 신규 상품 — 재판정(_reprice) 불요, 기존 가격 무영향
            {"pc": pc, "s": body.supplier_id, "c": body.cost_price,
             "st": srow[0] if srow else "가능", "f": srow[1] if srow else None})
        _log(conn, "product_register", sku,
             {"product_code": pc, "sku": sku, "part_type": pt, "supplier_id": body.supplier_id,
              "model_key": body.model_name, "cost_price": body.cost_price}, kind="product")
        return {"ok": True, "sku": sku, "product_code": pc}


# ---- 슬라이스 53: 단건 상세 조회·수정 (ADM-PRD-040) ----
# **왜 필요했나.** 카탈로그 22,838건을 운영하는데 상품 하나를 손으로 고칠 방법이 없었다.
# 가격이 틀리거나 판매를 멈추려면 CSV를 통째로 다시 올려야 했다(검수 화면은 사양만 고친다).
#
# **수정한 값은 잠근다.** locked_fields에 등록하지 않으면 다음 적재가 그대로 덮어써
# 어제 고친 가격이 오늘 되돌아간다(A-16의 짝). 적재는 이미 이 잠금을 존중한다.
#
# 되돌리기는 삭제가 아니라 **역방향 값 복원**이다(원장 원칙) — before 스냅샷을 로그에 남기고
# undo가 그것을 되돌린다. 역참조 키는 규약대로 `ref_log_id`.

# 화면에서 고칠 수 있는 필드 -> (DB 컬럼, 파서). 여기 없는 것은 화면이 못 바꾼다.
EDITABLE = {
    "name": ("product_name", lambda v: (str(v).strip() or None)),
    "maker": ("maker", lambda v: (str(v).strip() or None)),
    "sale_price": ("sale_price", lambda v: None if v in ("", None) else int(v)),
    "purchase_price": ("purchase_price", lambda v: None if v in ("", None) else int(v)),
    "stock_qty": ("stock_qty", lambda v: int(v)),
    "status": ("status", lambda v: str(v).strip()),
}
STATUS_OK = ("판매중", "품절", "단종", "삭제대기")
# 가격·재고는 정본 수치다 — 음수나 터무니없는 값이 들어가면 견적이 통째로 흔들린다
LIMIT = {"sale_price": (0, 100_000_000), "purchase_price": (0, 100_000_000),
         "stock_qty": (0, 100_000)}


@router.get("/product-meta")
def product_meta():
    """등록·수정 화면이 쓰는 선택지 — 화면에 하드코딩하면 서버가 아는 것과 갈린다.

    실제로 등록 화면의 분류 셀렉트에 3종만 있어서 파워·케이스·메모리를 등록할 수 없었다
    (슬라이스 54).
    """
    core = {"CPU", "MB", "RAM", "GPU", "POWER", "CASE", "SSD", "HDD",
            "COOLER_CPU_AIR", "COOLER_CPU_AIO"}
    return {
        "part_labels": [{"part_type": k, "label": v}
                        for k, v in PART_TYPE_LABELS.items() if k in core],
        "peripheral_labels": [{"part_type": k, "label": v}
                              for k, v in PART_TYPE_LABELS.items()
                              if k not in core and k != "ETC"],
        "status_options": list(STATUS_OK),
        "editable": sorted(EDITABLE),
    }


@router.get("/products/{product_code}")
def get_product(product_code: int):
    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT p.product_code, p.sku, p.product_name, p.maker, p.model_name, p.part_type,"
            " p.category_group, p.status, p.ai_candidate_yn, p.review_required_yn,"
            " p.purchase_price, p.sale_price, p.market_price, p.stock_qty, p.supplier,"
            " p.danawa_code, p.data_origin, p.locked_fields, p.spec_source_text,"
            " p.created_at, p.updated_at, to_jsonb(ps) AS specs"
            " FROM products p LEFT JOIN product_specs ps USING (product_code)"
            " WHERE p.product_code = :pc"), {"pc": product_code}).mappings().first()
        if r is None:
            raise HTTPException(404, "상품이 없습니다")
        pending = conn.execute(text(
            "SELECT count(*) FROM product_reviews WHERE product_code=:pc"
            " AND review_status='대기'"), {"pc": product_code}).scalar_one()
        in_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty > 0"), {"pc": product_code}).first() is not None
    done, total = spec_progress(r["part_type"], r["specs"])
    locked = list(r["locked_fields"] or [])
    if in_pool:
        verdict = "추천 가능 재고에 있습니다."
    elif pending:
        verdict = f"사양 검수가 남아 추천에서 빠져 있습니다(대기 {pending}건)."
    elif r["status"] != "판매중":
        # 상태로 빠진 것을 "조건 미달"로 뭉뚱그리면 운영자가 원인을 못 찾는다
        verdict = f"판매 상태가 '{r['status']}'이라 추천에서 빠져 있습니다."
    elif (r["stock_qty"] or 0) <= 0:
        verdict = "재고가 없어 추천에서 빠져 있습니다."
    elif r["sale_price"] is None:
        verdict = "판매가가 없어 추천에서 빠져 있습니다."
    elif r["category_group"] != "core_part":
        verdict = "부품 분류가 아니라 추천 대상이 아닙니다."
    elif r["specs"] is None:
        verdict = "사양 정보가 없어 추천에서 빠져 있습니다(적재에서 부품 종류를 못 정함)."
    else:
        verdict = "추천 조건을 아직 만족하지 않습니다."
    return {
        "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
        "maker": r["maker"], "model_name": r["model_name"],
        "part_type": r["part_type"], "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
        "category_group": r["category_group"], "status": r["status"],
        "purchase_price": r["purchase_price"], "sale_price": r["sale_price"],
        "market_price": r["market_price"], "stock_qty": r["stock_qty"],
        "supplier": r["supplier"], "danawa_code": r["danawa_code"],
        "origin": r["data_origin"], "locked_fields": locked,
        "spec_source_text": r["spec_source_text"],
        "specs": r["specs"], "spec_done": done, "spec_total": total,
        "spec_row_missing": r["specs"] is None,
        "review_pending": pending, "in_pool": in_pool,
        "editable": sorted(EDITABLE), "status_options": list(STATUS_OK),
        "created_at": r["created_at"].isoformat(),
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        # 화면이 그대로 쓰는 한 문장 — 왜 추천에 들어가고 못 들어가는지
        "verdict": verdict,
    }


class PatchBody(BaseModel):
    changes: dict           # {필드: 값} — EDITABLE에 있는 것만
    lock: bool = True       # 고친 값을 적재가 못 덮게 잠근다(기본 켬)


@router.patch("/products/{product_code}")
def patch_product(product_code: int, body: PatchBody):
    import json as _json

    from .admin_orders import _log

    changes = {k: v for k, v in (body.changes or {}).items() if k in EDITABLE}
    unknown = [k for k in (body.changes or {}) if k not in EDITABLE]
    if unknown:
        raise HTTPException(400, "수정할 수 없는 필드: " + ", ".join(unknown))
    if not changes:
        raise HTTPException(400, "변경할 내용이 없습니다")

    parsed = {}
    for k, raw in changes.items():
        col, conv = EDITABLE[k]
        try:
            v = conv(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{k} 값 형식이 올바르지 않습니다: {raw!r}")
        if k == "status" and v not in STATUS_OK:
            raise HTTPException(400, f"알 수 없는 상태: {v}")
        if k in LIMIT and v is not None:
            lo, hi = LIMIT[k]
            if not lo <= v <= hi:
                raise HTTPException(400, f"{k}={v} 는 허용 범위({lo}~{hi}) 밖입니다")
        if k == "name" and v is None:
            raise HTTPException(400, "상품명은 비울 수 없습니다")
        parsed[k] = (col, v)

    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT product_code, sku, product_name, maker, purchase_price, sale_price,"
            " stock_qty, status, locked_fields FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        if cur is None:
            raise HTTPException(404, "상품이 없습니다")

        before, sets, params = {}, [], {"pc": product_code}
        for k, (col, v) in parsed.items():
            before[k] = cur[col]
            if before[k] == v:            # 같은 값이면 원장을 더럽히지 않는다
                continue
            sets.append(f"{col} = :{k}")
            params[k] = v
        after = {k: parsed[k][1] for k in parsed if k in params}
        if not after:
            return {"ok": True, "changed": 0, "undo_id": None,
                    "note": "값이 같아 바뀐 것이 없습니다"}

        locked = list(cur["locked_fields"] or [])
        if body.lock:
            for k in after:
                col = EDITABLE[k][0]
                if col not in locked:
                    locked.append(col)
        sets.append("locked_fields = CAST(:lf AS JSONB)")
        sets.append("updated_at = now()")
        params["lf"] = _json.dumps(locked, ensure_ascii=False)
        conn.execute(text("UPDATE products SET " + ", ".join(sets)
                          + " WHERE product_code=:pc"), params)

        log_id = _log(conn, "product_edit", cur["sku"],
                      {"product_code": product_code, "sku": cur["sku"],
                       "changes": {k: {"from": before[k], "to": after[k]} for k in after},
                       "before": {"locked_fields": list(cur["locked_fields"] or [])},
                       "locked": body.lock}, kind="product")
        in_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty > 0"), {"pc": product_code}).first() is not None

    return {"ok": True, "changed": len(after), "fields": sorted(after),
            "locked_fields": locked, "in_pool": in_pool, "undo_id": log_id,
            "note": ("수정한 필드는 잠겼습니다 — 다음 적재가 덮어쓰지 않습니다."
                     if body.lock else "잠그지 않았습니다 — 다음 적재가 덮어쓸 수 있습니다.")}


@router.post("/products/undo/{log_id}")
def undo_product_edit(log_id: int):
    """수정 되돌리기 — 삭제가 아니라 이전 값으로의 역방향 복원(원장 원칙)."""
    import json as _json

    from .admin_orders import _log

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if row is None or row["action"] != "product_edit":
            raise HTTPException(404, "되돌릴 수정 기록이 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE action='product_edit_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
            {"i": log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 수정입니다")

        d = row["detail"] or {}
        pc = d.get("product_code")
        chg = d.get("changes") or {}
        sets, params = [], {"pc": pc}
        for k, fromto in chg.items():
            if k not in EDITABLE:
                continue
            sets.append(EDITABLE[k][0] + " = :" + k)
            params[k] = fromto.get("from")
        if not sets:
            raise HTTPException(400, "되돌릴 변경 내용이 없습니다")
        restored = len(sets)
        # 잠금도 수정 전 상태로 되돌린다 — 되돌렸는데 잠금만 남으면 적재가 영영 못 채운다
        sets.append("locked_fields = CAST(:lf AS JSONB)")
        params["lf"] = _json.dumps((d.get("before") or {}).get("locked_fields") or [],
                                   ensure_ascii=False)
        sets.append("updated_at = now()")
        conn.execute(text("UPDATE products SET " + ", ".join(sets)
                          + " WHERE product_code=:pc"), params)
        _log(conn, "product_edit_undo", str(d.get("sku") or pc),
             {"ref_log_id": log_id, "product_code": pc,
              "restored": {k: v.get("from") for k, v in chg.items()}}, kind="product")
    return {"ok": True, "restored": restored}
