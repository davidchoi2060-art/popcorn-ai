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
    "COOLER_CPU_AIR": "CPU쿨러", "COOLER_CPU_AIO": "CPU쿨러",
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
    "CASE": ["form_factor", "gpu_max_mm", "cooler_height_mm"],
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
    supplier_id: int
    model_name: str            # 단가표 행 원문 — map model_key(상품명 입력과 별도)
    cost_price: int
    danawa_code: str | None = None


@router.post("/products")
def register_product(body: RegisterBody):
    from .admin_orders import _log  # kind 파라미터형 공용 로거
    rev = {}
    for k, v in PART_TYPE_LABELS.items():
        rev.setdefault(v, k)       # CPU쿨러 중복 라벨은 선순위(COOLER_CPU_AIR) 채택
    pt = rev.get(body.part_label.strip())
    if pt is None:
        raise HTTPException(400, f"알 수 없는 분류: {body.part_label}")
    if not body.name.strip():
        raise HTTPException(400, "상품명이 비어 있습니다")
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM suppliers WHERE supplier_id=:s"),
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
        conn.execute(text(
            "INSERT INTO product_specs (product_code, part_type) VALUES (:pc, :pt)"),
            {"pc": pc, "pt": pt})  # 검수 대상 필드는 확정 전 NULL 유지(ERD §3.5)
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
