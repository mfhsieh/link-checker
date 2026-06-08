# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。

---

## 1. 進階反爬蟲繞過與標頭特徵輪替 (Advanced Anti-Bot Bypass)
* **功能描述**：在面對部分極度嚴格的大型平台（如 Amazon、LinkedIn 等），單純使用特定 User-Agent 仍有高機率被封鎖。
* **規劃方案**：在爬蟲核心中實作動態標頭（Header）輪替、隨機 User-Agent 特徵池、以及請求延遲抖動（Jitter Delay），使連線行為更像隨機真人存取，降低被偵測率。
* **狀態**：**待評估與實作（Pending Review）**。

---

## 2. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**待後續 Web 化開發階段評估（Pending Review）**。

---

## 3. 任務進度推送升級：Polling → SSE (Server-Sent Events)
* **功能描述**：目前前台任務詳情頁面透過客戶端每 3 秒輪詢（Polling）`GET /api/jobs/{id}` 來取得進度更新，會造成不必要的無效請求。
* **規劃方案**：後端實作 `GET /api/jobs/{id}/stream` SSE 端點，爬蟲子程序狀態變更時主動推送事件至前台；前台改用 `EventSource` API 訂閱，減少網路往返並提升即時性。
* **狀態**：**待後續優化（Pending Review）**。

---

## 4. UI 元件擴充：支援進階程式碼編輯器與批次操作
* **功能描述**：目前後台的「系統配置」與前台的「檢視快照」是使用 `<textarea>` 與自訂 HTML 排版。外連結果列表目前僅支援單一匯出。
* **規劃方案**：引入輕量級無相依的語法高亮編輯器（如 CodeMirror / PrismJS）提升 JSON/YAML 的編輯體驗；並在外連結果列表增加 Checkbox，支援「批次勾選」以利針對特定連結進行局部匯出或重新 HTTP 探測。
* **狀態**：**待後續優化（Pending Review）**。

---

## 5. 建立完整自動化測試程序 (QUALITY-09)
* **功能描述**：目前專案缺乏完整的自動化測試程序（包含單元測試與整合測試），需要針對核心功能（如爬蟲引擎、身分驗證、任務排程等）建立完善的測試覆蓋。
* **規劃方案**：導入 `pytest` 作為測試框架，優先補齊核心業務邏輯的單元測試，並配置 FastAPI 測試客戶端進行整合測試。未來可進一步於 CI/CD 流程中加入自動化測試關卡，以確保系統穩定性。
* **狀態**：**待後續實作（Pending Review）**。

---

## 6. 跨資料庫刪除的不一致風險與 Session 垃圾回收 (Cross-DB Transaction & GC / QUALITY-12)
* **功能描述**：解決 `backend/admin/router.py` 跨庫刪除時，因缺乏分散式事務保護可能導致資料不一致的風險；同時解決資料庫中 Session 累積導致空間膨脹的問題。
* **規劃方案**：
  1. **軟刪除與排程清理 (最終一致性與 GC)**：在 `Auth DB` 的 `User` 表新增 `is_deleted` (Boolean) 欄位來實作軟刪除 (Soft Delete)。刪除帳號時僅標記此欄位，後續由 Cronjob 統一非同步清理兩個資料庫中的髒資料。同時，利用此 Cronjob 排程定期清理過期 (如超過 `max_age` 7 天) 的 Session 資料列。
  2. **進階分散式事務模式**：未來若系統遷移至 PostgreSQL 或 MySQL 等架構，可考慮實作「二階段提交 (Two-Phase Commit)」或 Saga 模式，以系統層級確保跨庫操作的最終一致性。
* **狀態**：**待後續實作（Pending Review）**。

---

## 7. 後端密碼強度強制驗證 (Backend Password Validation)
* **功能描述**：落實「絕不信任前端傳入資料」的安全鐵律，確保 API 端對密碼有嚴格的長度與複雜度驗證。
* **規劃方案**：在後端的 `SetPasswordRequest` (於 `backend/auth/router.py` 中) 加入對等的 Pydantic 長度或正規表示式驗證（例如至少 8 碼），與前端 `auth.js` 中的 `calcPasswordStrength` 進度條提示相互配合。
* **狀態**：**待後續實作（Pending Review）**。

---

## 8. Crawler 網路請求逾時精細化處理 (Crawler Timeout Optimization)
* **功能描述**：針對外部連結可能遇到的惡意阻擋 (Tarpit) 情況，優化現行單一的 `timeout` (預設 30 秒) 設定。
* **規劃方案**：將爬蟲引擎 `httpx.Client` 的逾時設定拆分為 `connect` 與 `read` 兩個不同維度的超時時間，以更精細、快速地處理連線掛起的狀況，避免單一惡意連結拖慢整體爬取效能。
* **狀態**：**待後續實作（Pending Review）**。
