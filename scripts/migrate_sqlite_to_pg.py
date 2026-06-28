"""
資料庫遷移工具：從 SQLite 轉移資料至 PostgreSQL。

此腳本會讀取目前的 `.env` 設定檔，將舊有 SQLite 資料庫中的資料
（包含使用者帳號、Session、任務、佇列與外連結果）遷移至 PostgreSQL 目標資料庫中。

請在執行此腳本前，先於 `.env` 中設定好對應的 `AUTH_DB_URL` 與 `CRAWLER_DB_URL` 為 PostgreSQL 連線字串。
"""

import logging
import os
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

# 將專案根目錄加入 PYTHONPATH
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# pylint: disable=wrong-import-position, import-error
from backend.auth.models import AuthBase, AuthLog, Invitation, PasswordResetToken, User  # noqa: E402
from backend.auth.models import Session as AuthSession  # noqa: E402
from backend.config import get_settings  # noqa: E402
from crawler.models import Base, CrawlQueue, ExternalLink, Job  # noqa: E402

# 初始化日誌
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger("migration")


# pylint: disable=too-many-locals
def migrate_auth_db(sqlite_url: str, pg_url: str) -> None:
    """
    遷移使用者帳號與認證相關資料。

    將使用者清單、邀請憑證、登入 Session 與安全操作日誌從 SQLite 來源庫
    搬移至目標的 PostgreSQL 中，並在遷移結束後自動更新 PostgreSQL 的序列值 (Sequence)。

    Args:
        sqlite_url (str): 來源 SQLite 資料庫連線 URL。
        pg_url (str): 目標 PostgreSQL 資料庫連線 URL。

    Raises:
        SQLAlchemyError: 當資料寫入發生例外時拋出。
    """
    logger.info("開始遷移 Auth DB...")

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    # 1. 於目標 PostgreSQL 清空並重新建立資料表
    logger.info("清空目標 PostgreSQL Auth DB 中的舊資料表並全新重建...")
    AuthBase.metadata.drop_all(pg_engine)
    AuthBase.metadata.create_all(pg_engine)

    sqlite_session_factory = sessionmaker(bind=sqlite_engine)
    pg_session_factory = sessionmaker(bind=pg_engine)

    with sqlite_session_factory() as src, pg_session_factory() as dest:
        # 關閉目標資料庫的外鍵檢查，加速導入並防制寫入順序衝突
        dest.execute(text("SET session_replication_role = 'replica';"))
        dest.commit()

        try:
            # A. 遷移 users
            users = src.scalars(select(User)).all()
            logger.info("讀取到 %d 筆使用者帳號...", len(users))
            for u in users:
                dest.merge(u)
            dest.commit()
            logger.info("Users 遷移完成。")

            # B. 遷移 invitations
            invitations = src.scalars(select(Invitation)).all()
            logger.info("讀取到 %d 筆邀請憑證...", len(invitations))
            for inv in invitations:
                dest.merge(inv)
            dest.commit()
            logger.info("Invitations 遷移完成。")

            # C. 遷移 sessions
            sessions = src.scalars(select(AuthSession)).all()
            logger.info("讀取到 %d 筆 Session 紀錄...", len(sessions))
            for s in sessions:
                dest.merge(s)
            dest.commit()
            logger.info("Sessions 遷移完成。")

            # D. 遷移 auth_logs
            logs = src.scalars(select(AuthLog)).all()
            logger.info("讀取到 %d 筆安全操作日誌...", len(logs))
            for log in logs:
                dest.merge(log)
            dest.commit()
            logger.info("Auth Logs 遷移完成。")

            # E. 遷移 password_reset_tokens
            tokens = src.scalars(select(PasswordResetToken)).all()
            logger.info("讀取到 %d 筆密碼重設憑證...", len(tokens))
            for t in tokens:
                dest.merge(t)
            dest.commit()
            logger.info("Password Reset Tokens 遷移完成。")

            # 2. 更新 PostgreSQL 的 Serial 序列值
            logger.info("更新 PostgreSQL 主鍵序列值 (Sequence)...")
            dest.execute(
                text("SELECT setval(pg_get_serial_sequence('auth_logs', 'id'), coalesce(max(id), 1)) FROM auth_logs;")
            )
            dest.commit()
            logger.info("Auth DB 序列更新完成。")

        finally:
            # 恢復目標資料庫的正常觸發器與外鍵檢查
            dest.execute(text("SET session_replication_role = 'origin';"))
            dest.commit()

    logger.info("Auth DB 遷移成功！")


# pylint: disable=too-many-locals
def migrate_crawler_db(sqlite_url: str, pg_url: str) -> None:
    """
    遷移爬蟲任務與結果資料。

    分批讀取 CrawlQueue 與 ExternalLink 等大量資料，並寫入目標 PostgreSQL，
    以避免 OOM (Out Of Memory) 崩潰，最後同步更新主鍵序列值 (Sequence)。

    Args:
        sqlite_url (str): 來源 SQLite 資料庫連線 URL。
        pg_url (str): 目標 PostgreSQL 資料庫連線 URL。

    Raises:
        SQLAlchemyError: 當資料寫入發生例外時拋出。
    """
    logger.info("開始遷移 Crawler DB...")

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    # 1. 於目標 PostgreSQL 清空並重新建立資料表
    logger.info("清空目標 PostgreSQL Crawler DB 中的舊資料表並全新重建...")
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)

    sqlite_session_factory = sessionmaker(bind=sqlite_engine)
    pg_session_factory = sessionmaker(bind=pg_engine)

    with sqlite_session_factory() as src, pg_session_factory() as dest:
        # 關閉目標資料庫的外鍵檢查
        dest.execute(text("SET session_replication_role = 'replica';"))
        dest.commit()

        try:
            # A. 遷移 jobs
            jobs = src.scalars(select(Job)).all()
            logger.info("讀取到 %d 筆任務紀錄...", len(jobs))
            for j in jobs:
                # 為了避免 relationships 被關聯載入導致重複 merge，此處將 state 設為 transient
                dest.merge(j)
            dest.commit()
            logger.info("Jobs 遷移完成。")

            # B. 遷移 crawl_queue (分批遷移防 OOM)
            logger.info("讀取並移轉佇列 (Crawl Queue) 資料...")
            batch_size = 1000
            offset = 0
            while True:
                q_batch = src.scalars(select(CrawlQueue).order_by(CrawlQueue.id).limit(batch_size).offset(offset)).all()
                if not q_batch:
                    break
                for q in q_batch:
                    dest.merge(q)
                dest.commit()
                offset += len(q_batch)
                logger.info("已遷移 %d 筆佇列項目...", offset)
            logger.info("Crawl Queue 遷移完成。")

            # C. 遷移 external_links (分批遷移防 OOM)
            logger.info("讀取並移轉外連結果 (External Links) 資料...")
            offset = 0
            while True:
                links_batch = src.scalars(
                    select(ExternalLink).order_by(ExternalLink.id).limit(batch_size).offset(offset)
                ).all()
                if not links_batch:
                    break
                for link in links_batch:
                    dest.merge(link)
                dest.commit()
                offset += len(links_batch)
                logger.info("已遷移 %d 筆外部連結結果...", offset)
            logger.info("External Links 遷移完成。")

            # 2. 更新 PostgreSQL 的 Serial 序列值
            logger.info("更新 PostgreSQL 主鍵序列值 (Sequence)...")
            dest.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('crawl_queue', 'id'), coalesce(max(id), 1)) FROM crawl_queue;"
                )
            )
            dest.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('external_links', 'id'), "
                    "coalesce(max(id), 1)) FROM external_links;"
                )
            )
            dest.commit()
            logger.info("Crawler DB 序列更新完成。")

        finally:
            # 恢復目標資料庫的正常觸發器與外鍵檢查
            dest.execute(text("SET session_replication_role = 'origin';"))
            dest.commit()

    logger.info("Crawler DB 遷移成功！")


def main() -> None:
    """
    主控流程，從環境設定中讀取 DSN 並驅動遷移邏輯。

    驗證設定的連線字串是否確實為 PostgreSQL，若通過則依序執行 Auth DB
    與 Crawler DB 的資料庫遷移，成功後結束。

    Raises:
        SystemExit: 當資料庫設定非 PostgreSQL 或遷移過程發生嚴重錯誤時。
    """
    settings = get_settings()

    # 目標 PG DSN（讀取自 .env）
    pg_auth_url = settings.AUTH_DB_URL
    pg_crawler_url = settings.CRAWLER_DB_URL

    # 來源 SQLite 預設位置 (可透過環境變數覆寫)
    sqlite_auth_url = os.environ.get("MIGRATION_SOURCE_SQLITE_URL", "sqlite:///db/auth.db")
    sqlite_crawler_url = os.environ.get("MIGRATION_SOURCE_CRAWLER_SQLITE_URL", "sqlite:///db/crawler.db")

    # 安全驗證：確認目標已經是 PostgreSQL，防制誤寫入
    if not pg_auth_url.startswith("postgresql") or not pg_crawler_url.startswith("postgresql"):
        logger.error("錯誤：偵測到 .env 中的資料庫連線尚未設定為 postgresql。")
        logger.error("請先修改 .env，設定 AUTH_DB_URL 與 CRAWLER_DB_URL 為 PostgreSQL 位址後再執行此腳本。")
        sys.exit(1)

    logger.info("========================================")
    logger.info(" 正在準備進行 SQLite -> PostgreSQL 遷移 ")
    logger.info("========================================")
    logger.info("來源 SQLite Auth DSN   : %s", sqlite_auth_url)
    logger.info("來源 SQLite Crawler DSN: %s", sqlite_crawler_url)
    logger.info("目標 PostgreSQL Auth DSN   : %s", pg_auth_url.split("@")[-1])  # 隱藏密碼
    logger.info("目標 PostgreSQL Crawler DSN: %s", pg_crawler_url.split("@")[-1])
    logger.info("========================================")

    # 執行遷移
    try:
        migrate_auth_db(sqlite_auth_url, pg_auth_url)
        migrate_crawler_db(sqlite_crawler_url, pg_crawler_url)
        logger.info("資料庫全數遷移成功！現在您可以啟動 Web 服務並改用 PostgreSQL 運行了。")
    except (SQLAlchemyError, OSError) as e:
        logger.exception("遷移過程中發生嚴重錯誤: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
