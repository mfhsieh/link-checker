"""
任務管理相關 API 端點。
"""

import asyncio
import json
import logging
import os
import typing

import yaml
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.config import get_settings
from backend.deps import get_auth_db, get_crawler_db, get_current_user, get_job_manager, require_csrf
from backend.jobs.constants import ALLOWED_CRAWLER_CONFIG_KEYS
from backend.jobs.schemas import (
    CreateJobRequest,
    JobCreateConfig,
    JobDetailResponse,
    ReprobeRequest,
    TransferJobRequest,
)
from backend.jobs.services import management as job_management
from backend.jobs.services.reprobe import reprobe_external_links, reprobe_internal_links
from crawler.config_utils import (
    DEFAULT_GLOBAL_CONFIG,
    _sanitize_crawler_types,
    merge_and_validate_crawler_config,
)
from crawler.manager import JobManager

logger: logging.Logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/default-config")
def get_default_config(
    _current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """
    取得任務預設的全域配置，供前端建立任務時填入預設值與限制。
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

    # 進行型別清洗，確保回傳的欄位型態與資料庫內存的數值型態一致
    _sanitize_crawler_types(crawler_config)

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
        "social_domains",
        "domain_delays",
    }

    return {k: v for k, v in crawler_config.items() if k in allowed_keys}


@router.get("")
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
    return job_management.list_jobs(manager, current_user.id, status=status_filter)


@router.post("")
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

    Returns:
        dict[str, object]: 新建任務的 ID 與訊息。

    Raises:
        HTTPException 500: 建立任務失敗時拋出。
    """

    # 安全白名單：只允許前端設定特定的 crawler_config 欄位
    allowed_crawler_keys = {
        "ignore_extensions",
        "ignore_regexes",
        *ALLOWED_CRAWLER_CONFIG_KEYS,
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
        except (OSError, yaml.YAMLError) as e:
            logger.warning("建立快照時讀取全域設定檔失敗: %s", e)

    final_crawler_config = merge_and_validate_crawler_config({"crawler": user_crawler_config}, global_config)

    try:
        config_obj = JobCreateConfig(
            start_url=body.start_url,
            target_domains=body.target_domains,
            trusted_domains=body.trusted_domains,
            crawler_config=final_crawler_config,
        )
        job_id = job_management.create_job(manager, current_user.id, config_obj)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    return {"job_id": job_id, "message": "任務已建立。"}


@router.get("/{job_id}")
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> JobDetailResponse:
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
        return JobDetailResponse(**job_management.get_job_detail(manager, job_id, current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{job_id}/start")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若任務狀態不允許啟動時拋出。
    """
    try:
        job_management.start_job(manager, job_id, current_user.id)
        return {"message": "任務已啟動。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/pause")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_management.pause_job(manager, job_id, current_user.id)
        return {"message": "已發送暫停指令，任務將在完成當前網頁後停止。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/resume")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若任務非暫停狀態時拋出。
    """
    try:
        # 先確認任務狀態，resume 只允許 paused 或 error 狀態
        job = manager.get_job(job_id)
        if not job:
            raise ValueError(f"找不到任務 ID: {job_id}")
        if job.user_id != current_user.id:
            raise ValueError("無權限操作此任務。")
        if job.status not in ("paused", "error"):
            raise ValueError(f"任務目前狀態為 {job.status}，resume 只允許恢復 paused 或 error 狀態的任務。")
        job_management.start_job(manager, job_id, current_user.id)
        return {"message": "任務已恢復執行。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/reset")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_management.reset_job(manager, job_id, current_user.id)
        return {"message": "任務已重置。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/retry-failed")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 400: 若操作失敗時拋出。
    """
    try:
        job_management.retry_failed_job(manager, job_id, current_user.id)
        return {"message": "任務失敗項目已重置。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/reprobe")
def reprobe_job_links(
    job_id: str,
    body: ReprobeRequest,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    db: DBSession = Depends(get_crawler_db),
    _csrf: None = Depends(require_csrf),
) -> dict[str, object]:
    """
    局部重新發起 HTTP 探測。

    Args:
        job_id (str): 任務 ID。
        body (ReprobeRequest): 包含連結類型與欲探測的網址清單。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。
        db (DBSession): 資料庫連線。

    Returns:
        dict[str, object]: 操作成功訊息或更新結果。
    """
    if not body.urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="網址清單不可為空")

    try:
        if body.link_type == "external":
            return reprobe_external_links(db, manager, job_id, current_user.id, body.urls, body.group_by)
        return reprobe_internal_links(db, manager, job_id, current_user.id, body.urls, body.group_by)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{job_id}")
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

    Returns:
        dict[str, str]: 成功訊息。

    Raises:
        HTTPException 404: 若任務不存在時拋出。
    """
    try:
        job_management.delete_job(manager, job_id, current_user.id)
        return {"message": "任務已刪除。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{job_id}/transfer")
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
        job_management.transfer_job(manager, job_id, current_user.id, target_user.id)
        return {"message": f"任務已成功移交給 {body.target_email}。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{job_id}/stream", include_in_schema=False)
async def stream_job_updates(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> StreamingResponse:
    """
    使用 Server-Sent Events (SSE) 串流任務進度更新。

    Args:
        job_id (str): 欲串流更新的任務 ID。
        request (Request): FastAPI 請求物件，用於偵測客戶端連線中斷。
        current_user (User): 當前登入的使用者。
        manager (JobManager): JobManager 實例。

    Returns:
        StreamingResponse: SSE 事件串流回應。
    """

    async def event_generator() -> typing.AsyncGenerator[str, None]:
        """
        產生 SSE 事件的非同步產生器。

        Yields:
            str: 格式化後的 SSE 資料區塊。
        """
        # 1. 初始嚴格權限驗證與首筆資料發送
        try:
            # 這裡一定會使用 current_user.id 進行驗證
            initial_detail = await run_in_threadpool(job_management.get_job_detail, manager, job_id, current_user.id)
            yield f"data: {json.dumps(initial_detail)}\n\n"
            if (
                initial_detail["status"] in ["completed", "error", "paused", "pending"]
                and not initial_detail["is_running"]
            ):
                logger.info("Job %s stopped. Closing SSE stream immediately.", job_id)
                return
        except ValueError as e:
            logger.warning("Job %s not found or permission error for SSE stream: %s. Closing.", job_id, e)
            return

        # 2. 建立 Queue 並訂閱事件
        queue: asyncio.Queue[str] = asyncio.Queue()

        def on_update(detail_str: str) -> None:
            queue.put_nowait(detail_str)

        event_name = f"job_progress_updated_{job_id}"
        from backend.events import subscribe, unsubscribe  # pylint: disable=import-outside-toplevel

        subscribe(event_name, on_update)

        # 3. 通知背景輪詢器開始關注此任務
        from backend.jobs.services.poller import job_progress_poller  # pylint: disable=import-outside-toplevel

        job_progress_poller.add_job(job_id)

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("SSE client for job %s disconnected.", job_id)
                    break

                try:
                    # 使用 wait_for 以便定期檢查連線是否中斷
                    current_data_str = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield f"data: {current_data_str}\n\n"

                    detail = json.loads(current_data_str)
                    if detail.get("status") in ["completed", "error", "paused", "pending"] and not detail.get(
                        "is_running"
                    ):
                        logger.info("Job %s stopped. Closing SSE stream.", job_id)
                        break
                except asyncio.TimeoutError:
                    continue
        finally:
            # 4. 確保斷線時清理資源
            unsubscribe(event_name, on_update)
            job_progress_poller.remove_job(job_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
