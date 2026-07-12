"""資料回填腳本：為 `external_links` 資料表中既有的舊紀錄補上 `target_domain` 欄位值。.

在 `target_domain` 欄位被新增至 `ExternalLink` 模型後，
所有在此之前建立的紀錄，該欄位值會是空值 (NULL 或空字串)。
此腳本會遍歷所有 `target_domain` 為空的紀錄，
從 `target_url` 中解析出網域並回填，以確保 `group_by=domain` 功能的正確性。

設計特性 (Selective Update)：
因為從 URL 萃取網域的運算為絕對客觀且不會改變的固定邏輯，
本腳本會在 SQL 查詢階段直接透過 `filter()` 排除掉已有值的紀錄，
僅針對空值 (NULL 或空字串) 進行回填，以最大化執行效能並節省系統資源。
"""

import logging
import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# 將專案路徑加入 path 以便引用 backend, crawler
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# pylint: disable=wrong-import-position
from backend.config import get_settings
from crawler.models import ExternalLink
from crawler.utils import get_domain

# pylint: enable=wrong-import-position

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger("backfill")


def backfill() -> None:
    """
    執行資料回填程序。

    連線至 Crawler DB 並分批查詢所有 `target_domain` 為空或 NULL 的紀錄，
    透過解析 `target_url` 來自動補齊並回填 `target_domain` 欄位值。
    每批處理 2000 筆紀錄，直到所有紀錄皆回填完畢。

    Raises:
        SQLAlchemyError: 當資料庫連線或更新失敗時拋出。
    """
    settings = get_settings()
    engine = create_engine(settings.CRAWLER_DB_URL)
    session_factory = sessionmaker(bind=engine)

    logger.info("開始回填 external_links.target_domain 欄位...")

    with session_factory() as session:
        total_processed = 0
        batch_size = 2000

        while True:
            # 分批查詢 target_domain 為空或 NULL 的紀錄
            links_to_update = session.scalars(
                select(ExternalLink)
                .filter((ExternalLink.target_domain == "") | (ExternalLink.target_domain.is_(None)))
                .limit(batch_size)
            ).all()

            if not links_to_update:
                logger.info("所有紀錄皆已包含 target_domain，無需回填。")
                break

            for link in links_to_update:
                domain = get_domain(link.target_url)
                link.target_domain = domain or ""

            session.commit()
            total_processed += len(links_to_update)
            logger.info("已處理 %d 筆紀錄...", total_processed)

    logger.info("資料回填完成！總共更新了 %d 筆紀錄。", total_processed)


if __name__ == "__main__":
    backfill()
