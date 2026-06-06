"""
任務管理 API 路由。

實作 §13.2 與 §13.3 定義的端點：
- GET    /api/jobs            — 列出當前使用者的任務
- POST   /api/jobs            — 建立新任務
- GET    /api/jobs/{id}       — 取得任務詳情
- POST   /api/jobs/{id}/start  — 啟動任務
- POST   /api/jobs/{id}/pause  — 暫停任務
- POST   /api/jobs/{id}/resume — 恢復任務
- POST   /api/jobs/{id}/reset  — 重置任務
- DELETE /api/jobs/{id}       — 刪除任務
- GET    /api/jobs/{id}/results          — 外連結果列表
- GET    /api/jobs/{id}/results/summary  — 統計摘要
- GET    /api/jobs/{id}/results/export   — 匯出 CSV / JSON
"""

import csv
import io
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.deps import get_crawler_db, get_current_user, get_job_manager, require_csrf
from backend.jobs import service as job_service
from crawler.manager import JobManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Request Schema ─────────────────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    """建立任務請求的 Schema。"""
    start_url: str
    target_domains: list[str]
    internal_domains: list[str] = []
    ignore_regexes: list[str] = []
    max_depth: int | None = None
    max_pages: int | None = None
    delay: float | None = None
    timeout: int | None = None

    @field_validator("start_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """驗證 URL 格式。"""
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("起始 URL 必須以 http:// 或 https:// 開頭。")
        return v

    @field_validator("target_domains")
    @classmethod
    def validate_domains(cls, v: list[str]) -> list[str]:
        """確保至少有一個目標網域。"""
        if not v:
            raise ValueError("至少需要指定一個目標網域。")
        return [d.strip() for d in v]


# ── 端點實作 ────────────────────────────────────────────────────────────────────

@router.get("", status_code=status.HTTP_200_OK)
async def list_jobs(
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> list[dict[str, Any]]:
    """列出當前使用者的所有任務。"""
    return job_service.list_jobs(manager, current_user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    """建立新的爬蟲任務。"""
    # 組建 crawler_config（從全域設定合併）
    crawler_config: dict[str, Any] = {}
    if body.ignore_regexes:
        crawler_config["ignore_regexes"] = body.ignore_regexes
    if body.max_depth is not None:
        crawler_config["max_depth"] = body.max_depth
    if body.max_pages is not None:
        crawler_config["max_pages"] = body.max_pages
    if body.delay is not None:
        crawler_config["delay"] = body.delay
    if body.timeout is not None:
        crawler_config["timeout"] = body.timeout

    try:
        config_obj = job_service.JobCreateConfig(
            start_url=body.start_url,
            target_domains=body.target_domains,
            internal_domains=body.internal_domains,
            crawler_config=crawler_config,
        )
        job_id = job_service.create_job(manager, current_user.id, config_obj)
    except Exception as e:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    return {"job_id": job_id, "message": "任務已建立。"}


@router.get("/{job_id}", status_code=status.HTTP_200_OK)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> dict[str, Any]:
    """取得任務詳情（含進度）。"""
    try:
        return job_service.get_job_detail(manager, job_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{job_id}/start", status_code=status.HTTP_200_OK)
async def start_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """啟動任務（spawn 爬蟲子程序）。"""
    try:
        job_service.start_job(manager, job_id, current_user.id)
        return {"message": "任務已啟動。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/pause", status_code=status.HTTP_200_OK)
async def pause_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """暫停任務（協同暫停，更新 DB 狀態）。"""
    try:
        job_service.pause_job(manager, job_id, current_user.id)
        return {"message": "已發送暫停指令，任務將在完成當前網頁後停止。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{job_id}/resume", status_code=status.HTTP_200_OK)
async def resume_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """恢復已暫停的任務（只允許 paused 狀態）。"""
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
async def reset_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """重置任務（清除結果並回到 pending 狀態）。"""
    try:
        job_service.reset_job(manager, job_id, current_user.id)
        return {"message": "任務已重置。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{job_id}", status_code=status.HTTP_200_OK)
async def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, str]:
    """刪除任務及所有相關資料。"""
    try:
        job_service.delete_job(manager, job_id, current_user.id)
        return {"message": "任務已刪除。"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class ResultsQueryArgs:
    """任務結果查詢參數。"""
    # pylint: disable=too-few-public-methods,too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        status_filter: str | None = Query(
            None, alias="filter", pattern="^(dead|broken|unapproved)$"
        ),
        search: str | None = Query(None),
        group: bool = Query(False),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        """初始化結果查詢參數。"""
        self.status_filter = status_filter
        self.search = search
        self.group = group
        self.page = page
        self.page_size = page_size


@router.get("/{job_id}/results", status_code=status.HTTP_200_OK)
async def get_results(
    job_id: str,
    query_args: ResultsQueryArgs = Depends(),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, Any]:
    """外連結果列表（支援篩選、搜尋、去重聚合與分頁）。"""
    try:
        query_obj = job_service.JobResultQuery(
            job_id=job_id,
            user_id=current_user.id,
            status_filter=query_args.status_filter,
            search=query_args.search,
            group=query_args.group,
            page=query_args.page,
            page_size=query_args.page_size,
        )
        return job_service.get_job_results(db, query_obj)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/results/summary", status_code=status.HTTP_200_OK)
async def get_results_summary(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, Any]:
    """取得任務結果統計摘要。"""
    try:
        return job_service.get_results_summary(db, job_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


class ExportQueryArgs:
    """匯出結果查詢參數。"""
    # pylint: disable=too-few-public-methods,too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        status_filter: str | None = Query(
            None, alias="filter", pattern="^(dead|broken|unapproved)$"
        ),
        group: bool = Query(False),
        fmt: str = Query("csv", pattern="^(csv|json)$"),
    ) -> None:
        """初始化匯出查詢參數。"""
        self.status_filter = status_filter
        self.group = group
        self.fmt = fmt


@router.get("/{job_id}/results/export")
async def export_results(
    job_id: str,
    query_args: ExportQueryArgs = Depends(),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> Response:
    """
    匯出外連結果（CSV 或 JSON 格式下載）。

    查詢參數：
    - filter: dead / broken / unapproved
    - group: 是否去重聚合
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
            group=query_args.group,
            page=1,
            page_size=999999,
        )
        results = job_service.get_job_results(db, query_obj)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    items = results["items"]
    filename = f"job_{job_id}_results"
    if query_args.status_filter:
        filename += f"_{query_args.status_filter}"
    if query_args.group:
        filename += "_grouped"

    if query_args.fmt == "json":
        content = json.dumps(items, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    # CSV 格式
    output = io.StringIO()
    if items:
        writer = csv.DictWriter(output, fieldnames=list(items[0].keys()))
        writer.writeheader()
        for item in items:
            writer.writerow(item)

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
