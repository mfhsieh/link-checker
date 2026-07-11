"""
爬蟲套件的工具函式。

此模組提供網域擷取、網域驗證、IP 位址解析以及網址正規化等輔助函式。
"""

import ipaddress
import logging
import os
import socket
import urllib.parse
from typing import Any

import cachetools
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import JSON

from crawler.models import CrawlQueue

logger: logging.Logger = logging.getLogger(__name__)

# DNS 快取常數設定
DNS_CACHE_MAXSIZE = 1024
DNS_CACHE_TTL = 300


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
        return parsed_uri.netloc.split(":")[0]  # 移除可能存在的通訊埠
    except ValueError as e:
        logger.error("解析網址 %s 時發生錯誤: %s", url, e)
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
        if domain == d or domain.endswith("." + d):
            return True
    return False


@cachetools.cached(cachetools.TTLCache(maxsize=DNS_CACHE_MAXSIZE, ttl=DNS_CACHE_TTL))
def resolve_ip(domain: str) -> str | None:
    """
    針對給定的網域解析其 IP 位址（具備 5 分鐘 DNS 快取）。

    Args:
        domain (str): 欲解析的網域名稱。

    Returns:
        str | None: 解析成功的 IP 位址字串，若解析失敗則回傳 None。
    """
    try:
        ip: str = socket.gethostbyname(domain)
        return ip
    except socket.gaierror:
        logger.warning("無法解析此網域的 IP 位址: %s", domain)
        return None
    except (UnicodeError, ValueError) as e:
        logger.warning("網域解析失敗 (可能為畸形網域): %s, 錯誤: %s", domain, e)
        return None
    except OSError as e:
        logger.error("解析 %s IP 時發生未預期錯誤: %s", domain, e)
        return None


def is_safe_ip(ip_str: str) -> bool:
    """
    檢查 IP 是否為安全的外部 IP（阻擋 SSRF 攻擊）。

    Args:
        ip_str (str): 欲檢查的 IP 位址字串。

    Returns:
        bool: 如果是安全的公開 IP 則回傳 True，否則（如 Loopback, Private, Link-local）回傳 False。
    """
    if os.environ.get("CRAWLER_ALLOW_LOCAL_IPS", "false").lower() == "true":
        return True

    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
        # 阻擋本機、私有網段、鏈結本地端、多播網段，以及未指定位置
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        return True
    except ValueError:
        return False


def normalize_url(url: str, base_url: str) -> str:
    """
    正規化網址，會將相對路徑與基準網址 (Base URL) 進行合併解析，並剝離片段 (Fragment, #)。

    Args:
        url (str): 欲正規化的網址 (可以是相對路徑或絕對路徑)。
        base_url (str): 用來解析相對路徑的基準網址。

    Returns:
        str: 完整的絕對網址字串。
    """
    joined_url = urllib.parse.urljoin(base_url, url)
    parsed, _ = urllib.parse.urldefrag(joined_url)
    return parsed


def format_crawl_queue_item(q: CrawlQueue) -> dict[str, object]:
    """
    格式化 CrawlQueue 項目為字典供報表使用。

    Args:
        q (CrawlQueue): 欲格式化的佇列項目。

    Returns:
        dict[str, object]: 包含佇列項目詳細資訊的字典。
    """
    return {
        "source_url": q.source_url if q.source_url else "",
        "target_url": q.url,
        "Status": q.status,
        "Status Category": q.status_category,
        "Depth": q.depth,
        "Retry Count": q.retry_count,
        "is_secure": q.is_secure,
        "http_status_code": q.status_code if q.status_code is not None else "",
        "error_message": q.error_message if q.error_message else "",
        "Created At": q.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "Updated At": q.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


class JSONGroupArray(FunctionElement):
    """
    跨資料庫的 JSON 陣列聚合函數。
    SQLite 編譯為 json_group_array，PostgreSQL 編譯為 json_agg。
    """

    name = "json_group_array"
    type_ = JSON()
    inherit_cache = True


@compiles(JSONGroupArray, "sqlite")
def _compile_json_group_array_sqlite(element: JSONGroupArray, compiler: Any, **kw: Any) -> str:
    """
    編譯 JSONGroupArray 函式至 SQLite 相容的 SQL。

    Args:
        element (JSONGroupArray): SQLAlchemy 的 JSONGroupArray 函式元素。
        compiler (object): SQL 編譯器。
        **kw (object): 其他編譯參數。

    Returns:
        str: 編譯後的 SQLite SQL 字串。
    """
    return f"json_group_array({compiler.process(element.clauses, **kw)})"


@compiles(JSONGroupArray, "postgresql")
def _compile_json_group_array_postgresql(element: JSONGroupArray, compiler: Any, **kw: Any) -> str:
    """
    編譯 JSONGroupArray 函式至 PostgreSQL 相容的 SQL。

    Args:
        element (JSONGroupArray): SQLAlchemy 的 JSONGroupArray 函式元素。
        compiler (object): SQL 編譯器。
        **kw (object): 其他編譯參數。

    Returns:
        str: 編譯後的 PostgreSQL SQL 字串。
    """
    return f"json_agg({compiler.process(element.clauses, **kw)})"


class JSONObject(FunctionElement):
    """
    跨資料庫的 JSON 物件建構函數。
    SQLite 編譯為 json_object，PostgreSQL 編譯為 json_build_object。
    """

    name = "json_object"
    type_ = JSON()
    inherit_cache = True


@compiles(JSONObject, "sqlite")
def _compile_json_object_sqlite(element: JSONObject, compiler: Any, **kw: Any) -> str:
    """
    編譯 JSONObject 函式至 SQLite 相容的 SQL。

    Args:
        element (JSONObject): SQLAlchemy 的 JSONObject 函式元素。
        compiler (object): SQL 編譯器。
        **kw (object): 其他編譯參數。

    Returns:
        str: 編譯後的 SQLite SQL 字串。
    """
    return f"json_object({compiler.process(element.clauses, **kw)})"


@compiles(JSONObject, "postgresql")
def _compile_json_object_postgresql(element: JSONObject, compiler: Any, **kw: Any) -> str:
    """
    編譯 JSONObject 函式至 PostgreSQL 相容的 SQL。

    Args:
        element (JSONObject): SQLAlchemy 的 JSONObject 函式元素。
        compiler (object): SQL 編譯器。
        **kw (object): 其他編譯參數。

    Returns:
        str: 編譯後的 PostgreSQL SQL 字串。
    """
    return f"json_build_object({compiler.process(element.clauses, **kw)})"


def create_optimized_engine(  # pylint: disable=too-many-arguments
    db_url: str,
    sqlite_timeout: int = 30,
    pool_size: int = 20,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
    sqlite_cache_size: int = 10000,
) -> Engine:
    """
    建立並設定最佳化參數的 SQLAlchemy 資料庫引擎。

    Args:
        db_url (str): 資料庫連線字串。
        sqlite_timeout (int): SQLite 連線鎖定等待超時 (秒)。
        pool_size (int): 連線池大小 (適用於 PostgreSQL 等)。
        max_overflow (int): 最大溢出連線數 (適用於 PostgreSQL 等)。
        pool_pre_ping (bool): 是否開啟連線池自動偵測重連機制。
        sqlite_cache_size (int): SQLite 快取大小 (分頁數)。

    Returns:
        Engine: 設定完成的 SQLAlchemy Engine。

    Raises:
        OSError: 若建立資料庫目錄失敗時拋出。
    """
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    engine_kwargs: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": sqlite_timeout}
    else:
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow
        engine_kwargs["pool_pre_ping"] = pool_pre_ping

    engine = create_engine(db_url, **engine_kwargs)
    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            """
            設定 SQLite 的 PRAGMA 參數，提升並發效能與安全性。

            Args:
                dbapi_connection (Any): SQLite 資料庫連線物件。
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA cache_size={sqlite_cache_size}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# pylint: disable=too-many-return-statements
def determine_external_link_status_category(ip_address: str | None, status_code: int | None) -> str:
    """
    根據目標的 IP 解析結果與 HTTP 狀態碼，判斷外部連結的狀態分類。

    Args:
        ip_address (str | None): 網域解析出的 IP 位址。
        status_code (int | None): 取得的 HTTP 狀態碼。

    Returns:
        str: 分類字串 (例如 "healthy", "dns_failed", "not_found" 等)。
    """
    if not ip_address:
        return "dns_failed"

    if status_code is None:
        return "connection_error"

    if status_code in (404, 410):
        return "not_found"

    if 500 <= status_code < 600:
        return "server_error"

    if status_code in (401, 403, 405, 406, 429):
        return "blocked"

    if status_code >= 400:
        return "other_error"

    return "healthy"


# pylint: disable=too-many-return-statements
def determine_internal_link_status_category(status: str, status_code: int | None, error_message: str | None) -> str:
    """
    根據 CrawlQueue 的狀態、HTTP 狀態碼與錯誤訊息，判斷內部連結的狀態分類。

    Args:
        status (str): CrawlQueue 的當前狀態。
        status_code (int | None): 取得的 HTTP 狀態碼。
        error_message (str | None): 例外或錯誤訊息。

    Returns:
        str: 分類字串 (例如 "healthy", "warning", "not_found", "server_error" 等)。
    """
    if status == "warning":
        return "warning"

    if status != "failed":
        return status

    msg = str(error_message or "").lower()

    if status_code is None:
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        return "connection_error"

    if status_code in (404, 410):
        return "not_found"

    if 500 <= status_code < 600:
        return "server_error"

    if status_code in (401, 403, 405, 406, 429):
        return "blocked"

    return "other_error"
