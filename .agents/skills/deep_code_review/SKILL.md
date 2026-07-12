---
name: Deep Code Review
description: 執行深度程式碼審查，關注併發、資安、架構、效能、韌性與需求合規性，產出結構化報告。
---

# 深度程式碼審查原則 (Deep Code Review Rule)

當被要求進行 Code Review 時，**絕對禁止**僅進行表層的語法與排版檢查。你必須以「資深架構師」與「資安專家」的視角，嚴格依據以下 9 個維度進行深度挖掘。

---

## 審查前準備

在開始審查之前，你**必須**先執行以下準備步驟：

1. **確認審查範圍 (Scope)**：若使用者指定了特定模組或檔案，則聚焦於該範圍；若未指定，則優先審查近期有變動的檔案（可透過 `git log` 或 `git diff` 確認）。
2. **交叉參照專案文件**：主動查閱 `doc/requirements.md` 與 `doc/architecture.md`，確保審查時有明確的規格基準線可供比對，而非僅憑通用知識進行判斷。

---

## 審查維度

### 1. 併發與資源洩漏 (Concurrency & Resource Leaks)
   - FastAPI 中是否有 `async def` 呼叫了同步阻塞的 I/O（如 DB 查詢、密集計算或同步網路請求）導致主迴圈卡死？
   - 資料庫連線池、檔案控制代碼是否都有在 `finally` 區塊或 Context Manager 中確實釋放？
   - 記憶體消耗是否安全（是否有遵守 `yield_per` 等串流處理原則避免 OOM）？
   - **[爬蟲專案特有]** 資料庫任務狀態更新（如 `queued` 轉 `running`）是否有考量 Race Condition（例如使用 Select FOR UPDATE 或樂觀鎖）避免任務被 Worker 重複執行？

### 2. 資安與錯誤邊界 (Security & Error Handling)
   - 使用者輸入或外部不可信資料是否有可能引發 SQL Injection 或 XSS？
   - 是否有隱藏的 `Exception` 被無聲吞噬 (Silenced) 而沒有記錄 Log？
   - **[爬蟲專案特有]** 爬蟲抓取目標時是否具備防範 SSRF (Server-Side Request Forgery) 的機制（如解析 DNS 並攔截存取內網 IP）？

### 3. 架構耦合度 (Architecture & Coupling)
   - 前端是否違反了 MVC 或本專案定義的「Web Component 模組化與狀態封裝」原則？
   - 核心後端模組之間是否存在不必要的循環依賴 (Circular Dependency)？
   - **[爬蟲專案特有]** 爬蟲核心引擎 (`crawler/`) 與後端 API (`backend/`) 的邊界是否清晰？爬蟲引擎絕對不可反向依賴 Web Request 或 HTTP 權限等伺服器層級模組。

### 4. 邊角案例 (Corner Cases)
   - 面對極端狀況（如超時、死結、非預期的 Content-Type、無限重新導向），系統是否有防護機制？
   - **[爬蟲專案特有]** 面對惡意爬蟲陷阱（如 Tarpit 延遲回應、10GB 的超大假檔案），爬蟲是否嚴格限制了 Max Content-Length 並強制使用 Streaming 分塊下載以防 OOM？

### 5. 資料一致性與狀態機完整性 (Data Integrity & State Machine)
   - 任務狀態轉換是否遵守合法的狀態遷移路徑？是否有可能跳過中間狀態（例如從 `queued` 直接跳到 `completed`）？
   - 跨資料庫操作（Auth DB 與 Crawler DB）是否有一致性風險？例如一邊寫入成功但另一邊失敗時，是否有補償或回滾機制？
   - 進度更新（如爬取頁數、外連數量）與最終結果之間，是否有可能因為競態條件而產生數據不一致？

### 6. 可觀測性與日誌品質 (Observability & Logging Hygiene)
   - 日誌是否具備足夠的上下文可供追蹤（例如：關鍵操作的日誌是否都帶有 `job_id`、目標 URL、狀態碼、重試次數等資訊）？
   - 是否有敏感資訊（密碼、Token、Cookie 值、使用者個資）被意外寫入日誌？
   - 錯誤日誌是否包含足夠的除錯資訊，還是只丟出一個空泛的 `Exception` 訊息？

### 7. 效能與可擴展性 (Performance & Scalability)
   - 資料庫查詢是否存在 N+1 問題？批次寫入是否有使用 `bulk_insert` 或 `executemany`？
   - API 端點的分頁查詢是否正確使用了資料庫索引 (Index)？大量資料匯出（CSV/ZIP）是否採用串流 (Streaming) 而非一次載入記憶體？
   - 前端是否有不必要的重複渲染、頻繁的 DOM 操作、或是未經節流 (Throttle/Debounce) 的高頻事件監聽？

### 8. 錯誤復原與韌性 (Resilience & Recovery)
   - 長時間執行的爬蟲任務若中途崩潰（如進程被 kill），重新啟動後系統是否能正確識別並處理孤兒任務 (Orphaned Jobs)？
   - 資料庫連線中斷後是否有自動重連機制？是否有設定合理的 `pool_recycle` 與 `pool_pre_ping`？
   - 外部服務（目標網站）持續無回應時，是否有 Backoff 策略或上限機制避免無限重試耗盡資源？

### 9. 需求合規性 (Requirements Compliance)
   - **規格落實度**：`doc/requirements.md` 中明確規定的功能與限制（例如 SSRF 防禦規則、記憶體上限、連線池配置約束等），是否都有對應的程式碼實作？是否存在「規格有寫但沒人實作」的遺漏？
   - **實作偏離**：已實作的功能是否偏離了規格中描述的行為？例如規格要求「白名單機制」，但實際程式碼卻用了「黑名單機制」。
   - **未文件化行為**：是否存在程式碼中有實作、但 `doc/` 目錄下完全沒有對應文件描述的「隱藏功能」？這類未文件化行為會增加未來維護的風險。

---

## 產出報告要求

### 報告格式
1. **儲存位置與版號**：產出的 Review 報告必須直接寫入 `doc/` 目錄下（例如 `doc/code_review_report_v3.0.md`），並且在文件標題下方明確標註**文件版號 (Version)** 與**審查日期**。
2. **每個發現項目必須包含**：
   - **嚴重程度** (Critical / High / Medium / Low)
   - **問題精準定位** (檔案名稱與行號範圍)
   - **現狀描述** (為什麼這是個問題)
   - **改善建議** (具體的修正思路或程式碼片段)

### 審查後動作
3. **與 todo.md 整合**：報告產出後，必須主動詢問使用者：是否將「未立即修復的項目」歸檔至 `doc/todo.md` 作為待辦追蹤。
