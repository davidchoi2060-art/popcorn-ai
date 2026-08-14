# -*- coding: utf-8 -*-
"""AI 작업 설정(ADM-AI-030) API — 작업 종류 <-> 프로바이더/모델 배정 (A-35).

■ 위치
  화면 라우트는 `api/admin_ui_ai_task_settings.py`(별도 파일 — §단일 원천 규약:
  "화면 하나 = api/admin_ui_<screen>.py 파일 하나"). 이 파일은 그 화면이 부르는
  REST API만 담는다.

■ 데이터
  현재값 = `ai_task_assignments`(마이그레이션 0046, DBA 적용 대기 — 미적용이면
  `ready=False`로 응답한다. **테이블이 없다고 500을 내지 않는다.**).
  변경 이력 = 새 테이블이 아니라 기존 `admin_operator_activity_logs`
  (`target_kind='ai_task'`) — 근거는 0046 마이그레이션 docstring 참조.

■ 닫힌 목록 (A-35, decision-log.md 2026-08-13 사장님 확정)
  작업 종류 4종 · 프로바이더 3사(Codex·Claude·Gemini)는 여기 상수가 정본이다.
  task_key 4종의 근거는 A-35 원문. 벤더+모델 구체 문자열(gpt-5-codex 등)은 A-35
  원문에는 없고 화면 정본 `docs/design/dc-ai-task-settings.html`의 JS 상수가 유일한
  구체적 소재다(조사자 실측 — "디자인 산출물이 유일한 구체적 소재"). DB화하지 않은
  이유: 이 화면은 배정을 저장하는 화면이지 프로바이더 카탈로그를 관리하는 화면이
  아니다(비범위) — 실제 연동 착수 시 AI 연동 설정(ADM-AI-040) 쪽에서 카탈로그를
  다루게 되면 그때 단일 원천을 그리로 옮긴다.

■ owner 전용 쓰기
  `api/auth.py`의 `OWNER_WRITE_PREFIXES`에 `/api/admin/ai-task-settings`가 아직
  등록돼 있지 않다(그 파일은 공유 파일이라 이 화면 담당이 직접 고치지 않는다 —
  하네스가 반영한다. 제작 보고서 참조). 그래서 이 파일은 **`_owner()`로 직접
  가드한다**(`api/admin_usage_floors.py`가 이미 같은 이유로 쓰는 이중 가드 패턴 —
  프리픽스가 나중에 등록돼도 무해하게 중복된다).
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin")

# ── 닫힌 목록 (A-35) ─────────────────────────────────────────────────────
TASK_CATALOG = [
    {"key": "task.s1_parse", "label": "입력 파싱",
     "note": "고객 문장을 구조화 입력으로 — 견적은 만들지 않는다(A-02)"},
    {"key": "task.s2_explain", "label": "근거 설명",
     "note": "엔진이 고른 조합을 말로 설명 — 선택은 하지 않는다(A-03)"},
    {"key": "task.ops_assist", "label": "운영 도우미 질의",
     "note": "운영자 질문 응답 — 같은 경계 규칙을 받는다"},
    {"key": "task.spec_fill", "label": "웹 사양 채움",
     "note": "specfiller 배치가 쓰는 모델 — 실행은 ADM-AI-020 소관"},
]
TASK_META = {t["key"]: t for t in TASK_CATALOG}
TASK_KEYS = set(TASK_META)

# 구체적 벤더+모델 문자열의 유일한 소재 = docs/design/dc-ai-task-settings.html (위 docstring)
PROVIDER_CATALOG = [
    {"vendor": "Codex", "model": "gpt-5-codex"},
    {"vendor": "Codex", "model": "gpt-5-mini"},
    {"vendor": "Claude", "model": "claude-opus-4-8"},
    {"vendor": "Claude", "model": "claude-sonnet-4-5"},
    {"vendor": "Gemini", "model": "gemini-2.5-pro"},
]
PROVIDER_PAIRS = {(p["vendor"], p["model"]) for p in PROVIDER_CATALOG}

ROLE_OPTIONS = ["기준 해석", "교차 확인", "주", "폴백 전용"]

# "문서 간 불일치" 패널 — A-35가 실제로 해소한 두 결정을 그대로 보여준다(지어낸 문구
# 아님, decision-log.md A-35 원문 발췌·요약).
CONFLICTS = [
    {"date": "2026-07-21", "title": "LLM 실연동 파일럿 보류", "badge": "프로바이더 1개",
     "desc": "Claude Opus 4.8 단일, 팝콘톡 파일럿 한정. 별도 승인 전까지 실행 없음.",
     "adopted": False},
    {"date": "2026-08-09", "title": "UX-14 부속 · AI 축", "badge": "프로바이더 3개 - A-35가 채택",
     "desc": "Codex·Claude·Gemini 역할분담 + 폴백. 교차 검증은 주목적이 아님.",
     "adopted": True},
]

DEFAULT_PROVIDERS = [{"vendor": "Claude", "model": "claude-opus-4-8", "role": "주"}]

NOT_READY_MSG = ("설정 테이블이 아직 준비되지 않았습니다 — 마이그레이션 0046이 적용된 뒤"
                  " 다시 시도하세요(DBA 적용 대기).")


def _owner() -> dict:
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(
            403, f"권한이 부족합니다 (필요: owner, 현재: {me.get('role') or '(로그인 필요)'})")
    return me


def _ready(conn) -> bool:
    """마이그레이션 0046 적용 여부. 없다고 500을 내지 않고 화면이 '원천 준비 중'을 말하게 한다."""
    return sa_inspect(conn).has_table("ai_task_assignments")


def _mode_label(m: str) -> str:
    return "동시 호출·수렴" if m == "concurrent" else "단일 + 폴백"


def _fmt_providers(ps: list) -> str:
    return "[" + ", ".join(f"{p['vendor']}({p['role']})" for p in (ps or [])) + "]"


def _fmt_fallback(fb: list) -> str:
    return "[" + ", ".join(fb or []) + "]"


def _fmt_prompt(v) -> str:
    return v or "미지정"


def _task_out(row, prompt_options: list) -> dict:
    meta = TASK_META.get(row["task_key"], {})
    return {
        "task_key": row["task_key"],
        "label": meta.get("label", row["task_key"]),
        "note": meta.get("note", ""),
        "mode": row["mode"], "mode_label": _mode_label(row["mode"]),
        "providers": row["providers"] or [],
        "fallback_order": row["fallback_order"] or [],
        "prompt_version": row["prompt_version"],
        "prompt_options": prompt_options,
        "updated_by": row["updated_by"], "updated_at": iso(row["updated_at"]),
        "created_at": iso(row["created_at"]),
    }


def _prompt_options(conn, task_key: str, current: str | None) -> list:
    """이 작업에 실제로 쓰였던 프롬프트 버전 값 — 지어낸 카탈로그가 아니라 변경 이력에서
    파생한다(값 = 과거 저장 시점에 실제로 저장됐던 prompt_version). 현재값도 맨 앞에 넣는다."""
    rows = conn.execute(text(
        "SELECT detail->>'after' AS v, MIN(created_at) AS at"
        " FROM admin_operator_activity_logs"
        " WHERE target_kind = 'ai_task' AND target_id = :k"
        "   AND action = 'ai_task_update' AND detail->>'field' = 'prompt_version'"
        "   AND detail->>'after' IS NOT NULL"
        " GROUP BY detail->>'after' ORDER BY MIN(created_at) DESC"),
        {"k": task_key}).mappings().all()
    seen = set()
    out = []
    if current:
        out.append({"version": current, "at": None})
        seen.add(current)
    for r in rows:
        v = r["v"]
        if not v or v in seen:
            continue
        seen.add(v)
        out.append({"version": v, "at": iso(r["at"])})
    return out


def _next_version(conn) -> int:
    """이력 화면의 'vN' 배지 — 작업별이 아니라 이 설정 전체에 걸친 전역 순번(원안과 동일
    개념: 원안 state.ver는 태스크별이 아니라 화면 전체 공유 카운터였다)."""
    v = conn.execute(text(
        "SELECT COALESCE(MAX((detail->>'version')::int), 0)"
        " FROM admin_operator_activity_logs WHERE target_kind = 'ai_task'")).scalar_one()
    return int(v or 0) + 1


def _validate_task_key(k: str):
    if k not in TASK_KEYS:
        raise HTTPException(400, f"알 수 없는 작업 종류입니다: {k} — 목록은 4종으로 닫혀 있습니다")


class ProviderIn(BaseModel):
    vendor: str
    model: str
    role: str


class UpdateTaskBody(BaseModel):
    mode: str
    providers: list[ProviderIn]
    fallback_order: list[str] = []
    prompt_version: str | None = None
    reason: str | None = None


class CreateTaskBody(BaseModel):
    task_key: str
    reason: str | None = None


def _validate_update(body: UpdateTaskBody):
    if body.mode not in ("concurrent", "single"):
        raise HTTPException(400, f"알 수 없는 모드입니다: {body.mode}")
    if not body.providers:
        raise HTTPException(400, "최소 1개의 프로바이더가 필요합니다")
    if body.mode == "concurrent" and len(body.providers) < 2:
        raise HTTPException(400, "동시 호출은 프로바이더가 2곳 이상이어야 합니다")
    for p in body.providers:
        if (p.vendor, p.model) not in PROVIDER_PAIRS:
            raise HTTPException(400, f"알 수 없는 프로바이더입니다: {p.vendor}/{p.model}")
        if p.role not in ROLE_OPTIONS:
            raise HTTPException(400, f"알 수 없는 역할입니다: {p.role}")
    vendors = {p.vendor for p in body.providers}
    seen_fb = set()
    for v in body.fallback_order:
        if v not in vendors:
            raise HTTPException(400, f"폴백은 배정된 프로바이더 안에서만 선택할 수 있습니다: {v}")
        if v in seen_fb:
            raise HTTPException(400, f"폴백 순서에 같은 프로바이더가 중복됩니다: {v}")
        seen_fb.add(v)


def _compute_diffs(before: dict, after: dict, task_key: str) -> list:
    """(field, what, before_val, after_val) 목록. 화살표는 ASCII '->' 만 쓴다 —
    서버 stdout이 cp949라 유니코드 화살표가 로그 경로에서 500을 낸 전례가 있다
    (CLAUDE.md '함정' — 이 값이 예외 메시지 등으로 콘솔에 찍힐 가능성을 원천 차단)."""
    out = []
    if before["mode"] != after["mode"]:
        out.append(("mode", f"{task_key}.mode: {_mode_label(before['mode'])} -> {_mode_label(after['mode'])}",
                     before["mode"], after["mode"]))
    bp, ap = _fmt_providers(before["providers"]), _fmt_providers(after["providers"])
    if bp != ap:
        out.append(("providers", f"{task_key}.providers: {bp} -> {ap}", bp, ap))
    bf, af = _fmt_fallback(before["fallback_order"]), _fmt_fallback(after["fallback_order"])
    if bf != af:
        out.append(("fallback_order", f"{task_key}.fallback: {bf} -> {af}", bf, af))
    bpv, apv = before.get("prompt_version") or None, after.get("prompt_version") or None
    if bpv != apv:
        out.append(("prompt_version",
                     f"{task_key}.prompt_version: {_fmt_prompt(bpv)} -> {_fmt_prompt(apv)}", bpv, apv))
    return out


# ───────────────────────────── 조회 ─────────────────────────────
@router.get("/ai-task-settings")
def get_settings():
    with engine.connect() as conn:
        ready = _ready(conn)
        tasks: list = []
        unassigned = list(TASK_CATALOG)
        history_count = 0
        if ready:
            rows = conn.execute(text(
                "SELECT task_key, mode, providers, fallback_order, prompt_version,"
                " updated_by, updated_at, created_at FROM ai_task_assignments"
                " ORDER BY created_at")).mappings().all()
            have = {r["task_key"] for r in rows}
            unassigned = [t for t in TASK_CATALOG if t["key"] not in have]
            for r in rows:
                popts = _prompt_options(conn, r["task_key"], r["prompt_version"])
                tasks.append(_task_out(r, popts))
            history_count = conn.execute(text(
                "SELECT count(*) FROM admin_operator_activity_logs"
                " WHERE target_kind = 'ai_task'")).scalar_one()
    return {
        "ready": ready,
        "reason": None if ready else NOT_READY_MSG,
        "role_options": ROLE_OPTIONS,
        "provider_catalog": PROVIDER_CATALOG,
        "task_catalog": TASK_CATALOG,
        "tasks": tasks,
        "unassigned": unassigned,
        "conflicts": CONFLICTS,
        "history_count": history_count,
    }


@router.get("/ai-task-settings/history")
def get_history(limit: int = 200):
    limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        ready = _ready(conn)
        rows = conn.execute(text(
            "SELECT l.action, l.target_id, l.detail, l.created_at, o.name AS operator"
            " FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " WHERE l.target_kind = 'ai_task'"
            " ORDER BY l.log_id DESC LIMIT :n"), {"n": limit}).mappings().all()
        total = conn.execute(text(
            "SELECT count(*) FROM admin_operator_activity_logs"
            " WHERE target_kind = 'ai_task'")).scalar_one()
    items = []
    for r in rows:
        d = r["detail"] or {}
        ver = d.get("version")
        items.append({
            "at": iso(r["created_at"]), "who": r["operator"] or "—",
            "what": d.get("what") or r["target_id"],
            "why": d.get("reason") or "",
            "ver": f"v{ver}" if ver is not None else "",
        })
    return {"ready": ready, "items": items, "total": total}


# ───────────────────────────── 쓰기 (owner 전용) ─────────────────────────────
@router.post("/ai-task-settings/tasks")
def create_task(body: CreateTaskBody):
    me = _owner()
    _validate_task_key(body.task_key)
    with engine.begin() as conn:
        if not _ready(conn):
            raise HTTPException(503, NOT_READY_MSG)
        exists = conn.execute(text(
            "SELECT 1 FROM ai_task_assignments WHERE task_key = :k"),
            {"k": body.task_key}).first()
        if exists:
            raise HTTPException(409, "이미 배정된 작업입니다")
        conn.execute(text(
            "INSERT INTO ai_task_assignments"
            " (task_key, mode, providers, fallback_order, prompt_version, updated_by)"
            " VALUES (:k, 'single', CAST(:p AS JSONB), '[]'::jsonb, NULL, :who)"),
            {"k": body.task_key, "p": json.dumps(DEFAULT_PROVIDERS), "who": me.get("name")})
        row = conn.execute(text(
            "SELECT task_key, mode, providers, fallback_order, prompt_version,"
            " updated_by, updated_at, created_at FROM ai_task_assignments"
            " WHERE task_key = :k"), {"k": body.task_key}).mappings().first()
        ver = _next_version(conn)
        label = TASK_META.get(body.task_key, {}).get("label", body.task_key)
        what = f"{body.task_key} 배정 생성 -> {_fmt_providers(DEFAULT_PROVIDERS)}"
        _log(conn, "ai_task_create", body.task_key,
             {"what": what, "reason": body.reason or "화면에서 직접 변경", "version": ver,
              "after": {"mode": "single", "providers": DEFAULT_PROVIDERS,
                        "fallback_order": [], "prompt_version": None}},
             kind="ai_task")
    return {"ok": True, "task": _task_out(row, []),
            "message": f"{label} 작업을 추가했습니다 — 이력에 남았습니다 (실행에는 여전히 미적용)"}


@router.patch("/ai-task-settings/tasks/{task_key}")
def update_task(task_key: str, body: UpdateTaskBody):
    me = _owner()
    _validate_task_key(task_key)
    _validate_update(body)
    providers = [p.model_dump() for p in body.providers]
    fallback_order = list(body.fallback_order)
    prompt_version = (body.prompt_version or "").strip() or None

    with engine.begin() as conn:
        if not _ready(conn):
            raise HTTPException(503, NOT_READY_MSG)
        row = conn.execute(text(
            "SELECT mode, providers, fallback_order, prompt_version"
            " FROM ai_task_assignments WHERE task_key = :k FOR UPDATE"),
            {"k": task_key}).mappings().first()
        if row is None:
            raise HTTPException(404, "배정되지 않은 작업입니다 — 먼저 추가하세요")
        before = {"mode": row["mode"], "providers": row["providers"] or [],
                  "fallback_order": row["fallback_order"] or [],
                  "prompt_version": row["prompt_version"]}
        after = {"mode": body.mode, "providers": providers,
                 "fallback_order": fallback_order, "prompt_version": prompt_version}
        diffs = _compute_diffs(before, after, task_key)
        if not diffs:
            raise HTTPException(400, "변경 사항이 없습니다")
        conn.execute(text(
            "UPDATE ai_task_assignments SET mode = :m, providers = CAST(:p AS JSONB),"
            " fallback_order = CAST(:f AS JSONB), prompt_version = :pv,"
            " updated_by = :who, updated_at = now() WHERE task_key = :k"),
            {"m": body.mode, "p": json.dumps(providers), "f": json.dumps(fallback_order),
             "pv": prompt_version, "who": me.get("name"), "k": task_key})
        ver = _next_version(conn)
        reason = body.reason or "화면에서 직접 변경"
        for field, what, bval, aval in diffs:
            _log(conn, "ai_task_update", task_key,
                 {"what": what, "reason": reason, "version": ver,
                  "field": field, "before": bval, "after": aval}, kind="ai_task")
        newrow = conn.execute(text(
            "SELECT task_key, mode, providers, fallback_order, prompt_version,"
            " updated_by, updated_at, created_at FROM ai_task_assignments"
            " WHERE task_key = :k"), {"k": task_key}).mappings().first()
        popts = _prompt_options(conn, task_key, newrow["prompt_version"])
    what_lines = [d[1] for d in diffs]
    return {"ok": True, "task": _task_out(newrow, popts), "diffs": what_lines,
            "message": f"저장했습니다 — 이력 {len(diffs)}건 기록. 연동 보류 상태라 실행에는 미적용입니다."}


@router.delete("/ai-task-settings/tasks/{task_key}")
def delete_task(task_key: str, reason: str | None = None):
    me = _owner()
    _validate_task_key(task_key)
    with engine.begin() as conn:
        if not _ready(conn):
            raise HTTPException(503, NOT_READY_MSG)
        row = conn.execute(text(
            "SELECT mode, providers, fallback_order, prompt_version"
            " FROM ai_task_assignments WHERE task_key = :k FOR UPDATE"),
            {"k": task_key}).mappings().first()
        if row is None:
            raise HTTPException(404, "배정되지 않은 작업입니다")
        conn.execute(text("DELETE FROM ai_task_assignments WHERE task_key = :k"), {"k": task_key})
        ver = _next_version(conn)
        label = TASK_META.get(task_key, {}).get("label", task_key)
        _log(conn, "ai_task_delete", task_key,
             {"what": f"{task_key} 배정 삭제", "reason": reason or "화면에서 직접 변경",
              "version": ver,
              "before": {"mode": row["mode"], "providers": row["providers"] or [],
                         "fallback_order": row["fallback_order"] or [],
                         "prompt_version": row["prompt_version"]}},
             kind="ai_task")
    return {"ok": True, "deleted": task_key, "who": me.get("name"),
            "message": f"{label} 배정을 삭제했습니다 — 이력에 남았습니다 (실행에는 여전히 미적용)"}
