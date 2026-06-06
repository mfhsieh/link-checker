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
