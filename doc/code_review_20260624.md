# 專案完整 Code Review 報告

> 本報告依據 [requirements.md](requirements.md) 對本專案進行系統性審查，確認需求完成狀態、業務邏輯正確性，以及資訊安全防護完整性。

---

## 一、功能需求完成狀態審查

### § 2 爬蟲核心功能

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **BFS 廣度優先巡覽** | ✅ 完成 | [`crawler/runner.py#L297`](../crawler/runner.py#L297)：`order_by(CrawlQueue.id)` 確保 FIFO；`_run_loop()` 逐筆從佇列取出 |
| **指定起點 Start URL** | ✅ 完成 | `crawler/manager.py` `create_job()`；`cli.py` `--start-url` |
| **最大深度 / 最大頁數限制** | ✅ 完成 | `crawler/runner.py` `_process_item()`；設定由 `crawler/config_utils.py` 載入 |
| **越界重導向防護** | ✅ 完成 | `crawler/core.py` `_handle_redirect()` |
| **`<base>` 標籤支援** | ✅ 完成 | `crawler/core.py` `_extract_base_url()` |
| **網址去重** | ✅ 完成 | `crawler/runner.py` `_handle_internal_links()`；DB 層 UniqueConstraint |
| **外連標籤掃描 (a/script/img/link/form/object)** | ✅ 完成 | `crawler/core.py` `_collect_raw_links()`（涵蓋 href/src/action/data 屬性） |
| **外連 IP 解析 + HTTP 存活檢查** | ✅ 完成 | `crawler/core.py` `check_external_link()`；`_resolve_and_check_ssrf()` |
| **外連去重 (job_id, source, target UniqueConstraint)** | ✅ 完成 | `crawler/models.py` `ExternalLink` 模型 |
| **is_secure 安全協定標記** | ✅ 完成 | `crawler/core.py` `_execute_external_request()` 寫入 `is_secure` |
| **大檔案攔截 (Chunked Stream)** | ✅ 完成 | `crawler/core.py` `_download_content()`：分塊讀取並在超過上限後截斷 |
| **靜態副檔名過濾** | ✅ 完成 | `crawler/core.py` `_check_ignore_rules()` |
| **媒體內容攔截 (Content-Type)** | ✅ 完成 | `crawler/core.py` `_check_mime_type()` |
| **preconnect/dns-prefetch 忽略** | ✅ 完成 | `crawler/core.py` `_collect_raw_links()`：L427-432 明確過濾 |
| **正規表示式排除路徑** | ✅ 完成 | `crawler/core.py` `_check_ignore_rules()`；`_compile_regexes()` |
| **延遲等待 (請求延遲 + 延遲抖動)** | ✅ 完成 | `crawler/runner.py` `_get_domain_delay()`；抖動由 config 中 jitter 比例控制 |
| **網域專屬延遲 + 最長匹配優先** | ✅ 完成 | `crawler/runner.py` `_get_domain_delay()`；`crawler/config_utils.py` |
| **動態 User-Agent + 瀏覽器指紋** | ✅ 完成 | `crawler/profiles.py`；`crawler/core.py` 隨機配對 Sec-Ch-Ua 等標頭 |
| **HTTP/2 支援** | ✅ 完成 | `crawler/core.py`：使用 `httpx` 支援 h2 協定 |
| **HEAD → GET 雙層探測 + 自動降級** | ✅ 完成 | `crawler/core.py` `_execute_external_request()` → `_fallback_get()` |
| **社群平台自動降級 (Social Domains)** | ✅ 完成 | `crawler/core.py` `_check_external_single()` |
| **HTTP → HTTPS 自動升級重試** | ✅ 完成 | `crawler/core.py` `_handle_http_failure_retry()` |
| **任務級存活檢查快取** | ✅ 完成 | `crawler/runner.py` `_check_single_link()`：快取已探測的外連結果 |
| **多工並發外連探測** | ✅ 完成 | `crawler/runner.py` `_handle_external_links()`：`ThreadPoolExecutor` |
| **雙 HttpClient (SSL 豁免)** | ✅ 完成 | `crawler/core.py` `_get_client()`；ssl_exempt_domains 最長匹配 |
| **錯誤分類重試 (暫時性 vs 永久性)** | ✅ 完成 | `crawler/core.py` `_handle_http_failure_retry()`；指數退避 |
| **畸形網域容錯** | ✅ 完成 | `crawler/core.py` `check_external_link()`：捕捉 UnicodeError/ValueError/socket.gaierror |
| **Proxy 支援 + 環境變數優先** | ✅ 完成 | `crawler/config_utils.py`；`CRAWLER_PROXY_URL` 環境變數 |
| **設定三層合併 (env > task YAML > global YAML)** | ✅ 完成 | `crawler/config_utils.py` `merge_and_validate_crawler_config()` |

### § 3 任務管理與容錯

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **PID 檔案持久化子程序追蹤** | ✅ 完成 | `backend/jobs/services/process.py`；`log/pids/` 目錄 |
| **殭屍任務懶加載偵測** | ✅ 完成 | `backend/jobs/services/management.py` `_cleanup_zombie_jobs()`：動態比對 PID |
| **暫停 / 恢復** | ✅ 完成 | `backend/jobs/routers/management.py`：`/pause`、`/resume` 端點；`crawler/manager.py` |
| **重置 (Reset)** | ✅ 完成 | `crawler/manager.py` `reset_job()`；`/api/jobs/{id}/reset` |
| **刪除 (Delete)** | ✅ 完成 | `crawler/manager.py` `delete_job()`；`/api/jobs/{id}` DELETE |
| **失敗重試 (Retry Failed)** | ✅ 完成 | `crawler/manager.py` `retry_failed_job()`；`/api/jobs/{id}/retry-failed` |
| **排隊機制 + 並發限制 (Queued)** | ✅ 完成 | `backend/jobs/services/scheduler.py`；`CRAWLER_MAX_CONCURRENT_JOBS` |
| **強制接管 (Takeover)** | ✅ 完成 | `backend/admin/router.py` `/admin/jobs/{id}/takeover` |
| **任務移交 (Transfer)** | ✅ 完成 | `/api/jobs/{id}/transfer`；`crawler/manager.py` `transfer_job()` |
| **任務複製 (Duplicate)** | ✅ 完成 | 前端 `jobs.js`：`?clone=` 參數帶入新增表單；Proxy 密碼遮蔽由後端 `get_job_detail()` 處理 |
| **局部重新探測 (Partial Reprobe)** | ✅ 完成 | `backend/jobs/routers/management.py` `/reprobe`；`backend/jobs/services/reprobe.py` |
| **Email 通知 (completed/error)** | ✅ 完成 | `backend/jobs/services/notifier.py`；`crawler/runner.py` 任務結束時觸發 |
| **CLI 完整生命週期指令** | ✅ 完成 | `cli.py`：`--pause`/`--resume`/`--reset`/`--delete`/`--retry-failed` |
| **CLI 匯出 + 篩選** | ✅ 完成 | `cli.py`：`--export`/`--export-internal`/`--filter`/`--exclude`/`--group-by`/`--json` |
| **CLI 完整 ZIP 報表 (--export-full)** | ✅ 完成 | `cli.py`；`backend/jobs/services/exporter.py` |
| **任務備份/匯入 (manage_job_data.py)** | ✅ 完成 | `scripts/manage_job_data.py`；`scripts/job_sync.sh` |
| **資料回填工具** | ✅ 完成 | `scripts/backfill_target_domain.py`；`scripts/backfill_status_category.py` |
| **設定檔持久化快照** | ✅ 完成 | `crawler/manager.py`：任務啟動時將 config 序列化存入 `jobs.config_json` |
| **多使用者任務隔離** | ✅ 完成 | `crawler/models.py` `jobs.user_id`；所有 API 端點均驗證 `user_id` |

### § 4 系統架構

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **雙資料庫分離 (Auth DB / Crawler DB)** | ✅ 完成 | `backend/auth/db.py`；`crawler/models.py`；`AUTH_DB_URL`/`CRAWLER_DB_URL` |
| **SQLite PRAGMA foreign_keys=ON** | ✅ 完成 | 於 `crawler/utils.py` `create_optimized_engine` 已透過 `@event.listens_for` 實作，且藉由 `if sqlite` 判斷兼顧 PostgreSQL 相容性 |
| **軟刪除 + 最終一致性** | ✅ 完成 | `backend/auth/service.py` `cleanup_deleted_user_task()`；帳號軟刪除後由背景任務清理 Crawler DB |
| **SSE 串流 + 斷線偵測** | ✅ 完成 | `backend/jobs/routers/management.py` `stream_job_updates()`：`await request.is_disconnected()` |
| **爬蟲以子程序執行** | ✅ 完成 | `backend/jobs/services/management.py` `start_job()`：`subprocess.Popen` |
| **CLI-First 獨立運作** | ✅ 完成 | `cli.py` 完全不依賴 backend 模組；`notifier.py` 使用 try/except ImportError |
| **DB Schema 合規檢驗** | ✅ 完成 | `scripts/check_db_schema.py` |
| **SQLite → PostgreSQL 遷移工具** | ✅ 完成 | `scripts/migrate_sqlite_to_pg.py` |

### § 5 資訊安全

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **SSRF 防禦 + 私有 IP 阻絕** | ✅ 完成 | `crawler/core.py` `_resolve_and_check_ssrf()`；Socket monkey-patch `_patched_getaddrinfo()` |
| **CSRF 防禦 (Double Submit Cookie)** | ✅ 完成 | `backend/deps.py` `require_csrf()`：`secrets.compare_digest()` 恆定時間比對 |
| **CSP Nonce + X-Frame-Options + X-Content-Type** | ✅ 完成 | `backend/main.py` `SecurityHeadersMiddleware` |
| **bcrypt 密碼雜湊 (rounds=12)** | ✅ 完成 | `backend/auth/password.py`：`bcrypt.gensalt(rounds=12)` |
| **XSS 防禦 (escapeHtml / textContent)** | ✅ 完成 | `frontend/js/job-detail.js`：全面使用 `textContent` 與 `escapeHtml()`；`innerHTML` 僅用於清空 |
| **CSV 注入防禦** | ✅ 完成 | `backend/jobs/routers/export.py` `_sanitize_csv_dict()`：透過 `_sanitize_csv_value()` 跳脫危險字元 |
| **Proxy 密碼遮蔽** | ✅ 完成 | `backend/jobs/services/management.py` `get_job_detail()`：將密碼替換為 `***` |
| **全域例外攔截 (Stack Trace 隱藏)** | ✅ 完成 | `backend/main.py` `global_exception_handler()`：捕捉所有 Exception 回傳標準 500 |
| **計時攻擊防禦 (Timing Attack)** | ✅ 完成 | `backend/deps.py`：`secrets.compare_digest()`；忘記密碼流程中無論帳號是否存在都執行雜湊運算 |
| **Session 滑動視窗續期** | ✅ 完成 | `backend/auth/service.py` `refresh_session()` |
| **Session StaleDataError 競態防禦** | ✅ 完成 | `backend/auth/service.py`：捕捉 `StaleDataError` 並執行 `db.rollback()` |
| **登入失敗鎖定** | ✅ 完成 | `backend/auth/service.py` `_increment_failed_login()`：連續失敗達閾值後鎖定 |
| **忘記密碼限速 (IP Rate Limiting)** | ✅ 完成 | `backend/auth/service.py` `request_password_reset()`：依 IP 統計近期申請次數 |
| **防帳號列舉 (Anti-Enumeration)** | ✅ 完成 | `request_password_reset()`：無論帳號是否存在皆執行相同耗時操作後返回 |
| **路徑防禦 (Path Traversal)** | ✅ 完成 | `cli.py`：`os.path.realpath()` 比對安全目錄 |
| **資源耗盡防禦 (設定上下限)** | ✅ 完成 | `crawler/config_utils.py` `_enforce_crawler_limits()` |
| **Cookie Secure + HttpOnly** | ✅ 完成 | `backend/auth/router.py` `_set_session_cookie()`：設有 Secure/HttpOnly 旗標（非 debug 模式） |
| **生產環境 CORS 關閉** | ✅ 完成 | `backend/main.py`：僅 debug 模式開放 CORS |

### § 6 使用者帳號管理

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **邀請制登入 (UUID 邀請碼)** | ✅ 完成 | `backend/auth/service.py` `create_invitation()`；`authenticate_with_invitation()` |
| **首次登入強制設密** | ✅ 完成 | `authenticate_with_invitation()`；`backend/deps.py` 攔截 pending 帳號 |
| **密碼複雜度驗證** | ✅ 完成 | `backend/auth/service.py` `set_first_password()`：長度 ≥ 12、大小寫+數字+特殊符號 |
| **忘記密碼 + Token Hash 儲存** | ✅ 完成 | `backend/auth/service.py`：`_hash_token()` 儲存 Hash；1 小時過期 |
| **密碼重設後強制登出所有 Session** | ✅ 完成 | `reset_password()`：呼叫 `invalidate_all_user_sessions()` |
| **帳號狀態管理 (Pending/Active/Suspended/Expired)** | ✅ 完成 | `backend/auth/models.py`；`backend/admin/router.py` `update_user()` |
| **角色提降 (Promote/Demote)** | ✅ 完成 | `backend/admin/router.py` `update_user()` |
| **Session GC 背景清理** | ✅ 完成 | `backend/auth/service.py` `run_session_gc_task()` |
| **初始管理員 Bootstrap (CLI)** | ✅ 完成 | `cli.py` `--create-admin`；強制設密攔截 |

### § 7 前台功能

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **任務列表 + 狀態篩選** | ✅ 完成 | `frontend/js/jobs.js`；`frontend/app.html` |
| **完整 UUID 呈現 / 選單格式化 (前 5 + 後 5)** | ✅ 完成 | `frontend/js/jobs.js`：任務列表完整 UUID；複製/比對選單截短 |
| **新增任務表單 + URL 前端驗證** | ✅ 完成 | `frontend/app.html`；`frontend/js/jobs.js` |
| **網域自動填寫 (Domain Auto-Fill)** | ✅ 完成 | `frontend/js/jobs.js`：blur 事件解析 hostname 填入欄位 |
| **SSE 即時進度更新** | ✅ 完成 | `frontend/js/job-detail.js` `startSseStream()`；後端 `stream_job_updates()` |
| **外連結果表格 (來源→目標欄位順序)** | ✅ 完成 | `frontend/app.html` / `job-detail.js` |
| **外連篩選卡片 (DNS/Broken/Blocked/Insecure/Healthy)** | ✅ 完成 | `frontend/js/job-detail.js` 外連篩選邏輯 |
| **外連重新探測 (Reprobe)** | ✅ 完成 | `frontend/app.html` `btn-ext-reprobe-selected`；`backend/jobs/services/reprobe.py` |
| **內連診斷 7 大失效分類** | ✅ 完成 | `frontend/js/job-detail.js` 內連分類卡片；`backend/jobs/services/internal_results.py` |
| **內連重新探測** | ✅ 完成 | `frontend/app.html` `btn-int-reprobe-selected` |
| **批次勾選 Checkbox** | ✅ 完成 | `frontend/js/job-detail.js`：`int-select-all`/`ext-select-all` |
| **任務差異比對引擎 (Diff Engine)** | ✅ 完成 | `backend/jobs/routers/results.py` `get_job_diff()`；`frontend/js/compare.js` |
| **匯出 CSV/JSON/ZIP** | ✅ 完成 | `backend/jobs/routers/export.py` |
| **篩選防抖 500ms Debounce** | ✅ 完成 | `frontend/js/job-detail.js`：`_filterTimeout` / `_internalFilterTimeout`，`setTimeout(..., 500)` |
| **半透明載入緩衝 (opacity 0.5)** | ✅ 完成 | `frontend/js/job-detail.js`：`tableEl.style.opacity = '0.5'` |
| **API 串行加載** | ✅ 完成 | `frontend/js/job-detail.js` `loadResults()`：先載入表格再呼叫 summary |
| **全站排序 + 篩選 (Client-side)** | ✅ 完成 | `frontend/js/job-detail.js`；`frontend/js/jobs.js` |
| **Toast 非阻塞通知系統** | ✅ 完成 | `frontend/js/toast.js` |
| **自訂 Modal 二次確認 (非 alert)** | ✅ 完成 | `frontend/js/job-detail.js` `showConfirm()`；`frontend/app.html` confirm-modal |
| **滾動穿透防禦** | ✅ 完成 | `frontend/app.html`：Modal 開啟時設定 `body.modal-open` 的 `overflow: hidden` |
| **SPA Hash-based Routing** | ✅ 完成 | `frontend/app.html`：`hashchange` 事件驅動；`window.location.hash` |
| **分頁快速跳頁 (« »)** | ✅ 完成 | `frontend/js/job-detail.js` 分頁元件 |
| **非同步 Race Condition 防禦** | ✅ 完成 | `frontend/js/job-detail.js`：API 回應前比對 `jobId` 是否與 `_currentJobId` 相符 |
| **時間戳記本地化 (YYYY/MM/DD HH:mm:ss)** | ✅ 完成 | 前端 JS 統一格式化函式 |
| **密碼強度指示器** | ✅ 完成 | `frontend/set-password.html` |
| **API 請求統一封裝 (含 CSRF 自動夾帶)** | ✅ 完成 | `frontend/js/api.js`：統一讀取 CSRF cookie 放入 header；401 自動重導向 |

### § 8 後台功能

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **使用者列表 + 邀請 + 停用 + 刪除** | ✅ 完成 | `backend/admin/router.py`：`/admin/users` 系列端點 |
| **重新寄送邀請** | ✅ 完成 | `/admin/users/{id}/resend-invite` |
| **全任務列表 (跨使用者)** | ✅ 完成 | `backend/admin/router.py` `list_all_jobs()` |
| **任務強制接管 (Takeover)** | ✅ 完成 | `/admin/jobs/{id}/takeover` |
| **全域配置管理 + 關聯性驗證** | ✅ 完成 | `backend/admin/router.py` `update_config()`；`validate_min_max_pairs()` 交叉驗證 |
| **配置修改寫入操作日誌** | ✅ 完成 | `update_config()`：寫入 `AuthLog` 含前後差異 |
| **SMTP 唯讀檢視 + 測試郵件** | ✅ 完成 | `/admin/smtp`、`/admin/smtp/test` |
| **SMTP 密碼遮蔽** | ✅ 完成 | `backend/admin/router.py` `get_smtp_config()`：回傳時遮蔽密碼 |
| **操作日誌 + 日期範圍篩選** | ✅ 完成 | `/admin/logs`；支援 `start_date`/`end_date` 參數 |
| **後台路由 RBAC 隔離** | ✅ 完成 | `backend/admin/router.py`：依賴 `require_admin` 驗證 |

### § 9-14 技術堆疊 / 效能 / 配置 / CI/CD / 測試

| 需求 | 狀態 | 實作位置 |
|------|------|---------|
| **Vanilla JS + ESM (無框架)** | ✅ 完成 | `frontend/js/*.js`：均使用 `type="module"` |
| **禁止 CDN 未鎖定版本** | ✅ 完成 | 前端未引入任何外部 CDN 資源 |
| **HTTP-only Session Cookie** | ✅ 完成 | `backend/auth/router.py`：`httponly=True` |
| **FastAPI ASGI + 同步 I/O 用 def** | ✅ 完成 | `backend/main.py`；所有 DB 密集端點均為同步 `def` |
| **健康檢查端點 /api/health** | ✅ 完成 | `backend/main.py` `health_check()` |
| **靜態資源 In-Memory Cache** | ✅ 完成 | `backend/main.py` `_serve_html_with_nonce()`：生產環境字典快取 |
| **暫存檔 GC (ZIP 匯出後清理)** | ✅ 完成 | `backend/jobs/routers/export.py` `export_full_report()`：`BackgroundTasks` 清理 |
| **SPA Fallback (404 重導向)** | ✅ 完成 | `backend/main.py`：攔截非 API 的 404 重導向 |
| **yield_per() 批次迭代防 OOM** | ✅ 完成 | `backend/jobs/services/exporter.py`；`scripts/manage_job_data.py` |
| **Streaming 串流匯出 (Generator)** | ✅ 完成 | `backend/jobs/routers/export.py`：所有匯出均採用 Generator |
| **原生 SQL 聚合 (json_group_array)** | ✅ 完成 | `backend/jobs/services/external_results.py`；SQLite 原生 JSON 函式 |
| **passive_deletes + ON DELETE CASCADE** | ✅ 完成 | `crawler/models.py`：`passive_deletes=True`；`ondelete="CASCADE"` |
| **複合索引 (Composite Index)** | ✅ 完成 | `crawler/models.py`：`ix_crawl_queue_job_category`、`ix_external_links_job_category` 等 |
| **status_category 預計算欄位** | ✅ 完成 | `crawler/models.py`；`CrawlQueue.status_category`、`ExternalLink.status_category` |
| **聯集合併 (ignore_extensions/ssl_exempt_domains)** | ✅ 完成 | `crawler/config_utils.py` `_merge_crawler_lists()` |
| **設定上下限強制** | ✅ 完成 | `crawler/config_utils.py` `_enforce_crawler_limits()` |
| **日誌輪轉 (RotatingFileHandler)** | ✅ 完成 | `cli.py`：`RotatingFileHandler(maxBytes=10MB, backupCount=5)` |
| **Pytest 整合測試 + Fixture 隔離** | ✅ 完成 | `test/test_api.py`、`test/test_cli.py`、`test/test_admin_logs.py` 等 |
| **Playwright E2E + API Mocking** | ✅ 完成 | `test/e2e/test_app.py`：`page.route()` 攔截 API |
| **Ruff + Pylint 靜態分析** | ✅ 完成 | `ruff.toml`；`.pylintrc` |
| **OpenAPI 自動化文件生成** | ✅ 完成 | `scripts/gen_api_doc.py` |
| **單一 URL 診斷工具** | ✅ 完成 | `scripts/test_url.py`；`.vscode/launch.json` |

---

## 二、業務邏輯審查

### 正確的業務邏輯

**1. 「重試」vs「重置」vs「局部重新探測」語意正確分離**

- **重置 (Reset)**：清除所有外連結果與佇列，從零重新開始。實作：[`crawler/manager.py` `reset_job()`](../crawler/manager.py#L355)
- **重試 (Retry Failed)**：僅針對「已完成」但有部分失敗的任務，重新加入佇列，不清除成功紀錄。實作：[`crawler/manager.py` `retry_failed_job()`](../crawler/manager.py#L408)
- **局部重新探測 (Reprobe)**：針對特定選定 URL 重設為 pending，更精細的局部操作。實作：[`backend/jobs/services/reprobe.py`](../backend/jobs/services/reprobe.py)

**2. 按鈕顯示邏輯符合業務規則**（已於本次 session 修正）

- `canRetry`：僅在 `status === 'completed'` 且非執行中才顯示「重試」按鈕。
- `canReset`：在 `completed`/`error`/`paused` 且非執行中時顯示。
- 中斷 (`error`) 狀態：僅有「啟動」和「重置」，**無「重試」**，符合規格。
- 實作：[`frontend/js/job-detail.js#L1007`](../frontend/js/job-detail.js#L1007)

**3. 外連 Reprobe 依分組模式差異化處理**

- 依「外連目標」聚合 → 重測目標外連 URL 本身。
- 依「自家網頁」聚合 → 重測包含外連的來源內部頁面。
- 平舖列表 / 依網域統計 → 隱藏 Reprobe 按鈕，避免業務邏輯衝突。

**4. Proxy 密碼不落地**：任務配置快照儲存時密碼以 `***` 遮蔽，複製任務時用戶需重新輸入。

### 值得關注的業務邏輯

> [!NOTE]
> **SQLite PRAGMA foreign_keys=ON 已完美實作**
>
> 經重新確認，專案在 `crawler/utils.py` 的 `create_optimized_engine` 函式中，已經針對 SQLite 連線註冊了 `@event.listens_for(engine, "connect")` 事件，確實執行了 `PRAGMA foreign_keys=ON`。並且因為外層有 `if db_url.startswith("sqlite"):` 判斷，所以完全相容 PostgreSQL 預設的外鍵行為。

> [!NOTE]
> **資料庫 Schema 遷移未使用 Alembic**（需求 §9.3 建議）
>
> 目前採用 `create_all()` 直接建表，在生產環境更新欄位時，若資料庫已存在，`create_all()` 不會自動新增欄位，需手動執行 `ALTER TABLE`。`scripts/check_db_schema.py` 可輔助偵測差異，但缺乏自動遷移能力。

---

## 三、資訊安全審查

### 強健的安全防護

| 防護項目 | 評級 | 說明 |
|---------|------|------|
| **SSRF 防禦** | 🟢 優秀 | Socket 層級 monkey-patch + IP 白名單驗證；`CRAWLER_ALLOW_LOCAL_IPS` 例外豁免 |
| **CSRF 防護** | 🟢 優秀 | Double Submit Cookie + `secrets.compare_digest()` 恆定時間比對 |
| **XSS 防禦** | 🟢 優秀 | 全面 `textContent` + `escapeHtml()`；`innerHTML` 僅用於清空 |
| **密碼安全** | 🟢 優秀 | bcrypt rounds=12；複雜度驗證；禁止相似帳號名稱 |
| **計時攻擊防禦** | 🟢 優秀 | 忘記密碼流程無論帳號是否存在皆執行相同耗時操作 |
| **CSV 注入防禦** | 🟢 優秀 | 所有匯出均透過 `_sanitize_csv_dict()` 跳脫危險字元 |
| **CSP + nonce** | 🟢 優秀 | 每次請求動態生成 nonce 注入 script/style 標籤 |
| **Stack Trace 隱藏** | 🟢 優秀 | 全域 Exception Handler 統一回傳標準 500 |
| **Session 管理** | 🟢 優秀 | Token Hash 儲存；滑動視窗續期；StaleDataError 競態防禦 |
| **登入暴力破解防禦** | 🟢 優秀 | 連續失敗達閾值後鎖定帳號 |
| **Token 安全** | 🟢 優秀 | Session token / Reset token 均儲存 Hash，不儲存明文 |
| **路徑防禦** | 🟢 良好 | CLI 路徑使用 `realpath()` 比對安全目錄 |
| **機密保護** | 🟢 良好 | Proxy 密碼遮蔽；SMTP 密碼只讀環境變數 |

### 安全建議

1. **SQLite PRAGMA foreign_keys=ON 缺失**：見業務邏輯章節，在外鍵約束上存在潛在風險。

2. **缺乏全局 API 速率限制中介層 (Rate Limiting Middleware)**
   - 目前僅有登入鎖定和忘記密碼的個別限速保護，沒有全局 API Rate Limiting。
   - 建議在 Nginx/反向代理層補充速率限制，或引入輕量 in-memory Rate Limiter。

---

## 四、程式碼品質審查

### 優點

- **型別標註完整**：後端 Python 程式碼廣泛使用 Type Hints，有助維護性。
- **Docstring 品質高**：函式均有詳細的 Args/Returns/Raises 說明。
- **錯誤隔離良好**：各模組精確捕捉特定例外型別（`yaml.YAMLError`、`SQLAlchemyError` 等）。
- **SRP 原則落實**：[`notifier.py`](../backend/jobs/services/notifier.py)、[`exporter.py`](../backend/jobs/services/exporter.py)、[`reprobe.py`](../backend/jobs/services/reprobe.py) 各自獨立，職責清晰。
- **無廣域例外捕捉**：符合 §13 `broad-exception-caught` 禁止規範。
- **測試全數通過**：本次 session 確認 `pytest test/ -v` 全數 17 項測試 PASSED。

### 潛在改善點

1. **命名一致性問題（Todo #8）**：部分變數/API 名稱因歷史沿革未明確區分內部/外部連結，待規劃重構。
2. **Alembic 未整合（待評估）**：生產環境 Schema 演進的管理略顯不足。
3. **mypy 靜態型別錯誤仍有殘餘（Todo #6）**：`dict[str, object]` 協變性等問題待後續逐步修正。

---

## 五、結論

> [!IMPORTANT]
> **整體完成度極高**：requirements.md 中的絕大多數核心功能需求均已完整實作，資安防護機制設計嚴謹且多層次，特別是 SSRF、CSRF、計時攻擊等高風險防禦均達到優秀水準。

**特別值得肯定的高風險需求實作**：

- ✅ SSRF 防禦（Socket Monkey-patch 層級，確保無法繞過）
- ✅ CSRF Double Submit Cookie + 恆定時間比對（防計時攻擊）
- ✅ 忘記密碼計時攻擊 + 帳號列舉防禦
- ✅ Session StaleDataError 競態防禦（多視窗並發安全）
- ✅ CSV 注入防禦（所有匯出路徑均覆蓋）
- ✅ 串流匯出 OOM 防禦（Generator + yield_per 全面實作）

**主要待改善項目**：

| 項目 | 優先級 | 說明 |
|------|-------|------|
| 全局 API 速率限制 | 🟡 中 | 目前無全局 Rate Limiting Middleware，建議在反向代理層或應用層補充 |
| Alembic Schema 遷移工具 | 🟡 中 | 目前用 `create_all()`，生產環境增量遷移需手動執行 ALTER TABLE |
| mypy 靜態型別修復 | 🟢 低 | Todo #6，功能無影響但影響型別安全性 |
| 命名一致性重構 | 🟢 低 | Todo #8，提升程式碼可讀性 |
