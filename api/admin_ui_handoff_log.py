# -*- coding: utf-8 -*-
"""인계 기록(ADM-HND-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery,
`api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

**조회 전용.** 계약 `docs/design/spec-handoff-log.md`(사장님 확정 **1a** "인계 건 축",
2026-08-15. 1b "세션 축"은 탈락). 정의서 `docs/design/req/req-handoff-log.md`. 원문
(Claude Design)은 하네스만 연다 — 이 화면은 계약 요약 텍스트만으로 지었다.

■ 이 화면의 존재 이유 — 「인계」는 「구매」가 아니다
  `api/handoff.py`를 직접 읽어 확인했다(담당 파일 밖, 읽기만): `create_handoff()`가
  돌려주는 `cart`는 "담을 목록"이고 `cart_url`은 몰의 **장바구니 목록 페이지** URL
  (`mall.BASE + "/shop/order_basket_list.html"`)일 뿐이다. 이 서버가 그 상품을 실제로
  몰 장바구니에 담는 요청(`POST .../order_basket_action.php` 같은 것)을 보내는 코드는
  `handoff.py` 전체에 **없다** — `POST`를 부르는 곳은 없고, 응답을 만들어 돌려줄
  뿐이다. **계약의 전제("담는 요청을 어디에서도 보내지 않는다")가 코드로도 사실이다.**
  그래서 상단 배너·행 비고·서랍 머리 밑, 세 곳에 같은 사실을 반복해 밝힌다.

■ 실측 (2026-08-15, `handoffs`·`handoff_items` 직접 SELECT, 읽기 전용)
  인계 3건(HO-1001·HO-1002·HO-1003) · 라인 27개(부품 24·조립비 3·주변기기 0).
  `status`는 3건 전부 `'인계'`(DISTINCT 결과 1행 — "상태는 사실상 하나뿐"이 실측으로도
  참이다. 코드에도 INSERT 시 상수 `'인계'` 1회뿐, `handoff.py` L138). `mall_status`
  분포: 가격변동 13 · 확인됨 12 · 확인못함 2(=27) — 계약의 "27라인 중 13개(48.1%)"와
  일치한다.

  **「몰 0원」≠「확인 못함」을 실제 데이터에서 확인했다** — 같은 두 데모 상품
  (RAM `20483003`·SSD `20486102`)이 `HO-1001`에서는 `price_mall=0`(`mall_status`
  `'가격변동'`, 팔 수 없는 값을 **읽었다**)인데, 3분 46초 뒤 같은 세션의 `HO-1002`
  에서는 `price_mall=NULL`(`mall_status` `'확인못함'`, **아예 못 읽었다**) — 실시간
  스크래핑의 비결정성이 같은 상품·비슷한 시각에도 두 값을 만든다. 화면은 이 둘을
  절대 같은 "0"으로 뭉개지 않는다(`mall_text`: "못 읽음" vs "0원").

  세션 `4247`이 `HO-1001`(12:56:58)·`HO-1002`(13:00:44)로 **2회 인계**됐고
  `user_id`가 473→474로 다르다 — "세션 1개=인계 1건"을 전제하지 않는다(아래
  `session_group`, 원인은 단정하지 않고 사실만 나열).

■★ 인증 구멍을 스스로 메웠다 — `api/auth.py`를 직접 읽어 확인(2026-08-15)
  `auth_middleware`(`auth.py` L145-150)는 `path.startswith("/api/admin/")`인 요청만
  세션을 검사한다. `/admin2/*` 페이지 라우트(이 파일이 등록하는 것 포함)는 그 미들웨어
  **밖**이다 — `reviews.py`·`swap_click_logs.py`도 그래서 페이지 셸 자체는 원래
  로그인 없이 열린다(그 화면들의 실 데이터는 `/api/admin/reviews`·`/api/admin/
  swap-logs`처럼 진짜 `/api/admin/*` 아래 있어 미들웨어가 막는다). 이 화면은 담당
  파일이 이 두 개뿐이라 데이터 API를 `/api/admin/*`에 새로 만들 수 없고(그러려면
  세 번째 파일이 필요하다 — `main.py`의 자동 등록은 모듈당 `router` 속성 하나만
  줍는다, `main.py` L60-71 실측), 같은 라우터(prefix `/admin2`) 안에 데이터 엔드포인트
  `/admin2/handoff-log/data`를 둘 수밖에 없다. **그러면 미들웨어가 이 경로를 보지
  않으므로 조회 등급 확인 없이 아무나 인계 내역(가격·세션·방문자 키)을 볼 수 있게
  된다.** 그래서 이 엔드포인트 **자신이 직접** `api.auth.resolve_session` +
  `COOKIE`를 불러 세션을 확인한다(아래 `handoff_log_data()`). 페이지 셸(`handoff_log()`)
  은 기존 두 화면과 동일하게 그대로 열어 둔다 — 빈 골격만 있고 실데이터가 없어
  열려 있어도 새는 것이 없다. **실데이터가 나가는 경로만 게이트를 세운다.**

■ 세션 이동 링크·쇼핑몰 동기화 링크 — «경로»로 판정한다, 라벨이 아니다
  `api/admin_ui_swap_click_logs.py`가 겪은 사고(라벨 리네임으로 조회가 조용히
  `None`이 된 사건, 2026-08-14)와 같은 기법을 그대로 썼다: 각 화면의 실제 라우트
  선언을 그 파일에서 직접 읽어(`api/admin_ui_consult_sessions.py` L10 `@router.get(
  "/consult-sessions")`, prefix `/admin2` → `/admin2/consult-sessions` · `api/
  admin_ui_mall_sync.py` L410 `@router.get("/mall-sync")` → `/admin2/mall-sync`)
  `NAV_TARGETS`에 경로 문자열로 박아 두고, `admin_nav.NAV`에서 그 경로가 실제로
  `href`로 걸려 있는지만 매 요청 확인한다(라벨은 조회에 전혀 안 쓴다). 실측
  (2026-08-15): 두 화면 다 라우트 코드는 있지만 `admin_nav.py`의 href는 아직
  `None`(신설 표시) — 그래서 지금은 두 링크 다 비활성 + 사유로 뜨는 것이 맞다
  (화면 결함 아님). 하네스가 `admin_nav.py`에 href를 채우면 이 파일은 코드 수정
  없이 다음 요청부터 바로 살아있는 링크를 낸다.

■ 판단한 것 (계약에 명시되지 않아 이 화면이 정한 것)
  ① **데이터 전달 방식** — SSR 한 번에 다 박지 않고, 페이지 셸(가벼움) +
     `/admin2/handoff-log/data`(AJAX) 두 단계로 나눴다. 이유는 위 "인증 구멍"과
     같다 — 셸에 데이터를 박으면 그 구멍이 고스란히 남는다. 또한 `reviews`·
     `swap_click_logs`와 같은 loading/error/body 패턴(재시도 가능한 에러박스)을
     그대로 쓸 수 있다.
  ② **집계(KPI)는 페이지네이션과 무관하게 전체 테이블 기준** — "표본 N"이 현재
     페이지 크기가 아니라 실제 전체를 말해야 한다(계약 "비율·합계에 반드시 표본을
     병기한다").
  ③ **라인 종류 배지** — 계약 §우측서랍이 "부품/조립비/시연용" 셋을 들었는데,
     `item_kind`(부품/조립비/주변기기)와 "시연용"(`products.data_origin='demo'`)은
     **서로 다른 축**이다(하나는 무엇을 넘겼는지, 하나는 어디서 온 상품인지) — 실제로
     `HO-1001`의 데모 라인은 `item_kind='core_part'`다. 그래서 배지를 양자택일로
     만들지 않고 **둘 다** 보여준다(부품/조립비/주변기기 배지 + 데모면 "시연용" 배지
     추가) — 어느 쪽도 감추지 않는 쪽을 택했다.
  ④ **세션 이동 링크 쿼리** — `?session_id=` 를 붙였다. 대상 화면이 지금 그 쿼리를
     읽는지는 확인하지 못했다(그 파일은 담당 밖이라 로직까지 읽지 않았다 — 라우트
     선언만 확인). 못 읽어도 해가 없고(무시될 뿐), 나중에 지원되면 바로 동작한다.
  ⑤ **필터 UI(가격변동만 보기 등)를 만들지 않았다** — `req-handoff-log.md` §⑤엔
     있지만 **확정 계약(spec-handoff-log.md) §구조 1a에는 없다**(`MAKER-CHECKLIST`
     §1 "확정 안만 정본이다"). 정의서는 계약 이전 문서라 계약을 따랐다.
  ⑥ **soldout_cnt는 화면에 안 올렸다** — 계약 §구조 1a 어디에도 없고 실측값이 3건
     전부 0이라(지어낼 것도 없음) API 응답에는 남기되(`raw` 확장 여지) 화면 엘리먼트는
     안 만들었다.
  ⑦ **페이지네이션은 API만 갖추고 페이저 UI는 안 달았다** — 실측 3건뿐이라 지금은
     `limit`(기본 50·최대 200)/`offset` 파라미터와 정직한 `total`만 두고, "다음
     페이지" 버튼은 데이터가 그 규모가 될 때 붙이는 편이 낫다고 판단했다(지금 달면
     "0건"짜리 페이지 버튼을 시험할 방법이 없다). **checker 판단 필요 항목으로 보고.**
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .admin_nav import NAV
from .auth import COOKIE, resolve_session
from .db import engine
from .timeutil import iso as _iso

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

# quote_type(엔진 코드) -> 화면 표시. CLAUDE.md "티어 서열 가성비 ≤ 추천 ≤ 고성능"과
# `api/handoff.py`의 `if body.tier not in ("value", "recommend", "highend")` 그대로.
# 저장소 안에 이 셋의 공용 라벨 사전이 따로 없어(taxonomy.py 등에 없음 실측) 이 화면이
# 직접 든다 — 다른 정본을 복제한 것이 아니라 원래 없던 자리를 채운 것.
TIER_LABELS = {
    "highend": {"label": "고성능형", "cls": "hi"},
    "recommend": {"label": "추천형", "cls": "re"},
    "value": {"label": "가성비형", "cls": "va"},
}

ITEM_KIND_LABELS = {
    "core_part": "부품",
    "assembly_service": "조립비",
    "peripheral": "주변기기",
}

# handoff_items.mall_status — 컬럼 자체는 varchar이고(실측: information_schema, enum 아님),
# `api/handoff.py`가 실제로 쓰는 값은 이 3종뿐(L116-122). 계약이 경고한 그대로
# "4종이 저장되지 않는다"(세부 실패 사유 컬럼이 없다) — 화면은 이 3종만 신뢰한다.
MALL_STATUS_LABELS = {
    "확인됨": {"mark": "✓", "text": "확인됨", "cls": "ok"},        # ✓
    "가격변동": {"mark": "▲", "text": "가격변동", "cls": "chg"},    # ▲
    "확인못함": {"mark": "—", "text": "확인 못함", "cls": "unk"},   # —
}

# 세션 이동 · 쇼핑몰 동기화 링크 대상 — 경로로 조회한다(라벨 아님). 근거는 위 모듈
# docstring "세션 이동 링크" 절 — 각 화면의 admin_ui_*.py에서 @router.get(...)을
# 직접 읽어 확인한 경로 문자열이다(2026-08-15).
NAV_TARGETS = {
    "consult_sessions": {"display": "견적 상담 기록", "path": "/admin2/consult-sessions"},
    "mall_sync": {"display": "쇼핑몰 동기화", "path": "/admin2/mall-sync"},
}


def _nav_links() -> dict:
    """admin_nav.NAV를 "그 경로가 실제로 링크돼 있는가"로만 훑는다(읽기만, 고치지 않는다)."""
    live = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    out = {}
    for key, t in NAV_TARGETS.items():
        ok = t["path"] in live
        out[key] = {
            "label": t["display"], "path": t["path"], "available": ok,
            "reason": None if ok else "아직 admin2 메뉴에 연결되지 않았습니다 — 신설 예정",
        }
    return out


def _tier(quote_type):
    t = TIER_LABELS.get(quote_type)
    if t:
        return {"code": quote_type, "label": t["label"], "cls": t["cls"]}
    return {"code": quote_type, "label": quote_type or "미상", "cls": "unk"}


def _load(limit: int, offset: int) -> dict:
    """읽기 전용 집계 + 페이지. 집계(KPI)는 전체 테이블 기준, `rows`만 페이지 적용."""
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM handoffs")).scalar() or 0
        period = conn.execute(text(
            "SELECT MIN(created_at), MAX(created_at) FROM handoffs")).first()
        status_rows = [r[0] for r in conn.execute(text("SELECT DISTINCT status FROM handoffs"))]

        kind_rows = conn.execute(text(
            "SELECT item_kind, COUNT(*) FROM handoff_items GROUP BY item_kind")).all()
        line_kinds = {k: 0 for k in ITEM_KIND_LABELS}
        line_total = 0
        for k, n in kind_rows:
            line_kinds[k] = n
            line_total += n

        mismatch_n = conn.execute(text(
            "SELECT COUNT(*) FROM handoff_items WHERE mall_status='가격변동'")).scalar() or 0
        quoted_sum = conn.execute(text(
            "SELECT COALESCE(SUM(total_quoted),0) FROM handoffs")).scalar() or 0

        # 세션 다건 인계 — 전체 테이블 기준(§"세션 1개=인계 1건 전제 금지").
        sess_rows = conn.execute(text(
            "SELECT session_id, array_agg(handoff_no ORDER BY created_at) nos,"
            " array_agg(user_id ORDER BY created_at) uids,"
            " array_agg(created_at ORDER BY created_at) ts"
            " FROM handoffs WHERE session_id IS NOT NULL"
            " GROUP BY session_id HAVING COUNT(*) > 1")).mappings().all()
        sess_multi = {}
        for r in sess_rows:
            ts = list(r["ts"])
            gaps = [round((b - a).total_seconds() / 60.0, 1) for a, b in zip(ts, ts[1:])]
            sess_multi[int(r["session_id"])] = {
                "handoffs": list(r["nos"]), "user_ids": [int(u) for u in r["uids"]],
                "gap_min": gaps, "count": len(r["nos"]),
            }

        # 페이지 — handoffs를 먼저 LIMIT/OFFSET으로 자른 뒤 라인을 LEFT JOIN한다.
        # (배열 파라미터 ANY(:ids) 바인딩 불확실성을 피하려고 서브쿼리로 합쳤다.)
        page_rows = conn.execute(text(
            "SELECT h.handoff_id, h.handoff_no, h.session_id, h.snapshot_id, h.quote_type,"
            " h.member_id, h.user_id, h.total_quoted, h.total_mall, h.price_checked,"
            " h.changed_cnt, h.soldout_cnt, h.status, h.created_at,"
            " hi.line_no, hi.product_code, hi.item_kind, hi.part_type, hi.name_snap,"
            " hi.price_quoted, hi.price_mall, hi.qty, hi.mall_status, p.data_origin"
            " FROM (SELECT * FROM handoffs ORDER BY created_at DESC, handoff_id DESC"
            "       LIMIT :l OFFSET :o) h"
            " LEFT JOIN handoff_items hi ON hi.handoff_id = h.handoff_id"
            " LEFT JOIN products p ON p.product_code = hi.product_code"
            " ORDER BY h.created_at DESC, h.handoff_id DESC, hi.line_no"),
            {"l": limit, "o": offset}).mappings().all()

    order, by_id = [], {}
    for r in page_rows:
        hid = r["handoff_id"]
        if hid not in by_id:
            order.append(hid)
            by_id[hid] = {"h": r, "items": []}
        if r["line_no"] is not None:
            by_id[hid]["items"].append(r)

    rows = []
    for hid in order:
        h = by_id[hid]["h"]
        items_raw = by_id[hid]["items"]
        demo = [it for it in items_raw if it["data_origin"] == "demo"]
        demo_zero = sum(1 for it in demo if it["price_mall"] == 0)
        demo_unknown = sum(1 for it in demo if it["price_mall"] is None)
        unknown_count = sum(1 for it in items_raw if it["mall_status"] == "확인못함")

        note_parts = ["넘긴 기록 — 장바구니 도달 여부는 모릅니다"]
        if demo:
            tail = []
            if demo_zero:
                tail.append("몰 0원 %d라인" % demo_zero)
            if demo_unknown:
                tail.append("확인 못함 %d라인" % demo_unknown)
            suffix = "(" + ", ".join(tail) + ")" if tail else ""
            note_parts.append("시연용 상품 %d라인 포함%s" % (len(demo), suffix))
        note_text = " · ".join(note_parts)

        items = []
        for it in items_raw:
            ms = MALL_STATUS_LABELS.get(
                it["mall_status"], {"mark": "?", "text": it["mall_status"] or "—", "cls": "unk"})
            items.append({
                "line_no": it["line_no"], "product_code": it["product_code"],
                "item_kind": it["item_kind"],
                "item_kind_label": ITEM_KIND_LABELS.get(it["item_kind"], it["item_kind"] or "—"),
                "part_type": it["part_type"], "name": it["name_snap"], "qty": it["qty"],
                "price_quoted": it["price_quoted"], "price_mall": it["price_mall"],
                "mall_status": it["mall_status"], "mall_mark": ms["mark"],
                "mall_text": ms["text"], "mall_cls": ms["cls"],
                "is_demo": it["data_origin"] == "demo",
            })

        sid = h["session_id"]
        rows.append({
            "handoff_id": hid, "handoff_no": h["handoff_no"],
            "created_at": _iso(h["created_at"]),
            "tier": _tier(h["quote_type"]),
            "session_id": sid, "user_id": h["user_id"], "member_id": h["member_id"],
            "total_quoted": h["total_quoted"], "total_mall": h["total_mall"],
            "price_checked": bool(h["price_checked"]),
            "changed_cnt": h["changed_cnt"], "soldout_cnt": h["soldout_cnt"],
            "unknown_count": unknown_count, "status": h["status"],
            "line_count": len(items_raw), "note": note_text, "items": items,
            "session_group": sess_multi.get(int(sid)) if sid is not None else None,
        })

    return {
        "total": total,
        "page": {"limit": limit, "offset": offset, "returned": len(rows)},
        "period": ({"min": _iso(period[0]), "max": _iso(period[1])}
                   if period and period[0] is not None else None),
        "status_distinct": status_rows,
        "kpi": {
            "handoff_count": total,
            "lines": {**line_kinds, "total": line_total},
            "mismatch": {"n": mismatch_n, "sample": line_total,
                         "pct": round(mismatch_n * 100.0 / line_total, 1) if line_total else 0.0},
            "quoted_sum": {"sum": quoted_sum, "sample": total},
        },
        "rows": rows,
        "nav": _nav_links(),
    }


@router.get("/handoff-log", response_class=HTMLResponse)
def handoff_log(request: Request) -> HTMLResponse:
    """인계 기록(ADM-HND-020) — 조회 전용 원장. 셸만 그린다(빈 골격, 실데이터 없음) —
    실데이터는 `handoff_log_data()`가 별도로 인증을 거쳐 내보낸다(위 모듈 docstring
    "인증 구멍" 절 참조).
    """
    return render(request, "admin/handoff_log.html.j2",
                  screen_id="ADM-HND-020", domain="handoff-log",
                  crumb_group="인계 · 성과", crumb_now="인계 기록")


@router.get("/handoff-log/data")
def handoff_log_data(request: Request, limit: int = 50, offset: int = 0):
    """실 데이터. **이 경로는 `/api/admin/*` 인증 미들웨어 밖이라 직접 세션을 확인한다**
    (위 모듈 docstring "인증 구멍" 절 — `api/auth.py` L145-150 실측 근거). 등급은
    보지 않는다(계약 "권한 열람 등급 무관") — 로그인만 확인한다.
    """
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None:
        raise HTTPException(401, "로그인이 필요합니다")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return _load(limit, offset)
