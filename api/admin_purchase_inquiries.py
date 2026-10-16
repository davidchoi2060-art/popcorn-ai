"""구매 상담 신청(ADM-ORD-012 · 가칭) — 관리자 데이터 API.

고객이 지금 고객 화면(mvp3)에서 남긴 구매 상담 신청(`purchase_inquiries`, 0139 ·
`api/mvp3_purchase_inquiry.py`)을 보고 처리한다.

■ 할 수 있는 일
  목록(상태별) · 상세 · 상태 바꾸기(대기 · 처리 중 · 완료) · 내가 맡기 · 메모.
  같은 방문자의 문의 · 보관 견적은 「고객 문의 · 보관 견적」 화면으로 잇는다(방문자 키).

■ 개인정보
  연락처는 운영자 이상에게만 그대로 보인다. 조회 권한은 가운데를 가린다.
  조회 권한에는 문의 내용 · 메모 안의 연락처도 가린다(`api/talk.mask_pii`).
  보관 기한이 지난 신청은 연락처 · 문의 내용을 내보내지 않는다(`contact_purged`).
  행을 지우지 않는다 — 상태로 처리한다. 보관 기한(`purge_at`)은 응답에 함께 싣는다.
  시험 신청(회귀 표식 · 「QA-」로 시작하는 이름이나 내용)은 기본으로 뺀다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from .auth import current_operator
from .admin_raw_text import NOTICE as RAW_NOTICE, expired
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-purchase-inquiries"])

LIMIT = 50
STATUSES = ("대기", "처리 중", "완료")
MEMO_MAX = 1000
IS_TEST = ("(i.data_origin <> 'real' OR COALESCE(i.contact_name, '') ILIKE 'QA-%'"
           " OR COALESCE(i.message, '') ILIKE 'QA-%')")


def _can_write(me) -> bool:
    return (me or {}).get("role") in ("owner", "operator")


def _mask_phone(p):
    if not p:
        return p
    digits = p.replace("-", "")
    return digits[:3] + "-****-" + digits[-4:] if len(digits) >= 7 else "****"


def _mask_email(e):
    if not e or "@" not in e:
        return e
    local, _, dom = e.partition("@")
    return local[:2] + "***@" + dom


def _mask_text(s):
    """자유 입력(문의 내용 · 메모)에 고객이 적은 연락처를 가린다 — 조회 권한용.
    연락처 칸만 가리고 본문을 그대로 주면 같은 번호가 본문으로 드러났다(2026-10-11 코덱스 검수 #85)."""
    if not s:
        return s
    from .talk import mask_pii
    return mask_pii(s)


def _row(r, full: bool) -> dict:
    # 보관 기한(신청 후 180일)이 지난 연락처 · 문의 내용은 내보내지 않는다 — 고객 동의 문구의 약속이다.
    gone = expired(r["purge_at"])
    return {
        "inquiry_id": r["inquiry_id"], "inquiry_no": r["inquiry_no"], "at": iso(r["created_at"]),
        "topic": r["topic"], "status": r["status"],
        "name": None if gone else r["contact_name"],
        "phone": None if gone else (r["contact_phone"] if full else _mask_phone(r["contact_phone"])),
        "email": None if gone else (r["contact_email"] if full else _mask_email(r["contact_email"])),
        "message": None if gone else (r["message"] if full else _mask_text(r["message"])),
        # 기한이 지나면 메모에 옮겨 적힌 연락처도 가린다(2026-10-11 코덱스 검수 #124 · #126).
        "memo": r["memo"] if full and not gone else _mask_text(r["memo"]),
        "contact_purged": gone,
        "visitor": ("u%d" % r["user_id"]) if r["user_id"] is not None else None,
        "quote_id": str(r["quote_id"]) if r["quote_id"] else None,
        "product_code": r["product_code"], "product_name": r["product_name"],
        "configuration_id": r.get("configuration_id"),
        "assignee": r["assignee_name"], "assignee_id": r["assignee_id"],
        "updated_at": iso(r["updated_at"]), "purge_at": iso(r["purge_at"]),
        "test": bool(r["is_test"]),
    }


_SELECT = f"""
    SELECT i.*, {IS_TEST} AS is_test,
           COALESCE(s.product_snapshot->>'name', '새로 구성된 PC · ' || (pc.content->>'title')) AS product_name,
           o.name AS assignee_name
      FROM purchase_inquiries i
      LEFT JOIN mvp3_saved_recommendations s ON s.quote_id = i.quote_id
      LEFT JOIN pc_configurations pc ON pc.configuration_id = i.configuration_id
      LEFT JOIN admin_operators o ON o.operator_id = i.assignee_id
"""


@router.get("/purchase-inquiries")
def list_inquiries(offset: int = 0, status: str | None = None, include_test: bool = False,
                   visitor: str | None = None):
    me = current_operator()
    offset = max(0, offset)
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "알 수 없는 상태입니다")
    where = ["TRUE" if include_test else f"NOT {IS_TEST}"]
    params: dict = {"lim": LIMIT, "off": offset}
    if status:
        where.append("i.status = :st"); params["st"] = status
    if visitor:
        if not (visitor.startswith("u") and visitor[1:].isdigit()):
            raise HTTPException(400, "방문자 표시가 올바르지 않습니다")
        where.append("i.user_id = :u"); params["u"] = int(visitor[1:])
    w = " AND ".join(where)
    test_w = "TRUE" if include_test else f"NOT {IS_TEST}"
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        rows = conn.execute(text(f"{_SELECT} WHERE {w} ORDER BY i.created_at DESC, i.inquiry_id DESC"
                                 " LIMIT :lim OFFSET :off"), params).mappings().all()
        total = conn.execute(text(f"SELECT COUNT(*) FROM purchase_inquiries i WHERE {w}"),
                             params).scalar_one()
        counts = dict(conn.execute(text(f"SELECT i.status, COUNT(*) FROM purchase_inquiries i"
                                        f" WHERE {test_w} GROUP BY i.status")).all())
        excluded = 0 if include_test else conn.execute(text(
            f"SELECT COUNT(*) FROM purchase_inquiries i WHERE {IS_TEST}")).scalar_one()
    full = _can_write(me)
    return {"ok": True, "items": [_row(r, full) for r in rows], "total": int(total),
            "offset": offset, "limit": LIMIT,
            "counts": {s: int(counts.get(s, 0)) for s in STATUSES},
            "test_excluded": int(excluded), "include_test": include_test,
            "contact_masked": not full, "can_write": full, "raw_notice": RAW_NOTICE}


class UpdateBody(BaseModel):
    status: str
    memo: str | None = None
    assign_me: bool = False


@router.put("/purchase-inquiries/{inquiry_id}")
def update_inquiry(inquiry_id: int, body: UpdateBody):
    me = current_operator() or {}
    if not _can_write(me):
        raise HTTPException(403, "운영자 이상만 처리할 수 있습니다")
    if body.status not in STATUSES:
        raise HTTPException(400, "상태는 대기 · 처리 중 · 완료 중 하나입니다")
    memo = (body.memo or "").strip() or None
    if memo and len(memo) > MEMO_MAX:
        raise HTTPException(400, "메모는 %d자까지 적을 수 있습니다" % MEMO_MAX)
    with engine.begin() as conn:
        n = conn.execute(text("""
            UPDATE purchase_inquiries
               SET status = :s, memo = :m, updated_by = :who, updated_at = now(),
                   assignee_id = CASE WHEN :mine THEN :who ELSE assignee_id END
             WHERE inquiry_id = :i"""),
            {"s": body.status, "m": memo, "who": me.get("operator_id"),
             "mine": bool(body.assign_me), "i": inquiry_id}).rowcount
    if not n:
        raise HTTPException(404, "없는 신청입니다")
    return {"ok": True, "inquiry_id": inquiry_id, "status": body.status, "note": "처리 결과를 저장했습니다."}
