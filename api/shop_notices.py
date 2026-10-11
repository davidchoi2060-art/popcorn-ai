"""판매 안내 자료 — 고객 상담 AI 가 읽는 쪽 (2026-10-11 품질관리 · 관리자 확인 R3·F11).

관리자가 「판매 안내 자료」 화면(`api/admin_shop_notices.py`)에 적고 «사용»으로 둔
안내만 읽는다. 주제 목록과 기본 안내는 `api/talk_rules.PURCHASE_TOPICS` 한 곳에 있다.

읽기에 실패하면 빈 사전을 돌려준다 — 기본 안내가 나가고 상담은 끊기지 않는다.
실패 사실은 로그에 남긴다(삼키지 않는다).
"""
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)


def load_written(conn) -> dict:
    """{주제 키: 관리자가 적은 안내} — «사용» 상태이고 내용이 있는 것만."""
    try:
        rows = conn.execute(text(
            "SELECT topic_key, body FROM shop_notices WHERE status = '사용' AND body IS NOT NULL"
        )).all()
    except Exception as e:                                    # noqa: BLE001
        log.warning("[shop_notices] load failed - default notices used: %s", type(e).__name__)
        return {}
    return {r[0]: r[1] for r in rows}


def load_custom(conn) -> list:
    """관리자가 직접 더한 주제 중 «사용»인 것 — [{label, keywords, body}] (0150).

    표가 아직 없거나(마이그레이션 전) 읽기에 실패하면 빈 목록 — 상담은 끊기지 않는다.
    """
    try:
        rows = conn.execute(text(
            "SELECT label, keywords, body FROM shop_notice_topics"
            " WHERE status = '사용' ORDER BY topic_id")).mappings().all()
    except Exception as e:                                    # noqa: BLE001
        log.warning("[shop_notices] custom topics load failed - skipped: %s", type(e).__name__)
        return []
    return [{"label": r["label"], "keywords": [k for k in (r["keywords"] or []) if isinstance(k, str)],
             "body": r["body"]} for r in rows]
