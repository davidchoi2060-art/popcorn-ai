# -*- coding: utf-8 -*-
"""쇼핑몰 동기화(ADM-HND-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다
(§discovery, `api/` 평면에 둔다 — 하위 폴더는 자동 등록이 훑지 않는다).

**조회 전용.** 계약 `docs/design/spec-mall-sync.md`(사장님 확정 **1a** "라인 축" ·
2026-08-15. 1b "인계 건 축 + 커버리지"는 탈락). 정의서 `docs/design/req/req-mall-sync.md`.
원문(Claude Design)은 하네스만 연다(`docs/design/MAKER-CHECKLIST.md` §1) — 이 화면은
계약 요약 + 직접 실측만으로 지었다(원안 `.dc.html`은 열지 못했다).

■ 데이터 실측 — 짓기 전에 다섯 가지를 직접 쟀다(지시서 §⚠⚠ 그대로, 전부 읽기 전용 SELECT)

  ① handoffs 표에 무엇이 남아 있나
     `db/migrations/versions/0042_handoffs.py` 직접 대조. `handoffs`(15컬럼: handoff_no·
     session_id·total_quoted·total_mall·price_checked·changed_cnt·soldout_cnt·status·
     created_at 등) + `handoff_items`(10컬럼, PK `(handoff_id, line_no)` — **라인 단위가
     맞다**). `api/admin_sessions.py`가 이미 `handoffs.session_id`를
     `consult_sessions.session_id`로 LEFT JOIN하는 것을 확인했다.

  ② 라인별 「당시」 몰 가격이 남아 있나 — **있다.**
     `handoff_items.price_mall`이 그 라인 하나하나의 인계 시점 몰 가격이다
     (`api/handoff.py` L104-124, L145-152). `price_quoted`(우리가 보여준 값)와
     나란히 저장된다 — 표 7열의 "우리 값"·"몰 값"이 바로 이 두 컬럼이다.

  ③ 확인 실패 사유 4종을 「구분해」 저장하나 — **아니다. 이것이 이 화면 최대의 간극이다.**
     `api/mall.py::_one()`은 "몰에 없는 상품"/"가격 필드 없음"/"몰 가격 0원"/예외(타임아웃 등)
     네 사유를 **계산은** 한다(`out["err"]`). 그런데 `api/handoff.py` L109-122은 그 `err`
     문자열을 아예 받지 않고, `l["mall"] is None`이면 무조건 `mall_status="확인못함"`
     **하나로 뭉뚱그려** INSERT한다(L116, L148-152). 게다가 "몰 가격 0원"인 경우도
     `mall.py`가 `out["price"]`를 끝내 채우지 않으므로(`_one()`은 0원이면 `out["price"]=p`
     줄에 도달하지 못하고 그 앞에서 반환) DB에 저장되는 `price_mall`은 **0이 아니라
     NULL**이 된다 — "0원"·"몰에 없음"·"가격 필드 없음"·"타임아웃"이 저장 시점에 전부
     `price_mall=NULL, mall_status='확인못함'`으로 **구별 불가능하게 뭉개진다.** 저장되는
     `mall_status` 값은 확인됨/가격변동/확인못함 **셋뿐**이다(`req-mall-sync.md` ④의
     실측과 일치). 그래서 이 화면은:
       - 과거 각 라인이 "몰에 없음"이었는지 "0원"이었는지 "타임아웃"이었는지는 「원천 없음」
         으로 정직하게 비운다(지어내지 않는다) — 4사유는 "왜 확인 못함이 존재하는가"를
         설명하는 교육적 문구로만 쓰고, 행 단위 사유로는 쓰지 않는다.
       - 계약 문구 "확인 실패 사유는 뭉뚱그리지 않습니다 — …각각 다르게 표시합니다"는
         행 단위로는 지킬 수 없어, 하단 고지 문구를 사실에 맞게 조정했다(아래 라우트
         함수 docstring·템플릿 참조). 판단 근거는 제작 보고에 남긴다.
       - ⚠ **정정(자체 검증 중 실측, 2026-08-15)** — 처음엔 여기 "`price_mall == 0`은
         현재 쓰기 경로로 절대 도달하지 않는 방어적 죽은 분기"라 적었는데 **틀렸다.**
         `SELECT`로 직접 대조한 결과 `HO-1001`의 시연용 두 라인(RAM 20483003 · SSD
         20486102)이 실제로 `price_mall=0, mall_status='가격변동'`으로 저장돼 있다 —
         이것이 바로 이 문서 위에서 말한 "몰 가격이 0원으로 와서 드러났다"는 사고의
         **원본 기록**이다(당시 `mall.py`에 0원 가드가 없었던 것으로 보인다). 4분 뒤
         `HO-1002`에서 같은 두 라인이 `price_mall=NULL, mall_status='확인못함'`으로
         바뀐 것은 그 사고를 잡은 뒤 가드가 붙은 결과다. 근거·수정 내역은
         `_mall_fmt`·`_hist_desc`·`is_incident` 계산부 주석 참조.

  ④ soldout_cnt 컬럼이 실제로 있고 정말 항상 0인가 — **있고, 항상 0이다.**
     `api/handoff.py`의 INSERT문이 `soldout_cnt`에 SQL 리터럴 `0`을 그대로 박는다(바인드
     파라미터가 아니다). `api/mall.py`에는 품절·재고를 읽는 코드가 아예 없다 — 판정 로직
     자체가 없다. 그래서 이 화면은 그 숫자를 **절대 노출하지 않는다**(SELECT조차 하지
     않는다) — "판정 로직 없음"이라는 문장으로만 대체한다.

  ⑤ 「지금 확인」에 쓸 실서비스 조회 API가 있나 — **없다.**
     `popcornpc.co.kr`과 통신하는 코드는 저장소 전체에서 `api/mall.py` 하나뿐이고
     (`grep -rn "popcornpc.co.kr" api/*.py` = `api/mall.py` 유일), 그것을 부르는 곳은
     `api/handoff.py::create_handoff()` 한 곳뿐이다(`grep -rn "import mall" api/*.py`).
     admin 전용 조회 엔드포인트는 0개(`req-mall-sync.md` ④ "쓰는 API: (없음)"과 일치).
     **사장님 확정(2026-08-15, 작업 목록 #38)대로 이 화면은 스크래퍼를 새로 만들지
     않는다** — `mall.py`를 import하지 않고, 「지금 확인」 버튼은 `disabled` +
     "향후 사용예정 — 실서비스 조회 API 준비 중"으로 잠근다.

■ 「판매가 관리에서 열기 →」 — 경로로 판정한다(라벨 금지)
  `admin_ui_swap_click_logs.py`의 사고(라벨 리네임으로 조회가 조용히 깨짐)와 같은 방식으로
  막는다: **경로 문자열**을 하드코딩해 두고 `api/admin_nav.py`의 NAV에 그 경로가 **지금
  실제로 링크돼 있는지**만 매 요청 확인한다(라벨은 조회에 관여하지 않는다). 경로는
  `docs/design/req/req-sale-price.md` ②가 스스로 제안한 가칭 `/admin2/sale-price`를
  그대로 썼다 — 이 작업 시각(2026-08-15 00시경) 기준 `api/admin_ui_sale_price.py`·
  `templates/admin/sale_price.html.j2`가 **다른 제작자가 방금 만든 상태**였다(그 파일은
  "다른 화면 파일"이라 열어서 대조하지 않았다 — 대신 이미 떠 있는 :8002 서버에
  `GET /admin2/sale-price`를 직접 던져 **200**을 확인했다. 코드를 읽지 않고 서버 동작만
  본 것이다). 그런데 `api/admin_nav.py`의 "판매가 관리" 항목은 이 작성 시점 여전히
  `href=None`이다(검증 통과 전에는 하네스가 메뉴에 안 붙인다는 팀 규약 그대로) — 그래서
  **지금은 비활성이 맞다.** 하네스가 검증 후 admin_nav.py의 href를 채우면 이 파일을
  다시 고치지 않아도 다음 요청부터 바로 살아있는 링크가 된다.

■ 표기 오류 발견 — "원인소프트" → "윈윈소프트" (계약 문서 대조로 발견)
  `docs/design/spec-mall-sync.md` 39행이 "원인소프트 API"라 적었는데, 실제 벤더명은
  `api/mall.py` 모듈 docstring과 `docs/design/winwin-api-request-2026-08-11.md`(파일명·
  본문 1행 모두)가 일관되게 말하는 **"윈윈소프트"**다. "원인소프트"는 저장소 전체에서
  이 한 줄에만 나온다(grep 전수 확인). 계약을 옮겨 적을 때 생긴 오기로 보고, 화면에는
  실측된 이름 "윈윈소프트"를 썼다(MAKER-CHECKLIST §8: 코드가 맞으면 코드를 따르고
  지시가 틀렸다는 것도 보고에 적는다).

■ 데이터 집계 API를 따로 만들지 않았다 — 담당 파일이 이 두 개뿐이라서
  `req-mall-sync.md` ④는 "이 화면이 서려면 최소 '핸드오프 이력 집계'용 신규 엔드포인트가
  필요하다"고 적었지만, 이 작업의 담당 파일은 `templates/admin/mall_sync.html.j2` + 이
  파일 **둘뿐**이다(새 `api/admin_mall_sync.py` 데이터 API 파일은 범위 밖 — 만들면
  "담당 파일 밖은 만들지 않는다" 규약 위반). 그래서 집계 SQL을 이 페이지 라우트 안에서
  직접 돌리고(읽기 전용 SELECT만, `handoffs`·`handoff_items`·`products`), 결과를 서버
  렌더(Jinja — 새로고침 없이도 항상 보이는 본문)와 서랍용 JSON(`detail_json`, 행 클릭
  시 참조) 양쪽으로 함께 내보낸다. 재사용 가능한 JSON API가 필요해지면(예: "판매가 관리"가
  같은 확인됨/가격변동/확인못함 집계를 다시 쓰려는 겹침 — req-mall-sync.md §겹침) 그건
  별도 담당의 신규 파일이 필요하다 — 이 파일 범위 밖.

■ 셸 블록 이름 — 추정이다, 확인 필요
  `_admin2_shell.html.j2`·`admin_ui_common.py`는 지시서가 "절대 열지 마라"로 막아서
  열지 않았다. 대신 `mockups/shared/admin2/admin2.css`(금지 목록에 없고 MAKER-CHECKLIST
  §2 필독 목록)의 주석에서 실제 블록 이름 둘을 확인했다: **`head_extra`**("화면마다
  의미가 다른 클래스는 각 템플릿 자신의 `<style>`(head_extra 블록)에 남는다") ·
  **`header_extra`**("화면별 추가 위젯은 `header_extra` 블록(권한 표시 바로 뒤, 아바타
  앞)에 얹는다"). 본문 블록 이름은 이 파일에 힌트가 없어 **`content`로 추정**했다(가장
  흔한 Jinja 관례). 화면이 빈 셸만 보이면(카드·표가 하나도 안 보이면) 이 추정이 틀렸다는
  신호다 — 확인자가 제일 먼저 볼 지점.

■★ 인증 전제(2026-08-15) — 이 화면은 서버 렌더 시점에 실데이터를 싣는다 — 미들웨어가
  `/admin2/` 를 막는 것이 전제다(`api/auth.py` `auth_middleware`/`_is_gated`). 이 파일
  자신은 로그인을 확인하지 않는다 — 확인하지 않아도 되는 이유가 이 한 줄이다.
"""
from datetime import timezone as _tz
from urllib.parse import quote

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .admin_ui_common import render
from .admin_nav import NAV
from .db import engine
from .taxonomy import PART_LABELS
from .timeutil import KST

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

PAGE_SIZE = 50

# req-sale-price.md ②가 제안한 가칭 경로. 위 모듈 docstring "■ 판매가 관리에서 열기" 참조.
# 2026-08-15 서버 동작(GET 200)으로 라우트 존재는 확인했지만, admin_nav.py의 href가
# 채워지기 전까지는 이 화면이 링크를 살리지 않는다(경로로만 판정 — 라벨 금지).
SALE_PRICE_PATH = "/admin2/sale-price"

ITEM_KIND_LABELS = {
    "core_part": "핵심 부품", "assembly_service": "조립 서비스", "peripheral": "주변기기",
}

# api/handoff.py L116-122이 실제로 만드는 값은 이 셋뿐이다(실측). 4사유(몰에 없음/
# 가격 필드 없음/0원/타임아웃)는 여기 포함되지 않는다 — 저장되지 않기 때문이다.
STATUS_META = {
    "확인됨":   {"label": "확인됨",    "symbol": "✓", "cls": "done"},   # ✓
    "가격변동": {"label": "가격변동",  "symbol": "▲", "cls": "run"},    # ▲
    "확인못함": {"label": "확인 못함", "symbol": "—", "cls": "wait"},   # —
}
STATUS_FALLBACK = {"label": "알 수 없음", "symbol": "?", "cls": "wait"}


def _fmt(n) -> str:
    return "{:,}".format(n) if isinstance(n, (int, float)) else "—"


def _pct(a: int, b: int) -> float:
    return round(a / b * 100, 1) if b else 0.0


def _kst(dt):
    """UTC(또는 naive-UTC로 간주) → 서울 시각 'YYYY-MM-DD HH:MM' 문자열. `api/timeutil.py` 관례."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _status_meta(status) -> dict:
    return STATUS_META.get(status, STATUS_FALLBACK)


def _mall_fmt(mall) -> str:
    """몰 값 표시 — 못 읽으면 「못 읽음」, 0원이면 「0」(계약 그대로).

    ⚠ **정정(자체 검증 중 발견, 2026-08-15)** — 이 함수를 처음 짤 때 "지금 handoff.py
    쓰기 경로로는 price_mall=0이 절대 저장되지 않는다(항상 NULL)"고 docstring에 적었는데
    **실측으로 틀렸다는 것이 드러났다.** `HO-1001`의 시연용 두 라인(RAM 20483003 · SSD
    20486102)이 실제로 `price_mall=0, mall_status='가격변동'`로 저장돼 있다(직접 SELECT로
    확인). 이건 `req-mall-sync.md`가 적은 그 사고의 원본 기록이다 — **"몰 가격이 0원으로
    와서 드러났다"**는 문장이 가리키는 실제 행이 이것이다. 4분 뒤 `HO-1002`에서 같은 두
    라인이 `price_mall=NULL, mall_status='확인못함'`로 바뀐 것은 **그 사고를 잡은 뒤
    `api/mall.py`에 추가된 0원 가드가 적용된 결과**로 보인다(그 가드 이후로는 0원이
    NULL로 흡수된다 — 지금 시점 기준으로는 여전히 맞는 말이다). 즉 `mall == 0` 분기는
    **죽은 코드가 아니라, 사고 당시 기록을 정확히 보여주는 데 실제로 쓰인다.**
    """
    if mall is None:
        return "못 읽음"
    if mall == 0:
        return "0"
    return _fmt(mall) + "원"


def _diff_fmt(quoted, mall) -> str:
    """차액 — 부호 포함, 못 읽으면 —."""
    if mall is None:
        return "—"
    d = mall - quoted
    if d == 0:
        return "0원"
    if d > 0:
        return "+{}원".format(_fmt(d))
    return "-{}원".format(_fmt(abs(d)))


def _hist_desc(quoted, mall, status, handoff_no) -> str:
    """서랍 "확인 기록" 한 줄 설명.

    코디네이터 중계(2026-08-15, 판매가 관리 제작자 실측과 동일 결론) — 확인못함의 세부
    사유(몰에 없음/필드 없음/0원/타임아웃)는 저장되지 않으므로 **지어내지 않는다.**
    「인계 시점에 몰 가격을 확인하지 못했습니다」로만 말한다(판매가 관리 화면과 같은 원칙).

    `mall == 0`은 별도 문장으로 — `_mall_fmt` docstring의 2026-08-15 정정 참조. `HO-1001`의
    시연용 두 라인처럼 **몰 값이 실제로 0으로 읽힌 사고 원본 기록**이 존재하므로, "차액"
    산수만 보여주면 그 의미(공짜로 넘어갈 뻔했다)가 묻힌다.
    """
    if status == "확인못함":
        return "인계 {} 시점에 몰 가격을 확인하지 못했습니다(우리 값 {}원 안내).".format(
            handoff_no, _fmt(quoted))
    if mall == 0:
        return ("인계 {} 시점에 몰 가격이 0원으로 읽혔습니다(우리 값 {}원 안내) — "
                 "팔 수 없는 값이라 확인된 값으로 세지 않습니다.").format(handoff_no, _fmt(quoted))
    return "우리 {}원 → 몰 {} (차액 {})".format(_fmt(quoted), _mall_fmt(mall), _diff_fmt(quoted, mall))


def _origin_label(data_origin, item_kind: str) -> str:
    if data_origin == "demo":
        return "시연용"
    if data_origin == "real":
        return "실데이터"
    if item_kind == "assembly_service":
        return "조립 서비스(카탈로그 상품 아님)"
    return "카탈로그에 없음"


def _sale_price_link() -> dict:
    """「판매가 관리에서 열기」 — admin_nav.NAV를 href로만 확인한다(라벨 금지, 위 참조)."""
    live_hrefs = {href for _title, _icon, items in NAV for _label, href, _note in items if href}
    available = SALE_PRICE_PATH in live_hrefs
    return {
        "href": SALE_PRICE_PATH if available else None,
        "available": available,
        "reason": None if available else "아직 admin2 메뉴에 연결되지 않았습니다 — 신설 예정",
    }


def _fetch(status_filter: str, page: int) -> dict:
    """읽기 전용 집계 — 전부 SELECT. `handoffs`·`handoff_items`·`products`만 읽는다."""
    with engine.connect() as conn:
        handoffs_count = conn.execute(text("SELECT COUNT(*) FROM handoffs")).scalar() or 0
        items_count = conn.execute(text("SELECT COUNT(*) FROM handoff_items")).scalar() or 0

        status_rows = conn.execute(text(
            "SELECT mall_status, COUNT(*) c FROM handoff_items GROUP BY mall_status")
        ).mappings().all()
        sc = {r["mall_status"]: r["c"] for r in status_rows}
        matched = sc.get("확인됨", 0)
        changed = sc.get("가격변동", 0)
        unmatched = sc.get("확인못함", 0)

        # 확인 못함 중 시연용 상품 비중 — KPI 캡션을 지어내지 않고 실측치로 채운다.
        unmatched_demo = conn.execute(text(
            "SELECT COUNT(*) FROM handoff_items hi"
            " JOIN products p ON p.product_code = hi.product_code"
            " WHERE hi.mall_status = '확인못함' AND p.data_origin = 'demo'")
        ).scalar() or 0

        total_products = conn.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0
        # 분모(total_products)와 같은 모집단(=products에 실제로 있는 상품)으로 분자를 맞춘다.
        # (정정 2026-08-15, 확인자·조사자 독립 실측 일치) 조립비(pd_no 92983)는 products에
        # 실재한다("제작 공임1", status='판매중', data_origin='real' — 직접 SELECT로 확인,
        # 참조 handoff_items에도 3행) — 이 JOIN에서 자연히 빠지지 않고 분자에 포함된다.
        # 위 주석이 전에 들었던 예시("92983은 카탈로그에 없어 빠진다")는 틀린 예시였다.
        # 집계 쿼리(JOIN 자체)는 실재 여부를 정확히 반영하므로 화면이 보여주는 값은 맞다 —
        # 틀렸던 것은 이 주석뿐이었다.
        checked_products = conn.execute(text(
            "SELECT COUNT(DISTINCT hi.product_code) FROM handoff_items hi"
            " JOIN products p ON p.product_code = hi.product_code")
        ).scalar() or 0

        last = conn.execute(text(
            "SELECT handoff_no, created_at FROM handoffs"
            " ORDER BY created_at DESC, handoff_id DESC LIMIT 1")
        ).mappings().first()

        where = ""
        params = {}
        if status_filter in STATUS_META:
            where = " WHERE hi.mall_status = :st"
            params["st"] = status_filter
        total_rows = conn.execute(text(
            "SELECT COUNT(*) FROM handoff_items hi" + where), params).scalar() or 0

        total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, page), total_pages)

        q_params = dict(params)
        q_params["lim"] = PAGE_SIZE
        q_params["off"] = (page - 1) * PAGE_SIZE
        rows = conn.execute(text(
            "SELECT hi.handoff_id, hi.line_no, hi.product_code, hi.item_kind, hi.part_type,"
            " hi.name_snap, hi.price_quoted, hi.price_mall, hi.qty, hi.mall_status,"
            " h.handoff_no, h.created_at, p.data_origin"
            " FROM handoff_items hi"
            " JOIN handoffs h ON h.handoff_id = hi.handoff_id"
            " LEFT JOIN products p ON p.product_code = hi.product_code"
            + where +
            " ORDER BY h.created_at DESC, h.handoff_id DESC, hi.line_no ASC"
            " LIMIT :lim OFFSET :off"), q_params).mappings().all()

        # 서랍의 "② 확인 기록" — 이 페이지에 실린 상품코드들의 전체 이력(페이지 무관).
        codes = list({r["product_code"] for r in rows if r["product_code"] is not None})
        history_by_code: dict = {}
        if codes:
            hist = conn.execute(text(
                "SELECT hi.product_code, hi.price_quoted, hi.price_mall, hi.mall_status,"
                " h.handoff_no, h.created_at"
                " FROM handoff_items hi JOIN handoffs h ON h.handoff_id = hi.handoff_id"
                " WHERE hi.product_code = ANY(:codes)"
                " ORDER BY hi.product_code, h.created_at DESC"),
                {"codes": codes}).mappings().all()
            for r in hist:
                history_by_code.setdefault(r["product_code"], []).append(r)

    # ── 표시용으로 정리 (여기부터는 DB 연결 밖 — 순수 가공) ──────────────
    items = []
    for r in rows:
        sm = _status_meta(r["mall_status"])
        is_demo = r["data_origin"] == "demo"
        # 시연용 상품이 실제 인계에 등장한 두 형태 다 "사고를 드러낸 자리"다 — 자체 검증
        # 중 실측(2026-08-15): HO-1001은 몰 값이 문자 그대로 0으로 읽힌 원본 사고 기록
        # (price_mall=0), HO-1002는 그 뒤 붙은 0원 가드가 잡아 "확인못함"으로 남은 기록.
        # 어느 쪽이든 시연용 상품이 실제 인계 라인에 섞였다는 같은 사실을 가리킨다.
        is_incident = is_demo and (r["mall_status"] == "확인못함" or r["price_mall"] == 0)
        part_label = (PART_LABELS.get(r["part_type"], r["part_type"]) if r["part_type"]
                      else ITEM_KIND_LABELS.get(r["item_kind"], r["item_kind"]))

        hist_list = []
        for h in history_by_code.get(r["product_code"], []):
            hsm = _status_meta(h["mall_status"])
            hist_list.append({
                "handoff_no": h["handoff_no"], "created_at": _kst(h["created_at"]),
                "desc": _hist_desc(h["price_quoted"], h["price_mall"], h["mall_status"], h["handoff_no"]),
                "status_label": hsm["label"], "status_symbol": hsm["symbol"],
                "status_cls": hsm["cls"],
            })

        items.append({
            "handoff_id": r["handoff_id"], "line_no": r["line_no"],
            "handoff_no": r["handoff_no"], "created_at_kst": _kst(r["created_at"]),
            "product_code": r["product_code"], "item_kind": r["item_kind"],
            "part_type": r["part_type"], "part_label": part_label,
            "name_snap": r["name_snap"], "qty": r["qty"],
            "price_quoted_fmt": _fmt(r["price_quoted"]) + "원",
            "price_mall_fmt": _mall_fmt(r["price_mall"]),
            "diff_fmt": _diff_fmt(r["price_quoted"], r["price_mall"]),
            "mall_status": r["mall_status"] or "", "status_label": sm["label"],
            "status_symbol": sm["symbol"], "status_cls": sm["cls"],
            "is_demo": is_demo, "origin_label": _origin_label(r["data_origin"], r["item_kind"]),
            "is_incident": is_incident,
            "history": hist_list,
        })

    def _page_href(p: int) -> str:
        qs = "" if status_filter not in STATUS_META else "&status=" + quote(status_filter)
        return "?page={}{}".format(p, qs)

    def _chip(key: str, label: str, count: int) -> dict:
        return {
            "key": key, "label": label, "count": count,
            "href": "?page=1" + ("" if key == "all" else "&status=" + quote(key)),
            "active": status_filter == key,
        }

    chips = [
        _chip("all", "전체", items_count),
        _chip("가격변동", "가격변동", changed),
        _chip("확인못함", "확인 못함", unmatched),
        _chip("확인됨", "일치", matched),
    ]

    unmatched_caption = "표본 {}건".format(_fmt(items_count))
    if unmatched_demo:
        unmatched_caption += " · 시연용 상품 {}건 포함".format(_fmt(unmatched_demo))

    kpi_cards = [
        {"label": "확인 회차", "value": _fmt(handoffs_count), "caption": "인계가 일어난 순간뿐"},
        {"label": "확인한 라인", "value": _fmt(items_count), "caption": "전 상품이 아닙니다"},
        {"label": "가격 어긋남", "value": "{:.1f}%".format(_pct(changed, items_count)),
         "caption": "표본 {}건 중 {}건".format(_fmt(items_count), _fmt(changed))},
        {"label": "확인 못함", "value": _fmt(unmatched), "caption": unmatched_caption},
        {"label": "확인해 본 상품", "value": "{:.1f}%".format(_pct(checked_products, total_products)),
         "caption": "전체 {}개 중 {}개".format(_fmt(total_products), _fmt(checked_products))},
    ]

    uncovered = max(0, total_products - checked_products)
    banner = {
        "has_any": handoffs_count > 0,
        "last_no": last["handoff_no"] if last else None,
        "last_time": _kst(last["created_at"]) if last else None,
        "uncovered_fmt": _fmt(uncovered),
    }

    start = 0 if total_rows == 0 else (page - 1) * PAGE_SIZE + 1
    end = min(page * PAGE_SIZE, total_rows)
    pager = {
        "page": page, "total_pages": total_pages, "total_rows_fmt": _fmt(total_rows),
        "start": start, "end": end,
        "prev_href": _page_href(page - 1) if page > 1 else None,
        "next_href": _page_href(page + 1) if page < total_pages else None,
    }

    return {
        "kpi_cards": kpi_cards, "banner": banner, "chips": chips,
        "items": items, "pager": pager,
        "sale_price_link": _sale_price_link(),
    }


@router.get("/mall-sync", response_class=HTMLResponse)
def mall_sync(request: Request, status: str = "all", page: int = 1) -> HTMLResponse:
    """쇼핑몰 동기화(ADM-HND-010). 조회 전용 — 실서비스에 쓰기 요청을 보내지 않는다.

    `status`는 확인됨/가격변동/확인못함 중 하나 또는 "all"만 받는다 — 그 밖의 값은
    조용히 "all"로 되돌린다(SQL은 바인드 파라미터라 인젝션 위험은 없지만, 오타 파라미터가
    "결과 0건"으로 조용히 보이는 것을 막는다). `page`는 1 미만이면 1로 올린다 —
    실제 상한(`total_pages`)은 필터가 정해지는 `_fetch` 안에서 클램프한다.
    """
    status_filter = status if status in STATUS_META else "all"
    data = _fetch(status_filter, max(1, page))

    # 서랍(우측 패널)이 행 클릭 시 참조할 상세 — 표와 같은 순서의 배열이라
    # `data-idx`(0부터, Jinja `loop.index0`)로 바로 찾는다. `<` 를 이스케이프해
    # name_snap 등에 `</script>` 가 섞여도 인라인 스크립트가 깨지지 않게 한다.
    detail_json = json.dumps(data["items"], ensure_ascii=False).replace("<", "\\u003c")

    return render(
        request, "admin/mall_sync.html.j2",
        screen_id="ADM-HND-010", domain="mall-sync",
        crumb_group="인계 · 성과", crumb_now="쇼핑몰 동기화",
        kpi_cards=data["kpi_cards"], banner=data["banner"], chips=data["chips"],
        items=data["items"], pager=data["pager"],
        sale_price_link=data["sale_price_link"], status_filter=status_filter,
        detail_json=detail_json,
    )
