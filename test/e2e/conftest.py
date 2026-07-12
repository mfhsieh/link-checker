"""
E2E 自動化整合測試的 Pytest Fixture 配置模組。

提供測試伺服器生命週期管理、資料庫初始化，以及 Playwright 相關設定。
"""

# pylint: disable=protected-access, duplicate-code

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Generator
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

# 將專案路徑加入 path 以便引用 backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.auth.db import get_auth_engine, get_auth_session_local  # pylint: disable=wrong-import-position
from backend.auth.models import User  # pylint: disable=wrong-import-position
from backend.auth.password import hash_password  # pylint: disable=wrong-import-position
from backend.deps import get_job_manager  # pylint: disable=wrong-import-position

PORT: int = 8085
BASE_URL: str = f"http://127.0.0.1:{PORT}"


def _set_e2e_test_env() -> None:
    """
    設定 E2E 測試專用的環境變數。

    在每次 `setup_databases()` 前呼叫，確保環境變數指向正確的測試資料庫與設定檔，
    避免被其他測試模組或環境中的設定覆蓋。此函式也會強制更新 Settings 類別的快取。

    Returns:
        None
    """
    os.environ["AUTH_DB_URL"] = "sqlite:///db/test_auth_e2e.db"
    os.environ["CRAWLER_DB_URL"] = "sqlite:///db/test_crawler_e2e.db"
    os.environ["GLOBAL_CONFIG_PATH"] = "config/test_config_global_e2e.yaml"
    # 強制更新 Settings class 的 DB URL（因為 Settings 使用 class-level 屬性且有 lru_cache）
    from test.conftest import refresh_settings_cache  # pylint: disable=import-outside-toplevel

    refresh_settings_cache()


def setup_databases() -> None:
    """
    清理並初始化 E2E 測試用資料庫。

    此函式會確保環境變數正確，釋放舊有的資料庫連線，移除舊的 SQLite 檔案，
    並重新建立 Auth DB 與 Crawler DB 的資料表，以確保每個測試 Session 都在乾淨的環境開始。
    """
    import backend.auth.db as auth_db  # pylint: disable=import-outside-toplevel
    import backend.deps as backend_deps  # pylint: disable=import-outside-toplevel

    # 確保環境變數指向正確的測試 DB
    _set_e2e_test_env()

    # 強制關閉並釋放 SQLAlchemy Engine 連線池，釋放 sqlite fd
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

    if os.path.exists("config/config_global.yaml.example"):
        shutil.copy("config/config_global.yaml.example", "config/test_config_global_e2e.yaml")

    # 清除舊的資料庫主檔案與 -shm/-wal 暫存檔
    for db_file in ["db/test_auth_e2e.db", "db/test_crawler_e2e.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass

    get_auth_engine()
    get_job_manager()


def teardown_databases() -> None:
    """
    清理 E2E 測試所產生的資料庫檔案。

    釋放所有資料庫連線池，並移除測試期間產生的 SQLite 主檔案及其暫存檔（-shm, -wal），
    以及測試用的全域設定檔。
    """
    import backend.auth.db as auth_db  # pylint: disable=import-outside-toplevel
    import backend.deps as backend_deps  # pylint: disable=import-outside-toplevel

    # 強制關閉並釋放 SQLAlchemy Engine 連線池，釋放 sqlite fd
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

    if os.path.exists("config/test_config_global_e2e.yaml"):
        try:
            os.remove("config/test_config_global_e2e.yaml")
        except OSError:
            pass

    # 清除資料庫主檔案與 -shm/-wal 暫存檔
    for db_file in ["db/test_auth_e2e.db", "db/test_crawler_e2e.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass


def create_admin_user() -> None:
    """
    建立 E2E 測試用的管理員帳號。

    在 Auth 資料庫中直接插入一筆 admin@test.com 帳號，並將密碼預設為 'Admin@12345678'，
    以利後續 E2E 流程（如登入頁面測試）的使用。
    """
    session_factory = get_auth_session_local()
    with session_factory() as db:
        pwd_hash = hash_password("Admin@12345678")
        admin_user = User(
            email="admin@test.com",
            password_hash=pwd_hash,
            role="admin",
            status="active",
            last_login_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(admin_user)
        db.commit()


def wait_for_server(port: int, timeout: int = 10) -> bool:
    """
    等待伺服器啟動並回應 HTTP 請求。

    Args:
        port (int): 伺服器監聽的通訊埠。
        timeout (int): 最長等待時間（秒），預設為 10。

    Returns:
        bool: 若伺服器成功啟動並回應，則回傳 True；否則回傳 False。
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            res = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
            if res.status_code in (200, 201, 202):
                return True
        except httpx.RequestError:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session", autouse=True)
def test_server() -> Generator[str, None, None]:
    """
    在整個 E2E 測試期間啟動 FastAPI 伺服器，並提供乾淨的資料庫。

    Yields:
        str: 測試伺服器的 Base URL。

    Raises:
        RuntimeError: 當 FastAPI 伺服器無法啟動時拋出。
    """
    setup_databases()
    create_admin_user()

    env = os.environ.copy()
    with subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    ) as server_proc:
        if not wait_for_server(PORT):
            server_proc.terminate()
            raise RuntimeError("FastAPI Server failed to start.")

        yield BASE_URL

        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
    teardown_databases()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, object]) -> dict[str, object]:  # pylint: disable=redefined-outer-name
    """
    覆寫 Playwright 啟動參數，強制使用系統的 Chromium。

    Args:
        browser_type_launch_args (dict[str, object]): 原始啟動參數。

    Returns:
        dict[str, object]: 覆寫後的啟動參數。
    """
    return {**browser_type_launch_args, "executable_path": "/usr/bin/chromium"}


@pytest.fixture(scope="session")
def base_url() -> str:
    """
    Playwright 預設會使用此 base_url 來訪問網頁。

    Returns:
        str: 測試伺服器的 Base URL。
    """
    return BASE_URL


@pytest.fixture(autouse=True)
def clean_database_state() -> None:
    """
    在每個測試案例執行前清理資料庫狀態。

    此 fixture 會自動在每個測試案例執行前被呼叫，用以重置或清理資料庫中的狀態，
    確保各個 E2E 測試案例之間的獨立性，避免數據殘留導致互相干擾。

    Returns:
        None
    """
