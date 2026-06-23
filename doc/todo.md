# 待辦功能與後續規劃 (TODO List)

本文件列出目前專案保留給未來審查、並決定是否實作的延伸功能與架構優化建議。

---

## 1. 主爬行迴圈與健康診斷之非同步解耦架構 (Async Distributed Architecture)
* **功能描述**：目前外部連結健康診斷是與主爬行迴圈同步進行（雖已採用 `ThreadPoolExecutor` 提升單頁內速度，但當外連高達數萬個時，仍會佔用主程序資源）。
* **規劃方案**：將外部連結檢查徹底解耦為物理獨立的背景任務。主爬蟲專職遍歷，並將待探測外連丟入非同步工作佇列（如 Celery、Redis 或是 RabbitMQ），由背景的探測 worker 進程池獨立執行診斷並非同步寫入資料庫。此為未來 Web 後台架構擴充時的重要優化方向。
* **狀態**：**待後續 Web 化開發階段評估（Pending Review）**。

---

## 2. UI 元件擴充：掃描結果 (內外部) 批次操作支援
* **功能描述**：目前內部診斷與外連結果列表僅支援全域匯出。
* **規劃方案**：在結果列表增加 Checkbox，支援「批次勾選」以利針對特定連結進行局部匯出或重新發起 HTTP 探測。
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

---

## 5. CLI 支援匯出內部紀錄之狀態篩選 (export-internal filter)
* **功能描述**：目前 CLI 的 `--export-internal` 參數不支援使用 `--filter` 進行精確狀態篩選，會無條件匯出全部的內部頁面（包含成功與各種失敗）。雖然 Web API 的 `InternalResultQuery` 已具備過濾能力，但尚未整合至命令列工具中。
* **規劃方案**：擴充 `cli.py` 中關於 `--export-internal` 的參數解析邏輯，使其能夠接收與處理 `--filter` 參數（例如支援 `not_found`, `server_error` 等），並將此參數對接傳遞給底層的匯出服務 (`export_internal_job_results`)。
* **狀態**：**待後續優化（Pending Review）**。

---

## 6. 全面修復與整合 Mypy 靜態型別檢查
* **功能描述**：目前專案雖已大規模採用 Type Hinting，但尚未達到完全無錯的狀態（掃描仍有百餘個 `mypy` 錯誤，主要為 `dict[str, object]` 協變性操作或測試檔參數型別等議題）。
* **規劃方案**：逐一排除剩餘的 `mypy` 型別報錯，待全站檢查通過後，再將 `mypy --explicit-package-bases backend/ crawler/ cli.py scripts/ test/` 正式納入開發者的 Workflow 檢驗清單與未來的 CI/CD 流程中，確保最高標準的靜態型別安全。
* **狀態**：**待後續優化（Pending Review）**。

## 7. 擴充與完善系統輔助說明 (Help & FAQ)
* **功能描述**：目前前端的 `help.html` 與 `faq.html` 已建立基礎架構，但部分教學內容與問答細節尚待補齊。
* **規劃方案**：將 `frontend/help.html` 的支援與說明教學內容，以及 `frontend/faq.html` 的常見問答內容補充完整，提供使用者更詳盡的操作指引與問題排解。
* **狀態**：**待後續優化（Pending Review）**。
