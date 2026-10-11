# -*- coding: utf-8 -*-
"""쇼핑몰 가격 반영(ADM-PRC-070 · 가칭) — 관리자 데이터 API (2026-10-11).

1겹 배치 안전장치의 «사람 손» 길이다. 관리자가 쇼핑몰(윈윈) 관리자에서 내려받은
「상품엑셀」 파일을 올리면:

  ① POST /mall-price/preview   파일을 읽어 «무엇이 바뀌는지»만 보여 준다. DB 를 안 바꾼다.
                               바뀌는 상품 수 · 오르는 것 · 내리는 것 · 큰 변동 · 잠금 제외 ·
                               우리에게 없는 상품. 읽은 가격은 서버에 잠시 보관한다(1시간).
  ② POST /mall-price/apply     미리보기가 준 token 을 되돌려 보내야 한다. 그 사이 우리 판매가가
                               바뀌어 내용이 달라졌으면 409 — 다른 내용을 보고 확인하는 사고를 막는다.
  ③ POST /mall-price/runs/{id}/undo   그 실행을 통째로 되돌린다.

자동 갱신(1겹 배치 ②, api/mall_price_auto):
  GET  /mall-price/auto         마지막 자동·바로 실행 결과와 설정 «이름·유무»(값은 절대 안 준다)
  POST /mall-price/auto/run     「지금 실행」 — 실행 행을 만들고 수집은 뒤에서 돈다(대표만)

조회: GET /mall-price/runs (실행 기록) · GET /mall-price/checks (가격 확인 기록 — 배치와
실시간 두 겹이 같은 표에 있다, moment 로 거른다).

권한: 쓰기는 대표(owner)만 — 고객 카드 가격 전체를 한 번에 바꾸는 일이라 상품 일괄 등록과
같은 등급이다. 읽기는 로그인한 관리자 누구나(api/auth 기본 규칙).
"""
import hashlib
import io
import json
import os
import tempfile
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import text

from . import mall_price as MP
from . import mall_price_auto as AUTO
from .auth import current_operator, current_operator_id
from .db import engine
from .pricing_write_guard_core import ProductScopeChanged
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-mall-price"])
# 자동 갱신(매일 06:00 · 13:00 KST)은 API 프로세스 안에서 돈다 — api/mall_price_auto.start_scheduler
router.add_event_handler("startup", AUTO.start_scheduler)

STAGE_DIR = os.path.join(os.environ.get("POPCORN_UPLOAD_DIR") or os.path.join(
    tempfile.gettempdir(), "popcorn-uploads"), "mall-price")
STAGE_TTL = 60 * 60
PREVIEW_ROWS = 300            # 미리보기 표에 싣는 줄 수(차이 큰 순). 전체 건수는 따로 준다.

MOMENT_KO = {"file": "파일 올리기", "auto": "자동 갱신", "manual": "바로 실행",
             "cart": "장바구니", "checkout": "결제 이동"}
OUTCOME_KO = {"changed": "판매가 바꿈", "same": "같음", "held": "보류(큰 변동)",
              "locked": "잠금이라 건너뜀", "stale": "그 사이 바뀌어 건너뜀", "failed": "확인 못 함"}


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "대표 권한만 판매가를 일괄로 바꿀 수 있습니다")
    return me


def _stage_path(staging_id: str) -> str:
    if not staging_id.isalnum() or len(staging_id) > 40:
        raise HTTPException(400, "잘못된 미리보기 번호입니다")
    return os.path.join(STAGE_DIR, staging_id + ".json")


def _sweep():
    try:
        now = time.time()
        for n in os.listdir(STAGE_DIR):
            p = os.path.join(STAGE_DIR, n)
            if os.path.isfile(p) and now - os.path.getmtime(p) > STAGE_TTL:
                os.remove(p)
    except OSError:
        pass


def _plan_out(plan: dict) -> dict:
    return {
        "seen": plan["seen"], "matched": plan["matched"], "change_count": len(plan["changes"]),
        "up": plan["up"], "down": plan["down"], "big": plan["big"], "same": plan["same"],
        "locked_count": len(plan["locked"]), "out_of_scope": plan["out_of_scope"],
        "not_found_count": len(plan["not_found"]), "not_found_sample": plan["not_found"][:20],
        "include_parts": plan["include_parts"], "token": plan["token"],
        "changes": plan["changes"][:PREVIEW_ROWS], "locked": plan["locked"][:50],
    }


@router.post("/mall-price/preview")
async def preview(file: UploadFile = File(...), include_parts: bool = Form(False)):
    _owner()
    _sweep()
    raw = await file.read()
    try:
        parsed = MP.read_price_file(raw)
    except MP.PriceFileError as e:
        raise HTTPException(400, str(e))
    with engine.connect() as conn:
        plan = MP.build_plan(conn, parsed["prices"], include_parts=include_parts)
    staging_id = hashlib.sha256(raw).hexdigest()[:32]
    os.makedirs(STAGE_DIR, exist_ok=True)
    with io.open(_stage_path(staging_id), "w", encoding="utf-8") as f:
        json.dump({"file_name": file.filename, "prices": parsed["prices"]}, f)
    return {"staging_id": staging_id, "file_name": file.filename,
            "file": {k: parsed[k] for k in ("format", "rows", "bad_rows", "dup_codes", "columns")},
            **_plan_out(plan)}


@router.post("/mall-price/apply")
def apply(staging_id: str = Form(...), token: str = Form(...), include_parts: bool = Form(False)):
    me = _owner()
    p = _stage_path(staging_id)
    if not os.path.exists(p):
        raise HTTPException(410, "미리보기가 만료됐습니다. 파일을 다시 올려 주세요.")
    with io.open(p, encoding="utf-8") as f:
        staged = json.load(f)
    prices = {int(k): int(v) for k, v in staged["prices"].items()}
    op = me.get("operator_id") or current_operator_id()
    with engine.begin() as conn:
        plan = MP.build_plan(conn, prices, include_parts=include_parts)
        if plan["token"] != token:
            raise HTTPException(409, "미리보기 뒤 판매가가 바뀌었습니다. 다시 미리보기 해 주세요.")
        run_id = MP.start_run(conn, "file", source="file", operator_id=op,
                              file_name=staged.get("file_name"), include_parts=include_parts)
        try:
            res = MP.apply_changes(conn, plan["changes"] + plan["locked"], moment="file",
                                   operator_id=op, run_id=run_id)
        except ProductScopeChanged:
            raise HTTPException(409, "그 사이 상품이 바뀌었습니다. 다시 미리보기 해 주세요.")
        MP.finish_run(conn, run_id, ok=True, apply_log_id=res["log_id"], counts={
            "seen": plan["seen"], "matched": plan["matched"], "changed": res["changed"],
            "up": res["up"], "down": res["down"], "held": res["held"],
            "locked": res["locked"]}, detail={"stale": res["stale"],
                                              "not_found": len(plan["not_found"])})
    try:
        os.remove(p)
    except OSError:
        pass
    return {"ok": True, "run_id": run_id, "changed": res["changed"], "up": res["up"],
            "down": res["down"], "locked": res["locked"], "stale": res["stale"],
            "note": "판매가 %d건을 쇼핑몰 가격으로 바꿨습니다(오름 %d · 내림 %d)."
                    % (res["changed"], res["up"], res["down"])}


@router.post("/mall-price/runs/{run_id}/undo")
def undo(run_id: int):
    me = _owner()
    op = me.get("operator_id") or current_operator_id()
    with engine.begin() as conn:
        try:
            res = MP.undo_run(conn, run_id, operator_id=op)
        except MP.UndoRefused as e:
            raise HTTPException(409, str(e))
        except ProductScopeChanged:
            raise HTTPException(409, "그 사이 상품이 바뀌었습니다. 다시 시도해 주세요.")
    note = "판매가 %d건을 이전 값으로 되돌렸습니다." % res["restored"]
    if res["skipped"]:
        note += " %d건은 그 뒤 다른 경로가 바꿔 그대로 두었습니다." % res["skipped"]
    return {"ok": True, **res, "note": note}


@router.get("/mall-price/runs")
def runs(limit: int = 20):
    limit = max(1, min(int(limit), 100))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT r.*, o.name AS operator_name FROM mall_price_runs r"
            " LEFT JOIN admin_operators o ON o.operator_id = r.operator_id"
            " ORDER BY r.run_id DESC LIMIT :n"), {"n": limit}).mappings().all()
    out = []
    for r in rows:
        out.append({
            "run_id": r["run_id"], "moment": r["moment"], "moment_label": MOMENT_KO[r["moment"]],
            "source": r["source"], "file_name": r["file_name"], "include_parts": r["include_parts"],
            "started_at": iso(r["started_at"]), "finished_at": iso(r["finished_at"]),
            "ok": r["ok"], "fail_reason": r["fail_reason"],
            "seen": r["seen_count"], "matched": r["matched_count"], "changed": r["changed_count"],
            "up": r["up_count"], "down": r["down_count"], "held": r["held_count"],
            "locked": r["locked_count"], "undone_at": iso(r["undone_at"]),
            "can_undo": r["apply_log_id"] is not None and r["undone_at"] is None,
            "operator_name": r["operator_name"], "detail": r["detail"],
        })
    return {"items": out}


@router.get("/mall-price/checks")
def checks(moment: str = "", product_code: int | None = None, run_id: int | None = None,
           only_diff: bool = False, page: int = 1, size: int = 50):
    if moment and moment not in MP.MOMENTS:
        raise HTTPException(400, "알 수 없는 시점입니다")
    size = max(1, min(int(size), 200))
    page = max(1, int(page))
    where, params = [], {}
    if moment:
        where.append("c.moment = :m"); params["m"] = moment
    if product_code:
        where.append("c.product_code = :pc"); params["pc"] = product_code
    if run_id:
        where.append("c.run_id = :r"); params["r"] = run_id
    if only_diff:
        where.append("c.outcome <> 'same'")
    w = (" WHERE " + " AND ".join(where)) if where else ""
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM mall_price_checks c" + w), params).scalar()
        rows = conn.execute(text(
            "SELECT c.*, p.product_name FROM mall_price_checks c"
            " LEFT JOIN products p ON p.product_code = c.product_code" + w +
            " ORDER BY c.check_id DESC LIMIT :n OFFSET :o"),
            {**params, "n": size, "o": (page - 1) * size}).mappings().all()
    return {"total": total, "page": page, "size": size, "items": [{
        "check_id": r["check_id"], "checked_at": iso(r["checked_at"]),
        "moment": r["moment"], "moment_label": MOMENT_KO[r["moment"]],
        "run_id": r["run_id"], "product_code": r["product_code"], "product_name": r["product_name"],
        "our_price": r["our_price"], "mall_price": r["mall_price"], "diff": r["diff"],
        "outcome": r["outcome"], "outcome_label": OUTCOME_KO[r["outcome"]], "note": r["note"],
        "source_url": r["source_url"], "quote_id": str(r["quote_id"]) if r["quote_id"] else None,
    } for r in rows]}


# ================================================================ 자동 갱신 ==

def _run_row(r):
    if r is None:
        return None
    return {"run_id": r["run_id"], "moment": r["moment"], "moment_label": MOMENT_KO[r["moment"]],
            "source": r["source"], "started_at": iso(r["started_at"]), "finished_at": iso(r["finished_at"]),
            "ok": r["ok"], "fail_reason": r["fail_reason"], "changed": r["changed_count"],
            "held": r["held_count"], "matched": r["matched_count"], "detail": r["detail"]}


@router.get("/mall-price/auto")
def auto_status():
    with engine.connect() as conn:
        last = conn.execute(text(
            "SELECT * FROM mall_price_runs WHERE moment IN ('auto','manual')"
            " ORDER BY run_id DESC LIMIT 1")).mappings().first()
        last_ok = conn.execute(text(
            "SELECT * FROM mall_price_runs WHERE moment IN ('auto','manual') AND ok"
            " ORDER BY run_id DESC LIMIT 1")).mappings().first()
    cfg = AUTO.settings()
    return {"last": _run_row(last), "last_ok": _run_row(last_ok),
            "source": "export" if cfg["login"] and cfg["export_url"] else "pages",
            "settings": cfg, "schedule": "매일 06:00 · 13:00 (한국 시각)"}


@router.post("/mall-price/auto/run")
def auto_run():
    me = _owner()
    try:
        run_id = AUTO.start_background(operator_id=me.get("operator_id") or current_operator_id())
    except AUTO.AlreadyRunning as e:
        raise HTTPException(409, "이미 실행 중입니다 (실행 #%s)" % e.args[0])
    return {"ok": True, "run_id": run_id,
            "note": "쇼핑몰 가격 읽기를 시작했습니다. 끝나면 실행 기록에 결과가 남습니다."}
