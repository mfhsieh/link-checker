"""
爬蟲設定與全域設定合併工具模組。
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_GLOBAL_CONFIG = {
    "crawler": {
        "timeout": 30,
        "delay": 3.0,
        "retries": 3,
        "max_depth": None,
        "max_pages": None,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "proxy_url": None,
        "ssl_exempt_domains": [],
        "approved_domains": [],
        "domain_delays": {},
        "ignore_extensions": ["pdf", "zip", "jpg", "png", "gif", "mp4", "mp3", "doc", "docx", "xls", "xlsx", "csv"],
        "ignore_regexes": [],
        "mime_type_filter": {
            "enabled": True,
            "allowed_types": ["text/html", "application/xhtml+xml"]
        },
        "min_timeout": 5,
        "max_timeout": 120,
        "min_delay": 0.5,
        "max_delay": 10.0,
        "min_retries": 0,
        "max_retries": 5,
    }
}

ALLOWED_CRAWLER_KEYS: set[str] = {
    "timeout",
    "delay",
    "retries",
    "mime_type_filter",
    "ignore_extensions",
    "ignore_regexes",
    "user_agent",
    "ssl_exempt_domains",
    "domain_delays",
    "max_depth",
    "max_pages",
    "proxy_url",
}

def _apply_crawler_defaults(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """套用全域預設值到 crawler_config 中。"""
    if "timeout" not in crawler_config:
        crawler_config["timeout"] = global_crawler_config.get("timeout", 30)
    if "delay" not in crawler_config:
        crawler_config["delay"] = global_crawler_config.get("delay", 3.0)
    if "retries" not in crawler_config:
        crawler_config["retries"] = global_crawler_config.get("retries", 3)
    if "mime_type_filter" not in crawler_config:
        crawler_config["mime_type_filter"] = global_crawler_config.get(
            "mime_type_filter",
            {"enabled": True, "allowed_types": ["text/html", "application/xhtml+xml"]},
        )
    if "user_agent" not in crawler_config:
        crawler_config["user_agent"] = global_crawler_config.get(
            "user_agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
    if "max_depth" not in crawler_config:
        crawler_config["max_depth"] = global_crawler_config.get("max_depth", None)
    if "max_pages" not in crawler_config:
        crawler_config["max_pages"] = global_crawler_config.get("max_pages", None)
    if "proxy_url" not in crawler_config:
        crawler_config["proxy_url"] = global_crawler_config.get("proxy_url", None)

def _merge_crawler_lists(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """聯集合併 crawler_config 中的 list 參數。"""
    list_keys = [
        "ignore_extensions",
        "ignore_regexes",
        "ssl_exempt_domains",
    ]
    for key in list_keys:
        g_list: list[str] = global_crawler_config.get(key) or []
        l_list: list[str] = crawler_config.get(key) or []

        if isinstance(g_list, str):
            g_list = [g_list]
        if isinstance(l_list, str):
            l_list = [l_list]

        if g_list or l_list:
            crawler_config[key] = list(set(g_list + l_list))
        elif key in ["ssl_exempt_domains"]:
            crawler_config[key] = []

    global_domain_delays: dict = global_crawler_config.get("domain_delays") or {}
    local_domain_delays: dict = crawler_config.get("domain_delays") or {}
    crawler_config["domain_delays"] = {**global_domain_delays, **local_domain_delays}

def _enforce_crawler_limits(
    crawler_config: dict[str, Any], global_crawler_config: dict[str, Any]
) -> None:
    """強制套用全域上下限。"""
    limits = [
        ("timeout", "min_timeout", "max_timeout", 30, 120),
        ("delay", "min_delay", "max_delay", 3.0, 6.0),
        ("retries", "min_retries", "max_retries", 0, 5),
    ]
    for key, min_k, max_k, def_min, def_max in limits:
        min_val = global_crawler_config.get(min_k, def_min)
        max_val = global_crawler_config.get(max_k, def_max)
        if crawler_config[key] < min_val:
            logging.warning("個別設定的 %s (%s) 小於最小值 (%s)，強制套用。", key, crawler_config[key], min_val)
            crawler_config[key] = min_val
        elif crawler_config[key] > max_val:
            logging.warning("個別設定的 %s (%s) 大於最大值 (%s)，強制套用。", key, crawler_config[key], max_val)
            crawler_config[key] = max_val

def merge_and_validate_crawler_config(
    config: dict[str, Any], global_config: dict[str, Any]
) -> dict[str, Any]:
    """合併全域與個別的爬蟲設定，並確保個別設定遵守全域上下限。"""
    crawler_config: dict[str, Any] = config.get("crawler", {})
    for key in list(crawler_config.keys()):
        if key not in ALLOWED_CRAWLER_KEYS:
            logging.warning("個別設定 config.yaml 不允許覆寫 crawler.%s，此設定將被忽略。", key)
            del crawler_config[key]

    global_crawler_config: dict[str, Any] = global_config.get("crawler", {})

    _apply_crawler_defaults(crawler_config, global_crawler_config)
    _merge_crawler_lists(crawler_config, global_crawler_config)

    env_proxy = os.environ.get("CRAWLER_PROXY_URL")
    if env_proxy:
        crawler_config["proxy_url"] = env_proxy

    env_ssl_exempt = os.environ.get("CRAWLER_SSL_EXEMPT_DOMAINS")
    if env_ssl_exempt:
        crawler_config["ssl_exempt_domains"] = list(
            set(
                crawler_config.get("ssl_exempt_domains", [])
                + [d.strip() for d in env_ssl_exempt.split(",") if d.strip()]
            )
        )

    _enforce_crawler_limits(crawler_config, global_crawler_config)
    return crawler_config