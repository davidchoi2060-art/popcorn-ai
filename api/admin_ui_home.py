"""운영 대시보드(ADM-DASH-010) — admin2 진입 화면. `api/main.py`가 자동으로 싣는다(§discovery).

■ 재구축(2026-08-15) — UX-22(`docs/decisions/decision-log.md`, 2026-08-14 사장님 확정).
  승인 디자인 `docs/design/dc-dashboard-3안.html` **1b 카드 그리드형**을 그대로 구현한다
  (1a 큐 목록형 · 1c 브리핑형은 탈락 — 세 안은 "지금 할 일" 표현 방식만 다르고 콘텐츠는 같다).

  이전 버전은 옛 Phoenix(Bootstrap) 이커머스 대시보드 견본을 제목만 바꿔 그대로 쓰고
  있었다(본문 전체가 예시값 · 외부 CDN · 죽은 링크 45건 · `:root` 브릿지). 이번 재구축이
  셋을 해소한다 — Phoenix(Bootstrap·list.js·choices.js·feather) 전부 걷어내고 admin2.css
  토큰만 쓴다. 승인 디자인 자체가 물고 있던 구글 폰트 CDN(IBM Plex)은 Claude Design 캔버스의
  공통 서문일 뿐 이 화면의 의도된 콘텐츠가 아니라 옮기지 않았다(판단) — `var(--font)`/
  `var(--font-num)`로 대신한다. `:root{ --phoenix-font-sans-serif: var(--font); }` 브릿지는
  Phoenix를 걷어내면 참조하는 CSS가 없어 그대로 지운다.

■★ 데이터 — 새 쿼리를 만들지 않았다. `api/admin_dashboard.py`(담당 파일 밖 · 읽기만)의 네
  함수를 그대로 부른다 — decision-log UX-22가 "실데이터 API 4종이 고아(admin2 어느 화면도
  안 씀) → 이 화면이 그 API를 쓴다"고 확정한 바로 그 네 개다. `@router.get(...)`은 FastAPI가
  원래 함수 객체를 그대로 돌려주므로(라우트 등록은 부수효과), 여기서는 HTTP를 타지 않고
  **같은 프로세스 안에서 평범한 파이썬 함수로** 부른다(그래서 `/api/admin/*` 인증 미들웨어와도
  무관하다 — 그건 HTTP 요청 계층에서만 본다). 방문마다 다시 부르므로 "수치는 매 방문 서버
  재조회"(UX-22)를 별도 캐시 없이 만족한다.

    dashboard()       오늘의 흐름(상담·성립) · 최근 운영자 활동 3건
    quote_quality()   견적 품질 누적(성립률·모드별) · 재고 정합(stock_qty = SUM(qty_delta))
    funnel()          유입 깔때기(접속 → AI 문의 → 견적 성공)
    worklist()        지금 할 일(검수·매핑·가격 등 대기 건수 + 안내 문구)

  ■ 화면에서 뺀 필드 — 지어내지 않고 조용히 버리는 대신 이유를 남긴다.
    orders_total/orders_active/orders_by_status(dashboard) · order 단계(funnel) ·
    inbound/refund(worklist)  →  CANON §3 · decision-log UX-22: "주문·결제 계열은 화면에서
    제외한다"(팝콘AI = 신규 고객 유입 채널, 결제·배송·환불은 쇼핑몰 소관). worklist()의
    `inbound`(재고 입고)는 "아직 안 지었다"가 아니라 `admin_nav.py`가 애초에 admin2 IA
    범위에서 뺀 축이라(재고 원장은 쇼핑몰이 갖는다 — 그 모듈 docstring 실측) "지금 할 일"에
    올리지 않는다(판단 — 보고 대상).
    import_rows/ai_cost/pool_*(dashboard) · tiers/members/payments(quote_quality) ·
    s2/members_linked(funnel)  →  승인 디자인 6종 콘텐츠에 없는 축이라 얹지 않는다.

  ■ "몰 인계" — decision-log UX-22가 명시한 그대로: **handoffs 기준 API가 아직 없다.**
    없는 API를 지어내지 않고, 어디에도 없는 숫자를 「향후 사용예정」 문구로만 둔다 —
    0 자리를 만들지 않는다(0은 "인계 0건"이라는 사실 주장이 되어버린다).

■★★ "지금 할 일" 링크 — **경로로 조회한다. 라벨로 조회하지 않는다**
  (`api/admin_ui_swap_click_logs.py`의 해법을 그대로 따른다 — 그 파일이 라벨 키 조회로 실제
  사고를 낸 뒤 경로 키로 바꾼 전례가 있다). `admin_nav.NAV`(읽기만)를 "이 경로가 지금 메뉴에
  살아 있는가"로만 훑고, 화면 표시 라벨은 `admin_nav.py`의 현재 라벨을 그대로 쓴다
  (worklist() 자신의 라벨과 표기가 다를 수 있어 — 예: "상품 검수" vs "상품 사양 검수" —
  admin_nav를 우선한다. 화면 이름의 단일 원천이라서다).

  2026-08-15 실측(각 `admin_ui_*.py`의 `@router.get(...)` 선언을 직접 읽어 확인):

      review        /admin2/reviews           api/admin_ui_reviews.py              admin_nav 연결됨
      category      /admin2/category-mapping  api/admin_ui_product_category_map.py admin_nav 연결됨
      price         /admin2/price-review      api/admin_ui_price_review.py         코드는 있으나
                                                                                    admin_nav href
                                                                                    는 아직 None
      price_import  (없음)                    admin_ui_price_import.py 자체가 없다
      sourcing      (없음)                    admin_ui_sourcing.py 자체가 없다

  `admin_nav.py`의 href가 채워지면(하네스 몫) 이 파일을 고치지 않아도 다음 요청부터 바로
  살아있는 링크가 된다 — 하드코딩한 것은 "경로 문자열"뿐이고 "그 경로가 지금 연결됐는가"는
  매 요청 `admin_nav.py`를 다시 읽는다.

■ 실패를 삼키지 않는다 — 네 함수를 각각 독립적으로 부르고, 하나가 실패해도 나머지 콘텐츠는
  그대로 보여준다(표 하나가 죽었다고 대시보드 전체를 500으로 막지 않는다). 실패한 자리는
  "값이 비어 있을 뿐"으로 보이지 않게 한다 — 상단 배너 + 각 값의 `title`에 실패 사유를 남기고,
  화면 표시는 "—"로 한다. 재고 정합처럼 실제 0/모름(조회 실패)/N건이 뜻이 다른 자리는 셋을
  구분한다(0을 "정상"으로, 조회 실패를 "정상"으로 같은 값으로 뭉개지 않는다).

■ 낡은 상수 정리 — 이전 버전의 `BUILT`/`NEXT_STEPS`(admin2 재구축 진행 현황판 콘텐츠)를
  들어냈다. 승인 디자인 6종 콘텐츠에 그 항목이 없고(재구축 진행률이 아니라 오늘의 실제 운영
  현황을 보여주는 화면으로 성격이 바뀌었다), 남아 있던 값도 낡아 있었다 — `BUILT`에는
  "상품 관리" 하나뿐이었는데 `admin_nav.py` 기준 지금 admin2에 연결된 화면(state="new")은
  그보다 훨씬 많다(상품 분류 관리·상품 분류 매핑·조립 호환 지도·조립 사양 표준·상품 사양
  검수·작업 현황판·웹 사양 채움 등). `NEXT_STEPS`의 "IA 제안"·"기준 화면 1개"도 이미 지난
  일이다. 화면이 늘고 주는 진행률이 다시 필요해지면 이 상수를 되살리지 말고 `api/admin_nav.py`
  의 `nav_for`/`counts()`(이미 "몇 항목 중 몇 개가 new인가"를 정본으로 센다)를 읽는다 —
  같은 것을 두 벌 두지 않는다.
"""
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render, login_required_html
from .admin_nav import NAV
from .admin_dashboard import (
    dashboard as _dashboard_data,
    quote_quality as _quote_quality_data,
    funnel as _funnel_data,
    worklist as _worklist_data,
    # 다른 넷과 같은 관례 — 인자 없이 자기 커넥션을 여는 라우트 함수 쪽을 부른다.
    # `mall_sync_status(conn)` 자체는 conn 을 받는 헬퍼라 _safe(label, fn) 의
    # "fn()" 호출 관례(무인자)와 안 맞는다 — admin_dashboard.pending_counts(conn)와
    # dashboard()의 관계와 같은 짝이다.
    mall_sync_status_route as _mall_sync_status_data,
)
from .auth import resolve_session, COOKIE
from .timeutil import KST

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

# ■★ 이 화면의 자체 게이트 — 서버 렌더에서 직접 세션을 확인한다.
#
# ⚠ 2026-08-15 정정 — 바로 아래 문단은 한동안 "`auth_middleware`는 `/api/admin/*`만
# 막고 `/admin2/*`는 안 막는다"를 사실로 적어 두고 있었다. **그 전제가 깨졌다**:
# `admin_ui_reprice.py`·`admin_ui_margin_policy.py`·`admin_ui_mall_sync.py` 세
# 화면이 이 화면과 같은 방식(서버 렌더 시점에 실데이터를 페이지 셸에 직접 싣는다)
# 이면서 **이 화면과 달리 자체 게이트가 없어서**, 무세션으로 열면 회차·정책·인계
# 실데이터가 그대로 나갔다(조사자 실측, 2026-08-15). 그래서 `auth_middleware`
# (`api/auth.py`)를 **`/admin2/*`도 검사하도록 넓혔다** — 아래 문단이 말하는
# "막지 않는다"는 그 날짜 **이전**엔 사실이었고 지금은 아니다(코드가 바뀐 것이지,
# 아래 문단이 처음부터 틀렸던 게 아니다). 거절 응답 형식은 경로로 가른다:
# `/api/admin/*`는 그대로 JSON 401(기존 화면 스크립트가 그 형식을 읽으므로 한 글자도
# 안 바꾼다), `/admin2/*`는 이 파일이 쓰던 `_login_required_html()`을
# `admin_ui_common.login_required_html()`로 옮겨 미들웨어와 이 화면이 함께 쓴다
# (단일 원천 — 복제하지 않는다. `auth.py`가 이 파일을 직접 import하면 이 파일이
# 이미 `from .auth import resolve_session, COOKIE`를 하고 있어 순환이 되므로,
# 둘 다 import해도 안전한 `admin_ui_common.py`로 옮겼다).
#
# 아래는 넓히기 **전**의 원래 이유이고, 넓힌 뒤에도 이 화면이 자체 게이트를
# **지우지 않는** 이유이기도 하다(이중 방어는 해가 없다) — `admin_dashboard.py`의
# 함수를 HTTP가 아니라 파이썬 호출로 직접 부르므로(모듈 docstring 참조), 미들웨어가
# 막는 것은 "`/admin2/` 페이지 요청 자체"이지 이 파이썬 함수 호출이 아니다. 지금은
# 미들웨어가 요청을 401로 끊으면 이 핸들러 자체가 실행되지 않아 자연히 그 함수들도
# 안 불리지만, 그대로 두면(핸들러가 어떤 경로로든 실행되는 경우) 검수 대기 건수 ·
# 견적 성립률 · 운영자 이름이 박힌 최근 활동까지 로그인 없이 그대로 보인다 — 승인
# 디자인 자신의 하단 문구("실데이터 연결 후 미로그인 접근은 401 → 로그인으로
# 보냅니다")를 어기는 셈이다. 그래서 이 화면만 렌더 앞단에서 같은 쿠키로 같은 세션
# 확인을 한 번 더 한다(가짜 인증을 새로 만들지 않고 `auth.resolve_session`을 그대로
# 부른다 — 정본을 복제하지 않는다).


def _safe(label: str, fn):
    """`fn()`을 부르고 실패하면 (None, 사유)를 돌려준다 — 페이지 전체를 죽이지 않는다.

    조회 실패의 상세(원문 예외)는 서버 로그에만 남긴다(ASCII만 — cp949 stdout이 em-dash·
    화살표를 만나면 500을 낸 전례가 있다). 화면에는 종류(예외 클래스명)까지만 보인다 —
    내부 커넥션 문자열 같은 것이 관리자 화면이라도 그대로 노출되지 않게 한다.
    """
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 — 조회 실패 자체를 화면에 알리려 넓게 잡는다
        print(f"[admin_ui_home] {label} query failed: {type(e).__name__}: {e}")
        return None, f"{label} 조회 실패({type(e).__name__})"


# "지금 할 일" — worklist() 8항목 중 admin2 범위에 드는 다섯만 쓴다.
# 뺀 셋: orders·refund(주문·결제 계열, CANON §3로 화면 제외) · inbound(재고 입고,
# admin_nav.py가 admin2 IA 범위 자체에서 뺀 축 — "아직 없음"이 아니라 "여기서 할 일이
# 아님"이라 다르다. 판단 — 보고 대상).
_WORK_KEYS = ["review", "category", "price", "price_import", "sourcing"]

# admin_nav.py의 현재 라벨(정본)로 표시한다 — worklist() 자체 라벨과 표기가 다를 수 있다.
_NAV_LABEL = {
    "review": "상품 사양 검수",
    "category": "상품 분류 매핑",
    "price": "가격 검토 대기",
    "price_import": "단가표 반영",
    "sourcing": "매입 견적(용산)",
}

# 경로 실측(모듈 docstring "■★★" 참조) — 라벨이 아니라 경로로 admin_nav.NAV를 조회한다.
# 값이 None 이면 "화면 없음"으로 회색 처리된다. 실재하는 화면을 None 으로 두면
# 대시보드가 「할 일 N건」을 보여주면서 갈 곳은 없다고 말하는 거짓말이 된다 —
# 2026-08-15 에 price-import·sourcing 두 화면이 admin_nav 에 연결됐는데 이 표만
# 안 따라가 11일 동안 그랬다(2026-08-26 대시보드 매뉴얼을 쓰다 발견).
# 아래 `_live_hrefs()` 가 admin_nav 를 정본으로 한 번 더 거르므로, 여기 적힌 경로가
# 메뉴에서 사라지면 자동으로 회색이 된다 — 즉 지어낸 경로는 화면에 나가지 않는다.
_TARGET_PATH = {
    "review": "/admin2/reviews",
    "category": "/admin2/category-mapping",
    "price": "/admin2/price-review",
    "price_import": "/admin2/price-import",
    "sourcing": "/admin2/sourcing",
}


def _live_hrefs() -> set:
    """admin_nav.NAV에 실제로 걸려 있는 href 전체(읽기만 — 고치지 않는다)."""
    return {href for _title, _icon, items in NAV for _label, href, _note in items if href}


def _work_items(wl: dict | None):
    if wl is None:
        return [], None
    live = _live_hrefs()
    by_key = {i["key"]: i for i in wl["items"]}
    out = []
    active_total = 0
    for key in _WORK_KEYS:
        src = by_key.get(key)
        if src is None:          # worklist()가 이 키를 더는 안 주면 조용히 건너뛴다
            continue
        target = _TARGET_PATH.get(key)
        live_href = target if (target and target in live) else None
        count = src["count"]
        sub = src.get("hint") or ""
        if src.get("focus") is not None and src.get("focus_label"):
            extra = f'{src["focus_label"]} {src["focus"]:,}건 포함'
            sub = f"{sub} · {extra}" if sub else extra
        if live_href:
            active_total += count
            reason = None
        elif target:
            reason = "화면은 준비됐지만 아직 admin2 메뉴에 연결되지 않았습니다"
        else:
            reason = "이 화면은 아직 admin2에 없습니다"
        out.append({
            "key": key,
            "name": _NAV_LABEL.get(key, src["label"]),
            "count": count, "count_fmt": f"{count:,}",
            "sub": sub, "href": live_href, "active": bool(live_href),
            "badge": "이동 →" if live_href else "화면 없음",
            "reason": reason,
            "urgent": count > 1000,
        })
    return out, active_total


def _flow(dash: dict | None, quality: dict | None, err_dash, err_quality) -> dict:
    consult = {"value_fmt": "—", "status": "error", "reason": err_dash}
    quoted = {"value_fmt": "—", "status": "error", "reason": err_dash}
    drop_fmt = "—"
    if dash is not None:
        f = dash["flow"]
        # A-81 — 세션 수는 「시험 운영 기간」 제외분이다. 기존 title 툴팁 자리(에러 사유가
        # 쓰던 자리)를 성공 상태에서도 재사용한다 — 새 자리를 만들지 않는다.
        note = f.get("sessions_scope_note")
        consult = {"value_fmt": f'{f["sessions_today"]:,}', "status": "ok", "reason": note}
        quoted = {"value_fmt": f'{f["sessions_done"]:,}', "status": "ok", "reason": note}
        drop_fmt = f'{f["sessions_drop"]:,}'
    stock = {"status": "error", "label": "— 조회 실패", "reason": err_quality}
    if quality is not None:
        drift = quality["stock_drift"]
        if drift == 0:
            stock = {"status": "ok", "label": "✓ 이상 0건", "reason": None}
        else:
            stock = {"status": "warn", "label": f"⚠ 이상 {drift:,}건", "reason": None}
    return {"consult": consult, "quoted": quoted, "drop_fmt": drop_fmt, "stock": stock}


def _mall_sync_view(st: dict | None, err) -> dict:
    """몰 공급처·가격 자동 갱신(tools/mall_daily_sync.py) — 가장 최근 실행 한 줄.

    2026-08-27 사장님 확인: 이 배치의 결과는 작업 현황판이 아니라 **이 대시보드**가
    유일한 표시 자리다(배치가 배포 서버에서 돌아 로컬 세션 전사본에 안 닿는다).
    그래서 여기서 "언제 · 성공/실패 · 건수"를 한 줄로 낸다 — 지시서가 준 문구
    형태(성공/실패/미실행 세 예시)를 그대로 따른다.

    상태 배지는 기존 "재고 정합" 자리가 쓰던 ok/warn/error 셋을 그대로 재사용한다
    (dash-flow .stock .badge — home.html.j2, 새 CSS를 만들지 않는다). 다만 그 셋의
    의미를 이 자리에 맞게 다시 정한다:
      ok    최근 실행이 성공했고 24h+6h(MALL_SYNC_STALE_HOURS) 안에 시작됐다 — 조용히.
      warn  실패했거나(신선도 무관 — 실패는 항상 눈에 띄어야 한다) 성공은 했지만
            오래 안 돌았다("하루 넘게 안 돌았으면 그것도 경고로") — 진행 중인데
            너무 오래 걸리는 것도 여기 포함(stalled).
      error 아직 한 번도 실행된 적이 없다(표는 있지만 행이 0) 또는 조회 자체가
            실패했다(마이그레이션 미적용 등 — err 인자로 들어온다).
    """
    if st is None:
        return {"status": "error", "text": "몰 갱신 상태를 불러오지 못했습니다",
                "reason": err}

    if st["state"] == "never":
        return {"status": "error", "text": "몰 갱신 — 아직 실행된 적 없습니다",
                "reason": "mall_sync_runs 에 실행 기록이 없습니다"
                          "(타이머가 아직 등록 전이거나 첫 실행 전일 수 있습니다)"}

    when = "—"
    if st.get("started_at"):
        try:
            when = datetime.fromisoformat(st["started_at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = "—"

    if st["state"] == "running":
        return {"status": "ok", "text": f"몰 갱신 실행 중 — {when} 시작",
                "reason": None}

    if st["state"] == "stalled":
        return {"status": "warn",
                "text": f"⚠ 몰 갱신 — {when} 시작 후 {st['age_hours']:.0f}시간째 응답이 없습니다",
                "reason": "실행이 끝나지 않았거나(오래 걸리는 중) 타이머가 멈췄을 수 있습니다"
                          " — 서버에서 journalctl -u popcorn-mall-sync.service 로 확인하세요"}

    if st["state"] == "fail":
        reason = st.get("fail_reason") or "사유가 기록되지 않았습니다"
        return {"status": "warn", "text": f"⚠ 몰 갱신 실패({when}) — {reason}",
                "reason": reason}

    # ok 또는 stale_ok — 성공한 마지막 실행의 건수를 그대로 보여준다. 0건도 값이다
    # (측정했는데 0인 것과 못 잰 것은 다르다 — count 가 None 일 때만 생략한다).
    parts = []
    if st.get("collected_count") is not None:
        parts.append(f"수집 {st['collected_count']:,}건")
    if st.get("price_changed_count") is not None:
        parts.append(f"가격 {st['price_changed_count']:,}건 변경")
    if st.get("held_count") is not None:
        parts.append(f"보류 {st['held_count']:,}건")
    if st.get("excluded_count") is not None:
        parts.append(f"후보 제외 {st['excluded_count']:,}건")
    body = " · ".join(parts)
    text_ = f"몰 갱신 {when}" + (f" — {body}" if body else "")

    if st["state"] == "stale_ok":
        return {"status": "warn",
                "text": f"⚠ {text_} (마지막 실행 후 {st['age_hours']:.0f}시간 경과)",
                "reason": "새벽 타이머가 하루 넘게 돌지 않았습니다 — 서버 타이머 상태를 확인하세요"}
    return {"status": "ok", "text": text_, "reason": None}


def _quality_view(quality: dict | None, err) -> dict:
    if quality is None:
        return {"status": "error", "reason": err, "modes": []}
    sess = quality["sessions"]
    modes = []
    for m in quality["modes"]:
        pct = round(m["count"] / sess * 100) if sess else 0
        modes.append({"label": m["label"], "pct": pct})
    return {
        "status": "ok", "reason": None,
        "rate_fmt": f'{quality["rate"]:.1f}%',
        "quoted_fmt": f'{quality["quoted"]:,}', "sessions_fmt": f'{sess:,}',
        "modes": modes,
        # A-81 — sessions/quoted/rate 전부 「시험 운영 기간」 제외분. 패널 헤드의 title
        # 툴팁 자리에 얹는다(새 자리를 만들지 않는다).
        "scope_note": quality.get("scope_note"),
    }


def _funnel_view(fn: dict | None, err) -> list:
    rows = []
    if fn is None:
        for label in ("접속", "AI 문의", "견적 성공"):
            rows.append({"label": label, "status": "error", "value_fmt": "—", "pct": 0,
                        "reason": err})
    else:
        steps = {s["key"]: s for s in fn["steps"]}
        visit = steps["visit"]["value"] or 0
        for key, label in (("visit", "접속"), ("consult", "AI 문의"), ("quote", "견적 성공")):
            v = steps[key]["value"] or 0
            pct = round(v / visit * 100, 1) if visit else 0.0
            # A-81 — consult·quote 단계는 funnel()이 이미 단계별 note(steps[key]["note"])로
            # 시험 운영 기간 제외 사실을 실어 보낸다. visit 은 users 테이블이라 대상이 아니다
            # (funnel() 쪽에서도 그 단계에는 note를 안 실었다 — steps[key].get()이 None을 돌려준다).
            rows.append({"label": label, "status": "ok", "value_fmt": f"{v:,}", "pct": pct,
                        "reason": steps[key].get("note")})
    # 장바구니·몰 인계는 API 응답의 일부가 아니다 — decision-log UX-22가 명시한 빈 값
    # 두 종류를 그대로 옮긴다(장바구니 = 원천 없음, 몰 인계 = 향후 사용예정). 0을 넣지 않는다.
    rows.append({"label": "장바구니", "status": "empty", "value_fmt": "원천 없음", "pct": 0,
                "reason": "carts 테이블 자체가 없습니다 — 원천 부재(funnel() 응답 그대로)"})
    rows.append({"label": "몰 인계", "status": "empty", "value_fmt": "향후 사용예정", "pct": 0,
                "reason": "handoffs 기준 API 재정비가 선행되어야 합니다"})
    return rows


def _recent_logs(dash: dict | None) -> list:
    if dash is None:
        return []
    out = []
    for entry in dash["system"]["recent_logs"]:
        at = entry["at"]
        hhmm = "—"
        if at:
            try:
                hhmm = datetime.fromisoformat(at).astimezone(KST).strftime("%H:%M")
            except ValueError:
                hhmm = "—"
        msg = f'{entry["operator"]} — {entry["kind"]} {entry["action"]}'
        if entry["target"]:
            msg += f' · {entry["target"]}'
        out.append({"at": hhmm, "msg": msg})
    return out


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """운영 대시보드(ADM-DASH-010) — 1b 카드 그리드형(UX-22, 2026-08-14 사장님 확정).

    맨 위 세션 확인이 이 라우트만의 예외인 이유는 모듈 docstring "■★"를 본다 — 실데이터를
    HTTP(`/api/admin/*`, 미들웨어 보호)가 아니라 파이썬 함수 호출로 직접 채우기 때문에
    이 화면만은 그 보호를 지나가지 않고, 그래서 여기서 스스로 확인한다.
    """
    op = resolve_session(request.cookies.get(COOKIE, ""))
    if op is None:
        return HTMLResponse(login_required_html(), status_code=401)

    dash, err_dash = _safe("오늘의 흐름 · 최근 활동", _dashboard_data)
    quality, err_quality = _safe("견적 품질 · 재고 정합", _quote_quality_data)
    fn, err_funnel = _safe("유입 깔때기", _funnel_data)
    wl, err_worklist = _safe("지금 할 일", _worklist_data)
    mall_sync, err_mall_sync = _safe("몰 갱신 상태", _mall_sync_status_data)

    work_items, active_total = _work_items(wl)
    errors = [e for e in (err_dash, err_quality, err_funnel, err_worklist, err_mall_sync) if e]

    return render(
        request, "admin/home.html.j2",
        screen_id="ADM-DASH-010", domain="dashboard",
        crumb_group="대시보드", crumb_now="대시보드",
        generated_at=datetime.now(KST).strftime("%H:%M"),
        errors=errors,
        work_items=work_items,
        active_total_fmt=(f"{active_total:,}" if active_total is not None else "모름"),
        work_error=err_worklist,
        flow=_flow(dash, quality, err_dash, err_quality),
        quality=_quality_view(quality, err_quality),
        funnel_steps=_funnel_view(fn, err_funnel),
        logs=_recent_logs(dash),
        dash_error=err_dash,
        mall_sync=_mall_sync_view(mall_sync, err_mall_sync),
    )
