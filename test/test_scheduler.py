"""
排程器與並發控制整合測試模組。

本腳本用於驗證當同時執行的任務數量達到系統設定的上限 (`CRAWLER_MAX_CONCURRENT_JOBS`) 時，
後續的任務是否能夠正確地進入 `queued` (排隊中) 狀態，而不會直接啟動。
"""

from test.test_api import setup_databases
import pytest

from backend.config import get_settings
from backend.deps import get_job_manager
from backend.jobs.services.management import start_job
from crawler.manager import JobCreateOptions
from crawler.models import Job


def test_scheduler_queuing(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    測試排程器的排隊機制。

    設定系統最大並發任務數量為 1，連續建立並啟動 3 個任務。
    驗證第一個任務會順利進入 `starting` 或 `running` 狀態，
    而第二與第三個任務會因為達到並發上限，自動轉為 `queued` 狀態。

    Raises:
        AssertionError: 當任務沒有進入預期的狀態時拋出。
    """
    monkeypatch.setenv("AUTH_DB_URL", "sqlite:///db/test_scheduler.db")
    monkeypatch.setenv("CRAWLER_DB_URL", "sqlite:///db/test_scheduler.db")
    monkeypatch.setenv("CRAWLER_MAX_CONCURRENT_JOBS", "1")

    # 清除 cache 以套用新的環境變數
    get_settings.cache_clear()

    # 強制覆寫已生成的 Settings 類別屬性 (因為它是 class-level 定義的預設值)
    from backend.config import Settings  # pylint: disable=import-outside-toplevel

    Settings.CRAWLER_MAX_CONCURRENT_JOBS = 1

    # 初始化測試資料庫
    setup_databases()

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

    # Start all 3 jobs
    for j_id in job_ids:
        start_job(manager, j_id, user_id="test_user")

    with manager.session_factory() as session:
        j0 = session.query(Job).filter(Job.id == job_ids[0]).first()
        j1 = session.query(Job).filter(Job.id == job_ids[1]).first()
        j2 = session.query(Job).filter(Job.id == job_ids[2]).first()

        assert j0 is not None
        assert j1 is not None
        assert j2 is not None

        print(f"Status of jobs: {j0.status}, {j1.status}, {j2.status}")
        assert j0.status in ("starting", "running")
        assert j1.status == "queued"
        assert j2.status == "queued"
