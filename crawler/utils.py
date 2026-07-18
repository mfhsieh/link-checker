"""
爬蟲套件的共用工具函式與輔助類別。

此模組涵蓋下列大領域：

- **網址與網域處理**：網域擷取、子網域比對、網址正規化。
- **IP 位址與資安**：具備 TTL 快取的 DNS 解析、SSRF 風險防護檢查。
- **資料庫工具**：跨資料庫最佳化引擎建立、跨方言 JSON SQL 聚合函式、
  批次 Upsert (Insert Ignore)、任務進度重算。
- **狀態分類**：依據 HTTP 狀態碼與錯誤訊息對內部與外部連結進行語意分類。
- **報表格式化**：將 ORM 物件轉換為 API 回應用字典。

模組層級常數：
    DNS_CACHE_MAXSIZE: DNS 解析結果 LRU 快取的最大條數。
    DNS_CACHE_TTL: DNS 解析快取的存活時間（秒）。
"""

import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import threading
import urllib.parse

import cachetools
from sqlalchemy import Engine, create_engine, event, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import JSON

from crawler.env import get_env
from crawler.models import CrawlQueue, ExternalLink, Job

logger: logging.Logger = logging.getLogger(__name__)

#: DNS_CACHE_MAXSIZE: DNS 解析結果 LRU 快取的最大條數。
DNS_CACHE_MAXSIZE: int = 1024
#: DNS_CACHE_TTL: DNS 解析快取的存活時間（秒），預設為 5 分鐘。
DNS_CACHE_TTL: int = 300


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


@cachetools.cached(cachetools.TTLCache(maxsize=DNS_CACHE_MAXSIZE, ttl=DNS_CACHE_TTL), lock=threading.Lock())
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
    # 若啟用開發模式覆寫，則直接放行
    env = get_env()
    if env.allow_local_ips:
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


def sanitize_error_message(msg: str | None) -> str:
    """
    清洗錯誤訊息中的敏感資訊（如密碼、IP、Cookie、Token）。

    Args:
        msg (str | None): 原始錯誤訊息。

    Returns:
        str: 清洗後的字串。若傳入 None 則回傳空字串。
    """
    if not msg:
        return ""

    # 遮蔽 URL 中的憑證: http://user:pass@host -> http://***:***@host
    msg = re.sub(r"([a-zA-Z0-9+.-]+://)[^:\s@]+:[^@\s]+@", r"\g<1>***:***@", msg)

    # 遮蔽 Header 或字典中的敏感值 (Cookie, Authorization, Bearer)
    msg = re.sub(r"(?i)(cookie|authorization|bearer)(\s*[:=]\s*)([^\s'\"\]}]+)", r"\1\2***", msg)

    # 遮蔽 IPv4 位址
    msg = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP_MASKED]", msg)

    # 遮蔽 IPv6 位址 (完整涵蓋標準與 :: 縮寫格式)
    ipv6_pattern = (
        r"(?<![a-zA-Z0-9])"
        r"("
        r"([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|"
        r"([0-9a-fA-F]{1,4}:){1,7}:|"
        r"([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|"
        r"([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|"
        r"([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|"
        r"([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|"
        r"([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|"
        r"[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|"
        r":((:[0-9a-fA-F]{1,4}){1,7}|:)"
        r")"
        r"(?![a-zA-Z0-9])"
    )
    msg = re.sub(ipv6_pattern, "[IP_MASKED]", msg)

    return msg


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
    將 CrawlQueue ORM 物件序列化為報表用字典。

    回傳的字典鍵名同時包含首字母大寫（如 ``Status``）與小寫（如 ``is_secure``）
    兩種樣式，為對歷史 CSV/Excel 導出格式的相容設計。

    Args:
        q (CrawlQueue): 欲格式化的佇列 ORM 物件。

    Returns:
        dict[str, object]: 包含下列鍵的詳細字典：
            - ``source_url`` (str): 來源網址（來源不明時為空字串）。
            - ``target_url`` (str): 目標網址。
            - ``Status`` (str): 爬取狀態（pending / completed / failed / skip / warning）。
            - ``Status Category`` (str): 語意化分類（如 healthy、broken 等）。
            - ``Depth`` (int): 爬取深度。
            - ``Retry Count`` (int): 重試次數。
            - ``is_secure`` (bool): 是否為 HTTPS 連結。
            - ``http_status_code`` (int | str): HTTP 狀態碼（未取得時為空字串）。
            - ``error_message`` (str): 錯誤訊息（無訊息時為空字串）。
            - ``Created At`` (str): 建立時間（格式 ``YYYY-MM-DD HH:MM:SS``）。
            - ``Updated At`` (str): 最後更新時間（格式 ``YYYY-MM-DD HH:MM:SS``）。
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

    將多筆資料列直下的值聚合為 JSON 陣列：
    SQLite 編譯為 ``json_group_array(...)``，
    PostgreSQL 編譯為 ``json_agg(...)``。

    典型用法：

        session.query(JSONGroupArray(MyModel.name)).scalar()

    Attributes:
        name (str): SQLAlchemy 內部識別用的函數名稱。
        type_ (JSON): 回傳值的 SQLAlchemy 型別為 JSON。
        inherit_cache (bool): 設為 True 表示允許 SQLAlchemy 對此函數元素快取編譯結果。
    """

    name = "json_group_array"
    type_ = JSON()
    inherit_cache = True


@compiles(JSONGroupArray, "sqlite")
def _compile_json_group_array_sqlite(element: JSONGroupArray, compiler: SQLCompiler, **kw: object) -> str:
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
def _compile_json_group_array_postgresql(element: JSONGroupArray, compiler: SQLCompiler, **kw: object) -> str:
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

    將鍵值對列表建構為單一 JSON 物件：
    SQLite 編譯為 ``json_object(...)``，
    PostgreSQL 編譯為 ``json_build_object(...)``。

    典型用法：

        session.query(JSONObject("key", MyModel.value)).scalar()

    Attributes:
        name (str): SQLAlchemy 內部識別用的函數名稱。
        type_ (JSON): 回傳值的 SQLAlchemy 型別為 JSON。
        inherit_cache (bool): 設為 True 表示允許 SQLAlchemy 對此函數元素快取編譯結果。
    """

    name = "json_object"
    type_ = JSON()
    inherit_cache = True


@compiles(JSONObject, "sqlite")
def _compile_json_object_sqlite(element: JSONObject, compiler: SQLCompiler, **kw: object) -> str:
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
def _compile_json_object_postgresql(element: JSONObject, compiler: SQLCompiler, **kw: object) -> str:
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
        def set_sqlite_pragma(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
            """
            新連線建立時自動設定 SQLite 的 PRAGMA 參數。

            將 WAL 日誌、同步模式、快取頁數、外鍵等 PRAGMA 套入每條新連線，
            提升多執行緒並發安全性與效能。

            Args:
                dbapi_connection (sqlite3.Connection): SQLite DBAPI 連線物件，
                    由 SQLAlchemy 於連線池建立連線時傳入。
                    ``_connection_record`` 參數為 SQLAlchemy ``connect`` 事件的必要
                    簽名，但此處不使用，故以底線開頭命名。
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
    依據目標的 IP 解析結果與 HTTP 狀態碼，判斷外部連結的語意分類。

    分類導用於前端報表呈現與筛選。分類優先順序為：
    IP 解析失敗 > HTTP 狀態碼未取得 > 404/410 > 5xx > WAF 攔截 > 其他 4xx > 健康。

    Args:
        ip_address (str | None): 網域解析出的 IP 位址。為 None 表示 DNS 解析失敗。
        status_code (int | None): 取得的 HTTP 狀態碼。為 None 表示連線層失敗。

    Returns:
        str: 語意分類字串，可能值為：
            - ``"dns_failed"``：網域無法解析 (ip_address 為 None)。
            - ``"connection_error"``：連線建立失敗，未取得任何 HTTP 回應。
            - ``"not_found"``：資源不存在 (HTTP 404 / 410)。
            - ``"server_error"``：目標伺服器內部錯誤 (HTTP 5xx)。
            - ``"blocked"``：被 WAF 或存取控制政策攔截 (HTTP 401/403/405/406/429)。
            - ``"other_error"``：其他 4xx 狀態碼，非上述明確類別。
            - ``"healthy"``：連結正常存活（HTTP 2xx/3xx）。
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
    依據 CrawlQueue 的狀態、HTTP 狀態碼與錯誤訊息，判斷內部連結的語意分類。

    此函式將 CrawlerCore 回傳的原始狀態資訊轉換為更細粒的語意分類，
    分類僅在狀態為 ``"failed"`` 時才進一步分析錯誤原因。

    Args:
        status (str): CrawlQueue 的當前狀態（completed / failed / skip / warning）。
        status_code (int | None): 取得的 HTTP 狀態碼。為 None 表示連線層失敗。
        error_message (str | None): 爬取時回傳的例外或錯誤訊息。

    Returns:
        str: 語意分類字串，可能值為：
            - ``"warning"``：爬取成功但內容被截斷（如網頁體積超限）。
            - ``"completed"``、``"skip"``、``"pending"``：非 failed 時直接回傳原始 status 字串。
            - ``"timeout"``：連線超時（status=failed 且對應訊息含 timeout）。
            - ``"connection_error"``：連線層失敗且未取得 HTTP 狀態碼。
            - ``"not_found"``：資源不存在 (HTTP 404 / 410)。
            - ``"server_error"``：目標伺服器內部錯誤 (HTTP 5xx)。
            - ``"blocked"``：被 WAF 或政策攔截 (HTTP 401/403/405/406/429)。
            - ``"other_error"``：其他不明原因的 4xx 錯誤。
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


def bulk_insert_ignore(
    session: Session,
    model: type,
    mappings: list[dict[str, object]],
    index_elements: list[str],
) -> None:
    """
    跨資料庫的批次 Upsert (Insert Ignore) 函式。
    利用 PostgreSQL 與 SQLite 專屬的 insert 語法，加上 on_conflict_do_nothing
    來迴避主鍵或唯一約束衝突。

    Args:
        session (Session): SQLAlchemy 的資料庫對話。
        model (type): 欲寫入的 SQLAlchemy 模型類別。
        mappings (list[dict[str, object]]): 包含要寫入資料的字典陣列。
        index_elements (list[str]): 判定衝突的索引或欄位名稱 (例如 ['job_id', 'source_url', 'target_url'])。

    Raises:
        ValueError: 遇到不支援的資料庫方言時拋出。
    """
    if not mappings:
        return

    dialect_name = session.bind.dialect.name if session.bind else ""
    if dialect_name == "postgresql":
        stmt_pg = pg_insert(model).values(mappings).on_conflict_do_nothing(index_elements=index_elements)
        session.execute(stmt_pg)
    elif dialect_name == "sqlite":
        stmt_sq = sqlite_insert(model).values(mappings).on_conflict_do_nothing(index_elements=index_elements)
        session.execute(stmt_sq)
    else:
        raise ValueError(f"不支援的資料庫方言: {dialect_name}")


def recalculate_job_progress(session: Session, job_id: str) -> None:
    """
    從資料庫重新計算特定任務的進度統計，並更新 Job.progress_stats。

    通常用於局部重新探測或手動干預資料後，確保 UI 顯示的統計數據與 DB 一致。

    Note:
        此函式僅修改 ``job.progress_stats``，不會自動執行 ``session.commit()``。
        呼叫端負責在需要時自行 commit。

    Args:
        session (Session): SQLAlchemy 資料庫 Session。
        job_id (str): 欲更新統計的任務 ID。
    """
    job = session.query(Job).filter(Job.id == job_id).first()
    if not job:
        return

    # 統計 queue 各狀態數量
    # 狀態包含: pending, completed, failed, skip, warning
    status_counts = (
        session.query(CrawlQueue.status, func.count(CrawlQueue.id))  # pylint: disable=not-callable
        .filter(CrawlQueue.job_id == job_id)
        .group_by(CrawlQueue.status)
        .all()
    )

    counts_dict: dict[str, int] = dict(status_counts)  # type: ignore[arg-type]

    queue_total = sum(counts_dict.values())
    queue_completed = counts_dict.get("completed", 0)
    queue_warning = counts_dict.get("warning", 0)
    queue_skipped = counts_dict.get("skip", 0)
    queue_pending = counts_dict.get("pending", 0)
    queue_failed = counts_dict.get("failed", 0)

    # 統計外部連結總數
    external_total = session.query(func.count(ExternalLink.id)).filter(ExternalLink.job_id == job_id).scalar() or 0  # pylint: disable=not-callable

    progress_dict = {
        "queue": {
            "total": queue_total,
            "completed": queue_completed,
            "warning": queue_warning,
            "skipped": queue_skipped,
            "pending": queue_pending,
            "failed": queue_failed,
        },
        "external_links": external_total,
    }

    job.progress_stats = json.dumps(progress_dict)
