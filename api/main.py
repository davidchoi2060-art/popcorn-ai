"""팝콘PC AI 로컬 API — 수직 슬라이스 전용 (운영 배포 금지).

실행: .venv/Scripts/python -m uvicorn api.main:app --port 8000
목업은 같은 오리진에서 서빙(/admin/products.html 등) → CORS 불필요.
"""
import importlib
import pkgutil
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

# 미들웨어는 라우터가 아니라서 자동 탐색 대상이 아니다 — 명시적으로만 건다(순서가 계약).
from .auth import auth_middleware
from .customer_auth import member_middleware
from .db import engine

app = FastAPI(title="popcorn-pc-ai (local slice)")

# 인증 게이트. 미들웨어는 **등록 역순으로 실행**되므로 고객 게이트를 먼저 등록해
# 관리자 게이트가 바깥(먼저 실행)에 오게 한다 — 관리자 경로가 고객 세션 조회를 타지 않는다.
# 고객(슬라이스 38): /api/my/*는 세션 필요 · 상담·추천·주문은 게스트 허용
app.middleware("http")(member_middleware)
# 관리자(슬라이스 37): /api/admin/*는 세션+권한 필요(인증 엔드포인트 예외)
app.middleware("http")(auth_middleware)


@app.get("/api/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
# 라우터 자동 등록 (2026-08-13 사장님 지시 — 제작자 병렬화)
#
# ■ 왜 있는가
#   예전엔 API 모듈 하나(`api/admin_*.py`)를 새로 지을 때마다 **이 파일**에 import
#   한 줄 + `include_router` 한 줄을 추가해야 했다. admin2 페이지 라우트(`admin_ui.py`)
#   도 마찬가지였다 — 새 화면을 지을 때마다 그 한 파일을 같이 고쳤다. 제작자 둘이
#   동시에 화면을 지으면 이 두 "공유 파일"에서 매번 충돌해, 결국 한 번에 한 명만
#   돌리는 병목이 됐다(2026-08-13 사장님 지적).
#
#   그래서 `api/` 안의 각 모듈을 훑어 **module-level `router`(APIRouter)가 있으면
#   자동으로 싣는다.** 새 API·새 admin2 페이지 라우트는 새 `api/*.py` 파일 하나만
#   만들면 되고, 이 파일(main.py)을 더는 고치지 않는다. admin2 페이지 라우트도 같은
#   원리다 — `api/admin_ui_*.py`(화면 하나당 파일 하나, 각자 `router = APIRouter(
#   prefix="/admin2")`)가 이 스캔에 함께 걸린다. 공용 헬퍼(`admin_ui_common.py`
#   등)는 `router`가 없어 자동으로 빠진다 — 로직만 있는 모듈까지 실을 이유가 없다.
#
# ■ 조용한 실패를 만들지 않는다
#   임포트가 실패하면 **그대로 예외를 올려 서버 기동을 멈춘다**(삼키지 않는다). 이
#   저장소가 가장 자주 겪은 사고가 "화면·자산이 조용히 빠졌는데 아무도 몰랐다"
#   (`.claude/CANON.md` §1 — 좌측 메뉴 36화면 복제, 자산 404 등)라서, 라우터 하나가
#   빠지는 것도 시끄럽게 실패해야 한다. 무엇을 실었는지는 기동 로그 한 줄 +
#   `GET /api/health/routers`(조회 가능한 목록)로 확인한다.
def _discover_routers() -> list[tuple[str, APIRouter]]:
    here = Path(__file__).resolve().parent
    found: list[tuple[str, APIRouter]] = []
    for modinfo in sorted(pkgutil.iter_modules([str(here)]), key=lambda m: m.name):
        name = modinfo.name
        if name == "main" or name.startswith("_"):
            continue
        module = importlib.import_module(f"api.{name}")  # 실패하면 그대로 터진다 (의도)
        candidate = getattr(module, "router", None)
        if isinstance(candidate, APIRouter):
            found.append((name, candidate))
    return found


_DISCOVERED_ROUTERS = _discover_routers()

# admin2 페이지 라우트(`admin_ui_*`)는 **정적 캐치올 마운트보다 먼저** 걸려야 한다 —
# 뒤에 걸면 `/` 마운트가 먼저 잡아 404 다. 아래 for 루프가 정적 마운트(파일 맨 아래)
# 보다 앞에 있기만 하면 되고, 발견 순서(모듈명 알파벳순)는 서로 다른 prefix를 쓰는
# 라우터끼리는 영향이 없다 — 같은 경로를 두 라우터가 등록하는 경우만 순서가 의미를
# 갖는데, 지금 목록엔 그런 중복이 없다(제작 보고서에 라우트 전수 대조 기록).
for _mod_name, _router in _DISCOVERED_ROUTERS:
    app.include_router(_router)

print("[main] auto-included %d routers: %s" % (
    len(_DISCOVERED_ROUTERS), ", ".join(n for n, _ in _DISCOVERED_ROUTERS)))


@app.get("/api/health/routers", include_in_schema=False)
def _discovered_routers_debug():
    """기동 시 자동 등록된 라우터 모듈 목록 — 무엇이 실렸는지(빠졌는지) 조회용."""
    return {"count": len(_DISCOVERED_ROUTERS), "modules": [n for n, _ in _DISCOVERED_ROUTERS]}


# 정적 마운트는 반드시 마지막 — 먼저 걸면 /api/*가 캐치올에 잡힌다.
# mockups 전체를 마운트해야 admin/의 ../shared/su-icons.js 참조가 유지된다.
MOCKUPS_DIR = Path(__file__).resolve().parent.parent / "mockups"


class NoCacheStatic(StaticFiles):
    """HTML·JS·CSS를 브라우저가 캐시하지 않게 한다 (슬라이스 71).

    배포했는데 **옛 화면이 그대로 보이는 일**이 반복됐다. 실제 사고: 로그인 화면에
    비밀번호 칸을 넣어 배포했는데도 폰에서는 옛 화면이 떠서 로그인할 수 없었다.
    서버 파일은 새것이었고 브라우저가 옛 사본을 쥐고 있었다.

    개발·베타 단계에서는 캐시 이득보다 **"고쳤는데 안 바뀐다"는 혼선의 비용이 크다.**
    화면이 바뀌지 않는 것보다 조금 느린 편이 낫다. 이미지·폰트는 그대로 캐시한다.
    """

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.endswith((".html", ".js", ".css")) or path in ("", "/"):
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        return resp


# 디자인 토큰(`design-system/tokens.css`)도 서빙한다 (2026-08-05).
#
# 토큰 파일은 "단일 원천"으로 만들어 두고 **아무 화면도 불러오지 않고 있었다** —
# 서버가 `mockups/` 만 마운트해서 닿을 길이 없었기 때문이다. 그 결과
# `var(--font-num, monospace)` 가 전부 폴백으로 떨어져 숫자가 브라우저 기본
# 고정폭(Windows: Courier New)으로 그려졌다. 사용자가 "글자 간격이 이상하다"고
# 신고한 판매가 재산정 화면의 증상이 이것이다.
#
# 화면은 `../../design-system/tokens.css` 로 참조한다 — 브라우저가 루트 위로는
# 올라가지 않으므로 HTTP 에서는 `/design-system/tokens.css` 로 풀리고,
# `file://` 로 직접 열 때도 리포의 같은 파일을 가리킨다(둘 다 동작).
TOKENS_DIR = Path(__file__).resolve().parent.parent / "design-system"
if TOKENS_DIR.is_dir():
    app.mount("/design-system", NoCacheStatic(directory=TOKENS_DIR), name="design-system")


# ══════════════════════════════════════════════════════════════════════════
# 구 관리자 화면(`mockups/admin/*.html`) 접근 차단 (2026-08-13 사장님 지시)
#
# ■ 배경 — P-09(CLAUDE.md)는 구 `/admin/*.html` 37화면을 "백업용 동결"(수정·안내·
#   링크 연결 금지)로 정했는데, 아래 캐치올 정적 마운트가 여전히 그대로 서빙하고
#   있어 지금도 그냥 열렸다(규약과 실제가 어긋남). 파일은 지우지 않는다(P-09 "구
#   화면 파일 자체는 지우지 않는다") — **접근만** 막는다. 캐치올 마운트 자체를
#   고치는 대신, 그보다 먼저 잡히는 라우트로 `/admin/<이름>.html` 만 가로챈다
#   (Starlette는 등록 순서대로 매치하므로, 이 라우트가 아래 `app.mount("/", …)`
#   보다 앞에 있기만 하면 된다 — admin2 페이지 라우터를 마운트보다 먼저 건
#   §라우터 자동 등록과 같은 원리).
#
# ■ 왜 `/admin/` 전체가 아니라 `<이름>.html` 만인가
#
#   ⚠ 아래 「admin2 넷이 읽는다」는 2026-08-13 시점의 실측 기록이다 — 역사로 남긴다.
#   **2026-08-17 재실측: admin2 템플릿의 `/admin/assets/*`·`/admin/vendors/*` 참조는
#   0건이다**(전부 `_admin2_shell.html.j2` 상속 · 유일한 절대경로 참조는 폐기된
#   `_layout.html.j2` 뿐인데 아무 코드도 렌더하지 않는다). 지금 이 자산을 열어 두는
#   이유는 admin2가 아니라 **`mockups/admin/` 에 남은 구 화면 8개**(door인 my-profile
#   포함)가 상대경로 `assets/`·`vendors/` 로 각 36건씩 읽기 때문이다 — 그 8개가
#   admin2로 옮겨간 뒤에야 자산을 치울 수 있다.
#
#   (이하 2026-08-13 기록) — 실측(2026-08-13) 결과 admin2의
#   `templates/admin/{home,products,spec_fill,spec_standard}.html.j2` 넷은 **지금도
#   Phoenix 벤더 스택(Bootstrap·simplebar·feather-icons 등)과 파비콘을
#   `/admin/assets/*`·`/admin/vendors/*` 에서 그대로 읽는다**(폐기된 `_layout.html.j2`
#   가 쓰던 경로를 각 화면의 head_extra/foot_extra 블록으로 그대로 옮겨 실었다 —
#   `home.html.j2` 는 다름아닌 `/admin2/` 자기 자신이다). `/admin/` 전체를 막으면
#   **`/admin2/`(홈)·`/admin2/products`·`/admin2/spec-fill`·`/admin2/spec-standard`
#   가 스타일·스크립트 없이 깨진다** — `theme.css` 참조 누락으로 화면이 이틀간
#   스타일 없이 돌았던 슬라이스 100 사고와 같은 종류다. 그래서 이 라우트는
#   `/admin/<이름>.html`(슬래시 없는 단일 세그먼트 + `.html`)만 잡는다 —
#   `/admin/assets/...`·`/admin/vendors/...` 처럼 세그먼트가 더 있는 경로는 FastAPI
#   기본 문자열 컨버터가 `/` 를 허용하지 않아 이 패턴에 안 걸리고, 캐치올 마운트로
#   그대로 넘어가 계속 서빙된다.
#
# ■ 410 인 이유 — "없었다"(404)가 아니라 "치웠다"(410)가 사실이다. 본문은 admin2로
#   옮겨졌다는 안내 한 줄과 `/admin2/` 링크 하나뿐이다 — 화면 설계는 이 작업의
#   몫이 아니다.
_ADMIN_LEGACY_GONE_HTML = (
    "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
    "<title>이전된 화면</title></head><body>"
    "<p>이 화면은 admin2로 이전되었습니다. "
    "<a href=\"/admin2/\">admin2로 이동</a></p>"
    "</body></html>"
)


# ── 인증·세션 화면은 "치우는 대상"이 아니라 "들어오는 문"이다 (2026-08-13 긴급) ──
#
# ■ 무슨 사고였나 — 위 410 차단이 `/admin/login.html`까지 막아 **세션이 만료되면
#   아무도 재로그인할 수 없는 상태**가 됐다. 실측: admin2 화면 넷(reviews·
#   ai_integration·ai_usage_cost·build_map)이 401을 받으면 이 경로로 안내하는데,
#   그 안내가 막다른 길이었다(`/admin2/login`은 애초에 없다 — 404). 사장님이 막으라고
#   한 것은 "이전 관리 화면"(admin2로 대체된 콘텐츠 열람)이지 인증 진입점이 아니다.
#
# ■ 예외 셋 — 기준은 "이 화면이 없으면 사람이 이 시스템에 (재)진입할 방법이
#   원천적으로 없어지는가"다. admin2 쪽 페이지 라우트(`api/admin_ui_*.py`, 공용 헬퍼
#   `admin_ui_common.py` 제외 14개 — 기동 로그 "auto-included" 목록으로 실측)를
#   확인한 결과 operators·my-profile에 대응하는 admin2 화면이 아직 없다 — 대체 화면이
#   생기기 전까지는 이 셋이 유일한 경로다. `index.html`(구 대시보드)은 admin2에 이미
#   대체 화면(`admin_ui_home.py` → `/admin2/`)이 있어 예외에 넣지 않았다(그대로 410 →
#   "admin2로 이동" 안내 — 의도된 동작, P-09).
#     · login.html      로그인 화면 그 자체.
#     · my-profile.html 본인 비밀번호 변경(`POST /api/admin/auth/password`)의 유일한
#                        화면. login.html이 임시 비밀번호 로그인 뒤 "내 정보에서
#                        비밀번호를 바꿔 주세요"라고 안내하는 그 화면 — 막으면 그
#                        안내마저 막다른 길이 된다.
#     · operators.html  신규 운영자 **승인**(`POST /api/admin/operators/{id}/approve`)과
#                        **임시 비밀번호 발급**(`POST /api/admin/auth/operators/{id}/
#                        password`)의 유일한 화면. 자기 스스로 푸는 "비밀번호 찾기"가
#                        없으므로(`api/auth.py`), 비밀번호를 잊은 운영자의 유일한 복구
#                        경로이기도 하다 — owner가 여기서 재발급해야 들어올 수 있다.
#
# ■ 왜 안전한가 — 이 셋을 여는 것은 데이터를 여는 게 아니다. 세 화면 다 서버 렌더
#   데이터를 담지 않고, 화면이 부르는 API(`/api/admin/*`)는 `auth.py`의 미들웨어가
#   세션·권한을 **별도로** 검사한다(예: `/api/admin/operators`는 조회조차 owner 필요).
#   정적 HTML 껍데기를 열어도 API는 여전히 401/403을 준다 — 여기서 여는 것은 "문"이지
#   "방"이 아니다. 그래서 이 예외는 P-09("구화면 기능이 필요하면 admin2에 새로
#   짓는다")를 어기는 게 아니라 — 그 규칙이 다루는 대상(콘텐츠 화면)과 이 셋(진입·
#   복구 경로)이 다른 종류라는 판단이다.
# ■ 2026-08-17 전환 — `login`을 이 집합에서 뺐다 (셋 -> 둘)
#
#   ⚠ **위 「예외 셋」 서술은 2026-08-13 시점의 기록이다 — 지우지 않고 역사로 남긴다.**
#   («`/admin2/login`은 애초에 없다 — 404» 도 그때의 실측이다. 지금은 있다.) 지우면
#   다음 사람이 「원래 login 은 예외가 아니었다」로 읽고, 왜 열었다 닫았는지를 잃는다.
#   지금 유효한 것은 아래 집합과 이 블록이다.
#
#   **왜 뺄 수 있게 됐나** — 그때 이 예외를 만든 이유는 «대체 화면이 없어서»였다
#   (「이 화면이 없으면 사람이 이 시스템에 (재)진입할 방법이 원천적으로 없어지는가」).
#   `/admin2/login`(ADM-SYS-021, `api/admin_ui_login.py`)이 서고 확인자 검증을
#   통과하면서 그 전제가 사라졌다. 같은 커밋에서 `admin_ui_common._LOGIN_PAGE`도
#   그리로 옮겼으므로, 무세션으로 `/admin2/*` 어디를 열든 안내가 새 화면을 가리킨다.
#
#   ⚠ **`my-profile`·`operators`는 남긴다** — admin2 대체 화면이 아직 «없다»
#   (실측: `api/admin_ui_my_profile.py` 없음 · `admin_ui_operators_roles.py`는
#   `/admin2/operators`로 서 있으나 이 전환의 검증 대상이 아니었다). 위 기준이
#   그대로 적용되는 자리라 건드리지 않았다. 그 화면들이 검증을 통과하면 같은 방식으로
#   하나씩 뺀다 — **한 번에 셋을 닫지 않는다.**
#
#   ⚠ **옛 북마크는 이제 410을 받는다**(`/admin/login.html`). 막다른 길은 아니다 —
#   `/admin2/*` 어디를 열어도 401 안내가 새 화면으로 보내고, 410 본문도 admin2 로
#   안내한다. 캐시된 410 문제는 아래 함수의 no-cache 정책이 그대로 처리한다.
#
# ■ 2026-08-17 전환 — `operators`를 뺐다 (둘 -> 하나, 사장님 확정 ㉮)
#
#   위 「하나씩 뺀다」의 두 번째 적용이다. `/admin2/operators`(admin_ui_operators_roles.py)
#   가 대체 화면으로 서 있어 예외의 전제(「이 화면이 없으면 재진입 방법이 없는가」)가
#   사라졌다. `/admin/operators.html`도 이제 410을 받는다. `my-profile`만 남는다 —
#   여전히 admin2 대체가 없다(api/admin_ui_my_profile.py 없음, 2026-08-17 재확인).
#
#   같은 날 구 화면 파일도 옮겼다: admin2 대체가 없는 8화면(customers·my-profile·
#   orders·payments·refunds·reviews·shipping·stock-inbound)만 `mockups/admin/` 에
#   남기고, 나머지 29화면 + `_demo-products.html` 은 `_legacy/admin-phoenix/` 로
#   git mv(P-09 「파일은 지우지 않는다」 — 위치만 바꿈, 이력 보존). `_legacy/` 는
#   리포 루트라 아래 캐치올 마운트(MOCKUPS_DIR) 밖이다 — 서빙되지 않는다(실측).
#   이 라우트의 410은 파일 존재와 무관하므로 옮긴 뒤에도 그대로다.
_ADMIN_AUTH_DOOR_SCREENS = {"my-profile"}


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
@app.get("/admin/{page_name}.html", include_in_schema=False)
def _legacy_admin_page_gone(page_name: str = ""):
    """구 관리자 화면(`mockups/admin/*.html`) 접근 차단 — 위 블록 주석 참조.

    `/admin/assets/*`·`/admin/vendors/*` 는 이 경로 패턴에 걸리지 않아 캐치올
    마운트가 그대로 서빙한다 — `mockups/admin/` 에 남은 구 화면 8개가 상대경로로
    읽기 때문이다(admin2 참조는 0건 — 2026-08-17 재실측, 위 블록 주석 참조).

    `_ADMIN_AUTH_DOOR_SCREENS`(내 정보)는 차단하지 않고 실제
    파일을 그대로 서빙한다 — 위 "인증·세션 화면" 블록 참조. `NoCacheStatic`이 이
    캐치올 대신 여기서 먼저 잡히므로, 캐시 미적용 정책(no-cache)도 동일하게 직접
    건다 — 옛 로그인 화면이 브라우저에 캐시돼 새 배포가 안 보이는 사고(슬라이스 71)를
    이 경로에서도 반복하지 않는다.

    ■ 410 응답도 같은 정책이 필요하다 (2026-08-14 발견) — HTTP 규격상 410 Gone은
      기본적으로 캐시 가능한 상태코드다. 이 차단이 걸려 있던 동안(예: login.html이
      아직 예외에 없던 시점) 그 주소를 연 브라우저가 410을 저장했고, 차단을 풀어
      200을 돌려주기 시작한 뒤에도 브라우저가 캐시된 410을 계속 보여줘 재진입이
      막혔다(no-store로 강제 재요청해야만 200을 받았다). 그래서 위 door-screens
      분기와 **같은 두 헤더·같은 값**을 410에도 직접 건다 — 이 파일 안에서 캐시
      금지 방식을 두 가지로 두지 않는다.
    """
    if page_name in _ADMIN_AUTH_DOOR_SCREENS:
        resp = FileResponse(MOCKUPS_DIR / "admin" / f"{page_name}.html")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp
    resp = HTMLResponse(content=_ADMIN_LEGACY_GONE_HTML, status_code=410)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


app.mount("/", NoCacheStatic(directory=MOCKUPS_DIR, html=True), name="mockups")
