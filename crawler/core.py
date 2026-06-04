"""
爬蟲核心邏輯模組，負責網頁抓取與解析。

此模組提供 CrawlerCore 類別，負責發送 HTTP 請求抓取網頁、
解析 HTML、擷取連結，並依據網域規則過濾與分類連結。
"""

import httpx
from bs4 import BeautifulSoup
import logging
from urllib.parse import urlparse, ParseResult
from crawler.utils import normalize_url, get_domain, is_in_domain_list

logger: logging.Logger = logging.getLogger(__name__)

class CrawlerCore:
    """
    網頁爬蟲的核心引擎。

    負責處理 HTML 內容的抓取、連結的擷取，並根據提供的網域規則
    將連結分類為內部連結與外部目標連結。

    Attributes:
        timeout (int): HTTP 請求的逾時時間 (單位：秒)。
        client (httpx.Client): 用於發送同步連線的 HTTPX 客戶端物件。
    """

    def __init__(self, timeout: int = 30, ignore_extensions: list[str] | None = None) -> None:
        """
        初始化 CrawlerCore 物件。

        Args:
            timeout (int): HTTP 請求的逾時時間 (單位：秒)，預設為 30 秒。
            ignore_extensions (list[str] | None): 要忽略的副檔名清單，預設包含常見非 HTML 檔案。
        """
        self.timeout: int = timeout
        self.ignore_extensions: list[str] = ignore_extensions or ['.pdf', '.jpg', '.png', '.gif', '.mp4', '.zip']
        self.client: httpx.Client = httpx.Client(timeout=self.timeout, follow_redirects=True)

    def fetch(self, url: str) -> str | None:
        """
        抓取給定網址的 HTML 內容。

        Args:
            url (str): 欲抓取的網址字串。

        Returns:
            str | None: 如果連線成功且內容類型為 text/html，則回傳 HTML 字串；否則回傳 None。
        """
        try:
            # 略過指定的非 HTML 副檔名以節省頻寬與時間
            if any(url.lower().endswith(ext) for ext in self.ignore_extensions):
                return None
            
            response: httpx.Response = self.client.get(url)
            response.raise_for_status()
            
            # 檢查 HTTP 回應的 Content-Type
            content_type: str = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
                
            return response.text
        except httpx.RequestError as e:
            logger.error(f"抓取 {url} 時發生連線請求錯誤: {e}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"抓取 {url} 時發生 HTTP 狀態碼錯誤 {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"抓取 {url} 時發生未預期例外: {e}")
            return None

    def extract_links(self, html: str, base_url: str) -> list[str]:
        """
        從給定的 HTML 內容中擷取所有有效且絕對路徑的連結。

        Args:
            html (str): 準備進行解析的 HTML 字串。
            base_url (str): 用來將相對路徑轉換為絕對路徑的基準網址。

        Returns:
            list[str]: 包含所有已擷取且去重複的正規化網址陣列。
        """
        if not html:
            return []
            
        try:
            soup: BeautifulSoup = BeautifulSoup(html, 'html.parser')
            links: list[str] = []
            for a_tag in soup.find_all('a', href=True):
                href: str = a_tag['href'].strip()
                # 排除 javascript, mailto 等非 http(s) 的錨點連結
                if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                    continue
                normalized_link: str = normalize_url(href, base_url)
                
                # 進行基礎驗證，確保為有效的 HTTP/HTTPS 網址
                parsed: ParseResult = urlparse(normalized_link)
                if parsed.scheme in ('http', 'https'):
                    links.append(normalized_link)
            return list(set(links))  # 移除陣列中的重複網址
        except Exception as e:
            logger.error(f"從 {base_url} 擷取連結時發生錯誤: {e}")
            return []

    def process_url(self, url: str, target_domains: list[str], internal_domains: list[str]) -> tuple[list[str], list[str]]:
        """
        處理單一網址，包含抓取網頁、擷取連結以及分類。

        Args:
            url (str): 準備處理的網址。
            target_domains (list[str]): 允許爬蟲進入的網域陣列。
            internal_domains (list[str]): 被視為內部的網域陣列。指向這些網域以外的連結將被視為目標。

        Returns:
            tuple[list[str], list[str]]: 包含兩個陣列的 Tuple：
                - internal_links_to_crawl: 準備加入佇列繼續爬取的內部連結陣列。
                - external_target_links: 需被記錄的外部連結陣列。
        """
        html: str | None = self.fetch(url)
        if not html:
            return [], []

        links: list[str] = self.extract_links(html, url)
        
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
                
        return internal_links, external_target_links
        
    def close(self) -> None:
        """關閉底層的 HTTPX 客戶端連線。"""
        self.client.close()
