"""ADM-SYS-030 작업 기록 — 감사 로그 읽기 (읽기 전용 슬라이스).

원칙: 삭제 없는 전 행 원장 — *_undo 행도 "…되돌림" 행위로 그대로 노출하고, 원본 행에는
undone(되돌려짐) 배지를 파생한다(ref_log_id 역참조 EXISTS — 각 도메인의 이중 undo 가드와
동일 관계. ref_log_id는 price_import가 문자열, 나머지가 int로 저장해 텍스트 비교로 통일).
비가역 처리(환불 complete 등)는 undo 행 자체가 없어 배지도 자연히 없다.
표시 문장(행위·대상·변경 내용)은 서버 파생 — 화면은 렌더만.
운영자는 mock 인증 한계로 전 행 '관리자'(OPERATOR_ID=1 고정 — 실 인증 이관).
이관: 페이지네이션·created_at 인덱스·기간/운영자 필터·CSV 내보내기.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api/admin")

LIMIT = 500  # 초과 시 total과 함께 정직 표기("최근 500건") — 페이지네이션 이관

KIND_LABELS = {"order": "주문", "refund": "환불", "settlement": "정산",
               "price_file": "단가표", "product_review": "검수·매입", "product": "상품"}
ACTION_LABELS = {
    "order_advance": "주문 처리", "order_advance_undo": "주문 처리 되돌림",
    "refund_advance": "환불 처리", "refund_advance_undo": "환불 처리 되돌림",
    "settlement_close": "정산 마감", "settlement_close_undo": "정산 마감 되돌림",
    "price_import_apply": "단가표 반영", "price_import_undo": "단가표 반영 되돌림",
    "review_process": "검수 처리", "review_bulk_confirm": "검수 일괄 확정",
    "review_undo": "검수 되돌림",
    "sourcing_link": "매입 모델 연결", "sourcing_unlink": "매입 모델 연결 해제",
    "product_register": "상품 등록",
}
ORDER_SUB = {"assemble": "조립 시작", "ship": "출고", "done": "배송 완료"}
REFUND_SUB = {"review": "검토 시작", "approve": "승인", "complete": "완료", "reject": "반려"}
REVIEW_MODE = {"approve": "승인", "manual": "직접 수정", "reject": "보류"}


def _summary(action: str, d: dict) -> str:
    """detail JSONB → 사람이 읽는 변경 내용 한 문장. 미지의 action은 원문 폴백(정직)."""
    d = d or {}
    if action == "order_advance":
        return f"{ORDER_SUB.get(d.get('action'), d.get('action', ''))} · {d.get('from')} → {d.get('to')}"
    if action == "refund_advance":
        return f"{REFUND_SUB.get(d.get('action'), d.get('action', ''))} · {d.get('from')} → {d.get('to')}"
    if action == "settlement_close":
        return f"{d.get('settle_date')} · 순액 {d.get('net', 0):,}원 · 결제 {len(d.get('payment_ids', []))}건"
    if action == "price_import_apply":
        return f"매입가 {len(d.get('items', []))}건 반영 · 판매가 재계산"
    if action == "review_process":
        mode = REVIEW_MODE.get(d.get("mode"), d.get("mode", ""))
        return f"{mode} · {d.get('field')} = {d.get('value')}" if d.get("field") else mode
    if action == "review_bulk_confirm":
        return f"저신뢰 {len(d.get('items', []))}건 원문값 일괄 확정"
    if action == "sourcing_link":
        return f"{(d.get('model_key') or '')[:40]} → {d.get('sku')} ({d.get('method')})"
    if action == "sourcing_unlink":
        return f"{(d.get('model_key') or '')[:40]} 연결 해제"
    if action == "product_register":
        return f"{d.get('sku')} 등록 · 매입 {d.get('cost_price', 0):,}원 ({d.get('part_type')})"
    if action.endswith("_undo") or d.get("ref_log_id"):
        return f"원 기록 #{d.get('ref_log_id')} 되돌림"
    return action  # 미지의 action — 원문 폴백


@router.get("/activity-logs")
def list_activity_logs():
    with engine.connect() as conn:
        total = conn.execute(text(
            "SELECT COUNT(*) FROM admin_operator_activity_logs")).scalar_one()
        rows = conn.execute(text(
            "SELECT l.log_id, l.action, l.target_kind, l.target_id, l.detail, l.created_at,"
            " COALESCE(o.name, '—') AS operator,"
            " EXISTS(SELECT 1 FROM admin_operator_activity_logs u"
            "        WHERE u.action LIKE '%undo'"
            "          AND u.detail->>'ref_log_id' = CAST(l.log_id AS TEXT)) AS undone"
            " FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " ORDER BY l.log_id DESC LIMIT :lim"), {"lim": LIMIT}).mappings().all()
    return {"total": total, "limit": LIMIT, "items": [{
        "log_id": r["log_id"],
        "at": r["created_at"].isoformat(),
        "operator": r["operator"],
        "kind": r["target_kind"],
        "kind_label": KIND_LABELS.get(r["target_kind"], r["target_kind"]),
        "action_label": ACTION_LABELS.get(r["action"], r["action"]),
        "is_undo": r["action"].endswith("_undo"),
        "target": r["target_id"],
        "summary": _summary(r["action"], r["detail"]),
        "undone": r["undone"],
    } for r in rows]}
