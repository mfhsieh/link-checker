"""
測試頂層 Pytest Fixture 配置模組。

提供跨測試模組的隔離性保證：
- 每個測試模組執行前重設 backend singleton（Engine / SessionLocal / JobManager）
- 每個測試模組執行後清空 FastAPI dependency_overrides
- 清除 get_settings() 的 lru_cache，確保各模組能使用正確的 DB URL
"""

import os
from collections.abc import Generator

import pytest


def refresh_settings_cache() -> None:
    """
    清除 get_settings() 的 lru_cache 並強制更新 Settings class 的 DB URL。

    由於 Settings 使用 class-level 屬性（在 class 定義時求值），
    即使環境變數已更新，重新建立 Settings() 也不會讀取新值。
    因此需要手動將 os.environ 的最新值覆寫到 Settings class 屬性上。

    Returns:
        None
    """
    # pylint: disable=import-outside-toplevel
    from backend.config import Settings, get_settings

    # 清除 lru_cache
    get_settings.cache_clear()

    # 強制用最新的環境變數更新 class-level 屬性
    Settings.AUTH_DB_URL = os.environ.get("AUTH_DB_URL", "sqlite:///db/auth.db")
    Settings.CRAWLER_DB_URL = os.environ.get("CRAWLER_DB_URL", "sqlite:///db/crawler.db")
    Settings.GLOBAL_CONFIG_PATH = os.environ.get("GLOBAL_CONFIG_PATH", "config/config_global.yaml")


@pytest.fixture(autouse=True, scope="module")
def _reset_singletons_and_overrides() -> Generator[None, None, None]:
    """
    在每個測試模組執行前，重設所有 backend singleton 並清空 dependency overrides。

    這確保各測試模組在乾淨的環境下啟動，不會受到前一個模組殘留的
    Engine / SessionLocal / JobManager / dependency_overrides 影響。

    Yields:
        None: 在模組執行完畢後進行清理。
    """
    # pylint: disable=import-outside-toplevel, protected-access
    from sqlalchemy.exc import SQLAlchemyError

    import backend.auth.db as auth_db
    import backend.deps as backend_deps

    # ── 重設 Auth DB singleton ──
    if auth_db._ENGINE is not None:
        try:
            auth_db._ENGINE.dispose()
        except (SQLAlchemyError, OSError):
            pass
    auth_db._ENGINE = None
    auth_db._SESSION_LOCAL = None

    # ── 重設 Crawler DB singleton（JobManager）──
    if backend_deps._JOB_MANAGER is not None:
        try:
            backend_deps._JOB_MANAGER.engine.dispose()
        except (SQLAlchemyError, OSError):
            pass
    backend_deps._JOB_MANAGER = None

    # ── 清空 FastAPI dependency overrides（防止前一模組的 mock 影響後續模組）──
    from backend.main import app

    app.dependency_overrides.clear()

    # ── 清除 get_settings 快取（防止前一模組的 Settings 被後續模組繼承）──
    refresh_settings_cache()

    yield

    # ── teardown：再次清理，確保不污染下一個模組 ──
    if auth_db._ENGINE is not None:
        try:
            auth_db._ENGINE.dispose()
        except (SQLAlchemyError, OSError):
            pass
    auth_db._ENGINE = None
    auth_db._SESSION_LOCAL = None

    if backend_deps._JOB_MANAGER is not None:
        try:
            backend_deps._JOB_MANAGER.engine.dispose()
        except (SQLAlchemyError, OSError):
            pass
    backend_deps._JOB_MANAGER = None

    app.dependency_overrides.clear()
    refresh_settings_cache()

    # ── 清理可能殘留的測試用環境變數 ──
    for key in ["CRAWLER_ALLOW_LOCAL_IPS", "CRAWLER_PROXY_URL", "CRAWLER_SSL_EXEMPT_DOMAINS"]:
        os.environ.pop(key, None)
