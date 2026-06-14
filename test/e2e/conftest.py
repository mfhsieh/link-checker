"""
E2E 自動化整合測試的 Pytest Fixture 配置模組。

提供測試伺服器生命週期管理、資料庫初始化，以及 Playwright 相關設定。
"""

# pylint: disable=protected-access, broad-exception-caught, duplicate-code, consider-using-with

import os
import subprocess
import sys
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

# Ensure we don't accidentally touch dev databases
os.environ["AUTH_DB_URL"] = "sqlite:///db/test_auth_e2e.db"
os.environ["CRAWLER_DB_URL"] = "sqlite:///db/test_crawler_e2e.db"

# 將專案路徑加入 path 以便引用 backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.auth.db import get_auth_engine, get_auth_session_local  # pylint: disable=wrong-import-position
from backend.auth.models import User  # pylint: disable=wrong-import-position
from backend.auth.password import hash_password  # pylint: disable=wrong-import-position
from backend.deps import get_job_manager  # pylint: disable=wrong-import-position

PORT = 8085
BASE_URL = f"http://127.0.0.1:{PORT}"


def setup_databases() -> None:
    """
    清理並初始化 E2E 測試用資料庫。

    此函式會重建 Auth DB 與 Crawler DB 以確保測試環境乾淨。
    """
    import backend.auth.db as auth_db  # pylint: disable=import-outside-toplevel
    import backend.deps as backend_deps  # pylint: disable=import-outside-toplevel

    # 強制關閉並釋放 SQLAlchemy Engine 連線池，釋放 sqlite fd
    if auth_db._ENGINE is not None:
        try:
            auth_db._ENGINE.dispose()
        except Exception:
            pass
    auth_db._ENGINE = None
    auth_db._SESSION_LOCAL = None

    if backend_deps._JOB_MANAGER is not None:
        try:
            backend_deps._JOB_MANAGER.engine.dispose()
        except Exception:
            pass
    backend_deps._JOB_MANAGER = None

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
    """
    import backend.auth.db as auth_db  # pylint: disable=import-outside-toplevel
    import backend.deps as backend_deps  # pylint: disable=import-outside-toplevel

    # 強制關閉並釋放 SQLAlchemy Engine 連線池，釋放 sqlite fd
    if auth_db._ENGINE is not None:
        try:
            auth_db._ENGINE.dispose()
        except Exception:
            pass
    auth_db._ENGINE = None
    auth_db._SESSION_LOCAL = None

    if backend_deps._JOB_MANAGER is not None:
        try:
            backend_deps._JOB_MANAGER.engine.dispose()
        except Exception:
            pass
    backend_deps._JOB_MANAGER = None

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

    在 Auth 資料庫中直接插入一筆 admin@test.com 帳號，以利後續 E2E 測試登入。
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
    """
    setup_databases()
    create_admin_user()

    env = os.environ.copy()
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if not wait_for_server(PORT):
        server_proc.terminate()
        stdout, stderr = server_proc.communicate()
        raise RuntimeError(f"FastAPI Server failed to start.\\nSTDOUT: {stdout}\\nSTDERR: {stderr}")

    yield BASE_URL

    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()
    teardown_databases()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:  # pylint: disable=redefined-outer-name
    """
    覆寫 Playwright 啟動參數，強制使用系統的 Chromium。

    Args:
        browser_type_launch_args (dict[str, Any]): 原始啟動參數。

    Returns:
        dict[str, Any]: 覆寫後的啟動參數。
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
    每個測試案例前可以清理狀態。

    為了 E2E 流暢度，這裡只做示範，真實的狀態分離可透過 UI 操作或是重建資料庫來達成。
    """
