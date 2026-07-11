from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Listen to requests
        page.on(
            "request",
            lambda request: print(f">>> {request.method} {request.url}") if "summary" in request.url else None,
        )

        # Login
        page.goto("http://localhost:8085/index.html")
        page.fill('input[type="email"]', "admin@test.com")
        page.fill('input[type="password"]', "Admin@12345678")
        page.click('button[type="submit"]')
        page.wait_for_url("**/app.html*", timeout=10000)

        print("Logged in, going to job detail...")

        # We need a job ID. Let's create one or just use the first one from /api/jobs
        # Alternatively, we can just intercept the API call on the jobs page
        # Wait for jobs to load
        page.wait_for_selector("td.td-id a")
        # Click the first job
        page.click("td.td-id a")

        # Wait for some time to see network requests
        page.wait_for_timeout(3000)

        browser.close()


if __name__ == "__main__":
    run()
