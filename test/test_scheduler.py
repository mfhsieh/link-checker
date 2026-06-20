"""
排程器與並發控制整合測試模組。

本腳本用於驗證當同時執行的任務數量達到系統設定的上限 (`CRAWLER_MAX_CONCURRENT_JOBS`) 時，
後續的任務是否能夠正確地進入 `queued` (排隊中) 狀態，而不會直接啟動。
"""

import pytest

from backend.config import Settings, get_settings
from backend.deps import get_job_manager
from backend.jobs.services.management import start_job
from crawler.manager import JobCreateOptions
from test.test_api import setup_databases, teardown_databases  # pylint: disable=wrong-import-order


def test_scheduler_queuing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    測試排程器的排隊機制。

    設定系統最大並發任務數量為 1，連續建立並啟動 3 個任務。
    驗證第一個任務會順利進入 `starting` 或 `running` 狀態，
    而第二與第三個任務會因為達到並發上限，自動轉為 `queued` 狀態。

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest 提供的猴子補丁物件，用於修改環境變數與模擬。

    Raises:
        AssertionError: 當任務沒有進入預期的狀態時拋出。
    """
    import subprocess  # pylint: disable=import-outside-toplevel

    class MockPopen:  # pylint: disable=too-few-public-methods
        """模擬的 subprocess.Popen，用於避免測試中產生背景程序。"""

        def __init__(self, *args: object, **kwargs: object) -> None:  # pylint: disable=unused-argument
            """初始化模擬的 Popen，給定假的 PID。"""
            self.pid: int = 99999

        def poll(self) -> int | None:
            """模擬 poll 方法，回傳 0 表示程序已結束。"""
            return 0

    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    monkeypatch.setenv("AUTH_DB_URL", "sqlite:///db/test_scheduler.db")
    monkeypatch.setenv("CRAWLER_DB_URL", "sqlite:///db/test_scheduler.db")
    monkeypatch.setenv("CRAWLER_MAX_CONCURRENT_JOBS", "1")

    # 清除 cache 以套用新的環境變數
    get_settings.cache_clear()

    # 強制覆寫已生成的 Settings 類別屬性 (因為它是 class-level 定義的預設值)
    Settings.CRAWLER_MAX_CONCURRENT_JOBS = 1

    # 初始化測試資料庫
    setup_databases()

    try:
        manager = get_job_manager()

        # Create 3 jobs
        job_ids = []
        for i in range(3):
            job_id = manager.create_job(
                JobCreateOptions(
                    start_url=f"http://example.com/{i}",
                    target_domains=["example.com"],
                    trusted_domains=[],
                    user_id="test_user",
                )
            )
            job_ids.append(job_id)

        # 啟動 3 個任務
        for job_id in job_ids:
            start_job(manager, job_id, "test_user")

        # 斷言：第 1 個任務因為並發數內，應該進入 starting 或 running 狀態
        job1 = manager.get_job(job_ids[0])
        assert job1 is not None
        assert job1.status in ("starting", "running"), f"First job status should be starting/running, got {job1.status}"

        # 斷言：第 2 與第 3 個任務應該因為並發限制而進入 queued 狀態
        job2 = manager.get_job(job_ids[1])
        assert job2 is not None
        assert job2.status == "queued", f"Second job status should be queued, got {job2.status}"

        job3 = manager.get_job(job_ids[2])
        assert job3 is not None
        assert job3.status == "queued", f"Third job status should be queued, got {job3.status}"

    finally:
        teardown_databases()
