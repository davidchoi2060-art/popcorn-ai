"""ADM-PRD-010 관리자 상품 목록 — 읽기 1본.

응답 계약(목업 products.html과 합의):
  { items: [{product_code, sku, name, cat, maker, spec_done, spec_total,
             stock, supplier_count, sale_price, status_key}],
    kpis: {total, ok, review, oos, price} }   # 상호배타 버킷 합 (목업의 독립 카운트와 다름)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .timeutil import iso
from .auth import current_operator_id
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
    # 쿨러는 소켓을 **목록**으로 가진다(하나의 쿨러가 여러 소켓을 지원한다).
    # 화면만 `socket`을 보고 있어 socket_list가 채워진 쿨러 33건을 미확인으로 셌고,
    # 추천 뷰·적재·호환 규칙은 모두 socket_list를 쓴다 — 정본에 맞춘다(슬라이스 56).
    "COOLER_CPU_AIR": ["socket_list", "cooler_height_mm", "cooler_tdp"],
    "COOLER_CPU_AIO": ["socket_list", "cooler_tdp"],
    # 주변기기에는 필수를 걸지 않는다(슬라이스 84). 견적 8슬롯 밖이고, 제안을 그리는
    # _companion()이 이미 NULL을 견딘다("없는 값은 지어내지 않고 그 자리를 비운다").
    # 필수로 두면 모니터 585개 중 556개가 근거 없이 제안에서 빠졌다.
    # 이건 폴백 상수다 — 정본은 spec_field_defs 메타이고, 둘이 어긋나면 회귀가 잡는다.
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
      AND (:maker = '' OR p.maker = :maker)
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


def required_fields(part_type: str) -> list:
    """필수 사양 — **메타(spec_field_defs)가 단일 원천**이다(슬라이스 57).

    상수를 그대로 쓰면 화면에서 '필수로 지정'해도 게이트가 모른다 — 아무 효과 없는
    버튼이 된다. 메타를 못 읽는 상황(초기화 전·DB 단절)에서만 상수로 되돌아간다.
    """
    try:
        from . import spec_fields as SF
        got = SF.required_for(part_type)
        if got:
            return got
    except Exception:                                    # noqa: BLE001
        pass
    return REQUIRED_SPEC_FIELDS.get(part_type, [])


def spec_progress(part_type: str, specs: dict | None) -> tuple[int, int]:
    fields = required_fields(part_type)
    if not fields:
        return 0, 0
    if specs is None:
        return 0, len(fields)
    done = sum(1 for f in fields if specs.get(f) is not None)
    return done, len(fields)


@router.get("/products")
def list_products(q: str = "", part_type: str = "", status: str = "", origin: str = "",
                  maker: str = "", page: int = 1, size: int = 100):
    # def(비동기 아님) — psycopg2 동기 드라이버, FastAPI 스레드풀 실행
    size = max(1, min(size, 500))     # 상한 — 브라우저가 버티는 범위
    page = max(1, page)
    # maker는 **서버에서 거른다**(슬라이스 66). 화면이 현재 페이지 안에서만 걸러
    # 22,841건 중 100건에만 필터가 먹었다 — 운영자는 "그 제조사 상품이 없다"고 읽는다.
    p = {"q": q.strip(), "part_type": part_type.strip(), "status": status.strip(),
         "origin": origin.strip(), "maker": maker.strip(),
         "size": size, "offset": (page - 1) * size}
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
    # 닮은 상품이 있어도 "다른 상품이다"라고 확인했으면 그대로 등록한다(슬라이스 68)
    confirm_similar: bool = False


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
        # 이름이 거의 같은 상품이 이미 있으면 **먼저 묻는다**(슬라이스 68).
        # 실수로 같은 상품을 두 번 만들면 재고·매입가가 갈라져 어느 쪽이 맞는지 알 수 없다.
        # 막지는 않는다 — 운영자가 "다른 상품"이라고 하면 그대로 등록한다.
        if not body.confirm_similar:
            from . import dedupe
            similar = dedupe.find_similar(conn, body.name.strip(), pt)
            if similar:
                raise HTTPException(409, {
                    "error": "similar_products",
                    "message": "이름이 거의 같은 상품이 이미 있습니다 — 확인해 주세요",
                    "items": similar})
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
    # 목록 필터와 상세 셀렉트가 **같은 원천**을 봐야 한다(슬라이스 66).
    # 목록은 지금까지 '현재 페이지에 로드된 행'에서 분류·제조사를 뽑아 썼다.
    # 서버 페이지네이션이라 한 페이지에 없는 값은 필터에 아예 안 나왔고,
    # 그래서 상세에서 고른 분류가 목록 필터엔 없는 일이 생겼다.
    with engine.connect() as conn:
        makers = [r[0] for r in conn.execute(text(
            "SELECT maker FROM products WHERE maker IS NOT NULL AND maker <> ''"
            " GROUP BY maker ORDER BY count(*) DESC, maker"))]
        used = [r[0] for r in conn.execute(text(
            "SELECT part_type FROM products WHERE part_type IS NOT NULL"
            " GROUP BY part_type ORDER BY count(*) DESC"))]
    return {
        "part_labels": [{"part_type": k, "label": v}
                        for k, v in PART_TYPE_LABELS.items() if k in core],
        "peripheral_labels": [{"part_type": k, "label": v}
                              for k, v in PART_TYPE_LABELS.items()
                              if k not in core and k != "ETC"],
        # 목록 필터용 — 실제로 상품이 있는 분류만(빈 분류를 고르면 결과가 0이라 혼란스럽다)
        "used_parts": [{"part_type": k, "label": PART_TYPE_LABELS.get(k, k)} for k in used],
        "makers": makers,
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
        # 공급처별 매입가 — 화면 표는 지금까지 마크업 하드코딩이었다(용산도매A 352,000 등).
        # 신규 등록 화면에도 그 값이 그대로 떠서 **없는 공급처가 있는 것처럼** 보였다.
        sups = [dict(x) for x in conn.execute(text(
            "SELECT sp.psp_id, sp.supplier_id, s.name AS supplier, sp.cost_price,"
            " sp.supply_state, sp.updated_at"
            " FROM product_supplier_prices sp JOIN suppliers s USING (supplier_id)"
            " WHERE sp.product_code = :pc"
            " ORDER BY sp.cost_price NULLS LAST, sp.psp_id"), {"pc": product_code}).mappings()]
    done, total = spec_progress(r["part_type"], r["specs"])
    locked = list(r["locked_fields"] or [])

    # ── 게이트 체크리스트 (슬라이스 95) ─────────────────────────────
    # 왜 필요했나: `verdict`는 **막힌 이유를 하나씩만** 말한다(elif 사슬).
    # 사양·판매가·재고가 동시에 비어 있으면, 사양을 채우고 돌아왔을 때 "판매가가 없어"가
    # 새로 뜨고 그걸 고치면 또 "재고가 없어"가 뜬다. 두더지잡기다 — 운영자는 몇 번
    # 왕복해야 끝나는지 알 수 없다. 그래서 **남은 것을 한 번에 전부** 보여준다.
    #
    # 조건은 추천 뷰(`v_recommendation_candidates`)의 실제 WHERE와 한 줄씩 대응한다.
    # 뷰를 고치면 여기도 고쳐야 한다 — 어긋나면 화면이 "다 됐다"고 말하는데 후보가
    # 아닌 상태가 된다(슬라이스 46과 같은 부류의 사고).
    gate = [
        {"key": "category", "label": "부품 분류",
         "ok": r["category_group"] == "core_part" and r["part_type"] in PART_TYPE_LABELS,
         "value": PART_TYPE_LABELS.get(r["part_type"], r["part_type"] or "미분류"),
         "fix": "상세에서 분류를 고칩니다 — 바꾸기 전에 영향을 먼저 보여줍니다",
         "fix_screen": None},
        {"key": "spec_row", "label": "사양 정보",
         "ok": r["specs"] is not None,
         "value": "있음" if r["specs"] is not None else "없음(적재가 부품 종류를 못 정함)",
         "fix": "분류를 바로잡으면 사양 자리가 생깁니다",
         "fix_screen": None},
        {"key": "review", "label": "필수 사양",
         "ok": pending == 0 and bool(r["ai_candidate_yn"]) and not r["review_required_yn"],
         "value": (f"{done}/{total} 항목"
                   + (f" · 검수 대기 {pending}건" if pending else "")),
         "fix": "이 화면에서 사양 값을 넣으면 검수도 함께 해소됩니다",
         "fix_screen": "review-queue.html"},
        {"key": "price", "label": "판매가",
         "ok": r["sale_price"] is not None,
         "value": (f"{r['sale_price']:,}원" if r["sale_price"] is not None else "없음"),
         "fix": "아래 [공급처별 매입가]에 매입가를 넣으면 산정됩니다",
         "fix_screen": "price-import.html"},
        {"key": "status", "label": "판매 상태",
         "ok": r["status"] == "판매중",
         "value": r["status"],
         "fix": "상세에서 '판매중'으로 바꿉니다",
         "fix_screen": None},
        {"key": "stock", "label": "재고",
         "ok": (r["stock_qty"] or 0) > 0,
         "value": f"{r['stock_qty'] or 0}개",
         "fix": "재고 입고에서 수량을 넣습니다",
         "fix_screen": "stock-inbound.html"},
    ]
    blocked = [g for g in gate if not g["ok"]]

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
        "suppliers": [{"psp_id": s["psp_id"], "supplier_id": s["supplier_id"],
                       "supplier": s["supplier"], "cost_price": s["cost_price"],
                       "state": s["supply_state"], "at": iso(s["updated_at"])}
                      for s in sups],
        "editable": sorted(EDITABLE), "status_options": list(STATUS_OK),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]) if r["updated_at"] else None,
        # 화면이 그대로 쓰는 한 문장 — 왜 추천에 들어가고 못 들어가는지.
        # 하위호환으로 남긴다(회귀·기존 화면이 쓴다). 다만 **하나씩만** 말하므로,
        # 운영자가 실제로 봐야 하는 것은 아래 `gate`다.
        "verdict": verdict,
        # 남은 것을 한 번에 전부 — 왕복을 없앤다(슬라이스 95)
        "gate": gate,
        "gate_blocked": [g["key"] for g in blocked],
        # **순서가 의미를 갖는다.** 분류를 고치면 사양 자리가 생기고 검수가 다시 판정된다.
        # 아래에서부터 고치면(재고 먼저) 헛수고가 된다 — 첫 번째를 지목한다.
        "gate_first": None if not blocked else {
            "key": blocked[0]["key"], "label": blocked[0]["label"],
            "fix": blocked[0]["fix"], "fix_screen": blocked[0]["fix_screen"]},
        "gate_note": ("추천 가능 재고에 있습니다 — 견적에 나갈 수 있습니다"
                      if not blocked else
                      f"추천 후보가 되려면 {len(blocked)}가지 남았습니다 — "
                      + " · ".join(g["label"] for g in blocked)),
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

        # ── 재고를 고치면 원장에 남긴다 (슬라이스 97) ──────────────────
        # 여기서 stock_qty를 바꿀 수 있는데 stock_movements에 아무것도 남지 않았다.
        # 재고 입고(ADM-SRC-020)는 원장 계약대로 남기는데 이 경로만 건너뛰었다.
        #
        # 실제 사용은 0건이었지만 **등록 직후 재고를 넣는 가장 자연스러운 경로가 여기다** —
        # 상세에 칸이 있으니 굳이 다른 화면으로 갈 이유가 없다. 쓰기 시작하면
        # 슬라이스 69가 경고한 상태가 된다: "수량만 고치면 어디서 왔는지 알 수 없다".
        #
        # 칸을 지우는 대신 원장을 남기는 쪽을 택했다 — 지우면 등록 직후 또 다른 화면으로
        # 보내야 해서 편의성이 나빠진다. 종류는 `adjust`다(입고가 아니라 사람의 보정이므로).
        if "stock_qty" in after:
            delta = int(after["stock_qty"]) - int(before["stock_qty"] or 0)
            if delta:
                conn.execute(text(
                    "INSERT INTO stock_movements"
                    " (product_code, movement_type, qty_delta, ref_kind, ref_id)"
                    " VALUES (:pc, 'adjust', :q, 'manual', :ref)"),
                    {"pc": product_code, "q": delta, "ref": log_id})

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
        # 재고를 되돌리면 원장도 **역방향 행**으로 되돌린다(슬라이스 97).
        # 원래 행을 지우면 "재고가 늘었다가 줄었다"는 사실이 사라진다 — 원장 규약대로
        # 상쇄 행을 남긴다. 되돌림 로그를 먼저 남길 수 없으므로 ref_id는 원본 log_id다.
        if "stock_qty" in chg:
            back = int(chg["stock_qty"].get("from") or 0) - int(chg["stock_qty"].get("to") or 0)
            if back:
                conn.execute(text(
                    "INSERT INTO stock_movements"
                    " (product_code, movement_type, qty_delta, ref_kind, ref_id)"
                    " VALUES (:pc, 'adjust', :q, 'manual', :ref)"),
                    {"pc": pc, "q": back, "ref": log_id})
        _log(conn, "product_edit_undo", str(d.get("sku") or pc),
             {"ref_log_id": log_id, "product_code": pc,
              "restored": {k: v.get("from") for k, v in chg.items()}}, kind="product")
    return {"ok": True, "restored": restored}


# ---- 슬라이스 57: 상품별 사양 값 입력 ----
# 사양 항목을 화면에서 만들 수 있게 됐지만(슬라이스 56) **값을 넣을 곳이 없었다.**
# 상세는 사양을 읽기만 하고, 검수 큐는 검수 행이 있는 필드만 다룬다 — 새로 만든 항목에는
# 검수 행이 없으므로 영영 비어 있게 된다.
#
# 검수 승인과 같은 규칙을 따른다: 값 반영 → **고친 필드 잠금**(다음 적재가 못 덮게) →
# 그 필드의 검수 대기 행 해소 → 필수가 다 차면 게이트 통과(추천 후보 진입).


class SpecBody(BaseModel):
    values: dict            # {field_key: value} — 그 part_type에 유효한 필드만
    lock: bool = True


@router.patch("/products/{product_code}/specs")
def patch_product_specs(product_code: int, body: SpecBody):
    import json as _json

    from . import spec_fields as SF
    from .admin_orders import _log

    with engine.begin() as conn:
        prod = conn.execute(text(
            "SELECT product_code, sku, part_type, category_group, review_required_yn,"
            " ai_candidate_yn, locked_fields FROM products"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).mappings().first()
        if prod is None:
            raise HTTPException(404, "상품이 없습니다")
        pt = prod["part_type"]

        # 이 부품 종류에서 쓰는 항목만 받는다. 다른 종류 전용 필드를 넣으면
        # 값은 들어가도 아무도 읽지 않는 죽은 데이터가 된다.
        allowed = {f["field_key"]: f for f in SF.fields_for(pt)}
        unknown = [k for k in (body.values or {}) if k not in allowed]
        if unknown:
            raise HTTPException(400, f"{pt}에서 쓰지 않는 사양입니다: " + ", ".join(unknown))
        if not body.values:
            raise HTTPException(400, "입력한 사양이 없습니다")

        cast = SF.field_cast()
        jsonf = SF.json_cols()
        cur = conn.execute(text(
            "SELECT to_jsonb(ps) AS s FROM product_specs ps"
            " WHERE product_code=:pc FOR UPDATE"), {"pc": product_code}).scalar()
        if cur is None:
            conn.execute(text(
                "INSERT INTO product_specs (product_code, part_type) VALUES (:pc, :pt)"),
                {"pc": product_code, "pt": pt})
            cur = {}

        before, sets, params = {}, [], {"pc": product_code}
        for k, raw in body.values.items():
            v = raw
            if isinstance(v, str) and not v.strip():
                v = None                      # 빈 문자열은 '지운다'가 아니라 '입력 안 함'
            if v is not None and k in jsonf and not isinstance(v, str):
                v = _json.dumps(v, ensure_ascii=False)
            if cur.get(k) == v:
                continue
            before[k] = cur.get(k)
            sets.append(f"{k} = CAST(:{k} AS {cast.get(k, 'VARCHAR')})")
            params[k] = v
        if not sets:
            return {"ok": True, "changed": 0, "undo_id": None,
                    "note": "값이 같아 바뀐 것이 없습니다"}

        try:
            conn.execute(text(
                "UPDATE product_specs SET " + ", ".join(sets)
                + ", updated_at = now() WHERE product_code = :pc"), params)
        except DBAPIError:
            raise HTTPException(400, "값 형식이 올바르지 않습니다 — 자료형을 확인하세요")

        # 사람이 넣은 값은 잠근다(A-16의 짝) — 안 그러면 다음 적재가 덮는다
        locked = list(prod["locked_fields"] or [])
        if body.lock:
            for k in params:
                if k != "pc" and k not in locked:
                    locked.append(k)
            conn.execute(text(
                "UPDATE products SET locked_fields = CAST(:lf AS JSONB), updated_at = now()"
                " WHERE product_code = :pc"),
                {"lf": _json.dumps(locked, ensure_ascii=False), "pc": product_code})

        # 채운 필드의 검수 대기 행 해소 — 안 하면 큐가 실제 할 일보다 부풀어 보인다
        filled = [k for k in params if k != "pc" and params[k] is not None]
        closed = 0
        if filled:
            r = conn.execute(text(
                "UPDATE product_reviews SET review_status='처리', reviewed_by=:op,"
                " reviewed_at=now(),"
                " detail = detail || ' [운영자 직접 입력으로 해소]'"
                " WHERE product_code=:pc AND review_status='대기'"
                "   AND field_name = ANY(:f)"),
                {"pc": product_code, "f": filled, "op": current_operator_id()})
            closed = r.rowcount

        # 게이트 ② — 필수가 다 차고 대기가 없으면 추천 후보로 승격
        now = conn.execute(text(
            "SELECT to_jsonb(ps) AS s FROM product_specs ps WHERE product_code=:pc"),
            {"pc": product_code}).scalar() or {}
        need = required_fields(pt)
        all_filled = bool(need) and all(now.get(f) is not None for f in need)
        remain = conn.execute(text(
            "SELECT count(*) FROM product_reviews WHERE product_code=:pc"
            " AND review_status IN ('대기','검수중')"), {"pc": product_code}).scalar_one()
        promoted = False
        if all_filled and remain == 0 and prod["category_group"] == "core_part":
            conn.execute(text(
                "UPDATE products SET review_required_yn=false, ai_candidate_yn=true,"
                " updated_at=now() WHERE product_code=:pc"), {"pc": product_code})
            conn.execute(text(
                "UPDATE product_specs SET verified_yn=true, updated_at=now()"
                " WHERE product_code=:pc"), {"pc": product_code})
            promoted = not prod["ai_candidate_yn"]

        log_id = _log(conn, "spec_edit", prod["sku"],
                      {"product_code": product_code, "sku": prod["sku"],
                       "changes": {k: {"from": before.get(k), "to": params[k]}
                                   for k in params if k != "pc"},
                       "before": {"locked_fields": list(prod["locked_fields"] or []),
                                  "review_required_yn": prod["review_required_yn"],
                                  "ai_candidate_yn": prod["ai_candidate_yn"]},
                       "locked": body.lock}, kind="product")
        in_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty > 0"), {"pc": product_code}).first() is not None

    n = len([k for k in params if k != "pc"])
    return {"ok": True, "changed": n, "fields": sorted(k for k in params if k != "pc"),
            "reviews_closed": closed, "promoted": promoted, "in_pool": in_pool,
            "locked_fields": locked, "undo_id": log_id,
            "note": (f"{n}개 사양을 저장했습니다."
                     + (f" 검수 대기 {closed}건이 해소됐습니다." if closed else "")
                     + (" 필수 사양이 모두 채워져 추천 후보에 올랐습니다." if promoted else "")
                     + (" 수정한 사양은 잠겼습니다 — 다음 적재가 덮어쓰지 않습니다."
                        if body.lock else ""))}


@router.post("/products/specs/undo/{log_id}")
def undo_spec_edit(log_id: int):
    """사양 입력 되돌리기 — 값·잠금·게이트 상태를 함께 되돌린다."""
    import json as _json

    from .admin_orders import _log

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if row is None or row["action"] != "spec_edit":
            raise HTTPException(404, "되돌릴 사양 입력 기록이 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE action='spec_edit_undo' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
            {"i": log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 입력입니다")

        from . import spec_fields as SF
        cast = SF.field_cast()
        d = row["detail"] or {}
        pc = d.get("product_code")
        chg = d.get("changes") or {}
        sets, params = [], {"pc": pc}
        for k, ft in chg.items():
            if k not in cast:
                continue
            sets.append(f"{k} = CAST(:{k} AS {cast[k]})")
            params[k] = ft.get("from")
        if sets:
            conn.execute(text("UPDATE product_specs SET " + ", ".join(sets)
                              + ", updated_at = now() WHERE product_code = :pc"), params)
        b = d.get("before") or {}
        conn.execute(text(
            "UPDATE products SET locked_fields = CAST(:lf AS JSONB),"
            " review_required_yn = :rr, ai_candidate_yn = :ac, updated_at = now()"
            " WHERE product_code = :pc"),
            {"lf": _json.dumps(b.get("locked_fields") or [], ensure_ascii=False),
             "rr": b.get("review_required_yn", True),
             "ac": b.get("ai_candidate_yn", False), "pc": pc})
        _log(conn, "spec_edit_undo", str(d.get("sku") or pc),
             {"ref_log_id": log_id, "product_code": pc,
              "restored": {k: v.get("from") for k, v in chg.items()}}, kind="product")
    return {"ok": True, "restored": len(sets)}


# ---- 슬라이스 66: 공급처별 매입가 ----
# 화면의 공급처 표가 마크업 하드코딩이었다(용산도매A 352,000 · 다나와직송B 361,000).
# **신규 등록 화면에도 그 값이 그대로 떠서** 없는 공급처가 있는 것처럼 보였고,
# [+ 공급처 추가]는 아무 일도 하지 않았다.
#
# 매입가는 단가표 반영(price-import)이 주 경로다. 여기서는 **단건 보정**만 한다 —
# 운영자가 전화로 받은 값을 그 자리에 넣는 용도다. 출처를 남겨 나중에 구분한다.


# supply_state는 NOT NULL이고 실데이터는 '가능'/'품절' 둘뿐이다.
# 화면이 안 보내면 '가능'으로 둔다 — 매입가를 넣는다는 건 살 수 있다는 뜻이다.
SUPPLY_STATES = ("가능", "품절")


class SupplierPriceBody(BaseModel):
    supplier_id: int
    cost_price: int | None = None
    state: str | None = None


# GET /suppliers는 `api/admin_suppliers.py`로 옮겼다(슬라이스 93).
# 같은 경로를 두 곳에서 정의하면 먼저 등록된 쪽이 이겨서, 고친 쪽이 안 먹는다.


@router.post("/products/{product_code}/suppliers")
def upsert_supplier_price(product_code: int, body: SupplierPriceBody):
    from .admin_orders import _log

    if body.cost_price is not None and body.cost_price < 0:
        raise HTTPException(400, "매입가는 0원 이상이어야 합니다")
    if body.state is not None and body.state not in SUPPLY_STATES:
        raise HTTPException(400, "공급 상태는 " + " · ".join(SUPPLY_STATES) + " 중 하나입니다")
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM products WHERE product_code=:pc"),
                        {"pc": product_code}).first() is None:
            raise HTTPException(404, "상품이 없습니다")
        sup = conn.execute(text("SELECT name FROM suppliers WHERE supplier_id=:s"),
                           {"s": body.supplier_id}).scalar()
        if sup is None:
            raise HTTPException(400, "등록되지 않은 공급처입니다")
        before = conn.execute(text(
            "SELECT psp_id, cost_price FROM product_supplier_prices"
            " WHERE product_code=:pc AND supplier_id=:s"),
            {"pc": product_code, "s": body.supplier_id}).mappings().first()
        # 같은 (상품, 공급처)는 한 행이다 — 같은 공급처를 두 번 넣으면 어느 값이 맞는지 알 수 없다
        conn.execute(text(
            "INSERT INTO product_supplier_prices"
            " (product_code, supplier_id, cost_price, supply_state, updated_at)"
            " VALUES (:pc, :s, :c, :st, now())"
            " ON CONFLICT (product_code, supplier_id) DO UPDATE SET"
            "   cost_price = EXCLUDED.cost_price,"
            "   supply_state = COALESCE(EXCLUDED.supply_state, product_supplier_prices.supply_state),"
            "   updated_at = now()"),
            {"pc": product_code, "s": body.supplier_id,
             "c": body.cost_price, "st": body.state or "가능"})
        log_id = _log(conn, "supplier_price", str(product_code),
                      {"product_code": product_code, "supplier_id": body.supplier_id,
                       "supplier": sup, "to": body.cost_price,
                       "from": before["cost_price"] if before else None,
                       "new": before is None}, kind="product")
        n = conn.execute(text(
            "SELECT count(*) FROM product_supplier_prices WHERE product_code=:pc"),
            {"pc": product_code}).scalar_one()
    return {"ok": True, "supplier": sup, "count": n, "undo_id": log_id,
            "note": (f"{sup} 매입가를 "
                     + (f"{body.cost_price:,}원으로 " if body.cost_price is not None else "")
                     + ("등록했습니다." if before is None else "수정했습니다."))}


@router.delete("/products/{product_code}/suppliers/{supplier_id}")
def delete_supplier_price(product_code: int, supplier_id: int):
    from .admin_orders import _log

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT sp.cost_price, s.name FROM product_supplier_prices sp"
            " JOIN suppliers s USING (supplier_id)"
            " WHERE sp.product_code=:pc AND sp.supplier_id=:s"),
            {"pc": product_code, "s": supplier_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "그 공급처 가격이 없습니다")
        conn.execute(text(
            "DELETE FROM product_supplier_prices WHERE product_code=:pc AND supplier_id=:s"),
            {"pc": product_code, "s": supplier_id})
        _log(conn, "supplier_price_remove", str(product_code),
             {"product_code": product_code, "supplier_id": supplier_id,
              "supplier": row["name"], "cost_price": row["cost_price"]}, kind="product")
    return {"ok": True, "note": f"{row['name']} 매입가를 삭제했습니다."}


# ---- 슬라이스 67: 분류(part_type) 변경 ----
# 규약은 "상세에서 분류는 고치지 않는다 — 슬롯을 바꾸는 일이라 재적재 소관"이었다.
# 그런데 적재가 잘못 넣은 분류(미분류 5,149건)를 운영자가 바로잡을 길이 없어서
# 그 상품들이 영영 추천에서 빠진 채 남았다. 그래서 연다 — 단, **눈 감고 바꾸게 하지는
# 않는다**: 분류가 바뀌면 필수 사양 목록이 통째로 바뀌고 추천 슬롯도 달라진다.
# 바꾸기 전에 그 영향을 먼저 보여준다(preview).

CORE_PARTS = {"CPU", "MB", "RAM", "GPU", "POWER", "CASE", "SSD", "HDD",
              "COOLER_CPU_AIR", "COOLER_CPU_AIO"}
PERIPHERALS = {"MONITOR", "KEYBOARD", "MOUSE", "HEADSET", "SPEAKER", "WEBCAM"}


def group_of(part_type: str) -> str:
    """분류 -> 카테고리 그룹. 적재(catalog_map)와 같은 기준."""
    if part_type in CORE_PARTS:
        return "core_part"
    if part_type in PERIPHERALS:
        return "peripheral"
    return "etc"


class PartTypeBody(BaseModel):
    part_type: str
    preview: bool = False       # True면 DB를 바꾸지 않고 영향만 계산한다


@router.post("/products/{product_code}/part-type")
def change_part_type(product_code: int, body: PartTypeBody):
    """분류 변경 — preview로 영향을 먼저 보고, 확인 후 적용한다."""
    from .admin_orders import _log

    new_pt = (body.part_type or "").strip()
    if new_pt not in PART_TYPE_LABELS:
        raise HTTPException(400, "알 수 없는 분류입니다")

    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, category_group,"
            " ai_candidate_yn, review_required_yn, sale_price, stock_qty, status"
            " FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        if r is None:
            raise HTTPException(404, "상품이 없습니다")
        old_pt = r["part_type"]
        if old_pt == new_pt:
            raise HTTPException(400, "이미 그 분류입니다")

        specs = conn.execute(text(
            "SELECT to_jsonb(ps) FROM product_specs ps WHERE product_code=:pc"),
            {"pc": product_code}).scalar() or {}
        old_need, new_need = required_fields(old_pt), required_fields(new_pt)
        missing = [f for f in new_need if specs.get(f) is None]
        dropped = [f for f in old_need if f not in new_need]
        in_pool_now = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty>0"), {"pc": product_code}).first() is not None
        new_group = group_of(new_pt)
        # 바꾼 뒤 추천 후보가 될 수 있는가 — 4중 게이트를 그대로 따져본다
        will_pool = (new_group == "core_part" and not missing
                     and r["status"] == "판매중" and (r["stock_qty"] or 0) > 0
                     and r["sale_price"] is not None)

        impact = {
            "from": {"part_type": old_pt, "label": PART_TYPE_LABELS.get(old_pt, old_pt),
                     "group": r["category_group"]},
            "to": {"part_type": new_pt, "label": PART_TYPE_LABELS.get(new_pt, new_pt),
                   "group": new_group},
            "required_add": [f for f in new_need if f not in old_need],
            "required_drop": dropped,
            "missing_after": missing,
            "in_pool_now": in_pool_now, "in_pool_after": will_pool,
        }
        impact["note"] = (
            impact["from"]["label"] + " -> " + impact["to"]["label"] + "로 바꿉니다."
            + (" 필수 사양 " + str(len(missing)) + "건이 비어 검수 대기가 됩니다."
               if missing else " 필수 사양은 모두 채워져 있습니다.")
            + (" 추천 후보에서 빠집니다." if in_pool_now and not will_pool
               else (" 추천 후보에 오릅니다." if not in_pool_now and will_pool else "")))

        if body.preview:
            return {"preview": True, "impact": impact}

        conn.execute(text(
            "UPDATE products SET part_type=:pt, category_group=:g,"
            " ai_candidate_yn = CASE WHEN :ok THEN true ELSE false END,"
            " review_required_yn = CASE WHEN :ok THEN false ELSE true END,"
            " updated_at=now() WHERE product_code=:pc"),
            {"pt": new_pt, "g": new_group, "ok": will_pool, "pc": product_code})
        # 사양 행의 분류도 함께 옮긴다 — 어긋나면 적재·검수가 서로 다른 종류로 본다
        conn.execute(text(
            "UPDATE product_specs SET part_type=:pt, updated_at=now()"
            " WHERE product_code=:pc"), {"pt": new_pt, "pc": product_code})
        # 사양 행이 아예 없을 수 있다 — ETC로 적재된 상품은 만들어지지 않았다.
        # 그대로 두면 부품인데 사양 행이 없는 상태가 되어 '사양 미등록'으로 잡힌다
        # (실제로 그렇게 됐다: 운영자가 ETC → 메인보드로 바꾼 상품 하나가 그 상태였다).
        conn.execute(text(
            "INSERT INTO product_specs (product_code, part_type) VALUES (:pc, :pt)"
            " ON CONFLICT (product_code) DO NOTHING"),
            {"pc": product_code, "pt": new_pt})
        # 새 분류에서 쓰지 않는 필드의 검수 대기는 의미가 없다 — 닫는다
        closed = 0
        if dropped:
            closed = conn.execute(text(
                "UPDATE product_reviews SET review_status=:done, reviewed_by=:op,"
                " reviewed_at=now(), detail = detail || :tail"
                " WHERE product_code=:pc AND review_status=:wait"
                "   AND field_name = ANY(:f)"),
                {"pc": product_code, "f": dropped, "op": current_operator_id(),
                 "done": "처리", "wait": "대기", "tail": " [분류 변경으로 해소]"}).rowcount
        # 새 분류에서 필요한데 비어 있는 사양은 검수로 올린다
        opened = 0
        for f in missing:
            exists = conn.execute(text(
                "SELECT 1 FROM product_reviews WHERE product_code=:pc"
                " AND field_name=:f AND review_status=:wait"),
                {"pc": product_code, "f": f, "wait": "대기"}).first()
            if exists:
                continue
            # review_type은 NOT NULL이고 큐가 유형별로 화면을 나눈다.
            # 분류를 바꿔 비게 된 필수 사양은 결국 '사양 없음'이므로 기존 유형을 쓴다 —
            # 새 유형을 만들면 검수 화면이 그 항목을 어디에도 못 놓는다.
            conn.execute(text(
                "INSERT INTO product_reviews (product_code, review_type, field_name,"
                " review_status, detail, created_at)"
                " VALUES (:pc, :rt, :f, :wait, :d, now())"),
                {"pc": product_code, "rt": "spec_missing", "f": f, "wait": "대기",
                 "d": "분류 변경(" + PART_TYPE_LABELS.get(new_pt, new_pt)
                      + ") - 필수 사양 미확인"})
            opened += 1

        log_id = _log(conn, "part_type_change", r["sku"],
                      {"product_code": product_code, "sku": r["sku"],
                       "from": old_pt, "to": new_pt,
                       "before": {"category_group": r["category_group"],
                                  "ai_candidate_yn": r["ai_candidate_yn"],
                                  "review_required_yn": r["review_required_yn"]},
                       "closed": closed, "opened": opened}, kind="product")
        now_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty>0"), {"pc": product_code}).first() is not None

    return {"ok": True, "impact": impact, "reviews_closed": closed,
            "reviews_opened": opened, "in_pool": now_pool, "undo_id": log_id,
            "note": ("분류를 " + impact["to"]["label"] + "로 바꿨습니다."
                     + (" 검수 " + str(closed) + "건이 해소되고" if closed else "")
                     + (" " + str(opened) + "건이 새로 올라왔습니다." if opened else
                        (" 추천 후보에 올랐습니다." if now_pool else "")))}


@router.post("/products/part-type/undo/{log_id}")
def undo_part_type(log_id: int):
    """분류 변경 되돌리기 — 분류·그룹·게이트 상태를 함께 되돌린다."""
    from .admin_orders import _log

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if row is None or row["action"] != "part_type_change":
            raise HTTPException(404, "되돌릴 분류 변경 기록이 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE action='part_type_change_undo'"
            "   AND (detail->>'ref_log_id')::int=:i LIMIT 1"), {"i": log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 변경입니다")
        d = row["detail"] or {}
        pc, b = d.get("product_code"), d.get("before") or {}
        conn.execute(text(
            "UPDATE products SET part_type=:pt, category_group=:g,"
            " ai_candidate_yn=:ac, review_required_yn=:rr, updated_at=now()"
            " WHERE product_code=:pc"),
            {"pt": d.get("from"), "g": b.get("category_group"),
             "ac": b.get("ai_candidate_yn", False),
             "rr": b.get("review_required_yn", True), "pc": pc})
        conn.execute(text(
            "UPDATE product_specs SET part_type=:pt, updated_at=now()"
            " WHERE product_code=:pc"), {"pt": d.get("from"), "pc": pc})
        # 분류 변경으로 새로 올린 검수는 근거가 사라졌으니 함께 거둔다
        conn.execute(text(
            "DELETE FROM product_reviews WHERE product_code=:pc"
            "   AND review_status=:wait AND detail LIKE :pat"),
            {"pc": pc, "wait": "대기", "pat": "분류 변경(%"})
        _log(conn, "part_type_change_undo", str(d.get("sku") or pc),
             {"ref_log_id": log_id, "product_code": pc, "restored": d.get("from")},
             kind="product")
    return {"ok": True, "restored": d.get("from")}


@router.get("/product-similar")
def similar_products(name: str = "", part_type: str = "", exclude: int | None = None):
    """이름이 닮은 기존 상품 — 등록 전 확인·중복 정리에 쓴다(슬라이스 68).

    판정 기준은 `api/dedupe`가 단일 원천이다. 등록 API와 이 조회가 다른 잣대를 쓰면
    "확인창엔 안 떴는데 등록은 막힌다" 같은 일이 생긴다.
    """
    from . import dedupe

    if not name.strip():
        return {"items": [], "threshold": dedupe.SIMILAR_THRESHOLD}
    with engine.connect() as conn:
        items = dedupe.find_similar(conn, name.strip(), part_type.strip() or None, exclude)
    return {"items": items, "threshold": dedupe.SIMILAR_THRESHOLD,
            "note": ("이름이 거의 같은 상품입니다 — 같은 상품이면 등록하지 말고"
                     " 기존 상품을 수정하세요.")}


# ---- 슬라이스 69: 중복 상품 편입·삭제 ----
# 실수로 같은 상품을 두 번 만들면 재고와 매입가가 갈라진다. 정리할 길이 필요하다.
#
# **삭제는 마지막 수단이다.** products를 참조하는 테이블이 15개고, 그중 order_items에
# 걸린 상품을 지우면 **과거 주문서가 깨진다**(실측 33종). 그래서 두 갈래로 나눈다:
#   · 편입(권장) — 재고·공급처를 원본으로 옮기고 중복은 '삭제대기'로. 원장이 남고 되돌릴 수 있다.
#   · 삭제       — 주문 이력이 하나도 없을 때만. 되돌릴 수 없어 화면이 먼저 그렇게 말한다.

# 편입해도 되는 참조 = 옮기거나 남겨도 뜻이 변하지 않는 것.
# order_items는 여기 없다 — 과거 주문은 그때 그 상품을 가리켜야 한다.
BLOCK_DELETE = [
    ("order_items", "product_code", "주문 이력"),
]
CHECK_REFS = [
    ("order_items", "product_code", "주문"),
    ("stock_movements", "product_code", "재고 원장"),
    ("promo_click_logs", "product_code", "근거 클릭"),
    ("swap_event_logs", "from_product", "부품 교체(이전)"),
    ("swap_event_logs", "to_product", "부품 교체(이후)"),
    ("member_favorites", "product_code", "찜"),
    ("product_price_history", "product_code", "가격 이력"),
    ("stock_reservations", "product_code", "재고 예약"),
]


def _ref_counts(conn, pc: int) -> list:
    out = []
    for tbl, col, label in CHECK_REFS:
        n = conn.execute(text(
            f"SELECT count(*) FROM {tbl} WHERE {col} = :pc"), {"pc": pc}).scalar_one()
        if n:
            out.append({"table": tbl, "label": label, "count": n})
    return out


class MergeBody(BaseModel):
    into: int                   # 남길 원본 상품
    preview: bool = False


@router.post("/products/{product_code}/merge")
def merge_product(product_code: int, body: MergeBody):
    """중복 상품을 원본에 편입한다 — 재고·공급처를 옮기고 중복은 '삭제대기'로."""
    from .admin_orders import _log

    if product_code == body.into:
        raise HTTPException(400, "같은 상품끼리는 합칠 수 없습니다")
    with engine.begin() as conn:
        dup = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, status, stock_qty"
            " FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        keep = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, status, stock_qty"
            " FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": body.into}).mappings().first()
        if dup is None or keep is None:
            raise HTTPException(404, "상품이 없습니다")
        if dup["status"] == "삭제대기":
            raise HTTPException(409, "이미 정리된 상품입니다")

        refs = _ref_counts(conn, product_code)
        move_stock = dup["stock_qty"] or 0
        # 원본에 없는 공급처만 옮긴다 — 같은 공급처가 두 값을 가지면 어느 쪽이 맞는지 모른다
        sups = conn.execute(text(
            "SELECT sp.supplier_id, sp.cost_price, sp.supply_state"
            " FROM product_supplier_prices sp WHERE sp.product_code=:d"
            "   AND NOT EXISTS (SELECT 1 FROM product_supplier_prices k"
            "                    WHERE k.product_code=:k AND k.supplier_id=sp.supplier_id)"),
            {"d": product_code, "k": body.into}).mappings().all()

        impact = {
            "dup": {"product_code": dup["product_code"], "sku": dup["sku"],
                    "name": dup["product_name"], "stock": dup["stock_qty"]},
            "keep": {"product_code": keep["product_code"], "sku": keep["sku"],
                     "name": keep["product_name"], "stock": keep["stock_qty"]},
            "move_stock": move_stock, "move_suppliers": len(sups),
            "refs": refs,
            "part_type_same": dup["part_type"] == keep["part_type"],
        }
        impact["note"] = (
            "재고 " + str(move_stock) + "개와 공급처 " + str(len(sups)) + "곳을 "
            + keep["sku"] + "로 옮기고, " + dup["sku"] + "는 삭제대기로 둡니다."
            + ("" if impact["part_type_same"]
               else " 두 상품의 분류가 다릅니다 — 확인하세요."))
        if body.preview:
            return {"preview": True, "impact": impact}

        # 재고는 원장으로 옮긴다 — 수량만 고치면 어디서 왔는지 알 수 없다
        if move_stock:
            conn.execute(text(
                "INSERT INTO stock_movements (product_code, movement_type, qty_delta,"
                " ref_kind, ref_id) VALUES (:pc, :mt, :q, :rk, :ri)"),
                {"pc": product_code, "mt": "adjust", "q": -move_stock,
                 "rk": "manual", "ri": body.into})
            conn.execute(text(
                "INSERT INTO stock_movements (product_code, movement_type, qty_delta,"
                " ref_kind, ref_id) VALUES (:pc, :mt, :q, :rk, :ri)"),
                {"pc": body.into, "mt": "adjust", "q": move_stock,
                 "rk": "manual", "ri": product_code})
            conn.execute(text(
                "UPDATE products SET stock_qty = stock_qty + :q, updated_at=now()"
                " WHERE product_code=:pc"), {"q": move_stock, "pc": body.into})
            conn.execute(text(
                "UPDATE products SET stock_qty = 0, updated_at=now()"
                " WHERE product_code=:pc"), {"pc": product_code})
        for s in sups:
            conn.execute(text(
                "UPDATE product_supplier_prices SET product_code=:k, updated_at=now()"
                " WHERE product_code=:d AND supplier_id=:s"),
                {"k": body.into, "d": product_code, "s": s["supplier_id"]})
        # 중복은 지우지 않는다 — 상태로 내린다(원장·이력이 그대로 남는다)
        conn.execute(text(
            "UPDATE products SET status=:st, ai_candidate_yn=false,"
            " review_required_yn=true, updated_at=now() WHERE product_code=:pc"),
            {"st": "삭제대기", "pc": product_code})
        # 정리된 상품의 검수 대기는 의미가 없다
        closed = conn.execute(text(
            "UPDATE product_reviews SET review_status=:done, reviewed_by=:op,"
            " reviewed_at=now(), detail = detail || :tail"
            " WHERE product_code=:pc AND review_status=:wait"),
            {"pc": product_code, "op": current_operator_id(),
             "done": "처리", "wait": "대기", "tail": " [중복 편입으로 해소]"}).rowcount

        log_id = _log(conn, "product_merge", dup["sku"],
                      {"dup": product_code, "into": body.into,
                       "dup_sku": dup["sku"], "keep_sku": keep["sku"],
                       "moved_stock": move_stock,
                       "moved_suppliers": [s["supplier_id"] for s in sups],
                       "before": {"status": dup["status"], "stock_qty": dup["stock_qty"]},
                       "closed": closed}, kind="product")
    return {"ok": True, "impact": impact, "reviews_closed": closed, "undo_id": log_id,
            "note": (dup["sku"] + "를 " + keep["sku"] + "에 편입했습니다."
                     + (" 재고 " + str(move_stock) + "개 이동." if move_stock else "")
                     + (" 공급처 " + str(len(sups)) + "곳 이동." if sups else ""))}


@router.post("/products/merge/undo/{log_id}")
def undo_merge(log_id: int):
    """편입 되돌리기 — 재고를 역방향 원장으로 돌리고 상태를 복원한다."""
    from .admin_orders import _log

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if row is None or row["action"] != "product_merge":
            raise HTTPException(404, "되돌릴 편입 기록이 없습니다")
        dup2 = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs WHERE action='product_merge_undo'"
            "   AND (detail->>'ref_log_id')::int=:i LIMIT 1"), {"i": log_id}).first()
        if dup2:
            raise HTTPException(409, "이미 되돌린 편입입니다")
        d = row["detail"] or {}
        pc, into, qty = d.get("dup"), d.get("into"), d.get("moved_stock") or 0
        if qty:
            cur = conn.execute(text(
                "SELECT stock_qty FROM products WHERE product_code=:p FOR UPDATE"),
                {"p": into}).scalar_one()
            if cur < qty:
                raise HTTPException(409, "원본 재고가 편입분보다 적습니다 — 이후 판매·조정이 있었습니다")
            conn.execute(text(
                "INSERT INTO stock_movements (product_code, movement_type, qty_delta,"
                " ref_kind, ref_id) VALUES (:pc, :mt, :q, :rk, :ri)"),
                {"pc": into, "mt": "adjust", "q": -qty, "rk": "manual", "ri": pc})
            conn.execute(text(
                "INSERT INTO stock_movements (product_code, movement_type, qty_delta,"
                " ref_kind, ref_id) VALUES (:pc, :mt, :q, :rk, :ri)"),
                {"pc": pc, "mt": "adjust", "q": qty, "rk": "manual", "ri": into})
            conn.execute(text(
                "UPDATE products SET stock_qty = stock_qty - :q, updated_at=now()"
                " WHERE product_code=:p"), {"q": qty, "p": into})
            conn.execute(text(
                "UPDATE products SET stock_qty = :q, updated_at=now()"
                " WHERE product_code=:p"), {"q": qty, "p": pc})
        for sid in (d.get("moved_suppliers") or []):
            conn.execute(text(
                "UPDATE product_supplier_prices SET product_code=:p, updated_at=now()"
                " WHERE product_code=:k AND supplier_id=:s"),
                {"p": pc, "k": into, "s": sid})
        b = d.get("before") or {}
        conn.execute(text(
            "UPDATE products SET status=:st, updated_at=now() WHERE product_code=:p"),
            {"st": b.get("status") or "판매중", "p": pc})
        _log(conn, "product_merge_undo", str(d.get("dup_sku") or pc),
             {"ref_log_id": log_id, "dup": pc, "into": into}, kind="product")
    return {"ok": True, "restored": pc}


@router.delete("/products/{product_code}")
def delete_product(product_code: int, force: bool = False):
    """상품 삭제 — 주문 이력이 있으면 거부한다(과거 주문서가 깨진다)."""
    from .admin_orders import _log

    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT sku, product_name, status FROM products WHERE product_code=:pc"
            " FOR UPDATE"), {"pc": product_code}).mappings().first()
        if r is None:
            raise HTTPException(404, "상품이 없습니다")
        for tbl, col, label in BLOCK_DELETE:
            n = conn.execute(text(
                f"SELECT count(*) FROM {tbl} WHERE {col} = :pc"),
                {"pc": product_code}).scalar_one()
            if n:
                raise HTTPException(409, {
                    "error": "has_history",
                    "message": (label + " " + str(n) + "건이 있어 지울 수 없습니다 —"
                                " 편입하거나 '삭제대기'로 내려 주세요"),
                    "refs": _ref_counts(conn, product_code)})
        refs = _ref_counts(conn, product_code)
        if refs and not force:
            raise HTTPException(409, {
                "error": "has_refs",
                "message": "이 상품을 가리키는 기록이 있습니다 — 확인 후 지웁니다",
                "refs": refs})
        # 참조를 먼저 정리한다(FK 순서). 이력 성격이라 상품과 함께 사라져도 뜻이 남는다.
        for tbl, col in (("stock_reservations", "product_code"),
                         ("promo_click_logs", "product_code"),
                         ("member_favorites", "product_code"),
                         ("product_price_history", "product_code"),
                         ("stock_movements", "product_code"),
                         ("supplier_product_map", "product_code"),
                         ("product_sourcing_quotes", "product_code"),
                         ("product_sourcing_match_candidates", "product_code"),
                         ("product_supplier_prices", "product_code"),
                         ("product_reviews", "product_code"),
                         ("product_specs", "product_code")):
            conn.execute(text(f"DELETE FROM {tbl} WHERE {col} = :pc"), {"pc": product_code})
        conn.execute(text("DELETE FROM swap_event_logs WHERE from_product=:pc"
                          "   OR to_product=:pc"), {"pc": product_code})
        conn.execute(text("DELETE FROM products WHERE product_code=:pc"),
                     {"pc": product_code})
        _log(conn, "product_delete", r["sku"],
             {"product_code": product_code, "sku": r["sku"],
              "name": r["product_name"], "refs": refs}, kind="product")
    return {"ok": True, "note": r["sku"] + " 상품을 삭제했습니다. 되돌릴 수 없습니다."}
