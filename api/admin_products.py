"""ADM-PRD-010 관리자 상품 목록 — 읽기 1본.

응답 계약(목업 products.html과 합의):
  { items: [{product_code, sku, name, cat, maker, spec_done, spec_total,
             stock, supplier_count, sale_price, status_key}],
    kpis: {total, ok, review, oos, price} }   # 상호배타 버킷 합 (목업의 독립 카운트와 다름)
"""
from fastapi import APIRouter
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

_QUERY = text("""
    SELECT p.product_code, p.sku, p.product_name, p.maker, p.part_type,
           p.status, p.review_required_yn, p.sale_price, p.stock_qty,
           COALESCE(sp.cnt, 0) AS supplier_count,
           to_jsonb(ps) AS specs
    FROM products p
    LEFT JOIN product_specs ps USING (product_code)
    LEFT JOIN (SELECT product_code, COUNT(*) AS cnt
               FROM product_supplier_prices GROUP BY product_code) sp USING (product_code)
    ORDER BY p.product_code
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
def list_products():  # def(비동기 아님) — psycopg2 동기 드라이버, FastAPI 스레드풀 실행
    with engine.connect() as conn:
        rows = conn.execute(_QUERY).all()

    items = []
    kpis = {"total": 0, "ok": 0, "review": 0, "oos": 0, "price": 0}
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
            "stock": r.stock_qty,
            "supplier_count": r.supplier_count,
            "sale_price": r.sale_price,
            "status_key": status_key,
        })
        kpis["total"] += 1
        kpis[status_key] += 1
    return {"items": items, "kpis": kpis}
