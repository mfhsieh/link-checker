"""
測試頂層 Pytest Fixture 配置模組。

此模組提供跨測試模組的隔離性保證。透過在每個測試模組執行前後重設全域單例 (Singleton)
物件、清空 FastAPI 的相依注入覆寫 (dependency_overrides) 以及清除設定快取，
確保測試環境的純淨，防止不同測試模組之間的資料庫連線或配置狀態互相干擾。
"""

import os
from collections.abc import Generator

import pytest


def refresh_settings_cache() -> None:
    """
    清除 get_settings() 的 lru_cache 並強制更新 Settings 類別的資料庫連線屬性。

    由於 `Settings` 類別使用類別層級屬性（在類別定義時即完成求值），因此即使環境變數
    已變動，單純重新實例化 `Settings()` 仍會取得舊值。本函式透過手動將最新的環境變數
    覆寫回類別屬性，確保測試能切換至正確的資料庫 URL。
    """
    from backend.config import Settings, get_settings  # pylint: disable=import-outside-toplevel

    # 清除 lru_cache
    get_settings.cache_clear()

    # 強制用最新的環境變數更新 class-level 屬性
    Settings.AUTH_DB_URL = os.environ.get("AUTH_DB_URL", "sqlite:///db/auth.db")
    Settings.CRAWLER_DB_URL = os.environ.get("CRAWLER_DB_URL", "sqlite:///db/crawler.db")
    Settings.GLOBAL_CONFIG_PATH = os.environ.get("GLOBAL_CONFIG_PATH", "config/config_global.yaml")


@pytest.fixture(autouse=True, scope="module")
def _reset_singletons_and_overrides() -> Generator[None, None, None]:
    """
    在每個測試模組執行前與執行後，重設所有後端單例物件並清空相依覆寫。

    此 Fixture 採取自動執行模式 (autouse)，確保每個測試模組在啟動時：
    1. 關閉並清理 Auth DB 與 Crawler DB 的舊有連線池 (SQLAlchemy Engine)。
    2. 清空 FastAPI 應用程式的 `dependency_overrides` 以移除先前模組的 Mock。
    3. 強制刷新環境設定快取。

    在模組測試結束後 (Teardown)，會再次執行相同的清理程序，確保不污染下一個測試模組。

    Yields:
        None: 在測試模組執行期間暫停，等待結束後執行 Teardown。
    """
    from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

    import backend.auth.db as auth_db  # pylint: disable=import-outside-toplevel
    import backend.deps as backend_deps  # pylint: disable=import-outside-toplevel

    # pylint: disable=protected-access

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
    from backend.main import app  # pylint: disable=import-outside-toplevel

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
