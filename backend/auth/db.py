"""
Auth DB 的資料庫連線設定。

此模組建立獨立的 SQLAlchemy engine 用於帳號資料庫（Auth DB），
與爬蟲資料庫（Crawler DB）完全分離，不共用連線池或 Session。
"""

# pylint: disable=unsubscriptable-object

import os
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from backend.auth.models import AuthBase
from backend.config import get_settings


def _create_auth_engine() -> Engine:
    """
    建立 Auth DB 的 SQLAlchemy engine。

    若資料庫目錄不存在則自動建立。
    SQLite 連線會套用 WAL 模式與效能優化 PRAGMA。

    Returns:
        Engine: 已設定完成的 SQLAlchemy engine。
    """
    settings = get_settings()
    db_url = settings.AUTH_DB_URL

    # 自動建立資料庫目錄
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    # sqlite 預設為單執行緒，使用 check_same_thread=False
    # 允許多執行緒共用 (FastAPI / Celery)
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": settings.SQLITE_TIMEOUT}
        if db_url.startswith("sqlite")
        else {},
    )

    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: object, _connection_record: object) -> None:
            """
            設定 SQLite 的 PRAGMA 參數，提升並發效能與安全性。

            Args:
                dbapi_connection (object): SQLite 資料庫連線物件。
                _connection_record (object): SQLAlchemy 連線紀錄物件（此處未使用）。
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # 建立所有資料表（若尚未存在）
    AuthBase.metadata.create_all(engine)

    return engine


# 模組層級的變數（單例模式）
_ENGINE: Engine | None = None
_SESSION_LOCAL: sessionmaker[Session] | None = None


def get_auth_engine() -> Engine:
    """
    取得 Auth DB engine 的單例。

    Returns:
        Engine: Auth DB engine。
    """
    global _ENGINE  # pylint: disable=global-statement
    if _ENGINE is None:
        _ENGINE = _create_auth_engine()
    return _ENGINE


def get_auth_session_local() -> sessionmaker[Session]:
    """
    取得 Auth DB SessionLocal 的單例。

    Returns:
        sessionmaker[Session]: SessionLocal 工廠。
    """
    global _SESSION_LOCAL  # pylint: disable=global-statement
    if _SESSION_LOCAL is None:
        _SESSION_LOCAL = sessionmaker(bind=get_auth_engine(), autocommit=False, autoflush=False)
    return _SESSION_LOCAL
