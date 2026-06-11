"""
爬蟲核心邏輯模組，負責網頁抓取與解析。

此模組提供 CrawlerCore 類別，負責發送 HTTP 請求抓取網頁、
解析 HTML、擷取連結，並依據網域規則過濾與分類連結。
"""

import logging
import re
import socket
import threading
from contextlib import contextmanager, nullcontext
from collections.abc import Iterator
from collections.abc import Callable
from urllib.parse import urlparse, ParseResult, urljoin
import httpx
from bs4 import BeautifulSoup
from crawler.utils import normalize_url, get_domain, is_in_domain_list, resolve_ip, is_safe_ip
from crawler.profiles import get_random_profile

logger: logging.Logger = logging.getLogger(__name__)


# 實作執行緒安全的 DNS 解析攔截器 (Monkey Patch)
_original_getaddrinfo: Callable = socket.getaddrinfo
_dns_override: threading.local = threading.local()


# pylint: disable=too-many-arguments
def _patched_getaddrinfo(
    host: str | bytes | None,
    port: str | int | None,
    family: int = 0,
    type_: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[tuple[int, int, int, str, object]]:
    """
    攔截 socket.getaddrinfo 以支援自訂 DNS 解析。

    Args:
        host (str | bytes | None): 目標主機。
        port (str | int | None): 目標通訊埠。
        family (int): 位址家族。
        type_ (int): Socket 類型。
        proto (int): 協定。
        flags (int): 標記。

    Returns:
        list[tuple[int, int, int, str, object]]: 原始或被替換的位址資訊列表。
    """
    overrides = getattr(_dns_override, "overrides", {})
    if host in overrides:
        return _original_getaddrinfo(overrides[host], port, family, type_, proto, flags)
    return _original_getaddrinfo(host, port, family, type_, proto, flags)


socket.getaddrinfo = _patched_getaddrinfo


@contextmanager
def dns_override(host: str, ip: str) -> Iterator[None]:
    """
    Thread-safe Context Manager，用以強制替換指定網域的 DNS 解析結果。

    Args:
        host (str): 欲攔截的網域名稱。
        ip (str): 強制對應的 IP 位址。

    Yields:
        None: 無回傳值。
    """
    if not hasattr(_dns_override, "overrides"):
        _dns_override.overrides = {}
    _dns_override.overrides[host] = ip
    try:
        yield
    finally:
        _dns_override.overrides.pop(host, None)


# pylint: disable=too-many-instance-attributes
class CrawlerCore:
    """
    網頁爬蟲的核心引擎。

    負責處理 HTML 內容的抓取、連結的擷取，並根據提供的網域規則
    將連結分類為內部連結與外部目標連結。

    Attributes:
        timeout (int): HTTP 請求的逾時時間 (單位：秒)。
            connect_timeout (float): 建立 HTTP 連線的逾時時間 (單位：秒)。
            external_check_timeout (float): 外部連結存活探測的總體逾時時間 (單位：秒)。
        client (httpx.Client): 用於發送同步連線的 HTTPX 客戶端物件。
            exempt_client (httpx.Client): 用於發送免除 SSL 驗證的 HTTPX 客戶端物件。
    """

    # pylint: disable=too-many-arguments,too-many-locals
    def __init__(
        self,
        timeout: int = 30,
        connect_timeout: float = 5.0,
        external_check_timeout: float = 10.0,
        ignore_extensions: list[str] | None = None,
        mime_type_filter: dict[str, object] | None = None,
        ignore_regexes: list[str] | None = None,
        user_agent: str | None = None,
        ssl_exempt_domains: list[str] | None = None,
        proxy_url: str | None = None,
        max_content_length: int = 10485760,
        max_redirects: int = 10,
        social_domains: list[str] | None = None,
    ) -> None:
        """
        初始化 CrawlerCore 物件。

        Args:
            timeout (int): HTTP 請求的逾時時間 (單位：秒)，預設為 30 秒。
                connect_timeout (float): 建立 HTTP 連線的逾時時間 (單位：秒)，預設為 5.0 秒。
                external_check_timeout (float): 外部連結存活探測的總體逾時時間 (單位：秒)，預設為 10.0 秒。
            ignore_extensions (list[str] | None): 要忽略的副檔名清單，預設包含常見非 HTML 檔案。
            mime_type_filter (dict[str, object] | None): MIME 類型過濾設定。
            ignore_regexes (list[str] | None): 要忽略的網址正規表示式 (Regex) 清單。
            user_agent (str | None): (選填) 自訂 HTTP 請求標頭的 User-Agent。
            ssl_exempt_domains (list[str] | None): (選填) 豁免 SSL 憑證驗證之網域清單。
            proxy_url (str | None): (選填) 代理伺服器 URL。
            max_content_length (int): 最大允許下載的網頁容量 (Bytes)，預設為 10 MB。
            max_redirects (int): HTTP 重導向次數上限，預設為 10 次。
            social_domains (list[str] | None): (選填) 允許 GET 降級探測的社群網域清單。
        """
        self.timeout: int = timeout
        self.connect_timeout: float = connect_timeout
        self.external_check_timeout: float = external_check_timeout
        self.ignore_extensions: list[str] = ignore_extensions or [
            ".pdf",
            ".jpg",
            ".png",
            ".gif",
            ".mp4",
            ".zip",
        ]
        self.mime_type_filter: dict[str, object] = mime_type_filter or {
            "enabled": True,
            "allowed_types": ["text/html", "application/xhtml+xml"],
        }
        self.ignore_regexes: list[str] = ignore_regexes or []
        self.ignore_regex_compiled = []
        for p in self.ignore_regexes:
            try:
                self.ignore_regex_compiled.append(re.compile(p))
            except re.error as e:
                logger.warning("略過無效的正則表達式 '%s': %s", p, e)
        self.enable_dynamic_headers: bool = user_agent is None
        self.user_agent: str = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.ssl_exempt_domains: list[str] = ssl_exempt_domains or []
        self.proxy_url: str | None = proxy_url
        self.max_content_length: int = max_content_length
        self.max_redirects: int = max_redirects
        self.social_domains: list[str] = social_domains or [
            "facebook.com",
            "fb.com",
            "youtube.com",
            "instagram.com",
            "twitter.com",
            "linkedin.com",
        ]

        timeout_config = httpx.Timeout(self.timeout, connect=self.connect_timeout)

        self.client: httpx.Client = httpx.Client(
            timeout=timeout_config,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
            proxy=self.proxy_url,
        )
        self.exempt_client: httpx.Client = httpx.Client(
            timeout=timeout_config,
            follow_redirects=False,
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

    # pylint: disable=too-many-locals,too-many-return-statements
    def fetch(
        self, url: str, target_domains: list[str] | None = None
    ) -> tuple[str | None, int | None, str, str, bool, str | None]:
        """
        抓取給定網址的 HTML 內容。

        Args:
            url (str): 欲抓取的網址字串。
            target_domains (list[str] | None): 目標網域清單，用於防止重導向跨出邊界。

        Returns:
            tuple[str | None, int | None, str, str, bool, str | None]: 回傳 (HTML字串, HTTP狀態碼, 狀態, 最終網址, 是否發送請求, 錯誤或警告訊息)。
                狀態字串為 'completed', 'warning' 或 'skip'。

        Raises:
            httpx.HTTPStatusError: 若 HTTP 回應狀態碼非 2xx 時拋出（預設由外層捕捉）。
            httpx.RequestError: 發生網路連線層級錯誤時拋出（預設由外層捕捉）。
        """
        max_redirects = self.max_redirects
        current_url = url
        request_sent = False

        for _ in range(max_redirects):
            # 略過符合 Regex 規則的連結以節省請求
            if any(pattern.search(current_url) for pattern in self.ignore_regex_compiled):
                logger.debug("網址 %s 符合忽略之 Regex 規則，略過爬取", current_url)
                return None, None, "skip", current_url, request_sent, "符合忽略之 Regex 規則"

            # 略過指定的非 HTML 副檔名以節省頻寬與時間
            parsed_path = urlparse(current_url).path.lower()
            if any(parsed_path.endswith(ext) for ext in self.ignore_extensions):
                return None, None, "skip", current_url, request_sent, "符合忽略之副檔名"

            client = self._get_client(current_url)

            # SSRF 防禦：解析 IP 並確保為安全的外部 IP
            domain = get_domain(current_url)
            ip = None
            if domain:
                ip = resolve_ip(domain)
                if ip:
                    if not is_safe_ip(ip):
                        logger.warning(
                            "網址 %s 的 IP (%s) 被判定為不安全，已攔截潛在的 SSRF 攻擊！",
                            current_url,
                            ip,
                        )
                        return None, None, "skip", current_url, request_sent, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全"

            with dns_override(domain, ip) if domain and ip else nullcontext():
                headers = get_random_profile() if self.enable_dynamic_headers else None
                with client.stream("GET", current_url, headers=headers) as response:
                    request_sent = True

                    # 處理重導向
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            return (
                                None,
                                response.status_code,
                                "skip",
                                current_url,
                                request_sent,
                                "重導向但無 Location 標頭",
                            )
                        next_url = urljoin(current_url, location)

                        # 防止重導向跨出目標網域，進而爬取外部網站的所有內容
                        if target_domains:
                            next_domain = get_domain(next_url)
                            if next_domain and not is_in_domain_list(next_domain, target_domains):
                                logger.info("網址 %s 重導向至外部網域 %s，停止深入抓取", current_url, next_url)
                                fake_html = f'<a href="{next_url}"></a>'
                                return (
                                    fake_html,
                                    response.status_code,
                                    "completed",
                                    current_url,
                                    request_sent,
                                    f"重導向至外部網域: {next_domain}",
                                )

                        current_url = next_url
                        continue

                    response.raise_for_status()

                    # 檢查 HTTP 回應的 Content-Type
                    content_type: str = response.headers.get("Content-Type", "").lower()

                    if self.mime_type_filter.get("enabled", True):
                        allowed_types: list[str] = self.mime_type_filter.get("allowed_types", ["text/html"])
                        # 若 content_type 不包含任何一個 allowed_type，則提早中斷並回傳 None
                        if not any(allowed.lower() in content_type for allowed in allowed_types):
                            logger.debug("網址 %s 略過，不符 MIME 類型: %s", current_url, content_type)
                            return (
                                None,
                                response.status_code,
                                "skip",
                                current_url,
                                request_sent,
                                f"略過非目標 MIME 類型 ({content_type})",
                            )

                    # 若檢查通過，讀取所有資料
                    # 改用分塊讀取，並限制最大記憶體用量
                    content_bytes = bytearray()
                    err_msg = None
                    for chunk in response.iter_bytes(chunk_size=8192):
                        content_bytes.extend(chunk)
                        if len(content_bytes) > self.max_content_length:
                            err_msg = f"網頁容量超過上限 ({self.max_content_length} bytes)，內容已被提早截斷"
                            logger.warning(
                                "網址 %s 內容超過 %d bytes，已提早截斷保護記憶體",
                                current_url,
                                self.max_content_length,
                            )
                            break

                    charset = response.charset_encoding or "utf-8"
                    text = content_bytes.decode(charset, errors="replace")

                    status = "warning" if err_msg else "completed"

                    return (
                        text,
                        response.status_code,
                        status,
                        current_url,
                        request_sent,
                        err_msg,
                    )

        logger.warning("網址 %s 超過最大重導向次數", url)
        return None, None, "skip", current_url, request_sent, "超過最大重導向次數"

    # pylint: disable=too-many-branches
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
            raw_links: list[object] = []

            # 透過單次遍歷 HTML 樹來擷取所有標籤，大幅提升大型網頁的解析效能
            for tag in soup.find_all(["a", "link", "script", "iframe", "img", "embed", "form", "object"]):
                # 1. 擷取 href 屬性 (超連結 a, 樣式表 link)
                if tag.name in ("a", "link") and tag.has_attr("href"):
                    raw_links.append(tag.get("href"))
                # 2. 擷取 src 屬性 (script, iframe, img, embed)
                elif tag.name in ("script", "iframe", "img", "embed") and tag.has_attr("src"):
                    raw_links.append(tag.get("src"))
                # 3. 擷取 action 屬性 (form)
                elif tag.name == "form" and tag.has_attr("action"):
                    raw_links.append(tag.get("action"))
                # 4. 擷取 data 屬性 (object)
                elif tag.name == "object" and tag.has_attr("data"):
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
        self, url: str, target_domains: list[str], trusted_domains: list[str]
    ) -> tuple[list[str], list[str], int | None, str, bool, str | None]:
        """
        處理單一網址，包含抓取網頁、擷取連結以及分類。

        Args:
            url (str): 準備處理的網址。
            target_domains (list[str]): 允許爬蟲進入的網域陣列。
            trusted_domains (list[str]): 被視為信任的網域陣列。指向這些網域以外的連結將被視為目標。

        Returns:
            tuple[list[str], list[str], int | None, str, bool, str | None]: 包含：
                - internal_links: 準備加入佇列繼續爬取的內部連結陣列。
                - external_target_links: 需被記錄的外部連結陣列。
                - status_code: HTTP 狀態碼 (若有)。
                - status: 最終狀態 ('completed' 或 'skip')。
                - request_sent: 是否發送了 HTTP 請求。
                - err_msg: 擷取過程的警告或錯誤訊息 (若有)。
        """
        html, status_code, status, final_url, request_sent, err_msg = self.fetch(url, target_domains=target_domains)

        if not html:
            return [], [], status_code, status, request_sent, err_msg

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

            # 規則 2: 找出連向信任網域 (trusted_domains) 以外的外部網址
            if not is_in_domain_list(domain, trusted_domains):
                external_target_links.append(link)

        return internal_links, external_target_links, status_code, status, request_sent, err_msg

    # pylint: disable=too-many-return-statements
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
        max_redirects = self.max_redirects
        current_url = url

        for _ in range(max_redirects):
            try:
                tgt_dom = get_domain(current_url)
                ip = None
                if tgt_dom:
                    ip = resolve_ip(tgt_dom)
                    if ip:
                        if not is_safe_ip(ip):
                            return None, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全"

                client = self._get_client(current_url)
                with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
                    # 優先使用 HEAD 請求以節省流量與時間，並套用精細化超時配置
                    head_timeout = httpx.Timeout(self.external_check_timeout, connect=self.connect_timeout)
                    headers = get_random_profile() if self.enable_dynamic_headers else None
                    response = client.request("HEAD", current_url, timeout=head_timeout, headers=headers)

                # 處理重導向
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if location:
                        current_url = urljoin(current_url, location)
                        continue
                    return response.status_code, None

                # 針對可能阻擋 HEAD 的大型社群/特定網域或狀態碼 (如 400, 403, 405) 進行 GET 降級試探
                # 使用精確的子網域比對（防止 notfacebook.com 被誤判為社群網域）
                is_social_media = tgt_dom and is_in_domain_list(tgt_dom.lower(), self.social_domains)

                if response.status_code in (400, 403, 405) or (response.status_code >= 400 and is_social_media):
                    # 改用微量 GET stream 試探，並加上 Range 標頭避免下載大檔案
                    headers = {"Range": "bytes=0-1023"}
                    if self.enable_dynamic_headers:
                        headers.update(get_random_profile())
                    stream_timeout = httpx.Timeout(self.external_check_timeout, connect=self.connect_timeout)
                    with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
                        with client.stream("GET", current_url, headers=headers, timeout=stream_timeout) as resp:
                            if resp.status_code in (301, 302, 303, 307, 308):
                                location = resp.headers.get("Location")
                                if location:
                                    current_url = urljoin(current_url, location)
                                    continue
                                return resp.status_code, None
                            return resp.status_code, None
                return response.status_code, None
            except httpx.HTTPStatusError as e:
                return e.response.status_code, str(e)
            except httpx.RequestError as e:
                return None, str(e)
            except Exception as e:  # pylint: disable=broad-exception-caught
                return None, str(e)

        return None, "超過最大重導向次數限制"

    def close(self) -> None:
        """
        關閉底層的 HTTPX 客戶端連線。

        釋放底層連線池資源。建議在爬蟲任務結束時呼叫。
        """
        self.client.close()
        self.exempt_client.close()
