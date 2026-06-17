"""
任務狀態通知模組。

負責在爬蟲任務完成或發生錯誤時，組裝報表統計資訊並發送 Email 通知信。
獨立於 manager.py 以符合單一職責原則 (SRP)。
"""

import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy.exc
from sqlalchemy.orm import Session

from crawler.models import ExternalLink, Job

try:
    from backend.auth.db import get_auth_session_local
    from backend.auth.models import User
    from backend.email_sender import send_notification_email

    _BACKEND_AVAILABLE: bool = True
except ImportError:
    _BACKEND_AVAILABLE = False

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class JobStats:
    """外部連結統計資訊。

    Attributes:
        total (int): 外部連結總數。
        healthy (int): 正常連結數。
        broken (int): 損壞連結數 (實質失效或連線異常)。
        dead (int): 失效連結數 (DNS 解析失敗)。
        blocked (int): 權限阻擋數。
    """

    total: int
    healthy: int
    broken: int
    dead: int
    blocked: int


def _get_user_email(user_id: str) -> str | None:
    """取得使用者的 Email。

    Args:
        user_id (str): 查詢的使用者 ID。

    Returns:
        str | None: 使用者的 Email 字串，若無則回傳 None。
    """
    try:
        auth_session_factory = get_auth_session_local()
        with auth_session_factory() as auth_session:
            user = auth_session.query(User).filter(User.id == user_id).first()
            if not user or not user.email:
                return None
            return user.email
    except sqlalchemy.exc.SQLAlchemyError as ex:
        logger.error(
            "[Email Notification] 自 Auth DB 查詢使用者 %s 的信箱時發生錯誤: %s",
            user_id,
            ex,
        )
        return None


def _build_and_send_email(
    to_email: str,
    job: Job,
    status: str,
    stats: JobStats,
) -> None:
    """組裝並寄送通知信。

    Args:
        to_email (str): 收件者 Email。
        job (Job): 目標爬蟲任務。
        status (str): 任務狀態 ("completed" 或 "failed")。
        stats (JobStats): 任務統計數據。
    """
    status_text = "已完成 (Completed)" if status == "completed" else "發生嚴重異常 (Error)"
    subject = f"【外部連結檢查系統】任務狀態通知 ({status_text}) - 任務 ID: {job.id}"

    plain_text = (
        f"您好，\n\n"
        f"您所建立的外部連結檢查任務已執行結束。\n\n"
        f"任務資訊：\n"
        f"  - 任務 ID：{job.id}\n"
        f"  - 起始網址：{job.start_url}\n"
        f"  - 任務狀態：{status_text}\n"
        f"  - 建立時間：{job.created_at}\n"
        f"  - 結束時間：{job.updated_at}\n\n"
        f"外部連結檢查統計：\n"
        f"  - 總共發現外部連結數：{stats.total}\n"
        f"  - 正常連結 (Healthy)：{stats.healthy} 個\n"
        f"  - 損壞連結 (Broken Links，實質失效或連線異常)：{stats.broken} 個\n"
        f"  - 權限阻擋 (Blocked，遭防火牆阻擋之低風險連結)：{stats.blocked} 個\n"
        f"  - 失效連結 (Dead Links，DNS 解析失敗)：{stats.dead} 個\n\n"
        f"詳細檢查結果，請登入系統後台查看。\n\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    html_body = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#333;">
  <h2 style="color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:12px;">外部連結檢查任務通知</h2>
  <p>您好，</p>
  <p>您所建立的外部連結檢查任務已執行結束。詳細統計數據請登入系統查看。</p>
  <p style="color:#999;font-size:0.75rem;">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

    try:
        send_notification_email(to_email, subject, plain_text, html_body)
    except smtplib.SMTPException as ex:
        logger.error("[Email Notification] 寄送任務通知信失敗: %s", ex)


def send_job_status_notification(session_factory: Callable[[], Session], job_id: str, status: str) -> None:
    """
    在任務完成或發生錯誤時，向任務建立者發送 Email 通知，並附帶結果統計。

    Args:
        session_factory (Callable[[], Session]): Crawler DB 的 Session 工廠。
        job_id (str): 任務 ID。
        status (str): 結束的狀態 ('completed' 或 'error')。

    Returns:
        None
    """
    if not _BACKEND_AVAILABLE:
        logger.warning("[Email Notification] 因無法載入後端模組，跳過通知信發送。")
        return

    with session_factory() as session:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return

        user_id = job.user_id
        if not user_id:
            logger.info("[Email Notification] 任務為匿名任務，不發送通知信。")
            return

        to_email = _get_user_email(user_id)
        if not to_email:
            logger.warning(
                "[Email Notification] 找不到使用者 ID %s 或其無信箱設定，跳過通知信發送。",
                user_id,
            )
            return

        # 統計外部連結狀態
        dead_count = (
            session.query(ExternalLink)
            .filter(
                ExternalLink.job_id == job_id,
                (ExternalLink.ip_address.is_(None)) | (ExternalLink.ip_address == ""),
            )
            .count()
        )
        blocked_count = (
            session.query(ExternalLink)
            .filter(
                ExternalLink.job_id == job_id,
                ExternalLink.http_status_code.in_([401, 403, 405, 406, 429]),
            )
            .count()
        )
        broken_count = (
            session.query(ExternalLink)
            .filter(
                ExternalLink.job_id == job_id,
                (
                    (ExternalLink.http_status_code >= 400)
                    & (~ExternalLink.http_status_code.in_([401, 403, 405, 406, 429]))
                )
                | (
                    (ExternalLink.http_status_code.is_(None))
                    & (ExternalLink.ip_address.isnot(None))
                    & (ExternalLink.ip_address != "")
                ),
            )
            .count()
        )
        total_count = session.query(ExternalLink).filter(ExternalLink.job_id == job_id).count()

        healthy_count = total_count - dead_count - broken_count - blocked_count

        stats = JobStats(
            total=total_count,
            healthy=healthy_count,
            broken=broken_count,
            dead=dead_count,
            blocked=blocked_count,
        )
        _build_and_send_email(to_email, job, status, stats)
