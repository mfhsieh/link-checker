"""
爬蟲套件的工具函式。

此模組提供網域擷取、網域驗證、IP 位址解析以及網址正規化等輔助函式。
"""

import urllib.parse
import socket
import logging

logger: logging.Logger = logging.getLogger(__name__)

def get_domain(url: str) -> str:
    """
    從給定的網址中擷取網域 (Domain) 名稱。

    Args:
        url (str): 準備進行解析的完整網址字串。

    Returns:
        str: 擷取出的網域名稱，不包含通訊埠 (Port) 或路徑。如果解析失敗則回傳空字串。
    """
    try:
        parsed_uri: urllib.parse.ParseResult = urllib.parse.urlparse(url)
        return parsed_uri.netloc.split(':')[0]  # 移除可能存在的通訊埠
    except Exception as e:
        logger.error(f"解析網址 {url} 時發生錯誤: {e}")
        return ""

def is_in_domain_list(domain: str, domain_list: list[str]) -> bool:
    """
    檢查該網域是否包含在提供的網域清單中，或者是其子網域 (Subdomain)。

    Args:
        domain (str): 欲檢查的網域。
        domain_list (list[str]): 用來比對的基準網域清單。

    Returns:
        bool: 如果該網域符合清單中的任一項目或是其子網域，則回傳 True，否則回傳 False。
    """
    if not domain:
        return False
    domain = domain.lower()
    for d in domain_list:
        d = d.lower()
        if domain == d or domain.endswith('.' + d):
            return True
    return False

def resolve_ip(domain: str) -> str | None:
    """
    針對給定的網域解析其 IP 位址。

    Args:
        domain (str): 欲解析的網域名稱。

    Returns:
        str | None: 解析成功的 IP 位址字串，若解析失敗則回傳 None。
    """
    try:
        ip: str = socket.gethostbyname(domain)
        return ip
    except socket.gaierror:
        logger.warning(f"無法解析此網域的 IP 位址: {domain}")
        return None
    except Exception as e:
        logger.error(f"解析 {domain} IP 時發生未預期錯誤: {e}")
        return None

def normalize_url(url: str, base_url: str) -> str:
    """
    正規化網址，會將相對路徑與基準網址 (Base URL) 進行合併解析。

    Args:
        url (str): 欲正規化的網址 (可以是相對路徑或絕對路徑)。
        base_url (str): 用來解析相對路徑的基準網址。

    Returns:
        str: 完整的絕對網址字串。
    """
    return urllib.parse.urljoin(base_url, url)
