"""
FastAPI 應用程式主入口。

建立 FastAPI app、掛載所有 Router、設定靜態檔案服務、
CORS（開發模式）、全域例外處理。
"""

import logging
import os
import re
import secrets

from collections.abc import Callable, Awaitable
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.auth.router import router as auth_router
from backend.jobs.router import router as jobs_router
from backend.admin.router import router as admin_router
from backend.config import get_settings, Settings

logger: logging.Logger = logging.getLogger(__name__)

settings: Settings = get_settings()

app: FastAPI = FastAPI(
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
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


# ── 安全性標頭 (Security Headers) ──────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    實作安全性標頭的 Middleware。
    設定 CSP、X-Frame-Options、X-Content-Type-Options 以防禦常見攻擊。
    """

    # pylint: disable=too-few-public-methods
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        攔截請求並為回應加上安全性標頭，同時生成並注入 CSP Nonce。

        Args:
            request (Request): FastAPI 請求物件。
            call_next: 下一個中間件或路由處理常式。

        Returns:
            Response: 加上安全性標頭後的回應物件。
        """
        nonce = secrets.token_urlsafe(16)
        request.state.nonce = nonce

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Router 掛載 ────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(admin_router)

# ── 靜態檔案服務 ───────────────────────────────────────────────────────────────
_frontend_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.isdir(_frontend_dir):
    # 掛載 CSS / JS 靜態資源
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")
    _html_cache: dict[str, str] = {}

    def _serve_html_with_nonce(file_name: str, request: Request) -> HTMLResponse | RedirectResponse:
        """
        讀取 HTML 檔案並動態注入 CSP nonce。

        Args:
            file_name (str): 欲讀取的 HTML 檔案名稱。
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 HTML 回應，若檔案不存在則重導向。
        """
        content = _html_cache.get(file_name)
        if content is None:
            file_path = os.path.join(_frontend_dir, file_name)
            if not os.path.exists(file_path):
                return RedirectResponse(url="/")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if not settings.DEBUG:
                _html_cache[file_name] = content

        nonce = getattr(request.state, "nonce", "")
        if nonce:
            # 替換 script 與 style 標籤以動態注入 nonce
            # 使用更精確的正則匹配完整的開頭標籤，避免替換到屬性內文，並防範重複注入
            def _inject_nonce(match: re.Match) -> str:
                """
                替換正則匹配的 HTML 標籤，動態注入 CSP nonce。

                Args:
                    match (re.Match): 正規表示式的匹配物件。

                Returns:
                    str: 注入 nonce 屬性後的新標籤字串。
                """
                tag = match.group(1)
                attrs = match.group(2)
                if "nonce=" in attrs.lower():
                    return match.group(0)
                return f'<{tag} nonce="{nonce}"{attrs}>'

            content = re.sub(r"<(script|style)\b([^>]*)>", _inject_nonce, content, flags=re.IGNORECASE)

        return HTMLResponse(content=content)

    @app.get("/app.html", include_in_schema=False, response_model=None)
    def serve_app(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供前台爬蟲任務主介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 app.html 回應。
        """
        return _serve_html_with_nonce("app.html", request)

    @app.get("/admin.html", include_in_schema=False, response_model=None)
    def serve_admin(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供系統管理員後台介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 admin.html 回應。
        """
        return _serve_html_with_nonce("admin.html", request)

    @app.get("/set-password.html", include_in_schema=False, response_model=None)
    def serve_set_password(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供首次登入設定密碼介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 set-password.html 回應。
        """
        return _serve_html_with_nonce("set-password.html", request)

    @app.get("/", include_in_schema=False, response_model=None)
    def serve_index(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供登入與首頁介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 index.html 回應。
        """
        return _serve_html_with_nonce("index.html", request)

    @app.get("/index.html", include_in_schema=False)
    def redirect_index() -> RedirectResponse:
        """
        將 /index.html 重導向至根路徑。

        Returns:
            RedirectResponse: 重導向回應。
        """
        return RedirectResponse(url="/")


# ── 全域例外處理 ───────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    捕捉未處理的例外，回傳統一格式的錯誤回應（不暴露堆疊追蹤至 HTTP 回應）。

    Args:
        request (Request): FastAPI 請求物件。
        exc (Exception): 捕捉到的例外物件。

    Returns:
        JSONResponse: 包含錯誤細節的 500 JSON 回應。
    """
    logger.exception("未處理的例外（%s %s）: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "伺服器發生內部錯誤，請稍後再試。"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """
    處理 HTTP 例外。若是前端一般頁面 404 找不到，自動導向首頁；API 或靜態檔案錯誤則保留 JSON 回應。

    Args:
        request (Request): FastAPI 請求物件。
        exc (StarletteHTTPException): HTTP 例外物件。

    Returns:
        Response: 重導向或 JSON 錯誤回應。
    """
    if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/static/")):
        return RedirectResponse(url="/")

    # 其他 HTTP 錯誤（包含 API 404）則照常回傳 JSON
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# ── 健康檢查端點 ───────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """
    服務健康檢查端點（供 CI/CD 或 Load Balancer 使用）。

    Returns:
        dict[str, str]: 服務健康狀態。
    """
    return {"status": "ok"}
