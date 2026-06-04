# 外連檢查爬蟲 (External Link Checker) 架構與實作計畫

專案目標是建立一個能夠遍歷特定網域，並找出連向外部網域的網址，同時記錄其 IP 的爬蟲系統。系統需具備高擴充性，包含前後台網站、Job 管理，並支援中斷與恢復。

## 專案目錄架構

```text
ext-link-checker/
├── backend/            # [未來擴充] 網站後台 (FastAPI / Web API Server)
├── frontend/           # [未來擴充] 網站前台 UI (網頁管理介面)
├── crawler/            # 爬蟲程式與 JOB 管理 (核心模組)
│   ├── __init__.py
│   ├── core.py         # 爬蟲核心邏輯 (抓取網頁、解析 HTML、提取與過濾連結)
│   ├── manager.py      # JOB 管理 (任務分派、狀態機、中斷與斷點續傳機制)
│   ├── models.py       # 資料庫模型 (Job, CrawlQueue, ExternalLink)
│   └── utils.py        # 工具程式 (IP 解析、網域比對邏輯)
├── doc/                # 說明文件與規格
├── cli.py              # 命令列工具 (CLI)，讀取 config.yaml 並啟動獨立爬蟲
├── config.yaml         # 設定檔 (設定起始網址、允許爬取網域與內部網域)
└── requirements.txt    # Python 依賴套件清單
```

## 核心設計理念與技術選型

1. **獨立運作與斷點續傳**：
   - 採用 **SQLite** 作為輕量級的本地端資料庫 (`crawler.db`)。
   - 透過資料庫中的 `Job` 與 `CrawlQueue` 紀錄爬取狀態，當程式中斷時 (如 `Ctrl+C`)，爬蟲任務狀態會保持，下次啟動時可透過 `--resume <Job_ID>` 從尚未爬取的 Queue 繼續執行。
2. **爬蟲核心**：
   - 網路請求：使用非同步支援度高的 `httpx` 來發送請求。
   - 解析引擎：使用 `beautifulsoup4` 解析 HTML 找出所有 `<a>` 標籤的 `href`。
3. **網域過濾**：
   - `target_domains`：定義允許爬蟲深入遍歷的網域範圍 (相當於規格中的網域 A)。
   - `internal_domains`：定義被視為網站內部的網域，若解析出的目標連結不在這些網域中，即被判定為外部連結 (相當於規格中的網域 B)。
4. **外部連結紀錄**：
   - 找到外部連結時，會利用 `socket.gethostbyname` 進行 IP 解析，並儲存於資料庫的 `ExternalLink` 資料表。

## CLI 操作指南

關於如何建立、啟動與恢復爬蟲任務的詳細指令說明，請參閱獨立的說明文件：
👉 **[命令列 (CLI) 操作指南](file:///home/mfhsieh/projects/python/ext-link-checker/doc/cli_usage.md)**


## 開發階段規劃

- **✅ 第一階段：核心爬蟲開發 (已完成)**
  - 實作單一網址的獨立爬蟲核心。
  - 建立 SQLite 狀態與 Queue 管理，支援斷點續傳。
  - 提供 CLI 指令操作與 YAML 設定檔讀取。
- **📝 第二階段：網站後台 (API Server)**
  - 建立 FastAPI 伺服器，將 Job 的建立、暫停、恢復封裝成 RESTful API。
  - 提供 API 檢視已找到的外部連結與 IP。
- **📝 第三階段：網站前台 (Web UI)**
  - 建立網頁使用者介面 (Frontend)。
  - 提供視覺化的介面讓使用者可以交辦 JOB，以及觀看各個 JOB 的進度與抓取結果。
- **📝 第四階段：進階優化**
  - 將爬蟲改為非同步 (AsyncIO) 提升爬取效率。
  - 支援分散式或定期 JOB 執行排程。
