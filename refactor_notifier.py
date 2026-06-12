import sys

with open("crawler/notifier.py", "r") as f:
    content = f.read()

# 1. Remove pylint disable
content = content.replace("    # pylint: disable=too-many-locals\n", "")

# 2. Add _get_user_email and _build_and_send_email before send_job_status_notification
helper_methods = """
def _get_user_email(user_id: str) -> str | None:
    \"\"\"取得使用者的 Email。\"\"\"
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
    total_count: int,
    healthy_count: int,
    broken_count: int,
    dead_count: int,
) -> None:
    \"\"\"組裝並寄送通知信。\"\"\"
    status_text = "已完成 (Completed)" if status == "completed" else "發生嚴重異常 (Error)"
    subject = f"【外部連結檢查系統】任務狀態通知 ({status_text}) - 任務 ID: {job.id}"

    plain_text = (
        f"您好，\\n\\n"
        f"您所建立的外部連結檢查任務已執行結束。\\n\\n"
        f"任務資訊：\\n"
        f"  - 任務 ID：{job.id}\\n"
        f"  - 起始網址：{job.start_url}\\n"
        f"  - 任務狀態：{status_text}\\n"
        f"  - 建立時間：{job.created_at}\\n"
        f"  - 結束時間：{job.updated_at}\\n\\n"
        f"外部連結檢查統計：\\n"
        f"  - 總共發現外部連結數：{total_count}\\n"
        f"  - 正常連結 (Healthy)：{healthy_count} 個\\n"
        f"  - 損壞連結 (Broken Links，HTTP/連線異常)：{broken_count} 個\\n"
        f"  - 失效連結 (Dead Links，DNS 解析失敗)：{dead_count} 個\\n\\n"
        f"詳細檢查結果，請登入系統後台查看。\\n\\n"
        f"此為系統自動發送的郵件，請勿回覆。"
    )

    html_body = \"\"\"\\
<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px;color:#333;">
  <h2 style="color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:12px;">外部連結檢查任務通知</h2>
  <p>您好，</p>
  <p>您所建立的外部連結檢查任務已執行結束。詳細統計數據請登入系統查看。</p>
  <p style="color:#999;font-size:0.75rem;">此為系統自動發送的郵件，請勿回覆。</p>
</body>
</html>\"\"\"

    try:
        send_notification_email(to_email, subject, plain_text, html_body)
    except smtplib.SMTPException as ex:
        logger.error("[Email Notification] 寄送任務通知信失敗: %s", ex)

"""

content = content.replace("def send_job_status_notification(", helper_methods + "def send_job_status_notification(")

# 3. Replace the body of send_job_status_notification

import re

# replace user email fetching block
auth_block = re.compile(r"        # 取得使用者的 Email\n        try:\n            auth_session_factory = get_auth_session_local\(\)\n            with auth_session_factory\(\) as auth_session:\n                user = auth_session\.query\(User\)\.filter\(User\.id == user_id\)\.first\(\)\n                if not user or not user\.email:\n                    logger\.warning\(\n                        \"\[Email Notification\] 找不到使用者 ID %s 或其無信箱設定，跳過通知信發送。\",\n                        user_id,\n                    \)\n                    return\n                to_email = user\.email\n        except sqlalchemy\.exc\.SQLAlchemyError as ex:\n            logger\.error\(\n                \"\[Email Notification\] 自 Auth DB 查詢使用者 %s 的信箱時發生錯誤: %s\",\n                user_id,\n                ex,\n            \)\n            return")

new_auth_block = """        to_email = _get_user_email(user_id)
        if not to_email:
            logger.warning(
                "[Email Notification] 找不到使用者 ID %s 或其無信箱設定，跳過通知信發送。",
                user_id,
            )
            return"""

content = auth_block.sub(new_auth_block, content)


# replace the email sending block
email_block = re.compile(r"        status_text = \"已完成 \(Completed\)\" if status == \"completed\" else \"發生嚴重異常 \(Error\)\".*?        except smtplib\.SMTPException as ex:\n            logger\.error\(\"\[Email Notification\] 寄送任務通知信失敗: %s\", ex\)\n", re.DOTALL)

new_email_block = """        _build_and_send_email(
            to_email, job, status, total_count, healthy_count, broken_count, dead_count
        )\n"""

content = email_block.sub(new_email_block, content)


with open("crawler/notifier.py", "w") as f:
    f.write(content)
