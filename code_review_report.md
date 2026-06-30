# Link-Checker 程式碼與架構審查報告

## 1. 系統架構與文件審視 (Architecture & Documentation)
經過審視 `doc/architecture.md` 與 `doc/requirements.md`，專案的文件規劃極度詳盡且具備企業級的維運視野。架構設計嚴守 CLI-First 原則與模組解耦，雙資料庫分離 (Auth DB / Crawler DB) 與軟刪除機制能有效確保資料最終一致性。

**文件可微調或補充之建議：**
- **前端 Vanilla JS 限制的長期維護性**：文件強烈要求使用 Vanilla JS + ESM 以降低供應鏈風險。此立意良好，但對於龐大的前端狀態管理 (如 SSE 狀態更新、複雜的表格排序與篩選防抖) 會帶來顯著的程式碼複雜度。建議可於文件中補充「前端狀態管理與元件封裝的具體規範」，避免未來程式碼出現義大利麵條式的 DOM 操作。
- **`sqlite` 高併發注意事項**：雖然文件提到啟用 `WAL` 模式與 `check_same_thread=False`，但在極高併發寫入時仍可能有 `database is locked` 的問題，文件中提及的「例外回滾機制」非常關鍵，建議在開發時也要嚴格測試 SQLite 的併發寫入瓶頸。

## 2. 一般現實狀況的運作邏輯 (Real-World Operations)
- **OOM (Out Of Memory) 防護**：`crawler/core.py` 中 `_download_content` 使用了分塊串流 (`iter_bytes(chunk_size=8192)`) 並配有 `max_content_length` 的截斷機制，這在現實爬蟲中非常實用，能有效防止惡意網站傳送無限大檔案導致系統崩潰。
- **殭屍任務與中斷恢復**：透過 PID 檢查 `_is_job_running` 的懶加載機制，捨棄高耗能的心跳機制，是非常聰明且貼近維運現實的設計。
- **高階反爬蟲穿透**：系統內建了拔除 `Sec-Ch-Ua` 特徵，甚至底層啟用了 `curl_cffi` 來進行 TLS 指紋偽裝。這對於現實中常遇到 Cloudflare 或企業 WAF 阻擋的情境來說，是非常強大的武器。

## 3. 程式邏輯 (Program Logic - 以 `crawler/core.py` 為例)
- **例外統一封裝**：`_FETCH_SAFE_EXCEPTIONS` 將底層 `httpx` 與 `socket` 錯誤妥善捕捉，防止主流程因為未預期的網路異常而中斷，符合高容錯的爬蟲需求。
- **DNS 解析攔截 (Monkey Patch)**：
  - 為了實現 SSRF 防禦 (`dns_override` 與 `socket.getaddrinfo` patch)，程式採用了 `threading.local()` 來做執行緒安全的 DNS 替換。這在同步架構下是安全的。
  - **[改進建議]**：在 `_patched_getaddrinfo` 中有 `host_str = host.decode("utf-8") if isinstance(host, bytes) else host`，雖然大部份時候 host 是 `str` 或 `bytes`，但若遇到 `None` (如 `socket.getaddrinfo(None, ...)` 查詢本機介面)，`host_str` 為 `None`，若呼叫 `.decode()` 或放入 `overrides` dict 中作為 key 需小心處理。建議加上對 `host` 型別的完整防護。
- **Cookie 分桶隔離**：在跨域重導向時，`crawler/core.py` 手動管理 `accumulated_cookies`，依據 domain 進行分桶。這不僅符合資安要求，也突破了部分 `httpx` 跨域 Cookie 遺失的限制。

## 4. 資安要求 (Security Requirements)
- **SSRF 防禦與 DNS Rebinding**：爬蟲在發送請求前先 `resolve_ip` 並驗證是否為 `is_safe_ip`，之後透過 context manager 強制綁定 IP。這是非常高標準的 SSRF 防禦。
- **零信任與密碼安全**：文件規定密碼強制使用 `bcrypt` (work factor >= 12)，邀請碼單次使用即作廢，並防禦帳號列舉攻擊。
- **匯出安全**：CSV 匯出防禦 Excel 注入攻擊（CSV Injection），這在資安稽核工具中是常被忽略但極度重要的細節，文件規範很到位。

## 5. 程式註解與風格 (Code Comments & Styling)
- **Docstrings**：`crawler/core.py` 中的函數皆具備詳細的 Google Style Docstrings，清楚標明 `Args`, `Returns` 與例外狀況。
- **Linting 標籤**：保留了如 `# pylint: disable=too-many-lines`, `# pylint: disable=too-many-locals` 等標籤。雖然這代表某些函數有點過長（例如 `fetch` 函數），但這在處理重導向、降級重試等多層容錯邏輯的爬蟲核心中是常見的，可以接受。適度的 suppress 比強行拆分導致邏輯破碎來得好。

---

### 總結
本專案的架構設計與文件嚴謹度遠超一般開源專案，特別在「資安防禦 (SSRF, Cookie-gate)」與「維運穩定度 (OOM, Tarpit 防禦, 殭屍任務檢測)」上有極為深入的實作考量。

**若需進入直接修改階段，建議優先處理：**
1. `crawler/core.py` 中 `socket.getaddrinfo` monkey patch 對於 `host=None` 的容錯處理。
2. 確認 `target_domains` 的子網域繼承邏輯在 `is_in_domain_list` 中是否與預期完全一致。
