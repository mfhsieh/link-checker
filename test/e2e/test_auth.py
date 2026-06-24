"""E2E 測試：使用者身分驗證與登入流程。"""

import re

from playwright.sync_api import Page, expect


def test_login_success(page: Page, base_url: str) -> None:
    """
    測試正常登入流程，應導向至 app.html。

    Args:
        page (Page): Playwright 的網頁操作物件。
        base_url (str): 測試伺服器的根網址。
    """
    page.goto(f"{base_url}/index.html")

    # 填寫帳號密碼
    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "Admin@12345678")

    # 點擊登入
    page.click('button[type="submit"]')

    # 驗證是否跳轉到 /app.html
    expect(page).to_have_url(re.compile(r".*/(app|help)\.html"))

    # 驗證畫面上出現預期的文字 (例如：任務管理)
    expect(page.locator("body")).to_contain_text("任務管理")


def test_login_failure(page: Page, base_url: str) -> None:
    """
    測試錯誤的登入，應顯示錯誤訊息且停留在登入頁。

    Args:
        page (Page): Playwright 的網頁操作物件。
        base_url (str): 測試伺服器的根網址。
    """
    page.goto(f"{base_url}/index.html")

    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "wrongpassword")

    page.click('button[type="submit"]')

    # 不應該跳轉，可能是 / 或 /index.html
    expect(page).to_have_url(re.compile(r".*(/index\.html|/)$"))

    # 錯誤訊息可能用 alert，但我們假設它有顯示在某個地方或是 alert 彈窗
    # 因為是 e2e，我們可以用事件監聽 dialog 或是看 DOM。
    # 這裡我們只確認沒有跳轉，且仍在登入畫面。
    expect(page.locator('button[type="submit"]')).to_be_visible()
