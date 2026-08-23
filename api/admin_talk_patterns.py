# -*- coding: utf-8 -*-
"""팝콘톡 응답 패턴(ADM-TLK-010 · 가칭) — 관리자 데이터 API.

화면 = `templates/admin/talk_patterns.html.j2` · 승인 디자인 **1b(목록 전면)**
(`docs/design/dc-talk-patterns.html`) · 정의서 `docs/design/req/req-talk-patterns.md`
· 표 `talk_intents`·`talk_intent_hits`(0061·0062) · 결정 **A-95**·**A-96**.

■ 화면이 계속 말해야 하는 것 (승인 디자인 README — 여기가 그 데이터를 낸다)
  ① `자동`은 `사용`과 섞지 않는다 -> 상태를 그대로 내려보내고 화면이 색으로 가른다
  ② 회귀 트래픽은 빼고, **뺐다는 사실을 말한다** -> `regression_excluded` 를 함께 낸다
  ③ 「서로 다른 방문자 수」를 늘 함께 -> 큐 집계가 `visitors` 를 낸다(임계 5명)
  ④ `text` 는 자동 승격하지 않는다 -> 등록 응답이 그 사실을 문구로 돌려준다
  ⑤ 답 없는 `사용` 은 DB 가 거부한다 -> 여기서 **그 전에** 400 으로 막는다
  ⑥ 어휘 충돌은 **경고하되 막지 않는다** -> `conflicts` 로 알리고 저장은 진행한다
  ⑦ 내리기는 상태 전이지 삭제가 아니다 -> DELETE 엔드포인트를 두지 않는다

■ ⚠ 원문(`raw_text`)은 이 파일의 어떤 응답에도 실리지 않는다 (A-95 §0-1 ㉰)
  `/raw-stats` 는 **건수·시각만** 낸다. 원문 내용을 내려보내는 경로는 여기 없다 —
  「대량으로 읽히면 마스킹이 있어도 사실상 대화 열람」이라는 판단 때문이다.
  단건 열람 허용 여부는 **미정**(정의서 §9 ㉢)이라 그 경로 자체를 아직 만들지 않는다.

■ ⚠ 큐 집계의 한계를 화면에 그대로 말한다 (지어내지 않는다)
  「안 걸린 질문」은 정의상 **아무 의도에도 안 걸린 문장**이라 `matched_terms` 가 비어
  있는 경우가 많다. 그러면 **묶을 기준이 없다.** 그래서:

      matched_terms 가 있는 행   그 어휘 조합으로 묶는다 (min_hits 미달 등으로 걸린 말은 있는 경우)
      비어 있는 행               `(어휘 미상)` 한 묶음으로 모으고 **그 사실을 화면이 밝힌다**

  형태소 분석으로 어휘를 «지어내지» 않는다. 트래픽이 쌓여 이 묶음이 커지면 그때
  무엇으로 가를지 정한다 — 지금은 큐 자체가 0건이라 판단 근거가 없다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .auth import current_operator
from .db import engine
# ⚠ 시각은 «반드시» 이 함수를 지난다 — DB 컬럼이 naive(UTC)라 datetime 을 그대로
# 내보내면 브라우저가 **로컬 시각으로 오독해 9시간이 어긋난다**(KST-UTC 차이).
# 실제로 이 화면 검증에서 방금 한 질문이 「9시간 전」으로 떴다.
from .timeutil import iso
from .talk import AUTO_PROMOTE_VISITORS, RAW_KEEP_DAYS

router = APIRouter(prefix="/api/admin", tags=["admin-talk-patterns"])

STATUSES = ("대기", "사용", "자동", "미사용")
KINDS = ("text", "band_cards", "constraint_parse", "handoff")


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "관리자(owner)만 바꿀 수 있습니다")
    return me


# 「우리가 아직 답을 못 만든 질문」의 정의 — **한 자리에만 적는다.**
# 검증(2026-08-22)에서 `intent_key IS NULL` 만으로는 «답을 준 질문»까지 큐에 올라오는 것을
# 확인했다. 셋을 함께 봐야 한다:
#
#     intent_key IS NULL          어느 답변 패턴에도 안 걸렸다
#     matched_terms = '[]'        조건도 하나 못 읽었다 (예산·용도를 읽었으면 답한 것이다)
#     answer_kind = constraint_parse   band_cards 처럼 «다른 방식으로 답한» 경로가 아니다
#
# 실측 대조: 「모니터도 하나 추천해주세요」(band_cards, 답을 줌)와 「예산 12000만원까지」
# (matched=['예산'], 조건을 읽음)는 빠지고, 「오늘 서울 날씨 어때요?」만 남는다.
UNANSWERED = ("h.intent_key IS NULL AND h.matched_terms = '[]'::jsonb"
              " AND h.answer_kind = 'constraint_parse'")


def _origin_where(include_regression: bool) -> str:
    """회귀 트래픽을 빼는 술어. **뺐다는 사실은 응답이 따로 말한다.**"""
    return "" if include_regression else " AND h.data_origin = 'real'"


@router.get("/talk-patterns")
def list_patterns(include_regression: bool = False):
    """답변 패턴 목록 — 의도 + 걸린 횟수 + 마지막 사용 + 어휘 충돌 경고."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT i.intent_key, i.label, i.match_terms, i.min_hits,
                   i.answer_kind, (i.answer_body IS NOT NULL) AS has_body,
                   i.answer_ref, i.status, (i.answer_pack IS NOT NULL) AS has_pack,
                   COUNT(h.hit_id) AS hits, MAX(h.created_at) AS last_at
              FROM talk_intents i
              LEFT JOIN talk_intent_hits h
                     ON h.intent_key = i.intent_key"""
            # 회귀분을 뺄 때는 JOIN 조건에 건다 — WHERE 에 걸면 LEFT JOIN 이 INNER 가 되어
            # 「한 번도 안 걸린 의도」가 목록에서 통째로 사라진다(죽은 의도를 찾는 것이
            # 이 화면의 존재 이유 셋 중 하나다).
            + _origin_where(include_regression) + """
             GROUP BY i.intent_key
             ORDER BY i.intent_key
        """)).mappings().all()

        # 어휘 충돌 — 같은 말을 두 의도가 문다. **경고만 하고 막지 않는다**(gpu_compare 가
        # min_hits 로 갈리는 실재 설계다). 판정을 화면이 다시 하지 않도록 여기서 낸다.
        seen: dict = {}
        for r in rows:
            for t in (r["match_terms"] or []):
                seen.setdefault(t, []).append(r["intent_key"])
        clash = {t: ks for t, ks in seen.items() if len(ks) > 1}

    out = []
    for r in rows:
        mine = sorted({t for t in (r["match_terms"] or []) if t in clash})
        out.append({
            "key": r["intent_key"], "label": r["label"],
            "terms": list(r["match_terms"] or []), "min_hits": int(r["min_hits"] or 1),
            "kind": r["answer_kind"], "has_body": bool(r["has_body"]),
            "answer_ref": r["answer_ref"], "status": r["status"],
            "has_pack": bool(r["has_pack"]),
            "hits": int(r["hits"] or 0),
            "last_at": iso(r["last_at"]),
            # 충돌한 말과 «누구와» 겹치는지까지 준다 — 화면이 이유를 말할 수 있어야 한다.
            "conflicts": [{"term": t, "with": [k for k in clash[t] if k != r["intent_key"]]}
                          for t in mine],
        })
    return {
        "ok": True, "intents": out,
        "counts": {"total": len(out),
                   "with_pack": sum(1 for x in out if x["has_pack"]),
                   "auto": sum(1 for x in out if x["status"] == "자동")},
        # ②「뺐다는 사실을 말한다」 — 화면이 이 값으로 경고를 세운다.
        "regression_excluded": not include_regression,
    }


@router.get("/talk-patterns/queue")
def queue(include_regression: bool = False, limit: int = 8):
    """「안 걸린 질문」 큐 — 이 화면의 핵심(정의서 §5-2).

    자동 승격 임계(`AUTO_PROMOTE_VISITORS`)에 닿았는지를 함께 낸다 — 운영자가
    「이건 곧 올라가겠구나」를 미리 보게 하려는 것이다.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT COALESCE(NULLIF(h.matched_terms::text, '[]'), '(어휘 미상)') AS grp,
                   h.matched_terms AS terms,
                   COUNT(*) AS hits,
                   COUNT(DISTINCT h.visitor_key) FILTER (WHERE h.visitor_key IS NOT NULL)
                       AS visitors,
                   MAX(h.created_at) AS last_at
              FROM talk_intent_hits h
             WHERE """ + UNANSWERED + _origin_where(include_regression) + """
             GROUP BY 1, 2
             ORDER BY visitors DESC, hits DESC
             LIMIT :lim
        """), {"lim": max(1, min(limit, 40))}).mappings().all()
        total = conn.execute(text(
            "SELECT COUNT(*) FROM talk_intent_hits h WHERE " + UNANSWERED
            + _origin_where(include_regression))).scalar()
    groups = []
    for r in rows:
        v = int(r["visitors"] or 0)
        groups.append({
            "terms": list(r["terms"] or []),
            # 어휘가 비면 묶을 기준이 없다 — 지어내지 않고 그 사실을 이름으로 말한다.
            "unknown_terms": not (r["terms"] or []),
            "hits": int(r["hits"] or 0), "visitors": v,
            "last_at": iso(r["last_at"]),
            "at_threshold": v >= AUTO_PROMOTE_VISITORS,
        })
    return {"ok": True, "groups": groups, "total_hits": int(total or 0),
            "threshold": AUTO_PROMOTE_VISITORS,
            "regression_excluded": not include_regression}


@router.get("/talk-patterns/raw-stats")
def raw_stats():
    """원문 보관 현황 — **owner 전용 · 건수와 시각만**(A-95 §0-1 ㉰).

    ⚠ 원문 내용은 내려보내지 않는다. 단건 열람 허용 여부는 미정이라(정의서 §9 ㉢)
    그 경로 자체를 아직 만들지 않았다.
    """
    _owner()
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT COUNT(*) FILTER (WHERE raw_text IS NOT NULL) AS kept,
                   MIN(created_at) FILTER (WHERE raw_text IS NOT NULL) AS oldest,
                   MIN(raw_purge_at) FILTER (WHERE raw_text IS NOT NULL) AS next_purge
              FROM talk_intent_hits
        """)).mappings().first()
    return {"ok": True, "keep_days": RAW_KEEP_DAYS,
            "kept": int(r["kept"] or 0),
            "oldest_at": iso(r["oldest"]),
            "next_purge_at": iso(r["next_purge"])}


class PatternBody(BaseModel):
    intent_key: str
    label: str
    match_terms: list[str]
    min_hits: int = 1
    answer_kind: str
    answer_body: str | None = None
    answer_ref: str | None = None


def _validate(b: PatternBody, *, status: str = "대기"):
    if b.answer_kind not in KINDS:
        raise HTTPException(400, "알 수 없는 답변 종류입니다: %s" % b.answer_kind)
    if not (b.match_terms and all(t.strip() for t in b.match_terms)):
        raise HTTPException(400, "어휘를 한 개 이상 넣어야 합니다")
    # ⑤ 답 없는 「사용」은 DB(ck_talk_intents_answer)가 거부한다 — **화면이 그 전에 막는다.**
    if status in ("사용", "자동") and not (b.answer_body or b.answer_ref):
        raise HTTPException(400, "답변 문구나 API 경로 중 하나는 있어야 합니다")
    if b.answer_kind != "text" and not b.answer_ref:
        raise HTTPException(400, "문구가 아닌 답변은 API 경로가 필요합니다 — 수는 서버가 셉니다")


def _conflicts(conn, terms: list, exclude: str | None = None):
    rows = conn.execute(text(
        "SELECT intent_key, match_terms FROM talk_intents"
        + (" WHERE intent_key <> :ex" if exclude else "")),
        ({"ex": exclude} if exclude else {})).mappings().all()
    out = []
    for r in rows:
        shared = sorted(set(terms) & set(r["match_terms"] or []))
        if shared:
            out.append({"with": r["intent_key"], "terms": shared})
    return out


@router.post("/talk-patterns")
def create_pattern(body: PatternBody):
    """새 패턴 등록 — 저장하면 **`대기`**(아직 고객에게 안 나간다)."""
    _owner()
    _validate(body)
    with engine.begin() as conn:
        if conn.execute(text("SELECT 1 FROM talk_intents WHERE intent_key = :k"),
                        {"k": body.intent_key}).first():
            raise HTTPException(409, "이미 있는 의도명입니다: %s" % body.intent_key)
        # ⑥ 어휘 충돌은 **경고만** 한다 — 막지 않는다.
        clash = _conflicts(conn, body.match_terms)
        conn.execute(text("""
            INSERT INTO talk_intents
                (intent_key, label, match_terms, min_hits, answer_kind,
                 answer_body, answer_ref, status)
            VALUES (:k, :l, CAST(:t AS JSONB), :m, :ak, :ab, :ar, '대기')
        """), {"k": body.intent_key, "l": body.label,
               "t": json.dumps(body.match_terms, ensure_ascii=False),
               "m": max(1, body.min_hits), "ak": body.answer_kind,
               "ab": body.answer_body, "ar": body.answer_ref})
    return {"ok": True, "status": "대기", "conflicts": clash,
            "note": "저장했습니다 — 상태는 «대기»이고 승인 전까지 고객에게 나가지 않습니다."}


class StatusBody(BaseModel):
    status: str


@router.post("/talk-patterns/{intent_key}/status")
def set_status(intent_key: str, body: StatusBody):
    """상태 전이 — 승인·반려·내리기. **행을 지우지 않는다**(⑦)."""
    _owner()
    if body.status not in STATUSES:
        raise HTTPException(400, "알 수 없는 상태입니다: %s" % body.status)
    # ④ `text` 는 자동 승격하지 않는다 — 사람이 «자동»으로 올리는 것도 막는다.
    #    그 상태의 뜻이 「시스템이 올렸다」이므로 손으로 넣으면 기록이 거짓이 된다.
    if body.status == "자동":
        raise HTTPException(400, "«자동»은 시스템이 승격할 때만 붙는 상태입니다 — 손으로 지정하지 않습니다")
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT answer_body, answer_ref, answer_kind, status FROM talk_intents"
            " WHERE intent_key = :k"), {"k": intent_key}).mappings().first()
        if not r:
            raise HTTPException(404, "없는 의도입니다: %s" % intent_key)
        if body.status == "사용" and not (r["answer_body"] or r["answer_ref"]):
            raise HTTPException(400, "답이 없는 패턴은 «사용»으로 올릴 수 없습니다")
        conn.execute(text("""
            UPDATE talk_intents
               SET status = :s, updated_at = now(),
                   approved_by = CASE WHEN :s IN ('사용') THEN :who ELSE approved_by END,
                   approved_at = CASE WHEN :s IN ('사용') THEN now() ELSE approved_at END
             WHERE intent_key = :k
        """), {"s": body.status, "k": intent_key,
               "who": (current_operator() or {}).get("operator_id")})
    return {"ok": True, "from": r["status"], "to": body.status,
            "note": {"사용": "승인했습니다 — 다음 요청부터 팝콘톡이 이 답을 씁니다.",
                     "미사용": "내렸습니다 — 행은 남습니다(상태 전이지 삭제가 아닙니다).",
                     "대기": "«대기»로 되돌렸습니다."}.get(body.status, "")}
