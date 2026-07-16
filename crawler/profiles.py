"""
動態瀏覽器特徵 (Browser Profiles) 產生模組。

利用 ``fake_useragent`` 隨機取得真實的 User-Agent，並自動配對對應的現代瀏覽器 Headers，
提高繞過基礎反爬蟲機制的成功率。

公開入口：

- ``get_random_profile``：主要公開函式，產生偽裝性高的瀏覽器 HTTP 標頭組合。

若 ``fake_useragent`` 資料庫取得失敗，會自動退回 Chrome 120 的預設字串並發出警告日誌，
不會中斷呼叫。
"""

import logging
import re

from fake_useragent import UserAgent  # type: ignore[import-untyped]
from fake_useragent.errors import FakeUserAgentError  # type: ignore[import-untyped]

logger: logging.Logger = logging.getLogger(__name__)

# 初始化 UserAgent (避免每次呼叫都讀取磁碟或網路)
_ua: UserAgent = UserAgent(os=["windows", "macos", "linux"], browsers=["chrome", "firefox", "safari", "edge"])


def _extract_chrome_version(ua_string: str) -> str:
    """
    從 User-Agent 中擷取 Chrome 主版本號。

    Args:
        ua_string (str): User-Agent 字串。

    Returns:
        str: Chrome 主版本號字串。若無法從 ua_string 中擷取，則 fallback 為 ``"120"``。
    """
    match = re.search(r"Chrome/(\d+)\.", ua_string)
    return match.group(1) if match else "120"  # fallback 為常規 Chrome 版本號


def _extract_edge_version(ua_string: str) -> str:
    """
    從 User-Agent 中擷取 Edge 主版本號。

    Args:
        ua_string (str): User-Agent 字串。

    Returns:
        str: Edge 主版本號字串。若無法從 ua_string 中擷取，則 fallback 為 ``"120"``。
    """
    match = re.search(r"Edg/(\d+)\.", ua_string)
    return match.group(1) if match else "120"  # fallback 為常規 Edge 版本號


def get_random_profile(url: str | None = None) -> dict[str, str]:
    """
    隨機產生一組高擬真度的瀏覽器 HTTP 標頭。

    標頭內容會依據隨機取得的 User-Agent 屬於哪種瀏覽器（Chrome、Edge、Firefox、Safari）
    進行對應調整，並對安全/非安全連線分別處理：

    - HTTPS 連線（或 ``url`` 為 None）：附加 ``Sec-Fetch-*`` Secure Context 專屬標頭。
    - HTTP 明文連線：不附加上述標頭，避免觸發 WAF 防護。
    - Chrome/Edge：附加 ``Sec-Ch-Ua-*`` Client Hints。
    - Firefox/Safari：不附加 ``Sec-Ch-Ua-*``，符合其實際瀏覽器行為。

    Args:
        url (str | None): 當前請求的網址。用以判斷是否為安全連線，
            若為 None 則預設視為安全連線。

    Returns:
        dict[str, str]: 包含 User-Agent 與對應瀏覽器標頭的字典。
            實際包含的鍵因瀏覽器種類與連線名稱而異，
            常規項目有 ``"User-Agent"``、``"Accept"``、``"Accept-Language"``、
            ``"Upgrade-Insecure-Requests"``；HTTPS 另外附加 ``"Sec-Fetch-*"``；
            Chrome/Edge 另外附加 ``"Sec-Ch-Ua-*"``。
    """
    try:
        user_agent = _ua.random
    except FakeUserAgentError as e:
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
    }

    # Sec-Fetch 與 Sec-Ch-Ua 等 Client Hints 與 Metadata 標頭為 Secure Context 專屬。
    # 若在明文 HTTP 請求中夾帶此類標頭，極易觸發現代 WAF (如 Cloudflare) 的防護機制並回傳 520 錯誤。
    is_secure = url is None or url.startswith("https://")

    if is_secure:
        headers.update(
            {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )

        # 針對不同瀏覽器補齊專屬 Headers
        if "Chrome" in user_agent and "Edg" not in user_agent:
            version = _extract_chrome_version(user_agent)
            headers["Sec-Ch-Ua"] = f'"Not_A Brand";v="8", "Chromium";v="{version}", "Google Chrome";v="{version}"'
            headers["Sec-Ch-Ua-Mobile"] = "?0"
            headers["Sec-Ch-Ua-Platform"] = (
                '"Windows"' if "Windows" in user_agent else '"macOS"' if "Mac OS" in user_agent else '"Linux"'
            )
        elif "Edg" in user_agent:
            version = _extract_edge_version(user_agent)
            headers["Sec-Ch-Ua"] = f'"Not_A Brand";v="8", "Chromium";v="{version}", "Microsoft Edge";v="{version}"'
            headers["Sec-Ch-Ua-Mobile"] = "?0"
            headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in user_agent else '"macOS"'

    if "Firefox" in user_agent:
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
