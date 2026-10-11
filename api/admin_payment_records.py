"""ADM-PAY-020 결제·정산 기록장 API (2026-10-11 사장님 「기록장」 · 「표시만」 확정).

관리자가 은행·PG·쇼핑몰에서 **직접 확인한** 거래를 적는다. 시스템이 은행·PG 와 대조하지 않는다.
기준 문서: /mnt/project-files/품질관리-20261011/관리자/결제정산-기록장-데이터-준비.md

  기록 단위   거래 1건 = `payment_confirmation_records` 1행. 주문 연결은 `payment_confirmation_allocations`
              (부분 입금 · 여러 주문 합산). 환불은 kind='refund' 로 따로 적는다.
  금융 경계   이 모듈은 위 두 표와 `payment_month_reviews` 에만 쓴다. orders·payments·refunds·재고·
              commerce 상태는 읽기만 한다(테스트가 소스의 쓰기 대상 표를 고정한다).
  작성자      실제 로그인 운영자만. `current_operator_id()` 의 대체값 1 을 쓰지 않는다.
  중복        유효 기록 중 (기관, 참고번호)가 같으면 막는다. 참고번호가 없으면 막지 않고 경고만 준다.
  정정·철회   지우지 않는다. 새 행이 원래 행을 가리킨다. 한 행은 한 번만 이어받는다(동시 정정 409).
              철회는 기록의 효력만 거둔다 — 실제 거래를 취소하지 않는다. 옛 정산의 삭제형 undo 를 쓰지 않는다.
  월 기준     기관 거래일(occurred_on, KST 날짜). 관리자 확인일은 따로 보인다.
  월 점검     「표시만」. 점검 뒤에도 적을 수 있고, 점검 뒤 추가·정정 건수를 보여 준다.
  옛 계산     `admin_payments.list_payments()` 를 그대로 불러 참고 금액으로만 보인다(UTC 일자 · 현재
              수수료율은 미마감분에만). 새 주문을 옛 계산에 넣지 않는다.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .admin_orders import _commerce_order_ids
from .auth import current_operator
from .db import engine
from .timeutil import iso

router = APIRouter(prefix="/api/admin/payment-records")

KST = timezone(timedelta(hours=9))
KIND_KO = {"deposit": "입금 확인", "settlement": "정산 내역", "refund": "환불 출금"}
SOURCE_KO = {"bank": "은행", "pg": "PG", "mall": "쇼핑몰"}
LIST_LIMIT = 200

# 「지금 유효한 판」 — 이어받은 행이 없는 행. 철회 행도 현재 판이지만 효력은 없다.
CURRENT = ("NOT EXISTS (SELECT 1 FROM payment_confirmation_records n"
           " WHERE n.supersedes_id = r.record_id)")
EFFECTIVE = CURRENT + " AND r.action <> 'withdraw'"

NO_REF_WARNING = "참고번호가 없어 중복 여부를 확인하기 어렵습니다."


class Alloc(BaseModel):
    order_no: str
    amount: int


class RecordBody(BaseModel):
    kind: Literal["deposit", "settlement", "refund"]
    source: Literal["bank", "pg", "mall"]
    institution: str
    external_ref: str | None = None
    amount: int
    occurred_on: date
    confirmed_on: date
    memo: str | None = None
    allocations: list[Alloc] = []


class CorrectBody(RecordBody):
    reason: str


class WithdrawBody(BaseModel):
    reason: str


class ReviewBody(BaseModel):
    note: str | None = None


def _writer() -> int:
    """작성자 = 실제 로그인 운영자. 등급(운영자 이상)은 `auth.required_role` 이 이미 막는다."""
    op = current_operator()
    if not op or not op.get("operator_id"):
        raise HTTPException(401, "로그인한 운영자만 기록할 수 있습니다.")
    return int(op["operator_id"])


def _kst_today() -> date:
    return datetime.now(KST).date()


def _month(value: str | None) -> date:
    if not value:
        t = _kst_today()
        return t.replace(day=1)
    try:
        y, m = value.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        raise HTTPException(400, "월 형식은 YYYY-MM 입니다.")


def _next_month(m: date) -> date:
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def _clean(body: RecordBody) -> dict:
    inst = (body.institution or "").strip()
    ref = (body.external_ref or "").strip() or None
    if not inst:
        raise HTTPException(422, "기관명을 입력해 주세요.")
    if len(inst) > 60:
        raise HTTPException(422, "기관명은 60자 이내로 입력해 주세요.")
    if ref and len(ref) > 120:
        raise HTTPException(422, "거래 참고번호는 120자 이내로 입력해 주세요.")
    if body.amount <= 0:
        raise HTTPException(422, "금액은 0보다 커야 합니다.")
    if body.confirmed_on < body.occurred_on:
        raise HTTPException(422, "관리자 확인일은 기관 거래일보다 앞설 수 없습니다.")
    seen = set()
    for a in body.allocations:
        no = (a.order_no or "").strip()
        if not no:
            raise HTTPException(422, "연결할 주문번호를 입력해 주세요.")
        if no in seen:
            raise HTTPException(422, f"주문 {no} 이(가) 두 번 들어 있습니다.")
        if a.amount <= 0:
            raise HTTPException(422, f"주문 {no} 의 배분 금액은 0보다 커야 합니다.")
        seen.add(no)
    memo = (body.memo or "").strip() or None
    return {"kind": body.kind, "source": body.source, "institution": inst, "external_ref": ref,
            "amount": body.amount, "occurred_on": body.occurred_on,
            "confirmed_on": body.confirmed_on, "memo": memo}


def _resolve_orders(conn, allocs: list[Alloc]) -> list[tuple[int, int]]:
    if not allocs:
        return []
    nos = [a.order_no.strip() for a in allocs]
    found = dict(conn.execute(text(
        "SELECT order_no, order_id FROM orders WHERE order_no = ANY(:nos)"), {"nos": nos}).all())
    missing = [n for n in nos if n not in found]
    if missing:
        raise HTTPException(422, "없는 주문번호입니다: " + ", ".join(missing))
    return [(found[a.order_no.strip()], a.amount) for a in allocs]


def _check_duplicate(conn, inst: str, ref: str | None, replacing: int | None) -> list[str]:
    """유효 기록 중 같은 (기관, 참고번호)가 있으면 409. 참고번호가 없으면 경고만 돌려준다."""
    if not ref:
        return [NO_REF_WARNING]
    # 같은 번호를 동시에 두 명이 적는 경합을 막는다(트랜잭션 끝에 풀린다).
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                 {"k": "payrec|" + inst.lower() + "|" + ref})
    dup = conn.execute(text(
        "SELECT r.record_id FROM payment_confirmation_records r"
        " WHERE lower(r.institution) = lower(:inst) AND r.external_ref = :ref AND " + EFFECTIVE +
        " AND (CAST(:rep AS BIGINT) IS NULL OR r.record_id <> :rep) LIMIT 1"),
        {"inst": inst, "ref": ref, "rep": replacing}).scalar()
    if dup is not None:
        raise HTTPException(409, {"code": "duplicate_ref", "record_id": dup,
                                  "detail": "같은 기관과 거래 참고번호의 기록이 있습니다."})
    return []


def _insert(conn, row: dict, allocs: list[tuple[int, int]], *, action: str, supersedes: int | None,
            reason: str | None, by: int) -> int:
    try:
        with conn.begin_nested():
            rid = conn.execute(text(
                "INSERT INTO payment_confirmation_records (kind, source, institution, external_ref,"
                " amount, occurred_on, confirmed_on, memo, action, supersedes_id, reason, recorded_by)"
                " VALUES (:kind, :source, :institution, :external_ref, :amount, :occurred_on,"
                " :confirmed_on, :memo, :action, :sup, :reason, :by) RETURNING record_id"),
                {**row, "action": action, "sup": supersedes, "reason": reason, "by": by}).scalar_one()
    except IntegrityError:
        raise HTTPException(409, {"code": "stale", "detail":
                                  "다른 운영자가 이 기록을 먼저 고쳤습니다. 새로고침한 뒤 다시 확인해 주세요."})
    for order_id, amount in allocs:
        conn.execute(text(
            "INSERT INTO payment_confirmation_allocations (record_id, order_id, amount)"
            " VALUES (:r, :o, :a)"), {"r": rid, "o": order_id, "a": amount})
    return rid


def _lock_current(conn, record_id: int) -> dict:
    row = conn.execute(text(
        "SELECT r.*, " + CURRENT + " AS is_current FROM payment_confirmation_records r"
        " WHERE r.record_id = :id FOR UPDATE"), {"id": record_id}).mappings().first()
    if row is None:
        raise HTTPException(404, "기록을 찾지 못했습니다.")
    if not row["is_current"]:
        raise HTTPException(409, {"code": "stale", "detail":
                                  "이 기록은 이미 정정·철회됐습니다. 새로고침한 뒤 최신 기록을 확인해 주세요."})
    if row["action"] == "withdraw":
        raise HTTPException(409, {"code": "withdrawn", "detail": "철회된 기록은 정정할 수 없습니다."})
    return dict(row)


def _reason(value: str) -> str:
    r = (value or "").strip()
    if not r:
        raise HTTPException(422, "사유를 입력해 주세요.")
    return r


@router.post("")
def create_record(body: RecordBody):
    by = _writer()
    row = _clean(body)
    with engine.begin() as conn:
        allocs = _resolve_orders(conn, body.allocations)
        warnings = _check_duplicate(conn, row["institution"], row["external_ref"], None)
        rid = _insert(conn, row, allocs, action="create", supersedes=None, reason=None, by=by)
    return {"record_id": rid, "warnings": warnings,
            "verdict": "확인 내용을 기록했습니다. 실제 결제·입금·환불 상태는 바뀌지 않습니다."}


@router.post("/{record_id}/correct")
def correct_record(record_id: int, body: CorrectBody):
    by = _writer()
    reason = _reason(body.reason)
    row = _clean(body)
    with engine.begin() as conn:
        _lock_current(conn, record_id)
        allocs = _resolve_orders(conn, body.allocations)
        warnings = _check_duplicate(conn, row["institution"], row["external_ref"], record_id)
        rid = _insert(conn, row, allocs, action="correct", supersedes=record_id, reason=reason, by=by)
    return {"record_id": rid, "warnings": warnings, "verdict": "정정 기록을 남겼습니다. 원래 기록은 이력에 그대로 있습니다."}


@router.post("/{record_id}/withdraw")
def withdraw_record(record_id: int, body: WithdrawBody):
    by = _writer()
    reason = _reason(body.reason)
    with engine.begin() as conn:
        cur = _lock_current(conn, record_id)
        row = {k: cur[k] for k in ("kind", "source", "institution", "external_ref", "amount",
                                   "occurred_on", "confirmed_on", "memo")}
        # 철회 판도 원래 연결을 그대로 들고 간다 — 이력에서 무엇을 거뒀는지 보이게.
        allocs = [tuple(a) for a in conn.execute(text(
            "SELECT order_id, amount FROM payment_confirmation_allocations WHERE record_id = :r"
            " ORDER BY allocation_id"), {"r": record_id}).all()]
        rid = _insert(conn, row, allocs, action="withdraw", supersedes=record_id, reason=reason, by=by)
    return {"record_id": rid,
            "verdict": "기록을 철회했습니다. 이 처리는 기록의 효력만 거두며 실제 거래를 취소하지 않습니다."}


@router.post("/months/{month}/review")
def review_month(month: str, body: ReviewBody):
    by = _writer()
    m = _month(month)
    note = (body.note or "").strip() or None
    with engine.begin() as conn:
        rid = conn.execute(text(
            "INSERT INTO payment_month_reviews (month, note, reviewed_by) VALUES (:m, :n, :b)"
            " RETURNING review_id"), {"m": m, "n": note, "b": by}).scalar_one()
    return {"review_id": rid, "verdict": "월별 기록 점검 완료로 표시했습니다. 이후에도 기록할 수 있습니다."}


def _allocations(conn, record_ids: list[int]) -> dict[int, list[dict]]:
    if not record_ids:
        return {}
    rows = conn.execute(text(
        "SELECT a.record_id, a.order_id, o.order_no, a.amount FROM payment_confirmation_allocations a"
        " JOIN orders o USING (order_id) WHERE a.record_id = ANY(:ids) ORDER BY a.allocation_id"),
        {"ids": record_ids}).mappings().all()
    commerce = _commerce_order_ids(conn, [r["order_id"] for r in rows])
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["record_id"], []).append({
            "order_no": r["order_no"], "amount": r["amount"], "new_order": r["order_id"] in commerce})
    return out


def _record_view(r, allocs: list[dict]) -> dict:
    total = sum(a["amount"] for a in allocs)
    return {
        "id": r["record_id"], "kind": r["kind"], "kind_ko": KIND_KO[r["kind"]],
        "source": r["source"], "source_ko": SOURCE_KO[r["source"]],
        "institution": r["institution"], "external_ref": r["external_ref"],
        "amount": r["amount"], "occurred_on": iso(r["occurred_on"]),
        "confirmed_on": iso(r["confirmed_on"]), "memo": r["memo"],
        "action": r["action"], "withdrawn": r["action"] == "withdraw", "reason": r["reason"],
        "recorded_by": r["operator"], "recorded_at": iso(r["recorded_at"]),
        "allocations": allocs, "alloc_total": total,
        # 미해결 차이: 거래 금액과 주문별 배분 합계가 다르다(연결 주문이 없어도 차이다).
        "diff": r["amount"] - total,
    }


def _reference(month: date) -> dict:
    """옛 계산 기준 참고 금액 — 옛 화면 API 를 그대로 부른다. 실패해도 기록장은 뜬다."""
    from .admin_payments import list_payments
    try:
        data = list_payments()
    except Exception as e:  # noqa: BLE001 — 참고 영역만 실패로 보인다
        return {"error": f"옛 계산을 불러오지 못했습니다({type(e).__name__})."}
    prefix = month.strftime("%Y-%m")
    saved = [s for s in data["settles"] if s["date"].startswith(prefix) and s["state"] != "대기"]
    pending = [s for s in data["settles"] if s["date"].startswith(prefix) and s["state"] == "대기"]

    def tot(rows, key):
        return sum(s[key] for s in rows)
    return {
        "error": None,
        "saved": {"days": len(saved), "gross": tot(saved, "gross"), "fee": tot(saved, "fee"),
                  "net": tot(saved, "net"),
                  "late_n": sum((s["late"] or {}).get("n", 0) for s in saved)},
        # 미마감분만 지금 수수료율로 계산한 값이다. 저장된 계산의 당시 수수료율은 알 수 없다.
        "pending": {"days": len(pending), "gross": tot(pending, "gross"), "fee": tot(pending, "fee"),
                    "net": tot(pending, "net"), "fee_rate": data["fee_rate"]},
    }


@router.get("")
def list_records(month: str | None = None, kind: str | None = None, offset: int = 0):
    m = _month(month)
    nm = _next_month(m)
    if kind and kind not in KIND_KO:
        raise HTTPException(400, "kind 는 deposit · settlement · refund 중 하나입니다.")
    op = current_operator() or {}
    p = {"lo": m, "hi": nm}
    kind_sql = " AND r.kind = :kind" if kind else ""
    if kind:
        p["kind"] = kind
    base = ("FROM payment_confirmation_records r LEFT JOIN admin_operators o"
            " ON o.operator_id = r.recorded_by"
            " WHERE r.occurred_on >= :lo AND r.occurred_on < :hi AND " + CURRENT)
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) " + base + kind_sql), p).scalar_one()
        rows = conn.execute(text(
            "SELECT r.*, COALESCE(o.name, '—') AS operator " + base + kind_sql +
            " ORDER BY r.occurred_on DESC, r.record_id DESC LIMIT :lim OFFSET :off"),
            {**p, "lim": LIST_LIMIT, "off": max(0, offset)}).mappings().all()
        allocs = _allocations(conn, [r["record_id"] for r in rows])
        summary_rows = conn.execute(text(
            "SELECT r.kind, COUNT(*) AS n, SUM(r.amount) AS amt,"
            " COUNT(*) FILTER (WHERE r.external_ref IS NULL) AS no_ref,"
            " COUNT(*) FILTER (WHERE r.amount <> COALESCE((SELECT SUM(a.amount)"
            "   FROM payment_confirmation_allocations a WHERE a.record_id = r.record_id), 0)) AS diff_n"
            " FROM payment_confirmation_records r"
            " WHERE r.occurred_on >= :lo AND r.occurred_on < :hi AND " + EFFECTIVE +
            " GROUP BY r.kind"), p).mappings().all()
        review = conn.execute(text(
            "SELECT v.reviewed_at, v.note, COALESCE(o.name, '—') AS operator"
            " FROM payment_month_reviews v LEFT JOIN admin_operators o ON o.operator_id = v.reviewed_by"
            " WHERE v.month = :lo ORDER BY v.reviewed_at DESC, v.review_id DESC LIMIT 1"), p).mappings().first()
        after = None
        if review:
            # 점검 뒤 바뀐 건수. 정정·철회는 «새 판의 달»과 «원래 판의 달» 둘 다에 센다 —
            # 9월 점검 뒤 거래일을 10월로 옮긴 정정이 9월에서 사라지면 9월 합계가 바뀐 것을
            # 아무도 모른다(코덱스 #144 검수). 같은 달 안의 정정·철회는 한 번만 센다.
            after = conn.execute(text(
                "SELECT COUNT(*) FILTER (WHERE r.action = 'create' AND r.occurred_on >= :lo"
                "   AND r.occurred_on < :hi) AS added,"
                " COUNT(*) FILTER (WHERE r.action <> 'create') AS changed"
                " FROM payment_confirmation_records r"
                " LEFT JOIN payment_confirmation_records prev ON prev.record_id = r.supersedes_id"
                " WHERE r.recorded_at > :at AND ((r.occurred_on >= :lo AND r.occurred_on < :hi)"
                "   OR (r.action <> 'create' AND prev.occurred_on >= :lo AND prev.occurred_on < :hi))"),
                {**p, "at": review["reviewed_at"]}).mappings().one()

    by_kind = {k: {"n": 0, "amount": 0} for k in KIND_KO}
    no_ref = diff_n = 0
    for s in summary_rows:
        by_kind[s["kind"]] = {"n": s["n"], "amount": int(s["amt"] or 0)}
        no_ref += s["no_ref"]
        diff_n += s["diff_n"]
    return {
        "month": m.strftime("%Y-%m"),
        "can_write": op.get("role") in ("operator", "owner"),
        "total": total, "offset": max(0, offset), "limit": LIST_LIMIT,
        "records": [_record_view(r, allocs.get(r["record_id"], [])) for r in rows],
        "summary": {"by_kind": by_kind, "unresolved_n": diff_n, "no_ref_n": no_ref},
        "review": None if not review else {
            "reviewed_at": iso(review["reviewed_at"]), "note": review["note"],
            "reviewed_by": review["operator"],
            "added_after": after["added"], "changed_after": after["changed"]},
        "reference": _reference(m),
    }


@router.get("/orders")
def lookup_orders(q: str):
    """기록에 연결할 주문 찾기 — 주문번호 앞부분으로 10건까지. 읽기만 한다."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"items": []}
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT o.order_id, o.order_no, o.status, o.total_amount, o.created_at,"
            " COALESCE((SELECT SUM(a.amount) FROM payment_confirmation_allocations a"
            "   JOIN payment_confirmation_records r USING (record_id)"
            "   WHERE a.order_id = o.order_id AND r.kind <> 'refund' AND " + EFFECTIVE + "), 0) AS recorded_in,"
            " EXISTS (SELECT 1 FROM payment_confirmation_allocations a"
            "   JOIN payment_confirmation_records r USING (record_id)"
            "   WHERE a.order_id = o.order_id AND r.kind = 'settlement' AND " + EFFECTIVE + ") AS has_settlement"
            " FROM orders o WHERE o.order_no ILIKE :q ORDER BY o.order_id DESC LIMIT 10"),
            {"q": q.replace("%", "").replace("_", r"\_") + "%"}).mappings().all()
        commerce = _commerce_order_ids(conn, [r["order_id"] for r in rows])
    items = []
    for r in rows:
        state = ("정산 내역 기록됨" if r["has_settlement"]
                 else "입금 확인 내용 기록됨" if r["recorded_in"] else "확인 기록 없음")
        items.append({"order_no": r["order_no"], "status": r["status"], "total": r["total_amount"],
                      "created_at": iso(r["created_at"]), "recorded_in": int(r["recorded_in"]),
                      "record_state": state, "new_order": r["order_id"] in commerce})
    return {"items": items}


@router.get("/{record_id}")
def record_history(record_id: int):
    """한 거래의 판 전체(처음 기록 → 정정·철회). 지금 판이 맨 앞이다."""
    with engine.connect() as conn:
        # 이 행에서 앞으로(이어받은 행) 끝까지 간 뒤, 거기서 뒤로 처음 기록까지 거슬러 간다.
        head = conn.execute(text(
            "WITH RECURSIVE fwd AS (SELECT record_id FROM payment_confirmation_records WHERE record_id = :id"
            " UNION ALL SELECT n.record_id FROM payment_confirmation_records n JOIN fwd ON n.supersedes_id = fwd.record_id)"
            " SELECT max(record_id) FROM fwd"), {"id": record_id}).scalar()
        if head is None:
            raise HTTPException(404, "기록을 찾지 못했습니다.")
        rows = conn.execute(text(
            "WITH RECURSIVE back AS (SELECT * FROM payment_confirmation_records WHERE record_id = :h"
            " UNION ALL SELECT p.* FROM payment_confirmation_records p JOIN back ON back.supersedes_id = p.record_id)"
            " SELECT b.*, COALESCE(o.name, '—') AS operator FROM back b"
            " LEFT JOIN admin_operators o ON o.operator_id = b.recorded_by ORDER BY b.record_id DESC"),
            {"h": head}).mappings().all()
        allocs = _allocations(conn, [r["record_id"] for r in rows])
    return {"current_id": head,
            "versions": [_record_view(r, allocs.get(r["record_id"], [])) for r in rows]}
