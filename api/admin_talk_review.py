"""AI 답 점검(ADM-TLK-012 · 가칭) — 관리자 데이터 API.

■ 왜 있는가 (2026-10-11 품질관리 · 관리자 확인 R1·R2·R7·R11·M8)
  고객 AI 의 답은 어디에도 저장되지 않아, 「윈도우 깔아서 배송해 드립니다」「5대 주문
  확인했습니다」 같은 약속을 관리자가 볼 수 없었다. 문의마다 답을 남기고(`talk_reply_reviews`,
  0138 · `api/talk._record_reply`) 여기서 점검한다.

■ 무엇을 보이는가
  ① 문의 한 건 = 한 줄: 시각 · 문의 주제 · 반영 못 한 조건 · 약속하는 말 표시 ·
     AI 가 낸 말(서버가 바꾸기 전) · 고객이 본 말 · 자유 답변 · 점검 상태와 메모
  ② 같은 질문의 답을 나란히(`question_key` — 원문 대신 정규화 해시로 묶는다)
  ③ 집계: 표시 있는 답 · 상태별 · AI 답 실패 · 반영 못 한 조건별 · 문의 주제별

■ 정직 표기
  · 고객 문장 원문을 답과 나란히 싣는다(2026-10-11 중헌 님 결정 — req-talk-patterns §9 ㉢).
    표시 규칙은 `api/admin_raw_text.raw_view` 한 곳이다(보관 기한이 지난 원문은 내보내지 않는다).
  · 「약속하는 말」 표시는 단서이지 판정이 아니다. 판정은 관리자가 상태로 남긴다.
  · 이 표가 생기기 전(0138 이전) 문의는 답이 없다 — 그 사실을 `before_logging` 으로 센다.
  · 시험 문의(회귀 표식 · 「QA-」 이름표)는 기본으로 뺀다 — 「고객 문의 · 보관 견적」과 같은 기준.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import talk_rules as TR
from .admin_mvp3_consults import HIT_IS_TEST, _terms
from .admin_raw_text import NOTICE as RAW_NOTICE, expired, raw_view
from .admin_talk_patterns import NOTHING_READ
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-talk-review"])

LIMIT = 50
STATUSES = ("미확인", "문제 있음", "확인")
MEMO_MAX = 500


def _writer():
    me = current_operator() or {}
    if me.get("role") not in ("owner", "operator"):
        raise HTTPException(403, "운영자 이상만 점검 결과를 남길 수 있습니다")
    return me


def _row(r, same_n=None) -> dict:
    tags = [t for t in (r["matched_terms"] or []) if isinstance(t, str)]
    # AI 답은 고객 말을 되짚을 수 있어 원문과 같은 보관 기한을 둔다(0138) — 지나면 내보내지 않는다.
    gone = expired(r["reply_purge_at"])
    return {
        "hit_id": r["hit_id"], "at": iso(r["created_at"]),
        "question": raw_view(r["raw_text"], r["raw_purge_at"]),
        "visitor": ("u" + r["visitor_key"]) if (r["visitor_key"] or "").isdigit() else None,
        "topics": _terms([t for t in tags if t.startswith(TR.TOPIC_TAG)]),
        "unapplied": [t[len(TR.UNAPPLIED_TAG):] for t in tags if t.startswith(TR.UNAPPLIED_TAG)],
        "flags": list(r["flags"] or []),
        "ai_reply": None if gone else r["ai_reply"], "shown_reply": None if gone else r["shown_reply"],
        "replaced": bool(r["ai_reply"]) and r["ai_reply"] != r["shown_reply"],
        "answer": None if gone else r["answer"], "answer_error": bool(r["answer_error"]),
        "reply_purged": gone,
        "question_key": r["question_key"], "same_question_n": same_n,
        "status": r["status"], "memo": r["memo"],
        "reviewed_at": iso(r["reviewed_at"]),
        "test": bool(r["is_test"]),
    }


_SELECT = f"""
    SELECT h.hit_id, h.created_at, h.visitor_key, h.matched_terms, {HIT_IS_TEST} AS is_test,
           h.raw_text, h.raw_purge_at,
           r.ai_reply, r.shown_reply, r.answer, r.answer_error, r.flags, r.question_key,
           r.purge_at AS reply_purge_at,
           r.status, r.memo, r.reviewed_at
      FROM talk_reply_reviews r JOIN talk_intent_hits h ON h.hit_id = r.hit_id
"""


@router.get("/talk-review")
def list_reviews(offset: int = 0, status: str | None = None, flagged: bool = False,
                 include_test: bool = False, unread: bool = False):
    offset = max(0, offset)
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "알 수 없는 상태입니다")
    where = ["TRUE" if include_test else f"NOT {HIT_IS_TEST}"]
    params: dict = {"lim": LIMIT, "off": offset}
    if status:
        where.append("r.status = :st"); params["st"] = status
    if flagged:
        where.append("jsonb_array_length(r.flags) > 0")
    if unread:
        # 조건을 하나도 못 읽은 문의 — 응답 패턴 「AI 가 되물은 질문」과 같은 바탕(F9)
        where.append(NOTHING_READ)
    w = " AND ".join(where)
    base = "FROM talk_reply_reviews r JOIN talk_intent_hits h ON h.hit_id = r.hit_id"
    test_w = "TRUE" if include_test else f"NOT {HIT_IS_TEST}"
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        rows = conn.execute(text(f"{_SELECT} WHERE {w} ORDER BY h.created_at DESC, h.hit_id DESC"
                                 " LIMIT :lim OFFSET :off"), params).mappings().all()
        total = conn.execute(text(f"SELECT COUNT(*) {base} WHERE {w}"), params).scalar_one()
        keys = list({r["question_key"] for r in rows if r["question_key"]})
        same = {}
        if keys:
            for k, n in conn.execute(text(f"SELECT r.question_key, COUNT(*) {base}"
                                          f" WHERE r.question_key = ANY(:k) AND {test_w}"
                                          " GROUP BY r.question_key"), {"k": keys}).all():
                same[k] = int(n)
        s = conn.execute(text(f"""
            SELECT COUNT(*) AS logged,
                   COUNT(*) FILTER (WHERE jsonb_array_length(r.flags) > 0) AS flagged,
                   COUNT(*) FILTER (WHERE jsonb_array_length(r.flags) > 0 AND r.status = '미확인') AS to_check,
                   COUNT(*) FILTER (WHERE r.status = '문제 있음') AS problem,
                   COUNT(*) FILTER (WHERE r.status = '확인') AS checked,
                   COUNT(*) FILTER (WHERE r.answer_error) AS answer_errors,
                   COUNT(*) FILTER (WHERE r.ai_reply IS NOT NULL
                                      AND r.ai_reply IS DISTINCT FROM r.shown_reply) AS replaced
            {base} WHERE {test_w}""")).mappings().one()
        before = conn.execute(text(f"""
            SELECT COUNT(*) FROM talk_intent_hits h
             WHERE h.llm_called AND {test_w}
               AND NOT EXISTS (SELECT 1 FROM talk_reply_reviews r WHERE r.hit_id = h.hit_id)""")).scalar_one()
        # 반영 못 한 조건 · 문의 주제 — 문의 기록의 꼬리표에서 센다(답 기록 유무와 무관)
        tag_rows = conn.execute(text(f"""
            SELECT t AS tag, COUNT(*) AS n
              FROM talk_intent_hits h, jsonb_array_elements_text(h.matched_terms) t
             WHERE {test_w} AND (t LIKE :u OR t LIKE :p)
             GROUP BY t ORDER BY COUNT(*) DESC, t LIMIT 40"""),
            {"u": TR.UNAPPLIED_TAG + "%", "p": TR.TOPIC_TAG + "%"}).all()
    unapplied = [{"label": t[len(TR.UNAPPLIED_TAG):], "n": int(n)} for t, n in tag_rows
                 if t.startswith(TR.UNAPPLIED_TAG)]
    topics = [{"label": _terms([t])[0].replace("문의 주제: ", ""), "n": int(n)} for t, n in tag_rows
              if t.startswith(TR.TOPIC_TAG)]
    return {
        "ok": True, "items": [_row(r, same.get(r["question_key"])) for r in rows],
        "total": int(total), "offset": offset, "limit": LIMIT,
        "summary": {k: int(v or 0) for k, v in s.items()},
        "before_logging": int(before), "unapplied": unapplied, "topics": topics,
        "flag_kinds": [label for label, _ in TR.PROMISE_PATTERNS],
        "include_test": include_test, "unread": unread, "raw_notice": RAW_NOTICE,
    }


@router.get("/talk-review/same/{question_key}")
def same_question(question_key: str, include_test: bool = False):
    """같은 질문에 나간 답을 나란히 — 답이 매번 달라지는지 본다(M8)."""
    if len(question_key) != 64 or not all(c in "0123456789abcdef" for c in question_key):
        raise HTTPException(400, "질문 묶음 표시가 올바르지 않습니다")
    test_w = "TRUE" if include_test else f"NOT {HIT_IS_TEST}"
    with engine.connect() as conn:
        rows = conn.execute(text(f"{_SELECT} WHERE r.question_key = :k AND {test_w}"
                                 " ORDER BY h.created_at DESC, h.hit_id DESC LIMIT 50"),
                            {"k": question_key}).mappings().all()
    items = [_row(r) for r in rows]
    return {"ok": True, "items": items,
            # 답이 매번 달라지는지는 «AI 가 낸 말»로 센다 — 고객이 본 말은 서버 안내로 같아질 수 있다
            "distinct_replies": len({i["ai_reply"] for i in items if i["ai_reply"] is not None})}


class ReviewBody(BaseModel):
    status: str
    memo: str | None = None


@router.put("/talk-review/{hit_id}")
def save_review(hit_id: int, body: ReviewBody):
    me = _writer()
    if body.status not in STATUSES:
        raise HTTPException(400, "상태는 미확인 · 문제 있음 · 확인 중 하나입니다")
    memo = (body.memo or "").strip() or None
    if memo and len(memo) > MEMO_MAX:
        raise HTTPException(400, "메모는 %d자까지 적을 수 있습니다" % MEMO_MAX)
    with engine.begin() as conn:
        n = conn.execute(text("""
            UPDATE talk_reply_reviews
               SET status = :s, memo = :m, reviewed_by = :who, reviewed_at = now()
             WHERE hit_id = :h"""),
            {"s": body.status, "m": memo, "who": me.get("operator_id"), "h": hit_id}).rowcount
    if not n:
        raise HTTPException(404, "답 기록이 없는 문의입니다")
    return {"ok": True, "hit_id": hit_id, "status": body.status, "note": "점검 결과를 저장했습니다."}
