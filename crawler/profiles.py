"""
動態瀏覽器特徵 (Browser Profiles) 產生模組。

利用 fake_useragent 隨機取得真實的 User-Agent，並自動配對對應的現代瀏覽器 Headers，
提高繞過基礎反爬蟲機制的成功率。
"""

import re
import logging
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

# 初始化 UserAgent (避免每次呼叫都讀取磁碟或網路)
_ua = UserAgent(os=["windows", "macos", "linux"], browsers=["chrome", "firefox", "safari", "edge"])


def _extract_chrome_version(ua_string: str) -> str:
    """從 User-Agent 中擷取 Chrome 主版本號"""
    match = re.search(r"Chrome/(\d+)\.", ua_string)
    return match.group(1) if match else "120"


def _extract_edge_version(ua_string: str) -> str:
    """從 User-Agent 中擷取 Edge 主版本號"""
    match = re.search(r"Edg/(\d+)\.", ua_string)
    return match.group(1) if match else "120"


def get_random_profile() -> dict[str, str]:
    """
    隨機產生一組高擬真度的瀏覽器 HTTP 標頭。

    Returns:
        dict[str, str]: 包含 User-Agent 與對應 Sec-Ch-Ua 等欄位的標頭字典。
    """
    try:
        user_agent = _ua.random
    except Exception as e:
        logger.warning("fake_useragent 取得 UA 失敗，退回預設值: %s", e)
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    # 針對不同瀏覽器補齊專屬 Headers
    if "Chrome" in user_agent and "Edg" not in user_agent:
        version = _extract_chrome_version(user_agent)
        headers["Sec-Ch-Ua"] = f'"Not_A Brand";v="8", "Chromium";v="{version}", "Google Chrome";v="{version}"'
        headers["Sec-Ch-Ua-Mobile"] = "?0"
        headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in user_agent else '"macOS"' if "Mac OS" in user_agent else '"Linux"'
    elif "Edg" in user_agent:
        version = _extract_edge_version(user_agent)
        headers["Sec-Ch-Ua"] = f'"Not_A Brand";v="8", "Chromium";v="{version}", "Microsoft Edge";v="{version}"'
        headers["Sec-Ch-Ua-Mobile"] = "?0"
        headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in user_agent else '"macOS"'
    elif "Firefox" in user_agent:
        # Firefox 特定的 Accept 順序
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        # 移除 Chromium 專屬 Headers (如果存在的話)
        for key in ["Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform"]:
            headers.pop(key, None)
    elif "Safari" in user_agent and "Chrome" not in user_agent:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        for key in ["Sec-Ch-Ua", "Sec-Ch-Ua-Mobile", "Sec-Ch-Ua-Platform"]:
            headers.pop(key, None)

    return headers
