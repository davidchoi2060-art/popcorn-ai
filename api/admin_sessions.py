"""ADM-ORD-010 견적 상담 기록 — 읽기 전용 관측 창 (재현성 소명 근거).

원칙(A-02 재현성): 같은 입력 + 같은 재고 → 같은 결과. 상담 세션은 **제약 객체(단일 원천)**를
그대로 저장하고, 티어별 견적은 quote_snapshots에 부품·가격 스냅샷으로 남는다. 이 화면은
"이 고객이 어떤 조건으로 무슨 견적을 받았는지"를 당시 그대로 재현해 분쟁·문의에 소명한다.

정직 표기 2건:
  ① **회원 귀속 제한** — consult_sessions.member_id는 전부 NULL(recommend가 로그인 전 세션이라
     member를 싣지 않는다). 화면은 '비로그인 세션'으로 표기하고, 회원 연결은 실 인증 슬라이스 몫.
  ② **이탈 판정은 스냅샷 유무 파생** — 단계별 이탈 지점을 남기는 이벤트 로그가 없다(S1은
     확정 시점에만 서버를 호출). 스냅샷 0건 = "견적 미생성(이탈)"으로만 구분(이관: 단계 이벤트).
'재현'은 저장된 스냅샷 원문을 그대로 보여주는 것이며, **현재 재고로 엔진을 재실행해 대조하는
기능은 이관**(재고가 바뀌면 결과가 달라지는 것이 정상 — 재현은 당시 스냅샷 기준).
주문 연결 = orders.session_id(마이그레이션 0003).
"""
from fastapi import APIRouter
from sqlalchemy import text

from .admin_products import PART_TYPE_LABELS
from .db import engine

router = APIRouter(prefix="/api/admin")

LIMIT = 200
MODE_KO = {"guided": ("맡김", "primary"), "chat": ("함께", "info"),
           "expert": ("직접", "secondary"), "talk": ("팝콘톡", "info")}
TIER_KO = {"value": "가성비", "recommend": "추천", "highend": "고성능"}


def _parts(items) -> list:
    """스냅샷 items 형태 2종 방어 — {"parts":[...]}(recommend 생성분)와 [...](스왑 생성분)."""
    if isinstance(items, dict):
        return items.get("parts") or []
    return items if isinstance(items, list) else []


def _companion(comp) -> list:
    if isinstance(comp, dict):
        return comp.get("offered") or []
    return comp if isinstance(comp, list) else []


@router.get("/sessions")
def list_sessions():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT s.session_id, s.member_id, s.mode, s.constraints, s.created_at,"
            " m.nickname, o.order_no, o.status AS order_status,"
            " (SELECT COUNT(*) FROM quote_snapshots q WHERE q.session_id=s.session_id) AS snaps"
            " FROM consult_sessions s"
            " LEFT JOIN members m USING (member_id)"
            " LEFT JOIN (SELECT DISTINCT ON (session_id) session_id, order_no, status"
            "            FROM orders WHERE session_id IS NOT NULL"
            "            ORDER BY session_id, order_id DESC) o USING (session_id)"
            " ORDER BY s.session_id DESC LIMIT :lim"), {"lim": LIMIT}).mappings().all()
        snaps = conn.execute(text(
            "SELECT snapshot_id, session_id, quote_type, total_amount, items, companion, created_at"
            " FROM quote_snapshots WHERE session_id = ANY(:ids) ORDER BY snapshot_id"),
            {"ids": [r["session_id"] for r in rows] or [0]}).mappings().all()
        today = conn.execute(text(
            "SELECT COUNT(*) FROM consult_sessions WHERE created_at::date = CURRENT_DATE")).scalar_one()

    by_session: dict = {}
    for q in snaps:
        by_session.setdefault(q["session_id"], []).append(q)

    items, done, drop = [], 0, 0
    for r in rows:
        cons = r["constraints"] or []
        labels = [f"{c.get('l')}: {c.get('v')}" for c in cons if isinstance(c, dict)]
        sq = by_session.get(r["session_id"], [])
        # 대표 스냅샷 = 추천 티어 우선, 없으면 마지막(스왑 적용분이 가장 최신)
        rep = next((q for q in sq if q["quote_type"] == "recommend"), sq[-1] if sq else None)
        parts = _parts(rep["items"]) if rep else []
        if sq:
            done += 1
        else:
            drop += 1
        items.append({
            "session_id": r["session_id"], "at": r["created_at"].isoformat(),
            "mode": r["mode"], "mode_label": MODE_KO.get(r["mode"], (r["mode"], "secondary"))[0],
            "mode_color": MODE_KO.get(r["mode"], (r["mode"], "secondary"))[1],
            "member": r["nickname"],            # 전부 None — 화면은 '비로그인 세션'
            "constraints": labels,
            "summary": " · ".join(labels) or "제약 없음",
            "snapshots": [{
                "id": q["snapshot_id"], "tier": q["quote_type"],
                "tier_label": TIER_KO.get(q["quote_type"], q["quote_type"]),
                "total": q["total_amount"], "part_count": len(_parts(q["items"])),
            } for q in sq],
            "result": (f"{rep['total_amount']:,}원 · {len(parts)}부품" if rep else "견적 미생성"),
            "status": ("완주 → 주문" if r["order_no"] else ("완주" if sq else "이탈(견적 미생성)")),
            "order_no": r["order_no"], "order_status": r["order_status"],
            "rep": ({
                "id": rep["snapshot_id"], "tier_label": TIER_KO.get(rep["quote_type"], rep["quote_type"]),
                "total": rep["total_amount"],
                "parts": [{"cat": PART_TYPE_LABELS.get(p.get("part_type"), p.get("part_type")),
                           "name": p.get("name"), "price": p.get("price"), "sku": p.get("sku")}
                          for p in parts],
                "companion": [{"name": c.get("name"), "price": c.get("price")}
                              for c in _companion(rep["companion"]) if isinstance(c, dict)],
            } if rep else None),
        })
    return {"items": items, "today": today, "done": done, "drop": drop, "limit": LIMIT,
            "note": ("상담은 로그인 전 세션이라 회원 귀속이 비어 있습니다(실 인증 슬라이스 몫) ·"
                     " 이탈은 스냅샷 유무로만 판정합니다(단계별 이탈 이벤트는 준비 중) ·"
                     " 재현은 당시 스냅샷 기준이며 현재 재고로 재실행한 대조는 준비 중입니다.")}
