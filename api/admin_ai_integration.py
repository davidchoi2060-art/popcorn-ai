"""AI 연동 설정(ADM-AI-040) — 프로바이더 연결 상태 + 한도 정책. `api/main.py`가 자동으로
싣는다(§discovery, `api/main.py` 상단 주석 참조). 페이지 라우트는 `admin_ui_ai_integration.py`.

■ 이 화면이 절대 하지 않는 일 — **키 값을 입력·수정·삭제하지 않는다**(CANON §2-5,
  `docs/design/req/req-ai-integration.md` ⑤). 그래서 이 파일에 키 문자열을 저장하는
  컬럼·바디 필드가 하나도 없다. "연결 상태"는 **env 키 존재 여부만** 본다 —
  프로바이더에 네트워크 호출을 보내지 않는다(이 화면을 여는 것으로 과금이 생기지 않는다).

  3분류 판정(`_env_state`):
    · 미설정(unset) — 환경변수 자체가 없다(`os.environ`에 키 이름이 없음).
    · 설정됨(ok)    — 있고 값이 비어 있지 않다.
    · 확인 실패(fail) — **있지만 값이 빈 문자열/공백뿐이다.** 네트워크 확인을 하지 않는
      이 화면에서 "실패"가 발생할 수 있는 유일한 로컬 근거다 — `.env`에 `KEY=` 처럼
      선언만 되고 값을 채우지 않은 상태. "없음"(처음부터 항목이 없음)과 "못 함"(선언은
      했는데 확인이 안 됨)을 같은 말로 쓰지 않기 위한 구분이다(요구사항 ⑦).
  오늘 실측 상태(2026-08-13, `req-ai-integration.md` ④): 3개 프로바이더 전부 `.env`에
  키 항목 자체가 없다 → 3종 전부 "미설정"이 정직한 결과다.

■ 프로바이더·작업·동작 카탈로그 — DB 테이블이 없다(조사자 datamap 실측: "코드화 안 됨").
  정본은 `docs/decisions/decision-log.md` A-35(프로바이더 3사·작업 4종 확정)와
  `docs/design/dc-ai-integration.html`(모델명·envKey·동작 4종 제안값)이다. 이 두 파일이
  이 모듈의 **구조**(벤더 3사·작업 4종·동작 4종)의 근거이므로, 그 구조를 바꾸려면
  그 결정이 먼저 바뀌어야 한다.

  ⚠ **구체적 모델 ID 문자열은 예외다(2026-08-16 갱신)** — dc-ai-integration.html이
  제안값을 적던 시점엔 세 모델 다 최신이었지만 이후 세대가 갈렸다(gpt-5-codex →
  gpt-5.6-sol · claude-opus-4-8 → claude-opus-5 · gemini-2.5-pro → gemini-3.7-flash).
  모델 세대는 A-35의 결정 대상이 아니라 각 회사가 바꾸는 사실이라 낡으면 그 자체가
  결함이다. 지금 값은 `api/llm.py`의 `PROVIDERS[...].default_model`과 같다(그 파일이
  실제 호출에 쓰는 값 — 실측 근거는 그 파일 docstring, 2026-08-16 확인:
  GET /v1/models·공식 단가 문서 대조). 이 필드는 프로바이더당 **대표 모델 하나**만
  담는다 — 작업별로 다른 모델을 쓰는 세부 배정은 `api/admin_ai_tasks.py`의
  `PROVIDER_CATALOG`/작업별 배정 소관이다(그 파일에서 카탈로그 전체를 고를 수 있다).
  단가($/1M 토큰)는 여기 두지 않는다 — 정본은 `api/llm.py`의 `ModelPricing`
  하나다(중복하면 갈라진다, `api/admin_ai_tasks.py` docstring도 같은 근거).

■ 한도 저장 — `cost_thresholds`·`rate_limit_policies`는 이미 있는 테이블이다(0행,
  컬럼 충분 — 마이그레이션 불필요, 실측 `db/migrations/versions/0001_initial_schema.py`).
  `key`가 자유문자열 PK라 **프로바이더 전체 한도는 `key=provider`**, **작업별 부분
  한도는 `key=f"{provider}:{task_key}"`**로 같은 테이블에 함께 둔다(스키마 변경 없이
  두 축을 표현). 값이 없는 행은 "0"이 아니라 **없음(None)**으로 응답한다 — 저장한 적
  없는 한도를 0으로 보여주면 그 자체가 지어낸 숫자다.

■ 이력 — 전용 이력 테이블을 새로 만들지 않는다. 조사자 datamap 실측: `ops_settings_history`는
  시드 2행뿐 실제 writer가 없고, `admin_operator_activity_logs`(5,118행)가 실제로
  쓰이는 이력 경로다. 그래서 저장은 `admin_orders._log`(기존 3개 모듈이 이미 재사용
  중인 헬퍼 — `admin_ops.py` 참조)를 그대로 불러 `target_kind='ai_integration'`으로 남긴다.

■ 권한 — 한도 저장은 **owner 전용**(요구사항 ①). `api/auth.py`의 `OWNER_WRITE_PREFIXES`에
  `/api/admin/ai-integration`이 아직 등록돼 있지 않다(그 파일은 제작자 셋의 공유 파일이라
  이 세션에서 고치지 않는다 — 보고서에 등록 요청을 남긴다). 등록 전에도 안전하도록
  **엔드포인트 자체가 `current_operator()`로 owner 여부를 직접 검사한다**
  (`api/auth.issue_password`가 쓰는 것과 같은 패턴).
"""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .admin_orders import _log
from .auth import current_operator
from .db import engine
from .timeutil import iso, now_iso

router = APIRouter(prefix="/api/admin/ai-integration")

# ── 카탈로그(코드 상수 — 위 모듈 docstring 참조: DB 테이블 없음, A-35 + 디자인 원안이 근거) ──
# 모델 ID는 2026-08-16 갱신 — api/llm.py의 PROVIDERS[...].default_model과 동일 문자열
# (그 파일이 실제 호출에 쓰는 값, GET /v1/models·공식 단가 문서로 실측 확인됨).
PROVIDERS = [
    {"key": "codex", "vendor": "Codex", "company": "OpenAI",
     "env_key": "OPENAI_API_KEY", "model": "gpt-5.6-sol"},
    {"key": "claude", "vendor": "Claude", "company": "Anthropic",
     "env_key": "ANTHROPIC_API_KEY", "model": "claude-opus-5"},
    {"key": "gemini", "vendor": "Gemini", "company": "Google",
     "env_key": "GEMINI_API_KEY", "model": "gemini-3.7-flash"},
]
PROVIDER_MAP = {p["key"]: p for p in PROVIDERS}

TASKS = [
    {"key": "task.s1_parse", "label": "입력 파싱"},
    {"key": "task.s2_explain", "label": "근거 설명"},
    {"key": "task.ops_assist", "label": "운영 도우미"},
    {"key": "task.spec_fill", "label": "웹 사양 채움"},
]
TASK_KEYS = [t["key"] for t in TASKS]

ACTIONS = [
    {"key": "batch_defer", "label": "배치만 연기 (고객 대면은 유지)",
     "desc": "한도를 넘으면 specfiller 같은 배치를 미루고, 고객이 쓰는 파싱·설명은 계속합니다"},
    {"key": "stop", "label": "호출 즉시 중단",
     "desc": "고객 대면 기능까지 멈춥니다 — 사고 대응용"},
    {"key": "fallback", "label": "폴백 프로바이더로 전환",
     "desc": "AI 작업 설정의 폴백 사슬을 그대로 씁니다"},
    {"key": "warn", "label": "경고만 보내고 계속",
     "desc": "한도를 관측용으로만 씁니다"},
]
ACTION_KEYS = {a["key"] for a in ACTIONS}

STATE_LABEL = {"ok": "설정됨", "fail": "확인 실패", "unset": "미설정"}
# 표 행(짧게)·드로어(그대로) 둘 다 이 문구를 쓴다 — 자리마다 다시 쓰면 언젠가 말이 갈린다.
STATE_NOTE = {
    "ok": "env에 키가 있습니다. 값 자체는 서버 밖으로 나오지 않으며 이 화면은 존재 여부만 봅니다.",
    "fail": ("키는 있는데 값이 비어 있습니다 — 확인 절차가 실패했습니다."
             " \"미설정\"과 다른 상태이므로 같은 말로 쓰지 않습니다."),
    "unset": ("env에 키 항목 자체가 없습니다 — 확인 대상이 아닙니다."
              " 키는 서버에서만 넣을 수 있고 이 화면에는 입력 칸이 없지만,"
              " 한도는 지금 미리 정해 둘 수 있습니다."),
}

NOTE = ("연결 확인은 env 키 존재 여부만 봅니다 — 프로바이더에 호출을 보내지 않으므로"
        " 이 화면을 여는 것으로 과금이 생기지 않습니다.")


def _env_state(env_key: str) -> str:
    """env 키 존재 여부만으로 판정한다(네트워크 호출 없음) — 모듈 docstring 참조."""
    raw = os.environ.get(env_key)
    if raw is None:
        return "unset"
    return "fail" if raw.strip() == "" else "ok"


def _num(v):
    return float(v) if v is not None else None


def _read_many(conn, provider_keys: list[str]) -> dict[str, dict]:
    """provider 전체 한도 + 작업별 부분 한도 + 호출 제한을 한 번에 읽는다.

    GET(전체 3개 배치 조회)·POST(단일 프로바이더 before/after)가 이 함수 하나를 같이 쓴다
    — 같은 판정을 두 곳에서 다시 구현하지 않는다.
    """
    if not provider_keys:
        return {}
    all_keys = list(provider_keys) + [f"{pk}:{tk}" for pk in provider_keys for tk in TASK_KEYS]
    thr = {r["key"]: r for r in conn.execute(text(
        "SELECT key, daily_usd, action, updated_at FROM cost_thresholds WHERE key = ANY(:ks)"),
        {"ks": all_keys}).mappings().all()}
    rl = {r["key"]: r for r in conn.execute(text(
        "SELECT key, per_minute, per_day, updated_at FROM rate_limit_policies WHERE key = ANY(:ks)"),
        {"ks": provider_keys}).mappings().all()}
    out = {}
    for pk in provider_keys:
        base = thr.get(pk)
        rate = rl.get(pk)
        stamps = [x["updated_at"] for x in ([base] if base else []) + ([rate] if rate else [])
                  if x and x["updated_at"]]
        out[pk] = {
            "daily_usd": _num(base["daily_usd"]) if base else None,
            "action": base["action"] if base else None,
            "per_minute": rate["per_minute"] if rate else None,
            "per_day": rate["per_day"] if rate else None,
            "sub": {tk: (_num(thr[f"{pk}:{tk}"]["daily_usd"]) if thr.get(f"{pk}:{tk}") else None)
                    for tk in TASK_KEYS},
            "updated_at": iso(max(stamps)) if stamps else None,
        }
    return out


@router.get("/status")
def status():
    keys = [p["key"] for p in PROVIDERS]
    with engine.connect() as conn:
        limits = _read_many(conn, keys)
    now = now_iso()
    counts = {"ok": 0, "fail": 0, "unset": 0}
    providers_out = []
    for p in PROVIDERS:
        st = _env_state(p["env_key"])
        counts[st] += 1
        providers_out.append({
            "key": p["key"], "vendor": p["vendor"], "company": p["company"],
            "env_key": p["env_key"], "model": p["model"],
            "state": st, "state_label": STATE_LABEL[st], "state_note": STATE_NOTE[st],
            "checked_at": now,
            "limit": limits[p["key"]],
        })
    return {
        "generated_at": now, "note": NOTE,
        "tasks": TASKS, "actions": ACTIONS, "counts": counts,
        "providers": providers_out,
    }


class LimitBody(BaseModel):
    daily_usd: float | None = None
    per_minute: int | None = None
    per_day: int | None = None
    action: str | None = None
    sub: dict[str, float | None] = {}


@router.post("/limits/{provider}")
def set_limit(provider: str, body: LimitBody):
    op = current_operator()
    if op is None or op.get("role") != "owner":
        raise HTTPException(
            403, f"권한이 부족합니다 (필요: owner, 현재: {op['role'] if op else '로그인 필요'})")
    if provider not in PROVIDER_MAP:
        raise HTTPException(404, f"알 수 없는 프로바이더입니다: {provider}")
    if body.daily_usd is None or body.daily_usd <= 0:
        raise HTTPException(400, "일 한도는 0보다 커야 합니다")
    if body.action is not None and body.action not in ACTION_KEYS:
        raise HTTPException(400, f"알 수 없는 동작입니다: {body.action}")
    if body.per_minute is not None and body.per_minute <= 0:
        raise HTTPException(400, "분당 호출 제한은 0보다 커야 합니다")
    if body.per_day is not None and body.per_day <= 0:
        raise HTTPException(400, "일 호출 제한은 0보다 커야 합니다")
    unknown_sub = set((body.sub or {}).keys()) - set(TASK_KEYS)
    if unknown_sub:
        raise HTTPException(400, f"알 수 없는 작업 종류입니다: {', '.join(sorted(unknown_sub))}")

    with engine.begin() as conn:
        before = _read_many(conn, [provider])[provider]

        merged_sub = dict(before["sub"])
        for tk, v in (body.sub or {}).items():
            merged_sub[tk] = v
        sub_total = sum(v for v in merged_sub.values() if v is not None)
        if sub_total > body.daily_usd:
            raise HTTPException(
                400, f"부분 한도 합계 ${sub_total:g}가 프로바이더 한도 ${body.daily_usd:g}를 넘습니다")

        action = body.action if body.action is not None else before["action"]
        conn.execute(text(
            "INSERT INTO cost_thresholds (key, daily_usd, action, updated_at)"
            " VALUES (:k, :d, :a, now())"
            " ON CONFLICT (key) DO UPDATE SET daily_usd = EXCLUDED.daily_usd,"
            " action = EXCLUDED.action, updated_at = now()"),
            {"k": provider, "d": body.daily_usd, "a": action})

        per_minute = body.per_minute if body.per_minute is not None else before["per_minute"]
        per_day = body.per_day if body.per_day is not None else before["per_day"]
        conn.execute(text(
            "INSERT INTO rate_limit_policies (key, per_minute, per_day, updated_at)"
            " VALUES (:k, :m, :d, now())"
            " ON CONFLICT (key) DO UPDATE SET per_minute = EXCLUDED.per_minute,"
            " per_day = EXCLUDED.per_day, updated_at = now()"),
            {"k": provider, "m": per_minute, "d": per_day})

        for tk, v in (body.sub or {}).items():
            conn.execute(text(
                "INSERT INTO cost_thresholds (key, daily_usd, action, updated_at)"
                " VALUES (:k, :d, NULL, now())"
                " ON CONFLICT (key) DO UPDATE SET daily_usd = EXCLUDED.daily_usd,"
                " updated_at = now()"),
                {"k": f"{provider}:{tk}", "d": v})

        after = _read_many(conn, [provider])[provider]
        changed = {}
        for k in ("daily_usd", "per_minute", "per_day", "action"):
            if before[k] != after[k]:
                changed[k] = {"from": before[k], "to": after[k]}
        for tk in TASK_KEYS:
            if before["sub"][tk] != after["sub"][tk]:
                changed.setdefault("sub", {})[tk] = {"from": before["sub"][tk], "to": after["sub"][tk]}

        if not changed:
            return {"ok": True, "provider": provider, "limit": after, "changed": {},
                    "message": "변경 사항이 없습니다"}

        log_id = _log(conn, "ai_integration_limit_update", provider,
                       {"before": before, "after": after, "changed": changed},
                       kind="ai_integration")
        n = sum(len(v) if k == "sub" else 1 for k, v in changed.items())
        return {"ok": True, "provider": provider, "limit": after, "changed": changed,
                "undo_id": log_id, "message": f"저장했습니다 — 변경 {n}건 기록"}
