"""ADM-SRC-030 공급처 관리 — 빈 상태에서 막혀 있던 길 (슬라이스 93).

**이 화면이 없어서 빈 DB로는 개업이 불가능했다.** `INSERT INTO suppliers`가
`db/seed/seed.sql`에만 있었는데 그 시드는 개발용 더미 전용이다. API에는 목록 조회와
상품-공급처 매입가 연결만 있었고, 새 공급처를 만드는 수단이 어디에도 없었다.

    공급처 0 → 매입가 넣을 대상 없음 → 판매가 산정 불가
              → 4중 게이트 통과 불가 → 추천 후보 0 → 견적 0건

`docs/07_운영-시작-순서.md` 3단계가 유일하게 화면 이름을 적지 않은 단계였다.

■ 삭제하지 않는다
suppliers를 참조하는 테이블이 6개다. 매입 이력이 걸린 공급처를 지우면 과거 단가·매입
기록이 깨진다. 그래서 원장 규약대로 **상태 전이**('활성' ↔ '중지')로 접는다.
중지하면 선택지에서 빠지되 과거 기록과 이미 연결된 매입가는 그대로 남는다.

■ 중지 전에 영향을 먼저 말한다
"이 공급처로 매입가가 걸린 상품이 12건입니다. 중지해도 그 매입가는 남고 새 매입가만
넣을 수 없게 됩니다." — 누르고 나서 알면 늦다(슬라이스 67·75와 같은 원칙).

■ 이름 중복을 막는다
같은 이름이 둘이면 매입가를 어느 쪽에 넣었는지 알 수 없다. 대소문자·앞뒤 공백을
무시하고 막는다(0025의 유니크 인덱스). 화면에도 같은 판정을 먼저 보여준다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .admin_orders import _log
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

STATES = ("활성", "중지")


class SupplierBody(BaseModel):
    # 모르는 필드는 조용히 무시하지 않는다 — 보낸 쪽이 성공했다고 믿게 두면 안 된다.
    model_config = ConfigDict(extra="forbid")
    name: str
    platform: str | None = None
    brands: str | None = None
    status: str | None = None


def _rows(conn):
    """공급처 + 실제로 쓰이고 있는 정도. 화면이 세지 않는다 — 서버가 센다."""
    return conn.execute(text(
        "SELECT s.supplier_id, s.name, s.platform, s.brands, s.status, s.created_at,"
        " (SELECT COUNT(*) FROM product_supplier_prices p"
        "    WHERE p.supplier_id = s.supplier_id) AS linked_products,"
        " (SELECT COUNT(*) FROM supplier_price_files f"
        "    WHERE f.supplier_id = s.supplier_id) AS price_files"
        " FROM suppliers s"
        " ORDER BY (s.status = '중지'), s.name")).mappings().all()


def _shape(r):
    return {"id": r["supplier_id"], "name": r["name"],
            "platform": r["platform"], "brands": r["brands"],
            "status": r["status"], "created": iso(r["created_at"]),
            "linked_products": r["linked_products"],
            "price_files": r["price_files"]}


@router.get("/suppliers")
def list_suppliers():
    """공급처 목록 — 선택지 겸 관리 화면의 원천.

    product-edit의 매입가 셀렉트도 이 경로를 쓴다. 화면이 이름을 지어내지 않게 한다.
    """
    with engine.connect() as conn:
        items = [_shape(r) for r in _rows(conn)]
    active = [i for i in items if i["status"] == "활성"]
    return {
        "items": items,
        "total": len(items),
        "active": len(active),
        # 빈 상태를 화면이 정확히 말할 수 있게 서버가 판정해 준다.
        "empty": len(active) == 0,
        "note": ("공급처가 없으면 매입가를 넣을 대상이 없고, 매입가가 없으면 판매가가"
                 " 산정되지 않아 추천 후보가 되지 않습니다"
                 if not active else
                 "중지한 공급처는 새 매입가 입력에서 빠지며 과거 기록은 그대로 남습니다"),
    }


@router.post("/suppliers")
def create_supplier(body: SupplierBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "공급처 이름을 입력하세요")
    if len(name) > 100:
        raise HTTPException(400, "이름은 100자 이하로 입력하세요")
    status = (body.status or "활성").strip()
    if status not in STATES:
        raise HTTPException(400, "상태는 " + " · ".join(STATES) + " 중 하나입니다")

    with engine.begin() as conn:
        # 같은 이름을 먼저 잡아 사람이 읽을 수 있는 문구로 돌려준다.
        # (인덱스에 맡기면 IntegrityError 원문이 그대로 나가 운영자가 못 읽는다)
        dup = conn.execute(text(
            "SELECT supplier_id, name, status FROM suppliers"
            " WHERE lower(btrim(name)) = lower(btrim(:n))"), {"n": name}).mappings().first()
        if dup:
            raise HTTPException(409, {
                "error": "duplicate_name",
                "message": f"이미 있는 공급처입니다 — {dup['name']}({dup['status']})."
                           " 중지된 공급처라면 목록에서 다시 활성으로 바꾸세요.",
                "supplier_id": dup["supplier_id"]})
        try:
            sid = conn.execute(text(
                "INSERT INTO suppliers (name, platform, brands, status)"
                " VALUES (:n, :p, :b, :s) RETURNING supplier_id"),
                {"n": name, "p": (body.platform or "").strip() or None,
                 "b": (body.brands or "").strip() or None, "s": status}).scalar()
        except IntegrityError:                     # 동시 요청으로 인덱스가 먼저 잡은 경우
            raise HTTPException(409, "이미 있는 공급처입니다")
        _log(conn, "supplier_create", name,
             {"platform": body.platform, "brands": body.brands}, kind="supplier")
        row = conn.execute(text(
            "SELECT s.supplier_id, s.name, s.platform, s.brands, s.status, s.created_at,"
            " 0 AS linked_products, 0 AS price_files"
            " FROM suppliers s WHERE s.supplier_id = :i"), {"i": sid}).mappings().first()

    out = _shape(row)
    out["note"] = f"{name} 등록했습니다 — 상품 상세의 [공급처별 매입가]에서 선택할 수 있습니다"
    return out


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "공급처 이름을 입력하세요")
    status = (body.status or "활성").strip()
    if status not in STATES:
        raise HTTPException(400, "상태는 " + " · ".join(STATES) + " 중 하나입니다")

    with engine.begin() as conn:
        before = conn.execute(text(
            "SELECT supplier_id, name, platform, brands, status FROM suppliers"
            " WHERE supplier_id = :i"), {"i": supplier_id}).mappings().first()
        if before is None:
            raise HTTPException(404, "공급처를 찾을 수 없습니다")

        dup = conn.execute(text(
            "SELECT supplier_id FROM suppliers"
            " WHERE lower(btrim(name)) = lower(btrim(:n)) AND supplier_id <> :i"),
            {"n": name, "i": supplier_id}).scalar()
        if dup:
            raise HTTPException(409, "같은 이름의 공급처가 이미 있습니다")

        changed = {}
        for key, new in (("name", name),
                         ("platform", (body.platform or "").strip() or None),
                         ("brands", (body.brands or "").strip() or None),
                         ("status", status)):
            if (before[key] or None) != new:
                changed[key] = {"before": before[key], "after": new}

        linked = conn.execute(text(
            "SELECT COUNT(*) FROM product_supplier_prices WHERE supplier_id = :i"),
            {"i": supplier_id}).scalar()

        if not changed:
            row = conn.execute(text(
                "SELECT s.supplier_id, s.name, s.platform, s.brands, s.status, s.created_at,"
                " :lp AS linked_products, 0 AS price_files FROM suppliers s"
                " WHERE s.supplier_id = :i"), {"i": supplier_id, "lp": linked}).mappings().first()
            out = _shape(row)
            out["note"] = "바뀐 값이 없습니다"
            out["changed"] = {}
            return out

        conn.execute(text(
            "UPDATE suppliers SET name=:n, platform=:p, brands=:b, status=:s"
            " WHERE supplier_id=:i"),
            {"n": name, "p": (body.platform or "").strip() or None,
             "b": (body.brands or "").strip() or None, "s": status, "i": supplier_id})
        _log(conn, "supplier_update", before["name"], {"changed": changed}, kind="supplier")

        row = conn.execute(text(
            "SELECT s.supplier_id, s.name, s.platform, s.brands, s.status, s.created_at,"
            " (SELECT COUNT(*) FROM product_supplier_prices p"
            "    WHERE p.supplier_id = s.supplier_id) AS linked_products,"
            " (SELECT COUNT(*) FROM supplier_price_files f"
            "    WHERE f.supplier_id = s.supplier_id) AS price_files"
            " FROM suppliers s WHERE s.supplier_id = :i"),
            {"i": supplier_id}).mappings().first()

    out = _shape(row)
    out["changed"] = changed
    if changed.get("status", {}).get("after") == "중지":
        out["note"] = (f"{name} 중지했습니다 — 새 매입가 입력에서 빠집니다."
                       + (f" 이미 연결된 매입가 {linked}건은 그대로 남습니다."
                          if linked else ""))
    else:
        out["note"] = f"{name} 저장했습니다"
    return out


@router.get("/suppliers/{supplier_id}/impact")
def deactivate_impact(supplier_id: int):
    """중지하면 무엇이 달라지는지 **누르기 전에** 알려준다(슬라이스 67·75와 같은 원칙)."""
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT name, status FROM suppliers WHERE supplier_id = :i"),
            {"i": supplier_id}).mappings().first()
        if row is None:
            raise HTTPException(404, "공급처를 찾을 수 없습니다")
        linked = conn.execute(text(
            "SELECT COUNT(*) FROM product_supplier_prices WHERE supplier_id = :i"),
            {"i": supplier_id}).scalar()
        files = conn.execute(text(
            "SELECT COUNT(*) FROM supplier_price_files WHERE supplier_id = :i"),
            {"i": supplier_id}).scalar()
        # 이 공급처가 **유일한** 매입처인 상품 — 중지 후 판매가 갱신 경로가 사라진다
        only = conn.execute(text(
            "SELECT COUNT(*) FROM ("
            "  SELECT product_code FROM product_supplier_prices"
            "  GROUP BY product_code HAVING COUNT(*) = 1"
            "     AND MIN(supplier_id) = :i) t"), {"i": supplier_id}).scalar()

    return {
        "supplier_id": supplier_id, "name": row["name"], "status": row["status"],
        "linked_products": linked, "price_files": files, "sole_source_products": only,
        "note": (f"매입가가 걸린 상품 {linked}건 · 단가표 {files}건은 그대로 남습니다."
                 + (f" 이 중 {only}건은 이 공급처가 유일한 매입처라"
                    " 앞으로 매입가를 갱신할 곳이 없어집니다." if only else "")
                 + " 삭제가 아니라 중지이므로 언제든 다시 활성으로 되돌릴 수 있습니다."),
    }
