"""
爬蟲核心邏輯模組，負責網頁抓取與解析。

此模組提供 CrawlerCore 類別，負責發送 HTTP 請求抓取網頁、
解析 HTML、擷取連結，並依據網域規則過濾與分類連結。
"""

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse, ParseResult
import httpx
from bs4 import BeautifulSoup
from crawler.utils import normalize_url, get_domain, is_in_domain_list, resolve_ip, is_safe_ip

logger: logging.Logger = logging.getLogger(__name__)

_default_social_domains = "facebook.com,fb.com,youtube.com,instagram.com,twitter.com,linkedin.com"
SOCIAL_DOMAINS: tuple[str, ...] = tuple(
    d.strip() for d in os.environ.get("CRAWLER_SOCIAL_DOMAINS", _default_social_domains).split(",") if d.strip()
)
MAX_CONTENT_LENGTH: int = int(os.environ.get("CRAWLER_MAX_CONTENT_LENGTH", 10 * 1024 * 1024))


# pylint: disable=too-many-instance-attributes
class CrawlerCore:
    """
    網頁爬蟲的核心引擎。

    負責處理 HTML 內容的抓取、連結的擷取，並根據提供的網域規則
    將連結分類為內部連結與外部目標連結。

    Attributes:
        timeout (int): HTTP 請求的逾時時間 (單位：秒)。
        client (httpx.Client): 用於發送同步連線的 HTTPX 客戶端物件。
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        timeout: int = 30,
        ignore_extensions: list[str] | None = None,
        mime_type_filter: dict | None = None,
        ignore_regexes: list[str] | None = None,
        user_agent: str | None = None,
        ssl_exempt_domains: list[str] | None = None,
        proxy_url: str | None = None,
    ) -> None:
        """
        初始化 CrawlerCore 物件。

        Args:
            timeout (int): HTTP 請求的逾時時間 (單位：秒)，預設為 30 秒。
            ignore_extensions (list[str] | None): 要忽略的副檔名清單，預設包含常見非 HTML 檔案。
            mime_type_filter (dict | None): MIME 類型過濾設定。
            ignore_regexes (list[str] | None): 要忽略的網址正規表示式 (Regex) 清單。
            user_agent (str | None): (選填) 自訂 HTTP 請求標頭的 User-Agent。
            ssl_exempt_domains (list[str] | None): (選填) 豁免 SSL 憑證驗證之網域清單。
            proxy_url (str | None): (選填) 代理伺服器 URL。
        """
        self.timeout: int = timeout
        self.ignore_extensions: list[str] = ignore_extensions or [
            ".pdf",
            ".jpg",
            ".png",
            ".gif",
            ".mp4",
            ".zip",
        ]
        self.mime_type_filter: dict = mime_type_filter or {
            "enabled": True,
            "allowed_types": ["text/html", "application/xhtml+xml"],
        }
        self.ignore_regexes: list[str] = ignore_regexes or []
        self.ignore_regex_compiled = [re.compile(p) for p in self.ignore_regexes]
        self.user_agent: str = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.ssl_exempt_domains: list[str] = ssl_exempt_domains or []
        self.proxy_url: str | None = proxy_url
        self.client: httpx.Client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
            proxy=self.proxy_url,
        )
        self.exempt_client: httpx.Client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
            verify=False,  # 自簽憑證豁免
            proxy=self.proxy_url,
        )

    def _get_client(self, url: str) -> httpx.Client:
        """
        根據網址的網域選擇適合的 HTTPX 客戶端。

        若目標網域在 ssl_exempt_domains 白名單中，則回傳關閉憑證驗證的 exempt_client，
        否則回傳預設的 client。

        Args:
            url (str): 目標網址。

        Returns:
            httpx.Client: 應使用的 HTTPX 客戶端實例。
        """
        domain = get_domain(url)
        if domain and is_in_domain_list(domain, self.ssl_exempt_domains):
            return self.exempt_client
        return self.client

    def fetch(self, url: str) -> tuple[str | None, int | None, str, str, bool]:
        """
        抓取給定網址的 HTML 內容。

        Args:
            url (str): 欲抓取的網址字串。

        Returns:
            tuple[str | None, int | None, str, str, bool]: 回傳 (HTML字串, HTTP狀態碼, 狀態字串, 最終網址, 是否發送請求)。
                狀態字串為 'completed' 或 'skip'。
        """
        # 略過符合 Regex 規則的連結以節省請求
        if any(pattern.search(url) for pattern in self.ignore_regex_compiled):
            logger.debug("網址 %s 符合忽略之 Regex 規則，略過爬取", url)
            return None, None, "skip", url, False

        # 略過指定的非 HTML 副檔名以節省頻寬與時間
        parsed_path = urlparse(url).path.lower()
        if any(parsed_path.endswith(ext) for ext in self.ignore_extensions):
            return None, None, "skip", url, False

        client = self._get_client(url)

        # SSRF 防禦：解析 IP 並確保為安全的外部 IP
        domain = get_domain(url)
        if domain:
            ip = resolve_ip(domain)
            if ip and not is_safe_ip(ip):
                logger.warning("網址 %s 的 IP (%s) 被判定為不安全，已攔截潛在的 SSRF 攻擊！", url, ip)
                return None, None, "skip", url, False

        with client.stream("GET", url) as response:
            response.raise_for_status()

            # 檢查 HTTP 回應的 Content-Type
            content_type: str = response.headers.get("Content-Type", "").lower()

            if self.mime_type_filter.get("enabled", True):
                allowed_types: list[str] = self.mime_type_filter.get(
                    "allowed_types", ["text/html"]
                )
                # 若 content_type 不包含任何一個 allowed_type，則提早中斷並回傳 None
                if not any(
                    allowed.lower() in content_type for allowed in allowed_types
                ):
                    logger.debug("網址 %s 略過，不符 MIME 類型: %s", url, content_type)
                    return None, response.status_code, "skip", str(response.url), True

            # 若檢查通過，讀取所有資料
            # 改用分塊讀取，並限制最大記憶體用量
            content_bytes = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                content_bytes.extend(chunk)
                if len(content_bytes) > MAX_CONTENT_LENGTH:
                    logger.warning("網址 %s 內容超過 %d bytes，已提早截斷保護記憶體", url, MAX_CONTENT_LENGTH)
                    break

            charset = response.charset_encoding or "utf-8"
            text = content_bytes.decode(charset, errors="replace")

            return (
                text,
                response.status_code,
                "completed",
                str(response.url),
                True,
            )

    def extract_links(self, html: str, base_url: str) -> list[str]:
        """
        從給定的 HTML 內容中擷取所有有效且絕對路徑的連結與外連資源（如超連結、script、stylesheet、iframe、img、embed、form、object 等）。

        Args:
            html (str): 準備進行解析的 HTML 字串。
            base_url (str): 用來將相對路徑轉換為絕對路徑的基準網址。

        Returns:
            list[str]: 包含所有已擷取且去重複的正規化網址陣列。
        """
        if not html:
            return []

        try:
            soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
            links: list[str] = []
            raw_links: list[Any] = []

            # 1. 擷取 href 屬性 (超連結 a, 樣式表 link)
            for tag in soup.find_all(["a", "link"], href=True):
                raw_links.append(tag.get("href"))

            # 2. 擷取 src 屬性 (script, iframe, img, embed)
            for tag in soup.find_all(["script", "iframe", "img", "embed"], src=True):
                raw_links.append(tag.get("src"))

            # 3. 擷取 action 屬性 (form)
            for tag in soup.find_all("form", action=True):
                raw_links.append(tag.get("action"))

            # 4. 擷取 data 屬性 (object)
            for tag in soup.find_all("object", data=True):
                raw_links.append(tag.get("data"))

            for attr_val in raw_links:
                if isinstance(attr_val, list):
                    val_str = attr_val[0] if attr_val else ""
                else:
                    val_str = attr_val

                if not isinstance(val_str, str):
                    continue

                href: str = val_str.strip()
                # 排除 javascript, mailto 等非 http(s) 的錨點連結
                if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                normalized_link: str = normalize_url(href, base_url)

                # 進行基礎驗證，確保為有效的 HTTP/HTTPS 網址
                parsed: ParseResult = urlparse(normalized_link)
                if parsed.scheme in ("http", "https"):
                    links.append(normalized_link)
            return list(set(links))  # 移除陣列中的重複網址
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("從 %s 擷取連結時發生錯誤: %s", base_url, e)
            return []

    def process_url(
        self, url: str, target_domains: list[str], internal_domains: list[str]
    ) -> tuple[list[str], list[str], int | None, str, bool]:
        """
        處理單一網址，包含抓取網頁、擷取連結以及分類。

        Args:
            url (str): 準備處理的網址。
            target_domains (list[str]): 允許爬蟲進入的網域陣列。
            internal_domains (list[str]): 被視為內部的網域陣列。指向這些網域以外的連結將被視為目標。

        Returns:
            tuple[list[str], list[str], int | None, str, bool]: 包含：
                - internal_links: 準備加入佇列繼續爬取的內部連結陣列。
                - external_target_links: 需被記錄的外部連結陣列。
                - status_code: HTTP 狀態碼 (若有)。
                - status: 最終狀態 ('completed' 或 'skip')。
                - request_sent: 是否發送了 HTTP 請求。
        """
        html, status_code, status, final_url, request_sent = self.fetch(url)

        if not html:
            return [], [], status_code, status, request_sent

        links: list[str] = self.extract_links(html, final_url)

        internal_links: list[str] = []
        external_target_links: list[str] = []

        for link in links:
            domain: str = get_domain(link)
            if not domain:
                continue

            # 規則 1: 遍歷在允許網域 (target_domains) 內的網頁
            if is_in_domain_list(domain, target_domains):
                internal_links.append(link)

            # 規則 2: 找出連向內部網域 (internal_domains) 以外的外部網址
            if not is_in_domain_list(domain, internal_domains):
                external_target_links.append(link)

        return internal_links, external_target_links, status_code, status, request_sent

    def check_external_link(self, url: str) -> tuple[int | None, str | None]:
        """
        對外部連結進行存活檢查。

        優先使用 HEAD 請求以節省流量。若遇到特定阻擋狀態碼或目標為社群平台，
        則自動降級為帶有 Range 標頭的 GET 請求，嘗試繞過反爬蟲機制。

        Args:
            url (str): 準備進行探測的外部網址。

        Returns:
            tuple[int | None, str | None]: 回傳 (HTTP 狀態碼, 錯誤訊息)。
        """
        try:
            client = self._get_client(url)
            # 優先使用 HEAD 請求以節省流量與時間，逾時時間設為較短的 10 秒
            response = client.request("HEAD", url, timeout=10.0, follow_redirects=True)

            # 針對可能阻擋 HEAD 的大型社群/特定網域或狀態碼 (如 400, 403, 405) 進行 GET 降級試探
            domain = get_domain(url)
            # 使用精確的子網域比對（防止 notfacebook.com 被誤判為社群網域）
            is_social_media = domain and is_in_domain_list(domain.lower(), list(SOCIAL_DOMAINS))

            if response.status_code in (400, 403, 405) or (
                response.status_code >= 400 and is_social_media
            ):
                # 改用微量 GET stream 試探，並加上 Range 標頭避免下載大檔案
                headers = {"Range": "bytes=0-1023"}
                with client.stream(
                    "GET", url, headers=headers, timeout=10.0, follow_redirects=True
                ) as resp:
                    return resp.status_code, None
            return response.status_code, None
        except httpx.HTTPStatusError as e:
            return e.response.status_code, str(e)
        except httpx.RequestError as e:
            return None, str(e)
        except Exception as e:  # pylint: disable=broad-exception-caught
            return None, str(e)

    def close(self) -> None:
        """
        關閉底層的 HTTPX 客戶端連線。

        釋放底層連線池資源。建議在爬蟲任務結束時呼叫。
        """
        self.client.close()
        self.exempt_client.close()
