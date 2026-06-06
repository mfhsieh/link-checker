# 外連檢查爬蟲 (External Link Checker) 架構與實作計畫

專案目標是建立一個能夠遍歷特定網域，並找出連向外部網域的網址，同時記錄其 IP 的爬蟲系統。系統需具備高擴充性，包含前後台網站、Job 管理，並支援中斷與恢復。

## 專案目錄架構

```text
ext-link-checker/
├── backend/            # [未來擴充] 網站後台 (FastAPI / Web API Server)
├── frontend/           # [未來擴充] 網站前台 UI (網頁管理介面)
├── config/             # 存放全域設定檔 (config_global.yaml)
├── crawler/            # 爬蟲程式與 JOB 管理 (核心模組)
│   ├── __init__.py
│   ├── core.py         # 爬蟲核心邏輯 (抓取網頁、解析 HTML、提取與過濾連結)
│   ├── manager.py      # JOB 管理 (任務分派、狀態機、中斷與斷點續傳機制)
│   ├── models.py       # 資料庫模型 (Job, CrawlQueue, ExternalLink)
│   └── utils.py        # 工具程式 (IP 解析、網域比對邏輯)
├── doc/                # 說明文件與規格
├── job/                # 存放個別爬蟲任務 (JOB) 的 YAML 設定檔
├── log/                # 存放爬蟲執行日誌 (crawler.log)
├── cli.py              # 命令列工具 (CLI)，讀取 yaml 設定檔並啟動獨立爬蟲
└── requirements.txt    # Python 依賴套件清單
```

## 核心設計理念與技術選型

1. **獨立運作與多租戶隔離**：
   - 採用 **SQLite** 作為輕量級的本地端資料庫 (`crawler.db`)。
   - 透過資料庫中的 `Job` 與 `CrawlQueue` 紀錄爬取狀態，支援中斷與斷點續傳 (`--resume <Job_ID>`)。
   - 內建 `user_id` 任務隔離機制，為未來網站前台的多使用者環境 (Multi-tenant) 打下基礎，確保使用者只能存取自己建立的任務。
2. **爬蟲核心與來源追蹤**：
   - 網路請求：使用非同步支援度高的 `httpx` 來發送請求。
   - 解析引擎：使用 `beautifulsoup4` 解析 HTML。除 `<a>` 標籤的 `href` 超連結外，一併自動提取 `<script>`、`<link>` (CSS 樣式表)、`<iframe>`、`<form>` (表單傳送目的地)、`<img>`、`<embed>`、`<object>` 等外部資源資產，防堵失效連結劫持與個資洩漏。
   - 來源追蹤：佇列設計包含了 `source_url`，能夠精準追溯每一個連結的「上一層來源網頁」，方便後續除錯或修復失效連結 (404)。
3. **網域過濾**：
   - `target_domains`：定義允許爬蟲深入遍歷的網域範圍 (相當於規格中的網域 A)。
   - `internal_domains`：定義被視為網站內部的網域，若解析出的目標連結不在這些網域中，即被判定為外部連結 (相當於規格中的網域 B)。
4. **外部連結紀錄與安全防護**：
   - 找到外部連結時，會利用 `socket.gethostbyname` 進行 IP 解析，並儲存於資料庫的 `ExternalLink` 資料表。
   - 支援雙連線 Client（正常 SSL 校驗 vs 豁免網域自簽憑證 `verify=False` 繞過）。
   - 支援 `max_depth` 與 `max_pages` 限制。

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
