"""팝콘PC AI 로컬 API — 수직 슬라이스 전용 (운영 배포 금지).

실행: .venv/Scripts/python -m uvicorn api.main:app --port 8000
목업은 같은 오리진에서 서빙(/admin/products.html 등) → CORS 불필요.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .admin_products import router as admin_products_router
from .db import engine

app = FastAPI(title="popcorn-pc-ai (local slice)")


@app.get("/api/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


app.include_router(admin_products_router)

# 정적 마운트는 반드시 마지막 — 먼저 걸면 /api/*가 캐치올에 잡힌다.
# mockups 전체를 마운트해야 admin/의 ../shared/su-icons.js 참조가 유지된다.
MOCKUPS_DIR = Path(__file__).resolve().parent.parent / "mockups"
app.mount("/", StaticFiles(directory=MOCKUPS_DIR, html=True), name="mockups")
