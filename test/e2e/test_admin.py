"""
E2E 測試：管理員後台操作與設定修改流程。
"""

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
    expect(page).to_have_url(re.compile(r".*/app\.html.*"))

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
    page.wait_for_selector("#confirm-modal-submit", state="visible")
    page.click("#confirm-modal-submit")

    # 驗證是否有成功提示，例如 toast 訊息
    # class 為 toast-container 的內部
    expect(page.locator(".toast-container").last).to_contain_text(re.compile("成功|儲存|已"))
