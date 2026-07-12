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

from backend.config import get_settings

logger: logging.Logger = logging.getLogger(__name__)


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
    login_url = f"{settings.BASE_URL}/?action=invite"

    plain_text = (
        f"您好，\n\n"
        f"您已被邀請使用「{settings.APP_NAME}」。\n\n"
        f"請前往以下網址，並輸入您的電子郵件及邀請碼以完成首次登入與密碼設定：\n"
        f"系統網址：{login_url}\n"
        f"邀請碼：{invitation_token}\n\n"
        f"此邀請碼有效期為 {expires_hours} 小時，逾期後將失效。\n"
        f"若您未曾申請此邀請，請忽略此封郵件。\n\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    # pylint: disable=duplicate-code
    html_body = f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="color:#1a1a2e">{settings.APP_NAME} 邀請</h2>
  <p>您好，</p>
  <p>您已被邀請使用「<strong>{settings.APP_NAME}</strong>」。</p>
  <p>請前往下方網址，並輸入您的電子郵件及專屬邀請碼以完成首次登入與密碼設定：</p>
  <div style="background:#f4f4f5;padding:16px;border-radius:8px;margin:24px 0;">
    <p style="margin:0 0 8px 0;font-size:0.875rem;color:#666;">系統網址</p>
    <p style="margin:0 0 16px 0;font-size:1.25rem;font-weight:bold;color:#1a1a2e;">
      <a href="{login_url}" style="color:#2563eb;text-decoration:none;">{login_url}</a>
    </p>
    <p style="margin:0 0 8px 0;font-size:0.875rem;color:#666;">邀請碼</p>
    <p style="margin:0;font-size:1.25rem;font-weight:bold;letter-spacing:1px;color:#1a1a2e;">
      {invitation_token}
    </p>
  </div>
  <p style="color:#666;font-size:0.875rem">
    此邀請碼有效期為 <strong>{expires_hours} 小時</strong>，逾期後將失效。
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:0.75rem">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

    msg = EmailMessage()
    msg["Subject"] = f"【{settings.APP_NAME}】邀請通知"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(plain_text)
    msg.add_alternative(html_body, subtype="html")

    return msg


def _build_password_reset_email(
    to_email: str,
    reset_token: str,
) -> EmailMessage:
    """
    組建重設密碼郵件的 EmailMessage 物件。

    Args:
        to_email (str): 收件者電子郵件地址。
        reset_token (str): 密碼重設的 Token。

    Returns:
        EmailMessage: 組建完成的郵件物件。
    """
    settings = get_settings()
    reset_url = f"{settings.BASE_URL}/reset-password.html?token={reset_token}"

    plain_text = (
        f"您好，\n\n"
        f"我們收到了您要求重設「{settings.APP_NAME}」密碼的申請。\n\n"
        f"請點擊以下網址重設您的密碼（該連結 1 小時內有效）：\n"
        f"{reset_url}\n\n"
        f"若您並未申請重設密碼，請忽略此郵件。\n\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="color:#1a1a2e">{settings.APP_NAME} 密碼重設</h2>
  <p>您好，</p>
  <p>我們收到了您要求重設密碼的申請。請點擊下方按鈕或連結來設定新密碼：</p>
  <div style="margin:24px 0;">
    <a href="{reset_url}"
       style="background:#2563eb;color:#ffffff;padding:12px 24px;text-decoration:none;
              border-radius:6px;font-weight:bold;display:inline-block;">重設密碼</a>
  </div>
  <p style="margin:0 0 16px 0;font-size:0.875rem;color:#666;">
    或複製以下網址至瀏覽器貼上：<br>
    <a href="{reset_url}" style="color:#2563eb;text-decoration:none;word-break:break-all;">{reset_url}</a>
  </p>
  <p style="color:#666;font-size:0.875rem">
    此連結有效期為 <strong>1 小時</strong>，逾期後將失效。若您並未申請重設密碼，請忽略此封郵件。
  </p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="color:#999;font-size:0.75rem">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>"""

    msg = EmailMessage()
    msg["Subject"] = f"【{settings.APP_NAME}】密碼重設通知"
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(plain_text)
    msg.add_alternative(html_body, subtype="html")

    return msg


def _send_email(msg: EmailMessage) -> None:
    """
    執行實際的 SMTP 發送邏輯。

    Args:
        msg (EmailMessage): 欲寄送的郵件物件。
    """
    settings = get_settings()
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
        login_url = f"{settings.BASE_URL}/?action=invite"
        logger.info(
            "[SMTP Console Mode] 邀請郵件（未實際寄送）:\n  收件者: %s\n  Subject: %s\n  登入連結: %s\n  邀請碼: %s",
            to_email,
            msg["Subject"],
            login_url,
            invitation_token,
        )
        return True

    try:
        _send_email(msg)

        logger.info("邀請郵件已成功寄送至 %s", to_email)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.critical("[NOTIFICATION_FAILURE] 寄送邀請郵件至 %s 時發生錯誤: %s", to_email, e, exc_info=True)
        return False


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """
    發送重設密碼郵件。

    Args:
        to_email (str): 收件者電子郵件地址。
        reset_token (str): 密碼重設的 Token。

    Returns:
        bool: 寄送成功回傳 True，失敗回傳 False。
    """
    settings = get_settings()
    msg = _build_password_reset_email(to_email, reset_token)

    if settings.SMTP_CONSOLE_MODE:
        reset_url = f"{settings.BASE_URL}/reset-password.html?token={reset_token}"
        logger.info(
            "[SMTP Console Mode] 重設密碼郵件（未實際寄送）:\n  收件者: %s\n  Subject: %s\n  重設連結: %s",
            to_email,
            msg["Subject"],
            reset_url,
        )
        return True

    try:
        _send_email(msg)
        logger.info("重設密碼郵件已成功寄送至 %s", to_email)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.critical("[NOTIFICATION_FAILURE] 寄送重設密碼郵件至 %s 時發生錯誤: %s", to_email, e, exc_info=True)
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
        f"這是一封由「{settings.APP_NAME}」發送的 SMTP 測試郵件。\n若您收到此郵件，代表 SMTP 設定已正確運作。"
    )

    if settings.SMTP_CONSOLE_MODE:
        logger.info("[SMTP Console Mode] 測試郵件（未實際寄送）收件者: %s", to_email)
        return True

    try:
        _send_email(msg)

        logger.info("SMTP 測試郵件已成功寄送至 %s", to_email)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.critical("[NOTIFICATION_FAILURE] SMTP 測試郵件寄送失敗: %s", e, exc_info=True)
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
            "[SMTP Console Mode] 通知郵件（未實際寄送）:\n  收件者: %s\n  Subject: %s\n  內文:\n%s",
            to_email,
            subject,
            plain_text,
        )
        return True

    try:
        _send_email(msg)

        logger.info("通知郵件已成功寄送至 %s", to_email)
        return True
    except (smtplib.SMTPException, OSError) as e:
        logger.critical("[NOTIFICATION_FAILURE] 寄送通知郵件至 %s 時發生錯誤: %s", to_email, e, exc_info=True)
        return False
