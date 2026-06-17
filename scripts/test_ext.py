"""
單一外部連結存活測試腳本。

此腳本用於在終端機中快速測試特定外部連結的存活狀態，
直接印出 HTTP 狀態碼與錯誤訊息，方便開發除錯與驗證。
"""

import argparse
import os
import sys

# 加入專案根目錄到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position,import-error
from crawler.core import CrawlerCore
from scripts.test_url import get_test_crawler_config


def main() -> None:
    """
    解析命令列參數，並針對目標外部連結進行存活探測。

    Raises:
        SystemExit: 當命令列參數解析錯誤或缺少必填參數時拋出。
    """
    parser = argparse.ArgumentParser(description="測試單一外部連結存活狀態")
    parser.add_argument("url", help="欲測試的外部連結網址")
    parser.add_argument(
        "--disable-social", action="store_true", help="停用社群網域降級探測機制 (不套用 social_domains)"
    )
    parser.add_argument(
        "-g", "--global-config", type=str, default="config/config_global.yaml", help="全域 YAML 設定檔的路徑"
    )
    args = parser.parse_args()

    # 1. 準備需要覆寫的個別參數
    user_config_overrides = {}
    if args.disable_social:
        user_config_overrides["social_domains"] = []

    # 2. 取得合併後的設定實例
    config = get_test_crawler_config(args.global_config, user_config_overrides)

    core = CrawlerCore(config)
    print(f"[*] 開始測試外部連結: {args.url}")

    # check_external_link 回傳: (status_code, error_msg)
    status_code, error_msg = core.check_external_link(args.url)

    if status_code is not None and status_code < 400:
        print(f"[+] 測試成功 (Healthy)！狀態碼: {status_code}")
    else:
        print(f"[-] 測試失敗或異常 (Broken/Dead)。狀態碼: {status_code}")
        # pylint: disable=duplicate-code
        if error_msg:
            print(f"    - 錯誤訊息: {error_msg}")

    core.close()


if __name__ == "__main__":
    main()
