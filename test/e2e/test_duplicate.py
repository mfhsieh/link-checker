"""E2E 測試：複製任務時過濾與全域預設相同的配置參數，僅回填自訂覆寫值。"""

# pylint: disable=duplicate-code

import re

from playwright.sync_api import Page, expect


def test_duplicate_job_filters_defaults(page: Page, base_url: str) -> None:
    """
    測試複製任務時，是否正確過濾掉與全域預設相同的設定值（留空），
    並僅回填與全域預設不同的自訂覆寫值（回填實體值）。

    Args:
        page (Page): Playwright 的網頁操作物件。
        base_url (str): 測試伺服器的根網址。
    """
    # 1. 登入系統
    page.goto(f"{base_url}/index.html")
    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "Admin@12345678")

    with page.expect_response(lambda response: "/api/jobs" in response.url and response.request.method == "GET"):
        page.click('button[type="submit"]')

    expect(page).to_have_url(re.compile(r".*/app\.html"))
    page.wait_for_selector("text=我的任務")

    # 2. 建立新任務，其中 delay 設為 5.5 秒 (非預設值 3.0)，其他維持預設
    page.click('a[href="#/new"]')
    expect(page).to_have_url(re.compile(r".*/app\.html#/new"))
    page.wait_for_load_state("networkidle")

    page.fill('input[id="job-url"]', "https://example-clone-test.com")
    page.fill('textarea[id="job-target-domains"]', "example-clone-test.com")
    # 填入自訂 delay
    page.fill('input[id="job-delay"]', "5.5")
    # timeout 維持空值 (使用全域預設)

    with page.expect_response("**/api/jobs", timeout=5000) as response_info:
        page.click("#btn-submit-job")

    response = response_info.value
    assert response.ok, f"Job creation failed: {response.status}"

    # 取得剛建立任務的 ID
    expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"), timeout=5000)
    job_id = page.url.split("/")[-1]

    # 3. 點擊「複製任務」按鈕跳轉至複製表單
    # 等待詳情載入並點擊複製
    page.wait_for_selector("#btn-duplicate-job", state="visible")

    with page.expect_response(re.compile(r".*/api/jobs/[0-9a-fA-F-]+$"), timeout=5000):
        page.click("#btn-duplicate-job")

    expect(page).to_have_url(re.compile(r".*/app\.html#/new\?clone=" + job_id))
    page.wait_for_load_state("networkidle")

    # 4. 驗證回填的欄位值是否被正確過濾或保留
    # 自訂的 delay 應該被正確回填為 5.5
    delay_val = page.eval_on_selector('input[id="job-delay"]', "el => el.value")
    assert delay_val == "5.5", f"delay 欄位應為 '5.5'，但得到 '{delay_val}'"

    # 單一覆寫欄位如 timeout (預設值為 60) 即使與預設相同也應直接回填，不應留空
    timeout_val = page.eval_on_selector('input[id="job-timeout"]', "el => el.value")
    assert timeout_val == "60", f"timeout 欄位應為 '60'，但得到 '{timeout_val}'"

    # 單一覆寫欄位如 retries (預設值為 3) 即使與預設相同也應直接回填，不應留空
    retries_val = page.eval_on_selector('input[id="job-retries"]', "el => el.value")
    assert retries_val == "3", f"retries 欄位應為 '3'，但得到 '{retries_val}'"

    # 5. 修改 URL 並提交複製的新任務
    page.fill('input[id="job-url"]', "https://example-clone-target.com")
    page.fill('textarea[id="job-target-domains"]', "example-clone-target.com")

    with page.expect_response("**/api/jobs", timeout=5000) as new_job_response_info:
        page.click("#btn-submit-job")

    new_job_response = new_job_response_info.value
    assert new_job_response.ok, f"Cloned job creation failed: {new_job_response.status}"

    # 驗證新建立成功
    expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"), timeout=5000)
