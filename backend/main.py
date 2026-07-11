"""
FastAPI 應用程式主入口。

建立 FastAPI app、掛載所有 Router、設定靜態檔案服務、
CORS（開發模式）、全域例外處理。
"""

import asyncio
import logging
import os
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from backend.admin.router import router as admin_router
from backend.auth.router import router as auth_router
from backend.auth.service import register_auth_events
from backend.config import Settings, get_settings
from backend.jobs.router import router as jobs_router
from backend.jobs.services.events import register_job_events
from backend.jobs.services.poller import job_progress_poller
from backend.jobs.services.scheduler import check_and_spawn_queued_jobs

logger: logging.Logger = logging.getLogger(__name__)

settings: Settings = get_settings()


SCHEDULER_INTERVAL_SEC = 5
MAX_BACKOFF_SEC = 640


async def _run_scheduler_loop() -> None:
    """背景排程器迴圈，喚醒 queued 任務"""
    error_count = 0
    while True:
        try:
            # 任務操作包含資料庫讀寫與子程序啟動，應丟入 Thread Pool 避免阻塞 Event Loop
            await asyncio.to_thread(check_and_spawn_queued_jobs)
            error_count = 0  # 執行成功，重置計數
        except asyncio.CancelledError:
            break
        except SQLAlchemyError as e:
            error_count += 1
            logger.error("背景排程器存取資料庫時發生錯誤: %s", e)
        except RuntimeError as e:
            error_count += 1
            logger.error("背景排程器建立執行緒或非同步執行時發生系統錯誤: %s", e)
        except ValueError as e:
            error_count += 1
            logger.error("背景排程器資料狀態或參數錯誤: %s", e)
        except OSError as e:
            error_count += 1
            logger.error("背景排程器子程序或系統資源錯誤: %s", e)
        except Exception as e:  # pylint: disable=broad-except
            error_count += 1
            logger.exception("背景排程器執行時發生未預期錯誤: %s", e)

        if error_count > 0:
            # 隨著錯誤次數增加，休眠時間成指數級延長 (Exponential Backoff)，直到達到 MAX_BACKOFF_SEC
            sleep_time = min(SCHEDULER_INTERVAL_SEC * (2 ** (error_count - 1)), MAX_BACKOFF_SEC)
            if error_count >= 5:
                logger.critical(
                    "背景排程器連續發生 %d 次錯誤，休眠時間延長為 %d 秒以避免癱瘓系統！", error_count, sleep_time
                )
            await asyncio.sleep(sleep_time)
        else:
            await asyncio.sleep(SCHEDULER_INTERVAL_SEC)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):  # pylint: disable=unused-argument
    """管理 FastAPI 生命週期（啟動與關閉）

    Yields:
        None
    """
    logger.info("初始化系統事件監聽器...")
    register_auth_events()
    register_job_events()
    # pylint: disable=import-outside-toplevel
    from backend.admin.services.audit import subscribe_to_audit_events

    subscribe_to_audit_events()

    # 在此加入 Notifier 事件監聽
    # pylint: disable=import-outside-toplevel
    from backend.deps import get_job_manager
    from backend.jobs.services.notifier import subscribe_to_events

    manager = get_job_manager()
    subscribe_to_events(manager.session_factory)

    logger.info("啟動背景排程器任務...")
    scheduler_task = asyncio.create_task(_run_scheduler_loop())

    await job_progress_poller.start()

    yield

    logger.info("關閉背景輪詢器與排程器任務...")
    await job_progress_poller.stop()
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


app: FastAPI = FastAPI(
    title=settings.APP_NAME,
    description="外部連結檢查爬蟲 Web 服務 API",
    version="2.0.0",
    lifespan=app_lifespan,
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
class SecurityHeadersMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    實作安全性標頭的 Middleware。
    設定 CSP、X-Frame-Options、X-Content-Type-Options 以防禦常見攻擊。
    """

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

            content = re.sub(r"<(script|style)(?=[\s>])([^>]*)>", _inject_nonce, content, flags=re.IGNORECASE)

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

    @app.get("/help.html", include_in_schema=False, response_model=None)
    def serve_help(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供說明與教學頁面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 help.html 回應。
        """
        return _serve_html_with_nonce("help.html", request)

    @app.get("/faq.html", include_in_schema=False, response_model=None)
    def serve_faq(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供常見問答頁面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 faq.html 回應。
        """
        return _serve_html_with_nonce("faq.html", request)

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

    @app.get("/forgot-password.html", include_in_schema=False, response_model=None)
    def serve_forgot_password(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供忘記密碼申請介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 forgot-password.html 回應。
        """
        return _serve_html_with_nonce("forgot-password.html", request)

    @app.get("/reset-password.html", include_in_schema=False, response_model=None)
    def serve_reset_password(request: Request) -> HTMLResponse | RedirectResponse:
        """
        提供重設密碼介面。

        Args:
            request (Request): FastAPI 請求物件。

        Returns:
            HTMLResponse | RedirectResponse: 注入 nonce 後的 reset-password.html 回應。
        """
        return _serve_html_with_nonce("reset-password.html", request)

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
