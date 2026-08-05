"""
Alembic 雙資料庫 (Auth DB & Crawler DB) 遷移環境腳本 (Multiple Binds)。

此腳本負責讀取 alembic.ini 的配置並解析環境變數（如 AUTH_DB_URL 與 CRAWLER_DB_URL），
進而建立各個資料庫（auth, crawler）的 SQLAlchemy Engine 與 Connection。
它支援離線產出 DDL 語法 (Offline mode) 與線上執行增量遷移 (Online mode)。
"""

import logging
import os
import re
import sys
from logging.config import fileConfig
from typing import Protocol

from dotenv import load_dotenv
from sqlalchemy import MetaData, engine_from_config, pool
from sqlalchemy.engine import Connection, Engine

from alembic import context  # pylint: disable=no-name-in-module
from backend.auth.models import AuthBase
from crawler.models import Base as CrawlerBase


class MigrationTransaction(Protocol):
    """
    資料庫 Transaction 的型別介面。

    主要供 Mypy 在多資料庫交易管理（含單一交易與二階段提交）時進行靜態型別推斷與檢查。
    """

    def prepare(self) -> None:
        """
        準備二階段提交 (Two-Phase Commit)。
        """

    def commit(self) -> None:
        """
        提交目前交易。
        """

    def rollback(self) -> None:
        """
        回溯目前交易。
        """


# 載入專案環境變數 (.env)
load_dotenv()

USE_TWOPHASE: bool = False

# Alembic 組態物件，提供存取 alembic.ini 中設定數值的介面。
config = context.config

# 設定 Python 內建的 logging 日誌解析與格式。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger: logging.Logger = logging.getLogger("alembic.env")

# ==========================================
# 破壞性操作防呆保護 (Safe Destructive Testing Protection)
# ==========================================
if "downgrade" in sys.argv:
    if os.getenv("CONFIRM_DESTRUCTIVE_DOWNGRADE") != "yes":
        logger.error(
            "\n=======================================================\n"
            "【危險操作警告】您正在嘗試執行 Alembic downgrade 操作！\n"
            "這將可能會刪除資料表並造成歷史資料永久遺失。\n"
            "為防止誤砍，您必須明確設定環境變數才能放行。\n"
            "若您確定要降級，請使用以下指令：\n"
            "CONFIRM_DESTRUCTIVE_DOWNGRADE=yes alembic downgrade <revision>\n"
            "=======================================================\n"
        )
        sys.exit(1)

# 取得 alembic.ini 中所定義的多資料庫識別名稱清單。
db_names: str = config.get_main_option("databases", "")

# 針對多庫路由定義目標 MetaData 映射字典。
target_metadata: dict[str, MetaData] = {
    "auth": AuthBase.metadata,
    "crawler": CrawlerBase.metadata,
}


def get_url(name: str) -> str:
    """
    從環境變數取得各個資料庫連線 DSN。

    若環境變數中未設定對應名稱的 URL，則嘗試從 alembic.ini 設定檔讀取；
    若皆未設定，則降級使用預設的 SQLite 本地資料庫檔案路徑。

    Args:
        name (str): 資料庫識別名稱（例如 'auth' 或 'crawler'）。

    Returns:
        str: 資料庫連線 URL 字串。
    """
    env_url = os.getenv(f"{name.upper()}_DB_URL")
    if env_url:
        return env_url
    ini_url = config.get_section_option(name, "sqlalchemy.url")
    if ini_url and not ini_url.startswith("driver://"):
        return ini_url
    # 預設的 fallback
    return f"sqlite:///db/{name}.db"


def run_migrations_offline() -> None:
    """
    以離線 (Offline) 模式執行資料庫 Schema 遷移。

    無須直接連接實體資料庫，僅根據 MetaData 與指定 Dialect 產出對應之 SQL DDL 腳本檔案。

    Raises:
        OSError: 當寫入輸出的 SQL 檔案發生 I/O 錯誤時拋出。
    """
    # 針對離線 (--sql) 的使用情境，將各個資料庫的 DDL 輸出至對應的 SQL 檔案中。

    urls: dict[str, str] = {}
    for name in re.split(r",\s*", db_names):
        urls[name] = get_url(name)

    for name, url in urls.items():
        logger.info("Migrating database %s", name)
        file_ = f"{name}.sql"
        logger.info("Writing output to %s", file_)
        with open(file_, "w", encoding="utf-8") as buffer:
            context.configure(
                url=url,
                output_buffer=buffer,
                target_metadata=target_metadata.get(name),
                literal_binds=True,
                dialect_opts={"paramstyle": "named"},
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations(engine_name=name)


def run_migrations_online() -> None:
    """
    以連線 (Online) 模式執行資料庫 Schema 增量遷移。

    動態建立 SQLAlchemy Database Engine 並開啟 Connection，
    針對實體 SQLite (batch mode) 或 PostgreSQL 執行增量 DDL 遷移與版號更新。

    Raises:
        Exception: 當資料庫連線或 Schema 遷移過程中發生錯誤時，
            將進行 Transaction rollback 並向上拋出原始例外。
    """

    # 針對直接連線 (Online) 的情境，啟動所有資料庫的 Transaction 並統一執行遷移，最後一併 Commit。

    engines_map: dict[str, Engine] = {}
    for name in re.split(r",\s*", db_names):
        configuration = context.config.get_section(name, {}) or {}
        configuration["sqlalchemy.url"] = get_url(name)
        engines_map[name] = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    connections_map: dict[str, Connection] = {}
    transactions_map: dict[str, MigrationTransaction] = {}

    for name, engine in engines_map.items():
        conn = engine.connect()
        connections_map[name] = conn
        if USE_TWOPHASE:
            transactions_map[name] = conn.begin_twophase()  # type: ignore[assignment]
        else:
            transactions_map[name] = conn.begin()  # type: ignore[assignment]

    try:
        for name, conn in connections_map.items():
            logger.info("Migrating database %s", name)
            context.configure(
                connection=conn,
                upgrade_token=f"{name}_upgrades",
                downgrade_token=f"{name}_downgrades",
                target_metadata=target_metadata.get(name),
                render_as_batch=True,
            )
            context.run_migrations(engine_name=name)

        if USE_TWOPHASE:
            for trans in transactions_map.values():
                trans.prepare()

        for trans in transactions_map.values():
            trans.commit()
    except Exception:
        for trans in transactions_map.values():
            trans.rollback()
        raise
    finally:
        for conn in connections_map.values():
            conn.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
