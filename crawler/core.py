"""
爬蟲核心邏輯模組，負責網頁抓取與解析。

此模組提供 CrawlerCore 類別，負責發送 HTTP 請求抓取網頁、
解析 HTML、擷取連結，並依據網域規則過濾與分類連結。
"""

# pylint: disable=too-many-lines

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

try:
    import h2  # noqa: F401 # pylint: disable=unused-import

    _HTTP2_SUPPORTED = True
except ImportError:
    _HTTP2_SUPPORTED = False

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

    Attributes:
        config (CrawlerConfig): 爬蟲引擎配置物件。
        ignore_regex_compiled (list[re.Pattern]): 預先編譯的忽略路徑正規表示式。
        enable_dynamic_headers (bool): 是否啟用動態標頭 (當未自訂 User-Agent 時)。
        user_agent (str): 使用的 User-Agent 標頭。
        client (httpx.Client): 預設的 HTTPX 客戶端。
        exempt_client (httpx.Client): 豁免 SSL 驗證的 HTTPX 客戶端。
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
            http2=_HTTP2_SUPPORTED,
            timeout=httpx.Timeout(self.config.timeout, connect=self.config.connect_timeout),
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
            proxy=self.config.proxy_url,
        )
        self.exempt_client: httpx.Client = httpx.Client(
            http2=_HTTP2_SUPPORTED,
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
        self, current_url: str, request_sent: bool, target_domains: list[str] | None, strip_sec_headers: bool = False
    ) -> tuple[bool, str, tuple[str | None, int | None, str, str, bool, str | None] | None]:
        """執行單次 fetch 流程，回傳 (request_sent, next_url, result_tuple)。

        Args:
            current_url (str): 當前網址。
            request_sent (bool): 標記此循環是否已實際發送過 HTTP 請求。
            target_domains (list[str] | None): 允許進入的目標網域清單。
            strip_sec_headers (bool): 是否拔除現代瀏覽器的 Sec-* 特徵標頭，用於繞過 WAF。

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
            headers = get_random_profile(current_url) if self.enable_dynamic_headers else None

            if headers and strip_sec_headers:
                keys_to_remove = {
                    "sec-ch-ua",
                    "sec-ch-ua-mobile",
                    "sec-ch-ua-platform",
                    "sec-fetch-dest",
                    "sec-fetch-mode",
                    "sec-fetch-site",
                    "sec-fetch-user",
                }
                for hk in list(headers.keys()):
                    if hk.lower() in keys_to_remove:
                        headers.pop(hk)

            with self._get_client(current_url).stream("GET", current_url, headers=headers) as response:
                next_url, result = self._process_response(response, current_url, target_domains)
                if result:
                    return True, current_url, result
                return True, next_url or current_url, None

    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
    def fetch(
        self, url: str, target_domains: list[str] | None = None
    ) -> tuple[str | None, int | None, str, str, bool, str | None]:
        """抓取給定網址的 HTML 內容。

        Args:
            url (str): 欲抓取的網址字串。
            target_domains (list[str] | None): 目標網域清單，用於防止重導向跨出邊界。

        Returns:
            tuple[str | None, int | None, str, str, bool, str | None]: (HTML字串, HTTP狀態碼, 狀態, 最終網址,
                是否發送請求, 錯誤或警告訊息)。狀態字串為 'completed', 'warning', 'skip' 或 'failed'。

        """
        # 注意：本方法已經封裝所有 httpx 相關的 RequestError 與 HTTPStatusError，
        # 並會轉化為 status='failed' 的 Tuple 回傳，不會再向外拋出例外。

        current_url = url
        request_sent = False

        for _ in range(self.config.max_redirects):
            try:
                request_sent, current_url, result = self._fetch_single(current_url, request_sent, target_domains)
                if result:
                    return result
            except (httpx.RequestError, socket.gaierror, httpx.HTTPStatusError) as e:
                status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                parsed = urlparse(current_url)

                # 1. 內部連結 HTTP 連線或狀態異常 (>=400)，自動升級至 HTTPS 重試
                if parsed.scheme == "http" and (status_code is None or status_code >= 400):
                    new_url = parsed._replace(scheme="https").geturl()
                    logger.info(
                        "內部連結 HTTP 連線或狀態異常 (%s)，嘗試自動升級至 HTTPS 並重試: %s",
                        status_code or type(e).__name__,
                        new_url,
                    )
                    try:
                        request_sent, current_url, result = self._fetch_single(new_url, request_sent, target_domains)
                        if result:
                            return result
                        continue  # 成功升級 HTTPS 並取得跳轉，繼續下一輪跳轉跟隨
                    except (httpx.RequestError, socket.gaierror, httpx.HTTPStatusError) as retry_e:
                        e = retry_e
                        status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                        current_url = new_url
                        logger.warning("HTTPS 重試亦失敗: %s", e)

                # 2. 如果遇到 WAF 經常阻擋的特定狀態碼，嘗試拔除 Sec-* 標頭再次重試
                if status_code in (400, 403, 405, 406, 501, 520):
                    logger.info("網址 %s 遇到 %s 阻擋，嘗試拔除特徵標頭再次重試...", current_url, status_code)
                    try:
                        request_sent, current_url, result = self._fetch_single(
                            current_url, request_sent, target_domains, strip_sec_headers=True
                        )
                        if result:
                            return result
                        continue  # 拔除標頭後成功取得跳轉，繼續下一輪跳轉跟隨，避免用過時的 status_code/e 誤判為失敗
                    except (httpx.RequestError, socket.gaierror, httpx.HTTPStatusError) as fallback_e:
                        e = fallback_e
                        status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None

                # 3. 終極 TLS 偽裝降級 (curl_cffi)
                if status_code in (400, 403, 405, 406, 520):
                    logger.info("網址 %s 拔除特徵仍受阻 (%s)，啟動終極 TLS 偽裝引擎...", current_url, status_code)
                    cffi_status, cffi_err, cffi_text, cffi_final_url = self._execute_curl_cffi_fallback(
                        current_url, is_internal=True
                    )
                    if cffi_status is not None and cffi_status < 400 and cffi_text is not None:
                        return cffi_text, cffi_status, "completed", cffi_final_url or current_url, True, None

                    status_code = cffi_status
                    e = Exception(cffi_err) if cffi_err else Exception(f"TLS 偽裝失敗，狀態碼 {cffi_status}")

                # 4. 封裝所有例外，不向外拋出，統一回傳狀態
                return None, status_code, "failed", current_url, request_sent, str(e)

            except (ValueError, TypeError, UnicodeError) as e:
                logger.warning("網址 %s 格式錯誤或無法解析: %s", current_url, e)
                return None, None, "failed", current_url, request_sent, f"網址格式無效: {e}"

        logger.warning("網址 %s 超過最大重導向次數", url)
        return None, None, "skip", current_url, request_sent, "超過最大重導向次數"

    def _extract_base_url(self, soup: BeautifulSoup, base_url: str) -> str:
        """解析 <base> 標籤以更新相對路徑的基準網址。

        Args:
            soup (BeautifulSoup): 已解析的 HTML 樹。
            base_url (str): 原始基準網址。

        Returns:
            str: 更新後（或維持原樣）的基準網址。
        """
        base_tag = soup.find("base", href=True)
        if base_tag:
            href_val = base_tag.get("href")
            if isinstance(href_val, str) and href_val.strip():
                return urljoin(base_url, href_val.strip())
        return base_url

    def _collect_raw_links(self, soup: BeautifulSoup) -> list[object]:
        """遍歷 HTML 樹以收集可能包含網址的屬性值。

        Args:
            soup (BeautifulSoup): 已解析的 HTML 樹。

        Returns:
            list[object]: 收集到的原始網址屬性值清單。
        """
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
            # 針對 <link> 標籤，忽略 dns-prefetch 與 preconnect。
            # 這些標籤通常只指向網域根目錄（如 https://fonts.gstatic.com/）作為提早連線提示，並非實際可下載的資源，探測其根目錄通常會得到 404。
            if tag.name == "link":
                rel_attr = tag.get("rel", [])
                rel_list = [rel_attr] if isinstance(rel_attr, str) else (rel_attr or [])
                if any(r.lower() in ("preconnect", "dns-prefetch") for r in rel_list):
                    continue

            attr = tag_attr_map.get(tag.name)
            if attr and tag.has_attr(attr):
                raw_links.append(tag.get(attr))
        return raw_links

    def _normalize_and_filter_link(self, attr_val: object, base_url: str) -> str | None:
        """對原始網址屬性值進行正規化、排除無效連結與非 HTTP/HTTPS 協議的連結。

        Args:
            attr_val (object): 原始網址屬性值。
            base_url (str): 正規化時使用的基準網址。

        Returns:
            str | None: 正規化且驗證通過的 HTTP/HTTPS 網址，若不符則回傳 None。
        """
        if isinstance(attr_val, list):
            val_str = attr_val[0] if attr_val else ""
        else:
            val_str = attr_val

        if not isinstance(val_str, str):
            return None

        href: str = val_str.strip()
        # 排除 javascript, mailto 等非 http(s) 的錨點連結
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            return None

        normalized_link: str = normalize_url(href, base_url)

        # 進行基礎驗證，確保為有效的 HTTP/HTTPS 網址
        parsed: ParseResult = urlparse(normalized_link)
        if parsed.scheme in ("http", "https"):
            return normalized_link
        return None

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
            base_url = self._extract_base_url(soup, base_url)
            raw_links = self._collect_raw_links(soup)

            links: list[str] = []
            for attr_val in raw_links:
                normalized = self._normalize_and_filter_link(attr_val, base_url)
                if normalized:
                    links.append(normalized)

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

            # 規則 2: 找出連向 (信任網域 + 目標網域) 以外的外部網址 (凡是目標網域，自動視為信任網域)
            if not is_in_domain_list(domain, trusted_domains) and not is_in_domain_list(domain, target_domains):
                external_target_links.append(link)

        return internal_links, external_target_links, status_code, status, request_sent, err_msg

    def _execute_curl_cffi_fallback(
        self, url: str, is_internal: bool = False
    ) -> tuple[int | None, str | None, str | None, str | None]:
        """終極備援核心邏輯：使用 curl_cffi 進行 TLS 指紋偽裝。

        Args:
            url (str): 目標網址。
            is_internal (bool): 是否為內部抓取（需要防 OOM 與 MIME 驗證並回傳內容）。

        Returns:
            tuple[int | None, str | None, str | None, str | None]:
                (status_code, error_msg, content_text, final_url)。
                final_url 反映 curl_cffi 內部 allow_redirects=True 自動跟隨完整重導向鏈後
                的實際落點，供呼叫端 (fetch()) 作為解析 HTML 內相對路徑連結的正確基準網址；
                若請求從未實際送出 (例如未安裝 curl_cffi)，則退回傳入的原始 url。
        """
        try:
            # pylint: disable=import-outside-toplevel
            from curl_cffi import requests as cffi_requests
            from curl_cffi.requests.errors import CurlError as CFFICurlError
            from curl_cffi.requests.errors import RequestsError as CFFIRequestsError

            # 1. SSRF 驗證防護
            domain = get_domain(url)
            ip, ssrf_err = self._resolve_and_check_ssrf(domain, url)
            if ssrf_err:
                logger.warning("TLS 偽裝降級遭到 SSRF 防護攔截: %s", ssrf_err)
                return None, ssrf_err, None, url

            logger.info("啟動 TLS 偽裝備援引擎 (curl_cffi) 探測: %s", url)
            proxies = None
            if self.config.proxy_url:
                proxies = {"http": self.config.proxy_url, "https": self.config.proxy_url}

            stream = is_internal

            with dns_override(domain, ip) if domain and ip else nullcontext():
                resp = cffi_requests.get(
                    url,
                    impersonate="chrome120",
                    timeout=self.config.external_check_timeout,
                    allow_redirects=True,
                    proxies=proxies,
                    stream=stream,
                )

            status_code = resp.status_code
            # resp.url 反映 allow_redirects=True 自動跟隨完整重導向鏈後的最終落點
            final_url = resp.url or url

            if not is_internal:
                resp.close()
                return status_code, None, None, final_url

            if status_code >= 400:
                resp.close()
                return status_code, f"HTTP 狀態異常: {status_code}", None, final_url

            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                resp.close()
                return status_code, f"MIME 類型不符 (非 HTML): {content_type}", None, final_url

            content_bytes = bytearray()
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    content_bytes.extend(chunk)
                    if len(content_bytes) > self.config.max_content_length:
                        logger.warning(
                            "網頁容量超過上限 (%s bytes)，內容已被提早截斷: %s",
                            self.config.max_content_length,
                            url,
                        )
                        break
            resp.close()

            try:
                text = content_bytes.decode(resp.encoding or "utf-8", errors="replace")
            except LookupError:
                text = content_bytes.decode("utf-8", errors="replace")

            return status_code, None, text, final_url

        except ImportError:
            logger.warning("未安裝 curl_cffi，無法執行 TLS 偽裝降級")
            return None, "未安裝 curl_cffi", None, url
        except (CFFICurlError, CFFIRequestsError) as e:
            logger.warning("TLS 偽裝備援探測失敗: %s", e)
            cffi_resp = getattr(e, "response", None)
            status_code = getattr(cffi_resp, "status_code", None) if cffi_resp is not None else None
            return status_code, f"TLS 偽裝探測失敗: {e}", None, url
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("TLS 偽裝備援遭遇未預期底層例外: %s", type(e).__name__)
            return None, f"TLS 偽裝發生底層異常: {e}", None, url

    def _tls_spoofed_fallback(self, url: str) -> tuple[int | None, str | None]:
        """外部探測專用的 TLS 指紋偽裝降級包裹方法。"""
        status_code, err_msg, _, _ = self._execute_curl_cffi_fallback(url, is_internal=False)
        return status_code, err_msg

    # pylint: disable=too-many-arguments
    def _fallback_get(
        self,
        current_url: str,
        tgt_dom: str | None,
        ip: str | None,
        client: httpx.Client,
        accumulated_cookies: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """降級為 GET 請求以進行外部連結探測。

        Args:
            current_url (str): 當前外部網址。
            tgt_dom (str | None): 目標網域。
            ip (str | None): 解析出的 IP 位址。
            client (httpx.Client): HTTPX 客戶端物件。
            accumulated_cookies (dict[str, dict[str, str]] | None):
                依網域分桶的跨跳共用 Cookie 字典 (domain -> {name: value})，傳入方式為引用。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        # 移除 Range: bytes=0-1023 標頭，因為部分 IIS 伺服器與 WAF
        # 對於帶有 Range 標頭的動態網頁 (.aspx) 請求會誤判並直接回傳 404/400。
        # 由於使用 client.stream()，讀取完標頭後連線即會中斷，因此不加 Range 依然能達到節省頻寬的效果。
        headers: dict[str, str] = {}
        if self.enable_dynamic_headers:
            headers.update(get_random_profile(current_url))

            # WAF 常會因為 HTTP/1.1 卻帶有現代瀏覽器的 Sec-Fetch 標頭而判定為異常 (403 阻擋)。
            # 在降級探測時，拔除這些標頭以降低異常特徵，提升繞過成功率。
            keys_to_remove = {
                "sec-ch-ua",
                "sec-ch-ua-mobile",
                "sec-ch-ua-platform",
                "sec-fetch-dest",
                "sec-fetch-mode",
                "sec-fetch-site",
                "sec-fetch-user",
            }
            for hk in list(headers.keys()):
                if hk.lower() in keys_to_remove:
                    headers.pop(hk)

        # 外部探測不需下載網頁內容，大膽宣告支援現代壓縮格式，可繞過部分嚴格 WAF
        # 此行放在 get_random_profile() 套用之後，確保不會被 profile 自帶的 Accept-Encoding 值覆蓋掉
        headers["Accept-Encoding"] = "gzip, deflate, br, zstd"

        # 直接將 Cookie 寫入請求標頭，避免使用 httpx 已棄用的 per-request cookies 參數
        # (該參數具有不確定行為且可能不實際傳送 Cookie 到伺服器)
        domain_cookies = self._get_applicable_cookies(tgt_dom, accumulated_cookies)
        if domain_cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in domain_cookies.items())

        stream_timeout = httpx.Timeout(self.config.external_check_timeout, connect=self.config.connect_timeout)
        with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
            with client.stream("GET", current_url, headers=headers, timeout=stream_timeout) as resp:
                # 從回應標頭收集 Set-Cookie，依據其定義的 domain 寫入共用的 accumulated_cookies
                if accumulated_cookies is not None:
                    for c in resp.cookies.jar:
                        if c.value is not None:
                            # 若未顯式帶有 Domain 屬性，預設歸屬目標網域
                            c_dom = c.domain.lstrip(".") if c.domain else tgt_dom
                            if c_dom:
                                accumulated_cookies.setdefault(c_dom, {})[c.name] = c.value

                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        return urljoin(current_url, location), None
                    return None, (resp.status_code, None)
                return None, (resp.status_code, None)

    def _get_applicable_cookies(
        self, tgt_dom: str | None, accumulated_cookies: dict[str, dict[str, str]] | None
    ) -> dict[str, str]:
        """從分桶 Cookie 字典中獲取適用於特定網域的 Cookie。

        支援子網域繼承父網域的萬用字元 Cookie (例如 .elearn.hrd.gov.tw 適用於 acs.elearn.hrd.gov.tw)。
        """
        if not accumulated_cookies or not tgt_dom:
            return {}
        applicable = {}
        # 按照網域長度排序（從短到長），讓子網域的 Cookie 可以覆寫父網域的同名 Cookie
        sorted_keys = sorted(accumulated_cookies.keys(), key=len)
        for k in sorted_keys:
            k_clean = k.lstrip(".")
            if tgt_dom == k_clean or tgt_dom.endswith("." + k_clean):
                applicable.update(accumulated_cookies[k])
        return applicable

    def _execute_external_request(
        self,
        current_url: str,
        tgt_dom: str | None,
        ip: str | None,
        accumulated_cookies: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """執行 HEAD 或 GET 請求探測。

        注意：本方法刻意不呼叫 response.raise_for_status()，所有狀態碼 (包含 4xx/5xx)
        皆視為正常回應並回傳，由呼叫端決定如何處理。若未來新增 raise_for_status() 呼叫，
        需同步在 _check_external_single 補上 httpx.HTTPStatusError 的例外處理。

        Args:
            current_url (str): 當前外部網址。
            tgt_dom (str | None): 目標網域。
            ip (str | None): 解析出的 IP 位址。
            accumulated_cookies (dict[str, dict[str, str]] | None):
                依網域分桶的跨跳共用 Cookie 字典 (domain -> {name: value})，傳入方式為引用。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        client = self._get_client(current_url)
        domain_cookies = self._get_applicable_cookies(tgt_dom, accumulated_cookies)

        with dns_override(tgt_dom, ip) if tgt_dom and ip else nullcontext():
            head_timeout = httpx.Timeout(self.config.external_check_timeout, connect=self.config.connect_timeout)
            headers = get_random_profile(current_url) if self.enable_dynamic_headers else {}
            # 外部探測不需下載網頁內容，大膽宣告支援現代壓縮格式
            headers["Accept-Encoding"] = "gzip, deflate, br, zstd"

            # 直接將 Cookie 寫入請求標頭，避免使用 httpx 已棄用的 per-request cookies 參數
            if domain_cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in domain_cookies.items())

            try:
                response = client.request("HEAD", current_url, timeout=head_timeout, headers=headers)
            except httpx.RequestError as e:
                # WAF 經常以 Tarpit (刻意不回應導致超時) 或直接切斷連線來阻擋帶有現代瀏覽器特徵的 HEAD 請求。
                # 當 HEAD 請求發生網路層異常時，主動降級使用剝離衝突特徵的 GET 請求進行二次確認。
                logger.debug("HEAD 請求發生網路層異常 (%s)，嘗試降級使用 GET...", e)
                return self._fallback_get(current_url, tgt_dom, ip, client, accumulated_cookies)

        # 將 HEAD 回應的 Set-Cookie 合併回正確的網域桶中
        if accumulated_cookies is not None:
            for c in response.cookies.jar:
                if c.value is not None:
                    c_dom = c.domain.lstrip(".") if c.domain else tgt_dom
                    if c_dom:
                        accumulated_cookies.setdefault(c_dom, {})[c.name] = c.value

        if response.status_code in (301, 302, 303, 307, 308):
            # HEAD 的重導向結果在許多伺服器上並不可靠：可能是 Cookie-gate 要求重新帶
            # Cookie 確認 (如 Citrix NetScaler)，也可能是伺服器單純不支援 HEAD 重導向、
            # 固定回傳錯誤的 Location 造成彈跳 (即使完全沒有 Cookie 涉入)。兩種情況的
            # 共同解法相同：不論是否持有 Cookie，一律改用 GET 對同一網址重新確認，
            # 取得可信的結果或正確的下一步網址，而不是冒險信任 HEAD 給出的 Location。
            return self._fallback_get(current_url, tgt_dom, ip, client, accumulated_cookies)

        is_social_media = tgt_dom and is_in_domain_list(tgt_dom.lower(), self.config.social_domains)
        # 許多伺服器 (如 IIS) 對 HEAD 請求的轉址設定不完整，可能直接回傳 404 或 405。
        # 將 404 等常見誤判狀態碼納入降級條件，若 HEAD 遇到 404 將以 GET (Stream) 二次確認。
        if response.status_code in (400, 403, 404, 405, 406, 500, 501, 502, 503, 504) or (
            response.status_code >= 400 and is_social_media
        ):
            return self._fallback_get(current_url, tgt_dom, ip, client, accumulated_cookies)
        return None, (response.status_code, None)

    def _check_external_single(
        self,
        current_url: str,
        accumulated_cookies: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str | None, tuple[int | None, str | None] | None]:
        """單次外部連結檢查邏輯，攔截異常並回傳。

        Args:
            current_url (str): 準備進行探測的當前外部網址。
            accumulated_cookies (dict[str, dict[str, str]] | None):
                依網域分桶的跨跳共用 Cookie 字典 (domain -> {name: value})，傳入方式為引用。

        Returns:
            tuple[str | None, tuple | None]: (重導向的下一步網址, 回傳狀態結果的 tuple)。
        """
        try:
            tgt_dom = get_domain(current_url)
            ip = resolve_ip(tgt_dom) if tgt_dom else None
            if ip and not is_safe_ip(ip):
                return None, (None, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全")
            return self._execute_external_request(current_url, tgt_dom, ip, accumulated_cookies)
        except httpx.RequestError as e:
            return None, (None, str(e))
        except (ValueError, socket.gaierror, TypeError, AttributeError, UnicodeError) as e:
            return None, (None, str(e))

    def _handle_http_failure_retry(
        self,
        current_url: str,
        original_result: tuple[int | None, str | None],
        accumulated_cookies: dict[str, dict[str, str]] | None = None,
    ) -> tuple[str | None, tuple[int | None, str | None] | None, bool]:
        """當 HTTP 外部連結探測失敗時，嘗試升級至 HTTPS 並重新探測。

        Args:
            current_url (str): 當前探測的網址。
            original_result (tuple[int | None, str | None]): 原始探測結果。
            accumulated_cookies (dict[str, dict[str, str]] | None):
                依網域分桶的跨跳共用 Cookie 字典 (domain -> {name: value})，傳入方式為引用。

        Returns:
            tuple[str | None, tuple[int | None, str | None] | None, bool]:
                (重導向新網址, 最終探測結果, 是否因 HTTPS 連線徹底失敗才退回原始結果)。
                第三個值刻意以明確旗標表示「是否退回」，而非讓呼叫端用 result_retry 是否
                等於 original_result 來猜測：HTTP 與 HTTPS 兩次探測即使各自獨立成功，
                也可能恰好回傳完全相同的 (status_code, None) (例如同一套 WAF 規則同時
                擋下兩種協定，這其實是最常見的情況)，此時不該被誤判為「HTTPS 連線失敗」
                而放棄後續的 TLS 偽裝降級機會。
        """
        parsed = urlparse(current_url)
        if parsed.scheme != "http":  # 防衛性檢查：額外保護，避免誤用。
            return None, None, False

        new_url = parsed._replace(scheme="https").geturl()
        logger.info("HTTP 檢測失敗，嘗試自動升級至 HTTPS: %s", new_url)

        next_url_retry, result_retry = self._check_external_single(new_url, accumulated_cookies)

        if result_retry is not None:
            status_code_retry, err_msg_retry = result_retry
            # 若 HTTPS 連線徹底失敗 (無狀態碼)，保留原始 HTTP 檢測結果，並明確標記為
            # 「因連線失敗而退回」，避免呼叫端誤判而繼續嘗試已知連不上的 TLS 偽裝降級
            if status_code_retry is None:
                logger.info("HTTPS 重試失敗: %s", err_msg_retry)
                return None, original_result, True
            # 若 HTTPS 有取得狀態碼（即使是 4xx/5xx），就取代原本 HTTP 結果
            return None, result_retry, False

        if next_url_retry:
            return next_url_retry, None, False

        return None, None, False

    def check_external_link(self, url: str) -> tuple[int | None, str | None]:
        """對外部連結進行存活檢查。

        優先使用 HEAD 請求以節省流量。若 HEAD 回傳任何重導向 (3xx)、特定阻擋狀態碼，
        或目標為社群平台，則一律自動降級為 GET 請求重新確認——因為 HEAD 在許多伺服器
        上對這些情況的回應並不可靠 (無論是否涉及 Cookie-gate 防護)，直接信任 HEAD 給出
        的 Location 可能造成重導向迴圈或誤判。

        部分網站（如採用 Citrix NetScaler / Cookie-gate 防護的站台）會在重導向時設定
        驗證 Cookie，並要求後續請求必須攜帶該 Cookie 才能取得正式回應。本方法在重導向
        迴圈中會自動收集並傳遞跨跳的 Set-Cookie，並依目標網域分桶儲存，確保每一跳只會
        帶上與當前目標網域相符的 Cookie，避免重導向跨網域時夾帶不相關 Cookie 送出。

        如果經過 HEAD/GET 探測與 HTTP 升級重試後，依然遭遇常見的企業級 WAF 或 Cloudflare
        阻擋碼 (如 403, 520)，系統將作為最後防線啟動 TLS 指紋偽裝降級 (curl_cffi)，使用
        100% 擬真的瀏覽器 TLS/HTTP2 特徵來完成探測，徹底消弭高階機器人防護盾導致的誤判。

        Args:
            url (str): 準備進行探測的外部網址。

        Returns:
            tuple[int | None, str | None]: 回傳 (HTTP 狀態碼, 錯誤訊息)。
        """
        current_url = url
        # 跨跳共用的 Cookie 字典，用於繞過 Cookie-gate 防爬蟲機制。
        # 使用普通 dict 並以引用方式傳遞，避免 httpx 已棄用的 per-request cookies 參數。
        # 內部各方法直接寫入 accumulated_cookies，不需要回傳值。
        accumulated_cookies: dict[str, dict[str, str]] = {}

        for _ in range(self.config.max_redirects):
            # next_url: 重導向的下一步網址 (None 表示沒有重導向), result: 回傳狀態結果 (None 表示有重導向，尚未取得最終結果)
            next_url, result = self._check_external_single(current_url, accumulated_cookies)

            if result is not None:
                # 許多現代網站與防火牆 (Cloudflare, HSTS) 對明文 HTTP 請求會直接中斷或回傳 403/520
                # 若遇到連線錯誤 (status_code is None) 或是 WAF / 伺服器回傳異常 (>= 400)
                # 可對明文 HTTP 連結嘗試升級至 HTTPS 重試；HTTPS 有結果則回傳，重導向則繼續
                status_code, err_msg = result
                is_failed = (status_code is None and err_msg) or (status_code is not None and status_code >= 400)

                if is_failed and urlparse(current_url).scheme == "http":
                    next_url_retry, result_retry, fell_back = self._handle_http_failure_retry(
                        current_url, result, accumulated_cookies
                    )
                    if result_retry is not None:
                        # fell_back 為 True 代表 HTTPS 連線層級徹底失敗 (無狀態碼)，
                        # 該站不支援 HTTPS 或無法連線，不應再嘗試 TLS 偽裝降級
                        if fell_back:
                            return result_retry

                        status_code_retry, err_msg_retry = result_retry
                        is_retry_failed = (status_code_retry is None and err_msg_retry) or (
                            status_code_retry is not None and status_code_retry >= 400
                        )

                        # 終極 TLS 偽裝降級 (curl_cffi)
                        if is_retry_failed and status_code_retry in (400, 403, 405, 406, 520):
                            new_url = urlparse(current_url)._replace(scheme="https").geturl()
                            return self._tls_spoofed_fallback(new_url)

                        return result_retry

                    if next_url_retry:
                        current_url = next_url_retry
                        continue

                # 如果一開始就是 HTTPS 且遭遇 WAF 阻擋，啟動終極 TLS 偽裝降級
                if is_failed and status_code in (400, 403, 405, 406, 520):
                    return self._tls_spoofed_fallback(current_url)

                return result

            if next_url:
                current_url = next_url
                continue

        return None, "超過最大重導向次數"

    def close(self) -> None:
        """關閉底層的 HTTPX 客戶端連線。

        釋放底層連線池資源。建議在爬蟲任務結束時呼叫。
        """
        self.client.close()
        self.exempt_client.close()
