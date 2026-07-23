"""ADM-PRC-040 단가표 일일 반영 — 스냅샷 diff → 선택 반영(첫 파일 기반 대량 쓰기) → undo.

의도된 차이(ERD §6.4 "판매가 재계산은 제안+승인, 자동 집행 안 함"): diff 화면이 재계산
판매가를 미리 보여주고 운영자의 "선택 반영" 클릭이 곧 승인이다(목업=스펙). 반영 시
sale_price를 갱신하되, ERD §6.4의 잠금 규칙은 준수 — 'sale_price'가 products.locked_fields에
있으면 갱신·이력을 스킵한다(응답 sale_locked_skipped).

한계(의도됨): model_key = 모델명 원문 완전 일치. 정규화·엑셀 파싱은 파일 확보 후 별도 슬라이스.
diff는 같은 공급처의 직전 파일 rows와의 비교로만 산출(ERD §11 — 별도 diff 테이블 없음).
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

OPERATOR_ID = 1
SIM_THRESHOLD = 0.3


def _half_up_1000(v: float) -> int:
    # 목업 Math.round(half-up)와 일치 — Python round()는 은행가 반올림이라 사용 금지
    return int(v / 1000 + 0.5) * 1000


def _settings(conn):
    r = conn.execute(text(
        "SELECT card_fee_rate, margin_rate FROM pricing_settings"
        " ORDER BY effective_from DESC LIMIT 1")).one()
    return float(r[0]), float(r[1])


def _ctx(conn, supplier_id: int) -> dict:
    """매칭·표시에 필요한 참조 데이터 일괄 로드(상품 13종 규모 전제)."""
    maps = dict(conn.execute(text(
        "SELECT model_key, product_code FROM supplier_product_map WHERE supplier_id=:s"),
        {"s": supplier_id}).all())
    products = {r["product_code"]: r for r in conn.execute(text(
        "SELECT product_code, sku, product_name, part_type, purchase_price, sale_price, locked_fields, danawa_code"
        " FROM products")).mappings().all()}
    danawa = {r["danawa_code"]: r["product_code"] for r in products.values() if r["danawa_code"]}
    psp = {}
    for r in conn.execute(text(
            "SELECT product_code, supplier_id, cost_price, supply_state FROM product_supplier_prices")).mappings():
        psp.setdefault(r["product_code"], {})[r["supplier_id"]] = (r["cost_price"], r["supply_state"])
    supplier_names = dict(conn.execute(text("SELECT supplier_id, name FROM suppliers")).all())
    return {"maps": maps, "products": products, "danawa": danawa, "psp": psp, "names": supplier_names}


def _match(row, ctx):
    """매칭 우선순위(ERD §11): ① 기억된 map ② danawa_code. (유사도는 nw 표시 전용 — 확정은 검수 소관)"""
    pc = ctx["maps"].get(row["model_name"])
    if pc is None and row["danawa_code"]:
        pc = ctx["danawa"].get(row["danawa_code"])
    return pc


def _file_diff(conn, file_row, ctx):
    """diff 버킷 계산(비배타 — 한 행이 chg와 stat에 동시 소속 가능).
    pending(반영 대상) = 매칭 ∧ psp가 없거나 cost 상이 — 반영하면 자연 소멸(멱등),
    undo하면 재등장. '반영 완료' 파일도 같은 식으로 chg 0에 수렴한다."""
    sid = file_row["supplier_id"]
    today = conn.execute(text(
        "SELECT row_id, model_name, danawa_code, prices, cost_price, supply_state, memo"
        " FROM supplier_price_rows WHERE file_id=:f ORDER BY row_id"),
        {"f": file_row["file_id"]}).mappings().all()
    prev_id = conn.execute(text(
        "SELECT file_id FROM supplier_price_files WHERE supplier_id=:s AND received_at < :r"
        " ORDER BY received_at DESC LIMIT 1"),
        {"s": sid, "r": file_row["received_at"]}).scalar()
    prev = {}
    if prev_id:
        prev = {r["model_name"]: r for r in conn.execute(text(
            "SELECT model_name, cost_price, supply_state FROM supplier_price_rows WHERE file_id=:f"),
            {"f": prev_id}).mappings().all()}

    price_cols = []
    preset = conn.execute(text(
        "SELECT rules FROM supplier_presets WHERE supplier_id=:s ORDER BY version DESC LIMIT 1"),
        {"s": sid}).scalar()
    if preset:
        price_cols = preset.get("price_cols", [])

    chg, nw, stat, same, pending = [], [], [], 0, {}
    for r in today:
        pc = _match(r, ctx)
        prod = ctx["products"].get(pc) if pc else None
        cat = PART_TYPE_LABELS.get(prod["part_type"], prod["part_type"]) if prod else "—"
        p = prev.get(r["model_name"])
        if p is None:
            # 신규 — 매칭 상태 표시만(map 등록·psp 추가는 검수 확정 소관)
            if pc:
                k, txt = "code", f"기억된 매핑/다나와코드 일치 — {prod['sku']} 자동 연결"
            else:
                sim = conn.execute(text(
                    "SELECT sku, similarity(:m, product_name) s FROM products"
                    " WHERE similarity(:m, product_name) > :th ORDER BY s DESC LIMIT 1"),
                    {"m": r["model_name"], "th": SIM_THRESHOLD}).first()
                if sim:
                    k, txt = "sim", f"이름 유사도 {round(sim[1]*100)}% — 후보 {sim[0]}"
                else:
                    k, txt = "none", "다나와코드·유사 이름 없음 — 신규 등록 필요"
            nw.append({"row_id": r["row_id"], "name": r["model_name"], "cat": cat,
                       "cost": r["cost_price"], "match": {"k": k, "text": txt,
                       "sku": prod["sku"] if prod else None}})
            continue
        if p["supply_state"] != r["supply_state"]:
            stat.append({"row_id": r["row_id"], "name": r["model_name"],
                         "raw": r["memo"] or f"{p['supply_state']} → {r['supply_state']}",
                         "from": p["supply_state"], "to": r["supply_state"]})
        if p["cost_price"] != r["cost_price"]:
            cur_psp = ctx["psp"].get(pc, {}).get(sid) if pc else None
            if pc and cur_psp and cur_psp[0] == r["cost_price"]:
                continue  # 이미 반영됨 — chg에서도 same에서도 제외
            sub = alt = None
            if price_cols and (r["prices"] or {}).get(price_cols[0]) is None:
                used = next((c for c in price_cols if (r["prices"] or {}).get(c) == r["cost_price"]), None)
                sub = f"{price_cols[0]} 결측 — 최저가({used or '다음 열'}) 적용"
            if pc:
                others = [(c, s2) for s2, (c, _st) in ctx["psp"].get(pc, {}).items() if s2 != sid]
                if others:
                    mn = min(others)
                    if mn[0] < r["cost_price"]:
                        alt = f"타 공급처 최저 {mn[0]:,}원({ctx['names'].get(mn[1], mn[1])}) — 이 파일이 최저 아님"
                pending[r["row_id"]] = r
            chg.append({"row_id": r["row_id"], "product_code": pc,
                        "sku": prod["sku"] if prod else None, "name": r["model_name"],
                        "cat": cat, "y": p["cost_price"], "t": r["cost_price"],
                        "memo": r["memo"], "sub": sub, "alt": alt})
        elif p["supply_state"] == r["supply_state"]:
            same += 1
    return {"chg": chg, "nw": nw, "stat": stat, "same": same, "pending": pending}


def _reprice(conn, pc: int, fee: float, margin: float, reason: str, ref_id: int,
             restore: dict | None = None) -> dict:
    """공급처 간 재판정(ERD §11): purchase = '가능' 상태 최저 cost, 없으면 전체 최저.
    변경분만 UPDATE + product_price_history 기록. undo도 이 헬퍼를 재실행한다(블라인드 복원 금지).

    restore(undo 전용) = 반영 시점의 {purchase, sale} 스냅샷. 재판정 결과 purchase가 반영 전
    값으로 완전히 복귀했다면 sale도 기록된 원본으로 복원한다(공식 재도출이 아니라 — 시드처럼
    공식과 무관한 판매가를 보존). 교차 반영으로 purchase가 다른 값이면 공식 도출 유지."""
    prod = conn.execute(text(
        "SELECT purchase_price, sale_price, locked_fields FROM products"
        " WHERE product_code=:pc FOR UPDATE"), {"pc": pc}).mappings().one()
    rows = conn.execute(text(
        "SELECT cost_price, supply_state FROM product_supplier_prices WHERE product_code=:pc"),
        {"pc": pc}).all()
    if not rows:
        return {"purchase_changed": False, "sale_changed": False, "sale_locked": False}
    avail = [c for c, s in rows if s == "가능"]
    new_purchase = min(avail) if avail else min(c for c, _ in rows)
    out = {"purchase_changed": False, "sale_changed": False, "sale_locked": False}
    if new_purchase != prod["purchase_price"]:
        conn.execute(text(
            "UPDATE products SET purchase_price=:v, updated_at=now() WHERE product_code=:pc"),
            {"v": new_purchase, "pc": pc})
        conn.execute(text(
            "INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, 'purchase', :o, :n, :r, :ref, :op)"),
            {"pc": pc, "o": prod["purchase_price"], "n": new_purchase,
             "r": reason, "ref": ref_id, "op": OPERATOR_ID})
        out["purchase_changed"] = True
    if restore is not None and new_purchase == restore["purchase"]:
        new_sale = restore["sale"]
    else:
        new_sale = _half_up_1000(new_purchase * (1 + fee + margin))
    if "sale_price" in (prod["locked_fields"] or []):
        out["sale_locked"] = new_sale != prod["sale_price"]
    elif new_sale != prod["sale_price"]:
        conn.execute(text(
            "UPDATE products SET sale_price=:v, updated_at=now() WHERE product_code=:pc"),
            {"v": new_sale, "pc": pc})
        conn.execute(text(
            "INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by)"
            " VALUES (:pc, 'sale', :o, :n, :r, :ref, :op)"),
            {"pc": pc, "o": prod["sale_price"], "n": new_sale,
             "r": reason, "ref": ref_id, "op": OPERATOR_ID})
        out["sale_changed"] = True
    return out


def _log(conn, action: str, target_id: str, detail: dict) -> int:
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, 'price_file', :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": OPERATOR_ID, "a": action, "t": target_id, "d": json.dumps(detail)}).scalar()


def _preset_view(conn, supplier_id: int, row_count) -> dict:
    rules = conn.execute(text(
        "SELECT rules FROM supplier_presets WHERE supplier_id=:s ORDER BY version DESC LIMIT 1"),
        {"s": supplier_id}).scalar() or {}
    cols = rules.get("price_cols", [])
    state = " · ".join(f"{k}→{v}" for k, v in rules.get("state_map", {}).items())
    return {
        "summary": f"헤더 {rules.get('header_rows', '?')}행 · 가격 열 {len(cols)}종 · "
                   + ("다나와코드 열 있음" if rules.get("danawa_code_col") else "모델명 매칭")
                   + (f" · {row_count}행" if row_count else ""),
        "map_text": f"매입가 ← 가격 열 중 최저가 ({', '.join(cols)}) · 상태 정규화 {state}",
        "note": "다나와 상품코드 매칭 — 자동 연결 우선" if rules.get("danawa_code_col")
                else "상품코드 없음 — 모델명 매칭",
    }


@router.get("/price-import")
def price_import():
    with engine.connect() as conn:
        fee, margin = _settings(conn)
        files = conn.execute(text(
            "SELECT DISTINCT ON (f.supplier_id) f.file_id, f.supplier_id, s.name AS supplier,"
            " f.file_name, f.received_at, f.status, f.row_count"
            " FROM supplier_price_files f JOIN suppliers s USING (supplier_id)"
            " ORDER BY f.supplier_id, f.received_at DESC")).mappings().all()
        out = []
        for f in files:
            ctx = _ctx(conn, f["supplier_id"])
            d = _file_diff(conn, f, ctx)
            out.append({
                "file_id": f["file_id"], "supplier_id": f["supplier_id"], "supplier": f["supplier"],
                "label": f["file_name"], "received_at": f["received_at"].isoformat(),
                "status": f["status"], "row_count": f["row_count"],
                "preset": _preset_view(conn, f["supplier_id"], f["row_count"]),
                "same": d["same"], "chg": d["chg"], "nw": d["nw"], "stat": d["stat"],
            })
    return {"fee_rate": fee, "margin_rate": margin, "files": out}


class ApplyBody(BaseModel):
    row_ids: list[int]


@router.post("/price-import/{file_id}/apply")
def apply_rows(file_id: int, body: ApplyBody):
    if not body.row_ids:
        raise HTTPException(400, "반영할 행이 없습니다")
    with engine.begin() as conn:
        f = conn.execute(text(
            "SELECT file_id, supplier_id, received_at, status FROM supplier_price_files"
            " WHERE file_id=:f FOR UPDATE"), {"f": file_id}).mappings().first()
        if f is None:
            raise HTTPException(404, "파일이 없습니다")
        if f["status"] == "반영 완료":
            raise HTTPException(409, "이미 반영 완료된 파일입니다")
        fee, margin = _settings(conn)
        ctx = _ctx(conn, f["supplier_id"])
        d = _file_diff(conn, f, ctx)
        bad = [rid for rid in body.row_ids if rid not in d["pending"]]
        if bad:
            raise HTTPException(400, f"반영 불가 행 포함(미매칭·미대기): {bad}")

        items, price_changed, sale_locked = [], 0, 0
        for rid in sorted(body.row_ids):
            row = d["pending"][rid]
            pc = _match(row, ctx)
            before = conn.execute(text(
                "SELECT cost_price, supply_state FROM product_supplier_prices"
                " WHERE product_code=:pc AND supplier_id=:s FOR UPDATE"),
                {"pc": pc, "s": f["supplier_id"]}).first()
            conn.execute(text(
                "INSERT INTO product_supplier_prices (product_code, supplier_id, cost_price, supply_state, src_file_id)"
                " VALUES (:pc, :s, :c, :st, :f)"
                " ON CONFLICT (product_code, supplier_id)"
                " DO UPDATE SET cost_price=:c, supply_state=:st, src_file_id=:f, updated_at=now()"),
                {"pc": pc, "s": f["supplier_id"], "c": row["cost_price"],
                 "st": row["supply_state"], "f": file_id})
            prod_before = ctx["products"][pc]
            rp = _reprice(conn, pc, fee, margin, "price_import", file_id)
            price_changed += 1 if rp["purchase_changed"] or rp["sale_changed"] else 0
            sale_locked += 1 if rp["sale_locked"] else 0
            items.append({
                "row_id": rid, "product_code": pc,
                "applied": {"cost": row["cost_price"], "state": row["supply_state"]},
                "psp_before": {"cost": before[0], "state": before[1]} if before else None,
                "product_before": {"purchase": prod_before["purchase_price"],
                                   "sale": prod_before["sale_price"]},
            })

        # 완료 판정 = 매칭된 pending chg 0건 (미매칭 chg 행은 여기서 반영 불가 — 판정 제외)
        d2 = _file_diff(conn, f, _ctx(conn, f["supplier_id"]))
        new_status = "반영 완료" if not d2["pending"] else "부분 반영"
        conn.execute(text("UPDATE supplier_price_files SET status=:s WHERE file_id=:f"),
                     {"s": new_status, "f": file_id})
        log_id = _log(conn, "price_import_apply", str(file_id),
                      {"file_id": file_id, "file_status_before": f["status"], "items": items})
        return {"applied": len(items), "price_changed": price_changed,
                "sale_locked_skipped": sale_locked, "undo_id": log_id, "file_status": new_status}


@router.post("/price-import/undo/{log_id}")
def undo(log_id: int):
    with engine.begin() as conn:
        log = conn.execute(text(
            "SELECT action, detail FROM admin_operator_activity_logs WHERE log_id=:id"),
            {"id": log_id}).mappings().first()
        if log is None or log["action"] != "price_import_apply":
            raise HTTPException(404, "되돌릴 반영 기록이 없습니다")
        if conn.execute(text(
                "SELECT 1 FROM admin_operator_activity_logs"
                " WHERE action='price_import_undo' AND detail->>'ref_log_id' = :id"),
                {"id": str(log_id)}).first():
            raise HTTPException(409, "이미 되돌린 작업입니다")
        detail = log["detail"]
        file_id = detail["file_id"]
        f = conn.execute(text(
            "SELECT supplier_id FROM supplier_price_files WHERE file_id=:f FOR UPDATE"),
            {"f": file_id}).mappings().one()
        fee, margin = _settings(conn)
        # 가드 2: 반영 이후 다른 변경이 겹쳤으면 중단(최종 승자 원칙 — 주석)
        for it in detail["items"]:
            cur = conn.execute(text(
                "SELECT cost_price, supply_state FROM product_supplier_prices"
                " WHERE product_code=:pc AND supplier_id=:s FOR UPDATE"),
                {"pc": it["product_code"], "s": f["supplier_id"]}).first()
            if cur is None or cur[0] != it["applied"]["cost"] or cur[1] != it["applied"]["state"]:
                raise HTTPException(409, "반영 이후 다른 변경이 감지되어 되돌릴 수 없습니다")
        for it in detail["items"]:
            if it["psp_before"] is None:
                conn.execute(text(
                    "DELETE FROM product_supplier_prices WHERE product_code=:pc AND supplier_id=:s"),
                    {"pc": it["product_code"], "s": f["supplier_id"]})
            else:
                conn.execute(text(
                    "UPDATE product_supplier_prices SET cost_price=:c, supply_state=:st, updated_at=now()"
                    " WHERE product_code=:pc AND supplier_id=:s"),
                    {"c": it["psp_before"]["cost"], "st": it["psp_before"]["state"],
                     "pc": it["product_code"], "s": f["supplier_id"]})
            # 재판정 재실행 — 역방향 이력은 실제 바뀐 필드에만 기록(이력 삭제 금지 원칙)
            _reprice(conn, it["product_code"], fee, margin, "price_import_undo", file_id,
                     restore=it["product_before"])
        conn.execute(text("UPDATE supplier_price_files SET status=:s WHERE file_id=:f"),
                     {"s": detail["file_status_before"], "f": file_id})
        _log(conn, "price_import_undo", str(file_id),
             {"ref_log_id": log_id, "count": len(detail["items"])})
        return {"ok": True, "restored": len(detail["items"])}
