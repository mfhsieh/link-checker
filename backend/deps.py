"""
FastAPI 共用依賴注入模組。

提供以下依賴函式供所有路由使用：
- get_auth_db()       — 取得 Auth DB Session（每個請求一個）
- get_crawler_db()    — 取得 Crawler DB Session（每個請求一個）
- get_current_session() — 從 Cookie 解析並驗證 Session
- get_current_user()  — 從 Session 取得 User 物件（需一般登入狀態）
- require_admin()     — 驗證當前使用者具備 admin 角色
- require_csrf()      — 驗證 CSRF Token（POST/PATCH/DELETE 必用）
"""

import logging
import secrets
import threading
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from backend.auth.db import get_auth_session_local
from backend.auth.models import Session as AuthSession
from backend.auth.models import User
from backend.config import get_settings
from crawler.manager import JobManager

logger: logging.Logger = logging.getLogger(__name__)


# ── Auth DB 依賴 ────────────────────────────────────────────────────────────────


def get_auth_db() -> Generator[DBSession, None, None]:
    """
    取得 Auth DB Session 的 FastAPI 依賴函式。

    使用 try/finally 確保 Session 在請求結束後自動關閉。

    Yields:
        DBSession: Auth DB SQLAlchemy Session。
    """
    session_factory = get_auth_session_local()
    with session_factory() as db:
        yield db


# ── Crawler DB 依賴（透過 JobManager）──────────────────────────────────────────

_JOB_MANAGER: JobManager | None = None
_JOB_MANAGER_LOCK: threading.Lock = threading.Lock()


def get_job_manager() -> JobManager:
    """
    提供全域單一實例的 JobManager。

    Returns:
        JobManager: 系統全域唯一的 JobManager 實例。
    """
    global _JOB_MANAGER  # pylint: disable=global-statement
    if _JOB_MANAGER is None:
        with _JOB_MANAGER_LOCK:
            if _JOB_MANAGER is None:
                settings = get_settings()

                # pylint: disable=import-outside-toplevel
                from backend.jobs.services.notifier import send_job_status_notification

                _JOB_MANAGER = JobManager(
                    db_url=settings.CRAWLER_DB_URL,
                    status_callback=lambda j_id, stat: (
                        send_job_status_notification(_JOB_MANAGER.session_factory, j_id, stat) if _JOB_MANAGER else None
                    ),
                )
    return _JOB_MANAGER


def get_crawler_db() -> Generator[DBSession, None, None]:
    """
    取得 Crawler DB Session 的 FastAPI 依賴函式。

    透過 JobManager 的 SessionLocal 取得 Session。

    Yields:
        DBSession: Crawler DB SQLAlchemy Session。
    """
    manager = get_job_manager()
    with manager.session_factory() as db:
        yield db


# ── Session / 使用者依賴 ────────────────────────────────────────────────────────


def get_current_session(
    request: Request,
    db: DBSession = Depends(get_auth_db),
) -> AuthSession:
    """
    從 Cookie 中解析並驗證 Session Token。

    此依賴允許 is_first_login=True 的首次登入 Session 通過，
    供 /api/auth/set-password 使用。

    Args:
        request (Request): FastAPI 請求物件。
        db (DBSession): Auth DB Session。

    Returns:
        AuthSession: 有效的 Session 物件。

    Raises:
        HTTPException 401: 若 Cookie 不存在或 Session 已過期。
    """
    # 避免循環匯入
    # pylint: disable=import-outside-toplevel, cyclic-import
    from backend.auth import service as auth_service

    settings = get_settings()
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登入或 Session 已過期，請重新登入。",
        )

    session = auth_service.get_session_by_token(db, raw_token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session 已過期或無效，請重新登入。",
        )

    # Sliding Window：刷新有效期
    auth_service.refresh_session(db, session)
    return session


def get_current_user(
    session: AuthSession = Depends(get_current_session),
    db: DBSession = Depends(get_auth_db),
) -> User:
    """
    從 Session 取得當前已登入的使用者。

    此依賴要求使用者已完成密碼設定（is_first_login=False），
    並且帳號狀態為 active。

    Args:
        session (AuthSession): 有效的 Session。
        db (DBSession): Auth DB Session。

    Returns:
        User: 當前使用者物件。

    Raises:
        HTTPException 401: 帳號不存在或狀態異常。
        HTTPException 403: 首次登入 Session 嘗試存取功能頁面。
    """
    if session.is_first_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="請先完成密碼設定才能使用系統功能。",
        )

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="使用者不存在。",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"帳號狀態異常（{user.status}），請聯繫管理員。",
        )

    return user


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    驗證當前使用者具備 admin 角色。

    Args:
        current_user (User): 當前登入使用者。

    Returns:
        User: Admin 使用者物件。

    Raises:
        HTTPException 403: 使用者不具備 admin 角色。
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此操作需要管理員權限。",
        )
    return current_user


# ── CSRF 防禦依賴 ───────────────────────────────────────────────────────────────


def require_csrf(request: Request) -> None:
    """
    驗證 CSRF Token（Double Submit Cookie 模式）。

    前端需從 CSRF Cookie 讀取 token 值，並放入 X-CSRF-Token 請求標頭。
    後端驗證標頭值與 Cookie 值是否一致。

    應用於所有狀態變更類請求（POST / PATCH / DELETE）。

    Args:
        request (Request): FastAPI 請求物件。

    Raises:
        HTTPException 403: CSRF Token 不存在或不一致。
    """
    settings = get_settings()
    csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
    csrf_header = request.headers.get(settings.CSRF_TOKEN_HEADER)

    if not csrf_cookie or not csrf_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF Token 驗證失敗：Token 缺失。",
        )

    if not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF Token 驗證失敗：Token 不一致。",
        )
