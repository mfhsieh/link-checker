# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。

---

## 1. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**待後續 Web 化開發階段評估（Pending Review）**。

---

## 2. 任務進度推送升級：Polling → SSE (Server-Sent Events)
* **功能描述**：目前前台任務詳情頁面透過客戶端每 10 秒輪詢（Polling）`GET /api/jobs/{id}` 來取得進度更新，會造成不必要的無效請求。
* **規劃方案**：後端實作 `GET /api/jobs/{id}/stream` SSE 端點，爬蟲子程序狀態變更時主動推送事件至前台；前台改用 `EventSource` API 訂閱，減少網路往返並提升即時性。
* **狀態**：**已完成 (Completed)**。

---

## 3. UI 元件擴充：外連結果批次操作支援
* **功能描述**：目前外連結果列表僅支援全域匯出。
* **規劃方案**：在外連結果列表增加 Checkbox，支援「批次勾選」以利針對特定連結進行局部匯出或重新發起 HTTP 探測。
* **狀態**：**待後續優化（Pending Review）**。

---

## 4. PostgreSQL 連線池效能調校 (Connection Pool Optimization)
* **功能描述**：系統底層已支援遷移為 PostgreSQL，但 `create_engine` 尚未配置專屬的連線池參數。在多執行緒並發爬取 (`ThreadPoolExecutor`) 加上前端高頻 API 存取的情境下，預設的連線池大小 (5) 可能被耗盡，導致 Timeout 或是連線中斷問題。
* **規劃方案**：在 `backend/auth/db.py` 與 `crawler/manager.py` 初始化資料庫引擎時，若偵測連線字串非 SQLite (如 PostgreSQL)，則明確加入 `pool_size=20`、`max_overflow=20`，以及啟用斷線重連防護 `pool_pre_ping=True` 等進階連線池參數，徹底發揮 PostgreSQL 高併發潛力。
* **狀態**：**已完成 (Completed)**。
