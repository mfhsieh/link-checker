"""
負責傳送任務狀態通知信件的服務模組。

提供查詢使用者信箱、組裝 Email 內容以及發送任務完成通知的相關功能。
"""

import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import count as sql_count
from sqlalchemy.sql.functions import sum as sql_sum

from backend.auth.db import get_auth_session_local
from backend.auth.models import User
from backend.config import get_settings
from backend.email_sender import send_notification_email
from backend.events import subscribe
from crawler.models import CrawlQueue, ExternalLink, Job

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class JobStats:
    # pylint: disable=too-many-instance-attributes
    """任務統計資訊。"""

    queue_total: int
    queue_completed: int
    queue_warning: int
    queue_skipped: int
    queue_failed: int
    queue_pending: int

    int_total: int
    int_server_error: int
    int_connection_error: int
    int_timeout: int
    int_not_found: int
    int_other_error: int
    int_warning: int
    int_blocked: int

    ext_total: int
    ext_healthy: int
    ext_dns_failed: int
    ext_not_found: int
    ext_server_error: int
    ext_connection_error: int
    ext_other_error: int
    ext_blocked: int
    ext_insecure: int


def _get_user_email(user_id: str) -> str | None:
    """
    查詢指定使用者的 Email 位址。

    Args:
        user_id (str): 使用者的 UUID 字串。

    Returns:
        str | None: 若找到該使用者則回傳 Email 字串，否則回傳 None。
    """
    try:
        session_factory = get_auth_session_local()
        with session_factory() as auth_session:
            user = auth_session.query(User).filter(User.id == user_id).first()
            if user:
                return str(user.email)
            return None
    except Exception as ex:  # pylint: disable=broad-exception-caught
        logger.error(
            "[Email Notification] 自 Auth DB 查詢使用者 %s 的信箱時發生錯誤: %s",
            user_id,
            ex,
        )
        return None


def _build_and_send_email(to_email: str, job: Job, status: str, stats: JobStats) -> None:
    """
    組裝並寄送任務狀態通知信。

    根據任務的統計數據 (JobStats) 動態生成 HTML 與純文字格式的信件內容，
    並透過設定好的郵件發送服務將信件寄給目標使用者。

    Args:
        to_email (str): 收件者的 Email 位址。
        job (Job): 對應的爬蟲任務實例。
        status (str): 任務的最終狀態，例如 'completed' 或 'error'。
        stats (JobStats): 任務的各項統計數據。
    """
    status_text = "已完成 (Completed)" if status == "completed" else "發生嚴重異常 (Error)"
    subject = f"【網站連結檢查系統】任務狀態通知 ({status_text}) - 任務 ID: {job.id}"

    settings = get_settings()
    job_url = f"{settings.BASE_URL.rstrip('/')}/app.html#/jobs/{job.id}"

    def c(val: int, active_color: str, always: bool = False) -> str:
        """動態上色：大於 0 或 always 為 True 時使用 active_color，否則使用低調灰 (#9ca3af)"""
        return active_color if always or val > 0 else "#9ca3af"

    plain_text = (
        f"您好，\n\n"
        f"您所建立的網站連結檢查任務已執行結束。\n\n"
        f"【任務資訊】\n"
        f"  - 任務 ID：{job.id}\n"
        f"  - 起始網址：{job.start_url}\n"
        f"  - 任務狀態：{status_text}\n"
        f"  - 建立時間：{job.created_at}\n"
        f"  - 結束時間：{job.updated_at}\n\n"
        f"【爬取進度】\n"
        f"  - 總計：{stats.queue_total}\n"
        f"  - 完成：{stats.queue_completed}\n"
        f"  - 截斷：{stats.queue_warning}\n"
        f"  - 略過：{stats.queue_skipped}\n"
        f"  - 失敗：{stats.queue_failed}\n"
        f"  - 等待：{stats.queue_pending}\n\n"
        f"【內部連結診斷】\n"
        f"  - 診斷總數：{stats.int_total}\n"
        f"  - 伺服器異常：{stats.int_server_error}\n"
        f"  - 底層異常：{stats.int_connection_error}\n"
        f"  - 連線逾時：{stats.int_timeout}\n"
        f"  - 資源遺失：{stats.int_not_found}\n"
        f"  - 其他異常：{stats.int_other_error}\n"
        f"  - 網頁截斷：{stats.int_warning}\n"
        f"  - 權限阻擋：{stats.int_blocked}\n\n"
        f"【外部連結診斷】\n"
        f"  - 診斷總數：{stats.ext_total}\n"
        f"  - 正常連結：{stats.ext_healthy}\n"
        f"  - DNS 錯誤：{stats.ext_dns_failed}\n"
        f"  - 資源遺失：{stats.ext_not_found}\n"
        f"  - 伺服器異常：{stats.ext_server_error}\n"
        f"  - 底層異常：{stats.ext_connection_error}\n"
        f"  - 其他異常：{stats.ext_other_error}\n"
        f"  - 權限阻擋：{stats.ext_blocked}\n"
        f"  - 非 HTTPS：{stats.ext_insecure}\n\n"
        f"詳細檢查結果，請登入系統後台查看。\n\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    # pylint: disable=duplicate-code
    html_body = f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#333;line-height:1.6;">
  <h2 style="color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:12px;">網站連結檢查任務通知</h2>
  <p>您好，您所建立的檢查任務已執行結束。</p>

  <div style="background-color:#f8f9fa;padding:16px;border-radius:8px;margin-bottom:24px;">
    <h3 style="margin-top:0;color:#1a1a2e;font-size:16px;">任務資訊</h3>
    <ul style="margin:0;padding-left:20px;font-size:14px;">
      <li><strong>任務 ID：</strong>{job.id}</li>
      <li><strong>起始網址：</strong>{job.start_url}</li>
      <li><strong>狀態：</strong>{status_text}</li>
    </ul>
  </div>

  <div style="margin-bottom:24px;">
    <h3 style="background-color:#1a1a2e;color:white;padding:10px 12px;margin:0;border-top-left-radius:6px;border-top-right-radius:6px;font-size:15px;">爬取進度</h3>
    <div style="border:1px solid #eee;border-top:none;padding:16px;border-bottom-left-radius:6px;border-bottom-right-radius:6px;font-size:14px;">
      <ul style="margin:0;padding:0;list-style:none;line-height:1.8;">
        <li><strong>總計：</strong>{stats.queue_total}</li>
        <li><span style="color:{c(stats.queue_completed, "#16a34a", True)}">完成：{stats.queue_completed}</span></li>
        <li><span style="color:{c(stats.queue_warning, "#d97706")}">截斷：{stats.queue_warning}</span></li>
        <li><span style="color:{c(stats.queue_skipped, "#6b7280")}">略過：{stats.queue_skipped}</span></li>
        <li><span style="color:{c(stats.queue_failed, "#dc2626")}">失敗：{stats.queue_failed}</span></li>
        <li><span style="color:{c(stats.queue_pending, "#6b7280")}">等待：{stats.queue_pending}</span></li>
      </ul>
    </div>
  </div>

  <div style="margin-bottom:24px;">
    <h3 style="background-color:#1a1a2e;color:white;padding:10px 12px;margin:0;border-top-left-radius:6px;border-top-right-radius:6px;font-size:15px;">內部連結診斷</h3>
    <div style="border:1px solid #eee;border-top:none;padding:16px;border-bottom-left-radius:6px;border-bottom-right-radius:6px;font-size:14px;">
      <ul style="margin:0;padding:0;list-style:none;line-height:1.8;">
        <li><strong>診斷總數：</strong>{stats.int_total}</li>
        <li><span style="color:{c(stats.int_server_error, "#dc2626")}">伺服器異常：{stats.int_server_error}</span></li>
        <li><span style="color:{c(stats.int_connection_error, "#2563eb")}">底層異常：{stats.int_connection_error}</span></li>
        <li><span style="color:{c(stats.int_timeout, "#2563eb")}">連線逾時：{stats.int_timeout}</span></li>
        <li><span style="color:{c(stats.int_not_found, "#d97706")}">資源遺失：{stats.int_not_found}</span></li>
        <li><span style="color:{c(stats.int_other_error, "#6b7280")}">其他異常：{stats.int_other_error}</span></li>
        <li><span style="color:{c(stats.int_warning, "#d97706")}">網頁截斷：{stats.int_warning}</span></li>
        <li><span style="color:{c(stats.int_blocked, "#6b7280")}">權限阻擋：{stats.int_blocked}</span></li>
      </ul>
    </div>
  </div>

  <div style="margin-bottom:24px;">
    <h3 style="background-color:#1a1a2e;color:white;padding:10px 12px;margin:0;border-top-left-radius:6px;border-top-right-radius:6px;font-size:15px;">外部連結診斷</h3>
    <div style="border:1px solid #eee;border-top:none;padding:16px;border-bottom-left-radius:6px;border-bottom-right-radius:6px;font-size:14px;">
      <ul style="margin:0;padding:0;list-style:none;line-height:1.8;">
        <li><strong>診斷總數：</strong>{stats.ext_total}</li>
        <li><span style="color:{c(stats.ext_healthy, "#16a34a", True)}">正常連結：{stats.ext_healthy}</span></li>
        <li><span style="color:{c(stats.ext_dns_failed, "#dc2626")}">DNS 錯誤：{stats.ext_dns_failed}</span></li>
        <li><span style="color:{c(stats.ext_not_found, "#d97706")}">資源遺失：{stats.ext_not_found}</span></li>
        <li><span style="color:{c(stats.ext_server_error, "#dc2626")}">伺服器異常：{stats.ext_server_error}</span></li>
        <li><span style="color:{c(stats.ext_connection_error, "#2563eb")}">底層異常：{stats.ext_connection_error}</span></li>
        <li><span style="color:{c(stats.ext_other_error, "#6b7280")}">其他異常：{stats.ext_other_error}</span></li>
        <li><span style="color:{c(stats.ext_blocked, "#6b7280")}">權限阻擋：{stats.ext_blocked}</span></li>
        <li><span style="color:{c(stats.ext_insecure, "#d97706")}">非 HTTPS：{stats.ext_insecure}</span></li>
      </ul>
    </div>
  </div>

  <p style="text-align:center;margin-top:32px;">
    <a href="{job_url}" style="background-color:#1a1a2e;color:white;padding:12px 24px;text-decoration:none;
        border-radius:6px;font-weight:bold;display:inline-block;">前往系統檢視詳細報表</a>
  </p>

  <p style="color:#999;font-size:12px;margin-top:48px;border-top:1px solid #eee;padding-top:12px;">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

    try:
        send_notification_email(to_email, subject, plain_text, html_body)
    except smtplib.SMTPException as ex:
        logger.error("[Email Notification] 寄送任務通知信失敗: %s", ex)


def send_job_status_notification(session_factory: Callable[[], Session], job_id: str, status: str) -> None:
    """
    在任務完成或發生錯誤時，向任務建立者發送 Email 通知，並附帶結果統計。

    根據給定的任務 ID 查詢關聯的使用者，並進行資料庫的聚合運算，
    統計內部與外部連結的各項診斷數據，最後呼叫內部方法寄送信件。

    Args:
        session_factory (Callable[[], Session]): Crawler 資料庫的 Session 工廠。
        job_id (str): 目標爬蟲任務的 ID。
        status (str): 任務結束的狀態（例如 'completed' 或 'error'）。
    """
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

        # 1. 爬取進度統計 (CrawlQueue)
        q_row = (
            session.query(
                sql_count(CrawlQueue.id).label("total"),
                sql_sum(case((CrawlQueue.status_category == "completed", 1), else_=0)).label("completed"),
                sql_sum(case((CrawlQueue.status_category == "warning", 1), else_=0)).label("warning"),
                sql_sum(case((CrawlQueue.status_category == "skipped", 1), else_=0)).label("skipped"),
                sql_sum(case((CrawlQueue.status_category == "failed", 1), else_=0)).label("failed"),
                sql_sum(case((CrawlQueue.status_category == "pending", 1), else_=0)).label("pending"),
                sql_sum(case((CrawlQueue.status_category == "server_error", 1), else_=0)).label("server_error"),
                sql_sum(case((CrawlQueue.status_category == "connection_error", 1), else_=0)).label("connection_error"),
                sql_sum(case((CrawlQueue.status_category == "timeout", 1), else_=0)).label("timeout"),
                sql_sum(case((CrawlQueue.status_category == "not_found", 1), else_=0)).label("not_found"),
                sql_sum(case((CrawlQueue.status_category == "other_error", 1), else_=0)).label("other_error"),
                sql_sum(case((CrawlQueue.status_category == "blocked", 1), else_=0)).label("blocked"),
            )
            .filter(CrawlQueue.job_id == job_id)
            .one()
        )

        q_failed = int(q_row.failed or 0)
        q_warning = int(q_row.warning or 0)

        # 2. 外部連結診斷統計 (ExternalLink)
        ext_row = (
            session.query(
                sql_count(ExternalLink.id).label("total"),
                sql_sum(case((ExternalLink.status_category == "healthy", 1), else_=0)).label("healthy"),
                sql_sum(case((ExternalLink.status_category == "dns_failed", 1), else_=0)).label("dns_failed"),
                sql_sum(case((ExternalLink.status_category == "not_found", 1), else_=0)).label("not_found"),
                sql_sum(case((ExternalLink.status_category == "server_error", 1), else_=0)).label("server_error"),
                sql_sum(case((ExternalLink.status_category == "connection_error", 1), else_=0)).label(
                    "connection_error"
                ),
                sql_sum(case((ExternalLink.status_category == "other_error", 1), else_=0)).label("other_error"),
                sql_sum(case((ExternalLink.status_category == "blocked", 1), else_=0)).label("blocked"),
                sql_sum(case((ExternalLink.status_category == "insecure", 1), else_=0)).label("insecure"),
            )
            .filter(ExternalLink.job_id == job_id)
            .one()
        )

        stats = JobStats(
            queue_total=int(q_row.total or 0),
            queue_completed=int(q_row.completed or 0),
            queue_warning=q_warning,
            queue_skipped=int(q_row.skipped or 0),
            queue_failed=q_failed,
            queue_pending=int(q_row.pending or 0),
            int_total=q_failed + q_warning,
            int_server_error=int(q_row.server_error or 0),
            int_connection_error=int(q_row.connection_error or 0),
            int_timeout=int(q_row.timeout or 0),
            int_not_found=int(q_row.not_found or 0),
            int_other_error=int(q_row.other_error or 0),
            int_warning=q_warning,
            int_blocked=int(q_row.blocked or 0),
            ext_total=int(ext_row.total or 0),
            ext_healthy=int(ext_row.healthy or 0),
            ext_dns_failed=int(ext_row.dns_failed or 0),
            ext_not_found=int(ext_row.not_found or 0),
            ext_server_error=int(ext_row.server_error or 0),
            ext_connection_error=int(ext_row.connection_error or 0),
            ext_other_error=int(ext_row.other_error or 0),
            ext_blocked=int(ext_row.blocked or 0),
            ext_insecure=int(ext_row.insecure or 0),
        )

        _build_and_send_email(to_email, job, status, stats)


def subscribe_to_events(session_factory: Callable[[], Session]) -> None:
    """
    註冊事件監聽，當任務狀態變更為 completed 或 error 時發送 Email 通知。

    Args:
        session_factory (Callable[[], Session]): Crawler 資料庫的 Session 工廠。
    """

    def _handle_job_status_changed(job_id: str, status: str, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        if status in ("completed", "error"):
            send_job_status_notification(session_factory, job_id, status)

    subscribe("job_status_changed", _handle_job_status_changed)
    logger.info("[Email Notification] 已成功註冊 job_status_changed 事件監聽。")
