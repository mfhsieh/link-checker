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

## 5. [已完成] 整合 GitHub Actions 自動化 CI/CD (QUALITY-09)
* **功能描述**：建立完整的自動化測試與靜態分析程序，確保每次程式碼提交都能維持高穩定性與 10.0 滿分品質。
* **實作細節**：已撰寫 `test/run_test.py` 涵蓋 E2E 爬蟲流程與 API 整合測試，並建立 `.github/workflows/ci.yml`，在每次 Git Push 時自動執行 Ruff 排版檢查、Pylint 滿分檢驗與 E2E 測試腳本。
* **狀態**：**✅ 已完成 (Completed)**。

---

## 6. [部分完成] 跨資料庫刪除的不一致風險與 Session 垃圾回收 (Cross-DB Transaction & GC / QUALITY-12)
* **功能描述**：解決 `backend/admin/router.py` 跨庫刪除時，因缺乏分散式事務保護可能導致資料不一致的風險；同時解決資料庫中 Session 累積導致空間膨脹的問題。
* **實作進度**：
  1. **✅ Session 垃圾回收 (GC)**：已實作 `run_session_gc_task` 背景任務，在每次使用者登入或登出時，利用 FastAPI 的 `BackgroundTasks` 自動於背景非同步清除資料庫中的過期 Session，徹底解決空間無限膨脹的隱患。
  2. **⏳ 軟刪除與分散式事務**：帳號與任務的跨庫刪除尚未實作軟刪除或二階段提交，目前仍維持循序物理刪除。未來若遷移至 PostgreSQL 可考慮實作 Saga 模式。
* **狀態**：**🟡 部分實作 (Partially Completed)**。

---

## 7. [已完成] 後端密碼強度強制驗證 (Backend Password Validation)
* **功能描述**：落實「絕不信任前端傳入資料」的安全鐵律，已於後端實作嚴格的密碼強度驗證。
* **實作細節**：已在 `backend/auth/password.py` 中實作 `validate_password_strength`，並於 `auth/service.py` 的 `set_first_password` 與 `change_password` 中強制呼叫檢驗。
* **狀態**：**✅ 已完成 (Completed)**。

---

## 8. [已完成] Crawler 網路請求逾時精細化處理 (Crawler Timeout Optimization)
* **功能描述**：針對外部連結可能遇到的惡意阻擋 (Tarpit) 情況，優化現行單一的 `timeout` (預設 30 秒) 設定。
* **實作細節**：已於系統中導入全域可配置之 `connect_timeout` 與 `external_check_timeout`。透過 `httpx.Timeout` 精細控制「TCP 連線建立」與「外連探測總體超時」之時間，確保遇到惡意伺服器時不佔用 ThreadPool，兼具高效防護與高度客製化彈性。
* **狀態**：**✅ 已完成 (Completed)**。
