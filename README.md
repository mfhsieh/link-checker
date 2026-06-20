# 網站連結檢查系統 (Link Checker)

本專案是一個具備命令列介面 (CLI) 與現代化網頁介面 (Web UI) 的外部連結檢查工具。系統主要用於自動巡覽特定網站，找出連向外部（非信任網域）的連結，並檢查其有效性與傳輸安全性，以協助網站管理員維護連結品質並降低潛在的資安風險。

## 主要功能

- **雙介面操作**：支援現代化的 Web 管理介面與純命令列 (CLI) 獨立執行模式，適應不同維運場景。
- **精準爬行控制**：基於廣度優先搜尋 (BFS)，支援設定最大爬行深度、抓取頁數限制、請求延遲與錯誤重試機制。
- **智慧過濾與探測**：內建 MIME 類型過濾、副檔名忽略與 Regex 路徑排除，並支援繞過特定防爬蟲機制的降級探測。
- **安全性檢查**：自動解析外部連結的 IP 位址，內建 SSRF 防禦，並主動標記非 HTTPS 的明文傳輸連結。
- **內部連結診斷**：自動分類 7 大內部失效樣態 (404, 5xx, 連線逾時, 網頁截斷, 權限不足等)，並支援來源網頁聚合視角，協助快速修補。
- **極致前端效能與資安**：全站採 Vanilla JS (ESM) 原生開發，零第三方框架依賴，並 100% 以 `document.createElement` 進行 DOM 渲染，徹底根絕 XSS 風險。
- **高併發與記憶體保護**：後端採用 O(1) 記憶體去重聚合與 ZIP 串流匯出，前端實作長清單自適應截斷，無懼百萬級資料量。
- **多維度報表匯出**：支援將掃描結果依外連目標、來源頁面或外部網域進行去重聚合，並可匯出為 CSV 或 JSON 格式。

## 系統需求

- Python 3.12 或以上版本
- （建議）使用虛擬環境 (Virtual Environment) 進行安裝

## 第三方元件清單

本專案在技術選型上極度克制，堅持「夠用就好」且「資安至上」的原則。前端實現了「零第三方依賴」，後端則嚴選具備活躍社群維護的穩定開源套件。

### 前端介面 (Frontend)
* **零依賴 (Zero Dependencies)**：全站 UI 介面 100% 採用純原生 Vanilla JavaScript (ESM) 與 CSS 開發，**不包含** React、Vue、jQuery 或 TailwindCSS 等任何框架或函式庫。

### 後端與爬蟲核心 (Backend & Crawler)
* **[FastAPI](https://fastapi.tiangolo.com/)** (`0.115.12`)：高效能的非同步 Web 框架，負責建構管理後台的 RESTful API 與 SSE (Server-Sent Events) 長連線串流。
* **[Uvicorn](https://www.uvicorn.org/)** (`0.34.3`)：作為 FastAPI 底層的高效能 ASGI 伺服器，負責處理 HTTP/網頁請求。
* **[SQLAlchemy](https://www.sqlalchemy.org/)** (`2.0.50`)：業界標準的 Python ORM 框架，負責抽象化底層 SQL 語法，實作 SQLite 與 PostgreSQL 的無縫切換與高效能連線池管理。
* **[psycopg2-binary](https://www.psycopg.org/)** (`2.9.12`)：PostgreSQL 的高可靠 Python 連線驅動程式。
* **[httpx](https://www.python-httpx.org/)** (`0.28.1`)：處理非同步 HTTP 請求，負責執行併發的網頁抓取與狀態碼檢測（搭配 **[h2](https://github.com/python-hyper/h2)** `4.3.0` 模組支援 HTTP/2 通訊協定）。
* **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** (`4.14.3`)：穩定可靠的 HTML 解析神器，負責從雜亂的網頁原始碼中精確萃取出所有連結。
* **[PyYAML](https://pyyaml.org/)** (`6.0.3`)：用於解析、校驗與讀寫 `.yaml` 設定檔。
* **[bcrypt](https://github.com/pyca/bcrypt/)** (`4.3.0`)：採用業界標準的雜湊演算法，處理並保護使用者的登入密碼。
* **[python-dotenv](https://github.com/theskumar/python-dotenv)** (`1.0.1`)：負責從 `.env` 檔案載入機密參數，確保安全配置不寫死於程式碼中。
* **[fake-useragent](https://github.com/fake-useragent/fake-useragent)** (`1.5.1`)：自動隨機產生真實瀏覽器的 User-Agent 標頭，藉以規避基礎防爬蟲機制。
* **[email-validator](https://github.com/JoshData/python-email-validator)** (`2.2.0`)：提供符合 RFC 標準的 Email 格式與 DNS 深度驗證。

### 開發與測試環境 (Development & Testing)
* **[pytest](https://docs.pytest.org/)** (`8.2.0`)：強大的自動化單元與整合測試框架。
* **[Playwright](https://playwright.dev/)** (`1.60.0`)：無頭 (Headless) 瀏覽器測試框架，負責執行前端 UI 的端到端 (E2E) 真實互動測試。
* **[Ruff](https://astral.sh/ruff)** / **[Pylint](https://pylint.pycqa.org/)** / **[Mypy](https://mypy-lang.org/)**：靜態型別檢查與程式碼風格掃描工具，確保專案品質的一致性。

## 快速開始

### 1. 安裝依賴套件

```bash
# 建立虛擬環境
python3.12 -m venv .venv  # 建議使用 python3.12

# 啟動虛擬環境
source .venv/bin/activate
pip install --upgrade pip

# 安裝依賴套件
pip install -r requirements.txt
```

### 2. (可選) 設定環境變數 (.env)

若您只是想在本機快速體驗，**可完全略過此步驟**，系統會自動以預設值建立 SQLite 資料庫。

若要自訂組態，請建立 `.env` 檔案並設定以下變數（可用於覆寫預設值）：

```env
# 應用程式設定
APP_NAME="網站連結檢查系統"
DEBUG="false"

# 資料庫連線
AUTH_DB_URL="sqlite:///db/auth.db"
CRAWLER_DB_URL="sqlite:///db/crawler.db"

# SMTP 設定 (邀請與通知郵件)
SMTP_HOST="smtp.example.com"
SMTP_PORT="587"
SMTP_USERNAME="your-smtp-username"
SMTP_PASSWORD="your-smtp-password"
SMTP_FROM_NAME="網站連結檢查系統"
SMTP_FROM_EMAIL="noreply@example.com"
SMTP_USE_TLS="true"
SMTP_CONSOLE_MODE="false"  # 開發階段可設為 true，將郵件內容輸出至終端機而不實際寄送
```

### 3. 系統管理員初始化

系統採邀請制，首次使用需手動建立第一組管理員帳號：

```bash
python cli.py --create-admin admin@example.com
```

建立完成後，終端機會顯示一組系統產生的高強度隨機密碼。請使用該密碼首次登入 Web 介面，並依照系統提示設定您的專屬密碼。

### 4. 啟動 Web 服務

使用 CLI 指令啟動內建的 FastAPI + Uvicorn 伺服器：

```bash
python cli.py --serve  # 若為開發環境，可加上 --reload 啟用熱重載
```

伺服器將預設在 `http://127.0.0.1:8000` 啟動，請開啟瀏覽器並訪問。

## 命令列 (CLI) 使用方式

除了 Web 介面，您依然可以直接使用 CLI 操作爬蟲核心。

```bash
# 執行單次爬蟲任務（讀取專案內建的 YAML 範例設定檔）
python cli.py -c job/config_job.yaml.example

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
* **[命令列 (CLI) 操作指南](doc/cli_usage.md)**：完整的 CLI 參數、功能介紹與全域設定檔說明。
* **[API 路由清單](doc/api_routes.md)** 與 **[API 完整規格書](doc/api_spec.md)**：後端 RESTful API 規格與傳輸 Schema。
* **[系統需求規格書](doc/requirements.md)**：詳細的功能需求、資安防護與業務邏輯邊界。
* **[爬蟲引擎參數設定指南](doc/crawler_parameters.md)**：爬蟲核心進階參數、白名單與資源限制說明。
* **[資料庫 Schema 說明](doc/db_schema.md)**：Crawler DB 與 Auth DB 實體關聯圖與詳細結構。
* **[GCP VM 部署指南](doc/deploy_gcp_vm.md)** 與 **[PostgreSQL 升級指南](doc/migrate_to_postgresql.md)**：雲端建置、Nginx 反向代理與資料庫平滑移轉。
* **[自動化測試策略](doc/testing_strategy.md)**：模組級隔離架構與自動化測試執行指引。
* **程式風格與開發規範**：[Python 規範](doc/python_coding_style.md) / [JavaScript 規範](doc/js_coding_style.md)
* **[待辦清單與後續規劃](doc/todo.md)**

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

---

## 訊息揭露
本應用程式的程式碼主要透過 AI 工具（Antigravity IDE）協助生成，並經人工審閱與修改。
