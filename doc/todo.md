# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。

---

## 1. 任務完成與異常警報通知 (Alert Notifications / Webhooks)
* **功能描述**：爬蟲執行過程可能耗時數小時，手動輪詢進度效率低。
* **規劃方案**：在全域設定檔中配置 Slack、Discord、Microsoft Teams 或 Email 通訊協議。任務轉換至 `completed`（完成）或 `error`（嚴重異常崩潰）時，自動發送訊息通報，並附帶尋獲的 `dead` 連結與 `broken` 連結統計。
* **狀態**：**待評估與實作（Pending Review）**。

---

## 2. 進階反爬蟲繞過與標頭特徵輪替 (Advanced Anti-Bot Bypass)
* **功能描述**：在面對部分極度嚴格的大型平台（如 Amazon、LinkedIn 等），單純使用特定 User-Agent 仍有高機率被封鎖。
* **規劃方案**：在爬蟲核心中實作動態標頭（Header）輪替、隨機 User-Agent 特徵池、以及請求延遲抖動（Jitter Delay），使連線行為更像隨機真人存取，降低被偵測率。
* **狀態**：**待評估與實作（Pending Review）**。

---

## 3. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**待後續 Web 化開發階段評估（Pending Review）**。

---

## 4. 任務進度推送升級：Polling → SSE (Server-Sent Events)
* **功能描述**：目前前台任務詳情頁面透過客戶端每 3 秒輪詢（Polling）`GET /api/jobs/{id}` 來取得進度更新，會造成不必要的無效請求。
* **規劃方案**：後端實作 `GET /api/jobs/{id}/stream` SSE 端點，爬蟲子程序狀態變更時主動推送事件至前台；前台改用 `EventSource` API 訂閱，減少網路往返並提升即時性。
* **狀態**：**待後續優化（Pending Review）**。

---

## 5. CLI `--create-admin` 管理員建立的密碼行為 (Implementation Difference)
* **功能描述**：目前 `--create-admin` 指令在建立管理員時的密碼設定行為，與 `requirements.md` 所述的初始管理員 Bootstrap 機制存在實作差異。
* **規劃方案**：後續需盤點 CLI 實際行為與文件規範，對齊密碼產生邏輯或更新文件，確保整體安全設計一致。
* **狀態**：**已修正 (Resolved)**：已調整 `create_admin.py` 及 `cli.py` 邏輯，改為自動產生高強度隨機密碼並標記帳號為 `pending` (待設密)，符合原始規格要求。
