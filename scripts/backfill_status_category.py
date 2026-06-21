"""
資料庫遷移腳本：新增 status_category 欄位並更新現有的外部連結與內部連結紀錄。

此腳本用於在 SQLite 或 PostgreSQL 資料庫的 external_links 與 crawl_queue 表格中，
擴增 status_category 欄位，建立對應的複合索引，並根據現有紀錄的
狀態、HTTP 狀態碼與 IP 位址等，自動回填所有舊資料的狀態分類值。

設計特性 (Reconciliation)：
本腳本具備「冪等性」(Idempotent)。由於狀態碼的分類邏輯可能會隨商業需求改變（例如新增 405/429 的判定），
本腳本不會跳過已有值的紀錄，而是會「掃描所有紀錄」並重新執行最新的判斷邏輯。
只要發現舊分類與新邏輯不符，就會自動進行校正覆寫。因此若更新了 `crawler/utils.py` 裡的判斷規則，
可隨時再次執行本腳本以確保資料庫狀態與程式邏輯保持 100% 同步。
"""

import logging
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 將專案根目錄加入 PYTHONPATH 以匯入本地模組
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# pylint: disable=wrong-import-position, import-error
from backend.config import get_settings  # noqa: E402
from crawler.models import CrawlQueue, ExternalLink  # noqa: E402
from crawler.utils import determine_external_link_status_category, determine_internal_link_status_category  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger: logging.Logger = logging.getLogger("backfill_status_category")


def migrate_external_links(engine, session_factory) -> None:
    """處理 external_links 表格。"""
    with engine.connect() as conn:
        logger.info("[ExternalLink] 檢查是否已存在 status_category 欄位...")
        try:
            conn.execute(text("SELECT status_category FROM external_links LIMIT 1"))
            logger.info("[ExternalLink] 欄位 status_category 已經存在，跳過 ALTER TABLE")
        except Exception:  # pylint: disable=broad-exception-caught
            conn.rollback()
            logger.info("[ExternalLink] 新增 status_category 欄位...")
            conn.execute(text("ALTER TABLE external_links ADD COLUMN status_category VARCHAR(30) DEFAULT 'healthy'"))
            conn.commit()

        logger.info("[ExternalLink] 檢查並建立複合索引 ix_external_links_job_category...")
        try:
            conn.execute(text("CREATE INDEX ix_external_links_job_category ON external_links(job_id, status_category)"))
            conn.commit()
            logger.info("[ExternalLink] 複合索引建立成功")
        except Exception:  # pylint: disable=broad-exception-caught
            conn.rollback()
            logger.info("[ExternalLink] 索引可能已存在或建立失敗，略過建立")

    logger.info("[ExternalLink] 開始更新舊資料的 status_category 值...")
    with session_factory() as session:
        batch_size = 2000
        offset = 0
        total_updated = 0

        while True:
            records = session.query(ExternalLink).order_by(ExternalLink.id).offset(offset).limit(batch_size).all()
            if not records:
                break

            batch_updated = 0
            for ext in records:
                new_cat = determine_external_link_status_category(ext.ip_address, ext.http_status_code)
                if ext.status_category != new_cat:
                    ext.status_category = new_cat
                    batch_updated += 1

            if batch_updated > 0:
                session.commit()
                total_updated += batch_updated

            offset += batch_size
            logger.info("[ExternalLink] 已掃描 %d 筆紀錄，目前累計更新 %d 筆...", offset, total_updated)


def migrate_crawl_queue(engine, session_factory) -> None:
    """處理 crawl_queue 表格。"""
    with engine.connect() as conn:
        logger.info("[CrawlQueue] 檢查是否已存在 status_category 欄位...")
        try:
            conn.execute(text("SELECT status_category FROM crawl_queue LIMIT 1"))
            logger.info("[CrawlQueue] 欄位 status_category 已經存在，跳過 ALTER TABLE")
        except Exception:  # pylint: disable=broad-exception-caught
            conn.rollback()
            logger.info("[CrawlQueue] 新增 status_category 欄位...")
            conn.execute(text("ALTER TABLE crawl_queue ADD COLUMN status_category VARCHAR(30) DEFAULT 'pending'"))
            conn.commit()

        logger.info("[CrawlQueue] 檢查並建立複合索引 ix_crawl_queue_job_category...")
        try:
            conn.execute(text("CREATE INDEX ix_crawl_queue_job_category ON crawl_queue(job_id, status_category)"))
            conn.commit()
            logger.info("[CrawlQueue] 複合索引建立成功")
        except Exception:  # pylint: disable=broad-exception-caught
            conn.rollback()
            logger.info("[CrawlQueue] 索引可能已存在或建立失敗，略過建立")

    logger.info("[CrawlQueue] 開始更新舊資料的 status_category 值...")
    with session_factory() as session:
        batch_size = 2000
        offset = 0
        total_updated = 0

        while True:
            records = session.query(CrawlQueue).order_by(CrawlQueue.id).offset(offset).limit(batch_size).all()
            if not records:
                break

            batch_updated = 0
            for q in records:
                new_cat = determine_internal_link_status_category(q.status, q.status_code, q.error_message)
                if q.status_category != new_cat:
                    q.status_category = new_cat
                    batch_updated += 1

            if batch_updated > 0:
                session.commit()
                total_updated += batch_updated

            offset += batch_size
            logger.info("[CrawlQueue] 已掃描 %d 筆紀錄，目前累計更新 %d 筆...", offset, total_updated)


def main() -> None:
    """
    執行資料庫 Schema 更新與舊資料回填作業。
    """
    settings = get_settings()
    engine = create_engine(settings.CRAWLER_DB_URL)
    session_factory = sessionmaker(bind=engine)

    migrate_external_links(engine, session_factory)
    migrate_crawl_queue(engine, session_factory)

    logger.info("資料庫遷移與回填作業完成！")


if __name__ == "__main__":
    main()
