"""
任務局部重新探測 (Reprobe) 服務模組。

本模組負責處理使用者在介面上觸發的「重新探測」操作，包含內部連結 (自家網頁)
與外部連結的重測邏輯。主要行為是將對應的資料庫紀錄狀態重置為 pending，
並將已完成或暫停的任務切換回暫停 (paused) 狀態，以便背景的爬蟲服務 (Crawler Runner)
在重新啟動後接續處理這些 pending 的項目。
"""

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from crawler.manager import JobManager
from crawler.models import CrawlQueue, ExternalLink, Job

logger: logging.Logger = logging.getLogger(__name__)


# pylint: disable=too-many-arguments
def reprobe_external_links(
    db: DBSession, manager: JobManager, job_id: str, user_id: str, urls: list[str], group_by: str = "none"
) -> dict[str, object]:
    """
    將指定的外部連結標記為待重新探測 (pending)。

    此函式並不會同步執行 HTTP 網路請求，而是將資料庫中指定的 `ExternalLink`
    紀錄狀態重置為 `pending`，清空先前的 HTTP 狀態碼與錯誤訊息。同時，若任務目前
    處於已完成 (completed) 或錯誤 (error) 狀態，將其切換為暫停 (paused)，
    以便使用者後續可以點擊「啟動任務」交由背景爬蟲程式接手處理。

    Args:
        db (DBSession): SQLAlchemy 的資料庫連線階段。
        manager (JobManager): 負責管理任務實體與狀態的管理器。
        job_id (str): 欲操作的目標任務 ID。
        user_id (str): 當前發起請求的使用者 ID。
        urls (list[str]): 欲重新探測的外部網址 (target_url) 清單。
        group_by (str): 分組模式。

    Returns:
        dict[str, object]: 包含狀態與更新成功訊息的字典 (例如 `{"status": "success", "message": "..."}`)。

    Raises:
        ValueError: 若找不到指定的任務 ID，或當前使用者無權限操作該任務時拋出。
    """
    job = manager.get_job(job_id)
    if not job or job.user_id != user_id:
        raise ValueError("找不到任務或無權限操作")

    query = db.query(ExternalLink).filter(ExternalLink.job_id == job_id)
    if group_by == "source":
        query = query.filter(ExternalLink.source_url.in_(urls))
    elif group_by == "domain":
        query = query.filter(ExternalLink.target_domain.in_(urls))
    else:
        query = query.filter(ExternalLink.target_url.in_(urls))

    # 更新 ExternalLink，清空既有結果並將狀態重置為 pending
    query.update(
        {
            "status_category": "pending",
            "http_status_code": None,
            "error_message": None,
        },
        synchronize_session=False,
    )

    # 確保 Job 狀態切換為 paused，以便前端顯示「啟動任務」按鈕
    job_record = db.query(Job).filter(Job.id == job_id).first()
    if job_record and job_record.status in ("completed", "error"):
        job_record.status = "paused"

    db.commit()

    return {"status": "success", "message": f"已將 {len(urls)} 個外部連結設為待測狀態"}


# pylint: disable=too-many-arguments
def reprobe_internal_links(
    db: DBSession, manager: JobManager, job_id: str, user_id: str, urls: list[str], group_by: str = "none"
) -> dict[str, object]:
    """
    將指定的內部連結 (自家網頁) 標記為待重新探測 (pending)，並清除其衍生的外連紀錄。

    當使用者修正了自家網頁的內容並希望重新掃描時，此函式會先刪除舊有由這些網頁
    (source_url) 所萃取出來的 `ExternalLink` 紀錄，避免重新爬取時產生重複或髒資料。
    接著將 `CrawlQueue` 中對應的紀錄狀態重置為 `pending`，最後若任務處於已完成或
    錯誤狀態，則將其切換為暫停 (paused) 準備讓背景爬蟲接手。

    Args:
        db (DBSession): SQLAlchemy 的資料庫連線階段。
        manager (JobManager): 負責管理任務實體與狀態的管理器。
        job_id (str): 欲操作的目標任務 ID。
        user_id (str): 當前發起請求的使用者 ID。
        urls (list[str]): 欲重測的內部網址清單。
        group_by (str): 分組模式。

    Returns:
        dict[str, object]: 包含操作成功訊息的字典。

    Raises:
        ValueError: 若找不到指定的任務 ID，或當前使用者無權限操作該任務時拋出。
    """
    job = manager.get_job(job_id)
    if not job or job.user_id != user_id:
        raise ValueError("找不到任務或無權限操作")

    if group_by == "source":
        # 刪除之前由這些內部連結 (source_url) 萃取出的外部連結，確保重新爬取時的資料純淨度
        db.query(ExternalLink).filter(ExternalLink.job_id == job_id, ExternalLink.source_url.in_(urls)).delete(
            synchronize_session=False
        )

        # 針對母網頁重設
        db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url.in_(urls)).update(
            {
                "status": "pending",
                "status_category": "pending",
                "retry_count": 0,
                "status_code": None,
                "error_message": None,
            },
            synchronize_session=False,
        )

        # 針對其子代異常網頁也重設
        db.query(CrawlQueue).filter(
            CrawlQueue.job_id == job_id,
            CrawlQueue.source_url.in_(urls),
            or_(CrawlQueue.status.in_(["failed", "warning"]), CrawlQueue.is_secure.is_(False)),
        ).update(
            {
                "status": "pending",
                "status_category": "pending",
                "retry_count": 0,
                "status_code": None,
                "error_message": None,
            },
            synchronize_session=False,
        )
    else:
        # 平面模式：直接重設被勾選的網頁本身
        db.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url.in_(urls)).update(
            {
                "status": "pending",
                "status_category": "pending",
                "retry_count": 0,
                "status_code": None,
                "error_message": None,
            },
            synchronize_session=False,
        )
        # 視情況清除其子代衍生的外連（確保重新爬取能刷新外連）
        db.query(ExternalLink).filter(ExternalLink.job_id == job_id, ExternalLink.source_url.in_(urls)).delete(
            synchronize_session=False
        )

    # 若任務已結束或發生錯誤，則切換回暫停 (paused) 狀態以利後續重新啟動
    if job.status in ("completed", "error"):
        db.query(Job).filter(Job.id == job_id).update({"status": "paused"}, synchronize_session=False)
        job.status = "paused"

    db.commit()

    return {"message": "已將選取的內部連結設為待爬取，請點擊「啟動任務」以重新處理。"}
