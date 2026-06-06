"""
FastAPI 應用程式主入口。

建立 FastAPI app、掛載所有 Router、設定靜態檔案服務、
CORS（開發模式）、全域例外處理。
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.auth.router import router as auth_router
from backend.jobs.router import router as jobs_router
from backend.admin.router import router as admin_router
from backend.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="外部連結檢查爬蟲 Web 服務 API",
    version="2.0.0",
    # 生產環境關閉自動文件（避免 API 暴露）
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

# ── CORS（僅限開發環境）─────────────────────────────────────────────────────────
if settings.DEBUG:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Router 掛載 ────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(admin_router)

# ── 靜態檔案服務 ───────────────────────────────────────────────────────────────
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.isdir(_frontend_dir):
    # 掛載 CSS / JS 靜態資源
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")

    @app.get("/app.html", include_in_schema=False)
    async def serve_app():
        return FileResponse(os.path.join(_frontend_dir, "app.html"))

    @app.get("/admin.html", include_in_schema=False)
    async def serve_admin():
        return FileResponse(os.path.join(_frontend_dir, "admin.html"))

    @app.get("/set-password.html", include_in_schema=False)
    async def serve_set_password():
        return FileResponse(os.path.join(_frontend_dir, "set-password.html"))

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(os.path.join(_frontend_dir, "index.html"))


# ── 全域例外處理 ───────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕捉未處理的例外，回傳統一格式的錯誤回應（不暴露堆疊追蹤至 HTTP 回應）。"""
    logger.exception("未處理的例外（%s %s）: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "伺服器發生內部錯誤，請稍後再試。"},
    )


# ── 健康檢查端點 ───────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """服務健康檢查端點（供 CI/CD 或 Load Balancer 使用）。"""
    return {"status": "ok"}
