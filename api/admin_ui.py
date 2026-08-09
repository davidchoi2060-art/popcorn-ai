"""운영자 시스템 재구축 (Jinja2 서버 렌더) — 2026-08-09 착수.

**기존 `mockups/admin/` 37화면은 그대로 둔다.** 이것은 이관이 아니라 **병행 신축**이다
(사용자 결정 2026-08-09). 기존 화면은 계속 `/admin/*` 에서 돌고, 새 시스템은 `/admin2/*`
에서 따로 자란다. 다 자라면 그때 갈아탄다 — 그전까지 둘은 서로를 깨뜨리지 않는다.

  기존 : /admin/products.html   (정적 파일 37개, mockups/ 캐치올 마운트)
  신규 : /admin2/               (여기)

**왜 다시 짓는가** — 지금 37화면은 슬라이스 1~104를 거치며 하나씩 쌓인 것이지 동선에서
도출된 적이 없다. 좌측 메뉴가 전부 명사(상품·가격·추천 설정·주문·회원·시스템)인 것이
그 증거다. 데이터 객체별 CRUD 구성이지 운영자가 하는 **일** 기준이 아니라서,
"이 상품이 왜 추천에 안 나오지?" 하나에 화면 다섯을 오가야 한다.

**경로 접두어가 `/admin2` 인 이유**: `/admin` 은 이미 정적 마운트가 잡고 있다.
그리고 **이 라우터는 `api/main.py` 의 캐치올 마운트보다 먼저 include 돼야 한다** —
뒤에 걸면 `/` 마운트가 먼저 잡아 404 를 낸다.

인증: 걸지 않는다. 기존 정적 화면도 안 걸려 있고(막는 것은 `/api/admin/*` 미들웨어다),
같은 조건이어야 둘을 나란히 비교할 수 있다.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .admin_nav import counts as nav_counts, nav_for

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


def _render(request: Request, template: str, **ctx) -> HTMLResponse:  # noqa: D401
    """템플릿을 렌더하고 캐시를 막는다.

    캐시 정책은 정적 쪽 `NoCacheStatic` 과 같아야 한다 — 한쪽만 캐시하면
    "고쳤는데 안 바뀐다"가 한쪽에서만 일어나 비교가 오염된다.
    """
    # 좌측 메뉴는 **서버가 그린다**(admin_nav 가 단일 원천). 레이아웃이 한 벌이라
    # 모든 화면이 자동으로 같은 메뉴를 받는다 — 화면마다 복제되던 병이 구조적으로 사라진다.
    ctx.setdefault("nav", nav_for(request.url.path))
    ctx.setdefault("nav_counts", nav_counts())
    resp = templates.TemplateResponse(request, template, ctx)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


# 재구축 현황 — **화면이 지어내지 않게 여기서 사실만 준다.**
# 화면 하나가 실제로 서면 BUILT 로 옮긴다. 옮기지 않은 채 목록만 늘리면
# 이 현황판이 곧 거짓말이 된다(기존 화면들이 그랬다).
BUILT = [
    {"href": "/admin2/products", "label": "상품 관리",
     "note": "A/B 시험판 — 기존 /admin/products.html 과 같은 API·같은 배선"},
]

NEXT_STEPS = [
    "분석 — API 56개 모듈을 '일' 단위로 재그룹하고, 일 ↔ 현재 37화면 대조표를 만든다",
    "새 IA 제안 — 화면 목록과 그룹. 통합·분리·신설·폐기 표기. 승인 지점",
    "기준 화면 1개를 끝까지 — 스택(Jinja2)도 여기서 확정",
    "확산 — 회귀의 마크업 검사분을 렌더 결과 검사로 옮긴다",
]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """재구축 현황판. 화면이 늘면 이 자리가 새 대시보드가 된다."""
    return _render(request, "admin/home.html.j2", built=BUILT, next_steps=NEXT_STEPS)


@router.get("/products", response_class=HTMLResponse)
def products(request: Request) -> HTMLResponse:
    """상품 관리(ADM-PRD-010) — 기존 `/admin/products.html` 의 대조군."""
    return _render(request, "admin/products.html.j2")
