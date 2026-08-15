"""웹 사양 채움(ADM-AI-020) 페이지 라우트 — `api/main.py`가 자동으로 싣는다(§discovery)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_ui_common import render

router = APIRouter(prefix="/admin2", tags=["admin-ui"])


@router.get("/spec-fill", response_class=HTMLResponse)
def spec_fill(request: Request) -> HTMLResponse:
    """웹 사양 채움(ADM-AI-020) — **1a안 재구축**(2026-08-15, `docs/design/spec-spec-fill.md`).

    2026-08-13에 B안(전용 실행 화면, decision-log P-10)으로 처음 섰다. B안의 원칙은
    지금도 유효하다 — 이 화면은 로직을 갖지 않는다: 실행은 기존 대시보드 큐
    (`POST /api/admin/dash/say`, `api/dash.py`)를 그대로 쓰고, 승인은 검수 화면
    (ADM-PRD-020)으로 필터 링크만 한다. 신규 로직은 집계 조회
    (`api/admin_spec_fill.py` — `status`·`field-context`·`runs`)뿐이다.

    2026-08-15 재구축 — Phoenix(Bootstrap) 벤더 자산을 전부 걷어냈다(admin2 37개
    템플릿 중 Phoenix를 실제로 로드하던 마지막 화면이었다, 회귀 [30]이 잡던
    `--phoenix-font-sans-serif` 재정의 포함). 지금은 admin2 공통 셸(`_admin2_shell.
    html.j2`) + `admin2.css` 토큰만 쓰는 네이티브 화면이고, `head_extra`/`foot_extra`는
    이 화면 자체 `<style>`/`<script>`만 싣는다(추가 벤더 자산 0개).
    """
    return render(request, "admin/spec_fill.html.j2",
                  screen_id="ADM-AI-020", domain="spec-fill",
                  crumb_group="AI 관리", crumb_now="웹 사양 채움")
