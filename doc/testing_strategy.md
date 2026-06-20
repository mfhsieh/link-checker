# 自動化測試策略與執行指南 (Testing Strategy)

本文件詳細說明「網站連結檢查系統」的自動化測試架構、設計理念與執行方式，作為未來增修測試案例的統一規範。

---

## 1. 核心設計理念：模組級隔離與單例重設 (Module-Level Isolation & Singleton Reset)

為了解決不同測試案例（`test_api.py`, `test_cli.py`, `test/e2e/`）在透過 `pytest test/` 一次性執行時，因共用全域單例物件（Singleton）或 FastAPI 依賴覆寫所造成的互相干擾與狀態污染問題，本專案的測試框架已重構為以 `pytest` Fixture 為核心的**模組級隔離架構**。

### 1.1 中央隔離 Fixture (`test/conftest.py`)

所有跨測試模組共用的隔離邏輯，皆統一集中於根目錄的 `test/conftest.py` 中。其核心職責是提供一個在**每個測試檔案 (`test_*.py`) 執行前後**都會自動運行的 Fixture：

*   **`_reset_singletons_and_overrides`**：此為最核心的隔離 Fixture，其生命週期為 `scope="module"`。它會在**每個測試檔案執行前**，自動完成以下隔離操作：
    1.  **安全釋放與重設單例 (Dispose & Reset Singletons)**：強制關閉連線池 (`dispose()`) 以解除 SQLite 的檔案鎖定，並將 `backend` 模組中快取的全域單例物件（如 `_ENGINE`, `_SESSION_LOCAL`, `_JOB_MANAGER`）設為 `None`。這確保了每個測試檔案在首次使用這些物件時，都會根據其專屬的環境變數重新初始化，徹底阻絕狀態污染。
    2.  **清除依賴覆寫 (Clear Dependency Overrides)**：強制呼叫 `app.dependency_overrides.clear()`，移除上一個測試檔案可能設定的任何 Mock 或依賴覆寫，防止測試之間的 Mock 污染。
    3.  **刷新設定快取 (Refresh Settings Cache)**：強制清除 `get_settings()` 的 `lru_cache`，確保每個測試檔案都能讀取到自己專屬的 `AUTH_DB_URL` 與 `CRAWLER_DB_URL` 環境變數。

### 1.2 隔離原則與檔案內狀態管理

*   **模組級隔離 (`scope="module"`)**：本專案的隔離層級為「模組級」，意即**每個測試檔案 (`test_*.py`) 都會取得一個乾淨的沙箱環境**。
*   **檔案內狀態管理**：由於隔離層級為模組，同一個檔案內的不同測試函式 (`def test_...`) 可能會共享狀態。因此，各個測試檔案內部仍需自行管理其專屬的資料庫檔案與狀態清理。例如，`test_api.py` 與 `test_cli.py` 內部皆有各自的 `setup_databases()` 與 `teardown_databases()` 函式，用以在測試前後清理 `db/test_auth_api.db` 或 `db/test_crawler_cli.db` 等實體檔案。

### 1.3 前端 E2E 測試之 API 攔截與模擬策略 (API Interception & Mocking in E2E)

為了確保前端 UI 測試在面對異步爬蟲、背景任務與網絡不確定性時的穩定度與執行效能，本專案的前端 E2E 測試（Playwright 框架）實施了以下 API 攔截與模擬機制：
*   **動態 API 攔截 (`page.route`)**：在 UI 測試（如 `test_app.py` 與 `test_duplicate.py`）中，我們廣泛使用 Playwright 攔截了發往 `/api/jobs` 等控制端點的請求。這使我們能動態控制回傳的任務狀態（如 `pending`, `running`, `completed`, `error` 等）並強制模擬伺服器錯誤 (HTTP 500)，而無須依賴真實爬蟲子程序的執行。此方法不僅 100% 避開了後端時序競態造成的干擾，更能完美驗證公用元件（如 `toast.js`）在接收各種成功或失敗回應時的 UI 彈出邏輯。
*   **Server-Sent Events (SSE) 串流模擬**：為防止前端 JavaScript 的 `EventSource` 連線因為 API 攔截而一直處於掛起 (pending) 狀態進而影響按鈕點擊等 UI 互動，測試攔截了 `/stream` 端點，並回傳正確的 `text/event-stream` 標頭及空內容，確保前端連線能被溫和地關閉與釋放。

---

## 2. 測試檔案職責劃分

*   **`test/test_api.py`**：
    *   **職責**：針對後端 API 進行完整的整合與端到端劇本測試。
    *   **狀態管理**：在檔案內部透過 `setup_databases()` 與 `teardown_databases()` 管理其專屬的 `db/test_auth_api.db` 與 `db/test_crawler_api.db` 資料庫檔案。
    *   **主要測試範疇**：
        1. **端點功能驗證**：登入/登出、修改密碼、設定密碼（Pending 帳號）、忘記/重設密碼；管理員端點（邀請使用者、重新邀請、停用/啟用、角色權限 Promote/Demote、修改/取得全域配置、SMTP 發信測試、操作日誌取得）；任務控制（建立、啟動、暫停、恢復、重置、重試失敗、任務移交、管理員接管與刪除）。
        2. **真實劇本情境測試 (Real Scenario Flow)**：利用 Mock Server 為靶機，模擬真實使用者登入、建立並啟動爬蟲任務、API 狀態輪詢 (Polling)、檢驗外連結果與匯出 CSV/JSON 報表的完整閉環流程。

*   **`test/test_cli.py`**：
    *   **職責**：針對 CLI 任務調度與核心爬蟲引擎進行單元測試與整合測試。
    *   **狀態管理**：在檔案內部透過 `setup_databases()` 與 `teardown_databases()` 管理其專屬的 `db/test_auth_cli.db` 與 `db/test_crawler_cli.db` 資料庫檔案。
    *   **主要測試範疇**：
        1. **單元測試**：驗證核心模組中的「雙 Client 憑證驗證豁免與子網域繼承機制 (`CrawlerCore._get_client`)」、「網域專屬延遲 (`domain_delays`) 的優先順序匹配算法」，以及「多層級配置合併與環境變數優先覆寫規則」。
        2. **整合與指令測試**：以 Mock Server 作為爬行目標，測試全域/局部配置套用；驗證 `--max-depth` 與 `--max-pages` 的精確限制；測試任務生命週期指令（暫停 `--pause` 與恢復 `--resume`、重置 `--reset`、刪除 `--delete` 與局部重試 `--retry-failed`）；驗證 WAF 520 對社群平台 (`social_domains`) 自動 GET 降級重試；驗證惡意拖延 (Tarpit) 之逾時防禦；測試 CLI 匯出與多維度篩選器 (`--export`, `--filter dead|broken|insecure`, `--exclude`, `--group-by`) 暨 ZIP 完整報告打包匯出 (`--export-full`)。

*   **`test/test_admin_logs.py`**：
    *   **職責**：驗證後台管理員之敏感管理與安全稽核日誌功能。
    *   **主要測試範疇**：驗證全域配置修改、使用者帳號狀態變更、刪除使用者、強制接管任務、刪除任務等高風險操作是否正確寫入 `auth_logs`。同時，驗證日誌查詢 API 對日期範圍篩選參數（`from_date`）的過濾精確度。
    *   **狀態管理**：採用 `unittest.TestCase` 框架，於 class 級別進行環境的準備與清理。

*   **`test/test_scheduler.py`**：
    *   **職責**：針對後端排程器與任務並發控制機制進行整合測試。
    *   **主要測試範疇**：驗證當系統同時執行的任務數量達到 `CRAWLER_MAX_CONCURRENT_JOBS` 上限時，後續建立並啟動的任務會被正確攔截並強制進入 `queued` (排隊中) 狀態，確保系統不會因資源超載而崩潰。

*   **`test/utils.py`**：
    *   **職責**：測試環境共用之底層輔助工具模組。
    *   **主要測試範疇**：提供 `is_port_in_use` 與 `wait_for_server` 等網路狀態檢查函式，專供 E2E 測試在動態啟動 Fastapi 測試伺服器時，進行通訊埠綁定確認與防呆等待，避免時序競態問題。

*   **`test/e2e/`**：
    *   **職責**：前端使用者介面 (UI) 真實互動與確認對話框 (Modal) 的自動化 E2E 測試。
    *   **主要測試範疇**：
        1. **身分驗證 (`test_auth.py`)**：測試登入成功（跳轉至 `app.html`）與登入失敗（留在原頁並顯示錯誤）的 UI 表現。
        2. **任務管理與生命週期 (`test_app.py`, `test_duplicate.py`)**：測試建立任務時的防呆與預設值載入；測試啟動、暫停、重置、重試、刪除按鈕與確認對話框二次確認、Toast 提示與頁面跳轉的 UI 整合。另外，驗證「複製任務」時，UI 是否能聰明地過濾掉與全域預設值相同的參數，確保表單僅回填使用者的自訂覆寫值。
        3. **管理員後台與使用者管理 (`test_admin.py`)**：測試全域配置修改；測試邀請使用者、重寄邀請、提降帳號角色 (Promote/Demote)、停用與啟用帳號、以及刪除使用者等 UI 操作與確認 Modal 流程。
    *   **狀態管理**：透過 `test/e2e/conftest.py` 中的 `session`-scoped Fixture，在所有 E2E 測試執行前啟動一次 Web 伺服器與測試資料庫，並在所有測試結束後清理。

---

## 3. 測試執行

由於已建立模組級隔離，您可以安全地透過單一指令執行所有測試，無需擔心互相干擾。

```bash
# 於專案根目錄執行
pytest test/ -v
```

為求便利，專案也提供了 `scripts/run_all_tests.sh` 腳本，其內容即為上述指令。
    
