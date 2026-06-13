"""
單一頁面爬取測試腳本。

此腳本用於在終端機中快速測試特定網址，並限定爬取深度與頁數為 1，
直接印出爬取結果，方便開發除錯與驗證。
"""

import argparse
import os
import sys

# 加入專案根目錄到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position,import-error
from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig


def main() -> None:
    """
    解析命令列參數，並針對目標網址進行單次頁面爬取測試。
    """
    parser = argparse.ArgumentParser(description="測試單一頁面爬取 (限定 1 頁)")
    parser.add_argument("url", help="欲爬取的目標網址")
    args = parser.parse_args()

    # 設定 crawler config
    config = CrawlerConfig(timeout=10, connect_timeout=5.0)

    core = CrawlerCore(config)
    print(f"[*] 開始爬取單一頁面: {args.url}")

    # process_url 回傳: (internal_links, external_links, status_code, error_msg, is_html, redirect_url)
    internal_links, external_links, status_code, error_msg, _is_html, _redirect = core.process_url(
        args.url, target_domains=[], trusted_domains=[]
    )

    if status_code == 200:
        print(f"[+] 爬取成功！狀態碼: {status_code}")
        print(f"    - 內部連結數量: {len(internal_links)}")
        print(f"    - 外部連結數量: {len(external_links)}")

        print("\n[外部連結預覽 (最多顯示 10 筆)]")
        for link in external_links[:10]:
            print(f"  - {link}")
    else:
        print(f"[-] 爬取失敗或異常。狀態碼: {status_code}")
        print(f"    - 錯誤訊息: {error_msg}")


if __name__ == "__main__":
    main()
