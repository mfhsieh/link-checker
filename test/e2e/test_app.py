"""E2E 測試：應用程式主要功能與任務操作流程。"""

import re

from playwright.sync_api import Page, expect


def test_create_job(page: Page, base_url: str) -> None:
    """
    測試登入後建立一個爬蟲任務。

    Args:
        page (Page): Playwright 的網頁操作物件.
        base_url (str): 測試伺服器的根網址.

    Raises:
        AssertionError: 任務建立失敗或發生非預期錯誤時拋出.
    """
    # 必須先登入
    page.goto(f"{base_url}/index.html")
    page.fill('input[type="email"]', "admin@test.com")
    page.fill('input[type="password"]', "Admin@12345678")

    # 等待頁面跳轉與載入完成 (確保 JS 已完整執行並綁定事件)
    with page.expect_response(lambda response: "/api/jobs" in response.url and response.request.method == "GET"):
        page.click('button[type="submit"]')

    expect(page).to_have_url(re.compile(r".*/app\.html"))
    page.wait_for_selector("text=我的任務")

    # 點擊建立任務按鈕
    page.click('a[href="#/new"]')
    expect(page).to_have_url(re.compile(r".*/app\.html#/new"))

    # 等待 router() 中的 loadJobDefaults 與 form.reset() 完成，避免清空我們填寫的值
    page.wait_for_load_state("networkidle")

    # 填寫任務資訊
    page.fill('input[id="job-url"]', "https://example.com")
    page.fill('textarea[id="job-target-domains"]', "example.com")

    # 紀錄 console.log 方便除錯
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(f"CONSOLE: {msg.text}"))

    try:
        # 點擊送出並等待 API 回應
        with page.expect_response("**/api/jobs", timeout=5000) as response_info:
            page.click("#btn-submit-job")

        response = response_info.value
        assert response.ok, f"Job creation failed: {response.status}"

        # 驗證跳轉回任務詳情頁面並出現新任務的 URL
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"), timeout=5000)
        expect(page.locator("#view-job-detail")).to_contain_text("https://example.com")
    except Exception as e:
        error_text = (
            page.locator("#create-job-error").inner_text()
            if page.locator("#create-job-error").is_visible()
            else "Not visible"
        )
        raise AssertionError(
            f"Error during job creation: {type(e).__name__} - {str(e)}\nUI Error text: {error_text}\nConsole logs:\n"
            + "\n".join(console_msgs)
        ) from e


# pylint: disable=too-many-statements
def test_job_lifecycle_ui(page: Page, base_url: str) -> None:
    """
    測試任務控制按鈕（啟動、暫停、重置、重試、刪除）的 UI 互動與確認 Modal 流程。

    此測試使用 page.route 攔截並模擬 API 回應，以確保測試在各種任務狀態下的穩定度，
    並避免受後端進程狀態或假死清理機制的影響。

    Args:
        page (Page): Playwright 的網頁操作物件.
        base_url (str): 測試伺服器的根網址.

    Raises:
        AssertionError: 測試流程中發生非預期結果或驗證失敗.
    """
    # 紀錄 console.log 與攔截日誌方便除錯
    console_msgs = []
    page.on("console", lambda msg: console_msgs.append(f"CONSOLE: {msg.text}"))

    # 配置 API 攔截器狀態與攔截邏輯（必須在第一次 page.goto 之前註冊以保證 reload 時不失效）
    mock_state = {"status": "pending", "is_running": False}
    context_data = {"job_id": None}

    def handle_jobs_api(route):
        url = route.request.url
        method = route.request.method
        jid = context_data["job_id"]

        console_msgs.append(
            f"PLAYWRIGHT INTERCEPTED: {method} {url} "
            f"(jid={jid}, mock_status={mock_state['status']}, mock_running={mock_state['is_running']})"
        )

        try:
            # 1. 建立任務的 POST 請求直接放行，讓其真實建立任務取得真實 ID
            if url.endswith("/api/jobs") and method == "POST":
                route.continue_()
                return

            # 2. 當我們取得 job_id 後，攔截後續的任務詳情與控制 API 請求
            if jid and jid in url:
                if method == "DELETE":
                    route.fulfill(json={"status": "success"})
                elif url.endswith(f"/api/jobs/{jid}"):
                    route.fulfill(
                        json={
                            "id": jid,
                            "start_url": "https://example-lifecycle.com",
                            "status": mock_state["status"],
                            "created_at": "2026-06-18T00:00:00Z",
                            "updated_at": "2026-06-18T00:00:00Z",
                            "config": {
                                "target_domains": ["example-lifecycle.com"],
                                "trusted_domains": [],
                            },
                            "progress": {
                                "total": 10,
                                "completed": 5,
                                "warning": 1,
                                "skipped": 1,
                                "pending": 2,
                                "failed": 1,
                            },
                            "external_link_count": 5,
                            "is_running": mock_state["is_running"],
                        }
                    )
                elif url.endswith("/stream"):
                    # 模擬 SSE 長連線，回傳空的 event-stream 避免連線阻塞掛起
                    route.fulfill(
                        status=200,
                        content_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                        },
                        body="",
                    )
                elif (
                    url.endswith("/start")
                    or url.endswith("/pause")
                    or url.endswith("/reset")
                    or url.endswith("/retry-failed")
                ):
                    route.fulfill(json={"status": "success"})
                else:
                    route.continue_()
            else:
                route.continue_()
        except Exception as err:  # pylint: disable=broad-exception-caught
            console_msgs.append(f"ERROR IN ROUTE HANDLER: {err}")
            route.continue_()

    # 註冊全域任務 API 攔截，使用 lambda 精確匹配以避免 minimatch 匹配問題
    page.route(lambda url: "/api/jobs" in url, handle_jobs_api)

    try:
        # 1. 登入系統
        page.goto(f"{base_url}/index.html")
        page.fill('input[type="email"]', "admin@test.com")
        page.fill('input[type="password"]', "Admin@12345678")

        with page.expect_response(lambda response: "/api/jobs" in response.url and response.request.method == "GET"):
            page.click('button[type="submit"]')

        expect(page).to_have_url(re.compile(r".*/app\.html"))
        page.wait_for_selector("text=我的任務")

        # 2. 建立新測試任務以取得真實 ID
        page.click('a[href="#/new"]')
        expect(page).to_have_url(re.compile(r".*/app\.html#/new"))
        page.wait_for_load_state("networkidle")

        page.fill('input[id="job-url"]', "https://example-lifecycle.com")
        page.fill('textarea[id="job-target-domains"]', "example-lifecycle.com")

        with page.expect_response("**/api/jobs", timeout=5000) as response_info:
            page.click("#btn-submit-job")

        response = response_info.value
        assert response.ok, f"Job creation failed: {response.status}"

        # 等待跳轉並取得任務 ID，此時將 ID 設定至攔截器 context 中
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"), timeout=5000)
        job_id = page.url.split("/")[-1]
        context_data["job_id"] = job_id

        # 3. 測試【啟動任務】UI
        mock_state["status"] = "pending"
        mock_state["is_running"] = False
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"))

        page.wait_for_selector("#btn-start-job", state="visible")
        page.click("#btn-start-job")
        page.wait_for_selector("#confirm-modal-submit", state="visible")

        with page.expect_response(f"**/api/jobs/{job_id}/start"):
            page.click("#confirm-modal-submit")

        expect(page.locator(".toast-container").last).to_contain_text(re.compile("啟動|成功"))

        # 4. 測試【暫停任務】UI
        mock_state["status"] = "running"
        mock_state["is_running"] = True
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"))

        page.wait_for_selector("#btn-pause-job", state="visible")
        page.click("#btn-pause-job")
        page.wait_for_selector("#confirm-modal-submit", state="visible")

        with page.expect_response(f"**/api/jobs/{job_id}/pause"):
            page.click("#confirm-modal-submit")

        expect(page.locator(".toast-container").last).to_contain_text(re.compile("暫停|指令"))

        # 5. 測試【重置任務】UI
        mock_state["status"] = "completed"
        mock_state["is_running"] = False
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"))

        page.wait_for_selector("#btn-reset-job", state="visible")
        page.click("#btn-reset-job")
        page.wait_for_selector("#confirm-modal-submit", state="visible")

        with page.expect_response(f"**/api/jobs/{job_id}/reset"):
            page.click("#confirm-modal-submit")

        expect(page.locator(".toast-container").last).to_contain_text(re.compile("重置"))

        # 6. 測試【重試失敗項目】UI
        mock_state["status"] = "error"
        mock_state["is_running"] = False
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs/[0-9a-fA-F-]+$"))

        page.wait_for_selector("#btn-retry-failed-job", state="visible")
        page.click("#btn-retry-failed-job")
        page.wait_for_selector("#confirm-modal-submit", state="visible")

        with page.expect_response(f"**/api/jobs/{job_id}/retry-failed"):
            page.click("#confirm-modal-submit")

        expect(page.locator(".toast-container").last).to_contain_text(re.compile("重試|失敗項目"))

        # 7. 測試【刪除任務】UI
        page.wait_for_selector("#btn-delete-job", state="visible")
        page.click("#btn-delete-job")
        page.wait_for_selector("#confirm-modal-submit", state="visible")

        with page.expect_response(lambda r: f"/api/jobs/{job_id}" in r.url and r.request.method == "DELETE"):
            page.click("#confirm-modal-submit")

        expect(page).to_have_url(re.compile(r".*/app\.html#/jobs"))
        expect(page.locator(".toast-container").last).to_contain_text(re.compile("刪除"))
    except Exception as e:
        raise AssertionError(
            f"Error during lifecycle UI test: {type(e).__name__} - {str(e)}\nConsole logs:\n" + "\n".join(console_msgs)
        ) from e
