# 外部連結檢查系統 (External Link Checker)

本專案是一個具備命令列介面 (CLI) 與現代化網頁介面 (Web UI) 的外部連結檢查系統。使用者可以透過介面管理爬蟲任務，掃描指定網域的外部連結，並產生詳細的報告。

## 系統需求

- Python 3.12 或以上版本
- （建議）使用虛擬環境 (Virtual Environment) 進行安裝

## 安裝

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

# Session 設定
SECRET_KEY="your-strong-random-secret-key"  # 生產環境必填

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
python cli.py --serve
```

伺服器將預設在 `http://0.0.0.0:8000` 啟動，請開啟瀏覽器並訪問。

## 命令列 (CLI) 使用方式

除了 Web 介面，您依然可以直接使用 CLI 操作爬蟲核心。

```bash
# 執行單次爬蟲任務（讀取 YAML 設定檔）
python cli.py -c job/my_job_config.yaml

# 列出所有任務
python cli.py --list-jobs

# 匯出任務報告為 CSV
python cli.py --export <JOB_ID> --output report.csv

# 查詢可用的參數選項
python cli.py --help
```
