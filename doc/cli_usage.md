# 命令列 (CLI) 操作指南

外部連結檢查爬蟲可以完全不依賴網站後台，透過命令列直接執行與管理。請確認已進入虛擬環境，並參考以下完整指令與設定檔操作說明。

---

## 1. 完整的命令列參數 (Arguments)

執行 `python cli.py` 時，系統支援以下命令列參數：

### 群組 1：任務生命週期與調度 (Job Lifecycle & Scheduling)

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--config` | `-c` | 字串 | **[建立新任務時必填]** 指定個別任務的 YAML 設定檔路徑。具備**路徑智慧自動補齊功能**（若未指定 `job/` 前綴且不含相對/絕對路徑，自動在前綴補上 `job/`）。 | 無 |
| `--user-id` | `-u` | 字串 | (選填) 綁定任務的擁有者 ID 或作為查詢過濾條件 (多使用者隔離用)。 | 無 |
| `--resume` | `-r` | 字串 | **[恢復任務時必填]** 指定要恢復執行的任務 Job ID (UUID 格式)。 | 無 |
| `--force` | `-f` | 旗標 | (選填) 搭配 `--resume` 使用，當任務狀態卡在 `running` 時強制接管任務。 | 無 |
| `--pause` | `-p` | 字串 | 暫停指定任務 (僅在任務狀態為 `running` 時生效)。 | 無 |
| `--delete` | `-d` | 字串 | 刪除指定任務，並清理其所有佇列與外連記錄。 | 無 |
| `--reset` | `-R` | 字串 | 重設指定任務，清除已探索外連並將狀態與佇列歸零。 | 無 |
| `--retry-failed` | `-T` | 字串 | 局部重試指定任務中爬取失敗的內部網頁與包含無效外連的網頁。 | 無 |

### 群組 2：報表檢視與結果匯出 (Reporting & Exporting)

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--list-jobs` | *(無)* | 旗標 | 印出系統中所有的爬蟲任務與狀態列表。 | 無 |
| `--report` | *(無)* | 字串 | 指定任務 ID，顯示該任務的詳細進度與統計報表。 | 無 |
| `--export` | *(無)* | 字串 | 指定任務 ID，將該任務尋獲的外部連結匯出 (預設為 CSV，若帶有 `--json` 則為 JSON)。 | 無 |
| `--export-full` | *(無)*| 字串 | 指定任務 ID，匯出該任務的完整報表 (ZIP 壓縮檔，含爬取紀錄與外連清單)。亦可搭配 `--output` 自訂檔名。 | 無 |
| `--output` | *(無)* | 字串 | (選填) 搭配 `--export` 或 `--export-full` 使用，自訂輸出路徑。 | 依格式而定，如 `report/<JOB_ID>.csv` 或 `.zip` |
| `--filter` | *(無)* | 字串 | (選填) 搭配 `--export` 使用，篩選匯出內容。支援 `dead`、`broken`、`blocked`、`insecure`。 | 無 |
| `--exclude`| *(無)* | 字串 | (選填) 搭配 `--export` 使用，排除指定的目標網域（多個以逗號分隔）。 | 無 |
| `--group-by`| *(無)* | 字串 | (選填) 搭配 `--export` 使用，聚合模式：`target` (依外連)、`source` (依來源頁面)、`domain` (依網域)。 | `none` |
| `--json` | *(無)* | 旗標 | (選填) 啟用 JSON 格式支援。支援 `--list-jobs` 與 `--report` 的 stdout 輸出，以及 `--export` 的 JSON 檔案導出。 | 無 |

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
> * `--filter` 篩選條件說明：
>   * `dead`：特指 **「DNS 解析失敗 (IP 位址為空) 的無效外部連結」**（例如網域已過期）。
>   * `broken`：特指 **「HTTP 狀態碼為實質異常 (如 404, 500) 或連線失敗的超連結與資源」**。
>   * `blocked`：特指 **「遭目標網站防火牆 (WAF) 阻擋或權限不足 (如 401, 403, 429)」**，屬低風險連結。
>   * `insecure`：特指 **「使用明文 HTTP 傳輸的非安全外部連結」**。
> * 爬蟲執行過程中的日誌會依據全域設定，同時輸出至畫面並備份至 `log/crawler.log`。

---

## 1.5 全域設定檔說明 (config_global.yaml)

系統使用 `config/config_global.yaml` 作為預設的全域設定檔，用以定義爬蟲引擎的安全上下限閥值與預設行為（資料庫連線與系統日誌已全面改由 `.env` 環境變數控管）：

```yaml
# 爬蟲引擎的全域限制與預設值
crawler:
  # 安全上下限限制（個別任務若超出此範圍將被強制修正，以防負載過大或逾時失效）
  min_timeout: 10             # 逾時時間最小值限制 (秒)
  max_timeout: 60             # 逾時時間最大值限制 (秒)
  min_connect_timeout: 1.0    # 建立連線逾時最小值限制 (秒)
  max_connect_timeout: 30.0   # 建立連線逾時最大值限制 (秒)
  min_external_check_timeout: 1.0  # 外連探測逾時最小值限制 (秒)
  max_external_check_timeout: 30.0 # 外連探測逾時最大值限制 (秒)
  min_delay: 1.0              # 請求延遲時間最小值限制 (秒)
  max_delay: 10.0             # 請求延遲時間最大值限制 (秒)
  min_retries: 0              # 錯誤重試次數最小值限制 (次)
  max_retries: 5              # 錯誤重試次數最大值限制 (次)
  max_max_depth: null         # 任務可設定之最大探索深度的全域上限
  max_max_pages: null         # 任務可設定之最大抓取頁數的全域上限

  # 爬蟲硬性資源限制（僅限全域配置，個別任務無法覆寫）
  max_content_length: 10485760 # 爬蟲最大網頁讀取容量上限 (預設 10MB)
  max_redirects: 10           # HTTP 重導向追蹤次數上限

  # 隨機延遲抖動比例 (Jitter) (防範行為分析，預設 0.2 代表 ±20% 抖動)
  jitter_ratio: 0.2

  # 預設瀏覽器 User-Agent（若為 null 則自動啟用高擬真動態瀏覽器特徵與標頭輪替，防範 WAF 阻擋）
  user_agent: null

  # MIME 類型過濾器（防止爬蟲下載非網頁媒體資源）
  mime_type_filter:
    enabled: true
    allowed_types:
      - "text/html"
      - "application/xhtml+xml"

  # 代理伺服器 URL (預設為 null，可藉由環境變數優先覆寫)
  proxy_url: null

  # 預設行為參數（當個別任務設定檔未指定時自動套用此預設值）
  timeout: 30                 # 預設逾時時間 (秒)
  connect_timeout: 5.0        # 預設 TCP 建立連線逾時 (秒)
  external_check_timeout: 10.0 # 預設外連存活探測總超時 (秒)
  delay: 3.0                  # 預設請求延遲 (秒)
  retries: 3                  # 預設重試次數 (次)

  # 自簽憑證豁免網域清單 (僅在連線這些網域時會跳過 SSL 憑證驗證)
  ssl_exempt_domains:
    # - "example.com"

  # 網域特定請求延遲時間對照表 (單位：秒，支援最長匹配優先原則)
  domain_delays:
    # example.com: 5.0

  # 全域排除的路徑規則 (Regular Expression)
  ignore_regexes:
    # - "^https://example\\.com/logout"

  # 允許在遇到 HTTP 錯誤時降級使用 GET 請求探測的大型社群或反爬蟲網域清單
  social_domains:
    - "facebook.com"
    - "fb.com"
    - "youtube.com"
    - "youtu.be"

  # 預設略過且不進行 HTML 抓取解析的副檔名清單（會與個別任務清單聯集合併）
  ignore_extensions:
    - ".pdf"
    - ".doc"
    - ".docx"
    # ... (其餘壓縮檔、影音檔與程式庫詳見預設設定檔)
```

---

## 2. 建立並啟動新爬蟲任務

爬蟲需要一個任務設定檔來定義起始網址 (`start_url`)、允許深入的目標網域與信任網域。基於專案規範，建議將這些個別設定檔放置於 `job/` 目錄中。

### 步驟 1：建立任務設定檔 (例如 `job/my_task.yaml`)

請參考以下範例建立您的設定檔。檔案中包含了必填的核心邏輯，以及可選的爬蟲行為覆寫：

```yaml
# ==========================================
# 必填設定 (核心邏輯)
# ==========================================

# 爬蟲的起始網址
start_url: "https://www.example.com/"

# 允許爬蟲進入並繼續深入解析的目標網域清單
target_domains:
  - "www.example.com"
  - "blog.example.com"

# 被視為「信任網域」的清單。
# 若爬取到的 <a> 連結其網域「不在」此清單內，就會被判定為外部連結並記錄下來。
trusted_domains:
  - "www.example.com"
  - "blog.example.com"
  - "auth.example.com"

# ==========================================
# 選填設定 (爬蟲行為覆寫)
# ==========================================
crawler:
  # 每次發送 HTTP 請求前的預設延遲時間 (單位：秒)
  delay: 4.0
  
  # HTTP 請求連線逾時時間 (單位：秒)
  timeout: 45
  
  # 建立連線 (TCP Connect) 逾時時間 (單位：秒)
  connect_timeout: 5.0
  
  # 外連存活探測的總體逾時時間 (單位：秒)
  external_check_timeout: 10.0
  
  # 遇到暫時性錯誤時的重試次數
  retries: 2

  # 請求延遲的隨機抖動比例 (選填，預設為 0.2)
  jitter_ratio: 0.2

  # 最大爬取深度限制 (選填，預設為無限制)
  # 1 代表僅爬起始網頁；2 代表向下延伸一層內部連結，依此類推。
  max_depth: 2

  # 最大抓取頁數限制 (選填，預設為無限制)
  # 超過此抓取頁數時，爬蟲將優雅終止任務。
  max_pages: 100

  # 網域特定請求延遲設定 (選填)
  # 支援最長匹配優先原則，用以精確調控特定目標網站的請求頻率。
  domain_delays:
    "example.com": 5.0
    "sub.example.com": 10.0

  # 信任的自簽憑證豁免網域白名單 (選填)
  # 位於此清單之網域將豁免 SSL 鏈結校驗，避免自簽憑證導致存活探測失敗。
  ssl_exempt_domains:
    - "internal-self-signed.local"
    - "my-partner-api.com"

  # 自訂此任務的 User-Agent 標頭，用以偽裝瀏覽器 (選填)
  user_agent: null
  
  # 額外要略過解析的副檔名 (會與全域設定檔中的清單聯集)
  ignore_extensions:
    - ".custom_ext"
```

> [!WARNING]
> 在 `crawler` 區塊中自訂的 `delay`、`timeout` 與 `retries` 數值，必須落在全域設定檔 (`config/config_global.yaml`) 定義的上下限內。若超出範圍，系統將印出警告並強制套用全域的安全限制。

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
若想在不變更任務 Job ID 的前提下，將任務退回初始狀態並清除所有已抓取的外連：
```bash
python cli.py --reset <JOB_ID>
```
這會清除該 Job 在資料庫中的所有外連記錄與佇列，並將佇列狀態歸零，回到僅剩 `start_url` 處於 `pending` 的狀態。

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
此操作會利用資料庫的級聯刪除機制 (Cascade)，將該 Job 的所有 `crawl_queue` 佇列與 `external_links` 結果一次清理乾淨。

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
這會為您計算出目前**已完成、等待中、失敗的網址數量**，以及已經找到的**外部連結總數**。

### 匯出結果 (CSV / JSON 與聚合去重)
如果您希望把找到的外部目標連結整理下來：
```bash
# 預設會匯出為 CSV，路徑為 report/<JOB_ID>.csv
python cli.py --export <JOB_ID>

# 您也可以加上 --output 自訂路徑
python cli.py --export <JOB_ID> --output ./my_result.csv

# 僅匯出「DNS 解析失敗」的無效外連連結
python cli.py --export <JOB_ID> --filter dead --output ./dead_links.csv

# 匯出所有損毀外連 (包含 DNS 解析失敗，以及 HTTP 狀態碼 >= 400 比如 404/500)
python cli.py --export <JOB_ID> --filter broken

# 匯出所有非 HTTPS 的外連 (資安稽核用)
python cli.py --export <JOB_ID> --filter insecure

# 匯出為 JSON 格式 (預設會輸出到 report/<JOB_ID>.json)
python cli.py --export <JOB_ID> --json

# 依外連目標聚合導出 (同個外連在不同頁面出現時會被合併)
python cli.py --export <JOB_ID> --group-by target

# 依自家網頁修補視角導出 (顯示我的 A 網頁底下壞了哪些外連)
python cli.py --export <JOB_ID> --group-by source

# 依外部網域統計導出 (檢視對外部服務的依賴分佈與次數)
python cli.py --export <JOB_ID> --group-by domain

# 匯出完整報表大禮包 (自動打包為 ZIP 檔，內含外部連結與內部連結診斷 CSV)
python cli.py --export-full <JOB_ID>

# 匯出完整報表並自訂 ZIP 檔名
python cli.py --export-full <JOB_ID> --output custom_report.zip

# 匯出結果並排除特定網域 (例如不想看社群網站的外連)
python cli.py --export <JOB_ID> --exclude "facebook.com,youtube.com,twitter.com"
```


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

系統提供了一支便利的 Shell Script (`scripts/job_sync.sh`)，協助您在不同伺服器或不同資料庫（如 SQLite 與 PostgreSQL）之間，安全地轉移與備份爬蟲任務資料（包含設定、待爬佇列與外部連結結果）。

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
