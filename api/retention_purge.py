"""보관 기한이 지난 고객 개인정보를 지우는 일일 작업 (2026-10-11 코덱스 검수 #84 · #85).

고객에게 약속한 보관 기한이 있다. 기한이 지나면 화면은 이미 가린다(`api/admin_raw_text.expired`).
이 작업은 값 자체를 지운다. 행은 지우지 않는다 — 값만 비운다(집계 · 원장은 남는다).

    대상(TARGETS)     지우는 칸                                       기한 칸
    talk_raw          talk_intent_hits.raw_text                       raw_purge_at (naive UTC)
    talk_reply        talk_reply_reviews.ai_reply · shown_reply · answer   purge_at
    inquiry_contact   purchase_inquiries.contact_name · phone · email · message
                      (+ contact_purged_at 에 지운 시각)              purge_at

운영자 메모(`memo`)는 고객이 쓴 글이 아니라 지우지 않는다.

**기본은 미리보기다.** 지울 대상 건수만 `retention_purge_runs` 에 남긴다. 실제로 지우려면
`RETENTION_PURGE_APPLY=on`. 실행 기록(미리보기 포함)은 한 번에 한 줄이고 지우지 않는다.

정기 실행은 API 프로세스 안에서 매일 04:00 KST(쇼핑몰 가격 자동 갱신과 같은 방식 —
`api/mall_price_auto`). 끄려면 `RETENTION_PURGE_SCHEDULE=off`. 루프백 DB(CI · 테스트 ·
개인 로컬 DB)에서는 정기 실행이 돌지 않는다. 손으로 돌리려면 `tools/retention_purge.py`.
"""
import datetime as dt
import json
import logging
import os
import threading

from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

log = logging.getLogger(__name__)      # ASCII only (server stdout is cp949)

APPLY_ENV = "RETENTION_PURGE_APPLY"
SCHEDULE_ENV = "RETENTION_PURGE_SCHEDULE"
SLOT_KST = 4                           # 매일 04:00 한국 시각
TICK = 300                             # 몇 초마다 확인하나
_KST = dt.timezone(dt.timedelta(hours=9))
_LOCK = "retention_purge"

# (이름, 대상 조건, 지우는 SET) — 조건은 «아직 지울 값이 남은» 행만 고른다(두 번 세지 않는다).
TARGETS = (
    ("talk_raw",
     "talk_intent_hits WHERE raw_text IS NOT NULL AND raw_purge_at <= :now_naive",
     "raw_text = NULL"),
    ("talk_reply",
     "talk_reply_reviews WHERE purge_at <= :now"
     " AND (ai_reply IS NOT NULL OR shown_reply IS NOT NULL OR answer IS NOT NULL)",
     "ai_reply = NULL, shown_reply = NULL, answer = NULL"),
    ("inquiry_contact",
     "purchase_inquiries WHERE purge_at <= :now AND contact_purged_at IS NULL",
     "contact_name = NULL, contact_phone = NULL, contact_email = NULL, message = NULL,"
     " contact_purged_at = :now"),
)


class SlotDone(Exception):
    """같은 정기 시각에 이미 돈 실행이 있다."""


def _on(name, default="off"):
    return (os.environ.get(name) or default).strip().lower() in ("on", "1", "true", "yes")


def apply_enabled() -> bool:
    return _on(APPLY_ENV)


def _split(sql):
    table, where = sql.split(" WHERE ", 1)
    return table, where


def purge(moment="manual", *, apply=None, now=None, slot=None) -> dict:
    """한 번 실행한다. 반환 {ok, run_id, dry_run, counts}. 같은 정기 시각이면 {ok: False, skipped}."""
    if moment not in ("auto", "manual"):
        raise ValueError("moment")
    apply = apply_enabled() if apply is None else bool(apply)
    now = now or dt.datetime.now(dt.timezone.utc)
    params = {"now": now, "now_naive": now.astimezone(dt.timezone.utc).replace(tzinfo=None)}
    try:
        with engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _LOCK})
            if slot is not None:
                last = _last_auto_started(c)
                if last is not None and last >= slot:
                    raise SlotDone()
            run_id = c.execute(text(
                "INSERT INTO retention_purge_runs (moment, dry_run, started_at)"
                " VALUES (:m, :d, :now) RETURNING run_id"),
                {"m": moment, "d": not apply, "now": now}).scalar()
            counts = {}
            for name, target, assign in TARGETS:
                table, where = _split(target)
                if apply:
                    counts[name] = c.execute(text("UPDATE %s SET %s WHERE %s" % (table, assign, where)),
                                             params).rowcount
                else:
                    counts[name] = c.execute(text("SELECT count(*) FROM %s WHERE %s" % (table, where)),
                                             params).scalar()
            c.execute(text(
                "UPDATE retention_purge_runs SET counts = CAST(:c AS JSONB), finished_at = now()"
                " WHERE run_id = :r"), {"c": json.dumps(counts), "r": run_id})
    except SlotDone:
        return {"ok": False, "run_id": None, "skipped": "slot_done"}
    except Exception as e:                                          # noqa: BLE001
        # 실패도 기록한다 — 조용히 안 지워지는 날이 없게
        try:
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO retention_purge_runs (moment, dry_run, error, started_at, finished_at)"
                    " VALUES (:m, :d, :e, :now, now())"),
                    {"m": moment, "d": not apply, "e": ("%s: %s" % (type(e).__name__, e))[:500], "now": now})
        except Exception:                                           # noqa: BLE001
            log.exception("[retention-purge] could not record failure")
        raise
    log.info("[retention-purge] run=%s dry_run=%s counts=%s", run_id, not apply, counts)
    return {"ok": True, "run_id": run_id, "dry_run": not apply, "counts": counts}


def due_slot(now, last_auto_started):
    """지금 돌려야 할 정기 시각(aware) 또는 None. 놓친 시각은 그날 안에 한 번 만회한다."""
    local = now.astimezone(_KST)
    slot = local.replace(hour=SLOT_KST, minute=0, second=0, microsecond=0)
    if slot > local:
        slot -= dt.timedelta(days=1)
    if last_auto_started is not None and last_auto_started >= slot:
        return None
    return slot


def _last_auto_started(conn):
    return conn.execute(text(
        "SELECT max(started_at) FROM retention_purge_runs WHERE moment = 'auto'")).scalar()


def _tick():
    now = dt.datetime.now(dt.timezone.utc)
    with engine.connect() as c:
        last = _last_auto_started(c)
    slot = due_slot(now, last)
    if slot is not None:
        res = purge("auto", now=now, slot=slot)
        log.info("[retention-purge] scheduled run ok=%s", res.get("ok"))


def _loop(stop):
    while not stop.wait(TICK):
        try:
            _tick()
        except Exception:                                           # noqa: BLE001
            log.exception("[retention-purge] scheduler tick failed")


def scheduler_enabled() -> bool:
    if not _on(SCHEDULE_ENV, "on"):
        return False
    from sqlalchemy.engine import make_url
    try:
        host = make_url(os.environ.get("DATABASE_URL") or "").host
    except Exception:                                               # noqa: BLE001
        return False
    return bool(host) and host not in ("127.0.0.1", "localhost", "::1")


_scheduler = None


def start_scheduler() -> None:
    """API 시작 때 한 번."""
    global _scheduler
    if _scheduler is not None or not scheduler_enabled():
        return
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(stop,), name="retention-purge-scheduler", daemon=True)
    t.start()
    _scheduler = (t, stop)
    log.info("[retention-purge] scheduler started slot=%02d:00 KST apply=%s", SLOT_KST, apply_enabled())


# 경로는 없다. API 시작 때 정기 실행을 거는 자리로만 쓴다(api/main.py 자동 등록).
router = APIRouter()
router.add_event_handler("startup", start_scheduler)
