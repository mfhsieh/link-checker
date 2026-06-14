"""
任務結果查詢相關 API 端點。
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session as DBSession

from backend.auth.models import User
from backend.deps import get_crawler_db, get_current_user
from backend.jobs.schemas import JobResultQuery, ResultsQueryArgs
from backend.jobs.services import results as job_results

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
        return job_results.get_job_results(db, query_obj)
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
        return job_results.get_results_summary(db, job_id, current_user.id, exclude, group_by)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/diff")
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
        return job_results.get_job_diff(
            db,
            base_job_id=job_id,
            compare_job_id=compare_with,
            user_id=current_user.id,
            exclude=exclude,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


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
    """
    try:
        return job_results.get_internal_results_summary(db, job_id, current_user.id, group_by)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{job_id}/internal-results")
# pylint: disable=too-many-arguments
def get_internal_results(
    job_id: str,
    status_filter: str | None = Query(
        None,
        alias="filter",
        pattern="^(not_found|server_error|access_denied|timeout|connection_error|other_error|all)$",
    ),
    group_by: str = Query("none", pattern="^(none|source)$"),
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
        return job_results.get_internal_errors(db, job_id, current_user.id, status_filter, group_by, page, page_size)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
