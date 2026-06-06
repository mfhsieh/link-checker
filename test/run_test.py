#!/usr/bin/env python3
"""
E2E integration test script for external link checker.
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PORT = 8000
DB_PATH = "db/crawler.db"
YAML_CONFIG = "job/test_job.yaml"


def is_port_in_use(port: int) -> bool:
    """
    檢查指定的 TCP 通訊埠 (Port) 是否已被本地端佔用。

    Args:
        port (int): 欲檢查的 TCP 通訊埠號碼。

    Returns:
        bool: 若已被佔用回傳 True，否則回傳 False。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """
    循環等待指定的 TCP 伺服器就緒並成功綁定通訊埠。

    Args:
        port (int): 伺服器所監聽的 TCP 通訊埠。
        timeout (float): 最長等待超時時間（秒），預設為 5 秒。

    Returns:
        bool: 若伺服器在限時內啟動成功並就緒回傳 True，否則回傳 False。
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.1)
    return False


# pylint: disable=too-many-locals, too-many-branches, too-many-statements, line-too-long
# pylint: disable=import-outside-toplevel, import-error, protected-access
# pylint: disable=subprocess-run-check, unspecified-encoding, multiple-statements
# pylint: disable=consider-using-with, unused-variable, broad-exception-caught
def run_test() -> None:
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
    """
    print("=== [CI/CD E2E Test Suite] ===")

    # 1. 執行 Unit Test 驗證雙 Client 網域 SSL 豁免機制
    print("\nRunning Unit Test: SSL Exempt Domains Client Check...")
    from crawler.core import CrawlerCore

    crawler_instance = CrawlerCore(ssl_exempt_domains=["badssl.com", "self-signed.org"])
    client_normal = crawler_instance._get_client("https://www.google.com")
    client_exempt = crawler_instance._get_client("https://badssl.com/index.html")
    client_exempt2 = crawler_instance._get_client("https://sub.self-signed.org/test")

    assert (
        client_normal is crawler_instance.client
    ), "Normal client should be the standard client"
    assert (
        client_exempt is crawler_instance.exempt_client
    ), "Exempted domain client should be the exempt client"
    assert (
        client_exempt2 is crawler_instance.exempt_client
    ), "Subdomain of exempted domain should be the exempt client"
    crawler_instance.close()
    print("Unit Test Passed: SSL Exempt Client check.")

    # 2. 執行 Unit Test 驗證 domain_delays 匹配邏輯
    print("\nRunning Unit Test: Domain Delays Matching...")
    from crawler.manager import _get_domain_delay

    domain_delays = {"example.com": 5.0, "sub.example.com": 10.0}
    assert _get_domain_delay("http://example.com/a", domain_delays, 3.0) == 5.0
    assert _get_domain_delay("http://sub.example.com/b", domain_delays, 3.0) == 10.0
    assert _get_domain_delay("http://another.example.com/c", domain_delays, 3.0) == 5.0
    assert _get_domain_delay("http://google.com/d", domain_delays, 3.0) == 3.0
    print("Unit Test Passed: Domain Delays Matching.")

    # 2.5 執行 Unit Test 驗證環境變數優先覆寫邏輯與設定合併
    print("\nRunning Unit Test: Config Merge and Environment Override...")
    from cli import merge_and_validate_crawler_config

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
    assert (
        merged["proxy_url"] == "http://env-proxy:8080"
    ), f"Proxy should be overridden by env, got {merged['proxy_url']}"

    # 斷言 ssl_exempt_domains 包含全域、個別與環境變數之聯集
    exempt_set = set(merged["ssl_exempt_domains"])
    assert (
        "global-exempt.com" in exempt_set
    ), "global-exempt.com should be in exempt domains"
    assert (
        "local-exempt.com" in exempt_set
    ), "local-exempt.com should be in exempt domains"
    assert "env-exempt.com" in exempt_set, "env-exempt.com should be in exempt domains"
    assert (
        "sub.env-exempt.org" in exempt_set
    ), "sub.env-exempt.org should be in exempt domains"

    # 清理環境變數
    del os.environ["CRAWLER_PROXY_URL"]
    del os.environ["CRAWLER_SSL_EXEMPT_DOMAINS"]
    print("Unit Test Passed: Config Merge and Environment Override.")

    # 3. 檢查 port 是否已被佔用
    if is_port_in_use(PORT):
        print(
            f"Warning: Port {PORT} is already in use. Attempting to run anyway, but it might fail."
        )

    # 4. 啟動 Mock HTTP Server
    server_cmd = [sys.executable, "test/test_server/server.py", str(PORT)]
    print(f"Starting Mock Server: {' '.join(server_cmd)}")
    server_proc = subprocess.Popen(
        server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    try:
        # 等待伺服器就緒
        if not wait_for_server(PORT):
            print("Error: Mock Server failed to start or bind to port.")
            # 輸出伺服器的錯誤日誌
            stdout, stderr = server_proc.communicate(timeout=1)
            print(f"Server stderr:\n{stderr}")
            sys.exit(1)

        print("Mock Server is ready.")

        # 5. 執行第一個測試：無限制爬行，驗證功能正確性與 is_secure
        if os.path.exists(DB_PATH):
            print(f"Removing old database: {DB_PATH}")
            os.remove(DB_PATH)

        crawler_cmd = [sys.executable, "cli.py", "-c", YAML_CONFIG]
        print(f"Running Crawler: {' '.join(crawler_cmd)}")
        crawler_proc = subprocess.run(crawler_cmd, capture_output=True, text=True)

        # 輸出爬蟲執行結果
        print("--- Crawler stdout ---")
        print(crawler_proc.stdout)
        if crawler_proc.stderr:
            print("--- Crawler stderr ---")
            print(crawler_proc.stderr)

        if crawler_proc.returncode != 0:
            print(
                f"Error: Crawler process exited with non-zero code {crawler_proc.returncode}"
            )
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

        assert (
            queue_stats.get("completed", 0) == 6
        ), f"Expected 6 completed urls, got {queue_stats.get('completed')}"
        assert (
            queue_stats.get("skip", 0) == 2
        ), f"Expected 2 skipped urls, got {queue_stats.get('skip')}"
        assert (
            queue_stats.get("failed", 0) == 1
        ), f"Expected 1 failed urls, got {queue_stats.get('failed')}"

        # B. 驗證外部連結與安全標記
        cursor.execute(
            "SELECT target_url, ip_address, http_status_code, error_message, is_secure FROM external_links"
        )
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
        assert len(ext_dict) == 9, f"Expected 9 external links, got {len(ext_dict)}"

        # 斷言 1: Google (應為 200, 且有 IP, is_secure 應為 1)
        google_url = "https://www.google.com"
        assert google_url in ext_dict, "Google link not found in DB"
        assert (
            ext_dict[google_url]["status_code"] == 200
        ), f"Google status code should be 200, got {ext_dict[google_url]['status_code']}"
        assert ext_dict[google_url]["ip"] is not None, "Google IP should not be None"
        assert (
            ext_dict[google_url]["is_secure"] == 1
        ), "Google is_secure should be 1 (True)"

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
            assert (
                ext_dict[status_404_url]["error"] is not None
            ), "Error message should not be None when status_code is None"
        assert (
            ext_dict[status_404_url]["is_secure"] == 1
        ), "httpbin 404 is_secure should be 1"

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
            assert (
                ext_dict[status_500_url]["error"] is not None
            ), "Error message should not be None when status_code is None"
        assert (
            ext_dict[status_500_url]["is_secure"] == 1
        ), "httpbin 500 is_secure should be 1"

        # 斷言 4: DNS 失敗連結
        dns_fail_url = "https://this-dns-does-not-exist-at-all-123456789.com"
        assert dns_fail_url in ext_dict, "DNS fail link not found in DB"
        assert (
            ext_dict[dns_fail_url]["ip"] is None
        ), f"DNS fail link IP should be None, got {ext_dict[dns_fail_url]['ip']}"
        assert (
            ext_dict[dns_fail_url]["status_code"] is None
        ), f"DNS fail link status code should be None, got {ext_dict[dns_fail_url]['status_code']}"
        assert (
            ext_dict[dns_fail_url]["error"] is not None
        ), "DNS fail link should have an error message"
        assert (
            ext_dict[dns_fail_url]["is_secure"] == 1
        ), "DNS fail link is_secure should be 1"

        # 斷言 5: neverssl.com (應為 HTTP, is_secure 應為 0)
        neverssl_url = "http://neverssl.com"
        assert neverssl_url in ext_dict, "neverssl.com link not found in DB"
        assert (
            ext_dict[neverssl_url]["is_secure"] == 0
        ), f"neverssl.com is_secure should be 0 (False), got {ext_dict[neverssl_url]['is_secure']}"

        # 新增外部資源類型斷言 (CSS Link)
        fonts_url = "https://fonts.googleapis.com/css?family=Roboto"
        assert fonts_url in ext_dict, "Fonts CSS link not found in DB"
        assert (
            ext_dict[fonts_url]["is_secure"] == 1
        ), "Fonts CSS link is_secure should be 1"

        # 新增外部資源類型斷言 (JS Script)
        analytics_url = "https://www.google-analytics.com/analytics.js"
        assert analytics_url in ext_dict, "Analytics JS link not found in DB"
        assert (
            ext_dict[analytics_url]["is_secure"] == 1
        ), "Analytics JS link is_secure should be 1"

        # 新增外部資源類型斷言 (Form action)
        form_url = "https://httpbin.org/post"
        assert form_url in ext_dict, "Form action link not found in DB"
        assert (
            ext_dict[form_url]["is_secure"] == 1
        ), "Form action link is_secure should be 1"

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
            "--group",
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
                assert (
                    item["occurrence_count"] == 2
                ), f"Expected 404 occurrence count to be 2, got {item['occurrence_count']}"
                assert (
                    len(item["source_urls"]) == 2
                ), "Expected 2 source urls for 404 link"
                assert (
                    "http://localhost:8000/index.html" in item["source_urls"]
                ), "Missing index.html source"
                assert (
                    "http://localhost:8000/page2.html" in item["source_urls"]
                ), "Missing page2.html source"
                assert (
                    item["is_secure"] is True
                ), "404 is_secure in export should be True"
            elif item["target_url"] == google_url:
                found_grouped_google = True
                assert (
                    item["is_secure"] is True
                ), "Google is_secure in export should be True"
            elif item["target_url"] == neverssl_url:
                found_grouped_neverssl = True
                assert (
                    item["is_secure"] is False
                ), "neverssl.com is_secure in export should be False"

        assert found_grouped_404, "Grouped 404 not found in export"
        assert found_grouped_google, "Grouped Google not found in export"
        assert found_grouped_neverssl, "Grouped neverssl.com not found in export"

        # 清理暫存匯出檔案
        if os.path.exists(export_file):
            os.remove(export_file)

        conn.close()

        # =====================================================================
        # 6.5. 驗證 --filter 導出篩選器 (dead, broken, unapproved)
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
        assert (
            dead_data[0]["target_url"]
            == "https://this-dns-does-not-exist-at-all-123456789.com"
        ), "Dead link target mismatch"
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
                f"URL: {item.get('target_url')}, Code: {item.get('http_status_code')}, IP: {item.get('ip_address')}, Error: {item.get('error_message')}"
            )

        # 預期非 200 的外連共有 6 個（httpbin 404 x2, httpbin 500, httpbin post, broken-img, dns fail）
        # 排除 possibly flaky neverssl.com 連結 (若它連不上會被歸類為 broken)
        filtered_broken = [
            item
            for item in broken_data
            if item.get("target_url") != "http://neverssl.com"
        ]
        assert (
            len(filtered_broken) == 6
        ), f"Expected 6 broken links (excluding neverssl.com), got {len(filtered_broken)}: {[x['target_url'] for x in filtered_broken]}"
        os.remove(broken_file)

        # 測試 --filter unapproved
        unapproved_file = "tmp_unapproved.json"
        if os.path.exists(unapproved_file):
            os.remove(unapproved_file)
        export_unapproved_cmd = [
            sys.executable,
            "cli.py",
            "--export",
            job_id,
            "--json",
            "--filter",
            "unapproved",
            "--output",
            unapproved_file,
        ]
        res_unapproved = subprocess.run(
            export_unapproved_cmd, capture_output=True, text=True
        )
        assert res_unapproved.returncode == 0, "Export with --filter unapproved failed"
        with open(unapproved_file, "r") as f:
            unapproved_data = json.load(f)
        # 預期不屬於白名單的外連有 9 個 (因為 config_global.yaml 的白名單已被註解)
        assert (
            len(unapproved_data) == 9
        ), f"Expected 9 unapproved links, got {len(unapproved_data)}"
        os.remove(unapproved_file)
        print("Verification Passed: Export filters.")

        # =====================================================================
        # 6.6. 驗證任務生命週期管理指令 (--pause, --resume, --reset, --delete)
        # =====================================================================
        print("\nRunning Verification: Job Lifecycle Commands...")

        # A. 測試 --pause 非 running 任務 (此時狀態是 completed，應該不能暫停)
        pause_cmd = [sys.executable, "cli.py", "--pause", job_id]
        res_pause_fail = subprocess.run(pause_cmd, capture_output=True, text=True)
        # 雖然不能暫停，但 CLI 程序應該仍是 exit 0，只是會顯示警告且狀態不變
        assert res_pause_fail.returncode == 0, "Pause CLI should exit with 0"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert (
            cur_check.fetchone()[0] == "completed"
        ), "Job status should remain completed"
        conn_check.close()

        # B. 測試 --reset (重置任務)
        reset_cmd = [sys.executable, "cli.py", "--reset", job_id]
        res_reset = subprocess.run(reset_cmd, capture_output=True, text=True)
        assert res_reset.returncode == 0, "Reset CLI failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert (
            cur_check.fetchone()[0] == "pending"
        ), "Job status should be reset to pending"

        cur_check.execute(
            "SELECT COUNT(*) FROM external_links WHERE job_id = ?", (job_id,)
        )
        assert (
            cur_check.fetchone()[0] == 0
        ), "External links should be cleared after reset"

        cur_check.execute(
            "SELECT COUNT(*) FROM crawl_queue WHERE job_id = ?", (job_id,)
        )
        # 重置後佇列應該只剩下 1 個 (即 start_url)
        assert (
            cur_check.fetchone()[0] == 1
        ), "Queue should only contain start URL after reset"
        conn_check.close()

        # C. 測試暫停與恢復爬行 (--pause & --resume)
        print("Resuming job in background...")
        resume_bg_cmd = [sys.executable, "cli.py", "--resume", job_id]
        bg_proc = subprocess.Popen(
            resume_bg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

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

        assert (
            res_pause.returncode == 0
        ), f"Pause command failed with exit code {res_pause.returncode}"

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

        assert (
            bg_proc.returncode == 0
        ), f"Background resume failed with code {bg_proc.returncode}"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert (
            cur_check.fetchone()[0] == "paused"
        ), f"Expected job status to be paused, got {cur_check.fetchone()[0]}"
        conn_check.close()

        # 再次恢復爬行直到完畢
        print("Resuming job again to completion...")
        res_resume_final = subprocess.run(resume_bg_cmd, capture_output=True, text=True)
        assert res_resume_final.returncode == 0, "Final resume failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert (
            cur_check.fetchone()[0] == "completed"
        ), "Job should be completed after resume"
        conn_check.close()

        # D. 測試 --delete (刪除任務)
        delete_cmd = [sys.executable, "cli.py", "--delete", job_id]
        res_delete = subprocess.run(delete_cmd, capture_output=True, text=True)
        assert res_delete.returncode == 0, "Delete CLI failed"

        conn_check = sqlite3.connect(DB_PATH)
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", (job_id,))
        assert cur_check.fetchone()[0] == 0, "Job record should be deleted"

        cur_check.execute(
            "SELECT COUNT(*) FROM crawl_queue WHERE job_id = ?", (job_id,)
        )
        assert cur_check.fetchone()[0] == 0, "Crawl queue should be cleared"

        cur_check.execute(
            "SELECT COUNT(*) FROM external_links WHERE job_id = ?", (job_id,)
        )
        assert cur_check.fetchone()[0] == 0, "External links should be cleared"
        conn_check.close()

        print("Verification Passed: Job Lifecycle Commands.")

        # 7. 執行第二個測試：驗證爬取限制功能 (max_depth=1, max_pages=3)
        print("\nRunning Limits Validation Job (max_depth=1, max_pages=3)...")
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

        limit_crawler_cmd = [sys.executable, "cli.py", "-c", "test_limit_job.yaml"]
        print(f"Running Limit Crawler: {' '.join(limit_crawler_cmd)}")
        limit_proc = subprocess.run(limit_crawler_cmd, capture_output=True, text=True)
        print("--- Limit Crawler stdout ---")
        print(limit_proc.stdout)
        if limit_proc.stderr:
            print("--- Limit Crawler stderr ---")
            print(limit_proc.stderr)

        assert (
            limit_proc.returncode == 0
        ), f"Limit crawler failed with exit code {limit_proc.returncode}"

        # 連線資料庫驗證深度與頁數限制
        conn_lim = sqlite3.connect(DB_PATH)
        cur_lim = conn_lim.cursor()

        # A. 斷言 max_depth=1: 深度為 2 的 relative-link.html 不應在佇列中
        cur_lim.execute(
            "SELECT COUNT(*) FROM crawl_queue WHERE url LIKE '%relative-link.html'"
        )
        rel_count = cur_lim.fetchone()[0]
        assert (
            rel_count == 0
        ), f"relative-link.html (depth 2) should NOT exist in queue when max_depth=1, got {rel_count}"

        # B. 斷言 max_pages=3: completed / failed / skip-with-code 的實質請求網頁數量應恰為 3
        cur_lim.execute("""
            SELECT COUNT(*) FROM crawl_queue 
            WHERE status IN ('completed', 'failed') 
               OR (status = 'skip' AND status_code IS NOT NULL)
        """)
        total_pages_crawled = cur_lim.fetchone()[0]
        assert (
            total_pages_crawled == 3
        ), f"Total crawled pages should be exactly 3 when max_pages=3, got {total_pages_crawled}"

        conn_lim.close()
        print("Limits Validation Job Passed Successfully!")

        print("\n=== All E2E Assertions Passed! Test SUCCESS ===")
        sys.exit(0)

    except AssertionError as ae:
        print(f"\n=== Validation AssertionError: {ae} ===")
        sys.exit(1)
    except Exception as e:
        print(f"\n=== Test Runner Error: {e} ===")
        sys.exit(1)
    finally:
        print("Terminating Mock Server process...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=2)
            print("Mock Server process terminated.")
        except subprocess.TimeoutExpired:
            server_proc.kill()
            print("Mock Server process killed.")


if __name__ == "__main__":
    run_test()
