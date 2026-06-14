"""
單一頁面爬取測試腳本。

此腳本用於在終端機中快速測試特定網址，並限定爬取深度與頁數為 1，
直接印出爬取結果，方便開發除錯與驗證。
"""

import argparse
import os
import sys

import yaml

# 加入專案根目錄到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pylint: disable=wrong-import-position,import-error
from crawler.config_utils import merge_and_validate_crawler_config
from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig


def get_test_crawler_config(
    global_config_path: str, user_config_overrides: dict[str, object] | None = None
) -> CrawlerConfig:
    """
    讀取全域設定檔並合併個別任務設定，產生測試用的 CrawlerConfig 實例。

    Args:
        global_config_path (str): 全域設定檔的路徑。
        user_config_overrides (dict[str, object] | None): 欲覆寫的個別任務設定。

    Returns:
        CrawlerConfig: 最終合併後的爬蟲配置實例。
    """
    global_config: dict[str, object] = {}
    if os.path.exists(global_config_path):
        try:
            with open(global_config_path, "r", encoding="utf-8") as f:
                global_config = yaml.safe_load(f) or {}
        except Exception as e:  # pylint: disable=broad-exception-caught
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
        social_domains=list(final_cfg.get("social_domains", []))
        if isinstance(final_cfg.get("social_domains"), list)
        else [],
        user_agent=str(final_cfg["user_agent"]) if final_cfg.get("user_agent") else None,
        proxy_url=str(final_cfg["proxy_url"]) if final_cfg.get("proxy_url") else None,
        ssl_exempt_domains=list(final_cfg.get("ssl_exempt_domains", []))
        if isinstance(final_cfg.get("ssl_exempt_domains"), list)
        else [],
        ignore_extensions=list(final_cfg.get("ignore_extensions", []))
        if isinstance(final_cfg.get("ignore_extensions"), list)
        else [],
        ignore_regexes=list(final_cfg.get("ignore_regexes", []))
        if isinstance(final_cfg.get("ignore_regexes"), list)
        else [],
        mime_type_filter=dict(final_cfg.get("mime_type_filter", {}))
        if isinstance(final_cfg.get("mime_type_filter"), dict)
        else {"enabled": True, "allowed_types": ["text/html", "application/xhtml+xml"]},
    )


def main() -> None:
    """
    解析命令列參數，並針對目標網址進行單次頁面爬取測試。
    """
    parser = argparse.ArgumentParser(description="測試單一頁面爬取 (限定 1 頁)")
    parser.add_argument("url", help="欲爬取的目標網址")
    parser.add_argument(
        "-g", "--global-config", type=str, default="config/config_global.yaml", help="全域 YAML 設定檔的路徑"
    )
    args = parser.parse_args()

    # 1. 取得合併後的設定實例
    config = get_test_crawler_config(args.global_config)

    core = CrawlerCore(config)
    print(f"[*] 開始爬取單一頁面: {args.url}")

    # process_url 回傳: (internal_links, external_target_links, status_code, status, request_sent, err_msg)
    internal_links, external_links, status_code, status, _request_sent, error_msg = core.process_url(
        args.url, target_domains=[], trusted_domains=[]
    )

    if status_code == 200:
        print(f"[+] 爬取成功！狀態碼: {status_code}")
        print(f"    - 內部連結數量: {len(internal_links)}")
        print(f"    - 外部連結數量: {len(external_links)}")

        print("\n[外部連結預覽")
        for link in external_links:
            print(f"  - {link}")
    else:
        print(f"[-] 爬取失敗或異常。狀態: {status}, 狀態碼: {status_code}")
        # pylint: disable=duplicate-code
        if error_msg:
            print(f"    - 錯誤訊息: {error_msg}")

    core.close()


if __name__ == "__main__":
    main()
