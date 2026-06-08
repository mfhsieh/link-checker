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

## 5. 程式碼品質與架構優化 (QUALITY-09)
* **功能描述**：針對 `@code_review.md` 中指出的 QUALITY-09 項目進行重構。
* **規劃方案**：將此程式碼品質優化事項保留至下一個 Sprint 迭代中進行審查與修復。
* **狀態**：**待後續實作（Pending Review）**。

---

## 6. 跨資料庫刪除的不一致風險 (QUALITY-12)
* **功能描述**：解決 `backend/admin/router.py` 跨資料庫刪除時缺乏分散式事務保護所造成的不一致風險。
* **規劃方案**：在 `Auth DB` 的 `User` 表新增 `is_deleted` (Boolean) 欄位來實作**軟刪除 (Soft Delete)**，當使用者被刪除時，只要標記此欄位即可，後續再由 Cronjob 統一清理兩個資料庫中的髒資料，以達到最終一致性。
* **狀態**：**待後續實作（Pending Review）**。
