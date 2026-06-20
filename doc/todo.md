# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。

---

## 1. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**待後續 Web 化開發階段評估（Pending Review）**。

---

## 2. UI 元件擴充：外連結果批次操作支援
* **功能描述**：目前外連結果列表僅支援全域匯出。
* **規劃方案**：在外連結果列表增加 Checkbox，支援「批次勾選」以利針對特定連結進行局部匯出或重新發起 HTTP 探測。
* **狀態**：**待後續優化（Pending Review）**。

---

## 3. 匯出完整報表 (ZIP) 新增獨立的內部失效連結清單
* **功能描述**：目前完整匯出的 ZIP 檔中僅包含 `crawl_records.csv` (全部爬取紀錄) 與 `external_links.csv` (外部連結)。雖然 `crawl_records.csv` 已涵蓋所有失敗資訊，但缺乏預先分類的內部失效名單，較不便於非技術人員快速查閱。
* **規劃方案**：在 `export_full_report` 匯出打包 ZIP 的過程中，額外過濾並產出一份 `job_{id}_internal_errors.csv` 檔案，專門條列 `failed` 與 `warning` 狀態的內部連結。
* **狀態**：**待後續優化（Pending Review）**。

---

## 4. 實作應用層快取 (Application Caching)
* **功能描述**：針對已完成或異常終止的任務，其外連結果與報表是靜態的。目前切換聚合模式會重複消耗運算資源。
* **規劃方案**：在 FastAPI 路由中針對靜止狀態（如 `completed`, `error`）的任務加入記憶體快取（如 `functools.lru_cache` 或 `cachetools`），將 API 回應時間降至極短，大幅減輕 Python 的 CPU 運算壓力。
* **狀態**：**待後續優化（Pending Review）**。
