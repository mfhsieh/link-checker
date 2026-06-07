# 外連檢查爬蟲 (External Link Checker) 架構說明

本文件旨在概述系統的目錄結構與核心設計理念。專案目標為建立一個能夠遍歷特定網域，找出外部網域連結並記錄其 IP 的高擴充性爬蟲系統。

## 專案目錄架構

```text
ext-link-checker/
├── .env                # 環境變數設定檔 (如資料庫路徑、SMTP 憑證等)
├── .gitignore          # git 追蹤忽略清單
├── .pylintrc           # Pylint 靜態程式碼分析設定檔
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
│   ├── js/             # Vanilla JS (ESM) 邏輯模組
│   ├── index.html      # 登入與首頁
│   ├── app.html        # 爬蟲任務管理主介面
│   ├── admin.html      # 系統管理員後台介面
│   └── set-password.html # 首次登入密碼設定介面
├── config/             # 存放全域設定檔 (config_global.yaml)
├── crawler/            # 爬蟲程式與 JOB 管理 (核心模組)
│   ├── __init__.py
│   ├── core.py         # 爬蟲核心邏輯 (抓取網頁、解析 HTML、提取與過濾連結)
│   ├── manager.py      # JOB 管理 (任務分派、資料持久化、防呆安全鎖)
│   ├── models.py       # Crawler DB 資料庫模型
│   └── utils.py        # 工具程式 (IP 解析、網域比對邏輯)
├── db/                 # 存放 SQLite 本地資料庫 (crawler.db, auth.db)
├── doc/                # 系統架構、Schema 與需求規格說明文件
├── job/                # 存放個別任務 YAML 設定檔的安全目錄
├── log/                # 存放系統日誌 (crawler.log)
├── report/             # 外部連結分析報告之預設匯出目錄
├── test/               # 一鍵式自動化整合測試套件
│   ├── test_server/    # 本機 Mock HTTP 測試伺服器
│   └── run_test.py     # 測試套件主執行程式
└── tmp/                # 暫存檔與備份目錄
```

## 核心技術選型與設計理念

* **系統架構解耦 (CLI-First)**：
  爬蟲核心 (`crawler/`) 與後台網頁系統 (`backend/`) 徹底解耦。在沒有啟動 Web 伺服器的情況下，依然能單獨透過 `cli.py` 命令列程式完整運行與管理爬蟲任務。
* **資料庫實體分離**：
  系統維護兩個獨立的資料庫：`crawler.db` (爬蟲業務資料) 與 `auth.db` (帳號與身分驗證資料)，兩者不共用連線池與 Schema，確保業務邏輯邊界清晰。針對高頻寫入的 `crawler.db`，啟用了 SQLite 的 **WAL (Write-Ahead Logging)** 與 **NORMAL** 同步模式以防 I/O 阻塞。
* **後端 Web API Server**：
  採用 **FastAPI** 作為後端框架，提供非同步、高效能的 RESTful API，並實作基於 HttpOnly Cookie 的安全 Session 管理與邀請制帳號機制。內建例外攔截器以支援 SPA 前端路由的無縫重導向 (404 Fallback)。
* **前端 Web UI**：
  堅持採用**輕量原生技術棧 (Vanilla JS + ESM / Vanilla CSS)**，不引入 React、Vue 等框架與打包工具，大幅降低供應鏈風險與長期維護成本。
* **網路連線與網頁解析**：
  採用 **HTTPX** 處理同步 HTTP/HTTPS 連線，並搭配 **BeautifulSoup 4** 進行 HTML 樹狀結構解析。針對外部連結的存活探測，引入 **`ThreadPoolExecutor`** 進行多執行緒並發處理，最大化診斷效能。
* **任務狀態驅動**：
  系統具備高可靠度，所有的任務與網址佇列皆由資料庫狀態驅動 (`pending`, `running`, `paused`, `completed` 等)。攔截 `Ctrl+C` 訊號轉化為溫和暫停，支援中斷與斷點續傳。
* **來源精準追溯與防重**：
  佇列中明確記錄 `source_url`，能追蹤每一個外連的母來源頁面。系統亦具備防止重複記錄相同來源與目標連結的資料庫索引設計。

## 相關參考文件

為了保持文件聚焦，更詳細的系統細節已拆分至獨立文件：
* [系統需求規格書 (Requirements)](requirements.md)
* [命令列 (CLI) 操作指南](cli_usage.md)
* [API 路由清單](api_routes.md)
* [資料庫 Schema 說明 (db_schema.md)](db_schema.md)
* [待辦清單與後續優化計畫](todo.md)
