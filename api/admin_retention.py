"""보관 기한 · 파기 이력(ADM-SYS-031 · 가칭) — 관리자 데이터 API, 읽기 전용.

2026-10-18 관리자 정리 기획 A05(대표 승인 · 2묶음). 고객 개인정보의 보관 기한이 어디까지 왔는지와
일일 파기 작업(`api/retention_purge`)이 실제로 무엇을 했는지를 **나눠서** 보인다.

■ 기한과 실제 파기는 다른 사실이다
  · 기한 지남      `purge_at <= now()` — 화면이 개인정보를 가린다(표시 제한). 값이 지워졌다는 뜻이 아니다.
  · 값이 남음      기한은 지났는데 아직 값이 있다. 셈은 파기 작업의 대상 조건(`retention_purge.TARGETS`)을
                   그대로 쓴다 — 같은 정의를 두 곳에 적지 않는다(작업 미리보기 건수와 같아야 한다).
  · 지운 시각 기록  `contact_purged_at` 이 있는 행(상담 신청 · 등록 연락처). 문의 원문 · AI 답은 지운
                   시각 칸이 없어 「값 없음」만 알 수 있다 — 지워졌는지 처음부터 없었는지 가르지 않는다.
  · 실행 기록      `retention_purge_runs` 한 줄 = 실행 한 번. 미리보기(dry_run)는 «지울 대상 건수»,
                   실제 실행은 «비운 건수»다. 끝난 시각이 없고 오류도 없으면 결과 미확인으로 둔다.

■ 하지 않는 것 — 실행 · 재시도 · 기한 연장 버튼이 없다. 보유 기간(180일은 임시 코드값 · 대표 미확정)을
  화면에 고정 문구로 적지 않는다. 설정값은 «이 서버 프로세스가 읽은 값»으로만 밝힌다(운영 설정 확인 아님).
  개인정보 값 자체는 싣지 않는다 — 건수와 시각만.
"""
import datetime as dt

from fastapi import APIRouter
from sqlalchemy import text

from . import retention_purge as RP
from .admin_purchase_inquiries import DUE_SOON_DAYS
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-retention"])

RUNS_LIMIT = 50

# 파기 대상마다: 화면 이름 · 기한 칸 · 기한 칸이 naive UTC 인가 · 지운 시각 칸(없으면 None).
# 대상 이름과 표 · 조건은 retention_purge.TARGETS 가 정본이다(여기서는 이름으로만 잇는다).
TARGET_INFO = {
    "talk_raw": ("고객 문의 원문", "raw_purge_at", True, None),
    "talk_reply": ("고객에게 나간 AI 답", "purge_at", False, None),
    "inquiry_contact": ("구매 상담 신청 연락처 · 내용", "purge_at", False, "contact_purged_at"),
    "visitor_contact": ("견적 보관 등록 연락처", "purge_at", False, "contact_purged_at"),
}
EXTRA_COUNTS = {"inquiry_memo": "구매 상담 메모 속 연락처 가림"}


def _params(now):
    naive = now.astimezone(dt.timezone.utc).replace(tzinfo=None)
    soon = dt.timedelta(days=DUE_SOON_DAYS)
    return {"now": now, "now_naive": naive, "soon": now + soon, "soon_naive": naive + soon}


def _summary(conn, now) -> list[dict]:
    p = _params(now)
    out = []
    for name, target, _assign in RP.TARGETS:
        label, col, naive, purged_col = TARGET_INFO[name]
        table, holding_where = RP._split(target)
        n, s = (":now_naive", ":soon_naive") if naive else (":now", ":soon")
        r = conn.execute(text(
            f"SELECT count(*) AS total,"
            f" count(*) FILTER (WHERE {col} > {s}) AS valid,"
            f" count(*) FILTER (WHERE {col} > {n} AND {col} <= {s}) AS soon,"
            f" count(*) FILTER (WHERE {col} <= {n}) AS expired,"
            f" count(*) FILTER (WHERE {col} IS NULL) AS no_deadline"
            + (f", count(*) FILTER (WHERE {purged_col} IS NOT NULL) AS purged,"
               f" max({purged_col}) AS last_purged_at" if purged_col else "")
            + f" FROM {table}"), p).mappings().one()
        holding = conn.execute(text(f"SELECT count(*) FROM {table} WHERE {holding_where}"), p).scalar()
        out.append({
            "key": name, "label": label, "total": int(r["total"]),
            "valid": int(r["valid"]), "soon": int(r["soon"]), "expired": int(r["expired"]),
            "expired_holding": int(holding), "expired_cleared": int(r["expired"]) - int(holding),
            "no_deadline": int(r["no_deadline"]),
            "purge_recorded": purged_col is not None,
            "purged": int(r["purged"]) if purged_col else None,
            "last_purged_at": iso(r["last_purged_at"]) if purged_col else None,
        })
    return out


def _run(r) -> dict:
    if r["error"]:
        state, state_label = "failed", "실패"
    elif r["finished_at"] is None:
        state, state_label = "unknown", "끝난 기록 없음 · 결과 미확인"
    else:
        state, state_label = "done", "끝남"
    counts = r["counts"] if isinstance(r["counts"], dict) else {}
    names = {k: v[0] for k, v in TARGET_INFO.items()} | EXTRA_COUNTS
    return {
        "run_id": r["run_id"], "moment": r["moment"],
        "moment_label": "정기 실행" if r["moment"] == "auto" else "수동 실행",
        "dry_run": bool(r["dry_run"]),
        "kind_label": "미리보기 · 지울 대상 건수" if r["dry_run"] else "실제 비움 · 비운 건수",
        "state": state, "state_label": state_label, "error": r["error"],
        "started_at": iso(r["started_at"]), "finished_at": iso(r["finished_at"]),
        "counts": [{"key": k, "label": names.get(k, k), "n": v}
                   for k, v in counts.items() if type(v) is int],
    }


@router.get("/retention")
def retention(offset: int = 0):
    """보관 기한 요약(대상별) · 이 서버 프로세스의 파기 작업 설정 · 실행 기록(최근 순)."""
    offset = max(0, offset)
    now = dt.datetime.now(dt.timezone.utc)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        summary = _summary(conn, now)
        rows = conn.execute(text(
            "SELECT run_id, moment, dry_run, counts, error, started_at, finished_at"
            "  FROM retention_purge_runs ORDER BY started_at DESC, run_id DESC LIMIT :lim OFFSET :off"),
            {"lim": RUNS_LIMIT, "off": offset}).mappings().all()
        r = conn.execute(text(
            "SELECT count(*) AS total, count(*) FILTER (WHERE NOT dry_run AND error IS NULL"
            "   AND finished_at IS NOT NULL) AS applied, max(started_at) FILTER (WHERE NOT dry_run"
            "   AND error IS NULL AND finished_at IS NOT NULL) AS last_applied_at,"
            " max(started_at) AS last_at FROM retention_purge_runs")).mappings().one()
    return {
        "now": iso(now), "due_soon_days": DUE_SOON_DAYS, "summary": summary,
        "process": {"apply": RP.apply_enabled(), "schedule": RP.scheduler_enabled(),
                    "note": "이 서버 프로세스가 읽은 설정입니다. 운영 서버의 실제 설정과 정기 실행 성공 여부를 확인한 값이 아닙니다."},
        "runs": [_run(x) for x in rows], "runs_total": int(r["total"]),
        "runs_applied": int(r["applied"]), "last_applied_at": iso(r["last_applied_at"]),
        "last_run_at": iso(r["last_at"]), "limit": RUNS_LIMIT, "offset": offset,
        "note": ("기한 지남은 화면에서 개인정보를 가린다는 뜻이고, 값을 지웠다는 뜻이 아닙니다. "
                 "건수에는 시험 자료도 들어 있습니다."),
    }
