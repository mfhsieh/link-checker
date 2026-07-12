"""
背景排程器服務。

負責定時檢查是否有正在排隊中 (queued) 的任務，並在目前系統資源有餘裕時將其喚醒執行。
"""

import logging

from sqlalchemy.exc import SQLAlchemyError

from backend.config import get_settings
from backend.deps import get_job_manager
from backend.jobs.services.management import start_job
from crawler.models import Job

logger: logging.Logger = logging.getLogger(__name__)


def check_and_spawn_queued_jobs() -> None:
    """
    檢查並喚醒排隊中的任務。

    若目前系統中 running / starting 狀態的任務數量低於
    `CRAWLER_MAX_CONCURRENT_JOBS`，則會從資料庫取出最舊的
    `queued` 任務，並將其推進至執行狀態。

    Raises:
        SQLAlchemyError: 資料庫存取錯誤時拋出，由外層捕抓。
        ValueError: 任務狀態不符或參數錯誤時由 start_job 拋出。
        OSError: 建立爬蟲子程序時遭遇系統錯誤拋出。
        Exception: 其他非預期例外將拋出交由事件迴圈處理。
    """
    settings = get_settings()
    max_concurrent = settings.CRAWLER_MAX_CONCURRENT_JOBS

    if max_concurrent <= 0:
        return

    manager = get_job_manager()

    with manager.session_factory() as session:
        active_count = session.query(Job).filter(Job.status.in_(["starting", "running"])).count()
        if active_count >= max_concurrent:
            return

        available_slots = max_concurrent - active_count
        queued_jobs = (
            session.query(Job)
            .filter(Job.status == "queued")
            .order_by(Job.updated_at.asc(), Job.created_at.asc())
            .limit(available_slots)
            .all()
        )

        job_ids = [job.id for job in queued_jobs]

    # 脫離 session scope，避免 spawn 過程拉長資料庫鎖定時間
    for job_id in job_ids:
        logger.info("排程器分配可用資源 (Slot)，準備喚醒任務: %s", job_id)
        try:
            # user_id=None 觸發系統排程啟動邏輯
            start_job(manager, job_id, user_id=None)
        except ValueError as e:
            logger.error("排程器啟動任務 %s 失敗 (資料狀態或參數異常): %s", job_id, e)
        except SQLAlchemyError as e:
            logger.error("排程器啟動任務 %s 失敗 (資料庫存取異常): %s", job_id, e)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.critical("[SCHEDULER_FAILURE] 排程器喚醒任務 %s 時發生未預期錯誤: %s", job_id, e, exc_info=True)
