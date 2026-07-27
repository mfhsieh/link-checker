# 全專案深度 Code Review 報告 v1.0

> **審查日期**：2026-07-27  
> **審查範圍**：全專案（`crawler/`、`backend/`、`frontend/`、`doc/`）  
> **審查維度**：併發安全性、資安、架構、效能、韌性、測試覆蓋、API 合規、文件一致性、需求合規（共九維度）

---

## 執行摘要

整體而言，本專案的架構設計品質相當優秀，展現了高度的安全意識與系統韌性思考。進程隔離模型、CLI-First 設計、雙資料庫分離（Auth DB / Crawler DB）、SSRF 防禦、Session-based Auth 等核心設計均符合高標準。爬蟲核心的降級策略（`httpx` → `curl_cffi` TLS 偽裝）、cookie 跨跳傳遞、WAF 繞過邏輯等實作細節相當精緻，顯示出對現實爬蟲場景的深入理解。

本報告聚焦於發現潛在的**安全漏洞**、**併發風險**、**資料一致性問題**以及**架構技術債**，供後續改善優先化參考。

---

## 嚴重度定義

| 等級 | 說明 |
|------|------|
| 🔴 **CRITICAL** | 必須立即修復，存在安全性漏洞或資料一致性重大缺口 |
| 🟠 **HIGH** | 高優先改善，可能導致運行期錯誤、資料遺失或主要功能失效 |
| 🟡 **MEDIUM** | 中優先，涉及維護性、效能或邊界情況 |
| 🟢 **LOW** | 輕微問題，屬程式品質與一致性改善 |

---

## 維度一：併發安全性 (Concurrency Safety)

### F-01 ✅ FALSE POSITIVE：`ContextVar` 在 `ThreadPoolExecutor` 子執行緒的傳播（已確認正確）

**位置**：`crawler/runner.py` L226、L588-L601、L926-L940

**確認結果**：經查閱原始碼後，此項為**誤報**。

Python 3.7+ 的官方規格明確：`ThreadPoolExecutor` 在透過 `executor.map()` 提交任務時，會自動複製當前執行緒的 `contextvars.copy_context()` 快照導入子執行緒。實際執行路徑為：

1. `__init__` → `current_job_id_var.set(self.job_id)` ← **在主執行緒設定**
2. `execute()` → `ThreadPoolExecutor` 建立 → `executor.map(check_single, ...)` ← **Context 快照在此時複製**

由於步驟 1 發生在步驟 2 **之前**，子執行緒繼承的 `job_id` 已正確，不需在閉包內額外設定。此外，爬蟲屬於獨立的 CLI 子程序（`subprocess`），每個任務的 `JobRunner` 為獨立實例，不共享 Context，亦不存在 `job_id` 洩漏的風險。**現行實作完全正確**，無需任何修改。

---

### F-02 🟡 MEDIUM：`_cleanup_finished_processes` 節流計時器未更新 `_LAST_CLEANUP_TIME`（已列入 todo.md）

**位置**：`backend/jobs/services/process.py` L183-L199

**問題**：`_cleanup_finished_processes` 有節流檢查，但函式內部**未更新** `_LAST_CLEANUP_TIME`。僅 `_cleanup_zombie_jobs` 才會更新全域變數。如果 `_cleanup_finished_processes` 被單獨頻繁呼叫（例如透過 `start_job` 的路徑），節流機制將失效，每次都會遍歷 PID 目錄，造成不必要的磁碟 I/O。

**建議**（已移至 `doc/todo.md` 待排程）：在 `_cleanup_finished_processes` 的實際清理邏輯執行後，也更新 `_LAST_CLEANUP_TIME`：

```python
def _cleanup_finished_processes() -> None:
    global _LAST_CLEANUP_TIME
    current_time = time.time()
    if current_time - _LAST_CLEANUP_TIME < _CLEANUP_THROTTLE_SECONDS:
        return
    _LAST_CLEANUP_TIME = current_time  # 補上此行
    # ...
```

---

### F-03 🟡 MEDIUM：`JobProgressPoller.active_jobs` 在非同步環境中的執行緒安全假設應文件化（已列入 todo.md）

**位置**：`backend/jobs/services/poller.py` L42-L68

**問題**：`active_jobs` 字典的 `add_job` 和 `remove_job` 方法與 `_poll_loop` 中的 `list(self.active_jobs.keys())` 均在同一個事件迴圈中執行，在純 `asyncio` 環境中這是安全的（GIL 保護 + 事件迴圈單執行緒特性）。但若未來引入 `run_in_threadpool` 呼叫這些方法，將產生競態條件。目前設計未加鎖，應以文件明確標注此假設。

**建議**（已移至 `doc/todo.md` 待排程）：在類別的 docstring 中明確記錄「此類別設計僅限於單一 asyncio Event Loop 執行緒中使用」。

---

## 維度二：資訊安全 (Security)

### S-01 ✅ FALSE POSITIVE：CSRF Cookie 的 `SameSite` 屬性設定（已確認誤報）

**位置**：`backend/auth/router.py` L92-L129（`_set_session_cookie` / `_set_csrf_cookie`）

**確認結果**：經實際查閱原始碼後，此項為**誤報**。

- `_set_csrf_cookie`：`samesite="strict"`、`httponly=False`（JS 必須可讀，符合 Double Submit Cookie 設計） ✅
- `_set_session_cookie`：`samesite="strict"`、`httponly=True`、生產環境 `secure=True` ✅
- `_clear_auth_cookies`：登出時同樣設定 `samesite="strict"` ✅

兩個 Cookie 皆已明確設定為 `SameSite=Strict`（比 `Lax` 更嚴格），且 Session Cookie 有完整的 `httponly=True` 保護，**CSRF 防護設定完全正確**，無需任何修改。

---

### S-02 🟡 MEDIUM：`sanitize_error_message` 未防禦日誌注入 (Log Injection)（已列入 todo.md）

**位置**：`crawler/utils.py` L140-L180

**問題**：`sanitize_error_message` 函式未移除 `\r`（CR）和 `\n`（LF）字元。

**實際資料流分析**（經查閱呼叫端後修正原始描述）：

- 函式回傳值**全部寫入資料庫欄位**（`CrawlQueue.error_message`、`ExternalLink.error_message`），再透過 API 以 **JSON 欄位值**的形式回傳前端。JSON 序列化會自動跳脫 `\r\n`，**不會造成 HTTP Header 注入**。
- 真正的風險是**日誌注入（Log Injection）**：`runner.py` 多處有 `logger.error("...: %s", e)` 等呼叫，若惡意伺服器在 HTTP 回應中嵌入含有 `\n[CRITICAL] FAKE LOG ENTRY` 的錯誤訊息，寫入日誌後會被解析為偽造的日誌條目，影響日誌完整性與告警可信度。

**建議**（已移至 `doc/todo.md` 待排程）：在函式尾端添加換行字元清理：

```python
# 清除日誌注入風險字元
msg = msg.replace("\r", "").replace("\n", " ")
return msg
```

---

### S-03 🟢 LOW：`_serve_html_with_nonce` 邊界情況防護與單元測試補充（已列入 todo.md）

**位置**：`backend/main.py` L187-L232

**分析與問題說明**：
- 在生產模式下，原始 HTML 被快取至 `_html_cache`，每次請求動態替換注入 nonce。
- 此機制**並非資安漏洞**（最壞情況為 nonce 漏注入導致頁面腳本被 CSP 阻擋，屬功能性渲染議題而非安全風險）。
- 但若 HTML 中包含罕見的屬性寫法（例如屬性 JSON 值中包含 `"nonce="` 字串），正則的防重複注入檢查 `if "nonce=" in attrs.lower()` 可能被誤觸發而跳過注入。

**建議**（已移至 `doc/todo.md` 待排程）：針對此邊界情況補充單元測試（包含帶有特殊屬性字串的 `<script>` 標籤、已有 nonce 的標籤），驗證 nonce 注入的穩定度。

---

### S-04 ✅ FALSE POSITIVE：`is_safe_ip` 的 IPv6 ULA 覆蓋（已確認正確）

**位置**：`crawler/utils.py` L113-L137

**確認結果**：經測試與環境確認，此項為**誤報**。

1. 本專案使用 Python 3.12+ 虛擬環境（且大量使用 `A | B` 等 Python 3.10+ 原生語法，不支援 Python < 3.10 舊版本）。
2. 在 Python 3.11+ 中，`ipaddress.ip_address('fc00::1').is_private` 官方已完全覆蓋包含 `fc00::/7` 在內的所有 IPv6 Unique Local Address (ULA)，並正確回傳 `True`。
3. `is_safe_ip()` 的 SSRF 防禦在當前環境下完全正常運作，無須進行手動判斷擴充。

---

### S-05 🟡 MEDIUM：`_ACTIVE_PROCESSES` 全域字典建議明確加鎖（已列入 todo.md）

**位置**：`backend/jobs/services/management.py` 與 `process.py`（`_ACTIVE_PROCESSES` 存取位置）

**問題**：`_ACTIVE_PROCESSES[job_id] = proc` 的寫入和 `_ACTIVE_PROCESSES.pop(job_id, None)` 的刪除可能來自不同的 FastAPI 路由執行緒。Python 的 GIL 保護了字典操作的原子性，但若未來引入 multiprocessing 或 Python 3.13+ free-threading，此處將產生競態條件。

**建議**（已移至 `doc/todo.md` 待排程）：在 `_ACTIVE_PROCESSES` 的存取位置明確添加 `threading.Lock()`，使邏輯意圖更清晰，並為未來的 free-threading 做好準備。

---

## 維度三：架構設計 (Architecture)

### A-01 🟠 HIGH：`crawler` 模組對 `backend.events` 存在反向依賴（已知技術債）

**位置**：`crawler/runner.py` L40

```python
from backend.events import SystemEvent
```

**問題**：`crawler/runner.py` 直接引入 `backend.events`，使得爬蟲層（下層）依賴於 Web 層（上層），違反了分層架構的依賴倒置原則。此問題已在 `todo.md` 列為「觀察中」技術債，但值得在此再次強調：

**現況影響**：爬蟲子程序啟動時會 import `backend.*`，若 `backend` 有語法錯誤或 import 失敗，爬蟲子程序也將無法啟動。

**建議**：按照 `todo.md` 中已規劃的方向，將事件通知改為 `on_event_callback` 參數（Callable），使 `runner.py` 對 `backend` 零依賴。

---

### A-02 🟡 MEDIUM：`retry_failed_job` 的批次大小魔術數字應提取為常數（已列入 todo.md）

**位置**：`crawler/manager.py` L563-L574

```python
# SQLite 每条 IN 子句的參數數量限制為 999，故以 900 為安全批次大小
for i in range(0, len(source_urls_to_retry), 900):
```

**建議**（已移至 `doc/todo.md` 待排程）：提取為模組級常數：

```python
_SQLITE_MAX_IN_BATCH_SIZE = 900  # SQLite IN 子句參數上限 999，取 900 為安全值
```

---

### A-03 🟡 MEDIUM：`CrawlerConfig` 初始化使用 `cast()` 而非實際型別轉換（已列入 todo.md）

**位置**：`crawler/runner.py` `_initialize` 方法

**問題**：`max_depth`、`max_pages` 等參數均使用 `cast()` 而非真正的型別轉換（`cast` 在 runtime 是 no-op）。若使用者傳入非預期型別（如字串 `"10"` 而非整數 `10`），系統將靜默接受，可能在後續比較操作時引發 `TypeError`。

**建議**（已移至 `doc/todo.md` 待排程）：將 `cast()` 替換為實際的型別轉換包裝：

```python
max_depth = int(crawler_config.get("max_depth", 5))
```

---

## 維度四：效能 (Performance)

### P-01 🟢 LOW / 已確認：雙階佇列備援查詢行為（無需特別優化）

**位置**：`crawler/runner.py` L500-L506

**確認結果與分析**：
- 備援查詢 `session.query(CrawlQueue)...first()` 僅在記憶體雙階 deque 完全耗盡時才會觸發一次（用於確認無記憶體漏同步的 pending 網址）。
- 若備援查詢回傳 None，程式會隨即轉去處理外部連結重測或結束任務跳出迴圈，**並非處於熱路徑 (Hot Path) 上高頻觸發的操作**。
- 此機制屬低風險的防禦性機制，**維持現狀即可，無需特別優化**。

---

### P-02 🟢 LOW：`get_all_jobs` 在任務數量大時缺乏分頁機制（已列入 todo.md）

**位置**：`crawler/manager.py` L205-L243

**建議**（已移至 `doc/todo.md` 待排程）：新增 `limit` 和 `offset` 參數，或改用遊標分頁（Cursor-based Pagination）。可列為低優先技術債追蹤。

---

## 維度五：韌性與錯誤處理 (Resilience)

| R-01 | 🟠 HIGH | 韌性 | 狀態查詢異常可能誤判任務失敗（已列入 todo.md） |

**位置**：`crawler/runner.py` L455-L462

**問題**：若 `session.query(Job)` 拋出 `SQLAlchemyError`（例如 SQLite busy 超時），此例外將直接冒泡到 `execute()` 的 `except Exception` 塊，將任務標記為 `error`。這在瞬間的 SQLite 忙碌等待超時時可能導致誤判任務失敗。

**建議**（已移至 `doc/todo.md` 待排程）：在狀態查詢處加上針對 `SQLAlchemyError` 的捕捉，允許短暫失敗後繼續：

```python
try:
    session.expire(job)
    fetched_job = session.query(Job).filter(Job.id == self.job_id).first()
except SQLAlchemyError as e:
    logger.warning("狀態查詢暫時失敗，跳過本次檢查: %s", e)
    last_status_check_time = current_time
    continue
```

---

### R-02 🟡 MEDIUM：指數退避的 `time.sleep()` 阻塞暫停響應（已列入 todo.md）

**位置**：`crawler/runner.py` `_handle_error` L1078

**問題**：在指數退避重試時，`time.sleep()` 會阻塞爬蟲主執行緒。若 `backoff_delay` 達數十秒，整個任務在此期間完全停滯，無法響應使用者的暫停指令（需等待 sleep 結束後的下一次狀態檢查）。

**建議**（已移至 `doc/todo.md` 待排程）：考慮將長時間 sleep 分割為多個短暫 sleep 並穿插狀態檢查，例如：

```python
elapsed = 0
while elapsed < actual_delay:
    time.sleep(min(1.0, actual_delay - elapsed))
    elapsed += 1.0
    # 若有必要可在此處加入快速狀態檢查
```

---

### R-03 🟢 LOW / 重複：`retry_failed_job` 的批次邏輯（已併入 A-02，無須重複追蹤）

**位置**：`crawler/manager.py` L563-L574

**確認結果與分析**：
- 經查閱原始碼，`manager.py` 現行邏輯本身已對所有資料庫後端（包含 PostgreSQL）無條件採用以 900 筆為單位的分批切片。
- 此項目本質與 **A-02（將 Magic Number 900 抽離為模組級常數）** 完全相同，**已併入 A-02 統一追蹤，無須重複處理**。

---

## 維度六：測試覆蓋 (Test Coverage)

### T-01 🟠 HIGH：核心降級路徑缺乏整合測試（已列入 todo.md）

**問題**：`check_external_link` 涉及多層降級邏輯（HEAD → GET → HTTP 升級 HTTPS → TLS 偽裝），每一分支的行為正確性對系統準確性至關重要。

**建議**（已移至 `doc/todo.md` 待排程）：使用 `respx` mock HTTP 客戶端，為以下場景編寫整合測試：
- HEAD 請求超時 → 降級 GET
- HEAD 請求返回 404 → 降級 GET
- HTTP 連結返回 403 → 嘗試 HTTPS → TLS 偽裝降級
- Cookie-gate 重導向場景

---

### T-02 🟡 MEDIUM：`sanitize_error_message` 的正則表達式缺少邊界情況測試（已列入 todo.md）

**問題**：`sanitize_error_message` 包含複雜的 IPv6 正則表達式，但邊界情況（如 `::1`、映射 IPv4 的 IPv6 `::ffff:192.168.1.1`）未見對應單元測試。

**建議**（已移至 `doc/todo.md` 待排程）：補充單元測試涵蓋所有 IP 遮蔽的邊界情況，特別是 IPv6 縮寫格式與 CRLF 注入場景。

---

## 維度七：API 合規性 (API Compliance)

### API-01 ✅ FALSE POSITIVE：`start_url` 的 Schema 層驗證（已確認正確）

**位置**：`backend/jobs/schemas.py` L61-L78（`CreateJobRequest.validate_url`）

**確認結果**：經查閱原始碼後，此項為**誤報**。

`CreateJobRequest` Schema 中早已包含 `@field_validator("start_url")` 驗證器 `validate_url()`，會強制檢查 `start_url` 必須以 `http://` 或 `https://` 開頭，否則直接在 Pydantic API 驗證層攔截並回傳 422 錯誤。**API 驗證邏輯已非常完整，無須任何修改**。

---

### API-02 🟡 MEDIUM：SSE 的 `paused` 狀態處理可能讓前端陷入需手動輪詢（已列入 todo.md）

**位置**：`backend/jobs/routers/management.py` L509-L514

**問題**：當使用者連線 SSE 時，若任務狀態已是 `paused`，SSE 會立即關閉。在 `reprobe_external_links` 後，任務可能從 `completed` 切換為 `paused`，此時前端再重新連線 SSE 以等待啟動任務，會立即被關閉。

**建議**（已移至 `doc/todo.md` 待排程）：考慮在 `paused` 狀態下，若偵測到有 `pending` 狀態的外部連結，保持 SSE 連線開啟，或在 API 文件中明確說明此行為讓前端改用輪詢。

---

## 維度八：文件一致性 (Documentation Consistency)

### D-01 ✅ FALSE POSITIVE：`doc/architecture.md` MCP Server 組件說明（已確認誤報）

**確認結果**：經查閱原始碼與文件後，此項為**誤報**。

`doc/architecture.md` 已完整包含 `scripts/mcp_server.py` 與 `doc/mcp_usage.md` 之檔案目錄說明、架構層級定位（L157-L158）與參考文件連結。**架構文件已精確反映 MCP Server，無須任何修改**。

---

### D-02 🟢 LOW：`format_crawl_queue_item` 回傳字典的鍵名不一致應文件化（已列入 todo.md）

**位置**：`crawler/utils.py` L199-L235

**問題**：回傳字典中同時存在 `"Status"`、`"Status Category"`（大寫 / 有空格）與 `"is_secure"`、`"http_status_code"`（小寫 / 底線）兩種命名風格，docstring 備注這是「對歷史 CSV/Excel 格式的相容設計」，但此設計決策未在 API 規格文件中明確記錄。

**建議**（已移至 `doc/todo.md` 待排程）：在 `doc/api_spec.md` 中明確記錄此欄位命名為遺留設計，並標注未來重構計劃。

---

### D-03 ✅ FALSE POSITIVE：`_handle_error` 的函式簽名型別標註（已確認誤報）

**位置**：`crawler/runner.py` L1007-L1013 (`_handle_error`)

**確認結果**：經查驗原始碼後，此項為**誤報**。

`httpx.HTTPError` 即為 HTTPX 例外體系的頂層基類（`RequestError` 與 `HTTPStatusError` 皆繼承自它）。呼叫端（L715）捕捉 `httpx.HTTPError` 後傳入此函式，`e: httpx.HTTPError` 型別標註非常精確且符合規範，**現行型別標註完全正確，無須修改**。

---

## 維度九：需求合規性 (Requirements Compliance)

### RC-01 🟡 MEDIUM：`max_depth` 存取路徑應統一至 `CrawlerConfig`（已列入 todo.md）

**位置**：`crawler/runner.py` `_initialize` 與 `_run_loop`

**問題**：`max_depth` 被讀入 `crawler_config_dict` 但未被加入 `CrawlerConfig` dataclass，在 `_run_loop` 中從 `self.crawler_config_dict.get("max_depth")` 直接取得而非透過 `self.config`。這意味著 `CrawlerConfig` 的型別安全保護未涵蓋此參數，形成兩種存取路徑並存的不一致設計。

**建議**（已移至 `doc/todo.md` 待排程）：將 `max_depth` 加入 `CrawlerConfig` dataclass 並統一從 `self.config.max_depth` 存取。

---

### RC-02 🟢 LOW：`doc/requirements.md` 的軟刪除要求與實作偏差未明確標注（已列入 todo.md）

**問題**：`doc/requirements.md` §4.1 規範跨資料庫資源刪除應採軟刪除，但目前實作為硬刪除。雖然 `todo.md` 已將此列為「觀察中」，但需求文件本身未標注「已知偏差（Intentional Deviation）」。

**建議**（已移至 `doc/todo.md` 待排程）：在 `doc/requirements.md` 的軟刪除需求處添加說明，標注此為已知偏差並指向 `todo.md` 的追蹤條目。

---

## 亮點設計 (Commendations)

以下設計值得特別表揚，體現了高水準的工程實踐：

1. **SSRF 防禦機制**：`_resolve_and_check_ssrf` 在 DNS 解析後對 IP 進行 `is_safe_ip` 驗證，徹底防止 DNS Rebinding 攻擊。
2. **Session Token 安全**：Token 以 SHA-256 雜湊儲存（不儲存明文），且使用 `secrets.token_urlsafe(32)` 生成（128 位安全隨機）。
3. **Timing Attack 防禦**：`authenticate_with_password` 在帳號不存在時仍執行 `hash_password(password)`，確保回應時間一致。
4. **Cookie-gate 繞過**：`accumulated_cookies` 跨跳累積機制優雅地解決了 Citrix NetScaler 等 WAF 的挑戰。
5. **進度追蹤記憶體優化**：`JobRunnerState` 的計數器策略避免了 Hot Path 上的 O(N) 資料庫查詢。
6. **雙階佇列**：`primary_id_deque` / `other_id_deque` 設計確保主網域優先爬取，提升爬蟲深度效率。
7. **Zombie Job 清理**：PID 檔案 + `/proc/[pid]/stat` 啟動時間比對，完美解決 PID 重用誤判問題。
8. **樂觀鎖防止雙重 Spawn**：`start_job` 使用條件式 UPDATE 確保任務啟動的原子性。
9. **全域例外捕捉**：`backend/main.py` 的 `global_exception_handler` 確保錯誤訊息不洩漏至 HTTP 回應，僅記錄至日誌。

---

## 發現摘要

| ID | 嚴重度 | 類別 | 簡述 |
|----|--------|------|------|
| F-01 | ✅ 誤報 | 併發 | ContextVar 子執行緒傳播（Python 3.7+ 快照語義已保證正確） |
| F-02 | 🟡 MEDIUM | 併發 | `_cleanup_finished_processes` 節流計時器未更新（已列入 todo.md） |
| F-03 | 🟡 MEDIUM | 併發 | `active_jobs` 應文件化其 asyncio 單執行緒假設（已列入 todo.md） |
| S-01 | ✅ 誤報 | 資安 | CSRF Cookie 的 SameSite 屬性（已確認正確，已設 strict） |
| S-02 | 🟡 MEDIUM | 資安 | `sanitize_error_message` 未防禦日誌注入（Log Injection）（已列入 todo.md） |
| S-03 | 🟢 LOW | 資安 | HTML nonce 注入邊界情況防護與單元測試補充（已列入 todo.md） |
| S-04 | ✅ 誤報 | 資安 | `is_safe_ip` 的 IPv6 ULA 覆蓋（Python 3.11+ 已原生涵蓋） |
| S-05 | 🟡 MEDIUM | 資安 | `_ACTIVE_PROCESSES` 應明確加鎖保護（已列入 todo.md） |
| A-01 | 🟠 HIGH | 架構 | `crawler` 對 `backend.events` 反向依賴（已知技術債）|
| A-02 | 🟡 MEDIUM | 架構 | 批次大小魔術數字應提取為常數（已列入 todo.md） |
| A-03 | 🟡 MEDIUM | 架構 | `cast()` 應替換為實際型別轉換（已列入 todo.md） |
| P-01 | 🟢 LOW | 效能 | 雙階佇列備援查詢（防禦性機制，維持現狀無需優化） |
| P-02 | 🟢 LOW | 效能 | `get_all_jobs` 缺乏分頁機制（已列入 todo.md） |
| R-01 | 🟠 HIGH | 韌性 | 狀態查詢異常可能誤判任務失敗（已列入 todo.md） |
| R-02 | 🟡 MEDIUM | 韌性 | 指數退避 `time.sleep()` 阻塞暫停響應（已列入 todo.md） |
| R-03 | 🟢 重複 | 韌性 | `retry_failed_job` 批次邏輯（已併入 A-02，無須重複追蹤） |
| T-01 | 🟠 HIGH | 測試 | 核心降級路徑缺乏整合測試（已列入 todo.md） |
| T-02 | 🟡 MEDIUM | 測試 | `sanitize_error_message` 邊界測試不足（已列入 todo.md） |
| API-01 | ✅ 誤報 | API | `start_url` 格式驗證（Pydantic 驗證器已涵蓋） |
| API-02 | 🟡 MEDIUM | API | SSE 的 `paused` 狀態處理可能讓前端陷入輪詢（已列入 todo.md） |
| D-01 | ✅ 誤報 | 文件 | `architecture.md` 未反映 MCP Server（已確認已完整反映） |
| D-02 | 🟢 LOW | 文件 | 回傳字典鍵名命名不一致應明確記錄（已列入 todo.md） |
| D-03 | ✅ 誤報 | 文件 | `_handle_error` 型別標註（已確認正確） |
| RC-01 | 🟡 MEDIUM | 需求 | `max_depth` 存取路徑應統一（已列入 todo.md） |
| RC-02 | 🟢 LOW | 需求 | 軟刪除偏差未在需求文件中明確標注（已列入 todo.md） |

---

## 建議行動優先序

### 立即行動（本週）
1. **S-01**：確認 CSRF Cookie 的 `SameSite` 設定 → 若未設定立即修復
2. **S-02**：在 `sanitize_error_message` 添加 CRLF 清理（一行修改，風險極低）
| R-01 | 🟠 HIGH | 韌性 | 狀態查詢異常可能誤判任務失敗（已列入 todo.md） |

### 近期排程（下一個 Sprint）
4. **F-01**：在 `check_single` 閉包顯式設定 `ContextVar`
5. **F-02**：修復 `_cleanup_finished_processes` 的節流計時器
6. **T-01**：建立核心降級路徑的整合測試套件
7. **API-01**：強化 `start_url` 的 Pydantic Schema 驗證
8. **D-01**：更新 `doc/architecture.md` 加入 MCP Server 描述

### 中期規劃（後續 Sprint）
9. **A-01**：解耦 `crawler` 對 `backend.events` 的依賴（已在 todo.md 追蹤）
10. **RC-01**：統一 `max_depth` 的存取路徑至 `CrawlerConfig`
11. **R-02**：重構指數退避機制以支援快速暫停響應

---

*本報告由 Antigravity AI 依照 `deep_code_review` SKILL 自動產出，審查日期 2026-07-27。*
