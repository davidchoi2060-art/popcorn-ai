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


def _finite_or_none(v):
    """NUMERIC 컬럼 값을 JSON에 실어도 안전한 float로 바꾼다.

    Postgres NUMERIC은 'NaN'을 실제 값으로 담을 수 있는데(정수·부동소수와 다른 점),
    2026-08-26 실측으로 product_supplier_prices.rebate_pct 4행이 실제로 Decimal('NaN')
    이었다(몰 수집 도구의 파싱 이상 — 이 파일 소관 밖). Starlette JSONResponse는
    allow_nan=False라 NaN을 그대로 내보내면 그 상품 상세 전체가 500이 된다("Out of
    range float values are not JSON compliant"). 값이 없다는 뜻으로 취급해 None을
    돌려준다 — 화면은 이미 None을 "리베이트 없음"으로 다룬다.
    """
    if v is None:
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


router = APIRouter(prefix="/api/admin")

# part_type 어휘는 taxonomy가 단일 원천(슬라이스 A) — 여기서 다시 정의하지 않는다.
from .taxonomy import (PART_LABELS as PART_TYPE_LABELS, CORE_TYPES,
                       BUILT_TYPES, choice_tree)

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

# 상품명 검색 — 띄어쓰기에 걸리지 않게 «두 갈래»로 본다(요청 35).
#
#   ① 조각 전부 포함  「Bri B」 -> 'Bri' 와 'B' 가 «둘 다» 들어간 이름을 찾는다.
#      사장님 예시(2026-09-01 댓글): 「Bri 한칸 띄우고 B」로 「Britz BA 100」이 나와야 한다.
#      ⚠ 처음엔 ②만 넣었는데 그것으로는 이 예시가 «0건»이었다 — 'BriB' 는 'BritzBA100'
#        안에 없다. 조각을 나눠 보는 것이 사장님이 말씀하신 「유관검색어」다.
#   ② 공백 무시 통짜  「RTX4060」 <-> 「RTX 4060 Ti」. 원천이 같은 제품을 제각각 적어
#      와서, 운영자가 본 대로 붙여 쳐도 나와야 한다.
#
# 값을 고치지 않고 «비교만» 느슨하게 한다 — 원천 표기를 바꾸면 마켓에 나가는 이름이
# 달라진다. sku·maker 는 기존 방식 그대로다(정확히 치는 값이고, 그쪽까지 느슨하게
# 하면 전 컬럼이 순차 검색이 된다).
# ⚠ ①의 NOT EXISTS 는 «조각이 하나도 없으면 참»이라 빈 검색어를 막아야 한다 —
#   그래서 바깥 가드를 `:q = ''` 가 아니라 `btrim(:q) = ''` 로 둔다(공백만 친 경우 포함).
_WHERE = """
    WHERE (btrim(:q) = ''
           OR NOT EXISTS (
                SELECT 1 FROM unnest(string_to_array(btrim(:q), ' ')) AS t(tok)
                 WHERE tok <> '' AND p.product_name NOT ILIKE '%%' || tok || '%%')
           OR REPLACE(p.product_name, ' ', '') ILIKE '%%' || REPLACE(:q, ' ', '') || '%%'
           OR p.product_name ILIKE '%%' || :q || '%%' OR p.sku ILIKE '%%' || :q || '%%'
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


def derive_status(review_required_yn, stock_qty, status, sale_price) -> str:
    """화면 상태 4종 파생. 우선순위 순 — 한 상품은 정확히 한 버킷.

    한계(주석으로 명시): sale_price=0은 NULL이 아니라 ok로 흐른다.

    **목록·상세가 같은 신호를 보게 하는 단일 원천**(결함 ⓐ-3, 2026-08-15).
    예전엔 상세 서랍(`get_product`)이 이 함수를 안 쓰고 `review_pending`
    (`product_reviews` 대기행 실count)을 따로 봤다. 그런데 그 수는 살아있는
    신호가 아니다 — 실측: ① 신규 등록은 review 행을 아예 만들지 않는다(이
    화면에서 등록한 상품은 전부 review_pending=0으로 시작하는데도 검수가
    필요하다) ② `undo_spec_edit`는 사양 값과 `review_required_yn`은 되돌리지만
    그 편집이 닫았던 `product_reviews` 행은 다시 열지 않는다(105481·105489
    실사례 — 값은 다시 비었는데 검수행만 '처리'로 남았다). 반대로
    `review_required_yn`은 등록·분류변경·사양완료 승격 세 지점에서만 바뀌고
    되돌리기도 그 컬럼 자체를 원래 값으로 복원하므로 어긋나지 않는다. 그래서
    이 함수(=`review_required_yn` 기준)를 목록과 상세 양쪽의 단일 원천으로 쓴다.

    row 객체 대신 낱개 인자를 받는다 — 목록은 `.all()`의 Row(속성 접근),
    상세(`get_product`)는 `.mappings()`의 dict(첨자 접근)라 하나의 시그니처로
    둘 다 못 받는다. 호출부가 각자 방식으로 값을 꺼내 넘긴다.
    """
    if review_required_yn:
        return "review"
    if stock_qty == 0 or status == "품절":
        return "oos"
    if sale_price is None:
        return "price"
    if status == "판매중":
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
        status_key = derive_status(r.review_required_yn, r.stock_qty, r.status, r.sale_price)
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
    # 분류는 **코드로 받는 것이 정본**이다(`part_type`). 라벨은 옛 경로다 —
    # 화면이 한글 라벨을 들고 왕복하면 표기를 다듬는 순간 등록이 깨진다.
    # 2단 선택(2026-08-06)부터 화면은 코드를 보낸다.
    part_type: str | None = None
    part_label: str | None = None   # 옛 경로(라벨) — 둘 중 하나는 있어야 한다
    # 아래 셋은 **단가표發 등록일 때만** 온다(슬라이스 54에서 선택으로 완화).
    # 상품 관리에서 직접 등록하면 공급처가 정해지지 않은 상태이고, 없는 사실을
    # 매핑·매입가 원장에 적을 수는 없다.
    supplier_id: int | None = None
    model_name: str | None = None      # 단가표 행 원문 — map model_key(상품명 입력과 별도)
    cost_price: int | None = None
    danawa_code: str | None = None
    maker: str | None = None
    # products.supplier — **위 supplier_id와 다른 필드다**(혼동 주의). supplier_id는
    # suppliers 테이블 FK로 단가표發 등록에서만 오고 product_supplier_prices(구조화된
    # 공급처별 매입가 표)에 연결된다. 이 supplier는 products의 자유 텍스트 한 칸으로,
    # 몰 CSV가 주는 값을 그대로 담는 별개 저장소다(둘을 합치지 않는다 — 사장님 지시).
    # 선택 입력 — 비워도 등록된다.
    supplier: str | None = None
    # 닮은 상품이 있어도 "다른 상품이다"라고 확인했으면 그대로 등록한다(슬라이스 68)
    confirm_similar: bool = False


@router.post("/products")
def register_product(body: RegisterBody):
    from .admin_orders import _log  # kind 파라미터형 공용 로거
    # 라벨은 이제 1:1이다(공랭/수냉 분리) — setdefault로 뭉갤 중복이 없다.
    if body.part_type:
        pt = body.part_type.strip()
        if pt not in PART_TYPE_LABELS or pt == "ETC":
            raise HTTPException(400, f"알 수 없는 분류: {body.part_type}")
    else:
        rev = {v: k for k, v in PART_TYPE_LABELS.items()}
        lab = (body.part_label or "").strip()
        if not lab:
            raise HTTPException(400, "분류를 선택하세요")
        # 뭉뚱그린 옛 라벨('CPU쿨러')을 보내는 화면이 남아 있을 수 있어 공랭으로 받아준다.
        # **새 화면은 코드를 보내므로 여기 오지 않는다** — 옛 경로의 안전망일 뿐이다.
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
        # supplier는 VARCHAR(200) 자유 텍스트 — 선택 입력이라 안 넣으면 NULL(등록은 그대로 된다).
        sup_val = (body.supplier or "").strip()[:200] or None
        conn.execute(text(
            "INSERT INTO products (product_code, sku, product_name, part_type, category_group,"
            " status, ai_candidate_yn, review_required_yn, purchase_price, stock_qty, danawa_code,"
            " supplier)"
            " VALUES (:pc, :sku, :n, :pt, 'core_part', '판매중', false, true, :cost, 0, :d, :sup)"),
            {"pc": pc, "sku": sku, "n": body.name.strip(), "pt": pt,
             "cost": body.cost_price, "d": body.danawa_code, "sup": sup_val})
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
# ⚠ 문자열 필드는 **None 을 먼저 걸러야 한다**(2026-09-01 요청 37 검증에서 드러남).
#   `str(v).strip() or None` 만 쓰면 v 가 None 일 때 `str(None)` == "None" 이 되고,
#   그 네 글자가 참값이라 **문자열 "None" 이 상품 정보로 저장된다.** 화면에는 제조사가
#   「None」인 상품으로 보인다. maker·supplier 에 원래 있던 결함이고, 값을 «지우는»
#   경로(빈 칸 저장)가 열리면서 실제로 밟게 됐다.
def _s(v, n=None):
    """문자열 정리 — None 은 None 으로 둔다(지운다는 뜻). n 은 길이 상한."""
    if v is None:
        return None
    s = str(v).strip()
    return (s[:n] if n else s) or None


EDITABLE = {
    "name": ("product_name", _s),
    "maker": ("maker", _s),
    # products.supplier — 자유 텍스트(몰 CSV 값). product_supplier_prices(공급처별
    # 매입가 표, 별도 탭)와는 다른 필드다 — 합치지 않는다. maker와 같은 규칙:
    # 빈 문자열은 '지운다'는 뜻으로 NULL 저장, 컬럼 자체를 안 보내면 안 바뀐다.
    "supplier": ("supplier", lambda v: _s(v, 200)),
    "sale_price": ("sale_price", lambda v: None if v in ("", None) else int(v)),
    "purchase_price": ("purchase_price", lambda v: None if v in ("", None) else int(v)),
    "stock_qty": ("stock_qty", lambda v: int(v)),
    "status": ("status", lambda v: str(v).strip()),
    # ── 요청 37 (2026-09-01 사장님 지시) ────────────────────────────────────
    #   "상품코드·SKU 말고는 다 변경할 수 있어야 한다 — 특가판매로 시장가가 바뀌고
    #    다나와 코드도 고치는 경우가 있다."
    #   ⚠ 잠금이 실제로 지켜지는지 «먼저» 확인하고 넣었다. `CLAUDE.md`에는 "잠금이
    #     지키는 것은 매입가·판매가 둘뿐"이라 적혀 있지만 **그 서술이 낡았다** —
    #     catalog_ingest.UPSERT_PRODUCTS_SQL 에 셋 다 가드가 이미 있다
    #     (model_name:549 · market_price:592 · danawa_code:612 · 2026-08-24 확장).
    #     그때 주석이 "나중에 EDITABLE 이 넓어질 때를 위해 미리 넣는다"고 적어 뒀고,
    #     오늘 그 "나중"이 왔다. 즉 여기 추가하는 것만으로 잠금이 살아난다.
    "model_name": ("model_name", _s),
    # ⚠ danawa_code 는 부분 UNIQUE 인덱스가 걸려 있다(0001_initial_schema:127 —
    #   `WHERE danawa_code IS NOT NULL`). 남의 코드를 넣으면 23505 로 죽으므로
    #   저장 전에 미리 보고 사람이 읽는 문장으로 막는다(아래 patch_product).
    "danawa_code": ("danawa_code", _s),
    "market_price": ("market_price", lambda v: None if v in ("", None) else int(v)),
}
STATUS_OK = ("판매중", "품절", "단종", "삭제대기")
# 가격·재고는 정본 수치다 — 음수나 터무니없는 값이 들어가면 견적이 통째로 흔들린다
LIMIT = {"sale_price": (0, 100_000_000), "purchase_price": (0, 100_000_000),
         "stock_qty": (0, 100_000),
         # 시장가도 정본 수치다 — 가격 검토 화면이 이 값을 기준으로 삼는다(요청 37).
         "market_price": (0, 100_000_000)}

# EDITABLE의 가격 필드 -> product_price_history.field 값(실측: 이 테이블은 'sale'/
# 'purchase' 둘만 쓴다 — 'sale_price' 문자열 그대로가 아니다). PATCH가 이 필드들을
# 바꾸면서도 이 원장에 안 남기고 있었다(2026-08-15 실측 결함 — 판매가 관리 제작자가
# 46158로 먼저 지목, 119253으로 재현). stock_qty를 stock_movements에 남기는 것과
# 같은 이유로 같은 자리(PATCH·undo)에서 함께 남긴다.
PRICE_HISTORY_FIELD = {"sale_price": "sale", "purchase_price": "purchase"}


@router.get("/product-meta")
def product_meta(part_type: str = ""):
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
    # 제조사 목록은 **고른 분류 안에서만** 낸다(요청 36 · 2026-08-31).
    # 메인보드를 골라도 전 제조사가 나와, 운영자가 고른 제조사에 그 분류 상품이
    # 하나도 없는 조합을 만들 수 있었다 — 결과 0건을 보고 "상품이 없다"고 읽는다.
    # `part_type` 이 없으면 전체다(등록·수정 화면은 분류가 정해지기 «전»에도 부른다).
    pt = (part_type or "").strip()
    with engine.connect() as conn:
        makers = [r[0] for r in conn.execute(text(
            "SELECT maker FROM products WHERE maker IS NOT NULL AND maker <> ''"
            "   AND (:pt = '' OR part_type = :pt)"
            " GROUP BY maker ORDER BY count(*) DESC, maker"), {"pt": pt})]
        used = [r[0] for r in conn.execute(text(
            "SELECT part_type FROM products WHERE part_type IS NOT NULL"
            " GROUP BY part_type ORDER BY count(*) DESC"))]
    return {
        "part_labels": [{"part_type": k, "label": v}
                        for k, v in PART_TYPE_LABELS.items() if k in core],
        # **이진 분기가 아니다**(2026-08-05): 조립 부품도 주변기기도 아닌 완성품이 생겼다.
        # 예전 조건(`core 아니고 ETC 아니면 주변기기`)을 그대로 두면 화면이 완제품 PC를
        # '주변기기'라 부른다. 종류가 늘 때 이런 else 가 조용히 틀린 말을 한다.
        "peripheral_labels": [{"part_type": k, "label": v}
                              for k, v in PART_TYPE_LABELS.items()
                              if k not in core and k != "ETC" and k not in BUILT_TYPES],
        "built_labels": [{"part_type": k, "label": PART_TYPE_LABELS[k]}
                         for k in BUILT_TYPES if k in PART_TYPE_LABELS],
        # **2단 선택지**(2026-08-06 사용자 결정). 접히는 종류만 `options` 를 갖는다.
        # 화면은 그것이 있으면 두 번째 칸을 띄우기만 한다 — 무엇이 접히는지는
        # `taxonomy` 만 안다. 등록은 코어만, 수정은 고를 수 있는 전부를 쓴다.
        "part_choices": choice_tree([k for k in PART_TYPE_LABELS if k in core]),
        "all_choices": choice_tree([k for k in PART_TYPE_LABELS if k != "ETC"]),
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
        # **전체** 대기 건수(필드 종류 무관) — 표시용 보조 수치일 뿐, 차단 여부 판정에
        # 이 값 자체를 쓰지 않는다(2026-08-24 결함 수정). 다나와 시세 제안
        # (field_name='market_price')류 대기는 review_required_yn을 안 건드리는데
        # 예전엔 이 수만 보고 "검수가 남았다"고 판정했다 — 아래 gate "review"·verdict
        # 참고.
        pending = conn.execute(text(
            "SELECT count(*) FROM product_reviews WHERE product_code=:pc"
            " AND review_status='대기'"), {"pc": product_code}).scalar_one()
        in_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty > 0"), {"pc": product_code}).first() is not None
        # 공급처별 매입가 — 화면 표는 지금까지 마크업 하드코딩이었다(용산도매A 352,000 등).
        # 신규 등록 화면에도 그 값이 그대로 떠서 **없는 공급처가 있는 것처럼** 보였다.
        # 2026-08-26 A-114 후속: 몰 수집 칸(mall_rank·rebate_*·mall_state_raw·fetched_at)과
        # 공급처 연락처(suppliers.contact_*)를 더한다 — 받아 놓고 화면에 못 보내던 값들
        # (0066 마이그레이션). order_price는 뺀다: 몰 마크업에서 행별 구분이 안 돼 항상
        # NULL이라 화면에 실으면 "발주가 0원"으로 오해를 부른다.
        # 정렬은 몰 순위(mall_rank, NULL=옛 엑셀 유입은 뒤로) 우선 — 몰 순서=싼 순이라
        # 화면이 다시 정렬하지 않아도 된다.
        sups = [dict(x) for x in conn.execute(text(
            "SELECT sp.psp_id, sp.supplier_id, s.name AS supplier, sp.cost_price,"
            " sp.supply_state, sp.updated_at,"
            " sp.mall_rank, sp.rebate_pct, sp.rebate_price, sp.mall_state_raw, sp.fetched_at,"
            " s.contact_name, s.contact_phone, s.order_phone, s.contact_raw, s.contact_fetched_at"
            " FROM product_supplier_prices sp JOIN suppliers s USING (supplier_id)"
            " WHERE sp.product_code = :pc"
            " ORDER BY sp.mall_rank NULLS LAST, sp.cost_price NULLS LAST, sp.psp_id"),
            {"pc": product_code}).mappings()]
        # "살 수 있는 최저가" — 품절 행의 가격을 최저가로 오인하지 않게 서버가 미리 골라
        # 낸다(A-114 실측: 102780류 24건이 "전체 최저가가 품절인 곳"이었다). 화면은 이
        # 값을 그대로 쓰고 스스로 재계산하지 않는다. supply_state=='가능' 판정은
        # api/admin_price_import.py _reprice()의 매입가 선정 기준과 같다.
        avail = [s for s in sups if s["supply_state"] == "가능" and s["cost_price"] is not None]
        cheapest_available = None
        if avail:
            best = min(avail, key=lambda s: s["cost_price"])
            cheapest_available = {"psp_id": best["psp_id"], "supplier_id": best["supplier_id"],
                                   "supplier": best["supplier"], "cost_price": best["cost_price"]}
    done, total = spec_progress(r["part_type"], r["specs"])
    locked = list(r["locked_fields"] or [])
    # 목록 배지와 같은 신호(결함 ⓐ-3) — `review_pending`(검수 큐 실행 건수)은
    # 부수 정보일 뿐 배지 판정 기준이 아니다. derive_status 독스트링 참고.
    status_key = derive_status(r["review_required_yn"], r["stock_qty"], r["status"], r["sale_price"])

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
         # 추천 뷰의 part_type IN (...) 조건은 CORE_TYPES 10종뿐이다. PART_TYPE_LABELS는
         # 주변기기·완제품까지 포함한 전체 어휘라 그걸로 재면 뷰가 거르는 조합을
         # "분류는 맞다"고 잘못 통과시킬 수 있다(2026-08-24 실측: 지금은 실제로 그런
         # 상품이 0건이지만, 뷰 조건과 다른 어휘로 판정하는 것 자체가 다음 적재에서
         # 어긋날 여지를 남긴다 — CORE_TYPES가 이미 taxonomy.py 정본이라 이걸 쓴다).
         "ok": r["category_group"] == "core_part" and r["part_type"] in CORE_TYPES,
         # 폴백은 "ETC(분류됨)"와 다른 사실이다 — part_type 자체가 없다는 뜻이라
         # PART_TYPE_LABELS(정본) 값과 같은 글자를 쓰지 않는다(화면 정직성 규약).
         "value": PART_TYPE_LABELS.get(r["part_type"], r["part_type"] or "미지정"),
         "fix": "상세에서 분류를 고칩니다 — 바꾸기 전에 영향을 먼저 보여줍니다",
         "fix_screen": None},
        {"key": "spec_row", "label": "사양 정보",
         "ok": r["specs"] is not None,
         "value": "있음" if r["specs"] is not None else "없음(적재가 부품 종류를 못 정함)",
         "fix": "분류를 바로잡으면 사양 자리가 생깁니다",
         "fix_screen": None},
        {"key": "review", "label": "필수 사양",
         # **차단 신호는 review_required_yn이다 — product_reviews 대기 행이 있다는
         # 사실 자체가 아니다**(2026-08-24 결함 수정, derive_status와 같은 원천으로
         # 맞춤). 다나와 시세 제안(field_name='market_price')·다나와 코드 재확인
         # (field_name='danawa_code')류 대기 행은 review_required_yn을 건드리지
         # 않는다(_approve_product_field는 products.market_price만 갱신 — api/
         # admin_reviews.py 실측) — 그런데 예전 식(`pending == 0 and ...`)은 그런
         # 대기 행이 하나만 있어도 이 항목을 "막힘"으로 셌다. 실사례: 94959는
         # market_price 제안 대기 1건뿐이고 review_required_yn=false·in_pool=true인데
         # 이 항목이 막힘으로 나왔다(danawa_code만 대기인 상품 31건 전수 확인 —
         # 전부 review_required_yn=false). ai_candidate_yn은 그대로 함께 본다 —
         # 필수 사양이 다 찼는데도 후보 승격이 안 된 상품이 core_part 대상 종류에서만
         # 98건 실측된다(카탈로그 적재가 review_required_yn만 재계산하고 ai_candidate_yn
         # 승격은 건드리지 않는 경로가 있다 — catalog_ingest.py 소관, 여기서 고치지
         # 않는다).
         "ok": bool(r["ai_candidate_yn"]) and not r["review_required_yn"],
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

    # ── verdict: 한 문장 요약(하위호환) ─────────────────────────────────
    # **gate와 같은 원천·같은 순서에서 고른다.** 예전엔 이 elif 사슬이 gate와 따로
    # 놀아 서로 다른 조건·다른 순서로 판정했다 — review 자리가 특히 그랬다(위
    # gate "review" 항목과 어긋난 채 원시 pending 값을 1순위로 봤다). 지금은
    # blocked[0](gate 배열 순서상 첫 미통과 항목 — gate_first와 동일 기준)을
    # 그대로 문장으로 옮긴다. 여러 사유가 동시에 걸려도 **하나만** 말하는 것은
    # 그대로 유지한다 — 전부 말하는 건 이미 gate_blocked·gate_note·gate_first가
    # 한다(슬라이스 95), verdict는 하위호환 한 줄 요약이라 화면 자리를 늘리지 않는다.
    if in_pool:
        verdict = "추천 가능 재고에 있습니다."
    elif not blocked:
        # gate 6개가 전부 통과인데 in_pool은 아닌 경우 — 뷰의 data_origin='demo'
        # 제외처럼 gate가 못 담는 조건일 수 있다(2026-08-24 실측 20건, 전부 데모
        # 상품). 없는 사유를 지어내지 않고 조건 미충족만 말한다.
        verdict = "추천 조건을 아직 만족하지 않습니다."
    else:
        first_key = blocked[0]["key"]
        if first_key == "category":
            verdict = "부품 분류가 아니라 추천 대상이 아닙니다."
        elif first_key == "spec_row":
            verdict = "사양 정보가 없어 추천에서 빠져 있습니다(적재에서 부품 종류를 못 정함)."
        elif first_key == "review":
            if r["review_required_yn"] and pending:
                verdict = f"사양 검수가 남아 추천에서 빠져 있습니다(대기 {pending}건)."
            elif r["review_required_yn"]:
                # 등록 직후 등 검수 행 자체가 아직 없는 경우(derive_status 독스트링의
                # ①과 같은 사례) — 없는 건수를 "(대기 0건)"으로 지어내지 않는다.
                verdict = "사양 검수가 필요해 추천에서 빠져 있습니다."
            else:
                # review_required_yn은 이미 false(검수는 끝남) — ai_candidate_yn만
                # 아직 false인 경우. "사양 검수가 남았다"고 하면 거짓말이 된다.
                verdict = "추천 후보로 지정되지 않아 추천에서 빠져 있습니다."
        elif first_key == "price":
            verdict = "판매가가 없어 추천에서 빠져 있습니다."
        elif first_key == "status":
            # 상태로 빠진 것을 "조건 미달"로 뭉뚱그리면 운영자가 원인을 못 찾는다
            verdict = f"판매 상태가 '{r['status']}'이라 추천에서 빠져 있습니다."
        elif first_key == "stock":
            verdict = "재고가 없어 추천에서 빠져 있습니다."
        else:
            verdict = "추천 조건을 아직 만족하지 않습니다."  # 안전망 — gate 키가 늘어날 때 대비
    return {
        "product_code": r["product_code"], "sku": r["sku"], "name": r["product_name"],
        "maker": r["maker"], "model_name": r["model_name"],
        "part_type": r["part_type"], "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
        "category_group": r["category_group"], "status": r["status"],
        # 목록(items[].status_key)과 같은 값·같은 판정 함수 — 결함 ⓐ-3
        "status_key": status_key,
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
                       "state": s["supply_state"], "state_raw": s["mall_state_raw"],
                       "at": iso(s["updated_at"]),
                       # 몰 수집 칸 — 전부 NULL 가능(옛 엑셀 유입행, 0066 마이그레이션 주석)
                       "mall_rank": s["mall_rank"],
                       "rebate_pct": _finite_or_none(s["rebate_pct"]),
                       "rebate_price": s["rebate_price"],
                       "fetched_at": iso(s["fetched_at"]),
                       # 공급처(업체) 단위 연락처 — suppliers 조인. 발주할 때 필요하다는
                       # 사장님 명시 지시(2026-08-26)로 연다. 로그에는 남기지 않는다.
                       "contact_name": s["contact_name"], "contact_phone": s["contact_phone"],
                       "order_phone": s["order_phone"], "contact_raw": s["contact_raw"],
                       "contact_fetched_at": iso(s["contact_fetched_at"])}
                      for s in sups],
        # "살 수 있는 최저가" — 없으면(전부 품절/문의) null. 화면은 null일 때
        # "판매 가능한 공급처가 없다"고 말하고 절대 품절가를 최저가로 대신 쓰지 않는다.
        "cheapest_available": cheapest_available,
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
        # **원천은 in_pool이다 — blocked가 비었다고 후보인 게 아니다**
        # (2026-08-24 결함 수정). 예전엔 `not blocked`만 보고 "견적에 나갈 수
        # 있습니다"를 냈는데, gate 6개는 v_recommendation_candidates의 WHERE를
        # 옮겨 적은 것일 뿐이라 뷰가 보는데 gate가 못 담는 조건(data_origin='demo'
        # 등, 실측 20건)이 있으면 "gate 전부 통과인데 in_pool=false"인 상품이
        # 생긴다 — 그 상품에서 이 배너가 "견적 가능"을 말하고 같은 응답의
        # verdict는 "조건 미충족"을 말해 서로 반대말을 했다. 지금은 위 verdict와
        # **같은 순서·같은 기준**(in_pool -> blocked -> 그 외)으로 판정하고,
        # 마지막 갈래(gate는 다 통과했지만 in_pool은 아닌 경우)는 새 문장을 짓지
        # 않고 verdict를 그대로 재사용한다 — 문구를 두 곳에 따로 적으면 다음에
        # 또 갈라진다.
        "gate_note": (
            "추천 가능 재고에 있습니다 — 견적에 나갈 수 있습니다" if in_pool
            else (f"추천 후보가 되려면 {len(blocked)}가지 남았습니다 — "
                  + " · ".join(g["label"] for g in blocked)) if blocked
            else verdict
        ),
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
            "SELECT product_code, sku, product_name, maker, supplier, purchase_price, sale_price,"
            " stock_qty, status, model_name, danawa_code, market_price, locked_fields"
            " FROM products WHERE product_code=:pc FOR UPDATE"),
            {"pc": product_code}).mappings().first()
        if cur is None:
            raise HTTPException(404, "상품이 없습니다")

        # danawa_code 는 부분 UNIQUE 라 남의 코드를 넣으면 23505 로 죽는다 — 그러면
        # 운영자에게는 "500 오류"만 보인다. **누가 이미 쓰고 있는지**를 먼저 찾아
        # 그 상품코드와 이름을 함께 말한다(찾아가 고칠 수 있어야 한다).
        # 시세 관측이 이 컬럼 하나로 이어지므로 조용히 덮게 두면 안 된다.
        if "danawa_code" in parsed:
            _, newdc = parsed["danawa_code"]
            if newdc is not None and newdc != cur["danawa_code"]:
                dup = conn.execute(text(
                    "SELECT product_code, product_name FROM products"
                    " WHERE danawa_code = :d AND product_code <> :pc LIMIT 1"),
                    {"d": newdc, "pc": product_code}).mappings().first()
                if dup:
                    raise HTTPException(409, {
                        "error": "danawa_code_taken",
                        "detail": f"다나와 코드 {newdc} 는 이미 상품 {dup['product_code']}"
                                  f"({dup['product_name'][:40]})가 쓰고 있습니다"
                                  " — 한 코드는 한 상품에만 붙습니다.",
                        "taken_by": dup["product_code"]})

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

        # ── 가격을 고치면 이력에 남긴다 (결함 발견 2026-08-15) ──────────────────
        # 여기서 sale_price·purchase_price를 바꿀 수 있는데 product_price_history에
        # 아무것도 남지 않았다 — 위 stock_qty와 같은 병이다(슬라이스 97). 실측 증거:
        # 상품 119253을 판매가 관리에서 853,200→904,700으로 맞춘 뒤(이력 O, reason
        # manual_match) 이 PATCH로 904,700→853,200으로 되돌리자(이력 X) 원장 마지막
        # 행이 904,700을 가리키는데 실제 값은 853,200인 상태가 됐다 — 원장이 거짓을
        # 말한다. 상품 46158도 같은 증상(판매가 관리 제작자가 먼저 지목).
        #
        # reason은 새로 만들지 않고 기존 8종 중 'manual'을 쓴다 — 가격 검토 화면의
        # price_review_decide 로그(활동 로그 79)가 이미 이 값을 "운영자가 직접 값을
        # 넣었다"는 뜻으로 쓰고 있고, 여기도 정확히 그 뜻이다(재산정·단가표 반영처럼
        # 자동 계산이 아니라 사람이 상세 화면에서 직접 입력).
        #
        # 2026-08-15 후속(사장님 확정 — new_price를 비울 수 있게, 마이그레이션 0050):
        # 예전엔 "new_price가 NOT NULL이니 값을 지우는(빈 문자열 -> NULL) 패치는
        # 이 표에 못 담는다"며 건너뛰었다 — "products.sale_price 자체는 정상적으로
        # NULL이 되고 활동 로그에 남으니 괜찮다"고 판단했는데 틀렸다. 확인자가 데모
        # 상품 93720으로 재현: PATCH sale_price="" 가 changed:1로 성공해도 이 표엔
        # 행이 0개였고, 그동안 가격 이력 화면은 마지막 기록(예: 16,501원)을 지금
        # 가격인 것처럼 보여준다 — 실제로는 비어 있는데도. ERD §6 원칙 3("모든 가격
        # 변경을 기록한다")이 깨지는 사례였다(원장 공백). 이제는 값을 지우는 것도
        # 그대로 기록한다 — `k in after`만으로 충분하다: 위에서 `before[k] == v`인
        # 필드는 이미 걸러(572-573행) `after`에 실제로 값이 바뀐 필드만 남으므로,
        # NULL -> NULL(변경 아님)은 애초에 이 루프에 들어오지 않는다.
        for k, field in PRICE_HISTORY_FIELD.items():
            if k in after:
                conn.execute(text(
                    "INSERT INTO product_price_history"
                    " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                    " VALUES (:pc, :f, :old, :new, 'manual', :ref, :op)"),
                    {"pc": product_code, "f": field, "old": before[k], "new": after[k],
                     "ref": log_id, "op": current_operator_id()})

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
        # 가격을 되돌리면 이력도 역방향 행으로 남긴다 — 바로 위 재고와 같은 이유
        # (결함 발견 2026-08-15, PRICE_HISTORY_FIELD 정의부 참고). 되돌린 뒤의 값은
        # chg[k]["from"], 되돌리기 직전 값은 chg[k]["to"]다.
        #
        # 2026-08-15 후속(마이그레이션 0050): 예전엔 new_price가 NOT NULL이라 "값을
        # 지우는 패치"를 되돌리는 경우(from이 NULL — 원래 비어 있던 필드에 값을
        # 넣었다가, 그 되돌리기로 다시 비우는 경우)를 이 표에 못 담아 건너뛰었다.
        # 그러면 products.{field}는 UPDATE로 정상 NULL이 되는데 이 표의 마지막
        # 행은 여전히 지워지기 전 값을 가리켜 원장이 어긋난다 — patch_product
        # 쪽 결함과 같은 모양이다(가격 원장 드리프트, tests/regression.py). 이제는
        # 건너뛰지 않는다. old_v != new_v는 항상 보장된다 — chg[k]는
        # patch_product가 `before[k] != after[k]`인 필드만 `changes`에 남긴
        # 결과이므로 "값이 안 바뀐" 되돌리기 행은 애초에 여기 들어오지 않는다.
        for k, field in PRICE_HISTORY_FIELD.items():
            if k in chg:
                new_v, old_v = chg[k].get("from"), chg[k].get("to")
                conn.execute(text(
                    "INSERT INTO product_price_history"
                    " (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
                    " VALUES (:pc, :f, :old, :new, 'manual', :ref, :op)"),
                    {"pc": pc, "f": field, "old": old_v, "new": new_v,
                     "ref": log_id, "op": current_operator_id()})
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

    # `product_supplier_prices.cost_price` 는 **NOT NULL** 이다. 그런데 이 API 는
    # `int | None` 을 받고 화면 입력창은 "비워 두면 가격 미확인"이라 안내하고 있었다 —
    # 지킬 수 없는 약속이라 비워서 저장하면 **500** 이 났다(2026-08-05 사용자 신고).
    # 500 은 운영자에게 아무것도 알려주지 않는다. 왜 안 되는지 먼저 말한다.
    if body.cost_price is None:
        raise HTTPException(400, "매입가를 입력하세요 — 가격 없이 공급처만 등록할 수는 없습니다")
    if body.cost_price < 0:
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

CORE_PARTS = set(CORE_TYPES)   # taxonomy가 단일 원천 — 두 벌이던 것을 합쳤다(슬라이스 A)
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
    import json as _json

    from .admin_orders import _log

    new_pt = (body.part_type or "").strip()
    if new_pt not in PART_TYPE_LABELS:
        raise HTTPException(400, "알 수 없는 분류입니다")

    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT product_code, sku, product_name, part_type, category_group,"
            " ai_candidate_yn, review_required_yn, sale_price, stock_qty, status,"
            " locked_fields"
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

        # 분류·게이트 결과를 잠근다(2026-08-16 — 사장님 지시: 잠금을 사양·분류·검수
        # 플래그까지 넓힌다). 안 그러면 다음 재적재가 그대로 되돌린다 — 실사고 둘:
        # ① 0031이 완제품·베어본을 ETC에서 올려놓은 뒤 08-15 몰 적재가 340건을 다시
        # ETC로 되돌렸다 ② 123034는 검수로 회부된 채(review_id=8193, 대기)인데
        # 적재가 review_required_yn을 재계산해 후보로 되돌렸다. 이 UPDATE가 실제로
        # 쓰는 네 컬럼을 그대로 잠근다 — part_type·category_group은 이 결정 자체이고,
        # ai_candidate_yn·review_required_yn은 그 결정을 근거로 지금 계산한 게이트
        # 결과다. 사양을 나중에 채우면(patch_product_specs) 그 경로가 잠금과 무관하게
        # 직접 재승격하므로 이후 교정 경로는 막히지 않는다 — apply_plan(catalog_ingest)의
        # UPSERT만 이 잠금을 존중한다.
        locked = list(r["locked_fields"] or [])
        for col in ("part_type", "category_group", "ai_candidate_yn", "review_required_yn"):
            if col not in locked:
                locked.append(col)
        conn.execute(text(
            "UPDATE products SET part_type=:pt, category_group=:g,"
            " ai_candidate_yn = CASE WHEN :ok THEN true ELSE false END,"
            " review_required_yn = CASE WHEN :ok THEN false ELSE true END,"
            " locked_fields = CAST(:lf AS JSONB),"
            " updated_at=now() WHERE product_code=:pc"),
            {"pt": new_pt, "g": new_group, "ok": will_pool, "pc": product_code,
             "lf": _json.dumps(locked, ensure_ascii=False)})
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
                                  "review_required_yn": r["review_required_yn"],
                                  "locked_fields": list(r["locked_fields"] or [])},
                       "closed": closed, "opened": opened}, kind="product")
        now_pool = conn.execute(text(
            "SELECT 1 FROM v_recommendation_candidates WHERE product_code=:pc"
            " AND stock_qty>0"), {"pc": product_code}).first() is not None

    return {"ok": True, "impact": impact, "reviews_closed": closed,
            "reviews_opened": opened, "in_pool": now_pool, "undo_id": log_id,
            "locked_fields": locked,
            "note": ("분류를 " + impact["to"]["label"] + "로 바꿨습니다."
                     + (" 검수 " + str(closed) + "건이 해소되고" if closed else "")
                     + (" " + str(opened) + "건이 새로 올라왔습니다." if opened else
                        (" 추천 후보에 올랐습니다." if now_pool else ""))
                     + " 분류·게이트는 잠겼습니다 — 다음 적재가 덮지 않습니다.")}


@router.post("/products/part-type/undo/{log_id}")
def undo_part_type(log_id: int):
    """분류 변경 되돌리기 — 분류·그룹·게이트·잠금 상태를 함께 되돌린다."""
    import json as _json

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
        # 잠금도 변경 전 상태로 되돌린다 — 값만 원복하고 잠금이 남으면 적재가 영영
        # 못 채운다(CLAUDE.md §관리자 화면 규약: "되돌릴 때 잠금도 함께 되돌린다").
        conn.execute(text(
            "UPDATE products SET part_type=:pt, category_group=:g,"
            " ai_candidate_yn=:ac, review_required_yn=:rr,"
            " locked_fields = CAST(:lf AS JSONB), updated_at=now()"
            " WHERE product_code=:pc"),
            {"pt": d.get("from"), "g": b.get("category_group"),
             "ac": b.get("ai_candidate_yn", False),
             "rr": b.get("review_required_yn", True),
             "lf": _json.dumps(b.get("locked_fields") or [], ensure_ascii=False), "pc": pc})
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


# ─────────────────────────── 목록 일괄 상태 변경 ───────────────────────────
# 상품 목록에는 **일괄 선택이 없었다**(2026-08-05 실측 — `category-mapping` 한 곳뿐).
# Phoenix 원본(`apps/e-commerce/admin/products.html`)은 첫 열이 선택 체크박스이고
# 우리는 그 컴포넌트를 갖고 있으면서 목록 화면에 쓰지 않고 있었다.
#
# 일괄 선택만 붙이면 **아무 일도 못 하는 체크박스**가 된다. 그래서 실제 동작 하나를
# 함께 준다: 상태 일괄 변경. 오늘 나온 필요가 근거다 — 완제품 208건처럼 성격이 같은
# 덩어리를 한 번에 세우거나 내려야 할 때 지금은 한 건씩 눌러야 한다.
#
# 규약은 이미 검증된 `category-mapping/move` 를 그대로 따른다:
#   · 바꾸기 **전 상태를 읽어** 로그에 담는다 — 부분 되돌리기도 정확해진다
#   · 이미 그 상태인 것은 대상에서 뺀다(로그를 부풀리지 않는다)
#   · 상한을 숨기지 않는다 — 넘으면 몇 건이 빠졌는지 응답이 밝힌다
#   · 되돌리기는 삭제가 아니라 역방향 전이이고 `ref_log_id` 로 원 기록을 가리킨다
#
# **잠긴 상태는 건드리지 않는다** — 운영자가 손으로 정한 값을 일괄 작업이 덮으면
# 어제 고친 것이 오늘 사라진다(A-16의 짝, 재산정이 잠긴 판매가를 세기만 하는 것과 같다).
MAX_BULK = 2000


class BulkStatusBody(BaseModel):
    product_codes: list[int]
    status: str


def _bulk_operator():
    from .auth import current_operator

    me = current_operator() or {}
    if me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 일괄 변경할 수 있습니다")
    return me


def _pool_count(conn) -> int:
    return conn.execute(text(
        "SELECT count(*) FROM v_recommendation_candidates WHERE stock_qty > 0")).scalar_one()


@router.post("/products/bulk-status")
def bulk_status(body: BulkStatusBody):
    from .admin_orders import _log

    _bulk_operator()
    if body.status not in STATUS_OK:
        raise HTTPException(400, "상태는 " + " · ".join(STATUS_OK) + " 중 하나입니다")
    codes = list(dict.fromkeys(body.product_codes or []))
    if not codes:
        raise HTTPException(400, "상품을 선택하세요")
    dropped = 0
    if len(codes) > MAX_BULK:
        dropped = len(codes) - MAX_BULK
        codes = codes[:MAX_BULK]

    with engine.begin() as conn:
        before = conn.execute(text(
            "SELECT product_code, status, locked_fields FROM products"
            " WHERE product_code = ANY(:c)"), {"c": codes}).mappings().all()
        if not before:
            raise HTTPException(404, "해당 상품을 찾을 수 없습니다")
        missing = len(codes) - len(before)

        locked = [r for r in before if "status" in (r["locked_fields"] or [])]
        targets = [r for r in before
                   if r["status"] != body.status and r not in locked]
        if not targets:
            raise HTTPException(400, "바꿀 것이 없습니다 — 이미 모두 그 상태이거나 잠겨 있습니다")

        pool_before = _pool_count(conn)
        conn.execute(text(
            "UPDATE products SET status = :s, updated_at = now()"
            " WHERE product_code = ANY(:c)"),
            {"s": body.status, "c": [r["product_code"] for r in targets]})
        pool_after = _pool_count(conn)

        log_id = _log(conn, "상품 상태 일괄 변경", body.status, {
            "to": body.status, "changed": len(targets), "locked": len(locked),
            "pool_before": pool_before, "pool_after": pool_after,
            # 되돌리기용 — 상품별 원래 상태
            "before": [{"pc": r["product_code"], "st": r["status"]} for r in targets],
        }, kind="product")

    # **건수가 아니라 영향을 말한다** — 상태는 추천 후보 게이트를 직접 건드린다.
    delta = pool_after - pool_before
    msg = f"{len(targets):,}건을 '{body.status}'(으)로 바꿨습니다"
    if delta:
        msg += f" · 추천 후보 {abs(delta):,}건이 " + ("늘었습니다" if delta > 0 else "줄었습니다")
    if locked:
        msg += f" · 잠긴 {len(locked):,}건은 그대로 뒀습니다"
    if dropped:
        msg += f" · 상한 {MAX_BULK:,}건을 넘어 {dropped:,}건은 건너뛰었습니다"
    if missing:
        msg += f" · 없는 상품 {missing:,}건은 건너뛰었습니다"
    return {"verdict": msg, "changed": len(targets), "locked": len(locked),
            "dropped": dropped, "missing": missing,
            "pool_before": pool_before, "pool_after": pool_after, "log_id": log_id}


class BulkUndoBody(BaseModel):
    log_id: int


@router.post("/products/bulk-status/undo")
def bulk_status_undo(body: BulkUndoBody):
    from .admin_orders import _log

    _bulk_operator()
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT detail, action FROM admin_operator_activity_logs WHERE log_id = :i"),
            {"i": body.log_id}).mappings().first()
        if row is None or row["action"] != "상품 상태 일괄 변경":
            raise HTTPException(404, "되돌릴 기록을 찾을 수 없습니다")
        dup = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs"
            " WHERE detail->>'ref_log_id' = CAST(:i AS TEXT)"), {"i": body.log_id}).first()
        if dup:
            raise HTTPException(409, "이미 되돌린 기록입니다")

        detail = row["detail"] or {}
        before = detail.get("before") or []
        if not before:
            raise HTTPException(400, "되돌릴 내역이 비어 있습니다")
        for b in before:
            conn.execute(text(
                "UPDATE products SET status = :s, updated_at = now()"
                " WHERE product_code = :pc"), {"s": b["st"], "pc": b["pc"]})
        _log(conn, "상품 상태 일괄 변경 되돌림", str(body.log_id),
             {"ref_log_id": body.log_id, "restored": len(before)}, kind="product")
    return {"verdict": f"{len(before):,}건의 상태를 되돌렸습니다", "restored": len(before)}
