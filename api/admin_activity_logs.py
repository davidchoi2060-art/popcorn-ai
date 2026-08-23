"""ADM-SYS-030 작업 기록 — 감사 로그 읽기 (읽기 전용 슬라이스).

원칙: 삭제 없는 전 행 원장 — *_undo 행도 "…되돌림" 행위로 그대로 노출하고, 원본 행에는
undone(되돌려짐) 배지를 파생한다(ref_log_id 역참조 EXISTS — 각 도메인의 이중 undo 가드와
동일 관계. ref_log_id는 price_import가 문자열, 나머지가 int로 저장해 텍스트 비교로 통일).
비가역 처리(환불 complete 등)는 undo 행 자체가 없어 배지도 자연히 없다.
표시 문장(행위·대상·변경 내용)은 서버 파생 — 화면은 렌더만.
운영자 주체는 슬라이스 37부터 로그인 세션의 운영자다(그 전 기록은 시드 운영자 1 고정 —
과거 행은 원장이므로 소급 수정하지 않는다).
이관: 페이지네이션·created_at 인덱스·기간/운영자 필터·CSV 내보내기.

★ undone/is_undo 판정은 action 문자열을 절대 보지 않는다 — ref_log_id 보유/역참조 EXISTS만
본다(2026-08-14 결함 수정). 예전엔 undone SQL에 `AND u.action LIKE '%undo'`가 섞여 있었는데,
되돌림 action이 전부 영문 "_undo" 접미사인 게 아니다 — 도메인 코드가 `_log(conn, "카테고리
매핑 이동 되돌림", ...)`처럼 한국어 문자열을 action 컬럼에 직접 쓰는 경로가 있고(카테고리
매핑 이동·판매가 재산정·상품 상태 일괄 변경 3종), "되돌림"이라는 낱말조차 없이 같은 일을
하는 것도 있다(`sourcing_unlink` — admin_reviews.py가 "이미 되돌린 연결입니다"로 이중 실행을
막는, undo와 동일한 이중 가드 패턴을 쓰는 domain 동사). 실측(2026-08-14, .venv/Scripts/python
으로 api.db.engine 직접 SELECT)으로 ref_log_id를 detail에 쓰는 action 17종 전 행(수천 건)에
예외 없이 100% 붙어 있었다 — 빠진 행이 하나도 없어 이 키 하나로 판정이 충분하다. 반대로
action 이름으로 좁히면 좁힐수록 새 도메인이 되돌림을 다른 동사로 지을 때마다 다시 샌다
(사람이 놓친 게 아니라 방식 자체가 깨지기 쉽다 — 문자열 접미사 매칭이므로). action 이름
필터를 다시 넣지 마라. `_summary()`의 폴백(`d.get("ref_log_id")`)과 같은 근거를 쓴다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .timeutil import iso, kst_day_range, range_sql
from .db import engine

router = APIRouter(prefix="/api/admin")

LIMIT = 500  # 초과 시 total과 함께 정직 표기("최근 500건") — 페이지네이션 이관

# ⚠ 2026-08-15 점검자 실측(admin_operator_activity_logs 전수 SELECT DISTINCT) — target_kind
# 19종 중 7종, action 65종 중 30종이 이 두 표에서 누락돼 있었다(최근 500건 응답의 64%가
# 영문 원본 그대로 노출). `.get(key, key)` 폴백이 에러를 안 내 2026-07-26부터 3주간
# 조용히 틀렸다. **이 표는 완전한 사전이 아니다** — 새 kind·action이 코드에 추가되면
# 여기도 늘려야 한다. `list_activity_logs`가 매 응답에 실어 보내는 `unmapped_kinds`·
# `unmapped_actions`(최근 페이지 안에서 사전에 없는 값)가 그 순간을 알린다 — 조용히
# 넘어가지 않는다.
KIND_LABELS = {"order": "주문", "refund": "환불", "settlement": "정산",
               "price_file": "단가표", "product_review": "검수·매입", "product": "상품",
               "member_review": "후기", "member": "회원", "stock": "재고", "sourcing": "매입 견적", "ops": "운영 전환",
               "category": "카테고리",
               # 2026-08-15 추가분 — 각 kind가 실제로 어디서 쓰이는지 `_log(..., kind=...)`
               # 호출부를 코드로 직접 확인했다(추측 금지 — MAKER-CHECKLIST §4).
               "operator": "운영자",             # admin_operators.py·admin_profile.py — 운영자 계정 관리
               "engine": "엔진",                 # admin_usage_floors.py — 추천 엔진의 용도 하한 규칙
               "price": "가격",                  # admin_categories.py·admin_engine_rules.py·admin_reprice.py — 마진·판매가 정책
               "supplier": "공급처",             # admin_suppliers.py
               "ops_assistant_faq": "운영 도우미 FAQ",  # admin_ops_assistant.py
               "ai_task": "AI 작업",             # admin_ai_tasks.py
               "ai_integration": "AI 연동"}      # admin_ai_integration.py
ACTION_LABELS = {
    "order_advance": "주문 처리", "order_advance_undo": "주문 처리 되돌림",
    "refund_advance": "환불 처리", "refund_advance_undo": "환불 처리 되돌림",
    "settlement_close": "정산 마감", "settlement_close_undo": "정산 마감 되돌림",
    "price_import_apply": "단가표 반영", "price_import_undo": "단가표 반영 되돌림",
    "review_process": "검수 처리", "review_bulk_confirm": "검수 일괄 확정",
    "review_undo": "검수 되돌림",
    # A-108(2026-08-23) — 시세(market_price) 자동 승인. 사람이 누른 review_process와
    # 구분되는 별개 action(operator_id=NULL, api/admin_reviews.py auto_approve_market_price
    # 참조). 사전에 없으면 원문 "review_auto_approve"가 그대로 노출된다(위 _untranslated
    # 주석 그대로) — 그래서 다른 action과 마찬가지로 여기 올린다.
    "review_auto_approve": "시세 자동 승인",
    "sourcing_link": "매입 모델 연결", "sourcing_unlink": "매입 모델 연결 해제",
    "product_register": "상품 등록",
    "member_review_moderate": "후기 처리", "member_review_undo": "후기 처리 되돌림",
    "member_map_request": "매핑 요청 발송", "member_map_request_undo": "매핑 요청 되돌림",
    "price_review_decide": "가격 검토 처리",
    "stock_inbound": "재고 입고", "stock_inbound_undo": "재고 입고 되돌림",
    "sourcing_request": "견적 요청", "sourcing_reply": "회신 기록", "sourcing_confirm": "매입 확정",
    "ops_change": "운영 모드 전환", "ops_change_undo": "운영 모드 되돌림",
    # 2026-08-15 추가분 — DB 전수 실측(action별 건수)으로 찾은 누락. 각 action의 뜻은
    # 실제 호출부(api/*.py)를 읽어 확인했다 — 뜻을 모르는 코드는 옮기지 않았다(있으면
    # 보고에 남긴다).
    # kind="operator" (admin_operators.py · admin_profile.py)
    "operator_self_update": "운영자 정보 수정", "operator_approve": "운영자 승인",
    "operator_role": "운영자 권한 변경", "operator_suspend": "운영자 정지",
    "operator_email_fix": "운영자 이메일 정정",
    "session_revoke_others": "다른 기기에서 로그아웃",  # admin_profile.py 화면 버튼 문구 그대로
    # kind="product" (admin_products.py · grades.py)
    "product_edit": "상품 수정", "product_edit_undo": "상품 수정 되돌림",
    "spec_edit": "사양 수정", "spec_edit_undo": "사양 수정 되돌림",
    "part_type_change": "분류 변경", "part_type_change_undo": "분류 변경 되돌림",
    "product_delete": "상품 삭제",
    "product_merge": "중복 상품 편입", "product_merge_undo": "중복 상품 편입 되돌림",
    "grade_set": "부품 등급 저장", "grade_clear": "부품 등급 삭제",
    # kind="supplier" (admin_suppliers.py) · 상품별 매입가(admin_products.py)
    "supplier_create": "공급처 등록", "supplier_update": "공급처 수정",
    "supplier_price": "공급처 매입가 등록", "supplier_price_remove": "공급처 매입가 삭제",
    # kind="price" (admin_engine_rules.py) · kind="engine" (admin_usage_floors.py)
    "pricing_settings": "마진 정책 저장", "usage_floor": "용도 하한 변경",
    # kind="product" (사양 항목 신설, admin_spec_fields.py — ADM-PRD-050)
    "spec_field_add": "사양 항목 추가",
    # kind="ai_task" (admin_ai_tasks.py) · kind="ai_integration" (admin_ai_integration.py)
    "ai_task_create": "AI 작업 배정 생성", "ai_task_delete": "AI 작업 배정 삭제",
    "ai_integration_limit_update": "AI 연동 한도 수정",
    # kind="ops_assistant_faq" (admin_ops_assistant.py) — edit는 DB에 아직 0건이지만
    # 코드에 있는 액션이라 같은 화면의 add·delete와 함께 미리 채운다(조기 발견 취지와
    # 정확히 같은 이유로, 발생 전에 옮겨 둔다).
    "ops_assistant_faq_add": "운영 도우미 FAQ 추가",
    "ops_assistant_faq_edit": "운영 도우미 FAQ 수정",
    "ops_assistant_faq_delete": "운영 도우미 FAQ 삭제",
    # kind="product" (admin_ui_sale_price.py — ADM-PRC-060 판매가 관리). 2026-08-15
    # 확인자 결함 보고: 이 두 액션만 "번역 미비" 같은 표식 없이 원문 코드가 그대로
    # 노출되고 있었다(가격 이력 화면과 달리 여기는 미번역 방어 장치가 없다 — 그래서
    # 라벨을 빠뜨리면 조용히 코드가 샌다). 판매가 관리 화면이 실제 값을 바꾸는 유일한
    # 두 액션이라 감사 추적에서 특히 눈에 띈다. 실측(log_id 7306·7374)으로 detail 구조
    # (before/after/handoff_no, sale_price)를 확인하고 아래 _summary()에도 반영했다.
    "sale_price_match": "판매가 몰 값 맞춤", "sale_price_lock": "판매가 잠금",
}
PRICE_REVIEW_SUB = {"approve": "제안가 승인", "keep": "판매가 유지(제안 차단)",
                    "manual": "직접 수정"}
MODERATE_SUB = {"hide": "숨김 처리", "keep": "게시 유지", "restore": "게시 복원",
                "cite_on": "S2 근거 인용", "cite_off": "S2 근거 인용 해제"}
ORDER_SUB = {"assemble": "조립 시작", "ship": "출고", "done": "배송 완료"}
REFUND_SUB = {"review": "검토 시작", "approve": "승인", "complete": "완료", "reject": "반려"}
REVIEW_MODE = {"approve": "승인", "manual": "직접 수정", "reject": "보류"}


def _untranslated(raw: str | None) -> bool:
    """영문(ASCII) 코드인데 사전에 없으면 화면에 원문이 그대로 노출된다 — 번역 누락.

    한국어로 직접 기록된 action(예: "카테고리 추가")은 그 자체로 이미 정상 표시되므로
    번역 누락이 아니다(파일 상단 주석 참고 — 도메인 코드가 action 컬럼에 한국어 문자열을
    직접 쓰는 경로가 있다). 그래서 ASCII인데 사전에 없는 것만 "누락"으로 잡는다.
    """
    return bool(raw) and raw.isascii()


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
    if action == "member_review_moderate":
        a = d.get("after", {})
        return f"{MODERATE_SUB.get(d.get('action'), d.get('action', ''))} · 후기 #{d.get('review_id')} → {a.get('status')}"
    if action == "stock_inbound":
        b = (d.get("before") or {}).get("stock_qty", 0)
        sub = "실사 조정" if d.get("why") == "adjust" else "매입 입고"
        return f"{d.get('sku')} · {sub} +{d.get('qty')} · 재고 {b} → {b + (d.get('qty') or 0)}"
    if action == "price_review_decide":
        sub = PRICE_REVIEW_SUB.get(d.get("action"), d.get("action", ""))
        p = d.get("price")
        return f"{d.get('sku')} · {sub}" + (f" {p:,}원" if p else "")
    if action == "sourcing_request":
        return f"{len(d.get('quotes', []))}개 공급처에 견적 요청 — {d.get('sku', '')}"
    if action == "sourcing_reply":
        return f"회신가 {d.get('price', 0):,}원 기록 (견적 #{d.get('quote_id')})"
    if action == "sourcing_confirm":
        b = (d.get("before") or {}).get("cost_price")
        return (f"매입 확정 {d.get('price', 0):,}원"
                + (f" (이전 {b:,}원)" if b else " (신규 공급처)"))
    if action == "member_map_request":
        return f"{d.get('nickname')}님에게 쇼핑몰 계정 매핑 요청 발송 — 동의 대기"
    if action == "sale_price_match":
        # detail 구조(실측 log_id 7306, 상품 119253): before/after 각각 sale_price·locked,
        # handoff_no. old==new(값은 그대로인데 잠금만 해제된 경우 — admin_ui_sale_price.py
        # 참조)도 "유지"로 정직하게 구분한다. "before"/"after"만 있고 값 자체는 없는 옛
        # 형태의 detail이 와도 죽지 않게 .get()으로만 읽는다.
        b, a = d.get("before") or {}, d.get("after") or {}
        old, new = b.get("sale_price"), a.get("sale_price")
        if old is not None and new is not None and old != new:
            chg = f"판매가 {old:,}원 → {new:,}원"
        elif new is not None:
            chg = f"판매가 {new:,}원 유지"
        else:
            chg = "몰 값 맞춤"
        tail = " · 잠금 해제" if b.get("locked") else ""
        ho = f" (인계 {d.get('handoff_no')})" if d.get("handoff_no") else ""
        return f"{d.get('sku')} · {chg}{tail}{ho}"
    if action == "sale_price_lock":
        # detail 구조(실측 log_id 7374, 상품 87519): sale_price 하나뿐(before/after 아님).
        p = d.get("sale_price")
        price_txt = f"{p:,}원" if p is not None else "값 없음"
        return f"{d.get('sku')} · 판매가 {price_txt} 잠금"
    if action == "review_auto_approve":
        # detail 구조(api/admin_reviews.py auto_approve_market_price): mode·auto·review_id·
        # field(항상 market_price)·value(str)·pct_change(float|None)·threshold_pct(float)·
        # before. "무엇이 왜 자동 승인됐는지"가 한 줄에 다 보여야 한다(지시서 요구) — 값 +
        # 변동률 + 기준을 함께 적는다. pct_change는 auto_approved=True일 때는 항상 값이
        # 있지만(market_auto_approve_decision — ok=True면 pct는 None이 아니다) 방어적으로
        # None도 다룬다.
        pct = d.get("pct_change")
        thr = d.get("threshold_pct")
        val = d.get("value")
        try:
            val_txt = f"{int(val):,}원"
        except (TypeError, ValueError):
            val_txt = str(val) if val is not None else "값 없음"
        pct_txt = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else "산출 불가"
        thr_txt = f"{thr:g}%" if isinstance(thr, (int, float)) else "-"
        return f"시세 자동 승인 · market_price {val_txt} (변동 {pct_txt}, 기준 {thr_txt})"
    if action.endswith("_undo") or d.get("ref_log_id"):
        return f"원 기록 #{d.get('ref_log_id')} 되돌림"
    return action  # 미지의 action — 원문 폴백


@router.get("/activity-logs")
def list_activity_logs(date_from: str | None = None, date_to: str | None = None):
    # 기간은 **서울 날짜**로 받는다 — 변환은 `timeutil` 하나가 한다(9시간 함정).
    try:
        _lo, _hi = kst_day_range(date_from, date_to)
    except ValueError as e:
        raise HTTPException(400, str(e) or "기간 형식은 YYYY-MM-DD 입니다")
    _p = {}
    if _lo is not None:
        _p["_dt_lo"] = _lo
    if _hi is not None:
        _p["_dt_hi"] = _hi
    _RANGE = range_sql("l.created_at", _lo, _hi)
    with engine.connect() as conn:
        # **합계도 같은 조건으로 센다.** 목록만 거르고 합계를 그대로 두면 화면이
        # "전체 N건"이라 말하면서 M건을 보여준다 — 이 프로젝트가 이미 겪은 형태다.
        total = conn.execute(text(
            "SELECT COUNT(*) FROM admin_operator_activity_logs l"
            " WHERE TRUE" + _RANGE), _p).scalar_one()
        rows = conn.execute(text(
            "SELECT l.log_id, l.action, l.target_kind, l.target_id, l.detail, l.created_at,"
            # A-108(2026-08-23) — operator_id가 NULL인 행은 "운영자를 못 찾음"이 아니라
            # "사람이 안 했다"는 뜻이다(api/admin_reviews.py _log(auto=True) — 자동 승인
            # 전용, 슬라이스 37부터 사람 행은 항상 operator_id가 채워진다. 그 전 과거
            # 행은 시드 운영자 id로 고정돼 있어 NULL이 아니다 — admin_reviews.py 주석
            # 참조). COALESCE만 쓰면 둘 다 '—'로 뭉개져 "자동"임이 화면에서 사라진다.
            " CASE WHEN l.operator_id IS NULL THEN '자동' ELSE COALESCE(o.name, '—') END AS operator,"
            # action 이름을 보지 않는다 — ref_log_id 역참조 EXISTS 하나가 판정 전부다(근거는
            # 파일 상단 주석). action LIKE로 좁히면 한국어로 지어진 되돌림·"되돌림"이라는
            # 낱말이 없는 되돌림류(sourcing_unlink 등)를 놓친다.
            " EXISTS(SELECT 1 FROM admin_operator_activity_logs u"
            "        WHERE u.detail->>'ref_log_id' = CAST(l.log_id AS TEXT)) AS undone"
            " FROM admin_operator_activity_logs l"
            " LEFT JOIN admin_operators o USING (operator_id)"
            " WHERE TRUE" + _RANGE +
            " ORDER BY l.log_id DESC LIMIT :lim"), {"lim": LIMIT, **_p}).mappings().all()
    # 2026-08-15 추가 — 이 페이지(최근 LIMIT건) 안에서 KIND_LABELS·ACTION_LABELS에
    # 없어 원문이 그대로 노출되는 값. 비어 있으면 지금 보이는 페이지는 전부 번역됐다는
    # 뜻이다(전체 DB 보장은 아니다 — 페이지 밖 값은 이 필드로 알 수 없다). 기존 필드는
    # 그대로 두고 **추가만** 한다 — 다음에 새 kind·action이 조용히 영문으로 새는 것을
    # 이 필드로 알아챈다(폴백이 에러를 안 내 3주간 몰랐던 문제의 재발 방지).
    unmapped_kinds = sorted({r["target_kind"] for r in rows
                             if r["target_kind"] not in KIND_LABELS and _untranslated(r["target_kind"])})
    unmapped_actions = sorted({r["action"] for r in rows
                               if r["action"] not in ACTION_LABELS and _untranslated(r["action"])})
    return {"total": total, "limit": LIMIT, "items": [{
        "log_id": r["log_id"],
        "at": iso(r["created_at"]),
        "operator": r["operator"],
        "kind": r["target_kind"],
        "kind_label": KIND_LABELS.get(r["target_kind"], r["target_kind"]),
        "action_label": ACTION_LABELS.get(r["action"], r["action"]),
        # 이 행 자체가 되돌림 행인가 — 같은 근거(자기 detail의 ref_log_id 보유)로 본다.
        # action이 "_undo"로 끝나는지로 보면 위 undone과 같은 이유로 한국어 되돌림 action을
        # 놓친다(SQL 없이 이미 읽어 온 detail로 판정 — 별도 쿼리가 필요 없다).
        "is_undo": bool((r["detail"] or {}).get("ref_log_id")),
        "target": r["target_id"],
        "summary": _summary(r["action"], r["detail"]),
        "undone": r["undone"],
    } for r in rows], "unmapped_kinds": unmapped_kinds, "unmapped_actions": unmapped_actions}
