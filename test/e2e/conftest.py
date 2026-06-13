import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx
import pytest

# Ensure we don't accidentally touch dev databases
os.environ["AUTH_DB_URL"] = "sqlite:///db/test_auth_e2e.db"
os.environ["CRAWLER_DB_URL"] = "sqlite:///db/test_crawler_e2e.db"

# 將專案路徑加入 path 以便引用 backend
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.auth.db import get_auth_engine, get_auth_session_local
from backend.auth.models import User
from backend.auth.password import hash_password
from backend.deps import get_job_manager

PORT = 8085
BASE_URL = f"http://127.0.0.1:{PORT}"


def setup_databases() -> None:
    """清理並初始化 E2E 測試用資料庫。"""
    import backend.auth.db as auth_db
    import backend.deps as backend_deps

    auth_db._ENGINE = None
    auth_db._SESSION_LOCAL = None
    backend_deps._JOB_MANAGER = None

    if os.path.exists("db/test_auth_e2e.db"):
        os.remove("db/test_auth_e2e.db")
    if os.path.exists("db/test_crawler_e2e.db"):
        os.remove("db/test_crawler_e2e.db")

    get_auth_engine()
    get_job_manager()


def create_admin_user() -> None:
    """建立 E2E 測試用的管理員帳號。"""
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
    """等待伺服器啟動並回應 HTTP 請求。"""
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
def test_server():
    """在整個 E2E 測試期間啟動 FastAPI 伺服器，並提供乾淨的資料庫。"""
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


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """覆寫 Playwright 啟動參數，強制使用系統的 Chromium。"""
    return {**browser_type_launch_args, "executable_path": "/usr/bin/chromium"}


@pytest.fixture(scope="session")
def base_url():
    """Playwright 預設會使用此 base_url 來訪問網頁。"""
    return BASE_URL


@pytest.fixture(autouse=True)
def clean_database_state():
    """每個測試案例前可以清理狀態，但為了 E2E 流暢度，這裡只做示範，
    真實的狀態分離可以透過 UI 操作或是重建資料庫來達成。"""
    pass
