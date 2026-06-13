import re
from playwright.sync_api import Page, expect

def test_create_job(page: Page, base_url: str):
    """測試登入後建立一個爬蟲任務。"""
    # 必須先登入
    page.goto(f"{base_url}/index.html")
    page.fill('input[type="email"]', 'admin@test.com')
    page.fill('input[type="password"]', 'Admin@12345678')
    page.click('button[type="submit"]')
    
    # 等待頁面跳轉與載入完成 (確保 JS 已完整執行並綁定事件)
    with page.expect_response(lambda response: "/api/jobs" in response.url and response.request.method == "GET"):
        expect(page).to_have_url(re.compile(r".*/app\.html"))
        
    page.wait_for_selector('text=我的任務')
    
    # 點擊建立任務按鈕
    page.click('a[href="#/new"]')
    expect(page).to_have_url(re.compile(r".*/app\.html#/new"))
    
    # 等待 router() 中的 loadJobDefaults 與 form.reset() 完成，避免清空我們填寫的值
    page.wait_for_load_state('networkidle')

    # 填寫任務資訊
    page.fill('input[id="job-url"]', 'https://example.com')
    page.fill('textarea[id="job-target-domains"]', 'example.com')
    
    # 紀錄 console.log 方便除錯
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(f"CONSOLE: {msg.text}"))

    try:
        # 點擊送出並等待 API 回應
        with page.expect_response("**/api/jobs", timeout=5000) as response_info:
            page.click('#btn-submit-job')
            
        response = response_info.value
        assert response.ok, f"Job creation failed: {response.status}"
        
        # 驗證跳轉回任務詳情頁面並出現新任務的 URL
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"), timeout=5000)
        expect(page.locator('#view-job-detail')).to_contain_text("https://example.com")
    except Exception as e:
        error_text = page.locator('#create-job-error').inner_text() if page.locator('#create-job-error').is_visible() else "Not visible"
        raise AssertionError(f"Error during job creation: {type(e).__name__} - {str(e)}\nUI Error text: {error_text}\nConsole logs:\n" + "\n".join(console_msgs)) from e
