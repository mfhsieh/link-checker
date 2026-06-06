"""
SMTP 郵件發送工具模組。

使用 Python 標準函式庫 smtplib 發送郵件，不引入第三方郵件服務 SDK。
SMTP 設定從環境變數讀取（透過 backend.config.Settings），不存入資料庫。
支援 STARTTLS 與 SSL/TLS 連線，禁止使用明文 SMTP。
開發環境可啟用 SMTP_CONSOLE_MODE，改為輸出至 console 而非實際寄送。
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote_plus

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _build_invitation_email(
    to_email: str,
    invitation_token: str,
    expires_hours: int,
) -> EmailMessage:
    """
    組建邀請郵件的 EmailMessage 物件。

    郵件為純文字 + 最小化 HTML，不嵌入任何外連資源或追蹤像素。

    Args:
        to_email (str): 收件者電子郵件地址。
        invitation_token (str): 邀請 UUID。
        expires_hours (int): 連結有效時數。

    Returns:
        EmailMessage: 組建完成的郵件物件。
    """
    settings = get_settings()
    login_url = (
        f"{settings.BASE_URL}/?email={quote_plus(to_email)}&token={invitation_token}"
    )

    plain_text = (
        f"您好，\n\n"
        f"您已被邀請使用「{settings.APP_NAME}」系統。\n\n"
        f"請點擊以下連結完成首次登入並設定您的密碼：\n"
        f"{login_url}\n\n"
        f"此連結有效期為 {expires_hours} 小時，逾期後將失效。\n"
        f"若您未曾申請此邀請，請忽略此封郵件。\n\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="color:#1a1a2e">{settings.APP_NAME} 系統邀請</h2>
  <p>您好，</p>
  <p>您已被邀請使用「<strong>{settings.APP_NAME}</strong>」系統。</p>
  <p>請點擊下方按鈕完成首次登入並設定您的密碼：</p>
  <p style="margin:24px 0">
    <a href="{login_url}"
       style="background:#2563eb;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold">
      立即登入並設定密碼
    </a>
  </p>
  <p style="color:#666;font-size:0.875rem">
    此連結有效期為 <strong>{expires_hours} 小時</strong>，逾期後將失效。<br>
    若無法點擊按鈕，請複製以下連結至瀏覽器：<br>
    <code style="word-break:break-all">{login_url}</code>
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:0.75rem">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

    msg = EmailMessage()
    msg["Subject"] = f"【{settings.APP_NAME}】系統邀請通知"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(plain_text)
    msg.add_alternative(html_body, subtype="html")

    return msg


def send_invitation_email(to_email: str, invitation_token: str) -> bool:
    """
    發送邀請郵件給指定的使用者。

    Args:
        to_email (str): 收件者電子郵件地址。
        invitation_token (str): 邀請 UUID。

    Returns:
        bool: 發送成功回傳 True，失敗回傳 False。
    """
    settings = get_settings()
    expires_hours = settings.INVITATION_EXPIRE_SECONDS // 3600
    msg = _build_invitation_email(to_email, invitation_token, expires_hours)

    # 開發模式：僅輸出至 console，不實際發送
    if settings.SMTP_CONSOLE_MODE:
        logger.info(
            "[SMTP Console Mode] 邀請郵件（未實際寄送）:\n"
            "  收件者: %s\n  Subject: %s\n  登入連結: %s/?email=%s&token=%s",
            to_email,
            msg["Subject"],
            settings.BASE_URL,
            quote_plus(to_email),
            invitation_token,
        )
        return True

    try:
        context = ssl.create_default_context()
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as smtp:
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)

        logger.info("邀請郵件已成功寄送至 %s", to_email)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("寄送邀請郵件至 %s 時發生錯誤: %s", to_email, e)
        return False


def send_test_email(to_email: str) -> bool:
    """
    寄送 SMTP 測試郵件以驗證設定是否正確。

    Args:
        to_email (str): 測試郵件的收件者地址。

    Returns:
        bool: 寄送成功回傳 True，失敗回傳 False。
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["Subject"] = f"【{settings.APP_NAME}】SMTP 設定測試郵件"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(
        f"這是一封由「{settings.APP_NAME}」系統發送的 SMTP 測試郵件。\n"
        f"若您收到此郵件，代表 SMTP 設定已正確運作。"
    )

    if settings.SMTP_CONSOLE_MODE:
        logger.info("[SMTP Console Mode] 測試郵件（未實際寄送）收件者: %s", to_email)
        return True

    try:
        context = ssl.create_default_context()
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as smtp:
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)

        logger.info("SMTP 測試郵件已成功寄送至 %s", to_email)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("SMTP 測試郵件寄送失敗: %s", e)
        return False


def send_notification_email(
    to_email: str,
    subject: str,
    plain_text: str,
    html_body: str | None = None,
) -> bool:
    """
    發送一般通知郵件至指定的電子郵件地址。

    Args:
        to_email (str): 收件者電子郵件地址。
        subject (str): 郵件主旨。
        plain_text (str): 郵件純文字內容。
        html_body (str | None): 郵件 HTML 格式內容，若無則只發送純文字。

    Returns:
        bool: 發送成功回傳 True，失敗回傳 False。
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(plain_text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    if settings.SMTP_CONSOLE_MODE:
        logger.info(
            "[SMTP Console Mode] 通知郵件（未實際寄送）:\n"
            "  收件者: %s\n  Subject: %s\n  內文:\n%s",
            to_email,
            subject,
            plain_text,
        )
        return True

    try:
        context = ssl.create_default_context()
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as smtp:
                if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                    smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.send_message(msg)

        logger.info("通知郵件已成功寄送至 %s", to_email)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("寄送通知郵件至 %s 時發生錯誤: %s", to_email, e)
        return False

