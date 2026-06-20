"""
後台管理 API 路由。

實作 §13.4 定義的後台管理端點（所有端點需 Admin 角色）：
使用者管理、任務監控、全域配置、SMTP 測試、操作日誌查閱。
"""

import copy
import json
import logging
import os
from datetime import datetime

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy.orm import Session as DBSession

from backend.auth import service as auth_service
from backend.auth.models import AuthLog, User
from backend.config import get_settings
from backend.deps import (
    get_auth_db,
    get_job_manager,
    require_admin,
    require_csrf,
)
from backend.email_sender import send_test_email
from crawler.config_utils import (
    DEFAULT_GLOBAL_CONFIG,
    validate_domain_delays,
    validate_ignore_regexes,
)
from crawler.manager import JobManager

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Request Schema ─────────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    """建立使用者的請求結構。"""

    email: EmailStr

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


class UpdateUserRequest(BaseModel):
    """更新使用者的請求結構。"""

    status: str | None = None  # active / suspended
    role: str | None = None  # user / admin

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        """
        驗證 status 是否合法。

        Args:
            v (str | None): 帳號狀態值。

        Returns:
            str | None: 驗證後的狀態值。

        Raises:
            ValueError: 當狀態值不是 active 或 suspended 時拋出。
        """
        if v is not None and v not in ("active", "suspended"):
            raise ValueError("status 必須為 active 或 suspended。")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        """
        驗證 role 是否合法。

        Args:
            v (str | None): 角色值。

        Returns:
            str | None: 驗證後的角色值。

        Raises:
            ValueError: 當角色值不是 user 或 admin 時拋出。
        """
        if v is not None and v not in ("user", "admin"):
            raise ValueError("role 必須為 user 或 admin。")
        return v


class SendTestEmailRequest(BaseModel):
    """寄送測試郵件的請求結構。"""

    to_email: EmailStr


class MimeTypeFilterConfig(BaseModel):
    """MimeType 過濾設定。"""

    enabled: bool
    allowed_types: list[str]


class CrawlerConfigUpdate(BaseModel):
    """Crawler 區塊配置更新請求結構。"""

    model_config = {"extra": "forbid"}

    timeout: int | None = Field(None, ge=1)
    delay: float | None = Field(None, ge=0.0)
    retries: int | None = Field(None, ge=0)
    max_depth: int | None = Field(None, ge=1)
    max_pages: int | None = Field(None, ge=1)
    max_content_length: int | None = Field(None, ge=1024)
    max_redirects: int | None = Field(None, ge=0)
    jitter_ratio: float | None = Field(None, ge=0.0, le=1.0)
    user_agent: str | None = None
    proxy_url: str | None = None
    ssl_exempt_domains: list[str] | None = None
    social_domains: list[str] | None = None
    domain_delays: dict[str, float] | None = None
    ignore_extensions: list[str] | None = None
    ignore_regexes: list[str] | None = None
    mime_type_filter: MimeTypeFilterConfig | None = None
    min_timeout: int | None = Field(None, ge=1)
    max_timeout: int | None = Field(None, ge=1)
    connect_timeout: float | None = Field(None, ge=1.0)
    external_check_timeout: float | None = Field(None, ge=1.0)
    min_connect_timeout: float | None = Field(None, ge=1.0)
    max_connect_timeout: float | None = Field(None, ge=1.0)
    min_external_check_timeout: float | None = Field(None, ge=1.0)
    max_external_check_timeout: float | None = Field(None, ge=1.0)
    min_delay: float | None = Field(None, ge=0.0)
    max_delay: float | None = Field(None, ge=0.0)
    min_retries: int | None = Field(None, ge=0)
    max_retries: int | None = Field(None, ge=0)
    max_max_depth: int | None = Field(None, ge=1)
    max_max_pages: int | None = Field(None, ge=1)

    @field_validator("ssl_exempt_domains", "social_domains", "ignore_extensions")
    @classmethod
    def clean_string_lists(cls, v: list[str] | None) -> list[str] | None:
        """
        移除清單中的前後空白與空字串。

        Args:
            v (list[str] | None): 原始字串列表。

        Returns:
            list[str] | None: 清理後的字串列表。
        """
        if v is not None:
            return [item.strip() for item in v if item.strip()]
        return v

    @field_validator("ignore_regexes")
    @classmethod
    def validate_regexes(cls, v: list[str] | None) -> list[str] | None:
        """
        驗證正則表達式列表是否合法。

        Args:
            v (list[str] | None): 欲驗證的正則表達式列表。

        Returns:
            list[str] | None: 驗證後的正則表達式列表。

        Raises:
            ValueError: 若有任何正則表達式編譯失敗時拋出。
        """
        return validate_ignore_regexes(v)

    @model_validator(mode="after")
    def validate_min_max_pairs(self) -> "CrawlerConfigUpdate":
        """
        確保各項安全上下限設定的最小值不大於最大值。

        Returns:
            CrawlerConfigUpdate: 驗證後的模型本身。
        """
        pairs = [
            ("min_timeout", "max_timeout", "逾時時間"),
            ("min_connect_timeout", "max_connect_timeout", "TCP 連線逾時"),
            ("min_external_check_timeout", "max_external_check_timeout", "外連探測逾時"),
            ("min_delay", "max_delay", "請求延遲"),
            ("min_retries", "max_retries", "重試次數"),
        ]
        for min_k, max_k, label in pairs:
            min_v = getattr(self, min_k)
            max_v = getattr(self, max_k)
            if min_v is not None and max_v is not None and min_v > max_v:
                raise ValueError(f"{label}的最小值 ({min_v}) 不可大於最大值 ({max_v})。")
        return self

    @field_validator("domain_delays")
    @classmethod
    def validate_domain_delays(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        """
        驗證網域延遲時間是否合法。

        Args:
            v (dict[str, float] | None): 欲驗證的網域延遲時間字典。

        Returns:
            dict[str, float] | None: 驗證後的網域延遲時間字典。

        Raises:
            ValueError: 若有任何延遲時間小於 0 時拋出。
        """
        return validate_domain_delays(v)


class UpdateConfigRequest(BaseModel):
    """全域配置更新的請求結構。"""

    model_config = {"extra": "forbid"}
    crawler: CrawlerConfigUpdate


# ── 使用者管理 ─────────────────────────────────────────────────────────────────


@router.get("/users", status_code=status.HTTP_200_OK)
def list_users(
    status_filter: str | None = Query(None, alias="status", description="依帳號狀態篩選"),
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
) -> list[dict[str, object]]:
    """
    列出所有使用者帳號。

    Args:
        status_filter (str | None): (選填) 依帳號狀態篩選。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。

    Returns:
        list[dict[str, object]]: 系統中所有使用者的資訊陣列。
    """
    query = auth_db.query(User).filter(User.status != "deleted")
    if status_filter:
        query = query.filter(User.status == status_filter)
    users = query.order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "status": u.status,
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, object]:
    """
    新增使用者並寄送邀請郵件。

    Args:
        body (CreateUserRequest): 建立使用者的請求內容（含 email）。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。

    Returns:
        dict[str, object]: 操作成功與邀請狀態訊息。
    """
    try:
        result = auth_service.create_invitation(auth_db, body.email)
        return {"message": "邀請已建立並寄送。", **result}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.patch("/users/{user_id}", status_code=status.HTTP_200_OK)
def update_user(
    user_id: str,
    body: UpdateUserRequest,
    request: Request,
    auth_db: DBSession = Depends(get_auth_db),
    current_admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    修改帳號狀態或角色。帳號停用時自動清除所有 Session。

    Args:
        user_id (str): 欲修改的使用者 ID。
        body (UpdateUserRequest): 欲修改的狀態或角色內容。
        request (Request): FastAPI 的 Request 物件（供紀錄 IP 使用）。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。
        current_admin (User): 當前執行操作的管理員物件。

    Returns:
        dict[str, str]: 操作成功訊息。
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的帳號狀態或角色。",
        )

    user = auth_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="使用者不存在。")

    # [安全防護 1] 防止停用管理員
    if body.status == "suspended" and user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無法直接停用管理員帳號。請先將其降權為一般使用者。",
        )

    # [安全防護 2] 防止將停用/已過期的帳號設為管理員
    future_status = body.status if body.status else user.status
    if body.role == "admin" and future_status in ("suspended", "expired", "deleted"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無法將停用或已過期的帳號設為管理員。",
        )

    changes = {}
    if body.status and body.status != user.status:
        changes["status"] = {"before": user.status, "after": body.status}
        user.status = body.status
        if body.status == "suspended":
            # 停用帳號 → 清除所有 Session
            count = auth_service.invalidate_all_user_sessions(auth_db, user_id)
            logger.info("帳號 %s 已停用，清除 %d 個 Session", user.email, count)

    if body.role and body.role != user.role:
        changes["role"] = {"before": user.role, "after": body.role}
        user.role = body.role

    if changes:
        log_detail = {
            "target_user_id": user_id,
            "target_email": user.email,
            "changes": changes,
        }
        auth_log = AuthLog(
            user_id=current_admin.id,
            event_type="user_status_changed",
            ip_address=request.client.host if request.client else None,
            detail=json.dumps(log_detail, ensure_ascii=False),
        )
        auth_db.add(auth_log)

    auth_db.commit()
    return {"message": f"帳號 {user.email} 已更新。"}


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    auth_db: DBSession = Depends(get_auth_db),
    current_admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    刪除帳號及所有關聯資料（含 Crawler DB 中的任務）。

    跨庫刪除順序（§12.4）：先刪 Crawler DB 資料，再刪 Auth DB 帳號。

    Args:
        user_id (str): 被刪除使用者的 UUID。
        request (Request): FastAPI Request。
        background_tasks (BackgroundTasks): 用於發送背景清理任務。
        auth_db (DBSession): Auth 資料庫 Session。
        current_admin (User): 當前操作的管理員使用者物件。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若管理員企圖刪除自己的帳號。
        HTTPException 403: 企圖直接刪除其他管理員帳號。
        HTTPException 404: 若被刪除的使用者不存在。
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能刪除自己的帳號。",
        )

    user = auth_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="使用者不存在。")

    # [安全防護 3] 防止刪除管理員
    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="無法直接刪除管理員帳號。請先將其降權為一般使用者。",
        )

    # 記錄刪除帳號的操作日誌
    log_detail = {
        "deleted_user_id": user_id,
        "deleted_email": user.email,
        "action": "soft_delete_and_schedule_cleanup",
    }
    auth_log = AuthLog(
        user_id=current_admin.id,
        event_type="user_deleted",
        ip_address=request.client.host if request.client else None,
        detail=json.dumps(log_detail, ensure_ascii=False),
    )
    auth_db.add(auth_log)

    # 1. 將 Auth DB 帳號標記為軟刪除 (Soft Delete)，以保證跨庫刪除的最終一致性。
    # 並且使所有 Session 立即失效。
    user.status = "deleted"
    auth_service.invalidate_all_user_sessions(auth_db, user_id)
    auth_db.commit()

    # 2. 加入背景任務，執行跨庫清理與實體刪除
    background_tasks.add_task(auth_service.cleanup_deleted_user_task, user_id)

    return {"message": f"帳號 {user.email} 已進入刪除排程，所有關聯資料將被非同步清理。"}


@router.post("/users/{user_id}/resend-invite", status_code=status.HTTP_200_OK)
def resend_invite(
    user_id: str,
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    重新寄送邀請郵件（重置邀請 token）。

    Args:
        user_id (str): 目標使用者的 ID。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。

    Returns:
        dict[str, str]: 成功寄送邀請的訊息。
    """
    user = auth_db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="使用者不存在。")

    if user.status not in ("pending", "expired"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"帳號狀態為 {user.status}，無法重新寄送邀請。",
        )

    try:
        auth_service.create_invitation(auth_db, user.email)
        return {"message": f"邀請已重新寄送至 {user.email}。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# ── 任務監控（Admin 視圖）─────────────────────────────────────────────────────


@router.get("/jobs", status_code=status.HTTP_200_OK)
def list_all_jobs(
    user_id: str | None = Query(None, description="依使用者 ID 篩選"),
    status_filter: str | None = Query(None, alias="status", description="依任務狀態篩選"),
    manager: JobManager = Depends(get_job_manager),
    _admin: User = Depends(require_admin),
) -> list[dict[str, object]]:
    """
    列出所有使用者的任務（Admin 全視圖）。

    Args:
        user_id (str | None): (選填) 依使用者 ID 篩選。
        status_filter (str | None): (選填) 依任務狀態篩選。
        manager (JobManager): JobManager 實例。

    Returns:
        list[dict[str, object]]: 系統中所有任務的列表。
    """
    return manager.get_all_jobs(user_id=user_id, status=status_filter)


@router.post("/jobs/{job_id}/takeover", status_code=status.HTTP_200_OK)
def takeover_job(
    job_id: str,
    request: Request,
    manager: JobManager = Depends(get_job_manager),
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    強制接管卡死任務（重置 running 狀態為 paused）。

    Args:
        job_id (str): 欲接管的任務 ID。
        request (Request): FastAPI 請求物件。
        manager (JobManager): JobManager 實例。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。

    Returns:
        dict[str, str]: 操作成功訊息。
    """
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任務不存在。")
    if job.status not in ("running", "starting"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"任務狀態為 {job.status}，只有 running 或 starting 狀態的任務才能被強制接管。",
        )

    # 記錄任務強制接管的操作日誌
    log_detail = {
        "job_id": job_id,
        "action": "takeover",
        "before_status": job.status,
    }
    auth_log = AuthLog(
        user_id=_admin.id,
        event_type="job_force_action",
        ip_address=request.client.host if request.client else None,
        detail=json.dumps(log_detail, ensure_ascii=False),
    )
    auth_db.add(auth_log)
    auth_db.commit()

    manager.pause_job(job_id)
    return {"message": f"任務 {job_id} 已強制接管並設為 paused。"}


@router.delete("/jobs/{job_id}", status_code=status.HTTP_200_OK)
def admin_delete_job(
    job_id: str,
    request: Request,
    manager: JobManager = Depends(get_job_manager),
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    強制刪除任意任務（Admin 用）。

    Args:
        job_id (str): 欲刪除的任務 ID。
        request (Request): FastAPI 請求物件。
        manager (JobManager): JobManager 實例。
        auth_db (DBSession): Auth DB 的 SQLAlchemy Session。

    Returns:
        dict[str, str]: 操作成功訊息。
    """
    if not manager.get_job(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任務不存在。")

    # 記錄任務強制刪除的操作日誌
    log_detail = {
        "job_id": job_id,
        "action": "delete",
    }
    auth_log = AuthLog(
        user_id=_admin.id,
        event_type="job_force_action",
        ip_address=request.client.host if request.client else None,
        detail=json.dumps(log_detail, ensure_ascii=False),
    )
    auth_db.add(auth_log)
    auth_db.commit()

    if not manager.delete_job(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任務不存在。")
    return {"message": f"任務 {job_id} 已刪除。"}


# ── 全域配置管理 ───────────────────────────────────────────────────────────────


@router.get("/config", status_code=status.HTTP_200_OK)
def get_config(
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """
    取得全域爬蟲配置（讀取 config_global.yaml）。
    Returns:
        dict[str, object]: 目前的全域爬蟲配置。
    """
    settings = get_settings()
    config_path = settings.GLOBAL_CONFIG_PATH
    if not os.path.exists(config_path):
        return DEFAULT_GLOBAL_CONFIG
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data else DEFAULT_GLOBAL_CONFIG
    except (OSError, yaml.YAMLError) as e:
        logger.error("讀取設定檔失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="讀取設定檔失敗，請聯繫管理員。",
        ) from e


@router.patch("/config", status_code=status.HTTP_200_OK)
def update_config(
    body: UpdateConfigRequest,
    request: Request,
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    修改全域配置（僅允許修改 crawler 區塊下的安全欄位）。

    採用 Pydantic 模型驗證：只允許修改 crawler.* 區塊中預先核准的欄位與型別，
    禁止修改 db_url、logging（含 log_file 路徑）等系統級設定，
    防範 Path Traversal 等攻擊與無效數值。

    Args:
        body (UpdateConfigRequest): 包含欲修改設定值的結構。
        request (Request): FastAPI Request。
        auth_db (DBSession): Auth 資料庫 Session。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 422: 若請求格式、數值不正確。
        HTTPException 500: 若寫入設定檔時發生 I/O 錯誤。
    """
    settings = get_settings()
    config_path = settings.GLOBAL_CONFIG_PATH

    # 僅提取有更新的 crawler 欄位 (exclude_unset=True)
    crawler_updates = body.crawler.model_dump(exclude_unset=True)
    safe_body = {"crawler": crawler_updates}

    try:
        existing: dict[str, object] = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}

        # 深度合併 crawler 區塊（不覆蓋其他頂層欄位）
        existing_crawler = existing.get("crawler", {})
        existing_crawler_before = copy.deepcopy(existing_crawler)
        existing_crawler.update(safe_body["crawler"])
        existing["crawler"] = existing_crawler

        os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)

        # 記錄全域配置修改日誌
        log_detail = {
            "action": "update_global_config",
            "before": existing_crawler_before,
            "after": existing["crawler"],
        }
        auth_log = AuthLog(
            user_id=_admin.id,
            event_type="config_change",
            ip_address=request.client.host if request.client else None,
            detail=json.dumps(log_detail, ensure_ascii=False),
        )
        auth_db.add(auth_log)
        auth_db.commit()

        return {"message": "全域配置已更新。"}
    except (OSError, yaml.YAMLError) as e:
        logger.error("寫入設定檔失敗: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="寫入設定檔失敗，請聯繫管理員。",
        ) from e


# ── SMTP 配置（唯讀狀態）─────────────────────────────────────────────────────


@router.get("/smtp", status_code=status.HTTP_200_OK)
def get_smtp_config(
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """
    取得 SMTP 配置狀態（密碼遮罩，從環境變數讀取）。
    Returns:
        dict[str, object]: SMTP 配置狀態，包含各種設定值。
    """
    settings = get_settings()
    return {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "username": settings.SMTP_USERNAME,
        "password": "***" if settings.SMTP_PASSWORD else "(未設定)",
        "from_name": settings.SMTP_FROM_NAME,
        "from_email": settings.SMTP_FROM_EMAIL,
        "use_tls": settings.SMTP_USE_TLS,
        "console_mode": settings.SMTP_CONSOLE_MODE,
        "note": "SMTP 設定透過環境變數管理，如需修改請更新伺服器環境變數後重啟服務。",
    }


@router.post("/smtp/test", status_code=status.HTTP_200_OK)
def test_smtp(
    body: SendTestEmailRequest,
    _admin: User = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    寄送測試郵件以驗證 SMTP 設定。

    Args:
        body (SendTestEmailRequest): 請求內容，包含收件者信箱。

    Returns:
        dict[str, str]: 操作成功訊息。
    """
    success = send_test_email(body.to_email)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SMTP 測試郵件寄送失敗，請確認 SMTP 環境變數設定是否正確。",
        )
    return {"message": f"測試郵件已成功寄送至 {body.to_email}。"}


# ── 操作日誌查閱 ───────────────────────────────────────────────────────────────


class DateQueryArgs:  # pylint: disable=too-few-public-methods
    """日期範圍查詢參數。"""

    def __init__(
        self,
        start_date: str | None = Query(None, description="開始日期 (YYYY-MM-DD 或 ISO 格式)"),
        end_date: str | None = Query(None, description="結束日期 (YYYY-MM-DD 或 ISO 格式)"),
    ) -> None:
        """
        初始化日期範圍查詢參數。

        Args:
            start_date (str | None): 開始日期。
            end_date (str | None): 結束日期。

        Returns:
            None
        """
        self.start_date = start_date
        self.end_date = end_date


class PaginationArgs:  # pylint: disable=too-few-public-methods
    """分頁查詢參數。"""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        """
        初始化分頁查詢參數。

        Args:
            page (int): 頁碼。
            page_size (int): 每頁筆數。

        Returns:
            None
        """
        self.page = page
        self.page_size = page_size


class LogQueryArgs:  # pylint: disable=too-few-public-methods
    """日誌查詢參數封裝。"""

    def __init__(
        self,
        event_type: str | None = Query(None),
        user_id: str | None = Query(None),
        dates: DateQueryArgs = Depends(),
        pagination: PaginationArgs = Depends(),
    ) -> None:
        """
        初始化日誌查詢參數。

        Args:
            event_type (str | None): 事件類型過濾。
            user_id (str | None): 使用者 ID 過濾。
            dates (DateQueryArgs): 日期範圍過濾。
            pagination (PaginationArgs): 分頁參數。

        Returns:
            None
        """
        self.event_type = event_type
        self.user_id = user_id
        self.start_date = dates.start_date
        self.end_date = dates.end_date
        self.page = pagination.page
        self.page_size = pagination.page_size


@router.get("/logs", status_code=status.HTTP_200_OK)
def get_logs(
    query_args: LogQueryArgs = Depends(),
    auth_db: DBSession = Depends(get_auth_db),
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """
    查閱系統操作日誌（支援事件類型、使用者 ID 及時間範圍篩選）。

    Args:
        query_args (LogQueryArgs): 日誌查詢參數。
        auth_db (DBSession): Auth DB Session。

    Returns:
        dict[str, object]: 包含日誌項目列表與分頁資訊的字典。
    """
    query = auth_db.query(AuthLog).order_by(AuthLog.created_at.desc())

    if query_args.event_type:
        query = query.filter(AuthLog.event_type == query_args.event_type)
    if query_args.user_id:
        query = query.filter(AuthLog.user_id == query_args.user_id)

    if query_args.start_date:
        try:
            if "T" in query_args.start_date:
                start_dt = datetime.fromisoformat(query_args.start_date)
            else:
                start_dt = datetime.strptime(query_args.start_date.strip(), "%Y-%m-%d")
            query = query.filter(AuthLog.created_at >= start_dt)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"start_date 格式不正確，需為 YYYY-MM-DD 或 ISO 格式。錯誤: {e}",
            ) from e

    if query_args.end_date:
        try:
            if "T" in query_args.end_date:
                end_dt = datetime.fromisoformat(query_args.end_date)
            else:
                end_dt = datetime.strptime(query_args.end_date.strip(), "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            query = query.filter(AuthLog.created_at <= end_dt)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"end_date 格式不正確，需為 YYYY-MM-DD 或 ISO 格式。錯誤: {e}",
            ) from e

    total = query.count()
    offset = (query_args.page - 1) * query_args.page_size
    logs = query.offset(offset).limit(query_args.page_size).all()

    return {
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "event_type": log.event_type,
                "ip_address": log.ip_address,
                "detail": log.detail,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
        "total": total,
        "page": query_args.page,
        "page_size": query_args.page_size,
        "total_pages": (total + query_args.page_size - 1) // query_args.page_size if total > 0 else 1,
    }
