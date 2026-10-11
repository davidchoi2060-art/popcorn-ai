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
  ① 주제는 코드에 정해진 일곱 개뿐이다 — 새 주제는 판정 규칙이 함께 있어야 하므로
     이 화면에서 만들지 않는다.
  ② 바꾸기는 대표 권한(owner)만 한다.
  ③ 내용 없는 «사용»은 막는다(DB CHECK 도 같은 조건).
  ④ 행을 지우지 않는다 — «미사용»으로 내리면 기본 안내로 돌아간다.
"""
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
    return {"ok": True, "items": items, "max_len": MAX_LEN}


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
