"""
Alembic 雙資料庫 (Auth DB & Crawler DB) 遷移環境腳本。

配置並執行 SQLite (batch mode) 與 PostgreSQL 之 Schema 增量遷移。
"""

import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context  # pylint: disable=no-name-in-module
from backend.auth.models import AuthBase
from crawler.models import Base as CrawlerBase

# Load .env variables
load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata combining Auth & Crawler models
target_metadata: list = [AuthBase.metadata, CrawlerBase.metadata]


def get_url() -> str:
    """
    從環境變數或設定檔取得資料庫連線 DSN。

    優先讀取環境變數 CRAWLER_DB_URL，
    若未設定則退回讀取 alembic.ini 之 sqlalchemy.url 設定或預設本機 SQLite。

    Returns:
        str: 資料庫連線 URL 字串。
    """
    env_url = os.getenv("CRAWLER_DB_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and not ini_url.startswith("driver://"):
        return ini_url
    return "sqlite:///db/crawler.db"


def run_migrations_offline() -> None:
    """
    以離線 (Offline) 模式執行資料庫 Schema 遷移。

    無須直接連接實體資料庫，僅根據 MetaData 與指定 Dialect 產出對應之 SQL DDL 腳本。
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    以連線 (Online) 模式執行資料庫 Schema 增量遷移。

    動態建立 SQLAlchemy Database Engine 並開啟 Connection，
    針對實體 SQLite (batch mode) 或 PostgreSQL 執行增量 DDL 遷移與版號更新。
    """
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
