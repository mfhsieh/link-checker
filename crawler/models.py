"""
爬蟲專用的資料庫模型。

此模組定義了 SQLAlchemy ORM 模型，用於追蹤 Job、爬取佇列 (Queue)
以及探索到的外部連結，並採用 SQLAlchemy 2.0 的 Type Hinting 宣告風格。

公開元素：

- ``Base``：所有 ORM 模型的共同基底類別。
- ``CrawlerConfig``：爬蟲引擎的運行期配置封裝物件。
- ``Job``：表一個完整的爬蟲任務紀錄。
- ``CrawlQueue``：表一筆等待爬取的網址佇列項目。
- ``ExternalLink``：表在爬蟲任務期間發現的外部連結紀錄。
- ``apply_job_result_filters``：對外連查詢套用搜尋、排除與狀態篩選條件的共用工具函式。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Query, mapped_column, relationship

from crawler.config_utils import DEFAULT_GLOBAL_CONFIG

_crawler_def = DEFAULT_GLOBAL_CONFIG.get("crawler", {})
_DEF: dict[str, object] = _crawler_def if isinstance(_crawler_def, dict) else {}


class Base(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """
    所有 SQLAlchemy 宣告式模型的基底類別 (Base Class)。

    此專案中的所有 ORM 模型（``Job``、``CrawlQueue``、``ExternalLink``）
    均繼承此類別，以便統一管理 ``metadata`` 與 ``Base.metadata.create_all()``。
    """


def get_utc_now() -> datetime:
    """
    取得不含時區資訊（naive）的當前 UTC 時間，以配合 SQLite 儲存格式。

    與 auth/models.py 的 _utc_now() 保持一致策略。

    Returns:
        datetime: 不含時區的當前 UTC 時間物件。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class CrawlerConfig:  # pylint: disable=too-many-instance-attributes
    """
    爬蟲引擎的全域與進階配置物件。

    Attributes:
        timeout (int): 網頁請求等待回應的最大秒數。
        connect_timeout (float): TCP 建立連線等待時間。
        external_check_timeout (float): 外連存活檢查等待時間。
        ignore_extensions (list[str]): 忽略的副檔名清單。
        mime_type_filter (dict[str, object]): MIME 類型過濾設定。
        ignore_regexes (list[str]): 忽略的路徑規則清單。
        user_agent (str | None): 自訂 User-Agent 標頭。
        ssl_exempt_domains (list[str]): 自簽憑證豁免網域清單。
        proxy_url (str | None): 代理伺服器網址。
        max_content_length (int): 最大下載容量限制 (Bytes)。
        max_redirects (int): 最大重導向次數限制。
        social_domains (list[str]): 社群與反爬蟲網域清單。
    """

    timeout: int = cast(int, _DEF["timeout"])
    connect_timeout: float = cast(float, _DEF["connect_timeout"])
    external_check_timeout: float = cast(float, _DEF["external_check_timeout"])
    ignore_extensions: list[str] = field(default_factory=lambda: cast(list[str], _DEF["ignore_extensions"]))
    mime_type_filter: dict[str, object] = field(
        default_factory=lambda: cast(dict[str, object], _DEF["mime_type_filter"])
    )
    ignore_regexes: list[str] = field(default_factory=lambda: cast(list[str], _DEF["ignore_regexes"]))
    user_agent: str | None = cast(str | None, _DEF["user_agent"])
    ssl_exempt_domains: list[str] = field(default_factory=lambda: cast(list[str], _DEF["ssl_exempt_domains"]))
    proxy_url: str | None = cast(str | None, _DEF["proxy_url"])
    max_content_length: int = cast(int, _DEF["max_content_length"])
    max_redirects: int = cast(int, _DEF["max_redirects"])
    social_domains: list[str] = field(default_factory=lambda: cast(list[str], _DEF["social_domains"]))

    def __post_init__(self) -> None:
        """
        在 dataclass 初始化完成後，確保所有可變預設值皆有有效的初始列表。

        當 ``ignore_extensions``、``mime_type_filter``、``ignore_regexes``、
        ``ssl_exempt_domains``、``social_domains`` 之一為 None 時，
        將其改寫為從 ``DEFAULT_GLOBAL_CONFIG`` 複製的預設值。
        此防禦性處理有其必要，因為 ``cast()`` 在少數情況下可能回傳 None，
        而可變預設值若共用同一物件會導致意外連帶修改。
        """
        if self.ignore_extensions is None:
            self.ignore_extensions = list(_DEF["ignore_extensions"])
        if self.mime_type_filter is None:
            self.mime_type_filter = dict(_DEF["mime_type_filter"])
        if self.ignore_regexes is None:
            self.ignore_regexes = list(_DEF["ignore_regexes"])
        if self.ssl_exempt_domains is None:
            self.ssl_exempt_domains = list(_DEF["ssl_exempt_domains"])
        if self.social_domains is None:
            self.social_domains = list(_DEF["social_domains"])


class Job(Base):  # pylint: disable=too-few-public-methods
    """
    代表一個爬蟲任務 (Job)。

    Attributes:
        id (str): 任務的主鍵 (Primary Key)，使用 UUID 格式。
        user_id (str | None): 該任務的擁有者 ID。若是系統匿名任務則為 None。
        start_url (str): 爬蟲起始的網址。
        target_domains (str): 允許爬蟲進入的網域清單，以逗號分隔。
        trusted_domains (str): 被視為信任網域的清單，以逗號分隔。
        status (str): 任務的當前狀態
            (例如：pending, queued, starting, running, paused, completed, error)。
        config_json (str | None): 紀錄啟動時的爬蟲設定 (JSON 格式)，以確保後續 Resume 設定一致。
        progress_stats (str | None): 由爬蟲器寫入的任務進度統計快取 (JSON 格式)。用於加速
            ``get_job_report`` 查詢，避免每次全表掃描。
        created_at (datetime): 任務建立的時間戳記。
        updated_at (datetime): 任務最後更新的時間戳記。
        queues (list[CrawlQueue]): 此任務中等待爬取的網址佇列關聯。
        external_links (list[ExternalLink]): 此任務中所找到的外部連結紀錄關聯。
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_domains: Mapped[str] = mapped_column(Text, nullable=False)
    trusted_domains: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress_stats: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    queues: Mapped[list["CrawlQueue"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    external_links: Mapped[list["ExternalLink"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class CrawlQueue(Base):  # pylint: disable=too-few-public-methods
    """
    代表特定任務在爬取佇列 (Queue) 中的一筆網址紀錄。

    Attributes:
        id (int): 佇列項目的主鍵。
        job_id (str): 關聯到所屬任務的外部鍵 (Foreign Key)。
        url (str): 準備要爬取的網址。
        source_url (str | None): 發現此網址的來源網頁網址（若為起始網址則為 None）。
        status (str): 此網址的當前狀態 (例如：pending, completed, failed, warning, skipped)。
        status_code (int | None): HTTP 回應狀態碼（尚未處理時為 None）。
        retry_count (int): 目前已經失敗並重試的次數。
        depth (int): 此網址在爬取樹狀結構中的深度層數（從起始網址計起）。
        error_message (str | None): 若爬取失敗時的例外或錯誤訊息紀錄。
        status_category (str): 狀態分類總結，用於快速統計（例如：pending, completed, warning, failed）。
        is_secure (bool): 指示該網址是否通過 HTTPS 連線，用於安全性報告。
        created_at (datetime): 此網址加入佇列的時間戳記。
        updated_at (datetime): 此網址狀態最後更新的時間戳記。
        job (Job): 關聯的任務物件。
    """

    __tablename__ = "crawl_queue"
    __table_args__ = (
        Index("ix_crawl_queue_job_url", "job_id", "url"),
        Index("ix_crawl_queue_job_status_id", "job_id", "status", "id"),
        Index("ix_crawl_queue_job_category", "job_id", "status_category"),
        Index(
            "ix_crawl_queue_internal_issues",
            "job_id",
            postgresql_where=text("status IN ('failed', 'warning') OR is_secure = false"),
            sqlite_where=text("status IN ('failed', 'warning') OR is_secure = 0"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    depth: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_category: Mapped[str] = mapped_column(String(30), default="pending")
    is_secure: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    job: Mapped["Job"] = relationship(back_populates="queues")


class ExternalLink(Base):  # pylint: disable=too-few-public-methods
    """
    代表在爬蟲任務期間找到的外部連結紀錄。

    Attributes:
        id (int): 外部連結紀錄的主鍵。
        job_id (str): 關聯到所屬任務的外部鍵。
        source_url (str): 發現此外部連結的來源網頁網址。
        target_url (str): 外部連結本身的網址。
        target_domain (str): 外部連結的網域名稱，用於分組與索引加速查詢。
        ip_address (str | None): 該外部連結網域解析出的 IP 位址（IPv4 或 IPv6）。
        is_secure (bool): 指示該外部連結是否通過 HTTPS 安全連線。
        http_status_code (int | None): 探測到的 HTTP 狀態碼（尚未探測則為 None）。
        error_message (str | None): 探測時發生的錯誤訊息（如 DNS 失敗、連線消時）。
        status_category (str): 外連狀態分類，用於快速評估健康度
            (例如：pending, healthy, not_found, server_error, connection_error, other_error, blocked, dns_failed)。
        created_at (datetime): 紀錄此外部連結的時間戳記。
        updated_at (datetime): 此外連狀態最後更新的時間戳記。
        job (Job): 關聯的任務物件。
    """

    __tablename__ = "external_links"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "source_url",
            "target_url",
            name="uq_external_links_job_src_tgt",
        ),
        Index("ix_external_links_job_created", "job_id", "created_at"),
        Index("ix_external_links_job_category", "job_id", "status_category"),
        Index("ix_external_links_job_domain", "job_id", "target_domain"),
        Index("ix_external_links_job_target", "job_id", "target_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_domain: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    is_secure: Mapped[bool] = mapped_column(default=True)
    http_status_code: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 依 Code Review 修正預設語意，新建之外部連結尚未實際探測，應為 pending (修改前為 healthy)
    status_category: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    job: Mapped["Job"] = relationship(back_populates="external_links")


def apply_job_result_filters(
    query: Query,
    search: str | None = None,
    exclude: str | None = None,
    status_filter: str | None = None,
) -> Query:
    """
    對外連查詢套用搜尋、排除與狀態篩選條件。

    該函式套用的所有 LIKE 查詢均會對特殊字元 (``%``、``_``、``\\``)
    進行逸出處理，防範 SQL LIKE Injection。

    Args:
        query (Query): SQLAlchemy 查詢物件（基於 ``ExternalLink``）。
        search (str | None): (選填) 對 ``target_url`` 與 ``source_url`` 進行模糊搜尋的關鍵字。
        exclude (str | None): (選填) 要從 ``target_url`` 中排除的關鍵字，
            多項以逗號分隔（例如 ``"example.com,test.org"``）。
        status_filter (str | None): (選填) 依據 ``status_category`` 進行狀態篩選，
            支援的値為：
            - ``"dead"`` 或 ``"dns_failed"``：dns_failed 類別。
            - ``"broken"``：not_found, server_error, connection_error, other_error 類別。
            - ``"not_found"``：HTTP 404 類別。
            - ``"server_error"``：HTTP 5xx 類別。
            - ``"connection_error"``：連線失敗。
            - ``"other_error"``：其他錯誤類別。
            - ``"blocked"``：被對方識別為機器人或主動封鎖。
            - ``"insecure"``：已完成探測且為非 HTTPS 連線。
            - ``"healthy"``：正常可連結。
            - 其他值或 None：不套用任何狀態過濾。

    Returns:
        Query: 加上過濾條件後的 SQLAlchemy 查詢物件。
    """
    if search:
        # 防範 LIKE Injection：對 LIKE 語法的特殊字元 (%, _) 與跳脫字元 (\) 進行逸出處理
        search_escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{search_escaped}%"
        query = query.filter(
            ExternalLink.target_url.like(search_pattern, escape="\\")
            | ExternalLink.source_url.like(search_pattern, escape="\\")
        )

    if exclude:
        excludes = [e.strip() for e in exclude.split(",") if e.strip()]
        for exc in excludes:
            # 同樣防範 LIKE Injection，保護排除查詢的效能與正確性
            exc_escaped = exc.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(~ExternalLink.target_url.ilike(f"%{exc_escaped}%", escape="\\"))

    if status_filter in ("dead", "dns_failed"):
        query = query.filter(ExternalLink.status_category == "dns_failed")
    elif status_filter == "broken":
        query = query.filter(
            ExternalLink.status_category.in_(["not_found", "server_error", "connection_error", "other_error"])
        )
    elif status_filter == "not_found":
        query = query.filter(ExternalLink.status_category == "not_found")
    elif status_filter == "server_error":
        query = query.filter(ExternalLink.status_category == "server_error")
    elif status_filter == "connection_error":
        query = query.filter(ExternalLink.status_category == "connection_error")
    elif status_filter == "other_error":
        query = query.filter(ExternalLink.status_category == "other_error")
    elif status_filter == "blocked":
        query = query.filter(ExternalLink.status_category == "blocked")
    elif status_filter == "insecure":
        query = query.filter(
            ExternalLink.is_secure == False,  # pylint: disable=singleton-comparison  # noqa: E712
            ExternalLink.status_category != "pending",
        )
    elif status_filter == "healthy":
        query = query.filter(ExternalLink.status_category == "healthy")
    return query
