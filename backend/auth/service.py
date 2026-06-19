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

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.exc import StaleDataError

from backend.auth.models import AuthLog, Invitation, PasswordResetToken, Session, User
from backend.auth.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from backend.config import get_settings
from backend.email_sender import send_invitation_email, send_password_reset_email

logger: logging.Logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """
    取得不含時區資訊（naive）的當前 UTC 時間。

    Returns:
        datetime: 當前的 UTC 時間物件。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    """
    對 Session Token 進行 SHA-256 雜湊（不可逆，僅儲存雜湊值）。

    Args:
        token (str): 原始 Token。

    Returns:
        str: SHA-256 雜湊值。
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _log_event(
    db: DBSession,
    event_type: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
) -> None:
    """
    寫入身分驗證事件日誌。

    Args:
        db (DBSession): Auth DB Session。
        event_type (str): 記錄的事件類型。
        user_id (str | None): 相關使用者的 ID。
        ip_address (str | None): 客戶端 IP。
        detail (str | None): 補充詳細資訊。
    """
    log = AuthLog(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        detail=detail,
    )
    db.add(log)
    db.commit()


# ── 邀請管理 ───────────────────────────────────────────────────────────────────


def create_invitation(db: DBSession, email: str) -> dict[str, object]:
    """
    建立新使用者帳號並寄送邀請郵件。

    若 email 已存在（且狀態為 pending 或 expired），則重新生成邀請而非建立新帳號。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 受邀者的電子郵件地址。

    Returns:
        dict[str, object]: 包含 user_id、email、token、expires_at 的邀請資料。

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
    """
    判斷帳號是否目前被鎖定。

    Args:
        user (User): 使用者物件。

    Returns:
        bool: 如果被鎖定則回傳 True。
    """
    if user.locked_until and user.locked_until > _utc_now():
        return True
    return False


def _increment_failed_login(db: DBSession, user: User, ip: str | None) -> None:
    """
    增加失敗登入次數，超過閾值則鎖定帳號。

    Args:
        db (DBSession): Auth DB Session。
        user (User): 使用者物件。
        ip (str | None): 客戶端 IP 位址。
    """
    settings = get_settings()
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
        user.locked_until = _utc_now() + timedelta(seconds=settings.LOGIN_LOCKOUT_SECONDS)
        logger.warning(
            "帳號 %s 因連續登入失敗 %d 次，已鎖定至 %s",
            user.email,
            user.failed_login_count,
            user.locked_until,
        )
        _log_event(
            db,
            "account_locked",
            user_id=user.id,
            ip_address=ip,
            detail=f"連續失敗 {user.failed_login_count} 次",
        )
    db.commit()


def _reset_failed_login(db: DBSession, user: User) -> None:
    """
    登入成功後重置失敗計數與鎖定狀態。

    Args:
        db (DBSession): Auth DB Session。
        user (User): 使用者物件。
    """
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()


def authenticate_with_invitation(
    db: DBSession,
    email: str,
    token: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    """
    以邀請 UUID 進行首次登入身分驗證，並建立首次登入 Session。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 使用者電子郵件。
        token (str): 邀請 UUID。
        ip (str | None): 客戶端 IP。
        user_agent (str | None): 客戶端 User-Agent。

    Returns:
        dict[str, object]: 包含 session_token 與 user 資訊。

    Raises:
        ValueError: 邀請無效或帳號狀態不符。
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise ValueError("無效的邀請連結，請確認電子郵件與邀請連結正確。")

    if user.status == "deleted":
        raise ValueError("此帳號已被刪除。")

    if user.status not in ("pending", "expired"):
        raise ValueError("此帳號已完成設定，請使用密碼登入。")

    invitation = (
        db
        .query(Invitation)
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

    # 清除該帳號先前可能遺留的首次登入 Session，避免產生多個有效 first-login session
    db.query(Session).filter(Session.user_id == user.id, Session.is_first_login.is_(True)).delete()

    # 建立首次登入 Session（is_first_login=True，需強制設密）
    session_token, _ = _create_session(db, user.id, ip, user_agent, is_first_login=True)
    _log_event(db, "first_login_attempt", user_id=user.id, ip_address=ip)

    return {
        "session_token": session_token,
        "is_first_login": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
        },
    }


def authenticate_with_password(
    db: DBSession,
    email: str,
    password: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    """
    以電子郵件 + 密碼進行一般登入。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 使用者電子郵件。
        password (str): 純文字密碼。
        ip (str | None): 客戶端 IP。
        user_agent (str | None): 客戶端 User-Agent。

    Returns:
        dict[str, object]: 包含 session_token 與 user 資訊。

    Raises:
        ValueError: 帳號不存在、密碼錯誤、帳號鎖定或狀態不符。
    """
    user = db.query(User).filter(User.email == email).first()

    # 確保無論帳號是否存在或狀態為何，雜湊驗證的耗時都保持一致（防禦 Timing Attack）
    password_is_correct = False
    if user and user.password_hash:
        password_is_correct = verify_password(password, user.password_hash)
    else:
        hash_password(password)

    if not user or not user.password_hash:
        _log_event(db, "login_failed", ip_address=ip, detail=f"帳號不存在或尚未設密: {email}")
        raise ValueError("電子郵件或密碼錯誤。")

    if user.status == "pending":
        # pending 帳號應透過邀請連結完成首次設密，不允許直接密碼登入
        _log_event(
            db,
            "login_failed",
            user_id=user.id,
            ip_address=ip,
            detail="帳號尚未完成設密",
        )
        raise ValueError("此帳號尚未完成首次設定，請使用邀請郵件中的連結進行登入。")

    if user.status == "suspended":
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="帳號已停用")
        raise ValueError("此帳號已被停用，請聯繫管理員。")

    if user.status == "deleted":
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="帳號已被刪除")
        raise ValueError("此帳號已被刪除。")

    if _is_account_locked(user):
        remaining = int((user.locked_until - _utc_now()).total_seconds() / 60)
        raise ValueError(f"帳號因多次登入失敗已暫時鎖定，請 {remaining} 分鐘後再試。")

    if not password_is_correct:
        _increment_failed_login(db, user, ip)
        _log_event(db, "login_failed", user_id=user.id, ip_address=ip, detail="密碼錯誤")
        raise ValueError("電子郵件或密碼錯誤。")

    is_first_time_login = user.last_login_at is None

    # 登入成功
    _reset_failed_login(db, user)
    if not is_first_time_login:
        user.last_login_at = _utc_now()
    db.commit()

    session_token, _ = _create_session(db, user.id, ip, user_agent, is_first_login=is_first_time_login)
    _log_event(db, "login_success", user_id=user.id, ip_address=ip)

    return {
        "session_token": session_token,
        "is_first_login": is_first_time_login,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "status": user.status,
        },
    }


# ── Session 管理 ───────────────────────────────────────────────────────────────


def _create_session(
    db: DBSession,
    user_id: str,
    ip: str | None,
    user_agent: str | None,
    is_first_login: bool = False,
) -> tuple[str, Session]:
    """
    建立新的 Session，回傳原始 token（供設定 Cookie）與 Session ORM 物件。

    Args:
        db (DBSession): Auth DB Session。
        user_id (str): 使用者 ID。
        ip (str | None): 客戶端 IP。
        user_agent (str | None): 客戶端 User-Agent。
        is_first_login (bool): 是否為首次登入，預設為 False。

    Returns:
        tuple[str, Session]: 包含原始 Token 與 Session ORM 物件的元組。
    """
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
        db
        .query(Session)
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

    Args:
        db (DBSession): Auth 資料庫 Session。
        session (Session): 要更新的 Session 物件。
    """
    settings = get_settings()
    session.expires_at = _utc_now() + timedelta(seconds=settings.SESSION_EXPIRE_SECONDS)
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        logger.debug("Session 紀錄可能已被併發登出或背景 GC 清除，略過滑動更新。")
    except SQLAlchemyError as e:
        db.rollback()
        logger.warning("更新 Session 有效期時發生未預期錯誤: %s", e)


def invalidate_session(db: DBSession, raw_token: str, ip: str | None = None) -> None:
    """
    使指定 Session 立即失效（登出），並寫入登出日誌。

    Args:
        db (DBSession): Auth DB Session。
        raw_token (str): Cookie 中的原始 Session Token。
        ip (str | None): 客戶端 IP 位址。
    """
    token_hash = _hash_token(raw_token)
    session = db.query(Session).filter(Session.token_hash == token_hash).first()
    if session:
        user_id = session.user_id
        db.delete(session)
        _log_event(db, "logout", user_id=user_id, ip_address=ip)
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

    # 防禦 Timing Attack，確保無論之前是否設過密碼，執行時間都一致
    is_same_as_initial = False
    if user.password_hash:
        is_same_as_initial = verify_password(new_password, user.password_hash)
    else:
        hash_password(new_password)

    if is_same_as_initial:
        raise ValueError("新密碼不得與初始密碼相同。")

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

    # 防禦 Timing Attack，確保執行時間一致
    password_is_correct = False
    if user and user.password_hash:
        password_is_correct = verify_password(current_password, user.password_hash)
    else:
        hash_password(current_password)

    if not user or not user.password_hash:
        raise ValueError("使用者不存在。")

    if not password_is_correct:
        raise ValueError("現有密碼錯誤。")

    if current_password == new_password:
        raise ValueError("新密碼不得與現有密碼相同。")

    errors = validate_password_strength(new_password, user.email)
    if errors:
        raise ValueError("新密碼不符合安全標準：" + " ".join(errors))

    user.password_hash = hash_password(new_password)
    db.commit()

    _log_event(db, "password_changed", user_id=user_id)


def cleanup_deleted_user_task(user_id: str) -> None:
    """
    背景任務：清理已被軟刪除 (status='deleted') 使用者的跨庫資料，達成最終一致性。

    Args:
        user_id (str): 欲清理的使用者 ID。
    """
    # pylint: disable=import-outside-toplevel
    from backend.auth.db import get_auth_session_local
    from backend.deps import get_job_manager
    from crawler.models import Job

    auth_session_factory = get_auth_session_local()
    manager = get_job_manager()
    crawler_session_factory = manager.session_factory

    # 1. 刪除 Crawler DB 資料
    try:
        with crawler_session_factory() as crawler_db:
            crawler_jobs = crawler_db.query(Job).filter(Job.user_id == user_id).all()
            for job in crawler_jobs:
                crawler_db.delete(job)
            crawler_db.commit()
            if crawler_jobs:
                logger.info("已背景清理使用者 %s 的 %d 個爬蟲任務", user_id, len(crawler_jobs))
    except SQLAlchemyError as e:
        logger.error("背景清理 Crawler DB 時發生錯誤: %s", e)
        return

    # 2. 刪除 Auth DB 資料與實體使用者
    try:
        with auth_session_factory() as auth_db:
            user = auth_db.query(User).filter(User.id == user_id, User.status == "deleted").first()
            if user:
                auth_db.query(Session).filter(Session.user_id == user_id).delete()
                auth_db.query(Invitation).filter(Invitation.user_id == user_id).delete()
                auth_db.delete(user)
                auth_db.commit()
                logger.info("已背景實體刪除使用者 %s (%s)", user.email, user_id)
    except SQLAlchemyError as e:
        logger.error("背景清理 Auth DB 時發生錯誤: %s", e)


def run_session_gc_task() -> None:
    """
    背景任務：清除 Auth DB 中所有已過期的 Session 紀錄 (Garbage Collection)。
    並同時巡檢是否有處於軟刪除狀態 (status='deleted') 尚未清理乾淨的使用者。
    """
    # 延遲載入以避免與 router / deps 產生循環依賴
    from backend.auth.db import get_auth_session_local  # pylint: disable=import-outside-toplevel

    deleted_user_ids = []
    try:
        session_factory = get_auth_session_local()
        with session_factory() as db:
            now = _utc_now()
            count = (
                db.query(Session).filter((Session.expires_at <= now) | (Session.absolute_expires_at <= now)).delete()
            )
            if count > 0:
                db.commit()
                logger.info("Session GC: 成功清理了 %d 筆過期的 Session", count)

            # 巡檢軟刪除未完成的帳號
            deleted_users = db.query(User).filter(User.status == "deleted").all()
            deleted_user_ids = [u.id for u in deleted_users]

    except SQLAlchemyError as e:
        logger.error("Session GC 發生錯誤: %s", e)
        return

    # 脫離 Auth DB session 範圍再執行跨庫清理，避免長時間鎖定
    for uid in deleted_user_ids:
        cleanup_deleted_user_task(uid)


# ── 忘記密碼與重設 ─────────────────────────────────────────────────────────────


def request_password_reset(db: DBSession, email: str, ip: str | None = None) -> None:
    """
    申請重設密碼。

    包含簡易的 IP 限速防護，並防禦帳號列舉攻擊（找不到帳號也不會拋出例外，且確保耗時相近）。

    Args:
        db (DBSession): Auth DB Session。
        email (str): 申請重設的信箱。
        ip (str | None): 客戶端 IP 位址。

    Raises:
        ValueError: 若該 IP 請求過於頻繁時拋出。
    """
    settings = get_settings()
    # 簡易限速：同一 IP 在設定時間內最多允許的申請次數
    if ip:
        recent_requests = (
            db
            .query(AuthLog)
            .filter(
                AuthLog.event_type == "password_reset_requested",
                AuthLog.ip_address == ip,
                AuthLog.created_at >= _utc_now() - timedelta(seconds=settings.PASSWORD_RESET_WINDOW_SECONDS),
            )
            .count()
        )
        if recent_requests >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
            logger.warning("IP %s 申請重設密碼頻率過高", ip)
            raise ValueError("請求過於頻繁，請稍後再試。")

    _log_event(db, "password_reset_requested", ip_address=ip, detail=email)

    user = db.query(User).filter(User.email == email).first()

    # 為了防禦 Timing Attack，即使帳號不存在，我們也做一次無用的雜湊運算
    dummy_token = secrets.token_urlsafe(32)
    _hash_token(dummy_token)

    if not user or user.status not in ("active", "suspended"):
        # 找不到帳號或狀態不允許，直接返回，不透露資訊
        return

    # 產生 Token 並儲存 Hash (1 小時過期)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = _utc_now() + timedelta(hours=1)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)
    db.commit()

    # 寄送重設信件
    send_password_reset_email(email, raw_token)


def reset_password(db: DBSession, token: str, new_password: str, ip: str | None = None) -> None:
    """
    透過重設 Token 設定新密碼。

    Args:
        db (DBSession): Auth DB Session。
        token (str): 郵件中的重設 Token。
        new_password (str): 新密碼。
        ip (str | None): 客戶端 IP 位址。

    Raises:
        ValueError: Token 無效、過期，或新密碼強度不足。
    """
    token_hash = _hash_token(token)
    reset_record = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()

    if not reset_record or reset_record.used_at is not None:
        raise ValueError("無效的或已使用的重設連結。")

    if reset_record.expires_at < _utc_now():
        raise ValueError("重設連結已過期，請重新申請。")

    user = db.query(User).filter(User.id == reset_record.user_id).first()
    if not user:
        raise ValueError("無效的重設連結。")

    errors = validate_password_strength(new_password, user.email)
    if errors:
        raise ValueError("新密碼不符合安全標準：" + " ".join(errors))

    user.password_hash = hash_password(new_password)
    reset_record.used_at = _utc_now()
    user.failed_login_count = 0
    user.locked_until = None

    db.commit()

    # 清除該使用者的所有現有 Session，強制重新登入
    invalidate_all_user_sessions(db, user.id)
    _log_event(db, "password_reset_success", user_id=user.id, ip_address=ip)
