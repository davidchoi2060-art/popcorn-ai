"""상담 해석 바로잡기 — 관리자가 등록한 표현 규칙을 고객 상담에 적용하는 쪽 (0151 · 개편 14번).

관리자 화면(「팝콘톡 응답 패턴」 아래 「해석 바로잡기」, `api/admin_talk_text_fixes.py`)에서
«사용»으로 둔 규칙만 읽는다. 고객 문장에 표현이 들어 있으면(공백·대소문자 무시) AI 가 읽은
예산·해상도 대신 규칙 값을 쓰고, 그 사실을 `dropped` 에 남긴다(삼키지 않는다).

읽기에 실패하면(표가 없거나 DB 오류) 빈 목록 — 상담은 끊기지 않는다. 실패는 로그에 남긴다.
"""
import logging
import re

from sqlalchemy import text

log = logging.getLogger(__name__)

KINDS = ("예산", "해상도")
PHRASE_MIN = 2
PHRASE_MAX = 30


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def load(conn) -> list:
    """«사용» 규칙 — 긴 표현부터(짧은 표현이 긴 표현 안에 들어 있을 때 긴 쪽이 이긴다)."""
    try:
        rows = conn.execute(text(
            "SELECT fix_id, phrase, phrase_norm, kind, budget_won, budget_bound, resolution"
            " FROM talk_text_fixes WHERE status = '사용'"
            " ORDER BY length(phrase_norm) DESC, fix_id")).mappings().all()
    except Exception as e:                                    # noqa: BLE001
        log.warning("[talk_text_fixes] load failed - skipped: %s", type(e).__name__)
        return []
    return [dict(r) for r in rows]


def _won(won: int) -> str:
    return "{:,}만원".format(won // 10_000) if won % 10_000 == 0 else "{:,}원".format(won)


def apply(text_raw: str, raw: dict, fixes_rules: list) -> list:
    """raw(AI state dict)를 규칙대로 고친다. 고친 내역 [{field, value, reason}] 을 돌려준다.

    종류마다 처음 맞는(가장 긴) 규칙 하나만 쓴다.
    """
    t = norm(text_raw)
    out: list = []
    done: set = set()
    for r in fixes_rules or []:
        if r["kind"] in done or not r["phrase_norm"] or r["phrase_norm"] not in t:
            continue
        done.add(r["kind"])
        reason = "관리자 해석 규칙 「%s」" % r["phrase"]
        if r["kind"] == "예산":
            if raw.get("budget_won") != r["budget_won"] or raw.get("budget_bound") != r["budget_bound"]:
                out.append({"field": "budget_won", "value": raw.get("budget_won"),
                            "reason": reason + " -> " + _won(r["budget_won"])
                                      + (" " + r["budget_bound"] if r["budget_bound"] else "")})
            raw["budget_won"], raw["budget_bound"] = r["budget_won"], r["budget_bound"]
        elif r["kind"] == "해상도":
            game = dict(raw["game"]) if isinstance(raw.get("game"), dict) else {}
            if game.get("resolution") != r["resolution"]:
                out.append({"field": "game.resolution", "value": game.get("resolution"),
                            "reason": reason + " -> " + r["resolution"]})
            game["resolution"] = r["resolution"]
            raw["game"] = game
    return out
