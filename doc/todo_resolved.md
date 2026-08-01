# 已解決的待辦事項 (Resolved TODOs)

1. **`checked_links_cache` 併發存取加鎖保護（Code Review v1.9.8 Finding 1）**
   * **說明**：（於 `crawler/runner.py` 為 `JobRunnerState.checked_links_cache` 增加 `cache_lock` 鎖定機制與線程安全存取方法）
   * **問題描述**：`JobRunnerState.checked_links_cache` 使用 `cachetools.LRUCache(maxsize=1000)`，在多執行緒併發探測外部連結時未進行鎖定，可能引發競態條件或快取資料損壞。
   * **修復方案**：在 `JobRunnerState` 中加入 `cache_lock: Lock` 鎖頭，並實作 `get_cached_link`、`set_cached_link` 與 `contains_cached_link` 線程安全方法，替代所有直接存取區塊。
   * **狀態**：**已解決 (Resolved)**。

1. **`JobManager.run_job` 任務狀態切換之原子化防禦（Code Review v1.9.8 Finding 2）**
   * **說明**：（於 `crawler/runner.py` 實作條件式原子化 UPDATE，避免多 Worker 競態搶佔執行相同任務）
   * **問題描述**：多 Worker 或 API 進程同時呼叫 `run_job` 時採「先查詢後更新」方式，存在 Race Condition 視窗，可能導致兩個程序同時搶佔並重複執行同一個任務。
   * **修復方案**：在 `JobRunner._initialize` 檢查前置合法狀態後，採用原子化 `UPDATE jobs SET status='running' WHERE id=:job_id AND status=:old_status` 語法並透過 `synchronize_session="fetch"` 自動同步 ORM 物件，若影響列數為 0 則安全退出。
   * **狀態**：**已解決 (Resolved)**。

1. **正則表達式防禦與長度限制（Code Review v1.9.8 Finding 3）**
   * **說明**：（於 `crawler/config_utils.py` 增加正則表達式單條長度與總條數限制，防止 ReDoS 攻擊）
   * **問題描述**：`validate_ignore_regexes` 僅檢查語法是否合法。若傳入具備災難性回溯特徵的正則表達式，爬行特定長字串時可能引發 ReDoS (Regex Denial of Service) 導致 CPU 卡死。
   * **修復方案**：於 `crawler/config_utils.py` 設定常數 `MAX_REGEX_COUNT = 50` 與 `MAX_REGEX_LENGTH = 200`，並於 `validate_ignore_regexes` 驗證時進行長度與數量檢查。
   * **狀態**：**已解決 (Resolved)**。

1. **預設瀏覽器指紋版本常數收攏（Code Review v1.9.8 Finding 4）**
   * **說明**：（將分散於 `profiles.py` 與 `core.py` 的退回版本與 TLS 指紋名單收攏於 `crawler/profiles.py` 頂層常數管理）
   * **問題描述**：預設退回的 Chrome/Edge 版本號 `"120"` 以及 `curl_cffi` 備援指紋名單 `["chrome120", "safari15_3", "edge101"]` 分散硬編碼在 `profiles.py` 與 `core.py` 的例外處理處，不易維護與統一升級。
   * **修復方案**：將全域預設指紋常數 `DEFAULT_FALLBACK_BROWSER_VERSION` 與 `DEFAULT_IMPERSONATE_PROFILES` 統一宣告於 `crawler/profiles.py` 頂層，並在 `profiles.py` 與 `core.py` 中引用。
   * **狀態**：**已解決 (Resolved)**。

1. **說明文件繁簡用語一致性修復（Code Review v1.9.8 Finding 5）**
   * **說明**：（修正 `crawler/config_utils.py` 註解中殘留的簡體字，維護繁體中文文件規範）
   * **問題描述**：`_sanitize_domain_delays` 函式註解寫有「會过濾掉負數...」，其中「过」字為簡體字，不符專案繁體中文標準。
   * **修復方案**：將 `crawler/config_utils.py` 函式註解中的簡體字修復為繁體中文「會過濾掉負數與無法轉換為 float 的對應值」。
   * **狀態**：**已解決 (Resolved)**。

1. **多方言資料庫連線池設定彈性強化（Code Review v1.9.8 Finding 6）**
   * **說明**：（改善 `crawler/manager.py` 的資料庫分流判斷，擴充非 SQLite 關係型資料庫的連線池與 Pre-ping 支援）
   * **問題描述**：`JobManager` 初始化時僅在連線字串為 `postgresql://` 時設定 `pool_size` 與 `pool_pre_ping`，若採用 MySQL 或使用指定驅動前綴的 PostgreSQL 時會誤走 SQLite 分支。
   * **修復方案**：將 `crawler/manager.py` 的判斷邏輯改為 `is_sqlite = db_url.startswith("sqlite")` 進行反向分流保護，使所有非 SQLite 關係型資料庫皆能正確套用連線池與 `pool_pre_ping` 設定。
   * **狀態**：**已解決 (Resolved)**。

1. **修復任務比對引擎快取寫入的競態條件 (Race Condition)**
   * **說明**：（修正 `get_job_diff` 在高並發下可能因重複寫入觸發 `IntegrityError` 的系統不穩定問題）
   * **問題描述**：當資料庫不存在快取紀錄時，會動態計算差異並寫入新的 `JobDiffResult`。若同時有兩個以上對同一個任務組合的並發請求，兩者都會嘗試寫入，導致觸發 `uq_job_diff_a_b` 唯一約束，引發 `IntegrityError` 並導致 500 Server Error。
   * **修復方案**：在寫入時使用 `try...except IntegrityError` 捕捉例外，若發生衝突則進行 `db.rollback()`，並重新撈取已由其他執行緒成功建立的快取資料返回，此設計在 SQLite 與 PostgreSQL 均可安全生效。
   * **狀態**：**已解決 (Resolved)**。

1. **重構任務比對架構：實作比對結果持久化 (Materialized Diff Table)**
   * **說明**：（符合 `requirements.md` 任務歷史差異比對引擎之「比對結果持久化 (Materialized Diff)」規範，解決大任務比對時的記憶體與 OOM 崩潰問題，並支援分頁）
   * **問題描述**：目前「任務比對」API 是在記憶體中一次性算出所有差異，並回傳巨大 JSON 給前端處理分頁。當任務包含數十萬個連結時，這會引發 Server 記憶體飆升、網路傳輸壅塞與瀏覽器 OOM 崩潰。
   * **修復方案**：實作 `job_diff_results` 與 `job_diff_items` 資料表，將比對結果寫入實體資料表。前端 API 改以分頁讀取，避免記憶體問題。透過排程或存取期限設定自動清理快取（例如 14 天未存取即自動清除）。
   * **狀態**：**已解決 (Resolved)**。

1. **擴充比對任務 (Job Diff) 支援內部連結與診斷邏輯全面升級**
   * **說明**：（符合 `requirements.md` §7.3「任務歷史差異比對引擎 (Job Diff Engine)」規範）
   * **問題描述**：原本任務比對僅限於外部連結，且未標示雙方皆失敗的死鏈（持續失效）。內部網頁健康度變遷亦無比對機制。
   * **修復方案**：建立專責比對模組 `backend/jobs/services/diff.py`。新增 `persistently_failed`（持續失效）外部比對診斷，並全新實作內部網頁健康度差異比對（`internal_degraded`, `internal_recovered`, `internal_persistently_failed`, `internal_new_pages`, `internal_removed_pages`）。前端 `compare` 頁面同步更新頁籤導覽與表格渲染。
   * **狀態**：**已解決 (Resolved)**。

1. **任務結束時自動即時刷新診斷摘要與結果列表 (Diagnostic Summary Auto-Refresh)**
   * **說明**：（符合 `requirements.md` 7.2 任務管理（前台）規範）
   * **問題描述**：任務執行完畢時，前端透過 SSE 推送能即時更新控制按鈕狀態（如移轉、刪除解鎖），但頂部診斷摘要卡片與詳細連結列表需等待使用者手動切換頁籤或刷新頁面，才能看到最終結果。
   * **修復方案**：於 `frontend/js/job-detail.js` 的 `handleSseMessage` 加入狀態轉換偵測。當任務由執行中轉換為終態（`completed`/`error`/`paused`）時，先觸發 `invalidateCaches()` 清空快取，並立即自動呼叫 `loadResults()` 向 API 發起最新診斷統計與詳細列表之請求，隨後關閉 SSE 串流與輪詢。
   * **狀態**：**已解決 (Resolved)**。

1. **解耦 `crawler` 模組對 `backend.events` 的反向依賴**
   * **說明**：（符合 CLI-First 架構原則，徹底隔離模組邊界）
   * **問題描述**：爬蟲模組 (`crawler/manager.py`, `crawler/runner.py`) 直接 `from backend.events import SystemEvent, publish`，造成底層爬蟲引擎反向依賴 Web 後端模組。
   * **修復方案**：移除 `crawler/` 對 `backend.events` 的所有直接 import。將狀態變更通知完全改由外部注入的 `on_event_callback` 機制處理，並改用純字串事件名稱（如 `"job_status_changed"`），實現 100% 的物理與模組解耦。
   * **狀態**：**已解決 (Resolved)**。

1. **CLI 支援匯出內部紀錄之狀態篩選 (export-internal filter)**
   * **說明**：（從 Dropped 中撈回並實作，因 CP 值極高）
   * **問題描述**：CLI 雖然可用 `jq` 處理匯出結果，但作為 CLI-first 專案，讓 CLI 內建 `--filter` 過濾內部結果 (如 `--filter failed`) 能大幅提升使用者體驗與減少磁碟 I/O。
   * **修復方案**：於 `cli.py` 的 `--filter` 增加對內部狀態（如 `warning`, `timeout` 等）的支援說明，並傳遞該參數至 `backend.jobs.services.exporter.export_internal_job_results`，在 SQLAlchemy 查詢時依 `status_category` 進行篩選。
   * **狀態**：**已解決 (Resolved)**。

1. **實作 Alembic 破壞性操作 (Downgrade) 環境防呆鎖**
   * **說明**：（符合 `requirements.md` §9.3「Schema 遷移與破壞性操作防護」規範）
   * **問題描述**：Alembic 的 `downgrade base` 操作具備高度破壞性（會執行 `DROP TABLE`）。若在正式或開發環境中手滑誤觸，將導致資料庫瞬間被清空且歷史資料永久遺失。
   * **修復方案**：已於 `alembic/env.py` 中寫入底層的防呆保護鎖。當腳本偵測到 `downgrade` 指令時，會要求必須攜帶 `CONFIRM_DESTRUCTIVE_DOWNGRADE=yes` 環境變數才能放行，否則立即阻擋並中斷執行。
   * **狀態**：**已解決 (Resolved)**。

1. **`_handle_error` 重試退避期間未持久化 `retry_count`**
   * **說明**：（依據 TODO CP 值評估優先實作）
   * **修復方案**：在 `crawler/runner.py` 的 `_handle_error` 中補上 `session` 參數，並於進入長時間 sleep 之前執行 `session.commit()`，確保重試計數在退避等待期間不會因斷電或中斷而遺失。
   * **狀態**：**已解決 (Resolved)**。

1. **加入結構化的任務執行統計日誌 (Observability)**
   * **說明**：（依據 TODO CP 值評估從擱置中恢復實作）
   * **修復方案**：在 `crawler/runner.py` 的 `_mark_job_completed` 加上了包含 `crawled_count`、`external_links_total` 與總耗時的結構化日誌輸出。大幅提升無介面 CLI 執行與伺服器日誌除錯的可觀測性。
   * **狀態**：**已解決 (Resolved)**。

1. **任務狀態轉換缺乏資料庫層面約束**
   * **說明**：（依據 TODO CP 值評估優先實作）
   * **問題描述**：狀態轉換僅在應用層檢查，資料庫無 `CHECK CONSTRAINT`，並發請求可能繞過應用層檢查。
   * **修復方案**：在 SQLAlchemy `Job` 模型中加入 `CheckConstraint("status IN ('pending', 'queued', 'starting', 'running', 'paused', 'completed', 'error')")`，從資料庫底層徹底封堵非法狀態轉換，並已透過 Alembic 自動遷移。
   * **狀態**：**已解決 (Resolved)**。

1. **外部網域延遲設定的快取優化 (Performance)**
   * **說明**：（依據 Deep Code Review 建議優化）
   * **問題描述**：`crawler/runner.py` 內的 `_get_domain_delay` 方法在處理大量外部連結時，會透過迴圈逐一比對子網域來決定 Crawl Delay。這在遇到上萬個外部連結時，會產生額外的字串比對開銷 `O(N)`。
   * **修復方案**：在 `JobRunner` 初始化時，已引入一個簡單的字典 (`_domain_delay_cache`) 作為快取。當解析過某個 hostname 的 delay 後即暫存，下次同一個 hostname 直接 O(1) 讀取，壓低 CPU 消耗。
   * **狀態**：**已解決 (Resolved)**。

1. **前端 `JobService` 業務邏輯層封裝與 API 調用規範統一**
   * **說明**：（符合 `requirements.md` §7 前端模組化、職責分離與 API 呼叫契約一致性規範）
   * **功能描述**：原 `job-service.js` 僅封裝 2 個 API 函式，其餘 API 直接呼叫底層 `api.js`，導致調用風格不一致與抽象層薄弱。
   * **修復方案**：補齊 `getJobs`, `getJob`, `deleteJob`, `pauseJob`, `resumeJob` 等通用 CRUD 介面，統一全站前端對 Job 資源的調用規範。
   * **狀態**：**已解決 (Resolved)**。

1. **通用二次確認 Modal (Confirm Modal) 二重送防呆與 Loading 狀態防護**
   * **說明**：（符合 `requirements.md` §7 前端 UI/UX 互動、敏感操作與防呆機制規範）
   * **功能描述**：在刪除任務、停用帳號等二次確認對話框中，若非同步操作耗時較長，使用者快速連擊按鈕會引發二次重複 API 發送。
   * **修復方案**：於點擊「確認」按鈕時立即將按鈕設為 `disabled` 並提示 Loading，防範連擊重複發送。
   * **狀態**：**已解決 (Resolved)**。

1. **SSE 即時串流連線失敗自動降級與斷線上限防護**
   * **說明**：（符合 `requirements.md` §7.2「當串流發生錯誤時，前端需優雅處理並停止連線，避免資源洩漏」條文）
   * **功能描述**：`job-detail-sse.js` 在 `onerror` 缺乏重試上限，當網路中斷或 Session 過期時原生的 `EventSource` 會無限背景重連發起失敗請求。
   * **修復方案**：加入 `maxRetries = 5` 失敗次數累計上限，超過 5 次自動關閉 `EventSource` 串流連線並退回背景 30s 定期輪詢。
   * **狀態**：**已解決 (Resolved)**。

1. **前端模組 Code Review v3.0 架構重構與資源洩漏修復**
   * **說明**：（包含異步競態資源洩漏修復、透傳檔精簡、死碼監聽器清理與日期解析容錯）
   * **修復方案**：
     1. **[High] 異步競態資源洩漏修復**：修正 `job-detail.js` 中的 `refreshJobDetail` 異步競態防禦，當切離詳情頁或 `currentJobId` 變更時，自動阻止發起新的背景 `EventSource` 連線。
     2. **[Medium] 介面與透傳檔精簡**：精簡重構 `compare.js`, `duplicate.js`, `transfer.js` 透傳中轉檔。
     3. **[Low] 日期格式化解析容錯**：`api.js` 之 `formatLocalTime` 加入空格至 `T` 轉換與格式清理，保障跨瀏覽器解析 100% 正確。
     4. **[Low] 移除死碼事件監聽器**：清理 `job-detail.js` 對全域 `#job-config-close` 的重複監聽器。
   * **狀態**：**已解決 (Resolved)**。

1. **導入 Alembic 進行資料庫 Schema 遷移管理 (Database Migrations)**
   * **說明**：（符合 `requirements.md` §9.3「Schema 遷移」規範與 `README.md` 升級指南）
   * **問題描述**：目前專案在啟動時會直接透過 SQLAlchemy 的 `create_all()` 建立資料庫表。在生產環境下，若有後續的 Schema 異動（如新增欄位），無法做到自動化的增量遷移。
   * **修復方案**：已建立 Alembic 工具結構（`alembic.ini`, `alembic/env.py`），支援 `Auth DB` 與 `Crawler DB` 雙庫連線與 SQLite `render_as_batch=True` 語法，產生 `v1.9.7` 初始 Schema 版本（包含歷史 `is_secure`、`progress_stats` 等欄位與索引），並於 [README.md](file:///home/mfhsieh/projects/python/link-checker/README.md) 中將過去手動貼 `psql` 指令升級為 `.venv/bin/alembic upgrade head` 標準自動化流程。
   * **狀態**：**已解決 (Resolved)**。

1. **爬蟲深度 (Depth) 監控與探索層級顯示**
   * **說明**：（符合 `requirements.md` §7.2 之任務監控與進度規範）
   * **問題描述**：目前使用者在任務執行期間，無法在前端介面直觀地得知爬蟲當前探索到了哪一個層級 (Depth) 的內部連結。
   * **修復方案**：於 `JobManager.get_job_progress` 統計查詢 `max(CrawlQueue.depth)`，並於前端 `<job-progress>` 元件新增「當前探索深度 Badge」，即時隨 SSE 串流反饋當前探測層級（若無資料以 `-` 優雅顯示）。
   * **狀態**：**已解決 (Resolved)**。

1. **全站表格操作欄與工具列 RWD 自動折行優化 (Responsive Actions Group)**
   * **說明**：（已寫入 `requirements.md` §7.6 成為正式前端 UI/RWD 規範）
   * **問題描述**：原本在「我的任務」列表、後台管理表格與任務詳情/比對工具列中，操作欄位的按鈕在窄螢幕或行動端會排成一長橫列而不折行，導致爆欄或排版不優雅。
   * **修復方案**：全域與元件層級（`jobs.js`, `admin-main.js`, `link-table.js`, `app.html` 及全域 CSS）補齊 `.job-actions`, `.table-actions`, `.link-toolbar` 的 `flex-wrap: wrap` 與適應性間距，確保窄畫面與行動端自動優雅折行。
   * **狀態**：**已解決 (Resolved)**。

1. **為 `JobManager.get_all_jobs` 與 API 端點新增分頁機制 (Pagination)**
   * **說明**：（已寫入 `requirements.md` 與 `api_spec.md` 成為正式 API 分頁規範）
   * **問題描述**：`crawler/manager.py` 的 `get_all_jobs()` 函式先前呼叫 `.all()` 撈出全量歷史任務，若資料庫累積龐大歷史任務時會產生記憶體與資料庫 I/O 開銷。
   * **修復方案**：已於 `JobManager.get_all_jobs`、`list_jobs` 服務、`GET /api/jobs` 與 `GET /api/admin/jobs` 端點成功引入 `limit` 與 `offset` 分頁查詢參數，並同步調整前端 `JobsStore.fetchJobs()` 支援分頁。
   * **狀態**：**已解決 (Resolved)**。

1. **建立 MCP Server 以監控遠端 Production 任務狀態**
   * **說明**：（已寫入 `requirements.md` §15.1 成為正式 MCP 介面與工具規格）
   * **問題描述**：開發者需要隨時查看 Production 環境中各項爬蟲任務的即時狀態，但目前必須登入後台網頁介面。希望能讓 AI 助理直接取得資料。
   * **規劃方案**：建置一個 MCP (Model Context Protocol) 伺服器，直接連線至 `crawler.db` 提供任務清單與進度。為了不破壞現有 FastAPI 的穩定與安全性，採用獨立腳本 (`scripts/mcp_server.py`) 透過 SSH stdio 提供連線。已完成 MCP Server 建置，包含 `get_job_config`、`get_jobs_status`、`get_disk_usage` 與 `test_internal_url`/`test_external_url` 等功能驗證。
   * **狀態**：**已解決 (Resolved)**。

1. **前端程式碼重構：導入 MVC 或 Web Components 模組化封裝**
   * **說明**：（已寫入 `requirements.md` §7.5 成為正式前端規範）
   * **問題描述**：目前前端程式碼（如 `frontend/js/job-detail.js` 與 `frontend/js/jobs.js`）存在大量的全域變數狀態與未封裝的 DOM 操作（義大利麵條式程式碼），缺乏模組化設計。這導致在處理複雜的動態資料流（如 SSE 即時更新、多條件過濾）時，程式碼高度耦合，難以追蹤錯誤與進行長期維護。
   * **修復方案**：遵循 `doc/requirements.md` 中的「前端狀態管理與元件封裝防呆」規範，已全面重構現有的 Vanilla JS 程式碼。將各個獨立的 UI 區塊封裝成獨立的類別 (Class) 或原生 Web Components (Custom Elements)。確保每個元件自行管理內部狀態與事件監聽，達成高內聚低耦合的架構。已完成 Web Components 提取與 Controller/State 協調層重構 (`JobsStore`, `JobsController`, `JobDetailStore`, `JobDetailSSEManager`, `JobDetailTableManager`, `JobDetailController`, `CompareController`, `TransferController`, `DuplicateController`)，並將全域 UI 監聽邏輯抽離至 `modal-helper.js`。
   * **狀態**：**已解決 (Resolved)**。

1. **擴充與完善系統輔助說明 (Help & FAQ)**
   * **說明**：（已補充 `help.html` 報表與主網域優先說明，以及 `faq.html` 補充 Email/併發/Cookie-gate 等 Q&A 內容）
   * **功能描述**：前端 `help.html` 與 `faq.html` 說明與常見問答內容已完整補充，提供使用者詳盡的操作指引與問題排解。
   * **狀態**：**已解決 (Resolved)**。

1. **優化 `_html_cache` 基於 `mtime` 的動態快取過期檢驗機制 (S-01)**
   * **說明**：（已寫入 `requirements.md` §5.2 成為正式靜態檔案服務快取規範）
   * **問題描述**：`_html_cache` 在 `DEBUG=False`（生產模式）下會永久快取前端 HTML，部署新頁面後需手動重啟服務。
   * **修復方案**：已於 `backend/main.py` 的 `_serve_html_with_nonce` 引入 `os.path.getmtime(file_path)` 修改時間校驗，達成檔案未修改走零 I/O 快取，一旦修改自動即時感應刷新。
   * **狀態**：**已解決 (Resolved)**。

1. **微優化 `get_job_report` Fallback 路徑外部連結 count 查詢效能 (P-01)**
   * **問題描述**：`get_job_report` 在 fallback 時呼叫 `.count()` 會產生多餘子查詢 SQL。
   * **修復方案**：已於 `crawler/manager.py` 中重構為 `session.query(func.count(ExternalLink.id)).filter(...).scalar() or 0`，消除子查詢開銷。
   * **狀態**：**已解決 (Resolved)**。

1. **`ContextVar` 上下文傳播至 `ThreadPoolExecutor` 子執行緒 (C-02 / O-01)**
   * **說明**：（已寫入 `requirements.md` §5.4 成為正式並發日誌上下文規範）
   * **問題描述**：`ThreadPoolExecutor` 工作執行緒探測外部連結與執行 `curl_cffi` 降級時，產生的 log 未繼承 `current_job_id_var` 的 `job_id` 上下文。
   * **修復方案**：已於 `crawler/runner.py` 的 `check_single` 閉包內加入 `current_job_id_var.set(self.job_id)`，補齊背景執行緒與降級路徑日誌的 `[Job <id>]` 標籤。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `create_job` API 路由例外處理洩露內部堆疊資訊 (S-02)**
   * **說明**：（已寫入 `requirements.md` §5.4 成為正式資安防禦規範）
   * **問題描述**：`create_job` 路由中的 `except Exception as e:` 捕捉區塊直接將 `str(e)` 當作 HTTP 500 的 `detail` 回傳，生產環境下可能包含內部資料庫資訊或檔案路徑。
   * **修復方案**：已於 `backend/jobs/routers/management.py` 中補充 `logger.error("建立任務失敗: %s", e, exc_info=True)`，並將回傳 detail 統一遮蔽為通用錯誤訊息。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `_run_loop` 狀態查詢異常時的 `job` 物件過期順序 (C-01)**
   * **說明**：（已寫入 `requirements.md` §3.4 成為正式架構容錯規範）
   * **問題描述**：在 `_run_loop` 中，若在查詢 DB 之前先呼叫 `session.expire(job)`，一旦 `session.query(Job)` 拋出例外，`job` 屬性會保持過期狀態，後續讀取屬性時將觸發隱式查詢並引發連鎖錯誤。
   * **修復方案**：已將 `session.expire(job)` 移至 `session.query(Job)` 確認成功執行之後，確保僅在查詢成功時才過期舊物件。
   * **狀態**：**已解決 (Resolved)**。

1. **為 `_execute_curl_cffi_fallback` 重導向防護新增 `_depth` 防禦參數 (E-01)**
   * **說明**：（已寫入 `requirements.md` §2 成為正式核心遞迴防禦規範）
   * **問題描述**：在 `_execute_curl_cffi_fallback` 方法中，當重導向達到 `max_redirects` 時會嘗試發起自我遞迴呼叫，但方法簽章缺乏防禦性遞迴深度控制。
   * **修復方案**：已於 `crawler/core.py` 的 `_execute_curl_cffi_fallback` 方法簽章中加入 `_depth: int = 0` 預設參數，並在遞迴呼叫處加入 `_depth == 0` 及 `_depth=_depth + 1`，確保自我遞迴最多僅執行一次。
   * **狀態**：**已解決 (Resolved)**。

1. **補充 `CrawlerCore.check_external_link` 核心降級路徑單元與整合測試**
   * **說明**：（已寫入 `requirements.md` §13 成為正式測試規範）
   * **問題描述**：`CrawlerCore.check_external_link()` 為爬蟲核心探測引擎，包含多層複雜降級邏輯（如 HEAD 失敗降級 GET、HTTP 升級 HTTPS 探測、`httpx` 降級至 `curl_cffi` TLS 指紋偽裝、Cookie-gate 重導向維持等）。目前測試集中缺乏針對這些降級分支的自動化測試覆蓋，若後續重構可能無法即時發現 regression。
   * **修復方案**：已建立獨立測試檔案 [`test/test_crawler_fallback.py`](file:///home/mfhsieh/projects/python/link-checker/test/test_crawler_fallback.py)，撰寫包含 HEAD 網路異常/404 降級 GET、明文 HTTP 連線失敗自動升級 HTTPS、WAF 403 觸發 TLS 偽裝引擎 (curl_cffi) 以及跨跳 Set-Cookie 分桶繼承等 5 大降級分支的完整自動化單元測試。
   * **狀態**：**已解決 (Resolved)**。

1. **優化 SSE 於 `paused` 狀態下的生命週期處理**
   * **說明**：（已寫入 `requirements.md` §4.3 成為正式架構規範）
   * **問題描述**：`backend/jobs/routers/management.py` 的 `stream_job_updates` 在建立 SSE 連線時，若任務狀態為 `paused` 且非運行中，會直接結束傳輸關閉連線；前端接收到 `paused` 狀態時亦會終止 SSE 與背景輪詢。在 `reprobe_external_links` 後任務狀態轉為 `paused` 時，若使用者隨後啟動任務，前端連線會因為先前的自動中斷而無法及時獲得 SSE 動態推播。
   * **修復方案**：已優化 [`backend/jobs/routers/management.py`](file:///home/mfhsieh/projects/python/link-checker/backend/jobs/routers/management.py) 中 `stream_job_updates` 的 SSE 串流關閉判定，分離 `completed/error` 與 `paused/pending` 之生命週期處置，確保前端於任務啟動與重試狀態變更時能流暢重新建立 SSE 事件推播。
   * **狀態**：**已解決 (Resolved)**。

1. **補充 `_serve_html_with_nonce` 的標籤 nonce 動態注入單元測試**
   * **說明**：（已寫入 `requirements.md` §13 成為正式測試規範）
   * **問題描述**：`backend/main.py` 中的 `_serve_html_with_nonce()` 在生產模式下會將 HTML 快取至記憶體並動態注入 CSP nonce。正則匹配邏輯 `if "nonce=" in attrs.lower()` 若遇到包含 `"nonce="` 字串的特殊屬性 (如 JSON dataset) 時，可能發生誤判。目前缺乏自動化單元測試覆蓋此動態替換行為。
   * **修復方案**：已將 `_serve_html_with_nonce()` 內的屬性比對正則表達式優化為嚴格單字匹配 `re.search(r"\bnonce\s*=", ...)`，並於 [`test/test_api.py`](file:///home/mfhsieh/projects/python/link-checker/test/test_api.py) 補齊涵蓋不存在頁面重導向、script/style 標籤注入、dataset 屬性匹配及防範重複注入等情境之單元測試案例。
   * **狀態**：**已解決 (Resolved)**。

1. **優化 `JobRunner._handle_error` 指數退避延遲解耦長時間阻塞以提升暫停響應**
   * **說明**：（已寫入 `requirements.md` §3.3 成為正式任務調度規範）
   * **問題描述**：`crawler/runner.py` 的 `_handle_error()` 在進行失敗重試時，直接使用 `time.sleep(actual_delay)`。當退避延遲達數十秒時，長時間阻塞會導致爬蟲無法即時響應使用者的暫停/停止指令。
   * **修復方案**：已將 `_handle_error()` 中單次長延遲 `time.sleep(actual_delay)` 重構為 0.5 秒步長之微輪詢 sleep 迴圈 `while time.time() < end_time:`，解耦長時間線程阻塞。
   * **狀態**：**已解決 (Resolved)**。

1. **補充 `sanitize_error_message` 敏感資訊過濾與邊界情況單元測試**
   * **說明**：（已寫入 `requirements.md` §13 成為正式測試規範）
   * **問題描述**：`crawler/utils.py` 中的 `sanitize_error_message` 涵蓋複雜的 IPv6、IPv4、URL 密碼與 Token 遮蔽正則表達式，但目前測試集中缺乏專屬單元測試。對於 IPv6 縮寫格式 (如 `::1`)、IPv4-mapped IPv6 及換行符等邊界測試覆蓋不足。
   * **修復方案**：已新增 [`test/test_utils.py`](file:///home/mfhsieh/projects/python/link-checker/test/test_utils.py) 測試套件，針對敏感 Token、URL 帳密、IPv4、完整/縮寫 IPv6 地址遮蔽以及 CRLF 換行符 Log Injection 清洗撰寫了 7 個涵蓋各種邊界條件的自動化單元測試。
   * **狀態**：**已解決 (Resolved)**。

1. **在 `doc/api_spec.md` 補充 `format_crawl_queue_item` 的歷史 CSV 命名規範說明**
   * **說明**：（已寫入 `requirements.md` §9.1 成為正式 Legacy API 規範）
   * **問題描述**：`crawler/utils.py` 的 `format_crawl_queue_item()` 字典鍵名混用大寫空格與小寫底線（例如 `"Status"` vs `"is_secure"`），此為向後相容舊有 CSV/Excel 導出的既有設計，但 `doc/api_spec.md` 中未記錄此欄位相容性細節。
   * **修復方案**：已於 `crawler/utils.py` 及 `backend/jobs/routers/results.py` 的 Docstring 補充 Legacy CSV/Excel 欄位命名相容說明，並執行 `scripts/gen_api_doc.py` 將說明自動寫入 `doc/api_spec.md` 與 `doc/api.json`。
   * **狀態**：**已解決 (Resolved)**。

1. **在 `doc/requirements.md` 標註軟刪除 (Soft Delete) 的已知實作偏差**
   * **問題描述**：`doc/requirements.md` §4.1 規範跨資料庫資源刪除應採「軟刪除」，但當前系統基於簡化 ORM 查詢考量暫採硬刪除（此項已在 `todo.md` 追蹤）。需求規格書中未記載此「意圖性偏差 (Intentional Deviation)」，容易引發文件不一致。
   * **修復方案**：已於 `doc/requirements.md` §4.1 軟刪除條目補充「已知偏差 (Intentional Deviation)」與說明現階段實體層採 Hard Delete 之考量與 `todo.md` 追蹤連結。
   * **狀態**：**已解決 (Resolved)**。

1. **替換 `CrawlerConfig` 初始化中的 `cast()` 為真實運行期型別轉換**
   * **說明**：（已寫入 `requirements.md` §5.1 成為強型別防禦規範）
   * **問題描述**：`crawler/runner.py` 中建立 `CrawlerConfig` 物件時使用 `cast()`（如 `cast(int, ...)`）。`cast()` 在 Runtime 是無效的（no-op），若 CLI 傳入字串等非預期型別，無法在初始化時及時防禦。
   * **修復方案**：已將 `runner.py` 中建立 `CrawlerConfig` 的無效 `cast()` 替換為 `int()`、`float()`、`str()` 及 `bool()` 等真實運行期顯式型別轉換包裝，強化強型別防禦。
   * **狀態**：**已解決 (Resolved)**。

1. **全域字典 `_ACTIVE_PROCESSES` 存取顯式添加 Thread Lock 保護**
   * **說明**：（已寫入 `requirements.md` §4.5 成為正式併發安全規範）
   * **問題描述**：`backend/jobs/constants.py` 中定義的全域字典 `_ACTIVE_PROCESSES` 在 `management.py` 與 `process.py` 之間被多個 FastAPI 路由執行緒併發讀寫（`__setitem__` / `get` / `pop`）。雖然 CPython 的 GIL 保障了單步字典操作的原子性，但顯式加鎖能傳達明確的執行緒安全意圖，並為未來的 Python free-threading (PEP 703) 做準備。
   * **修復方案**：已建立全域 `_ACTIVE_PROCESSES_LOCK = threading.Lock()`，並於 `management.py` 及 `process.py` 所有對 `_ACTIVE_PROCESSES` 的讀取、寫入與 pop 操作顯式加上 `with _ACTIVE_PROCESSES_LOCK:` 保護。
   * **狀態**：**已解決 (Resolved)**。

1. **統一 `max_depth` 與 `max_pages` 參數存取路徑至 `CrawlerConfig` Dataclass**
   * **說明**：（已寫入 `requirements.md` §3.1 成為核心模型封裝規範）
   * **問題描述**：`crawler/models.py` 的 `CrawlerConfig` dataclass 缺少 `max_depth` 與 `max_pages` 欄位定義，導致 `crawler/runner.py` 在 `_run_loop` 必須繞過 Dataclass 封裝直接讀取字典 `self.crawler_config_dict.get(...)`，破壞了核心配置物件的抽象封裝與型別安全。
   * **修復方案**：已在 `CrawlerConfig` Dataclass 補齊 `max_depth` 與 `max_pages` 欄位，並將 `runner.py` 中全數 `crawler_config_dict.get(...)` 重構統一為 `self.config.max_depth` 與 `self.config.max_pages` 存取。
   * **狀態**：**已解決 (Resolved)**。

1. **補充 `JobProgressPoller` 執行緒安全假設文檔標注**
   * **說明**：（已寫入 `requirements.md` §4.5 成為執行緒安全假設規範）
   * **問題描述**：`backend/jobs/services/poller.py` 中的 `JobProgressPoller.active_jobs` 字典未加鎖保護，依賴於單一 asyncio Event Loop 的調度特性。為防止未來開發者將 `add_job` 或 `remove_job` 放入 `run_in_threadpool` 導致競態條件，應補齊類別級別的 docstring 說明。
   * **修復方案**：已在 `JobProgressPoller` 類別的 docstring 補齊單一 asyncio Event Loop 執行緒存取限制與禁止放入 ThreadPool 執行的執行緒安全假設說明。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `JobRunner._run_loop` 狀態查詢異常導致誤判任務失敗**
   * **說明**：（已寫入 `requirements.md` §3.3 成為正式容錯規範）
   * **問題描述**：在 `crawler/runner.py` 的 `_run_loop` 主迴圈中，每隔 10 秒會向資料庫查詢任務當前狀態（如是否被暫停）。若該 DB 查詢因 SQLite 鎖定（database is locked）、PostgreSQL 連線瞬斷/逾時/死鎖等待，或任何暫時性 DB 異常拋出 `SQLAlchemyError` 例外，目前缺乏專門的捕捉機制，例外會直接冒泡至外層頂層 `try...except Exception` 區塊，導致原本正常的爬蟲任務被錯誤標記為 `error` 狀態並異常終止。
   * **修復方案**：已在 `_run_loop` 的狀態查詢段落加入 `try...except SQLAlchemyError` 捕捉區塊。遇到 DB 暫時性異常時會記錄警告日誌並重置計時器跳過當次檢查，確保爬蟲任務持續穩定運作。
   * **狀態**：**已解決 (Resolved)**。

1. **重構 `crawler/manager.py` 提取 IN 子句批次大小魔術數字為常數**
   * **說明**：（已寫入 `requirements.md` §4.1 成為 DB 操作批次限制規範）
   * **問題描述**：`crawler/manager.py` 中的 `retry_failed_job()` 函式包含寫死的 Magic Number `900`（因應 SQLite IN 子句參數 999 限制）。魔術數字直接寫死於 `range()` 與切片中，降低了程式碼維護性。
   * **修復方案**：已在 `crawler/manager.py` 中定義模組級常數 `_SQLITE_MAX_IN_BATCH_SIZE: int = 900` 並替換 `retry_failed_job()` 內所有硬編碼數值。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `sanitize_error_message` 未防禦日誌注入 (Log Injection)**
   * **說明**：（已寫入 `requirements.md` §5.4 成為正式資安防禦規範）
   * **問題描述**：`crawler/utils.py` 中的 `sanitize_error_message` 函式雖有遮蔽 IP、密碼與 Token 等敏感資料，但未清洗 `\r` (Carriage Return) 與 `\n` (Line Feed) 字元。當爬蟲抓取回傳帶有換行符的惡意 HTTP 回應或例外字串時，寫入日誌可能會造成日誌偽造 (Log Forgery)，干擾日誌分析與告警機制。
   * **修復方案**：已在 `crawler/utils.py` 的 `sanitize_error_message()` 尾端加入 `msg = msg.replace("\r", "").replace("\n", " ")` 進行 CRLF 換行符清洗，徹底封堵日誌偽造風險。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `_cleanup_finished_processes` 節流計時器未更新問題**
   * **說明**：（已寫入 `requirements.md` §4.3 成為進程清理節流規範）
   * **問題描述**：`backend/jobs/services/process.py` 中的 `_cleanup_finished_processes()` 函式雖有 `_LAST_CLEANUP_TIME` 節流判斷，但通過判斷後未進行 `_LAST_CLEANUP_TIME = current_time` 的更新賦值。當該函式被單獨呼叫時，節流機制會徹底失效，導致每次都會觸發 PID 目錄走訪與檔案 I/O 操作。
   * **修復方案**：已在 `_cleanup_finished_processes()` 宣告 `global _LAST_CLEANUP_TIME` 並於檢查通過後正確賦值更新全域時間標記 `_LAST_CLEANUP_TIME = current_time`。
   * **狀態**：**已解決 (Resolved)**。

1. **支援對「被忽略的內部連結」進行輕量死檔探測**
   * **說明**：（已寫入 `requirements.md` §2 成為正式系統規範）
   * **問題描述**：目前系統對於符合「忽略副檔名」或「忽略路徑規則」的內部連結，會直接跳過不予處理。這導致使用者雖然不希望爬蟲深入抓取這些資源（如 PDF、圖片檔或特定目錄），但同時也無從得知這些連結「是否真的存在（避免死檔或斷鏈）」。
   * **修復方案**：
     1. 在任務設定或全域設定中新增一個選項 `check_skipped_links`（預設為 `True`），啟用時採用「GET 串流標頭截斷模式」進行輕量探測（發送 GET 請求但在成功讀取 HTTP 標頭後即關閉連線，只檢查存活而不下載檔案內容）。
     2. **相容性防護**：未來新建的任務預設啟用此功能；但對於歷史舊任務，若設定檔中無此參數，則必須強制預設為 `False`，以維護其原本不發送探測請求的行為。
     3. 若探測結果為異常（如 404 或 500），則將該連結納入內部死鏈的錯誤報告中。
   * **狀態**：**已解決 (Resolved)**。

1. **Web UI 起始網址自動帶入「目標網域」與「信任網域」時自動去除 `www.` 前綴**
   * **說明**：（已寫入 `requirements.md` §4 成為正式前端規範）
   * **問題描述**：目前在 Web UI 建立任務頁面中，當使用者輸入起始網址 (Start URL，例如 `https://www.example.com/`) 並失焦 (`blur`) 時，前端自動帶入「目標網域」與「信任網域」填空會保留 `www.` 前綴 (即帶入 `www.example.com`)。這會導致預設情況下爬蟲將同機構下的其他附屬子網域 (如 `ws.example.com` 或 `law.example.com`) 過濾或誤判為外部連結。
   * **修復方案**：在前端 `frontend/js/app-main.js` 的 `jobUrlInput` `blur` 事件監聽器中，自動提取 `url.hostname` 並套用 `.replace(/^www\./i, "")`。當使用者輸入 `https://www.example.com/` 且未填寫網域時，前端會自動切除 `www.` 並將基底網域 `example.com` 帶入「目標網域」與「信任網域」輸入框中。
   * **狀態**：**已解決 (Resolved)**。

1. **CrawlQueue 記憶體 ID 雙階佇列 (In-Memory ID Queue Partitioning) 優先級分流**
   * **說明**：（已寫入 `requirements.md` §3 成為正式系統規範）
   * **問題描述**：當爬取包含多重子網域之廣域目標 (如 `target_domains: example.com` 且含資源子網域 `ws.example.com`) 時，數萬筆靜態資源/附件子網域寫入 `CrawlQueue` 佇列，佔據單一 FIFO 佇列前端，導致主目標網域 (`www.example.com`) 的深層 HTML 新聞列表與內容頁面被迫延後處理數十小時，最終因目標伺服器 Session Token (`_CSN`) 到期而引發連鎖斷鏈缺漏。
   * **規劃方案**：
     1. 在不更動任何資料庫 Schema 的前提下，於 `JobRunner` 導入「記憶體 ID 雙階佇列」機制。
     2. 任務啟動或 Resume 恢復時，以 `get_domain(job.start_url)` 鎖定主探索網域，將 `pending` 的 ID 極速分流至 `primary_id_deque` (高優先) 與 `other_id_deque` (低優先)。
     3. 爬蟲主迴圈優先取高優先 ID，透過 PK 主鍵 `WHERE id = ?` 進行 < 0.1ms 亞毫秒級高效查詢，確保主目標網域的 HTML 頁面於數小時內全數爬完。
   * **狀態**：**已解決 (Resolved)**。

1. **重構前端 Resume 任務的邏輯與 API 呼叫**
   * **說明**：（已寫入 `requirements.md` §4 成為正式前端規範）
   * **問題描述**：目前前端在「恢復」任務時，直接共用了 `btn-start-job` 與 `/api/jobs/{job_id}/start` API。雖然底層能順利接續跑起來，但未利用到後端專門提供、具備嚴格安全狀態檢查機制 (`paused` / `error`) 的 `/api/jobs/{job_id}/resume` 端點。
   * **規劃方案**：在前端 `job-controls.js` 中依據任務狀態分流：狀態為 `paused` 或 `error` 時派發 `job-resume` 事件。然後在 `job-detail.js` 新增對 `job-resume` 的監聽器，精準呼叫專屬的 `/resume` API。
   * **狀態**：**已解決 (Resolved)**。

1. **實作雲端測試 MCP 與本地/雲端結果比對 Skill**
   * **說明**：（已寫入 `architecture.md` 成為正式架構規範）
   * **問題描述**：同一個連結在本地端用 `scripts/test_ext.py` 或 `scripts/test_url.py` 測試時可能成功，但在雲端主機測試時，偶爾會因為目標主機的防禦策略（例如阻擋雲端 IP 或資料中心網段）而失敗。這導致難以釐清是連結真的失效，還是防禦策略造成的誤判。
   * **規劃方案**：
     1. **新增 MCP 功能**：擴充現有 MCP 伺服器，提供能在遠端（雲端主機）執行單一連結探測並回傳詳細結果與狀態碼的功能。
     2. **新增 Agent Skill**：建立一個新的 Skill，用於接收特定連結後，自動同時觸發本地端測試與雲端 MCP 測試，並交叉比對兩者結果。若本地成功而雲端失敗，即可明確判斷為目標主機防禦策略所致。
   * **狀態**：**已解決 (Resolved)**。

1. **修復任務詳情頁「返回列表」按鈕失效與導覽動線問題**
   * **問題描述**：使用者在讀取大量資料的任務詳情頁面時，若中途（或甚至讀取完成後）點擊「返回列表」，畫面會卡住無法跳轉；且管理者從監控面板進入詳情頁後，返回時會被錯誤導向一般使用者的任務列表，操作體驗中斷。
   * **修正方案**：
     1. 修復事件委派 (Event Delegation) 中 `e.target.closest` 因點擊文字節點而拋出 TypeError 中斷路由的錯誤。
     2. 強化 `destroyJobDetailPage` 的資源清理邏輯，強制重置 `_currentJobId`，避免背景仍在執行的非同步請求完成後，錯誤觸發 DOM 重繪並污染列表畫面 (Race Condition)。
     3. 引入 `sessionStorage` 紀錄來源路徑機制。當從管理員介面 (`/admin.html#/admin/jobs`) 進入任務詳情時，返回按鈕會智慧辨識並導回管理者的監控列表。
   * **狀態**：**已解決（Resolved）**。

1. **修復例外處理區塊的 N+1 查詢效能隱患 (Lazy Load Overhead)**
   * **問題描述**：`crawler/runner.py` 中，當抓取過程發生 `httpx.HTTPError` 或其他例外時，程式呼叫了 `session.rollback()`。在 rollback 後，ORM Session 會強制過期 (Expire) 所有綁定的物件。緊接著程式修改 `queue_item.status` 時，會自動觸發一次額外的 `SELECT` 查詢來重新載入該物件。在大量錯誤發生的情境下，這會引發多餘的 N+1 查詢效能損耗。
   * **修正方案**：經評估 `httpx.HTTPError` 並非資料庫層級錯誤，且交易狀態仍屬乾淨，因此直接移除了 `_handle_error` 內的 `session.rollback()`；而對於未知例外的捕獲，則在 `rollback()` 後改用提取 `queue_item.id` 搭配原子性的 `update()` 語法更新狀態。這完全消除了不必要的 Lazy Load 查詢，大幅提升大量錯誤情況下的處理吞吐量。
   * **狀態**：**已解決（Resolved）**。

1. **擴充 `sanitize_error_message` 支援 IPv6 遮蔽**
   * **說明**：（已寫入 `requirements.md` §5.4 成為正式資安防禦規範）
   * **問題描述**：`crawler/utils.py` 中的 `sanitize_error_message` 函式目前僅能成功遮蔽 IPv4 位址。若未來目標伺服器回傳帶有 IPv6 位址的連線錯誤訊息，該 IP 仍可能會被明文暴露。
   * **修正方案**：已在 `crawler/utils.py` 的 `sanitize_error_message` 函式中加入能完整涵蓋標準與縮寫格式（含 `::`）的 IPv6 正則表達式，進一步阻絕 IPv6 位址洩漏的風險。
   * **狀態**：**已解決 (Resolved)**。

1. **修復全域日誌變數污染導致的任務追蹤失效 (Race Condition)**
   * **說明**：（已寫入 `requirements.md` §4.5 成為正式架構需求規範）
   * **問題描述**：`crawler/runner.py` 中使用了 `setattr(logging, "current_job_id", ...)` 的做法來注入日誌前綴。由於 `logging` 是全域模組，這會導致當多個 `JobRunner` 同時運行時，後啟動的任務會覆寫先啟動任務的 `job_id`，引發嚴重的 Race Condition 與日誌污染，使得多任務並發時的除錯追蹤功能失效。
   * **修正方案**：已將 `crawler/runner.py` 中全域的 `setattr(logging, ...)` 移除，改用 Python 原生的 `contextvars.ContextVar` 來儲存 `job_id`。由於 Python 的 `ThreadPoolExecutor` 會自動傳遞 context，這能確保在並發環境下安全地隔離，並正確標記個別任務的日誌。
   * **狀態**：**已解決 (Resolved)**。

1. **為關鍵操作日誌加入 `job_id` 上下文追蹤**
   * **說明**：（已寫入 `requirements.md` §4.5 成為正式架構需求規範）
   * **問題描述**：當有多個爬蟲任務在背景同時運行時，若日誌只印出正在爬取的 URL，維運人員無法區分該日誌屬於哪一個任務，增加多任務並發時的除錯難度。
   * **修正方案**：已透過在 `crawler/runner.py` 中全域覆寫 `logging.setLogRecordFactory`，於 `JobRunner` 初始化時將當前執行的 `job_id` 注入環境上下文。這讓所有 `CrawlerRunner` 與底層 `CrawlerCore` 的日誌輸出皆會自動帶上 `[Job <id>]` 的前綴，不僅達成目標，且完全無須逐一修改歷史程式碼中的 `logger.info()` 呼叫，為最優雅且無侵入式的解法。
   * **狀態**：**已解決 (Resolved)**。

1. **修復殭屍任務偵測僅依賴 PID 導致的重用誤判風險**
   * **說明**：（已寫入 `requirements.md` §4.3 成為正式容錯需求規範）
   * **問題描述**：Unix 系統的 PID 會循環重用。如果爬蟲意外崩潰，而作業系統剛好把同一個 PID 配發給了其他不相干的進程，原本單純檢查 `os.kill(pid, 0)` 的作法會誤以為爬蟲還活著，導致這個任務永遠卡在 `running` 成為無法中斷的殭屍狀態。
   * **修正方案**：已在 `backend/jobs/services/process.py` 實作防護機制。現在在寫入 PID 檔案時，會一併讀取 `/proc/{pid}/stat` 取出該進程的啟動時間 (starttime) 並寫入檔案。在後續驗證進程存活時，除了比對 PID，也會二次比對啟動時間。一旦發現 PID 存在但啟動時間不同，就能準確判斷這是被作業系統重用的進程，並立即將卡死的任務狀態設為 `error`。
   * **狀態**：**已解決 (Resolved)**。

1. **實作錯誤訊息與日誌的敏感資訊清洗機制**
   * **說明**：（已寫入 `requirements.md` §5.4 成為正式資安防禦規範）
   * **問題描述**：目前爬蟲底層若遇到連線錯誤，會把原始的錯誤字串直接寫入資料庫的 `error_message` 欄位或印到 Log 中。如果連線剛好帶有 Proxy 的密碼或是敏感的 Cookie，這些機密就會被明文存下來。
   * **修正方案**：已在 `crawler/utils.py` 實作 `sanitize_error_message` 函式，透過正規表達式主動遮蔽 URL 憑證 (`user:pass`)、HTTP Header (如 `Cookie`, `Authorization`) 的值，以及內含的 IPv4 位址。並已整合至 `crawler/runner.py` 的所有例外紀錄儲存點，徹底阻絕機密外洩風險。
   * **狀態**：**已解決 (Resolved)**。

1. **修復畸形網域 (IDNA) 解析例外導致爬蟲崩潰的風險**
   * **問題描述**：爬蟲在處理具有瑕疵的網址時，若遭遇 IDNA 編碼錯誤（如 `idna.IDNAError`），而系統目前的 `_FETCH_SAFE_EXCEPTIONS` 沒有捕捉到這個特定的例外，這會導致未處理的例外直接往上層拋，造成爬蟲任務意外崩潰。
   * **修正方案**：已在 `crawler/core.py` 引入 `idna` 套件，並將 `idna.IDNAError` 加入 `_FETCH_SAFE_EXCEPTIONS` 元組中，確保遇到格式錯誤的網域時能安全略過而不引發任務中斷。
   * **狀態**：**已解決 (Resolved)**。

1. **將外部連結檢查的 `ThreadPool` 數量調優**
   * **說明**：（已寫入 `requirements.md` §4.5 成為正式架構需求規範）
   * **問題描述**：外部連結探測是純 I/O 密集的操作，預設只開 5 個 Worker 數量過少，導致外部連結多的網頁爬取速度被嚴重拖慢。
   * **修正方案**：在 `crawler/runner.py` 中，將 `CRAWLER_MAX_WORKERS` 的預設值由 5 調大至 50，一舉提升 10 倍的外連並發探測吞吐量。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `_process_item` 非原子性 Commit 導致內外部連結資料不一致**
   * **說明**：（已寫入 `requirements.md` §3.4 成為正式架構需求規範）
   * **問題描述**：`_process_item` 先處理內部連結並 `session.commit()`，再處理外部連結並再次 `session.commit()`。若外部連結處理途中拋出例外，內部連結已入庫但外部連結遺失，且佇列項目狀態已被標記為 `completed`，形成資料不一致。
   * **修正方案**：移除中間的提早 `commit()`，改用 `session.flush()` 取得 ID；待 `_handle_internal_links` 與 `_handle_external_links` 均執行完畢後，才於 `_process_item` 末尾統一執行最後一次 `session.commit()`。
   * **狀態**：**已解決 (Resolved)**。

1. **修復 `_handle_error` 後缺少 `session.commit()` 導致狀態更新遺失**
   * **說明**：（已寫入 `requirements.md` §3.4 成為正式架構需求規範）
   * **問題描述**：`_process_item` 在捕捉 `httpx.HTTPError` 後呼叫 `_handle_error`，而 `_handle_error` 內部會先執行 `session.rollback()`，再修改 `queue_item` 的 `status`、`retry_count` 等屬性。但 `_handle_error` 回傳後，`_process_item` 沒有後續的 `session.commit()`，導致這些修改永遠不會寫入資料庫。結果是：永久性錯誤（404/403）的失敗狀態遺失、重試計數不遞增。
   * **修正方案**：在 `crawler/runner.py` 的 `except httpx.HTTPError` 區塊，於 `self._handle_error(...)` 呼叫後補上 `session.commit()`。
   * **狀態**：**已解決 (Resolved)**。

1. **全面盤查並修復進度數據 (progress_stats) 更新不一致的問題**
   * **說明**：（已寫入 `requirements.md` §3.4 成為正式架構需求規範）
   * **問題描述**：目前使用 `progress_stats` 來紀錄快取進度，但在「重新探測」部份連結後，或是發生其他非預期情況時，`progress_stats` 沒有正確同步更新，導致介面上「爬取進度」內的數據與實際狀況脫節。
   * **規劃方案**：全面盤查所有會更動內部或外部連結狀態的邏輯（尤其是重新探測、狀態變更等流程），確保每次狀態異動時，都會對應地重新計算並寫入最新的 `progress_stats`，以維持數據一致性與正確性。
   * **狀態**：**已解決 (Resolved)**。

---
