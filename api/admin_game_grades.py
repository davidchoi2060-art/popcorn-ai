"""게임 사양 등급(ADM-TLK-021 · 가칭) — 관리자 데이터 API (2026-10-11 품질관리 · R9·F13).

■ 왜 있는가
  고객이 게임 이름을 말하면 견적은 `game_grade_assignments`(게임 -> 부하 등급)와
  `game_grade_resolution_tiers`(등급 x 해상도 -> 사양 단계)를 읽는다(`api/talk_schema`).
  그런데 관리자 화면은 그 등급을 보기만 했다(`api/admin_grid.py`·`api/admin_game_matrix.py`
  에 쓰기 API 0개). 등급이 틀려도 고칠 길이 없었다.

■ 할 수 있는 일
  게임 목록(검색·등급별) · 게임 하나의 등급 바꾸기(E·A·B·C·S·L·미배정, 이유 필수) ·
  최근 바꾼 기록 · 되돌리기. 바꾸는 순간 해상도별 사양 단계가 같이 보인다.

■ 권한 — 쓰기는 **대표(owner)만**
  등급 하나가 그 게임을 말한 모든 고객의 견적 사양 하한을 바꾼다. 0103 이 「제안 -> 확정
  승인 흐름은 사장님 승인이 먼저」라고 적어 둔 그 확정 배정을 바꾸는 자리라, 대표 권한만
  저장한다. 조회는 누구나 한다.

■ 원장 — 새 이력표를 만들지 않는다
  `admin_operator_activity_logs` 에 `target_kind='game_grade'` 로 남긴다(바꾸기 전·후 값과
  이유). 되돌리기도 그 한 건을 근거로 역방향으로 바꾸고 `ref_log_id` 로 잇는다 —
  「변경 이력」 화면이 그 키로 「되돌려짐」을 표시한다. 행을 지우지 않는다: 미배정은
  `grade = NULL` 이다(`api/talk_schema` 가 NULL 과 행 없음을 같게 본다).

■ 제안 등급(`game_grade_suggestions`)은 참고로만 보여 준다. 여기서 그 표를 쓰지 않는다.
■ 로그는 ASCII 기호만(서버 stdout cp949).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin/game-grades", tags=["admin-game-grades"])
log = logging.getLogger(__name__)

LIMIT = 50
REASON_MAX = 300
RESOLUTIONS = ("1080p", "1440p", "4K")
TARGET_KIND = "game_grade"


def _me() -> dict:
    op = current_operator()
    if not op:
        raise HTTPException(401, "로그인이 필요합니다")
    return op


def _owner() -> dict:
    op = _me()
    if op.get("role") != "owner":
        raise HTTPException(403, "게임 사양 등급은 대표 권한만 바꿀 수 있습니다")
    return op


def _grades(conn) -> list[dict]:
    """등급 어휘와 등급별 해상도 단계 — 화면이 박지 않게 서버가 준다."""
    grades = [dict(r) for r in conn.execute(text(
        "SELECT grade, label, example_titles, note FROM game_load_grades ORDER BY sort_order"
    )).mappings().all()]
    tiers = {r["tier_key"]: r["popcorn_name"] for r in conn.execute(text(
        "SELECT tier_key, popcorn_name FROM spec_tiers")).mappings().all()}
    by_grade: dict[str, dict] = {}
    for r in conn.execute(text(
            "SELECT grade, resolution, gpu_tier_key, cpu_tier_key_override"
            " FROM game_grade_resolution_tiers")).mappings().all():
        by_grade.setdefault(r["grade"], {})[r["resolution"]] = {
            "gpu_tier": r["gpu_tier_key"], "gpu_tier_name": tiers.get(r["gpu_tier_key"]),
            "cpu_tier": r["cpu_tier_key_override"],
            "cpu_tier_name": tiers.get(r["cpu_tier_key_override"]),
        }
    for g in grades:
        g["tiers"] = [{"resolution": res, **by_grade.get(g["grade"], {}).get(res, {})}
                      for res in RESOLUTIONS if res in by_grade.get(g["grade"], {})]
    return grades


def _state(conn, game_id: int, lock: bool = False):
    return conn.execute(text(
        "SELECT g.game_id, g.name, a.game_id IS NOT NULL AS existed, a.grade,"
        "       COALESCE(a.is_confirmed, FALSE) AS is_confirmed, a.note"
        "  FROM games g LEFT JOIN game_grade_assignments a ON a.game_id = g.game_id"
        " WHERE g.game_id = :g" + (" FOR UPDATE OF g" if lock else "")),
        {"g": game_id}).mappings().first()


def _write(conn, game_id: int, grade, is_confirmed: bool, note):
    conn.execute(text(
        "INSERT INTO game_grade_assignments (game_id, grade, is_confirmed, note, assigned_at)"
        " VALUES (:g, :gr, :c, :n, now())"
        " ON CONFLICT (game_id) DO UPDATE SET grade = EXCLUDED.grade,"
        "   is_confirmed = EXCLUDED.is_confirmed, note = EXCLUDED.note, assigned_at = now()"),
        {"g": game_id, "gr": grade, "c": is_confirmed, "n": note})


def _log(conn, op: dict, action: str, game_id: int, detail: dict) -> int:
    return conn.execute(text(
        "INSERT INTO admin_operator_activity_logs"
        " (operator_id, action, target_kind, target_id, detail)"
        " VALUES (:op, :a, :k, :t, CAST(:d AS JSONB)) RETURNING log_id"),
        {"op": op["operator_id"], "a": action, "k": TARGET_KIND, "t": str(game_id),
         "d": json.dumps(detail, ensure_ascii=False)}).scalar()


def _snap(r) -> dict:
    return {"grade": r["grade"], "is_confirmed": bool(r["is_confirmed"]), "note": r["note"]}


# ── 조회 ────────────────────────────────────────────────────────────────────
@router.get("")
def list_games(offset: int = 0, q: str = "", grade: str = ""):
    """게임 목록 — 서버 페이지네이션. `grade='none'` 은 미배정."""
    _me()
    offset = max(0, int(offset or 0))
    q = (q or "").strip()[:40]
    grade = (grade or "").strip()
    where, params = ["TRUE"], {"lim": LIMIT, "off": offset}
    if q:
        where.append("g.name ILIKE :q")
        params["q"] = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
    if grade == "none":
        where.append("a.grade IS NULL")
    elif grade:
        where.append("a.grade = :gr")
        params["gr"] = grade
    w = " AND ".join(where)
    base = (" FROM games g LEFT JOIN game_grade_assignments a ON a.game_id = g.game_id"
            " LEFT JOIN game_grade_suggestions s ON s.game_id = g.game_id WHERE " + w)
    with engine.connect() as conn:
        grades = _grades(conn)
        if grade and grade != "none" and grade not in {g["grade"] for g in grades}:
            raise HTTPException(400, "없는 등급입니다")
        total = conn.execute(text("SELECT count(*)" + base), params).scalar_one()
        rows = conn.execute(text(
            "SELECT g.game_id, g.name, g.genre, a.grade, COALESCE(a.is_confirmed, FALSE) AS is_confirmed,"
            "       a.note, a.assigned_at, s.suggested_grade, s.confidence AS suggested_confidence,"
            "       s.reason AS suggested_reason" + base +
            " ORDER BY g.name, g.game_id LIMIT :lim OFFSET :off"), params).mappings().all()
        counts = dict(conn.execute(text(
            "SELECT COALESCE(a.grade, 'none'), count(*) FROM games g"
            " LEFT JOIN game_grade_assignments a ON a.game_id = g.game_id"
            " GROUP BY 1")).all())
    me = current_operator() or {}
    return {
        "items": [{
            "game_id": r["game_id"], "name": r["name"], "genre": r["genre"],
            "grade": r["grade"], "is_confirmed": bool(r["is_confirmed"]), "note": r["note"],
            "assigned_at": iso(r["assigned_at"]),
            "suggestion": None if r["suggested_grade"] is None and r["suggested_reason"] is None else {
                "grade": r["suggested_grade"], "confidence": r["suggested_confidence"],
                "reason": r["suggested_reason"]},
        } for r in rows],
        "total": total, "offset": offset, "limit": LIMIT,
        "counts": counts, "grades": grades, "can_write": me.get("role") == "owner",
    }


@router.get("/history")
def history(limit: int = 30):
    """최근 바꾼 기록 — 되돌렸는지는 `ref_log_id` 역참조로 판정한다(action 이름을 보지 않는다)."""
    _me()
    limit = max(1, min(int(limit or 30), 100))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT l.log_id, l.action, l.target_id, l.detail, l.created_at, o.name AS operator,"
            "  EXISTS (SELECT 1 FROM admin_operator_activity_logs u"
            "           WHERE u.target_kind = :k AND u.detail->>'ref_log_id' = CAST(l.log_id AS TEXT)) AS undone"
            "  FROM admin_operator_activity_logs l"
            "  LEFT JOIN admin_operators o ON o.operator_id = l.operator_id"
            " WHERE l.target_kind = :k ORDER BY l.created_at DESC, l.log_id DESC LIMIT :lim"),
            {"k": TARGET_KIND, "lim": limit}).mappings().all()
    out = []
    for r in rows:
        d = r["detail"] or {}
        out.append({"log_id": r["log_id"], "game_id": int(r["target_id"]), "game": d.get("game"),
                    "before": (d.get("before") or {}).get("grade"),
                    "after": (d.get("after") or {}).get("grade"),
                    "reason": d.get("reason"), "is_undo": bool(d.get("ref_log_id")),
                    "undone": bool(r["undone"]), "operator": r["operator"],
                    "at": iso(r["created_at"])})
    return {"items": out}


# ── 쓰기 ────────────────────────────────────────────────────────────────────
class GradeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grade: str | None = Field(default=None, max_length=1)
    reason: str = Field(max_length=REASON_MAX)


@router.put("/{game_id}")
def set_grade(game_id: int, body: GradeBody):
    """등급 하나를 바꾼다. 같은 값이면 아무것도 쓰지 않는다. 이유는 필수다."""
    op = _owner()
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "바꾸는 이유를 적어 주세요")
    grade = (body.grade or "").strip() or None
    with engine.begin() as conn:
        if grade is not None and grade not in {g["grade"] for g in _grades(conn)}:
            raise HTTPException(400, "없는 등급입니다")
        cur = _state(conn, game_id, lock=True)
        if cur is None:
            raise HTTPException(404, "없는 게임입니다")
        if cur["grade"] == grade and (grade is None or cur["is_confirmed"]):
            return {"ok": True, "changed": False, "note": "지금 등급과 같아 바꾸지 않았습니다."}
        before = _snap(cur)
        after = {"grade": grade, "is_confirmed": grade is not None,
                 "note": "관리자 변경: " + reason}
        _write(conn, game_id, after["grade"], after["is_confirmed"], after["note"])
        log_id = _log(conn, op, "game_grade_set", game_id,
                      {"game": cur["name"], "existed": bool(cur["existed"]),
                       "before": before, "after": after, "reason": reason})
    log.info("[game-grade] game=%s %s->%s log=%s", game_id, before["grade"], grade, log_id)
    return {"ok": True, "changed": True, "log_id": log_id,
            "note": "%s 등급을 %s(으)로 바꿨습니다. 다음 상담부터 반영됩니다."
                    % (cur["name"], grade or "미배정")}


@router.post("/undo/{log_id}")
def undo(log_id: int):
    """바꾼 기록 한 건을 되돌린다. 그 뒤에 다시 바뀌었으면 되돌리지 않는다(409)."""
    op = _owner()
    with engine.begin() as conn:
        src = conn.execute(text(
            "SELECT log_id, target_id, detail FROM admin_operator_activity_logs"
            " WHERE log_id = :i AND target_kind = :k AND action = 'game_grade_set' FOR UPDATE"),
            {"i": log_id, "k": TARGET_KIND}).mappings().first()
        if src is None:
            raise HTTPException(404, "없는 기록입니다")
        done = conn.execute(text(
            "SELECT 1 FROM admin_operator_activity_logs WHERE target_kind = :k"
            " AND detail->>'ref_log_id' = :i LIMIT 1"), {"k": TARGET_KIND, "i": str(log_id)}).first()
        if done:
            raise HTTPException(409, "이미 되돌린 기록입니다")
        d = src["detail"] or {}
        game_id = int(src["target_id"])
        cur = _state(conn, game_id, lock=True)
        if cur is None:
            raise HTTPException(404, "없는 게임입니다")
        after, before = d.get("after") or {}, d.get("before") or {}
        if cur["grade"] != after.get("grade"):
            raise HTTPException(409, "그 뒤에 등급이 다시 바뀌어 이 기록은 되돌릴 수 없습니다")
        _write(conn, game_id, before.get("grade"), bool(before.get("is_confirmed")), before.get("note"))
        undo_id = _log(conn, op, "game_grade_undo", game_id,
                       {"game": cur["name"], "ref_log_id": log_id,
                        "before": _snap(cur), "after": before, "reason": "되돌림"})
    log.info("[game-grade] undo log=%s by=%s", log_id, undo_id)
    return {"ok": True, "log_id": undo_id,
            "note": "%s 등급을 %s(으)로 되돌렸습니다." % (cur["name"], before.get("grade") or "미배정")}
