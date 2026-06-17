"""
E2E integration test script for external link checker.
"""

# pylint: disable=protected-access, duplicate-code

import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile

from sqlalchemy.exc import SQLAlchemyError

from test.utils import is_port_in_use, wait_for_server

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PORT: int = 8080
DB_PATH: str = "db/test_crawler_cli.db"
YAML_CONFIG: str = "job/test_job.yaml"


def _set_cli_test_env() -> None:
    """
    設定 CLI 測試專用的環境變數。

    在每次 setup_databases() 前呼叫，確保環境變數指向正確的測試資料庫，
    避免被其他測試模組的模組級設定覆蓋。
    """
    os.environ["AUTH_DB_URL"] = "sqlite:///db/test_auth_cli.db"
    os.environ["CRAWLER_DB_URL"] = "sqlite:///db/test_crawler_cli.db"
    # 強制更新 Settings class 的 DB URL（因為 Settings 使用 class-level 屬性且有 lru_cache）
    from test.conftest import refresh_settings_cache  # pylint: disable=import-outside-toplevel
    refresh_settings_cache()


def setup_databases() -> None:
    """
    建立並初始化全新的測試用資料庫。
    """
    # pylint: disable=import-outside-toplevel, protected-access
    import backend.auth.db as auth_db
    import backend.deps as backend_deps

    # 確保環境變數指向正確的測試 DB
    _set_cli_test_env()

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
    for db_file in ["db/test_auth_cli.db", "db/test_crawler_cli.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass

    from backend.auth.db import get_auth_engine
    from backend.deps import get_job_manager

    get_auth_engine()
    get_job_manager()


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
    for db_file in ["db/test_auth_cli.db", "db/test_crawler_cli.db"]:
        for suffix in ["", "-shm", "-wal"]:
            target_file = db_file + suffix
            if os.path.exists(target_file):
                try:
                    os.remove(target_file)
                except OSError:
                    pass


# pylint: disable=too-many-locals, too-many-branches, too-many-statements
# pylint: disable=import-outside-toplevel, import-error, protected-access
# pylint: disable=subprocess-run-check, unspecified-encoding, multiple-statements
# pylint: disable=consider-using-with, unused-variable
def test_cli_full_flow() -> None:
    """
    執行端到端 (E2E) 整合測試與各核心組件的單元測試。

    此函數會按序執行以下測試步驟：
    1. 驗證雙 Client 機制下的 SSL 豁免網域邏輯。
    2. 驗證特定網域爬取延遲 (domain_delays) 的匹配算法。
    3. 驗證命令列環境變數 (CRAWLER_PROXY_URL 等) 的優先覆寫與配置合併邏輯。
    4. 啟動 Mock HTTP 測試伺服器。
    5. 執行無限制爬行任務，分析網頁並抓取外部連結寫入資料庫。
    6. 連線資料庫檢驗 Queue 狀態、外部連結數量與 HTTPS 安全標記的斷言。
    7. 測試 CLI 匯出與聚合篩選器功能（導出 CSV / JSON 與 --filter 篩選）。
    8. 測試任務生命週期管理（包括暫停、重置、繼續與刪除任務）。
    9. 執行限制條件爬行測試，驗證最大探索深度 (max_depth) 與頁數 (max_pages) 限制。

    Raises:
        AssertionError: 當斷言失敗時拋出。
        SystemExit: 當 CLI 子程序或腳本因錯誤異常終止時拋出。
    """
    print("=== [CI/CD E2E Test Suite] ===")

    # 1. 執行 Unit Test 驗證雙 Client 網域 SSL 豁免機制
    print("\nRunning Unit Test: SSL Exempt Domains Client Check...")
    from crawler.core import CrawlerCore
    from crawler.models import CrawlerConfig

    crawler_instance = CrawlerCore(config=CrawlerConfig(ssl_exempt_domains=["badssl.com", "self-signed.org"]))
    client_normal = crawler_instance._get_client("https://www.google.com")
    client_exempt = crawler_instance._get_client("https://badssl.com/index.html")
    client_exempt2 = crawler_instance._get_client("https://sub.self-signed.org/test")

    assert client_normal is crawler_instance.client, "Normal client should be the standard client"
    assert client_exempt is crawler_instance.exempt_client, "Exempted domain client should be the exempt client"
    assert client_exempt2 is crawler_instance.exempt_client, "Subdomain of exempted domain should be the exempt client"
    crawler_instance.close()
    print("Unit Test Passed: SSL Exempt Client check.")

    # 2. 執行 Unit Test 驗證 domain_delays 匹配邏輯
    print("\nRunning Unit Test: Domain Delays Matching...")
    from crawler.runner import _get_domain_delay

    domain_delays = {"example.com": 5.0, "sub.example.com": 10.0}
    assert _get_domain_delay("http://example.com/a", domain_delays, 3.0) == 5.0
    assert _get_domain_delay("http://sub.example.com/b", domain_delays, 3.0) == 10.0
    assert _get_domain_delay("http://another.example.com/c", domain_delays, 3.0) == 5.0
    assert _get_domain_delay("http://google.com/d", domain_delays, 3.0) == 3.0
    print("Unit Test Passed: Domain Delays Matching.")

    # 2.5 執行 Unit Test 驗證環境變數優先覆寫邏輯與設定合併
    print("\nRunning Unit Test: Config Merge and Environment Override...")
    from crawler.config_utils import merge_and_validate_crawler_config

    # 模擬環境變數
    os.environ["CRAWLER_PROXY_URL"] = "http://env-proxy:8080"
    os.environ["CRAWLER_SSL_EXEMPT_DOMAINS"] = "env-exempt.com, sub.env-exempt.org"

    global_cfg = {
        "crawler": {
            "timeout": 40,
            "delay": 4.0,
            "retries": 2,
            "proxy_url": "http://global-proxy:8080",
            "ssl_exempt_domains": ["global-exempt.com"],
        }
    }
    local_cfg = {
        "crawler": {
            "timeout": 50,
            "delay": 5.0,
            "retries": 3,
            "ssl_exempt_domains": ["local-exempt.com"],
        }
    }

    merged = merge_and_validate_crawler_config(local_cfg, global_cfg)

    # 斷言環境變數正確覆寫
    assert merged["proxy_url"] == "http://env-proxy:8080", (
        f"Proxy should be overridden by env, got {merged['proxy_url']}"
    )

    # 斷言 ssl_exempt_domains 包含全域、個別與環境變數之聯集
    exempt_set = set(merged["ssl_exempt_domains"])
    assert "global-exempt.com" in exempt_set, "global-exempt.com should be in exempt domains"
    assert "local-exempt.com" in exempt_set, "local-exempt.com should be in exempt domains"
    assert "env-exempt.com" in exempt_set, "env-exempt.com should be in exempt domains"
    assert "sub.env-exempt.org" in exempt_set, "sub.env-exempt.org should be in exempt domains"

    # 清理環境變數
    del os.environ["CRAWLER_PROXY_URL"]
    del os.environ["CRAWLER_SSL_EXEMPT_DOMAINS"]
    print("Unit Test Passed: Config Merge and Environment Override.")

    # 3. 檢查 port 是否已被佔用
    if is_port_in_use(PORT):
        print(f"Warning: Port {PORT} is already in use. Attempting to run anyway, but it might fail.")

    # 4. 啟動 Mock HTTP Server
    server_cmd = [sys.executable, "test/test_server/server.py", str(PORT)]
    print(f"Starting Mock Server: {' '.join(server_cmd)}")
    server_proc = subprocess.Popen(server_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

    try:
        # 等待伺服器就緒
        if not wait_for_server(PORT):
            print("Error: Mock Server failed to start or bind to port.")
            sys.exit(1)

        print("Mock Server is ready.")

        # 5. 執行第一個測試：無限制爬行，驗證功能正確性與 is_secure
        print("Setting up fresh test databases...")
        setup_databases()

        # 動態產生全域設定檔，允許更小的 timeout
        os.makedirs("config", exist_ok=True)
        TEST_GLOBAL_CONFIG = "config/test_global.yaml"
        with open(TEST_GLOBAL_CONFIG, "w", encoding="utf-8") as f:
            f.write("""\
crawler:
  min_timeout: 1
  min_connect_timeout: 0.1
  min_external_check_timeout: 0.1
""")

        # 動態產生主測試設定檔，確保 PORT 與最新欄位名稱正確
        os.makedirs("job", exist_ok=True)
        with open(YAML_CONFIG, "w", encoding="utf-8") as f:
            f.write(f"""\
start_url: "http://localhost:{PORT}/index.html"
target_domains:
  - "localhost"
trusted_domains:
  - "localhost"
crawler:
  retries: 0
  delay: 0.1
  timeout: 2
  social_domains:
    - "127.0.0.1"
""")

        # Allow local IPs for testing SSRF bypass
        os.environ["CRAWLER_ALLOW_LOCAL_IPS"] = "true"

        crawler_cmd = [sys.executable, "cli.py", "-g", TEST_GLOBAL_CONFIG, "-c", YAML_CONFIG]
        print(f"Running Crawler: {' '.join(crawler_cmd)}")
        crawler_proc = subprocess.run(crawler_cmd, capture_output=True, text=True)

        # 輸出爬蟲執行結果
        print("--- Crawler stdout ---")
        print(crawler_proc.stdout)
        if crawler_proc.stderr:
            print("--- Crawler stderr ---")
            print(crawler_proc.stderr)

        if crawler_proc.returncode != 0:
            print(f"Error: Crawler process exited with non-zero code {crawler_proc.returncode}")
            sys.exit(1)

        print("Crawler finished successfully.")

        # 6. 斷言驗證資料庫結果
        if not os.path.exists(DB_PATH):
            print(f"Error: Database file not created at {DB_PATH}")
            sys.exit(1)

        print("Connecting to database for validations...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # A. 驗證 Queue 狀態數量
        # completed: 6, skipped: 2, failed: 1
        cursor.execute("SELECT status, COUNT(*) FROM crawl_queue GROUP BY status")
        queue_stats = dict(cursor.fetchall())
        print(f"Queue Stats: {queue_stats}")

        assert queue_stats.get("completed", 0) == 6, f"Expected 6 completed urls, got {queue_stats.get('completed')}"
        assert queue_stats.get("skip", 0) == 2, f"Expected 2 skipped urls, got {queue_stats.get('skip')}"
        assert queue_stats.get("failed", 0) == 1, f"Expected 1 failed urls, got {queue_stats.get('failed')}"

        # B. 驗證外部連結與安全標記
        cursor.execute("SELECT target_url, ip_address, http_status_code, error_message, is_secure FROM external_links")
        external_links = cursor.fetchall()

        ext_dict = {}
        for target_url, ip, status_code, err, is_sec in external_links:
            ext_dict[target_url] = {
                "ip": ip,
                "status_code": status_code,
                "error": err,
                "is_secure": is_sec,
            }

        print(f"Found {len(ext_dict)} external links in DB.")
        assert len(ext_dict) == 11, f"Expected 11 external links, got {len(ext_dict)}"

        # 斷言 1: Google (應為 200, 且有 IP, is_secure 應為 1)
        google_url = "https://www.google.com"
        assert google_url in ext_dict, "Google link not found in DB"
        assert ext_dict[google_url]["status_code"] == 200, (
            f"Google status code should be 200, got {ext_dict[google_url]['status_code']}. "
            f"Error: {ext_dict[google_url]['error']}",
        )
        assert ext_dict[google_url]["ip"] is not None, "Google IP should not be None"
        assert ext_dict[google_url]["is_secure"] == 1, "Google is_secure should be 1 (True)"

        # 斷言 2: httpbin 404
        status_404_url = "https://httpbin.org/status/404"
        assert status_404_url in ext_dict, "httpbin 404 link not found in DB"
        s_code_404 = ext_dict[status_404_url]["status_code"]
        assert s_code_404 in (
            404,
            503,
            None,
        ), f"404 status should be 404, 503 or None, got {s_code_404}"
        if s_code_404 is None:
            assert ext_dict[status_404_url]["error"] is not None, (
                "Error message should not be None when status_code is None"
            )
        assert ext_dict[status_404_url]["is_secure"] == 1, "httpbin 404 is_secure should be 1"

        # 斷言 3: httpbin 500
        status_500_url = "https://httpbin.org/status/500"
        assert status_500_url in ext_dict, "httpbin 500 link not found in DB"
        s_code_500 = ext_dict[status_500_url]["status_code"]
        assert s_code_500 in (
            500,
            503,
            None,
        ), f"500 status should be 500, 503 or None, got {s_code_500}"
        if s_code_500 is None:
            assert ext_dict[status_500_url]["error"] is not None, (
                "Error message should not be None when status_code is None"
            )
        assert ext_dict[status_500_url]["is_secure"] == 1, "httpbin 500 is_secure should be 1"

        # 斷言 4: DNS 失敗連結
        dns_fail_url = "https://this-dns-does-not-exist-at-all-123456789.com"
        assert dns_fail_url in ext_dict, "DNS fail link not found in DB"
        assert ext_dict[dns_fail_url]["ip"] is None, (
            f"DNS fail link IP should be None, got {ext_dict[dns_fail_url]['ip']}"
        )
        assert ext_dict[dns_fail_url]["status_code"] is None, (
            f"DNS fail link status code should be None, got {ext_dict[dns_fail_url]['status_code']}"
        )
        assert ext_dict[dns_fail_url]["error"] is not None, "DNS fail link should have an error message"
        assert ext_dict[dns_fail_url]["is_secure"] == 1, "DNS fail link is_secure should be 1"

        # 斷言 5: neverssl.com (應為 HTTP, is_secure 應為 0)
        neverssl_url = "http://neverssl.com"
        assert neverssl_url in ext_dict, "neverssl.com link not found in DB"
        assert ext_dict[neverssl_url]["is_secure"] == 0, (
            f"neverssl.com is_secure should be 0 (False), got {ext_dict[neverssl_url]['is_secure']}"
        )

        # 斷言 6: mock-social-media (因 127.0.0.1 設為社群網域，HEAD 520 會觸發 GET 降級並取得 200)
        social_url = f"http://127.0.0.1:{PORT}/mock-social-media"
        assert social_url in ext_dict, "Mock social media link not found in DB"
        assert ext_dict[social_url]["is_secure"] == 0, "Mock social media is_secure should be 0"
        assert ext_dict[social_url]["status_code"] == 200, (
            f"Mock social media status_code should be 200, got {ext_dict[social_url]['status_code']}"
        )

        # 斷言 7: mock-non-social (127.0.0.2 非社群網域，HEAD 520 不會降級，狀態碼維持 520)
        non_social_url = f"http://127.0.0.2:{PORT}/mock-non-social"
        assert non_social_url in ext_dict, "Mock non-social link not found in DB"
        assert ext_dict[non_social_url]["status_code"] == 520, (
            f"Mock non-social status_code should be 520, got {ext_dict[non_social_url]['status_code']}"
        )

        # 新增外部資源類型斷言 (CSS Link)
        fonts_url = "https://fonts.googleapis.com/css?family=Roboto"
        assert fonts_url in ext_dict, "Fonts CSS link not found in DB"
        assert ext_dict[fonts_url]["is_secure"] == 1, "Fonts CSS link is_secure should be 1"

        # 新增外部資源類型斷言 (JS Script)
        analytics_url = "https://www.google-analytics.com/analytics.js"
        assert analytics_url in ext_dict, "Analytics JS link not found in DB"
        assert ext_dict[analytics_url]["is_secure"] == 1, "Analytics JS link is_secure should be 1"

        # 新增外部資源類型斷言 (Form action)
        form_url = "https://httpbin.org/post"
        assert form_url in ext_dict, "Form action link not found in DB"
        assert ext_dict[form_url]["is_secure"] == 1, "Form action link is_secure should be 1"

        # 新增外部資源類型斷言 (Img src)
        img_url = "https://example.com/broken-img.jpg"
        assert img_url in ext_dict, "Img src link not found in DB"
        assert ext_dict[img_url]["is_secure"] == 1, "Img src link is_secure should be 1"

        # C. 驗證聚合去重 (匯出測試，包含匯出 is_secure 驗證)
        print("Testing Export CLI with Grouping & JSON export...")
        export_file = "tmp_test_export.json"
        if os.path.exists(export_file):
            os.remove(export_file)

        # 找出剛剛的 Job ID
        cursor.execute("SELECT id FROM jobs LIMIT 1")
        job_id = cursor.fetchone()[0]

        export_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--group-by",
            "target",
            "--output",
            export_file,
        ]
        export_res = subprocess.run(export_cmd, capture_output=True, text=True)
        if export_res.returncode != 0:
            print(f"Error: Export CLI failed with code {export_res.returncode}")
            sys.exit(1)

        with open(export_file, "r") as f:
            export_data = json.load(f)

        # 尋找 httpbin 404 與 google
        found_grouped_404 = False
        found_grouped_google = False
        found_grouped_neverssl = False
        for item in export_data:
            if item["target_url"] == status_404_url:
                found_grouped_404 = True
                assert item["occurrence_count"] == 2, (
                    f"Expected 404 occurrence count to be 2, got {item['occurrence_count']}"
                )
                assert len(item["source_urls"]) == 2, "Expected 2 source urls for 404 link"
                assert f"http://localhost:{PORT}/index.html" in item["source_urls"], "Missing index.html source"
                assert f"http://localhost:{PORT}/page2.html" in item["source_urls"], "Missing page2.html source"
                assert item["is_secure"] is True, "404 is_secure in export should be True"
            elif item["target_url"] == google_url:
                found_grouped_google = True
                assert item["is_secure"] is True, "Google is_secure in export should be True"
            elif item["target_url"] == neverssl_url:
                found_grouped_neverssl = True
                assert item["is_secure"] is False, "neverssl.com is_secure in export should be False"

        assert found_grouped_404, "Grouped 404 not found in export"
        assert found_grouped_google, "Grouped Google not found in export"
        assert found_grouped_neverssl, "Grouped neverssl.com not found in export"

        # 清理暫存匯出檔案
        if os.path.exists(export_file):
            os.remove(export_file)

        conn.close()

        # =====================================================================
        # 6.5. 驗證 --filter 導出篩選器 (dead, broken, insecure)
        # =====================================================================
        print("\nRunning Verification: Export filters (--filter)...")

        # 測試 --filter dead
        dead_file = "tmp_dead.json"
        if os.path.exists(dead_file):
            os.remove(dead_file)
        export_dead_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--filter",
            "dead",
            "--output",
            dead_file,
        ]
        res_dead = subprocess.run(export_dead_cmd, capture_output=True, text=True)
        assert res_dead.returncode == 0, "Export with --filter dead failed"
        with open(dead_file, "r") as f:
            dead_data = json.load(f)
        assert len(dead_data) == 1, f"Expected 1 dead link, got {len(dead_data)}"
        assert dead_data[0]["target_url"] == "https://this-dns-does-not-exist-at-all-123456789.com", (
            "Dead link target mismatch"
        )
        os.remove(dead_file)

        # 測試 --filter broken
        broken_file = "tmp_broken.json"
        if os.path.exists(broken_file):
            os.remove(broken_file)
        export_broken_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--filter",
            "broken",
            "--output",
            broken_file,
        ]
        res_broken = subprocess.run(export_broken_cmd, capture_output=True, text=True)
        assert res_broken.returncode == 0, "Export with --filter broken failed"
        with open(broken_file, "r") as f:
            broken_data = json.load(f)

        # DEBUG: 印出所有 broken 網址
        print("--- Debug: Broken links found ---")
        for item in broken_data:
            print(
                f"URL: {item.get('target_url')}, "
                f"Code: {item.get('http_status_code')}, "
                f"IP: {item.get('ip_address')}, "
                f"Error: {item.get('error_message')}"
            )

        # 預期 broken 的外連共有 5 個（httpbin 404 x2, httpbin 500, broken-img, mock-non-social）
        # 排除 possibly flaky neverssl.com 連結 (若它連不上會被歸類為 broken)
        # 排除 httpbin.org/post 連結 (有時回傳 405 歸類為 blocked，有時 timeout 歸類為 broken)
        filtered_broken = [
            item
            for item in broken_data
            if item.get("target_url") not in ("http://neverssl.com", "https://httpbin.org/post")
        ]
        assert len(filtered_broken) == 5, (
            "Expected 5 broken links (excluding neverssl.com and httpbin.org/post), "
            f"got {len(filtered_broken)}: "
            f"{[x['target_url'] for x in filtered_broken]}"
        )
        os.remove(broken_file)

        # 測試 --filter insecure
        insecure_file = "tmp_insecure.json"
        if os.path.exists(insecure_file):
            os.remove(insecure_file)
        export_insecure_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--filter",
            "insecure",
            "--output",
            insecure_file,
        ]
        res_insecure = subprocess.run(export_insecure_cmd, capture_output=True, text=True)
        assert res_insecure.returncode == 0, "Export with --filter insecure failed"
        with open(insecure_file, "r") as f:
            insecure_data = json.load(f)
        assert len(insecure_data) >= 2, f"Expected at least 2 insecure links, got {len(insecure_data)}"
        assert all(item.get("is_secure") is False for item in insecure_data), (
            "All insecure links should have is_secure=False"
        )
        os.remove(insecure_file)

        # 測試 --exclude
        exclude_file = "tmp_exclude.json"
        if os.path.exists(exclude_file):
            os.remove(exclude_file)
        export_exclude_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--exclude",
            "google.com",
            "--output",
            exclude_file,
        ]
        res_exclude = subprocess.run(export_exclude_cmd, capture_output=True, text=True)
        assert res_exclude.returncode == 0, "Export with --exclude failed"
        with open(exclude_file, "r") as f:
            exclude_data = json.load(f)
        assert not any("google.com" in item.get("target_url") for item in exclude_data), (
            "Excluded domain should not be in export"
        )
        os.remove(exclude_file)

        # 測試 --export-full
        print("Testing Export CLI with Full Report (ZIP)...")
        full_zip_file = "tmp_full_report.zip"
        if os.path.exists(full_zip_file):
            os.remove(full_zip_file)
        export_full_cmd = [
            sys.executable,
            "cli.py",
            "--export-full",
            job_id,
            "--output",
            full_zip_file,
        ]
        res_full = subprocess.run(export_full_cmd, capture_output=True, text=True)
        assert res_full.returncode == 0, "Export full report failed"

        with zipfile.ZipFile(full_zip_file, "r") as zf:
            namelist = zf.namelist()
            assert any("crawl_records.csv" in n for n in namelist), "crawl_records.csv missing in ZIP"
            assert any("external_links.csv" in n for n in namelist), "external_links.csv missing in ZIP"

        os.remove(full_zip_file)

        print("Verification Passed: Export filters and internal report.")

        # =====================================================================
        # 6.6. 驗證任務生命週期管理指令 (--pause, --resume, --reset, --delete)
        # =====================================================================
        print("\nRunning Verification: Job Lifecycle Commands...")

        # A. 測試 --pause 非 running 任務 (此時狀態是 completed，應該不能暫停)
        pause_cmd = [sys.executable, "cli.py", "--pause", job_id]
        res_pause_fail = subprocess.run(pause_cmd, capture_output=True, text=True)
        # 因為不能暫停，所以 CLI 程序應 exit 1 回報操作未成功
        assert res_pause_fail.returncode == 1, "Pause CLI should exit with 1"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == "completed", "Job status should remain completed"
        conn_check.close()

        # B. 測試 --reset (重置任務)
        reset_cmd = [sys.executable, "cli.py", "--reset", job_id]
        res_reset = subprocess.run(reset_cmd, capture_output=True, text=True)
        assert res_reset.returncode == 0, "Reset CLI failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == "pending", "Job status should be reset to pending"

        cur_check.execute("SELECT COUNT(*) FROM external_links WHERE job_id = ?", (job_id,))
        assert cur_check.fetchone()[0] == 0, "External links should be cleared after reset"

        cur_check.execute("SELECT COUNT(*) FROM crawl_queue WHERE job_id = ?", (job_id,))
        # 重置後佇列應該只剩下 1 個 (即 start_url)
        assert cur_check.fetchone()[0] == 1, "Queue should only contain start URL after reset"
        conn_check.close()

        # C. 測試暫停與恢復爬行 (--pause & --resume)
        print("Resuming job in background...")
        resume_bg_cmd = [sys.executable, "cli.py", "--resume", job_id]
        bg_proc = subprocess.Popen(resume_bg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        # 等待 1.5 秒等它開始執行並鎖定在 running 狀態
        time.sleep(1.5)

        # 發送暫停指令
        print("Sending pause command...")
        res_pause = subprocess.run(pause_cmd, capture_output=True, text=True)
        if res_pause.returncode != 0:
            print("--- Pause CLI stdout ---")
            print(res_pause.stdout)
            print("--- Pause CLI stderr ---")
            print(res_pause.stderr)
            bg_proc.kill()
            bg_out, bg_err = bg_proc.communicate()
            print("--- Background Resume stdout ---")
            print(bg_out)
            print("--- Background Resume stderr ---")
            print(bg_err)

        assert res_pause.returncode == 0, f"Pause command failed with exit code {res_pause.returncode}"

        # 等待背景任務結束 (協同暫停)
        try:
            stdout_bg, stderr_bg = bg_proc.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            bg_proc.kill()
            stdout_bg, stderr_bg = bg_proc.communicate()

        if bg_proc.returncode != 0:
            print("--- Background Resume Completed with Non-zero Exit Code ---")
            print("stdout:", stdout_bg)
            print("stderr:", stderr_bg)

        assert bg_proc.returncode == 0, f"Background resume failed with code {bg_proc.returncode}"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == "paused", f"Expected job status to be paused, got {cur_check.fetchone()[0]}"
        conn_check.close()

        # 再次恢復爬行直到完畢
        print("Resuming job again to completion...")
        res_resume_final = subprocess.run(resume_bg_cmd, capture_output=True, text=True)
        assert res_resume_final.returncode == 0, "Final resume failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == "completed", "Job should be completed after resume"
        conn_check.close()

        # D. 測試 --delete (刪除任務)
        delete_cmd = [sys.executable, "cli.py", "--delete", job_id]
        res_delete = subprocess.run(delete_cmd, capture_output=True, text=True)
        assert res_delete.returncode == 0, "Delete CLI failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == 0, "Job record should be deleted"

        cur_check.execute("SELECT COUNT(*) FROM crawl_queue WHERE job_id = ?", (job_id,))
        assert cur_check.fetchone()[0] == 0, "Crawl queue should be cleared"

        cur_check.execute("SELECT COUNT(*) FROM external_links WHERE job_id = ?", (job_id,))
        assert cur_check.fetchone()[0] == 0, "External links should be cleared"
        conn_check.close()

        print("Verification Passed: Job Lifecycle Commands.")

        # 7. 執行第二個測試：驗證爬取限制功能 (max_depth=1, max_pages=3)
        print("\nRunning Limits Validation Job (max_depth=1, max_pages=3)...")
        setup_databases()

        limit_yaml = "job/test_limit_job.yaml"
        with open(limit_yaml, "w", encoding="utf-8") as f:
            f.write(f"""\
start_url: "http://localhost:{PORT}/index.html"
target_domains:
  - "localhost"
trusted_domains:
  - "localhost"
crawler:
  retries: 0
  delay: 0.1
  timeout: 2
  max_depth: 1
  max_pages: 3
""")

        limit_crawler_cmd = [sys.executable, "cli.py", "-g", TEST_GLOBAL_CONFIG, "-c", limit_yaml]
        print(f"Running Limit Crawler: {' '.join(limit_crawler_cmd)}")
        limit_proc = subprocess.run(limit_crawler_cmd, capture_output=True, text=True)
        print("--- Limit Crawler stdout ---")
        print(limit_proc.stdout)
        if limit_proc.stderr:
            print("--- Limit Crawler stderr ---")
            print(limit_proc.stderr)

        assert limit_proc.returncode == 0, f"Limit crawler failed with exit code {limit_proc.returncode}"

        # 連線資料庫驗證深度與頁數限制
        conn_lim = sqlite3.connect(DB_PATH)
        cur_lim = conn_lim.cursor()

        # A. 斷言 max_depth=1: 深度為 2 的 relative-link.html 不應在佇列中
        cur_lim.execute("SELECT COUNT(*) FROM crawl_queue WHERE url LIKE '%relative-link.html'")
        rel_count = cur_lim.fetchone()[0]
        assert rel_count == 0, (
            f"relative-link.html (depth 2) should NOT exist in queue when max_depth=1, got {rel_count}"
        )

        # B. 斷言 max_pages=3: completed / failed / skip-with-code 的實質請求網頁數量應恰為 3
        cur_lim.execute("""
            SELECT COUNT(*) FROM crawl_queue 
            WHERE status IN ('completed', 'failed', 'warning') 
               OR (status = 'skip' AND status_code IS NOT NULL)
        """)
        total_pages_crawled = cur_lim.fetchone()[0]
        assert total_pages_crawled == 3, (
            f"Total crawled pages should be exactly 3 when max_pages=3, got {total_pages_crawled}"
        )

        conn_lim.close()
        print("Limits Validation Job Passed Successfully!")

        # =====================================================================
        # 8. 執行進階測試：失敗重試 (Flaky) 與 Tarpit 防禦 (Timeout)
        # =====================================================================
        print("\nRunning Advanced Validation: Flaky Retry and Tarpit Defense...")
        import urllib.request
        import urllib.error

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/reset_flaky").read()
        except (urllib.error.URLError, OSError):
            pass

        setup_databases()

        advanced_yaml = "job/test_advanced_job.yaml"
        with open(advanced_yaml, "w", encoding="utf-8") as f:
            f.write(f"""\
start_url: "http://127.0.0.1:{PORT}/advanced_test"
target_domains:
  - "127.0.0.1"
trusted_domains:
  - "127.0.0.1"
crawler:
  retries: 0
  delay: 0.1
  timeout: 2
  connect_timeout: 1.0
  external_check_timeout: 1.0
""")

        advanced_cmd = [sys.executable, "cli.py", "-g", TEST_GLOBAL_CONFIG, "-c", advanced_yaml]
        print(f"Running Advanced Crawler: {' '.join(advanced_cmd)}")
        adv_proc = subprocess.run(advanced_cmd, capture_output=True, text=True)
        print("--- Advanced Crawler stdout ---")
        print(adv_proc.stdout)
        if adv_proc.stderr:
            print("--- Advanced Crawler stderr ---")
            print(adv_proc.stderr)

        assert adv_proc.returncode == 0, f"Advanced crawler failed with exit code {adv_proc.returncode}"

        conn_adv = sqlite3.connect(DB_PATH)
        cur_adv = conn_adv.cursor()

        # 取得 job_id
        cur_adv.execute("SELECT id FROM jobs LIMIT 1")
        adv_job_id = cur_adv.fetchone()[0]

        # 斷言 A: Tarpit 外連被正確標記為超時錯誤
        cur_adv.execute("SELECT http_status_code, error_message FROM external_links WHERE target_url LIKE '%/tarpit'")
        tarpit_res = cur_adv.fetchone()
        assert tarpit_res is not None, "Tarpit link should be recorded"
        assert tarpit_res[0] is None, "Tarpit link should have no status code due to timeout"
        assert tarpit_res[1] is not None and (
            "timeout" in tarpit_res[1].lower() or "timed out" in tarpit_res[1].lower()
        ), f"Tarpit link should timeout, got error: {tarpit_res[1]}"

        # 斷言 B: flaky_internal 爬取失敗 (因為 retries=0)
        cur_adv.execute("SELECT status FROM crawl_queue WHERE url LIKE '%/flaky_internal'")
        flaky_status = cur_adv.fetchone()
        assert flaky_status is not None, "Flaky internal page should be in queue"
        assert flaky_status[0] == "failed", (
            f"Flaky internal page status should be failed on first try, got {flaky_status[0]}"
        )

        # 觸發 --retry-failed 指令
        print("Retrying failed internal pages...")
        retry_cmd = [sys.executable, "cli.py", "--retry-failed", adv_job_id]
        subprocess.run(retry_cmd, capture_output=True, text=True, check=True)

        # 斷言 C: 狀態已被重置為 pending，接著恢復執行
        cur_adv.execute("SELECT status FROM crawl_queue WHERE url LIKE '%/flaky_internal'")
        assert cur_adv.fetchone()[0] == "pending", "Flaky internal page status should be reset to pending"

        print("Resuming advanced job to process retried pages...")
        resume_adv_cmd = [sys.executable, "cli.py", "--resume", adv_job_id]
        subprocess.run(resume_adv_cmd, capture_output=True, text=True, check=True)

        # 斷言 D: flaky_internal 這次成功了 (completed)，並且發現了裡面的 external link
        cur_adv.execute("SELECT status FROM crawl_queue WHERE url LIKE '%/flaky_internal'")
        assert cur_adv.fetchone()[0] == "completed", "Flaky internal page should be completed after retry"

        cur_adv.execute("SELECT target_url FROM external_links WHERE target_url = 'https://www.example.com'")
        assert cur_adv.fetchone() is not None, "External link from flaky page should be found after retry"

        conn_adv.close()
        if os.path.exists(advanced_yaml):
            os.remove(advanced_yaml)
        print("Advanced Validation (Tarpit & Flaky) Passed Successfully!")

        # 清理測試過程中動態產生的設定檔，保持工作目錄乾淨
        if os.path.exists(YAML_CONFIG):
            os.remove(YAML_CONFIG)
        if os.path.exists("job/test_limit_job.yaml"):
            os.remove("job/test_limit_job.yaml")
        if os.path.exists(TEST_GLOBAL_CONFIG):
            os.remove(TEST_GLOBAL_CONFIG)

        print("All CLI Integration Tests Passed Successfully!")

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
