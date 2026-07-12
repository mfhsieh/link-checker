# 網站連結檢查系統 (Link Checker)

本專案是一個具備命令列介面 (CLI) 與現代化網頁介面 (Web UI) 的網站連結檢查工具。系統主要用於自動巡覽特定網站，不僅能深度檢測網頁內部連結的失效狀態（如 404、5xx 等），還能找出外部連結並檢查其有效性與安全性。目標在協助網站管理員維護整體網站品質、提升使用者體驗，並降低潛在的資安風險。

## 主要功能

- **雙介面操作**：支援現代化的 Web 管理介面與純命令列 (CLI) 獨立執行模式，適應不同維運場景。
- **精準爬行控制**：基於廣度優先搜尋 (BFS)，支援設定最大爬行深度、抓取頁數限制、請求延遲與錯誤重試機制。
- **智慧過濾與探測**：內建 MIME 類型過濾、副檔名忽略與 Regex 路徑排除，並支援繞過特定防爬蟲機制的降級探測。
- **外部連結檢查**：針對站外連結，自動分類異常狀態並支援多維度視角檢視（如外部網域、來源頁面），同時內建解析 IP 防禦 SSRF 與非 HTTPS 標記，確保對外連線的安全。
- **內部連結診斷**：針對站內連結，自動分類異常狀態，並支援來源網頁聚合視角，協助快速修補。
- **極致前端效能與資安**：全站採 Vanilla JS (ESM) 原生開發，零第三方框架依賴，並 100% 以 `document.createElement` 進行 DOM 渲染，徹底根絕 XSS 風險。
- **高併發與記憶體保護**：後端採用 O(1) 記憶體去重聚合與 ZIP 串流匯出，前端實作長清單自適應截斷，無懼百萬級資料量。
- **多維度報表匯出**：支援將掃描結果依目標頁面、來源頁面或外部網域進行去重聚合，並可匯出為 CSV 或 JSON 格式。
- **即時狀態監控**：後端透過 Server-Sent Events (SSE) 推播進度，讓使用者能在 Web 介面即時查看爬蟲的執行狀態與數據變化。
- **資料備份與遷移**：內建維運腳本支援單一任務資料的匯出匯入與移交；並提供升級腳本，支援從本機 SQLite 平滑移轉至 PostgreSQL。
- **身分驗證與安全**：系統後台採邀請制設計，採用 Bcrypt 密碼雜湊與基於 HTTPOnly Cookie 的工作階段管理，並實作 CSRF 防禦機制。

## 系統需求

- （建議）Python 3.12
- （建議）使用虛擬環境 (Virtual Environment) 進行安裝

## 第三方元件清單

本專案在技術選型上極度克制，堅持「夠用就好」的原則。前端「零第三方依賴」，後端則嚴選由活躍社群維護的開源套件。

### 前端介面 (Frontend)
* **零依賴 (Zero Dependencies)**：全站 UI 介面採用原生 Vanilla JavaScript (ESM) 與 CSS 開發，**不包含** React、Vue、jQuery 或 TailwindCSS 等任何框架或函式庫。

### 後端與爬蟲核心 (Backend & Crawler)
* **[FastAPI](https://fastapi.tiangolo.com/)** (`0.115.12`)：高效能的非同步 Web 框架，負責建構管理後台的 RESTful API 與 SSE (Server-Sent Events) 串流。
* **[Uvicorn](https://www.uvicorn.org/)** (`0.34.3`)：作為 FastAPI 底層的高效能 ASGI 伺服器，負責處理 HTTP/網頁請求。
* **[SQLAlchemy](https://www.sqlalchemy.org/)** (`2.0.50`)：標準的 Python ORM 框架，負責封裝 SQL 語法，實作 SQLite 與 PostgreSQL 的無縫切換。
* **[psycopg2-binary](https://www.psycopg.org/)** (`2.9.12`)：PostgreSQL 的 Python 驅動程式。
* **[httpx](https://www.python-httpx.org/)** (`0.28.1`)：處理非同步 HTTP 請求，負責執行併發的網頁抓取與狀態碼檢測（搭配 **[h2](https://github.com/python-hyper/h2)** `4.3.0` 模組支援 HTTP/2 通訊協定）。
* **[curl_cffi](https://github.com/yifeikong/curl_cffi)** (`0.15.0`)：基於 curl-impersonate 的進階 HTTP 客戶端，用於模擬真實瀏覽器 TLS/JA3 指紋，協助繞過 Cloudflare 等高階防爬蟲機制 (WAF)。
* **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** (`4.14.3`)：負責 HTML 解析，從網頁原始碼中萃取連結。
* **[PyYAML](https://pyyaml.org/)** (`6.0.3`)：用於解析、校驗與讀寫 `.yaml` 設定檔。
* **[bcrypt](https://github.com/pyca/bcrypt/)** (`4.3.0`)：雜湊演算法，處理並保護使用者的登入密碼。
* **[python-dotenv](https://github.com/theskumar/python-dotenv)** (`1.0.1`)：負責從 `.env` 檔案載入環境變數，確保配置與程式碼分離。
* **[fake-useragent](https://github.com/fake-useragent/fake-useragent)** (`1.5.1`)：自動隨機產生模仿瀏覽器的 User-Agent，藉以規避基礎防爬蟲機制。
* **[email-validator](https://github.com/JoshData/python-email-validator)** (`2.2.0`)：提供符合 RFC 標準的 Email 格式與 DNS 深度驗證。
* **[cachetools](https://github.com/tkem/cachetools/)** (`7.1.4`)：提供具備自動到期 (TTL) 能力的記憶體快取，減輕後端 API 的重複聚合運算壓力。
### 開發與測試環境 (Development & Testing)
* **[pytest](https://docs.pytest.org/)** (`8.2.0`)：自動化單元與整合測試框架。
* **[Playwright](https://playwright.dev/)** (`1.60.0`)：無頭 (Headless) 瀏覽器測試框架，負責執行前端 UI 的端到端 (E2E) 互動測試。
* **[Ruff](https://astral.sh/ruff)** / **[Pylint](https://pylint.pycqa.org/)** / **[Mypy](https://mypy-lang.org/)**：靜態型別檢查與程式碼風格掃描工具，確保專案品質。

## 快速開始

### 1. 取得原始碼

首先，將專案原始碼複製到本機並進入專案目錄：

```bash
git clone https://github.com/mfhsieh/link-checker.git
cd link-checker
```

### 2. 安裝依賴套件

```bash
# 建立虛擬環境，建議使用 python 3.12
python3.12 -m venv .venv

# 啟動虛擬環境
source .venv/bin/activate

# 更新 PIP
pip install --upgrade pip

# 安裝套件
pip install -r requirements.txt
```

### 3. (可選) 設定環境變數 (.env)

若您只是想在本機快速體驗，**可完全略過此步驟**，系統會自動以預設組態執行。

若要自訂組態，請參考 [.env.example](.env.example) 建立 `.env` 檔案。

> ⚠️ **安全提醒**：`.env` 檔案通常會用來儲存機敏資訊（例如 SMTP 密碼或 Proxy 帳密等）。請務必在建立檔案後**更改其讀寫權限**，防止未經授權的存取。在 Linux/macOS 環境下，建議執行以下指令：
> ```bash
> chmod 600 .env
> ```

### 4. 系統管理員初始化

系統採邀請制，首次使用需手動建立第一組管理員帳號：

```bash
python cli.py --create-admin admin@example.com
```

建立完成後，終端機會顯示一組系統產生的高強度隨機密碼。請使用該密碼首次登入 Web 介面，並依照系統提示設定您的專屬密碼。

### 5. 啟動 Web 服務

使用 CLI 指令啟動 Web 介面：

```bash
# 若為開發環境，可加上 --reload 啟用熱重載
python cli.py --serve
```

網站預設在 `http://127.0.0.1:8000` 啟動，請開啟瀏覽器進入。

## 命令列 (CLI) 使用方式

除了 Web 介面，您也可以直接使用 CLI 操作爬蟲核心。

```bash
# 執行單次爬蟲任務（可參考 job 目錄下的範例設定檔）
python cli.py -c job/config_job.yaml

# 列出所有任務
python cli.py --list-jobs

# 匯出任務報告為 CSV
python cli.py --export <JOB_ID> --output report.csv

# 查詢可用的參數選項
python cli.py --help
```

## 進階文件與資源

為了保持 README 的簡潔，更詳細的系統設計與操作手冊已拆分至 `doc/` 目錄中：

* **[系統架構說明](doc/architecture.md)**：了解系統目錄結構與核心技術選型。
* **[模組依賴說明](doc/module_dependencies.md)**：詳細條列本專案各核心模組（前端、後端、爬蟲核心與 CLI）間的依賴關係與隔離邊界。
* **[命令列 (CLI) 操作指南](doc/cli_usage.md)**：完整的 CLI 參數、功能介紹與全域設定檔說明。
* **[MCP Server 使用指南](doc/mcp_usage.md)**：提供 AI 助理與開發者遠端查詢任務狀態的 Model Context Protocol 介面說明。
* **[API 路由清單](doc/api_routes.md)** 與 **[API 完整規格書](doc/api_spec.md)**：後端 RESTful API 規格與傳輸 Schema。
* **[系統需求規格書](doc/requirements.md)**：詳細的功能需求、資安防護與業務邏輯邊界。
* **[網站爬蟲核心流程說明](doc/crawler_workflow.md)**：詳細說明爬蟲抓取、解析、與錯誤重試的完整生命週期與驗證機制。
* **[爬蟲引擎參數設定指南](doc/crawler_parameters.md)**：爬蟲核心進階參數、白名單與資源限制說明。
* **[資料庫 Schema 說明](doc/db_schema.md)**：Crawler DB 與 Auth DB 實體關聯圖與詳細結構。
* **[GCP VM 部署指南](doc/deploy_gcp_vm.md)** 與 **[PostgreSQL 升級指南](doc/migrate_to_postgresql.md)**：雲端建置、Nginx 反向代理與資料庫平滑移轉。
* **[自動化測試策略](doc/testing_strategy.md)**：模組級隔離架構與自動化測試執行指引。
* **程式風格與開發規範**：[Python 規範](doc/python_coding_style.md) / [JavaScript 規範](doc/js_coding_style.md)
* **[待辦清單與後續規劃](doc/todo.md)**

---

## 升級提醒 (Upgrading)

> [!IMPORTANT]
> **從 v1.8.x 升級至 v1.9.0 或更高版本**
> 因為 `crawl_queue` 新增 HTTPS 檢測欄位 (`is_secure`)，如使用 PostgreSQL，請務必手動執行以下指令（ `lc_user` 指 `crawler_db` 的 username）：
> 
> ```bash
> sudo systemctl stop link-checker
> psql -U lc_user -d crawler_db -c "ALTER TABLE crawl_queue ADD COLUMN is_secure BOOLEAN DEFAULT TRUE;"
> psql -U lc_user -d crawler_db -c "UPDATE crawl_queue SET is_secure = FALSE WHERE url LIKE 'http://%';"
> psql -U lc_user -d crawler_db -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_crawl_queue_internal_issues ON crawl_queue (job_id) WHERE status IN ('failed', 'warning') OR is_secure = false;"
> sudo systemctl start link-checker
> ```

> [!IMPORTANT]
> **升級至 v1.9.4 或更高版本**
> 為了讓外部連結具備 `updated_at` 追蹤能力，以及減輕 `poller.py` 造成的 `O(N)` 全表掃描負擔（`jobs` 新增 `progress_stats` 欄位快取），如使用 PostgreSQL，請務必手動執行以下指令：
> 
> ```bash
> sudo systemctl stop link-checker
> psql -U lc_user -d crawler_db -c "ALTER TABLE external_links ADD COLUMN updated_at TIMESTAMP;"
> psql -U lc_user -d crawler_db -c "UPDATE external_links SET updated_at = created_at WHERE updated_at IS NULL;"
> psql -U lc_user -d crawler_db -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_external_links_job_target ON external_links (job_id, target_url);"
> psql -U lc_user -d crawler_db -c "ALTER TABLE jobs ADD COLUMN progress_stats TEXT;"
> sudo systemctl start link-checker
> ```

*(備註：若是在測試環境使用 SQLite，您可以刪除舊有資料庫讓系統自動重建，或是參考上述 SQL 語法自行更新。)*

---

## 授權條款
本專案採用 **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-Hant)** 授權條款釋出。

使用者可自由分享或修改，但須遵循以下條件：

| 條件 | 說明 |
|------|------|
| **姓名標示 (BY)** | 必須提供適當的姓名標示，並附上授權條款連結 |
| **非商業性 (NC)** | 不得用於商業目的 |
| **相同方式分享 (SA)** | 若改作或再發布，須採用相同授權條款 |

作者：[mfhsieh at github](https://github.com/mfhsieh)

## 版本更新日誌 (Release Notes)

- **v1.9.4 (2026-07-12)**: 
  - 於後台管理端加入 `backup.py` 等模組，實作資料備份與匯出匯入。
  - 建立 `events.py` 與 `JobProgressPoller`，調整內部事件驅動機制。
  - 實作多層次快取機制 (包含 DNS 解析、後端 API、爬蟲核心與前端摘要)，大幅降低重複計算與網路請求。
  - 全面整合 mypy 靜態型別檢查。
  - 調整 DB schema，為 `jobs` 資料表新增 `progress_stats` 欄位，以及為 `external_links` 資料表新增 `updated_at` 欄位。
  - 加入 `.agents/` 目錄，提供 AI 開發輔助設定與工具。
  - 新增 `scripts/mcp_server.py`，提供對外部 MCP 系統的任務監控與控制指令 (待持續擴充)。
  - 其它優化。
- **v1.9.3 (2026-07-05)**: 前端 (frontend/) 重構，並導入 Web Components 架構。
- **v1.9.2 (2026-06-27)**: [爬蟲核心](crawler/core.py) 升級，詳 [網站爬蟲核心流程說明](doc/crawler_workflow.md)

---

## 訊息揭露
本應用程式的程式碼主要透過 AI 工具（Antigravity IDE）協助生成，並經人工審閱與修改。
