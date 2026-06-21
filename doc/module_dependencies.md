# 模組間詳細依賴說明文件 (Module Dependencies)

本文件明確條列本專案各核心模組（Frontend, Backend, Crawler, CLI）之間的依賴關係、通訊介面以及具體的程式碼引入情況。

---

## 1. 前端展示層 (Frontend) 對 後端網站層 (Backend) 的依賴

前端完全採用靜態 HTML/JS 開發，**完全不依賴後端程式碼**。其與後端的唯一依賴是 **RESTful API / SSE 介面契約**。

- **通訊方式**: 透過 AJAX / Fetch 進行異步通訊，API 基礎網址設定為同源 `BASE_URL = ''`（參見 [frontend/js/api.js](file:///home/mfhsieh/projects/python/link-checker/frontend/js/api.js)）。
- **主要依賴的 API 路由端點**:
  - **身分驗證**: `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/password/reset`
  - **任務管理**: `/api/jobs` (CRUD), `/api/jobs/{job_id}/start`, `/api/jobs/{job_id}/pause`, `/api/jobs/{job_id}/results`
  - **報表匯出**: `/api/jobs/{job_id}/results/export`, `/api/jobs/{job_id}/internal-results/export`, `/api/jobs/{job_id}/export/full`
  - **系統管理**: `/api/admin/users`, `/api/admin/logs`
- **安全防禦依賴**: POST / PATCH / DELETE 請求必須在 Request Header 中附加 `X-CSRF-Token`（讀取自 Cookie中的 `csrf_token`）。
- **前端內部公用庫依賴**:
  - **公用通知**: 所有業務邏輯模組 (`jobs.js`, `auth.js` 等) 皆依賴 [frontend/js/toast.js](file:///home/mfhsieh/projects/python/link-checker/frontend/js/toast.js) 來進行全域通知與警示。

---

## 2. 後端網站層 (Backend) 對 命令列進入點 (CLI) 的依賴

為落實進程隔離 (Subprocess Bridge)，避免爬蟲運算阻塞 Web 伺服器的非同步事件迴圈，後端以啟動子程序的方式呼叫 CLI 來達成目的。

- **呼叫檔案**: [backend/jobs/services/management.py](../backend/jobs/services/management.py#L90-L99) 中的 `start_job` 函式。
- **依賴形式**: 使用 Python 的 `subprocess.Popen`。
- **具體呼叫指令**:
  ```bash
  python cli.py --api-spawn <job_id>
  ```
- **狀態協同**: CLI 執行時將狀態寫入 Crawler DB。Web 服務則透過讀取資料庫狀態（State-driven）或監控 PID 檔案來判定任務是否仍在運行。

---

## 3. 後端網站層 (Backend) 對 爬蟲核心 (Crawler) 的依賴

網站後台需要提供任務的建立、查詢、結果展示及重置等服務，因此需要引入 Crawler 模組的管理器與資料庫模型。

- **依賴的 Crawler 類別與函式**:
  - **依賴注入實例**: [backend/deps.py](../backend/deps.py) 中透過 `JobManager` 與資料庫進行連線：
    ```python
    from crawler.manager import JobManager
    ```
  - **任務管理與查詢**: [backend/jobs/services/management.py](../backend/jobs/services/management.py) 與 [backend/jobs/services/results.py](../backend/jobs/services/results.py) 中，直接調用 `JobManager` 類別並引入 `crawler.models`。
- **核心引入語句 (Imports)**:
  - `from crawler.manager import JobManager, JobCreateOptions`
  - `from crawler.models import Job, CrawlQueue, ExternalLink`
  - `from crawler.config_utils import merge_and_validate_crawler_config`

---

## 4. 命令列進入點 (CLI) 對 爬蟲核心 (Crawler) 的依賴

`cli.py` 作為系統的獨立運行進入點，直接調用爬蟲的所有控制層級。

- **主要職責**: 解析命令列參數、讀取並合併設定檔、啟動爬蟲工作執行器。
- **核心引入語句 (Imports)**:
  - `from crawler.manager import JobManager, JobCreateOptions, Job`
  - `from crawler.config_utils import merge_and_validate_crawler_config`

---

## 5. 命令列進入點 (CLI) 對 後端網站層 (Backend) 的依賴 (有限制依賴)

依據「CLI-First」獨立性原則，`cli.py` 僅在執行管理員建立及觸發狀態通知時，會有限度地調用後端的 Auth 與郵件服務。

- **管理員建立 (Local Import)**:
  - 於 `cli.py` 的 `create_admin()` 函式內部局部引入，避免在執行一般爬蟲任務時載入網站身分驗證資料庫：
    ```python
    from backend.auth.db import get_auth_session_local
    from backend.auth.models import User
    from backend.auth.password import hash_password
    ```
- **任務狀態通知 (Dynamic Callback Injection)**:
  - CLI 在執行爬蟲任務時，會動態嘗試載入後端的發信通知服務。若載入成功，則會將發信服務當作 callback 傳遞給 `JobManager.run_job()`：
    ```python
    try:
        from backend.jobs.services.notifier import send_job_status_notification as _send_notification
    except ImportError:
        _send_notification = None
    ```
  - 這能保證 CLI 子程序執行完畢後能順利呼叫後端的發信邏輯，同時也確保了 CLI 在無 backend 程式碼的純淨環境中仍能優雅降級運行。

- **報表匯出功能**:
  - `cli.py` 的 `--export-external`, `--export-internal` 及 `--export-full` 報表輸出功能，直接調用後端業務服務層的 Exporter：
    ```python
    from backend.jobs.services.exporter import (
        export_full_report,
        export_external_job_results,
        export_internal_job_results,
        ExportOptions,
    )
    ```
- **過濾條件參數同步**:
  - `cli.py` 會動態引入後端的錯誤狀態過濾常數，確保 CLI 命令列的 `--filter` 選項與 Web API 支援的篩選條件保持 100% 同步：
    ```python
    from backend.jobs.services.query_utils import ERROR_STATUS_FILTERS
    ```

---

## 6. 爬蟲核心 (Crawler) 的依賴狀況 (完全解耦)

在重構完成後，`crawler` 模組（包含 `manager.py`, `runner.py`, `core.py`, `utils.py`）**完全去除了對 `backend` 與 `cli.py` 的任何直接程式碼引入**。

- **狀態通知**: 不再自行 import 後端的 `send_job_status_notification` 函式，而是依賴執行期外部注入的 `status_callback: Callable[[str, str], None]`。
- **報表匯出**: 移除所有報表產生邏輯，將產出 CSV/ZIP 的職責完全交給外部（如 `backend` 的 exporter 服務）。
- **資料庫訪問**: 完全依賴自有的 `crawler.models` 中宣告的 SQLite/PostgreSQL schema 映射，與後端 Auth DB 保持完全的庫級分離與物理隔離。

---

## 7. 系統維運腳本 (Scripts) 對核心的依賴

位於 `scripts/` 目錄下的各種維護腳本（例如資料庫遷移、任務備份等）由於需要繞過 API 直接進行批次處理，因此會直接依賴後端與 Crawler 的底層模組。

- **`migrate_sqlite_to_pg.py`**:
  - 直接依賴 `backend.auth.models` 與 `crawler.models` 以取得所有資料表 Metadata 進行清空與重建。
  - 直接依賴 SQLAlchemy 的 `create_engine` 與 `sessionmaker` 進行跨庫連線。
- **`manage_job_data.py`** (被 `job_sync.sh` 呼叫):
  - 直接依賴 `crawler.models` 中的 `Job`, `CrawlQueue`, `ExternalLink` 進行資料的 JSONL 序列化與反序列化。
  - 依賴 `backend.config` 以取得當前啟動環境的資料庫 URL。
- **`backfill_status_category.py`**:
  - 直接依賴 `crawler.models` 以撈取 `ExternalLink` 與 `CrawlQueue` 並更新 `status_category` 欄位。
  - 直接依賴 `crawler.utils` 內部與外部連結的狀態判斷函式 (`determine_external_link_status_category` 等) 來計算標準化分類。
  - 依賴 `backend.config` 獲取 Crawler DB 連線字串。
- **`backfill_target_domain.py`**:
  - 直接依賴 `crawler.models` 以撈取 `ExternalLink` 與 `Job` 並更新 `target_domain` 欄位。
  - 依賴 `backend.config` 獲取 Crawler DB 連線字串。
