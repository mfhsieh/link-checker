"""
爬蟲任務事件服務模組 (Crawler Job Events Service)。

此模組負責監聽系統內部發布的各種領域事件，並執行對應的任務管理或清理邏輯，
藉以解除 Crawler 與其他領域模組（如 Auth）間的直接依賴。
"""

import logging

from sqlalchemy.exc import SQLAlchemyError

from backend.deps import get_job_manager
from backend.events import SystemEvent, publish, subscribe
from crawler.models import Job

logger = logging.getLogger(__name__)


def on_user_permanently_deleted(user_id: str) -> None:
    """
    處理使用者被永久刪除的事件。

    當 Auth 模組實體刪除使用者時觸發，負責清理 Crawler DB 中與該使用者相關的所有爬蟲任務。
    若清理失敗，將發送反向事件讓 Auth 模組記錄該失敗資訊。

    Args:
        user_id (str): 被永久刪除的使用者 ID。
    """
    manager = get_job_manager()
    crawler_session_factory = manager.session_factory

    try:
        with crawler_session_factory() as crawler_db:
            crawler_jobs = crawler_db.query(Job).filter(Job.user_id == user_id).all()
            for job in crawler_jobs:
                crawler_db.delete(job)
            crawler_db.commit()
            if crawler_jobs:
                logger.info("已背景清理使用者 %s 的 %d 個爬蟲任務", user_id, len(crawler_jobs))
    except SQLAlchemyError as e:
        logger.critical(
            "[DATA_INCONSISTENCY_ALERT] 背景清理 Crawler DB 時發生錯誤，使用者 %s 的爬蟲資料可能成為孤兒資料: %s",
            user_id,
            e,
            exc_info=True,
        )
        publish(SystemEvent.USER_CLEANUP_FAILED, user_id=user_id, detail=str(e))


def register_job_events() -> None:
    """
    註冊所有與爬蟲任務相關的事件監聽器。

    在應用程式啟動時呼叫，將對應的事件處理函式綁定到事件匯流排上。
    """
    subscribe(SystemEvent.USER_PERMANENTLY_DELETED, on_user_permanently_deleted)
