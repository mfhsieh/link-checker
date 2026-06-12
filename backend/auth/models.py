"""
Auth DB 的 SQLAlchemy ORM 模型。

定義與帳號管理相關的四張資料表：
- users：使用者帳號基本資料
- invitations：一次性邀請憑證
- sessions：有效的 Session Token（以雜湊值儲存）
- auth_logs：身分驗證事件日誌

"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuthBase(DeclarativeBase):  # pylint: disable=too-few-public-methods
    """Auth DB 所有模型的基底類別（獨立於 Crawler DB 的 Base）。"""


def _utc_now() -> datetime:
    """
    取得不含時區資訊（naive）的當前 UTC 時間，以配合 SQLite。

    Returns:
        datetime: 當前 UTC 時間。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(AuthBase):  # pylint: disable=too-few-public-methods
    """
    使用者帳號資料表。

    Attributes:
        id (str): 主鍵，UUID v4 字串。
        email (str): 使用者電子郵件（唯一，作為登入帳號）。
        password_hash (str | None): bcrypt 雜湊後的密碼。首次登入設密前為 None。
        role (str): 角色，'user' 或 'admin'。
        status (str): 帳號狀態：pending / active / suspended / expired。
        failed_login_count (int): 連續登入失敗次數（用於帳號鎖定）。
        locked_until (datetime | None): 帳號鎖定解除時間（None 代表未鎖定）。
        created_at (datetime): 建立時間。
        last_login_at (datetime | None): 最後一次成功登入時間。
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Invitation(AuthBase):  # pylint: disable=too-few-public-methods
    """
    邀請憑證資料表。

    每個邀請對應一組 UUID，為單次使用；使用後需標記 used_at。
    超過 expires_at 的邀請自動失效（需在業務邏輯中判斷）。

    Attributes:
        id (str): 主鍵，UUID v4 字串。
        user_id (str): 關聯的使用者 ID（刻意不設 ForeignKey，以免跨庫或跨表 cascade 刪除帶來複雜度，於應用層手動控制）。
        token (str): 邀請 UUID（唯一）。
        expires_at (datetime): 連結有效期限。
        used_at (datetime | None): 使用時間（None 代表尚未使用）。
        created_at (datetime): 建立時間。
    """

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token", name="uq_invitations_token"),
        Index("ix_invitations_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)


class Session(AuthBase):  # pylint: disable=too-few-public-methods
    """
    Session 資料表。

    儲存有效的 Session Token 的雜湊值（非明文），以防資料庫外洩時 Token 被直接複用。
    支援同一帳號多裝置同時登入（同一 user_id 可有多筆有效 Session）。

    Attributes:
        id (str): 主鍵，UUID v4 字串。
        token_hash (str): Session Token 的 SHA-256 雜湊值（唯一）。
        user_id (str): 關聯的使用者 ID（刻意不設 ForeignKey，以免跨表 cascade 刪除帶來複雜度，於應用層手動控制）。
        is_first_login (bool): 是否為首次登入 Session（設密完成前的暫態）。
        expires_at (datetime): 滑動有效期（每次請求後重置）。
        absolute_expires_at (datetime): 最大絕對有效期（不受滑動影響）。
        created_at (datetime): 建立時間。
        ip_address (str | None): 建立 Session 時的客戶端 IP。
        user_agent (str | None): 建立 Session 時的 User-Agent 字串。
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    is_first_login: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuthLog(AuthBase):  # pylint: disable=too-few-public-methods
    """
    身分驗證事件日誌資料表。

    記錄登入成功、失敗、登出、帳號鎖定、密碼設定等安全相關事件。

    Attributes:
        id (int): 主鍵，自動遞增。
        user_id (str | None): 相關使用者 ID（刻意不設 ForeignKey，保留歷史日誌或免去 cascade 複雜度）。
        event_type (str): 事件類型（login_success, login_failed, logout, locked,
                          password_set, password_changed, invitation_sent 等）。
        ip_address (str | None): 事件發生時的客戶端 IP。
        detail (str | None): 附加描述（如失敗原因）。
        created_at (datetime): 事件時間。
    """

    __tablename__ = "auth_logs"
    __table_args__ = (
        Index("ix_auth_logs_user_id", "user_id"),
        Index("ix_auth_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
