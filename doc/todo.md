# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。
為方便查找與追蹤，所有項目已依據「當前狀態」進行分區。

## 快速跳轉目錄

- [待排程 / 待優化 (Pending)](#待排程--待優化-pending)
  - [最優先（安全性、資料庫與基礎架構）](#最優先安全性資料庫與基礎架構)
  - [高優先（效能優化、核心精準度與程式品質）](#高優先效能優化核心精準度與程式品質)
  - [中優先（架構重構與中大型功能擴充）](#中優先架構重構與中大型功能擴充)
  - [低優先（邊緣需求與周邊工具）](#低優先邊緣需求與周邊工具)
- [進行中 / 部分完成 (In Progress)](#進行中--部分完成-in-progress)
- [觀察中 / 技術儲備 (Monitoring)](#觀察中--技術儲備-monitoring)
- [已解決 / 已完成 (Resolved / Completed)](#已解決--已完成-resolved--completed)
- [永久擱置 / 已移除 (Dropped / Removed)](#永久擱置--已移除-dropped--removed)

---

## 待排程 / 待優化 (Pending)

### 最優先（安全性、資料庫與基礎架構）

#### 1. 導入 Alembic 進行資料庫 Schema 遷移管理
* **功能描述**：目前專案在啟動時會直接透過 SQLAlchemy 的 `create_all()` 建立資料庫表。在生產環境下，若有後續的 Schema 異動（如新增欄位），無法做到自動化的增量遷移。
* **規劃方案**：引入 Alembic 作為雙資料庫（Auth DB 與 Crawler DB）的 Migration 工具，取代直接建表的方式，並將遷移腳本納入版本控制，以確保未來欄位更動時的安全性。
* **狀態**：**待後續優化（Pending Review）**。

#### 2. 全面修復與整合 Mypy 靜態型別檢查
* **功能描述**：目前專案雖已大規模採用 Type Hinting，但尚未達到完全無錯的狀態（掃描仍有百餘個 `mypy` 錯誤，主要為 `dict[str, object]` 協變性操作或測試檔參數型別等議題）。
* **規劃方案**：逐一排除剩餘的 `mypy` 型別報錯，待全站檢查通過後，再將 `mypy --explicit-package-bases backend/ crawler/ cli.py scripts/ test/` 正式納入開發者的 Workflow 檢驗清單與未來的 CI/CD 流程中，確保最高標準的靜態型別安全。
* **狀態**：**待後續優化（Pending Review）**。

#### 3. 導入關鍵字標籤的日誌分類與告警機制
* **問題描述**：目前系統中大多直接使用 `logger.error`，對於可能導致資料不一致或需立刻處理的嚴重錯誤，缺乏統一的關鍵字或 `logger.critical` 分類，不利於未來整合 ELK、Datadog 等監控告警系統。
* **規劃方案**：
  1. 盤點系統中可能引發資料損壞或不一致的極端例外場景。
  2. 統一引入特定的 Log 前綴（如 `[DATA_INCONSISTENCY_ALERT]`）或提升至 `logger.critical` 層級。
  3. 確保維運端能透過簡單的關鍵字或層級過濾，建立可靠的警報觸發規則。
* **狀態**：**待排程（Pending）**。

### 高優先（效能優化、核心精準度與程式品質）

### 中優先（架構重構與中大型功能擴充）

#### 4. 針對 crawler/core.py 引入 Strategy Pattern 的設計模式
* **功能描述**：目前 `crawler/core.py` 的主流程中（例如 `_fetch_single`, `_handle_http_failure_retry`, `_fallback_get` 等），混雜了許多不同的連線重試、降級與錯誤處理策略（像是自動升級 HTTPS、移除 Sec 標頭、呼叫 `curl_cffi` 備援等），導致核心程式碼較為龐大且邏輯交織。
* **規劃方案**：引入 Strategy Pattern（策略模式），將各種網路請求、重試機制及異常降級處理抽象化為獨立的策略類別或介面。這樣能將複雜的條件判斷從主迴圈中抽離，讓核心爬蟲流程更加乾淨、易讀，並大幅提升未來新增或替換連線策略時的彈性與可維護性。
* **狀態**：**待後續優化（Pending Review）**。

#### 5. 程式碼重構：明確區分內部與外部連結的命名
* **功能描述**：早期本專案是專注在外部連結，後來加入把內部連結也列入考量。但有些程式，因歷史因素，變數名或 API 名沒有區分外部與內部的差別。
* **規劃方案**：盤點現有程式碼與 API 設計，將未能明確表達「內部 (Internal)」與「外部 (External)」意圖的變數名稱、函式名稱及 API 端點進行重構與正名，以提升程式碼可讀性與維護性。
* **狀態**：**待後續優化（Pending Review）**。

#### 6. 擴充比對任務 (Job Diff) 支援內部連結與診斷邏輯優化
* **問題描述**：目前的任務歷史差異比對引擎 (Job Diff Engine) 僅針對「外部連結」進行比對分析。然而，目標網站的「內部連結」健康度同樣重要，目前卻未被納入比對範圍。此外，現有的比對診斷方式及分類標籤在面對複雜的狀態變化時，可能不夠精確，仍需要進一步的調整與優化。
* **規劃方案**：
  1. 擴充比對引擎，使其將「內部連結」的結果一併納入差異比對與分析範圍。
  2. 重新梳理並調整比對任務的診斷方式與分類邏輯，確保各種狀態變遷（例如新增失效、狀態復原、錯誤代碼改變等）都能被精準標示。
* **狀態**：**待排程（Pending）**。

#### 7. 爬蟲深度 (Depth) 監控與動態調整任務參數
* **問題描述**：目前使用者在任務執行期間，無法直觀地得知爬蟲當前探索到了哪一個層級 (Depth) 的內部連結。此外，如果任務在中途發現原本設定的 `max_depth` (最大深度) 或 `max_pages` (最大頁面數) 不符預期（例如想提早結束或擴大探索範圍），系統目前並不支援在任務執行過程中動態修改這些參數。
* **規劃方案**：
  1. **深度狀態顯示**：在前端任務進度監控介面中，新增顯示「當前爬蟲深度 (Current Depth)」，讓探索進度更透明。
  2. **動態參數調整**：實作對應的後端 API 與前端介面，允許使用者在任務「執行中」動態修改該任務的 `max_depth` 與 `max_pages` 限制，並讓爬蟲核心引擎能在下一次迭代時即時套用新設定。
* **狀態**：**待排程（Pending）**。

#### 12. 支援對「被忽略的內部連結」進行 HEAD 存活探測
* **問題描述**：目前系統對於符合「忽略副檔名」或「忽略路徑規則」的內部連結，會直接跳過不予處理。這導致使用者雖然不希望爬蟲深入抓取這些資源（如 PDF、圖片檔或特定目錄），但同時也無從得知這些連結「是否真的存在（避免死檔或斷鏈）」。
* **規劃方案**：
  1. 在任務設定或全域設定中新增一個選項，允許使用者對於被忽略的內部連結改用 `HEAD` 請求進行輕量級探測。
  2. 若探測結果為異常（如 404 Not Found 或 500 Server Error），應將該連結一併納入內部死鏈的錯誤報告中，以提升連結健康度診斷的覆蓋率。
* **狀態**：**待排程（Pending）**。

---

## 進行中 / 部分完成 (In Progress)

#### 13. 建立 MCP Server 以監控遠端 Production 任務狀態
* **問題描述**：開發者需要隨時查看 Production 環境中各項爬蟲任務的即時狀態，但目前必須登入後台網頁介面。希望能讓 AI 助理直接取得資料。
* **規劃方案**：建置一個 MCP (Model Context Protocol) 伺服器，直接連線至 `crawler.db` 提供任務清單與進度。為了不破壞現有 FastAPI 的穩定與安全性，採用獨立腳本 (`scripts/mcp_server.py`) 透過 SSH stdio 提供連線。
* **狀態**：**進行中 (In Progress)**。該 mcp 的功能尚待擴充。

#### 14. 前端程式碼重構：導入 MVC 或 Web Components 模組化封裝
* **問題描述**：目前前端程式碼（如 `frontend/js/job-detail.js` 與 `frontend/js/jobs.js`）存在大量的全域變數狀態與未封裝的 DOM 操作（義大利麵條式程式碼），缺乏模組化設計。這導致在處理複雜的動態資料流（如 SSE 即時更新、多條件過濾）時，程式碼高度耦合，難以追蹤錯誤與進行長期維護。
* **規劃方案**：遵循 `doc/requirements.md` 中的「前端狀態管理與元件封裝防呆」規範，全面重構現有的 Vanilla JS 程式碼。將各個獨立的 UI 區塊（例如：任務狀態卡片、數據表格、篩選面板等）封裝成獨立的類別 (Class) 或原生 Web Components (Custom Elements)。確保每個元件自行管理內部狀態與事件監聽，達成高內聚低耦合的架構。
* **狀態**：**部分完成（Partially Completed）**。已完成多數 Web Components 提取，但負責協調的「Controller/State 層」（即 `job-detail.js` 和 `jobs.js`）尚未完成。

#### 15. 擴充與完善系統輔助說明 (Help & FAQ)
* **功能描述**：目前前端的 `help.html` 與 `faq.html` 已建立基礎架構，但部分教學內容與問答細節尚待補齊。
* **規劃方案**：將 `frontend/help.html` 的支援與說明教學內容，以及 `frontend/faq.html` 的常見問答內容補充完整，提供使用者更詳盡的操作指引與問題排解。
* **狀態**：**部分完成（Partially Completed）**。

---

## 觀察中 / 技術儲備 (Monitoring)

---

## 已解決 / 已完成 (Resolved / Completed)

#### 8. 將通知與信件發送系統解耦至事件驅動 (Event-driven Notification)
* **問題描述**：目前 `backend/deps.py` 建立 `JobManager` 時，將 `send_job_status_notification` 當作 Callback 綁定，這讓任務管理核心與外部通知業務邏輯產生了高度耦合。
* **規劃方案**：任務狀態改變時僅由核心發佈 `job_status_changed` 事件，由通知模組獨立訂閱該事件。不僅解除耦合，也確保發送信件的延遲或失敗不會影響主流程。
* **狀態**：**已解決（Resolved）**。

#### 9. [已完成] 引入管理員操作稽核日誌事件 (Audit Logging via Events)
* **問題描述**：目前的管理員操作（例如 config_change, job_takeover, user_deleted）會在 API 路由中手動寫入 Log 資料，導致 API 職責過於龐雜。
* **規劃方案**：API 只需負責執行業務邏輯，成功後發佈如 `user_deleted` 等事件。建立一個獨立的 `AuditLogService` 訂閱所有關鍵事件並統一寫入資料庫，提升 API 的整潔度與未來擴充性。
* **狀態**：**已解決（Resolved）** - 已實作 AuditLogService 並於各 API 點觸發對應事件。

#### 16. DNS 快取無過期機制（R7-04）
* **問題描述**（來源：Code Review v3.0 R7-04）：爬蟲工具 `resolve_ip` 使用了 `@functools.lru_cache(maxsize=1024)` 進行 DNS 快取，但此內建快取缺乏過期時間 (TTL) 機制。若爬蟲任務執行時間過長，且目標網站使用了 CDN 並頻繁切換 IP，可能會因快取命中舊 IP 而導致連線失敗與誤判。
* **規劃方案**：引入 `cachetools.TTLCache` 取代內建的 `lru_cache`，為 DNS 快取設定合理的存活時間（例如 5 到 10 分鐘），時間到期後強制重新查詢 DNS，確保取得最新的 IP。
* **相關位置**：`crawler/utils.py` L63-L85
* **狀態**：**已解決（Resolved）** - 已引入 `cachetools.TTLCache` 替換原有的 `lru_cache`，並設定 300 秒 (5 分鐘) 的 TTL。

#### 17. 後台任務監控新增「強制取回」、「任務備份匯出」與「任務匯入」操作
* **問題描述**：目前在後台 (`frontend/admin.html`) 的任務監控介面中，針對任務的維運操作尚不夠完整：
  1. 若任務因故卡死（例如進程異常終止導致狀態未更新），缺乏讓管理員強制接管重啟的機制。
  2. 目前任務的資料庫備份與復原只能透過 CLI 腳本 (`job_sync.sh`) 執行，這對於一般管理員來說不夠直覺，也不便於將任務匯出與轉移。
* **規劃方案**：在任務監控與後台介面中增加以下功能：
  1. 「強制取回 (Force Resume / Retrieve)」按鈕：透過後端 API 強制釋放卡死的任務鎖或重設任務狀態，以利在需要時能夠順利重新啟動該任務。**注意：針對本身即為管理員自己建立的任務，不應顯示此按鈕，避免混淆**。
  2. 「匯出 (Export Backup)」按鈕：比照 `job_sync.sh export` 的格式與邏輯，允許管理員直接在任務列表將特定任務打包為備份檔 (如 ZIP) 下載。
  3. 「匯入任務 (Import Backup)」功能：在 `frontend/admin.html` 提供匯入入口，比照 `job_sync.sh import` 邏輯，允許管理員上傳備份檔並將任務還原至系統中。實作上需注意 CSP 規範（不得使用 Inline Event Handlers），並加上完善的上傳進度防呆機制（按鈕鎖定、防跳出對話框）。
* **狀態**：**已解決（Resolved）**。

#### 18. 補強爬蟲 HTML 標籤解析的邊角案例與盲點
* **問題描述**：目前 `crawler/core.py` 針對部分 HTML 標籤的解析處理尚有遺漏：
  1. 對 `<link>` 標籤抓取過於寬鬆：目前僅排除 `dns-prefetch` 與 `preconnect`，導致如 `<link rel="preload">`、`<link rel="alternate">` 等非必要資源被抓取，可能引發無效的重複連線或下載非預期的二進位檔案。
  2. 遺漏多媒體標籤：`tag_attr_map` 遺漏了現代網頁極為重要的 `<source>` (`src`, `srcset`) 與 `<track>` (`src`) 標籤，導致 `<video>`、`<audio>` 以及 `<picture>` 的內部資源斷鏈無法被偵測。
* **執行結果**：已於 `crawler/core.py` 的 `tag_attr_map` 中加入 `"source": "src"` 與 `"track": "src"`，並在 `<link>` 解析規則中額外排除 `preload` 與 `alternate` 屬性。
* **狀態**：**已解決（Resolved）**。

#### 19. 實作應用層快取 (Application Caching)
* **功能描述**：針對已完成或異常終止的任務，其外連結果與報表是靜態的。目前切換聚合模式會重複消耗運算資源。
* **執行結果**：已引入 `cachetools`，並實作 TTL 快取工具 (`cache_utils.py`)，針對靜態任務的摘要與差異比對 API 端點 (`results/summary`, `internal-results/summary`, `diff`) 加入記憶體快取，大幅縮短載入時間並減輕 CPU 負擔。
* **狀態**：**已解決（Resolved）**。

#### 20. 修復前端詳情頁重複觸發 API 的問題 (UI Initialization Side Effects)
* **問題描述**：目前前端在載入「任務詳情頁 (Job Detail)」時，會導致在極短時間內對 `results/summary` 與 `internal-results/summary` 各發送兩次完全相同的 `GET` 請求。
* **執行結果**：經查證，根本原因為 `refreshJobDetail` 具備在任務結束或暫停時自動呼叫 `loadResults` 的副作用，導致上層初始化流程發生重複呼叫。已將該副作用移除，改由具體的事件操作（如重新探測、暫停任務後）明確呼叫對應的加載函式，從源頭徹底解決此問題。
* **狀態**：**已解決（Resolved）**。

#### 21. 解除 auth/service.py 與 deps.py 的循環依賴問題（R3-02）
* **問題描述**（來源：Code Review v3.0 R3-02）：在 `backend/auth/service.py` 的 `cleanup_deleted_user_task` 中，目前是透過在函式體內延遲導入（Lazy Import）`from backend.deps import get_job_manager` 來迴避與 `backend/deps.py` 的循環依賴問題。這是一種架構上的 Code Smell，意味著授權模組與任務模組邊界耦合。
* **規劃方案**：
  1. **抽離中介服務**：建立獨立的 `backend/cleanup_service.py`，統籌呼叫 Auth 和 Crawler 模組的刪除邏輯。
  2. **事件驅動 (Event-Driven)**：當 Auth DB 刪除使用者時發布 `UserDeletedEvent`，由 Crawler 模組監聽事件後自行刪除相關任務，達成徹底解耦。
* **相關位置**：`backend/auth/service.py` L603-L612
* **狀態**：**已解決（Resolved）** - 已成功建立輕量級事件匯流排 (`backend/events.py`) 並完全解除依賴。

#### 22. 解決 SSE 迴圈的同步阻塞問題（R1-01）
* **問題描述**（來源：Code Review v3.0 R1-01）：後端 `stream_job_updates` 在處理前端的 SSE (Server-Sent Events) 連線時，會因為無限輪詢導致 Thread Pool 被佔滿。
* **規劃方案**：
  1. **短期解法**：將輪詢的 Sleep 時間加長。
  2. **長期解法**：引入集中式背景輪詢器 `JobProgressPoller` 與內部事件匯流排 (`backend/events.py`)。由單一 Task 收集活躍任務更新，透過 Event Bus 廣播至所有 SSE 客戶端的 Async Queue，將資料庫負載從 O(N) 降至 O(1)。
* **相關位置**：`backend/jobs/routers/management.py`, `backend/jobs/services/poller.py`
* **狀態**：**已解決（Resolved）**。

---

## 永久擱置 / 已移除 (Dropped / Removed)

以下項目經評估後認為過度設計或效益極低，已決定擱置不再實作。

#### 10. 透過事件機制實作全域設定與快取自動更新 (Cache Invalidation)
* **問題描述**：當管理員修改全域設定（如 SMTP 設定）或使用者權限被停權時，目前的系統若引入 Memory Cache，將面臨資料不同步的風險。
* **規劃方案**：發布 `config_updated` 或 `user_permission_changed` 等系統事件，讓具備 In-memory Cache 的元件訂閱並自動清除或重新載入最新資料，避免反覆查詢資料庫驗證。
* **狀態**：**已擱置（Dropped）** - 原因：目前快取僅針對靜態的歷史任務診斷結果，並不會因為全域設定或使用者權限異動而導致資料不同步，因此無需實作複雜的快取更新事件。

#### 11. 透過事件機制實作統計與報表聚合 (Metrics Aggregation)
* **問題描述**：若未來需統計「系統每日執行任務數」、「平均爬蟲時間」等指標，若直接修改核心邏輯會增加系統複雜度與負擔。
* **規劃方案**：建立獨立的報表服務，專門訂閱 `job_completed` 或 `job_created` 事件，在背景非同步地累加統計數字，完全不干擾核心 API 的運作。
* **狀態**：**已擱置（Dropped）** - 原因：系統目前主要需求為「針對單一任務的診斷報告」，並無跨任務的大型數據統計看板需求。直接修改核心或增加獨立報表服務屬過度設計。
### 低優先（邊緣需求與周邊工具）

#### 23. 實作全局 API 速率限制 (Global Rate Limiting)
* **功能描述**：目前僅有登入鎖定和忘記密碼的個別限速保護，沒有全局 API Rate Limiting Middleware，若面臨大量異常請求可能會佔用過多伺服器資源。
* **規劃方案**：在反向代理層 (如 Nginx) 或是應用層 (如引入 SlowApi 或客製化 FastAPI Middleware) 補充全局 API 速率限制機制，保護伺服器免於遭受 DoS 或高頻惡意請求。
* **狀態**：**已擱置（Dropped）** - 原因：API 速率限制通常交由反向代理層（如 Nginx、Cloudflare）處理，在應用層實作會增加不必要的效能開銷與維護成本，對於內部使用的工具而言屬於過度設計。

#### 24. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**已擱置（Dropped）** - 原因：引入 Celery 或 Redis 等外部依賴會大幅增加專案的部署難度與架構複雜度。目前的 `ThreadPoolExecutor` 已經足夠應付單機環境下的效能需求，維持輕量級部署更符合本專案的定位。

#### 25. CLI 支援匯出內部紀錄之狀態篩選 (export-internal filter)
* **功能描述**：目前 CLI 的 `--export-internal` 參數不支援使用 `--filter` 進行精確狀態篩選，會無條件匯出全部的內部頁面（包含成功與各種失敗）。雖然 Web API 的 `InternalResultQuery` 已具備過濾能力，但尚未整合至命令列工具中。
* **規劃方案**：擴充 `cli.py` 中關於 `--export-internal` 的參數解析邏輯，使其能夠接收與處理 `--filter` 參數（例如支援 `not_found`, `server_error` 等），並將此參數對接傳遞給底層的匯出服務 (`export_internal_job_results`)。
* **狀態**：**已擱置（Dropped）** - 原因：CLI 主要用於自動化或 CI 環境，使用者通常會將完整結果輸出為 JSON 後再利用 `jq` 進行處理。將複雜的過濾邏輯重複實作在 CLI 參數中不但效益低，也會增加開發負擔。Web 介面已經提供完整的篩選功能。

#### 26. CSRF Token 與 Session 綁定（R2-02）
* **問題描述**（來源：Code Review v3.0 R2-02）：目前 CSRF 防護採用 Double Submit Cookie 模式（驗證 Cookie 與 Header 中的 Token 是否一致），並未將 Token 密碼學綁定至特定使用者的 Session。若發生子網域（Subdomain）遭攻破，駭客有可能偽造 Cookie，進而繞過 CSRF 驗證。
* **規劃方案**：在生成 CSRF Token 時，引入 HMAC 機制，以使用者的 Session ID 作為金鑰對 Token 進行簽章。後端驗證時一併檢查該簽章是否合法，防止 Token 遭偽造。
* **相關位置**：`backend/auth/router.py` L223-L228
* **狀態**：**已擱置（Dropped）** - 原因：本專案並未牽涉到複雜的子網域架構。目前的 `SameSite=Strict` Cookie 加上標準的 Double Submit Cookie 模式已經足以防禦絕大部分的 CSRF 攻擊。HMAC 綁定實作複雜度高但帶來的實際安全效益邊際遞減。
