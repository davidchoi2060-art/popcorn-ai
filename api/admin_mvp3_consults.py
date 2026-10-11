"""고객 화면 문의 · 보관 견적 (ADM-ORD-011 · 가칭) — 관리자 데이터 API, 읽기 전용.

■ 왜 있는가 (2026-10-11 품질관리 · 관리자 확인 결과 F1·F2)
  지금 쓰는 고객 화면(`mockups/mvp3/`)은 `consult_sessions` 를 쓰지 않는다
  (`api/talk.py` parse 의 「consult_sessions 를 안 쓰는 것은 그대로」). 그래서
  「견적 상담 기록」·대시보드 「오늘 상담」은 mvp3 문의를 하나도 못 센다.
  mvp3 가 남기는 자료는 둘뿐이다:

      talk_intent_hits              문의 한 번 = 한 행 (POST /api/talk/parse)
      mvp3_saved_recommendations    「견적 보관하기」 한 번 = 한 행

  고객 흐름을 바꾸지 않고, **이미 쌓이는 두 표를 관리자가 보게** 한다.
  둘은 방문자 키(`talk_intent_hits.visitor_key` = `users.user_id` 문자열 ·
  `mvp3_saved_recommendations.user_id`)로 이어 「한 방문자가 무엇을 묻고 무엇을
  보관했나」를 한 줄로 묶는다.

■ 정직 표기
  ① 문의 원문(`raw_text`)을 싣는다(2026-10-11 중헌 님 결정 — `req-talk-patterns.md` §9 ㉢).
     표시 규칙은 `api/admin_raw_text.raw_view` 한 곳이다(보관 기한이 지난 원문은 내보내지
     않는다). 읽어 낸 조건 이름과 AI 호출 여부도 함께 낸다.
  ② `talk_intent_hits` 는 mvp3 만의 표가 아니다 — 같은 `/api/talk/parse` 를 쓰는
     다른 고객 화면의 문의도 들어온다. 표가 어느 화면에서 왔는지 적지 않아 가를 수
     없다. 화면이 그 사실을 말한다.
  ③ 방문자 쿠키가 없던 문의는 `visitor_key` 가 비어 있다. 한 줄에 한 건씩
     「방문자 미확인」으로 둔다 — 다른 사람과 묶지 않는다.
  ④ 시험 문의(회귀 트래픽 `data_origin='test'`, 품질관리 이름표 「QA-」로 시작하는 문장)는
     기본으로 빼고, 뺐다는 사실과 건수를 함께 낸다. 시험 문의가 있는 방문자의 보관 견적도 뺀다.
  ⑤ 문의마다 「문의 주제」(결제·배송·A/S 등)와 「반영 못 함」(흰색 케이스·램 64GB 등) 꼬리표가
     있으면 보인다 — 조건을 하나도 못 읽은 문의도 빈 줄이 되지 않게(`api/talk.py` 가 남긴다).

■ 시각 — `talk_intent_hits.created_at` 은 naive UTC, `saved_at` 은 timestamptz 다.
  둘을 한 줄로 비교하려고 `saved_at AT TIME ZONE 'UTC'`(naive UTC)로 맞춘다.
  「오늘」은 KST 달력일(`kst_day_range`) — 대시보드 「오늘 상담」과 같은 규약.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from . import talk_rules as TR
from .admin_purchase_inquiries import IS_TEST as INQUIRY_IS_TEST
from .admin_raw_text import NOTICE as RAW_NOTICE, expired, raw_view
from .db import engine
from .timeutil import iso, KST, kst_day_range

router = APIRouter(prefix="/api/admin", tags=["admin-mvp3-consults"])

LIMIT = 50

# talk_intent_hits.matched_terms 에 들어가는 조건 이름(TalkState 필드) -> 화면 라벨
TERM_KO = {
    "usages": "용도", "budget_won": "예산", "budget_bound": "예산 범위",
    "platform": "플랫폼", "tier_key": "성능 등급", "game": "게임",
    "exclude": "제외 조건", "prefs": "선호",
}
ROLE_KO = {"value": "알뜰", "recommended": "추천", "reference": "참고"}


# 시험 문의 — 회귀 표식(data_origin) 또는 품질관리 이름표(문장 맨 앞 「QA-」).
# 이름표가 있는지는 SQL 안에서 본다(2026-10-11 관리자 확인 M1).
# 원문은 보관 기간이 지나면 지워지므로, 그 뒤에는 data_origin 만 남는다.
HIT_IS_TEST = "(data_origin <> 'real' OR COALESCE(raw_text, '') ILIKE 'QA-%')"


# 방문자 상세 한 번에 싣는 최대 건수(최근 것부터). 넘으면 `truncated` 로 알린다.
DETAIL_LIMITS = {"hits": 500, "saved": 200, "inquiries": 100}


def _hit_origin(include_test: bool) -> str:
    return "TRUE" if include_test else f"NOT {HIT_IS_TEST}"


def _saved_origin(include_test: bool) -> str:
    """시험 문의만 한 방문자의 보관 견적도 함께 뺀다(그 방문자에게 시험 문의가 하나라도 있으면)."""
    if include_test:
        return "TRUE"
    return (f"NOT EXISTS (SELECT 1 FROM talk_intent_hits t WHERE t.visitor_key = s.user_id::text"
            f" AND {HIT_IS_TEST.replace('data_origin', 't.data_origin').replace('raw_text', 't.raw_text')})")


def conditions(state) -> list[str]:
    """보관 견적의 조건(talk_state)을 사람이 읽는 말로 — mvp3 `live-model.js` conditions() 와 같은 순서."""
    if not isinstance(state, dict):
        return []
    out = []
    usages = [u for u in (state.get("usages") or []) if isinstance(u, str)]
    if usages:
        out.append(" · ".join(usages))
    b = state.get("budget_won")
    if isinstance(b, int) and b > 0:
        out.append(f"예산 {b:,}원" + (f" {state['budget_bound']}" if state.get("budget_bound") else ""))
    game = state.get("game") if isinstance(state.get("game"), dict) else {}
    names = [n for n in (game.get("names") or []) if isinstance(n, str)]
    if names:
        out.append(" · ".join(names))
    if game.get("resolution"):
        out.append(str(game["resolution"]))
    if state.get("platform"):
        out.append(str(state["platform"]))
    return out


def _term(t: str) -> str:
    if t.startswith(TR.TOPIC_TAG):
        key = t[len(TR.TOPIC_TAG):]
        return "문의 주제: " + (TR.topic_label(key) or key)
    if t.startswith(TR.UNAPPLIED_TAG):
        return "반영 못 함: " + t[len(TR.UNAPPLIED_TAG):]
    return TERM_KO.get(t, t)


def _terms(matched) -> list[str]:
    return [_term(t) for t in (matched or []) if isinstance(t, str)]


def _visitor_where(visitor: str):
    """`u123` = 방문자 키 123 · `h456` = 방문자 미확인 문의 한 건(hit_id 456)."""
    if visitor.startswith("u") and visitor[1:].isdigit():
        return int(visitor[1:]), None
    if visitor.startswith("h") and visitor[1:].isdigit():
        return None, int(visitor[1:])
    raise HTTPException(400, "방문자 표시가 올바르지 않습니다")


# 방문자 한 줄 = 문의와 보관을 같은 키로 모은 것. 키 없는 문의는 hit 하나가 한 줄이다.
_EVENTS = """
    SELECT CASE WHEN visitor_key ~ '^[0-9]+$' THEN 'u' || visitor_key ELSE 'h' || hit_id END AS vkey,
           created_at AS at, 1 AS hit, 0 AS saved, CASE WHEN llm_called THEN 1 ELSE 0 END AS ai
      FROM talk_intent_hits WHERE {hit_origin}
    UNION ALL
    SELECT 'u' || user_id, saved_at AT TIME ZONE 'UTC', 0, 1, 0
      FROM mvp3_saved_recommendations s WHERE {saved_origin}
"""


@router.get("/mvp3-consults")
def list_visitors(offset: int = 0, include_test: bool = False):
    """방문자별 문의·보관 요약 — 마지막 활동이 최근인 순서."""
    offset = max(0, offset)
    hit_origin = _hit_origin(include_test)
    today_kst = datetime.now(KST).date()
    lo, hi = kst_day_range(today_kst.isoformat(), today_kst.isoformat())
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        saved_origin = _saved_origin(include_test)
        ev = _EVENTS.format(hit_origin=hit_origin, saved_origin=saved_origin)
        rows = conn.execute(text(f"""
            SELECT vkey, MIN(at) AS first_at, MAX(at) AS last_at,
                   SUM(hit) AS hits, SUM(saved) AS saved, SUM(ai) AS ai
              FROM ({ev}) e GROUP BY vkey
             ORDER BY MAX(at) DESC, vkey DESC LIMIT :lim OFFSET :off"""),
            {"lim": LIMIT, "off": offset}).mappings().all()
        total_visitors = conn.execute(text(
            f"SELECT COUNT(DISTINCT vkey) FROM ({ev}) e")).scalar_one()
        s = conn.execute(text(f"""
            SELECT COUNT(*) AS hits,
                   COUNT(*) FILTER (WHERE created_at >= :lo AND created_at < :hi) AS hits_today,
                   COUNT(*) FILTER (WHERE llm_called) AS ai
              FROM talk_intent_hits WHERE {hit_origin}"""), {"lo": lo, "hi": hi}).mappings().one()
        sv = conn.execute(text(f"""
            SELECT COUNT(*) AS saved,
                   COUNT(*) FILTER (WHERE saved_at AT TIME ZONE 'UTC' >= :lo
                                      AND saved_at AT TIME ZONE 'UTC' < :hi) AS saved_today
              FROM mvp3_saved_recommendations s WHERE {saved_origin}"""),
            {"lo": lo, "hi": hi}).mappings().one()
        excluded = 0 if include_test else conn.execute(text(
            f"SELECT COUNT(*) FROM talk_intent_hits WHERE {HIT_IS_TEST}")).scalar_one()
        # 줄마다 마지막 보관 견적 한 건(있으면) — 상품명·가격을 목록에서 바로 보이게 한다.
        uids = [int(r["vkey"][1:]) for r in rows if r["vkey"].startswith("u")]
        last_saved = {}
        if uids:
            for q in conn.execute(text(f"""
                SELECT DISTINCT ON (user_id) user_id, product_snapshot, saved_at
                  FROM mvp3_saved_recommendations s WHERE user_id = ANY(:u) AND {saved_origin}
                 ORDER BY user_id, saved_at DESC, quote_id DESC"""), {"u": uids}).mappings():
                last_saved[q["user_id"]] = q
        last_terms = {}
        keys = [r["vkey"][1:] for r in rows if r["vkey"].startswith("u")]
        if keys:
            for h in conn.execute(text(f"""
                SELECT DISTINCT ON (visitor_key) visitor_key, matched_terms, raw_text, raw_purge_at
                  FROM talk_intent_hits WHERE visitor_key = ANY(:k) AND {hit_origin}
                 ORDER BY visitor_key, created_at DESC, hit_id DESC"""), {"k": keys}).mappings():
                last_terms[h["visitor_key"]] = h
        lone = [int(r["vkey"][1:]) for r in rows if r["vkey"].startswith("h")]
        if lone:
            for h in conn.execute(text(
                    "SELECT hit_id, matched_terms, raw_text, raw_purge_at FROM talk_intent_hits"
                    " WHERE hit_id = ANY(:h)"), {"h": lone}).mappings():
                last_terms["h" + str(h["hit_id"])] = h

    items = []
    for r in rows:
        vk = r["vkey"]
        known = vk.startswith("u")
        q = last_saved.get(int(vk[1:])) if known else None
        p = (q["product_snapshot"] or {}) if q else {}
        lh = last_terms.get(vk[1:] if known else vk)
        items.append({
            "visitor": vk, "visitor_known": known,
            "visitor_label": ("방문자 " + vk[1:]) if known else "방문자 미확인",
            "first_at": iso(r["first_at"]), "last_at": iso(r["last_at"]),
            "hits": int(r["hits"]), "saved": int(r["saved"]), "ai_calls": int(r["ai"]),
            "last_terms": _terms(lh["matched_terms"] if lh else None),
            "last_question": raw_view(lh["raw_text"], lh["raw_purge_at"]) if lh else None,
            "last_product": ({"name": p.get("name"), "price": p.get("price"),
                              "product_code": p.get("product_code"),
                              "saved_at": iso(q["saved_at"])} if q else None),
        })
    return {
        "items": items, "limit": LIMIT, "offset": offset, "total_visitors": int(total_visitors),
        "summary": {"hits": int(s["hits"]), "hits_today": int(s["hits_today"]),
                    "ai_calls": int(s["ai"]), "saved": int(sv["saved"]),
                    "saved_today": int(sv["saved_today"])},
        "include_test": include_test, "test_excluded": int(excluded),
        "raw_notice": RAW_NOTICE,
        "note": ("문의 원문은 저장할 때 전화번호·이메일이 가려진 채로 남고 90일 뒤 지워집니다. "
                 "문의 기록은 같은 상담 API를 쓰는 다른 고객 화면의 문의도 함께 셉니다."),
    }


@router.get("/mvp3-consults/{visitor}")
def visitor_detail(visitor: str, include_test: bool = False):
    """방문자 한 명의 문의와 보관 견적을 시간 순서로."""
    uid, hit_id = _visitor_where(visitor)
    hit_origin = _hit_origin(include_test)
    with engine.connect() as conn:
        if uid is not None:
            hits = conn.execute(text(f"""
                SELECT h.hit_id, h.created_at, matched_terms, unmatched_n, answer_kind, llm_called,
                       intent_key, {HIT_IS_TEST} AS is_test, h.raw_text, h.raw_purge_at,
                       r.shown_reply, r.flags, r.status AS review_status, r.purge_at AS reply_purge_at
                  FROM talk_intent_hits h LEFT JOIN talk_reply_reviews r ON r.hit_id = h.hit_id
                 WHERE visitor_key = :k AND {hit_origin}
                 ORDER BY h.created_at DESC, h.hit_id DESC LIMIT :n"""),
                {"k": str(uid), "n": DETAIL_LIMITS["hits"] + 1}).mappings().all()
            quotes = conn.execute(text(f"""
                SELECT quote_id, product_snapshot, talk_state, saved_at
                  FROM mvp3_saved_recommendations s WHERE user_id = :u AND {_saved_origin(include_test)}
                 ORDER BY saved_at DESC, quote_id DESC LIMIT :n"""),
                {"u": uid, "n": DETAIL_LIMITS["saved"] + 1}).mappings().all()
            # 구매 상담 신청(0139) — 연락처는 싣지 않는다. 처리는 「구매 상담 신청」 화면에서 한다.
            inquiries = conn.execute(text(f"""
                SELECT i.inquiry_no, i.created_at, i.topic, i.status
                  FROM purchase_inquiries i
                 WHERE i.user_id = :u AND ({'TRUE' if include_test else 'NOT ' + INQUIRY_IS_TEST})
                 ORDER BY i.created_at DESC, i.inquiry_id DESC LIMIT :n"""),
                {"u": uid, "n": DETAIL_LIMITS["inquiries"] + 1}).mappings().all()
        else:
            hits = conn.execute(text(f"""
                SELECT h.hit_id, h.created_at, matched_terms, unmatched_n, answer_kind, llm_called,
                       intent_key, {HIT_IS_TEST} AS is_test, h.raw_text, h.raw_purge_at,
                       r.shown_reply, r.flags, r.status AS review_status, r.purge_at AS reply_purge_at
                  FROM talk_intent_hits h LEFT JOIN talk_reply_reviews r ON r.hit_id = h.hit_id
                 WHERE h.hit_id = :h AND {hit_origin}"""), {"h": hit_id}).mappings().all()
            quotes = []
            inquiries = []
    if not hits and not quotes and not inquiries:
        raise HTTPException(404, "이 방문자의 기록이 없습니다")
    # 상한을 넘는 방문자는 «최근» 것만 싣고 잘린 사실을 함께 알린다 — 예전에는 오래된 것부터 읽어
    # 최신 내역이 말없이 빠졌다(2026-10-11 코덱스 검수 #81 지적 반영).
    truncated = {"hits": len(hits) > DETAIL_LIMITS["hits"], "saved": len(quotes) > DETAIL_LIMITS["saved"],
                 "inquiries": len(inquiries) > DETAIL_LIMITS["inquiries"]}
    hits = hits[:DETAIL_LIMITS["hits"]]
    quotes = quotes[:DETAIL_LIMITS["saved"]]
    inquiries = inquiries[:DETAIL_LIMITS["inquiries"]]

    timeline = [{
        "kind": "hit", "at": iso(h["created_at"]),
        "terms": _terms(h["matched_terms"]), "unread": int(h["unmatched_n"] or 0),
        "ai_called": bool(h["llm_called"]), "intent_key": h["intent_key"],
        "test": bool(h["is_test"]),
        "question": raw_view(h["raw_text"], h["raw_purge_at"]),
        # 고객이 본 AI 답(0138 이후 문의만 있다) — 점검은 「AI 답 점검」 화면에서 한다
        "reply": None if h["review_status"] is None else {
            "shown_reply": None if expired(h["reply_purge_at"]) else h["shown_reply"],
            "reply_purged": expired(h["reply_purge_at"]), "flags": list(h["flags"] or []),
            "status": h["review_status"]},
    } for h in hits]
    for q in quotes:
        p = q["product_snapshot"] or {}
        timeline.append({
            "kind": "saved", "at": iso(q["saved_at"]), "quote_id": str(q["quote_id"]),
            "product": {"name": p.get("name"), "price": p.get("price"),
                        "product_code": p.get("product_code"),
                        "role": ROLE_KO.get(p.get("role"), p.get("tag") or None),
                        "price_src": p.get("price_src"),
                        "reasons": [x for x in (p.get("reasons") or []) if isinstance(x, str)][:5]},
            "conditions": conditions(q["talk_state"]),
        })
    for i in inquiries:
        timeline.append({"kind": "inquiry", "at": iso(i["created_at"]),
                         "inquiry_no": i["inquiry_no"], "topic": i["topic"], "status": i["status"]})
    timeline.sort(key=lambda e: e["at"] or "")
    return {"visitor": visitor, "visitor_known": uid is not None,
            "visitor_label": ("방문자 " + str(uid)) if uid is not None else "방문자 미확인",
            "hits": len(hits), "saved": len(quotes), "inquiries": len(inquiries),
            "truncated": truncated, "limits": DETAIL_LIMITS,
            "raw_notice": RAW_NOTICE, "timeline": timeline}
