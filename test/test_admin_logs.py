"""
後台操作日誌的整合測試模組。

驗證全域配置修改、使用者狀態變更以及日誌篩選功能是否正確記錄與回傳。
"""

import os
import sys
import json
import unittest
from datetime import datetime, timedelta
from collections.abc import Generator

# 將專案路徑加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.main import app
from backend.deps import get_auth_db, require_admin, require_csrf
from backend.auth.models import AuthBase, AuthLog, User

# 測試用 SQLite DSN
TEST_AUTH_DB_URL: str = "sqlite:///tmp/auth_test.db"

# 建立 Engine
engine: Engine = create_engine(
    TEST_AUTH_DB_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 覆寫 get_auth_db 依賴
def override_get_auth_db() -> Generator[Session, None, None]:
    """
    覆寫取得 Auth DB Session 的依賴函式。

    Yields:
        Session: 測試用的 Auth DB Session。
    """
    try:
        db = TestingSessionLocal()
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# 模擬的管理員物件
mock_admin: User = User(
    id="admin-id", email="admin@test.com", role="admin", status="active"
)

# 設定 dependency overrides
app.dependency_overrides[get_auth_db] = override_get_auth_db
app.dependency_overrides[require_admin] = lambda: mock_admin
app.dependency_overrides[require_csrf] = lambda: None


class TestAdminLogs(unittest.TestCase):
    """
    測試管理員操作日誌的案例類別。
    """

    client: TestClient
    config_path: str
    config_backup: str | None

    @classmethod
    def setUpClass(cls) -> None:
        """
        在所有測試開始前執行的初始化操作。
        建立測試資料表、寫入初始使用者，並備份全域設定檔。
        """
        # 建立所有資料表
        os.makedirs("tmp", exist_ok=True)
        AuthBase.metadata.create_all(bind=engine)

        # 建立一些測試資料
        db = TestingSessionLocal()
        # 確保 mock admin 存在
        if not db.query(User).filter(User.id == "admin-id").first():
            db.add(User(id="admin-id", email="admin@test.com", role="admin", status="active"))
        # 確保要被操作的 user 存在
        if not db.query(User).filter(User.id == "test-user-id").first():
            db.add(User(id="test-user-id", email="user@test.com", role="user", status="active"))
        db.commit()
        db.close()

        cls.client = TestClient(app)

        # 備份 config_global.yaml，避免測試修改影響系統
        cls.config_path = "config/config_global.yaml"
        cls.config_backup = None
        if os.path.exists(cls.config_path):
            with open(cls.config_path, "r", encoding="utf-8") as f:
                cls.config_backup = f.read()

    @classmethod
    def tearDownClass(cls) -> None:
        """
        在所有測試結束後執行的清理操作。
        刪除測試資料表與檔案，並還原全域設定檔。
        """
        # 刪除測試資料表
        AuthBase.metadata.drop_all(bind=engine)
        if os.path.exists("tmp/auth_test.db"):
            try:
                os.remove("tmp/auth_test.db")
            except OSError:
                pass

        # 還原 config_global.yaml
        if cls.config_backup is not None:
            try:
                with open(cls.config_path, "w", encoding="utf-8") as f:
                    f.write(cls.config_backup)
            except OSError:
                pass

    def setUp(self) -> None:
        """
        在每個測試方法執行前清空操作日誌。
        """
        # 每次測試前清空 AuthLog，確保測試獨立性
        db = TestingSessionLocal()
        db.query(AuthLog).delete()
        db.commit()
        db.close()

    def test_config_change_logging(self) -> None:
        """
        測試全域配置修改時，是否正確記錄操作日誌。
        """
        # 先做一次配置更新
        payload = {
            "crawler": {
                "timeout": 12,
                "delay": 1.5,
            }
        }
        response = self.client.patch("/api/admin/config", json=payload)
        self.assertEqual(response.status_code, 200)

        # 驗證 AuthLog 是否寫入
        db = TestingSessionLocal()
        log = db.query(AuthLog).filter(AuthLog.event_type == "config_change").first()
        self.assertIsNotNone(log)
        if log:
            self.assertEqual(log.user_id, "admin-id")
            detail = json.loads(str(log.detail))
            self.assertEqual(detail["action"], "update_global_config")
            self.assertIn("before", detail)
            self.assertEqual(detail["after"]["timeout"], 12)
        db.close()

    def test_user_status_changed_logging(self) -> None:
        """
        測試使用者狀態與角色變更時，是否正確記錄操作日誌。
        """
        payload = {
            "status": "suspended",
        }
        response = self.client.patch("/api/admin/users/test-user-id", json=payload)
        self.assertEqual(response.status_code, 200)

        db = TestingSessionLocal()
        log = db.query(AuthLog).filter(AuthLog.event_type == "user_status_changed").first()
        self.assertIsNotNone(log)
        if log:
            self.assertEqual(log.user_id, "admin-id")
            detail = json.loads(str(log.detail))
            self.assertEqual(detail["target_user_id"], "test-user-id")
            self.assertEqual(detail["changes"]["status"]["after"], "suspended")
        db.close()

    def test_logs_date_filtering(self) -> None:
        """
        測試操作日誌的日期區間篩選功能。
        """
        db = TestingSessionLocal()
        # 建立幾個不同時間點的日誌
        now = datetime.now()
        log1 = AuthLog(
            user_id="admin-id", event_type="test_event", created_at=now - timedelta(days=5)
        )
        log2 = AuthLog(
            user_id="admin-id", event_type="test_event", created_at=now - timedelta(days=2)
        )
        log3 = AuthLog(user_id="admin-id", event_type="test_event", created_at=now)
        db.add_all([log1, log2, log3])
        db.commit()
        db.close()

        # 1. 查詢所有 (無時間過濾)
        response = self.client.get("/api/admin/logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)

        # 2. 用 start_date 查詢 (只查詢 3 天內的)
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        response = self.client.get(f"/api/admin/logs?start_date={three_days_ago}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)  # log2, log3

        # 3. 用 end_date 查詢 (查詢 1 天之前的)
        one_day_ago = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.get(f"/api/admin/logs?end_date={one_day_ago}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)  # log1, log2

        # 4. 用區間查詢
        response = self.client.get(
            f"/api/admin/logs?start_date={three_days_ago}&end_date={one_day_ago}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)  # log2


if __name__ == "__main__":
    unittest.main()
