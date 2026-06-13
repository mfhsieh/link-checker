"""
身分驗證 API 路由。

實作 §13.1 定義的五個身分驗證端點：
- POST /api/auth/login      — 一般登入或首次邀請登入
- POST /api/auth/set-password — 首次登入強制設密
- POST /api/auth/logout     — 登出
- GET  /api/auth/me         — 取得當前使用者資訊
- PATCH /api/auth/password  — 修改密碼

Session Token 以 HTTP-only Cookie 承載，不允許前端 JS 直接存取。
所有狀態變更端點（POST / PATCH）均驗證 CSRF Token。
"""

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session as DBSession

from backend.auth import service as auth_service
from backend.auth.models import Session as AuthSession
from backend.auth.models import User
from backend.config import get_settings
from backend.deps import (
    get_auth_db,
    get_current_session,
    get_current_user,
    require_csrf,
)

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response Schema ──────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """登入請求的 Schema。"""

    email: EmailStr
    password: str | None = None
    token: str | None = None  # 邀請 UUID（首次登入用）

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """
        將信箱轉為小寫去空白。

        Args:
            v (str): 原始信箱字串。

        Returns:
            str: 處理後的信箱字串。
        """
        return v.strip().lower()


class SetPasswordRequest(BaseModel):
    """首次登入設定密碼的 Schema。"""

    new_password: str


class ChangePasswordRequest(BaseModel):
    """修改密碼的 Schema。"""

    current_password: str
    new_password: str


# ── 輔助：設定 Session Cookie 與 CSRF Cookie ────────────────────────────────────


def _set_session_cookie(response: Response, token: str) -> None:
    """
    設定 HTTP-only Session Cookie。

    Args:
        response (Response): FastAPI 回應物件。
        token (str): 欲設定的 Session Token。
    """
    settings = get_settings()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=not settings.DEBUG,  # 生產環境強制 Secure
        samesite="strict",
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def _set_csrf_cookie(response: Response, token: str) -> None:
    """
    設定可讓 JS 讀取的 CSRF Cookie（非 HTTP-only）。

    Args:
        response (Response): FastAPI 回應物件。
        token (str): 欲設定的 CSRF Token。
    """
    settings = get_settings()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # JS 需要能讀取此值以放入請求標頭
        secure=not settings.DEBUG,
        samesite="strict",
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    """
    清除 Session Cookie 與 CSRF Cookie。

    Args:
        response (Response): FastAPI 回應物件。
    """
    settings = get_settings()
    response.delete_cookie(
        settings.SESSION_COOKIE_NAME,
        path="/",
        secure=not settings.DEBUG,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.CSRF_COOKIE_NAME,
        path="/",
        secure=not settings.DEBUG,
        httponly=False,
        samesite="strict",
    )


# ── 端點實作 ────────────────────────────────────────────────────────────────────


@router.post("/login", status_code=status.HTTP_200_OK)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_auth_db),
) -> dict[str, object]:
    """
    使用者登入。

    支援兩種登入模式：
    1. 首次登入：提供 email + token（邀請 UUID）
    2. 一般登入：提供 email + password

    登入成功後設定 HTTP-only Session Cookie 與 CSRF Cookie。

    Args:
        body (LoginRequest): 登入請求內容，包含 email、密碼或邀請 token。
        request (Request): FastAPI 請求物件。
        response (Response): FastAPI 回應物件，用於設定 Cookie。
        background_tasks (BackgroundTasks): 用於背景執行 GC。
        db (DBSession): Auth 資料庫 Session。

    Returns:
        dict[str, object]: 登入結果，包含是否為首次登入 (is_first_login) 與使用者資訊 (user)。

    Raises:
        HTTPException 400: 若參數不完整（同時提供或同時缺少密碼與 token）。
        HTTPException 401: 若驗證失敗或帳號異常。
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        if body.token and not body.password:
            # 首次登入（邀請 UUID 驗證）
            result = auth_service.authenticate_with_invitation(
                db,
                body.email,
                body.token,
                ip=client_ip,
                user_agent=user_agent,
            )
        elif body.password and not body.token:
            # 一般密碼登入
            result = auth_service.authenticate_with_password(
                db,
                body.email,
                body.password,
                ip=client_ip,
                user_agent=user_agent,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="請提供 password（一般登入）或 token（首次邀請登入）其中一項。",
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e

    session_token = result["session_token"]
    csrf_token = secrets.token_urlsafe(32)

    _set_session_cookie(response, session_token)
    _set_csrf_cookie(response, csrf_token)

    # 觸發背景 GC 清理過期 Session
    background_tasks.add_task(auth_service.run_session_gc_task)

    return {
        "is_first_login": result["is_first_login"],
        "user": result["user"],
    }


@router.post("/set-password", status_code=status.HTTP_200_OK)
def set_password(
    body: SetPasswordRequest,
    db: DBSession = Depends(get_auth_db),
    current_session: AuthSession = Depends(get_current_session),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    首次登入後的強制密碼設定。

    只允許 is_first_login=True 的 Session 呼叫此端點。
    密碼設定完成後，Session 狀態轉為正常，帳號啟用。

    Args:
        body (SetPasswordRequest): 新密碼設定請求。
        db (DBSession): Auth 資料庫 Session。
        current_session (AuthSession): 當前的 Session 物件。
        _csrf (None): CSRF 防禦依賴。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 403: 若當前 Session 不是首次登入 Session。
        HTTPException 422: 若新密碼不符合安全強度規範。
    """
    if not current_session.is_first_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="此端點僅供首次登入設密使用。",
        )

    try:
        auth_service.set_first_password(db, current_session, body.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return {"message": "密碼設定成功，帳號已啟用。"}


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    response: Response,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_auth_db),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    登出並清除 Session Token。

    Args:
        response (Response): FastAPI 回應物件，用於清除 Cookie。
        request (Request): FastAPI 請求物件，用於讀取 Cookie。
        background_tasks (BackgroundTasks): 用於背景執行 GC。
        db (DBSession): Auth DB Session。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。
    """
    settings = get_settings()
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    client_ip = request.client.host if request.client else None
    if raw_token:
        auth_service.invalidate_session(db, raw_token, ip=client_ip)

    _clear_auth_cookies(response)

    # 觸發背景 GC 清理過期 Session
    background_tasks.add_task(auth_service.run_session_gc_task)

    return {"message": "已成功登出。"}


@router.get("/me", status_code=status.HTTP_200_OK)
def get_me(
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """
    取得當前已登入使用者的基本資訊。

    Args:
        current_user (User): 當前登入的使用者物件。

    Returns:
        dict[str, object]: 使用者的基本資訊。
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "status": current_user.status,
        "last_login_at": (current_user.last_login_at.isoformat() if current_user.last_login_at else None),
    }


@router.patch("/password", status_code=status.HTTP_200_OK)
def change_password(
    body: ChangePasswordRequest,
    db: DBSession = Depends(get_auth_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    已登入使用者修改密碼（需提供現有密碼進行驗證）。

    Args:
        body (ChangePasswordRequest): 變更密碼的請求內容。
        db (DBSession): Auth DB Session。
        current_user (User): 當前登入的使用者物件。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 422: 現有密碼錯誤或新密碼不符合安全標準時拋出。
    """
    try:
        auth_service.change_password(
            db,
            current_user.id,
            body.current_password,
            body.new_password,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return {"message": "密碼已成功更新。"}
