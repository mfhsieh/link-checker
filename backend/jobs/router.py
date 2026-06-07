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
- DELETE /api/jobs/{id}                   — 刪除任務
- GET    /api/jobs/{id}/results           — 外連結果列表
- GET    /api/jobs/{id}/results/summary   — 統計摘要
- GET    /api/jobs/{id}/results/export    — 匯出 CSV / JSON
"""

import csv
import io
import json
import logging
import os
import tempfile
import zipfile
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.config import get_settings
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
    ignore_extensions: list[str] = []
    ignore_regexes: list[str] = []
    max_depth: int | None = None
    max_pages: int | None = None
    delay: float | None = None
    timeout: int | None = None
    retries: int | None = None
    proxy_url: str | None = None

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

@router.get("/default-config", status_code=status.HTTP_200_OK)
async def get_default_config(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """取得任務預設的全域配置，供前端建立任務時填入預設值與限制。"""
    # pylint: disable=import-outside-toplevel
    from crawler.config_utils import DEFAULT_GLOBAL_CONFIG

    settings = get_settings()
    config_path = settings.GLOBAL_CONFIG_PATH
    crawler_config = DEFAULT_GLOBAL_CONFIG.get("crawler", {})

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "crawler" in data:
                    crawler_config = data["crawler"]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("讀取全域設定檔失敗: %s", e)

    # 僅提取前端有使用到的欄位，過濾掉不需要暴露的敏感或內部配置
    allowed_keys = {
        "ignore_extensions", "ignore_regexes",
        "delay", "min_delay", "max_delay",
        "timeout", "min_timeout", "max_timeout",
        "retries", "min_retries", "max_retries",
        "proxy_url"
    }

    return {k: v for k, v in crawler_config.items() if k in allowed_keys}

@router.get("", status_code=status.HTTP_200_OK)
async def list_jobs(
    status_filter: str | None = Query(None, alias="status", description="依任務狀態篩選"),
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
) -> list[dict[str, Any]]:
    """列出當前使用者的所有任務。"""
    return job_service.list_jobs(manager, current_user.id, status=status_filter)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(
    body: CreateJobRequest,
    current_user: User = Depends(get_current_user),
    manager: JobManager = Depends(get_job_manager),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    """建立新的爬蟲任務。"""
    
    # 安全白名單：只允許前端設定特定的 crawler_config 欄位
    allowed_crawler_keys = {
        "ignore_extensions", "ignore_regexes",
        "max_depth", "max_pages", "delay", "timeout",
        "retries", "proxy_url"
    }

    # 透過白名單動態過濾並組建 crawler_config
    body_dict = body.model_dump()
    user_crawler_config: dict[str, Any] = {}
    for key in allowed_crawler_keys:
        val = body_dict.get(key)
        # 過濾掉 None 與空字串/空陣列，避免覆蓋掉全域預設設定
        if val is not None and val != [] and val != "":
            user_crawler_config[key] = val

    # 根據規格書 §4：將全域設定與個別任務設定合併，產生「最終執行配置快照」
    # pylint: disable=import-outside-toplevel
    from crawler.config_utils import merge_and_validate_crawler_config

    settings = get_settings()
    global_config = {}
    if os.path.exists(settings.GLOBAL_CONFIG_PATH):
        try:
            with open(settings.GLOBAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                global_config = yaml.safe_load(f) or {}
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("建立快照時讀取全域設定檔失敗: %s", e)

    final_crawler_config = merge_and_validate_crawler_config(
        {"crawler": user_crawler_config}, global_config
    )

    try:
        config_obj = job_service.JobCreateConfig(
            start_url=body.start_url,
            target_domains=body.target_domains,
            internal_domains=body.internal_domains,
            crawler_config=final_crawler_config,
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
            None, alias="filter", pattern="^(dead|broken|insecure)$"
        ),
        search: str | None = Query(None),
        exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ) -> None:
        """初始化結果查詢參數。"""
        self.status_filter = status_filter
        self.search = search
        self.exclude = exclude
        self.group_by = group_by
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
            exclude=query_args.exclude,
            group_by=query_args.group_by,
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
            None, alias="filter", pattern="^(dead|broken|insecure)$"
        ),
        exclude: str | None = Query(None),
        group_by: str = Query("none", pattern="^(none|target|source|domain)$"),
        fmt: str = Query("csv", pattern="^(csv|json)$"),
    ) -> None:
        """初始化匯出查詢參數。"""
        self.status_filter = status_filter
        self.exclude = exclude
        self.group_by = group_by
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
        def json_generator():
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
    def csv_generator():
        yield "\ufeff"  # BOM for Excel
        first = True
        for item in job_service.stream_job_results(db, query_obj):
            output = io.StringIO()
            if first:
                if query_args.group_by == "domain":
                    writer = csv.DictWriter(output, fieldnames=["Domain", "Occurrence Count", "Unique URLs Count", "Unique URLs"])
                elif query_args.group_by == "source":
                    writer = csv.DictWriter(output, fieldnames=["Source URL", "External Link Count", "Target URLs"])
                else:
                    writer = csv.DictWriter(output, fieldnames=list(item.keys()))
                writer.writeheader()
                first = False

            if query_args.group_by == "domain":
                urls_str = "\n".join(item["unique_urls"])
                writer = csv.DictWriter(output, fieldnames=["Domain", "Occurrence Count", "Unique URLs Count", "Unique URLs"])
                writer.writerow({
                    "Domain": item["domain"],
                    "Occurrence Count": item["occurrence_count"],
                    "Unique URLs Count": item["unique_urls_count"],
                    "Unique URLs": urls_str
                })
            elif query_args.group_by == "source":
                targets_str = "\n".join([f"[{t['status']}] {t['url']}" for t in item["targets"]])
                writer = csv.DictWriter(output, fieldnames=["Source URL", "External Link Count", "Target URLs"])
                writer.writerow({
                    "Source URL": item["source_url"],
                    "External Link Count": item["occurrence_count"],
                    "Target URLs": targets_str
                })
            else:
                writer = csv.DictWriter(output, fieldnames=list(item.keys()))
                writer.writerow(item)
            
            yield output.getvalue()

    return StreamingResponse(
        csv_generator(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )

@router.get("/{job_id}/export/full")
async def export_full_report(
    job_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> Response:
    """
    匯出完整報表 (ZIP 壓縮檔)，內含爬取紀錄與外連清單。
    """
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.user_id != current_user.id:
            raise ValueError(f"找不到任務 ID: {job_id}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    def cleanup():
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
                    writer.writerow(first_internal)
                    for item in internal_iterator:
                        writer.writerow(item)
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
                    writer.writerow(first_external)
                    for item in external_iterator:
                        writer.writerow(item)
        except StopIteration:
            pass

    filename = f"job_{job_id}_full_report.zip"
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename,
    )
