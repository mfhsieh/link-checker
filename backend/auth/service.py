"""
身分驗證業務邏輯服務模組。

封裝所有與帳號認證相關的業務邏輯，包括：
- 邀請制帳號建立與邀請郵件寄送
- 首次登入（email + UUID 驗證）
- 一般登入（email + password）
- Session 管理（建立、驗證、刷新有效期、登出）
- 密碼設定與變更
- 帳號鎖定保護
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from backend.auth.models import AuthLog, Invitation, Session, User
from backend.auth.password import hash_password, validate_password_strength, verify_password
from backend.config import get_settings
from backend.email_sender import send_invitation_email

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    """對 Session Token 進行 SHA-256 雜湊（不可逆，僅儲存雜湊值）。"""
    return hashlib.sha256(token.encode()).hexdigest()


def _log_event(
    db: DBSession,
    event_type: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
) -> None:
    """寫入身分驗證事件日誌。"""
    log = AuthLog(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        detail=detail,
    )
    db.add(log)
    db.commit()


# ── 邀請管理 ───────────────────────────────────────────────────────────────────

def create_invitation(db: DBSession, email: str) -> dict[str, Any]:
    """
    建立新使用者帳號並寄送邀請郵件。

    若 email 已存在（且狀態為 pending 或 expired），則重新生成邀請而非建立新帳號。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 受邀者的電子郵件地址。

    Returns:
        dict: 包含 user_id、email、token、expires_at 的邀請資料。

    Raises:
        ValueError: 若 email 格式無效或帳號已為 active/suspended 狀態。
    """
    settings = get_settings()

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        if existing_user.status in ("active", "suspended"):
            raise ValueError(f"帳號 {email} 已存在（狀態：{existing_user.status}），無法重複邀請。")
        # pending / expired → 重新邀請，沿用既有帳號
        user = existing_user
        user.status = "pending"
        # 廢棄舊邀請
        db.query(Invitation).filter(
            Invitation.user_id == user.id,
            Invitation.used_at.is_(None),
        ).delete()
    else:
        user = User(email=email, role="user", status="pending")
        db.add(user)
        db.flush()  # 取得 user.id

    token = str(uuid.uuid4())
    expires_at = _utc_now() + timedelta(seconds=settings.INVITATION_EXPIRE_SECONDS)
    invitation = Invitation(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()

    # 寄送邀請郵件（非同步失敗不影響帳號建立）
    sent = send_invitation_email(email, token)
    if not sent:
        logger.warning("邀請郵件寄送失敗（帳號已建立）: %s", email)

    _log_event(db, "invitation_sent", user_id=user.id, detail=email)

    return {
        "user_id": user.id,
        "email": email,
        "token": token,
        "expires_at": expires_at.isoformat(),
    }


# ── 登入驗證 ───────────────────────────────────────────────────────────────────

def _is_account_locked(user: User) -> bool:
    """判斷帳號是否目前被鎖定。"""
    if user.locked_until and user.locked_until > _utc_now():
        return True
    return False


def _increment_failed_login(db: DBSession, user: User, ip: str | None) -> None:
    """增加失敗登入次數，超過閾值則鎖定帳號。"""
    settings = get_settings()
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
        user.locked_until = _utc_now() + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
        logger.warning("帳號 %s 因連續登入失敗 %d 次，已鎖定至 %s", user.email, user.failed_login_count, user.locked_until)
        _log_event(db, "account_locked", user_id=user.id, ip_address=ip,
                   detail=f"連續失敗 {user.failed_login_count} 次")
    db.commit()


def _reset_failed_login(db: DBSession, user: User) -> None:
    """登入成功後重置失敗計數與鎖定狀態。"""
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()


def authenticate_with_invitation(
    db: DBSession,
    email: str,
    token: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    以邀請 UUID 進行首次登入身分驗證，並建立首次登入 Session。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 使用者電子郵件。
        token (str): 邀請 UUID。
        ip (str | None): 客戶端 IP。
        user_agent (str | None): 客戶端 User-Agent。

    Returns:
        dict: 包含 session_token 與 user 資訊。

    Raises:
        ValueError: 邀請無效或帳號狀態不符。
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise ValueError("無效的邀請連結，請確認電子郵件與邀請連結正確。")

    if user.status not in ("pending", "expired"):
        raise ValueError("此帳號已完成設定，請使用密碼登入。")

    invitation = (
        db.query(Invitation)
        .filter(
            Invitation.user_id == user.id,
            Invitation.token == token,
            Invitation.used_at.is_(None),
        )
        .first()
    )
    if not invitation:
        raise ValueError("無效的邀請連結，Token 不存在或已使用。")

    if invitation.expires_at < _utc_now():
        user.status = "expired"
        db.commit()
        raise ValueError("邀請連結已過期，請聯繫管理員重新寄送邀請。")

    # 建立首次登入 Session（is_first_login=True，需強制設密）
    session_token, session = _create_session(db, user.id, ip, user_agent, is_first_login=True)
    _log_event(db, "first_login_attempt", user_id=user.id, ip_address=ip)

    return {
        "session_token": session_token,
        "is_first_login": True,
        "user": {"id": user.id, "email": user.email, "role": user.role, "status": user.status},
    }


def authenticate_with_password(
    db: DBSession,
    email: str,
    password: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    以電子郵件 + 密碼進行一般登入。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 使用者電子郵件。
        password (str): 純文字密碼。
        ip (str | None): 客戶端 IP。
        user_agent (str | None): 客戶端 User-Agent。

    Returns:
        dict: 包含 session_token 與 user 資訊。

    Raises:
        ValueError: 帳號不存在、密碼錯誤、帳號鎖定或狀態不符。
    """
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash:
        _log_event(db, "login_failed", ip_address=ip, detail=f"帳號不存在或尚未設密: {email}")
        raise ValueError("電子郵件或密碼錯誤。")

    if user.status == "suspended":
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="帳號已停用")
        raise ValueError("此帳號已被停用，請聯繫管理員。")

    if user.status == "pending":
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="帳號尚未完成設定")
        raise ValueError("此帳號尚未完成設定，請使用邀請連結完成首次登入。")

    if _is_account_locked(user):
        remaining = int((user.locked_until - _utc_now()).total_seconds() / 60)
        raise ValueError(f"帳號因多次登入失敗已暫時鎖定，請 {remaining} 分鐘後再試。")

    if not verify_password(password, user.password_hash):
        _increment_failed_login(db, user, ip)
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="密碼錯誤")
        raise ValueError("電子郵件或密碼錯誤。")

    # 登入成功
    _reset_failed_login(db, user)
    user.last_login_at = _utc_now()
    db.commit()

    session_token, _ = _create_session(db, user.id, ip, user_agent, is_first_login=False)
    _log_event(db, "login_success", user_id=user.id, ip_address=ip)

    return {
        "session_token": session_token,
        "is_first_login": False,
        "user": {"id": user.id, "email": user.email, "role": user.role, "status": user.status},
    }


# ── Session 管理 ───────────────────────────────────────────────────────────────

def _create_session(
    db: DBSession,
    user_id: str,
    ip: str | None,
    user_agent: str | None,
    is_first_login: bool = False,
) -> tuple[str, Session]:
    """建立新的 Session，回傳原始 token（供設定 Cookie）與 Session ORM 物件。"""
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    now = _utc_now()

    session = Session(
        token_hash=token_hash,
        user_id=user_id,
        is_first_login=is_first_login,
        expires_at=now + timedelta(seconds=settings.SESSION_EXPIRE_SECONDS),
        absolute_expires_at=now + timedelta(seconds=settings.SESSION_MAX_AGE_SECONDS),
        ip_address=ip,
        user_agent=user_agent,
    )
    db.add(session)
    db.commit()
    return raw_token, session


def get_session_by_token(db: DBSession, raw_token: str) -> Session | None:
    """
    透過原始 Token 查詢有效的 Session。

    同時驗證 expires_at 與 absolute_expires_at。

    Args:
        db (DBSession): Auth DB Session。
        raw_token (str): Cookie 中的原始 Session Token。

    Returns:
        Session | None: 有效的 Session 物件，或 None（若無效或已過期）。
    """
    token_hash = _hash_token(raw_token)
    now = _utc_now()
    return (
        db.query(Session)
        .filter(
            Session.token_hash == token_hash,
            Session.expires_at > now,
            Session.absolute_expires_at > now,
        )
        .first()
    )


def refresh_session(db: DBSession, session: Session) -> None:
    """
    滑動更新 Session 有效期（Sliding Window）。

    每次成功的 API 請求後呼叫，重置 expires_at（不影響 absolute_expires_at）。
    """
    settings = get_settings()
    session.expires_at = _utc_now() + timedelta(seconds=settings.SESSION_EXPIRE_SECONDS)
    db.commit()


def invalidate_session(db: DBSession, raw_token: str) -> None:
    """
    使指定 Session 立即失效（登出）。

    Args:
        db (DBSession): Auth DB Session。
        raw_token (str): Cookie 中的原始 Session Token。
    """
    token_hash = _hash_token(raw_token)
    db.query(Session).filter(Session.token_hash == token_hash).delete()
    db.commit()


def invalidate_all_user_sessions(db: DBSession, user_id: str) -> int:
    """
    強制失效指定使用者的所有 Session（帳號停用時使用）。

    Args:
        db (DBSession): Auth DB Session。
        user_id (str): 使用者 ID。

    Returns:
        int: 被刪除的 Session 數量。
    """
    count = db.query(Session).filter(Session.user_id == user_id).delete()
    db.commit()
    return count


# ── 密碼管理 ───────────────────────────────────────────────────────────────────

def set_first_password(
    db: DBSession,
    session: Session,
    new_password: str,
) -> None:
    """
    完成首次登入的強制密碼設定。

    驗證通過後：
    1. 更新 password_hash
    2. 將帳號狀態設為 active
    3. 將邀請 token 標記為已使用
    4. 將 session.is_first_login 設為 False

    Args:
        db (DBSession): Auth DB Session。
        session (Session): 首次登入 Session。
        new_password (str): 使用者設定的新密碼（純文字）。

    Raises:
        ValueError: 密碼不符合安全標準。
    """
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise ValueError("使用者不存在。")

    errors = validate_password_strength(new_password, user.email)
    if errors:
        raise ValueError("密碼不符合安全標準：" + " ".join(errors))

    user.password_hash = hash_password(new_password)
    user.status = "active"
    user.last_login_at = _utc_now()

    # 將對應的邀請 token 標記為已使用
    db.query(Invitation).filter(
        Invitation.user_id == user.id,
        Invitation.used_at.is_(None),
    ).update({"used_at": _utc_now()})

    # Session 轉為正常登入狀態
    session.is_first_login = False
    db.commit()

    _log_event(db, "password_set", user_id=user.id)


def change_password(
    db: DBSession,
    user_id: str,
    current_password: str,
    new_password: str,
) -> None:
    """
    已登入使用者主動修改密碼。

    Args:
        db (DBSession): Auth DB Session。
        user_id (str): 使用者 ID。
        current_password (str): 目前的密碼（需先驗證）。
        new_password (str): 欲設定的新密碼。

    Raises:
        ValueError: 現有密碼錯誤或新密碼不符合安全標準。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.password_hash:
        raise ValueError("使用者不存在。")

    if not verify_password(current_password, user.password_hash):
        raise ValueError("現有密碼錯誤。")

    errors = validate_password_strength(new_password, user.email)
    if errors:
        raise ValueError("新密碼不符合安全標準：" + " ".join(errors))

    user.password_hash = hash_password(new_password)
    db.commit()

    _log_event(db, "password_changed", user_id=user_id)
