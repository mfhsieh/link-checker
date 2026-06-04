# 命令列 (CLI) 操作指南

外部連結檢查爬蟲可以完全不依賴網站後台，透過命令列直接執行與管理。請確認已進入虛擬環境，並參考以下完整指令與設定檔操作說明。

---

## 1. 完整的命令列參數 (Arguments)

執行 `python cli.py` 時，系統支援以下命令列參數：

| 參數 | 縮寫 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- | :--- |
| `--config` | `-c` | 字串 | **[建立新任務時必填]** 指定個別任務的 YAML 設定檔路徑。建議將其統一放置於 `jobs/` 目錄下。 | 無 |
| `--resume` | `-r` | 字串 | **[恢復任務時必填]** 指定要恢復執行的任務 Job ID (UUID 格式)。 | 無 |
| `--global-config`| `-g` | 字串 | (選填) 指定全域設定檔的路徑。用於定義全域逾時、延遲、重試上下限等。 | `config_global.yaml` |
| `--help` | `-h` | 旗標 | 顯示此說明訊息並離開。 | 無 |

> **💡 提示：** `--config` 與 `--resume` 為互斥概念。如果是啟動新爬蟲，請使用 `--config`；如果是中斷後繼續，請使用 `--resume`。若兩者皆未輸入，系統將會印出幫助說明。

---

## 2. 建立並啟動新爬蟲任務

爬蟲需要一個任務設定檔來定義起始網址 (`start_url`)、允許深入的目標網域與內部網域。基於專案規範，建議將這些個別設定檔放置於 `jobs/` 目錄中。

### 步驟 1：建立任務設定檔 (例如 `jobs/my_task.yaml`)

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

# 被視為「內部網域」的清單。
# 若爬取到的 <a> 連結其網域「不在」此清單內，就會被判定為外部連結並記錄下來。
internal_domains:
  - "www.example.com"
  - "blog.example.com"
  - "auth.example.com"

# ==========================================
# 選填設定 (爬蟲行為覆寫)
# ==========================================
crawler:
  # 每次發送 HTTP 請求前的延遲時間 (單位：秒)
  delay: 4.0
  
  # HTTP 請求連線逾時時間 (單位：秒)
  timeout: 45
  
  # 遇到錯誤時的重試次數
  retries: 2
  
  # 額外要略過解析的副檔名 (會與全域設定檔中的清單聯集)
  ignore_extensions:
    - ".custom_ext"
```

> [!WARNING]
> 在 `crawler` 區塊中自訂的 `delay`、`timeout` 與 `retries` 數值，必須落在全域設定檔 (`config_global.yaml`) 定義的上下限內。若超出範圍，系統將印出警告並強制套用全域的安全限制。

### 步驟 2：執行 CLI 指令

```bash
# 使用預設的 config_global.yaml
python cli.py -c jobs/my_task.yaml

# (選填) 若有客製化的全域設定檔，可加上 -g 指定
python cli.py -g my_custom_global.yaml -c jobs/my_task.yaml
```

系統啟動後，終端機會顯示類似如下的訊息，告知您被分配的 Job ID：
```text
INFO - 準備建立新任務...
INFO - 成功建立任務 5eebf2ac-250f-463d-a4cc-98a64d50b5fc。爬蟲啟動中...
```

---

## 3. 恢復中斷的爬蟲任務 (斷點續傳)

如果爬蟲在執行中途遇到網路中斷、被強制關閉 (例如按下 `Ctrl+C`) 或是發生預期外的崩潰，所有的爬取狀態 (Pending, Completed, Failed) 都已經妥善保存在 SQLite 資料庫中。

要讓該任務接續未完成的網址繼續爬取，只需要透過 `-r` 或 `--resume` 帶入先前的任務 ID 即可，**不需要**重新指定 `-c`。

```bash
# 使用完整指令
python cli.py --resume 5eebf2ac-250f-463d-a4cc-98a64d50b5fc

# 或是使用縮寫
python cli.py -r 5eebf2ac-250f-463d-a4cc-98a64d50b5fc
```

> [!NOTE]
> 系統會自動從資料庫抓出該任務原先設定的 `start_url`、`target_domains` 等資訊，並從狀態為 `pending` 的佇列接續處理。
