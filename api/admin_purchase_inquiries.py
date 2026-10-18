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

■ 연결 읽기 (2026-10-18 관리자 정리 기획 1묶음 · 규칙 = api/admin_mvp3_links)
  신청에 걸린 보관 견적(PC 한 대 가격 × 대수 · 바꾼 부품 차액) · 새로 구성된 PC ·
  그 견적의 팝콘PC 이동(인계 note 의 견적 번호)을 함께 싣는다. 명시 번호로만 잇는다.
  접수 경로 · 보관 목적 · 이동 이유 · 구매 결과는 저장하지 않으므로 「미기록」으로 밝힌다.
  신청서의 연락처(신청 당시)와 이 방문자의 «현재» 등록 연락처(0158)를 따로 보이고,
  다르면 알린다. 신청 기한이 지나면 현재 연락처로 빈칸을 채우지 않는다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from . import admin_mvp3_links as L
from .auth import current_operator
from .admin_raw_text import NOTICE as RAW_NOTICE, expired
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin", tags=["admin-purchase-inquiries"])

LIMIT = 50
STATUSES = ("대기", "처리 중", "완료")
# 목록 조건(2026-10-18 관리자 정리 기획 A01) — 연결 종류 · 보관 기한. 「곧」은 작업 편의용 표시일 뿐
# 보유 기간과 무관하다(보유 기간 자체는 대표 미확정 — api/mvp3_contact.KEEP_DAYS).
LINKS = {"quote": "i.quote_id IS NOT NULL", "config": "i.quote_id IS NULL AND i.configuration_id IS NOT NULL",
         "none": "i.quote_id IS NULL AND i.configuration_id IS NULL"}
DUE_SOON_DAYS = 14
DUES = {"soon": "i.purge_at > now() AND i.purge_at <= now() + make_interval(days => %d)" % DUE_SOON_DAYS,
        "expired": "i.purge_at <= now()"}
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
    kind_key, kind_label = L.kind(r.get("quote_snapshot"), r.get("configuration_id"), r.get("free_build"))
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
        # 고객이 부품을 직접 고른 구성(api/mvp3_free_build) — 신청 순간 다시 계산한 부품·판매가·총액
        "free_build": r.get("free_build"),
        "assignee": r["assignee_name"], "assignee_id": r["assignee_id"],
        "updated_at": iso(r["updated_at"]), "purge_at": iso(r["purge_at"]),
        "test": bool(r["is_test"]),
        # 연결 읽기(2026-10-18 관리자 정리 기획 A01·A01D) — 규칙은 api/admin_mvp3_links 한 곳.
        "kind": kind_key, "kind_label": kind_label,
        "link_label": L.link_label(r["quote_id"], r.get("configuration_id")),
        "quote": L.quote_view(r.get("quote_snapshot")),
        "handoff_no": r.get("ho_no"), "handoff_at": iso(r.get("ho_at")),
        "registered": None if gone else _registered(r, full),
    }


def _registered(r, full: bool):
    """이 방문자의 «현재» 등록 연락처(0158) — 신청서에 복사된 접수 당시 연락처와 따로 보인다.
    신청 기한이 지나면 내보내지 않는다(빈칸을 최신 연락처로 채우지 않는다). 둘이 다르면 알린다."""
    if r.get("reg_phone") is None:
        return None
    differs = bool(r["contact_phone"]) and L.digits(r["contact_phone"]) != L.digits(r["reg_phone"])
    return {"name": r["reg_name"],
            "phone": r["reg_phone"] if full else _mask_phone(r["reg_phone"]),
            "email": r["reg_email"] if full else _mask_email(r["reg_email"]),
            "purge_at": iso(r["reg_purge_at"]), "differs": differs}


_SELECT = f"""
    SELECT i.*, {IS_TEST} AS is_test,
           COALESCE(s.product_snapshot->>'name', '새로 구성된 PC · ' || (pc.content->>'title')) AS product_name,
           o.name AS assignee_name, s.product_snapshot AS quote_snapshot,
           ho.handoff_no AS ho_no, ho.created_at AS ho_at,
           vc.contact_name AS reg_name, vc.contact_phone AS reg_phone, vc.contact_email AS reg_email,
           vc.purge_at AS reg_purge_at
      FROM purchase_inquiries i
      LEFT JOIN mvp3_saved_recommendations s ON s.quote_id = i.quote_id
      LEFT JOIN pc_configurations pc ON pc.configuration_id = i.configuration_id
      LEFT JOIN admin_operators o ON o.operator_id = i.assignee_id
      LEFT JOIN LATERAL ({L.ho_for_quote_sql("i.quote_id")}) ho ON TRUE
      LEFT JOIN mvp3_visitor_contacts vc ON vc.user_id = i.user_id AND vc.contact_purged_at IS NULL
                                        AND vc.contact_phone IS NOT NULL AND vc.purge_at > now()
"""


@router.get("/purchase-inquiries")
def list_inquiries(offset: int = 0, status: str | None = None, include_test: bool = False,
                   visitor: str | None = None, link: str | None = None, due: str | None = None):
    me = current_operator()
    offset = max(0, offset)
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "알 수 없는 상태입니다")
    if link is not None and link not in LINKS:
        raise HTTPException(400, "알 수 없는 연결 조건입니다")
    if due is not None and due not in DUES:
        raise HTTPException(400, "알 수 없는 기한 조건입니다")
    where = ["TRUE" if include_test else f"NOT {IS_TEST}"]
    params: dict = {"lim": LIMIT, "off": offset}
    if status:
        where.append("i.status = :st"); params["st"] = status
    if link:
        where.append(LINKS[link])
    if due:
        where.append(DUES[due])
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
            "contact_masked": not full, "can_write": full, "raw_notice": RAW_NOTICE,
            "link": link, "due": due, "due_soon_days": DUE_SOON_DAYS}


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
