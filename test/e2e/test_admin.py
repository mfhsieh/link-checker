"""E2E 測試：管理員後台操作與設定修改流程。"""

import re

from playwright.sync_api import Page, expect


def test_admin_config(page: Page, base_url: str) -> None:
    """
    測試管理員登入後修改全域設定。

    Args:
        page (Page): Playwright 的網頁操作物件。
        base_url (str): 測試伺服器的根網址。
    """
    page.goto(f"{base_url}/index.html")
    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "Admin@12345678")
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r".*/(app|help)\.html.*"), timeout=10000)

    # 導航至管理後台
    page.goto(f"{base_url}/admin.html")

    # 點擊左側導覽列的設定選項
    page.click("#nav-config")

    # 修改設定 (例如 timeout)
    # 這裡的 id 為 cfg-timeout
    # 等待載入完成，原本可能是載入中的值
    page.wait_for_selector("#cfg-timeout", state="visible")

    # 確保資料載入完畢（不要太快按儲存導致失敗）
    page.wait_for_function('document.getElementById("cfg-timeout").value !== ""')

    # 原本的預設值可能是 30，將它改為 60
    page.fill("#cfg-timeout", "60")

    # 點擊儲存配置
    page.click("#save-config-btn")

    # 點擊 Modal 中的確認按鈕
    page.wait_for_selector("#submit-btn", state="visible")
    page.click("#submit-btn")

    # 驗證是否有成功提示，例如 toast 訊息
    # class 為 toast-container 的內部
    expect(page.locator(".toast").last).to_contain_text(re.compile("成功|儲存|已"))


# pylint: disable=too-many-statements
def test_admin_user_management_ui(page: Page, base_url: str) -> None:
    """
    測試管理員在後台管理使用者的 UI 互動，包含邀請、重寄邀請、停用/啟用、權限提降、刪除。

    Args:
        page (Page): Playwright 的網頁操作物件。
        base_url (str): 測試伺服器的根網址。

    Raises:
        AssertionError: 當操作結果與預期不合或 API 發生錯誤時拋出。
    """
    # 1. 登入並進入管理後台
    page.goto(f"{base_url}/index.html")
    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "Admin@12345678")
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r".*/(app|help)\.html.*"), timeout=10000)

    page.goto(f"{base_url}/admin.html")
    page.wait_for_selector("#users-table-container")

    # 2. 邀請新使用者
    page.wait_for_selector("#invite-user-btn", state="visible")
    page.click("#invite-user-btn")
    page.wait_for_selector("#invite-email", state="visible")
    page.fill("#invite-email", "invited_user@test.com")

    with page.expect_response("**/api/admin/users", timeout=5000) as response_info:
        page.click("#invite-user-submit")

    response = response_info.value
    assert response.ok, f"User invitation failed: {response.status}"
    expect(page.locator(".toast").last).to_contain_text(re.compile("邀請已寄送|成功"))

    # 確保列表已重新載入並出現新使用者
    expect(page.locator('tr:has-text("invited_user@test.com")')).to_be_visible()

    # 3. 重新寄送邀請
    page.click('tr:has-text("invited_user@test.com") button[data-action="resend"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response("**/resend-invite"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("重新寄送|成功"))

    # 4. 變更使用者角色：設為管理員 ➔ 取消管理員
    # 設為管理員 (Promote)
    page.click('tr:has-text("invited_user@test.com") button[data-action="promote"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response(lambda r: "/api/admin/users/" in r.url and r.request.method == "PATCH"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("角色已變更|成功"))
    expect(page.locator('tr:has-text("invited_user@test.com")')).to_contain_text("管理員")

    # 取消管理員 (Demote)
    page.click('tr:has-text("invited_user@test.com") button[data-action="demote"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response(lambda r: "/api/admin/users/" in r.url and r.request.method == "PATCH"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("角色已變更|成功"))
    expect(page.locator('tr:has-text("invited_user@test.com")')).to_contain_text("使用者")

    # 5. 帳號停用與啟用
    # 停用 (Suspend)
    page.click('tr:has-text("invited_user@test.com") button[data-action="suspend"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response(lambda r: "/api/admin/users/" in r.url and r.request.method == "PATCH"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("已停用|成功"))
    expect(page.locator('tr:has-text("invited_user@test.com")')).to_contain_text("已停用")

    # 啟用 (Activate)
    page.click('tr:has-text("invited_user@test.com") button[data-action="activate"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response(lambda r: "/api/admin/users/" in r.url and r.request.method == "PATCH"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("啟用|成功"))
    expect(page.locator('tr:has-text("invited_user@test.com")')).to_contain_text("正常")

    # 6. 刪除使用者 (Delete)
    page.click('tr:has-text("invited_user@test.com") button[data-action="delete"]')
    page.wait_for_selector("#submit-btn", state="visible")

    with page.expect_response(lambda r: "/api/admin/users/" in r.url and r.request.method == "DELETE"):
        page.click("#submit-btn")

    expect(page.locator(".toast").last).to_contain_text(re.compile("已進入刪除排程|成功"))
    expect(page.locator("#users-table-container")).not_to_contain_text("invited_user@test.com")
