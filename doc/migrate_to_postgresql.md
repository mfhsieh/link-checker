# 從 SQLite 升級與遷移至 PostgreSQL 指南 (SQLite to PostgreSQL Migration Guide)

本文件詳細說明如何將「外部連結檢查系統」專案的資料庫從 SQLite 升級並遷移至 **PostgreSQL**。此指南包含 WSL/Ubuntu 環境下的 PostgreSQL 安裝、使用者與資料庫建立、連線設定檔（`.env`）調校、資料遷移腳本執行以及遷移後的資料庫優化。

---

## 1. 為什麼要升級至 PostgreSQL？

雖然 SQLite 在開發與單人測試環境中極為便利，但當系統進入生產環境（Production）或需要高併發支援時，升級至 PostgreSQL 可帶來以下核心優勢：
* **高併發寫入能力**：SQLite 採用資料庫層級的鎖定（Database-level locking），在多個任務並行爬取寫入時容易遭遇 `database is locked` 的錯誤。PostgreSQL 支援細粒度的資料列層級鎖定（Row-level locking），能大幅提高多工平行爬取的寫入效能。
* **資料完整性與嚴格限制**：PostgreSQL 具有更嚴格的型別約束（例如字串長度限制），能提前暴露並避免不合規的資料寫入。
* **豐富的分析功能**：在大數據量下，PostgreSQL 的索引優化、查詢計畫器（Query Planner）與外部工具生態（如資料庫備份、即時監控等）皆遠比 SQLite 強大。

---

## 2. 前置準備：安裝與配置 PostgreSQL (WSL / Ubuntu)

以下以 **WSL (Windows Subsystem for Linux)** 或 **Ubuntu** 環境為例，說明如何建立 PostgreSQL 服務。

### 步驟 2.1：安裝 PostgreSQL 軟體包
在您的終端機執行以下指令進行安裝：
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

### 步驟 2.2：啟動 PostgreSQL 服務
在 WSL 中，系統服務通常不會自動啟動。請使用以下指令手動啟動服務：
```bash
sudo service postgresql start
```
*如需檢查服務狀態，可執行：`sudo service postgresql status`。*

### 步驟 2.3：建立使用者與資料庫
切換至 `postgres` 系統管理員帳號並進入 PostgreSQL 交談式終端機（`psql`）：
```bash
sudo -u postgres psql
```

進入 `psql` 互動介面後，執行以下 SQL 建立獨立的資料庫使用者以及兩個分別對應 **Auth DB** 與 **Crawler DB** 的資料庫：

```sql
-- 1. 建立專用使用者（請將 'your_secure_password' 替換為您的密碼）
CREATE USER elc_user WITH PASSWORD 'your_secure_password';

-- 2. 建立 Auth 資料庫，並將擁有權指定給該使用者
CREATE DATABASE auth_db OWNER elc_user;

-- 3. 建立 Crawler 資料庫，並將擁有權指定給該使用者
CREATE DATABASE crawler_db OWNER elc_user;

-- 4. 退出 psql
\q
```

---

## 3. 配置環境設定檔 (`.env`)

本專案使用雙資料庫架換，需要分別在專案根目錄的 `.env` 檔案中設定對應的連接 DSN (Connection String)。

請開啟 `.env`，並依據剛才建立的資料庫修改以下變數：

```ini
# 目標 PostgreSQL 連線 DSN 設定
AUTH_DB_URL=postgresql://elc_user:your_secure_password@localhost:5432/auth_db
CRAWLER_DB_URL=postgresql://elc_user:your_secure_password@localhost:5432/crawler_db
```

> [!WARNING]
> ### ⚠️ 密碼中包含特殊字元（如 `@`、`:`、`/` 等）的處理方式
>
> 由於資料庫連線 URL（DSN）採用特定的標準格式，若您的密碼中包含 `@`、`:`、`/`、`?` 等保留字元，**直接寫入會造成連線剖析器錯誤**。
>
> **解決方案**：必須先對密碼中的特殊字元進行 **URL 編碼 (Percent-encoding)**。
> * 例如：如果您的密碼是 `p@ssword`，請將其寫為 `p%40ssword`。
> * 例如：如果您的密碼是 `my:pass`，請將其寫為 `my%3Apass`。

---

## 4. 執行資料遷移腳本

專案已準備好全自動遷移工具 [migrate_sqlite_to_pg.py](file:///home/mfhsieh/projects/python/ext-link-checker/scripts/migrate_sqlite_to_pg.py)，可安全地將現存 SQLite 資料（包含使用者、Sessions、歷史任務、待爬佇列與外部連結結果）導入 PostgreSQL。

### 遷移安全機制說明：
* **全新重建與自動優化**：遷移工具在寫入前，會自動清除目標 PostgreSQL 資料庫中現存的資料表（透過 `drop_all`）並**根據最新的 `models.py` 定義全新建立 Schema**。這確保了所有最新的**效能複合索引 (Composite Indexes)** 與 **`ON DELETE CASCADE` (防 OOM 級聯刪除)** 設定都會被自動套用，無需手動調整。
* **外鍵約束暫停**：腳本在執行寫入時會自動在 session 中設定 `SET session_replication_role = 'replica';`，暫時停用外鍵約束與觸發器，以確保資料快速且不按順序地安全寫入，並於完成後自動恢復。
* **分批分流寫入**：針對海量資料（如 `crawl_queue` 或 `external_links` 資料表可能多達數十萬筆），腳本會以 `batch_size = 1000` 進行分批寫入，防止記憶體溢出（OOM）。
* **序列 (Sequence) 自動同步**：遷移結束後，腳本會自動同步並更新 PostgreSQL 的主鍵 Serial 序列值，防止後續新寫入資料時主鍵衝突。

### 執行遷移指令：
於專案根目錄下，在啟用了虛擬環境的情況下執行：
```bash
python scripts/migrate_sqlite_to_pg.py
```

**執行成功的輸出範例：**
```text
2026-06-14 22:10:00 [INFO] ========================================
2026-06-14 22:10:00 [INFO]  正在準備進行 SQLite -> PostgreSQL 遷移 
2026-06-14 22:10:00 [INFO] ========================================
2026-06-14 22:10:00 [INFO] 來源 SQLite Auth DSN   : sqlite:///db/auth.db
2026-06-14 22:10:00 [INFO] 來源 SQLite Crawler DSN: sqlite:///db/crawler.db
2026-06-14 22:10:00 [INFO] 目標 PostgreSQL Auth DSN   : localhost:5432/linkchecker_auth
2026-06-14 22:10:00 [INFO] 目標 PostgreSQL Crawler DSN: localhost:5432/linkchecker_crawler
2026-06-14 22:10:00 [INFO] ========================================
2026-06-14 22:10:01 [INFO] 開始遷移 Auth DB...
...
2026-06-14 22:14:22 [INFO] Crawler DB 遷移成功！
2026-06-14 22:14:22 [INFO] 資料庫全數遷移成功！現在您可以啟動 Web 服務並改用 PostgreSQL 運行了。
```

---

## 5. 遷移後的優化與維護

### 5.1 執行統計優化（推薦）
因為剛剛完成大量資料的批次匯入，PostgreSQL 的統計資訊尚未更新，這可能會影響資料庫的查詢計畫（Query Planner）效能。

建議在遷移完成後，連線至 PostgreSQL 並手動執行以下 SQL：
```sql
VACUUM ANALYZE;
```
> [!NOTE]
> `VACUUM ANALYZE` 與強力釋放空間的 `VACUUM FULL` 不同，它**不會鎖定資料表**，您可以在系統運行中安全地線上執行，它會回收死資料空間並重新估算索引統計資訊，讓查詢變得更流暢。

### 5.2 實體檔案管理 (了解 PostgreSQL 存放在哪裡)
在 WSL / Ubuntu 預設安裝下，PostgreSQL 的主要檔案儲存於系統底層：
* **資料與資料表物理檔案**：儲存在 `/var/lib/postgresql/<版本號>/main/` 目錄下。*(權限嚴格限制，僅 postgres 使用者有權讀取)*。
* **資料庫主設定檔**：如 `postgresql.conf` 與 `pg_hba.conf` 儲存在 `/etc/postgresql/<版本號>/main/`。

---

## 6. VS Code 資料庫管理工具推薦

若您使用 **VS Code** 開發，建議安裝以下插件以便於視覺化管理您的 PostgreSQL 資料庫：

* **PostgreSQL (由 Chris Kolkman 開發)**：
  官方老牌且受歡迎的插件，能直接連線多個伺服器，查詢資料表結構、執行自訂 SQL 查詢，並整合在 VS Code 左側面板。
* **Database Client (由 cweijan 開發)**：
  支援非常豐富的視覺化介面（支援 PostgreSQL, SQLite, MySQL 等），提供了類似 DBeaver / Navicat 的精美表格檢視、欄位點擊修改、ER 圖產生等強大功能。
