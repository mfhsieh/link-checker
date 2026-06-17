"""
報表匯出相關 API 端點。
"""

import csv
import io
import json
import logging
import os
import tempfile
import zipfile
from collections.abc import Generator, Iterator

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
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.deps import get_crawler_db, get_current_user
from backend.jobs.schemas import (
    ExportQueryArgs,
    JobResultQuery,
)
from backend.jobs.services import results as job_results
from crawler.exporter import _sanitize_csv_value
from crawler.models import Job

logger: logging.Logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _sanitize_csv_dict(row: dict[str, object]) -> dict[str, object]:
    """
    對 CSV 字典資料進行跳脫。

    Args:
        row (dict[str, object]): 原始資料字典。

    Returns:
        dict[str, object]: 安全跳脫後的字典。
    """
    return {k: _sanitize_csv_value(v) for k, v in row.items()}


def _write_iterator_to_zip(zf: zipfile.ZipFile, csv_filename: str, iterator: Iterator[dict[str, object]]) -> None:
    """
    從 iterator 讀取資料並寫入 ZIP 中的 CSV 檔。

    Args:
        zf (zipfile.ZipFile): ZIP 壓縮檔物件。
        csv_filename (str): 要寫入的 CSV 檔案名稱。
        iterator (Iterator[dict[str, object]]): 來源資料的產生器。
    """
    try:
        first_item = next(iterator)
        with zf.open(csv_filename, "w") as f:
            with io.TextIOWrapper(f, encoding="utf-8-sig", newline="") as text_file:
                writer = csv.DictWriter(text_file, fieldnames=list(first_item.keys()))
                writer.writeheader()
                writer.writerow(_sanitize_csv_dict(first_item))
                for item in iterator:
                    writer.writerow(_sanitize_csv_dict(item))
    except StopIteration:
        pass


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
        query_obj = JobResultQuery.from_query_args(job_id, current_user.id, query_args)
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
            for item in job_results.stream_job_results(db, query_obj):
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

        for item in job_results.stream_job_results(db, query_obj):
            if query_args.group_by == "domain":
                fieldnames = [
                    "Domain",
                    "Occurrence Count",
                    "Unique URLs Count",
                    "Unique URLs",
                    "Source URLs",
                ]
                row_data = {
                    "Domain": item["domain"],
                    "Occurrence Count": item["occurrence_count"],
                    "Unique URLs Count": item["unique_urls_count"],
                    "Unique URLs": "\n".join(item["unique_urls"]),
                    "Source URLs": "\n".join(item["source_urls"]),
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


@router.get("/{job_id}/internal-results/export")
# pylint: disable=too-many-arguments
def export_internal_results(
    job_id: str,
    query_filter: str | None = Query(
        None,
        alias="filter",
        pattern="^(not_found|server_error|access_denied|timeout|connection_error|other_error|warning|all)$",
    ),
    group_by: str = Query("none", pattern="^(none|source)$"),
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> Response:
    """
    匯出內部失效結果（CSV 或 JSON 格式下載）。

    Args:
        job_id (str): 任務 UUID。
        query_filter (str | None): 狀態過濾條件。
        group_by (str): 聚合方式。
        fmt (str): 輸出格式。
        current_user (User): 當前登入使用者。
        db (DBSession): Crawler 資料庫 Session。

    Returns:
        Response: 包含匯出檔案內容的 FastAPI Response 物件。

    Raises:
        HTTPException 404: 若任務不存在或不屬於當前使用者。
    """
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.user_id != current_user.id:
            raise ValueError(f"找不到任務 ID: {job_id}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    filename = f"job_{job_id}_internal_results"
    if query_filter and query_filter != "all":
        filename += f"_{query_filter}"
    if group_by != "none":
        filename += f"_by_{group_by}"

    if fmt == "json":

        def json_generator() -> Generator[str, None, None]:
            """
            產生 JSON 格式輸出字串的產生器。

            Yields:
                str: 區塊的 JSON 字串。
            """
            yield "[\n"
            first = True
            for item in job_results.stream_internal_errors(db, job_id, current_user.id, query_filter, group_by):
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

    def csv_generator() -> Generator[str, None, None]:
        """
        產生 CSV 格式輸出字串的產生器。

        Yields:
            str: 區塊的 CSV 字串。
        """
        yield "\ufeff"
        output = io.StringIO()
        writer = None
        for item in job_results.stream_internal_errors(db, job_id, current_user.id, query_filter, group_by):
            if group_by == "source":
                fieldnames = ["Source URL", "Failure Count", "Target URLs"]
                row_data = {
                    "Source URL": item["source_url"],
                    "Failure Count": item["occurrence_count"],
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
        internal_iterator = job_results.stream_internal_results(db, job_id, current_user.id)
        _write_iterator_to_zip(zf, f"job_{job_id}_crawl_records.csv", internal_iterator)

        query_obj = JobResultQuery(job_id=job_id, user_id=current_user.id, group_by="none")
        external_iterator = job_results.stream_job_results(db, query_obj)
        _write_iterator_to_zip(zf, f"job_{job_id}_external_links.csv", external_iterator)

    filename = f"job_{job_id}_full_report.zip"
    return FileResponse(
        temp_path,
        media_type="application/zip",
        filename=filename,
    )
