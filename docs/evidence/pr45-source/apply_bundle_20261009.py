"""묶음 「상품 94959 복원, 데이터 정리 7건」 — 한 트랜잭션. 조건이 하나라도 어긋나면 전부 롤백.
① 94959 복원 ② 105053 사양 행 생성 ③ 123034 검수 표시+잠금 ④ 9/30 도구가 잠근 7개 상품 11개 항목 잠금 해제.
검수 대기 행과 사양 값은 그대로 둔다. 되돌리기는 같은 폴더의 undo_bundle_20261009.sql.
"""
import os, json
from sqlalchemy import create_engine, text

eng = create_engine(os.environ["DATABASE_URL"])
NOTE = "regression cleanup 2026-10-09"
# ④ 사전 검사: 11개 값(다르면 전체 롤백)
EXPECT_VALUES = [
    (120906, "cooler_tdp", 280), (121011, "cooler_tdp", 280), (114514, "cooler_tdp", 290),
    (128119, "cooler_tdp", 200), (129775, "mem_type", "DDR5"),
    (129552, "gpu_max_mm", 240), (129552, "cooler_height_mm", 75), (129552, "form_factor_list", ["m-ATX", "mini-ITX"]),
    (129551, "gpu_max_mm", 240), (129551, "cooler_height_mm", 75), (129551, "form_factor_list", ["m-ATX", "mini-ITX"]),
]
# (상품, 지금 잠금 목록 — 정확히 같아야 적용, 뺄 항목)
UNLOCK = [
    (120906, ["market_price", "specs.cooler_height_mm", "specs.cooler_tdp", "specs.socket_list"], ["specs.cooler_tdp"]),
    (121011, ["market_price", "specs.cooler_height_mm", "specs.cooler_tdp", "specs.socket_list"], ["specs.cooler_tdp"]),
    (114514, ["market_price", "specs.cooler_tdp"], ["specs.cooler_tdp"]),
    (128119, ["market_price", "specs.cooler_tdp"], ["specs.cooler_tdp"]),
    (129552, ["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"],
     ["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"]),
    (129551, ["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"],
     ["specs.cooler_height_mm", "specs.form_factor_list", "specs.gpu_max_mm"]),
    (129775, ["specs.mem_type"], ["specs.mem_type"]),
]


class Abort(Exception):
    pass


def log(run, op, action, tid, detail):
    return run("INSERT INTO admin_operator_activity_logs (operator_id, action, target_kind, target_id, detail) "
               "VALUES (:op, :a, 'product', :t, CAST(:d AS JSONB)) RETURNING log_id",
               op=op, a=action, t=tid, d=json.dumps(detail, ensure_ascii=False)).scalar()


def work(run):
    out = []
    # ---- 1) 94959 복원 (log 22137, 되돌리기 409 건)
    src = run("SELECT operator_id, target_id, detail FROM admin_operator_activity_logs "
              "WHERE log_id=22137 AND action='product_edit' FOR UPDATE").mappings().first()
    if src is None or src["detail"].get("product_code") != 94959:
        raise Abort("94959: 원본 로그 불일치")
    if run("SELECT 1 FROM admin_operator_activity_logs WHERE action='product_edit_undo' "
           "AND (detail->>'ref_log_id')::int=22137").first():
        raise Abort("94959: 이미 되돌림 행 있음")
    p = run("SELECT sale_price, status, locked_fields FROM products WHERE product_code=94959 FOR UPDATE").mappings().first()
    if not (p["sale_price"] == 132400 and p["status"] == "품절" and p["locked_fields"] == ["sale_price", "status"]):
        raise Abort(f"94959: 현재값 다름 {dict(p)}")
    run("UPDATE products SET sale_price=131400, status='판매중', locked_fields='[]'::jsonb, updated_at=now() "
        "WHERE product_code=94959")
    run("INSERT INTO product_price_history (product_code, field, old_price, new_price, reason, ref_id, changed_by) "
        "VALUES (94959, 'sale', 132400, 131400, 'manual', 22137, :op)", op=src["operator_id"])
    out.append(("94959 undo log", log(run, src["operator_id"], "product_edit_undo", src["target_id"],
        {"ref_log_id": 22137, "product_code": 94959, "restored": {"status": "판매중", "sale_price": 131400},
         "note": "regression cleanup 2026-10-09 (undo 409)"})))

    # ---- 2) (A) 105053 잘만 ZM700-TX 파워 — 사양 행 생성(값 비움) + 필수 사양 검수 회부
    p = run("SELECT part_type, category_group, review_required_yn, locked_fields FROM products "
            "WHERE product_code=105053 FOR UPDATE").mappings().first()
    if not (p["part_type"] == "POWER" and p["category_group"] == "core_part" and p["review_required_yn"] is False):
        raise Abort(f"105053: 현재값 다름 {dict(p)}")
    if run("SELECT 1 FROM product_specs WHERE product_code=105053").first():
        raise Abort("105053: 사양 행이 이미 있음")
    if run("SELECT 1 FROM product_reviews WHERE product_code=105053").first():
        raise Abort("105053: 검수 행이 이미 있음")
    run("INSERT INTO product_specs (product_code, part_type) VALUES (105053, 'POWER')")
    for f in ("rated_watt", "form_factor"):
        run("INSERT INTO product_reviews (product_code, review_type, field_name, detail, confidence) "
            "VALUES (105053, 'spec_missing', :f, :d, 0.80)",
            f=f, d=f"POWER 필수 사양 '{f}' 미확인 — 사양 행 누락으로 회부({NOTE})")
    run("UPDATE products SET review_required_yn=true, updated_at=now() WHERE product_code=105053")
    out.append(("105053 log", log(run, 1, "product_edit", "105053",
        {"sku": "105053", "product_code": 105053, "locked": False, "before": {"locked_fields": p["locked_fields"]},
         "changes": {"review_required_yn": {"from": False, "to": True},
                     "product_specs": {"from": None, "to": "row created (part_type POWER, values empty)"}},
         "note": f"{NOTE} - core_part POWER had no product_specs row. Created empty row and referred required "
                 "specs (rated_watt, form_factor) to review; no values invented. NOTE: not in EDITABLE -- "
                 "the generic undo button will NOT revert this log."})))

    # ---- 3) (B) 검수 대기 5건 — 쓰기 없음. 상태가 그대로인지만 확인
    n = run("SELECT count(*) FROM product_reviews WHERE review_id IN (631,637,2544,7164,8614) AND review_status='대기'").scalar()
    if n != 5:
        raise Abort(f"(B): 대기 상태가 5건이 아님({n})")
    # ---- ④ 9/30 도구가 잠근 7개 상품 11개 항목 잠금 해제(값·검수 대기 행은 그대로)
    for pc, field, want in EXPECT_VALUES:
        got = run(f"SELECT {field} FROM product_specs WHERE product_code=:pc", pc=pc).scalar()
        if got != want:
            raise Abort(f"{pc}.{field}: 값 다름 {got!r} (기대 {want!r})")
    for pc, before, drop in UNLOCK:
        cur = run("SELECT locked_fields FROM products WHERE product_code=:pc FOR UPDATE", pc=pc).scalar()
        if cur != before:
            raise Abort(f"{pc}: 잠금 현재값 다름 {cur}")
        after = [x for x in before if x not in drop]
        run("UPDATE products SET locked_fields=CAST(:lf AS JSONB), updated_at=now() WHERE product_code=:pc",
            pc=pc, lf=json.dumps(after, ensure_ascii=False))
        out.append((f"{pc} unlock log", log(run, 1, "product_edit", str(pc),
            {"sku": str(pc), "product_code": pc, "locked": False, "before": {"locked_fields": before},
             "changes": {"locked_fields": {"from": before, "to": after}},
             "note": f"{NOTE} - unlock spec fields locked by the 2026-09-30 spec-fill tool (not operator-verified, "
                     "verified_yn=false, pending spec_missing reviews kept). Values unchanged. NOTE: not in EDITABLE -- "
                     "the generic undo button will NOT revert this log."})))
    left = run("SELECT count(*) FROM products p, LATERAL (VALUES " +
               ", ".join(f"({pc}, 'specs.{f}')" for pc, f, _ in EXPECT_VALUES) +
               ") t(pc, k) WHERE p.product_code=t.pc AND p.locked_fields ? t.k").scalar()
    if left != 0:
        raise Abort(f"④: 커밋 전 남은 잠금 {left}개(0이어야 함)")

    # ---- 4) 123034 판매조건 문구 이름 CPU — 검수 플래그 + 잠금
    p = run("SELECT review_required_yn, ai_candidate_yn, locked_fields, status FROM products "
            "WHERE product_code=123034 FOR UPDATE").mappings().first()
    if not (p["review_required_yn"] is False and p["ai_candidate_yn"] is True and p["locked_fields"] == []
            and p["status"] == "판매중"):
        raise Abort(f"123034: 현재값 다름 {dict(p)}")
    if run("SELECT review_status FROM product_reviews WHERE review_id=8193").scalar() != "대기":
        raise Abort("123034: 검수 8193 이 대기가 아님")
    run("UPDATE products SET review_required_yn=true, locked_fields='[\"review_required_yn\"]'::jsonb, updated_at=now() "
        "WHERE product_code=123034")
    out.append(("123034 log", log(run, 1, "product_edit", "123034",
        {"sku": "123034", "product_code": 123034, "locked": True, "before": {"locked_fields": []},
         "changes": {"review_required_yn": {"from": False, "to": True}},
         "note": f"{NOTE} - name is a sales-condition phrase (review 8193 pending); flag for review and lock so "
                 "the next import does not clear it. NOTE: not in EDITABLE -- the generic undo button will NOT revert this log."})))
    return out


def verify(run):
    run("SET TRANSACTION READ ONLY")
    for q in ("SELECT product_code, sale_price, status, locked_fields, review_required_yn, ai_candidate_yn, stock_qty FROM products WHERE product_code IN (94959,105053,123034,120906,121011,114514,128119,129552,129551,129775) ORDER BY 1",
              "SELECT count(*) n FROM admin_operator_activity_logs WHERE detail->>'note' LIKE 'regression cleanup 2026-10-09%'",
              "SELECT product_code, part_type, verified_yn FROM product_specs WHERE product_code=105053",
              "SELECT review_id, product_code, field_name, review_status FROM product_reviews WHERE product_code IN (105053,123034) OR review_id IN (631,637,2544,7164,8614) ORDER BY 1",
              "SELECT product_code FROM v_recommendation_candidates WHERE product_code IN (94959,105053,123034)",
              "SELECT history_id, product_code, old_price, new_price, ref_id FROM product_price_history WHERE product_code=94959 ORDER BY history_id DESC LIMIT 1"):
        for r in run(q).mappings():
            print("  ", json.dumps(dict(r), ensure_ascii=False, default=str))


DRY = os.environ.get("BUNDLE_DRY") == "1"
with eng.connect() as c:
    tx = c.begin()
    try:
        res = work(lambda q, **kw: c.execute(text(q), kw))
        print("적용 결과:", res)
        if DRY:
            tx.rollback(); print("DRY — 롤백함")
        else:
            tx.commit(); print("커밋 완료")
    except Abort as e:
        tx.rollback(); print("중단(롤백):", e)
with eng.connect() as c:
    c.begin()
    print("재조회:")
    verify(lambda q, **kw: c.execute(text(q), kw))
    c.rollback()
