"""
任務管理 API 路由。

實作 §13.2 與 §13.3 定義的端點：
- GET    /api/jobs/default-config         — 取得建立任務時的預設配置
- GET    /api/jobs                        — 列出當前使用者的任務
- POST   /api/jobs                        — 建立新任務
- GET    /api/jobs/{id}                   — 取得任務詳情
- POST   /api/jobs/{id}/start             — 啟動任務
- POST   /api/jobs/{id}/pause             — 暫停任務
- POST   /api/jobs/{id}/resume            — 恢復任務
- POST   /api/jobs/{id}/reset             — 重置任務
- POST   /api/jobs/{id}/retry-failed      — 重試任務的失敗項目
- DELETE /api/jobs/{id}                   — 刪除任務
- GET    /api/jobs/{id}/results           — 外連結果列表
- GET    /api/jobs/{id}/results/summary   — 統計摘要
- GET    /api/jobs/{id}/results/export    — 匯出 CSV / JSON
"""

# pylint: disable=too-many-lines

import csv
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from collections.abc import Generator

import yaml
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.config import get_settings
from backend.deps import get_auth_db, get_crawler_db, get_current_user, get_job_manager, require_csrf
from backend.jobs import service as job_service
from crawler.config_utils import (
    DEFAULT_GLOBAL_CONFIG,
    merge_and_validate_crawler_config,
)
from crawler.exporter import _sanitize_csv_value
from crawler.manager import JobManager
from crawler.models import Job

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Request Schema ─────────────────────────────────────────────────────────────


class CreateJobRequest(BaseModel):
    """建立任務請求的 Schema。"""

    model_config = {"extra": "forbid"}

    start_url: str
    target_domains: list[str]
    trusted_domains: list[str] = []
    ignore_extensions: list[str] = []
    ignore_regexes: list[str] = []
    max_depth: int | None = Field(None, ge=1)
    max_pages: int | None = Field(None, ge=1)
    delay: float | None = Field(None, ge=0.0)
    timeout: int | None = Field(None, ge=1)
    connect_timeout: float | None = Field(None, ge=1.0)
    external_check_timeout: float | None = Field(None, ge=1.0)
    retries: int | None = Field(None, ge=0)
    proxy_url: str | None = None
    user_agent: str | None = None
    ssl_exempt_domains: list[str] = []
    domain_delays: dict[str, float] | None = None

    @field_validator("start_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """
        驗證 URL 格式。

        Args:
            v (str): 原始網址字串。

        Returns:
            str: 驗證後的網址字串。

        Raises:
            ValueError: 若網址不以 http:// 或 https:// 開頭時拋出。
        """
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("起始 URL 必須以 http:// 或 https:// 開頭。")
        return v

    @field_validator("target_domains")
    @classmethod
    def validate_domains(cls, v: list[str]) -> list[str]:
        """
        確保至少有一個目標網域。

        Args:
            v (list[str]): 原始網域列表。

        Returns:
            list[str]: 驗證後的網域列表。

        Raises:
            ValueError: 若列表為空時拋出。
        """
        cleaned = [d.strip() for d in v if d.strip()]
        if not cleaned:
            raise ValueError("至少需要指定一個目標網域。")
        return cleaned

    @field_validator("trusted_domains", "ssl_exempt_domains", "ignore_extensions")
    @classmethod
    def clean_string_lists(cls, v: list[str]) -> list[str]:
        """
        移除清單中的前後空白與空字串。

        Args:
            v (list[str]): 原始字串列表。

        Returns:
            list[str]: 清理後的字串列表。
        """
        return [item.strip() for item in v if item.strip()]

    @field_validator("ignore_regexes")
    @classmethod
    def validate_regexes(cls, v: list[str]) -> list[str]:
        """
        驗證正則表達式列表是否合法。

        Args:
            v (list[str]): 欲驗證的正則表達式列表。

        Returns:
            list[str]: 驗證後的正則表達式列表。

        Raises:
            ValueError: 若有任何正則表達式編譯失敗時拋出。
        """
        cleaned = [pattern.strip() for pattern in v if pattern.strip()]
        for pattern in cleaned:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"無效的正則表達式 '{pattern}': {e}") from e
        return cleaned

    @field_validator("domain_delays")
    @classmethod
    def validate_domain_delays(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        """
        驗證特定網域延遲時間是否合法。

        Args:
            v (dict[str, float] | None): 欲驗證的網域延遲時間字典。

        Returns:
            dict[str, float] | None: 驗證後的網域延遲時間字典。

        Raises:
            ValueError: 若有任何延遲時間小於 0 時拋出。
        """
        if v is not None:
            for domain, delay in v.items():
                if delay < 0:
                    raise ValueError(f"網域 {domain} 的延遲時間不可小於 0")
        return v


class TransferJobRequest(BaseModel):
    """移交任務請求的 Schema。"""

    model_config = {"extra": "forbid"}

    target_email: EmailStr

    @field_validator("target_email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """
        將信箱轉為小寫去空白。
        """
        return v.strip().lower()


# ── 端點實作 ────────────────────────────────────────────────────────────────────


@router.get("/default-config", status_code=status.HTTP_200_OK)
def get_default_config(
    _current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """
    取得任務預設的全域配置，供前端建立任務時填入預設值與限制。

    Args:
        _current_user (User): 當前登入的使用者物件。

    Returns:
        dict[str, object]: 允許前端使用的預設配置過濾結果。
    """
    settings = get_settings()
    config_path = settings.GLOBAL_CONFIG_PATH
    crawler_config = DEFAULT_GLOBAL_CONFIG.get("crawler", {})

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "crawler" in data:
                    crawler_config = data["crawler"]
        except (OSError, yaml.YAMLError) as e:
            logger.warning("讀取全域設定檔失敗: %s", e)

    # 僅提取前端有使用到的欄位，過濾掉不需要暴露的敏感或內部配置
    allowed_keys = {
        "ignore_extensions",
        "ignore_regexes",
        "delay",
        "min_delay",
        "max_delay",
        "timeout",
        "connect_timeout",
        "external_check_timeout",
        "min_timeout",
        "max_timeout",
        "min_connect_timeout",
        "max_connect_timeout",
        "min_external_check_timeout",
        "max_external_check_timeout",
        "retries",
        "min_retries",
        "max_retries",
        "max_max_depth",
        "max_max_pages",
        "proxy_url",
        "user_agent",
        "ssl_exempt_domains",
        "domain_delays",
    }

    return {k: v for k, v in crawler_config.items() if k in allowed_keys}


@router.get("", status_code=status.HTTP_200_OK)
def list_jobs(
    status_filter: str | None = Query(None, alias="status", description="依任務狀態篩選"),
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> list[dict[str, object]]:
    """
    列出當前使用者的所有任務。

    Args:
        status_filter (str | None): 依任務狀態篩選。
        current_user (User): 當前登入的使用者物件。
        manager (JobManager): JobManager 實例。

    Returns:
        list[dict[str, object]]: 任務清單。
    """
    return job_service.list_jobs(manager, current_user.id, status=status_filter)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(
    body: CreateJobRequest,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, object]:
    """
    建立新的爬蟲任務。

    Args:
        body (CreateJobRequest): 建立任務的請求內容。
        current_user (User): 當前登入的使用者物件。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, object]: 新建任務的 ID 與訊息。

    Raises:
        HTTPException 500: 建立任務失敗時拋出。
    """

    # 安全白名單：只允許前端設定特定的 crawler_config 欄位
    allowed_crawler_keys = {
        "ignore_extensions",
        "ignore_regexes",
        "max_depth",
        "max_pages",
        "delay",
        "timeout",
        "connect_timeout",
        "external_check_timeout",
        "retries",
        "proxy_url",
        "user_agent",
        "ssl_exempt_domains",
        "domain_delays",
    }

    # 透過白名單動態過濾並組建 crawler_config
    body_dict = body.model_dump()
    user_crawler_config: dict[str, object] = {}
    for key in allowed_crawler_keys:
        val = body_dict.get(key)
        # 過濾掉 None 與空字串/空陣列，避免覆蓋掉全域預設設定
        if val is not None and val != [] and val != "":
            user_crawler_config[key] = val

    # 根據規格書 §4：將全域設定與個別任務設定合併，產生「最終執行配置快照」
    settings = get_settings()
    global_config = {}
    if os.path.exists(settings.GLOBAL_CONFIG_PATH):
        try:
            with open(settings.GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                global_config = yaml.safe_load(f) or {}
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("建立快照時讀取全域設定檔失敗: %s", e)

    final_crawler_config = merge_and_validate_crawler_config({"crawler": user_crawler_config}, global_config)

    try:
        config_obj = job_service.JobCreateConfig(
            start_url=body.start_url,
            target_domains=body.target_domains,
            trusted_domains=body.trusted_domains,
            crawler_config=final_crawler_config,
        )
        job_id = job_service.create_job(manager, current_user.id, config_obj)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    return {"job_id": job_id, "message": "任務已建立。"}


@router.get("/{job_id}", status_code=status.HTTP_200_OK)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> dict[str, object]:
    """
    取得任務詳情（含進度）。

    Args:
        job_id (str): 欲查詢的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。

    Returns:
        dict[str, object]: 任務詳情與進度。

    Raises:
        HTTPException 404: 找不到任務或無權限時拋出。
    """
    try:
        return job_service.get_job_detail(manager, job_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{job_id}/start", status_code=status.HTTP_200_OK)
def start_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    啟動任務（spawn 爬蟲子程序）。

    Args:
        job_id (str): 欲啟動的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若任務狀態不允許啟動時拋出。
    """
    try:
        job_service.start_job(manager, job_id, current_user.id)
        return {"message": "任務已啟動。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/pause", status_code=status.HTTP_200_OK)
def pause_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    暫停任務（協同暫停，更新 DB 狀態）。

    Args:
        job_id (str): 欲暫停的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_service.pause_job(manager, job_id, current_user.id)
        return {"message": "已發送暫停指令，任務將在完成當前網頁後停止。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/resume", status_code=status.HTTP_200_OK)
def resume_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    恢復已暫停的任務（只允許 paused 狀態）。

    Args:
        job_id (str): 欲恢復的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若任務非暫停狀態時拋出。
    """
    try:
        # 先確認任務狀態，resume 只允許 paused 狀態
        job = manager.get_job(job_id)
        if not job:
            raise ValueError(f"找不到任務 ID: {job_id}")
        if job.user_id != current_user.id:
            raise ValueError("無權限操作此任務。")
        if job.status != "paused":
            raise ValueError(f"任務目前狀態為 {job.status}，resume 只允許恢復 paused 狀態的任務。")
        job_service.start_job(manager, job_id, current_user.id)
        return {"message": "任務已恢復執行。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/reset", status_code=status.HTTP_200_OK)
def reset_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    重置任務（清除結果並回到 pending 狀態）。

    Args:
        job_id (str): 欲重置的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_service.reset_job(manager, job_id, current_user.id)
        return {"message": "任務已重置。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/retry-failed", status_code=status.HTTP_200_OK)
def retry_failed_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    局部重試任務中的失敗項目。

    Args:
        job_id (str): 欲重試的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_service.retry_failed_job(manager, job_id, current_user.id)
        return {"message": "任務失敗項目已重置。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{job_id}", status_code=status.HTTP_200_OK)
def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    刪除任務及所有相關資料。

    Args:
        job_id (str): 欲刪除的任務 ID。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 404: 若任務不存在時拋出。
    """
    try:
        job_service.delete_job(manager, job_id, current_user.id)
        return {"message": "任務已刪除。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{job_id}/transfer", status_code=status.HTTP_200_OK)
def transfer_job(
    job_id: str,
    body: TransferJobRequest,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    auth_db: DBSession = Depends(get_auth_db),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """
    將任務移交給其他使用者。

    Args:
        job_id (str): 欲移交的任務 ID。
        body (TransferJobRequest): 包含目標使用者信箱的請求內容。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        auth_db (DBSession): Auth DB Session。
        _csrf (None): CSRF 防禦標記。

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 目標使用者不存在或狀態異常時拋出。
    """
    target_user = auth_db.query(User).filter(User.email == body.target_email).first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目標使用者不存在。")
    if target_user.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目標使用者帳號狀態異常，無法接收任務。")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能將任務移交給自己。")

    try:
        job_service.transfer_job(manager, job_id, current_user.id, target_user.id)
        return {"message": f"任務已成功移交給 {body.target_email}。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


class ResultsQueryArgs:
    """任務結果查詢參數。"""

    def __init__(
        self,
        status_filter: str | None = Query(None, alias="filter", pattern="^(dead|broken|insecure|healthy|all)$"),
        search: str | None = Query(None),
        exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        """
        初始化結果查詢參數。

        Args:
            status_filter (str | None): 狀態過濾條件。
            search (str | None): 搜尋字串。
            exclude (str | None): 要排除的網域。
            group_by (str): 聚合方式。
            page (int): 頁碼。
            page_size (int): 每頁筆數。
        """
        self.status_filter = status_filter
        self.search = search
        self.exclude = exclude
        self.group_by = group_by
        self.page = page
        self.page_size = page_size


@router.get("/{job_id}/results", status_code=status.HTTP_200_OK)
def get_results(
    job_id: str,
    query_args: ResultsQueryArgs = Depends(),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    外連結果列表（支援篩選、搜尋、去重聚合與分頁）。

    Args:
        job_id (str): 任務 ID。
        query_args (ResultsQueryArgs): 結果查詢參數。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 查詢結果。

    Raises:
        HTTPException 404: 找不到任務時拋出。
    """
    try:
        query_obj = job_service.JobResultQuery(
            job_id=job_id,
            user_id=current_user.id,
            status_filter=query_args.status_filter,
            search=query_args.search,
            exclude=query_args.exclude,
            group_by=query_args.group_by,
            page=query_args.page,
            page_size=query_args.page_size,
        )
        return job_service.get_job_results(db, query_obj)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/results/summary", status_code=status.HTTP_200_OK)
def get_results_summary(
    job_id: str,
    exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
    group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    取得任務結果統計摘要。

    Args:
        job_id (str): 任務 ID。
        exclude (str | None): 要排除的目標網域。
        group_by (str): 聚合方式。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 任務結果統計。

    Raises:
        HTTPException 404: 找不到任務時拋出。
    """
    try:
        return job_service.get_results_summary(db, job_id, current_user.id, exclude, group_by)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/diff", status_code=status.HTTP_200_OK)
def get_job_diff(
    job_id: str,
    compare_with: str = Query(..., description="要比對的新任務 ID (對照組)"),
    exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    比對兩個任務的外連結果差異 (支援排除網域)。

    以 job_id 作為基準 (舊任務)，compare_with 作為對照 (新任務)。

    Args:
        job_id (str): 基準任務 ID。
        compare_with (str): 對照任務 ID。
        exclude (str | None): 要排除的目標網域。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 差異比對報表。

    Raises:
        HTTPException 404: 找不到任務時拋出。
    """
    try:
        return job_service.get_job_diff(
            db,
            base_job_id=job_id,
            compare_job_id=compare_with,
            user_id=current_user.id,
            exclude=exclude,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class ExportQueryArgs:
    """匯出結果查詢參數。"""

    def __init__(
        self,
        status_filter: str | None = Query(None, alias="filter", pattern="^(dead|broken|insecure|healthy|all)$"),
        exclude: str | None = Query(None),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        fmt: str = Query("csv", pattern="^(csv|json)$"),
    ) -> None:
        """
        初始化匯出查詢參數。

        Args:
            status_filter (str | None): 狀態過濾條件。
            exclude (str | None): 要排除的網域。
            group_by (str): 聚合方式。
            fmt (str): 輸出格式 (csv 或 json)。
        """
        self.status_filter = status_filter
        self.exclude = exclude
        self.group_by = group_by
        self.fmt = fmt


def _sanitize_csv_dict(row: dict[str, object]) -> dict[str, object]:
    """
    對 CSV 字典資料進行跳脫。

    Args:
        row (dict[str, object]): 原始資料字典。

    Returns:
        dict[str, object]: 安全跳脫後的字典。
    """
    return {k: _sanitize_csv_value(v) for k, v in row.items()}


@router.get("/{job_id}/results/export")
def export_results(
    job_id: str,
    query_args: ExportQueryArgs = Depends(),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> Response:
    """
    匯出外連結果（CSV 或 JSON 格式下載）。

    查詢參數：
    - filter: dead / broken / insecure
    - group_by: 聚合模式 (none / target / source / domain)
    - fmt: csv 或 json（預設 csv）

    Args:
        job_id (str): 任務 UUID。
        query_args (ExportQueryArgs): 匯出查詢參數，含過濾條件、聚合設定與格式。
        current_user (User): 當前登入使用者。
        db (DBSession): Crawler 資料庫 Session。

    Returns:
        Response: 包含匯出檔案內容的 FastAPI Response 物件。

    Raises:
        HTTPException 404: 若任務不存在或不屬於當前使用者。
    """
    try:
        query_obj = job_service.JobResultQuery(
            job_id=job_id,
            user_id=current_user.id,
            status_filter=query_args.status_filter,
            exclude=query_args.exclude,
            group_by=query_args.group_by,
        )
        # 僅用來驗證權限與是否存在，避免 stream 時才拋例外
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.user_id != current_user.id:
            raise ValueError(f"找不到任務 ID: {job_id}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    filename = f"job_{job_id}_results"
    if query_args.status_filter:
        filename += f"_{query_args.status_filter}"
    if query_args.group_by != "none":
        filename += f"_by_{query_args.group_by}"

    if query_args.fmt == "json":

        def json_generator() -> Generator[str, None, None]:
            """
            產生 JSON 格式輸出字串的產生器。

            Yields:
                str: 區塊的 JSON 字串。
            """
            yield "[\n"
            first = True
            for item in job_service.stream_job_results(db, query_obj):
                if not first:
                    yield ",\n"
                yield json.dumps(item, ensure_ascii=False, indent=2)
                first = False
            yield "\n]"

        return StreamingResponse(
            json_generator(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    # CSV 格式
    def csv_generator() -> Generator[str, None, None]:
        """
        產生 CSV 格式輸出字串的產生器。

        Yields:
            str: 區塊的 CSV 字串。
        """
        yield "\ufeff"  # BOM for Excel
        output = io.StringIO()
        writer = None

        for item in job_service.stream_job_results(db, query_obj):
            if query_args.group_by == "domain":
                fieldnames = [
                    "Domain",
                    "Occurrence Count",
                    "Unique URLs Count",
                    "Unique URLs",
                ]
                row_data = {
                    "Domain": item["domain"],
                    "Occurrence Count": item["occurrence_count"],
                    "Unique URLs Count": item["unique_urls_count"],
                    "Unique URLs": "\n".join(item["unique_urls"]),
                }
            elif query_args.group_by == "source":
                fieldnames = ["Source URL", "External Link Count", "Target URLs"]
                row_data = {
                    "Source URL": item["source_url"],
                    "External Link Count": item["occurrence_count"],
                    "Target URLs": "\n".join([f"[{t['status']}] {t['url']}" for t in item["targets"]]),
                }
            else:
                fieldnames = list(item.keys())
                row_data = item

            if writer is None:
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()

            writer.writerow(_sanitize_csv_dict(row_data))

            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        csv_generator(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/{job_id}/export/full")
def export_full_report(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> Response:
    """
    匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。

    Args:
        job_id (str): 任務 ID。
        background_tasks (BackgroundTasks): FastAPI 背景任務，用於清理暫存檔。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        Response: 檔案下載回應。

    Raises:
        HTTPException 404: 找不到任務時拋出。
    """
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.user_id != current_user.id:
            raise ValueError(f"找不到任務 ID: {job_id}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    def cleanup() -> None:
        """
        背景清理暫存 ZIP 檔案的任務。
        """
        if os.path.exists(temp_path):
            os.remove(temp_path)

    background_tasks.add_task(cleanup)

    with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        internal_iterator = job_service.stream_internal_results(db, job_id, current_user.id)
        try:
            first_internal = next(internal_iterator)
            with zf.open(f"job_{job_id}_crawl_records.csv", "w") as f:
                with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
                    writer = csv.DictWriter(text_file, fieldnames=list(first_internal.keys()))
                    writer.writeheader()
                    writer.writerow(_sanitize_csv_dict(first_internal))
                    for item in internal_iterator:
                        writer.writerow(_sanitize_csv_dict(item))
        except StopIteration:
            pass

        query_obj = job_service.JobResultQuery(job_id=job_id, user_id=current_user.id, group_by="none")
        external_iterator = job_service.stream_job_results(db, query_obj)
        try:
            first_external = next(external_iterator)
            with zf.open(f"job_{job_id}_external_links.csv", "w") as f:
                with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
                    writer = csv.DictWriter(text_file, fieldnames=list(first_external.keys()))
                    writer.writeheader()
                    writer.writerow(_sanitize_csv_dict(first_external))
                    for item in external_iterator:
                        writer.writerow(_sanitize_csv_dict(item))
        except StopIteration:
            pass

    filename = f"job_{job_id}_full_report.zip"
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename,
    )


@router.get("/{job_id}/internal-errors", status_code=status.HTTP_200_OK)
def get_internal_errors(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    取得內部網頁爬取失敗的紀錄列表（支援分頁）。

    Args:
        job_id (str): 任務 ID。
        page (int): 頁碼。
        page_size (int): 每頁筆數。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 包含失敗紀錄列表與分頁資訊的字典。

    Raises:
        HTTPException 404: 找不到任務或無權限存取時拋出。
    """
    try:
        return job_service.get_internal_errors(db, job_id, current_user.id, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
