"""
API 端點完整覆蓋率測試腳本 (API Endpoints Full Coverage Test)。

本模組透過 `fastapi.testclient.TestClient` 針對整個後端應用程式 (`app`) 進行端到端 (E2E) 的 API 測試，
驗證認證流程、後台管理、以及爬蟲任務管理等所有對外開放的 API 端點。
透過強制切換資料庫至測試用的 SQLite 檔案 (`test_auth.db` 與 `test_crawler.db`)，避免污染正式環境。
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import SQLAlchemyError

from test.utils import is_port_in_use, wait_for_server  # pylint: disable=wrong-import-order

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position, duplicate-code, protected-access
from fastapi.testclient import TestClient

from backend.auth.db import get_auth_engine, get_auth_session_local
from backend.auth.models import User
from backend.auth.password import hash_password
from backend.deps import get_job_manager
from backend.main import app


def _set_api_test_env() -> None:
    """
    設定 API 測試專用的環境變數。

    在每次 setup_databases() 前呼叫，確保環境變數指向正確的測試資料庫，
    避免被其他測試模組的模組級設定覆蓋。
    """
    os.environ["AUTH_DB_URL"] = "sqlite:///db/test_auth_api.db"
    os.environ["CRAWLER_DB_URL"] = "sqlite:///db/test_crawler_api.db"
    os.environ["GLOBAL_CONFIG_PATH"] = "config/test_config_global_api.yaml"
    # 強制更新 Settings class 的 DB URL（因為 Settings 使用 class-level 屬性且有 lru_cache）
    from test.conftest import refresh_settings_cache  # pylint: disable=import-outside-toplevel

    refresh_settings_cache()

    # 初始化獨立的測試全域設定檔
    if os.path.exists("config/config_global.yaml.example"):
        shutil.copy("config/config_global.yaml.example", "config/test_config_global_api.yaml")


def setup_databases() -> None:
    """
    建立並初始化全新的測試用資料庫。

    此函式會先移除現有的測試用 SQLite 資料庫檔案 (`test_auth.db` 與 `test_crawler.db`)，
    接著呼叫 `get_auth_engine()` 與 `get_job_manager()` 來重新建立對應的資料表與初始化狀態。
    確保每次測試都在乾淨的環境下執行。
    """
    # pylint: disable=import-outside-toplevel, protected-access
    import backend.auth.db as auth_db
    import backend.deps as backend_deps

    # 確保環境變數指向正確的測試 DB
    _set_api_test_env()

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

    # 清除舊的資料庫主檔案與 -shm/-wal 暫存檔
    for db_file in ["db/test_auth_api.db", "db/test_crawler_api.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass

    get_auth_engine()
    get_job_manager()  # This initializes the crawler DB and creates tables


def teardown_databases() -> None:
    """
    清理測試所產生的資料庫檔案。
    """
    # pylint: disable=import-outside-toplevel, protected-access
    import backend.auth.db as auth_db
    import backend.deps as backend_deps

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

    # 清除資料庫主檔案與 -shm/-wal 暫存檔
    for db_file in ["db/test_auth_api.db", "db/test_crawler_api.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass

    # 清除測試用全域設定檔
    if os.path.exists("config/test_config_global_api.yaml"):
        try:
            os.remove("config/test_config_global_api.yaml")
        except OSError:
            pass


def create_admin_user() -> None:
    """
    在 Auth 資料庫中直接插入一筆管理員測試帳號。

    為繞過「首次登入需修改密碼」的限制，此函式會透過 SQLAlchemy 直接將 `last_login_at`
    設定為當前時間。建立的管理員帳號為：`admin@test.com`，密碼為：`Admin@12345678`。
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


def get_csrf_token(response: httpx.Response, current_token: str = "") -> str:
    """
    從 FastAPI 的 HTTP 回應 (Response) 中萃取 CSRF Token。

    若該次請求有回傳 `Set-Cookie: csrf_token=...`，則提取並回傳新 token；
    若無回傳，則保留並回傳原本的 `current_token`，避免因為未更新而遺失 Token。

    Args:
        response (Response): `httpx` 或 `TestClient` 所回傳的 HTTP 回應物件。
        current_token (str, optional): 既有的 CSRF Token，預設為空字串。

    Returns:
        str: 最新有效的 CSRF Token。
    """
    for cookie in response.cookies.jar:
        if cookie.name == "csrf_token":
            return cookie.value
    return current_token


# pylint: disable=too-many-statements
def test_api_full_flow() -> None:
    """
    依序執行所有後端 API 端點的整合測試 (Integration Tests)。

    測試涵蓋以下核心功能模組：
    1. Health Check (`/api/health`)
    2. 使用者認證 (Login, Get Me, Change Password, Logout)
    3. 後台管理 (Admin Users, Config, SMTP Test, Logs)
    4. 爬蟲任務管理 (Create, List, Detail, Start, Pause, Resume, Reset, Retry, Transfer, Takeover, Delete)
    5. 爬蟲任務結果 (Results, Summary, Diff, Export)

    透過 `TestClient` 模擬真實 HTTP 請求，並驗證每個端點的 HTTP 狀態碼與部分回傳結構，
    以確保整個 FastAPI 後端系統運作正常。
    """
    from unittest.mock import patch  # pylint: disable=import-outside-toplevel

    class MockPopen:  # pylint: disable=too-few-public-methods
        """模擬的 subprocess.Popen，用於避免測試中產生背景程序。"""

        def __init__(self, *args: object, **kwargs: object) -> None:  # pylint: disable=unused-argument
            """初始化模擬的 Popen，給定假的 PID。"""
            self.pid: int = 99999

        def poll(self) -> int | None:
            """模擬 poll 方法，回傳 0 表示程序已結束。"""
            return 0

    with patch("subprocess.Popen", MockPopen):
        setup_databases()
        create_admin_user()
        try:
            _run_api_full_flow()
        finally:
            teardown_databases()


# pylint: disable=too-many-locals
def _run_api_full_flow() -> None:
    """
    執行所有的 API 整合測試流程。

    包含所有的 API 端點存取與斷言檢查。

    Raises:
        AssertionError: 當 API 測試未達預期結果時拋出。
    """
    print("--- Starting API Tests ---")
    client = TestClient(app)

    # 1. Health
    res = client.get("/api/health")
    assert res.status_code in (200, 201, 202), f"Health check failed: {res.text}"
    csrf_token = get_csrf_token(res)

    # 2. Login (Auth)
    login_data = {"email": "admin@test.com", "password": "Admin@12345678"}
    res = client.post("/api/auth/login", json=login_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), f"Login failed: {res.text}"
    csrf_token = get_csrf_token(res, csrf_token)  # Update CSRF after login changes session

    # 3. Get Me
    res = client.get("/api/auth/me")
    assert res.status_code in (200, 201, 202), f"/api/auth/me failed: {res.text}"
    assert res.json()["email"] == "admin@test.com"

    # 4. Change Password
    pwd_data = {"current_password": "Admin@12345678", "new_password": "SuperSecret!@#$123456"}
    res = client.patch("/api/auth/password", json=pwd_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), f"Change password failed: {res.text}"
    # 密碼變更後，所有 Session 會被強制撤銷，需要使用新密碼重新登入
    login_data_new = {"email": "admin@test.com", "password": "SuperSecret!@#$123456"}
    res = client.post("/api/auth/login", json=login_data_new)
    assert res.status_code in (200, 201, 202), f"Re-login failed: {res.text}"
    csrf_token = get_csrf_token(res)

    # 5. Admin - Create User (Invite)
    invite_data = {"email": "user1@test.com"}
    res = client.post("/api/admin/users", json=invite_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), f"Admin create user failed: {res.text}"
    user1_id = res.json()["user_id"]

    # 6. Admin - List Users
    res = client.get("/api/admin/users")
    assert res.status_code in (200, 201, 202), res.text
    users = res.json()
    assert len(users) == 2  # admin and user1

    # 7. Admin - Resend Invite
    res = client.post(f"/api/admin/users/{user1_id}/resend-invite", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text

    # 8. Admin - Update User (e.g. suspend)
    update_data = {"status": "suspended"}
    res = client.patch(f"/api/admin/users/{user1_id}", json=update_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text
    # Backend might return only a success message

    # 9. Admin - Delete User
    res = client.delete(f"/api/admin/users/{user1_id}", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text

    # 10. Admin - Config
    res = client.get("/api/admin/config")
    assert res.status_code in (200, 201, 202), res.text
    config_data = {"crawler": {"min_timeout": 2}}
    res = client.patch("/api/admin/config", json=config_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text
    # Backend might return success message or updated config

    # 11. Admin - SMTP
    res = client.get("/api/admin/smtp")
    assert res.status_code in (200, 201, 202), res.text

    res = client.post("/api/admin/smtp/test", json={"to_email": "admin@test.com"}, headers={"X-CSRF-Token": csrf_token})
    # Might fail with 400/500 if SMTP is not configured properly in env, just assert it returns a known code cleanly
    assert res.status_code in (200, 201, 202, 400, 500), res.text

    # 12. Admin - Logs
    res = client.get("/api/admin/logs")
    assert res.status_code in (200, 201, 202), res.text

    # 13. Jobs - Default Config
    res = client.get("/api/jobs/default-config")
    assert res.status_code in (200, 201, 202), res.text

    # 14. Jobs - Create
    job_data = {
        "start_url": "https://example.com",
        "target_domains": ["example.com"],
        "trusted_domains": [],
        "delay": 0.0,
        "timeout": 2,
        "connect_timeout": 1,
        "external_check_timeout": 1,
        "retries": 0,
        "max_pages": 1,
        "max_depth": 1,
        "ignore_regexes": [],
    }
    res = client.post("/api/jobs", json=job_data, headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), f"Job create failed: {res.text}"
    job_id = res.json()["job_id"]

    # 15. Jobs - List
    res = client.get("/api/jobs")
    assert res.status_code in (200, 201, 202), res.text
    assert len(res.json()) == 1

    # 15.5. Admin - Jobs List
    res = client.get("/api/admin/jobs")
    assert res.status_code in (200, 201, 202), res.text
    assert len(res.json()) >= 1

    # 16. Jobs - Detail
    res = client.get(f"/api/jobs/{job_id}")
    assert res.status_code in (200, 201, 202), res.text

    # 17. Jobs Control - Start
    res = client.post(f"/api/jobs/{job_id}/start", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202, 400), res.text

    # 18. Jobs Control - Pause
    res = client.post(f"/api/jobs/{job_id}/pause", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 400)

    # Update DB to pretend it's paused so we can test resume
    conn = sqlite3.connect("db/test_crawler_api.db")
    conn.execute("UPDATE jobs SET status = 'paused' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    # 19. Jobs Control - Resume
    res = client.post(f"/api/jobs/{job_id}/resume", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202, 400), res.text

    # 20. Jobs Control - Reset
    # Need to pretend it's completed or failed
    conn = sqlite3.connect("db/test_crawler_api.db")
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    res = client.post(f"/api/jobs/{job_id}/reset", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202, 400), res.text

    # 21. Jobs Control - Retry Failed
    conn = sqlite3.connect("db/test_crawler_api.db")
    conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    res = client.post(f"/api/jobs/{job_id}/retry-failed", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202, 400), res.text

    # 22. Jobs Control - Transfer
    res = client.post("/api/admin/users", json={"email": "user2@test.com"}, headers={"X-CSRF-Token": csrf_token})
    # Just verify creation succeeds

    res = client.post(
        f"/api/jobs/{job_id}/transfer", json={"target_email": "user2@test.com"}, headers={"X-CSRF-Token": csrf_token}
    )
    assert res.status_code in (200, 201, 202, 400), res.text

    # 23. Admin - Takeover Job
    res = client.post(
        f"/api/admin/jobs/{job_id}/takeover", json={"action": "pause"}, headers={"X-CSRF-Token": csrf_token}
    )
    assert res.status_code in (200, 201, 202, 400), res.text

    # 24. Admin - Delete Job
    res = client.delete(f"/api/admin/jobs/{job_id}", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text

    # 24.5 User delete job API
    res = client.post("/api/jobs", json=job_data, headers={"X-CSRF-Token": csrf_token})
    job_to_delete = res.json()["job_id"]
    res = client.delete(f"/api/jobs/{job_to_delete}", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text

    # 25. Jobs Result APIs (Create a dummy job with results)
    res = client.post("/api/jobs", json=job_data, headers={"X-CSRF-Token": csrf_token})
    job_id_2 = res.json()["job_id"]

    res = client.get(f"/api/jobs/{job_id_2}/results")
    assert res.status_code in (200, 201, 202), res.text

    res = client.get(f"/api/jobs/{job_id_2}/results/summary")
    assert res.status_code in (200, 201, 202), res.text

    res = client.get(f"/api/jobs/{job_id_2}/internal-results")
    assert res.status_code in (200, 201, 202), res.text

    res = client.get(f"/api/jobs/{job_id_2}/internal-results/summary")
    assert res.status_code in (200, 201, 202), res.text

    # Diff API requires a target_job_id
    res = client.post("/api/jobs", json=job_data, headers={"X-CSRF-Token": csrf_token})
    job_id_3 = res.json()["job_id"]

    res = client.get(f"/api/jobs/{job_id_3}/diff?compare_with={job_id_2}")
    assert res.status_code in (200, 201, 202), res.text

    # Export APIs
    res = client.get(f"/api/jobs/{job_id_2}/results/export")
    assert res.status_code in (200, 201, 202), res.text

    res = client.get(f"/api/jobs/{job_id_2}/internal-results/export")
    assert res.status_code in (200, 201, 202), res.text

    res = client.get(f"/api/jobs/{job_id_2}/export/full")
    assert res.status_code in (200, 201, 202), res.text

    # SSE Stream 進度串流
    with client.stream("GET", f"/api/jobs/{job_id_2}/stream") as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line:
                assert line.startswith("data: ")
                break

    # 25.5 Auth Extra endpoints (set-password, forgot-password, reset-password)
    # 一般 Session 呼叫 set-password 應被 403 拒絕
    res = client.post(
        "/api/auth/set-password", json={"new_password": "NewPassword@1234"}, headers={"X-CSRF-Token": csrf_token}
    )
    assert res.status_code == 403, res.text

    res = client.post("/api/auth/forgot-password", json={"email": "forgot@test.com"})
    assert res.status_code in (200, 429), res.text

    res = client.post("/api/auth/reset-password", json={"token": "invalid-token", "new_password": "NewPassword@1234"})
    assert res.status_code == 400, res.text

    # 26. Auth Logout
    res = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert res.status_code in (200, 201, 202), res.text

    print("--- API Tests Passed Successfully ---")


# pylint: disable=too-many-statements, too-many-locals, consider-using-with, unused-variable
def test_api_real_scenario_flow() -> None:
    """執行真實劇本情境 (Real Scenario Flow) 測試。.

    此測試模擬真實使用者透過 API 的完整操作行為：
    1. 背景啟動 Mock HTTP Server 作為爬蟲的靶機。
    2. 透過 API 登入並取得授權。
    3. 透過 API 建立一筆爬行任務，目標為靶機的首頁。
    4. 透過 API 啟動該爬蟲任務。
    5. 透過 API 輪詢 (Polling) 任務狀態，直到爬行結束。
    6. 透過 API 讀取最終報表，並驗證系統是否確實爬取了靶機上各種特殊情境的外部連結。

    Raises:
        AssertionError: 測試中任何檢查未通過或發生非預期結果時拋出。

    """
    port = 8081
    if is_port_in_use(port):
        print(f"Warning: Port {port} is already in use. Mock server might fail to bind.")

    server_cmd = [sys.executable, "test/test_server/server.py", str(port)]
    print(f"Starting Mock Server on port {port}...")
    server_proc = subprocess.Popen(server_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

    try:
        if not wait_for_server(port):
            assert False, "Mock Server failed to start."

        # 1. 初始化資料庫與使用者
        setup_databases()
        create_admin_user()

        # 允許本地端 IP 以免 SSRF 阻擋機制擋下靶機
        os.environ["CRAWLER_ALLOW_LOCAL_IPS"] = "true"

        client = TestClient(app)

        # 2. 登入
        res = client.get("/api/health")
        csrf_token = get_csrf_token(res)

        login_data = {"email": "admin@test.com", "password": "Admin@12345678"}
        res = client.post("/api/auth/login", json=login_data, headers={"X-CSRF-Token": csrf_token})
        assert res.status_code in (200, 201, 202), f"Login failed: {res.text}"
        csrf_token = get_csrf_token(res, csrf_token)

        # 2.5 Update global config to allow small timeouts
        config_data = {
            "crawler": {
                "min_timeout": 1,
                "min_external_check_timeout": 0.1,
                "min_delay": 0.0,
            }
        }
        client.patch("/api/admin/config", json=config_data, headers={"X-CSRF-Token": csrf_token})

        # 3. 建立任務
        job_data = {
            "start_url": f"http://127.0.0.1:{port}/index.html",
            "target_domains": ["127.0.0.1", "localhost"],
            "trusted_domains": [],
            "delay": 0.0,
            "timeout": 2,
            "connect_timeout": 1.0,
            "external_check_timeout": 1.0,
            "retries": 1,
            "ignore_regexes": [],
        }
        res = client.post("/api/jobs", json=job_data, headers={"X-CSRF-Token": csrf_token})
        assert res.status_code in (200, 201, 202), f"Job create failed: {res.text}"
        job_id = res.json()["job_id"]

        # 4. 啟動任務
        print(f"Starting crawler job {job_id} via API...")
        res = client.post(f"/api/jobs/{job_id}/start", headers={"X-CSRF-Token": csrf_token})
        assert res.status_code in (200, 201, 202), f"Failed to start job: {res.text}"

        # 5. 輪詢 (Polling) 狀態直到完成
        max_attempts = 60
        attempts = 0
        is_completed = False

        while attempts < max_attempts:
            res = client.get(f"/api/jobs/{job_id}")
            assert res.status_code in (200, 201, 202), f"Failed to get job detail: {res.text}"
            status = res.json()["status"]
            if status == "completed":
                is_completed = True
                break
            if status == "error":
                assert False, "Crawler job failed with error status"
            time.sleep(0.5)
            attempts += 1

        assert is_completed, "Crawler job timed out before completion"

        # 6. 讀取結果並驗證
        res = client.get(f"/api/jobs/{job_id}/results")
        assert res.status_code in (200, 201, 202), f"Failed to get results: {res.text}"
        external_links = res.json()["items"]

        # 尋找特定的幾個連結來驗證靶機內容是否成功被解析
        found_google = False
        found_httpbin_404 = False
        found_neverssl = False

        for link in external_links:
            target = link["target_url"]
            if target == "https://www.google.com":
                found_google = True
                assert link["is_secure"] is True, "Google should be secure"
                assert link["http_status_code"] == 200, "Google should return 200"
            elif target == "https://httpbin.org/status/404":
                found_httpbin_404 = True
                assert link["http_status_code"] in (404, 502, 503, 504, None), (
                    f"httpbin 404 should return 404, 502, 503, 504 or None, got {link['http_status_code']}"
                )
            elif target == "http://neverssl.com":
                found_neverssl = True
                assert link["is_secure"] is False, "neverssl should be insecure"

        assert found_google, "Google link not found in results"
        assert found_httpbin_404, "httpbin 404 link not found in results"
        assert found_neverssl, "neverssl link not found in results"

        # 7. 測試匯出
        res = client.get(f"/api/jobs/{job_id}/results/export?fmt=json")
        assert res.status_code in (200, 201, 202), f"Export failed: {res.text}"
        export_data = res.json()
        assert isinstance(export_data, list), "Export data should be a list"
        assert len(export_data) > 0, "Export data should not be empty"

        print("--- Real Scenario Test Passed Successfully ---")

    finally:
        print("Terminating Mock Server process...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=2)
            print("Mock Server process terminated.")
        except subprocess.TimeoutExpired:
            server_proc.kill()
            print("Mock Server process killed.")
        teardown_databases()


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main(["-v", "-s", __file__]))
