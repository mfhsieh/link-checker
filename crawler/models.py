"""
爬蟲專用的資料庫模型。

此模組定義了 SQLAlchemy ORM 模型，用於追蹤 Job、爬取佇列 (Queue)
以及探索到的外部連結，並採用 SQLAlchemy 2.0 的 Type Hinting 宣告風格。
"""
# pylint: disable=unsubscriptable-object

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# pylint: disable=too-few-public-methods
class Base(DeclarativeBase):
    """所有 SQLAlchemy 宣告式模型的基底類別 (Base Class)。"""


def get_utc_now() -> datetime:
    """
    取得不含時區資訊（naive）的當前 UTC 時間，以配合 SQLite 儲存格式。

    與 auth/models.py 的 _utc_now() 保持一致策略。

    Returns:
        datetime: 不含時區的當前 UTC 時間物件。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(Base):
    """
    代表一個爬蟲任務 (Job)。

    Attributes:
        id (str): 任務的主鍵 (Primary Key)，使用 UUID 格式。
        user_id (str | None): 該任務的擁有者 ID。若是系統匿名任務則為 None。
        start_url (str): 爬蟲起始的網址。
        target_domains (str): 允許爬蟲進入的網域清單，以逗號分隔。
        trusted_domains (str): 被視為信任網域的清單，以逗號分隔。
        status (str): 任務的當前狀態 (例如：pending, running, paused, completed, error)。
        config_json (str | None): 紀錄啟動時的爬蟲設定 (JSON 格式)，以確保後續 Resume 設定一致。
        created_at (datetime): 任務建立的時間戳記。
        updated_at (datetime): 任務最後更新的時間戳記。
        queues (list[CrawlQueue]): 此任務中等待爬取的網址佇列關聯。
        external_links (list[ExternalLink]): 此任務中所找到的外部連結紀錄關聯。
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    start_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_domains: Mapped[str] = mapped_column(Text, nullable=False)
    trusted_domains: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    queues: Mapped[list["CrawlQueue"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    external_links: Mapped[list["ExternalLink"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class CrawlQueue(Base):
    """
    代表特定任務在爬取佇列 (Queue) 中的一筆網址紀錄。

    Attributes:
        id (int): 佇列項目的主鍵。
        job_id (str): 關聯到所屬任務的外部鍵 (Foreign Key)。
        url (str): 準備要爬取的網址。
        source_url (str | None): 發現此網址的來源網頁網址 (若為起始網址則為 None)。
        status (str): 此網址的當前狀態 (例如：pending, completed, failed)。
        retry_count (int): 目前已經失敗並重試的次數。
        error_message (str | None): 若爬取失敗時的例外或錯誤訊息紀錄。
        created_at (datetime): 此網址加入佇列的時間戳記。
        updated_at (datetime): 此網址狀態最後更新的時間戳記。
        job (Job): 關聯的任務物件。
    """

    __tablename__ = "crawl_queue"
    __table_args__ = (
        Index("ix_crawl_queue_job_url", "job_id", "url"),
        Index("ix_crawl_queue_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    depth: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    job: Mapped["Job"] = relationship(back_populates="queues")


class ExternalLink(Base):
    """
    代表在爬蟲任務期間找到的外部連結紀錄。

    Attributes:
        id (int): 外部連結紀錄的主鍵。
        job_id (str): 關聯到所屬任務的外部鍵。
        source_url (str): 發現此外部連結的來源網頁網址。
        target_url (str): 外部連結本身的網址。
        ip_address (str | None): 該外部連結網域解析出的 IP 位址。
        created_at (datetime): 紀錄此外部連結的時間戳記。
        job (Job): 關聯的任務物件。
    """

    __tablename__ = "external_links"
    __table_args__ = (
        Index("ix_external_links_job_src_tgt", "job_id", "source_url", "target_url"),
        UniqueConstraint(
            "job_id",
            "source_url",
            "target_url",
            name="uq_external_links_job_src_tgt",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    is_secure: Mapped[bool] = mapped_column(default=True)
    http_status_code: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_utc_now)

    job: Mapped["Job"] = relationship(back_populates="external_links")
