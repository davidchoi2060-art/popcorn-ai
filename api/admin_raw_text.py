"""관리자 화면의 고객 질문 원문 표시 — 단일 원천 (2026-10-11 품질관리 11번).

중헌 님 결정(2026-10-11 11:18): 「관리자가 고객 질문·AI 답 원문을 읽어도 됩니다. 그래야
향후 개선이 됩니다.」 — `docs/design/req/req-talk-patterns.md` §9 ㉢.

  · 원문은 `talk_intent_hits.raw_text` 이다. 저장할 때 이미 전화번호·이메일 등이 가려져
    들어간다(`api/talk.mask_pii` · DB CHECK `ck_talk_hits_masked`). 화면은 더 가리지 않는다.
  · 보관 기한(`raw_purge_at`, 90일)이 지난 원문은 내보내지 않는다 — 고객에게 약속한 기한이다.
  · 화면 위에는 `NOTICE` 한 줄을 둔다.

라우터가 없는 모듈이다(`api/main.py` 자동 등록은 `router` 가 있는 모듈만 싣는다).
"""
from datetime import datetime, timezone

NOTICE = "고객 원문 · 개선 목적으로만 열람"
STATE_LABEL = {"kept": None, "purged": "원문 보관 기간 지남", "none": "원문 기록 없음"}


def expired(purge_at, now: datetime | None = None) -> bool:
    """보관 기한이 지났나. `purge_at` 은 naive UTC 또는 시간대 있는 값(TIMESTAMPTZ) 둘 다 받는다.

    AI 답(`talk_reply_reviews.purge_at`) · 구매 상담 연락처(`purchase_inquiries.purge_at`)도
    질문 원문과 같이 기한이 지나면 내보내지 않는다(2026-10-11 코덱스 검수 #84 · #85 지적 반영).
    """
    if purge_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if purge_at.tzinfo is None:
        purge_at = purge_at.replace(tzinfo=timezone.utc)
    return purge_at <= now


def raw_view(raw_text, purge_at, now: datetime | None = None) -> dict:
    """원문 한 건을 화면용으로 — {text, state, label}. `purge_at` 은 naive UTC."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if raw_text is None or not str(raw_text).strip():
        state = "none"
    elif purge_at is not None and purge_at <= now:
        state = "purged"
    else:
        state = "kept"
    return {"text": raw_text if state == "kept" else None, "state": state,
            "label": STATE_LABEL[state]}
