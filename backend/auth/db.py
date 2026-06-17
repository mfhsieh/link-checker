"""
Auth DB 的資料庫連線設定。

此模組建立獨立的 SQLAlchemy engine 用於帳號資料庫（Auth DB），
與爬蟲資料庫（Crawler DB）完全分離，不共用連線池或 Session。
"""

from collections.abc import Callable

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.auth.models import AuthBase
from backend.config import get_settings
from crawler.utils import create_optimized_engine


def _create_auth_engine() -> Engine:
    """
    建立 Auth DB 的 SQLAlchemy engine。

    若資料庫目錄不存在則自動建立。
    SQLite 連線會套用 WAL 模式與效能優化 PRAGMA。

    Returns:
        Engine: 已設定完成的 SQLAlchemy engine。

    Raises:
        OSError: 若建立資料庫目錄失敗時拋出。
        SQLAlchemyError: 若建立資料表失敗時拋出。
    """
    settings = get_settings()
    db_url = settings.AUTH_DB_URL

    engine = create_optimized_engine(
        db_url=db_url,
        sqlite_timeout=settings.SQLITE_TIMEOUT,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
        sqlite_cache_size=5000,
    )

    # 建立所有資料表（若尚未存在）
    AuthBase.metadata.create_all(engine)

    return engine


# 模組層級的變數（單例模式）
_ENGINE: Engine | None = None
_SESSION_LOCAL: Callable[[], Session] | None = None


def get_auth_engine() -> Engine:
    """
    取得 Auth DB engine 的單例。

    Returns:
        Engine: Auth DB engine。

    Raises:
        OSError: 若建立資料庫目錄失敗時拋出。
        SQLAlchemyError: 若初始化資料表失敗時拋出。
    """
    global _ENGINE  # pylint: disable=global-statement
    if _ENGINE is None:
        _ENGINE = _create_auth_engine()
    return _ENGINE


def get_auth_session_local() -> Callable[[], Session]:
    """
    取得 Auth DB SessionLocal 的單例。

    Returns:
        Callable[[], Session]: SessionLocal 工廠。
    """
    global _SESSION_LOCAL  # pylint: disable=global-statement
    if _SESSION_LOCAL is None:
        _SESSION_LOCAL = sessionmaker(bind=get_auth_engine(), autocommit=False, autoflush=False)
    return _SESSION_LOCAL
