"""판매 안내 자료(ADM-TLK-011 · 가칭) — 관리자 데이터 API.

■ 왜 있는가 (2026-10-11 품질관리 · 관리자 확인 R3·F11)
  고객 상담 AI 가 운영체제 설치·배송·A/S·세금계산서·할인·여러 대 구매·모니터 포함을
  물으면 근거 없이 「깔아서 보내 드려요」「5대 주문 확인했습니다」라고 약속했다.
  관리자가 그 안내를 적을 곳이 없었다.

■ 어떻게 쓰이는가
  고객 문장에 이 주제가 있으면(`api/talk_rules.purchase_topics`) 말풍선을 안내 문장으로
  바꾼다. 관리자가 적고 «사용»으로 둔 문장이 있으면 그것을, 없으면 기본 안내를 쓴다.
  기본 안내는 「상품마다 달라 쇼핑몰 상품 페이지에서 확인」처럼 약속하지 않는 말이다.

■ 규칙
  ① 기본 주제 일곱 개는 코드에 정해져 있다(판정 규칙이 함께 있어야 한다).
     그 밖의 질문(「인텔이 좋아요 AMD가 좋아요?」 등)은 관리자가 주제 이름 · 알아볼 낱말 ·
     안내를 직접 더한다(표 `shop_notice_topics`, 0150 · 개편 12번). 낱말은 글자 그대로
     비교한다(공백·대소문자 무시, 두 글자 이상).
  ② 바꾸기는 대표 권한(owner)만 한다.
  ③ 내용 없는 «사용»은 막는다(DB CHECK 도 같은 조건).
  ④ 행을 지우지 않는다 — «미사용»으로 내리면 기본 안내로 돌아간다.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import talk_rules as TR
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-shop-notices"])

STATUSES = ("사용", "미사용")
MAX_LEN = 400


def _owner():
    me = current_operator() or {}
    if me.get("role") != "owner":
        raise HTTPException(403, "대표 권한만 바꿀 수 있습니다")
    return me


def _topics():
    return {key: (label, default) for key, label, _pat, default in TR.PURCHASE_TOPICS}


@router.get("/shop-notices")
def list_notices():
    with engine.connect() as conn:
        rows = {r["topic_key"]: r for r in conn.execute(text(
            "SELECT topic_key, body, status, updated_at FROM shop_notices")).mappings()}
    items = []
    for key, (label, default) in _topics().items():
        r = rows.get(key)
        live = bool(r and r["status"] == "사용" and r["body"])
        items.append({
            "topic_key": key, "label": label, "default_text": default,
            "body": r["body"] if r else None,
            "status": r["status"] if r else "미사용",
            "updated_at": iso(r["updated_at"]) if r else None,
            # 지금 고객에게 나가는 문장 — 화면이 다시 고르지 않게 서버가 정한다
            "live_text": r["body"] if live else default,
            "live_source": "written" if live else "default",
        })
    return {"ok": True, "items": items, "max_len": MAX_LEN, "custom": _custom_rows(),
            "keyword_rule": {"min": TR.CUSTOM_KEYWORD_MIN, "max": TR.CUSTOM_KEYWORD_MAX,
                             "count_max": KEYWORDS_MAX}}


KEYWORDS_MAX = 20
LABEL_MAX = 40


def _custom_rows() -> list:
    """관리자가 더한 주제 전부(«미사용» 포함). 표가 아직 없으면 빈 목록."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT topic_id, label, keywords, body, status, updated_at"
                " FROM shop_notice_topics ORDER BY topic_id")).mappings().all()
    except Exception:                                         # noqa: BLE001
        return []
    return [{"topic_id": r["topic_id"], "label": r["label"], "keywords": list(r["keywords"] or []),
             "body": r["body"], "status": r["status"], "updated_at": iso(r["updated_at"])}
            for r in rows]


class CustomTopicBody(BaseModel):
    label: str
    keywords: list[str]
    body: str
    status: str = "미사용"


def _clean_custom(p: CustomTopicBody) -> tuple:
    label = (p.label or "").strip()
    if not label or len(label) > LABEL_MAX:
        raise HTTPException(400, "주제 이름은 1~%d자로 적어야 합니다" % LABEL_MAX)
    if label in _topics() or label in {lab for lab, _d in _topics().values()}:
        raise HTTPException(400, "기본 주제와 같은 이름은 쓸 수 없습니다")
    kws, seen = [], set()
    for k in p.keywords or []:
        k = (k or "").strip()
        n = TR.norm_keyword(k)
        if not n or n in seen:
            continue
        if len(n) < TR.CUSTOM_KEYWORD_MIN or len(k) > TR.CUSTOM_KEYWORD_MAX:
            raise HTTPException(400, "낱말은 %d~%d자로 적어야 합니다: %s"
                                % (TR.CUSTOM_KEYWORD_MIN, TR.CUSTOM_KEYWORD_MAX, k))
        seen.add(n)
        kws.append(k)
    if not kws:
        raise HTTPException(400, "알아볼 낱말을 하나 이상 적어야 합니다")
    if len(kws) > KEYWORDS_MAX:
        raise HTTPException(400, "낱말은 %d개까지 적을 수 있습니다" % KEYWORDS_MAX)
    body = (p.body or "").strip()
    if not body or len(body) > MAX_LEN:
        raise HTTPException(400, "안내는 1~%d자로 적어야 합니다" % MAX_LEN)
    if p.status not in STATUSES:
        raise HTTPException(400, "상태는 «사용» 또는 «미사용»입니다")
    return label, kws, body, p.status


def _custom_saved(status: str) -> str:
    return ("저장했습니다. 다음 문의부터 이 낱말이 나오면 고객에게 이 안내가 나갑니다." if status == "사용"
            else "저장했습니다. «미사용»이라 고객에게는 나가지 않습니다.")


@router.post("/shop-notices/custom")
def add_custom(payload: CustomTopicBody):
    me = _owner()
    label, kws, body, status = _clean_custom(payload)
    with engine.begin() as conn:
        dup = conn.execute(text("SELECT 1 FROM shop_notice_topics WHERE label = :l"), {"l": label}).first()
        if dup:
            raise HTTPException(409, "같은 이름의 주제가 이미 있습니다")
        tid = conn.execute(text("""
            INSERT INTO shop_notice_topics (label, keywords, body, status, created_by, updated_by)
            VALUES (:l, CAST(:k AS JSONB), :b, :s, :who, :who) RETURNING topic_id"""),
            {"l": label, "k": json.dumps(kws, ensure_ascii=False), "b": body, "s": status,
             "who": me.get("operator_id")}).scalar_one()
    return {"ok": True, "topic_id": tid, "status": status, "note": _custom_saved(status)}


@router.put("/shop-notices/custom/{topic_id}")
def save_custom(topic_id: int, payload: CustomTopicBody):
    me = _owner()
    label, kws, body, status = _clean_custom(payload)
    with engine.begin() as conn:
        dup = conn.execute(text("SELECT 1 FROM shop_notice_topics WHERE label = :l AND topic_id <> :id"),
                           {"l": label, "id": topic_id}).first()
        if dup:
            raise HTTPException(409, "같은 이름의 주제가 이미 있습니다")
        n = conn.execute(text("""
            UPDATE shop_notice_topics
               SET label = :l, keywords = CAST(:k AS JSONB), body = :b, status = :s,
                   updated_by = :who, updated_at = now()
             WHERE topic_id = :id"""),
            {"l": label, "k": json.dumps(kws, ensure_ascii=False), "b": body, "s": status,
             "who": me.get("operator_id"), "id": topic_id}).rowcount
    if not n:
        raise HTTPException(404, "없는 주제입니다")
    return {"ok": True, "topic_id": topic_id, "status": status, "note": _custom_saved(status)}


class NoticeBody(BaseModel):
    body: str | None = None
    status: str


@router.put("/shop-notices/{topic_key}")
def save_notice(topic_key: str, payload: NoticeBody):
    me = _owner()
    if topic_key not in _topics():
        raise HTTPException(404, "없는 주제입니다")
    if payload.status not in STATUSES:
        raise HTTPException(400, "상태는 «사용» 또는 «미사용»입니다")
    body = (payload.body or "").strip() or None
    if body and len(body) > MAX_LEN:
        raise HTTPException(400, "안내는 %d자까지 적을 수 있습니다" % MAX_LEN)
    if payload.status == "사용" and not body:
        raise HTTPException(400, "내용을 적어야 «사용»으로 둘 수 있습니다")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO shop_notices (topic_key, body, status, updated_by, updated_at)
            VALUES (:k, :b, :s, :who, now())
            ON CONFLICT (topic_key) DO UPDATE
               SET body = EXCLUDED.body, status = EXCLUDED.status,
                   updated_by = EXCLUDED.updated_by, updated_at = now()
        """), {"k": topic_key, "b": body, "s": payload.status, "who": me.get("operator_id")})
    return {"ok": True, "topic_key": topic_key, "status": payload.status,
            "note": ("저장했습니다. 다음 문의부터 고객에게 이 안내가 나갑니다." if payload.status == "사용"
                     else "저장했습니다. 고객에게는 기본 안내가 나갑니다.")}
