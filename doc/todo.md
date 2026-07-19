# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。
為方便查找與追蹤，所有項目已依據「當前狀態」進行分區。

## 快速跳轉目錄

- [待排程 / 待優化 (Pending)](#待排程--待優化-pending)
  - [最優先（安全性、資料庫與基礎架構）](#最優先安全性資料庫與基礎架構)
  - [高優先（效能優化、核心精準度與程式品質）](#高優先效能優化核心精準度與程式品質)
  - [中優先（中大型功能擴充）](#中優先中大型功能擴充)
  - [低優先（邊緣需求與周邊工具）](#低優先邊緣需求與周邊工具)
- [進行中 / 部分完成 (In Progress)](#進行中--部分完成-in-progress)
- [觀察中 / 長期規劃 (Monitoring)](#觀察中--長期規劃-monitoring)
- [已解決 / 已完成 (Resolved / Completed)](#已解決--已完成-resolved--completed)
- [永久擱置 / 已移除 (Dropped / Removed)](#永久擱置--已移除-dropped--removed)

---

## 待排程 / 待優化 (Pending)

### 最優先（安全性、資料庫與基礎架構）

*目前無項目。*

### 高優先（效能優化、核心精準度與程式品質）

1. **擴充比對任務 (Job Diff) 支援內部連結與診斷邏輯優化**
   * **問題描述**：目前的任務歷史差異比對引擎 (Job Diff Engine) 僅針對「外部連結」進行比對分析。然而，目標網站的「內部連結」健康度同樣重要，目前卻未被納入比對範圍。此外，現有的比對診斷方式及分類標籤在面對複雜的狀態變化時，可能不夠精確，仍需要進一步的調整與優化。
   * **規劃方案**：
     1. 擴充比對引擎，使其將「內部連結」的結果一併納入差異比對與分析範圍。
     2. 重新梳理並調整比對任務的診斷方式與分類邏輯，確保各種狀態變遷（例如新增失效、狀態復原、錯誤代碼改變等）都能被精準標示。
   * **狀態**：**待排程（Pending）**。

1. **導入 Alembic 進行資料庫 Schema 遷移管理**
   * **功能描述**：目前專案在啟動時會直接透過 SQLAlchemy 的 `create_all()` 建立資料庫表。在生產環境下，若有後續的 Schema 異動（如新增欄位），無法做到自動化的增量遷移。
   * **規劃方案**：引入 Alembic 作為雙資料庫（Auth DB 與 Crawler DB）的 Migration 工具，取代直接建表的方式，並將遷移腳本納入版本控制，以確保未來欄位更動時的安全性。
   * **狀態**：**待排程（Pending）**。

### 中優先（中大型功能擴充）

1. **支援對「被忽略的內部連結」進行 HEAD 存活探測**
   * **問題描述**：目前系統對於符合「忽略副檔名」或「忽略路徑規則」的內部連結，會直接跳過不予處理。這導致使用者雖然不希望爬蟲深入抓取這些資源（如 PDF、圖片檔或特定目錄），但同時也無從得知這些連結「是否真的存在（避免死檔或斷鏈）」。
   * **規劃方案**：
     1. 在任務設定或全域設定中新增一個選項，允許使用者對於被忽略的內部連結改用 `HEAD` 請求進行輕量級探測。
     2. 若探測結果為異常（如 404 Not Found 或 500 Server Error），應將該連結一併納入內部死鏈的錯誤報告中，以提升連結健康度診斷的覆蓋率。
   * **狀態**：**待排程（Pending）**。

1. **爬蟲深度 (Depth) 監控與動態調整任務參數**
   * **問題描述**：目前使用者在任務執行期間，無法直觀地得知爬蟲當前探索到了哪一個層級 (Depth) 的內部連結。此外，如果任務在中途發現原本設定的 `max_depth` (最大深度) 或 `max_pages` (最大頁面數) 不符預期（例如想提早結束或擴大探索範圍），系統目前並不支援在任務執行過程中動態修改這些參數。
   * **規劃方案**：
     1. **深度狀態顯示**：在前端任務進度監控介面中，新增顯示「當前爬蟲深度 (Current Depth)」，讓探索進度更透明。
     2. **動態參數調整**：實作對應的後端 API 與前端介面，允許使用者在任務「執行中」動態修改該任務的 `max_depth` 與 `max_pages` 限制，並讓爬蟲核心引擎能在下一次迭代時即時套用新設定。
   * **狀態**：**待排程（Pending）**。

1. **實作雲端測試 MCP 與本地/雲端結果比對 Skill**
   * **問題描述**：同一個連結在本地端用 `scripts/test_ext.py` 或 `scripts/test_url.py` 測試時可能成功，但在雲端主機測試時，偶爾會因為目標主機的防禦策略（例如阻擋雲端 IP 或資料中心網段）而失敗。這導致難以釐清是連結真的失效，還是防禦策略造成的誤判。
   * **規劃方案**：
     1. **新增 MCP 功能**：擴充現有 MCP 伺服器，提供能在遠端（雲端主機）執行單一連結探測並回傳詳細結果與狀態碼的功能。
     2. **新增 Agent Skill**：建立一個新的 Skill，用於接收特定連結後，自動同時觸發本地端測試與雲端 MCP 測試，並交叉比對兩者結果。若本地成功而雲端失敗，即可明確判斷為目標主機防禦策略所致。
   * **狀態**：**已解決（Resolved）**。

### 低優先（邊緣需求與周邊工具）

1. **前端 CSS 樣式清理 (Clean up unused CSS styles)**
   * **問題描述**：隨著專案演進與 UI 元件重構，前端可能殘留了許多不再使用的 Vanilla CSS 樣式與 Class。這些冗餘代碼會無謂地增加檔案體積，並降低樣式表的可維護性。
   * **規劃方案**：盤點前端目錄下的 HTML 與 CSS 檔案，找出從未被引用或已被廢棄的 CSS class 並予以移除，確保前端資源保持極致輕量與乾淨。
   * **狀態**：**待排程（Pending）**。

---

## 進行中 / 部分完成 (In Progress)

1. **前端程式碼重構：導入 MVC 或 Web Components 模組化封裝**
   * **問題描述**：目前前端程式碼（如 `frontend/js/job-detail.js` 與 `frontend/js/jobs.js`）存在大量的全域變數狀態與未封裝的 DOM 操作（義大利麵條式程式碼），缺乏模組化設計。這導致在處理複雜的動態資料流（如 SSE 即時更新、多條件過濾）時，程式碼高度耦合，難以追蹤錯誤與進行長期維護。
   * **規劃方案**：遵循 `doc/requirements.md` 中的「前端狀態管理與元件封裝防呆」規範，全面重構現有的 Vanilla JS 程式碼。將各個獨立的 UI 區塊（例如：任務狀態卡片、數據表格、篩選面板等）封裝成獨立的類別 (Class) 或原生 Web Components (Custom Elements)。確保每個元件自行管理內部狀態與事件監聽，達成高內聚低耦合的架構。
   * **狀態**：**部分完成（Partially Completed）**。已完成多數 Web Components 提取，但負責協調的「Controller/State 層」（即 `job-detail.js` 和 `jobs.js`）尚未完成。

1. **建立 MCP Server 以監控遠端 Production 任務狀態**
   * **問題描述**：開發者需要隨時查看 Production 環境中各項爬蟲任務的即時狀態，但目前必須登入後台網頁介面。希望能讓 AI 助理直接取得資料。
   * **規劃方案**：建置一個 MCP (Model Context Protocol) 伺服器，直接連線至 `crawler.db` 提供任務清單與進度。為了不破壞現有 FastAPI 的穩定與安全性，採用獨立腳本 (`scripts/mcp_server.py`) 透過 SSH stdio 提供連線。
   * **狀態**：**部分完成（Partially Completed）**。該 mcp 的功能尚待擴充。

1. **擴充與完善系統輔助說明 (Help & FAQ)**
   * **功能描述**：目前前端的 `help.html` 與 `faq.html` 已建立基礎架構，但部分教學內容與問答細節尚待補齊。
   * **規劃方案**：將 `frontend/help.html` 的支援與說明教學內容，以及 `frontend/faq.html` 的常見問答內容補充完整，提供使用者更詳盡的操作指引與問題排解。
   * **狀態**：**部分完成（Partially Completed）**。

---

## 觀察中 / 長期規劃 (Monitoring)

1. **實作雙資料庫軟刪除 (Soft Delete) 與背景清理機制**
   * **現狀描述**：規格書 **§4.1** 明確要求跨資料庫資源刪除時，應採軟刪除機制以確保最終一致性。但在當前架構下，跨資料庫的資源關聯極少頻繁變動，且全面改用軟刪除需改寫幾乎所有 SQLAlchemy 查詢以過濾 `deleted_at`。
   * **改善建議**：引入軟刪除機制與背景非同步清理腳本。
   * **狀態**：**觀察中（Monitoring）**。目前實體硬刪除 (Hard Delete) 在現行架構下運作良好且影響極小，列為技術債監控，待未來進行資料庫層的重大重構時再一併實作。

1. **針對 crawler/core.py 引入 Strategy Pattern 的設計模式**
   * **現狀描述**：目前 `crawler/core.py` 的主流程混雜了許多不同的連線重試、降級與錯誤處理策略，導致核心程式碼較為龐大且邏輯交織。
   * **改善建議**：引入 Strategy Pattern（策略模式），將各種網路請求、重試機制抽象化為獨立的策略類別或介面。
   * **狀態**：**觀察中（Monitoring）**。目前邏輯運作正常，不需急於拆解，可留待未來若有大規模連線策略重構需求時再一併進行。

1. **解耦 `crawler` 模組對 `backend.events` 的反向依賴**
   * **現狀描述**：爬蟲模組直接 `import` 了 `backend` 的事件匯流排。雖然規格書規定 CLI-First，但目前 CLI 執行時連帶載入 backend 並無嚴重副作用。
   * **改善建議**：將事件通知改為依賴注入或回呼函式機制，徹底解除耦合。
   * **狀態**：**觀察中（Monitoring）**。由於涉及較大範圍的架構調整且目前無明顯 Bug，列為未來架構翻新時的長期任務。

1. **程式碼重構：明確區分內部與外部連結的命名**
   * **現狀描述**：因歷史因素，部分變數與 API 命名未能精確區分內部與外部連結。
   * **改善建議**：盤點現有程式碼與 API 設計進行正名。
   * **狀態**：**觀察中（Monitoring）**。屬於大規模的重構與字串替換，風險較高且目前不影響功能，可待未來 API 版本升級時處理。

1. **任務狀態轉換缺乏資料庫層面約束**
   * **位置**: `crawler/models.py` `Job` 模型、`crawler/manager.py` 各狀態變更方法  
   * **現狀描述**: 狀態轉換僅在應用層檢查 (如 `pause_job` 檢查 `status in ("running", "pending", ...)`)，資料庫無 `CHECK CONSTRAINT` 或 Trigger 防止非法轉換 (如 `completed` -> `running`)。並發請求可能繞過應用層檢查。  
   * **改善建議**: 
     1. 在資料庫加入 `CHECK (status IN (...))`。
     1. 關鍵轉換 (如 `queued` -> `starting`) 使用 `SELECT FOR UPDATE` 或樂觀鎖 (`version` 欄位) 確保原子性。
   * **狀態**：**觀察中（Monitoring）**。Uvicorn 單 worker 情況下，目前架構足夠安全，暫時不處理。

1. **`socket.getaddrinfo` 的 Monkey Patch 副作用與 Async 隱患**
   * **問題描述**：目前為了支援自訂 DNS 解析（例如防禦 SSRF 或是本機測試），爬蟲模組全域攔截了 `socket.getaddrinfo`，並使用 `threading.local()` 來隔離不同執行緒的覆寫規則。這樣做有兩個潛在問題：
     1. 會影響同一個執行緒上所有依賴底層 `socket` 的第三方套件，可能導致非預期的網路路由。
     2. 若未來爬蟲引擎改用非同步 (`asyncio`) 併發執行，`threading.local()` 無法在同一個執行緒內的不同 Coroutine 之間隔離狀態，會造成嚴重的 Race Condition（覆寫規則互相污染）。
   * **改善建議**：未來若重構為非同步架構，應改用 `contextvars` 來取代 `threading.local`，或是直接利用 HTTP 客戶端（如 `httpx.AsyncClient`）內建的 DNS resolver 攔截機制，徹底移除全域的 Monkey Patch。
   * **狀態**：**觀察中（Monitoring）**。在目前的架構下（爬蟲任務在獨立執行緒中同步執行），不同任務的 DNS 覆寫能被正確隔離，暫時不受影響。

1. **FastAPI 同步端點 (`def`) 潛在的 ThreadPool 瓶頸**
   * **問題描述**：目前幾乎所有的 FastAPI API 端點皆使用同步函式 (`def`)。這在底層使用 SQLAlchemy 同步 ORM (`Session`) 時是完全正確的做法，能讓 FastAPI 將請求轉交給外部的 ThreadPool 執行，避免阻塞主事件迴圈。
   * **改善建議**：若未來 API 請求併發量極大，預設的 Starlette ThreadPool 數量 (約 40) 可能會成為瓶頸。屆時需調大 ThreadPool 的數量，或逐步將資料庫引擎遷移至非同步 (`asyncio` + `AsyncSession`) 架構。
   * **狀態**：**觀察中（Monitoring）**。在目前的流量與架構下是安全且最佳的實作，作為未來擴展時的長期規劃即可。

1. **外部連結探測的 `ThreadPoolExecutor` 缺乏優雅關閉與例外傳播機制**
   * **位置**: `crawler/runner.py` (執行外部連結探測的迴圈)
   * **問題描述**：目前外部連結檢查使用 `ThreadPoolExecutor`。雖然 `finally` 區塊呼叫了 `executor.shutdown(wait=True, cancel_futures=True)`，但若主迴圈發生例外中斷，池中正在等待 HTTP 網路 I/O 的任務可能無法被立即中斷，這取決於底層 `httpx` 的行為，有極低的機率造成連線資源短暫殘留。
   * **改善建議**：未來若要進一步提升爬蟲網路 I/O 效能與資源回收能力，建議將外部連結探測遷移至純 Async 協程架構 (`asyncio` + `httpx.AsyncClient`)，獲得更好的取消語意與併發能力。
   * **狀態**：**觀察中（Monitoring）**。屬於未來架構重構方向的長期規劃。

1. **資料庫 Schema 精簡與體積最佳化 (Database Size Optimization)**
   * **問題描述**：目前爬蟲系統儲存的歷史紀錄與佇列，會消耗極大的資料庫空間。字串冗餘（如相同的網址字串重複儲存）、低效型別（如 UUID 存為 36-byte 字串、狀態存為字串），以及長網址放入 B-Tree 索引造成的索引膨脹，皆會導致資料庫磁碟耗用過快。
   * **改善建議**：
     1. **網址正規化 (URL Normalization)**：將冗長且重複的 `url`、`source_url`、`target_url` 抽離至獨立的 URL 表格，並改用整數 ID 關聯。
     2. **UUID 原生型別**：將 `job_id` 等 UUID 欄位從 `String(36)` 改用原生 16-byte 二進位或 PostgreSQL 的原生 `UUID` 型別。
     3. **Hash 索引 (Hash Indexing)**：對長網址先計算 MD5 或 SHA-256 建立短欄位（如 `url_hash`）並建構索引，大幅消除長字串造成的 B-Tree 索引膨脹。
     4. **狀態欄位瘦身**：將 `status` 與 `status_category` 從 `String` 改為原生 `ENUM` 或是 `SmallInteger` 整數常數。
     5. **採用 JSONB**：若遷移至 PostgreSQL，將 `progress_stats` 等 JSON 欄位改為 `JSONB` 以獲得更好的二進位壓縮比。
   * **狀態**：**觀察中（Monitoring）**。若未來爬蟲資料量成長且造成嚴重的儲存空間瓶頸，再行評估啟動大規模 Schema 遷移計畫。

---

## 已解決 / 已完成 (Resolved / Completed)

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
   * **問題描述**：`crawler/utils.py` 中的 `sanitize_error_message` 函式目前僅能成功遮蔽 IPv4 位址。若未來目標伺服器回傳帶有 IPv6 位址的連線錯誤訊息，該 IP 仍可能會被明文暴露。
   * **修正方案**：已在 `crawler/utils.py` 的 `sanitize_error_message` 函式中加入能完整涵蓋標準與縮寫格式（含 `::`）的 IPv6 正則表達式，進一步阻絕 IPv6 位址洩漏的風險。
   * **狀態**：**已解決（Resolved）**。（已寫入 `requirements.md` 成為正式資安需求）

1. **修復全域日誌變數污染導致的任務追蹤失效 (Race Condition)**
   * **問題描述**：`crawler/runner.py` 中使用了 `setattr(logging, "current_job_id", ...)` 的做法來注入日誌前綴。由於 `logging` 是全域模組，這會導致當多個 `JobRunner` 同時運行時，後啟動的任務會覆寫先啟動任務的 `job_id`，引發嚴重的 Race Condition 與日誌污染，使得多任務並發時的除錯追蹤功能失效。
   * **修正方案**：已將 `crawler/runner.py` 中全域的 `setattr(logging, ...)` 移除，改用 Python 原生的 `contextvars.ContextVar` 來儲存 `job_id`。由於 Python 的 `ThreadPoolExecutor` 會自動傳遞 context，這能確保在並發環境下安全地隔離，並正確標記個別任務的日誌。
   * **狀態**：**已解決（Resolved）**。（已寫入 `requirements.md` 成為正式架構需求）

1. **為關鍵操作日誌加入 `job_id` 上下文追蹤**
   * **問題描述**：當有多個爬蟲任務在背景同時運行時，若日誌只印出正在爬取的 URL，維運人員無法區分該日誌屬於哪一個任務，增加多任務並發時的除錯難度。
   * **修正方案**：已透過在 `crawler/runner.py` 中全域覆寫 `logging.setLogRecordFactory`，於 `JobRunner` 初始化時將當前執行的 `job_id` 注入環境上下文。這讓所有 `CrawlerRunner` 與底層 `CrawlerCore` 的日誌輸出皆會自動帶上 `[Job <id>]` 的前綴，不僅達成目標，且完全無須逐一修改歷史程式碼中的 `logger.info()` 呼叫，為最優雅且無侵入式的解法。
   * **狀態**：**已解決（Resolved）**。（已寫入 `requirements.md` 成為正式架構需求）

1. **修復殭屍任務偵測僅依賴 PID 導致的重用誤判風險**
   * **問題描述**：Unix 系統的 PID 會循環重用。如果爬蟲意外崩潰，而作業系統剛好把同一個 PID 配發給了其他不相干的進程，原本單純檢查 `os.kill(pid, 0)` 的作法會誤以為爬蟲還活著，導致這個任務永遠卡在 `running` 成為無法中斷的殭屍狀態。
   * **修正方案**：已在 `backend/jobs/services/process.py` 實作防護機制。現在在寫入 PID 檔案時，會一併讀取 `/proc/{pid}/stat` 取出該進程的啟動時間 (starttime) 並寫入檔案。在後續驗證進程存活時，除了比對 PID，也會二次比對啟動時間。一旦發現 PID 存在但啟動時間不同，就能準確判斷這是被作業系統重用的進程，並立即將卡死的任務狀態設為 `error`。
   * **狀態**：**已解決（Resolved）**。（已寫入 `requirements.md` 成為正式容錯需求）

1. **實作錯誤訊息與日誌的敏感資訊清洗機制**
   * **問題描述**：目前爬蟲底層若遇到連線錯誤，會把原始的錯誤字串直接寫入資料庫的 `error_message` 欄位或印到 Log 中。如果連線剛好帶有 Proxy 的密碼或是敏感的 Cookie，這些機密就會被明文存下來。
   * **修正方案**：已在 `crawler/utils.py` 實作 `sanitize_error_message` 函式，透過正規表達式主動遮蔽 URL 憑證 (`user:pass`)、HTTP Header (如 `Cookie`, `Authorization`) 的值，以及內含的 IPv4 位址。並已整合至 `crawler/runner.py` 的所有例外紀錄儲存點，徹底阻絕機密外洩風險。
   * **狀態**：**已解決（Resolved）**。（已寫入 `requirements.md` 成為正式資安需求）

1. **修復畸形網域 (IDNA) 解析例外導致爬蟲崩潰的風險**
   * **問題描述**：爬蟲在處理具有瑕疵的網址時，若遭遇 IDNA 編碼錯誤（如 `idna.IDNAError`），而系統目前的 `_FETCH_SAFE_EXCEPTIONS` 沒有捕捉到這個特定的例外，這會導致未處理的例外直接往上層拋，造成爬蟲任務意外崩潰。
   * **修正方案**：已在 `crawler/core.py` 引入 `idna` 套件，並將 `idna.IDNAError` 加入 `_FETCH_SAFE_EXCEPTIONS` 元組中，確保遇到格式錯誤的網域時能安全略過而不引發任務中斷。
   * **狀態**：**已解決（Resolved）**。

1. **將外部連結檢查的 `ThreadPool` 數量調優**
   * **問題描述**：外部連結探測是純 I/O 密集的操作，預設只開 5 個 Worker 數量過少，導致外部連結多的網頁爬取速度被嚴重拖慢。
   * **修正方案**：在 `crawler/runner.py` 中，將 `CRAWLER_MAX_WORKERS` 的預設值由 5 調大至 50，一舉提升 10 倍的外連並發探測吞吐量。
   * **狀態**：**已解決（Resolved）**。

1. **修復 `_process_item` 非原子性 Commit 導致內外部連結資料不一致**
   * **問題描述**：`_process_item` 先處理內部連結並 `session.commit()`，再處理外部連結並再次 `session.commit()`。若外部連結處理途中拋出例外，內部連結已入庫但外部連結遺失，且佇列項目狀態已被標記為 `completed`，形成資料不一致。
   * **修正方案**：移除中間的提早 `commit()`，改用 `session.flush()` 取得 ID；待 `_handle_internal_links` 與 `_handle_external_links` 均執行完畢後，才於 `_process_item` 末尾統一執行最後一次 `session.commit()`。
   * **狀態**：**已解決（Resolved）**。

1. **修復 `_handle_error` 後缺少 `session.commit()` 導致狀態更新遺失**
   * **問題描述**：`_process_item` 在捕捉 `httpx.HTTPError` 後呼叫 `_handle_error`，而 `_handle_error` 內部會先執行 `session.rollback()`，再修改 `queue_item` 的 `status`、`retry_count` 等屬性。但 `_handle_error` 回傳後，`_process_item` 沒有後續的 `session.commit()`，導致這些修改永遠不會寫入資料庫。結果是：永久性錯誤（404/403）的失敗狀態遺失、重試計數不遞增。
   * **修正方案**：在 `crawler/runner.py` 的 `except httpx.HTTPError` 區塊，於 `self._handle_error(...)` 呼叫後補上 `session.commit()`。
   * **狀態**：**已解決（Resolved）**。

1. **全面盤查並修復進度數據 (progress_stats) 更新不一致的問題**
   * **問題描述**：目前使用 `progress_stats` 來紀錄快取進度，但在「重新探測」部份連結後，或是發生其他非預期情況時，`progress_stats` 沒有正確同步更新，導致介面上「爬取進度」內的數據與實際狀況脫節。
   * **規劃方案**：全面盤查所有會更動內部或外部連結狀態的邏輯（尤其是重新探測、狀態變更等流程），確保每次狀態異動時，都會對應地重新計算並寫入最新的 `progress_stats`，以維持數據一致性與正確性。
   * **狀態**：**已解決（Resolved）**。

---

## 永久擱置 / 已移除 (Dropped / Removed)

以下項目經評估後認為過度設計或效益極低，已決定擱置不再實作。

1. **修復 `ssl_exempt_domains` 繞過 SSRF 防護的漏洞**
   * **問題描述**：系統在遇到 TLS/SSL 豁免網域時，會停用憑證驗證。但在降級備援路徑中，這個豁免機制可能會不小心跳過對目標 IP 的「內網位址阻擋 (SSRF 防護)」。若攻擊者將惡意網域設為豁免，可能引導爬蟲存取內網。
   * **狀態**：**已擱置（Dropped）** - 原因：這是一個**假議題 (False Positive)**。經查核源碼，不論是 `_fetch_single`（呼叫 `_get_client` 前）還是 `_execute_curl_cffi_fallback` 的迴圈最開頭，都會強制先呼叫 `_resolve_and_check_ssrf`。若該 IP 不安全會直接 `return` 阻斷，根本無法進到發送請求的階段。`ssl_exempt_domains` 的白名單僅用於設定 `verify=False`，完全不會影響或繞過先前的 SSRF 檢查邏輯。因此這個雙重檢查是多餘的過度設計。

1. **實作重導向迴圈 (Redirect Loop) 的網址追蹤防禦**
   * **問題描述**：目前的實作只有「計數器 (如最多 10 次)」，沒有追蹤已經造訪過的 URL。這會導致無意義的死迴圈空轉，浪費資源。
   * **狀態**：**已擱置（Dropped）** - 原因：實務上有許多網站依賴「狀態重導向 (Stateful Redirects)」來設定授權 Cookie（例如 `GET /` -> 302 跳至 `/set_cookie` -> 302 帶上 Cookie 跳回 `/`）。若強制以網址 `Set[str]` 進行唯一性比對，會直接中斷這種合法且必要的跳轉流程。主流客戶端（如 Chrome、`requests`）也僅以最大跳轉次數 (`max_redirects`) 作為防護，因此引入 `visited_urls` 屬於會破壞正常功能的過度設計。

1. **實作全局 API 速率限制 (Global Rate Limiting)**
   * **功能描述**：目前僅有登入鎖定和忘記密碼的個別限速保護，沒有全局 API Rate Limiting Middleware，若面臨大量異常請求可能會佔用過多伺服器資源。
   * **規劃方案**：在反向代理層 (如 Nginx) 或是應用層 (如引入 SlowApi 或客製化 FastAPI Middleware) 補充全局 API 速率限制機制，保護伺服器免於遭受 DoS 或高頻惡意請求。
   * **狀態**：**已擱置（Dropped）** - 原因：API 速率限制通常交由反向代理層（如 Nginx、Cloudflare）處理，在應用層實作會增加不必要的效能開銷與維護成本，對於內部使用的工具而言屬於過度設計。

1. **主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)**
   * **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
   * **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
   * **狀態**：**已擱置（Dropped）** - 原因：引入 Celery 或 Redis 等外部依賴會大幅增加專案的部署難度與架構複雜度。目前的 `ThreadPoolExecutor` 已經足夠應付單機環境下的效能需求，維持輕量級部署更符合本專案的定位。

1. **CLI 支援匯出內部紀錄之狀態篩選 (export-internal filter)**
   * **功能描述**：目前 CLI 的 `--export-internal` 參數不支援使用 `--filter` 進行精確狀態篩選，會無條件匯出全部的內部頁面（包含成功與各種失敗）。雖然 Web API 的 `InternalResultQuery` 已具備過濾能力，但尚未整合至命令列工具中。
   * **規劃方案**：擴充 `cli.py` 中關於 `--export-internal` 的參數解析邏輯，使其能夠接收與處理 `--filter` 參數（例如支援 `not_found`, `server_error` 等），並將此參數對接傳遞給底層的匯出服務 (`export_internal_job_results`)。
   * **狀態**：**已擱置（Dropped）** - 原因：CLI 主要用於自動化或 CI 環境，使用者通常會將完整結果輸出為 JSON 後再利用 `jq` 進行處理。將複雜的過濾邏輯重複實作在 CLI 參數中不但效益低，也會增加開發負擔。Web 介面已經提供完整的篩選功能。

1. **CSRF Token 與 Session 綁定（R2-02）**
   * **問題描述**（來源：Code Review v3.0 R2-02）：目前 CSRF 防護採用 Double Submit Cookie 模式（驗證 Cookie 與 Header 中的 Token 是否一致），並未將 Token 密碼學綁定至特定使用者的 Session。若發生子網域（Subdomain）遭攻破，駭客有可能偽造 Cookie，進而繞過 CSRF 驗證。
   * **規劃方案**：在生成 CSRF Token 時，引入 HMAC 機制，以使用者的 Session ID 作為金鑰對 Token 進行簽章。後端驗證時一併檢查該簽章是否合法，防止 Token 遭偽造。
   * **相關位置**：`backend/auth/router.py` L223-L228
   * **狀態**：**已擱置（Dropped）** - 原因：本專案並未牽涉到複雜的子網域架構。目前的 `SameSite=Strict` Cookie 加上標準的 Double Submit Cookie 模式已經足以防禦絕大部分的 CSRF 攻擊。HMAC 綁定實作複雜度高但帶來的實際安全效益邊際遞減。

1. **加入結構化的任務執行統計日誌 (Observability)**
   * **問題描述**：目前在 `crawler/runner.py` 的 `_mark_job_completed` 中，任務完成時僅記錄了「任務完成」的簡單字串。缺少爬取頁數、外部連結探測數量、重試次數與總耗時等關鍵數據，不利於維運人員事後排查效能瓶頸或偵測反爬蟲異常。
   * **規劃方案**：在任務完成時（包含成功與異常中斷），加入結構化的統計日誌輸出，例如：`logger.info("任務 %s 完成 | 爬取: %d 頁 | 外連檢查: %d | 耗時: %.1f 秒", ...)`，提供系統效能基準 (Benchmark)。
   * **狀態**：**已擱置（Dropped）** - 原因：因為幾乎用不到，且任務詳情頁面就能直接看到相關數據了。
