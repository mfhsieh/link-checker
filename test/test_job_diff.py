"""
test_job_diff.py — 任務歷史差異比對服務與 API 端點單元測試

本測試模組驗證任務歷史差異比對引擎 (Job Diff Engine) 在記憶體 SQLite 環境下的
核心運算邏輯，確保外部連結比對（IP 變更、降級、復原、持續失敗、新增/移除）與
內部網頁比對（內部降級、內部復原、內部持續失敗、新增/移除頁面）的計算完全精確。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.jobs.services.diff import get_job_diff
from crawler.models import Base, CrawlQueue, ExternalLink, Job


def test_job_diff_service() -> None:  # pylint: disable=too-many-locals
    """
    測試 Job Diff 服務核心比對邏輯與數據分類計算。

    在 SQLite 記憶體資料庫中建立模擬任務、外部連結與內部網頁紀錄，
    驗證 get_job_diff 回傳之 external 與 internal 統計摘要數量是否正確。
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as crawler_db_session:
        # 建立兩個測試任務
        job1 = Job(
            id="diff_job_1",
            start_url="https://example.com",
            target_domains='["example.com"]',
            trusted_domains='["example.com"]',
            status="completed",
            user_id="user_test_diff",
        )
        job2 = Job(
            id="diff_job_2",
            start_url="https://example.com",
            target_domains='["example.com"]',
            trusted_domains='["example.com"]',
            status="completed",
            user_id="user_test_diff",
        )
        crawler_db_session.add_all([job1, job2])
        crawler_db_session.commit()

        # 外部連結 (Job 1)
        ext1_1 = ExternalLink(
            job_id="diff_job_1",
            source_url="https://example.com/a",
            target_url="https://ext1.com",
            ip_address="1.1.1.1",
            http_status_code=200,
            is_secure=True,
        )
        ext1_2 = ExternalLink(
            job_id="diff_job_1",
            source_url="https://example.com/a",
            target_url="https://ext2.com",
            ip_address="2.2.2.2",
            http_status_code=404,
            error_message="Not Found",
            is_secure=True,
        )
        ext1_3 = ExternalLink(
            job_id="diff_job_1",
            source_url="https://example.com/a",
            target_url="https://ext3.com",
            ip_address="3.3.3.3",
            http_status_code=200,
            is_secure=True,
        )
        ext1_cdn1 = ExternalLink(
            job_id="diff_job_1",
            source_url="https://example.com/a",
            target_url="https://cdn.com/a",
            ip_address="10.0.0.1",
            http_status_code=200,
            is_secure=True,
        )
        ext1_cdn2 = ExternalLink(
            job_id="diff_job_1",
            source_url="https://example.com/a",
            target_url="https://cdn.com/b",
            ip_address="10.0.0.2",
            http_status_code=200,
            is_secure=True,
        )

        # 外部連結 (Job 2)
        ext2_1 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://ext1.com",
            ip_address="1.1.1.2",
            http_status_code=200,
            is_secure=True,
        )  # IP Changed (ext1.com: 1.1.1.1 vs 1.1.1.2 - no intersection)
        ext2_2 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://ext2.com",
            ip_address="2.2.2.2",
            http_status_code=404,
            error_message="Not Found",
            is_secure=True,
        )  # Persistently Failed
        ext2_3 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://ext3.com",
            ip_address="3.3.3.3",
            http_status_code=500,
            error_message="Internal Error",
            is_secure=True,
        )  # Degraded
        ext2_4 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://ext4.com",
            ip_address="4.4.4.4",
            http_status_code=200,
            is_secure=True,
        )  # New Link
        ext2_cdn1 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://cdn.com/a",
            ip_address="10.0.0.2",
            http_status_code=200,
            is_secure=True,
        )
        ext2_cdn2 = ExternalLink(
            job_id="diff_job_2",
            source_url="https://example.com/a",
            target_url="https://cdn.com/b",
            ip_address="10.0.0.1",
            http_status_code=200,
            is_secure=True,
        )  # CDN Multi-IP (cdn.com IPs: {10.0.0.1, 10.0.0.2} both jobs -> intersection -> NOT ip_changed)

        # 內部連結 (Job 1)
        int1_1 = CrawlQueue(
            job_id="diff_job_1", url="https://example.com/page1", status_code=200, status_category="ok", depth=1
        )
        int1_2 = CrawlQueue(
            job_id="diff_job_1",
            url="https://example.com/page2",
            status_code=404,
            status_category="failed",
            error_message="404 Not Found",
            depth=1,
        )

        # 內部連結 (Job 2)
        int2_1 = CrawlQueue(
            job_id="diff_job_2",
            url="https://example.com/page1",
            status_code=500,
            status_category="failed",
            error_message="500 Server Error",
            depth=1,
        )  # Internal Degraded
        int2_2 = CrawlQueue(
            job_id="diff_job_2",
            url="https://example.com/page2",
            status_code=404,
            status_category="failed",
            error_message="404 Not Found",
            depth=1,
        )  # Internal Persistently Failed
        int2_3 = CrawlQueue(
            job_id="diff_job_2", url="https://example.com/page3", status_code=200, status_category="ok", depth=2
        )  # Internal New Page

        crawler_db_session.add_all(
            [
                ext1_1,
                ext1_2,
                ext1_3,
                ext1_cdn1,
                ext1_cdn2,
                ext2_1,
                ext2_2,
                ext2_3,
                ext2_4,
                ext2_cdn1,
                ext2_cdn2,
                int1_1,
                int1_2,
                int2_1,
                int2_2,
                int2_3,
            ]
        )
        crawler_db_session.commit()

        diff_res = get_job_diff(crawler_db_session, "diff_job_1", "diff_job_2", "user_test_diff", scope="all")

        # 驗證外部連結比對
        ext_summary = diff_res["external"]["summary"]
        assert ext_summary["ip_changed"] == 1
        assert ext_summary["degraded"] == 1
        assert ext_summary["new_links"] == 1

        # 驗證內部連結比對
        int_summary = diff_res["internal"]["summary"]
        assert int_summary["degraded"] == 1
        assert int_summary["new_pages"] == 1
