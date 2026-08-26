"""운영자 설명서(ADM-MAN-010) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery).

사장님 지시(2026-08-25): 매뉴얼을 파일로 흩어 두지 말고 관리자 화면 「시스템」 계열
아래 새 메뉴로 넣어, 직원이 관리자 화면에서 바로 연다. 뒤이어 메뉴 배치가 한 번 더
바뀌었다 — 「시스템」 그룹 한 줄이 아니라 **최상위 「운영자 매뉴얼」 그룹**을 신설해
그 안에 기존 관리자 메뉴 구조(41화면)를 그대로 반영한다(구현은 `api/admin_nav.py`
`_manual_nav_group()` — 이 파일의 `MANUAL_SCREENS` 화이트리스트를 읽어간다. 순환
import 를 피하려고 그쪽은 **지연 import**로 이 모듈을 참조한다).

■ 두 라우트
    GET /admin2/manual            목차 — 41화면 중 몇 개에 설명서가 있는지(서버가 센다)
    GET /admin2/manual/{screen}   그 화면의 설명서. **{screen}은 화이트리스트만 통과한다**
                                    (`MANUAL_SCREENS`의 키) — URL 문자열을 그대로 파일
                                    경로에 쓰지 않는다(임의 파일 읽기 차단).

■ 본문은 다른 제작자가 조각으로 쓴다
  `docs/manual/screens/{fragment}.html` — `<body>` 없이 본문만(`<div class="wrap">…`).
  이 라우터는 그 파일을 **읽기만** 한다(화이트리스트에 있는 고정 파일명으로만 접근 —
  `{screen}` 파라미터가 파일명을 결정하지 않는다). 조각이 아직 없으면(또는 화면 자체가
  화이트리스트에 없으면) 500을 내지 않고 "아직 없음"을 보여준다(요구사항 ④).

■ 캡처 자산 위치 — 지시서는 `static/manual/shots/`였지만, 이 저장소에는 최상위
  `static/` 마운트 자체가 없다(`api/main.py`에 `/static` mount 0건, `static/` 디렉터리도
  없었다 — 2026-08-25 실측). 대신 `app.mount("/", NoCacheStatic(directory=MOCKUPS_DIR…))`
  가 `mockups/` 전체를 루트에서 서빙하고, `mockups/shared/`가 이미 admin2 공용 정적
  자산의 실제 관례다(`/shared/admin2/admin2.css`·`/shared/fonts/…` 등). 그래서 캡처는
  `mockups/shared/manual/shots/*.png`에 두고 `/shared/manual/shots/*.png`로 참조한다 —
  `api/main.py`(공유 파일, 이 작업 담당 밖)를 고치지 않고도 실제로 서빙된다. 하네스
  보고에 이 편차와 근거를 남겼다.

■ 권한 — 조회 전용 화면. 쓰기 API를 하나도 부르지 않는다. `api/auth.py`의
  `OWNER_WRITE_PREFIXES`는 `/api/admin/…` 쓰기 엔드포인트만 다루고 이 GET 페이지 라우트는
  포함하지 않으므로(실측), 로그인한 어떤 등급(조회 포함)도 그대로 볼 수 있다 — 별도
  권한 분기를 두지 않았다(요구사항: "조회 등급도 볼 수 있어야 한다 — 매뉴얼이니까").
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .admin_nav import counts as nav_counts, nav_for_screens
from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])

SCREEN_ID = "ADM-MAN-010"

FRAGMENTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "manual" / "screens"

# ── 화이트리스트 — 설명서 조각이 있(을 예정이)는 화면만 여기 등록한다 ──────────────
#
# key = URL 슬러그(`/admin2/manual/{key}`). **`{screen}` 경로 파라미터는 이 딕셔너리의
# 키와 완전 일치할 때만 통과한다** — 그 값(`fragment`)은 이 파일 안에 문자열 리터럴로
# 박혀 있어(사용자 입력이 아니다) 임의 파일 읽기가 될 수 없다.
#
# `order`는 "사용 빈도 순서로 만들어 갈 예정"(지시서)을 담는 자리 — 지금은 전부 비워
# 두고(딱 하나뿐이라 순서가 의미 없다), 다음 화면부터 채우면 목차가 그 순서로 보인다.
# `api/admin_nav.py`의 `_manual_nav_group()`도 이 딕셔너리를 그대로 읽는다(지연 import) —
# LNB의 "운영자 매뉴얼" 하위 항목과 이 화이트리스트가 다른 소스를 갖지 않는다.
MANUAL_SCREENS: dict[str, dict] = {
    # order 는 「많이 쓰는 것부터」 순서다(2026-08-25 사장님 결정). 근거는 활동 기록
    # 실측 — product_review 3,694 · product 2,941 · operator 2,664 · category 1,489 ·
    # ops 999. 대시보드는 그 기록이 없지만 직원이 로그인해 제일 먼저 보는 화면이라 넣었다.
    "reviews": {
        "fragment": "reviews.html",       # FRAGMENTS_DIR 안의 파일명(리터럴)
        "nav_href": "/admin2/reviews",    # api/admin_nav.py 항목과 대조하는 키
        "title": "상품 사양 검수",
        "screen_id": "ADM-PRD-020",
        "order": 1,
    },
    "products": {
        "fragment": "products.html",
        "nav_href": "/admin2/products",
        "title": "상품 관리",
        "screen_id": "ADM-PRD-010",
        "order": 2,
    },
    "operators": {
        "fragment": "operators.html",
        "nav_href": "/admin2/operators",
        "title": "운영자 · 권한",
        "screen_id": "ADM-SYS-020",
        "order": 3,
    },
    "categories": {
        "fragment": "categories.html",
        "nav_href": "/admin2/categories",
        "title": "상품 분류 관리",
        "screen_id": "ADM-CAT-010",   # api/admin_ui_product_category.py
        "order": 4,
    },
    "ops-settings": {
        "fragment": "ops-settings.html",
        "nav_href": "/admin2/ops-settings",
        "title": "오픈 단계 설정",
        "screen_id": "ADM-OPS-010",   # api/admin_ui_ops_stage.py
        "order": 5,
    },
    "dashboard": {
        "fragment": "dashboard.html",
        "nav_href": "/admin2/",
        "title": "대시보드",
        "screen_id": "ADM-DASH-010",
        "order": 6,
    },
}


def _fragment_path(slug: str) -> Path:
    return FRAGMENTS_DIR / MANUAL_SCREENS[slug]["fragment"]


def _toc_rows() -> list[dict]:
    """목차 행 — 화면 목록의 정본은 `api/admin_nav.py`다(여기서 손으로 적지 않는다).

    각 행에 "설명서 있음"을 매기는 기준은 ① 화이트리스트에 등록돼 있고 ② 그 조각
    파일이 실제로 존재하는 것, 둘 다다 — 등록만 해두고 아직 못 쓴 화면은 "아직 없음"
    그대로 보인다(요구사항 ④와 같은 원칙: 지어내지 않는다).
    """
    by_href = {v["nav_href"]: slug for slug, v in MANUAL_SCREENS.items()}
    rows = []
    # ⚠ `nav_for()`가 아니라 `nav_for_screens()`다 — `nav_for()`는 이 화면 자신이
    # LNB에 얹는 "운영자 매뉴얼" 합성 그룹까지 포함해서 돌려준다. 그걸 그대로 쓰면
    # 목차가 41개 화면이 아니라 41 + 42(매뉴얼 그룹 자신)를 세게 된다(실측으로 발견
    # — 처음엔 이 줄이 nav_for()였고 목차에 84행이 떴었다).
    for grp in nav_for_screens():
        for it in grp["items"]:
            slug = by_href.get(it["href"]) if it["href"] else None
            has = bool(slug) and _fragment_path(slug).exists()
            rows.append({
                "group": grp["title"],
                "label": it["label"],
                "href": it["href"],
                "slug": slug if has else None,
                "has_manual": has,
                "order": MANUAL_SCREENS[slug]["order"] if slug else None,
            })
    # 순서가 있는 것 먼저(오름차순) · 없는 것은 원래 메뉴 순서 그대로 뒤에(안정 정렬).
    rows.sort(key=lambda r: (r["order"] is None, r["order"] if r["order"] is not None else 0))
    return rows


@router.get("/manual", response_class=HTMLResponse)
def manual_index(request: Request) -> HTMLResponse:
    """운영자 설명서 목차(ADM-MAN-010).

    "몇 개 중 몇 개 준비됐는가"는 **여기서 서버가 센다** — 화면(JS)이 세지 않는다.
    분모는 실제로 존재하는 화면 수(`nav_counts()["new"]`, href가 있는 것)로 잡는다 —
    아직 안 지어진 화면(todo)은 설명서가 있을 수 없어 분모에 넣으면 뜻이 흐려진다.
    """
    rows = _toc_rows()
    ready = sum(1 for r in rows if r["has_manual"])
    return render(
        request, "admin/manual.html.j2",
        screen_id=SCREEN_ID, domain="manual",
        crumb_group="운영자 매뉴얼", crumb_now="목차",
        view="index", toc=rows, total_screens=nav_counts()["new"], ready_count=ready,
    )


@router.get("/manual/{screen}", response_class=HTMLResponse)
def manual_detail(request: Request, screen: str) -> HTMLResponse:
    """운영자 설명서 상세(ADM-MAN-010) — `screen`은 화이트리스트만 통과한다.

    화이트리스트 밖 문자열은 404(등록되지 않은 화면 — 임의 파일 읽기 차단).
    화이트리스트 «안»인데 조각 파일이 아직 없으면 500이 아니라 "아직 없음"을 200으로
    보여준다(요구사항 ④ — 이 화면이 낡지 않게).
    """
    entry = MANUAL_SCREENS.get(screen)
    if entry is None:
        raise HTTPException(status_code=404, detail="등록되지 않은 설명서입니다")

    path = _fragment_path(screen)
    fragment_html = None
    if path.exists():
        try:
            fragment_html = path.read_text(encoding="utf-8")
        except OSError:
            fragment_html = None  # 읽기 실패도 "아직 없음"과 같은 방식으로 보여준다(500 금지)

    return render(
        request, "admin/manual.html.j2",
        screen_id=SCREEN_ID, domain="manual",
        crumb_group="운영자 매뉴얼", crumb_now=entry["title"],
        view="detail", entry=entry, fragment_html=fragment_html,
    )
