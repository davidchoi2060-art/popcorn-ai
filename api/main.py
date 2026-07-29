"""팝콘PC AI 로컬 API — 수직 슬라이스 전용 (운영 배포 금지).

실행: .venv/Scripts/python -m uvicorn api.main:app --port 8000
목업은 같은 오리진에서 서빙(/admin/products.html 등) → CORS 불필요.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .admin_activity_logs import router as admin_activity_logs_router
from .admin_dashboard import router as admin_dashboard_router
from .admin_engine_rules import router as admin_engine_rules_router
from .admin_usage_floors import router as admin_usage_floors_router
from .admin_member_reviews import router as admin_member_reviews_router
from .admin_members import router as admin_members_router
from .admin_operators import router as admin_operators_router
from .admin_profile import router as admin_profile_router
from .admin_imports import router as admin_imports_router
from .admin_ops import router as admin_ops_router
from .admin_orders import router as admin_orders_router
from .admin_refunds import router as admin_refunds_router
from .admin_payments import router as admin_payments_router
from .admin_pool import router as admin_pool_router
from .admin_price_import import router as admin_price_import_router
from .admin_price_history import router as admin_price_history_router
from .admin_price_review import router as admin_price_review_router
from .admin_products import router as admin_products_router
from .admin_sessions import router as admin_sessions_router
from .admin_sourcing import router as admin_sourcing_router
from .admin_stock import router as admin_stock_router
from .admin_suppliers import router as admin_suppliers_router
from .admin_swap_logs import router as admin_swap_logs_router
from .admin_system import router as admin_system_router
from .admin_reviews import router as admin_reviews_router
from .candidates import router as candidates_router
from .admin_catalog_import import router as admin_catalog_import_router
from .admin_spec_fields import router as admin_spec_fields_router
from .clicks import router as clicks_router
from .my_account import router as my_account_router
from .my_orders import router as my_orders_router
from .my_payments import router as my_payments_router
from .orders import router as orders_router
from .recommend import router as recommend_router
from .swap import router as swap_router
from .auth import auth_middleware, router as auth_router
from .customer_auth import member_middleware, router as customer_auth_router
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


app.include_router(auth_router)
app.include_router(customer_auth_router)
app.include_router(admin_operators_router)
app.include_router(admin_profile_router)
app.include_router(admin_suppliers_router)
app.include_router(admin_ops_router)
app.include_router(admin_imports_router)
app.include_router(admin_products_router)
app.include_router(admin_reviews_router)
app.include_router(admin_orders_router)
app.include_router(admin_refunds_router)
app.include_router(admin_payments_router)
app.include_router(admin_activity_logs_router)
app.include_router(admin_member_reviews_router)
app.include_router(admin_members_router)
app.include_router(admin_price_import_router)
app.include_router(admin_price_review_router)
app.include_router(admin_stock_router)
app.include_router(admin_swap_logs_router)
app.include_router(admin_pool_router)
app.include_router(admin_sessions_router)
app.include_router(admin_price_history_router)
app.include_router(admin_dashboard_router)
app.include_router(admin_engine_rules_router)
app.include_router(admin_usage_floors_router)
app.include_router(admin_system_router)
app.include_router(admin_sourcing_router)
app.include_router(candidates_router)
app.include_router(admin_catalog_import_router)
app.include_router(admin_spec_fields_router)
app.include_router(clicks_router)
app.include_router(recommend_router)
app.include_router(orders_router)
app.include_router(swap_router)
app.include_router(my_orders_router)
app.include_router(my_payments_router)
app.include_router(my_account_router)

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


app.mount("/", NoCacheStatic(directory=MOCKUPS_DIR, html=True), name="mockups")
