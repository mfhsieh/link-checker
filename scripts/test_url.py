"""
單一頁面爬取測試腳本。

此模組提供在終端機中快速測試特定網址的命令列工具，
限定爬取深度與頁數為 1，並直接印出內部與外部連結的爬取結果。
它使用核心的 ``CrawlerCore`` 進行單頁面解析，方便開發除錯與驗證。
"""
# pylint: disable=duplicate-code

import argparse
import json
import logging
import os
import sys
from typing import cast
from urllib.parse import urlparse

import yaml

# 將專案路徑加入 path 以便引用 crawler
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position
from crawler.config_utils import merge_and_validate_crawler_config
from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig

# pylint: enable=wrong-import-position


def get_test_crawler_config(
    global_config_path: str, user_config_overrides: dict[str, object] | None = None
) -> CrawlerConfig:
    """
    讀取全域設定檔並合併個別任務設定，產生測試用的 CrawlerConfig 實例。

    此函式會嘗試讀取指定路徑的 YAML 全域設定，並與預設的測試參數以及使用者提供的
    覆寫參數進行合併，最後透過 `merge_and_validate_crawler_config` 驗證後轉換為
    強型別的 `CrawlerConfig` 物件。

    Args:
        global_config_path (str): 全域設定檔 (.yaml) 的檔案路徑。
        user_config_overrides (dict[str, object] | None): 欲額外覆寫或新增的爬蟲設定項目。

    Returns:
        CrawlerConfig: 最終用於測試的爬蟲配置實例。
    """
    global_config: dict[str, object] = {}
    if os.path.exists(global_config_path):
        try:
            with open(global_config_path, "r", encoding="utf-8") as f:
                global_config = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            print(f"[!] 讀取全域設定檔發生錯誤: {e}")

    user_config: dict[str, object] = {
        "timeout": 10,
        "connect_timeout": 5.0,
        "external_check_timeout": 10.0,
    }
    if user_config_overrides:
        user_config.update(user_config_overrides)

    final_cfg = merge_and_validate_crawler_config({"crawler": user_config}, global_config)

    return CrawlerConfig(
        timeout=int(float(str(final_cfg.get("timeout", 10)))),
        connect_timeout=float(str(final_cfg.get("connect_timeout", 5.0))),
        external_check_timeout=float(str(final_cfg.get("external_check_timeout", 10.0))),
        social_domains=cast(list[str], final_cfg.get("social_domains", []))
        if isinstance(final_cfg.get("social_domains"), list)
        else [],
        user_agent=str(final_cfg["user_agent"]) if final_cfg.get("user_agent") else None,
        proxy_url=str(final_cfg["proxy_url"]) if final_cfg.get("proxy_url") else None,
        ssl_exempt_domains=cast(list[str], final_cfg.get("ssl_exempt_domains", []))
        if isinstance(final_cfg.get("ssl_exempt_domains"), list)
        else [],
        ignore_extensions=cast(list[str], final_cfg.get("ignore_extensions", []))
        if isinstance(final_cfg.get("ignore_extensions"), list)
        else [],
        ignore_regexes=cast(list[str], final_cfg.get("ignore_regexes", []))
        if isinstance(final_cfg.get("ignore_regexes"), list)
        else [],
        mime_type_filter=cast(dict[str, object], final_cfg.get("mime_type_filter", {}))
        if isinstance(final_cfg.get("mime_type_filter"), dict)
        else {"enabled": True, "allowed_types": ["text/html", "application/xhtml+xml"]},
    )


def main() -> None:
    """
    解析命令列參數，並針對目標網址進行單次頁面爬取測試。

    利用 argparse 接收指定的 URL 與選填參數，實例化 CrawlerCore 並進行單頁解析，
    最終將內部連結、外部連結與 HTTP 狀態印出至標準輸出 (stdout)。
    支援以純文字或 JSON 格式輸出，方便與其他工具或 MCP 整合。

    Raises:
        SystemExit: 當命令列參數解析錯誤、缺少必填參數或是使用者要求顯示說明 (--help) 時拋出。
    """
    parser = argparse.ArgumentParser(description="測試單一頁面爬取 (限定 1 頁)")
    parser.add_argument("url", help="欲爬取的目標網址")
    parser.add_argument(
        "-g", "--global-config", type=str, default="config/config_global.yaml", help="全域 YAML 設定檔的路徑"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="啟用除錯模式，顯示底層爬蟲的詳細處理日誌")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式輸出結果 (供程式或 MCP 介接使用)")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    # 1. 取得合併後的設定實例
    config = get_test_crawler_config(args.global_config)

    core = CrawlerCore(config)
    if not args.json:
        print(f"[*] 開始爬取單一頁面: {args.url}")

    parsed_url = urlparse(args.url)
    target_domains = [parsed_url.netloc] if parsed_url.netloc else []

    # process_url 回傳: (internal_links, external_target_links, status_code, status, request_sent, err_msg)
    internal_links, external_links, status_code, status, _request_sent, error_msg = core.process_url(
        args.url, target_domains=target_domains, trusted_domains=[]
    )

    if args.json:
        result_json = {
            "url": args.url,
            "status_code": status_code,
            "status": status,
            "error_msg": error_msg,
            "internal_links_count": len(internal_links),
            "external_links_count": len(external_links),
        }
        print(json.dumps(result_json, ensure_ascii=False))
    else:
        if status_code == 200:
            print(f"[+] 爬取成功！狀態碼: {status_code}")
            print(f"    - 內部連結數量: {len(internal_links)}")
            print(f"    - 外部連結數量: {len(external_links)}")

            print("\n[內部連結預覽]")
            for link in internal_links:
                print(f"  - {link}")

            print("\n[外部連結預覽]")
            for link in external_links:
                print(f"  - {link}")

        else:
            print(f"[-] 爬取失敗或異常。狀態: {status}, 狀態碼: {status_code}")
            if error_msg:
                print(f"    - 錯誤訊息: {error_msg}")

    core.close()


# pylint: disable=duplicate-code
if __name__ == "__main__":
    main()
