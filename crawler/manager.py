"""
爬蟲任務 (Job) 管理模組。

此模組提供 JobManager 類別，負責處理資料庫互動、建立爬蟲任務、
管理爬取佇列 (Queue)、處理中斷例外，以及執行主要的爬蟲迴圈。
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, case
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.functions import count as sql_count
from sqlalchemy.sql.functions import sum as sql_sum

from backend.events import publish
from crawler.models import Base, CrawlQueue, ExternalLink, Job
from crawler.runner import JobRunner
from crawler.utils import create_optimized_engine

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class JobCreateOptions:
    """
    任務建立選項。

    Attributes:
        start_url (str): 任務起始網址。
        target_domains (list[str]): 允許爬蟲深入遍歷的目標網域清單。
        trusted_domains (list[str]): 視為信任的網域清單。
        crawler_config (dict[str, object] | None): 爬蟲設定參數字典。
        user_id (str | None): 任務擁有者 ID。
    """

    start_url: str
    target_domains: list[str]
    trusted_domains: list[str]
    crawler_config: dict[str, object] | None = None
    user_id: str | None = None


class JobManager:
    """
    負責在資料庫中管理爬蟲任務與佇列狀態的管理器。

    Attributes:
        engine (Engine): SQLAlchemy 的資料庫引擎物件。
        session_factory (Callable[[], Session]): 用來建立新 SQLAlchemy Session 的工廠 (Factory)。
    """

    def __init__(
        self,
        db_url: str = "sqlite:///db/crawler.db",
    ) -> None:
        """
        初始化 Job 管理器並建立資料庫連線。

        Args:
            db_url (str): 資料庫的連線字串。預設為 'sqlite:///db/crawler.db'。

        Raises:
            OSError: 若建立資料庫目錄失敗時拋出。
            SQLAlchemyError: 若建立資料表失敗時拋出。
        """
        self.engine: Engine = create_optimized_engine(
            db_url=db_url,
            sqlite_timeout=int(os.environ.get("SQLITE_TIMEOUT", "30")),
            pool_size=int(os.environ.get("DB_POOL_SIZE", "40")),
            max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
            pool_pre_ping=os.environ.get("DB_POOL_PRE_PING", "true").lower() == "true",
            sqlite_cache_size=10000,
        )

        Base.metadata.create_all(self.engine)
        self.session_factory: Callable[[], Session] = sessionmaker(bind=self.engine)

    def create_job(
        self,
        options: JobCreateOptions,
    ) -> str:
        """
        建立一個全新的爬蟲任務，並將起始網址加入到佇列中。

        Args:
            options (JobCreateOptions): 任務建立的設定選項。

        Returns:
            str: 新建立任務的 ID。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        config_str: str | None = json.dumps(options.crawler_config) if options.crawler_config is not None else None

        with self.session_factory() as session:
            job: Job = Job(
                user_id=options.user_id,
                start_url=options.start_url,
                target_domains=",".join(options.target_domains),
                trusted_domains=",".join(options.trusted_domains),
                status="pending",
                config_json=config_str,
            )
            session.add(job)
            session.commit()

            # 將起始網址加入佇列
            queue_item: CrawlQueue = CrawlQueue(
                job_id=job.id,
                url=options.start_url,
                source_url=None,
                status="pending",
                is_secure=options.start_url.startswith("https://"),
                depth=0,
            )
            session.add(queue_item)
            session.commit()

            return job.id

    def get_job(self, job_id: str) -> Job | None:
        """
        透過 ID 查詢並取得特定的任務物件。

        Args:
            job_id (str): 欲查詢的任務 ID。

        Returns:
            Job | None: 若找到對應的任務物件則回傳，否則回傳 None。

        Raises:
            SQLAlchemyError: 當資料庫查詢失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if job:
                session.expunge(job)
            return job

    def run_job(
        self,
        job_id: str,
        crawler_config: dict[str, object] | None = None,
        force: bool = False,
        is_api_spawn: bool = False,
    ) -> None:
        """
        執行指定的爬蟲任務，直到佇列清空或遭到使用者中斷為止。

        Args:
            job_id (str): 欲執行的任務 ID。
            crawler_config (dict[str, object] | None): 爬蟲相關的設定參數。
            force (bool): 是否強制接管卡在 running 狀態的任務。
            is_api_spawn (bool): 是否由 API 背景程序觸發。
        """
        runner = JobRunner(self.session_factory, job_id)
        runner.execute(crawler_config, force, is_api_spawn)

    def get_all_jobs(self, user_id: str | None = None, status: str | None = None) -> list[dict[str, object]]:
        """
        取得所有任務的列表與基本資訊。可透過 user_id 進行過濾。

        Args:
            user_id (str | None): (選填) 若提供，則僅回傳該擁有者的任務。
            status (str | None): (選填) 依據任務狀態進行過濾。

        Returns:
            list[dict[str, object]]: 包含任務基本資訊的字典陣列。

        Raises:
            SQLAlchemyError: 當資料庫查詢失敗時拋出。
        """
        with self.session_factory() as session:
            query = session.query(Job)
            if user_id:
                query = query.filter(Job.user_id == user_id)
            if status:
                query = query.filter(Job.status == status)
            jobs = query.order_by(Job.created_at.desc()).all()
            return [
                {
                    "id": job.id,
                    "user_id": job.user_id,
                    "start_url": job.start_url,
                    "status": job.status,
                    "created_at": job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": job.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for job in jobs
            ]

    def get_job_report(self, job_id: str) -> dict[str, object] | None:
        """
        取得指定任務的詳細統計報告。

        Args:
            job_id (str): 欲查詢報告的任務 ID。

        Returns:
            dict[str, object] | None: 任務的詳細統計資料。若任務不存在則回傳 None。

        Raises:
            SQLAlchemyError: 當資料庫查詢失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                return None

            queue_stats = (
                session.query(
                    sql_count(CrawlQueue.id).label("total"),
                    sql_sum(case((CrawlQueue.status == "completed", 1), else_=0)).label("completed"),
                    sql_sum(case((CrawlQueue.status == "warning", 1), else_=0)).label("warning"),
                    sql_sum(case((CrawlQueue.status == "pending", 1), else_=0)).label("pending"),
                    sql_sum(case((CrawlQueue.status == "failed", 1), else_=0)).label("failed"),
                    sql_sum(case((CrawlQueue.status == "skip", 1), else_=0)).label("skipped"),
                )
                .filter(CrawlQueue.job_id == job_id)
                .first()
            )

            total_queue = int(queue_stats.total) if queue_stats and queue_stats.total else 0
            completed = int(queue_stats.completed) if queue_stats and queue_stats.completed else 0
            warning = int(queue_stats.warning) if queue_stats and queue_stats.warning else 0
            pending = int(queue_stats.pending) if queue_stats and queue_stats.pending else 0
            failed = int(queue_stats.failed) if queue_stats and queue_stats.failed else 0
            skipped = int(queue_stats.skipped) if queue_stats and queue_stats.skipped else 0

            total_external = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()

            return {
                "id": job.id,
                "start_url": job.start_url,
                "status": job.status,
                "created_at": job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": job.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                "queue": {
                    "total": total_queue,
                    "completed": completed,
                    "warning": warning,
                    "skipped": skipped,
                    "pending": pending,
                    "failed": failed,
                },
                "external_links": total_external,
            }

    def pause_job(self, job_id: str) -> bool:
        """
        將指定任務狀態更新為 paused（在任務當前為 running 或 pending 或 queued 時允許）。

        Args:
            job_id (str): 欲暫停的任務 ID。

        Returns:
            bool: 成功暫停回傳 True，否則回傳 False。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            if job.status in ("running", "pending", "starting", "queued"):
                job.status = "paused"
                session.commit()
                return True
            logger.warning("任務 %s 當前狀態為 %s，無法暫停。", job_id, job.status)
            return False

    def delete_job(self, job_id: str) -> bool:
        """
        刪除指定任務，並利用級聯刪除 (Cascade Delete) 機制清理其所有佇列與外連結果。

        Args:
            job_id (str): 欲刪除的任務 ID。

        Returns:
            bool: 成功刪除回傳 True，若任務不存在則回傳 False。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            session.delete(job)
            session.commit()
            return True

    def mark_job_error(self, job_id: str, error_msg: str) -> bool:
        """
        將任務強制標記為異常 (error)，用於處理假死任務 (Zombie Job)。

        Args:
            job_id (str): 任務 ID。
            error_msg (str): 錯誤原因說明 (供後續除錯參考)。

        Returns:
            bool: 成功回傳 True。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            if job.status == "running":
                logger.error("任務 %s 被標記為異常: %s", job_id, error_msg)
                job.status = "error"
                session.commit()
                publish("job_status_changed", job_id=job_id, status="error")
            return True

    def transfer_job(self, job_id: str, new_user_id: str) -> bool:
        """
        將任務移交給新的使用者。

        Args:
            job_id (str): 欲移交的任務 ID。
            new_user_id (str): 接收任務的新使用者 ID。

        Returns:
            bool: 成功移交回傳 True，若任務不存在則回傳 False。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False
            job.user_id = new_user_id
            session.commit()
            return True

    def reset_job(self, job_id: str) -> bool:
        """
        重設指定任務：將任務狀態設回 pending，清除已發生的外連記錄，重置佇列。

        Args:
            job_id (str): 欲重設的任務 ID。

        Returns:
            bool: 成功重設回傳 True，若任務不存在則回傳 False。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False

            # 執行中的任務不允許直接重置，避免子程序仍在運行時造成狀態不一致
            if job.status in ("running", "starting"):
                logger.error(
                    "任務 %s 目前正在執行中，無法直接重置。請先暫停任務再進行重置。",
                    job_id,
                )
                return False

            job.status = "pending"

            # 清除外連記錄
            session.query(ExternalLink).filter(ExternalLink.job_id == job_id).delete(synchronize_session=False)

            # 清除佇列中除起始網址外的所有記錄
            session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url != job.start_url).delete(
                synchronize_session=False
            )

            # 重設起始網址的佇列狀態
            start_queue = (
                session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url == job.start_url).first()
            )
            if start_queue:
                start_queue.status = "pending"
                start_queue.retry_count = 0
                start_queue.status_code = None
                start_queue.error_message = None
            else:
                new_start = CrawlQueue(job_id=job_id, url=job.start_url, source_url=None, status="pending")
                session.add(new_start)

            session.commit()
            return True

    def retry_failed_job(self, job_id: str) -> bool:
        """
        局部重試指定任務：將失敗的內部網頁與包含無效外連的網頁重新加入佇列。

        Args:
            job_id (str): 欲局部重試的任務 ID。

        Returns:
            bool: 成功發出重試指令回傳 True，若無法重試則回傳 False。

        Raises:
            SQLAlchemyError: 當資料庫寫入操作失敗時拋出。
        """
        with self.session_factory() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                logger.error("找不到指定的任務 ID: %s", job_id)
                return False

            if job.status in ("running", "starting", "queued"):
                logger.error("任務 %s 目前正在執行中，無法直接重試。請先暫停任務。", job_id)
                return False

            job.status = "pending"

            # 1. 將本身爬取失敗的內部網頁改回 pending
            session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.status == "failed").update(
                {
                    "status": "pending",
                    "retry_count": 0,
                    "status_code": None,
                    "error_message": None,
                },
                synchronize_session=False,
            )

            # 2. 處理探測異常或失敗的外部連結
            failed_ext_condition = (
                (ExternalLink.ip_address.is_(None))
                | (ExternalLink.ip_address == "")
                | (ExternalLink.http_status_code.is_(None))
                | (ExternalLink.http_status_code >= 400)
            )

            # 找出包含失效外連的來源網頁
            failed_links = (
                session.query(ExternalLink.source_url)
                .filter(ExternalLink.job_id == job_id, failed_ext_condition)
                .distinct()
                .all()
            )

            source_urls_to_retry = [row[0] for row in failed_links if row[0]]

            if source_urls_to_retry:
                # 刪除失效的外部連結紀錄
                session.query(ExternalLink).filter(ExternalLink.job_id == job_id, failed_ext_condition).delete(
                    synchronize_session=False
                )

                # 將包含失效外連的母網頁狀態重置為 pending，以便重新解析與探測
                for i in range(0, len(source_urls_to_retry), 900):
                    batch = source_urls_to_retry[i : i + 900]
                    session.query(CrawlQueue).filter(CrawlQueue.job_id == job_id, CrawlQueue.url.in_(batch)).update(
                        {
                            "status": "pending",
                            "retry_count": 0,
                            "status_code": None,
                            "error_message": None,
                        },
                        synchronize_session=False,
                    )

            session.commit()
            return True
