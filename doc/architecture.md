# 外連檢查爬蟲 (External Link Checker) 架構說明

本文件旨在概述系統的目錄結構與核心設計理念。專案目標為建立一個能夠遍歷特定網域，找出外部網域連結並記錄其 IP 的高擴充性爬蟲系統。

## 專案目錄架構

```text
ext-link-checker/
├── .env                # 環境變數設定檔 (如資料庫路徑、SMTP 憑證等)
├── .gitignore          # git 追蹤忽略清單
├── .pylintrc           # Pylint 靜態程式碼分析設定檔
├── ruff.toml           # Ruff 程式碼排版設定檔
├── README.md           # 專案首頁與安裝啟動說明
├── cli.py              # 系統核心單一入口 (CLI 操作、伺服器啟動與管理員建立)
├── requirements.txt    # Python 依賴套件清單
├── backend/            # 網站後台 (FastAPI / Web API Server)
│   ├── __init__.py
│   ├── admin/          # 後台管理員 API 模組
│   ├── auth/           # 身分驗證與 Session 管理模組
│   ├── jobs/           # 任務管理 API 模組
│   ├── config.py       # 系統組態與環境變數設定
│   ├── deps.py         # 依賴注入 (如 Session, Current User)
│   ├── email_sender.py # SMTP 郵件發送服務
│   └── main.py         # FastAPI 應用程式進入點
├── frontend/           # 網站前台 UI (原生 Vanilla JS/CSS)
│   ├── css/            # Vanilla CSS 樣式表
│   ├── js/             # Vanilla JS (ESM) 邏輯模組 (包含 api.js, auth.js, toast.js 等)
│   ├── index.html      # 登入與首頁
│   ├── app.html        # 爬蟲任務管理主介面
│   ├── admin.html      # 系統管理員後台介面
│   └── set-password.html # 首次登入密碼設定介面
├── config/             # 存放全域設定檔 (config_global.yaml)
├── crawler/            # 爬蟲程式與 JOB 管理 (核心模組)
│   ├── __init__.py
│   ├── config_utils.py # 組態防呆驗證與全域設定合併工具
│   ├── core.py         # 爬蟲核心邏輯 (抓取網頁、解析 HTML、提取與過濾連結)
│   ├── manager.py      # JOB 管理 (任務分派、資料持久化、防呆安全鎖)
│   ├── models.py       # Crawler DB 資料庫模型
│   ├── exporter.py     # 報表匯出引擎 (CSV/JSON/ZIP 串流導出)
│   ├── notifier.py     # 任務狀態通知模組 (Email 發送)
│   └── utils.py        # 工具程式 (IP 解析、網域比對邏輯)
├── db/                 # 存放 SQLite 本地資料庫 (crawler.db, auth.db)
├── doc/                # 系統架構、Schema 與需求規格說明文件
│   ├── deploy_gcp_vm.md      # GCP 雲端部署指南
│   └── python_coding_style.md # Python 程式風格與開發規範
├── job/                # 存放個別任務 YAML 設定檔的安全目錄
├── log/                # 存放系統日誌與進程狀態
│   ├── pids/           # 存放運行中爬蟲子程序的 PID 檔案
│   └── crawler.log     # 系統主日誌檔
├── report/             # 外部連結分析報告之預設匯出目錄
├── scripts/            # 系統維運與自動化腳本
│   ├── job_sync.sh             # 跨環境任務備份與還原工具便利包
│   ├── manage_job_data.py      # 任務資料跨庫 JSONL 匯出匯入核心
│   └── migrate_sqlite_to_pg.py # PostgreSQL 平滑升級全自動遷移腳本
├── test/               # 一鍵式自動化整合測試套件 (基於 Pytest)
│   ├── test_server/    # 本機 Mock HTTP 測試伺服器
│   ├── test_api.py     # API 端點與 Web 後台 E2E 整合測試
│   └── test_cli.py     # CLI 爬蟲核心與調度 E2E 整合測試
└── tmp/                # 暫存檔與備份目錄
```

## 核心技術選型與設計理念

* **系統架構解耦 (CLI-First)**：
  爬蟲核心 (`crawler/`)、後台網頁系統 (`backend/`) 與前台使用者介面 (`frontend/`) 三者徹底解耦。在沒有啟動 Web 伺服器的情況下，依然能單獨透過 `cli.py` 命令列程式完整運行與管理爬蟲任務。各模組應遵守單一職責原則 (SRP) 開發。
* **資料庫實體分離與 PostgreSQL 支援**：
  系統維護兩個獨立的資料庫：爬蟲業務資料庫與帳號身分驗證資料庫。系統支援 **SQLite 與 PostgreSQL 雙引擎無縫切換**：在 SQLite 下啟用 WAL 與大容量快取防 I/O 阻塞；在 PostgreSQL 生產環境下，則動態偵測並自動啟用進階連線池 (`pool_size`, `max_overflow`) 與 `pool_pre_ping` 防斷線重連機制，徹底發揮高併發寫入潛力。
* **後端 Web API Server**：
  採用 **FastAPI** 作為後端框架，提供非同步、高效能的 RESTful API，並實作基於 HttpOnly Cookie 的安全 Session 管理與邀請制帳號機制。針對資料庫 I/O 等阻塞操作，嚴格規範採用同步 `def` 路由以交由底層執行緒池處理，保護主事件迴圈 (Event Loop Blocking 防禦)。
* **Web 與爬蟲程序的橋接設計 (Subprocess Spawning)**：
  Web 後端不直接在自身記憶體或執行緒中運行爬蟲。當使用者觸發「啟動」時，後端透過 `subprocess.Popen` 生成獨立的子程序運行爬蟲。後端透過 **Server-Sent Events (SSE)** 監聽資料庫狀態變更並主動推送進度至前台，取代傳統的無效輪詢，大幅降低伺服器負載並確保 Web API 的極高可用性。
* **前端 Web UI**：
  堅持採用**輕量原生技術棧 (Vanilla JS + ESM / Vanilla CSS)**，不引入 React、Vue 等框架與打包工具，大幅降低供應鏈風險與長期維護成本。實作了基於 `hashchange` 的無刷新 SPA 路由，並全面升級為 Server-Sent Events (SSE) 即時通訊架構，提供極致流暢的操作體驗。
* **網路連線與網頁解析**：
  採用 **HTTPX** 處理同步 HTTP/HTTPS 連線，並搭配 **BeautifulSoup 4** 進行 HTML 樹狀結構解析。針對外部連結的存活探測，引入 **`ThreadPoolExecutor`** 進行多執行緒並發處理，最大化診斷效能。
* **進階反爬蟲與隱匿機制 (Anti-Bot Bypass)**：
  爬蟲核心內建高擬真動態瀏覽器指紋與 HTTP 標頭輪替產生器，並支援隨機延遲抖動 (Jitter) 與 HTTP Proxy 環境變數優先覆寫，以最大程度隱藏自動化存取行為並繞過進階 WAF 防護。
* **任務級快取與頻寬節約 (Job-level Cache)**：
  於爬蟲核心調度層 (`manager.py`) 實作了記憶體快取。同一個爬蟲任務中若多次遇到相同的外部連結，系統會直接複用初次的 DNS 解析與 HTTP 存活探測結果，不僅大幅提升掃描速度，更能避免對外部目標網站造成 DDoS 風險與節約頻寬。
* **記憶體聚合與前端渲染保護 (In-Memory Aggregation & UI Protection)**：
  在處理「依外部網域統計」或「依來源頁面聚合」等一對多報表時，捨棄效能低落的資料庫 `GROUP_CONCAT`，改採 Python `dict/set` 在記憶體中進行 O(1) 極速去重。為防範前端 DOM 節點過載癱瘓，UI 預覽強制截斷子清單至 10 筆；完整匯出則繞過此限制，兼顧極速渲染與資料完整性。
* **精細化診斷分類 (Diagnostics Categorization)**：
  將內部失效連結智慧分類為 7 大樣態（伺服器異常、底層異常、連線逾時、資源遺失、其他異常、網頁截斷、權限不足），並提供動態統計卡片與關聯過濾，精準對應不同維運角色的修補需求。
* **自動化測試與環境隔離 (Pytest)**：
  專案全面採用 Pytest 構建測試套件，並區分為 API 端與 CLI 端。測試期間會動態切換環境變數建立專用的測試資料庫 (`test_auth.db`, `test_crawler.db`)，並實作自動清除快取與重設綱要的機制，確保 E2E (端到端) 測試的高度穩定與零污染。
* **任務狀態驅動**：
  系統具備高可靠度，所有的任務與網址佇列皆由資料庫狀態驅動 (`pending`, `running`, `paused`, `completed` 等)。攔截 `Ctrl+C` 訊號轉化為溫和暫停，支援中斷與斷點續傳。
* **來源精準追溯與防重**：
  佇列中明確記錄 `source_url`，能追蹤每一個外連的母來源頁面。系統亦具備防止重複記錄相同來源與目標連結的資料庫索引設計。
* **巨量資料串流匯出 (Streaming Export)**：
  針對高達數十萬筆的外部連結報表，系統實作了基於生成器 (Generator) 與 SQLite `.yield_per()` 的串流寫入機制。能將極大容量的 CSV 邊讀邊即時寫入 ZIP 壓縮檔或 HTTP Response 中串流回傳，徹底防範 OOM (Out of Memory) 崩潰風險。
* **系統維運與跨庫可攜性 (Ops & Data Portability)**：
  提供 `job_sync.sh` 任務備份工具與 `migrate_sqlite_to_pg.py` 全自動移轉腳本。底層採用 JSON Lines 串流讀寫技術，完美解決開發機 (SQLite) 到生產環境 (PostgreSQL) 的平滑升級與跨機房任務備份交接。
* **進階任務生命週期與報表 (Job Lifecycle & Diff Engine)**：
  除基礎的暫停與重置外，系統實作了**局部失敗重試**、**任務擁有權移交**、**一鍵複製任務配置**。更內建了強大的**歷史任務差異比對引擎 (Job Diff Engine)**，提供 IP 發生異動、狀態劣化、安全降級等六大維度的精準比對報表，為長期的網站資安健康度追蹤提供強大火力。

## 相關參考文件

為了保持文件聚焦，更詳細的系統細節已拆分至獨立文件：
* [系統需求規格書 (Requirements)](requirements.md)
* [命令列 (CLI) 操作指南](cli_usage.md)
* [API 路由清單](api_routes.md)
* [資料庫 Schema 說明 (db_schema.md)](db_schema.md)
* [GCP 部署指南 (deploy_gcp_vm.md)](deploy_gcp_vm.md)
* [Python 程式風格規範 (python_coding_style.md)](python_coding_style.md)
* [待辦清單與後續優化計畫](todo.md)
