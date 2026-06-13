"""
爬蟲核心邏輯模組，負責網頁抓取與解析。

此模組提供 CrawlerCore 類別，負責發送 HTTP 請求抓取網頁、
解析 HTML、擷取連結，並依據網域規則過濾與分類連結。
"""

import logging
import re
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from urllib.parse import ParseResult, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from crawler.models import CrawlerConfig
from crawler.profiles import get_random_profile
from crawler.utils import get_domain, is_in_domain_list, is_safe_ip, normalize_url, resolve_ip

logger: logging.Logger = logging.getLogger(__name__)


# 實作執行緒安全的 DNS 解析攔截器 (Monkey Patch)
_original_getaddrinfo: Callable = socket.getaddrinfo
_dns_override: threading.local = threading.local()


def _patched_getaddrinfo(
    host: str | bytes | None,
    port: str | int | None,
    *args: object,
    **kwargs: object,
) -> list[tuple[int, int, int, str, object]]:
    """攔截 socket.getaddrinfo 以支援自訂 DNS 解析。

    Args:
        host (str | bytes | None): 目標主機。
        port (str | int | None): 目標通訊埠。
        *args (object): 傳遞給原始 getaddrinfo 的額外位置參數 (例如 family, type, proto, flags)。
        **kwargs (object): 傳遞給原始 getaddrinfo 的額外關鍵字參數。

    Returns:
        list[tuple[int, int, int, str, object]]: 原始或被替換的位址資訊列表。
    """
    overrides = getattr(_dns_override, "overrides", {})
    if host in overrides:
        return _original_getaddrinfo(overrides[host], port, *args, **kwargs)
    return _original_getaddrinfo(host, port, *args, **kwargs)


socket.getaddrinfo = _patched_getaddrinfo


@contextmanager
def dns_override(host: str, ip: str) -> Iterator[None]:
    """
    Thread-safe Context Manager，用以強制替換指定網域的 DNS 解析結果。

    Args:
        host (str): 欲攔截的網域名稱。
        ip (str): 強制對應的 IP 位址。

    Yields:
        None: 此 Context Manager 不回傳特定值。
    """
    if not hasattr(_dns_override, "overrides"):
        _dns_override.overrides = {}
    _dns_override.overrides[host] = ip
    try:
        yield
    finally:
        _dns_override.overrides.pop(host, None)


class CrawlerCore:
    """網頁爬蟲的核心引擎。

    負責處理 HTML 內容的抓取、連結的擷取，並根據提供的網域規則
    將連結分類為內部連結與外部目標連結。
    """

    @staticmethod
    def _compile_regexes(regexes: list[str]) -> list[re.Pattern]:
        """編譯正則表達式，忽略無效的語法。

        Args:
            regexes (list[str]): 原始的正則表達式字串列表。

        Returns:
            list[re.Pattern]: 編譯後的正則表達式物件列表。
        """
        compiled = []
        for p in regexes:
            try:
                compiled.append(re.compile(p))
            except re.error as e:
                logger.warning("略過無效的正則表達式 '%s': %s", p, e)
        return compiled

    def __init__(self, config: CrawlerConfig | None = None) -> None:
        """
        初始化 CrawlerCore 物件。

        Args:
            config (CrawlerConfig | None): 爬蟲引擎配置物件。若未提供則使用預設配置。
        """
        self.config: CrawlerConfig = config or CrawlerConfig()

        self.ignore_regex_compiled = self._compile_regexes(self.config.ignore_regexes)
        self.enable_dynamic_headers: bool = self.config.user_agent is None
        self.user_agent: str = self.config.user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        self.client: httpx.Client = httpx.Client(
            timeout=httpx.Timeout(self.config.timeout, connect=self.config.connect_timeout),
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
            proxy=self.config.proxy_url,
        )
        self.exempt_client: httpx.Client = httpx.Client(
            timeout=httpx.Timeout(self.config.timeout, connect=self.config.connect_timeout),
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
            verify=False,  # 自簽憑證豁免
            proxy=self.config.proxy_url,
        )

    def _get_client(self, url: str) -> httpx.Client:
        """根據網址的網域選擇適合的 HTTPX 客戶端。

        若目標網域在 ssl_exempt_domains 白名單中，則回傳關閉憑證驗證的 exempt_client，
        否則回傳預設的 client。

        Args:
            url (str): 目標網址。

        Returns:
            httpx.Client: 應使用的 HTTPX 客戶端實例。
        """
        domain = get_domain(url)
        if domain and is_in_domain_list(domain, self.config.ssl_exempt_domains):
            return self.exempt_client
        return self.client

    def _check_ignore_rules(self, url: str) -> str | None:
        """檢查是否符合忽略規則，若符合則回傳原因。

        Args:
            url (str): 欲檢查的網址。

        Returns:
            str | None: 若符合忽略規則回傳原因字串，否則回傳 None。
        """
        if any(pattern.search(url) for pattern in self.ignore_regex_compiled):
            logger.debug("網址 %s 符合忽略之 Regex 規則，略過爬取", url)
            return "符合忽略之 Regex 規則"

        parsed_path = urlparse(url).path.lower()
        if any(parsed_path.endswith(ext) for ext in self.config.ignore_extensions):
            return "符合忽略之副檔名"
        return None

    def _resolve_and_check_ssrf(self, domain: str | None, url: str) -> tuple[str | None, str | None]:
        """解析 IP 並檢查 SSRF，回傳 (IP, 錯誤訊息)。

        Args:
            domain (str | None): 目標網域。
            url (str): 目標網址。

        Returns:
            tuple[str | None, str | None]: (IP 位址, 錯誤訊息)。
        """
        if not domain:
            return None, None
        ip = resolve_ip(domain)
        if ip and not is_safe_ip(ip):
            logger.warning("網址 %s 的 IP (%s) 被判定為不安全，已攔截潛在的 SSRF 攻擊！", url, ip)
            return ip, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全"
        return ip, None

    def _handle_redirect(
        self, response: httpx.Response, current_url: str, target_domains: list[str] | None
    ) -> tuple[str | None, tuple[str | None, int | None, str, str, bool, str | None] | None]:
        """處理 HTTP 重導向，回傳 (next_url, 提前回傳的結果)。

        Args:
            response (httpx.Response): HTTP 回應物件。
            current_url (str): 當前網址。
            target_domains (list[str] | None): 允許進入的目標網域清單。

        Returns:
            tuple[str | None, tuple | None]: (下一步網址, 提前回傳的結果)。
        """
        location = response.headers.get("Location")
        if not location:
            return None, (None, response.status_code, "skip", current_url, True, "重導向但無 Location 標頭")

        next_url = urljoin(current_url, location)
        if target_domains:
            next_domain = get_domain(next_url)
            if next_domain and not is_in_domain_list(next_domain, target_domains):
                logger.info("網址 %s 重導向至外部網域 %s，停止深入抓取", current_url, next_url)
                fake_html = f'<a href="{next_url}"></a>'
                return None, (
                    fake_html,
                    response.status_code,
                    "completed",
                    current_url,
                    True,
                    f"重導向至外部網域: {next_domain}",
                )
        return next_url, None

    def _check_mime_type(self, response: httpx.Response, current_url: str) -> str | None:
        """檢查 MIME 類型是否允許，若不允許則回傳錯誤訊息。

        Args:
            response (httpx.Response): HTTP 回應物件。
            current_url (str): 當前網址。

        Returns:
            str | None: 若 MIME 類型不符則回傳錯誤訊息，否則回傳 None。
        """
        content_type: str = response.headers.get("Content-Type", "").lower()
        if self.config.mime_type_filter.get("enabled", True):
            allowed_types: list[str] = self.config.mime_type_filter.get("allowed_types", ["text/html"])
            if not any(allowed.lower() in content_type for allowed in allowed_types):
                logger.debug("網址 %s 略過，不符 MIME 類型: %s", current_url, content_type)
                return f"略過非目標 MIME 類型 ({content_type})"
        return None

    def _download_content(self, response: httpx.Response, current_url: str) -> tuple[str, str | None]:
        """下載網頁內容並回傳 (HTML 字串, 錯誤或警告訊息)。

        Args:
            response (httpx.Response): HTTP 回應物件。
            current_url (str): 當前網址。

        Returns:
            tuple[str, str | None]: (網頁 HTML 內容, 錯誤或警告訊息)。
        """
        content_bytes = bytearray()
        err_msg = None
        for chunk in response.iter_bytes(chunk_size=8192):
            content_bytes.extend(chunk)
            if len(content_bytes) > self.config.max_content_length:
                err_msg = f"網頁容量超過上限 ({self.config.max_content_length} bytes)，內容已被提早截斷"
                logger.warning(
                    "網址 %s 內容超過 %d bytes，已提早截斷保護記憶體",
                    current_url,
                    self.config.max_content_length,
                )
                break

        charset = response.charset_encoding or "utf-8"
        text = content_bytes.decode(charset, errors="replace")
        return text, err_msg

    def _process_response(
        self, response: httpx.Response, current_url: str, target_domains: list[str] | None
    ) -> tuple[str | None, tuple[str | None, int | None, str, str, bool, str | None] | None]:
        """處理 HTTP 回應，回傳 (next_url, 提前回傳的結果)。

        Args:
            response (httpx.Response): HTTP 回應物件。
            current_url (str): 當前網址。
            target_domains (list[str] | None): 允許進入的目標網域清單。

        Returns:
            tuple[str | None, tuple | None]: (下一步網址, 提前回傳的結果)。
        """
        if response.status_code in (301, 302, 303, 307, 308):
            return self._handle_redirect(response, current_url, target_domains)

        response.raise_for_status()

        if mime_err := self._check_mime_type(response, current_url):
            return None, (None, response.status_code, "skip", current_url, True, mime_err)

        text, err_msg = self._download_content(response, current_url)
        status = "warning" if err_msg else "completed"
        return None, (text, response.status_code, status, current_url, True, err_msg)

    def _fetch_single(
        self, current_url: str, request_sent: bool, target_domains: list[str] | None
    ) -> tuple[bool, str, tuple[str | None, int | None, str, str, bool, str | None] | None]:
        """執行單次 fetch 流程，回傳 (request_sent, next_url, result_tuple)。

        Args:
            current_url (str): 當前網址。
            request_sent (bool): 標記此循環是否已實際發送過 HTTP 請求。
            target_domains (list[str] | None): 允許進入的目標網域清單。

        Returns:
            tuple[bool, str, tuple | None]: (是否發送請求, 下一步網址, 提前回傳的結果)。
        """
        if ignore_reason := self._check_ignore_rules(current_url):
            return request_sent, current_url, (None, None, "skip", current_url, request_sent, ignore_reason)

        domain = get_domain(current_url)
        ip, ssrf_err = self._resolve_and_check_ssrf(domain, current_url)
        if ssrf_err:
            return request_sent, current_url, (None, None, "skip", current_url, request_sent, ssrf_err)

        with dns_override(domain, ip) if domain and ip else nullcontext():
            headers = get_random_profile() if self.enable_dynamic_headers else None
            with self._get_client(current_url).stream("GET", current_url, headers=headers) as response:
                next_url, result = self._process_response(response, current_url, target_domains)
                if result:
                    return True, current_url, result
                return True, next_url or current_url, None

    def fetch(
        self, url: str, target_domains: list[str] | None = None
    ) -> tuple[str | None, int | None, str, str, bool, str | None]:
        """抓取給定網址的 HTML 內容。

        Args:
            url (str): 欲抓取的網址字串。
            target_domains (list[str] | None): 目標網域清單，用於防止重導向跨出邊界。

        Returns:
            tuple[str | None, int | None, str, str, bool, str | None]: (HTML字串, HTTP狀態碼, 狀態, 最終網址,
                是否發送請求, 錯誤或警告訊息)。狀態字串為 'completed', 'warning' 或 'skip'。

        Raises:
          httpx.HTTPStatusError: 若 HTTP 回應狀態碼非 2xx 時拋出（預設由外層捕捉）。
          httpx.RequestError: 發生網路連線層級錯誤時拋出（預設由外層捕捉）。

        """
        current_url = url
        request_sent = False

        for _ in range(self.config.max_redirects):
            request_sent, current_url, result = self._fetch_single(current_url, request_sent, target_domains)
            if result:
                return result

        logger.warning("網址 %s 超過最大重導向次數", url)
        return None, None, "skip", current_url, request_sent, "超過最大重導向次數"

    def extract_links(self, html: str, base_url: str) -> list[str]:
        """從給定的 HTML 內容中擷取所有有效且絕對路徑的連結與外連資源（如超連結、script、stylesheet、iframe、img、embed、form、object 等）。

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

            tag_attr_map = {
                "a": "href",
                "link": "href",
                "script": "src",
                "iframe": "src",
                "img": "src",
                "embed": "src",
                "form": "action",
                "object": "data",
            }

            # 透過單次遍歷 HTML 樹來擷取所有標籤，大幅提升大型網頁的解析效能
            for tag in soup.find_all(list(tag_attr_map.keys())):
                attr = tag_attr_map.get(tag.name)
                if attr and tag.has_attr(attr):
                    raw_links.append(tag.get(attr))

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
        except (ValueError, TypeError, AttributeError, RecursionError) as e:
            logger.error("從 %s 擷取連結時發生錯誤: %s", base_url, e)
            return []

    def process_url(
        self, url: str, target_domains: list[str], trusted_domains: list[str]
    ) -> tuple[list[str], list[str], int | None, str, bool, str | None]:
        """處理單一網址，包含抓取網頁、擷取連結以及分類。

        Args:
            url (str): 準備處理的網址。
            target_domains (list[str]): 允許爬蟲進入的網域陣列。
            trusted_domains (list[str]): 被視為信任的網域陣列。指向這些網域以外的連結將被視為外部目標。

        Returns:
            tuple[list[str], list[str], int | None, str, bool, str | None]: (內部連結陣列, 外部目標連結陣列,
                HTTP 狀態碼, 最終狀態, 是否發送請求, 錯誤或警告訊息)。
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

    def _fallback_get(
        self, current_url: str, tgt_dom: str | None, ip: str | None, client: httpx.Client
    ) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """降級為 GET 請求以進行外部連結探測。

        Args:
            current_url (str): 當前外部網址。
            tgt_dom (str | None): 目標網域。
            ip (str | None): 解析出的 IP 位址。
            client (httpx.Client): HTTPX 客戶端物件。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        headers = {"Range": "bytes=0-1023"}
        if self.enable_dynamic_headers:
            headers.update(get_random_profile())
        stream_timeout = httpx.Timeout(self.config.external_check_timeout, connect=self.config.connect_timeout)
        with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
            with client.stream("GET", current_url, headers=headers, timeout=stream_timeout) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        return urljoin(current_url, location), None
                    return None, (resp.status_code, None)
                return None, (resp.status_code, None)

    def _execute_external_request(
        self, current_url: str, tgt_dom: str | None, ip: str | None
    ) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """執行 HEAD 或 GET 請求探測。

        Args:
            current_url (str): 當前外部網址。
            tgt_dom (str | None): 目標網域。
            ip (str | None): 解析出的 IP 位址。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        client = self._get_client(current_url)
        with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
            head_timeout = httpx.Timeout(self.config.external_check_timeout, connect=self.config.connect_timeout)
            headers = get_random_profile() if self.enable_dynamic_headers else None
            response = client.request("HEAD", current_url, timeout=head_timeout, headers=headers)

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if location:
                return urljoin(current_url, location), None
            return None, (response.status_code, None)

        is_social_media = tgt_dom and is_in_domain_list(tgt_dom.lower(), self.config.social_domains)
        if response.status_code in (400, 403, 405) or (response.status_code >= 400 and is_social_media):
            return self._fallback_get(current_url, tgt_dom, ip, client)
        return None, (response.status_code, None)

    def _check_external_single(self, current_url: str) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """單次外部連結檢查邏輯，攔截異常並回傳。

        Args:
            current_url (str): 準備進行探測的當前外部網址。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        try:
            tgt_dom = get_domain(current_url)
            ip = resolve_ip(tgt_dom) if tgt_dom else None
            if ip and not is_safe_ip(ip):
                return None, (None, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全")
            return self._execute_external_request(current_url, tgt_dom, ip)
        except httpx.HTTPStatusError as e:
            return None, (e.response.status_code, str(e))
        except httpx.RequestError as e:
            return None, (None, str(e))
        except (ValueError, socket.gaierror, TypeError, AttributeError, UnicodeError) as e:
            return None, (None, str(e))

    def check_external_link(self, url: str) -> tuple[int | None, str | None]:
        """對外部連結進行存活檢查。

        優先使用 HEAD 請求以節省流量。若遇到特定阻擋狀態碼或目標為社群平台，
        則自動降級為帶有 Range 標頭的 GET 請求，嘗試繞過反爬蟲機制。

        Args:
            url (str): 準備進行探測的外部網址。

        Returns:
            tuple[int | None, str | None]: 回傳 (HTTP 狀態碼, 錯誤訊息)。
        """
        current_url = url

        for _ in range(self.config.max_redirects):
            next_url, result = self._check_external_single(current_url)
            if result is not None:
                return result
            if next_url:
                current_url = next_url
                continue

        return None, "超過最大重導向次數限制"

    def close(self) -> None:
        """關閉底層的 HTTPX 客戶端連線。

        釋放底層連線池資源。建議在爬蟲任務結束時呼叫。

        """
        self.client.close()
        self.exempt_client.close()
