# 外部連結檢查系統 (External Link Checker)

本專案是一個具備命令列介面 (CLI) 與現代化網頁介面 (Web UI) 的外部連結檢查工具。系統主要用於自動巡覽特定網站，找出連向外部（非信任網域）的連結，並檢查其有效性與傳輸安全性，以協助網站管理員維護連結品質並降低潛在的資安風險。

## 主要功能

- **雙介面操作**：支援現代化的 Web 管理介面與純命令列 (CLI) 獨立執行模式，適應不同維運場景。
- **精準爬行控制**：基於廣度優先搜尋 (BFS)，支援設定最大爬行深度、抓取頁數限制、請求延遲與錯誤重試機制。
- **智慧過濾與探測**：內建 MIME 類型過濾、副檔名忽略與 Regex 路徑排除，並支援繞過特定防爬蟲機制的降級探測。
- **安全性檢查**：自動解析外部連結的 IP 位址，內建 SSRF 防禦，並主動標記非 HTTPS 的明文傳輸連結。
- **內部連結診斷**：自動分類 6 大內部失效樣態 (404, 5xx, 連線逾時, 權限不足等)，並支援來源網頁聚合視角，協助快速修補。
- **極致前端效能與資安**：全站採 Vanilla JS (ESM) 原生開發，零第三方框架依賴，並 100% 以 `document.createElement` 進行 DOM 渲染，徹底根絕 XSS 風險。
- **高併發與記憶體保護**：後端採用 O(1) 記憶體去重聚合與 ZIP 串流匯出，前端實作長清單自適應截斷，無懼百萬級資料量。
- **多維度報表匯出**：支援將掃描結果依外連目標、來源頁面或外部網域進行去重聚合，並可匯出為 CSV 或 JSON 格式。

## 系統需求

- Python 3.12 或以上版本
- （建議）使用虛擬環境 (Virtual Environment) 進行安裝

## 快速開始

### 1. 安裝依賴套件

```bash
# 建立虛擬環境
python3 -m venv .venv

# 啟動虛擬環境
source .venv/bin/activate

# 安裝依賴套件
pip install -r requirements.txt
```

## 設定環境變數 (.env 或全域環境)

啟動 Web 服務前，建議設定以下環境變數（可用於覆寫 `backend/config.py` 的預設值）：

```env
# 應用程式設定
APP_NAME="外部連結檢查系統"
DEBUG="false"

# 資料庫連線
AUTH_DB_URL="sqlite:///db/auth.db"
CRAWLER_DB_URL="sqlite:///db/crawler.db"

# SMTP 設定 (邀請與通知郵件)
SMTP_HOST="smtp.example.com"
SMTP_PORT="587"
SMTP_USERNAME="your-smtp-username"
SMTP_PASSWORD="your-smtp-password"
SMTP_FROM_NAME="外部連結檢查系統"
SMTP_FROM_EMAIL="noreply@example.com"
SMTP_USE_TLS="true"
SMTP_CONSOLE_MODE="false"  # 開發階段可設為 true，將郵件內容輸出至終端機而不實際寄送
```

## 系統管理員初始化

系統採邀請制，首次使用需手動建立第一組管理員帳號：

```bash
python cli.py --create-admin admin@example.com
```

建立完成後，終端機會顯示一組系統產生的高強度隨機密碼。請使用該密碼首次登入 Web 介面，並依照系統提示設定您的專屬密碼。

## 啟動 Web 服務

使用 CLI 指令啟動內建的 FastAPI + Uvicorn 伺服器：

```bash
python cli.py --serve  # 若為開發環境，可加上 --reload 啟用熱重載
```

伺服器將預設在 `http://0.0.0.0:8000` 啟動，請開啟瀏覽器並訪問。

## 命令列 (CLI) 使用方式

除了 Web 介面，您依然可以直接使用 CLI 操作爬蟲核心。

```bash
# 執行單次爬蟲任務（讀取 YAML 設定檔）
python cli.py -c y_job_config.yaml

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
* **[API 路由清單](doc/api_routes.md)**：後端 RESTful API 規格說明。
* **[系統需求規格書](doc/requirements.md)**：詳細的功能需求與業務邏輯邊界。
* **資料庫 Schema**：[Crawler DB](doc/db_schema_crawler.md) / [Auth DB](doc/db_schema_auth.md)
* **[待辦清單與後續規劃](doc/todo.md)**
