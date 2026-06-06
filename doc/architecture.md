# 外連檢查爬蟲 (External Link Checker) 架構與實作計畫

專案目標是建立一個能夠遍歷特定網域，並找出連向外部網域的網址，同時記錄其 IP 的爬蟲系統。系統需具備高擴充性，包含前後台網站、Job 管理，並支援中斷與恢復。

## 專案目錄架構

```text
ext-link-checker/
├── .gitignore
├── pyrefly.toml        # 靜態分析與開發環境配置
├── cli.py              # 命令列工具 (CLI)，啟動獨立爬蟲任務
├── requirements.txt    # Python 依賴套件清單
├── backend/            # [未來擴充] 網站後台 (FastAPI / Web API Server)
├── frontend/           # [未來擴充] 網站前台 UI (網頁管理介面)
├── config/             # 存放全域設定檔 (config_global.yaml)
├── crawler/            # 爬蟲程式與 JOB 管理 (核心模組)
│   ├── __init__.py
│   ├── core.py         # 爬蟲核心邏輯 (抓取網頁、解析 HTML、提取與過濾連結)
│   ├── manager.py      # JOB 管理 (任務分派、資料持久化、防呆安全鎖)
│   ├── models.py       # 資料庫模型 (Job, CrawlQueue, ExternalLink)
│   └── utils.py        # 工具程式 (IP 解析、網域比對邏輯)
├── db/                 # 存放 SQLite 本地資料庫 (crawler.db)
├── doc/                # 說明文件與需求規格書
├── job/                # 存放個別任務 YAML 設定檔的安全目錄
├── log/                # 存放系統日誌 (crawler.log)
├── report/             # 外部連結分析報告之預設匯出目錄
└── test/               # 一鍵式自動化整合測試套件
    ├── test_server/    # 本機 Mock HTTP 測試伺服器
    └── run_test.py     # 測試套件主執行程式
```

## 核心技術選型與設計理念

本系統之詳細系統功能與資安規格需求，請參閱：
👉 **[系統需求規格書 (Requirements)](file:///home/mfhsieh/projects/python/ext-link-checker/doc/requirements.md)**

以下說明本系統之核心技術選型與設計理念：

* **核心技術選型**：
  * **資料持久化**：採用 **SQLite** 作為輕量級的本地端資料庫，降低系統維護成本。搭配 **SQLAlchemy ORM** 進行資料操作與關聯宣告。
  * **HTTP 連線客戶端**：採用 **HTTPX** 處理同步 HTTP/HTTPS 連線，並可靈活配置代理伺服器與 SSL 自簽豁免。
  * **HTML 解析引擎**：採用 **BeautifulSoup 4** 解析 HTML 網頁樹狀結構，用以擷取超連結與各類資源資產。
  * **並發探測機制**：採用 **`ThreadPoolExecutor` (執行緒池)** 對外部連結進行多工並發存活探測，以防同步阻塞並最大化外連診斷效能。
* **高階設計理念**：
  * **CLI-First 與低耦合**：爬蟲核心與任務管理器與後台網頁系統徹底解耦，具備高度獨立性，可單獨以命令列程式獨立運行與管理。
  * **任務狀態驅動與中斷恢復**：藉由資料庫中的 Job 與 CrawlQueue 狀態，支援在執行中斷後恢復未完成之進度，達成高可靠度。
  * **多使用者隔離設計**：在資料持久層內建 `user_id` 任務隔離機制，為未來 Web 多租戶環境預作規劃。
  * **來源精準追溯**：佇列中記錄 `source_url`，能精準追蹤每一個外連的母來源頁面，便於資安與損毀連結修復。
  * **資料庫併發與 I/O 優化**：啟用 SQLite 的 **WAL (Write-Ahead Logging)** 預寫日誌模式與 **NORMAL** 同步模式，以防高頻率更新佇列狀態與寫入結果時造成的 I/O 阻塞或鎖定衝突。

## CLI 操作指南

關於如何建立、啟動與恢復爬蟲任務的詳細指令說明，請參閱獨立的說明文件：
👉 **[命令列 (CLI) 操作指南](file:///home/mfhsieh/projects/python/ext-link-checker/doc/cli_usage.md)**


## 開發階段規劃

- **✅ 第一階段：核心爬蟲與任務管理 (已完成)**
  - 實作單一網址的獨立爬蟲與任務管理 CLI 工具。
  - 建立 SQLite 佇列狀態管理與 Job 生命週期控制（暫停、重設、刪除與斷點續傳）。
  - 提供去重聚合導出（`--group` 與 `--filter unapproved/broken/dead` 支援），以及 JSON/CSV 檔案與 stdout 的 JSON 格式輸出。
  - 整合多標籤外部資源掃描（script, css, iframe, form action, img, object, embed），防止 Broken Link Hijacking 供應鏈威脅。
  - 提供安全防護：自簽憑證豁免通道（雙 Client）、環境變數機密保護、路徑安全防禦、以及爬行深度 (`max_depth`) 與抓取頁面數量 (`max_pages`) 的安全限制。
  - 附帶一鍵式自動化整合測試套件 (`test/run_test.py`)，完美支援 CI/CD 開發驗證。
- **📝 第二階段：網站後台 (API Server)**
  - 建立 FastAPI 伺服器，將 Job 的建立、暫停、恢復封裝成 RESTful API。
  - 提供 API 檢視已找到的外部連結與 IP。
- **📝 第三階段：網站前台 (Web UI)**
  - 建立網頁使用者介面 (Frontend)。
  - 提供視覺化的介面讓使用者可以交辦 JOB，以及觀看各個 JOB 的進度與抓取結果。
- **📝 第四階段：進階優化**
  - 將爬蟲改為非同步 (AsyncIO) 提升爬取效率。
  - 支援分散式或定期 JOB 執行排程。
