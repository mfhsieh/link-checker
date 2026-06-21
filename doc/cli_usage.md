# 命令列 (CLI) 操作指南

網站連結檢查系統可以透過命令列直接執行與管理，完全不依賴網站後台。請確認已進入虛擬環境，並參考以下說明。

---

## 1. 完整的命令列參數 (Arguments)

執行 `python cli.py` 時，系統支援以下命令列參數：

### 群組 1：任務生命週期與調度 (Job Lifecycle & Scheduling)

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--config` | `-c` | 字串 | **[建立新任務時必填]** 指定個別任務的 YAML 設定檔路徑。具備**路徑智慧自動補齊功能**（若未指定 `job/` 前綴且不含相對/絕對路徑，自動在前綴補上 `job/`）。 | 無 |
| `--user-id` | `-u` | 字串 | (選填) 綁定任務的擁有者 ID 或作為查詢過濾條件 (多使用者隔離用)。 | 無 |
| `--resume` | `-r` | 字串 | **[恢復任務時必填]** 指定要恢復執行的任務 Job ID (UUID 格式)。 | 無 |
| `--force` | `-f` | 旗標 | (選填) 搭配 `--resume` 使用，當任務狀態卡在 `running` 或因意外中斷被標記為 `error` 時，強制接續執行任務。 | 無 |
| `--pause` | `-p` | 字串 | 暫停指定任務 (僅在任務狀態為 `running` 時生效)。 | 無 |
| `--delete` | `-d` | 字串 | 刪除指定任務，並清理其所有內部網頁 (佇列) 與外部連結記錄。 | 無 |
| `--reset` | `-R` | 字串 | 重設指定任務，清除已探索的外部連結記錄，並將內部網頁的狀態歸零。 | 無 |
| `--retry-failed` | `-T` | 字串 | 局部重試指定任務中爬取失敗的內部網頁與包含無效外連的網頁。 | 無 |

### 群組 2：報表檢視與結果匯出 (Reporting & Exporting)

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--list-jobs` | *(無)* | 旗標 | 印出系統中所有的爬蟲任務與狀態列表。 | 無 |
| `--report` | *(無)* | 字串 | 指定任務 ID，顯示該任務的詳細進度與統計報表。 | 無 |
| `--export-external` | *(無)* | 字串 | 指定任務 ID，將該任務尋獲的外部連結匯出 (預設為 CSV，若帶有 `--json` 則為 JSON)。 | 無 |
| `--export-internal` | *(無)* | 字串 | 指定任務 ID，將該任務的內部網頁爬取紀錄匯出 (預設為 CSV，若帶有 `--json` 則為 JSON)。 | 無 |
| `--export-full` | *(無)*| 字串 | 指定任務 ID，匯出該任務的完整報表 (ZIP 壓縮檔，含內部爬取診斷紀錄與外部連結清單)。亦可搭配 `--output` 自訂檔名。 | 無 |
| `--output` | *(無)* | 字串 | (選填) 搭配匯出指令使用，自訂輸出路徑。 | 依格式而定，如 `report/<JOB_ID>.csv` 或 `.zip` |
| `--filter` | *(無)* | 字串 | (選填) 搭配 `--export-external` 使用，篩選匯出內容 (支援 `dead`, `broken`, `not_found`, `server_error`, `insecure` 等多種狀態，詳見下方提示)。 | 無 |
| `--exclude`| *(無)* | 字串 | (選填) 搭配 `--export-external` 使用，排除指定的目標網域（多個以逗號分隔）。 | 無 |
| `--group-by`| *(無)* | 字串 | (選填) 搭配 `--export-external` 使用，聚合模式：`target` (依外連)、`source` (依來源頁面)、`domain` (依網域)。 | `none` |
| `--json` | *(無)* | 旗標 | (選填) 啟用 JSON 格式支援。支援 `--list-jobs` 與 `--report` 的 stdout 輸出，以及各項匯出指令的 JSON 檔案導出。 | 無 |

### 群組 3：全域設定與系統維運 (Global & System Admin)

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--help` | `-h` | 旗標 | 顯示此說明訊息並離開。 | 無 |
| `--global-config`| `-g` | 字串 | (選填) 指定全域設定檔的路徑。具備**路徑智慧補齊功能**（自動補齊 `config/` 前綴）。 | 優先讀取 `.env` 內之 `GLOBAL_CONFIG_PATH` |
| `--serve` | *(無)* | 旗標 | 啟動 Web 後端伺服器 (FastAPI / Uvicorn)。 | 無 |
| `--reload` | *(無)* | 旗標 | (選填) 搭配 `--serve` 使用，啟用 Uvicorn 的開發模式熱重載。 | 無 |
| `--create-admin` | *(無)* | 字串 | 建立或更新系統管理員帳號。只需傳入 `EMAIL`，系統將自動產生並印出一次性臨時密碼。 | 無 |
| `--api-spawn` | *(無)* | 字串 | **[內部指令]** 專供 Web 後端 API 啟動爬蟲子程序使用，請勿手動呼叫。需傳入 Job ID。 | 無 |

> **💡 提示：** 
> * `--config` 與 `--resume` 為互斥概念。如果是啟動新爬蟲，請使用 `--config`；如果是中斷後繼續，請使用 `--resume`。若兩者皆未輸入，系統將會印出幫助說明。
> * **路徑自動補齊**：使用 `-c` 參數啟動時，若指定設定檔在 `job/` 底下，您可以直接簡寫為 `python cli.py -c my_task.yaml`（程式會自動補齊路徑並在 `job/` 目錄中搜尋）。
> * 爬蟲執行過程中的日誌會依據全域設定，同時輸出至畫面並備份至 `log/crawler.log`。

---

## 1.5 全域設定檔說明 (config_global.yaml)

系統使用 `config/config_global.yaml` 作為預設的全域設定檔，用以定義爬蟲引擎的安全上下限閥值與預設行為（資料庫連線與系統日誌已全面改由 `.env` 環境變數控管）。

為保持文件的單一來源 (Single Source of Truth) 與易讀性，關於各項參數的詳細定義、預設值與安全防護邏輯，請參考以下內容：

* **詳細參數說明與運作機制**：請參閱 [`crawler_parameters.md`](crawler_parameters.md)
* **全域設定檔完整範本**：請參閱 [`../config/config_global.yaml.example`](../config/config_global.yaml.example)

---

## 2. 建立並啟動新爬蟲任務

爬蟲需要一個任務設定檔來定義起始網址 (`start_url`)、允許深入的目標網域與信任網域。基於專案規範，建議將這些個別設定檔放置於 `job/` 目錄中。

### 步驟 1：建立任務設定檔 (例如 `job/my_task.yaml`)

為保持文件的單一來源 (Single Source of Truth)，我們已準備了一份包含所有核心邏輯與可選覆寫參數的完整設定檔範本。請直接參考並複製該範本來建立您的專屬任務設定檔：

* **任務設定檔完整範本**：請參閱 [`../job/config_job.yaml.example`](../job/config_job.yaml.example)

> [!WARNING]
> 在 `crawler` 區塊中自訂的數值（如 `delay`、`timeout` 與 `retries`），必須落在全域設定檔 (`config/config_global.yaml`) 所定義的上下限內。若超出範圍，系統將印出警告並強制套用全域的安全限制。

### 步驟 2：利用環境變數覆寫機密配置（資安防護）

為了防範機密憑證（例如 Proxy 等）明文寫入 YAML 檔中造成安全洩漏，系統優先支援自環境變數載入與覆寫配置。您可以在執行前設置：
```bash
# 設定外部代理伺服器
export CRAWLER_PROXY_URL="http://user:password@proxy.example.com:8080"

# 增補 SSL 自簽憑證豁免網域（以逗號分隔）
export CRAWLER_SSL_EXEMPT_DOMAINS="exempt1.com,exempt2.org"
```

### 步驟 3：執行 CLI 指令

```bash
# 使用預設的 config/config_global.yaml
python cli.py -c job/my_task.yaml

# (選填) 若有客製化的全域設定檔，可加上 -g 指定
python cli.py -g my_custom_global.yaml -c job/my_task.yaml

# (選填) 綁定任務擁有者，以便支援多使用者隔離
python cli.py -c job/my_task.yaml --user-id "user-alpha-123"
```

系統啟動後，終端機會顯示類似如下的訊息，告知您被分配的 Job ID：
```text
INFO - 準備建立新任務...
INFO - 成功建立任務 5eebf2ac-250f-463d-a4cc-98a64d50b5fc。爬蟲啟動中...
```

---

## 3. 恢復中斷的爬蟲任務 (斷點續傳)

如果爬蟲在執行中途遇到網路中斷、被強制關閉 (例如按下 `Ctrl+C`) 或是發生預期外的崩潰，所有的爬取狀態 (Pending, Completed, Failed) 都已經妥善保存在 SQLite 資料庫中。

若要恢復執行，請使用 `--resume` (或 `-r`) 參數並帶上任務的 Job ID：

```bash
# 恢復已暫停的爬蟲任務
python cli.py -r 123e4567-e89b-12d3-a456-426614174000
```

> **⚠️ 競爭危害與強制接管：** 
> 為了避免多個終端機同時執行相同的任務，系統在恢復任務時會檢查狀態。若狀態為 `running`，系統會拒絕執行。若您確定前一次的爬蟲程序已經因為斷電或強制終止而意外死亡，您可以加上 `-f` 或 `--force` 參數來強制接管該任務：
> ```bash
> python cli.py -r 123e4567-e89b-12d3-a456-426614174000 -f
> ```

> [!NOTE]
> 系統會自動從資料庫抓出該任務原先設定的 `start_url`、`target_domains` 等資訊，並從狀態為 `pending` 的佇列接續處理。

---

## 4. 任務生命週期管理 (暫停、重設、刪除)

我們提供了命令式的生命週期管理指令，讓您即使在前台沒有運行爬蟲的情況下，依然能控制任務狀態與清理資料庫：

### 暫停執行中的任務
若您需要從外部終端機主動讓執行中的爬蟲暫停：
```bash
python cli.py --pause <JOB_ID>
```
> **💡 協同暫停機制：** 前台運行的爬蟲程序每爬取一個網頁前，都會自動確認資料庫中的任務狀態。一旦偵測到狀態被改為 `paused`，它便會優雅地處理完當前請求後自動退出。

### 重設任務 (重新爬取)
若想在不變更任務 Job ID 的前提下，將任務退回初始狀態並清除所有已探索到的外部連結：
```bash
python cli.py --reset <JOB_ID>
```
這會清除該 Job 在資料庫中的所有外部連結記錄，並將內部網頁的佇列狀態歸零，回到僅剩 `start_url` 處於 `pending` 的狀態。

### 局部重試失敗項目
若任務執行完畢後，有部分內部網頁因暫時性錯誤而爬取失敗，或者產生了包含無效外連的網頁，您可以針對這些失敗的項目進行局部重試：
```bash
python cli.py --retry-failed <JOB_ID>
```
這會將所有爬取失敗的內部網頁與包含無效外連的網頁重新標記為 `pending`。設定完成後，您需要再利用 `--resume` 指令來啟動爬蟲接續處理這些網頁。

### 刪除任務 (清理資料)
若測試完畢或任務已過期，為了防堵 SQLite 資料庫檔案無限制膨脹，您可以將任務徹底刪除：
```bash
python cli.py --delete <JOB_ID>
```
此操作會利用資料庫的級聯刪除機制 (Cascade)，將該 Job 的所有內部網頁 (`crawl_queue`) 佇列與外部連結 (`external_links`) 診斷結果一次清理乾淨。

---

## 5. 查詢進度報表與結果匯出

我們提供了進度檢視與資料匯出功能，讓您可以隨時掌握爬蟲狀況與下載最終成果：

### 列出所有任務
```bash
python cli.py --list-jobs

# (選填) 僅列出特定使用者的任務
python cli.py --list-jobs --user-id "user-alpha-123"
```
此指令會印出歷史建立過的所有任務，包含狀態 (如 `completed`, `paused`, `running`) 以及它們的起始網址。

### 查詢特定任務的進度報表
取得任務 ID 後，您可以檢視更詳細的統計：
```bash
python cli.py --report <JOB_ID>
```
這會為您計算出目前內部網頁中**已完成、等待中、失敗的數量**，以及已經找到的**外部連結總數**。

### 匯出結果 (CSV / JSON 與聚合去重)
如果您希望把內部診斷結果或探索到的外部連結整理下來：
```bash
# 預設會匯出為 CSV，路徑為 report/<JOB_ID>.csv
python cli.py --export-external <JOB_ID>

# 單獨匯出內部網頁診斷紀錄（爬蟲走過的內部頁面與健康狀態）
python cli.py --export-internal <JOB_ID>

# 您也可以加上 --output 自訂路徑
python cli.py --export-external <JOB_ID> --output ./my_result.csv

# 僅匯出「DNS 解析失敗」的無效外連連結
python cli.py --export-external <JOB_ID> --filter dead --output ./dead_links.csv

# 匯出所有損毀外連 (包含 DNS 解析失敗，以及 HTTP 狀態碼 >= 400 比如 404/500)
python cli.py --export-external <JOB_ID> --filter broken

# 匯出所有非 HTTPS 的外連 (資安稽核用)
python cli.py --export-external <JOB_ID> --filter insecure

# 匯出為 JSON 格式 (預設會輸出到 report/<JOB_ID>.json)
python cli.py --export-external <JOB_ID> --json

# 依外連目標聚合導出 (同個外連在不同頁面出現時會被合併)
python cli.py --export-external <JOB_ID> --group-by target

# 依自家網頁修補視角導出 (顯示我的 A 網頁底下壞了哪些外連)
python cli.py --export-external <JOB_ID> --group-by source

# 依外部網域統計導出 (檢視對外部服務的依賴分佈與次數)
python cli.py --export-external <JOB_ID> --group-by domain

# 匯出完整報表大禮包 (自動打包為 ZIP 檔，內含外部連結與內部連結診斷 CSV)
python cli.py --export-full <JOB_ID>

# 匯出完整報表並自訂 ZIP 檔名
python cli.py --export-full <JOB_ID> --output custom_report.zip

# 匯出結果並排除特定網域 (例如不想看社群網站的外連)
python cli.py --export-external <JOB_ID> --exclude "facebook.com,youtube.com,twitter.com"
```

### 進階篩選條件 (`--filter`)

當使用 `--export-external` 匯出時，您可以搭配 `--filter` 來精確篩選要匯出的連結狀態。
> [!NOTE]
> 目前 CLI 的 `--filter` 參數僅專門為 `--export-external` 設計。若您使用 `--export-internal` 匯出內部紀錄時將不受此過濾參數影響，系統會無條件匯出所有內部頁面的完整爬取結果。

以下為系統支援的狀態字典與其詳細判定邏輯：

* `dead` (亦可使用 `dns_failed`)：特指 **「DNS 解析失敗 (IP 位址為空) 的無效外部連結」**（例如網域已過期或網址輸入錯誤）。
* `broken`：廣義的失效連結集合，涵蓋 `not_found`, `server_error`, `connection_error`, `other_error` 等四大類異常。（注意：**不包含** `dead`，也**不包含** `blocked`）。
* `not_found`：精確篩選 **「資源遺失 (404, 410)」** 的連結。
* `server_error`：精確篩選 **「伺服器異常 (500~599)」** 的連結。
* `connection_error`：精確篩選 **「底層連線異常 (DNS 成功但無 HTTP 狀態碼，例如連線逾時、憑證無效、連線被拒等)」** 的連結。
* `other_error`：精確篩選 **「其他未歸類的 HTTP 異常 (如 400, 408 或 >=600)」** 的連結。
* `blocked`：特指 **「遭目標網站防火牆 (WAF) 阻擋或權限不足 (401, 403, 405, 406, 429)」**，這類連結多半仍存活，只是爬蟲身分被阻擋，不被系統視為 Broken。
* `insecure`：特指 **「使用明文 HTTP 傳輸的非安全外部連結」**（資安稽核重點）。
* `healthy`：正常存活連結 (有 IP 解析成功，且 HTTP 狀態碼 < 400)。
* `all`：不進行篩選，匯出所有結果。

---

## 6. 後端伺服器與管理員帳號

雖然本系統可以純 CLI 獨立運行，但若您需要使用網頁前台或後台管理介面，可以透過 CLI 快速啟動 FastAPI 伺服器並設定初始權限。

### 建立初始管理員帳號
在一個封閉的邀請制系統中，您需要透過 CLI 建立系統的第一位管理員：
```bash
python cli.py --create-admin "admin@example.com"
```
> **⚠️ 提示：** 系統將自動產生一個高強度的一次性隨機密碼，並在終端機中印出。請妥善保管此密碼。後續的其他管理員可直接由網頁後台邀請與設定，不需要再次使用此指令。

### 啟動 Web 伺服器
若要啟動後端 API 伺服器以供前端介面連線：
```bash
python cli.py --serve  # 若為開發環境，可加上 --reload 啟用熱重載
```
伺服器啟動後，將預設監聽 `0.0.0.0:8000`。您可透過終端機的標準輸出檢視存取紀錄，按下 `Ctrl+C` 即可安全關閉伺服器。

---

## 7. 跨環境任務備份與還原 (Job Sync)

系統提供了一支便利的 Shell Script (`scripts/job_sync.sh`)，協助您在不同伺服器或不同資料庫（如 SQLite 與 PostgreSQL）之間，安全地轉移與備份爬蟲任務資料（包含設定、內部網頁佇列與外部連結結果）。

### 備份任務（匯出）
```bash
./scripts/job_sync.sh export <JOB_ID> <存放備份的資料夾路徑或ZIP檔名>

# 範例：將任務打包為 ZIP 壓縮檔
./scripts/job_sync.sh export 5eebf2ac-250f-463d-a4cc-98a64d50b5fc ./my_job_backup.zip
```

### 還原任務（匯入）
找出要接手該任務的目標使用者 ID，然後執行：
```bash
./scripts/job_sync.sh import <存放備份的資料夾路徑或ZIP檔名> <目標使用者的_USER_ID>

# 範例：從 ZIP 壓縮檔還原，並指派給指定使用者
./scripts/job_sync.sh import ./my_job_backup.zip user-uuid-1234
```

---

## 8. 全資料庫 PostgreSQL 遷移 (Database Migration)

若您的專案初期使用輕量的 SQLite，但在資料量膨脹後希望無縫升級為 PostgreSQL，系統提供了一鍵遷移腳本。此腳本會在底層利用 SQLAlchemy 進行跨資料庫的批量讀寫，並自動同步 PostgreSQL 的 Sequence。

詳細的遷移步驟（包含前置的 PostgreSQL 安裝、`.env` 雙資料庫連線字串設定，以及防呆防 OOM 的執行細節），請直接參閱專屬文件：
👉 **[從 SQLite 升級與遷移至 PostgreSQL 指南](file:///home/mfhsieh/projects/python/link-checker/doc/migrate_to_postgresql.md)**

```bash
# 在設定好 .env 後，執行遷移腳本
python scripts/migrate_sqlite_to_pg.py
```
