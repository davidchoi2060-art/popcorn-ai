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

완주 이후 원장은 둘이다(UX-33) — orders(2026-08-10까지, 이후 갱신 없음)와 handoffs(2026-08-11부터,
지금 쌓이는 원장). 한쪽만 조회하면 최근 인계가 화면에서 사라지므로 둘 다 LEFT JOIN한다.
주문 연결 = orders.session_id(마이그레이션 0003) · 인계 연결 = handoffs.session_id(마이그레이션 0042).

집계는 두 축이다: done/drop은 이 화면이 돌려주는 최신 LIMIT건 창 기준(기존 그대로 유지),
total·done_total·drop_total은 consult_sessions 전체 기준(창 밖 포함) — 완주율 분모를
200건 창이 아니라 전체로 잡을 수 있게 별도로 낸다.
"""
from fastapi import APIRouter
from sqlalchemy import text

from .timeutil import iso
from .admin_products import PART_TYPE_LABELS
from .db import engine
# 세션 조회 술어(「어느 세션을 포함하는가」) 단일 원천 — U-34 대응, 그 파일 docstring 참조.
# A-81 확정 이후: scope_note() = 「왜 세션 수가 줄었나」를 화면이 말할 문장(그 함수 참조).
from .session_scope import session_scope_where, scope_note

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
def list_sessions(offset: int = 0):
    # REPEATABLE READ로 연다(2026-08-15, 확인자 실측 재현 대응) — rows(LIMIT/OFFSET)·
    # today·total·done_total이 별개 SELECT라 기본 READ COMMITTED에서는 문장마다 새
    # 스냅샷을 본다. 그 사이 다른 커넥션이 INSERT를 커밋하면 rows 합계와 total이
    # 어긋난다(실측: offset=4800에서 1회차 total=4918·items=117 → 4800+117=4917≠4918,
    # 2회차 total=4923·items=123 → 일치. 화면은 그 어긋남으로 "25/25"(마지막 페이지)와
    # "다음 버튼 활성"이 동시에 뜨는 자기모순을 보였다). REPEATABLE READ는 트랜잭션
    # 시작 시점의 단일 스냅샷을 트랜잭션 내 모든 SELECT가 공유하게 한다 — rows·snaps·
    # today·total·done_total 다섯이 항상 서로 일치한다. 전부 SELECT뿐이라(쓰기 없음)
    # REPEATABLE READ 특유의 40001 직렬화 실패도 발생하지 않는다. execution_options의
    # isolation_level은 SQLAlchemy가 커넥션을 풀에 반납할 때 자동으로 기본 레벨로
    # 되돌린다(engine/characteristics.py IsolationLevelCharacteristic·pool/base.py
    # checkin의 finalize_callback) — 다른 요청·다른 화면에 새지 않는다.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        scope = session_scope_where()
        rows = conn.execute(text(
            "SELECT s.session_id, s.member_id, s.user_id, s.mode, s.constraints, s.created_at,"
            " m.nickname, o.order_no, o.status AS order_status,"
            " h.handoff_no, h.status AS handoff_status,"
            " h.total_quoted AS handoff_total_quoted, h.total_mall AS handoff_total_mall,"
            " h.price_checked AS handoff_price_checked, h.created_at AS handoff_created_at,"
            " (SELECT COUNT(*) FROM quote_snapshots q WHERE q.session_id=s.session_id) AS snaps"
            " FROM consult_sessions s"
            " LEFT JOIN members m USING (member_id)"
            " LEFT JOIN (SELECT DISTINCT ON (session_id) session_id, order_no, status"
            "            FROM orders WHERE session_id IS NOT NULL"
            "            ORDER BY session_id, order_id DESC) o USING (session_id)"
            " LEFT JOIN (SELECT DISTINCT ON (session_id) session_id, handoff_no, status,"
            "                   total_quoted, total_mall, price_checked, created_at"
            "            FROM handoffs WHERE session_id IS NOT NULL"
            "            ORDER BY session_id, handoff_id DESC) h USING (session_id)"
            f" WHERE {scope}"
            " ORDER BY s.session_id DESC LIMIT :lim OFFSET :off"),
            {"lim": LIMIT, "off": offset}).mappings().all()
        snaps = conn.execute(text(
            "SELECT snapshot_id, session_id, quote_type, total_amount, items, companion, created_at"
            " FROM quote_snapshots WHERE session_id = ANY(:ids) ORDER BY snapshot_id"),
            {"ids": [r["session_id"] for r in rows] or [0]}).mappings().all()
        today = conn.execute(text(
            f"SELECT COUNT(*) FROM consult_sessions s WHERE {scope}"
            " AND created_at::date = CURRENT_DATE")).scalar_one()
        # 전체 기준(창 밖 포함) — 완주율 분모가 200건 창이 아니라 전체가 되도록 별도로 낸다.
        # done_total은 quote_snapshots에 세션이 하나라도 있으면 완주로 센다(창 안 done과 같은 정의).
        # ⚠ 2026-08-20 정정 — done_total 을 quote_snapshots 단독으로 세면 total(scope 적용)만
        # 줄고 done_total(scope 미적용)은 그대로라 **정책이 켜지는 순간 완주율이 100%를
        # 넘는다**(제작 중 조사자 발견). quote_snapshots.session_id 는 NOT NULL + FK라
        # consult_sessions 에 없는 행이 없다(2026-08-20 직접 확인: 고아 행 0 · distinct
        # session_id 6,630 = JOIN 결과 6,630, 일치) — 그래서 JOIN 으로 같은 scope 를
        # 적용해도 **지금(scope=TRUE) 값은 그대로**다. total 과 done_total 이 항상 같은
        # 모집단(같은 scope)에서 나오게 한다.
        total = conn.execute(text(
            f"SELECT COUNT(*) FROM consult_sessions s WHERE {scope}")).scalar_one()
        done_total = conn.execute(text(
            "SELECT COUNT(DISTINCT q.session_id) FROM quote_snapshots q"
            f" JOIN consult_sessions s ON s.session_id = q.session_id WHERE {scope}")).scalar_one()
        drop_total = total - done_total

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
            "session_id": r["session_id"], "at": iso(r["created_at"]),
            "mode": r["mode"], "mode_label": MODE_KO.get(r["mode"], (r["mode"], "secondary"))[0],
            "mode_color": MODE_KO.get(r["mode"], (r["mode"], "secondary"))[1],
            "member": r["nickname"],            # 전부 None — 화면은 '비로그인 세션'
            "user_id": r["user_id"],            # 익명 방문자 키(FK users.user_id) — 회원 ID 아님. 비로그인 포함 전원에게 있다
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
            "handoff_no": r["handoff_no"], "handoff_status": r["handoff_status"],
            "handoff_total_quoted": r["handoff_total_quoted"],
            "handoff_total_mall": r["handoff_total_mall"],
            "handoff_price_checked": r["handoff_price_checked"],
            "handoff_at": (iso(r["handoff_created_at"]) if r["handoff_created_at"] else None),
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
            "offset": offset, "total": total,
            "done_total": done_total, "drop_total": drop_total,
            "scope_note": scope_note(),   # A-81 — 아래 kpiCard(「전체 세션」)의 note 자리로 간다
            "note": ("상담은 로그인 전 세션이라 회원 귀속이 비어 있습니다(실 인증 슬라이스 몫) ·"
                     " 이탈은 스냅샷 유무로만 판정합니다(단계별 이탈 이벤트는 준비 중) ·"
                     " 재현은 당시 스냅샷 기준이며 현재 재고로 재실행한 대조는 준비 중입니다 ·"
                     " user_id는 회원이 아니라 익명 방문자 키입니다(FK users, 익명 발급 — 회원과 혼동 금지) ·"
                     " done/drop은 최신 %d건 창 기준이고, done_total/drop_total·total은"
                     # ⚠ 2026-08-20 정정 — A-81 로 「전체」가 아니게 됐다(시험 운영 기간 제외).
                     " consult_sessions 중 「시험 운영 기간」 제외 %d건 기준입니다." % (LIMIT, total))}
