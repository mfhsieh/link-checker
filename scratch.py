from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/chromium")
    page = browser.new_page()
    page.goto("http://127.0.0.1:8085/index.html")
    page.fill('input[type="email"]', 'admin@test.com')
    page.fill('input[type="password"]', 'Admin@12345678')
    page.click('button[type="submit"]')
    page.wait_for_url("**/app.html")
    
    page.goto("http://127.0.0.1:8085/app.html#/new")
    page.fill('input[id="job-url"]', 'https://example.com')
    page.fill('textarea[id="job-target-domains"]', 'example.com')
    page.click('#btn-submit-job')
    
    page.wait_for_timeout(2000)
    print("URL:", page.url)
    print("Error:", page.locator('#create-job-error').inner_text())
    browser.close()
