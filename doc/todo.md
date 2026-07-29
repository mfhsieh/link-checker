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
- [永久擱置 / 已移除 (Dropped / Removed)](#永久擱置--已移除-dropped--removed)
- [已解決 / 已完成 (Resolved / Completed)](#已解決--已完成-resolved--completed)

---

## 待排程 / 待優化 (Pending)

### 最優先（安全性、資料庫與基礎架構）

*(目前無)*

### 高優先（效能優化、核心精準度與程式品質）

1. **擴充比對任務 (Job Diff) 支援內部連結與診斷邏輯優化**
   * **問題描述**：目前的任務歷史差異比對引擎 (Job Diff Engine) 僅針對「外部連結」進行比對分析。然而，目標網站的「內部連結」健康度同樣重要，目前卻未被納入比對範圍。此外，現有的比對診斷方式及分類標籤在面對複雜的狀態變化時，可能不夠精確，仍需要進一步的調整與優化。
   * **規劃方案**：
     1. 擴充比對引擎，使其將「內部連結」的結果一併納入差異比對與分析範圍。
     2. 重新梳理並調整比對任務的診斷方式與分類邏輯，確保各種狀態變遷（例如新增失效、狀態復原、錯誤代碼改變等）都能被精準標示。
   * **狀態**：**待排程（Pending）**。

### 中優先（中大型功能擴充）

*(目前無)*

### 低優先（邊緣需求與周邊工具）

1. **前端 CSS 樣式清理 (Clean up unused CSS styles)**
   * **問題描述**：隨著專案演進與 UI 元件重構，前端可能殘留了許多不再使用的 Vanilla CSS 樣式與 Class。這些冗餘代碼會無衛地增加檔案體積，並降低樣式表的可維護性。
   * **規劃方案**：盤點前端目錄下的 HTML 與 CSS 檔案，找出從未被引用或已被廢棄的 CSS class 並予以移除，確保前端資源保持極致輕量與乾淨。
   * **狀態**：**待排程（Pending）**。

---

## 進行中 / 部分完成 (In Progress)

*(目前無)*

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

1. **程式碼重構：明確區分內部與外部連結的命名**
   * **現狀描述**：因歷史因素，部分變數與 API 命名未能精確區分內部與外部連結。
   * **改善建議**：盤點現有程式碼與 API 設計進行正名。
   * **狀態**：**觀察中（Monitoring）**。屬於大規模的重構與字串替換，風險較高且目前不影響功能，可待未來 API 版本升級時處理。

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

1. **CSRF Token 與 Session 綁定（R2-02）**
   * **問題描述**（來源：Code Review v3.0 R2-02）：目前 CSRF 防護採用 Double Submit Cookie 模式（驗證 Cookie 與 Header 中的 Token 是否一致），並未將 Token 密碼學綁定至特定使用者的 Session。若發生子網域（Subdomain）遭攻破，駭客有可能偽造 Cookie，進而繞過 CSRF 驗證。
   * **規劃方案**：在生成 CSRF Token 時，引入 HMAC 機制，以使用者的 Session ID 作為金鑰對 Token 進行簽章。後端驗證時一併檢查該簽章是否合法，防止 Token 遭偽造。
   * **相關位置**：`backend/auth/router.py` L223-L228
   * **狀態**：**已擱置（Dropped）** - 原因：本專案並未牽涉到複雜的子網域架構。目前的 `SameSite=Strict` Cookie 加上標準的 Double Submit Cookie 模式已經足以防禦絕大部分的 CSRF 攻擊。HMAC 綁定實作複雜度高但帶來的實際安全效益邊際遞減。

---

## 已解決 / 已完成 (Resolved / Completed)

> 💡 詳細歷史紀錄已移至 [todo_resolved.md](./todo_resolved.md)。
