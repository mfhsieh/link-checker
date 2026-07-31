"""
任務結果查詢相關 API 端點。
"""

import csv
import json
import logging
from io import StringIO

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.cache_utils import get_cached_job_result
from backend.deps import get_crawler_db, get_current_user
from backend.jobs.schemas import InternalResultQuery, JobResultQuery, ResultsQueryArgs
from backend.jobs.services import diff, external_results, internal_results
from crawler.models import Job, JobDiffItem, JobDiffResult

logger: logging.Logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}/results")
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
        query_obj = JobResultQuery.from_query_args(job_id, current_user.id, query_args)
        return external_results.get_job_results(db, query_obj)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/results/summary")
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
        job = db.get(Job, job_id)
        if not job or (job.user_id != current_user.id and current_user.role != "admin"):
            raise ValueError(f"Job not found: {job_id}")

        def compute():
            return external_results.get_results_summary(db, job_id, current_user.id, exclude, group_by)

        return get_cached_job_result(
            job_status=job.status,
            job_updated_at=job.updated_at.timestamp(),
            job_id=job_id,
            endpoint_name="results_summary",
            params={"exclude": exclude, "group_by": group_by},
            compute_func=compute,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/diff")
def get_job_diff(  # pylint: disable=too-many-arguments
    job_id: str,
    compare_with: str = Query(..., description="要比對的新任務 ID (對照組)"),
    exclude: str | None = Query(None, description="排除指定的目標網域（多個以逗號分隔）"),
    scope: str = Query("all", description="比對範疇 (all, external, internal)"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    比對兩個任務的結果差異 (支援外部連結與內部網頁，以及排除網域)。

    以 job_id 作為基準 (舊任務)，compare_with 作為對照 (新任務)。

    Args:
        job_id (str): 基準任務 ID。
        compare_with (str): 對照任務 ID。
        exclude (str | None): 要排除的目標網域。
        scope (str): 比對範疇 ('all', 'external', 'internal')。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 差異比對報表。

    Raises:
        HTTPException 404: 找不到任務時拋出。
    """
    try:
        job = db.get(Job, job_id)
        if not job or (job.user_id != current_user.id and current_user.role != "admin"):
            raise ValueError(f"Job not found: {job_id}")

        return diff.get_job_diff(
            db,
            base_job_id=job_id,
            compare_job_id=compare_with,
            user_id=current_user.id,
            exclude=exclude,
            scope=scope,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/diff/items")
# pylint: disable=too-many-arguments
def get_job_diff_items(
    job_id: str,
    compare_with: str = Query(..., description="要比對的新任務 ID (對照組)"),
    category: str = Query(..., description="分類名稱"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    取得任務比對明細的分頁資料。
    """
    try:
        job = db.get(Job, job_id)
        if not job or (job.user_id != current_user.id and current_user.role != "admin"):
            raise ValueError(f"Job not found: {job_id}")

        diff_record = db.query(JobDiffResult).filter_by(job_a_id=job_id, job_b_id=compare_with).first()
        if not diff_record:
            raise ValueError("尚未建立比對結果，請先呼叫 /diff API。")

        # 確保更新 last_accessed_at
        diff_record.last_accessed_at = diff.get_utc_now()
        db.commit()

        query = db.query(JobDiffItem).filter(JobDiffItem.diff_id == diff_record.id, JobDiffItem.category == category)
        total = query.count()
        items = query.order_by(JobDiffItem.id).offset((page - 1) * page_size).limit(page_size).all()

        parsed_items = []
        for it in items:
            parsed_items.append(json.loads(it.details_json))

        return {"total": total, "page": page, "page_size": page_size, "items": parsed_items}

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/diff/export")
# pylint: disable=too-many-arguments,redefined-builtin
def export_job_diff(
    job_id: str,
    compare_with: str = Query(..., description="要比對的新任務 ID (對照組)"),
    category: str = Query(..., description="分類名稱"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
):
    """
    匯出任務比對明細。
    """
    job = db.get(Job, job_id)
    if not job or (job.user_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    diff_record = db.query(JobDiffResult).filter_by(job_a_id=job_id, job_b_id=compare_with).first()
    if not diff_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未建立比對結果，請先呼叫 /diff API。")

    diff_record.last_accessed_at = diff.get_utc_now()
    db.commit()

    query = (
        db.query(JobDiffItem)
        .filter(JobDiffItem.diff_id == diff_record.id, JobDiffItem.category == category)
        .order_by(JobDiffItem.id)
    )

    filename = f"diff_{category}.{format}"

    if format == "json":

        def generate_json():
            yield "["
            first = True
            for item in query.yield_per(1000):
                if not first:
                    yield ","
                yield item.details_json
                first = False
            yield "]"

        return StreamingResponse(
            generate_json(),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # CSV
    def generate_csv():
        buf = StringIO()
        writer = None
        for item in query.yield_per(1000):
            data = json.loads(item.details_json)
            # 將 list 型別的來源網址轉成字串
            if "sources" in data and isinstance(data["sources"], list):
                data["sources"] = " | ".join(data["sources"])

            if writer is None:
                writer = csv.DictWriter(buf, fieldnames=data.keys())
                writer.writeheader()
            writer.writerow(data)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        generate_csv(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/{job_id}/internal-results/summary")
def get_internal_results_summary(
    job_id: str,
    group_by: str = Query("none", pattern="^(none|source)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    取得任務內部網頁爬取失敗的統計摘要。

    Args:
        job_id (str): 任務 ID。
        group_by (str): 聚合方式。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 內部結果統計。

    Raises:
        HTTPException 404: 找不到任務或無權限存取時拋出。
    """
    try:
        job = db.get(Job, job_id)
        if not job or (job.user_id != current_user.id and current_user.role != "admin"):
            raise ValueError(f"Job not found: {job_id}")

        def compute():
            return internal_results.get_internal_results_summary(db, job_id, current_user.id, group_by)

        return get_cached_job_result(
            job_status=job.status,
            job_updated_at=job.updated_at.timestamp(),
            job_id=job_id,
            endpoint_name="internal_results_summary",
            params={"group_by": group_by},
            compute_func=compute,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/internal-results")
# pylint: disable=too-many-arguments
def get_internal_results(
    job_id: str,
    status_filter: str | None = Query(
        None,
        alias="filter",
        pattern="^(not_found|server_error|blocked|timeout|connection_error|other_error|warning|all|insecure)$",
    ),
    group_by: str = Query("none", pattern="^(none|source)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_asc: bool = Query(True),
    col_filters: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_crawler_db),
) -> dict[str, object]:
    """
    取得內部網頁爬取失敗的紀錄列表（支援分頁）。

    Args:
        job_id (str): 任務 ID。
        page (int): 頁碼。
        page_size (int): 每頁筆數。
        status_filter (str | None): 對應資料庫 status_category 欄位的篩選條件。
        group_by (str): 分組方式。
        sort_by (str | None): 排序欄位。
        sort_asc (bool): 升冪或降冪排序。
        col_filters (str | None): 欄位過濾條件。
        current_user (User): 當前登入的使用者。
        db (DBSession): Crawler DB Session。

    Returns:
        dict[str, object]: 包含內部網頁爬取紀錄列表與分頁資訊的字典。
            清單項目之鍵名為向後相容舊有 CSV/Excel 導出，部分保留 Legacy 大寫空格設計（如 Status 等）。

    Raises:
        HTTPException 404: 找不到任務或無權限存取時拋出。
    """
    try:
        query_args = InternalResultQuery(
            job_id=job_id,
            user_id=current_user.id,
            status_filter=status_filter,
            group_by=group_by,
            page=page,
            page_size=page_size,
            truncate_lists=True,
            sort_by=sort_by,
            sort_asc=sort_asc,
            col_filters=col_filters,
        )
        return internal_results.get_internal_errors(db, query_args)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
