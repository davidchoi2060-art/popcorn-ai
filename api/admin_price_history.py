"""ADM-PRC-030 가격 이력 — 판매가·매입가 변동 원장 조회 (읽기 전용).

원장 원칙: 가격 변경은 삭제하지 않는다 — 되돌림도 역방향 이력 행으로 남는다(슬라이스 3부터).
reason 어휘(ERD §3.4·§6.3): csv / sourcing / margin_policy / manual / price_import(+_undo).
⚠ "manual_match"는 위 ERD 어휘 밖의 신규 사유다(2026-08-15, admin_ui_sale_price.py의
판매가 관리 화면 — 몰 값 맞춤). ERD 문서(정본, 이 파일 담당 밖)는 아직 안 늘었으니
새 사유를 또 추가할 땐 REASON_KO만 보지 말고 이 docstring과 실 DB(SELECT DISTINCT
reason)를 같이 대조한다 — margin_policy_undo가 그렇게 3주간 빠졌었다(아래 참조).
정직 표기 2건:
  ① **공급처별 매입가 분리 불가** — product_price_history에 supplier 구분 컬럼이 없다.
     purchase 이력은 공급처 간 재판정 결과(최저가)이므로 차트는 판매가·매입가 2선만 그린다
     (목업의 공급처별 2선은 연출 — 컬럼화 이관).
  ② **6주 고정 축 아님** — 실데이터 구간이 짧아 이력 전체를 시간축에 그린다(구간 필터 이관).
ref_id는 사유별 의미가 다르다(price_import=file_id, margin_policy·manual=활동로그 log_id,
sourcing=sourcing_id) — 화면 링크도 사유별로 분기한다.
⚠ margin_policy·margin_policy_undo는 그 "활동로그 log_id"가 **항상 있는 게 아니다** —
개별 승인(admin_price_review.py)만 채우고, 대량 재산정(admin_reprice.py `/reprice/apply`·
`/reprice/undo`)은 INSERT 컬럼 목록에 ref_id가 아예 없어 NULL이다(2026-08-15 계약자 실측
결함 보고 반영 — 아래 REASON_KO_BULK 참조). ref_id 유무가 "개별 승인 vs 대량 재산정"을
가르는 유일한 신호라, 이 둘만 라벨을 ref_id로 한 번 더 가른다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .timeutil import iso, kst_day_range, range_sql
from .db import engine

router = APIRouter(prefix="/api/admin")

# ⚠ 2026-08-15 점검자 실측(product_price_history 전수 SELECT reason, count(*)) —
# "margin_policy_undo"가 빠져 있었다: 28,993행 중 14,478행(49.9%)이 이 코드라, 화면
# 절반이 영문 원본을 그대로 보여주고 있었다. 링크는 원본과 같은 화면(price-review.html)
# 으로 보낸다 — 되돌림도 같은 화면에서 다시 승인/직접수정할 수 있어야 하므로.
#
# ⚠⚠ 2026-08-15 재확인(같은 날, 계약자가 새 결함으로 잡음) — 바로 위 문단이 이미 그
# 혼동의 일부였다: "margin_policy는 admin_reprice.py 판매가 재산정에서 씀"이라고만
# 적었는데, 실제로는 **두 화면이 같은 reason 문자열을 함께 쓴다**.
#   개별 승인   admin_price_review.py:102 `_reprice(conn, pc, fee, margin,
#               "margin_policy", log_id)` -> ref_id = 그 결정의 활동로그 log_id(실값 —
#               admin_price_import._reprice가 INSERT마다 ref_id를 채운다. 168-191행)
#   대량 재산정  admin_reprice.py `/reprice/apply`(218-222행) · `/reprice/undo`(279-283행)
#               -> INSERT 컬럼 목록 자체에 ref_id가 없다(코드 확인) -> 항상 NULL.
#               (이 두 쓰기 엔드포인트는 지금 admin2 어느 화면에서도 호출되지 않는다 —
#               `/admin2/margin-policy`가 같은 재산정 기능을 쓰지만 `/reprice/preview`
#               (읽기 전용 미리보기)만 부른다. 기존 14,478건이 어떻게 쌓였는지는
#               이 화면의 담당 범위 밖이라 더 캐지 않았다 — admin_reprice.py는 읽기만
#               하기로 했다)
# 실측(전수, 2026-08-15): margin_policy 14,480건 중 ref_id NOT NULL **2건**(개별 승인) ·
# NULL 14,478건(대량 재산정). margin_policy_undo는 14,478건 **전량** ref_id NULL(대량
# 되돌림 — 개별 승인의 단건 되돌림 경로는 아직 없다). 상품 20489102로 재현:
# history_id 34·35(ref_id 81·82, 개별) · 6995·21480(ref_id NULL, 대량) ·
# 14234·28719(margin_policy_undo, ref_id NULL, 대량 되돌림).
# ref_id 유무로 라벨을 가른다 — 안 그러면 대량 재산정 14,478건(전체 이력의 49.9%)을
# "가격 검토 승인"(개별 운영자가 하나하나 판단했다는 뜻)이라 표시해, 원장이 누가 왜
# 이 값을 정했는지를 뒤바꿔 보여준다.
#
# ⚠⚠⚠ 2026-08-15 세 번째 재확인(같은 날, 확인자 실측) — "manual_match"가 이 표에
# 빠져 있었다. admin_ui_sale_price.py의 POST /api/admin/sale-price/{code}/match가
# product_price_history에 reason='manual_match'로 쓰는데(실측: 상품 119253,
# history_id 28995, ref_id 7306 — old_price 853,200 -> new_price 904,700) 여기 없어서
# 위 "번역 미비" 방어 장치(§25-51행 주석)가 그대로 작동해 원문 코드가 노출됐다 —
# 장치는 설계대로 동작한 것이고(3주간 조용히 틀렸던 margin_policy_undo 사고의 재발
# 방지용) 결함은 이 표에 항목이 없다는 것뿐이다. 라벨("몰 값 맞춤")은
# admin_ui_sale_price.py:321의 로컬 REASON_KO(그 화면 서랍의 이력 표시용, 별도 파일 —
# "화면 하나 = 파일 하나" 규약이라 공유 import하지 않는다)와 문구를 맞췄다 — 같은
# 사유를 두 화면이 다르게 부르면 그것도 결함이라 판단했다.
# target_path는 None: 이 사유의 출처 화면은 /admin2/sale-price인데 admin_nav.py에
# 아직 안 걸려 있다(실측: NAV href 목록에 없음 — 128행이 href=None인 채 "몰값·우리값·
# 낡은값 구분 필요"로 보류 중). admin_ui_price_history.py의 REASON_TARGETS와 같은
# "경로 없으면 None, 화면이 생기고 NAV에 걸리면 그때 채운다" 원칙을 따른다 — 다만 이
# 표는 그 파일처럼 매 요청 NAV를 다시 훑어 자동 판정하는 로직이 없다(그 로직은
# admin_ui_price_history.py 소관이라 복제하지 않는다). 그래서 여기 값은 정적이고,
# NAV가 나중에 연결돼도 이 파일을 다시 실측해 고쳐야 한다 — 자동으로는 안 바뀐다.
REASON_KO = {
    "price_import": ("단가표 반영", "price-import.html"),
    "price_import_undo": ("단가표 반영 되돌림", "price-import.html"),
    "margin_policy": ("가격 검토 승인", "price-review.html"),           # ref_id 있을 때만 — _reason_label() 참조
    "margin_policy_undo": ("가격 검토 승인 되돌림", "price-review.html"),  # 〃
    "manual": ("운영자 직접 수정", "activity-logs.html"),
    "manual_match": ("몰 값 맞춤", None),  # 판매가 관리(/admin2/sale-price) — NAV 미연결, 위 주석 참조
    "sourcing": ("매입 확정", "sourcing.html"),
    "csv": ("일괄 등록", "csv-jobs.html"),
}
# margin_policy(_undo)인데 ref_id가 NULL(대량 재산정)일 때만 쓰는 예외 라벨.
# REASON_KO와 같은 dict에 욱여넣지 않는다 — REASON_KO의 키는 "이 reason 코드가 무엇을
# 뜻하는가"이고, 이건 "그중 ref_id가 없는 경우엔 다른 말을 써야 한다"는 조건부 예외라
# 성격이 다르다(섞으면 다음 사람이 "reason만 보고 찾으면 된다"고 오해한다).
REASON_KO_BULK = {
    "margin_policy": "대량 재산정",
    "margin_policy_undo": "대량 재산정 되돌림",
}
FIELD_KO = {"sale": "판매가", "purchase": "매입가"}


def _reason_label(reason: str | None, ref_id: int | None) -> str:
    """사유 코드 -> 한글 라벨. margin_policy·margin_policy_undo만 ref_id로 한 번 더
    가른다(위 REASON_KO_BULK 설명 참조) — 나머지 5종은 REASON_KO 그대로 쓴다."""
    if reason in REASON_KO_BULK and ref_id is None:
        return REASON_KO_BULK[reason]
    return REASON_KO.get(reason, (reason, "activity-logs.html"))[0]


@router.get("/price-history")
def price_history(product_code: int | None = None,
                  date_from: str | None = None, date_to: str | None = None):
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
    _RANGE = range_sql("h.changed_at", _lo, _hi)
    with engine.connect() as conn:
        prods = conn.execute(text(
            "SELECT h.product_code, p.sku, p.product_name, COUNT(*) AS cnt,"
            " MAX(h.changed_at) AS last_at"
            " FROM product_price_history h JOIN products p USING (product_code)"
            " WHERE TRUE" + _RANGE +
            # 좌측 상품 목록도 같은 기간을 본다 — 안 그러면 "이 기간에 이력이 있는 상품"이
            # 아니라 전체가 뜨고, 골라 들어가면 오른쪽이 비어 있다.
            " GROUP BY h.product_code, p.sku, p.product_name"
            " ORDER BY cnt DESC, last_at DESC"), _p).mappings().all()
        if not prods:
            return {"products": [], "items": [], "series": {"sale": [], "purchase": []},
                    "product": None, "note": "가격 이력이 아직 없습니다."}
        pc = product_code or prods[0]["product_code"]
        if not any(p["product_code"] == pc for p in prods):
            raise HTTPException(404, "해당 상품의 가격 이력이 없습니다")
        rows = conn.execute(text(
            "SELECT h.history_id, h.field, h.old_price, h.new_price, h.reason, h.ref_id,"
            " h.changed_at, h.supplier_id, s.name AS supplier"
            " FROM product_price_history h LEFT JOIN suppliers s USING (supplier_id)"
            " WHERE h.product_code=:pc" + _RANGE +
            " ORDER BY h.changed_at, h.history_id"),
            {"pc": pc, **_p}).mappings().all()
        cur = conn.execute(text(
            "SELECT sku, product_name, purchase_price, sale_price FROM products"
            " WHERE product_code=:pc"), {"pc": pc}).mappings().one()

    # 판매가 1선 + 매입가는 **공급처별 분리**(0004에서 supplier_id 추가 — 출처 미기록분은 '기록 없음')
    series = {"sale": [], "purchase": []}
    by_supplier: dict = {}
    for r in rows:
        if r["field"] not in series or r["new_price"] is None:
            continue
        pt = {"at": iso(r["changed_at"]), "price": r["new_price"]}
        series[r["field"]].append(pt)
        if r["field"] == "purchase":
            key = r["supplier"] or "출처 미기록"
            by_supplier.setdefault(key, []).append(pt)
    items = [{
        "id": r["history_id"], "at": iso(r["changed_at"]),
        "field": r["field"], "field_label": FIELD_KO.get(r["field"], r["field"]),
        "old": r["old_price"], "new": r["new_price"],
        "delta": (r["new_price"] - r["old_price"]) if (r["old_price"] is not None and r["new_price"] is not None) else None,
        "reason": r["reason"],
        "reason_label": _reason_label(r["reason"], r["ref_id"]),
        "reason_link": REASON_KO.get(r["reason"], (r["reason"], "activity-logs.html"))[1],
        "ref_id": r["ref_id"], "supplier": r["supplier"],
    } for r in reversed(rows)]   # 최신 우선
    # 2026-08-15 추가 — 이 상품의 이력 안에서 REASON_KO에 없어 원문이 그대로 노출되는
    # reason. 빈 배열이면 지금 보이는 이력은 전부 번역됐다는 뜻이다(다른 상품·기간의
    # reason까지 보장하지는 않는다). 기존 필드는 그대로 두고 **추가만** 한다 — 새 reason이
    # 조용히 영문으로 새는 것을 다음에는 이 필드로 알아챈다(margin_policy_undo가 49.9%를
    # 3주간 조용히 틀리게 만든 것과 같은 패턴의 재발 방지).
    unmapped_reasons = sorted({r["reason"] for r in rows
                               if r["reason"] and r["reason"] not in REASON_KO})
    return {
        "products": [{"product_code": p["product_code"], "sku": p["sku"],
                      "name": p["product_name"], "count": p["cnt"]} for p in prods],
        "product": {"product_code": pc, "sku": cur["sku"], "name": cur["product_name"],
                    "purchase": cur["purchase_price"], "sale": cur["sale_price"]},
        "items": items, "series": series,
        "by_supplier": [{"supplier": k, "points": v} for k, v in by_supplier.items()],
        "note": ("매입가는 공급처별로 나눠 그립니다(마이그레이션 0004에서 이력에 공급처를 남김)."
                 " '출처 미기록'은 공급처 구분이 없던 시점의 이력입니다 —"
                 " 복수 공급처 상품은 추정하지 않고 그대로 둡니다 ·"
                 " 구간 필터는 준비 중이며 현재는 이력 전체를 시간축에 그립니다 ·"
                 " 되돌림도 역방향 행으로 남습니다."),
        "unmapped_reasons": unmapped_reasons,
    }
