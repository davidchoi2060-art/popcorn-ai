"""ADM-PRD-020 검수 큐 — 읽기 + 첫 쓰기 이음새 (처리/되돌리기/일괄 확정).

승인 전이(ERD §8 T2): specs 값 반영 → (잔여 0건이면) verified → locked_fields 등록
→ review_required 재산정(필수 충족 ∧ 잔여 0) → true→false 전이 시에만 ai_candidate 승격.
"""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .timeutil import iso
from .admin_products import PART_TYPE_LABELS, required_fields
from .db import engine

router = APIRouter(prefix="/api/admin")

# 작업 기록 주체 = 세션 운영자(슬라이스 37). 세션 없는 경로는 시드 운영자(1)로 폴백.
from .auth import current_operator_id


# ERD §7.3 호환성 치명 필드 (목업 CRIT_CONFLICT와 다름 — ERD 우선 채택, 의도된 차이)
CRITICAL_FIELDS = {"length_mm", "gpu_max_mm", "rated_watt", "socket"}

# 검수 처리 가능한 specs 컬럼 화이트리스트 + SQL 캐스트 타입.
# 컬럼명은 이 딕셔너리를 통해서만 SQL에 삽입된다(ports JSONB는 제외 — 구조 편집은 별도 화면).
FIELD_CAST = {
    **{f: "INTEGER" for f in (
        "length_mm", "rated_watt", "refresh_hz", "capacity_gb", "clock_mhz",
        "tdp_watt", "required_power_watt", "gpu_max_mm", "cooler_height_mm", "cooler_tdp")},
    "size_inch": "NUMERIC(4,1)",
    **{f: "VARCHAR" for f in (
        "socket", "chipset", "mem_type", "form_factor", "interface", "pcie_gen",
        "resolution", "panel", "switch_type", "key_layout", "connection")},
    # 목록형 사양(JSONB). 승인 대상에서 빠져 있어 케이스 규격·쿨러 소켓을 확정할 수
    # 없었다 — 검수 제안의 41%가 이 두 필드다(슬라이스 51).
    **{f: "JSONB" for f in ("form_factor_list", "socket_list")},
}
# JSONB 필드는 값이 JSON 배열 문자열이어야 한다 — 화면·수집기가 보내는 표기를 맞춘다
JSON_FIELDS = {"form_factor_list", "socket_list"}


def _risk(review_type: str, field: str | None) -> str:
    if review_type == "spec_conflict" and field in CRITICAL_FIELDS:
        return "치명"
    if review_type in ("spec_conflict", "spec_missing"):
        return "주의"
    return "경미"


def _crit(part_type: str, target_field: str | None, review_type: str, specs: dict | None):
    out = []
    for f in required_fields(part_type):
        if f == target_field:
            out.append({"field": f, "value": "불일치" if review_type == "spec_conflict" else "미확인", "ok": False})
        else:
            v = specs.get(f) if specs else None
            out.append({"field": f, "value": "미확인" if v is None else str(v), "ok": True if v is not None else None})
    return out


@router.get("/reviews")
def list_reviews(page: int = 1, size: int = 100, part_type: str = "", origin: str = "",
                 sellable: int = 0, suggested: int = 0, field: str = ""):
    """검수 큐 — 실데이터 적재 후 대기 건수가 수천이 되므로 서버 페이지네이션이 필수다(슬라이스 39).

    단가표發 편입 대기(sourcing_hold)는 **파생 목록**이라 페이지네이션 밖이다 —
    항목 수가 공급처 최신 파일 규모(수백)로 제한되므로 1페이지에만 덧붙인다.

    `suggested=1`이면 **외부 제안이 붙은 것만** — 승인/기각 판단만 하면 되는 목록이다.
    제안이 몇십 건인데 큐가 수천 건이면 화면에서 찾을 방법이 없다(슬라이스 52).

    `sellable=1`이면 **판매중 ∧ 재고>0** 상품만 — 지금 매출에 영향을 주는 것부터 본다
    (슬라이스 49: 6,490건 중 1,720건. 나머지는 팔 수도 없는 상품이라 급하지 않다).

    `field=cooler_tdp`처럼 **한 사양만** 볼 수 있다(슬라이스 85). 화면은 종류별 집계를
    이미 보여주면서 그걸로 좁힐 방법이 없었다 — 큐가 5,000건인데 "쿨러 발열 한도 350건을
    오늘 끝내겠다"는 작업을 시작할 수가 없었다. 같은 사양을 연달아 보면 판단 기준이
    유지되고, 자료를 한 번 펼쳐 놓고 처리할 수 있다.
    """
    size = max(1, min(size, 500))
    page = max(1, page)
    q = text("""
        SELECT r.review_id, r.product_code, r.review_type, r.field_name, r.detail,
               r.origin_value, r.suggested_value, r.confidence, r.created_at,
               p.sku, p.product_name, p.part_type, to_jsonb(ps) AS specs
        FROM product_reviews r
        JOIN products p USING (product_code)          -- product_code NULL(csv_error류)은 자연 제외
        LEFT JOIN product_specs ps USING (product_code)
        WHERE r.review_status = '대기'
          AND (:part_type = '' OR p.part_type = :part_type)
          AND (:origin = '' OR p.data_origin = :origin)
          AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
          AND (:suggested = 0 OR r.suggested_value IS NOT NULL)
          AND (:field = '' OR r.field_name = :field)
        ORDER BY r.created_at, r.review_id
        LIMIT :size OFFSET :offset
    """)
    qc = text("""
        SELECT count(*) FROM product_reviews r JOIN products p USING (product_code)
         WHERE r.review_status = '대기'
           AND (:part_type = '' OR p.part_type = :part_type)
           AND (:origin = '' OR p.data_origin = :origin)
           AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
           AND (:suggested = 0 OR r.suggested_value IS NOT NULL)
           AND (:field = '' OR r.field_name = :field)
    """)
    # 종류별 집계는 **지금 보고 있는 범위**를 따른다. 필터를 켰는데 전체 분포를 보여주면
    # 화면의 숫자와 배너의 숫자가 다른 말을 한다(슬라이스 49). part_type 필터만 제외한다 —
    # 자기 자신으로 거르면 한 종류만 남아 집계의 뜻이 없어진다.
    qg = text("""
        SELECT p.part_type, count(*) n FROM product_reviews r JOIN products p USING (product_code)
         WHERE r.review_status = '대기'
           AND (:origin = '' OR p.data_origin = :origin)
           AND (:sellable = 0 OR (p.status = '판매중' AND p.stock_qty > 0))
           AND (:suggested = 0 OR r.suggested_value IS NOT NULL)
         GROUP BY 1 ORDER BY 2 DESC
    """)
    # 큐 구성 — "6,490건"만 보여주면 운영자는 언젠가 처리하면 줄어들 줄 안다.
    # 실제로는 대부분이 **원문에 값 자체가 없어** 일괄 확정이 불가능한 항목이다(슬라이스 49).
    # 무엇이 손댈 수 있는 일이고 무엇이 사람 손이 필요한 일인지 화면이 구분해 말해야 한다.
    # bulkable은 **일괄 확정 API가 실제로 처리하는 조건과 같아야 한다**
    # (bulk_confirm: review_type='low_confidence' ∧ origin_value IS NOT NULL).
    # '값이 있는 것' 전부를 세면 버튼이 처리하지 못하는 수를 약속하게 된다.
    qs = text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE r.origin_value IS NOT NULL
                                  AND r.review_type = 'low_confidence') AS bulkable,
               count(*) FILTER (WHERE r.origin_value IS NOT NULL
                                  AND r.review_type <> 'low_confidence') AS single,
               count(*) FILTER (WHERE r.origin_value IS NULL) AS manual,
               count(*) FILTER (WHERE p.status = '판매중' AND p.stock_qty > 0) AS sellable,
               -- 외부 제안이 붙어 승인/기각 판단만 하면 되는 것(슬라이스 52)
               count(*) FILTER (WHERE r.suggested_value IS NOT NULL) AS suggested
        FROM product_reviews r JOIN products p USING (product_code)
        WHERE r.review_status = '대기'
    """)
    qf = text("""
        SELECT r.field_name, count(*) n,
               count(*) FILTER (WHERE p.status = '판매중' AND p.stock_qty > 0) sell
        FROM product_reviews r JOIN products p USING (product_code)
        WHERE r.review_status = '대기' AND r.field_name IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT 12
    """)
    p = {"part_type": part_type.strip(), "origin": origin.strip(),
         "field": field.strip(),
         "sellable": 1 if sellable else 0, "suggested": 1 if suggested else 0,
         "size": size, "offset": (page - 1) * size}
    with engine.connect() as conn:
        rows = conn.execute(q, p).mappings().all()
        total = conn.execute(qc, p).scalar_one()
        by_type = [{"part_type": r[0], "label": PART_TYPE_LABELS.get(r[0], r[0]), "n": r[1]}
                   for r in conn.execute(qg, p).all()]
        s = conn.execute(qs).mappings().first()
        by_field = [{"field": r[0], "n": r[1], "sellable": r[2]}
                    for r in conn.execute(qf).all()]
    items = [{
        "review_id": r["review_id"],
        "sku": r["sku"],
        "name": r["product_name"],
        "cat": PART_TYPE_LABELS.get(r["part_type"], r["part_type"]),
        "part_type": r["part_type"],
        "type": r["review_type"],
        "field": r["field_name"],
        "detail": r["detail"],
        "origin_value": r["origin_value"],
        "suggested_value": r["suggested_value"],
        # 제안값의 출처를 밝힌다 — 다나와에서 온 값을 'AI 지식'이라 부르면 거짓이다
        # (슬라이스 51). 스키마 무개정이라 detail의 표기에서 파생한다.
        "suggest_source": ("danawa" if "다나와 제안" in (r["detail"] or "") else
                           ("ai" if r["suggested_value"] is not None else None)),
        "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
        "created_at": iso(r["created_at"]),
        "risk": _risk(r["review_type"], r["field_name"]),
        "crit": _crit(r["part_type"], r["field_name"], r["review_type"], r["specs"]),
    } for r in rows]
    if page == 1 and not part_type and not sellable and not suggested and not field:
        items.extend(_sourcing_items())
    # 오늘 내가 처리한 건수 — **서버가 센다**(슬라이스 96).
    # 화면은 `let done = 0`이라는 JS 변수로 세고 있었다. 새로고침하면 0이 되므로
    # 하루 종일 검수하다 F5를 누르면 성과가 사라졌고, 무엇보다 라벨이 '오늘 처리'인데
    # 실제로는 '이 페이지를 연 뒤 처리'였다 — 화면이 사실과 다른 것을 말하고 있었다.
    #
    # **'오늘'은 서울 기준이다.** DB는 UTC로 돌고 `reviewed_at`은 naive UTC다.
    # `date_trunc('day', now())`를 그대로 쓰면 UTC 자정(= 09:00 KST)이 경계가 되어,
    # 오전 8시에 출근한 운영자는 어제 저녁 작업이 '오늘'로 잡히고 9시가 되기 전까지
    # 자기 오전 작업은 안 잡힌다. 사람에게 보여주는 '오늘'은 그 사람의 오늘이어야 한다.
    #   now() AT TIME ZONE 'Asia/Seoul'        -> 서울 벽시계
    #   date_trunc('day', ...)                 -> 서울 자정(naive)
    #   ... AT TIME ZONE 'Asia/Seoul'          -> 그 순간의 절대시각
    #   ... AT TIME ZONE 'UTC'                 -> naive UTC (reviewed_at과 같은 축)
    with engine.connect() as conn:
        me = current_operator_id()
        my_today = conn.execute(text(
            "SELECT count(*) FROM product_reviews"
            " WHERE reviewed_by = :me AND reviewed_at >="
            "   (date_trunc('day', now() AT TIME ZONE 'Asia/Seoul')"
            "      AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'UTC'"),
            {"me": me}).scalar_one() if me else 0

    return {"items": items, "page": page, "size": size, "total": total,
            "pages": (total + size - 1) // size, "by_type": by_type,
            # 지금 걸린 필터에서 남은 수. 화면의 큰 숫자가 이걸 써야 한다 —
            # 예전에는 현재 페이지 길이(최대 100)를 '남은 N건'으로 띄웠다.
            "remaining": total,
            "my_today": my_today,
            "field": field.strip(),        # 화면이 지금 무엇으로 좁혔는지 되돌려 말한다
            "queue": {
                "total": s["total"],
                "bulkable": s["bulkable"],      # 일괄 확정 버튼이 실제로 처리하는 수
                "single": s["single"],          # 값은 있지만 단건 검수 강제(치명·주의)
                "manual": s["manual"],          # 원문에 값이 없다 — 사람이 찾아 넣어야 한다
                "sellable": s["sellable"],      # 판매중 ∧ 재고>0 — 지금 매출에 영향
                "suggested": s["suggested"],    # 외부 제안 대기 — 승인/기각만 하면 된다
                "by_field": by_field,
                "verdict": (
                    f"대기 {s['total']:,}건 중 일괄 확정으로 끝낼 수 있는 건 {s['bulkable']:,}건, "
                    f"값은 있지만 단건 검수가 필요한 건 {s['single']:,}건입니다. "
                    f"나머지 {s['manual']:,}건은 원문에 값이 없어 사람이 사양을 찾아 넣어야 합니다"
                    f" — 재파싱(respec)으로는 더 회수되지 않습니다. "
                    f"지금 매출에 영향을 주는 건 판매중·재고 있는 {s['sellable']:,}건입니다."
                ),
            },
            "note": ("검수 대기는 서버에서 나눠 보냅니다 — by_type·queue는 전체 집계입니다."
                     " 단가표發 편입 대기는 파생 목록이라 1페이지에만 붙습니다."
                     " sellable=1이면 판매중·재고>0만, suggested=1이면 외부 제안이 붙은 것만 봅니다.")}


# ---- 슬라이스 16: 단가표 신규(sourcing_hold) — 저장 없는 파생 큐 ----
# 공급처별 최신 파일의 미매칭 행(map 무 ∧ danawa 불일치)을 편입 대기 항목으로 파생.
# 연결·등록이 supplier_product_map을 쓰면 파생 조건에서 자연 소멸(상태 테이블 불필요·멱등).
# 시트·칩셋은 스냅샷에 미저장(스키마 무개정) — 화면 '—' 정직 표시, 컬럼화·페이지네이션 이관.
SIM_THRESHOLD = 0.3  # admin_price_import._file_diff와 동일 규칙


def _sourcing_items():
    q = text("""
        SELECT r.row_id, r.model_name, r.danawa_code, r.cost_price, r.supply_state, r.memo,
               f.supplier_id, f.file_name, f.received_at, s.name AS sup_name,
               c.sku AS cand_sku, c.product_name AS cand_name, c.sim AS cand_sim
        FROM (SELECT DISTINCT ON (supplier_id) file_id, supplier_id, file_name, received_at
              FROM supplier_price_files ORDER BY supplier_id, received_at DESC) f
        JOIN suppliers s USING (supplier_id)
        JOIN supplier_price_rows r USING (file_id)
        LEFT JOIN supplier_product_map m
               ON m.supplier_id = f.supplier_id AND m.model_key = r.model_name
        LEFT JOIN LATERAL (
          -- similarity(a,b) > th 형태는 trgm GIN 인덱스를 타지 못한다
          -- (24,303행 × 단가표 308행 = 이 화면 1페이지가 247초 걸렸다 — 슬라이스 39 실측).
          -- trgm 유사도 연산자는 인덱스를 쓴다. 임계값은 위 set_limit()으로 명시한다.
          SELECT p.sku, p.product_name, similarity(r.model_name, p.product_name) AS sim
          FROM products p WHERE p.product_name % r.model_name
          ORDER BY sim DESC LIMIT 1
        ) c ON true
        WHERE m.map_id IS NULL
          AND (r.danawa_code IS NULL
               OR NOT EXISTS (SELECT 1 FROM products p2 WHERE p2.danawa_code = r.danawa_code))
        ORDER BY f.supplier_id, r.row_id
    """)
    with engine.connect() as conn:
        # 유사도 임계값을 세션에 고정 — `%` 연산자가 이 값을 쓴다(코드와 DB 판정을 일치시킨다).
        # SET 문은 파라미터를 받지 않으므로 pg_trgm의 set_limit() 함수를 쓴다.
        conn.execute(text("SELECT set_limit(:th)"), {"th": SIM_THRESHOLD})
        rows = conn.execute(q, {"th": SIM_THRESHOLD}).mappings().all()
    return [{
        "review_id": None, "sku": None, "type": "sourcing_hold",
        "src_row_id": r["row_id"], "supplier_id": r["supplier_id"],
        "name": r["model_name"], "cat": "미분류", "part_type": None,
        "field": None, "origin_value": None, "suggested_value": None, "confidence": None,
        "created_at": iso(r["received_at"]), "risk": "경미", "crit": [],
        "detail": ("단가표 신규 행 — 카탈로그에 같은 모델이 없습니다. 이름 유사 후보가 있어 연결 검토가 우선입니다."
                   if r["cand_sku"] else
                   "단가표 신규 행 — 유사 후보 없음. 취급하려면 신규 상품으로 등록하고 검수를 거칩니다."),
        "src": {"sup": r["sup_name"], "file": r["file_name"], "cost": r["cost_price"],
                "state": r["supply_state"], "memo": r["memo"],
                "danawa_code": r["danawa_code"]},
        "cand": ({"sku": r["cand_sku"], "name": r["cand_name"], "sim": float(r["cand_sim"])}
                 if r["cand_sku"] else None),
    } for r in rows]


class LinkBody(BaseModel):
    row_id: int
    sku: str
    via: str = "manual"  # candidate(유사 후보 채택 → similarity) | manual(SKU 직접 입력)


@router.post("/reviews/sourcing/link")
def sourcing_link(body: LinkBody):
    """편입 ①: 기존 상품에 연결 — map 등록만(psp·가격 무변경 — '다음 단가표부터 자동 매칭')."""
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT r.row_id, r.model_name, f.supplier_id FROM supplier_price_rows r"
            " JOIN supplier_price_files f USING (file_id) WHERE r.row_id=:i"),
            {"i": body.row_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "단가표 행이 없습니다")
        prod = conn.execute(text(
            "SELECT product_code, sku FROM products WHERE sku=:s"), {"s": body.sku.strip()}).mappings().first()
        if prod is None:
            raise HTTPException(404, f"상품이 없습니다: {body.sku}")
        method = "similarity" if body.via == "candidate" else "manual"
        map_id = conn.execute(text(
            "INSERT INTO supplier_product_map (supplier_id, model_key, product_code, match_method, confirmed_by, confirmed_at)"
            " VALUES (:s, :k, :pc, :m, :op, now())"
            " ON CONFLICT (supplier_id, model_key) DO NOTHING RETURNING map_id"),
            {"s": row["supplier_id"], "k": row["model_name"], "pc": prod["product_code"],
             "m": method, "op": current_operator_id()}).scalar()
        if map_id is None:
            raise HTTPException(409, "이미 연결된 모델입니다")
        log_id = _log(conn, "sourcing_link", row["model_name"][:100],
                      {"map_id": map_id, "row_id": row["row_id"], "supplier_id": row["supplier_id"],
                       "model_key": row["model_name"], "product_code": prod["product_code"],
                       "sku": prod["sku"], "method": method})
        return {"ok": True, "undo_id": log_id, "sku": prod["sku"]}


@router.post("/reviews/sourcing/unlink/{log_id}")
def sourcing_unlink(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:i"),
            {"i": log_id}).mappings().first()
        if log is None or log["action"] != "sourcing_link":
            raise HTTPException(404, "되돌릴 연결 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='sourcing_unlink' AND (detail->>'ref_log_id')::int=:i LIMIT 1"),
                {"i": log_id}).first():
            raise HTTPException(409, "이미 되돌린 연결입니다")
        d = log["detail"]
        m = conn.execute(text(
            "SELECT product_code, match_method FROM supplier_product_map WHERE map_id=:m FOR UPDATE"),
            {"m": d["map_id"]}).first()
        if m is None or m[0] != d["product_code"] or m[1] != d["method"]:
            raise HTTPException(409, "연결 이후 매핑이 변경되어 되돌릴 수 없습니다")
        conn.execute(text("DELETE FROM supplier_product_map WHERE map_id=:m"), {"m": d["map_id"]})
        _log(conn, "sourcing_unlink", str(log_id), {"ref_log_id": log_id, "model_key": d["model_key"]})
        return {"ok": True}


class ProcessBody(BaseModel):
    action: str  # origin | suggested | manual | reject
    value: str | None = None
    # 같은 모델의 변형에 같은 값을 함께 넣는다(슬라이스 85). **화면이 고른 것만** —
    # 서버가 알아서 확장하지 않는다. 목록은 /reviews/{id}/siblings가 제안한다.
    also: list[int] = []


def _approve(conn, review, value, new_status: str) -> tuple[dict, int]:
    """승인 전이 공용 헬퍼(단건·일괄 공유). before 스냅샷과 pool_added를 반환."""
    field = review["field_name"]
    if field not in FIELD_CAST:
        raise HTTPException(400, f"처리할 수 없는 필드: {field}")
    pc = review["product_code"]

    prod = conn.execute(text(
        "SELECT part_type, review_required_yn, ai_candidate_yn, locked_fields"
        " FROM products WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()
    spec = conn.execute(text(
        "SELECT to_jsonb(ps) AS specs FROM product_specs ps WHERE product_code=:pc FOR UPDATE"),
        {"pc": pc}).mappings().first()
    specs_before = spec["specs"] if spec else None

    before = {
        "spec_value": (specs_before or {}).get(field),
        "verified_yn": (specs_before or {}).get("verified_yn", False),
        "review_required_yn": prod["review_required_yn"],
        "ai_candidate_yn": prod["ai_candidate_yn"],
        "locked_fields": prod["locked_fields"],
        "review_status": review["review_status"],
    }

    try:
        conn.execute(text(f"""
            INSERT INTO product_specs (product_code, part_type, {field})
            VALUES (:pc, :pt, CAST(:v AS {FIELD_CAST[field]}))
            ON CONFLICT (product_code)
            DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = now()
        """), {"pc": pc, "pt": prod["part_type"], "v": value})
    except DBAPIError:
        raise HTTPException(400, f"값 형식 오류: {value!r} → {field}")

    remaining = conn.execute(text(
        "SELECT COUNT(*) FROM product_reviews WHERE product_code=:pc"
        " AND review_status IN ('대기','검수중') AND review_id<>:rid"),
        {"pc": pc, "rid": review["review_id"]}).scalar()
    if remaining == 0:
        conn.execute(text(
            "UPDATE product_specs SET verified_yn=true, updated_at=now() WHERE product_code=:pc"),
            {"pc": pc})

    specs_now = conn.execute(text(
        "SELECT to_jsonb(ps) AS s FROM product_specs ps WHERE product_code=:pc"),
        {"pc": pc}).scalar()
    required = required_fields(prod["part_type"])
    all_filled = all((specs_now or {}).get(f) is not None for f in required)
    new_review_required = not (all_filled and remaining == 0)

    pool_added = 0
    if prod["review_required_yn"] and not new_review_required:
        # 게이트 해제 전이 — 이 순간에만 ai_candidate 승격 (ERD §8 T2)
        conn.execute(text(
            "UPDATE products SET review_required_yn=false, ai_candidate_yn=true,"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})
        pool_added = 1
    else:
        conn.execute(text(
            "UPDATE products SET"
            " locked_fields = CASE WHEN locked_fields ? :lf THEN locked_fields"
            " ELSE locked_fields || jsonb_build_array(:lf) END, updated_at=now()"
            " WHERE product_code=:pc"), {"pc": pc, "lf": f"specs.{field}"})

    conn.execute(text(
        "UPDATE product_reviews SET review_status=:st, reviewed_by=:op, reviewed_at=now()"
        " WHERE review_id=:rid"),
        {"st": new_status, "op": current_operator_id(), "rid": review["review_id"]})
    return before, pool_added


def _log(conn, action: str, target_id: str, detail: dict) -> int:
    import json
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'product_review', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": current_operator_id(), "a": action, "t": target_id, "d": json.dumps(detail)}).scalar()


def _lock_waiting_review(conn, review_id: int):
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": review_id}).mappings().first()
    if r is None:
        raise HTTPException(404, "검수 항목이 없습니다")
    if r["review_status"] != "대기":
        raise HTTPException(409, "이미 처리된 항목입니다")
    return r


# 같은 모델의 색상·패키지 변형 — 사양이 같은데 검수만 따로 해야 했다.
# 실측: cooler_tdp 대기 307건이 서로 다른 모델로는 232개뿐이다(75건이 변형).
# **자동으로 채우지 않는다.** 후보를 찾아 보여주고, 사람이 골라서 함께 적용한다 —
# 이름이 닮았다는 것만으로 사양이 같다고 단정하면 지어낸 값과 다를 게 없다.
_VARIANT = re.compile(r"\(([^)]*)\)")
_COLOR = re.compile(r"(블랙|화이트|블루|레드|핑크|그레이|실버|골드|투명|"
                    r"BLACK|WHITE|BLUE|RED|PINK|GRAY|GREY|SILVER|GOLD)", re.I)


def _model_key(name: str) -> str:
    """색상·괄호 표기를 지운 모델 이름. 보수적으로 — 괄호 밖 단어는 건드리지 않는다
    (`AS500`과 `AS500 PLUS`는 다른 제품이므로 묶이면 안 된다)."""
    s = _VARIANT.sub(" ", name or "")
    s = _COLOR.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


@router.get("/reviews/{review_id}/siblings")
def review_siblings(review_id: int):
    """이 검수 건과 **같은 모델로 보이는** 대기 건들 — 함께 처리할 후보.

    조건을 좁게 둔다: 같은 제조사 · 같은 부품 종류 · 같은 사양 필드 · 대기 상태 ·
    색상 표기를 지운 이름이 같을 것. 하나라도 어긋나면 후보에서 뺀다.
    """
    with engine.connect() as conn:
        me = conn.execute(text(
            "SELECT r.review_id, r.product_code, r.field_name, p.product_name, p.maker,"
            " p.part_type FROM product_reviews r JOIN products p USING (product_code)"
            " WHERE r.review_id=:rid"), {"rid": review_id}).mappings().first()
        if me is None:
            raise HTTPException(404, "검수 항목이 없습니다")
        rows = conn.execute(text(
            "SELECT r.review_id, r.product_code, p.product_name, p.status, p.stock_qty"
            " FROM product_reviews r JOIN products p USING (product_code)"
            " WHERE r.review_status='대기' AND r.field_name=:f AND p.part_type=:pt"
            "   AND coalesce(p.maker,'')=coalesce(:mk,'') AND r.review_id <> :rid"
            " ORDER BY p.product_name"),
            {"f": me["field_name"], "pt": me["part_type"], "mk": me["maker"],
             "rid": review_id}).mappings().all()
    key = _model_key(me["product_name"])
    sibs = [{"review_id": r["review_id"], "product_code": r["product_code"],
             "name": r["product_name"],
             "sellable": bool(r["status"] == "판매중" and (r["stock_qty"] or 0) > 0)}
            for r in rows if _model_key(r["product_name"]) == key]
    return {"review_id": review_id, "field": me["field_name"],
            "name": me["product_name"], "model_key": key, "siblings": sibs,
            "note": ("같은 제조사·같은 부품 종류에서 색상 표기만 다른 대기 건입니다."
                     " 사양이 같은지는 **사람이 확인**해야 합니다 —"
                     " 이름이 닮았다는 것만으로 값을 옮기지 않습니다."
                     if sibs else "함께 처리할 만한 같은 모델 대기 건이 없습니다.")}


@router.post("/reviews/{review_id}/process")
def process_review(review_id: int, body: ProcessBody):
    if body.action not in ("origin", "suggested", "manual", "reject"):
        raise HTTPException(400, f"알 수 없는 액션: {body.action}")
    with engine.begin() as conn:
        review = _lock_waiting_review(conn, review_id)

        if body.action == "reject":
            conn.execute(text(
                "UPDATE product_reviews SET review_status='보류', reviewed_by=:op, reviewed_at=now()"
                " WHERE review_id=:rid"), {"op": current_operator_id(), "rid": review_id})
            log_id = _log(conn, "review_process", str(review_id),
                          {"mode": "reject", "review_id": review_id,
                           "before": {"review_status": "대기"}})
            return {"ok": True, "undo_id": log_id, "pool_added": 0}

        value = {"origin": review["origin_value"], "suggested": review["suggested_value"],
                 "manual": body.value}[body.action]
        if value is None:
            raise HTTPException(400, "확정할 값이 없습니다")
        new_status = "수정" if body.action == "manual" else "승인"
        before, pool_added = _approve(conn, review, value, new_status)
        detail = {"mode": "approve", "review_id": review_id,
                  "field": review["field_name"], "value": str(value), "before": before}

        # 함께 적용 — 화면이 지정한 대기 건에만 같은 값을 넣는다.
        # 같은 사양 필드가 아니면 거부한다: 다른 필드에 같은 숫자를 넣는 건 사고다.
        extra = []
        for rid in dict.fromkeys(body.also or []):
            if rid == review_id:
                continue
            sib = _lock_waiting_review(conn, rid)
            if sib["field_name"] != review["field_name"]:
                raise HTTPException(400, "다른 사양 항목은 함께 처리할 수 없습니다")
            sb, sadd = _approve(conn, sib, value, new_status)
            pool_added += sadd
            extra.append({"review_id": rid, "product_code": sib["product_code"],
                          "before": sb})
        if extra:
            # 한 로그에 함께 담는다 — 되돌리면 전부 함께 되돌아간다(부분 원복 금지).
            detail["also"] = extra
        log_id = _log(conn, "review_process", str(review_id), detail)
        return {"ok": True, "undo_id": log_id, "pool_added": pool_added,
                "applied": 1 + len(extra),
                "note": (f"{1 + len(extra)}건에 같은 값을 넣었습니다 — 되돌리면 함께 돌아갑니다."
                         if extra else None)}


@router.post("/reviews/bulk-confirm")
def bulk_confirm():
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT * FROM product_reviews WHERE review_type='low_confidence'"
            " AND review_status='대기' ORDER BY review_id FOR UPDATE")).mappings().all()
        entries, skipped, pool_total = [], 0, 0
        for r in rows:
            if r["origin_value"] is None:
                skipped += 1
                continue
            before, pool_added = _approve(conn, r, r["origin_value"], "승인")
            pool_total += pool_added
            entries.append({"mode": "approve", "review_id": r["review_id"],
                            "field": r["field_name"], "value": r["origin_value"], "before": before})
        if not entries:
            raise HTTPException(400, "일괄 확정 대상이 없습니다")
        log_id = _log(conn, "review_bulk_confirm", f"{len(entries)}건", {"items": entries})
        return {"count": len(entries), "skipped": skipped, "undo_id": log_id, "pool_added": pool_total}


def _revert_one(conn, entry: dict):
    rid = entry["review_id"]
    r = conn.execute(text(
        "SELECT * FROM product_reviews WHERE review_id=:rid FOR UPDATE"),
        {"rid": rid}).mappings().first()
    if r is None:
        raise HTTPException(404, f"검수 항목이 없습니다: {rid}")
    if r["review_status"] == "대기":
        raise HTTPException(409, "이미 대기 상태입니다")  # 이중 undo·경합 방어의 전부
    before = entry["before"]
    if entry["mode"] == "approve":
        field, pc = entry["field"], r["product_code"]
        import json
        conn.execute(text(f"""
            UPDATE product_specs SET {field} = CAST(:v AS {FIELD_CAST[field]}),
                   verified_yn = :vy, updated_at = now() WHERE product_code = :pc
        """), {"v": before["spec_value"], "vy": before["verified_yn"], "pc": pc})
        conn.execute(text(
            "UPDATE products SET review_required_yn=:rr, ai_candidate_yn=:ac,"
            " locked_fields=CAST(:lf AS JSONB), updated_at=now() WHERE product_code=:pc"),
            {"rr": before["review_required_yn"], "ac": before["ai_candidate_yn"],
             "lf": json.dumps(before["locked_fields"]), "pc": pc})
    conn.execute(text(
        "UPDATE product_reviews SET review_status='대기', reviewed_by=NULL, reviewed_at=NULL"
        " WHERE review_id=:rid"), {"rid": rid})


@router.post("/reviews/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:id"),
            {"id": log_id}).mappings().first()
        if log is None or log["action"] not in ("review_process", "review_bulk_confirm"):
            raise HTTPException(404, "되돌릴 작업 기록이 없습니다")
        detail = log["detail"]
        if log["action"] == "review_bulk_confirm":
            entries = detail["items"]
        else:
            # 함께 적용분(also)도 같은 로그에 담겨 있다 — **부분 원복은 없다**.
            # 하나만 되돌리면 같은 모델의 형제끼리 값이 갈려 어느 쪽이 맞는지 알 수 없다.
            entries = [detail] + [
                {"mode": detail.get("mode"), "field": detail.get("field"),
                 "review_id": a["review_id"], "before": a["before"]}
                for a in (detail.get("also") or [])]
        for e in entries:
            _revert_one(conn, e)
        _log(conn, "review_undo", str(log_id), {"ref_log_id": log_id, "count": len(entries)})
        return {"ok": True, "restored": len(entries)}
