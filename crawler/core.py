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
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, cast
from urllib.parse import ParseResult, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from crawler.models import CrawlerConfig
from crawler.profiles import get_random_profile
from crawler.utils import get_domain, is_in_domain_list, is_safe_ip, normalize_url, resolve_ip

if TYPE_CHECKING:
    from curl_cffi.requests import BrowserTypeLiteral, ProxySpec

try:
    import h2  # noqa: F401 # pylint: disable=unused-import

    _HTTP2_SUPPORTED: bool = True
except ImportError:
    _HTTP2_SUPPORTED = False

logger: logging.Logger = logging.getLogger(__name__)

#: REDIRECT_STATUS_CODES: HTTP 重導向狀態碼清單。
REDIRECT_STATUS_CODES: tuple[int, ...] = (301, 302, 303, 307, 308)
#: WAF_STATUS_CODES: 偵測到 WAF 攔截的狀態碼清單。
WAF_STATUS_CODES: tuple[int, ...] = (400, 403, 405, 406, 501, 520, 555)
#: TLS_SPOOF_STATUS_CODES: 需要觸發 TLS 偽裝的狀態碼清單。
TLS_SPOOF_STATUS_CODES: tuple[int | None, ...] = (None, 400, 403, 405, 406, 520, 555)
#: HEAD_FALLBACK_STATUS_CODES: 在 GET 請求失敗後，嘗試使用 HEAD 請求恢復的狀態碼清單。
HEAD_FALLBACK_STATUS_CODES: tuple[int, ...] = (400, 403, 404, 405, 406, 500, 501, 502, 503, 504, 555)
#: _FETCH_SAFE_EXCEPTIONS: 抓取網頁時可安全攔截並忽略的例外型別。
_FETCH_SAFE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.RequestError,
    httpx.HTTPStatusError,
    httpx.InvalidURL,
    socket.gaierror,
    ValueError,
    TypeError,
    UnicodeError,
    LookupError,
)

# 實作執行緒安全的 DNS 解析攔截器 (Monkey Patch)
_original_getaddrinfo = socket.getaddrinfo
_dns_override: threading.local = threading.local()


def _patched_getaddrinfo(  # pylint: disable=too-many-arguments
    host: str | bytes | None,
    port: str | int | None,
    family: int = 0,
    type_attr: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int] | tuple[str, int, int, int]]]:  # pylint: disable=no-member
    """攔截 socket.getaddrinfo 以支援自訂 DNS 解析。"""
    if host is None:
        return _original_getaddrinfo(host, port, family, type_attr, proto, flags)

    overrides = getattr(_dns_override, "overrides", {})
    host_str = host.decode("utf-8") if isinstance(host, bytes) else host
    if host_str in overrides:
        return _original_getaddrinfo(overrides[host_str], port, family, type_attr, proto, flags)
    return _original_getaddrinfo(host, port, family, type_attr, proto, flags)


socket.getaddrinfo = _patched_getaddrinfo  # type: ignore[assignment]


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
        _dynamic_impersonate_profiles (list[str] | None): 暫存的動態瀏覽器指紋輪替清單。
    """

    _dynamic_impersonate_profiles: list[str] | None = None

    @classmethod
    def get_dynamic_impersonate_profiles(cls) -> list[str]:
        """動態讀取 curl_cffi 支援的最新版瀏覽器指紋輪替清單。

        Returns:
            list[str]: 包含最新 Chrome, Safari 與 Edge 指紋字串的列表。
        """
        if cls._dynamic_impersonate_profiles is not None:
            return cls._dynamic_impersonate_profiles

        try:
            from curl_cffi import requests  # pylint: disable=import-outside-toplevel

            browsers = [b.name for b in requests.BrowserType]
            chrome_versions = []
            safari_versions = []
            edge_versions = []

            for b in browsers:
                # 排除行動裝置特徵以符合一般電腦版的偽裝情境
                if "android" in b.lower() or "ios" in b.lower():
                    continue

                if b.startswith("chrome"):
                    match = re.search(r"chrome(\d+)", b)
                    if match:
                        chrome_versions.append((int(match.group(1)), b))
                elif b.startswith("safari"):
                    match = re.search(r"safari(\d+(_\d+)*)", b)
                    if match:
                        ver_tuple = tuple(map(int, match.group(1).split("_")))
                        safari_versions.append((ver_tuple, b))
                elif b.startswith("edge"):
                    match = re.search(r"edge(\d+)", b)
                    if match:
                        edge_versions.append((int(match.group(1)), b))

            chrome_latest = max(chrome_versions, key=lambda x: x[0])[1] if chrome_versions else "chrome120"
            # 取得最新版本的 Safari 指紋
            safari_latest = max(safari_versions, key=lambda x: x[0])[1] if safari_versions else "safari15_3"
            edge_latest = max(edge_versions, key=lambda x: x[0])[1] if edge_versions else "edge101"

            cls._dynamic_impersonate_profiles = [chrome_latest, safari_latest, edge_latest]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("動態解析 curl_cffi 瀏覽器指紋失敗，退回預設名單: %s", e)
            cls._dynamic_impersonate_profiles = ["chrome120", "safari15_3", "edge101"]

        return cls._dynamic_impersonate_profiles

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

    def close(self) -> None:
        """關閉 HTTP 客戶端，釋放連線池資源。"""
        self.client.close()
        self.exempt_client.close()

    def __enter__(self) -> "CrawlerCore":
        """進入 context manager，支援 with 語句。

        Returns:
            CrawlerCore: 回傳自身實例。
        """
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """離開 context manager，自動關閉連線池。

        Args:
            exc_type (object): 例外型別。
            exc_val (object): 例外物件。
            exc_tb (object): 例外追蹤資訊。
        """
        self.close()

    @staticmethod
    def _safe_decode(content_bytes: bytes, charset: str) -> str:
        """安全地解碼位元組，避免未知的編碼名稱引發 LookupError。

        Args:
            content_bytes (bytes): 欲解碼的位元組資料。
            charset (str): 預期的字元編碼名稱。

        Returns:
            str: 解碼後的字串。
        """
        try:
            return content_bytes.decode(charset, errors="replace")
        except LookupError:
            return content_bytes.decode("utf-8", errors="replace")

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
        if ip is None:
            logger.warning("網址 %s 的網域無法解析 IP (Dead Link)", url)
            return None, "DNS 解析失敗 (Dead Link)"

        if not is_safe_ip(ip):
            logger.warning("網址 %s 的 IP (%s) 被判定為不安全，已攔截潛在的 SSRF 攻擊！", url, ip)
            return ip, f"SSRF 防禦攔截：目標 IP ({ip}) 不安全"
        return ip, None

    def _handle_redirect(
        self, response: httpx.Response, current_url: str, target_domains: list[str] | None
    ) -> tuple[str | None, tuple[str | list[str] | None, int | None, str, str, bool, str | None] | None]:
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
            logger.warning("網址 %s 回傳 3xx 但缺少 Location 標頭", current_url)
            return None, (None, response.status_code, "failed", current_url, True, "重導向但無 Location 標頭")

        next_url = urljoin(current_url, location)
        if target_domains:
            next_domain = get_domain(next_url)
            if next_domain and not is_in_domain_list(next_domain, target_domains):
                logger.info("網址 %s 重導向至外部網域 %s，停止深入抓取", current_url, next_url)
                return None, (
                    [next_url],
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
            allowed_types_raw = self.config.mime_type_filter.get("allowed_types", ["text/html"])
            allowed_types: list[str] = allowed_types_raw if isinstance(allowed_types_raw, list) else ["text/html"]
            if not any(str(allowed).lower() in content_type for allowed in allowed_types):
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
        text = self._safe_decode(content_bytes, charset)
        return text, err_msg

    def _process_response(
        self, response: httpx.Response, current_url: str, target_domains: list[str] | None
    ) -> tuple[str | None, tuple[str | list[str] | None, int | None, str, str, bool, str | None] | None]:
        """處理 HTTP 回應，回傳 (next_url, 提前回傳的結果)。

        Args:
            response (httpx.Response): HTTP 回應物件。
            current_url (str): 當前網址。
            target_domains (list[str] | None): 允許進入的目標網域清單。

        Returns:
            tuple[str | None, tuple | None]: (下一步網址, 提前回傳的結果)。
        """
        if response.status_code in REDIRECT_STATUS_CODES:
            return self._handle_redirect(response, current_url, target_domains)

        response.raise_for_status()

        if mime_err := self._check_mime_type(response, current_url):
            return None, (None, response.status_code, "skip", current_url, True, mime_err)

        text, err_msg = self._download_content(response, current_url)
        status = "warning" if err_msg else "completed"
        return None, (text, response.status_code, status, current_url, True, err_msg)

    def _fetch_single(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches
        self,
        current_url: str,
        request_sent: bool,
        target_domains: list[str] | None,
        accumulated_cookies: dict[str, dict[str, str]] | None = None,
        strip_sec_headers: bool = False,
    ) -> tuple[bool, str, tuple[str | list[str] | None, int | None, str, str, bool, str | None] | None]:
        """執行單次 HTTP 探測流程 (不含降級重試)，回傳狀態與下一步網址。

        涵蓋 SSRF 防護、MIME 類型驗證、跨域攔截與串流分塊下載機制。
        若遭遇 HTTP 重導向，會驗證是否跨越 `target_domains` 邊界；
        若內容為 HTML，則進行串流下載並防範大檔案 OOM 記憶體溢出。

        Args:
            current_url (str): 當前準備請求的網址。
            request_sent (bool): 標記此循環是否已實際發送過 HTTP 請求。
            target_domains (list[str] | None): 允許進入的目標網域清單。
            accumulated_cookies (dict[str, dict[str, str]] | None): 累積的分桶 cookies。
            strip_sec_headers (bool): 是否拔除現代瀏覽器的 Sec-* 特徵標頭，用於繞過 WAF。

        Returns:
            tuple[bool, str, tuple | None]:
                - request_sent (bool): 是否已實際發送請求
                - next_url (str): 重導向後的下一步網址 (若無則為原網址)
                - result_tuple (tuple | None): 若探測已完成 (如成功取得內容、或確定失敗/略過)，則回傳提早終止的結果。
        """
        if ignore_reason := self._check_ignore_rules(current_url):
            return request_sent, current_url, (None, None, "skip", current_url, request_sent, ignore_reason)

        domain = get_domain(current_url)
        ip, ssrf_err = self._resolve_and_check_ssrf(domain, current_url)
        if ssrf_err:
            return request_sent, current_url, (None, None, "failed", current_url, request_sent, ssrf_err)

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

            # 跨跳轉累積 Cookie
            applicable_cookies = self._get_applicable_cookies(domain, accumulated_cookies)
            if applicable_cookies:
                if headers is None:
                    headers = {}
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in applicable_cookies.items())

            with self._get_client(current_url).stream("GET", current_url, headers=headers) as response:
                next_url, result = self._process_response(response, current_url, target_domains)

                # 跨越安全邊界檢查：從未驗證網域跳轉至需驗證網域，存在 MITM Cookie 注入風險
                mitm_risk = False
                if next_url and next_url != current_url:
                    current_domain = domain
                    next_domain = get_domain(next_url)
                    was_exempt = current_domain and is_in_domain_list(current_domain, self.config.ssl_exempt_domains)
                    will_be_exempt = next_domain and is_in_domain_list(next_domain, self.config.ssl_exempt_domains)

                    if was_exempt and not will_be_exempt:
                        logger.warning(
                            "【資安邊界警告】網址 %s (SSL 豁免) 重導向至非豁免網域 %s，"
                            "為防止 Cookie 污染，已阻斷該次跳轉的狀態繼承。",
                            current_url,
                            next_url,
                        )
                        mitm_risk = True

                if accumulated_cookies is not None and not mitm_risk:
                    for c in response.cookies.jar:
                        if c.value is not None:
                            c_dom = c.domain.lstrip(".") if c.domain else domain
                            if c_dom:
                                accumulated_cookies.setdefault(c_dom, {})[c.name] = c.value

                if result:
                    return True, current_url, result
                return True, next_url or current_url, None

    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
    def fetch(
        self, url: str, target_domains: list[str] | None = None
    ) -> tuple[str | list[str] | None, int | None, str, str, bool, str | None]:
        """主動抓取網頁內容，處理重導向與多階層異常容錯。

        這是內部網頁爬取的主要進入點。包含了：
        1. 最大重導向追蹤 (max_redirects)
        2. 指數退避 (Exponential Backoff) 的隨機抖動重試
        3. 網路異常與 WAF 阻擋防護 (HTTP 自動升級、標頭拔除、curl_cffi 終極 TLS 偽裝)

        Args:
            url (str): 欲抓取的起點網址。
            target_domains (list[str] | None): 目標網域清單，用於防止重導向跨出邊界。若為 None 則不限制。

        Returns:
            tuple[str | None, int | None, str, str, bool, str | None]:
                - HTML 字串 (若跨域則為假標籤字串，失敗則為 None)
                - HTTP 狀態碼
                - 狀態字串 ('completed', 'failed', 'skip', 'warning')
                - 最終落點網址
                - 是否有發出真實請求 (bool)
                - 錯誤或警告訊息
        """
        # 注意：本方法已經封裝所有 httpx 相關的 RequestError 與 HTTPStatusError，
        # 並會轉化為 status='failed' 的 Tuple 回傳，不會再向外拋出例外。

        current_url = url
        request_sent = False
        accumulated_cookies: dict[str, dict[str, str]] = {}

        for _ in range(self.config.max_redirects + 1):
            try:
                request_sent, current_url, result = self._fetch_single(
                    current_url, request_sent, target_domains, accumulated_cookies
                )
                if result:
                    return result
            except _FETCH_SAFE_EXCEPTIONS as e:
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                parsed = urlparse(current_url)

                if isinstance(e, (ValueError, TypeError, UnicodeError, LookupError)):
                    # 這些是資料解析或格式錯誤，降級重試無效
                    logger.warning("網址 %s 格式錯誤或無法解析: %s", current_url, e)
                    return None, None, "failed", current_url, request_sent, f"無效或無法解析的內容: {e}"

                # 1. 內部連結 HTTP 連線或狀態異常 (>=400)，自動升級至 HTTPS 重試
                if parsed.scheme == "http" and (status_code is None or status_code >= 400):
                    new_url = parsed._replace(scheme="https").geturl()
                    logger.info(
                        "內部連結 HTTP 連線或狀態異常 (%s)，嘗試自動升級至 HTTPS 並重試: %s",
                        status_code or type(e).__name__,
                        new_url,
                    )
                    try:
                        request_sent, current_url, result = self._fetch_single(
                            new_url, request_sent, target_domains, accumulated_cookies
                        )
                        if result:
                            return result
                        continue  # 成功升級 HTTPS 並取得跳轉，繼續下一輪跳轉跟隨
                    except _FETCH_SAFE_EXCEPTIONS as retry_e:
                        e = retry_e
                        status_code = getattr(getattr(e, "response", None), "status_code", None)
                        current_url = new_url
                        if isinstance(e, (ValueError, TypeError, UnicodeError, LookupError)):
                            return None, None, "failed", current_url, request_sent, f"無效或無法解析的內容: {e}"
                        logger.warning("HTTPS 重試亦失敗: %s", e)

                # 2. 如果遇到 WAF 經常阻擋的特定狀態碼，嘗試拔除 Sec-* 標頭再次重試
                if status_code in WAF_STATUS_CODES:
                    logger.info("網址 %s 遇到 %s 阻擋，嘗試拔除特徵標頭再次重試...", current_url, status_code)
                    try:
                        request_sent, current_url, result = self._fetch_single(
                            current_url, request_sent, target_domains, accumulated_cookies, strip_sec_headers=True
                        )
                        if result:
                            return result
                        continue  # 拔除標頭後成功取得跳轉，繼續下一輪跳轉跟隨，避免用過時的 status_code/e 誤判為失敗
                    except _FETCH_SAFE_EXCEPTIONS as fallback_e:
                        e = fallback_e
                        status_code = getattr(getattr(e, "response", None), "status_code", None)
                        if isinstance(e, (ValueError, TypeError, UnicodeError, LookupError)):
                            return None, None, "failed", current_url, request_sent, f"無效或無法解析的內容: {e}"

                # 3. 終極 TLS 偽裝降級 (curl_cffi)
                # 當拔除標頭仍受阻，或是遭遇連線超時/TCP中斷 (狀態碼 None) 等無回應 Tarpit 時，啟動終極防護繞過
                if status_code in TLS_SPOOF_STATUS_CODES:
                    logger.info(
                        "網址 %s 拔除特徵仍受阻 (%s)，啟動終極 TLS 偽裝引擎 (從頭開始)...", current_url, status_code
                    )
                    cffi_status, cffi_err, cffi_text, cffi_final_url = self._execute_curl_cffi_fallback(
                        url, is_internal=True, target_domains=target_domains
                    )
                    # 若 curl_cffi 成功取得內容 (狀態碼 < 400)
                    if cffi_status is not None and cffi_status < 400 and cffi_text is not None:
                        return cffi_text, cffi_status, "completed", cffi_final_url or current_url, True, None

                    status_code = cffi_status
                    e = Exception(cffi_err) if cffi_err else Exception(f"TLS 偽裝失敗，狀態碼 {cffi_status}")

                # 4. 封裝所有例外，不向外拋出，統一回傳狀態
                # 即使遭遇各種未預期例外，也轉化為 failed 狀態回報
                return None, status_code, "failed", current_url, request_sent, str(e)

            except Exception as unhandled_e:  # pylint: disable=broad-exception-caught
                # 若發生 _FETCH_SAFE_EXCEPTIONS 之外的例外，做最後一道防護，絕不讓它洩漏
                logger.warning("網址 %s 遭遇非預期的例外: %s", current_url, unhandled_e)
                return None, None, "failed", current_url, request_sent, f"內部引擎發生例外: {unhandled_e}"

        logger.warning("網址 %s 超過最大重導向次數", url)
        return None, None, "failed", current_url, request_sent, "超過最大重導向次數"

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
            "source": "src",
            "track": "src",
        }

        # 透過單次遍歷 HTML 樹來擷取所有標籤，大幅提升大型網頁的解析效能
        for tag in soup.find_all(list(tag_attr_map.keys()) + ["meta"]):
            if tag.name == "meta":
                http_equiv = tag.get("http-equiv")
                if isinstance(http_equiv, str) and http_equiv.lower() == "refresh":
                    content = tag.get("content")
                    if isinstance(content, str):
                        match = re.search(r"url\s*=\s*['\"]?([^'\"]+)", content, re.IGNORECASE)
                        if match:
                            raw_links.append(match.group(1).strip())
                continue

            # 針對 <link> 標籤，忽略 dns-prefetch, preconnect, preload 與 alternate。
            # 這些標籤通常只指向網域根目錄或非必要的備用資源，並非實際需探測的連結。
            if tag.name == "link":
                rel_attr: str | list[str] = tag.get("rel") or []
                rel_list = [rel_attr] if isinstance(rel_attr, str) else (rel_attr or [])
                if any(r.lower() in ("preconnect", "dns-prefetch", "preload", "alternate") for r in rel_list):
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

            return list(dict.fromkeys(links))  # 移除陣列中的重複網址，同時保留原始順序
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

        if isinstance(html, list):
            links = html
        else:
            links = self.extract_links(html, final_url)

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

    def _execute_curl_cffi_fallback(  # pylint: disable=too-many-statements,too-many-nested-blocks
        self, url: str, is_internal: bool = False, target_domains: list[str] | None = None
    ) -> tuple[int | None, str | None, str | list[str] | None, str | None]:
        """終極備援核心邏輯：使用 curl_cffi 進行 TLS 指紋偽裝。

        手動處理重導向，每一跳均進行 SSRF 防護驗證，
        並透過 curl_cffi 的 resolve 參數實作安全的 DNS 覆寫。

        Args:
            url (str): 目標網址。
            is_internal (bool): 是否為內部抓取（需要防 OOM 與 MIME 驗證並回傳內容）。
            target_domains (list[str] | None): 允許進入的目標網域清單。

        Returns:
            tuple[int | None, str | None, str | None, str | None]:
                (status_code, error_msg, content_text, final_url)。
        """
        try:
            # pylint: disable=import-outside-toplevel
            from curl_cffi import CurlOpt
            from curl_cffi import requests as cffi_requests
            from curl_cffi.requests.errors import CurlError as CFFICurlError
            from curl_cffi.requests.errors import RequestsError as CFFIRequestsError
            # pylint: enable=import-outside-toplevel

            logger.info("啟動 TLS 偽裝備援引擎 (curl_cffi) 探測: %s", url)
            proxies = None
            if self.config.proxy_url:
                proxies = {"http": self.config.proxy_url, "https": self.config.proxy_url}

            stream = is_internal
            current_url = url

            accumulated_cookies: dict[str, dict[str, str]] = {}
            for redirect_idx in range(self.config.max_redirects + 1):
                domain = get_domain(current_url)
                ip, ssrf_err = self._resolve_and_check_ssrf(domain, current_url)
                if ssrf_err:
                    logger.warning("TLS 偽裝降級遭到 SSRF 防護攔截: %s", ssrf_err)
                    return None, ssrf_err, None, current_url

                # 設定 curl_cffi 的 DNS resolve
                cffi_curl_options = None
                if domain and ip:
                    parsed_url = urlparse(current_url)
                    port = parsed_url.port
                    if not port:
                        port = 443 if parsed_url.scheme == "https" else 80
                    # 若為 IPv6，必須用方括號包起來才能被 libcurl 正確解析
                    clean_ip = ip.strip("[]")
                    addr_for_resolve = f"[{clean_ip}]" if ":" in clean_ip else clean_ip
                    cffi_curl_options = {CurlOpt.RESOLVE: [f"{domain}:{port}:{addr_for_resolve}"]}

                # 決定是否需驗證 SSL 憑證 (依據 ssl_exempt_domains 白名單)
                verify_ssl = not (domain and is_in_domain_list(domain, self.config.ssl_exempt_domains))

                resp = None
                status_code = None
                last_error = None
                impersonate_profiles = self.get_dynamic_impersonate_profiles()

                try:
                    applicable_cookies = self._get_applicable_cookies(domain, accumulated_cookies)
                    for impersonate in impersonate_profiles:
                        try:
                            if resp is not None:
                                resp.close()

                            resp = cffi_requests.get(
                                current_url,
                                impersonate=cast("BrowserTypeLiteral", impersonate),
                                timeout=self.config.external_check_timeout,
                                allow_redirects=False,
                                proxies=cast("ProxySpec", proxies) if proxies else None,
                                stream=stream,
                                verify=verify_ssl,
                                curl_options=cffi_curl_options,
                                cookies=applicable_cookies,
                            )
                            status_code = resp.status_code
                            if status_code not in WAF_STATUS_CODES:
                                break  # 成功取得非 WAF 阻擋的回應，跳出輪替
                        except (CFFICurlError, CFFIRequestsError) as e:
                            logger.debug("TLS 偽裝探測使用 %s 遭遇錯誤: %s", impersonate, e)
                            last_error = e
                            continue

                    if resp is None:
                        if last_error:
                            raise last_error
                        return None, "TLS 偽裝探測全部失敗", None, current_url

                    for c_name, c_val in resp.cookies.items():
                        c_dom = domain  # curl_cffi 回傳的 cookies 為簡單 dict，在此統一綁定到當前網域
                        if c_dom:
                            accumulated_cookies.setdefault(c_dom, {})[c_name] = c_val

                    # 處理重導向
                    if status_code in REDIRECT_STATUS_CODES:
                        if redirect_idx >= self.config.max_redirects:
                            if url.startswith("http://"):
                                https_url = url.replace("http://", "https://", 1)
                                logger.info("網址 %s 發生無限重導向，嘗試升級為 HTTPS 進行最後驗證: %s", url, https_url)
                                return self._execute_curl_cffi_fallback(https_url, is_internal, target_domains)
                            return None, "超過最大重導向次數", None, current_url

                        location = resp.headers.get("Location")
                        if not location:
                            logger.warning("網址 %s 回傳 %d 但缺少 Location 標頭", current_url, status_code)
                            return status_code, "重導向但無 Location 標頭", None, current_url

                        next_url = urljoin(current_url, location)
                        if is_internal and target_domains:
                            next_domain = get_domain(next_url)
                            if next_domain and not is_in_domain_list(next_domain, target_domains):
                                logger.info("網址 %s 重導向至外部網域 %s，停止深入抓取", current_url, next_url)
                                return status_code, None, [next_url], current_url

                        current_url = next_url
                        continue

                    # 正常非重導向回應
                    if not is_internal:
                        return status_code, None, None, current_url

                    if status_code is not None and status_code >= 400:
                        return status_code, f"HTTP 狀態異常: {status_code}", None, current_url

                    content_type = resp.headers.get("Content-Type", "").lower()
                    if self.config.mime_type_filter.get("enabled", True):
                        allowed_types_raw = self.config.mime_type_filter.get("allowed_types", ["text/html"])
                        allowed_types: list[str] = (
                            allowed_types_raw if isinstance(allowed_types_raw, list) else ["text/html"]
                        )
                        if not any(str(a).lower() in content_type for a in allowed_types):
                            return status_code, f"略過非目標 MIME 類型 ({content_type})", None, current_url

                    content_bytes = bytearray()
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            content_bytes.extend(chunk)
                            if len(content_bytes) > self.config.max_content_length:
                                logger.warning(
                                    "網頁容量超過上限 (%s bytes)，內容已被提早截斷: %s",
                                    self.config.max_content_length,
                                    current_url,
                                )
                                break

                    try:
                        text = self._safe_decode(content_bytes, resp.encoding or "utf-8")
                    except Exception as decode_e:  # pylint: disable=broad-exception-caught
                        logger.warning("TLS 偽裝降級解析內容編碼失敗: %s", decode_e)
                        text = ""

                    return status_code, None, text, current_url

                finally:
                    if resp is not None:
                        resp.close()

            return None, "超過最大重導向次數", None, current_url

        except ImportError:
            logger.warning("未安裝 curl_cffi，無法執行 TLS 偽裝降級")
            return None, "未安裝 curl_cffi", None, url
        except (CFFICurlError, CFFIRequestsError) as e:
            logger.warning("TLS 偽裝備援探測失敗: %s", e)
            cffi_resp = getattr(e, "response", None)
            status_code = getattr(cffi_resp, "status_code", None) if cffi_resp is not None else None
            if status_code == 0:
                status_code = None
            err_str = str(e)
            if "curl:" in err_str:
                short_err = err_str.split("curl:", 1)[-1].split(". See https://", 1)[0].strip()
                # err_msg = f"TLS 偽裝探測失敗: {short_err}"
                err_msg = f"探測失敗: {short_err}"
            else:
                # err_msg = f"TLS 偽裝探測失敗: {err_str}"
                err_msg = f"探測失敗: {err_str}"
            return status_code, err_msg, None, url
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("TLS 偽裝備援遭遇未預期底層例外: %s", type(e).__name__)
            return None, f"TLS 偽裝發生底層異常: {e}", None, url

    def _tls_spoofed_fallback(self, url: str) -> tuple[int | None, str | None]:
        """外部探測專用的 TLS 指紋偽裝降級包裹方法。

        Args:
            url (str): 目標外部網址。

        Returns:
            tuple[int | None, str | None]: (HTTP 狀態碼, 錯誤或警告訊息)。
        """
        status_code, err_msg, _, _ = self._execute_curl_cffi_fallback(url, is_internal=False)
        return status_code, err_msg

    def _fallback_get(  # pylint: disable=too-many-arguments
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

                if resp.status_code in REDIRECT_STATUS_CODES:
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

        Args:
            tgt_dom (str | None): 目標網域。
            accumulated_cookies (dict[str, dict[str, str]] | None): 依網域分桶的 Cookie 字典。

        Returns:
            dict[str, str]: 適用於該網域的 Cookie 鍵值對。
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
            except Exception as e:  # pylint: disable=broad-except
                # 攔截 h2.exceptions.InvalidBodyLengthError 等非繼承自 httpx.RequestError 的底層協定錯誤。
                # 當遇到行為不符 HTTP/2 規範的伺服器 (如對 HEAD 請求回傳 Body) 時，同樣降級使用 GET。
                logger.debug("HEAD 請求發生底層或協定異常 (%s)，嘗試降級使用 GET...", e)
                return self._fallback_get(current_url, tgt_dom, ip, client, accumulated_cookies)

        # 將 HEAD 回應的 Set-Cookie 合併回正確的網域桶中
        if accumulated_cookies is not None:
            for c in response.cookies.jar:
                if c.value is not None:
                    c_dom = c.domain.lstrip(".") if c.domain else tgt_dom
                    if c_dom:
                        accumulated_cookies.setdefault(c_dom, {})[c.name] = c.value

        if response.status_code in REDIRECT_STATUS_CODES:
            # HEAD 的重導向結果在許多伺服器上並不可靠：可能是 Cookie-gate 要求重新帶
            # Cookie 確認 (如 Citrix NetScaler)，也可能是伺服器單純不支援 HEAD 重導向、
            # 固定回傳錯誤的 Location 造成彈跳 (即使完全沒有 Cookie 涉入)。兩種情況的
            # 共同解法相同：不論是否持有 Cookie，一律改用 GET 對同一網址重新確認，
            # 取得可信的結果或正確的下一步網址，而不是冒險信任 HEAD 給出的 Location。
            return self._fallback_get(current_url, tgt_dom, ip, client, accumulated_cookies)

        is_social_media = tgt_dom and is_in_domain_list(tgt_dom.lower(), self.config.social_domains)
        # 許多伺服器 (如 IIS) 對 HEAD 請求的轉址設定不完整，可能直接回傳 404 或 405。
        # 將 404 等常見誤判狀態碼納入降級條件，若 HEAD 遇到 404 將以 GET (Stream) 二次確認。
        if response.status_code in HEAD_FALLBACK_STATUS_CODES or (response.status_code >= 400 and is_social_media):
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
            ip, ssrf_err = self._resolve_and_check_ssrf(tgt_dom, current_url)

            if ssrf_err:
                return None, (None, ssrf_err)

            return self._execute_external_request(current_url, tgt_dom, ip, accumulated_cookies)
        except httpx.RequestError as e:
            return None, (None, str(e))
        # 外部連結探測的「統一防線」
        except Exception as e:  # pylint: disable=broad-exception-caught
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
            # 若 HTTPS 連線徹底失敗 (無狀態碼)，原本會退回 HTTP 結果。
            # 但若錯誤原因是 SSL/TLS 層級異常，很可能是 WAF 透過 TLS handshake 指紋識別而
            # 拒絕連線 (而非真正的憑證信任鏈問題——若是信任鏈問題且網域在白名單內，httpx
            # 早就改用 verify=False，根本不會走到這裡)。這類協定層級的拒絕，curl_cffi 的
            # TLS 指紋偽裝有機會繞過，因此回傳 HTTPS 的 SSL 錯誤，設 fell_back=False
            # 讓後續能進入 TLS 偽裝降級嘗試。
            if status_code_retry is None:
                if err_msg_retry and ("SSL" in err_msg_retry.upper() or "CERT" in err_msg_retry.upper()):
                    logger.info("HTTPS 重試發現憑證/連線錯誤: %s", err_msg_retry)
                    return None, result_retry, False

                logger.info("HTTPS 重試失敗: %s", err_msg_retry)
                return None, original_result, True
            # 若 HTTPS 有取得狀態碼（即使是 4xx/5xx），就取代原本 HTTP 結果
            return None, result_retry, False

        if next_url_retry:
            return next_url_retry, None, False

        return None, None, False

    def check_external_link(self, url: str, depth: int = 0) -> tuple[int | None, str | None]:
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
            depth (int, optional): 內部遞迴深度計數器，預設為 0。用以確保 HTTP 自動升級至 HTTPS 的遞迴嘗試最多只執行一層，防止無限遞迴（Stack Overflow）。

        Returns:
            tuple[int | None, str | None]: 回傳 (HTTP 狀態碼, 錯誤訊息)。
        """
        current_url = url
        # 跨跳共用的 Cookie 字典，用於繞過 Cookie-gate 防爬蟲機制。
        # 使用普通 dict 並以引用方式傳遞，避免 httpx 已棄用的 per-request cookies 參數。
        # 內部各方法直接寫入 accumulated_cookies，不需要回傳值。
        accumulated_cookies: dict[str, dict[str, str]] = {}

        for _ in range(self.config.max_redirects + 1):
            # next_url: 重導向的下一步網址 (None 表示沒有重導向), result: 回傳狀態結果 (None 表示有重導向，尚未取得最終結果)
            next_url, result = self._check_external_single(current_url, accumulated_cookies)

            if result is not None:
                # 許多現代網站與防火牆 (Cloudflare, HSTS) 對明文 HTTP 請求會直接中斷或回傳 403/520
                # 若遇到連線錯誤 (status_code is None) 或是 WAF / 伺服器回傳異常 (>= 400)
                # 可對明文 HTTP 連結嘗試升級至 HTTPS 重試；HTTPS 有結果則回傳，重導向則繼續
                status_code, err_msg = result

                # 若為 DNS 解析失敗或 SSRF 攔截，為物理層級斷線或安全封鎖，直接回傳，無須進行後續協定升級與偽裝嘗試
                if status_code is None and err_msg and ("DNS 解析失敗" in err_msg or "SSRF 防禦攔截" in err_msg):
                    return result

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
                        if is_retry_failed and status_code_retry in TLS_SPOOF_STATUS_CODES:
                            # 原始 HTTP 請求已直接失敗，且人工升級的 HTTPS 也遭 WAF 阻擋。
                            # 以下將原始 url 替換成 HTTPS，從頭發起請求，以發揮 TLS 偽裝能力。
                            # 重新走一遍以取回完整可用的 Cookie。
                            https_fallback_url = urlparse(url)._replace(scheme="https").geturl()
                            return self._tls_spoofed_fallback(https_fallback_url)

                        return result_retry

                    if next_url_retry:
                        current_url = next_url_retry
                        continue

                # 遭遇 WAF 阻擋（包含 Tarpit 連線超時），啟動終極 TLS 偽裝降級
                if is_failed and urlparse(current_url).scheme == "https":
                    if status_code in TLS_SPOOF_STATUS_CODES:
                        # 這裡傳入原始 url，即使原 url 為 HTTP 也「不手動替換 scheme」。
                        # 若原始為 HTTP 但 current 走到 HTTPS，代表中間有正常的 301/302 重導向。
                        # 讓 curl_cffi 完整重跑這段 HTTP -> HTTPS 的重導向過程，
                        # 可以確保蒐集到途中伺服器可能發放的驗證 Cookie（例如 Cookie-gate 防護）。
                        return self._tls_spoofed_fallback(url)

                return result

            if next_url:
                current_url = next_url
                continue
        # 正常跑完迴圈但仍未取得終端狀態
        # 為了防止極端情況下的無限遞迴（例如伺服器在 HTTP/HTTPS 間惡意交替重導向），
        # 透過 depth == 0 確保這個 HTTP 升級 HTTPS 的最後救援機制最多只會遞迴一次。
        if url.startswith("http://") and depth == 0:
            https_url = url.replace("http://", "https://", 1)
            logger.info("外部探測網址 %s 發生無限重導向，嘗試升級為 HTTPS 進行最後驗證: %s", url, https_url)
            return self.check_external_link(https_url, depth=1)
        return None, "超過最大重導向次數"
