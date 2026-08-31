"""ADM-CSV-010 상품 일괄 등록 — 업로드 → 드라이런 → 확인 → 적용 (슬라이스 50).

**곧바로 적재하지 않는다.** 잘못 올린 파일 하나가 22,000건 정본을 덮을 수 있기 때문에
반드시 두 걸음으로 나눈다:

  ① `POST /catalog-import/dryrun` — 파일을 받아 **계획만** 세우고 리포트를 준다.
     DB는 건드리지 않는다. 파일은 서버에 임시 보관하고 `staging_id`를 준다.
  ② `POST /catalog-import/apply`   — 운영자가 리포트를 보고 확정. 이때 드라이런이 보고한
     `expect_ok`를 되돌려 보내야 한다. 값이 다르면 거부한다 — 다른 파일을 보고
     확인 버튼을 누르는 사고를 막는다.

권한: **owner 전용**(auth.OWNER_WRITE_PREFIXES). 정본 전체를 바꾸는 일이라 운영자 등급으로는
열지 않는다. 적재 자체는 `catalog_ingest`가 하고 CLI와 같은 코드다.

되돌림: 적재는 product_code 기준 **upsert이고 삭제가 없다**. 즉 "올린 것만 지우는" 되돌림은
불가능하다(이전 값 스냅샷을 남기지 않는다). 그래서 화면이 그 사실을 먼저 말한다 —
되돌릴 수 있다고 믿게 두는 것이 되돌리지 못하는 것보다 나쁘다.
"""
import hashlib
import io
import json
import os
import shutil
import tempfile
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text

from .auth import current_operator
from .catalog_ingest import (
    apply_plan, build_plan, load_eav, plan_impact, plan_summary, read_master, read_refs,
)
from .db import engine

router = APIRouter(prefix="/api/admin")

# 실파일 기준: 마스터 12.6MB + db_products 3.6MB + db_specs 11.8MB ≈ 28MB.
MAX_BYTES = 64 * 1024 * 1024
STAGE_TTL = 60 * 60           # 1시간 — 확인 없이 방치된 업로드는 청소한다
STAGE_DIR = os.environ.get("POPCORN_UPLOAD_DIR") or os.path.join(
    tempfile.gettempdir(), "popcorn-uploads")

# ■ 적재한 원본 보관 (요청 39 · 2026-08-31 사장님 확정)
#   스테이징(STAGE_DIR)은 «확인 전» 파일이라 1시간 뒤 청소되지만, **실제로 적재된**
#   파일은 나중에 다시 받을 수 있어야 한다. 그래서 apply 가 성공한 것만 여기로 옮긴다.
#   ⚠ 리포 폴더에 두지 않는다 — 앱 계정은 리포에 쓸 수 없고 써서도 안 된다
#     (working tree drift · CLAUDE.md 슬라이스 81 실사고). 운영에서는
#     `POPCORN_ARCHIVE_DIR` 로 영속 볼륨을 가리킨다.
#   ⚠ STAGE_DIR 의 하위가 아니어야 한다 — _sweep() 이 훑는 자리에 두면 언젠가 지워진다.
ARCHIVE_DIR = os.environ.get("POPCORN_ARCHIVE_DIR") or os.path.join(
    tempfile.gettempdir(), "popcorn-import-archive")

# 보관하는 세 종류. 값은 스테이징 kind 와 같게 두어 옮길 때 이름을 다시 짜지 않는다.
ARCHIVE_KINDS = {"master": "마스터", "dbp": "사양 매핑", "dbs": "사양 값"}


def _stage_path(staging_id: str, kind: str) -> str:
    if not staging_id.isalnum() or len(staging_id) > 40:
        raise HTTPException(400, "잘못된 staging_id")
    return os.path.join(STAGE_DIR, f"{staging_id}.{kind}")


def _archive_path(job_id: int, kind: str) -> str:
    if kind not in ARCHIVE_KINDS and kind != "meta":
        raise HTTPException(400, "잘못된 파일 종류")
    return os.path.join(ARCHIVE_DIR, f"{int(job_id)}.{kind}")


def _sweep():
    """오래된 업로드 제거 — 서버에 원본 CSV가 무한정 남지 않게."""
    try:
        now = time.time()
        for n in os.listdir(STAGE_DIR):
            p = os.path.join(STAGE_DIR, n)
            if os.path.isfile(p) and now - os.path.getmtime(p) > STAGE_TTL:
                os.remove(p)
    except FileNotFoundError:
        pass
    except OSError:
        pass


async def _read_upload(f: UploadFile | None, label: str) -> bytes | None:
    if f is None:
        return None
    raw = await f.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f"{label} 파일이 너무 큽니다"
                                 f"({len(raw) / 1048576:.1f}MB · 한도 {MAX_BYTES // 1048576}MB)")
    if not raw:
        raise HTTPException(400, f"{label} 파일이 비어 있습니다")
    return raw


@router.post("/catalog-import/dryrun")
async def dryrun(
    master: UploadFile = File(..., description="상품 마스터 CSV"),
    db_products: UploadFile | None = File(None, description="사양 EAV 상품 매핑(선택)"),
    db_specs: UploadFile | None = File(None, description="사양 EAV 값(선택)"),
    origin: str = Form("real"),
):
    if origin not in ("real", "demo"):
        raise HTTPException(400, "origin은 real 또는 demo여야 합니다")
    _sweep()
    m_raw = await _read_upload(master, "마스터")
    p_raw = await _read_upload(db_products, "사양 매핑")
    s_raw = await _read_upload(db_specs, "사양 값")
    if bool(p_raw) != bool(s_raw):
        raise HTTPException(400, "사양 EAV는 두 파일(매핑·값)을 함께 올려야 합니다")

    try:
        rows = read_master(m_raw)
    except UnicodeDecodeError:
        raise HTTPException(400, "마스터 CSV를 UTF-8로 읽지 못했습니다 — UTF-8로 저장해 주세요")
    except ValueError as e:
        raise HTTPException(400, str(e))

    kvs, feats = load_eav(p_raw, s_raw)
    with engine.connect() as conn:
        refs = read_refs(conn)
        plan = build_plan(rows, kvs, feats, refs, origin)
        impact = plan_impact(conn, plan)
    summary = plan_summary(plan)

    staging_id = hashlib.sha256(
        m_raw + (p_raw or b"") + (s_raw or b"") + origin.encode()).hexdigest()[:32]
    os.makedirs(STAGE_DIR, exist_ok=True)
    with io.open(_stage_path(staging_id, "master"), "wb") as f:
        f.write(m_raw)
    for raw, kind in ((p_raw, "dbp"), (s_raw, "dbs")):
        if raw:
            with io.open(_stage_path(staging_id, kind), "wb") as f:
                f.write(raw)
    with io.open(_stage_path(staging_id, "meta"), "w", encoding="utf-8") as f:
        json.dump({"file_name": master.filename or "upload.csv", "origin": origin,
                   "eav": bool(p_raw), "ok": summary["ok"]}, f, ensure_ascii=False)

    return {
        "staging_id": staging_id,
        "file_name": master.filename,
        "origin": origin,
        "eav_included": bool(p_raw),
        "summary": summary,
        "impact": impact,
        # 화면이 그대로 쓰는 문장 — 무엇이 일어나고 무엇이 안 일어나는지 먼저 말한다
        "verdict": (
            f"{summary['row_total']:,}행을 읽어 {summary['ok']:,}건을 넣을 계획입니다"
            f"(신규 {impact['new']:,} · 갱신 {impact['update']:,}"
            f" · 검수 새로 회부 {impact['review_new']:,} · 제외 {summary['skipped_total']:,}"
            f" · 오류 {summary['error']:,})."
            + (f" 추천 후보는 {impact['pool_in']:,}건 늘고 {impact['pool_out']:,}건 빠집니다."
               if (impact["pool_in"] or impact["pool_out"]) else
               " 추천 후보 구성은 바뀌지 않습니다.")
            + ("" if summary["spec_rows"] else
               " 사양 EAV를 올리지 않아 사양은 상품명·스펙 원문에서만 추출됩니다"
               " — 이미 확인된 사양은 그대로 유지됩니다(적재는 채우기만 하고 지우지 않습니다).")),
        "warning": ("적재는 상품코드 기준 덮어쓰기이며 삭제는 없습니다."
                    " 운영자가 잠근(locked) 매입가·판매가는 덮지 않습니다."
                    " 적용 후 되돌리기는 없습니다 — 이전 값 스냅샷을 남기지 않습니다."),
        "note": "확인 후 apply에 staging_id와 expect_ok를 그대로 보내십시오.",
    }


@router.post("/catalog-import/apply")
def apply(staging_id: str = Form(...), expect_ok: int = Form(...)):
    """드라이런에서 본 그 파일, 그 건수일 때만 반영한다."""
    meta_path = _stage_path(staging_id, "meta")
    if not os.path.exists(meta_path):
        raise HTTPException(404, "업로드가 만료되었거나 없습니다 — 파일을 다시 올려 주세요")
    with io.open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    with io.open(_stage_path(staging_id, "master"), "rb") as f:
        m_raw = f.read()
    p_raw = s_raw = None
    if meta.get("eav"):
        with io.open(_stage_path(staging_id, "dbp"), "rb") as f:
            p_raw = f.read()
        with io.open(_stage_path(staging_id, "dbs"), "rb") as f:
            s_raw = f.read()

    rows = read_master(m_raw)
    kvs, feats = load_eav(p_raw, s_raw)
    with engine.connect() as conn:
        refs = read_refs(conn)
    plan = build_plan(rows, kvs, feats, refs, meta["origin"])
    got_ok = len(plan["prods"])
    if got_ok != expect_ok:
        # 재계산이 드라이런과 다르다 = 그 사이 DB가 바뀌었다(다나와 점유·잠금 등).
        # 운영자가 본 리포트와 다른 일을 하지 않는다.
        raise HTTPException(409, {
            "error": "plan_changed",
            "detail": f"확인하신 {expect_ok:,}건과 지금 계획 {got_ok:,}건이 다릅니다"
                      " — 그 사이 상품 데이터가 바뀌었습니다. 다시 검증해 주세요.",
            "expect_ok": expect_ok, "now_ok": got_ok})

    op = current_operator() or {}
    with engine.begin() as conn:
        job_id = apply_plan(conn, plan, meta["file_name"], meta["origin"],
                            operator_id=op.get("operator_id") or 1)
        after = {
            "catalog": conn.execute(text("SELECT count(*) FROM products")).scalar_one(),
            "pool": conn.execute(text(
                "SELECT count(*) FROM v_recommendation_candidates"
                " WHERE stock_qty > 0")).scalar_one(),
            "review": conn.execute(text(
                "SELECT count(*) FROM product_reviews"
                " WHERE review_status = '대기'")).scalar_one(),
        }
    # 지우기 «전에» 보관한다(요청 39). 보관에 실패해도 적재는 이미 끝났으므로
    # 요청을 실패로 만들지 않는다 — 대신 무엇이 안 남았는지 응답에 밝힌다
    # (슬라이스 81 과 같은 취지: 파일을 못 써도 조용히 넘어가지 않는다).
    archived, archive_error = [], None
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        for kind in ("master", "dbp", "dbs"):
            src = _stage_path(staging_id, kind)
            if os.path.exists(src):
                shutil.copyfile(src, _archive_path(job_id, kind))
                archived.append(kind)
        with io.open(_archive_path(job_id, "meta"), "w", encoding="utf-8") as f:
            json.dump({"file_name": meta["file_name"], "origin": meta["origin"],
                       "kinds": archived}, f, ensure_ascii=False)
    except OSError as e:
        archive_error = f"{type(e).__name__}: {e}"
        archived = []

    for kind in ("master", "dbp", "dbs", "meta"):
        try:
            os.remove(_stage_path(staging_id, kind))
        except OSError:
            pass

    s = plan_summary(plan)
    return {
        "job_id": job_id, "ok": s["ok"], "review": s["review"], "error": s["error"],
        "after": after,
        "archived": archived,
        "archive_error": archive_error,
        "verdict": (f"배치 #{job_id} 적재 완료 — {s['ok']:,}건 반영."
                    f" 현재 카탈로그 {after['catalog']:,}건 ·"
                    f" 추천 후보 {after['pool']:,}건 · 검수 대기 {after['review']:,}건."
                    + (f" 올린 파일 {len(archived)}개를 보관했습니다(다시 내려받을 수 있습니다)."
                       if archived else
                       " ⚠ 올린 파일을 보관하지 못했습니다 — 적재는 정상입니다.")),
    }


# ── 적재한 원본 다시 받기 (요청 39 · 2026-08-31) ─────────────────────────────
#   ⚠ **2026-08-31 이전 배치는 파일이 없다.** 그때는 apply 가 스테이징을 지우기만 했고
#     보관하지 않았다 — 없는 것을 있는 척하지 않고 404 로 그 사실을 말한다.

@router.get("/catalog-import/jobs/{job_id}/files")
def job_files(job_id: int):
    """이 배치에 보관된 파일 목록. 화면이 내려받기 단추를 그릴지 이걸로 정한다."""
    op = current_operator() or {}
    if op.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 적재 원본을 볼 수 있습니다")
    meta_p = _archive_path(job_id, "meta")
    if not os.path.exists(meta_p):
        return {"job_id": job_id, "items": [],
                "note": "이 배치는 원본을 보관하지 않았습니다"
                        " — 원본 보관은 2026-08-31 적재분부터입니다."}
    with io.open(meta_p, encoding="utf-8") as f:
        meta = json.load(f)
    items = []
    for kind in meta.get("kinds") or []:
        p = _archive_path(job_id, kind)
        if os.path.exists(p):
            items.append({"kind": kind, "label": ARCHIVE_KINDS.get(kind, kind),
                          "bytes": os.path.getsize(p)})
    return {"job_id": job_id, "file_name": meta.get("file_name"),
            "origin": meta.get("origin"), "items": items}


@router.get("/catalog-import/jobs/{job_id}/files/{kind}")
def job_file_download(job_id: int, kind: str):
    op = current_operator() or {}
    if op.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 적재 원본을 내려받을 수 있습니다")
    if kind not in ARCHIVE_KINDS:
        raise HTTPException(400, "잘못된 파일 종류")
    path = _archive_path(job_id, kind)
    if not os.path.exists(path):
        raise HTTPException(404, "보관된 파일이 없습니다"
                                 " — 원본 보관은 2026-08-31 적재분부터입니다.")
    # 내려받는 이름은 **올릴 때 그 이름**을 쓴다 — 운영자가 자기 파일로 알아본다.
    meta_p = _archive_path(job_id, "meta")
    base = f"import-{job_id}"
    if os.path.exists(meta_p):
        with io.open(meta_p, encoding="utf-8") as f:
            base = (json.load(f).get("file_name") or base)
    stem, ext = os.path.splitext(base)
    name = f"{stem}{ext or '.csv'}" if kind == "master" else f"{stem}-{kind}{ext or '.csv'}"
    return FileResponse(path, media_type="text/csv", filename=name)
